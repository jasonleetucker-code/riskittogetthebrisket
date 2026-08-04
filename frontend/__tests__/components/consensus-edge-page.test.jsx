/**
 * /consensus-edge page — the states that must never blur.
 *
 * The page had no test file at all, which is how it came to render a
 * component the model deliberately ignores as an ordinary contributing
 * bar. Three distinctions are load-bearing and are each pinned here:
 *
 * - a component with a value that carries ZERO WEIGHT is not the same
 *   as one that contributes. Opportunity is exactly this since its
 *   composite backtest returned a null, and drawing it as a normal bar
 *   leaves a user unable to tell which number the score used.
 * - a component scored from SOME of its axes is not the same as one
 *   scored from all of them. A row carrying only `boardMomentumRisk`
 *   (clamped ≤ 0) drew an ordinary negative bar.
 * - a component with NO DATA is not the same as one measured and
 *   rejected; the banner said "has no data" for both.
 *
 * Also pinned: the Strong threshold comes from the payload, not a JSX
 * literal.
 */

import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import React from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import ConsensusEdgePage from "@/app/consensus-edge/page";

function jsonResponse(status, body) {
  return { ok: status >= 200 && status < 300, status, json: async () => body };
}

const VALIDATION = {
  mispricing: { validated: true, measured: true, outcome: "positive", note: "rho +0.126" },
  sharpFlow: { validated: false, measured: false, outcome: null, note: "no ledger" },
  opportunity: {
    validated: false,
    measured: true,
    outcome: "null",
    note: "measured and rejected; weight is zero",
  },
};

function playerRow(overrides = {}) {
  return {
    playerKey: "Bijan Robinson",
    displayName: "Bijan Robinson",
    position: "RB",
    assetClass: "offense",
    score: 42,
    label: "Buy",
    confidence: 61,
    qualified: true,
    components: { mispricing: 0.42, sharpFlow: null, opportunity: -0.6 },
    componentsAbsent: ["sharpFlow"],
    componentsZeroWeight: ["opportunity"],
    effectiveWeights: { mispricing: 1.0 },
    mispricing: { pctGap: 0.21, fairValue: 6000, marketValue: 5000 },
    opportunity: {
      score: -0.6,
      axes: [],
      absentAxes: ["snapTrend"],
      observedAxes: ["boardMomentumRisk"],
    },
    fairValue: 6000,
    marketValue: 5000,
    anchorKey: "ktcSfTep",
    explanation: [],
    ...overrides,
  };
}

const BOARD = {
  status: "ok",
  modelVersion: "ce.2026-08-04.v0-shadow",
  paramSetId: "abc123",
  players: [playerRow()],
  componentAvailability: {
    mispricing: { available: true, rowsWithValue: 700, weight: 0.5 },
    sharpFlow: {
      available: false,
      rowsWithValue: 0,
      weight: 0.3,
      unavailableReason: "no_data",
    },
    opportunity: {
      available: false,
      rowsWithValue: 740,
      weight: 0.0,
      unavailableReason: "zero_weight",
    },
  },
  confidenceCeiling: 69.34,
  strongLabelThreshold: 70,
  strongLabelsReachable: false,
  validationScope: { matchesMeasured: true, differences: [] },
  sellSideValidation: {
    validated: false,
    measured: true,
    outcome: "null",
    note: "Measured over 22 non-overlapping folds and found to carry nothing.",
  },
  inputs: { hoursStale: 8.3 },
};

function mockFetch(board = BOARD) {
  return vi.fn(async (url) => {
    if (String(url).includes("methodology")) {
      return jsonResponse(200, { components: VALIDATION });
    }
    return jsonResponse(200, board);
  });
}

// The board renders each player twice — once in the position-leaders
// strip and once in the main list — so every query here is explicitly
// plural. Using a singular query would fail on ambiguity rather than on
// the thing being tested.
async function openTheCard() {
  const cards = await screen.findAllByRole("button", { name: /Bijan Robinson/ });
  await userEvent.click(cards[0]);
}

