"use client";

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";

import {
  canCancel,
  canSubmit,
  cancelBlockedReason,
  submitBlockedReason,
} from "@/lib/transitions";
import type { ApiError, Transfer } from "@/lib/types";

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
        <button
          type="button"
          className="button button--primary"
          disabled={!submitAllowed || pending}
          aria-disabled={!submitAllowed || pending}
          title={submitReason ?? "Submit this transfer to the provider"}
          onClick={() => run("submit", onSubmit)}
        >
          {running === "submit" ? "Submitting…" : "Submit to provider"}
        </button>

        <button
          type="button"
          className="button button--danger"
          disabled={!cancelAllowed || pending}
          aria-disabled={!cancelAllowed || pending}
          title={cancelReason ?? "Cancel this transfer"}
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

      {/* aria-live so the refusal is announced, not just drawn. */}
      <div aria-live="polite">
        {error && (
          <p className="notice notice--error" role="alert">
            {error.message}
            {error.kind === "conflict" && error.currentStatus && (
              <>
                {" "}
                <span className="notice__hint">
                  The transfer is now <strong>{error.currentStatus}</strong>; this
                  page has been refreshed to match.
                </span>
              </>
            )}
          </p>
        )}
      </div>
    </section>
  );
}
