import { describe, expect, it } from "vitest";
import fs from "node:fs";
import path from "node:path";
import {
  buildExclusionRows,
  buildTransparencyTiles,
  classifyEmptyState,
  describeBuySell,
  describeManagerConcentration,
  describeTrend,
  formatCount,
  formatDelta,
  formatPct,
  formatSample,
  formatTimestamp,
} from "@/lib/sharp-roster-percentage";

describe("formatting", () => {
  it("renders a percentage and an em dash for nothing", () => {
    expect(formatPct(0.5)).toBe("50.0%");
    expect(formatPct(1)).toBe("100.0%");
    expect(formatPct(null)).toBe("—");
    expect(formatPct(undefined)).toBe("—");
    expect(formatPct(Number.NaN)).toBe("—");
  });

  it("signs a percentage-point delta", () => {
    expect(formatDelta(0.333)).toBe("+33.3 pp");
    expect(formatDelta(-0.1)).toBe("-10.0 pp");
    expect(formatDelta(0)).toBe("0.0 pp");
    expect(formatDelta(null)).toBe("—");
  });

  it("always shows the sample behind a cell", () => {
    expect(formatSample({ sharpRosters: 3, eligibleRosters: 12 })).toBe("3 of 12");
    expect(formatSample(null)).toBe("—");
  });

  it("does not render a missing count as zero", () => {
    expect(formatCount(0)).toBe("0");
    expect(formatCount(null)).toBe("—");
    expect(formatTimestamp(null)).toBe("—");
    expect(formatTimestamp(0)).toBe("—");
  });
});

// W15-F009 (inv 4.6): a per-player manager count so "N sharp rosters" does
// not read as N independent opinions when they belong to fewer managers.
describe("manager concentration", () => {
  it("adds the manager count only when it differs from the roster count", () => {
    expect(
      formatSample({ sharpRosters: 5, eligibleRosters: 12, distinctManagers: 1 }),
    ).toBe("5 of 12 (1 manager)");
    expect(
      formatSample({ sharpRosters: 4, eligibleRosters: 12, distinctManagers: 3 }),
    ).toBe("4 of 12 (3 managers)");
  });

  it("omits the manager count when every roster belongs to a different manager", () => {
    expect(
      formatSample({ sharpRosters: 4, eligibleRosters: 12, distinctManagers: 4 }),
    ).toBe("4 of 12");
  });

  it("does not touch the base sample when the backend published nothing", () => {
    expect(formatSample({ sharpRosters: 3, eligibleRosters: 12 })).toBe("3 of 12");
  });

  it("describes concentration only when a manager holds more than one counted roster", () => {
    expect(
      describeManagerConcentration({
        sharpRosters: 5,
        distinctManagers: 1,
        managerConcentration: 1,
      }),
    ).toBe(
      "1 distinct manager behind these 5 rosters — one manager accounts for 100%.",
    );
    expect(
      describeManagerConcentration({
        sharpRosters: 4,
        distinctManagers: 3,
        managerConcentration: 0.5,
      }),
    ).toBe(
      "3 distinct managers behind these 4 rosters — one manager accounts for 50%.",
    );
  });

  it("returns undefined rather than a redundant note for the even case", () => {
    expect(
      describeManagerConcentration({
        sharpRosters: 4,
        distinctManagers: 4,
        managerConcentration: 0.25,
      }),
    ).toBeUndefined();
    expect(describeManagerConcentration(null)).toBeUndefined();
    expect(describeManagerConcentration({})).toBeUndefined();
  });
});

describe("describeTrend", () => {
  it("reports a change when the populations are comparable", () => {
    const trend = describeTrend(
      { thirtyDay: { available: true, rosterPctChange: 0.25, rostersAdded: 3, rostersDropped: 0 } },
      "thirtyDay",
    );
    expect(trend.available).toBe(true);
    expect(trend.label).toBe("+25.0 pp");
    expect(trend.tone).toBe("positive");
  });

  it("distinguishes 'not comparable' from 'no change'", () => {
    const withheld = describeTrend(
      {
        thirtyDay: {
          available: false,
          reason: "roster_population_changed",
          comparableRosters: 4,
        },
      },
      "thirtyDay",
    );
    expect(withheld.available).toBe(false);
    expect(withheld.label).toBe("n/a");
    expect(withheld.reason).toMatch(/Sample changed too much/);

    const flat = describeTrend({ thirtyDay: { available: true, rosterPctChange: 0 } }, "thirtyDay");
    expect(flat.available).toBe(true);
    expect(flat.label).toBe("0.0 pp");
    expect(flat.label).not.toBe(withheld.label);
  });

  it("returns an em dash when the period is absent entirely", () => {
    expect(describeTrend(undefined, "sevenDay").label).toBe("—");
  });
});

