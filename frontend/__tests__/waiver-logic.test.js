// @vitest-environment node
import { describe, it, expect } from "vitest";
import {
  normalizeName,
  buildOwnedNameSet,
  buildOwnerByName,
  classifyUpgradeTier,
  classifyDropConfidence,
  computeBestMoves,
  computeBestUniqueUpgradeSet,
  computeWaiverAnalysis as computeWaiverAnalysisServed,
} from "@/lib/waiver-logic";

/**
 * A PERMISSIVE canonical cut ladder: every roster player the rows price is
 * a legal release, cheapest (lowest value) first.  Since C2-DROP-01 the
 * drop side comes ONLY from the served ladder, so the value-comparison
 * cases below — written before that, against a roster where nobody is
 * lineup-protected — run against this stand-in for "the owner says
 * everyone is releasable".  The legality cases at the bottom of the file
 * pass a real, restrictive ladder instead.
 */
function permissiveLadder({ rows = [], myRosterNames = [] } = {}) {
  const byName = new Map(rows.map((r) => [String(r.name).trim().toLowerCase(), r]));
  const rungs = myRosterNames
    .map((n) => byName.get(String(n).trim().toLowerCase()))
    .filter((r) => r && r.assetClass !== "pick" && Number(r.rankDerivedValue) > 0)
    .sort((a, b) => a.rankDerivedValue - b.rankDerivedValue || a.name.localeCompare(b.name))
    .map((r, i) => ({
      rung: i + 1,
      playerId: "",
      name: r.name,
      position: r.pos,
      baseValue: r.rankDerivedValue,
      valueBasis: "board",
      effectiveCutCost: r.rankDerivedValue,
    }));
  return { state: "ok", rungs, undroppableCount: 0 };
}

function computeWaiverAnalysis(args = {}) {
  return computeWaiverAnalysisServed({
    ...args,
    cutLadder: args.cutLadder !== undefined ? args.cutLadder : permissiveLadder(args),
  });
}

// ── Fixture helpers ────────────────────────────────────────────────────

/** Minimal row shape — only the fields ``waiver-logic`` reads. */
function row(name, value, opts = {}) {
  return {
    name,
    pos: opts.pos || "WR",
    position: opts.position || opts.pos || "WR",
    rookie: Boolean(opts.rookie),
    assetClass: opts.assetClass || "offense",
    rankDerivedValue: value,
    values: { full: value },
    // Default to a corroborated multi-source player so existing
    // ownership/value/position cases aren't swept by the two-source
    // waiver gate.  Single-source cases set sourceCount explicitly.
    sourceCount: opts.sourceCount !== undefined ? opts.sourceCount : 2,
  };
}

/** Build N WR rows with descending values from ``startValue`` step ``step``. */
function descendingRows(prefix, n, startValue, step = 100, opts = {}) {
  return Array.from({ length: n }, (_, i) =>
    row(`${prefix} ${i}`, startValue - i * step, opts),
  );
}

/** Sleeper-team shape mock: just the ``name`` + ``players`` strings used. */
function team(name, players) {
  return { name, players };
}

// ── normalizeName ──────────────────────────────────────────────────────

describe("normalizeName", () => {
  it("collapses null / undefined / empty / whitespace identically", () => {
    expect(normalizeName(null)).toBe("");
    expect(normalizeName(undefined)).toBe("");
    expect(normalizeName("")).toBe("");
    expect(normalizeName("   ")).toBe("");
  });

  it("lowercases and trims", () => {
    expect(normalizeName("  Patrick Mahomes  ")).toBe("patrick mahomes");
    expect(normalizeName("PATRICK MAHOMES")).toBe("patrick mahomes");
  });
});

// ── buildOwnedNameSet ──────────────────────────────────────────────────

