import { describe, expect, it } from "vitest";
import {
  buildConstraints,
  capabilitiesFor,
  exposureCountFor,
  filterAthletes,
  formatPoints,
  pointsPerK,
  readinessCopy,
  setPlayerRule,
  singleLineupForm,
  statusCopy,
  statusTone,
} from "@/lib/dfs";

describe("dfs lib — missing is never zero", () => {
  it("renders a null projection as absent, not 0", () => {
    expect(formatPoints(null)).toBe(null);
    expect(formatPoints(undefined)).toBe(null);
    expect(formatPoints(0)).toBe("0.00");
    expect(pointsPerK({ projection: null, salary: 5000 })).toBe(null);
    expect(pointsPerK({ projection: 10, salary: 5000 })).toBe(2);
  });

  it("can hide unprojected players without treating them as 0", () => {
    const rows = [
      { name: "A", team: "X", positions: ["QB"], projection: 0 },
      { name: "B", team: "X", positions: ["QB"], projection: null },
    ];
    expect(filterAthletes(rows, { hideUnprojected: true }).map((r) => r.name)).toEqual(["A"]);
  });
});

describe("dfs lib — owner controls", () => {
  it("lock and exclude are mutually exclusive", () => {
    let r = { locks: [], excludes: [] };
    r = setPlayerRule(r, "1", "lock");
    expect(r).toEqual({ locks: ["1"], excludes: [] });
    r = setPlayerRule(r, "1", "exclude");
    expect(r).toEqual({ locks: [], excludes: ["1"] });
    r = setPlayerRule(r, "1", null);
    expect(r).toEqual({ locks: [], excludes: [] });
  });

  it("builds the backend payload and converts percentages to fractions", () => {
    const { payload, errors } = buildConstraints(
      { lineups: "20", minUnique: "2", maxExposurePct: "35", salaryMin: "48000", maxPerTeam: "", stack: true, stackMin: "2", stackBringBack: "1" },
      { locks: ["9"], excludes: [] },
    );
    expect(errors).toEqual({});
    expect(payload).toMatchObject({ lineups: 20, minUnique: 2, maxExposure: 0.35, salaryMin: 48000, locks: ["9"] });
    expect(payload.stacks[0]).toMatchObject({ primary: ["QB"], minSecondary: 2, bringBack: 1 });
    expect("maxPerTeam" in payload).toBe(false);
  });

  it("refuses invalid counts instead of guessing", () => {
    expect(buildConstraints({ lineups: "0" }, {}).errors.lineups).toBeTruthy();
    expect(buildConstraints({ lineups: "2.5" }, {}).errors.lineups).toBeTruthy();
    expect(buildConstraints({ lineups: "151" }, {}).errors.lineups).toBeTruthy();
    expect(buildConstraints({ lineups: "3", maxExposurePct: "140" }, {}).errors.maxExposurePct).toBeTruthy();
  });

  it("shows the exposure count the backend will enforce (rounded down)", () => {
    expect(exposureCountFor(50, 3)).toBe(1);
    expect(exposureCountFor(35, 20)).toBe(7);
    expect(exposureCountFor(100, 150)).toBe(150);
  });
});

describe("dfs lib — capability display", () => {
  it("never labels an unverified rule set as verified", () => {
    expect(readinessCopy("research_only").label).toMatch(/unverified/i);
    expect(readinessCopy("not_implemented").status).toBe("neutral");
    expect(readinessCopy("bogus").label).toMatch(/unknown/i);
  });

  it("filters the matrix by sport and platform", () => {
    const matrix = [
      { sport: "nfl", platform: "draftkings", format: "classic" },
      { sport: "nba", platform: "draftkings", format: "classic" },
    ];
    expect(capabilitiesFor(matrix, "nba", "draftkings")).toHaveLength(1);
    expect(capabilitiesFor(null, "nfl", "fanduel")).toEqual([]);
  });

  it("maps solver statuses to non-success tones unless optimal", () => {
    expect(statusTone("optimal")).toBe("positive");
    expect(statusTone("partial")).toBe("warning");
    expect(statusTone("infeasible")).toBe("negative");
  });
});

describe("dfs lib — single lineup vs portfolio", () => {
  it("drops portfolio-only controls for a single lineup", () => {
    const f = singleLineupForm({ lineups: "20", maxExposurePct: "50", minUnique: "3", salaryMin: "49000" });
    expect(f).toMatchObject({ lineups: "1", maxExposurePct: "", minUnique: "", salaryMin: "49000" });
    const { payload } = buildConstraints(f, {});
    expect(payload.maxExposure).toBeUndefined();
    expect(payload.lineups).toBe(1);
  });

  it("does not claim a sequential set is jointly optimal", () => {
    expect(statusCopy("optimal", 20)).toMatch(/not jointly optimized/);
    expect(statusCopy("optimal", 1)).toMatch(/no higher projected total/);
  });
});
