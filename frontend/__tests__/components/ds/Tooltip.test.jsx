/**
 * Tooltip spec — describedby wiring must MERGE with any existing
 * aria-describedby on the wrapped control (e.g. a Field hint/error)
 * while open, and restore the original value on close.
 */
import { describe, expect, it } from "vitest";
import React from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Tooltip } from "@/components/ds";

describe("Tooltip aria-describedby", () => {
  it("merges with the child's existing aria-describedby while open and restores it on close", async () => {
    const user = userEvent.setup();
    render(
      <>
        <Tooltip content="Extra context">
          <button type="button" aria-describedby="field-hint">
            Value
          </button>
        </Tooltip>
        <span id="field-hint">Whole dollars</span>
      </>
    );
    const trigger = screen.getByRole("button", { name: "Value" });
    expect(trigger).toHaveAttribute("aria-describedby", "field-hint");

    await user.hover(trigger);
    const tooltip = screen.getByRole("tooltip");
    const merged = trigger.getAttribute("aria-describedby").split(" ");
    expect(merged[0]).toBe("field-hint"); // existing guidance kept, first
    expect(merged[1]).toBe(tooltip.id); // tooltip appended
    expect(merged).toHaveLength(2);

    await user.unhover(trigger);
    expect(trigger).toHaveAttribute("aria-describedby", "field-hint");
  });

  it("uses only the tooltip id when the child had no describedby, and clears it on close", async () => {
    const user = userEvent.setup();
    render(
      <Tooltip content="Info">
        <button type="button">Trigger</button>
      </Tooltip>
    );
    const trigger = screen.getByRole("button", { name: "Trigger" });
    expect(trigger).not.toHaveAttribute("aria-describedby");
    await user.hover(trigger);
    expect(trigger).toHaveAttribute(
      "aria-describedby",
      screen.getByRole("tooltip").id
    );
    await user.unhover(trigger);
    expect(trigger).not.toHaveAttribute("aria-describedby");
  });

  it("shows on keyboard focus and hides on Escape", async () => {
    const user = userEvent.setup();
    render(
      <Tooltip content="Info">
        <button type="button">Trigger</button>
      </Tooltip>
    );
    await user.tab();
    expect(screen.getByRole("tooltip")).toBeInTheDocument();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("tooltip")).toBeNull();
  });
});
