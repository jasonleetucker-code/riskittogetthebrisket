/**
 * InfoTip / HelpModal spec.
 *
 * These carry explanation moved out of permanent page prose, so the
 * bar is higher than for a decorative hint: every pointer type must be
 * able to open them, and a screen reader must hear what the button is
 * for before activating it.  The pattern they replace — 650 native
 * `title=` attributes — satisfies neither.
 */
import { describe, expect, it, vi } from "vitest";
import React from "react";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { HelpModal, InfoTip } from "@/components/ds";

describe("InfoTip", () => {
  it("is closed initially and opens on click", async () => {
    const user = userEvent.setup();
    render(<InfoTip label="Fund gap">Fundamental minus market.</InfoTip>);
    const trigger = screen.getByRole("button", { name: "What is Fund gap?" });
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText("Fundamental minus market.")).toBeNull();

    await user.click(trigger);
    expect(trigger).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("Fundamental minus market.")).toBeInTheDocument();
  });

  it("names the topic in the trigger, not just an icon", async () => {
    // "button, i" tells a screen-reader user nothing about which of the
    // eight info icons on the page they just landed on.
    render(<InfoTip label="source spread">…</InfoTip>);
    expect(screen.getByRole("button", { name: "What is source spread?" })).toBeInTheDocument();
  });

  it("exposes the popover as a region labelled by the topic", async () => {
    const user = userEvent.setup();
    render(<InfoTip label="Tier gap">Where the cliffs are.</InfoTip>);
    await user.click(screen.getByRole("button", { name: /Tier gap/ }));
    const region = screen.getByRole("region", { name: "Tier gap" });
    expect(within(region).getByText("Where the cliffs are.")).toBeInTheDocument();
  });

  it("wires aria-controls to the popover only while open", async () => {
    const user = userEvent.setup();
    render(<InfoTip label="Confidence">Bucket rules.</InfoTip>);
    const trigger = screen.getByRole("button", { name: /Confidence/ });
    expect(trigger).not.toHaveAttribute("aria-controls");
    await user.click(trigger);
    const id = trigger.getAttribute("aria-controls");
    expect(id).toBeTruthy();
    expect(document.getElementById(id)).toBeInTheDocument();
  });

  it("toggles shut on a second click", async () => {
    const user = userEvent.setup();
    render(<InfoTip label="Spread">Body.</InfoTip>);
    const trigger = screen.getByRole("button", { name: /Spread/ });
    await user.click(trigger);
    await user.click(trigger);
    expect(screen.queryByText("Body.")).toBeNull();
  });

  it("closes on Escape and returns focus to the trigger", async () => {
    const user = userEvent.setup();
    render(<InfoTip label="Spread">Body.</InfoTip>);
    const trigger = screen.getByRole("button", { name: /Spread/ });
    await user.click(trigger);
    await user.keyboard("{Escape}");
    expect(screen.queryByText("Body.")).toBeNull();
    expect(trigger).toHaveFocus();
  });

  it("closes on an outside click", async () => {
    const user = userEvent.setup();
    render(
      <div>
        <InfoTip label="Spread">Body.</InfoTip>
        <button type="button">elsewhere</button>
      </div>,
    );
    await user.click(screen.getByRole("button", { name: /Spread/ }));
    await user.click(screen.getByRole("button", { name: "elsewhere" }));
    expect(screen.queryByText("Body.")).toBeNull();
  });

  it("stays open when the popover's own content is clicked", async () => {
    // The copy moved into these sometimes carries a link; clicking
    // inside must not dismiss it out from under the pointer.
    const user = userEvent.setup();
    render(
      <InfoTip label="Sources">
        <a href="/settings">Adjust weights</a>
      </InfoTip>,
    );
    await user.click(screen.getByRole("button", { name: /Sources/ }));
    await user.click(screen.getByRole("link", { name: "Adjust weights" }));
    expect(screen.getByRole("link", { name: "Adjust weights" })).toBeInTheDocument();
  });

  it("is reachable and operable by keyboard alone", async () => {
    const user = userEvent.setup();
    render(<InfoTip label="Spread">Body.</InfoTip>);
    await user.tab();
    const trigger = screen.getByRole("button", { name: /Spread/ });
    expect(trigger).toHaveFocus();
    await user.keyboard("{Enter}");
    expect(screen.getByText("Body.")).toBeInTheDocument();
  });
});

describe("HelpModal", () => {
  it("renders a labelled trigger and opens a dialog", async () => {
    const user = userEvent.setup();
    render(
      <HelpModal title="How rankings work">
        <p>Blend, then curve.</p>
      </HelpModal>,
    );
    const trigger = screen.getByRole("button", { name: /How this works/ });
    expect(screen.queryByRole("dialog")).toBeNull();
    await user.click(trigger);
    const dialog = screen.getByRole("dialog", { name: "How rankings work" });
    expect(within(dialog).getByText("Blend, then curve.")).toBeInTheDocument();
  });

  it("accepts a custom trigger label", async () => {
    render(
      <HelpModal title="Draft glossary" label="How this dashboard works">
        <p>…</p>
      </HelpModal>,
    );
    expect(
      screen.getByRole("button", { name: /How this dashboard works/ }),
    ).toBeInTheDocument();
  });

  it("closes on Escape", async () => {
    const user = userEvent.setup();
    render(
      <HelpModal title="How rankings work">
        <p>Blend, then curve.</p>
      </HelpModal>,
    );
    await user.click(screen.getByRole("button", { name: /How this works/ }));
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});
