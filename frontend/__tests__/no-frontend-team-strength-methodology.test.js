/**
 * Team Strength methodology may not live in the frontend.
 *
 * `/rosters` is titled "Team Strength" and, at the time this guard was
 * written, computed one in the browser:
 *
 *     score = 0.7 × starterValue + 0.2 × depthValue − 0.1 × pickValue
 *
 * — `frontend/lib/league-analysis.js::scoreTeamTiers`, three coefficients
 * chosen in JavaScript, then cut into thirds to label teams
 * contender / mid-tier / rebuilder. CLAUDE.md forbids it outright:
 * "There is no frontend ranking engine, period — not even a fallback."
 * `V1-35` is the binding owner decision that asset value, roster strength,
 * lineup, depth and power "may not collapse into one team score".
 *
 * The canonical owner is `src/roster_intel/strength.py`, served by
 * `GET /api/roster/intelligence`, which publishes `total` (meaningful core)
 * beside `fullRosterValue` (portfolio) precisely so the two "can never be
 * read as the same number".
 *
 * ── Why an ABSENCE test and not a parity test ─────────────────────────
 * Copied deliberately from `methodology-no-mirrored-formula.test.js`,
 * whose thesis applies verbatim: a parity test asserting the frontend
 * agrees with the backend formula "would have to be updated on every
 * promotion; an absence test cannot drift". We are not checking that the
 * weights match. We are checking that no weights exist here at all.
 *
 * ── Why this is a test and not a lint rule ────────────────────────────
 * Same reason as `a11y-tab-roles.test.js` and `a11y-clickable-keyboard.test.js`:
 * this repo has no ESLint at all, and the structural invariants live in
 * the vitest gate that already blocks CI.
 */
import { describe, it, expect } from "vitest";
import fs from "node:fs";
import path from "node:path";
import url from "node:url";

const ROOT = path.resolve(path.dirname(url.fileURLToPath(import.meta.url)), "..");

/**
 * Files that render or feed the "Team Strength" surface. Scoped rather
 * than repo-wide: a weighted blend inside, say, a chart smoothing helper
 * is not a team score, and a guard that fires on those trains people to
 * add exemptions.
 */
const SCOPE = [
  "app/rosters/page.jsx",
  "lib/league-analysis.js",
];

/**
 * Files that must read the canonical value/age axes from
 * `GET /api/roster/intelligence` rather than re-deriving them from raw
 * player rows. This is `team-phase.js`'s retired shape (V1-31 audit
 * finding F-3): not a weighted composite and not a tier-cut string —
 * `/phases`'s "contender"/"rebuild" LABELS are legitimate product
 * vocabulary for this page's own purpose, unlike `scoreTeamTiers`'
 * retired tier cut, so this scope does NOT reuse SCOPE/COMPOSITE/
 * TIER_CUT above. What was actually retired here is a client-side
 * top-25 `rankDerivedValue` sum plus a raw per-player age lookup,
 * scanning `rawData.sleeper.teams` directly.
 */
const NO_RAW_ROW_SCOPE = ["lib/team-phase.js", "components/TeamPhasePanel.jsx"];

/** Reading a raw player row's value directly, or the raw contract/hook
 *  that carries one, instead of the canonical `strengthTotal` /
 *  `valueWeightedCoreAge` the backend already aggregated. Deliberately
 *  NOT a bare `.age` check — `leagueMedians.age` is a legitimate median
 *  of already-canonical ages, and a generic `.age` pattern would flag
 *  it as if it were a raw player-row field access. */
const RAW_ROW_DERIVATION =
  /\brankDerivedValue\b|useDynastyData\s*\(|sleeper\?\.teams\b|sleeper\.teams\b/;

/**
 * A weighted-composite scoring expression: a numeric coefficient applied
 * to a *-Value/-Score term and summed with another. This is the shape of
 * a team score, not of a unit conversion.
 */
const COMPOSITE = /\b0?\.\d+\s*\*\s*\w*(?:[Vv]alue|[Ss]core)\w*|\w*(?:[Vv]alue|[Ss]core)\w*\s*\*\s*0?\.\d+/;

/** A contender/rebuilder tier cut — the classification half. */
const TIER_CUT = /["'`](?:contender|rebuilder|mid-?tier)["'`]/i;

/** Prose restating weights, e.g. an InfoTip saying "70%" / "-10%". */
const PROSE_WEIGHTS = /\b(?:70|20|10)\s*%\s*\)?\s*(?:,|\)|and\b|$)/;

