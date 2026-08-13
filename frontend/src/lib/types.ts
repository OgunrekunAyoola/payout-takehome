/**
 * The API contract, as TypeScript.
 *
 * Hand-written rather than generated: the backend publishes no OpenAPI schema (a
 * deliberate omission for an exercise this size), so these types are a *claim* about
 * the server, not proof. They are kept narrow — literal unions rather than `string` —
 * so that a backend change like renaming a status breaks compilation somewhere useful
 * instead of rendering an empty badge in production.
 */

export const TRANSFER_STATUSES = [
  "pending",
  "processing",
  "completed",
  "failed",
  "cancelled",
] as const;

export type TransferStatus = (typeof TRANSFER_STATUSES)[number];

export const CURRENCIES = ["NGN", "GBP", "USD"] as const;

export type Currency = (typeof CURRENCIES)[number];

/** The statuses a provider webhook is allowed to assert. */
export const WEBHOOK_STATUSES = ["completed", "failed"] as const;

export type WebhookStatus = (typeof WEBHOOK_STATUSES)[number];

export interface Transfer {
  reference: string;
  /**
   * A string, not a number — the backend serialises decimals as strings on purpose,
   * and parsing money into a JS float here would throw away the precision it went to
   * the trouble of preserving. It is formatted for display and otherwise passed
   * through untouched.
   */
  amount: string;
  currency: Currency;
  recipient_ref: string;
  status: TransferStatus;
  provider_transfer_id: string | null;
  created_at: string;
  updated_at: string;
}

/** DRF's PageNumberPagination envelope. */
export interface Paginated<T> {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
}

/**
 * How an API call failed, in terms this UI can act on.
 *
 * `conflict` is the interesting one. The backend answers every refused state change
 * with one 409 envelope — `{detail, current_status, attempted_status}` — and the two
 * reasons it fires need opposite responses from the user: an illegal move will fail
 * forever (stop), while a lost race means the transfer moved underneath this page
 * (re-read and decide again). Both arrive carrying `current_status`, which is what
 * lets the UI re-sync rather than just apologise.
 */
export type ApiErrorKind =
  | "validation"
  | "conflict"
  | "not_found"
  | "unauthorized"
  | "server"
  | "network";

export interface ApiError {
  kind: ApiErrorKind;
  /** Human-readable, safe to render. */
  message: string;
  /** Per-field messages from a DRF 400, keyed by field name. */
  fields?: Record<string, string[]>;
  /** From a 409: the status the transfer actually holds now. */
  currentStatus?: TransferStatus | null;
}

export type ApiResult<T> =
  | { ok: true; status: number; data: T }
  | { ok: false; status: number; error: ApiError };
