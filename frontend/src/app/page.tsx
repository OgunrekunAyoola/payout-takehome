import Link from "next/link";

import { createTransferAction } from "@/actions/transfers";
import { AutoRefresh } from "@/components/AutoRefresh";
import { CreateTransferForm } from "@/components/CreateTransferForm";
import { StatusBadge } from "@/components/StatusBadge";
import { listTransfers } from "@/lib/api";
import { formatAmount, formatTimestamp } from "@/lib/format";
import { isTerminal } from "@/lib/transitions";

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
          </p>
        ) : (
          <>
            {/* Poll while anything on this page can still move. A list of nothing but
                completed/failed/cancelled transfers is finished changing. */}
            <AutoRefresh
              enabled={result.data.results.some((t) => !isTerminal(t.status))}
            />
            <table className="table">
              <caption className="visually-hidden">
                Transfers, newest first
              </caption>
              <thead>
                <tr>
                  <th scope="col">Reference</th>
                  <th scope="col">Amount</th>
                  <th scope="col">Recipient</th>
                  <th scope="col">Status</th>
                  <th scope="col">Created</th>
                </tr>
              </thead>
              <tbody>
                {result.data.results.map((transfer) => (
                  <tr key={transfer.reference}>
                    <td>
                      <Link
                        href={`/transfers/${transfer.reference}`}
                        className="mono"
                      >
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
                    <td className="muted">
                      {formatTimestamp(transfer.created_at)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
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
