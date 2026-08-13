import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { TransferActions } from "./TransferActions";
import { makeTransfer } from "@/test-support/fixtures";
import type { ApiError, TransferStatus } from "@/lib/types";

const refresh = vi.fn();

// The component calls router.refresh() to re-read the transfer after a mutation.
// There is no app-router context in jsdom, so the hook is stubbed; the assertions
// below check that the refresh *happens*, which is the behaviour that matters.
vi.mock("next/navigation", () => ({
  useRouter: () => ({ refresh, push: vi.fn() }),
}));

beforeEach(() => {
  refresh.mockClear();
});

const ok = async () => ({ ok: true });

function renderActions(
  status: TransferStatus,
  overrides: {
    onSubmit?: (reference: string) => Promise<{ ok: boolean; error?: ApiError }>;
    onCancel?: (reference: string) => Promise<{ ok: boolean; error?: ApiError }>;
  } = {},
) {
  const transfer = makeTransfer({ status });
  const onSubmit = overrides.onSubmit ?? vi.fn(ok);
  const onCancel = overrides.onCancel ?? vi.fn(ok);
  render(
    <TransferActions
      transfer={transfer}
      onSubmit={onSubmit}
      onCancel={onCancel}
    />,
  );
  return { transfer, onSubmit, onCancel };
}

const submitButton = () => screen.getByRole("button", { name: /submit/i });
const cancelButton = () => screen.getByRole("button", { name: /cancel/i });

/**
 * The brief's named frontend requirement: illegal actions must be disabled for
 * processing and terminal states.
 *
 * These are written per-status rather than as one loop, because the *reason* each
 * state blocks an action differs, and a failure should name which state broke.
 */
describe("TransferActions — which actions each state allows", () => {
  it("offers both actions on a pending transfer", () => {
    renderActions("pending");
    expect(submitButton()).toBeEnabled();
    expect(cancelButton()).toBeEnabled();
  });

  it("disables both actions while processing (scenario E: no cancel after submit)", () => {
    renderActions("processing");
    expect(submitButton()).toBeDisabled();
    expect(cancelButton()).toBeDisabled();
    // Disabled is not enough — the page must say why, or it just looks broken.
    expect(screen.getByText(/only be settled by their webhook/i)).toBeInTheDocument();
  });

  it.each(["completed", "failed", "cancelled"] as const)(
    "disables both actions on a %s transfer, which is final",
    (status) => {
      renderActions(status);
      expect(submitButton()).toBeDisabled();
      expect(cancelButton()).toBeDisabled();
      expect(screen.getAllByText(/final/i).length).toBeGreaterThan(0);
    },
  );

  it("cannot fire a disabled action even if clicked", async () => {
    const onSubmit = vi.fn(ok);
    renderActions("completed", { onSubmit });
    await userEvent.click(submitButton());
    expect(onSubmit).not.toHaveBeenCalled();
  });
});

describe("TransferActions — running an action", () => {
  it("submits the transfer by reference and re-reads it afterwards", async () => {
    const onSubmit = vi.fn(ok);
    const { transfer } = renderActions("pending", { onSubmit });

    await userEvent.click(submitButton());

    await waitFor(() => expect(onSubmit).toHaveBeenCalledWith(transfer.reference));
    await waitFor(() => expect(refresh).toHaveBeenCalled());
  });

  /**
   * The important one. A transfer can be settled by a provider webhook between the
   * moment this page rendered and the moment the button is clicked, so the server
   * refusing a move the UI believed was legal is an expected outcome — not a crash.
   * The user must be told what the transfer is *now*, and the page must re-read.
   */
  it("shows the conflict and re-reads when the transfer moved underneath the page", async () => {
    const onSubmit = vi.fn(async () => ({
      ok: false,
      error: {
        kind: "conflict" as const,
        message: "A transfer in 'completed' cannot move to 'processing'.",
        currentStatus: "completed" as const,
      },
    }));
    renderActions("pending", { onSubmit });

    await userEvent.click(submitButton());

    expect(
      await screen.findByText(/cannot move to 'processing'/i),
    ).toBeInTheDocument();
    // The status it actually holds now is surfaced, so the user can act on it.
    expect(await screen.findByText("completed")).toBeInTheDocument();
    await waitFor(() => expect(refresh).toHaveBeenCalled());
  });

  it("disables both buttons while a request is in flight", async () => {
    let release: (value: { ok: boolean }) => void = () => {};
    const onSubmit = vi.fn(
      () => new Promise<{ ok: boolean }>((resolve) => (release = resolve)),
    );
    renderActions("pending", { onSubmit });

    await userEvent.click(submitButton());

    // Double-clicking a submit is how a user creates a second payout instruction.
    await waitFor(() => expect(submitButton()).toBeDisabled());
    expect(cancelButton()).toBeDisabled();

    release({ ok: true });
    await waitFor(() => expect(refresh).toHaveBeenCalled());
  });
});
