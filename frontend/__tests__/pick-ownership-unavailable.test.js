/**
 * Unknown pick ownership must never render as zero picks (#1618 review).
 *
 * When Sleeper's /traded_picks fetch fails, the backend publishes every
 * `sleeper.teams[]` entry with `picks: null`, `pickDetails: null` and
 * `pickOwnershipState: "unavailable"` (owner: `src/identity/picks.py`).
 * Every frontend surface that used to coerce that back to `[]` / `0` is
 * pinned here:
 *
 *   lib/pick-ownership.js       the one reader
 *   lib/bdvm.js                 pickCount null-preserving
 *   lib/league-analysis.js      PICKS null, total partial, pickCount null,
 *                               league averages skip the unknown team
 *   components/TeamSwitcher     "—pk", not "0pk"
 *   lib/portfolio-insights.js   hasPicks null, pickCount/pickValue null
 *   _pick-projector.jsx         refusal reason detected, not hidden
 */
import { describe, it, expect } from "vitest";

import {
  PICK_OWNERSHIP_UNAVAILABLE_LABEL,
  describePickOwnershipReason,
  pickOwnershipUnavailableReason,
} from "@/lib/pick-ownership";
import { buildBdvmRosterRows } from "@/lib/bdvm";
import {
  buildAllTeamSummaries,
  buildPlayerMetaMap,
  buildTeamValueBreakdown,
  computeGroupAverages,
} from "@/lib/league-analysis";
import { teamSwitcherPickMeta } from "@/components/TeamSwitcher";
import { computePortfolio } from "@/lib/portfolio-insights";
import { projectionOwnershipUnavailableReason } from "@/app/league/sections/_pick-projector.jsx";

const UNKNOWN = {
  picks: null,
  pickDetails: null,
  pickOwnershipState: "unavailable",
  pickOwnershipReason: "traded_picks_fetch_failed",
};
const OBSERVED = { pickOwnershipState: "observed", pickOwnershipReason: null };

describe("pickOwnershipUnavailableReason (the one reader)", () => {
  it("reads the explicit unavailable state", () => {
    expect(pickOwnershipUnavailableReason({ name: "T", ...UNKNOWN })).toBe(
      "traded_picks_fetch_failed",
    );
  });

  it("treats an explicit null pick list as unknown", () => {
    expect(pickOwnershipUnavailableReason({ picks: null })).toBe("pick_ownership_unstated");
  });

  it("observed and legacy payloads are usable", () => {
    expect(pickOwnershipUnavailableReason({ picks: [], ...OBSERVED })).toBeNull();
    expect(pickOwnershipUnavailableReason({ picks: ["2027 1st"] })).toBeNull();
    expect(pickOwnershipUnavailableReason({ players: [] })).toBeNull();
    expect(pickOwnershipUnavailableReason(null)).toBeNull();
  });

  it("explains the fetch failure in words", () => {
    expect(describePickOwnershipReason("traded_picks_fetch_failed")).toMatch(/traded-picks feed/);
    expect(describePickOwnershipReason("anything")).toMatch(/unknown/);
  });
});

describe("lib/bdvm buildBdvmRosterRows", () => {
  it("keeps an unknown pickCount null instead of 0", () => {
    const [row] = buildBdvmRosterRows({
      rosters: [
        {
          name: "A",
          ownerId: "o1",
          pickCount: null,
          pickCountUnavailableReason: "traded_picks_fetch_failed",
        },
      ],
    });
    expect(row.pickCount).toBeNull();
    expect(row.pickCountUnavailableReason).toBe("traded_picks_fetch_failed");
  });

  it("passes a real count through, including a real 0", () => {
    const rows = buildBdvmRosterRows({
      rosters: [
        { name: "A", ownerId: "o1", pickCount: 4 },
        { name: "B", ownerId: "o2", pickCount: 0 },
      ],
    });
    expect(rows.map((r) => r.pickCount)).toEqual([4, 0]);
    expect(rows[0].pickCountUnavailableReason).toBeNull();
  });
});

