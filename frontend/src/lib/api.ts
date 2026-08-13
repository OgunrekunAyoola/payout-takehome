import "server-only";

import { signProviderPayload } from "./provider-signature";
import type {
  ApiError,
  ApiResult,
  Currency,
  Paginated,
  Transfer,
  TransferStatus,
  WebhookStatus,
} from "./types";

/**
 * The only place this app talks to Django.
 *
 * Every call runs on the server — from a server component rendering a page, or from a
 * server action handling a click. The browser never holds a backend URL and never
 * makes a cross-origin request, which is why the Django side needs no CORS
 * configuration and no `django-cors-headers` dependency. It also means the webhook
 * secret can be used (see the simulator) without ever being served to a client.
 *
 * Nothing here throws on an HTTP error. Failures come back as data — an `ApiResult`
 * discriminated union — because every caller is either a page that must still render
 * something useful or a server action whose job is to hand the UI an error to display.
 * A thrown exception would become a 500 error page, which is a strictly worse answer
 * to "the transfer you clicked was already cancelled".
 */

const BACKEND_URL = process.env.BACKEND_URL ?? "http://127.0.0.1:8000";

export interface CreateTransferInput {
  amount: string;
  currency: Currency;
  recipient_ref: string;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/**
 * Turn a DRF error body into something renderable.
 *
 * DRF speaks two dialects: `{"detail": "..."}` for a single message, and
 * `{"field": ["...", "..."]}` for validation. Both reach the UI, so both are
 * normalised here rather than at each call site.
 */
function toApiError(status: number, body: unknown): ApiError {
  const kind: ApiError["kind"] =
    status === 400
      ? "validation"
      : status === 401 || status === 403
        ? "unauthorized"
        : status === 404
          ? "not_found"
          : status === 409
            ? "conflict"
            : "server";

  if (!isRecord(body)) {
    return { kind, message: `The server returned an unexpected ${status}.` };
  }

  const error: ApiError = { kind, message: "" };

  if (typeof body.detail === "string") {
    error.message = body.detail;
  }

  // A 409 from any state change carries the status the transfer actually holds now.
  // Passing it through is what lets the UI re-sync instead of merely apologising.
  if ("current_status" in body) {
    error.currentStatus = (body.current_status ?? null) as TransferStatus | null;
  }

  const fields: Record<string, string[]> = {};
  for (const [key, value] of Object.entries(body)) {
    if (key === "detail" || key === "current_status" || key === "attempted_status") {
      continue;
    }
    if (Array.isArray(value)) {
      fields[key] = value.map(String);
    } else if (typeof value === "string") {
      fields[key] = [value];
    }
  }
  if (Object.keys(fields).length > 0) {
    error.fields = fields;
  }

  if (!error.message) {
    const firstField = Object.entries(fields)[0];
    error.message = firstField
      ? `${firstField[0]}: ${firstField[1][0] ?? "Invalid value."}`
      : `The server returned an unexpected ${status}.`;
  }

  return error;
}

async function request<T>(
  path: string,
  init: RequestInit = {},
): Promise<ApiResult<T>> {
  let response: Response;
  try {
    response = await fetch(`${BACKEND_URL}${path}`, {
      ...init,
      headers: { Accept: "application/json", ...init.headers },
      // Transfers change without this app doing anything — a provider webhook can
      // complete one at any moment — so a cached read is a stale read. Correctness
      // over a cache hit on a page whose whole purpose is watching status change.
      cache: "no-store",
    });
  } catch (cause) {
    // Almost always "the Django server isn't running". Say that, rather than leaking
    // an ECONNREFUSED stack into the page.
    return {
      ok: false,
      status: 0,
      error: {
        kind: "network",
        message: `Could not reach the API at ${BACKEND_URL}. Is the Django server running?`,
      },
    };
  }

  if (response.status === 204) {
    return { ok: true, status: response.status, data: undefined as T };
  }

  let body: unknown = null;
  const text = await response.text();
  if (text) {
    try {
      body = JSON.parse(text);
    } catch {
      body = null;
    }
  }

  if (!response.ok) {
    return { ok: false, status: response.status, error: toApiError(response.status, body) };
  }

  return { ok: true, status: response.status, data: body as T };
}

export function listTransfers(): Promise<ApiResult<Paginated<Transfer>>> {
  return request<Paginated<Transfer>>("/api/transfers/");
}

export function getTransfer(reference: string): Promise<ApiResult<Transfer>> {
  return request<Transfer>(`/api/transfers/${encodeURIComponent(reference)}/`);
}

/**
 * Create a transfer.
 *
 * `idempotencyKey` is supplied by the caller rather than minted here, and that is the
 * whole point: the key must survive a retry to do its job. Generating one inside this
 * function would mint a fresh key per attempt, so a user retrying after a timeout
 * would create a second transfer — the exact double-payout the header exists to
 * prevent. The form owns the key and holds it steady across retries (see
 * CreateTransferForm).
 */
export function createTransfer(
  input: CreateTransferInput,
  idempotencyKey: string,
): Promise<ApiResult<Transfer>> {
  return request<Transfer>("/api/transfers/", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Idempotency-Key": idempotencyKey,
    },
    body: JSON.stringify(input),
  });
}

export function submitTransfer(reference: string): Promise<ApiResult<Transfer>> {
  return request<Transfer>(
    `/api/transfers/${encodeURIComponent(reference)}/submit/`,
    { method: "POST" },
  );
}

export function cancelTransfer(reference: string): Promise<ApiResult<Transfer>> {
  return request<Transfer>(
    `/api/transfers/${encodeURIComponent(reference)}/cancel/`,
    { method: "POST" },
  );
}

export interface WebhookAck {
  detail: string;
  event_id: string;
  outcome: string;
}

/**
 * Post a signed provider webhook — the demo's stand-in for the provider calling us.
 *
 * The body is posted exactly as signed. `signProviderPayload` returns the string it
 * hashed and that same string goes out as the request body, so the bytes Django
 * verifies are byte-for-byte the bytes that were signed.
 */
export function sendProviderWebhook(payload: {
  event_id: string;
  provider_transfer_id: string;
  status: WebhookStatus;
  occurred_at: string;
}): Promise<ApiResult<WebhookAck>> {
  const { body, signature } = signProviderPayload(payload);
  return request<WebhookAck>("/api/webhooks/provider/", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Provider-Signature": signature,
    },
    body,
  });
}