describe("buildOwnedNameSet", () => {
  it("returns an empty Set for missing / null / non-array input", () => {
    expect(buildOwnedNameSet(null).size).toBe(0);
    expect(buildOwnedNameSet(undefined).size).toBe(0);
    expect(buildOwnedNameSet("nope").size).toBe(0);
    expect(buildOwnedNameSet([]).size).toBe(0);
  });

  it("flattens every team's players into one normalized Set", () => {
    const teams = [
      team("A", ["Patrick Mahomes", "Josh Allen"]),
      team("B", ["  CeeDee Lamb  ", "JOSH ALLEN"]),  // dedupes across teams
    ];
    const owned = buildOwnedNameSet(teams);
    expect(owned.size).toBe(3);
    expect(owned.has("patrick mahomes")).toBe(true);
    expect(owned.has("josh allen")).toBe(true);
    expect(owned.has("ceedee lamb")).toBe(true);
  });

  it("ignores teams without a players array", () => {
    const teams = [team("A", null), team("B", ["Bo Nix"])];
    const owned = buildOwnedNameSet(teams);
    expect(owned.size).toBe(1);
    expect(owned.has("bo nix")).toBe(true);
  });
});

// ── buildOwnerByName ───────────────────────────────────────────────────

describe("buildOwnerByName", () => {
  it("maps each rostered name to the FIRST team that owns them", () => {
    const teams = [
      team("Russini Panini", ["Bo Nix"]),
      team("Brent",          ["Bo Nix"]),  // shouldn't overwrite
    ];
    const owner = buildOwnerByName(teams);
    expect(owner.get("bo nix")).toBe("Russini Panini");
  });
});

// ── Tier classifiers ───────────────────────────────────────────────────

describe("classifyUpgradeTier", () => {
  it("partitions cleanly across thresholds (2000 / 1000 / 250)", () => {
    expect(classifyUpgradeTier(2500)).toBe("smash");
    expect(classifyUpgradeTier(2000)).toBe("smash");
    expect(classifyUpgradeTier(1999)).toBe("strong");
    expect(classifyUpgradeTier(1000)).toBe("strong");
    expect(classifyUpgradeTier(999)).toBe("considering");
    expect(classifyUpgradeTier(250)).toBe("considering");
    expect(classifyUpgradeTier(249)).toBe("marginal");
    expect(classifyUpgradeTier(0)).toBe("marginal");
  });
});

describe("classifyDropConfidence", () => {
  it("partitions cleanly across the same thresholds with drop labels", () => {
    expect(classifyDropConfidence(2500)).toBe("obvious");
    expect(classifyDropConfidence(1500)).toBe("reasonable");
    expect(classifyDropConfidence(500)).toBe("risky");
    expect(classifyDropConfidence(100)).toBe("hold");
  });
});

// ── computeWaiverAnalysis: empty / edge cases ──────────────────────────

describe("computeWaiverAnalysis — empty / edge", () => {
  it("returns a fully-shaped empty result for empty inputs", () => {
    const r = computeWaiverAnalysis({});
    expect(r.addable).toEqual([]);
    expect(r.droppable).toEqual([]);
    expect(r.bestMoves).toEqual([]);
    expect(r.bestUniqueUpgradeSet).toEqual([]);
    expect(r.summary.bestAddable).toBeNull();
    expect(r.summary.bestGain).toBe(0);
    expect(r.summary.addableCount).toBe(0);
    expect(r.summary.droppableCount).toBe(0);
    expect(r.summary.rookieAddCount).toBe(0);
  });

  it("returns empty when roster is empty (nothing to compare against)", () => {
    const rows = descendingRows("Pool", 5, 5000);
    const r = computeWaiverAnalysis({
      rows,
      myRosterNames: [],
      sleeperTeams: [team("A", [])],
    });
    expect(r.addable).toEqual([]);
    expect(r.droppable).toEqual([]);
  });

  it("returns empty when no FA beats the floor of the roster", () => {
    const myRoster = ["Star1", "Star2"];
    const rows = [
      row("Star1", 9000),
      row("Star2", 8500),
      row("FA Junk 1", 100),
      row("FA Junk 2", 50),
    ];
    const r = computeWaiverAnalysis({
      rows,
      myRosterNames: myRoster,
      sleeperTeams: [team("Mine", myRoster)],
    });
    expect(r.addable).toEqual([]);
    expect(r.droppable).toEqual([]);
    expect(r.summary.bestGain).toBe(0);
  });
});

