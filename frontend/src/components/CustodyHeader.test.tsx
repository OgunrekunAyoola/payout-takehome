import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { CustodyHeader } from "./CustodyHeader";
import { makeTransfer } from "@/test-support/fixtures";

/**
 * The custody header carries the one thing on the page that changes with no user
 * action, so its accessible surface is the part worth protecting: a screen-reader user
 * watching a transfer resolve must be *told*, not left to re-read the page.
 */
function liveRegion(container: HTMLElement): HTMLElement {
  const region = container.querySelector<HTMLElement>('[aria-live="polite"]');
  if (!region) throw new Error("the status is not in a live region at all");
  return region;
}

describe("CustodyHeader — the resolution moment's accessible surface", () => {
  it("puts the status inside a live region so a change is announced", () => {
    const { container } = render(
      <CustodyHeader transfer={makeTransfer({ status: "processing" })} />,
    );

    expect(liveRegion(container)).toHaveTextContent("processing");
  });

  it("announces what settled, for how much, and to whom", () => {
    const { container } = render(
      <CustodyHeader
        transfer={makeTransfer({
          status: "completed",
          amount: "150.00",
          currency: "NGN",
          recipient_ref: "ACME-PAYROLL-014",
        })}
      />,
    );

    const region = liveRegion(container);
    // The sentence a sighted user assembles from the badge and its surroundings.
    expect(region).toHaveTextContent(/transfer completed/i);
    expect(region).toHaveTextContent(/150\.00/);
    expect(region).toHaveTextContent(/ACME-PAYROLL-014/);
  });
});

describe("CustodyHeader — what waiting looks like", () => {
  it("refuses to imply an ETA while the provider holds the transfer", () => {
    render(<CustodyHeader transfer={makeTransfer({ status: "processing" })} />);

    // The dashed third segment exists to say, in words, that we cannot know.
    expect(screen.getByText(/no ETA exists/i)).toBeInTheDocument();
    expect(screen.getByText(/every 3 seconds/i)).toBeInTheDocument();
  });

  it("beats a heartbeat only while there is something to wait for", () => {
    const { container: waiting } = render(
      <CustodyHeader transfer={makeTransfer({ status: "processing" })} />,
    );
    expect(waiting.querySelector(".custody__pulse")).not.toBeNull();

    const { container: settled } = render(
      <CustodyHeader transfer={makeTransfer({ status: "completed" })} />,
    );
    // A completed transfer is never going to change again. A pulse here would be
    // decoration claiming to be information.
    expect(settled.querySelector(".custody__pulse")).toBeNull();
  });

  /**
   * Regression: a pending transfer was rendering the dashed "no ETA exists" treatment,
   * which implied settlement was unknowable when in fact nothing had been sent yet.
   * Not started and unknowable are different facts and must not look alike. Found by
   * driving the real lifecycle, not by a unit test — hence this one.
   */
  it("does not treat an unsent transfer's settlement as unknowable", () => {
    const { container } = render(
      <CustodyHeader transfer={makeTransfer({ status: "pending" })} />,
    );

    expect(container.querySelector(".stage--unknown")).toBeNull();
    expect(screen.queryByText(/no ETA exists/i)).not.toBeInTheDocument();
    // The stage says plainly that it has not started — scoped to the stage values,
    // because the custody sentence above says the same thing in its own words.
    const stageValues = Array.from(
      container.querySelectorAll(".stage__value"),
    ).map((node) => node.textContent);
    expect(stageValues).toContain("not yet sent");
  });

  it("leaves a permanent record once a transfer is settled", () => {
    const { container } = render(
      <CustodyHeader transfer={makeTransfer({ status: "completed" })} />,
    );

    // The animation is for whoever was looking; this is for whoever was not.
    const stamp = container.querySelector(".custody__stamp");
    expect(stamp).not.toBeNull();
    expect(stamp).toHaveTextContent(/immutable/i);
  });
});
