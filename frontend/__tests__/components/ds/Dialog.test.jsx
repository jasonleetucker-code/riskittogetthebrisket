/**
 * Modal/Drawer spec — dialog semantics plus the re-render stability
 * regression: an inline onClose from a re-rendering parent must NOT
 * restart the open-lifecycle effect (which would steal focus from a
 * controlled input inside the dialog on every keystroke).
 */
import { describe, expect, it, vi } from "vitest";
import React, { useState } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Modal, Drawer } from "@/components/ds";

function ControlledInputHarness() {
  const [value, setValue] = useState("");
  return (
    // onClose is a NEW function identity on every parent render —
    // exactly what page code does with `onClose={() => setOpen(false)}`.
    <Modal open onClose={() => {}} title="Edit note">
      <input
        aria-label="Note"
        value={value}
        onChange={(e) => setValue(e.target.value)}
      />
    </Modal>
  );
}

describe("Dialog re-render stability", () => {
  it("a controlled input keeps focus and value across parent re-renders with an inline onClose", async () => {
    const user = userEvent.setup();
    render(<ControlledInputHarness />);
    const input = screen.getByLabelText("Note");
    await user.click(input);
    await user.keyboard("brisket");
    expect(input).toHaveValue("brisket");
    expect(input).toHaveFocus();
  });
});

describe("Dialog semantics", () => {
  it("renders role=dialog with aria-modal and a labelling title", () => {
    render(
      <Modal open onClose={() => {}} title="Confirm">
        body
      </Modal>
    );
    const dialog = screen.getByRole("dialog", { name: "Confirm" });
    expect(dialog).toHaveAttribute("aria-modal", "true");
  });

  it("Escape closes via the LATEST onClose callback", async () => {
    const user = userEvent.setup();
    const first = vi.fn();
    const second = vi.fn();
    const { rerender } = render(
      <Modal open onClose={first} title="T">
        body
      </Modal>
    );
    rerender(
      <Modal open onClose={second} title="T">
        body
      </Modal>
    );
    await user.keyboard("{Escape}");
    expect(first).not.toHaveBeenCalled();
    expect(second).toHaveBeenCalledTimes(1);
  });

  it("moves focus into the dialog on open and restores it on close", async () => {
    function Harness() {
      const [open, setOpen] = useState(false);
      return (
        <>
          <button type="button" onClick={() => setOpen(true)}>
            Open
          </button>
          <Drawer open={open} onClose={() => setOpen(false)} title="Player">
            <button type="button">Inside</button>
          </Drawer>
        </>
      );
    }
    const user = userEvent.setup();
    render(<Harness />);
    const opener = screen.getByRole("button", { name: "Open" });
    await user.click(opener);
    const dialog = screen.getByRole("dialog");
    expect(dialog.contains(document.activeElement)).toBe(true);
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(opener).toHaveFocus();
  });
});
