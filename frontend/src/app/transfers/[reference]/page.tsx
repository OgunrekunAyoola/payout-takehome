import Link from "next/link";
import { notFound } from "next/navigation";

import {
  cancelTransferAction,
  simulateWebhookAction,
  submitTransferAction,
} from "@/actions/transfers";
import { AutoRefresh } from "@/components/AutoRefresh";
import { SimulateWebhookPanel } from "@/components/SimulateWebhookPanel";
import { StatusBadge } from "@/components/StatusBadge";
import { TransferActions } from "@/components/TransferActions";
import { getTransfer } from "@/lib/api";
import { formatAmount, formatTimestamp } from "@/lib/format";
import { isTerminal } from "@/lib/transitions";

/**
 * One transfer: what it is, where it is, and what can still be done to it.
 *
 * The server actions are passed down as props rather than imported by the client
 * components. That is what keeps those components testable in isolation — a test can
 * hand them a stub instead of standing up a server — and it keeps the network surface
 * in one place.
 */
export default async function TransferDetailPage({
  params,
}: {
  params: Promise<{ reference: string }>;
}) {
  const { reference } = await params;
  const result = await getTransfer(reference);

  if (!result.ok && result.error.kind === "not_found") {
    notFound();
  }

  if (!result.ok) {
    return (
      <div className="detail">
        <Link href="/" className="backlink">
          ← All transfers
        </Link>
        <p className="notice notice--error" role="alert">
          {result.error.message}
        </p>
      </div>
    );
  }

  const transfer = result.data;

  return (
    <div className="detail">
      <Link href="/" className="backlink">
        ← All transfers
      </Link>

      {/* Only poll while the provider still owes us an answer. */}
      <AutoRefresh enabled={!isTerminal(transfer.status)} />

      <div className="section-head">
        <h1 className="mono">{transfer.reference}</h1>
        {/* The status is the one thing on this page that changes without the user
            doing anything — a provider webhook lands and the poll picks it up. Before
            this live region, the notices announced themselves but the status itself
            did not, so a screen-reader user watching a transfer resolve was told
            nothing at all. The hidden sentence carries what a sighted user gets from
            the badge plus its surroundings: what happened, to how much, for whom. */}
        <div aria-live="polite" className="status-region">
          <StatusBadge status={transfer.status} />
          <span className="visually-hidden">
            Transfer {transfer.status}.{" "}
            {formatAmount(transfer.amount, transfer.currency)} to{" "}
            {transfer.recipient_ref}.
          </span>
        </div>
      </div>

      <dl className="facts card">
        <div>
          <dt>Amount</dt>
          <dd className="numeric">
            {formatAmount(transfer.amount, transfer.currency)}
          </dd>
        </div>
        <div>
          <dt>Recipient reference</dt>
          <dd>{transfer.recipient_ref}</dd>
        </div>
        <div>
          <dt>Provider transfer id</dt>
          <dd className="mono">
            {transfer.provider_transfer_id ?? (
              <span className="muted">
                none — assigned when the transfer is submitted
              </span>
            )}
          </dd>
        </div>
        <div>
          <dt>Created</dt>
          <dd>{formatTimestamp(transfer.created_at)}</dd>
        </div>
        <div>
          <dt>Last updated</dt>
          <dd>{formatTimestamp(transfer.updated_at)}</dd>
        </div>
      </dl>

      <div className="card">
        <TransferActions
          transfer={transfer}
          onSubmit={submitTransferAction}
          onCancel={cancelTransferAction}
        />
      </div>

      <SimulateWebhookPanel
        transfer={transfer}
        onSimulate={simulateWebhookAction}
      />
    </div>
  );
}
