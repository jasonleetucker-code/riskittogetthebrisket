import React from "react";
import { describe, expect, it } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import DesignGallery from "@/app/design/DesignGallery";

// Real shared primitives, not mocks: this reference must preserve their APIs.
describe("PSI design reference", () => {
  it("fails closed for every unapproved chart preview without discarding fixture numbers", async () => {
    const user = userEvent.setup();
    const { container } = render(<DesignGallery />);
    expect(container.querySelectorAll(".ds-sparkline, .ds-meter")).toHaveLength(0);
    expect(screen.getByTestId("chart-preview-gate")).toHaveTextContent("9,541 / 10,000");
    expect(screen.getByTestId("chart-preview-gate")).toHaveTextContent("2,870 / 10,000");
    const table = screen.getByRole("table", { name: /Fixture value board/ });
    expect(within(table).getByLabelText("Justin Jefferson 6-week fixture values")).toHaveTextContent("92 → 93 → 95 → 94 → 96 → 97");
    await user.click(screen.getByRole("button", { name: "Open drawer" }));
    expect(document.querySelectorAll(".ds-sparkline, .ds-meter")).toHaveLength(0);
    await user.keyboard("{Escape}");
  });

  it("uses the approved scope and labels deterministic examples truthfully", () => {
    render(<DesignGallery />);
    expect(screen.getByTestId("psi-gallery")).toHaveClass("psi-editorial");
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
    expect(screen.getByText("Fixtures only")).toBeInTheDocument();
    expect(screen.getByText("Chart previews unavailable")).toBeInTheDocument();
    expect(screen.getByText("Personnel & market intelligence")).toBeInTheDocument();
    expect(screen.getByText("Value unavailable")).toBeInTheDocument();
    expect(screen.getByText("Partial coverage")).toBeInTheDocument();
    expect(screen.getByText("Actual zero")).toBeInTheDocument();
    expect(screen.queryByText(/franchise-gold|posts the offer to your league/)).toBeNull();
    // The shell owns main; a reference page must not introduce nested landmarks.
    expect(screen.queryByRole("main")).toBeNull();
  });

  it("retains complete fixture identity, sorting and density controls", async () => {
    const user = userEvent.setup();
    render(<DesignGallery />);
    const table = screen.getByRole("table", { name: /Fixture value board/ });
    expect(within(table).getAllByRole("row")).toHaveLength(6);
    expect(within(table).getByText("Justin Jefferson")).toBeInTheDocument();
    expect(within(table).getByText("Ja'Marr Chase")).toBeInTheDocument();
    expect(within(table).getByRole("columnheader", { name: "Value" })).toHaveAttribute("aria-sort", "descending");
    await user.click(within(table).getByRole("button", { name: "Value" }));
    expect(within(table).getByRole("columnheader", { name: "Value" })).toHaveAttribute("aria-sort", "ascending");
    await user.click(within(screen.getByRole("radiogroup", { name: "Density" })).getByRole("radio", { name: "Compact" }));
    expect(table).toHaveClass("ds-table--compact");
  });

  it("preserves modal keyboard closure and opener focus without a real trade action", async () => {
    const user = userEvent.setup();
    render(<DesignGallery />);
    const opener = screen.getByRole("button", { name: "Open modal" });
    await user.click(opener);
    const dialog = screen.getByRole("dialog", { name: "Trade proposal example" });
    expect(within(dialog).getByText("Demonstration only. No trade offer is sent or saved.")).toBeInTheDocument();
    expect(within(dialog).queryByRole("button", { name: "Send offer" })).toBeNull();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(opener).toHaveFocus();
  });

  it("keeps the player example and honest numeric drawer detail while chart acceptance is pending", async () => {
    const user = userEvent.setup();
    render(<DesignGallery />);
    const opener = screen.getByRole("button", { name: "Open drawer" });
    await user.click(opener);
    const dialog = screen.getByRole("dialog", { name: "Justin Jefferson" });
    expect(within(dialog).queryByRole("img", { name: "Jefferson 6-week value trend" })).toBeNull();
    expect(within(dialog).getByTestId("drawer-chart-gate")).toHaveTextContent("88 → 90 → 91 → 93 → 96 → 97");
    expect(within(dialog).getByText(/Chart preview unavailable/)).toBeInTheDocument();
    expect(within(dialog).getByText(/canonical Player File/)).toBeInTheDocument();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(opener).toHaveFocus();
  });
});
