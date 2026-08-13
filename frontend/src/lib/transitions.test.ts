import { describe, expect, it } from "vitest";

import {
  canCancel,
  canSubmit,
  cancelBlockedReason,
  custodyLine,
  isTerminal,
  submitBlockedReason,
  zoneFor,
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

/**
 * Custody is what the UI is actually organised around, so the mapping from five
 * statuses down to three zones is worth pinning: it drives the badge shape, the list
 * sectioning and the whole detail hierarchy.
 */
describe("custody zones", () => {
  it("puts each status in exactly one zone", () => {
    expect(zoneFor("pending")).toBe("ours");
    expect(zoneFor("processing")).toBe("theirs");
    expect(zoneFor("completed")).toBe("settled");
    expect(zoneFor("failed")).toBe("settled");
    expect(zoneFor("cancelled")).toBe("settled");
  });

  /** Derived from the transition table, so it cannot drift from isTerminal. */
  it("treats settled as exactly the terminal statuses", () => {
    const settled = TRANSFER_STATUSES.filter((s) => zoneFor(s) === "settled");
    const terminal = TRANSFER_STATUSES.filter(isTerminal);
    expect(settled).toEqual(terminal);
  });

  it("only calls a transfer ours while we can still act on it", () => {
    for (const status of TRANSFER_STATUSES) {
      if (zoneFor(status) === "ours") {
        expect(canSubmit(status) || canCancel(status)).toBe(true);
      } else {
        // Anything not ours must offer no actions at all — that is what "waiting on
        // someone else" and "finished" have in common.
        expect(canSubmit(status)).toBe(false);
        expect(canCancel(status)).toBe(false);
      }
    }
  });

  it("says who holds the money, in words, for every status", () => {
    for (const status of TRANSFER_STATUSES) {
      expect(custodyLine(status)).toBeTruthy();
    }
    expect(custodyLine("processing")).toMatch(/provider/i);
    expect(custodyLine("completed")).toMatch(/final/i);
    // A cancelled transfer must read as "never sent", not as money that failed to
    // arrive — that conflation is exactly why cancelled was split from failed.
    expect(custodyLine("cancelled")).toMatch(/sent/i);
    expect(custodyLine("cancelled")).not.toMatch(/fail|arriv/i);
  });
});