function read(rel) {
  const p = path.join(ROOT, rel);
  return fs.existsSync(p) ? fs.readFileSync(p, "utf8") : null;
}

/** Blank out block/line comments so a comment ABOUT the retired formula —
 *  including a source file's own explanatory prose — cannot fail the
 *  guard. We are policing code, not documentation.
 *
 *  Comments are replaced with EQUAL-LENGTH blanks (newlines preserved)
 *  rather than deleted, because deleting them renumbers every line after
 *  the first comment. The first version of this guard deleted them and
 *  reported `league-analysis.js:980` for a formula that lives at `:1225`
 *  — a failure message that sends the reader 245 lines from the defect is
 *  worse than no line number at all. */
function stripComments(src) {
  const blank = (m) => m.replace(/[^\n]/g, " ");
  return src.replace(/\/\*[\s\S]*?\*\//g, blank).replace(/^\s*\/\/.*$/gm, blank);
}

describe("no frontend Team Strength methodology", () => {
  it("the scoped files exist (the guard is not vacuously passing)", () => {
    for (const rel of SCOPE) {
      expect(read(rel), `${rel} not found — update SCOPE`).toBeTruthy();
    }
  });

  it("the matchers actually match the thing they police", () => {
    // Synthetic positives — the exact shapes retired here.
    expect(COMPOSITE.test("starterValue * 0.7 + depthValue * 0.2")).toBe(true);
    expect(COMPOSITE.test("const s = 0.7 * starterValue;")).toBe(true);
    expect(TIER_CUT.test('tier: i < top ? "contender" : "rebuilder"')).toBe(true);
    expect(PROSE_WEIGHTS.test("starter quality (70%), roster depth (20%)")).toBe(true);

    // Synthetic negatives — legitimate frontend work must NOT trip it.
    expect(COMPOSITE.test("const pct = gVal / maxActiveTotal;")).toBe(false);
    expect(COMPOSITE.test("width: `${share * 100}%`")).toBe(false);
    expect(TIER_CUT.test('aria-label="Team Strength"')).toBe(false);
  });

  it("contains no weighted-composite team score", () => {
    const offenders = [];
    for (const rel of SCOPE) {
      const src = stripComments(read(rel) || "");
      src.split("\n").forEach((line, i) => {
        if (COMPOSITE.test(line)) offenders.push(`${rel}:${i + 1}  ${line.trim()}`);
      });
    }
    expect(
      offenders,
      "A weighted blend of value terms IS a Team Strength methodology. Read " +
        "`strength.total` from GET /api/roster/intelligence instead:\n" +
        offenders.join("\n"),
    ).toEqual([]);
  });

  it("contains no contender/rebuilder tier classification", () => {
    const offenders = [];
    for (const rel of SCOPE) {
      const src = stripComments(read(rel) || "");
      src.split("\n").forEach((line, i) => {
        if (TIER_CUT.test(line)) offenders.push(`${rel}:${i + 1}  ${line.trim()}`);
      });
    }
    expect(
      offenders,
      "Tiering teams is a backend classification. The canonical rank is " +
        "`strength.leagueRank` / `strength.leaguePercentile`:\n" + offenders.join("\n"),
    ).toEqual([]);
  });

  it("does not restate backend weights in prose", () => {
    // A tooltip saying "70% / 20% / -10%" is the same defect one layer
    // out: it is a copy of a formula that will drift silently.
    const offenders = [];
    for (const rel of SCOPE) {
      const src = stripComments(read(rel) || "");
      src.split("\n").forEach((line, i) => {
        if (PROSE_WEIGHTS.test(line) && /quality|depth|penalt|weight/i.test(line)) {
          offenders.push(`${rel}:${i + 1}  ${line.trim()}`);
        }
      });
    }
    expect(
      offenders,
      "Describing the weights is describing the formula:\n" + offenders.join("\n"),
    ).toEqual([]);
  });

  it("scoreTeamTiers is gone from the production graph", () => {
    // The named retirement. A re-export or a re-import anywhere in app/
    // or lib/ resurrects the methodology however well-guarded the
    // arithmetic above is.
    const offenders = [];
    for (const dir of ["app", "lib", "components"]) {
      const abs = path.join(ROOT, dir);
      if (!fs.existsSync(abs)) continue;
      const stack = [abs];
      while (stack.length) {
        const cur = stack.pop();
        for (const e of fs.readdirSync(cur, { withFileTypes: true })) {
          if (e.name === "node_modules" || e.name.startsWith(".")) continue;
          const p = path.join(cur, e.name);
          if (e.isDirectory()) stack.push(p);
          else if (/\.(jsx?|mjs)$/.test(e.name)) {
            const src = stripComments(fs.readFileSync(p, "utf8"));
            if (/\bscoreTeamTiers\b/.test(src)) {
              offenders.push(path.relative(ROOT, p));
            }
          }
        }
      }
    }
    expect(
      offenders,
      "`scoreTeamTiers` is retired — /rosters consumes `strength` from " +
        "GET /api/roster/intelligence:\n" + offenders.join("\n"),
    ).toEqual([]);
  });

  it("RAW_ROW_DERIVATION actually matches the retired shape", () => {
    // Positive control: the exact lines team-phase.js used to carry.
    expect(RAW_ROW_DERIVATION.test("value: Number(r.rankDerivedValue || 0),")).toBe(true);
    expect(RAW_ROW_DERIVATION.test("const { rows, rawData } = useDynastyData();")).toBe(true);
    expect(RAW_ROW_DERIVATION.test("const teams = rawData?.sleeper?.teams || [];")).toBe(true);
    // Negative control: reading the canonical materializer's OWN output
    // field names, including a MEDIAN OF ages, must not trip it.
    expect(RAW_ROW_DERIVATION.test("totalValue: t.strengthTotal,")).toBe(false);
    expect(RAW_ROW_DERIVATION.test("medianAge: t.valueWeightedCoreAge,")).toBe(false);
    expect(RAW_ROW_DERIVATION.test("medianAge != null && leagueMedians.age != null")).toBe(false);
  });

  it("team-phase.js and TeamPhasePanel.jsx read canonical strength/age, not raw player rows", () => {
    const offenders = [];
    for (const rel of NO_RAW_ROW_SCOPE) {
      const src = stripComments(read(rel) || "");
      src.split("\n").forEach((line, i) => {
        if (RAW_ROW_DERIVATION.test(line)) offenders.push(`${rel}:${i + 1}  ${line.trim()}`);
      });
    }
    expect(
      offenders,
      "A raw player-row value/age derivation is a second Team Strength " +
        "engine (V1-31 audit F-3). Read strengthTotal / valueWeightedCoreAge " +
        "from lib/roster-intelligence.js::teamStrengthLadder instead:\n" +
        offenders.join("\n"),
    ).toEqual([]);
  });
});

// ── C2-WEAK-01 / C2-DROP-01: no page-local need or droppability rule ─────
//
// Team Weakness has one owner (`src/roster_intel/weakness.py`) and
// droppability has one owner (`src/draft/displacement.py`, adapted by
// `src/roster_intel/droppability.py`); both are served by
// `GET /api/roster/intelligence`. Two pages carried their own copies:
//
//   /rosters  Trade Targets  "Weakest/Strongest" = each position's raw
//                            full-roster `byGroup` sum ÷ the league average
//   /waivers  Droppable      the roster ranked by raw value, no lineup
//                            legality — the shape #1017 deleted from the
//                            backend's `src/trade/waiver.py`
//
// The structural half names the files and the retired shapes; the
// behavioural half runs the real waiver logic and fails on any drop the
// served ladder did not offer.

import { computeWaiverAnalysis } from "@/lib/waiver-logic";

/** Files that render a team's NEED. */
const NEED_SCOPE = ["app/rosters/page.jsx", "components/TradeTargetsCard.jsx"];

/** Files that decide or render who may be DROPPED on /waivers. */
const DROP_SCOPE = ["lib/waiver-logic.js", "components/useWaiverAnalysis.js", "app/waivers/page.jsx"];

/** A position's raw group sum divided by something — a strength ratio —
 *  or the league-average helper that fed it. */
const RAW_NEED_RATIO = /\bbyGroup\s*\[[^\]]+\]\s*(?:\|\|\s*0\s*\)?)?\s*\)?\s*\/|\bcomputeGroupAverages\b|\bgroupAvg\b/;

