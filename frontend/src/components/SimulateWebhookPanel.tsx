"use client";

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";

import type { Transfer, WebhookStatus } from "@/lib/types";

export interface SimulateOutcome {
  ok: boolean;
  eventId: string;
  detail: string;
  outcome?: string;
}

/**
 * Stand in for the provider, from the browser.
 *
 * The brief asks for a way to simulate a webhook from the UI *or* curl instructions in
 * the README. This app does both, and the UI version is here because the interesting
 * behaviour of this system is invisible from the outside: an idempotent handler and a
 * broken one look identical until you deliver the same event twice.
 *
 * So the panel keeps the last event id and offers to send it again. That single button
 * is brief scenario A — same `event_id` delivered twice — and the backend answers the
 * redelivery with "Event already applied; no change." while the transfer sits
 * unchanged. Sending a *fresh* completed event to a transfer that already completed is
 * scenario B/D, and comes back a 409 refusing to contradict a terminal state.
 *
 * The signing happens in the server action, never here: the HMAC needs
 * PROVIDER_WEBHOOK_SECRET, and shipping that to the browser would hand every visitor
 * the ability to forge a "completed" event — the exact thing the signature prevents.
 */
export function SimulateWebhookPanel({
  transfer,
  onSimulate,
}: {
  transfer: Transfer;
  onSimulate: (input: {
    reference: string;
    providerTransferId: string;
    status: string;
    eventId?: string;
  }) => Promise<SimulateOutcome>;
}) {
  const [pending, startTransition] = useTransition();
  // The id *and* the status it asserted. A redelivery must repeat the original claim:
  // the backend refuses a reused event_id carrying different content (409
  // WebhookEventMismatch), because an event id names one immutable fact. Keeping the
  // pair together is what makes "redeliver" mean redeliver.
  const [lastEvent, setLastEvent] = useState<{
    id: string;
    status: WebhookStatus;
  } | null>(null);
  const [result, setResult] = useState<SimulateOutcome | null>(null);
  const router = useRouter();

  const providerId = transfer.provider_transfer_id;

  if (!providerId) {
    return (
      <section className="card simulate" aria-labelledby="simulate-heading">
        <h2 id="simulate-heading">
          <span className="chip">Dev tool</span> Simulate a provider webhook
        </h2>
        <p className="muted">
          Nothing to simulate yet. The provider only learns about this transfer when it
          is submitted, and a webhook is matched on the{" "}
          <code>provider_transfer_id</code> assigned at that moment. Submit the transfer
          first.
        </p>
      </section>
    );
  }

  function fire(status: WebhookStatus, eventId?: string) {
    startTransition(async () => {
      const outcome = await onSimulate({
        reference: transfer.reference,
        providerTransferId: providerId!,
        status,
        eventId,
      });
      setResult(outcome);
      setLastEvent({ id: outcome.eventId, status });
      router.refresh();
    });
  }

  return (
    <section className="card simulate" aria-labelledby="simulate-heading">
      <h2 id="simulate-heading">Simulate a provider webhook</h2>
      <p className="muted">
        Posts a signed event to <code>/api/webhooks/provider/</code> for{" "}
        <code>{providerId}</code>, exactly as the provider would. In a real deployment
        the provider holds the signing key and this panel does not exist.
      </p>

      <div className="actions__buttons">
        <button
          type="button"
          className="button"
          disabled={pending}
          onClick={() => fire("completed")}
        >
          Send <strong>completed</strong>
        </button>
        <button
          type="button"
          className="button"
          disabled={pending}
          onClick={() => fire("failed")}
        >
          Send <strong>failed</strong>
        </button>
        <button
          type="button"
          className="button button--ghost"
          disabled={pending || !lastEvent}
          title={
            lastEvent
              ? "Deliver the same event_id a second time — it must change nothing"
              : "Send an event first, then you can redeliver it"
          }
          onClick={() => {
            if (!lastEvent) return;
            fire(lastEvent.status, lastEvent.id);
          }}
        >
          Redeliver last event
        </button>
      </div>

      <div aria-live="polite">
        {result && (
          <p
            className={`notice ${result.ok ? "notice--ok" : "notice--error"}`}
            role="status"
          >
            {result.detail}
            {result.outcome && (
              <span className="notice__hint"> Recorded outcome: {result.outcome}.</span>
            )}
            <span className="notice__hint">
              {" "}
              <code>event_id: {result.eventId}</code>
            </span>
          </p>
        )}
      </div>
    </section>
  );
}