// ── Single + multi addable ─────────────────────────────────────────────

describe("computeWaiverAnalysis — addable detection", () => {
  it("surfaces a single FA when their value beats one roster player", () => {
    const myRoster = ["Bench Guy"];
    const rows = [row("Bench Guy", 1000), row("FA Star", 5000)];
    const r = computeWaiverAnalysis({
      rows,
      myRosterNames: myRoster,
      sleeperTeams: [team("Mine", myRoster)],
    });
    expect(r.addable).toHaveLength(1);
    expect(r.addable[0].row.name).toBe("FA Star");
    expect(r.addable[0].bestDrop.name).toBe("Bench Guy");
    expect(r.addable[0].netGain).toBe(4000);
    expect(r.addable[0].upgradeTier).toBe("smash");
    expect(r.droppable).toHaveLength(1);
    expect(r.droppable[0].row.name).toBe("Bench Guy");
    expect(r.droppable[0].bestReplacement.name).toBe("FA Star");
  });

  it("never surfaces a single-source FA even when its value beats a roster player", () => {
    const myRoster = ["Bench Guy"];
    const rows = [
      row("Bench Guy", 1000),
      // Single-source FA whose (already haircut) value still beats the
      // bench — must NOT appear as addable (parity with the backend
      // two-source gate).
      row("Solo FA", 1500, { sourceCount: 1 }),
      // Corroborated FA — should still appear.
      row("Real FA", 5000, { sourceCount: 3 }),
    ];
    const r = computeWaiverAnalysis({
      rows,
      myRosterNames: myRoster,
      sleeperTeams: [team("Mine", myRoster)],
    });
    const addableNames = r.addable.map((a) => a.row.name);
    expect(addableNames).toContain("Real FA");
    expect(addableNames).not.toContain("Solo FA");
  });

  it("ranks multiple addables by net gain desc with stable tiebreakers", () => {
    const myRoster = ["B1", "B2", "B3"];
    const rows = [
      row("B1", 500),
      row("B2", 700),
      row("B3", 900),
      row("FA Big",    8000),  // beats B1 by 7500
      row("FA Med",    3000),  // beats B1 by 2500
      row("FA Small",  1100),  // beats B1 by 600
    ];
    const r = computeWaiverAnalysis({
      rows,
      myRosterNames: myRoster,
      sleeperTeams: [team("Mine", myRoster)],
    });
    expect(r.addable.map((a) => a.row.name)).toEqual([
      "FA Big", "FA Med", "FA Small",
    ]);
    // Each add pairs with the lowest-value beaten roster player (B1).
    expect(r.addable.every((a) => a.bestDrop.name === "B1")).toBe(true);
  });
});

// ── Rookie toggle ──────────────────────────────────────────────────────

