/**
 * lib/value-explainers.js — the one owner of player-value explanation
 * copy (Rankings + Player File), and the selectors that feed it.
 *
 * What this pins, and why each would otherwise drift silently:
 *
 *   - the non-voting source set mirrors the backend's
 *     `_NON_VOTING_SOURCE_CSV_KEYS` (read from the Python source, so a
 *     new benchmark key cannot reappear in a "sources that voted" list);
 *   - the copy carries none of the RETIRED methodology the surfaces
 *     used to show (spread ≤30 confidence, the λ·MAD "penalized source
 *     disagreement" gap, "the backend's spread signal");
 *   - every section names a methodology owner that exists in the repo;
 *   - confidence "none" stays "none" (not a low grade), labels and
 *     reasons are the backend's own;
 *   - per-row freshness is SELECTED from stamps (row-level factor when
 *     reduced, board-level clock and state, last fetch), non-voting keys
 *     are excluded, and freshness-quarantined sources are listed as not
 *     voting rather than dropped or zeroed;
 *   - the two board clocks (built vs scraped) are kept distinct.
 */
import { describe, it, expect } from "vitest";
import { readFileSync, existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import {
  NON_VOTING_SOURCE_KEYS,
  SOURCE_FRESHNESS_STATE_LABELS,
  VALUE_EXPLAINERS,
  VALUE_EXPLAINER_ORDER,
  boardClocks,
  confidenceDisplay,
  formatHours,
  rowAuthority,
  rowSourceFreshness,
} from "@/lib/value-explainers";

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO = join(HERE, "..", "..");

describe("non-voting source keys", () => {
  it("mirror the backend's _NON_VOTING_SOURCE_CSV_KEYS exactly", () => {
    const py = readFileSync(join(REPO, "src", "api", "data_contract.py"), "utf8");
    const m = py.match(/_NON_VOTING_SOURCE_CSV_KEYS[^=]*=\s*frozenset\(\{([^}]*)\}\)/);
    expect(m, "backend declaration must be found").not.toBeNull();
    const backend = [...m[1].matchAll(/"([^"]+)"/g)].map((x) => x[1]).sort();
    expect([...NON_VOTING_SOURCE_KEYS].sort()).toEqual(backend);
  });
});

describe("explanation copy", () => {
  const allText = VALUE_EXPLAINER_ORDER.map((k) => {
    const e = VALUE_EXPLAINERS[k];
    return [e.title, e.short, ...e.detail].join(" ");
  }).join(" ");

  it("covers every section in reading order with short, detail and owner", () => {
    expect(new Set(VALUE_EXPLAINER_ORDER)).toEqual(new Set(Object.keys(VALUE_EXPLAINERS)));
    for (const key of VALUE_EXPLAINER_ORDER) {
      const e = VALUE_EXPLAINERS[key];
      expect(e.title, key).toBeTruthy();
      expect(e.short.length, key).toBeGreaterThan(20);
      expect(e.detail.length, key).toBeGreaterThan(0);
      expect(e.owner, key).toBeTruthy();
    }
  });

  it("names methodology owners that exist in the repository", () => {
    for (const key of VALUE_EXPLAINER_ORDER) {
      const paths = VALUE_EXPLAINERS[key].owner.match(/(?:src|docs|config)\/[\w./-]+|CLAUDE\.md/g) || [];
      expect(paths.length, `${key} must cite a file`).toBeGreaterThan(0);
      for (const p of paths) {
        expect(existsSync(join(REPO, p)), `${key}: ${p}`).toBe(true);
      }
    }
  });

  it("carries none of the retired methodology the surfaces used to show", () => {
    expect(allText).not.toMatch(/spread\s*[≤<]=?\s*\d/);
    expect(allText).not.toMatch(/spread signal/i);
    expect(allText).not.toMatch(/penaliz/i);
    expect(allText).not.toMatch(/2\+ src/);
  });

  it("answers the questions the surfaces must answer", () => {
    // value, rank vs value, dynasty vs projection, league/scoring,
    // confidence + missing confidence, freshness (both clocks, stale
    // sources), provenance (KTC Market benchmark is not a vote).
    expect(VALUE_EXPLAINERS.value.short).toMatch(/1–9,999/);
    expect(VALUE_EXPLAINERS.rankVsValue.short).toMatch(/Rank/);
    expect(VALUE_EXPLAINERS.dynastyVsProjection.short).toMatch(/not a points projection/);
    expect(VALUE_EXPLAINERS.leagueContext.short).toMatch(/Scoring decides/);
    expect(VALUE_EXPLAINERS.missingConfidence.short).toMatch(/not a low grade/);
    const freshness = VALUE_EXPLAINERS.freshness.detail.join(" ");
    expect(freshness).toMatch(/Last fetched/);
    expect(freshness).toMatch(/Content as of/);
    expect(freshness).toMatch(/never counted as zero/);
    expect(VALUE_EXPLAINERS.provenance.short).toMatch(/benchmark only/);
  });
});

