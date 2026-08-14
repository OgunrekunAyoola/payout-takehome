# PayOut

A mock cross-border payout service. Transfers move through an explicit state machine and are
settled asynchronously by signed provider webhooks.

- `backend/` — Django 6 + Django REST Framework, SQLite
- `frontend/` — Next.js 16 (App Router) + TypeScript

Everything the brief asks for is implemented: the state machine, idempotent create, ops
submit/cancel, the signed provider webhook with dedupe by `event_id`, scenarios A–E, and a
minimal UI that creates a transfer and watches its status change. **94 tests** — 57 backend,
37 frontend.

---

## 1. How to run

Two terminals. The frontend talks to the backend, so start the backend first.

### Backend (port 8000)

```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python manage.py migrate
.venv/bin/python manage.py runserver
```

No `.env` needed to run locally: `DEBUG` defaults on and the webhook secret falls back to a
development default. That fallback is refused at boot when `DEBUG` is off — see
[Known limitations](#8-known-limitations-and-risks).

### Frontend (port 3000)

```bash
cd frontend
npm install
npm run dev
```

Then open <http://localhost:3000>. No `.env.local` is needed either; `frontend/.env.example`
documents both variables if you want to point at a different backend.

### Or with Docker

```bash
docker compose up --build
```

Then open <http://localhost:3000>. This runs the backend in deployment shape — `DEBUG` off,
gunicorn, an explicit webhook secret (the boot-time guard refuses the dev fallback outside
`DEBUG`, so the compose file must provide one). The values in `docker-compose.yml` are
machine-local demo values; a real deployment injects its own. SQLite lives inside the backend
container, so `docker compose down` discards the demo ledger. Ports are overridable:
`BACKEND_PORT=18000 FRONTEND_PORT=13000 docker compose up`.

### Tests

```bash
cd backend  && .venv/bin/python manage.py test transfers   # 57 tests
cd frontend && npm test                                    # 37 tests
```

Also available in the frontend: `npm run typecheck`, `npm run build`.

### The 60-second demo

1. Open <http://localhost:3000> and create a transfer (e.g. `150.00`, `NGN`, `ACME-PAYROLL-014`).
   You land on its detail page, `pending`.
2. Press **Submit to provider** → `processing`, and a `provider_transfer_id` appears. Both
   action buttons are now disabled, each explaining why.
3. In **Simulate a provider webhook**, press **Send completed** → the page updates itself to
   `completed` without a reload.
4. Press **Redeliver last event** → *"Event already applied; no change."* and the transfer does
   not move. That is scenario A, in the UI.
5. Press **Send completed** again (a *new* event id this time) → refused, because `completed` is
   terminal. That is scenario D.

### Firing webhooks by hand

From the backend, signing with the same secret the server verifies against:

```bash
cd backend
.venv/bin/python manage.py fire_webhook prov_abc123 --status completed
.venv/bin/python manage.py fire_webhook prov_abc123 --status completed --event-id evt_repeat  # send twice for scenario A
```

Or with curl. The signature is HMAC-SHA256 over the **exact request body bytes**, hex-encoded,
prefixed `sha256=`:

```bash
SECRET='dev-webhook-secret-change-me'
BODY='{"event_id":"evt_123","provider_transfer_id":"prov_abc123","status":"completed","occurred_at":"2026-08-13T12:00:00Z"}'
SIG=$(printf '%s' "$BODY" | openssl dgst -sha256 -hmac "$SECRET" | awk '{print $NF}')

curl -i -X POST http://127.0.0.1:8000/api/webhooks/provider/ \
  -H 'Content-Type: application/json' \
  -H "X-Provider-Signature: sha256=$SIG" \
  -d "$BODY"
```

`printf '%s'` rather than `echo` on purpose: `echo` appends a newline, that newline is part of
the body, and the signature would then be computed over different bytes than curl sends.

---

## 2. Assumptions

**Auth is skipped**, as the brief permits. The transfer endpoints are open, and this is
declared explicitly in `settings.py` (`DEFAULT_PERMISSION_CLASSES: [AllowAny]`,
`DEFAULT_AUTHENTICATION_CLASSES: []`) rather than left to DRF's defaults, so it reads as a
decision instead of an accident. It does **not** extend to the webhook: that endpoint
authenticates its caller by HMAC signature, because there the caller is an untrusted external
party asserting that money moved.

**The provider is a mock.** `submit_to_provider` mints an id and returns; there is no network
call, no timeout, no retry.

**One currency per transfer, no FX.** `amount` and `currency` are recorded as given. No rates,
no conversion, no ledger.

**`occurred_at` is informational.** It is stored, but ordering decisions are made by the state
machine rather than by comparing provider timestamps — see the scenario B decision below.

**A redelivery repeats the original claim.** Same `event_id` means the same asserted fact. A
delivery reusing an id while asserting a *different* provider id or status is treated as a
contradiction, not a retry (409).

**Money is never a float.** `DecimalField` in the database, decimal strings over the wire,
formatted client-side without ever being parsed into a JS number.

**Timestamps are UTC everywhere**, including in the UI, which labels them as such.

---

## 3. What I built (architecture sketch)

```
Browser ──▶ Next.js server (server components + server actions) ──▶ Django REST API
                                                                          ▲
                        "provider" (fire_webhook / curl / UI simulator) ───┘
                                                             signed POST /api/webhooks/provider/
```

The browser never calls Django directly. Every read is a server component and every mutation is
a server action, which has three consequences worth naming: Django needs no CORS configuration,
the webhook secret can be used for the UI simulator without ever entering a client bundle, and
the API's base URL is not public.

### Backend

| File | Holds |
| --- | --- |
| `transfers/states.py` | `ALLOWED_TRANSITIONS` — the single declaration of what moves are legal |
| `transfers/models.py` | `Transfer`, `WebhookEvent`, and `transition_to()`, the only sanctioned way to change status |
| `transfers/services.py` | Orchestration: submit, cancel, and apply-one-webhook-event, each defined once |
| `transfers/views.py` | Create with `Idempotency-Key` semantics, list, retrieve, submit, cancel |
| `transfers/webhooks/` | Signature verification, the provider's payload contract, the endpoint |
| `transfers/api_errors.py` | One place where domain exceptions become HTTP responses |

Two rules hold the design together. **The transition table is declared once**, because the ops
endpoints and the webhook both move transfers and would otherwise develop separate opinions
about what is legal. **Every status change is a compare-and-swap** — the `UPDATE` only matches
while the stored status is still the one that was validated — so checking in Python and writing
unconditionally can't let two racing requests both pass the check. A cancel landing on top of a
submit would otherwise leave a cancelled transfer holding a live provider id, unrecoverable
because cancelled is terminal and no webhook could ever correct it.

`WebhookEvent` records **every** authenticated event with its verdict, rejections included. It
does double duty: `event_id` is unique and handling an event *begins* by inserting the row, so
the database makes dedupe atomic (check-then-insert has a race a duplicate-happy provider will
find). And the stored verdict is what lets redelivery be asymmetric — see below.

### Frontend

| File | Holds |
| --- | --- |
| `src/lib/api.ts` | The only place this app talks to Django. Returns results, never throws |
| `src/lib/transitions.ts` | The lifecycle mirrored client-side: legal actions, and custody zones |
| `src/lib/provider-signature.ts` | HMAC signing for the simulator. Server-only |
| `src/actions/transfers.ts` | Server actions: create, submit, cancel, simulate |
| `src/components/CustodyHeader.tsx` | Who holds the money, and the three-stage line |
| `src/components/TransferActions.tsx` | Submit/Cancel, disabled per state, 409-tolerant |
| `src/components/CreateTransferForm.tsx` | The create form and its idempotency key |
| `src/components/SimulateWebhookPanel.tsx` | Stand in for the provider, including redelivery |
| `src/components/StatusBadge.tsx` | One status, as custody shape plus outcome hue |
| `src/components/AutoRefresh.tsx` | Polls while anything can still change |
| `src/components/Elapsed.tsx` | How long we have been waiting. The only client-only render |

Screens: a list of transfers **grouped by custody** — *In flight* above *Settled* — with the
create form beside it, and a detail page leading with a custody header (amount, recipient,
status, three-stage line) above the provider id and timestamps, the two actions, and the
simulator.

Client components receive the server actions **as props** rather than importing them. That
keeps them pure functions of their inputs, which is what makes the brief's named frontend test
possible without standing up a server.

#### The UI is organised around custody, not status

Five statuses are a state machine, but an operator's question is smaller than that: *can I act,
or am I waiting on someone else?* Three answers — `ours` (pending), `theirs` (processing),
`settled` (the three terminals) — and `zoneFor()` derives them from the same transition table
rather than restating them, so they cannot drift. That one function drives the badge shape, the
list grouping and the detail hierarchy, which is the difference between reading five colours and
reading one fact.

It also decides the two rules the palette follows: the accent is spent only on interactive
intent and never on status, so a coloured thing is never ambiguous between a button and a state;
and red appears in exactly two places, a failed transfer and a genuine system failure.

#### A refusal is not a failure

Three outcomes, three tones, because they need opposite responses from the operator. A transfer
that **moved** underneath the page (a webhook landed between render and click) was refused, not
lost, and nothing was sent. A move that is **refused** outright will refuse forever, so retrying
is pointless. Only a genuine **failure** earns red, because it is the only case where the
transfer's real state is unknown to us.

Both kinds of 409 carry `current_status`, so its presence cannot tell them apart. What separates
them is whether the status differs from the one the page rendered from — which the component
already knows. Every message also states what was **not** done, which is the sentence an
operator moving money actually needs.

#### Waiting, without lying about it

A transfer in `processing` has no ETA and never will: the webhook arrives when it arrives. So
the waiting screen shows three things that are all true *now* and predict nothing — stage (three
segments, the third drawn dashed and labelled `unknown — no ETA exists`), elapsed time counting
up, and a heartbeat whose period **is** the poll interval. When polling stops the motion stops,
and that stillness is also true. A progress bar there would be a claim we have no basis for.

Status stays live by polling — `router.refresh()` every 3s while anything on the page can still
move, paused on a hidden tab, stopped dead at a terminal status. SSE or a WebSocket would push
the change instead of asking for it, but both need the backend to hold and notify connections,
and the brief puts that infrastructure out of scope.

Timestamps are formatted with a pinned locale and `timeZone: "UTC"` so a server render and a
browser hydration produce identical strings. The elapsed counter cannot satisfy that — it is
derived from the current clock — so it is the one mount-gated client component, rendering
nothing until `useEffect` fires.

### API

| Method | Path | Behaviour |
| --- | --- | --- |
| `POST` | `/api/transfers/` | Create, `pending`. Requires `Idempotency-Key`. Same key + same body → **200** with the original; same key + different body → **409** |
| `GET` | `/api/transfers/` | List, newest first, paginated (`{count, next, previous, results}`) |
| `GET` | `/api/transfers/{reference}/` | Retrieve |
| `POST` | `/api/transfers/{reference}/submit/` | `pending` → `processing`, assigns `provider_transfer_id` |
| `POST` | `/api/transfers/{reference}/cancel/` | `pending` → `cancelled`; otherwise **409** |
| `POST` | `/api/webhooks/provider/` | Signed provider event |

Transfers are addressed by public reference (`TRF-` + 16 hex), never by primary key.

Idempotency is judged on the **validated** payload, not the raw bytes: key order, whitespace
and JSON scalar spelling (`"150.00"` vs `150.00` vs `150`) don't matter. A retry that means the
same thing must replay, because telling a semantically identical retry to "use a new key" is an
instruction to pay out twice. A malformed payload does **not** consume the key — the client's
next move is to fix the body and retry with the same key, and that retry must be allowed to
create.

Every refused state change — submit, cancel, webhook — answers with one envelope:
`{detail, current_status, attempted_status}`. One vocabulary for clients to parse.

### Scenarios A–E

| # | Situation | Response | Why |
| --- | --- | --- | --- |
| **A** | Same `event_id` twice | **200**, `"Event already applied; no change."` | The transport duplicated one fact. Its effects already happened; the answer is success with no second application |
| **B** | `completed`, then `failed` for the same transfer | **409** | See the decision log |
| **C** | Webhook for a transfer still `pending` | **409** if it has a provider id (`pending → completed` has no edge); **404** if it was never submitted, since there is nothing to match on | The event is stored either way and a redelivery is re-judged against fresh state |
| **D** | Two *different* `event_id`s, both `completed`, same transfer | First **200**, second **409** | Dedupe stays silent — the second event is genuinely new. The transition table refuses it, because `completed` is terminal |
| **E** | Cancel after submit (`processing`) | **409** | Once the provider holds it we cannot unilaterally withdraw it |

Named tests for each: `test_scenario_a_same_event_id_delivered_twice_is_a_noop_200`,
`test_scenario_b_failed_after_completed_is_rejected_409`,
`test_scenario_c_webhook_for_still_pending_transfer_is_rejected_409`,
`test_scenario_c_webhook_for_never_submitted_transfer_is_404`,
`test_scenario_d_two_events_both_completed_second_is_rejected_409` (all in
`backend/transfers/tests/test_webhook_scenarios.py`), and
`test_scenario_e_cancel_after_submit_is_rejected_409` for E in `test_submit_cancel.py`.

**Redelivery is asymmetric, and the asymmetry is the point.** A duplicate of an *applied* event
is a no-op. A duplicate of a *rejected* one is judged again against current state — a rejection
can be a function of timing, and an event that arrived before our submit committed was rightly
refused then and would be wrongly refused forever. Replaying that rejection would strand the
transfer in `processing` until a human noticed.
(`test_rejected_event_is_re_evaluated_on_redelivery`)

---

## 4. Decision log

### Why 409 for scenario B (`completed`, then `failed`)?

Because by the time the second event arrives, the first one is not just a status — it is
something we may already have told the customer. `completed` is terminal in this design, so
`completed → failed` has no edge, and the second event is refused with a 409 that names both
statuses.

The alternative is last-write-wins, and it is worse for a reason that has nothing to do with
elegance: it makes the *final* state of a payout depend on network delivery order between two
events the provider may have emitted seconds apart. A retried `completed` overtaking a `failed`
would silently produce the opposite outcome, and neither we nor the provider could tell from the
data which one won. Refusing gives up the ability to self-correct in exchange for a state that
cannot be rewritten by a late packet, which is the right trade when the state is "we told
someone their money arrived."

I also chose not to arbitrate on `occurred_at`. It looks like the principled fix — apply
whichever event happened later — but it puts a money decision in the hands of a remote clock we
don't control and can't audit, and it silently accepts contradiction as normal traffic.

What makes 409 defensible rather than merely strict is that **nothing is thrown away**. The
contradiction is stored as a `WebhookEvent` with `outcome=rejected_illegal_transition` and a
foreign key to the transfer. If a provider genuinely does complete then fail a payout, that is a
reconciliation problem for a human with the full evidence in front of them — not something to
resolve by overwriting a column. In production this rejection is exactly what I'd alert on: it
means our record and theirs disagree, which is worth a page.

### For an unknown `provider_transfer_id`, why 4xx rather than a soft success?

**404, and the event is stored anyway.**

The decisive fact is that the signature has already been verified. This isn't an anonymous
probe; it is a caller holding our shared secret, asserting that money moved on a transfer we
have no record of. There are only bad explanations — they're pointed at the wrong environment,
our submit wrote an id we then lost, or they succeeded where we recorded failure — and every one
of them is a real integration defect that a human needs to see.

A soft 200 hides all of it twice over. It tells the provider "handled", which ends their
retries, so if the mismatch was ours and transient we've destroyed the delivery that would have
fixed it. And a monitoring signal that reads "all webhooks 200" while payouts silently go
unmatched is worse than no signal at all. The usual argument for soft-success — don't let a bad
event stick in a retry loop forever — is really an argument against *5xx*, and I get its benefit
by making this a **404**: a well-behaved provider treats 4xx as permanent and stops, so nothing
loops, and the failure is loud instead of silent.

The part that makes this safe is that the 404 is not a discard. The event row is written with
`outcome=rejected_unknown_transfer` *before* the exception is raised, so it becomes a dead
letter an investigation can start from — with the full payload as received. Returning an error
and keeping the evidence are not in tension; choosing one over the other is the actual mistake.

### Where does webhook signature verification belong in a real Django codebase, and what do people get wrong?

Not in the view, once there is more than one webhook. It belongs in a boundary the endpoint
cannot forget: a small authentication class or a decorator applied by the URL layer, so a new
webhook endpoint is signed by default rather than by remembering. In DRF I'd make it an
`Authentication` class returning the provider as the authenticated principal — that puts it in
the same place a reader already looks to answer "who is allowed to call this?", and it composes
with permissions. In this codebase, with exactly one webhook, verification is the first thing in
`ProviderWebhookView.post`, and the ordering is documented and tested
(`test_signature_check_runs_before_transfer_lookup`) rather than left to be inferred from where
the lines happen to sit.

What people get wrong, in the order it bites:

**Signing the wrong bytes.** By far the most common. Verification runs against
`request.data` — parsed, then re-serialised — instead of `request.body`. Because the provider
signed whatever *their* serialiser emitted (their key order, their whitespace, their unicode
escaping), you are now hashing bytes they never sent. This is nastier than it sounds: it works
in tests, because the tests build the payload with the same JSON encoder as the code, and it
fails in production against every provider whose JSON spelling differs from yours. **This
codebase had exactly this bug** — see the next section.

**Comparing digests with `==`.** Leaks timing information. `hmac.compare_digest` exists for
this. Related and less discussed: `compare_digest` raises `TypeError` on non-ASCII input, so a
junk header turns a 401 into a 500 — and providers retry 5xx forever. Decode and validate the
digest first, then compare.

**Reading the body after something else has consumed the stream.** Django's `request.body`
raises once the stream is read, so middleware, an upstream parser, or DRF's own lazy parsing can
make the raw bytes unavailable at exactly the moment you need them. Read them first.

**Letting the endpoint become an oracle.** Returning 404 for an unknown id *before* checking the
signature turns the endpoint into a lookup service for which provider ids exist. Authenticate
first, then look things up. For the same reason every signature failure here — missing header,
malformed digest, wrong secret — returns one identical 401 body; telling a prober *which* check
failed is free information.

**Treating "signed" as "trustworthy".** A valid signature proves who sent it, not that what it
says is legal. This handler still routes every event through the same transition table as
everything else, which is why scenario B is refused even though the signature was perfect.

And the operational one: **a shared secret with no rotation path.** Verification should accept
any of a set of active keys so a rotation isn't a flag-day outage. Out of scope here, and noted
below.

---

## 5. The subtle bug I almost shipped

**The webhook signature was computed over a re-canonicalised payload instead of the raw request
body.** Fixed in commit [`d1cae88`](../../commit/d1cae88) on `feat/provider-webhook`.

The handler parsed the JSON, re-serialised it with sorted keys and compact separators, and
HMAC'd *that*. Which is a completely reasonable-looking thing to write, and it passed every test
I had, because my tests built their request bodies with the same `json.dumps(..., sort_keys=True,
separators=(",", ":"))` recipe the verifier used. Both sides agreed, so both sides were green.

A real provider signs the bytes *their* serialiser produced — probably `", "` separators,
probably insertion-ordered keys, possibly pretty-printed. Every one of those signatures would
have failed verification. Not intermittently: **permanently, for every event from every
provider**, presenting as a flood of 401s that looks exactly like a misconfigured secret. And
the failure mode is the worst-shaped one available — transfers stuck in `processing` forever,
with the money already moved on the provider's side and no webhook we'd accept to tell us.

What makes it a *good* bug to have found is that no amount of round-trip testing exposes it. The
bug lives precisely in the assumption shared by the code and its tests: that our JSON spelling is
the only one. It took writing down what the signature is supposed to *mean* — a claim about the
bytes on the wire, not about their parsed meaning — to see it.

The test that catches it, and would have caught it earlier:

`backend/transfers/tests/test_webhook_signature.py::test_signature_binds_to_the_bytes_sent_not_to_our_canonical_form`

It signs a **pretty-printed, unsorted** body (`json.dumps(payload, indent=2)`) and asserts a
200. Against the old code that is a 401; against the fix it passes. The point of the test is that
it deliberately refuses to spell JSON the way the implementation does.

Two smaller ones fell out of the same review, both in the same area: a non-hex or non-ASCII
signature header crashed `hmac.compare_digest` into a 500 (which a provider then retries
forever) instead of the documented uniform 401 — also `d1cae88`,
`test_malformed_signature_header_returns_401`; and `PROVIDER_WEBHOOK_SECRET` fell back to a
repo-published default with no fail-fast outside `DEBUG`, so a deploy that forgot to set it
would fail in the quietest possible way — by working (`ddb19e9`).

The frontend produced one of its own, and the test found it before I did: React resets a form
automatically once its action completes — *including when the action failed* — so with
uncontrolled inputs a rejected create silently wiped everything the user had typed. The test
`reuses the same idempotency key when a failed create is retried` failed on its second submit,
which is how it surfaced. The inputs are controlled now.

Two more worth naming, because they are the same *shape* of mistake as the signature bug — code
that agreed with itself and was wrong anyway:

**Both kinds of 409 read as failure.** The UI rendered every refusal in the error tone, so a
transfer settled by a webhook a moment before the click — the system working exactly as designed,
with nothing sent — told the operator in red that something had broken. The fix needed a rule to
separate "the world moved" from "this move does not exist", and the obvious rule is wrong: both
errors carry `current_status`, so testing for its presence collapses the two cases. The rule that
works compares it against the status the page rendered from. Tests:
`styles a moved transfer as a refusal, not a failure` and
`styles an impossible move as permanently refused rather than as movement`.

**A pending transfer claimed its settlement was unknowable.** The waiting screen draws its third
stage dashed and labelled `unknown — no ETA exists`, which is honest for a transfer the provider
holds. The same treatment was reaching transfers that had never been submitted, where nothing was
unknowable because nothing had been sent. Unit tests passed; driving the real lifecycle in a
browser is what exposed it, which is the argument for doing that at all. Now locked by
`does not treat an unsent transfer's settlement as unknowable`.

---

## 6. What I deliberately left out

- **Auth on the transfer endpoints**, as the brief permits. The webhook is authenticated.
- **Celery / Redis / background workers.** Nothing here needs to outlive a request.
- **Real KYC, wallets, FX, ledgers.** Out of scope per the brief.
- **An admin dashboard.** `WebhookEvent` is designed to be read during an investigation, but no
  UI reads it yet — the API and shell are enough at this size.
- **Pagination controls in the UI.** The API paginates (50/page) and the list says so when there
  is a second page. Building page controls would have added UI without exercising anything the
  brief is testing.
- **An OpenAPI schema and generated client.** `frontend/src/lib/types.ts` is hand-written, and
  is honest about being a claim about the server rather than proof.
- **A real provider integration** — no HTTP, no timeouts, no retries.
- **Structured logging, metrics, tracing.** The 409/404 paths log where a human would need them;
  there is no metrics pipeline.
- **Docker orchestration beyond local compose.** The Dockerfiles and compose file run both
  halves in deployment shape, but there is no registry push, no healthcheck/restart policy
  tuning, and SQLite stays inside the container — the compose file is a local demo, not a
  production topology.

---

## 7. What I'd do differently with more time

**Make the provider call idempotent on our reference.** The real remaining hole is in
`submit_transfer`: the transition table is consulted, the provider is called, then the
compare-and-swap writes. A concurrent cancel can win the race after the provider was
called, and the CAS then refuses our write — with a mock provider that costs nothing, with a
real one it is an orphaned payout instruction. The fix isn't a bigger lock, it's an idempotent
provider API keyed on our transfer reference, so every retry names the same payout and nothing
can orphan.

**Key rotation for the webhook secret.** Verify against a set of active keys so rotation isn't a
flag-day outage.

**Replay-window protection.** The signature proves authenticity but not freshness. A captured
event can be replayed forever. `event_id` dedupe blunts it, but a timestamped signature with a
tolerance window is the real answer.

**Property-based tests over the transition table.** The states are few enough to enumerate
exhaustively — generate every `(status, event)` pair and assert that only table-sanctioned moves
change the row. Hand-written scenarios cover the cases I thought of.

**A concurrency test with real threads.** The CAS and the APPLIED-verdict guard are both
reasoned about in comments and tested by simulating the interleaving. I'd rather prove them
under genuine contention against Postgres, where `select_for_update` also becomes an option.

**Expose the settling event on the transfer endpoint.** The detail page records *when* a transfer
settled and that the record is immutable, but not *which* event did it — the `event_id` lives in
`WebhookEvent` and the transfer serializer does not return it. Surfacing it would let the UI name
the event that moved the money, which is the honest close of the audit loop: the screen and the
audit trail would then agree, in public, on one identifier. I left it out rather than have the UI
imply an id it cannot see.

**A webhook/event view in the UI**, reading the audit trail the backend already keeps — the
rejected events are the interesting ones and nothing surfaces them yet.

**An end-to-end test** (Playwright) over the demo path. The flow is verified manually and each
layer is unit-tested; nothing yet asserts the whole chain in a browser.

---

## 8. Known limitations and risks

- **SQLite, single process.** Chosen so `manage.py test` works after nothing but
  `pip install -r requirements.txt` — a suite that needs a database server running is a suite
  some reviewer won't run. The concurrency design doesn't depend on it: every status change is a
  conditional `UPDATE`, which is correct on SQLite (where `select_for_update` is a no-op) and on
  Postgres. Under real write concurrency SQLite will serialise and eventually return "database is
  locked".
- **The webhook secret's development default is published in this repository.** It is refused at
  boot when `DEBUG` is off (`ImproperlyConfigured`), because that secret is the only thing between
  the internet and a forged `completed` event.
- **`DEBUG` defaults to on** for zero-setup local running. A deployment must set
  `DJANGO_DEBUG=false`, `DJANGO_SECRET_KEY` and `PROVIDER_WEBHOOK_SECRET`.
- **No rate limiting** anywhere, including on the webhook.
- **Polling, not push.** Status updates lag by up to ~3 seconds, and every open tab costs a
  request. Fine at this scale, not a pattern to carry into production.
- **The frontend duplicates the transition table.** Deliberate, documented in
  `src/lib/transitions.ts`, and structurally advisory: the UI treats a 409 as a normal outcome at
  any moment, so a stale mirror degrades to a refused click rather than a wrong write. It is still
  a second copy that a backend change could leave stale.
- **The UI's simulator signs with the server's own secret.** It is a demo affordance. In a real
  deployment the provider holds that key and this panel wouldn't exist.
- **No audit of who acted.** Submit and cancel are unauthenticated, so nothing records which
  operator moved a transfer — the first thing I'd add along with auth.

---

## 9. Commit history

Built in small commits on stacked feature branches, one branch per slice of behaviour, each
carrying its code and the tests for the edge cases it introduces:

1. `feat/transfer-state-machine` — the domain model and the transition table
2. `feat/create-transfer-idempotency` — create with `Idempotency-Key` semantics
3. `feat/submit-and-cancel` — the ops actions and one conflict vocabulary (scenario E)
4. `feat/provider-webhook` — signature, dedupe, scenarios A–D, and the review fixes above
5. `feat/frontend` — the Next.js UI and its tests, then a UI/UX pass in three further
   commits: the accessibility and refusal-vs-failure fixes, then tokens and type, then the
   custody structure and the waiting screen

Commit messages carry the reasoning, not a restatement of the diff — the *why* for the
non-obvious calls lives there and in the code comments, so a reviewer meets the argument next to
the thing it justifies. The five `fix(...)` commits on `feat/provider-webhook` are a genuine
review pass over my own work, kept as separate commits rather than squashed away, because the
bugs and their fixes are more informative than a clean history would have been.

All five branches were merged with merge commits, never squashed, so that history survives on
`main`. CI (`.github/workflows/ci.yml`) runs both suites plus a production build on every push
and PR — the same commands this README gives a human, on the same versions, so "CI is green"
and "it runs on a reviewer's machine" are one claim, not two.

## 10. Time spent

About **11 focused hours over two days** (12–13 Aug), measured from the commit record rather
than estimated: commit timestamps span 11:14–17:51 on the first day (backend: state machine
through webhook, plus a review pass over my own branches) and 12:05–16:41 on the second
(frontend, a UI/UX pass, README). The brief's 8–12 hour expectation held without squeezing —
mostly because the out-of-scope list was taken at its word.