describe("computeWaiverAnalysis — rookie toggle", () => {
  it("excludes rookie-flagged FAs when toggle is OFF", () => {
    const myRoster = ["Bench"];
    const rows = [
      row("Bench", 1000),
      row("FA Vet", 4000),
      row("FA Rookie", 4500, { rookie: true }),
    ];
    const r = computeWaiverAnalysis({
      rows,
      myRosterNames: myRoster,
      sleeperTeams: [team("Mine", myRoster)],
      includeRookies: false,
    });
    const names = r.addable.map((a) => a.row.name);
    expect(names).toContain("FA Vet");
    expect(names).not.toContain("FA Rookie");
  });

  it("includes rookie-flagged FAs when toggle is ON", () => {
    const myRoster = ["Bench"];
    const rows = [
      row("Bench", 1000),
      row("FA Rookie", 4500, { rookie: true }),
    ];
    const r = computeWaiverAnalysis({
      rows,
      myRosterNames: myRoster,
      sleeperTeams: [team("Mine", myRoster)],
      includeRookies: true,
    });
    expect(r.addable).toHaveLength(1);
    expect(r.addable[0].row.name).toBe("FA Rookie");
    expect(r.addable[0].isRookie).toBe(true);
    expect(r.addable[0].rosteredBy).toBeNull();
  });

  it("annotates rookies on OTHER teams with rosteredBy when toggle is ON", () => {
    const myRoster = ["My Bench"];
    const rows = [
      row("My Bench", 1000),
      row("Their Rookie", 5000, { rookie: true }),
    ];
    const r = computeWaiverAnalysis({
      rows,
      myRosterNames: myRoster,
      sleeperTeams: [
        team("Mine",   myRoster),
        team("Brent",  ["Their Rookie"]),
      ],
      includeRookies: true,
    });
    const found = r.addable.find((a) => a.row.name === "Their Rookie");
    expect(found).toBeTruthy();
    expect(found.rosteredBy).toBe("Brent");
    // Read-only rookie should NOT count toward droppable threshold.
    expect(r.summary.addableCount).toBe(0);  // realAdds (rosteredBy=null)
  });

  it("two-source gate exempts read-only rookies rostered by other teams", () => {
    const myRoster = ["My Bench"];
    const rows = [
      row("My Bench", 1000),
      // Single-source rookie owned by another team: it can never be a
      // waiver pickup (filtered from bestMoves/upgrades/replacements),
      // so the two-source gate must NOT strip it from the read-only
      // comparison list.
      row("Their Solo Rookie", 5000, { rookie: true, sourceCount: 1 }),
    ];
    const r = computeWaiverAnalysis({
      rows,
      myRosterNames: myRoster,
      sleeperTeams: [
        team("Mine",  myRoster),
        team("Brent", ["Their Solo Rookie"]),
      ],
      includeRookies: true,
    });
    const found = r.addable.find((a) => a.row.name === "Their Solo Rookie");
    expect(found).toBeTruthy();
    expect(found.rosteredBy).toBe("Brent");
    // Still never a real suggestion.
    expect(r.bestMoves).toEqual([]);
    expect(r.summary.addableCount).toBe(0);
  });

  it("rookies on other teams never appear in bestMoves or bestUniqueUpgradeSet", () => {
    const myRoster = ["My Bench"];
    const rows = [
      row("My Bench", 1000),
      row("Their Rookie", 5000, { rookie: true }),
    ];
    const r = computeWaiverAnalysis({
      rows,
      myRosterNames: myRoster,
      sleeperTeams: [
        team("Mine",   myRoster),
        team("Brent",  ["Their Rookie"]),
      ],
      includeRookies: true,
    });
    expect(r.bestMoves).toEqual([]);
    expect(r.bestUniqueUpgradeSet).toEqual([]);
  });
});

// ── BestMoves dedup + Best Unique Upgrade Set ──────────────────────────

describe("computeWaiverAnalysis — bestMoves dedup", () => {
  it("never lists the same add twice in bestMoves", () => {
    const myRoster = ["B1", "B2", "B3"];
    const rows = [
      row("B1", 100),
      row("B2", 200),
      row("B3", 300),
      row("FA Star", 9000),
    ];
    const r = computeWaiverAnalysis({
      rows,
      myRosterNames: myRoster,
      sleeperTeams: [team("Mine", myRoster)],
    });
    const adds = r.bestMoves.map((m) => m.add.name);
    expect(new Set(adds).size).toBe(adds.length);
    expect(adds).toEqual(["FA Star"]);
    // FA Star pairs with B1 (lowest value beaten), not B3.
    expect(r.bestMoves[0].drop.name).toBe("B1");
  });
});

