import { Elapsed } from "./Elapsed";
import { StatusBadge } from "./StatusBadge";
import { formatAmount, formatTimestamp } from "@/lib/format";
import { custodyLine, zoneFor } from "@/lib/transitions";
import type { Transfer } from "@/lib/types";

/**
 * The top of the detail page: who holds this money, and what that means.
 *
 * A server component — every value here is derived from the transfer the page was
 * already given, so there is no new fetch and nothing becomes interactive. The one
 * exception is the elapsed counter, which is clock-derived and therefore client-only.
 *
 * The three-segment line answers "what does waiting look like when there is nothing to
 * report?" with stage rather than percentage. The third segment is drawn dashed and
 * labelled `unknown — no ETA exists` while a transfer is with the provider: a design
 * element whose whole job is to refuse to lie about a future we cannot see.
 *
 * The parent renders this with `key={transfer.status}`, so a status change remounts it
 * and the one-shot resolution animation fires from CSS alone — no state, and it cannot
 * fire on a poll that changed nothing.
 */
export function CustodyHeader({ transfer }: { transfer: Transfer }) {
  const zone = zoneFor(transfer.status);
  const withProvider = transfer.provider_transfer_id !== null;

  return (
    <section className={`card custody custody--${zone}`}>
      {/* The heartbeat: only while the provider owes us an answer. Its period is the
          poll interval, so it reports that this page is still watching — the actual
          anxiety of the waiting screen. When polling stops, this stops. */}
      {zone === "theirs" && <div className="custody__pulse" aria-hidden="true" />}

      <div className="custody__top">
        <div>
          <p className="custody__amount numeric">
            {formatAmount(transfer.amount, transfer.currency)}
          </p>
          <p className="custody__to">to {transfer.recipient_ref}</p>
        </div>

        {/* The status is the one thing here that changes with no user action, so it is
            the one thing that has to announce itself. */}
        <div aria-live="polite" className="status-region">
          <StatusBadge status={transfer.status} />
          <span className="visually-hidden">
            Transfer {transfer.status}.{" "}
            {formatAmount(transfer.amount, transfer.currency)} to{" "}
            {transfer.recipient_ref}.
          </span>
        </div>
      </div>

      <p className="custody__line">{custodyLine(transfer.status)}</p>

      {/*
        Stage, not progress. Only `created_at` and `updated_at` are exposed by the API,
        so the middle segment can say *that* the provider has it but not since when once
        the transfer has moved on — stated as "yes" rather than invented. Surfacing the
        real per-transition timestamps would mean the API returning the transfer's
        webhook events, which it deliberately does not yet.
      */}
      <ol className="stages">
        <li className="stage stage--done">
          <span className="stage__label">Created</span>
          <span className="stage__value">{formatTimestamp(transfer.created_at)}</span>
        </li>

        <li className={`stage ${withProvider ? "stage--done" : "stage--future"}`}>
          <span className="stage__label">With provider</span>
          <span className="stage__value">
            {zone === "theirs" ? (
              <Elapsed since={transfer.updated_at} />
            ) : withProvider ? (
              "yes"
            ) : (
              "not yet sent"
            )}
          </span>
        </li>

        {/* The dashed "no ETA exists" treatment belongs only to a transfer actually
            with the provider. A pending transfer's settlement is not unknowable — it
            simply has not started, which is a different fact and reads differently. */}
        <li
          className={`stage ${
            zone === "settled"
              ? "stage--done"
              : zone === "theirs"
                ? "stage--unknown"
                : "stage--future"
          }`}
        >
          <span className="stage__label">Settled</span>
          <span className="stage__value">
            {zone === "settled"
              ? formatTimestamp(transfer.updated_at)
              : zone === "theirs"
                ? "unknown — no ETA exists"
                : "—"}
          </span>
        </li>
      </ol>

      {zone === "theirs" && (
        <p className="custody__poll">
          Checking for the provider&apos;s answer every 3 seconds — this page updates
          itself, no reload needed.
        </p>
      )}

      {/*
        The permanent acknowledgement. A brief animation serves the operator who was
        looking; this serves the one who was not, and they need the same information.
        The event id that settled it lives in the backend's WebhookEvent audit trail and
        is not exposed by the transfer endpoint, so this names the instant rather than
        claiming an id it cannot see.
      */}
      {zone === "settled" && (
        <p className="custody__stamp">
          Recorded {formatTimestamp(transfer.updated_at)} and immutable.
        </p>
      )}
    </section>
  );
}
