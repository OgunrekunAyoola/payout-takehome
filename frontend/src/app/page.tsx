import Link from "next/link";

import { createTransferAction } from "@/actions/transfers";
import { AutoRefresh } from "@/components/AutoRefresh";
import { CreateTransferForm } from "@/components/CreateTransferForm";
import { StatusBadge } from "@/components/StatusBadge";
import { listTransfers } from "@/lib/api";
import { formatAmount, formatTimestamp } from "@/lib/format";
import { isTerminal, zoneFor } from "@/lib/transitions";
import type { Transfer } from "@/lib/types";

/**
 * The list, newest first, with the create form beside it.
 *
 * A server component: the fetch happens on the server, so the browser gets rendered
 * HTML rather than a spinner that then goes looking for an API. The failure path is
 * rendered rather than thrown — a backend that is not running is the single most
 * likely thing to go wrong on a reviewer's machine, and it should produce a page that
 * says so, not a stack trace.
 */
export default async function TransfersPage() {
  const result = await listTransfers();

  // One read, partitioned by custody. The same predicate decides whether to poll, so
  // the two can't disagree about whether anything is still moving.
  const rows = result.ok ? result.data.results : [];
  const inFlight = rows.filter((transfer) => !isTerminal(transfer.status));
  const settled = rows.filter((transfer) => isTerminal(transfer.status));

  return (
    <div className="layout">
      <section className="layout__main">
        <div className="section-head">
          <h1>Transfers</h1>
          {result.ok && (
            <span className="muted">
              {result.data.count} total
              {result.data.next ? ` · showing first ${result.data.results.length}` : ""}
            </span>
          )}
        </div>

        {!result.ok ? (
          <p className="notice notice--error" role="alert">
            {result.error.message}
          </p>
        ) : result.data.results.length === 0 ? (
          <p className="muted empty">
            No transfers yet. Create one with the form, then submit it to the provider.
            Nothing leaves this system until you press Submit.
          </p>
        ) : (
          <>
            {/* Poll while anything on this page can still move. A list of nothing but
                completed/failed/cancelled transfers is finished changing. */}
            <AutoRefresh enabled={inFlight.length > 0} />

            {/*
              Split into two tables rather than one sorted list. "Can this still change?"
              is the only ordering an operator actually wants, and grouping answers it
              without a filter control to discover. Both groups come from the single
              server-side read already performed — partitioning is plain code, not
              another request.
            */}
            <TransferGroup
              title="In flight"
              note="these can still change"
              transfers={inFlight}
            />
            <TransferGroup
              title="Settled"
              note="immutable · newest first"
              transfers={settled}
            />

            {result.data.next && (
              <p className="muted">
                Only the first page is shown. Pagination is a deliberate omission —
                see the README.
              </p>
            )}
          </>
        )}
      </section>

      <aside className="layout__aside">
        <CreateTransferForm action={createTransferAction} />
      </aside>
    </div>
  );
}

/**
 * One custody group as a table.
 *
 * A queue of payouts is a table and the column is the point: running your eye down
 * Amount to find the unusually large one is the first review an operator does, and it
 * is exactly the affordance a card list destroys. The state presence a row needs comes
 * from the leading custody rail and from this grouping — neither of which costs any
 * vertical space, so rows got shorter rather than taller.
 */
function TransferGroup({
  title,
  note,
  transfers,
}: {
  title: string;
  note: string;
  transfers: Transfer[];
}) {
  if (transfers.length === 0) return null;

  return (
    <section className="group">
      <header className="group__head">
        <h2 className="group__title">{title}</h2>
        <span className="group__count">{transfers.length}</span>
        <span className="group__note">{note}</span>
      </header>

      <table className="table">
        <caption className="visually-hidden">
          {title} transfers, newest first
        </caption>
        <thead>
          <tr>
            <th scope="col">Reference</th>
            <th scope="col">Amount</th>
            <th scope="col">Recipient</th>
            <th scope="col">Status</th>
            <th scope="col">Created (UTC)</th>
          </tr>
        </thead>
        <tbody>
          {transfers.map((transfer) => (
            <tr
              key={transfer.reference}
              className={`row row--${zoneFor(transfer.status)}`}
            >
              <td>
                <Link href={`/transfers/${transfer.reference}`} className="mono">
                  {transfer.reference}
                </Link>
              </td>
              <td className="numeric">
                {formatAmount(transfer.amount, transfer.currency)}
              </td>
              <td>{transfer.recipient_ref}</td>
              <td>
                <StatusBadge status={transfer.status} />
              </td>
              <td className="muted">{formatTimestamp(transfer.created_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
