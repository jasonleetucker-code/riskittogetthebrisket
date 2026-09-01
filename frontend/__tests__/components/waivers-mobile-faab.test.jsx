/**
 * `WaiverBidFigure` — the ONE renderer for a backend-stamped FAAB bid
 * on /waivers, used by both the desktop column and the phone's inline
 * chip.
 *
 * RED-FIRST, against `2bb62b996`. The component does not exist there;
 * the board's bid lived only in a `hideBelow: "md"` column, so a phone
 * got no bid at all.
 *
 * One renderer, deliberately: two copies of "how do we print a bid"
 * is how the desktop and mobile boards would come to disagree about a
 * dollar figure — the same class of defect as the compact-view parity
 * break (`F-13`), where mobile and desktop rendered different numbers
 * for the same player.
 *
 * It renders. It does not compute. Every figure here arrives from
 * `src/trade/faab_engine.py` via `/api/waiver/suggestions`.
 */
import { describe, it, expect } from "vitest";
import React from "react";
import { render, screen, within } from "@testing-library/react";
import WaiverBidFigure from "@/components/waivers/WaiverBidFigure";
import { waiverBidStateForRow, buildWaiverBidIndex } from "@/lib/waiver-faab";

const PRICED = {
  state: "priced",
  bid: {
    reasonable: 15,
    aggressive: 22,
    lowball: 8,
    clearing: 12,
    clearingLow: 9,
    clearingHigh: 18,
    maxRational: 40,
    objectiveDollars: 55,
    confidence: "medium",
  },
  label: "$15",
  reason: "",
};

describe("WaiverBidFigure — priced", () => {
  it("headlines the backend's reasonable figure verbatim", () => {
    render(<WaiverBidFigure entry={PRICED} />);
    expect(screen.getByTestId("waiver-bid-figure")).toHaveTextContent("$15");
  });

  it("does not round, scale or otherwise move the number", () => {
    render(
      <WaiverBidFigure
        entry={{ ...PRICED, bid: { reasonable: 37, aggressive: 53, lowball: 19 } }}
      />,
    );
    expect(screen.getByTestId("waiver-bid-figure")).toHaveTextContent("$37");
  });

  it("renders a real zero as $0, not as an absence", () => {
    // Roughly half this league's real adds cost exactly $0 — see the
    // `bid_range` docstring in src/trade/waiver.py on why the $1 floor
    // was deliberately not carried over. $0 is an answer.
    render(
      <WaiverBidFigure
        entry={{ ...PRICED, bid: { reasonable: 0, aggressive: 0, lowball: 0 } }}
      />,
    );
    const el = screen.getByTestId("waiver-bid-figure");
    expect(el).toHaveTextContent("$0");
    expect(el.textContent).not.toContain("—");
  });

  it("carries the expected-clearing band and max-rational bid as supporting detail — not the retired lowball/aggressive ladder", () => {
    render(<WaiverBidFigure entry={PRICED} />);
    const detail = screen.getByTestId("waiver-bid-detail").textContent;
    expect(detail).toMatch(/clearing/i);
    expect(detail).toContain("9");
    expect(detail).toContain("18");
    expect(detail).toMatch(/max i'?d pay/i);
    expect(detail).toContain("40");
    // The retired ladder must not survive under a new label.
    expect(detail).not.toMatch(/lowball/i);
    expect(detail).not.toMatch(/aggressive/i);
  });

  it("falls back to the bare headline (no detail line) when the market-aware fields are absent", () => {
    // Older cached payload shape, or a transitional deploy where the
    // backend hasn't shipped the new per-candidate fields yet — must
    // never render half-built punctuation.
    render(
      <WaiverBidFigure
        entry={{ ...PRICED, bid: { reasonable: 15, aggressive: 22, lowball: 8 } }}
      />,
    );
    expect(screen.getByTestId("waiver-bid-figure")).toHaveTextContent("$15");
    expect(screen.queryByTestId("waiver-bid-detail")).toBeNull();
  });
});

describe("WaiverBidFigure — absent, with a reason", () => {
  // Entries come from the REAL resolver, not from strings invented
  // here. A fixture that makes up its own copy agrees with the test
  // and with nothing else — which is how a frontend defect on this
  // repo's last lane survived a green suite.
  const index = buildWaiverBidIndex({
    by_position: {
      WR: [
        {
          name: "Unpriced Guy",
          position: "WR",
          consensusValue: 400,
          bid: null,
        },
        { name: "Priced Guy", position: "WR", consensusValue: 3000, bid: { aggressive: 9, reasonable: 6, lowball: 3 } },
      ],
      DL: [{ name: "Two Ways", position: "DE", consensusValue: 900, bid: { aggressive: 4, reasonable: 3, lowball: 1 } }],
      TE: [{ name: "Two Ways", position: "TE", consensusValue: 800, bid: { aggressive: 3, reasonable: 2, lowball: 1 } }],
    },
  });

  const cases = [
    ["unavailable", waiverBidStateForRow(null, { name: "Priced Guy", pos: "WR" })],
    ["unpriced", waiverBidStateForRow(index, { name: "Unpriced Guy", pos: "WR" })],
    ["ambiguous", waiverBidStateForRow(index, { name: "Two Ways", pos: null })],
  ];

  for (const [state, entry] of cases) {
    it(`"${state}" states its reason instead of a bare dash`, () => {
      expect(entry.state, "resolver did not produce the state under test").toBe(state);
      render(<WaiverBidFigure entry={entry} />);
      const el = screen.getByTestId("waiver-bid-figure");
      expect(el.textContent.trim()).not.toBe("—");
      expect(el.textContent.trim().length).toBeGreaterThan(1);
      expect(el.dataset.state).toBe(state);
      // The explanation is reachable, not merely implied by a glyph,
      // and it is the resolver's own words.
      expect(el.getAttribute("title")).toBe(entry.reason);
      expect(el.getAttribute("title").length).toBeGreaterThan(20);
    });
  }

  it("never prints a dollar sign when there is no bid", () => {
    render(
      <WaiverBidFigure
        entry={waiverBidStateForRow(buildWaiverBidIndex({
          by_position: { WR: [{ name: "Priced Guy", position: "WR", bid: { aggressive: 9, reasonable: 6, lowball: 3 } }] },
        }), { name: "Nobody", pos: "RB" })}
      />,
    );
    expect(screen.getByTestId("waiver-bid-figure").textContent).not.toContain("$");
    expect(screen.queryByTestId("waiver-bid-detail")).toBeNull();
  });
});

describe("the phone surface sits beside the recommendation", () => {
  it("the inline variant is labelled so it reads as a bid, not a value", () => {
    // Three quantities live on this page and must stay distinct
    // (`docs/faab-model.md`): what the player is WORTH (the board's
    // Value column / objective ceiling), what you should BID, and the
    // posture that shapes the bid desk's recommendation. A naked "$15"
    // beside a player's name would read as the first.
    render(<WaiverBidFigure entry={PRICED} inline />);
    const el = screen.getByTestId("waiver-bid-figure");
    expect(el.textContent).toMatch(/FAAB|bid/i);
    expect(el.className).toMatch(/faabInline/);
  });

  it("the desktop variant carries no inline class", () => {
    render(<WaiverBidFigure entry={PRICED} />);
    expect(screen.getByTestId("waiver-bid-figure").className).not.toMatch(/faabInline/);
  });
});
