/**
 * Badge / StatusIndicator / Movement semantics spec.
 * Movement is the system's market-signal language: direction must never
 * be color-alone (SVG arrow), magnitude is formatted, confidence buckets
 * into 0-3 ticks, and the whole cluster is one labelled image for AT.
 */
import { describe, expect, it } from "vitest";
import React from "react";
import { render, screen } from "@testing-library/react";
import {
  Badge,
  StatusIndicator,
  Movement,
  confidenceBucket,
} from "@/components/ds";

describe("Badge", () => {
  it("defaults to the neutral tone", () => {
    render(<Badge>WR</Badge>);
    expect(screen.getByText("WR")).toHaveClass("ds-badge--neutral");
  });

  it.each(["accent", "positive", "negative", "warning", "info", "outline"])(
    "applies the %s tone class",
    (tone) => {
      render(<Badge tone={tone}>x</Badge>);
      expect(screen.getByText("x")).toHaveClass(`ds-badge--${tone}`);
    }
  );
});

describe("StatusIndicator", () => {
  it("never relies on color alone — label text is rendered", () => {
    render(<StatusIndicator status="warning">DLF stale</StatusIndicator>);
    expect(screen.getByText("DLF stale")).toBeInTheDocument();
  });

  it("renders a decorative dot with the status class", () => {
    const { container } = render(
      <StatusIndicator status="positive">Fresh</StatusIndicator>
    );
    const dot = container.querySelector(".ds-status-dot");
    expect(dot).toHaveClass("ds-status-dot--positive");
    expect(dot).toHaveAttribute("aria-hidden", "true");
  });
});

describe("confidenceBucket", () => {
  it("buckets 0..1 into 0-3 ticks", () => {
    expect(confidenceBucket(0)).toBe(0);
    expect(confidenceBucket(0.2)).toBe(1);
    expect(confidenceBucket(0.5)).toBe(2);
    expect(confidenceBucket(0.9)).toBe(3);
    expect(confidenceBucket(1)).toBe(3);
  });

  it("clamps out-of-range and rejects non-numbers", () => {
    expect(confidenceBucket(4)).toBe(3);
    expect(confidenceBucket(-1)).toBe(0);
    expect(confidenceBucket(null)).toBeNull();
    expect(confidenceBucket(undefined)).toBeNull();
    expect(confidenceBucket(NaN)).toBeNull();
  });
});

describe("Movement", () => {
  it("positive delta: up direction, magnitude shown unsigned, labelled for AT", () => {
    render(<Movement delta={340} />);
    const el = screen.getByRole("img", { name: "up 340" });
    expect(el).toHaveClass("ds-movement--up");
    expect(el).toHaveTextContent("340");
    expect(el).not.toHaveTextContent("-");
  });

  it("negative delta: down direction with magnitude in the label", () => {
    render(<Movement delta={-128} />);
    expect(
      screen.getByRole("img", { name: "down 128" })
    ).toHaveClass("ds-movement--down");
  });

  it("zero delta reads as unchanged, styled flat", () => {
    render(<Movement delta={0} />);
    expect(screen.getByRole("img", { name: "unchanged" })).toHaveClass(
      "ds-movement--flat"
    );
  });

  it("direction is carried by an svg arrow, not color alone", () => {
    const { container } = render(<Movement delta={12} />);
    expect(container.querySelector("svg.ds-movement__arrow")).not.toBeNull();
  });

  it("confidence renders ticks and joins the accessible label", () => {
    const { container } = render(<Movement delta={62} confidence={0.9} />);
    expect(
      screen.getByRole("img", { name: "up 62, high confidence" })
    ).toBeInTheDocument();
    const on = container.querySelectorAll(".ds-movement__tick--on");
    expect(on).toHaveLength(3);
    expect(container.querySelectorAll(".ds-movement__tick")).toHaveLength(3);
  });

  it("low confidence lights one tick and says so", () => {
    const { container } = render(<Movement delta={10} confidence={0.2} />);
    expect(
      screen.getByRole("img", { name: "up 10, low confidence" })
    ).toBeInTheDocument();
    expect(container.querySelectorAll(".ds-movement__tick--on")).toHaveLength(1);
  });

  it("omits ticks entirely when confidence is not provided", () => {
    const { container } = render(<Movement delta={10} />);
    expect(container.querySelector(".ds-movement__ticks")).toBeNull();
  });

  it("accepts a custom magnitude formatter", () => {
    render(<Movement delta={-1234.5} format={(n) => `${n / 1000}k`} />);
    expect(screen.getByRole("img", { name: "down 1.2345k" })).toBeInTheDocument();
  });

  it("custom formatters receive the MAGNITUDE, never the sign (no double negation)", () => {
    // a sign-naive percent formatter must yield "down 5%", not "down -5%"
    render(<Movement delta={-5} format={(n) => `${n}%`} />);
    const el = screen.getByRole("img", { name: "down 5%" });
    expect(el).toHaveTextContent("5%");
    expect(el).not.toHaveTextContent("-5%");
  });
});