describe("computeWaiverAnalysis — best unique upgrade set", () => {
  it("greedy-pairs adds desc with drops asc; stops when add ≤ drop", () => {
    const myRoster = ["R1", "R2", "R3", "R4"];
    const rows = [
      row("R1", 500),
      row("R2", 1500),
      row("R3", 4000),
      row("R4", 7000),
      row("FA1", 8500),  // > R1
      row("FA2", 3500),  // > R2
      row("FA3", 1000),  // > R1 only
      row("FA4", 600),   // > R1 only by 100
    ];
    const r = computeWaiverAnalysis({
      rows,
      myRosterNames: myRoster,
      sleeperTeams: [team("Mine", myRoster)],
    });
    // Adds sorted desc: FA1=8500, FA2=3500, FA3=1000, FA4=600.
    // Drops sorted asc: R1=500,  R2=1500, R3=4000, R4=7000.
    // Pair 1: 8500 > 500   ✓
    // Pair 2: 3500 > 1500  ✓
    // Pair 3: 1000 > 4000  ✗ — stop.
    expect(r.bestUniqueUpgradeSet).toHaveLength(2);
    expect(r.bestUniqueUpgradeSet[0].add.name).toBe("FA1");
    expect(r.bestUniqueUpgradeSet[0].drop.name).toBe("R1");
    expect(r.bestUniqueUpgradeSet[1].add.name).toBe("FA2");
    expect(r.bestUniqueUpgradeSet[1].drop.name).toBe("R2");
  });
});

// ── Filters ────────────────────────────────────────────────────────────

describe("computeWaiverAnalysis — filters", () => {
  it("position filter narrows addable + droppable to one position", () => {
    const myRoster = ["My RB", "My WR"];
    const rows = [
      row("My RB", 800,  { pos: "RB" }),
      row("My WR", 1000, { pos: "WR" }),
      row("FA RB", 4000, { pos: "RB" }),
      row("FA WR", 5000, { pos: "WR" }),
    ];
    const r = computeWaiverAnalysis({
      rows,
      myRosterNames: myRoster,
      sleeperTeams: [team("Mine", myRoster)],
      filters: { position: "WR" },
    });
    expect(r.addable.map((a) => a.row.name)).toEqual(["FA WR"]);
    expect(r.droppable.map((d) => d.row.name)).toEqual(["My WR"]);
  });

  it("min-gain filter drops pairs below the threshold", () => {
    const myRoster = ["B"];
    const rows = [
      row("B", 1000),
      row("Tiny FA", 1200),     // gap 200
      row("Medium FA", 2000),   // gap 1000
      row("Big FA", 5000),      // gap 4000
    ];
    const r = computeWaiverAnalysis({
      rows,
      myRosterNames: myRoster,
      sleeperTeams: [team("Mine", myRoster)],
      filters: { minGain: 500 },
    });
    expect(r.addable.map((a) => a.row.name)).toEqual(["Big FA", "Medium FA"]);
  });

  it("upgrade-strength filter (smash) restricts to smash tier only", () => {
    const myRoster = ["B"];
    const rows = [
      row("B", 1000),
      row("Marginal", 1100),   // gap 100 → marginal
      row("Strong", 2500),     // gap 1500 → strong
      row("Smash", 4000),      // gap 3000 → smash
    ];
    const r = computeWaiverAnalysis({
      rows,
      myRosterNames: myRoster,
      sleeperTeams: [team("Mine", myRoster)],
      filters: { upgradeStrength: "smash" },
    });
    expect(r.addable.map((a) => a.row.name)).toEqual(["Smash"]);
  });

  it("invalid position filter (unknown value) collapses to ALL", () => {
    const myRoster = ["B"];
    const rows = [
      row("B", 1000),
      row("FA", 5000, { pos: "RB" }),
    ];
    const r = computeWaiverAnalysis({
      rows,
      myRosterNames: myRoster,
      sleeperTeams: [team("Mine", myRoster)],
      filters: { position: "BOGUS" },
    });
    expect(r.addable).toHaveLength(1);
  });
});

// ── Robustness: ties, missing values, picks, IDP gate ──────────────────