describe("lib/league-analysis team summaries", () => {
  const rows = [
    { name: "QB1", pos: "QB", rankDerivedValue: 5000, values: { full: 5000 } },
    { name: "2026 Pick 1.02", pos: "PICK", rankDerivedValue: 3000, values: { full: 3000 } },
  ];
  const meta = buildPlayerMetaMap(rows);

  it("marks PICKS unknown and the total partial, never 0 picks", () => {
    const team = { name: "T", players: ["QB1"], ...UNKNOWN };
    const b = buildTeamValueBreakdown(team, meta, rows, "full");
    expect(b.byGroup.PICKS).toBeNull();
    expect(b.totalIsPartial).toBe(true);
    expect(b.pickOwnershipUnavailable).toBe("traded_picks_fetch_failed");
    expect(b.total).toBe(5000);

    const [summary] = buildAllTeamSummaries([team], meta, rows, "full");
    expect(summary.pickCount).toBeNull();
    expect(summary.totalIsPartial).toBe(true);
  });

  it("is not partial on the players-only scope, where picks never count", () => {
    const team = { name: "T", players: ["QB1"], ...UNKNOWN };
    const b = buildTeamValueBreakdown(team, meta, rows, "players");
    expect(b.totalIsPartial).toBe(false);
    expect(b.byGroup.PICKS).toBe(0);
  });

  it("observed ownership still counts picks", () => {
    const team = { name: "T", players: ["QB1"], picks: ["2026 1.02 (own)"], ...OBSERVED };
    const b = buildTeamValueBreakdown(team, meta, rows, "full");
    expect(b.byGroup.PICKS).toBe(3000);
    expect(b.totalIsPartial).toBe(false);
    const [summary] = buildAllTeamSummaries([team], meta, rows, "full");
    expect(summary.pickCount).toBe(1);
  });

  it("leaves an unknown team out of the league PICKS average", () => {
    const avg = computeGroupAverages([
      { byGroup: { PICKS: 3000 } },
      { byGroup: { PICKS: 1000 } },
      { byGroup: { PICKS: null } },
    ]);
    expect(avg.PICKS).toBe(2000);
  });
});

describe("components/TeamSwitcher pick meta", () => {
  it('shows "—pk" with the unavailable title, not "0pk"', () => {
    expect(teamSwitcherPickMeta({ name: "T", ...UNKNOWN })).toEqual({
      text: "—pk",
      title: PICK_OWNERSHIP_UNAVAILABLE_LABEL,
    });
  });

  it("shows the real count otherwise", () => {
    expect(teamSwitcherPickMeta({ picks: ["a", "b"], ...OBSERVED }).text).toBe("2pk");
    expect(teamSwitcherPickMeta({ picks: [], ...OBSERVED }).text).toBe("0pk");
  });
});

describe("lib/portfolio-insights computePortfolio", () => {
  const rows = [
    { name: "Josh Allen", pos: "QB", age: 30, rankDerivedValue: 9988 },
    { name: "2026 Pick 1.02", pos: "PICK", rankDerivedValue: 3000 },
  ];

  it("hasPicks is unknown (null), not false, and pick totals are null", () => {
    const p = computePortfolio({
      rows,
      selectedTeam: { name: "T", players: ["Josh Allen"], ...UNKNOWN },
      rawData: {},
      history: {},
    });
    expect(p.hasPicks).toBeNull();
    expect(p.pickCount).toBeNull();
    expect(p.pickValue).toBeNull();
    expect(p.totalIsPartial).toBe(true);
    expect(p.pickOwnershipUnavailable).toBe("traded_picks_fetch_failed");
  });

  it("observed ownership keeps real pick totals", () => {
    const p = computePortfolio({
      rows,
      selectedTeam: { name: "T", players: ["Josh Allen"], picks: ["2026 1.02 (own)"], ...OBSERVED },
      rawData: {},
      history: {},
    });
    expect(p.hasPicks).toBe(true);
    expect(p.pickCount).toBe(1);
    expect(p.pickValue).toBe(3000);
    expect(p.totalIsPartial).toBe(false);
  });
});

describe("Pick Projector refusal detection", () => {
  it("detects the backend refusal from meta or the route error", () => {
    expect(
      projectionOwnershipUnavailableReason({
        picks: null,
        meta: { pickOwnershipState: "unavailable", pickOwnershipReason: "traded_picks_fetch_failed" },
      }),
    ).toBe("traded_picks_fetch_failed");
    expect(
      projectionOwnershipUnavailableReason({ error: "pick_ownership_unavailable", meta: {} }),
    ).toBe("unavailable");
  });

  it("an ordinary payload is not a refusal", () => {
    expect(
      projectionOwnershipUnavailableReason({ picks: [], meta: { pickOwnershipState: "observed" } }),
    ).toBeNull();
    expect(projectionOwnershipUnavailableReason({ error: "no_teams" })).toBeNull();
  });
});