describe("/consensus-edge page", () => {
  beforeEach(() => {
    global.fetch = mockFetch();
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders the board", async () => {
    render(<ConsensusEdgePage />);
    expect((await screen.findAllByText("Bijan Robinson")).length).toBeGreaterThan(0);
  });

  describe("a zero-weight component", () => {
    it("is marked as not counted", async () => {
      render(<ConsensusEdgePage />);
      await openTheCard();
      expect(screen.getAllByText(/not counted/i).length).toBeGreaterThan(0);
    });

    it("still shows its value, because the evidence is real", async () => {
      render(<ConsensusEdgePage />);
      await openTheCard();
      expect(screen.getAllByText("-0.60").length).toBeGreaterThan(0);
    });

    it("is not labelled merely 'unvalidated'", async () => {
      // "unvalidated" reads as "we have not checked". This component
      // WAS checked and did not earn a weight, which is a stronger
      // statement and must not be softened into the weaker one.
      render(<ConsensusEdgePage />);
      await openTheCard();
      const badges = screen.queryAllByText(/^\s*unvalidated\s*$/i);
      expect(badges.length).toBe(0);
    });
  });

  describe("partial evidence", () => {
    // Queried by tooltip, not by the words "partial evidence": the
    // availability banner legitimately uses that phrase about component
    // coverage, so a text query matches the wrong element and passes
    // for the wrong reason. The tooltip naming the missing axes is the
    // affordance under test.
    const BADGE = /No evidence for:/;

    it("is called out when some axes had no data", async () => {
      render(<ConsensusEdgePage />);
      await openTheCard();
      const badges = screen.getAllByTitle(BADGE);
      expect(badges.length).toBeGreaterThan(0);
      expect(badges[0].getAttribute("title")).toContain("snapTrend");
    });

    it("is absent when every axis was observed", async () => {
      const row = playerRow({
        opportunity: {
          score: -0.6,
          axes: [],
          absentAxes: [],
          observedAxes: ["boardMomentumRisk", "snapTrend"],
        },
      });
      global.fetch = mockFetch({ ...BOARD, players: [row] });
      render(<ConsensusEdgePage />);
      await openTheCard();
      expect(screen.queryAllByTitle(BADGE)).toHaveLength(0);
    });
  });

  describe("the availability banner", () => {
    it("distinguishes no-data from measured-and-rejected", async () => {
      render(<ConsensusEdgePage />);
      expect(await screen.findByText(/measured and carries no weight/i)).toBeTruthy();
      expect(screen.getByText(/has no data/i)).toBeTruthy();
    });

    it("names components in English, not camelCase keys", async () => {
      render(<ConsensusEdgePage />);
      const banner = await screen.findByText(/components are live/i);
      expect(banner.textContent).toContain("Sharp flow");
      expect(banner.textContent).not.toContain("sharpFlow");
    });

    it("takes the Strong threshold from the payload", async () => {
      global.fetch = mockFetch({ ...BOARD, strongLabelThreshold: 85 });
      render(<ConsensusEdgePage />);
      expect(await screen.findByText(/below the threshold of 85/)).toBeTruthy();
    });

    it("omits the threshold rather than inventing one when absent", async () => {
      const board = { ...BOARD };
      delete board.strongLabelThreshold;
      global.fetch = mockFetch(board);
      render(<ConsensusEdgePage />);
      expect(await screen.findByText(/confidence ceiling is/)).toBeTruthy();
      expect(screen.queryByText(/threshold of 70/)).toBeNull();
    });
  });

  describe("the sell side", () => {
    // Buys and sells share one control, which makes them look equally
    // grounded. They are not: the sell side was measured over 22 folds
    // and carries no edge, so the sells view has to say so where a user
    // is one click from acting on it.
    it("warns on the sells view", async () => {
      render(<ConsensusEdgePage />);
      await screen.findAllByText("Bijan Robinson");
      await userEvent.click(screen.getByRole("radio", { name: /sells/i }));
      expect(await screen.findByText(/not validated/i)).toBeTruthy();
    });

    it("does not warn on the buys view", async () => {
      render(<ConsensusEdgePage />);
      await screen.findAllByText("Bijan Robinson");
      expect(screen.queryByText(/These are not validated/i)).toBeNull();
    });

    it("stays quiet if the backend ever marks sells validated", async () => {
      global.fetch = mockFetch({
        ...BOARD,
        sellSideValidation: { validated: true, measured: true, outcome: "positive", note: "" },
      });
      render(<ConsensusEdgePage />);
      await screen.findAllByText("Bijan Robinson");
      await userEvent.click(screen.getByRole("radio", { name: /sells/i }));
      expect(screen.queryByText(/These are not validated/i)).toBeNull();
    });
  });

  describe("market value on the row", () => {
    // 91% of the top-20 is priced under 2000, so a user needs to see
    // what a player is worth before deciding a call is worth acting on
    // — without having to open the card.
    it("shows the market value in the collapsed header", async () => {
      render(<ConsensusEdgePage />);
      const cards = await screen.findAllByRole("button", { name: /Bijan Robinson/ });
      expect(cards[0].textContent).toContain("5,000");
    });
  });

  describe("validation scope", () => {
    it("says so when the board is off the measured configuration", async () => {
      global.fetch = mockFetch({
        ...BOARD,
        validationScope: {
          matchesMeasured: false,
          differences: ["league scoring fit is applied to fair value on this board"],
        },
      });
      render(<ConsensusEdgePage />);
      expect(
        await screen.findByText(/not running the configuration the published measurement/i),
      ).toBeTruthy();
    });

    it("stays quiet when the configurations match", async () => {
      render(<ConsensusEdgePage />);
      await screen.findAllByText("Bijan Robinson");
      expect(screen.queryByText(/not running the configuration/i)).toBeNull();
    });
  });
});
