import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CreateTransferForm } from "./CreateTransferForm";
import type { CreateTransferState } from "@/actions/transfers";

const push = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, refresh: vi.fn() }),
}));

beforeEach(() => {
  push.mockClear();
});

/** The hidden field carrying the Idempotency-Key that will be sent with the create. */
function idempotencyKey(container: HTMLElement): string {
  const input = container.querySelector<HTMLInputElement>(
    'input[name="idempotency_key"]',
  );
  if (!input) throw new Error("form is not sending an idempotency key at all");
  return input.value;
}

async function fillAndSubmit() {
  await userEvent.type(screen.getByLabelText(/amount/i), "150.00");
  await userEvent.type(screen.getByLabelText(/recipient/i), "ACME-PAYROLL-014");
  await userEvent.click(screen.getByRole("button", { name: /create transfer/i }));
}

describe("CreateTransferForm", () => {
  it("sends the fields the API expects, with an idempotency key", async () => {
    const action = vi.fn(
      async (_prev: CreateTransferState, formData: FormData) => {
        expect(formData.get("amount")).toBe("150.00");
        expect(formData.get("currency")).toBe("NGN");
        expect(formData.get("recipient_ref")).toBe("ACME-PAYROLL-014");
        expect(String(formData.get("idempotency_key"))).not.toBe("");
        return { status: "created", reference: "TRF-0123456789abcdef" } as const;
      },
    );

    render(<CreateTransferForm action={action} />);
    await fillAndSubmit();

    await waitFor(() => expect(action).toHaveBeenCalledOnce());
  });

  /**
   * The test this component exists for.
   *
   * `Idempotency-Key` only protects anyone if a *retry* carries the same key. If the
   * key were regenerated per attempt, a user retrying after a failure would create a
   * second transfer — a real double payout — and every happy-path test would still
   * pass. So: fail the first submit, retry, and assert the key did not move.
   */
  it("reuses the same idempotency key when a failed create is retried", async () => {
    const keysSeen: string[] = [];
    let attempt = 0;
    const action = vi.fn(
      async (_prev: CreateTransferState, formData: FormData) => {
        keysSeen.push(String(formData.get("idempotency_key")));
        attempt += 1;
        if (attempt === 1) {
          return {
            status: "error",
            error: {
              kind: "network" as const,
              message: "Could not reach the API. Is the Django server running?",
            },
          } as const;
        }
        return { status: "created", reference: "TRF-0123456789abcdef" } as const;
      },
    );

    const { container } = render(<CreateTransferForm action={action} />);
    const keyBefore = idempotencyKey(container);

    await fillAndSubmit();
    expect(await screen.findByText(/could not reach the api/i)).toBeInTheDocument();

    // The failure must not have rotated the key — the retry has to replay, not create.
    expect(idempotencyKey(container)).toBe(keyBefore);

    await userEvent.click(screen.getByRole("button", { name: /create transfer/i }));

    await waitFor(() => expect(keysSeen).toHaveLength(2));
    expect(keysSeen[0]).toBe(keysSeen[1]);
  });

  /** A new intent must not replay the previous transfer, so success rotates the key. */
  it("rotates the key after a successful create and goes to the new transfer", async () => {
    const action = vi.fn(
      async () =>
        ({ status: "created", reference: "TRF-0123456789abcdef" }) as const,
    );

    const { container } = render(<CreateTransferForm action={action} />);
    const keyBefore = idempotencyKey(container);

    await fillAndSubmit();

    await waitFor(() =>
      expect(idempotencyKey(container)).not.toBe(keyBefore),
    );
    expect(push).toHaveBeenCalledWith("/transfers/TRF-0123456789abcdef");
  });

  it("shows validation errors against the field the server rejected", async () => {
    const action = vi.fn(
      async (): Promise<CreateTransferState> => ({
        status: "error",
        error: {
          kind: "validation",
          message: "amount: Ensure this value is greater than or equal to 0.01.",
          fields: {
            amount: ["Ensure this value is greater than or equal to 0.01."],
          },
        },
      }),
    );

    render(<CreateTransferForm action={action} />);
    await fillAndSubmit();

    const amount = screen.getByLabelText(/amount/i);
    await waitFor(() => expect(amount).toHaveAttribute("aria-invalid", "true"));
    expect(
      screen.getByText(/greater than or equal to 0.01/i),
    ).toBeInTheDocument();
  });

  it("disables the submit button while the create is in flight", async () => {
    let release: (value: CreateTransferState) => void = () => {};
    const action = vi.fn(
      () => new Promise<CreateTransferState>((resolve) => (release = resolve)),
    );

    render(<CreateTransferForm action={action} />);
    await fillAndSubmit();

    const button = screen.getByRole("button", { name: /creating/i });
    await waitFor(() => expect(button).toBeDisabled());

    release({ status: "created", reference: "TRF-0123456789abcdef" });
    await waitFor(() => expect(push).toHaveBeenCalled());
  });
});