describe("computeWaiverAnalysis — robustness", () => {
  it("ties in value resolve deterministically by displayName ascending", () => {
    const myRoster = ["Bench"];
    const rows = [
      row("Bench", 1000),
      row("Zara",   3000),
      row("Aaron",  3000),
      row("Mike",   3000),
    ];
    const r = computeWaiverAnalysis({
      rows,
      myRosterNames: myRoster,
      sleeperTeams: [team("Mine", myRoster)],
    });
    expect(r.addable.map((a) => a.row.name)).toEqual(["Aaron", "Mike", "Zara"]);
  });

  it("filters out players with NaN / missing / negative values", () => {
    const myRoster = ["B"];
    const rows = [
      row("B", 1000),
      row("FA Real", 4000),
      { name: "FA NaN", rankDerivedValue: NaN, pos: "WR", assetClass: "offense" },
      { name: "FA Null", rankDerivedValue: null, pos: "WR", assetClass: "offense" },
      { name: "FA Neg", rankDerivedValue: -10, pos: "WR", assetClass: "offense" },
      { name: "FA Missing", pos: "WR", assetClass: "offense" },
    ];
    const r = computeWaiverAnalysis({
      rows,
      myRosterNames: myRoster,
      sleeperTeams: [team("Mine", myRoster)],
    });
    expect(r.addable.map((a) => a.row.name)).toEqual(["FA Real"]);
  });

  it("picks (assetClass=pick) are excluded from BOTH pools", () => {
    const myRoster = ["My Bench"];
    const rows = [
      row("My Bench", 1000),
      row("FA Pick", 8000, { assetClass: "pick" }),
      row("FA Real", 4000),
    ];
    const r = computeWaiverAnalysis({
      rows,
      myRosterNames: myRoster,
      sleeperTeams: [team("Mine", myRoster)],
    });
    expect(r.addable.map((a) => a.row.name)).toEqual(["FA Real"]);
  });

  it("idpEnabled=false strips IDP rows from the addable pool", () => {
    const myRoster = ["My WR"];
    const rows = [
      row("My WR",   1000, { pos: "WR", assetClass: "offense" }),
      row("FA LB",   5000, { pos: "LB", assetClass: "idp" }),
      row("FA Vet",  3000, { pos: "WR", assetClass: "offense" }),
    ];
    const r = computeWaiverAnalysis({
      rows,
      myRosterNames: myRoster,
      sleeperTeams: [team("Mine", myRoster)],
      idpEnabled: false,
    });
    expect(r.addable.map((a) => a.row.name)).toEqual(["FA Vet"]);
  });

  it("idpEnabled=true keeps IDP rows", () => {
    const myRoster = ["My WR"];
    const rows = [
      row("My WR",   1000, { pos: "WR", assetClass: "offense" }),
      row("FA LB",   5000, { pos: "LB", assetClass: "idp" }),
    ];
    const r = computeWaiverAnalysis({
      rows,
      myRosterNames: myRoster,
      sleeperTeams: [team("Mine", myRoster)],
      idpEnabled: true,
    });
    expect(r.addable.map((a) => a.row.name)).toEqual(["FA LB"]);
  });
});

// ── Summary stats ──────────────────────────────────────────────────────

describe("computeWaiverAnalysis — summary", () => {
  it("populates every summary field", () => {
    const myRoster = ["B1", "B2"];
    const rows = [
      row("B1", 800),
      row("B2", 1200),
      row("FA Big",  6000),
      row("FA Mid",  3000),
      row("FA Rookie", 4000, { rookie: true }),  // rookie unrostered
      row("Picky", 9000, { assetClass: "pick" }), // ignored
    ];
    const r = computeWaiverAnalysis({
      rows,
      myRosterNames: myRoster,
      sleeperTeams: [team("Mine", myRoster)],
      includeRookies: true,
    });
    expect(r.summary.addableCount).toBe(3);            // FA Big, FA Mid, FA Rookie
    expect(r.summary.droppableCount).toBe(2);          // B1, B2
    expect(r.summary.rookieAddCount).toBe(1);          // FA Rookie
    expect(r.summary.bestAddable.name).toBe("FA Big");
    expect(r.summary.bestGain).toBe(6000 - 800);       // FA Big - lowest beaten (B1)
    expect(r.summary.rosterSize).toBe(2);
    expect(r.summary.freeAgentPoolSize).toBe(3);       // 3 unrostered offense rows
  });
});

// ── computeBestMoves / computeBestUniqueUpgradeSet directly ────────────