describe("describeBuySell", () => {
  it("reads accumulation and distribution as observations", () => {
    const buying = describeBuySell({ signal: "accumulating", buys: 4, sells: 1, net: 3, window: "30d" });
    expect(buying.label).toBe("Buying");
    expect(buying.tone).toBe("positive");
    expect(buying.detail).toBe("4 buys / 1 sell (net +3, 30d)");

    const selling = describeBuySell({ signal: "distributing", buys: 0, sells: 5, net: -5, window: "30d" });
    expect(selling.label).toBe("Selling");
    expect(selling.tone).toBe("negative");
  });

  it("shows nothing for a player with no recent sharp activity", () => {
    expect(describeBuySell({ signal: "none" }).label).toBe("—");
    expect(describeBuySell(null).label).toBe("—");
  });
});

describe("transparency", () => {
  it("surfaces every required disclosure", () => {
    const tiles = buildTransparencyTiles({
      transparency: {
        uniqueSharpManagers: 40,
        eligibleRosters: 96,
        sleeperRosters: 80,
        ffpcRosters: 16,
        otherPlatformRosters: 0,
        cohortManagers: 50,
        cohortManagersRepresented: 40,
        cohortCoveragePct: 0.8,
        lastRefreshedMs: 1_700_000_000_000,
      },
    });
    const byKey = Object.fromEntries(tiles.map((t) => [t.key, t]));
    expect(byKey.managers.value).toBe("40");
    expect(byKey.rosters.value).toBe("96");
    expect(byKey.sleeper.value).toBe("80");
    expect(byKey.ffpc.value).toBe("16");
    expect(byKey.other.value).toBe("0");
    expect(byKey.coverage.value).toBe("80%");
    expect(byKey.coverage.note).toBe("40 of 50");
    expect(byKey.refreshed.value).not.toBe("—");
  });

  it("degrades to em dashes rather than zeros on an empty payload", () => {
    const tiles = buildTransparencyTiles(null);
    expect(tiles.every((t) => t.value === "—")).toBe(true);
  });
});

describe("empty states", () => {
  it("says 'not collected yet' rather than 'error'", () => {
    const building = classifyEmptyState({ status: "cohort_building" });
    expect(building.title).toBe("Collecting sharp rosters");
    expect(building.detail).toMatch(/have not been collected yet/);
  });

  it("distinguishes no-eligible-rosters from no-filter-matches", () => {
    expect(classifyEmptyState({ status: "no_eligible_rosters" }).title).toBe("No eligible rosters");
    expect(classifyEmptyState({ status: "ok" }).title).toBe("No players match these filters");
  });
});

describe("exclusions", () => {
  it("humanises reasons and orders by weight", () => {
    const rows = buildExclusionRows({
      exclusions: { byReason: { stale_roster_data: 2, incompatible_league_format: 7 } },
    });
    expect(rows[0]).toMatchObject({ reason: "incompatible_league_format", count: 7 });
    expect(rows[0].label).toBe("Incompatible league format");
    expect(rows[1].label).toBe("Stale roster data");
  });
});

describe("the library derives no numbers of its own", () => {
  // The denominator rule is per-player and lives in the backend. A
  // client-side percentage would agree today and be wrong the moment
  // that rule changes, so the materializer must not contain one.
  // Comments are stripped first: the module's own docstring explains
  // the rule it must not implement, and a naive text search would
  // match the explanation rather than any code.
  const source = fs
    .readFileSync(path.join(process.cwd(), "lib/sharp-roster-percentage.js"), "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/^\s*\/\/.*$/gm, "");

  it("never divides sharpRosters by eligibleRosters", () => {
    expect(source).not.toMatch(/sharpRosters\s*\/\s*/);
    expect(source).not.toMatch(/\/\s*eligibleRosters/);
    expect(source).not.toMatch(/sharpRosterPct\s*=/);
  });

  it("never sorts or re-ranks the board", () => {
    expect(source).not.toMatch(/\.sort\(\s*\(a,\s*b\)\s*=>\s*b\.sharpRosterPct/);
  });
});
