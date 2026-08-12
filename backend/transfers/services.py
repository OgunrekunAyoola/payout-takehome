"""Operations that move transfers, shared by every caller.

Views own request/response shape; this module owns orchestration — what happens around a
state change, and in what order. "How to submit a transfer" and "how to apply a provider
event" each exist exactly once here, so the ordering that matters cannot drift between
callers.
"""

from django.db import IntegrityError, transaction
from rest_framework.exceptions import NotFound

from .exceptions import IllegalTransition, TransferConflict
from .models import Transfer, WebhookEvent, WebhookEventOutcome
from .provider import submit_to_provider
from .states import TransferStatus, can_transition


def submit_transfer(transfer: Transfer) -> Transfer:
    """Submit a pending transfer to the provider: ``pending`` → ``processing``.

    The ordering is the point:

    1. **Ask the transition table first.** The provider must not learn about a transfer
       whose move would be refused — call-then-check turns a double-clicked submit into a
       second real payout instruction that the 409 then throws away, unreconcilable
       because no row anywhere holds its id. This consults the same single table the
       write enforces; it is not a second copy of the rules.
    2. Then the provider call.
    3. Then the compare-and-swap write, which attaches the provider id in the same UPDATE
       that moves the status — no moment where a transfer is ``processing`` with nothing
       for a webhook to match on.

    A window remains between 1 and 3: a concurrent cancel can win the race after the
    provider was called, and the CAS then refuses our write. With the mock provider that
    costs nothing; with a real one it is still an orphaned instruction. The genuine fix
    is an idempotent provider API keyed on our reference (every retry names the same
    payout, so nothing orphans) — noted in the README, out of scope for the mock.
    """
    if not can_transition(transfer.status, TransferStatus.PROCESSING):
        raise IllegalTransition(transfer.status, TransferStatus.PROCESSING)
    provider_id = submit_to_provider(transfer)
    transfer.transition_to(
        TransferStatus.PROCESSING, provider_transfer_id=provider_id
    )
    return transfer


def cancel_transfer(transfer: Transfer) -> Transfer:
    """Cancel a transfer that has not been submitted: ``pending`` → ``cancelled``.

    Only possible before submission — once the provider has it we cannot unilaterally
    withdraw it (brief scenario E). No pre-check needed: nothing external is contacted,
    so the transition table's own refusal is the whole story.
    """
    transfer.transition_to(TransferStatus.CANCELLED)
    return transfer


def apply_webhook_event(
    *, event_id: str, provider_transfer_id: str, target_status: str, occurred_at, payload
):
    """Apply one provider event to its transfer, at most once.

    Returns ``(event, redelivered)``. Raises — *after* recording the verdict on the
    stored event — ``NotFound`` for an unmatchable provider id, or the ``TransferConflict``
    the state machine produced. The caller's exception handler turns those into 404/409;
    the record survives either way, because rejections are exactly what someone
    reconciling a discrepancy needs to see (a contradiction after a terminal state, an
    orphan event, an arrival before our submit committed).

    Dedupe is insert-first: handling *begins* by inserting the event row, and the unique
    constraint on ``event_id`` refusing the insert is what "we have seen this" means.
    Check-then-insert would let two concurrent deliveries of one event both pass the
    check and both apply — the double-apply the constraint exists to prevent.

    Redelivery is asymmetric, and the asymmetry matters:

    - Duplicate of an **applied** event → no-op. Its side effects already happened;
      doing anything would double-apply (brief scenario A).
    - Duplicate of a **rejected** (or crash-stranded ``received``) event → judged again
      against *current* state. A rejection can be a function of timing — an event that
      arrived before our submit committed was rightly refused then, and wrongly refused
      forever: the provider's retry must be allowed to land, or the transfer sits in
      ``processing`` until a human notices.

    A residual race is accepted and documented rather than hidden: two concurrent
    deliveries of one event where the second fetches the row while the first is still
    judging can leave the *outcome label* momentarily contested — but never the money:
    the transfer write is a compare-and-swap, so the state applies exactly once
    regardless of what the label says for that instant.
    """
    try:
        # atomic() so a refused INSERT rolls back cleanly; the connection stays usable.
        with transaction.atomic():
            event = WebhookEvent.objects.create(
                event_id=event_id,
                provider_transfer_id=provider_transfer_id,
                payload=payload,
                occurred_at=occurred_at,
            )
    except IntegrityError:
        event = WebhookEvent.objects.order_by().get(event_id=event_id)
        if event.outcome == WebhookEventOutcome.APPLIED:
            return event, True
        return _judge_event(event, target_status), True

    return _judge_event(event, target_status), False


def _judge_event(event: WebhookEvent, target_status: str) -> WebhookEvent:
    """Match the event to a transfer and apply the transition, recording the verdict."""
    transfer = (
        Transfer.objects.order_by()
        .filter(provider_transfer_id=event.provider_transfer_id)
        .first()
    )
    if transfer is None:
        # The signature already proved this is our provider, so an unmatchable id is
        # never probing — it is a real integration mismatch (wrong environment, a lost
        # write, their success/our failure). 404 makes it loud; the stored event is the
        # dead letter an investigation starts from.
        _record(event, WebhookEventOutcome.REJECTED_UNKNOWN_TRANSFER, transfer=None)
        raise NotFound(
            f"No transfer with provider_transfer_id '{event.provider_transfer_id}'."
        )

    try:
        transfer.transition_to(target_status)
    except TransferConflict:
        # Covers both the flat refusal (completed → failed: a contradiction after a
        # terminal state, brief scenario B) and losing a race. Either way the event is
        # kept with its verdict, and a redelivery will be judged against fresh state.
        _record(event, WebhookEventOutcome.REJECTED_ILLEGAL_TRANSITION, transfer=transfer)
        raise

    _record(event, WebhookEventOutcome.APPLIED, transfer=transfer)
    return event


def _record(event: WebhookEvent, outcome: str, *, transfer) -> None:
    event.outcome = outcome
    event.transfer = transfer
    event.save(update_fields=["outcome", "transfer", "updated_at"])
