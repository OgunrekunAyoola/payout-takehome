"use client";

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";

import {
  canCancel,
  canSubmit,
  cancelBlockedReason,
  submitBlockedReason,
} from "@/lib/transitions";
import type { ApiError, Transfer, TransferStatus } from "@/lib/types";

/**
 * Three outcomes, three tones — the distinction the UI previously collapsed.
 *
 * Both kinds of 409 arrive with `current_status`, so its mere presence cannot tell them
 * apart. What separates them is whether the transfer is still where this page thought
 * it was:
 *
 * - **moved** — the status changed underneath us, almost always because a provider
 *   webhook landed between render and click. The action was refused, not lost, and
 *   nothing was sent. Retrying against the new state may well be valid.
 * - **refused** — the transfer is exactly where we thought, and the move simply does
 *   not exist from here. Retrying is pointless, forever.
 * - **error** — a genuine failure. We do not know what the transfer's real state is,
 *   which is the one case that earns red.
 */
type NoticeTone = "moved" | "refused" | "error";

function toneFor(error: ApiError, renderedStatus: TransferStatus): NoticeTone {
  if (error.kind !== "conflict") return "error";
  if (error.currentStatus && error.currentStatus !== renderedStatus) return "moved";
  return "refused";
}

const HEADLINES: Record<NoticeTone, string> = {
  moved: "Nothing was sent — the transfer moved first.",
  refused: "This move does not exist.",
  error: "The action could not be completed.",
};

/**
 * What was *not* done — the clause an operator moving money actually needs, and the
 * one missing from every message before this. "Nothing was sent" and "nothing was
 * confirmed either way" are different facts and must not be phrased alike.
 */
const CONSEQUENCES: Record<NoticeTone, string> = {
  moved: "Nothing was sent to the provider. This page has been re-read and now shows the current state.",
  refused: "Nothing was sent to the provider. Retrying will refuse again.",
  error: "The transfer's real state is unknown from here — nothing was confirmed either way.",
};

/**
 * Submit and Cancel for one transfer.
 *
 * The two mutations arrive as props rather than being imported. That keeps this
 * component a pure function of its inputs — it can be rendered in a test with plain
 * stubs, which is what makes the "illegal actions are disabled" behaviour testable
 * without standing up a server. The real server actions are handed in by the detail
 * page.
 *
 * Two rules govern the whole component:
 *
 * 1. **Disable what the server would refuse.** `canSubmit`/`canCancel` come from the
 *    mirrored transition table, and every disabled button says *why* — an inert
 *    control with no explanation is indistinguishable from a broken page.
 * 2. **Never trust rule 1.** The state this component was rendered from is a snapshot,
 *    and a provider webhook can settle the transfer between render and click. So a
 *    refusal is an expected outcome, not an exception: a 409 is caught, its message
 *    shown, and the route refreshed so the buttons re-render against the status the
 *    transfer actually holds now.
 */
export function TransferActions({
  transfer,
  onSubmit,
  onCancel,
}: {
  transfer: Transfer;
  onSubmit: (reference: string) => Promise<{ ok: boolean; error?: ApiError }>;
  onCancel: (reference: string) => Promise<{ ok: boolean; error?: ApiError }>;
}) {
  const [pending, startTransition] = useTransition();
  // Which action is in flight, not merely that one is. Both buttons must lock while
  // either request is running, but only the button that was actually clicked should
  // claim to be working — labelling both "Working…" tells the user the app is doing
  // something it is not.
  const [running, setRunning] = useState<"submit" | "cancel" | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const router = useRouter();

  const submitReason = submitBlockedReason(transfer.status);
  const cancelReason = cancelBlockedReason(transfer.status);
  const submitAllowed = canSubmit(transfer.status);
  const cancelAllowed = canCancel(transfer.status);

  function run(
    which: "submit" | "cancel",
    action: (reference: string) => Promise<{ ok: boolean; error?: ApiError }>,
  ) {
    setError(null);
    setRunning(which);
    startTransition(async () => {
      try {
        const result = await action(transfer.reference);
        if (!result.ok && result.error) {
          setError(result.error);
        }
      } finally {
        setRunning(null);
        // Re-read either way. On success the status changed; on a refusal the
        // transfer moved under us, and the buttons must stop offering an action that
        // is now impossible.
        router.refresh();
      }
    });
  }

  return (
    <section className="actions" aria-labelledby="actions-heading">
      <h2 id="actions-heading">Actions</h2>

      <div className="actions__buttons">
        {/* No `aria-disabled` beside `disabled` — it is redundant on a genuinely
            disabled control. And no `title`: it is invisible on touch and to most
            screen readers, and the reason is stated in the page below, at full
            contrast, unconditionally. */}
        {/* `--working` on the clicked button only. Both buttons lock while either
            request is in flight, but "in flight" and "unavailable" mean opposite things
            and must not be drawn alike. */}
        <button
          type="button"
          className={`button button--primary${
            running === "submit" ? " button--working" : ""
          }`}
          disabled={!submitAllowed || pending}
          onClick={() => run("submit", onSubmit)}
        >
          {running === "submit" ? "Submitting…" : "Submit to provider"}
        </button>

        <button
          type="button"
          className={`button button--danger${
            running === "cancel" ? " button--working" : ""
          }`}
          disabled={!cancelAllowed || pending}
          onClick={() => run("cancel", onCancel)}
        >
          {running === "cancel" ? "Cancelling…" : "Cancel transfer"}
        </button>
      </div>

      {/* Why a button is unavailable, in the page rather than hidden in a tooltip —
          a `title` attribute is invisible on touch and to most screen readers. */}
      {(submitReason || cancelReason) && (
        <ul className="actions__reasons">
          {submitReason && (
            <li>
              <strong>Submit unavailable.</strong> {submitReason}
            </li>
          )}
          {cancelReason && (
            <li>
              <strong>Cancel unavailable.</strong> {cancelReason}
            </li>
          )}
        </ul>
      )}

      {/* aria-live so the refusal is announced, not just drawn. `role="status"` for the
          two refusals — they are correct outcomes, and an assertive alert would be
          overstating them. `role="alert"` only for a genuine failure. */}
      <div aria-live="polite">
        {error &&
          (() => {
            const tone = toneFor(error, transfer.status);
            return (
              <p
                className={`notice notice--${tone}`}
                role={tone === "error" ? "alert" : "status"}
              >
                <strong className="notice__headline">{HEADLINES[tone]}</strong>
                {/* The server's own sentence, verbatim — it names the exact move it
                    refused, which is more precise than anything restated here. */}
                {error.message}{" "}
                <span className="notice__hint">{CONSEQUENCES[tone]}</span>
                {tone === "moved" && error.currentStatus && (
                  <span className="notice__hint">
                    {" "}
                    It is now <strong>{error.currentStatus}</strong>.
                  </span>
                )}
              </p>
            );
          })()}
      </div>
    </section>
  );
}