describe("computeBestMoves (direct)", () => {
  it("returns [] for null / non-array input", () => {
    expect(computeBestMoves(null)).toEqual([]);
    expect(computeBestMoves(undefined)).toEqual([]);
    expect(computeBestMoves("nope")).toEqual([]);
  });

  it("respects the limit option", () => {
    // Build 5 enriched-addable items with monotonic netGain.
    const items = Array.from({ length: 5 }, (_, i) => ({
      row: row(`A${i}`, 5000 - i * 100),
      bestDrop: row("D", 100),
      netGain: 4900 - i * 100,
      upgradeTier: "smash",
      isRookie: false,
      rosteredBy: null,
    }));
    expect(computeBestMoves(items, { limit: 3 })).toHaveLength(3);
  });
});

describe("computeBestUniqueUpgradeSet (direct)", () => {
  it("returns [] for null / non-array input", () => {
    expect(computeBestUniqueUpgradeSet(null, [])).toEqual([]);
    expect(computeBestUniqueUpgradeSet([], null)).toEqual([]);
    expect(computeBestUniqueUpgradeSet(null, null)).toEqual([]);
  });
});

// ── C2-DROP-01: the drop side is the canonical cut ladder, nothing else ──
//
// Every case here FAILS on the pre-C2-DROP-01 waiver-logic.js, which
// ignored the ladder and ranked the roster by raw value: it would offer the
// lineup-protected player (the cheapest one on the roster) as the drop.

function rung(n, r, extra = {}) {
  return {
    rung: n,
    playerId: "",
    name: r.name,
    position: r.pos,
    baseValue: r.rankDerivedValue,
    valueBasis: "board",
    effectiveCutCost: r.rankDerivedValue,
    ...extra,
  };
}

describe("computeWaiverAnalysis — canonical cut ladder (C2-DROP-01)", () => {
  // "Only TE" is the CHEAPEST player on the roster but the lineup needs
  // him, so the owner leaves him off the ladder.  A raw-value ranking
  // would make him the first drop for every add.
  const onlyTe = row("Only TE", 300, { pos: "TE" });
  const benchA = row("Bench A", 800);
  const benchB = row("Bench B", 600);
  const star = row("Star WR", 7000);
  const fa1 = row("FA One", 2000);
  const fa2 = row("FA Two", 1500);
  const rows = [onlyTe, benchA, benchB, star, fa1, fa2];
  const myRosterNames = [onlyTe.name, benchA.name, benchB.name, star.name];
  const sleeperTeams = [team("Mine", myRosterNames)];
  // Owner's cut order deliberately NOT value order (scarcity can do this).
  const ladder = {
    state: "ok",
    rungs: [rung(1, benchA), rung(2, benchB)],
    undroppableCount: 1,
  };

  it("never offers a lineup-protected player as a drop anywhere", () => {
    const r = computeWaiverAnalysisServed({ rows, myRosterNames, sleeperTeams, cutLadder: ladder });
    const dropNames = [
      ...r.droppable.map((d) => d.row.name),
      ...r.bestMoves.map((m) => m.drop.name),
      ...r.bestUniqueUpgradeSet.map((m) => m.drop.name),
      ...r.addable.map((a) => a.bestDrop.name),
    ];
    expect(dropNames.length).toBeGreaterThan(0);
    expect(dropNames).not.toContain("Only TE");
    expect(r.dropState.state).toBe("ok");
  });

  it("lists droppable players in the owner's cut order, not by value", () => {
    const r = computeWaiverAnalysisServed({ rows, myRosterNames, sleeperTeams, cutLadder: ladder });
    expect(r.droppable.map((d) => [d.rung, d.row.name])).toEqual([
      [1, "Bench A"],
      [2, "Bench B"],
    ]);
    // Each add pairs with the FIRST legal release it beats (rung 1).
    expect(r.bestMoves[0].drop.name).toBe("Bench A");
    // Unique set pairs ladder releases by VALUE (cheapest first): every
    // rung is in one legal set, so any subset of them is legal too.
    expect(r.bestUniqueUpgradeSet.map((m) => m.drop.name)).toEqual(["Bench B", "Bench A"]);
  });

  it("an unavailable ladder empties every drop-dependent list and says why", () => {
    const r = computeWaiverAnalysisServed({
      rows,
      myRosterNames,
      sleeperTeams,
      cutLadder: { state: "unavailable", reason: "not_ready", reasonText: "data not ready" },
    });
    expect(r.dropState).toMatchObject({ state: "unavailable", reason: "not_ready", reasonText: "data not ready" });
    expect(r.droppable).toEqual([]);
    expect(r.addable).toEqual([]);
    expect(r.bestMoves).toEqual([]);
    expect(r.bestUniqueUpgradeSet).toEqual([]);
  });

  it("a missing ladder is unavailable, never a raw-value fallback", () => {
    const r = computeWaiverAnalysisServed({ rows, myRosterNames, sleeperTeams });
    expect(r.dropState.state).toBe("unavailable");
    expect(r.droppable).toEqual([]);
    expect(r.bestMoves).toEqual([]);
  });

  it("an unpriced rung keeps the owner's assumed waiver level — never 0, never skipped", () => {
    const ghostLadder = {
      state: "ok",
      rungs: [
        { rung: 1, playerId: "g1", name: "Ghost Player", position: "WR", baseValue: 450, valueBasis: "assumedWaiver", effectiveCutCost: 0 },
      ],
    };
    const r = computeWaiverAnalysisServed({
      rows,
      myRosterNames: [...myRosterNames, "Ghost Player"],
      sleeperTeams,
      cutLadder: ghostLadder,
    });
    expect(r.droppable).toHaveLength(1);
    expect(r.droppable[0]).toMatchObject({ value: 450, valueBasis: "assumedWaiver" });
    expect(r.droppable[0].row.name).toBe("Ghost Player");
    expect(r.droppable[0].netGain).toBe(2000 - 450);
  });

  it("the drop side is valued on the page's own board when the rung joins", () => {
    const shifted = { ...ladder, rungs: [rung(1, benchA, { baseValue: 9999 })] };
    const r = computeWaiverAnalysisServed({ rows, myRosterNames, sleeperTeams, cutLadder: shifted });
    // Same board as the add side (the user's overrides included), not the
    // served default-board number.
    expect(r.droppable[0].value).toBe(800);
  });
});

