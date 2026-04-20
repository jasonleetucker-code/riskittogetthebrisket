/**
 * Tests for the per-user source override flow.
 *
 * Architecture refresher (post-unification 2026-04-15)
 * ----------------------------------------------------
 * The backend canonical pipeline is the SINGLE authoritative engine
 * for rankings, values, and trade calculator outputs.  There is no
 * frontend recompute path for customized source weights, and there
 * is no frontend fallback blend — ``buildRows`` is a pure
 * materializer that fails fast when the payload has no backend
 * stamps.
 *
 * The override flow:
 *
 *   1. The user toggles a source or moves a weight slider on the
 *      settings page (``useSettings``) which writes a
 *      ``siteWeights`` map into localStorage.
 *   2. ``useDynastyData`` observes the change and calls
 *      ``fetchDynastyData({ siteOverrides })``.
 *   3. ``fetchDynastyData`` POSTs the override map to the backend
 *      ``/api/rankings/overrides?view=delta`` endpoint when the map
 *      is customized.  The backend re-runs
 *      ``_compute_unified_rankings(source_overrides=...)`` and
 *      returns a compact delta payload.
 *   4. ``fetchDynastyData`` merges the delta onto the cached base
 *      contract, producing a full contract for ``buildRows`` to
 *      render.
 *   5. ``buildRows`` materializes the merged contract — the backend
 *      stamps on each row are the truth.
 *
 * This test suite pins the invariants of that flow:
 *   1. ``siteOverridesAreCustomized`` correctly identifies
 *      defaults-matching maps as non-customized.
 *   2. ``buildRows`` preserves backend stamps whether or not
 *      overrides are in play.
 *   3. ``mergeRankingsDelta`` applies delta payloads correctly.
 *   4. ``fetchDynastyData`` routes to the override endpoint when
 *      customized and to the default endpoint when not, and caches
 *      the base contract between override fetches.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  buildRows,
  fetchDynastyData,
  mergeRankingsDelta,
  siteOverridesAreCustomized,
  tepMultiplierIsCustomized,
  _resetBaseContractCache,
} from "@/lib/dynasty-data";

// Minimal fixture: two offense players with backend-stamped
// canonicalConsensusRank + rankDerivedValue.  The stamps are the
// backend's opinion — buildRows must forward them without
// modification regardless of any ``siteOverrides`` option passed in.
function fixture({
  backendRank = { A: 1, B: 2 },
  backendValue = { A: 9800, B: 9400 },
} = {}) {
  return {
    playersArray: [
      {
        canonicalName: "Player A",
        displayName: "Player A",
        position: "QB",
        team: "AAA",
        age: 25,
        rookie: false,
        assetClass: "offense",
        values: {
          displayValue: backendValue.A,
          finalAdjusted: backendValue.A,
          rawComposite: backendValue.A,
        },
        canonicalSiteValues: { ktc: 9999, idpTradeCalc: 9999, dlfSf: 9999 },
        canonicalConsensusRank: backendRank.A,
        rankDerivedValue: backendValue.A,
        canonicalTierId: 1,
        sourceRanks: {
          ktc: backendRank.A,
          idpTradeCalc: backendRank.A,
          dlfSf: backendRank.A,
        },
        sourceOriginalRanks: { dlfSf: backendRank.A },
        confidenceBucket: "high",
        anomalyFlags: [],
      },
      {
        canonicalName: "Player B",
        displayName: "Player B",
        position: "RB",
        team: "BBB",
        age: 24,
        rookie: false,
        assetClass: "offense",
        values: {
          displayValue: backendValue.B,
          finalAdjusted: backendValue.B,
          rawComposite: backendValue.B,
        },
        canonicalSiteValues: { ktc: 9500, idpTradeCalc: 9500 },
        canonicalConsensusRank: backendRank.B,
        rankDerivedValue: backendValue.B,
        canonicalTierId: 1,
        sourceRanks: { ktc: backendRank.B, idpTradeCalc: backendRank.B },
        sourceOriginalRanks: {},
        confidenceBucket: "high",
        anomalyFlags: [],
      },
    ],
  };
}

describe("siteOverridesAreCustomized", () => {
  it("returns false for null / undefined / empty", () => {
    expect(siteOverridesAreCustomized(null)).toBe(false);
    expect(siteOverridesAreCustomized(undefined)).toBe(false);
    expect(siteOverridesAreCustomized({})).toBe(false);
  });

  it("returns false when every override matches the default weight", () => {
    // weight: 1.0 matches the canonical registry → not customized
    expect(siteOverridesAreCustomized({ ktc: { weight: 1.0 } })).toBe(false);
    expect(
      siteOverridesAreCustomized({ dlfSf: { weight: 1.0 }, ktc: { weight: 1.0 } }),
    ).toBe(false);
  });

  it("returns true when a source is excluded", () => {
    expect(siteOverridesAreCustomized({ ktc: { include: false } })).toBe(true);
    expect(
      siteOverridesAreCustomized({ dlfSf: { include: false, weight: 1.0 } }),
    ).toBe(true);
  });

  it("returns true when a source has a non-default weight", () => {
    expect(siteOverridesAreCustomized({ ktc: { weight: 2.0 } })).toBe(true);
    expect(siteOverridesAreCustomized({ dlfSf: { weight: 0 } })).toBe(true);
    expect(siteOverridesAreCustomized({ ktc: { weight: 0.5 } })).toBe(true);
  });

  it("ignores fields that are not include or weight", () => {
    expect(siteOverridesAreCustomized({ ktc: { label: "foo" } })).toBe(false);
  });
});

describe("buildRows — default path (no overrides)", () => {
  it("keeps backend canonicalConsensusRank and rankDerivedValue", () => {
    const rows = buildRows(fixture());
    const a = rows.find((r) => r.name === "Player A");
    const b = rows.find((r) => r.name === "Player B");
    expect(a).toBeDefined();
    expect(b).toBeDefined();
    expect(a.canonicalConsensusRank).toBe(1);
    expect(b.canonicalConsensusRank).toBe(2);
    expect(a.rankDerivedValue).toBe(9800);
    expect(b.rankDerivedValue).toBe(9400);
  });

  it("forwards backend sourceRanks onto the row", () => {
    const rows = buildRows(fixture());
    const a = rows.find((r) => r.name === "Player A");
    expect(a.sourceRanks).toEqual({ ktc: 1, idpTradeCalc: 1, dlfSf: 1 });
  });
});

describe("buildRows — override path (backend-driven)", () => {
  it("trusts backend stamps even when a legacy siteOverrides map is passed in", () => {
    // The caller (useDynastyData) routes overrides to the backend
    // via fetchDynastyData — by the time buildRows sees the
    // fixture, the payload is either the backend's default response
    // or a merged delta.  The siteOverrides option on buildRows is
    // ignored entirely; it used to feed the now-removed fallback.
    const rows = buildRows(fixture());
    const a = rows.find((r) => r.name === "Player A");
    const b = rows.find((r) => r.name === "Player B");
    expect(a.canonicalConsensusRank).toBe(1);
    expect(b.canonicalConsensusRank).toBe(2);
    expect(a.rankDerivedValue).toBe(9800);
    expect(b.rankDerivedValue).toBe(9400);
    expect(Object.keys(a.sourceRanks)).toEqual([
      "ktc",
      "idpTradeCalc",
      "dlfSf",
    ]);
  });

  it("simulates an override-adjusted backend response (ktc removed from stamps)", () => {
    // Construct a fixture that mirrors what the backend
    // /api/rankings/overrides endpoint returns when ktc is disabled:
    // every row's sourceRanks + canonicalSiteValues has ktc filtered
    // out, and the consensus rank/value reflect the blend over the
    // remaining sources.  buildRows must forward these overridden
    // stamps verbatim.
    const overrideFixture = fixture();
    for (const p of overrideFixture.playersArray) {
      delete p.sourceRanks.ktc;
      delete p.canonicalSiteValues.ktc;
    }
    overrideFixture.playersArray[0].rankDerivedValue = 9500;
    overrideFixture.playersArray[1].rankDerivedValue = 9200;

    const rows = buildRows(overrideFixture);
    const a = rows.find((r) => r.name === "Player A");
    const b = rows.find((r) => r.name === "Player B");
    expect(a.rankDerivedValue).toBe(9500);
    expect(b.rankDerivedValue).toBe(9200);
    expect(Object.keys(a.sourceRanks)).not.toContain("ktc");
    expect(a.canonicalSites.ktc).toBeUndefined();
  });
});

describe("buildRows fail-fast on zero backend stamps", () => {
  it("logs an error and returns empty when the payload has no stamps", () => {
    // Fixture with raw site values but NO backend
    // canonicalConsensusRank.  The fallback path used to recompute a
    // local blend here; it has been removed.  buildRows now fails
    // fast: it logs an error and returns an empty rows array so the
    // UI surface's existing "no players" banner fires instead of
    // rendering a silently-wrong board.
    const data = {
      playersArray: [
        {
          canonicalName: "Unstamped A",
          displayName: "Unstamped A",
          position: "QB",
          values: { finalAdjusted: 5000, rawComposite: 5000 },
          canonicalSiteValues: { ktc: 9500, idpTradeCalc: 9500 },
        },
      ],
    };
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const rows = buildRows(data);
    expect(rows).toEqual([]);
    expect(errorSpy).toHaveBeenCalled();
    const callMsg = errorSpy.mock.calls[0]?.[0] || "";
    expect(String(callMsg)).toMatch(/zero backend rank stamps/);
    errorSpy.mockRestore();
  });

  it("does not warn on an empty payload (no rows at all)", () => {
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const rows = buildRows({});
    expect(rows).toEqual([]);
    expect(errorSpy).not.toHaveBeenCalled();
    errorSpy.mockRestore();
  });
});

describe("mergeRankingsDelta", () => {
  function baseContract() {
    return {
      ok: true,
      source: "backend",
      data: {
        date: "2026-04-15",
        playersArray: [
          {
            displayName: "Player A",
            canonicalName: "Player A",
            position: "QB",
            team: "AAA",
            age: 25,
            rookie: false,
            assetClass: "offense",
            values: { displayValue: 9800, finalAdjusted: 9800, rawComposite: 9800 },
            canonicalSiteValues: { ktc: 9999, idpTradeCalc: 9999, dlfSf: 9999 },
            canonicalConsensusRank: 1,
            rankDerivedValue: 9800,
            sourceRanks: { ktc: 1, idpTradeCalc: 1, dlfSf: 1 },
            sourceRankMeta: {
              ktc: { effectiveRank: 1, weight: 1.0 },
              idpTradeCalc: { effectiveRank: 1, weight: 1.0 },
              dlfSf: { effectiveRank: 1, weight: 1.0 },
            },
            sourceCount: 3,
            blendedSourceRank: 1,
            confidenceBucket: "high",
            identityConfidence: 0.95,
            identityMethod: "name_only",
          },
          {
            displayName: "Player B",
            canonicalName: "Player B",
            position: "RB",
            team: "BBB",
            age: 24,
            rookie: false,
            assetClass: "offense",
            values: { displayValue: 9400, finalAdjusted: 9400, rawComposite: 9400 },
            canonicalSiteValues: { ktc: 9500, idpTradeCalc: 9500 },
            canonicalConsensusRank: 2,
            rankDerivedValue: 9400,
            sourceRanks: { ktc: 2, idpTradeCalc: 2 },
            sourceRankMeta: {
              ktc: { effectiveRank: 2, weight: 1.0 },
              idpTradeCalc: { effectiveRank: 2, weight: 1.0 },
            },
            sourceCount: 2,
            blendedSourceRank: 2,
            confidenceBucket: "high",
            identityConfidence: 0.95,
            identityMethod: "name_only",
          },
        ],
      },
    };
  }

  function deltaPayloadKtcOff() {
    return {
      mode: "delta",
      rankingsOverride: {
        isCustomized: true,
        enabledSources: ["idpTradeCalc", "dlfSf"],
        weights: { ktc: 1.0, idpTradeCalc: 1.0, dlfSf: 1.0 },
        defaults: { ktc: 1.0, idpTradeCalc: 1.0, dlfSf: 1.0 },
        received: { ktc: { include: false } },
      },
      rankingsDelta: {
        playerKey: "displayName",
        players: [
          {
            id: "Player A",
            canonicalConsensusRank: 1,
            rankDerivedValue: 9700,
            sourceRanks: { idpTradeCalc: 1, dlfSf: 1 },
            sourceRankMeta: {
              idpTradeCalc: { effectiveRank: 1, weight: 1.0 },
              dlfSf: { effectiveRank: 1, weight: 1.0 },
            },
            sourceCount: 2,
            blendedSourceRank: 1,
            confidenceBucket: "high",
            values: { displayValue: 9700, finalAdjusted: 9700, rawComposite: 9800 },
          },
          {
            id: "Player B",
            canonicalConsensusRank: 2,
            rankDerivedValue: 9200,
            sourceRanks: { idpTradeCalc: 2 },
            sourceRankMeta: {
              idpTradeCalc: { effectiveRank: 2, weight: 1.0 },
            },
            sourceCount: 1,
            blendedSourceRank: 2,
            confidenceBucket: "low",
            values: { displayValue: 9200, finalAdjusted: 9200, rawComposite: 9400 },
          },
        ],
        activePlayerIds: ["Player A", "Player B"],
      },
    };
  }

  it("merges override-adjusted rank / value fields onto the base contract", () => {
    const merged = mergeRankingsDelta(baseContract(), deltaPayloadKtcOff());
    expect(merged.source).toBe("backend:override:delta");

    const rows = buildRows(merged.data);
    const a = rows.find((r) => r.name === "Player A");
    const b = rows.find((r) => r.name === "Player B");
    expect(a).toBeDefined();
    expect(b).toBeDefined();
    expect(a.rankDerivedValue).toBe(9700);
    expect(b.rankDerivedValue).toBe(9200);
    expect(a.sourceRanks).toEqual({ idpTradeCalc: 1, dlfSf: 1 });
    expect(b.sourceRanks).toEqual({ idpTradeCalc: 2 });
  });

  it("preserves base-row identity fields that the delta does not touch", () => {
    const merged = mergeRankingsDelta(baseContract(), deltaPayloadKtcOff());
    const rows = buildRows(merged.data);
    const a = rows.find((r) => r.name === "Player A");
    expect(a.team).toBe("AAA");
    expect(a.age).toBe(25);
    expect(a.rookie).toBe(false);
    expect(a.assetClass).toBe("offense");
    expect(a.identityConfidence).toBe(0.95);
  });

  it("produces rows with the same shape as the full-payload path", () => {
    const base = baseContract();
    const full = buildRows(base.data);
    const merged = mergeRankingsDelta(base, deltaPayloadKtcOff());
    const deltaRows = buildRows(merged.data);
    expect(full.length).toBe(deltaRows.length);
    const fullKeys = Object.keys(full[0]).sort();
    const deltaKeys = Object.keys(deltaRows[0]).sort();
    expect(deltaKeys).toEqual(fullKeys);
  });

  it("clears canonicalConsensusRank when a player falls off the override board", () => {
    const delta = deltaPayloadKtcOff();
    delta.rankingsDelta.activePlayerIds = ["Player A"];
    const merged = mergeRankingsDelta(baseContract(), delta);
    const rows = buildRows(merged.data);
    const b = rows.find((r) => r.name === "Player B");
    expect(b.canonicalConsensusRank).toBeNull();
  });

  it("returns the base contract unchanged when delta is null", () => {
    const base = baseContract();
    const merged = mergeRankingsDelta(base, null);
    expect(merged).toBe(base);
  });
});

// ── Runtime-view merge path ──────────────────────────────────────────
//
// The live production default fetch hits ``/api/data?view=app`` on
// the backend, which returns the "runtime" view: same contract
// top-level shape as the full view, but with ``playersArray``
// stripped to keep the first-paint payload small.  The legacy
// ``players`` dict (keyed by displayName) is the only per-player
// collection in that view.
//
// When an override delta arrives, ``mergeRankingsDelta`` must still
// produce a merged contract whose ``playersArray`` is populated and
// drives ``buildRows``, otherwise the override is silently lost
// (``buildRows`` materializes the legacy dict which carries the
// pre-override ranks, and the user sees a customized board that
// looks exactly like the default).  This block pins that invariant.
describe("mergeRankingsDelta — runtime-view base (no playersArray)", () => {
  function runtimeBaseContract() {
    return {
      ok: true,
      source: "backend",
      data: {
        date: "2026-04-15",
        // Runtime view strips playersArray — only legacy dict.
        players: {
          "Player A": {
            _canonicalConsensusRank: 1,
            _canonicalSiteValues: { ktc: 9999, idpTradeCalc: 9800 },
            rankDerivedValue: 9800,
            sourceRanks: { ktc: 1, idpTradeCalc: 1 },
            sourceRankMeta: {
              ktc: { effectiveRank: 1, weight: 1.0 },
              idpTradeCalc: { effectiveRank: 1, weight: 1.0 },
            },
            blendedSourceRank: 1,
            sourceCount: 2,
            confidenceBucket: "high",
            identityConfidence: 0.95,
            identityMethod: "name_only",
          },
          "Player B": {
            _canonicalConsensusRank: 2,
            _canonicalSiteValues: { ktc: 9500, idpTradeCalc: 9300 },
            rankDerivedValue: 9400,
            sourceRanks: { ktc: 2, idpTradeCalc: 2 },
            sourceRankMeta: {
              ktc: { effectiveRank: 2, weight: 1.0 },
              idpTradeCalc: { effectiveRank: 2, weight: 1.0 },
            },
            blendedSourceRank: 2,
            sourceCount: 2,
            confidenceBucket: "high",
            identityConfidence: 0.95,
            identityMethod: "name_only",
          },
        },
        sleeper: { positions: { "Player A": "QB", "Player B": "RB" } },
      },
    };
  }

  function deltaKtcOff() {
    return {
      mode: "delta",
      rankingsOverride: {
        isCustomized: true,
        enabledSources: ["idpTradeCalc"],
        weights: { ktc: 1.0, idpTradeCalc: 1.0 },
        defaults: { ktc: 1.0, idpTradeCalc: 1.0 },
        received: { ktc: { include: false } },
      },
      rankingsDelta: {
        playerKey: "displayName",
        players: [
          {
            id: "Player A",
            canonicalConsensusRank: 1,
            rankDerivedValue: 9700,
            sourceRanks: { idpTradeCalc: 1 },
            sourceRankMeta: { idpTradeCalc: { effectiveRank: 1, weight: 1.0 } },
            sourceCount: 1,
            blendedSourceRank: 1,
            confidenceBucket: "high",
            values: { displayValue: 9700, finalAdjusted: 9700, rawComposite: 9800 },
          },
          {
            id: "Player B",
            canonicalConsensusRank: 2,
            rankDerivedValue: 9200,
            sourceRanks: { idpTradeCalc: 2 },
            sourceRankMeta: { idpTradeCalc: { effectiveRank: 2, weight: 1.0 } },
            sourceCount: 1,
            blendedSourceRank: 2,
            confidenceBucket: "high",
            values: { displayValue: 9200, finalAdjusted: 9200, rawComposite: 9400 },
          },
        ],
        activePlayerIds: ["Player A", "Player B"],
      },
    };
  }

  it("synthesizes a playersArray from delta + legacy dict", () => {
    const base = runtimeBaseContract();
    expect(Array.isArray(base.data.playersArray)).toBe(false);
    const merged = mergeRankingsDelta(base, deltaKtcOff());
    expect(merged.source).toBe("backend:override:delta");
    expect(Array.isArray(merged.data.playersArray)).toBe(true);
    expect(merged.data.playersArray.length).toBe(2);
  });

  it("applies override-sensitive fields onto the synthesized rows", () => {
    const merged = mergeRankingsDelta(runtimeBaseContract(), deltaKtcOff());
    const rows = buildRows(merged.data);
    const a = rows.find((r) => r.name === "Player A");
    const b = rows.find((r) => r.name === "Player B");
    expect(a).toBeDefined();
    expect(b).toBeDefined();
    // Override sourceRanks reflected on materialized rows
    expect(a.sourceRanks).toEqual({ idpTradeCalc: 1 });
    expect(b.sourceRanks).toEqual({ idpTradeCalc: 2 });
    // Override rankDerivedValue landed on values.full
    expect(a.values.full).toBe(9700);
    expect(b.values.full).toBe(9200);
    // Ranks preserved from the delta
    expect(a.canonicalConsensusRank).toBe(1);
    expect(b.canonicalConsensusRank).toBe(2);
  });

  it("reads position from sleeper.positions when synthesizing rows", () => {
    const merged = mergeRankingsDelta(runtimeBaseContract(), deltaKtcOff());
    const rows = buildRows(merged.data);
    const a = rows.find((r) => r.name === "Player A");
    const b = rows.find((r) => r.name === "Player B");
    expect(a.pos).toBe("QB");
    expect(b.pos).toBe("RB");
  });

  it("clears canonicalConsensusRank for dropped players in runtime-view path", () => {
    const delta = deltaKtcOff();
    delta.rankingsDelta.activePlayerIds = ["Player A"];
    const merged = mergeRankingsDelta(runtimeBaseContract(), delta);
    const rows = buildRows(merged.data);
    const b = rows.find((r) => r.name === "Player B");
    expect(b.canonicalConsensusRank).toBeNull();
  });

  it("zero ktc in any sourceRanks after merge (ktc disabled)", () => {
    const merged = mergeRankingsDelta(runtimeBaseContract(), deltaKtcOff());
    const rows = buildRows(merged.data);
    for (const r of rows) {
      expect(r.sourceRanks?.ktc).toBeUndefined();
    }
  });
});

describe("fetchDynastyData — routes overrides to backend endpoint", () => {
  const realFetch = globalThis.fetch;

  beforeEach(() => {
    globalThis.fetch = vi.fn();
    _resetBaseContractCache();
  });

  afterEach(() => {
    globalThis.fetch = realFetch;
    vi.restoreAllMocks();
  });

  it("calls /api/dynasty-data with no override body when map is empty", async () => {
    globalThis.fetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        ok: true,
        source: "backend",
        data: fixture(),
      }),
    });
    await fetchDynastyData();
    expect(globalThis.fetch).toHaveBeenCalledTimes(1);
    const [url, opts] = globalThis.fetch.mock.calls[0];
    expect(String(url)).toMatch(/\/api\/dynasty-data/);
    expect(opts?.method || "GET").toBe("GET");
  });

  it("POSTs to /api/rankings/overrides?view=delta when the map is customized", async () => {
    // First call: /api/dynasty-data (base contract load).
    globalThis.fetch
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          source: "backend",
          data: {
            playersArray: [
              {
                displayName: "Player A",
                canonicalName: "Player A",
                position: "QB",
                team: "AAA",
                values: { displayValue: 9800, finalAdjusted: 9800 },
                canonicalConsensusRank: 1,
                rankDerivedValue: 9800,
                sourceRanks: { ktc: 1, idpTradeCalc: 1 },
              },
            ],
          },
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          mode: "delta",
          rankingsOverride: {
            isCustomized: true,
            enabledSources: ["idpTradeCalc"],
            received: { ktc: { include: false } },
          },
          rankingsDelta: {
            playerKey: "displayName",
            players: [
              {
                id: "Player A",
                canonicalConsensusRank: 1,
                rankDerivedValue: 9700,
                sourceRanks: { idpTradeCalc: 1 },
              },
            ],
            activePlayerIds: ["Player A"],
          },
        }),
      });
    const result = await fetchDynastyData({
      siteOverrides: { ktc: { include: false } },
    });
    expect(globalThis.fetch).toHaveBeenCalledTimes(2);
    const [url1] = globalThis.fetch.mock.calls[0];
    const [url2, opts2] = globalThis.fetch.mock.calls[1];
    expect(String(url1)).toMatch(/\/api\/dynasty-data/);
    expect(String(url2)).toMatch(/\/api\/rankings\/overrides\?view=delta/);
    expect(opts2?.method).toBe("POST");
    expect(opts2?.headers?.["Content-Type"]).toBe("application/json");
    const body = JSON.parse(opts2.body);
    expect(body).toEqual({ ktc: { include: false } });
    expect(result.source).toBe("backend:override:delta");
    const merged = result.data.playersArray[0];
    expect(merged.rankDerivedValue).toBe(9700);
  });

  it("reuses the cached base contract for a second override fetch", async () => {
    globalThis.fetch
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          source: "backend",
          data: {
            playersArray: [
              {
                displayName: "Player A",
                canonicalName: "Player A",
                position: "QB",
                canonicalConsensusRank: 1,
                rankDerivedValue: 9800,
                sourceRanks: { ktc: 1 },
                values: { displayValue: 9800 },
              },
            ],
          },
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          mode: "delta",
          rankingsOverride: { isCustomized: true },
          rankingsDelta: {
            playerKey: "displayName",
            players: [
              {
                id: "Player A",
                canonicalConsensusRank: 1,
                rankDerivedValue: 9600,
              },
            ],
            activePlayerIds: ["Player A"],
          },
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          mode: "delta",
          rankingsOverride: { isCustomized: true },
          rankingsDelta: {
            playerKey: "displayName",
            players: [
              {
                id: "Player A",
                canonicalConsensusRank: 1,
                rankDerivedValue: 9500,
              },
            ],
            activePlayerIds: ["Player A"],
          },
        }),
      });

    await fetchDynastyData({ siteOverrides: { ktc: { include: false } } });
    expect(globalThis.fetch).toHaveBeenCalledTimes(2);

    const result2 = await fetchDynastyData({
      siteOverrides: { ktc: { weight: 2.0 } },
    });
    expect(globalThis.fetch).toHaveBeenCalledTimes(3);
    const [url3] = globalThis.fetch.mock.calls[2];
    expect(String(url3)).toMatch(/\/api\/rankings\/overrides\?view=delta/);
    expect(result2.data.playersArray[0].rankDerivedValue).toBe(9500);
  });

  it("falls through to base contract when the override endpoint fails", async () => {
    globalThis.fetch
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          source: "backend",
          data: fixture(),
        }),
      })
      .mockResolvedValueOnce({
        ok: false,
        status: 503,
        json: async () => ({ error: "unavailable" }),
      });
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    const result = await fetchDynastyData({
      siteOverrides: { ktc: { include: false } },
    });
    expect(globalThis.fetch).toHaveBeenCalledTimes(2);
    expect(result.source).toMatch(/^backend/);
    warnSpy.mockRestore();
  });
});

// ── TEP multiplier routing ───────────────────────────────────────────
//
// The TE-premium multiplier is backend-authoritative.  When the user
// sets ``settings.tepMultiplier`` to anything above 1.0, the rankings
// override endpoint must be hit with ``tep_multiplier`` in the POST
// body so the backend ranking pipeline bakes TEP into every TE row's
// ``rankDerivedValue`` stamp before the delta is materialized.
// ``fetchDynastyData`` is responsible for:
//   1. Detecting that the TEP slider is customized.
//   2. Routing to the override endpoint (the same endpoint the
//      siteOverrides path uses).
//   3. Stamping ``tep_multiplier`` onto the POST body.
//   4. Merging the returned delta onto the cached base contract.
// This block pins every step.

describe("tepMultiplierIsCustomized", () => {
  // The "customized" bit flips on EXPLICITNESS, not on a magic
  // value like 1.0.  ``null`` (the new default) means "auto from
  // league" — no override.  A finite number (including 1.0) means
  // "user dragged the slider, honor this value verbatim".
  //
  // Historical note: this function used to return ``true`` only for
  // ``n > 1.0``, which bundled the hardcoded 1.15 frontend default
  // into every TEP-league user's cold-start payload and masked
  // non-TEP-league users' over-boosted TEs.  The new shape lets the
  // backend derive from Sleeper ``bonus_rec_te`` and reserves
  // "customized" for the opt-in slider drag.
  it("returns false for null / undefined (auto-from-league default)", () => {
    expect(tepMultiplierIsCustomized(undefined)).toBe(false);
    expect(tepMultiplierIsCustomized(null)).toBe(false);
    expect(tepMultiplierIsCustomized("not a number")).toBe(false);
    expect(tepMultiplierIsCustomized(NaN)).toBe(false);
  });

  it("returns true for any finite number (explicit user override)", () => {
    // Critically: 1.0 IS customized now — "user explicitly set TEP to 1.0"
    // is a real override when the league derives a non-1.0 default.
    expect(tepMultiplierIsCustomized(1.0)).toBe(true);
    expect(tepMultiplierIsCustomized(1.15)).toBe(true);
    expect(tepMultiplierIsCustomized(1.2)).toBe(true);
    expect(tepMultiplierIsCustomized(1.5)).toBe(true);
    expect(tepMultiplierIsCustomized(0.5)).toBe(true);
  });
});

describe("fetchDynastyData — tepMultiplier routes overrides to backend", () => {
  const realFetch = globalThis.fetch;

  beforeEach(() => {
    globalThis.fetch = vi.fn();
    _resetBaseContractCache();
  });

  afterEach(() => {
    globalThis.fetch = realFetch;
    vi.restoreAllMocks();
  });

  function baseMock() {
    return {
      ok: true,
      json: async () => ({
        ok: true,
        source: "backend",
        data: {
          playersArray: [
            {
              displayName: "TE One",
              canonicalName: "TE One",
              position: "TE",
              team: "AAA",
              values: { displayValue: 4000, finalAdjusted: 4000 },
              canonicalConsensusRank: 20,
              rankDerivedValue: 4000,
              sourceRanks: { ktc: 20, idpTradeCalc: 20, dlfSf: 20 },
            },
          ],
        },
      }),
    };
  }

  function deltaTepMock(boostedValue) {
    return {
      ok: true,
      json: async () => ({
        mode: "delta",
        rankingsOverride: {
          isCustomized: true,
          enabledSources: ["ktc", "idpTradeCalc", "dlfSf", "dynastyNerdsSfTep"],
          tepMultiplier: 1.15,
          tepMultiplierDefault: 1.0,
        },
        rankingsDelta: {
          playerKey: "displayName",
          players: [
            {
              id: "TE One",
              canonicalConsensusRank: 18,
              rankDerivedValue: boostedValue,
              sourceRanks: { ktc: 20, idpTradeCalc: 20, dlfSf: 20 },
              values: {
                displayValue: boostedValue,
                finalAdjusted: boostedValue,
                rawComposite: 4000,
              },
            },
          ],
          activePlayerIds: ["TE One"],
        },
      }),
    };
  }

  it("does not hit override endpoint when tepMultiplier is null/undefined (auto-from-league)", async () => {
    // ``null`` is the new default — "let the backend derive from my
    // Sleeper league".  No override POST; the base contract already
    // carries the derived value baked into every rankDerivedValue.
    globalThis.fetch.mockResolvedValueOnce(baseMock());
    await fetchDynastyData({ tepMultiplier: null });
    expect(globalThis.fetch).toHaveBeenCalledTimes(1);
    const [url] = globalThis.fetch.mock.calls[0];
    expect(String(url)).toMatch(/\/api\/dynasty-data/);

    // Also verify undefined behaves the same (some callers omit the prop).
    _resetBaseContractCache();
    globalThis.fetch.mockResolvedValueOnce(baseMock());
    await fetchDynastyData({});
    expect(globalThis.fetch).toHaveBeenCalledTimes(2);
    const [url2] = globalThis.fetch.mock.calls[1];
    expect(String(url2)).toMatch(/\/api\/dynasty-data/);
  });

  it("routes to override endpoint when only tepMultiplier is customized", async () => {
    globalThis.fetch
      .mockResolvedValueOnce(baseMock())
      .mockResolvedValueOnce(deltaTepMock(4550));

    const result = await fetchDynastyData({ tepMultiplier: 1.15 });

    expect(globalThis.fetch).toHaveBeenCalledTimes(2);
    const [url2, opts2] = globalThis.fetch.mock.calls[1];
    expect(String(url2)).toMatch(/\/api\/rankings\/overrides\?view=delta/);
    expect(opts2.method).toBe("POST");
    const body = JSON.parse(opts2.body);
    expect(body.tep_multiplier).toBe(1.15);

    // The merged delta should reflect the boosted value for TE One.
    expect(result.source).toBe("backend:override:delta");
    const te = result.data.playersArray.find((p) => p.displayName === "TE One");
    expect(te.rankDerivedValue).toBe(4550);
  });

  it("routes to override endpoint with BOTH siteOverrides and tepMultiplier", async () => {
    globalThis.fetch
      .mockResolvedValueOnce(baseMock())
      .mockResolvedValueOnce(deltaTepMock(4400));

    await fetchDynastyData({
      siteOverrides: { ktc: { include: false } },
      tepMultiplier: 1.15,
    });

    expect(globalThis.fetch).toHaveBeenCalledTimes(2);
    const [, opts2] = globalThis.fetch.mock.calls[1];
    const body = JSON.parse(opts2.body);
    // siteOverrides map fields flow through
    expect(body.ktc).toEqual({ include: false });
    // tep_multiplier is stamped alongside
    expect(body.tep_multiplier).toBe(1.15);
  });

  it("cache key: changing tepMultiplier between fetches re-issues the override request", async () => {
    globalThis.fetch
      .mockResolvedValueOnce(baseMock())
      .mockResolvedValueOnce(deltaTepMock(4500))
      .mockResolvedValueOnce(deltaTepMock(4600));

    await fetchDynastyData({ tepMultiplier: 1.15 });
    await fetchDynastyData({ tepMultiplier: 1.25 });

    expect(globalThis.fetch).toHaveBeenCalledTimes(3);
    // First override call (1.15)
    const body1 = JSON.parse(globalThis.fetch.mock.calls[1][1].body);
    expect(body1.tep_multiplier).toBe(1.15);
    // Second override call (1.25)
    const body2 = JSON.parse(globalThis.fetch.mock.calls[2][1].body);
    expect(body2.tep_multiplier).toBe(1.25);
  });
});

// ── mergeRankingsDelta: TEP-adjusted values flow through ─────────────
//
// The delta merge path must carry the backend's TEP-adjusted
// rankDerivedValue onto the merged row without further mutation,
// because the backend has already baked TEP into the stamp.

describe("mergeRankingsDelta — TEP-adjusted delta values land on the merged row", () => {
  function tepBase() {
    return {
      ok: true,
      source: "backend",
      data: {
        date: "2026-04-15",
        playersArray: [
          {
            displayName: "Brock Bowers",
            canonicalName: "Brock Bowers",
            position: "TE",
            team: "LV",
            age: 22,
            rookie: false,
            assetClass: "offense",
            values: { displayValue: 9200, finalAdjusted: 9200, rawComposite: 9200 },
            canonicalSiteValues: { ktc: 9400, dlfSf: 9450 },
            canonicalConsensusRank: 15,
            rankDerivedValue: 9200,
            sourceRanks: { ktc: 15, idpTradeCalc: 15, dlfSf: 15, dynastyNerdsSfTep: 10 },
            sourceRankMeta: {
              ktc: { effectiveRank: 15, weight: 1.0 },
              dynastyNerdsSfTep: { effectiveRank: 10, weight: 1.0 },
            },
            sourceCount: 4,
            blendedSourceRank: 13.75,
            confidenceBucket: "high",
            identityConfidence: 0.95,
            identityMethod: "name_only",
          },
        ],
      },
    };
  }

  function tepDelta() {
    return {
      mode: "delta",
      rankingsOverride: {
        isCustomized: true,
        tepMultiplier: 1.15,
        tepMultiplierDefault: 1.0,
      },
      rankingsDelta: {
        playerKey: "displayName",
        players: [
          {
            id: "Brock Bowers",
            canonicalConsensusRank: 12,
            rankDerivedValue: 9900,
            sourceRanks: { ktc: 15, idpTradeCalc: 15, dlfSf: 15, dynastyNerdsSfTep: 10 },
            sourceRankMeta: {
              ktc: { effectiveRank: 15, weight: 1.0, tepBoostApplied: true, tepMultiplier: 1.15 },
              dynastyNerdsSfTep: { effectiveRank: 10, weight: 1.0 },
            },
            sourceCount: 4,
            blendedSourceRank: 13.75,
            confidenceBucket: "high",
            values: { displayValue: 9900, finalAdjusted: 9900, rawComposite: 9200 },
          },
        ],
        activePlayerIds: ["Brock Bowers"],
      },
    };
  }

  it("applies TEP-boosted rankDerivedValue from the delta onto the merged row", () => {
    const merged = mergeRankingsDelta(tepBase(), tepDelta());
    const rows = buildRows(merged.data);
    const bowers = rows.find((r) => r.name === "Brock Bowers");
    expect(bowers).toBeDefined();
    // TEP-adjusted: backend returned 9900 in the delta, the merged
    // row must carry it verbatim.
    expect(bowers.rankDerivedValue).toBe(9900);
    expect(bowers.values.full).toBe(9900);
  });

  it("passes rankingsOverride.tepMultiplier through on the merged contract", () => {
    const merged = mergeRankingsDelta(tepBase(), tepDelta());
    expect(merged.data.rankingsOverride.tepMultiplier).toBe(1.15);
  });
});
