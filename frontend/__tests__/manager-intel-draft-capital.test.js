import { describe, expect, it } from "vitest";
import {
  capitalCountsText,
  capitalValueText,
  coverageProblems,
  draftCapitalLeagues,
  draftYearsText,
  pickMovementRows,
  pickOriginText,
  pickOwnershipText,
  shapeLabel,
  shapeRows,
  stillHeldText,
  tendencyFlowText,
  tendencySampleText,
} from "@/lib/manager-intel";
import {
  ACTIVITY,
  DRAFT_CAPITAL,
  TENDENCIES,
} from "./fixtures/manager-intel-activity";

const [ALPHA, BETA] = DRAFT_CAPITAL.leagues;

describe("draft capital helpers (Batch B3)", () => {
  it("filters league entries and movement rows", () => {
    expect(draftCapitalLeagues(DRAFT_CAPITAL)).toHaveLength(2);
    expect(
      draftCapitalLeagues(DRAFT_CAPITAL, "L2").map((e) => e.leagueId),
    ).toEqual(["L2"]);
    expect(draftCapitalLeagues(null)).toEqual([]);
    expect(pickMovementRows(DRAFT_CAPITAL, "L1")).toHaveLength(1);
    expect(pickMovementRows(DRAFT_CAPITAL, "L2")).toEqual([]);
  });

  it("reads unknown ownership through the one pick-ownership reader", () => {
    expect(pickOwnershipText(ALPHA)).toBe("");
    expect(pickOwnershipText(BETA)).toMatch(/rate-limited/);
    expect(pickOwnershipText({ ...BETA, coverage: "unavailable" })).toMatch(
      /traded-picks feed could not be read/,
    );
    expect(pickOwnershipText({ ...BETA, coverage: "none" })).toMatch(
      /budget reached/,
    );
    expect(
      pickOwnershipText({
        ...BETA,
        pickOwnershipReason: "rosters_unavailable",
      }),
    ).toMatch(/rosters could not be read/);
    // An unknown league is never rendered as "owns no picks".
    expect(capitalValueText(BETA)).toBe("—");
    expect(capitalCountsText(BETA)).toBe("");
  });

  it("labels origin, counts, priced-only totals and covered classes", () => {
    expect(pickOriginText(ALPHA.picks[0])).toBe("Own");
    expect(pickOriginText(ALPHA.picks[1])).toBe("From Rival Two");
    expect(
      pickOriginText({ own: false, originOwnerName: null, originRosterId: 7 }),
    ).toBe("From roster 7");
    expect(capitalCountsText(ALPHA)).toBe(
      "3 held · 1 acquired · 1 own traded away",
    );
    expect(capitalValueText(ALPHA)).toBe("7,000 · 1 unpriced");
    expect(capitalValueText({ ...ALPHA, unpricedPickCount: 0 })).toBe("7,000");
    expect(
      capitalValueText({
        ...ALPHA,
        picks: [],
        pricedValue: 0,
        unpricedPickCount: 0,
      }),
    ).toBe("0");
    expect(draftYearsText(ALPHA.draftYears)).toBe(
      "2027–2028 · 2026 draft complete",
    );
    expect(
      draftYearsText({
        heldSeasons: [2027],
        retiredSeasons: [],
        draftCompleteSeasons: [],
      }),
    ).toBe("2027");
    expect(draftYearsText({ heldSeasons: [] })).toBe("No upcoming classes");
  });

  it("says whether a moved pick is still held, or that it cannot say", () => {
    expect(stillHeldText({ stillHeld: true })).toBe("Still held");
    expect(stillHeldText({ stillHeld: false })).toBe("No longer held");
    expect(
      stillHeldText({
        stillHeld: null,
        stillHeldReason: "class_not_in_owned_horizon",
      }),
    ).toMatch(/drafted/);
    expect(
      stillHeldText({
        stillHeld: null,
        stillHeldReason: "pick_ownership_unavailable",
      }),
    ).toBe("Unknown");
  });

  it("names a traded-picks gap in the coverage problems only when served", () => {
    const activity = {
      ...ACTIVITY,
      coverage: {
        leagues: [
          {
            leagueId: "L9",
            name: "Gamma",
            rosterHeld: true,
            transactions: "complete",
            drafts: "complete",
            tradedPicks: "rate_limited",
          },
        ],
      },
    };
    expect(coverageProblems(activity)).toEqual([
      { leagueId: "L9", name: "Gamma", text: "traded picks rate-limited" },
    ]);
    expect(
      coverageProblems({
        ...activity,
        draftCapital: { available: false, reason: "earlier_season" },
      }),
    ).toEqual([]);
  });
});

describe("tendency helpers (Batch B3)", () => {
  it("marks an insufficient sample with n and the minimum", () => {
    expect(tendencySampleText(TENDENCIES.pickPlayer, TENDENCIES)).toBe(
      "Insufficient sample — n = 2 trades (at least 3 needed) · last 30 days",
    );
    expect(tendencySampleText(TENDENCIES.positions, TENDENCIES)).toBe(
      "n = 4 players · last 30 days",
    );
    expect(
      tendencySampleText(TENDENCIES.positions, {
        window: "season",
        season: "2025",
      }),
    ).toBe("n = 4 players · 2025 season");
  });

  it("formats flows without inventing values", () => {
    const [rb, wr] = TENDENCIES.positions.rows;
    expect(tendencyFlowText(rb.acquired)).toBe("2 · 7,500");
    expect(tendencyFlowText(rb.sent)).toBe("0");
    expect(tendencyFlowText(wr.sent)).toBe("2 · 4,000 (1 unpriced)");
    expect(
      tendencyFlowText({
        count: 1,
        pricedValue: null,
        pricedCount: 0,
        unpricedCount: 1,
      }),
    ).toBe("1 · — (1 unpriced)");
  });

  it("labels shapes and drops empty counts", () => {
    expect(shapeRows(TENDENCIES.pieces.counts)).toEqual([
      {
        key: "consolidation",
        label: "Consolidation (fewer pieces in)",
        count: 1,
      },
      { key: "even", label: "Even piece count", count: 1 },
    ]);
    expect(shapeLabel("picks_for_players")).toBe("Picks for players");
    expect(shapeLabel("unknown_kind")).toBe("unknown_kind");
  });
});