/** The retired raw-value drop selector and its scaffolding. */
const RAW_DROP_SELECTOR = /\bfindBestDropMatch\b|\brosterSortedAsc\b|\brosterMin\b|\baddableMax\b/;

describe("no page-local need or droppability rule (C2-WEAK-01 / C2-DROP-01)", () => {
  it("the scoped files exist (the guard is not vacuously passing)", () => {
    for (const rel of [...NEED_SCOPE, ...DROP_SCOPE]) {
      expect(read(rel), `${rel} not found — update the scope`).toBeTruthy();
    }
  });

  it("the matchers match the retired shapes and spare legitimate code", () => {
    expect(RAW_NEED_RATIO.test("(myTeamData.byGroup[g] || 0) / groupAvg[g]")).toBe(true);
    expect(RAW_NEED_RATIO.test("const groupAvg = useMemo(() => computeGroupAverages(teams), [teams]);")).toBe(true);
    expect(RAW_NEED_RATIO.test("const pct = (gVal / maxActiveTotal) * 100;")).toBe(false);
    expect(RAW_NEED_RATIO.test("const gVal = team.byGroup[g] || 0;")).toBe(false);
    expect(RAW_DROP_SELECTOR.test("const bestDrop = findBestDropMatch(v, rosterSortedAsc);")).toBe(true);
    expect(RAW_DROP_SELECTOR.test("const best = firstBeatenRelease(v, releases);")).toBe(false);
  });

  it("no need ratio is computed from raw group sums on /rosters", () => {
    const offenders = [];
    for (const rel of NEED_SCOPE) {
      const src = stripComments(read(rel) || "");
      src.split("\n").forEach((line, i) => {
        if (RAW_NEED_RATIO.test(line)) offenders.push(`${rel}:${i + 1}  ${line.trim()}`);
      });
    }
    expect(
      offenders,
      "Need priority is `team.weakness` from GET /api/roster/intelligence " +
        "(lib/roster-intelligence.js::teamNeedDetail):\n" + offenders.join("\n"),
    ).toEqual([]);
  });

  it("Trade Targets reads the served need answer", () => {
    const src = stripComments(read("components/TradeTargetsCard.jsx") || "");
    expect(src).toMatch(/\bteamNeedDetail\s*\(/);
    expect(src).toMatch(/\bleagueNeedIndex\s*\(/);
  });

  it("no raw-value drop selector exists on /waivers", () => {
    const offenders = [];
    for (const rel of DROP_SCOPE) {
      const src = stripComments(read(rel) || "");
      src.split("\n").forEach((line, i) => {
        if (RAW_DROP_SELECTOR.test(line)) offenders.push(`${rel}:${i + 1}  ${line.trim()}`);
      });
    }
    expect(
      offenders,
      "Who may be dropped is the canonical cut ladder " +
        "(GET /api/roster/intelligence?droppability=1):\n" + offenders.join("\n"),
    ).toEqual([]);
    const hook = stripComments(read("components/useWaiverAnalysis.js") || "");
    expect(hook).toMatch(/useRosterIntelligence\s*\(\s*\{[^}]*droppability:\s*true/);
  });

  it("BEHAVIOUR: a player the served ladder omits is never offered as a drop", () => {
    const mk = (name, v, pos = "WR") => ({
      name, pos, position: pos, assetClass: "offense", rankDerivedValue: v, sourceCount: 3,
    });
    const rows = [mk("Protected", 100, "TE"), mk("Releasable", 700), mk("Free Agent", 3000)];
    const out = computeWaiverAnalysis({
      rows,
      myRosterNames: ["Protected", "Releasable"],
      sleeperTeams: [{ name: "Mine", players: ["Protected", "Releasable"] }],
      cutLadder: {
        state: "ok",
        rungs: [{ rung: 1, playerId: "", name: "Releasable", position: "WR", baseValue: 700, valueBasis: "board" }],
      },
    });
    const drops = [
      ...out.droppable.map((d) => d.row.name),
      ...out.bestMoves.map((m) => m.drop.name),
      ...out.bestUniqueUpgradeSet.map((m) => m.drop.name),
    ];
    expect(drops).toContain("Releasable");
    expect(drops).not.toContain("Protected");
    // And with no ladder, nothing is guessed.
    const none = computeWaiverAnalysis({
      rows,
      myRosterNames: ["Protected", "Releasable"],
      sleeperTeams: [{ name: "Mine", players: ["Protected", "Releasable"] }],
    });
    expect(none.droppable).toEqual([]);
    expect(none.bestMoves).toEqual([]);
  });
});
