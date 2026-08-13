"use server";

import { randomUUID } from "node:crypto";
import { revalidatePath } from "next/cache";

import {
  cancelTransfer,
  createTransfer,
  sendProviderWebhook,
  submitTransfer,
} from "@/lib/api";
import type { ApiError, Currency, Transfer, WebhookStatus } from "@/lib/types";
import { CURRENCIES, WEBHOOK_STATUSES } from "@/lib/types";

/**
 * Server actions — the only mutations this UI can perform.
 *
 * They return errors rather than throwing them. A thrown error in a server action
 * becomes a generic error boundary, which would turn "that transfer was already
 * cancelled" into a blank page; returning it lets the component that owns the button
 * render the message next to the button that caused it.
 *
 * Each action revalidates the paths whose content it just invalidated, so the list and
 * the detail page reflect the new status without a manual reload.
 */

export interface ActionResult {
  ok: boolean;
  error?: ApiError;
  transfer?: Transfer;
}

export type CreateTransferState =
  | { status: "idle" }
  | { status: "error"; error: ApiError }
  | { status: "created"; reference: string };

function isCurrency(value: string): value is Currency {
  return (CURRENCIES as readonly string[]).includes(value);
}

function isWebhookStatus(value: string): value is WebhookStatus {
  return (WEBHOOK_STATUSES as readonly string[]).includes(value);
}

/**
 * Create a transfer from the form.
 *
 * Field validation is deliberately *not* duplicated here. The backend's serializer
 * already rejects a zero amount, a third decimal place and an unsupported currency,
 * and it is the authority; a second copy of those rules in the UI would drift, and the
 * drift would show up as a form that accepts what the API refuses. What this action
 * does instead is pass DRF's per-field messages straight back to the form, so the user
 * sees the real reason against the real field. The only checks here are the ones that
 * protect *this* function's own contract — a currency it can type, a key it can send.
 *
 * The idempotency key arrives from the form and is used verbatim. See
 * CreateTransferForm for why the client owns it.
 */
export async function createTransferAction(
  _previous: CreateTransferState,
  formData: FormData,
): Promise<CreateTransferState> {
  const amount = String(formData.get("amount") ?? "").trim();
  const currency = String(formData.get("currency") ?? "").trim();
  const recipientRef = String(formData.get("recipient_ref") ?? "").trim();
  const idempotencyKey = String(formData.get("idempotency_key") ?? "").trim();

  if (!isCurrency(currency)) {
    return {
      status: "error",
      error: { kind: "validation", message: "Choose a supported currency.", fields: { currency: ["Choose a supported currency."] } },
    };
  }
  if (!idempotencyKey) {
    // The form always sends one; an empty key means something tampered with or broke
    // the form, and creating money-moving records without the retry protection would
    // be the wrong way to be forgiving.
    return {
      status: "error",
      error: { kind: "validation", message: "Missing idempotency key — reload the page and try again." },
    };
  }

  const result = await createTransfer(
    { amount, currency, recipient_ref: recipientRef },
    idempotencyKey,
  );

  if (!result.ok) {
    return { status: "error", error: result.error };
  }

  // Covers both 201 (created) and 200 (a replayed retry returning the original
  // transfer). From the user's point of view those are the same success — their
  // transfer exists exactly once — which is precisely what the idempotency key buys.
  revalidatePath("/");
  return { status: "created", reference: result.data.reference };
}

export async function submitTransferAction(
  reference: string,
): Promise<ActionResult> {
  const result = await submitTransfer(reference);
  revalidatePath("/");
  revalidatePath(`/transfers/${reference}`);
  if (!result.ok) return { ok: false, error: result.error };
  return { ok: true, transfer: result.data };
}

export async function cancelTransferAction(
  reference: string,
): Promise<ActionResult> {
  const result = await cancelTransfer(reference);
  revalidatePath("/");
  revalidatePath(`/transfers/${reference}`);
  if (!result.ok) return { ok: false, error: result.error };
  return { ok: true, transfer: result.data };
}

export interface SimulateWebhookResult {
  ok: boolean;
  /** Echoed back so the UI can offer to redeliver this exact event (scenario A). */
  eventId: string;
  detail: string;
  outcome?: string;
  error?: ApiError;
}

/**
 * Fire a signed provider webhook at our own backend — the demo's provider.
 *
 * `eventId` is optional and that option is the interesting part. Omit it and a fresh
 * event is minted, which is an ordinary settlement. Pass one back in and the same
 * event is delivered twice, which is the brief's scenario A: the second delivery must
 * change nothing. Being able to trigger that from the UI means the idempotency story
 * can be *shown* rather than described.
 */
export async function simulateWebhookAction(input: {
  reference: string;
  providerTransferId: string;
  status: string;
  eventId?: string;
}): Promise<SimulateWebhookResult> {
  const eventId = input.eventId?.trim() || `evt_${randomUUID().replace(/-/g, "").slice(0, 16)}`;

  if (!isWebhookStatus(input.status)) {
    return {
      ok: false,
      eventId,
      detail: "A provider can only report 'completed' or 'failed'.",
    };
  }

  const result = await sendProviderWebhook({
    event_id: eventId,
    provider_transfer_id: input.providerTransferId,
    status: input.status,
    occurred_at: new Date().toISOString(),
  });

  revalidatePath("/");
  revalidatePath(`/transfers/${input.reference}`);

  if (!result.ok) {
    return {
      ok: false,
      eventId,
      detail: result.error.message,
      error: result.error,
    };
  }

  return {
    ok: true,
    eventId,
    detail: result.data.detail,
    outcome: result.data.outcome,
  };
}
