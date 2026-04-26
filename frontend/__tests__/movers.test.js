import { describe, it, expect } from "vitest";
import {
  computeMovers,
  filterByFamily,
  familyOf,
  fmtDelta,
  WINDOW_OPTIONS,
} from "@/lib/movers";

function row({
  name,
  pos = "WR",
  rankChange = 0,
  rankHistory = null,
  rankDerivedValue = 5000,
  rank = 50,
}) {
  return {
    name,
    pos,
    rankChange,
    rankHistory,
    rankDerivedValue,
    canonicalConsensusRank: rank,
    teamAbbr: "BUF",
  };
}

describe("familyOf", () => {
  it("maps offense + IDP variants", () => {
    expect(familyOf("QB")).toBe("QB");
    expect(familyOf("FB")).toBe("RB");
    expect(familyOf("EDGE")).toBe("DL");
    expect(familyOf("ILB")).toBe("LB");
    expect(familyOf("CB")).toBe("DB");
  });

  it("returns OTHER for unknown positions", () => {
    expect(familyOf("XYZ")).toBe("OTHER");
    expect(familyOf("")).toBe("OTHER");
  });
});

describe("computeMovers — 1-day window uses rankChange", () => {
  it("returns rows sorted by absolute delta desc", () => {
    const rows = [
      row({ name: "Small", rankChange: 1 }),
      row({ name: "Big", rankChange: -10 }),
      row({ name: "Mid", rankChange: 5 }),
    ];
    const out = computeMovers(rows, { windowDays: 1 });
    expect(out.map((m) => m.name)).toEqual(["Big", "Mid", "Small"]);
  });

  it("filters zero/null rankChange rows", () => {
    const rows = [
      row({ name: "Zero", rankChange: 0 }),
      row({ name: "Null", rankChange: null }),
      row({ name: "Real", rankChange: 3 }),
    ];
    const out = computeMovers(rows, { windowDays: 1 });
    expect(out.map((m) => m.name)).toEqual(["Real"]);
  });

  it("respects gainers/losers direction", () => {
    const rows = [
      row({ name: "Up", rankChange: 5 }),
      row({ name: "Down", rankChange: -7 }),
    ];
    expect(computeMovers(rows, { windowDays: 1, direction: "gainers" }).map((m) => m.name))
      .toEqual(["Up"]);
    expect(computeMovers(rows, { windowDays: 1, direction: "losers" }).map((m) => m.name))
      .toEqual(["Down"]);
  });

  it("breaks ties by higher value", () => {
    const rows = [
      row({ name: "LowVal", rankChange: 5, rankDerivedValue: 1000 }),
      row({ name: "HighVal", rankChange: 5, rankDerivedValue: 9000 }),
    ];
    const out = computeMovers(rows, { windowDays: 1 });
    expect(out[0].name).toBe("HighVal");
  });

  it("respects limit", () => {
    const rows = Array.from({ length: 50 }, (_, i) =>
      row({ name: `P${i}`, rankChange: i + 1 }),
    );
    expect(computeMovers(rows, { windowDays: 1, limit: 5 })).toHaveLength(5);
  });
});

describe("computeMovers — multi-day window uses rankHistory", () => {
  it("uses computeWindowTrend when windowDays > 1", () => {
    const today = new Date();
    const iso = (offset) => {
      const d = new Date(today);
      d.setDate(d.getDate() - offset);
      return d.toISOString().slice(0, 10);
    };
    const rows = [
      row({
        name: "Climber",
        rankChange: 1, // ignored when windowDays > 1
        rankHistory: [
          { date: iso(6), rank: 60 },
          { date: iso(0), rank: 50 },
        ],
      }),
    ];
    const out = computeMovers(rows, { windowDays: 7 });
    expect(out).toHaveLength(1);
    expect(out[0].delta).toBe(10); // improved by 10
  });
});

describe("filterByFamily", () => {
  const movers = [
    { name: "qb", family: "QB" },
    { name: "edge", family: "DL" },
    { name: "wr", family: "WR" },
  ];
  it("passes through ALL", () => {
    expect(filterByFamily(movers, "ALL")).toHaveLength(3);
  });
  it("filters by family key", () => {
    expect(filterByFamily(movers, "DL").map((m) => m.name)).toEqual(["edge"]);
  });
});

describe("fmtDelta", () => {
  it("formats with sign + dot for zero", () => {
    expect(fmtDelta(5)).toBe("+5");
    expect(fmtDelta(-7)).toBe("-7");
    expect(fmtDelta(0)).toBe("·");
    expect(fmtDelta(null)).toBe("—");
    expect(fmtDelta(NaN)).toBe("—");
  });
});

it("WINDOW_OPTIONS exposes 1d/7d/30d", () => {
  expect(WINDOW_OPTIONS.map((w) => w.key)).toEqual(["1d", "7d", "30d"]);
});
