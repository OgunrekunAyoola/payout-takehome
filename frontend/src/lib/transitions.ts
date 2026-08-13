/**
 * The transfer lifecycle, mirrored on the client so the UI can disable what the server
 * would refuse.
 *
 * This is a *second copy* of a rule the backend already owns (`transfers/states.py`),
 * and that deserves a defence rather than a shrug. The alternative — deriving legal
 * actions from an endpoint — would be one more round trip before a button can render,
 * and the page would still have to handle a refusal, because the transfer can change
 * between that answer and the click. So the copy buys responsiveness, not authority.
 *
 * The rule this file exists under: **the server is the only authority.** Everything
 * here is advisory. A disabled button is a courtesy that keeps a user from firing a
 * request that is already known to be pointless; it is never what makes an illegal
 * transition impossible. That guarantee lives in the database's compare-and-swap, and
 * the UI is built to accept a 409 gracefully at any moment (see TransferActions) —
 * which is exactly what happens when a provider webhook lands while the page is open.
 */

import type { TransferStatus } from "./types";

/** Mirrors ALLOWED_TRANSITIONS in the backend's transfers/states.py. */
export const ALLOWED_TRANSITIONS: Record<
  TransferStatus,
  readonly TransferStatus[]
> = {
  pending: ["processing", "cancelled"],
  processing: ["completed", "failed"],
  completed: [],
  failed: [],
  cancelled: [],
};

export function canTransition(
  from: TransferStatus,
  to: TransferStatus,
): boolean {
  return ALLOWED_TRANSITIONS[from].includes(to);
}

/** True when no further transitions are possible — derived, never a second list. */
export function isTerminal(status: TransferStatus): boolean {
  return ALLOWED_TRANSITIONS[status].length === 0;
}

export function canSubmit(status: TransferStatus): boolean {
  return canTransition(status, "processing");
}

export function canCancel(status: TransferStatus): boolean {
  return canTransition(status, "cancelled");
}

/**
 * Why an action is unavailable, phrased for a person.
 *
 * A disabled button with no explanation reads as a broken page — the user cannot tell
 * "not allowed from here" apart from "this app is stuck". Returning null when the
 * action *is* allowed keeps the caller's branch honest.
 */
export function submitBlockedReason(status: TransferStatus): string | null {
  if (canSubmit(status)) return null;
  if (status === "processing") {
    return "Already submitted to the provider — waiting for its webhook.";
  }
  return `This transfer is ${status}, which is final. It cannot be submitted.`;
}

export function cancelBlockedReason(status: TransferStatus): string | null {
  if (canCancel(status)) return null;
  if (status === "processing") {
    // Scenario E in the brief. The wording matters: the user is not being told "no",
    // they are being told who holds the transfer now and what will resolve it.
    return "Already with the provider. It can only be settled by their webhook, not cancelled here.";
  }
  return `This transfer is ${status}, which is final. It cannot be cancelled.`;
}