describe("confidenceDisplay", () => {
  it("keeps 'none' as none — missing evidence is not a low grade", () => {
    const c = confidenceDisplay({ confidenceBucket: "none", confidenceLabel: "None — unpriced", raw: { confidenceBasis: "unpriced" } });
    expect(c.level).toBe("none");
    expect(c.short).toBe("None");
    expect(c.label).toBe("None — unpriced");
    expect(c.basisNote).toMatch(/No canonical value/);
  });

  it("uses the backend label and reasons verbatim, from the row or its raw stamp", () => {
    const row = {
      confidenceBucket: "low",
      confidenceLabel: "Low — limited by freshness",
      raw: {
        confidenceAxes: { independence: "high", freshness: "low" },
        confidenceReasons: ["14 independent evidence families", "11 of 14 contributing families are past their staleness budget"],
        confidenceBasis: "evidence_gate",
      },
    };
    const c = confidenceDisplay(row);
    expect(c.level).toBe("low");
    expect(c.label).toBe("Low — limited by freshness");
    expect(c.reasons).toHaveLength(2);
    expect(c.axes.freshness).toBe("low");
    expect(c.basisNote).toMatch(/five evidence checks/);
  });

  it("an unlabelled, unknown bucket reads 'None — not assessed', never an invented rule", () => {
    const c = confidenceDisplay({});
    expect(c.level).toBe("none");
    expect(c.label).toBe("None — not assessed");
  });
});

// A board with one stale source (IDP Show) and one on-schedule source,
// shaped like the live `sourceWeighting` / `dataFreshness` blocks.
const RAW = {
  generatedAt: "2026-09-29T12:25:51Z",
  scrapeTimestamp: "2026-09-29T06:16:45Z",
  dataFreshness: {
    generatedAt: "2026-09-29T12:25:51Z",
    sourceTimestamps: {
      idpShowCombined: { mtime: "2026-09-29T10:32:14Z" },
      ktcCrowdSfTep: { mtime: "2026-09-29T06:16:45Z" },
    },
  },
  sourceWeighting: {
    asOf: "2026-09-29T06:16:45Z",
    sources: {
      idpShowCombined: {
        baseWeight: 1,
        subsets: { players: { sourceDataAsOf: "2026-08-19T17:50:16Z", ageHours: 972.4, freshness: 0.0642, state: "SEVERELY_STALE" } },
      },
      ktcCrowdSfTep: {
        baseWeight: 1,
        subsets: { players: { sourceDataAsOf: "2026-09-28T23:36:35Z", ageHours: 6.7, freshness: 1, state: "ON_SCHEDULE" } },
      },
      dlfSf: {
        baseWeight: 1,
        subsets: { players: { sourceDataAsOf: "2026-09-01T00:00:00Z", ageHours: 700, freshness: 0.01, state: "QUARANTINED" } },
      },
    },
  },
};

