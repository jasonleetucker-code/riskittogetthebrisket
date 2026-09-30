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
import { contestPayload, contestToForm, formatCents, presetsForShape } from "@/lib/dfs-contests";

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

  it("never fills a blank stack count with a default", () => {
    const { errors } = buildConstraints({ lineups: "1", stack: true, stackMin: "", stackBringBack: "0" }, {});
    expect(errors.stack).toBeTruthy();
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

describe("dfs lib — contests", () => {
  it("formats integer cents without float money and keeps unknown null", () => {
    expect(formatCents(100050)).toBe("$1,000.50");
    expect(formatCents(5)).toBe("$0.05");
    expect(formatCents(null)).toBe(null);
    expect(formatCents(1.5)).toBe(null);
  });

  it("never turns a blank contest field into 0", () => {
    const form = {
      name: "x",
      entryMethod: "cash",
      entryFee: "",
      capacity: "",
      currentEntries: "",
      guaranteed: "unknown",
      maxEntriesPerUser: "",
      existingUserEntries: "",
      tieRule: "unknown",
      payoutText: "",
      hypothetical: false,
      platformContestId: "",
    };
    const p = contestPayload(form, { platform: "draftkings", sport: "nfl", format: "classic" });
    for (const k of ["entryFee", "capacity", "currentEntries", "maxEntriesPerUser", "existingUserEntries", "guaranteed"]) {
      expect(p[k]).toBeNull();
    }
  });

  it("round-trips a stored contest to the form and flags non-cash bands", () => {
    const f = contestToForm({
      name: "M",
      entry_method: "cash",
      entry_fee_cents: 2000,
      capacity: 100,
      current_entries: null,
      guaranteed: true,
      max_entries_per_user: 3,
      existing_user_entries: 0,
      tie_rule: "split_positions",
      ladder_source: "entered",
      ladder: [
        { min_rank: 1, max_rank: 1, prize_cents: 100000, kind: "cash" },
        { min_rank: 2, max_rank: 5, prize_cents: 2050, kind: "cash" },
        { min_rank: 6, max_rank: 6, prize_cents: 0, kind: "ticket" },
      ],
    });
    expect(f).toMatchObject({
      entryFee: "20.00",
      currentEntries: "",
      guaranteed: "yes",
      payoutText: "1 1000.00\n2-5 20.50",
      nonCashBands: 1,
    });
  });

  it("offers only presets that fit the derived shape", () => {
    const ps = [
      { id: "a", dimensions: { payoutShape: "any" } },
      { id: "b", dimensions: { payoutShape: "tournament" } },
      { id: "c", dimensions: { payoutShape: "double_up" } },
    ];
    expect(presetsForShape(ps, "tournament").map((p) => p.id)).toEqual(["a", "b"]);
  });
});

describe("dfs lib — owner overrides vs boosts", () => {
  it("sends overrides as points and boosts as fractions; blank is absent, never 0", async () => {
    const { ownerAdjustments } = await import("@/lib/dfs");
    const { payload, errors } = ownerAdjustments({ a: "22.5", b: "" }, { a: "10", c: "0", d: "" });
    expect(errors).toEqual({});
    expect(payload).toEqual({ projectionOverrides: { a: 22.5 }, boosts: { a: 0.1 } });
  });

  it("refuses out-of-range or non-numeric entries", async () => {
    const { ownerAdjustments } = await import("@/lib/dfs");
    expect(ownerAdjustments({ a: "abc" }, {}).errors.a).toBeTruthy();
    expect(ownerAdjustments({}, { a: "75" }).errors.a).toBeTruthy();
  });
});

describe("dfs lib — per-player exposure range", () => {
  it("sends fractions; blank is absent; min 0 is dropped but max 0 is a real instruction", async () => {
    const { exposureAdjustments } = await import("@/lib/dfs");
    const { payload, errors } = exposureAdjustments({
      a: { min: "30", max: "60" },
      b: { min: "0", max: "" },
      c: { min: "", max: "0" },
      d: {},
    });
    expect(errors).toEqual({});
    expect(payload).toEqual({ playerMinExposure: { a: 0.3 }, playerMaxExposure: { a: 0.6, c: 0 } });
  });

  it("refuses out-of-range entries and a minimum above the maximum", async () => {
    const { exposureAdjustments } = await import("@/lib/dfs");
    expect(exposureAdjustments({ a: { min: "120" } }).errors.a).toBeTruthy();
    expect(exposureAdjustments({ a: { max: "x" } }).errors.a).toBeTruthy();
    expect(exposureAdjustments({ a: { min: "70", max: "40" } }).errors.a).toMatch(/above the maximum/);
  });
});

describe("dfs lib — salary range", () => {
  it("sends both ends of the salary range, blank = unconstrained", async () => {
    const { buildConstraints } = await import("@/lib/dfs");
    const { payload } = buildConstraints({ lineups: "1", salaryMin: "48000", salaryMax: "49500" }, {});
    expect(payload).toMatchObject({ salaryMin: 48000, salaryMax: 49500 });
    expect("salaryMax" in buildConstraints({ lineups: "1", salaryMax: "" }, {}).payload).toBe(false);
  });
});
