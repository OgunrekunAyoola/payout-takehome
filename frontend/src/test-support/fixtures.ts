import type { Transfer, TransferStatus } from "@/lib/types";

/** A transfer in whatever state a test needs, with everything else sensible. */
export function makeTransfer(overrides: Partial<Transfer> = {}): Transfer {
  const status: TransferStatus = overrides.status ?? "pending";
  return {
    reference: "TRF-0123456789abcdef",
    amount: "150.00",
    currency: "NGN",
    recipient_ref: "ACME-PAYROLL-014",
    status,
    // A transfer only holds a provider id once it has been submitted; defaulting it
    // from the status keeps fixtures from describing states the backend cannot
    // produce (a pending transfer with a provider id, say).
    provider_transfer_id: status === "pending" ? null : "prov_abc123",
    created_at: "2026-08-13T09:00:00Z",
    updated_at: "2026-08-13T09:00:00Z",
    ...overrides,
  };
}
