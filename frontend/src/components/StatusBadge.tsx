import type { TransferStatus } from "@/lib/types";

/**
 * A transfer's status, as a pill.
 *
 * Colour is never the only signal — the status word is always present. A badge that
 * distinguishes "completed" from "failed" by green-vs-red alone is unreadable to a
 * colour-blind user, and this is a screen about whether money arrived.
 */
export function StatusBadge({ status }: { status: TransferStatus }) {
  return (
    <span className={`badge badge--${status}`} data-testid="status-badge">
      {status}
    </span>
  );
}