describe("computeBestUniqueUpgradeSet — full pairing over ladder releases", () => {
  it("does not stop at the first add that fails to beat its CUT-ORDER rung", () => {
    // Review repro: adds [600, 300, 250] vs rungs 1-3 valued [100, 500, 200].
    // Pairing in cut order: 600>100, then 300<500 -> stop, ONE pair.
    // The rungs form one legal set, so pairing by value is legal:
    // 600>100, 300>200, then 250<500 stops — the two pairs below.
    const adds = [row("Add 600", 600), row("Add 300", 300), row("Add 250", 250)].map((r) => ({
      row: r,
      value: r.rankDerivedValue,
      isRookie: false,
      rosteredBy: null,
    }));
    const drops = [
      { row: row("Rung1", 100), value: 100, rung: 1 },
      { row: row("Rung2", 500), value: 500, rung: 2 },
      { row: row("Rung3", 200), value: 200, rung: 3 },
    ];
    const set = computeBestUniqueUpgradeSet(adds, drops);
    expect(set.map((m) => [m.add.name, m.drop.name])).toEqual([
      ["Add 600", "Rung1"],
      ["Add 300", "Rung3"],
    ]);
  });

  it("pairs every add when each beats some distinct release", () => {
    const adds = [row("A9", 900), row("A8", 800), row("A7", 700)].map((r) => ({
      row: r,
      value: r.rankDerivedValue,
      isRookie: false,
      rosteredBy: null,
    }));
    const drops = [
      { row: row("R1", 100), value: 100, rung: 1 },
      { row: row("R2", 500), value: 500, rung: 2 },
      { row: row("R3", 200), value: 200, rung: 3 },
    ];
    expect(computeBestUniqueUpgradeSet(adds, drops)).toHaveLength(3);
  });
});
