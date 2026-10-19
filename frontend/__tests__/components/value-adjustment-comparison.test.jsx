/**
 * ValueAdjustmentComparison — the compact Chase Upside vs KTC-method entry
 * point in the decision area (owner directive 2026-10-19, part 2).  Display
 * only: every number comes from lib/va-comparison.js, which runs the ONE
 * package-model dispatch once per model.
 */
import { afterEach, describe, it, expect, vi } from "vitest";
import React from "react";
import { fireEvent, render, screen, within } from "@testing-library/react";

import ValueAdjustmentComparison from "@/components/trade/ValueAdjustmentComparison";
import { compareValueAdjustments } from "@/lib/va-comparison";

const LABELS = ["A", "B"];

afterEach(() => vi.restoreAllMocks());

describe("ValueAdjustmentComparison", () => {
  it("renders nothing until both sides hold an asset", () => {
    const { container } = render(
      <ValueAdjustmentComparison sideValues={[[9000], []]} sideLabels={LABELS} />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("agree: one plain sentence, both gaps, the calculation closed by default", () => {
    render(<ValueAdjustmentComparison sideValues={[[7200], [6000, 500]]} sideLabels={LABELS} />);
    const region = screen.getByRole("region", { name: "Value Adjustment comparison" });
    expect(region).toHaveAttribute("data-tone", "agree");
    expect(screen.getByTestId("va-comparison-summary")).toHaveTextContent(
      "Both methods agree: Side A's package is worth more after adjustment.",
    );
    expect(screen.getByTestId("va-comparison-gaps")).toHaveTextContent(
      "(Chase Upside adjustment) · Side A by 3,600 (KTC adjustment method)",
    );
    const toggle = screen.getByRole("button", { name: "Show the calculation" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByTestId("va-comparison-detail")).toBeNull();
  });

  it("the calculation shows each method's own adjustment and totals — no blending", () => {
    render(<ValueAdjustmentComparison sideValues={[[9000], [8200, 2000]]} sideLabels={LABELS} />);
    const toggle = screen.getByRole("button", { name: "Show the calculation" });
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    const detail = screen.getByTestId("va-comparison-detail");
    expect(toggle).toHaveAttribute("aria-controls", detail.id);
    expect(detail).toHaveTextContent("Before any adjustment: Side A 9,000 · Side B 10,200");
    const table = within(detail).getByRole("table");
    expect(
      within(table)
        .getAllByRole("columnheader")
        .map((h) => h.textContent),
    ).toEqual(["Measure", "Chase Upside adjustment (used)", "KTC adjustment method"]);
    const cmp = compareValueAdjustments([[9000], [8200, 2000]]);
    const rowText = (label) =>
      within(table)
        .getByRole("rowheader", { name: label })
        .closest("tr")
        .textContent.replace(label, "");
    expect(rowText("Adjustment to Side A")).toBe(
      `+${cmp.active.adjustments[0].toLocaleString("en-US")}+${cmp.comparator.adjustments[0].toLocaleString("en-US")}`,
    );
    expect(rowText("Adjustment to Side B")).toBe("NoneNone");
    expect(rowText("More adjusted value")).toBe("Side BSide A");
    expect(rowText("Gap (Side A minus Side B)")).toBe("−760+1,020");
    // A neutral share of the larger side — never the headline's verdict words
    // in the comparator column (it must not read like a second verdict).
    const pct = (ev) => `${ev.relativeGapPct.toFixed(1)}%${ev.nearEven ? " · near even" : ""}`;
    expect(rowText("Gap, % of the larger side")).toBe(pct(cmp.active) + pct(cmp.comparator));
    expect(table.textContent).not.toMatch(/Major gap|Strong lean|Lean|Near even|Fairness band/);
    // The disagreement is said once, with the method the decision uses.
    expect(screen.getByTestId("va-comparison-summary")).toHaveTextContent(
      "The methods disagree. Chase Upside adjustment: Side B's package is worth more. KTC adjustment method: Side A's package is worth more. The recommendation uses Chase Upside's.",
    );
    // KTC method = the formula on OUR values, never KTC-native values.
    expect(detail).toHaveTextContent("applied here to Chase Upside values");
    expect(detail).toHaveTextContent("These are not KTC's own player values.");
    expect(detail).toHaveTextContent("never added together, averaged");
    fireEvent.click(toggle);
    expect(screen.queryByTestId("va-comparison-detail")).toBeNull();
  });

  it("near even under both but different sides ahead: said in words, never 'agree'", () => {
    render(
      <ValueAdjustmentComparison
        sideValues={[
          [1378, 5343, 6310],
          [5741, 3842, 4641],
        ]}
        sideLabels={LABELS}
      />,
    );
    expect(screen.getByTestId("va-comparison")).toHaveAttribute("data-tone", "split");
    expect(screen.getByTestId("va-comparison-summary")).toHaveTextContent(
      "Both methods call it near even, but they differ on which side is slightly ahead.",
    );
    expect(screen.getByTestId("va-comparison-gaps")).toHaveTextContent(
      "Side B by 383 (Chase Upside adjustment) · Side A by 478 (KTC adjustment method)",
    );
  });

  it("one-for-one: explains no adjustment under either method instead of duplicate numbers", () => {
    render(<ValueAdjustmentComparison sideValues={[[7200], [6000]]} sideLabels={LABELS} />);
    expect(screen.getByTestId("va-comparison-summary")).toHaveTextContent(
      "No package adjustment under either method: a one-for-one trade carries none.",
    );
    expect(screen.queryByTestId("va-comparison-gaps")).toBeNull();
    expect(screen.queryByRole("button")).toBeNull();
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("unavailable when a piece has no value — never a 0", () => {
    render(<ValueAdjustmentComparison sideValues={[[9000, null], [8200]]} sideLabels={LABELS} />);
    expect(screen.getByTestId("va-comparison-summary")).toHaveTextContent(
      "Adjustment comparison unavailable: 1 piece has no Chase Upside value (unknown, not 0).",
    );
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("3+ teams: the honest two-team limit, no fabricated comparator", () => {
    render(
      <ValueAdjustmentComparison
        sideValues={[[9000], [8200], [3000, 2000]]}
        sideLabels={["A", "B", "C"]}
      />,
    );
    expect(screen.getByTestId("va-comparison")).toHaveAttribute("data-tone", "multi");
    expect(screen.getByTestId("va-comparison-summary")).toHaveTextContent(
      "the KTC adjustment method is not extended",
    );
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("says when the user's typed overrides are not in these numbers", () => {
    render(
      <ValueAdjustmentComparison
        sideValues={[[7200], [6000, 500]]}
        sideLabels={LABELS}
        hasOverrides
      />,
    );
    expect(screen.getByTestId("va-comparison-override-note")).toHaveTextContent(
      "your typed overrides change the headline only",
    );
  });

  it("asks the server nothing: it cannot reach the official decision", () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockImplementation(() => {
      throw new Error("the comparison must not fetch");
    });
    render(<ValueAdjustmentComparison sideValues={[[9000], [8200, 2000]]} sideLabels={LABELS} />);
    fireEvent.click(screen.getByRole("button", { name: "Show the calculation" }));
    fireEvent.click(screen.getByRole("button", { name: "Hide the calculation" }));
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("compact={false} starts with the calculation open", () => {
    render(
      <ValueAdjustmentComparison
        sideValues={[[7200], [6000, 500]]}
        sideLabels={LABELS}
        compact={false}
      />,
    );
    expect(screen.getByTestId("va-comparison-detail")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Hide the calculation" })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
    // The table is a named, keyboard-reachable scroll region on a phone.
    expect(screen.getByRole("region", { name: "Value Adjustment calculation" })).toHaveAttribute(
      "tabindex",
      "0",
    );
  });
});
