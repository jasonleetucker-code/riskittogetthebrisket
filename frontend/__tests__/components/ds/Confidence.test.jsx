/**
 * Confidence — the standalone confidence affordance (WS-J §3).
 *
 * The behaviour worth pinning is not "it renders three ticks"; it is the
 * QUIET-BY-DEFAULT rule. Confidence markers are only informative if they
 * are rare, so a confident value must render nothing at all. If that
 * regresses, the failure is invisible in code review (every value simply
 * grows a marker) and it silently reintroduces the wall of caveats the
 * component exists to prevent.
 */
import React from "react";
import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { Confidence } from "../../../components/ds/Badge";

describe("Confidence", () => {
  describe("quiet by default", () => {
    it("renders NOTHING for a high-confidence value", () => {
      const { container } = render(<Confidence confidence={0.9} />);
      expect(container).toBeEmptyDOMElement();
    });

    it("renders for medium confidence", () => {
      render(<Confidence confidence={0.5} />);
      expect(screen.getByRole("img")).toHaveAccessibleName(
        /medium confidence/i,
      );
    });

    it("renders for low confidence", () => {
      render(<Confidence confidence={0.1} />);
      expect(screen.getByRole("img")).toHaveAccessibleName(/low confidence/i);
    });

    it("renders zero confidence rather than treating it as absent", () => {
      // 0 is a real statement ("we have no confidence"), not a missing
      // value. A falsy-check bug here would silently drop the strongest
      // caveat on the page.
      render(<Confidence confidence={0} />);
      expect(screen.getByRole("img")).toHaveAccessibleName(/no confidence/i);
    });
  });

  describe("absent vs. known-zero", () => {
    it.each([
      ["undefined", undefined],
      ["null", null],
      ["NaN", NaN],
    ])("renders nothing when confidence is %s", (_label, value) => {
      const { container } = render(<Confidence confidence={value} />);
      expect(container).toBeEmptyDOMElement();
    });
  });

  describe("showWhen=always", () => {
    it("renders a high-confidence value when explicitly asked", () => {
      render(<Confidence confidence={0.9} showWhen="always" />);
      expect(screen.getByRole("img")).toHaveAccessibleName(/high confidence/i);
    });

    it("still renders nothing when confidence is unknown", () => {
      // "always" overrides the quiet rule, not the honesty rule.
      const { container } = render(
        <Confidence confidence={null} showWhen="always" />,
      );
      expect(container).toBeEmptyDOMElement();
    });
  });

  describe("ticks", () => {
    it.each([
      [0, 0],
      [0.1, 1],
      [0.5, 2],
      [0.9, 3],
    ])("fills %s -> %i ticks", (confidence, expected) => {
      const { container } = render(
        <Confidence confidence={confidence} showWhen="always" />,
      );
      expect(container.querySelectorAll(".ds-confidence__tick")).toHaveLength(
        3,
      );
      expect(
        container.querySelectorAll(".ds-confidence__tick--on"),
      ).toHaveLength(expected);
    });

    it("hides the glyphs from assistive tech", () => {
      const { container } = render(<Confidence confidence={0.5} />);
      expect(container.querySelector(".ds-confidence__ticks")).toHaveAttribute(
        "aria-hidden",
        "true",
      );
    });

    it("clamps out-of-range input instead of overfilling", () => {
      const { container } = render(
        <Confidence confidence={5} showWhen="always" />,
      );
      expect(
        container.querySelectorAll(".ds-confidence__tick--on"),
      ).toHaveLength(3);
    });
  });

  describe("the binding constraint", () => {
    it("names ONE limiting dimension in the announced label", () => {
      render(<Confidence confidence={0.2} limitedBy="role" />);
      expect(screen.getByRole("img")).toHaveAccessibleName(
        "low confidence, limited by role",
      );
    });

    it("omits the clause when no constraint is supplied", () => {
      render(<Confidence confidence={0.2} />);
      expect(screen.getByRole("img")).toHaveAccessibleName("low confidence");
    });

    it("lets srLabel replace the whole sentence", () => {
      render(<Confidence confidence={0.2} srLabel="thin sample" />);
      expect(screen.getByRole("img")).toHaveAccessibleName("thin sample");
    });
  });

  describe("not a status", () => {
    it("carries no positive/negative/warning tone class", () => {
      // Confidence must never borrow the reserved status palette: low
      // confidence means thin evidence, not a bad outcome.
      const { container } = render(
        <Confidence confidence={0.1} showWhen="always" />,
      );
      const el = container.querySelector(".ds-confidence");
      expect(el.className).not.toMatch(/positive|negative|warning|danger/);
    });
  });

  it("forwards className and arbitrary props", () => {
    render(<Confidence confidence={0.5} className="mine" data-testid="c" />);
    expect(screen.getByTestId("c")).toHaveClass("ds-confidence", "mine");
  });
});
