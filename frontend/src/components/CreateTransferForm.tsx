"use client";

import { useActionState, useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { CURRENCIES } from "@/lib/types";
import type { Currency } from "@/lib/types";
import type { CreateTransferState } from "@/actions/transfers";

/**
 * The create-transfer form.
 *
 * The part worth reading is the idempotency key.
 *
 * `POST /api/transfers/` requires an `Idempotency-Key`, and the header only protects
 * anyone if the *same* key is sent again when a request is retried. So the key is
 * minted once, when the form is first shown, and held in a ref — it deliberately
 * survives re-renders, failed submissions and network errors. If the API times out and
 * the user presses the button again, the retry carries the original key and the backend
 * replays the transfer it already created (200) instead of creating a second one. A key
 * generated per submit would look identical in the happy path and quietly double every
 * payout that was ever retried, which is the failure this whole mechanism exists to
 * prevent.
 *
 * The key rotates on exactly one event: a confirmed success. At that point the next
 * transfer is a genuinely new intent and must not replay the last one.
 */
export function CreateTransferForm({
  action,
}: {
  action: (
    previous: CreateTransferState,
    formData: FormData,
  ) => Promise<CreateTransferState>;
}) {
  const [state, formAction, pending] = useActionState<
    CreateTransferState,
    FormData
  >(action, { status: "idle" });
  const router = useRouter();

  // Minted after mount, same gate as Elapsed. A `useState` initialiser runs during the
  // server pass too, so it mints one key in the HTML and a different one on hydration —
  // a mismatch React reports on every page holding this form. Starting empty keeps the
  // server pass and the first client pass identical; the key appears a tick later. A
  // server-minted key is not an option regardless: every user served that HTML would
  // share it.
  const [idempotencyKey, setIdempotencyKey] = useState<string>("");

  useEffect(() => {
    setIdempotencyKey((current) => current || newKey());
  }, []);

  // The inputs are controlled, and that is not a stylistic choice. React resets a form
  // automatically once its action completes — including when the action *failed* — so
  // with uncontrolled inputs a rejected create would silently wipe everything the user
  // typed and make them enter it all again to retry. Holding the values in state means
  // a failure leaves the form exactly as it was, ready to resubmit under the same
  // idempotency key.
  const [amount, setAmount] = useState("");
  const [currency, setCurrency] = useState<Currency>(CURRENCIES[0]);
  const [recipientRef, setRecipientRef] = useState("");

  useEffect(() => {
    if (state.status !== "created") return;
    // Success: this intent is done with. Rotate the key, clear the form, and go to the
    // transfer so the user can act on it.
    setIdempotencyKey(newKey());
    setAmount("");
    setRecipientRef("");
    router.push(`/transfers/${state.reference}`);
  }, [state, router]);

  const fieldErrors = state.status === "error" ? (state.error.fields ?? {}) : {};

  return (
    <form action={formAction} className="card form">
      <h2>New transfer</h2>

      <input type="hidden" name="idempotency_key" value={idempotencyKey} />

      <div className="form__row">
        <label htmlFor="amount">Amount</label>
        <input
          id="amount"
          name="amount"
          // `inputMode` rather than `type="number"`: a number input in some browsers
          // silently mangles trailing zeros and lets the wheel change a value the user
          // already typed. On a money field neither is acceptable.
          inputMode="decimal"
          placeholder="150.00"
          required
          value={amount}
          onChange={(event) => setAmount(event.target.value)}
          aria-describedby={fieldErrors.amount ? "amount-error" : undefined}
          aria-invalid={Boolean(fieldErrors.amount)}
        />
        {fieldErrors.amount && (
          <p className="field-error" id="amount-error">
            {fieldErrors.amount.join(" ")}
          </p>
        )}
      </div>

      <div className="form__row">
        <label htmlFor="currency">Currency</label>
        <select
          id="currency"
          name="currency"
          value={currency}
          onChange={(event) => setCurrency(event.target.value as Currency)}
          aria-describedby={fieldErrors.currency ? "currency-error" : undefined}
          aria-invalid={Boolean(fieldErrors.currency)}
        >
          {CURRENCIES.map((currency) => (
            <option key={currency} value={currency}>
              {currency}
            </option>
          ))}
        </select>
        {fieldErrors.currency && (
          <p className="field-error" id="currency-error">
            {fieldErrors.currency.join(" ")}
          </p>
        )}
      </div>

      <div className="form__row">
        <label htmlFor="recipient_ref">Recipient reference</label>
        <input
          id="recipient_ref"
          name="recipient_ref"
          placeholder="ACME-PAYROLL-014"
          required
          value={recipientRef}
          onChange={(event) => setRecipientRef(event.target.value)}
          aria-describedby={
            fieldErrors.recipient_ref ? "recipient-error" : undefined
          }
          aria-invalid={Boolean(fieldErrors.recipient_ref)}
        />
        {fieldErrors.recipient_ref && (
          <p className="field-error" id="recipient-error">
            {fieldErrors.recipient_ref.join(" ")}
          </p>
        )}
      </div>

      <button
        type="submit"
        className="button button--primary"
        // Also inert for the tick before the key is minted: a create must never be
        // sent without its idempotency key.
        disabled={pending || !idempotencyKey}
      >
        {pending ? "Creating…" : "Create transfer"}
      </button>

      <div aria-live="polite">
        {state.status === "error" && !hasFieldErrors(state) && (
          <p className="notice notice--error" role="alert">
            {state.error.message}
          </p>
        )}
      </div>

      <p className="form__hint">
        Sent with <code>Idempotency-Key: {idempotencyKey || "…"}</code>. Retrying after a
        failure reuses this key, so a retry replays the original transfer instead of
        creating a second one.
      </p>
    </form>
  );
}

function hasFieldErrors(state: CreateTransferState): boolean {
  return (
    state.status === "error" &&
    Boolean(state.error.fields && Object.keys(state.error.fields).length > 0)
  );
}

function newKey(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  // Older browsers (and jsdom without a crypto shim). Uniqueness here only has to
  // hold across one user's submissions, and the value is never a security boundary.
  return `key-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}
