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
 * Who holds the money right now.
 *
 * Five statuses are a state machine, but an operator's question is smaller than that:
 * can I act, or am I waiting on someone else? Three answers — `ours`, `theirs`,
 * `settled` — and that grouping is what the badge shape, the list sectioning and the
 * detail page's hierarchy all encode. It costs nothing at the DOM level and it is the
 * difference between reading five colours and reading one fact.
 *
 * Derived from the transition table rather than kept as a fourth list, for the same
 * reason `isTerminal` is: a second declaration of the same fact drifts the first time
 * someone adds a status.
 */
export type CustodyZone = "ours" | "theirs" | "settled";

export function zoneFor(status: TransferStatus): CustodyZone {
  if (isTerminal(status)) return "settled";
  // Still moving. If we can still hand it over, it is ours; if we cannot, it is
  // because we already did.
  return canSubmit(status) ? "ours" : "theirs";
}

/** The custody fact, as a sentence — what is true of this transfer right now. */
export function custodyLine(status: TransferStatus): string {
  switch (zoneFor(status)) {
    case "ours":
      return "Not yet sent. Fully under your control.";
    case "theirs":
      return "With the provider. Only their webhook can resolve it.";
    case "settled":
      if (status === "completed") return "Money arrived. This is final and cannot be changed.";
      if (status === "failed") return "The provider reported failure. This is final and cannot be changed.";
      return "Cancelled before it was ever sent. This is final and cannot be changed.";
  }
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