describe("rowSourceFreshness", () => {
  // Shaped like the backend: a freshness/health-excluded observation is
  // KEPT in sourceRankMeta with appliedWeight 0.0 + contributedToBlend
  // false (data_contract.py), and also named in freshnessExcludedSources.
  const row = {
    assetClass: "offense",
    sourceRankMeta: {
      idpShowCombined: { appliedWeight: 0.0642, weight: 1, freshness: 0.0642, freshnessAgeHours: 972.4 },
      ktcCrowdSfTep: { appliedWeight: 0.5, weight: 1, familyAdjustment: 0.5 },
      dlfSf: {
        valueContribution: 9999,
        appliedWeight: 0,
        weight: 1,
        freshness: 0,
        contributedToBlend: false,
        excludedReason: "freshness_or_health_zero_weight",
      },
    },
    // Non-voting keys the contract also stamps must never be listed.
    raw: { freshnessExcludedSources: ["dlfSf", "ktcCrowdTradesSfTep"] },
  };

  it("selects row weight/freshness, board clock/state and last fetch per voting source", () => {
    const items = rowSourceFreshness(row, RAW);
    const idp = items.find((s) => s.key === "idpShowCombined");
    expect(idp.voting).toBe(true);
    expect(idp.appliedWeight).toBeCloseTo(0.0642);
    expect(idp.rowFreshness).toBeCloseTo(0.0642);
    expect(idp.boardState).toBe("SEVERELY_STALE");
    expect(idp.contentAsOf).toBe("2026-08-19T17:50:16Z");
    expect(idp.lastFetchedAt).toBe("2026-09-29T10:32:14Z");
    const ktc = items.find((s) => s.key === "ktcCrowdSfTep");
    // No row-level stamp → the row voted at full freshness (the backend
    // stamps the factor only when it reduced the weight).
    expect(ktc.rowFreshness).toBe(1);
    expect(ktc.familyShared).toBe(true);
  });

  it("lists an excluded source as not voting — never as a weight of 0 — and never a non-voting key", () => {
    const items = rowSourceFreshness(row, RAW);
    const dlf = items.find((s) => s.key === "dlfSf");
    expect(dlf.voting).toBe(false);
    expect(dlf.excluded).toBe(true);
    expect(dlf.appliedWeight).toBeNull(); // not 0
    expect(dlf.rowFreshness).toBeNull();
    expect(dlf.boardState).toBe("QUARANTINED");
    expect(items.some((s) => s.key === "ktcCrowdTradesSfTep")).toBe(false);
    // listed once, voting sources first, heaviest first
    expect(items.map((s) => s.key)).toEqual(["ktcCrowdSfTep", "idpShowCombined", "dlfSf"]);
  });

  it("on the compact view's slim meta, row-level freshness is UNKNOWN — not full freshness", () => {
    // src/api/compact_view.py keeps only these four fields per source.
    const items = rowSourceFreshness(
      { sourceRankMeta: { idpShowCombined: { valueContribution: 4184, appliedWeight: 0.0642, effectiveWeight: 1, method: "x" } } },
      RAW,
    );
    expect(items[0].rowFreshness).toBeNull();
    expect(items[0].rowDetailAvailable).toBe(false);
    expect(items[0].appliedWeight).toBeCloseTo(0.0642);
    expect(items[0].boardState).toBe("SEVERELY_STALE");
  });

  it("marks a Hampel-dropped observation as dropped, not voting", () => {
    const items = rowSourceFreshness(
      { sourceRankMeta: { draftSharksIdp: { appliedWeight: 1, hampelDropped: true } } },
      RAW,
    );
    expect(items[0].voting).toBe(false);
    expect(items[0].outlierDropped).toBe(true);
    expect(items[0].excluded).toBe(false);
  });
});

describe("board clocks and small formatters", () => {
  it("keeps board-built and scraped clocks distinct", () => {
    expect(boardClocks(RAW)).toEqual({
      builtAt: "2026-09-29T12:25:51Z",
      scrapedAt: "2026-09-29T06:16:45Z",
    });
    expect(boardClocks({})).toEqual({ builtAt: null, scrapedAt: null });
  });

  it("formats a missing age as null, never 0h", () => {
    expect(formatHours(null)).toBeNull();
    expect(formatHours(undefined)).toBeNull();
    expect(formatHours(6.7)).toBe("7h");
    expect(formatHours(972.4)).toBe("40.5d");
  });

  it("summarises row authority only when the backend stamped it", () => {
    expect(rowAuthority({})).toBeNull();
    const a = rowAuthority({ raw: { sourceWeightState: "SEVERELY_DEGRADED", retainedAuthority: 0.5321, dominantSource: "idpTradeCalc", dominantSourceShare: 0.94 } });
    expect(a.stateLabel).toBe("Severely degraded");
    expect(a.retained).toBeCloseTo(0.5321);
    expect(a.dominantLabel).toBeTruthy();
  });
});

describe("source freshness state labels", () => {
  it("labels every state the backend freshness owner can emit", () => {
    // Read from src/sources/freshness.py so a new backend state cannot
    // render as a raw enum string.
    const py = readFileSync(join(REPO, "src", "sources", "freshness.py"), "utf8");
    const states = [...py.matchAll(/^STATE_[A-Z_]+ = "([A-Z_]+)"$/gm)].map((m) => m[1]);
    expect(states).toContain("UNMEASURED");
    for (const st of states) {
      expect(SOURCE_FRESHNESS_STATE_LABELS[st], st).toBeTruthy();
    }
  });

  it("UNMEASURED says it was not measured — never that it is fresh", () => {
    // A first observation can prove staleness but never freshness (D1).
    const label = SOURCE_FRESHNESS_STATE_LABELS.UNMEASURED;
    expect(label).toBe("Not yet measured");
    expect(label.toLowerCase()).not.toMatch(/fresh|on schedule|current/);
  });
});
