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

describe("Stacked overlays", () => {
  function StackHarness() {
    const [drawerOpen, setDrawerOpen] = useState(true);
    const [modalOpen, setModalOpen] = useState(true);
    return (
      <>
        <Drawer open={drawerOpen} onClose={() => setDrawerOpen(false)} title="Bottom">
          bottom
        </Drawer>
        <Modal open={modalOpen} onClose={() => setModalOpen(false)} title="Top">
          top
        </Modal>
      </>
    );
  }

  function NestedHarness() {
    // Modal rendered INSIDE the Drawer's children — React runs the
    // child's (Modal's) effect first, so registration order is inverted
    // vs visual stacking. Topmost-ness must come from document order.
    const [drawerOpen, setDrawerOpen] = useState(true);
    const [modalOpen, setModalOpen] = useState(true);
    return (
      <Drawer open={drawerOpen} onClose={() => setDrawerOpen(false)} title="Host drawer">
        drawer body
        <Modal open={modalOpen} onClose={() => setModalOpen(false)} title="Nested modal">
          modal body
        </Modal>
      </Drawer>
    );
  }

  it("NESTED composition: Escape closes the inner Modal first, not the host Drawer", async () => {
    const user = userEvent.setup();
    document.body.style.overflow = "";
    render(<NestedHarness />);
    expect(screen.getByRole("dialog", { name: "Host drawer" })).toBeInTheDocument();
    expect(screen.getByRole("dialog", { name: "Nested modal" })).toBeInTheDocument();
    expect(document.body.style.overflow).toBe("hidden");

    await user.keyboard("{Escape}");
    // the nested (visually topmost) Modal closes; the host Drawer survives
    expect(screen.queryByRole("dialog", { name: "Nested modal" })).toBeNull();
    expect(screen.getByRole("dialog", { name: "Host drawer" })).toBeInTheDocument();
    expect(document.body.style.overflow).toBe("hidden");

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.body.style.overflow).toBe("");
  });

  it("each overlay owns one root stacking context so a later overlay's backdrop covers earlier panels", () => {
    render(<StackHarness />);
    const roots = document.querySelectorAll(".ds-overlay-root");
    expect(roots).toHaveLength(2);
    const drawerPanel = screen.getByRole("dialog", { name: "Bottom" });
    const modalPanel = screen.getByRole("dialog", { name: "Top" });
    const [drawerRoot, modalRoot] = roots;
    // each root contains its own backdrop AND panel (one stacking context)
    expect(drawerRoot.querySelector(".ds-backdrop")).not.toBeNull();
    expect(modalRoot.querySelector(".ds-backdrop")).not.toBeNull();
    expect(drawerRoot.contains(drawerPanel)).toBe(true);
    expect(modalRoot.contains(modalPanel)).toBe(true);
    // the top overlay's backdrop FOLLOWS the lower panel in document
    // order — with equal-z sibling roots, that is the paint order, so
    // the covered Drawer sits under the Modal's backdrop
    const modalBackdrop = modalRoot.querySelector(".ds-backdrop");
    expect(
      drawerPanel.compareDocumentPosition(modalBackdrop) &
        Node.DOCUMENT_POSITION_FOLLOWING
    ).toBeTruthy();
  });

  it("one Escape closes only the topmost overlay; scroll lock releases only when all close", async () => {
    const user = userEvent.setup();
    document.body.style.overflow = "";
    render(<StackHarness />);
    expect(screen.getByRole("dialog", { name: "Bottom" })).toBeInTheDocument();
    expect(screen.getByRole("dialog", { name: "Top" })).toBeInTheDocument();
    expect(document.body.style.overflow).toBe("hidden");

    await user.keyboard("{Escape}");
    // only the top (Modal) closed; the Drawer beneath survives
    expect(screen.queryByRole("dialog", { name: "Top" })).toBeNull();
    expect(screen.getByRole("dialog", { name: "Bottom" })).toBeInTheDocument();
    // stack not empty → body stays locked
    expect(document.body.style.overflow).toBe("hidden");

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();
    // stack emptied → original overflow restored
    expect(document.body.style.overflow).toBe("");
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
