import { describe, expect, it } from "vitest";

import {
  canCancel,
  canSubmit,
  cancelBlockedReason,
  isTerminal,
  submitBlockedReason,
} from "./transitions";
import { TRANSFER_STATUSES } from "./types";
import type { TransferStatus } from "./types";

/**
 * These rules are a mirror of the backend's transition table, so the thing worth
 * testing is that the mirror is faithful — every status, not just the two the UI
 * happens to exercise today.
 */
describe("transition rules", () => {
  it("allows submit only from pending", () => {
    const allowed = TRANSFER_STATUSES.filter(canSubmit);
    expect(allowed).toEqual(["pending"]);
  });

  it("allows cancel only from pending", () => {
    const allowed = TRANSFER_STATUSES.filter(canCancel);
    expect(allowed).toEqual(["pending"]);
  });

  it("treats completed, failed and cancelled as terminal", () => {
    const terminal = TRANSFER_STATUSES.filter(isTerminal);
    expect(terminal).toEqual(["completed", "failed", "cancelled"]);
  });

  it("never reports a transfer in flight as terminal", () => {
    expect(isTerminal("pending")).toBe(false);
    expect(isTerminal("processing")).toBe(false);
  });

  /**
   * A blocked action must always explain itself, and an allowed one must never
   * invent a reason — the components branch on exactly this null-vs-string contract
   * to decide whether to render an explanation at all.
   */
  it.each(TRANSFER_STATUSES)("explains blocked actions for %s", (status) => {
    const typed = status as TransferStatus;

    if (canSubmit(typed)) {
      expect(submitBlockedReason(typed)).toBeNull();
    } else {
      expect(submitBlockedReason(typed)).toBeTruthy();
    }

    if (canCancel(typed)) {
      expect(cancelBlockedReason(typed)).toBeNull();
    } else {
      expect(cancelBlockedReason(typed)).toBeTruthy();
    }
  });

  /** Scenario E in the brief: cancelling after submit is refused, and says why. */
  it("explains that a processing transfer belongs to the provider", () => {
    expect(cancelBlockedReason("processing")).toMatch(/provider/i);
  });
});
