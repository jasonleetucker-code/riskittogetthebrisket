/**
 * Tests for lib/dynasty-data.js — the data normalization layer
 * that feeds the trade page, rankings, and all other surfaces.
 */
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import {
  normalizePos,
  classifyPos,
  inferValueBundle,
  resolvedRank,
  buildRows,
  getSiteKeys,
  fetchDynastyData,
  normalizePlayerName,
  _resetBaseContractCache,
  SOURCE_VENDORS,
  SOURCE_VENDOR_LABELS,
  vendorForSource,
  RANKING_SOURCES,
} from "@/lib/dynasty-data";

// Common test helper: every fixture row that wants to be ranked must
// carry a backend stamp.  The backend pipeline stamps every rankable
// row in production; the frontend is a pure materializer, so tests
// must feed backend-stamped fixtures to exercise the ranking path.
function withStamps(player, rank, value) {
  return {
    canonicalConsensusRank: rank,
    rankDerivedValue: value,
    sourceRanks: player.sourceRanks || (player.canonicalSiteValues?.ktc ? { ktc: rank } : {}),
    sourceCount: player.sourceCount || 1,
    ...player,
  };
}

// ── normalizePlayerName ──────────────────────────────────────────────
//
// Frontend mirror of src/utils/name_clean.py::normalize_player_name.
// The canonical match key is what every name join across the app falls
// back on when backend-authored keys drift between snapshots.  The
// backend uses the same normaliser inside _enrich_from_source_csvs,
// so any divergence here re-introduces the T.J. Watt class of silent
// join-miss bugs.

describe("normalizePlayerName", () => {
  it("collapses adjacent single-letter initials across punctuation", () => {
    expect(normalizePlayerName("T.J. Watt")).toBe("tj watt");
    expect(normalizePlayerName("TJ Watt")).toBe("tj watt");
    expect(normalizePlayerName("t j watt")).toBe("tj watt");
    expect(normalizePlayerName("T.J. Watt")).toBe(normalizePlayerName("TJ Watt"));
  });

  it("handles C.J. Stroud and D.J. Moore punctuation variants", () => {
    expect(normalizePlayerName("C.J. Stroud")).toBe(
      normalizePlayerName("CJ Stroud")
    );
    expect(normalizePlayerName("D.J. Moore")).toBe(
      normalizePlayerName("DJ Moore")
    );
    expect(normalizePlayerName("A.J. Brown")).toBe(
      normalizePlayerName("AJ Brown")
    );
  });

  it("strips generational suffixes consistently", () => {
    expect(normalizePlayerName("Marvin Harrison Jr.")).toBe(
      normalizePlayerName("Marvin Harrison")
    );
    expect(normalizePlayerName("Kenneth Walker III")).toBe(
      normalizePlayerName("Kenneth Walker")
    );
    expect(normalizePlayerName("Brian Thomas Jr")).toBe(
      normalizePlayerName("Brian Thomas")
    );
  });

  it("folds diacritics to ASCII", () => {
    expect(normalizePlayerName("Juanyéh Thomas")).toBe(
      normalizePlayerName("Juanyeh Thomas")
    );
    // Apostrophes are collapsed to whitespace by the non-alnum rule,
    // matching the Python normalise_player_name helper exactly.  The
    // important parity property is that both spellings collide on the
    // SAME key whether or not the apostrophe is present.
    expect(normalizePlayerName("Ja'Marr Chase")).toBe(
      normalizePlayerName("Ja Marr Chase")
    );
  });

  it("returns empty string for empty or null input", () => {
    expect(normalizePlayerName("")).toBe("");
    expect(normalizePlayerName(null)).toBe("");
    expect(normalizePlayerName(undefined)).toBe("");
  });

  it("lowercases and trims whitespace", () => {
    expect(normalizePlayerName("  T.J.  WATT  ")).toBe("tj watt");
  });
});

// ── normalizePos ─────────────────────────────────────────────────────

describe("normalizePos", () => {
  it("maps DE/DT/EDGE/NT → DL", () => {
    expect(normalizePos("DE")).toBe("DL");
    expect(normalizePos("DT")).toBe("DL");
    expect(normalizePos("EDGE")).toBe("DL");
    expect(normalizePos("NT")).toBe("DL");
  });

  it("maps CB/S/FS/SS → DB", () => {
    expect(normalizePos("CB")).toBe("DB");
    expect(normalizePos("S")).toBe("DB");
    expect(normalizePos("FS")).toBe("DB");
    expect(normalizePos("SS")).toBe("DB");
  });

  it("maps OLB/ILB → LB", () => {
    expect(normalizePos("OLB")).toBe("LB");
    expect(normalizePos("ILB")).toBe("LB");
  });

  it("passes through standard offense positions", () => {
    expect(normalizePos("QB")).toBe("QB");
    expect(normalizePos("RB")).toBe("RB");
    expect(normalizePos("WR")).toBe("WR");
    expect(normalizePos("TE")).toBe("TE");
  });

  it("uppercases lowercase input", () => {
    expect(normalizePos("qb")).toBe("QB");
    expect(normalizePos("de")).toBe("DL");
  });

  it("handles null/undefined/empty", () => {
    expect(normalizePos(null)).toBe("");
    expect(normalizePos(undefined)).toBe("");
    expect(normalizePos("")).toBe("");
  });
});

// ── classifyPos ──────────────────────────────────────────────────────

describe("classifyPos", () => {
  it("classifies offense positions", () => {
    expect(classifyPos("QB")).toBe("offense");
    expect(classifyPos("RB")).toBe("offense");
    expect(classifyPos("WR")).toBe("offense");
    expect(classifyPos("TE")).toBe("offense");
  });

  it("classifies IDP positions", () => {
    expect(classifyPos("DL")).toBe("idp");
    expect(classifyPos("DE")).toBe("idp");
    expect(classifyPos("LB")).toBe("idp");
    expect(classifyPos("DB")).toBe("idp");
    expect(classifyPos("CB")).toBe("idp");
  });

  it("classifies PICK", () => {
    expect(classifyPos("PICK")).toBe("pick");
  });

  it("classifies kickers and punters as excluded", () => {
    expect(classifyPos("K")).toBe("excluded");
    expect(classifyPos("P")).toBe("excluded");
  });

  it("classifies unsupported positions as excluded", () => {
    expect(classifyPos("OL")).toBe("excluded");
    expect(classifyPos("OT")).toBe("excluded");
    expect(classifyPos("OG")).toBe("excluded");
    expect(classifyPos("C")).toBe("excluded");
    expect(classifyPos("G")).toBe("excluded");
    expect(classifyPos("T")).toBe("excluded");
    expect(classifyPos("LS")).toBe("excluded");
  });
});

// ── inferValueBundle ─────────────────────────────────────────────────

describe("inferValueBundle", () => {
  it("extracts value tiers from a full player", () => {
    const player = {
      _rawComposite: 8500,
      _finalAdjusted: 9100,
    };
    const v = inferValueBundle(player);
    expect(v.raw).toBe(8500);
    expect(v.full).toBe(9100);
  });

  it("falls back through the value chain when fields are missing", () => {
    const player = { _composite: 5000 };
    const v = inferValueBundle(player);
    expect(v.raw).toBe(5000);
    expect(v.full).toBe(5000);
  });

  it("rounds values to integers", () => {
    const player = { _rawComposite: 8500.7 };
    const v = inferValueBundle(player);
    expect(v.raw).toBe(8501);
  });

  it("prefers _canonicalDisplayValue for full when available", () => {
    const player = {
      _rawComposite: 7738,
      _finalAdjusted: 7738,
      _canonicalDisplayValue: 9920,
    };
    const v = inferValueBundle(player);
    expect(v.full).toBe(9920);
    expect(v.raw).toBe(7738);
  });

  it("falls back to _finalAdjusted when _canonicalDisplayValue is missing", () => {
    const player = {
      _rawComposite: 7738,
      _finalAdjusted: 7738,
    };
    const v = inferValueBundle(player);
    expect(v.full).toBe(7738);
  });

  it("returns zeros for empty/undefined player", () => {
    const v = inferValueBundle({});
    expect(v.raw).toBe(0);
    expect(v.full).toBe(0);
  });

  it("handles undefined argument", () => {
    const v = inferValueBundle();
    expect(v.raw).toBe(0);
  });
});

// ── getSiteKeys ──────────────────────────────────────────────────────

describe("getSiteKeys", () => {
  it("extracts site keys from data", () => {
    const data = { sites: [{ key: "ktc" }, { key: "idpTradeCalc" }] };
    expect(getSiteKeys(data)).toEqual(["ktc", "idpTradeCalc"]);
  });

  it("returns empty array for missing sites", () => {
    expect(getSiteKeys({})).toEqual([]);
    expect(getSiteKeys(null)).toEqual([]);
  });

  it("filters out empty keys", () => {
    const data = { sites: [{ key: "" }, { key: "ktc" }, {}] };
    expect(getSiteKeys(data)).toEqual(["ktc"]);
  });
});

// ── buildRows ────────────────────────────────────────────────────────
//
// The frontend no longer ranks or computes values — the backend
// pipeline stamps every rankable row with canonicalConsensusRank and
// rankDerivedValue, and ``buildRows`` forwards those stamps verbatim.
// Tests that used to feed raw site values and assert against a
// frontend-computed Hill curve have been rewritten to feed
// backend-stamped fixtures via the ``withStamps`` helper.

describe("buildRows", () => {
  it("builds rows from playersArray (contract format)", () => {
    const data = {
      playersArray: [
        withStamps({
          displayName: "Josh Allen",
          position: "QB",
          assetClass: "offense",
          sourceCount: 6,
          values: {
            rawComposite: 8500,
            finalAdjusted: 9100,
            overall: 9100,
          },
          canonicalSiteValues: { ktc: 8500 },
        }, 1, 9999),
        withStamps({
          displayName: "Micah Parsons",
          position: "LB",
          assetClass: "idp",
          sourceCount: 4,
          values: {
            rawComposite: 5000,
            finalAdjusted: 5200,
            overall: 5200,
          },
          canonicalSiteValues: {},
        }, 2, 5200),
      ],
    };
    const rows = buildRows(data);
    expect(rows.length).toBe(2);

    const allen = rows.find((r) => r.name === "Josh Allen");
    expect(allen).toBeDefined();
    expect(allen.pos).toBe("QB");
    expect(allen.assetClass).toBe("offense");
    // Backend rankDerivedValue wins over legacy finalAdjusted as the
    // displayed values.full (single-value pipe).
    expect(allen.values.full).toBe(9999);
    expect(allen.rankDerivedValue).toBe(9999);
    expect(allen.values.raw).toBe(8500);
    expect(allen.siteCount).toBe(6);
  });

  it("builds rows from legacy players map", () => {
    const data = {
      players: {
        "Josh Allen": {
          _composite: 8500,
          _rawComposite: 8500,
          _finalAdjusted: 9100,
          _sites: 6,
          position: "QB",
          // Without backend rankDerivedValue the materializer falls
          // back to _finalAdjusted for values.full.
          _canonicalConsensusRank: 1,
        },
      },
      sleeper: { positions: { "Josh Allen": "QB" } },
    };
    const rows = buildRows(data);
    expect(rows.length).toBe(1);
    expect(rows[0].values.full).toBe(9100);
    expect(rows[0].values.raw).toBe(8500);
  });

  it("prefers displayValue for full in contract format", () => {
    const data = {
      playersArray: [
        {
          displayName: "Josh Allen",
          position: "QB",
          assetClass: "offense",
          sourceCount: 6,
          values: {
            rawComposite: 7738,
            finalAdjusted: 7738,
            overall: 7738,
            displayValue: 9920,
          },
          canonicalSiteValues: {},
          canonicalConsensusRank: 1,
          // No rankDerivedValue so values.full comes from displayValue.
        },
      ],
    };
    const rows = buildRows(data);
    expect(rows[0].values.full).toBe(9920);
    expect(rows[0].values.raw).toBe(7738);
  });

  it("falls back to finalAdjusted when displayValue is missing", () => {
    const data = {
      playersArray: [
        {
          displayName: "Josh Allen",
          position: "QB",
          values: { finalAdjusted: 7738, rawComposite: 7738, overall: 7738 },
          canonicalConsensusRank: 1,
        },
      ],
    };
    const rows = buildRows(data);
    expect(rows[0].values.full).toBe(7738);
  });

  it("sorts rows by backend canonicalConsensusRank ascending", () => {
    // The backend stamps canonicalConsensusRank on every rankable
    // row; buildRows preserves that order as the primary sort key.
    const data = {
      playersArray: [
        withStamps({ displayName: "Low", position: "RB", values: { finalAdjusted: 1000, rawComposite: 1000, overall: 1000 }, canonicalSiteValues: { ktc: 1000 } }, 3, 1000),
        withStamps({ displayName: "High", position: "QB", values: { finalAdjusted: 9000, rawComposite: 9000, overall: 9000 }, canonicalSiteValues: { ktc: 9000 } }, 1, 9999),
        withStamps({ displayName: "Mid", position: "WR", values: { finalAdjusted: 5000, rawComposite: 5000, overall: 5000 }, canonicalSiteValues: { ktc: 5000 } }, 2, 5000),
      ],
    };
    const rows = buildRows(data);
    expect(rows[0].name).toBe("High");
    expect(rows[1].name).toBe("Mid");
    expect(rows[2].name).toBe("Low");
  });

  it("assigns computed row.rank from backend stamps", () => {
    const data = {
      playersArray: [
        withStamps({ displayName: "A", position: "QB", values: { finalAdjusted: 9000, rawComposite: 9000, overall: 9000 } }, 1, 9000),
        withStamps({ displayName: "B", position: "RB", values: { finalAdjusted: 5000, rawComposite: 5000, overall: 5000 } }, 2, 5000),
      ],
    };
    const rows = buildRows(data);
    expect(rows[0].rank).toBe(1);
    expect(rows[1].rank).toBe(2);
  });

  it("filters out kickers", () => {
    const data = {
      playersArray: [
        withStamps({ displayName: "Justin Tucker", position: "K", values: { finalAdjusted: 100, overall: 100, rawComposite: 100 } }, 500, 100),
        withStamps({ displayName: "Josh Allen", position: "QB", values: { finalAdjusted: 9000, overall: 9000, rawComposite: 9000 } }, 1, 9000),
      ],
    };
    const rows = buildRows(data);
    expect(rows.length).toBe(1);
    expect(rows[0].name).toBe("Josh Allen");
  });

  it("detects picks from legacy name pattern", () => {
    const data = {
      players: {
        "2026 Early 1st": {
          _composite: 7000,
          _finalAdjusted: 7000,
          _canonicalConsensusRank: 25,
          rankDerivedValue: 6800,
        },
        "2026 Pick 1.01": {
          _composite: 6500,
          _finalAdjusted: 6500,
          _canonicalConsensusRank: 28,
          rankDerivedValue: 6500,
        },
      },
    };
    const rows = buildRows(data);
    expect(rows.every((r) => r.pos === "PICK")).toBe(true);
    expect(rows.every((r) => r.assetClass === "pick")).toBe(true);
  });

  it("preserves backend sourceRanks integer values per row", () => {
    // Generate 25 players each with backend-stamped rank + value.
    const players = [];
    for (let i = 0; i < 25; i++) {
      players.push(
        withStamps(
          {
            displayName: `Player ${i}`,
            position: "QB",
            values: { finalAdjusted: 9000 - i * 100, rawComposite: 9000 - i * 100, overall: 9000 - i * 100 },
            canonicalSiteValues: { ktc: 9000 - i * 100 },
          },
          i + 1,
          9000 - i * 100,
        ),
      );
    }
    const rows = buildRows({ playersArray: players });
    expect(rows.length).toBe(25);

    const p0 = rows.find((r) => r.name === "Player 0");
    expect(p0.canonicalConsensusRank).toBe(1);
    expect(Number.isInteger(p0.canonicalConsensusRank)).toBe(true);

    const p24 = rows.find((r) => r.name === "Player 24");
    expect(p24.canonicalConsensusRank).toBe(25);

    expect(p0.values.full).toBe(9000);

    // Rows should be sorted by canonicalConsensusRank ascending.
    const ordered = rows.filter((r) => r.canonicalConsensusRank > 0);
    for (let i = 1; i < ordered.length; i++) {
      expect(ordered[i].canonicalConsensusRank).toBeGreaterThan(
        ordered[i - 1].canonicalConsensusRank,
      );
    }
  });

  it("forwards backend sourceRanks regardless of other site coverage", () => {
    // Every row carries its own canonicalConsensusRank regardless of
    // which sites contributed.  The backend handles scope-aware
    // ranking; buildRows just materializes.
    const players = [];
    for (let i = 0; i < 30; i++) {
      const sites = { ktc: 9000 - i * 100 };
      players.push(
        withStamps(
          {
            displayName: `TestPlayer ${i}`,
            position: i < 20 ? "QB" : "RB",
            values: { finalAdjusted: 9000 - i * 100, rawComposite: 9000 - i * 100, overall: 9000 - i * 100 },
            canonicalSiteValues: sites,
          },
          i + 1,
          9000 - i * 100,
        ),
      );
    }
    const rows = buildRows({ playersArray: players });
    const ranked = rows.filter((r) => r.canonicalConsensusRank != null);
    expect(ranked.length).toBe(30);
    const p0 = rows.find((r) => r.name === "TestPlayer 0");
    expect(p0.canonicalConsensusRank).toBe(1);
    const p1 = rows.find((r) => r.name === "TestPlayer 1");
    expect(p1.canonicalConsensusRank).toBe(2);
    const rankSet = new Set(ranked.map((r) => r.canonicalConsensusRank));
    expect(rankSet.size).toBe(30);
  });

  it("returns empty array for empty data", () => {
    expect(buildRows({})).toEqual([]);
    expect(buildRows({ players: {} })).toEqual([]);
  });

  it("skips players with no name", () => {
    const data = {
      playersArray: [
        { displayName: "", position: "QB", values: { overall: 5000 }, canonicalConsensusRank: 999 },
        { displayName: "Josh Allen", position: "QB", values: { overall: 9000, finalAdjusted: 9000, rawComposite: 9000 }, canonicalConsensusRank: 1 },
      ],
    };
    const rows = buildRows(data);
    expect(rows.length).toBe(1);
  });
});

// ── Backend displayValue preservation (regression) ──────────────────

describe("displayValue preservation", () => {
  it("backend displayValue is preserved as values.full when no rankDerivedValue is stamped", () => {
    // When the backend has NOT stamped a rankDerivedValue, the
    // materializer falls back to displayValue / finalAdjusted for
    // values.full.  This case exercises that fallback.
    const data = {
      playersArray: [
        {
          displayName: "Josh Allen",
          position: "QB",
          values: { rawComposite: 8500, finalAdjusted: 9100, overall: 9100, displayValue: 9500 },
          canonicalSiteValues: { ktc: 8500 },
          canonicalConsensusRank: 1,
        },
      ],
    };
    const rows = buildRows(data);
    const allen = rows[0];
    // Backend rankDerivedValue missing → displayValue (9500) wins.
    expect(allen.values.full).toBe(9500);
  });

  it("computedConsensusRank (row.rank) is assigned after sort", () => {
    const data = {
      playersArray: [
        withStamps({ displayName: "A", position: "QB", values: { finalAdjusted: 9000, rawComposite: 9000, overall: 9000 }, canonicalSiteValues: { ktc: 9000 } }, 1, 9000),
        withStamps({ displayName: "B", position: "RB", values: { finalAdjusted: 5000, rawComposite: 5000, overall: 5000 }, canonicalSiteValues: { ktc: 5000 } }, 2, 5000),
      ],
    };
    const rows = buildRows(data);
    expect(rows[0].rank).toBe(1);
    expect(rows[1].rank).toBe(2);
  });

  it("rankDerivedValue pass-through forwards backend value verbatim", () => {
    const data = {
      playersArray: [
        withStamps({ displayName: "A", position: "QB", values: { finalAdjusted: 9000, rawComposite: 9000, overall: 9000 }, canonicalSiteValues: { ktc: 9000 } }, 1, 9999),
      ],
    };
    const rows = buildRows(data);
    expect(rows[0].rankDerivedValue).toBe(9999);
  });

  it("legacy players dict is also materialized from backend-stamped fields", () => {
    // Legacy-path fixture — the backend's ``_mirror_trust_to_legacy``
    // pass copies rank stamps onto the legacy ``players`` dict as
    // ``_canonicalConsensusRank`` / ``rankDerivedValue``.
    const data = {
      players: {
        "Josh Allen": {
          _composite: 8500,
          _rawComposite: 8500,
          _finalAdjusted: 9100,
          _sites: 6,
          _canonicalSiteValues: { ktc: 8500 },
          _canonicalConsensusRank: 1,
          rankDerivedValue: 9999,
          position: "QB",
        },
      },
      sleeper: { positions: { "Josh Allen": "QB" } },
      sites: [{ key: "ktc" }],
    };
    const rows = buildRows(data);
    // The materializer overwrites values.full with the backend
    // rankDerivedValue (single-value pipe).
    expect(rows[0].values.full).toBe(9999);
    expect(rows[0].canonicalConsensusRank).toBe(1);
    expect(rows[0].rankDerivedValue).toBe(9999);
  });
});

// ── Rank precedence (resolvedRank) ──────────────────────────────────

describe("resolvedRank", () => {
  it("canonicalConsensusRank wins when present", () => {
    const row = { canonicalConsensusRank: 5, computedConsensusRank: 10 };
    expect(resolvedRank(row)).toBe(5);
  });

  it("falls back to computedConsensusRank when canonicalConsensusRank is null", () => {
    const row = { canonicalConsensusRank: null, computedConsensusRank: 10 };
    expect(resolvedRank(row)).toBe(10);
  });

  it("falls back to Infinity when both are null/missing", () => {
    expect(resolvedRank({})).toBe(Infinity);
    expect(resolvedRank({ canonicalConsensusRank: null })).toBe(Infinity);
  });

  it("handles undefined row gracefully", () => {
    expect(resolvedRank(null)).toBe(Infinity);
    expect(resolvedRank(undefined)).toBe(Infinity);
  });
});

// ── computedConsensusRank field ──────────────────────────────────────

describe("computedConsensusRank", () => {
  it("is assigned as explicit field on every row from playersArray path", () => {
    const data = {
      playersArray: [
        withStamps({ displayName: "A", position: "QB", values: { finalAdjusted: 9000, rawComposite: 9000, overall: 9000 }, canonicalSiteValues: { ktc: 9000 } }, 1, 9000),
        withStamps({ displayName: "B", position: "RB", values: { finalAdjusted: 5000, rawComposite: 5000, overall: 5000 }, canonicalSiteValues: { ktc: 5000 } }, 2, 5000),
      ],
    };
    const rows = buildRows(data);
    expect(rows[0].computedConsensusRank).toBe(1);
    expect(rows[1].computedConsensusRank).toBe(2);
  });

  it("is assigned as explicit field on every row from legacy path", () => {
    const data = {
      players: {
        "A": { _rawComposite: 9000, _finalAdjusted: 9000, _sites: 3, _canonicalSiteValues: { ktc: 9000 }, position: "QB", _canonicalConsensusRank: 1, rankDerivedValue: 9000 },
        "B": { _rawComposite: 5000, _finalAdjusted: 5000, _sites: 2, _canonicalSiteValues: { ktc: 5000 }, position: "RB", _canonicalConsensusRank: 2, rankDerivedValue: 5000 },
      },
      sleeper: { positions: { "A": "QB", "B": "RB" } },
    };
    const rows = buildRows(data);
    expect(rows[0].computedConsensusRank).toBe(1);
    expect(rows[1].computedConsensusRank).toBe(2);
  });

  it("row.rank uses canonicalConsensusRank when present, else computedConsensusRank", () => {
    const data = {
      playersArray: [
        {
          displayName: "Canonical",
          position: "QB",
          canonicalConsensusRank: 42,
          rankDerivedValue: 5100,
          sourceRanks: { ktc: 42 },
          values: { finalAdjusted: 9000, rawComposite: 9000, overall: 9000 },
          canonicalSiteValues: { ktc: 9000 },
        },
        {
          displayName: "Computed",
          position: "RB",
          canonicalConsensusRank: 2,
          rankDerivedValue: 9800,
          sourceRanks: { ktc: 2 },
          values: { finalAdjusted: 5000, rawComposite: 5000, overall: 5000 },
          canonicalSiteValues: { ktc: 5000 },
        },
      ],
    };
    const rows = buildRows(data);
    const canonical = rows.find(r => r.name === "Canonical");
    const computed = rows.find(r => r.name === "Computed");
    // canonicalConsensusRank (42) wins over computedConsensusRank
    expect(canonical.rank).toBe(42);
    // Sort order: Computed (rank 2) comes first; Canonical (rank 42) second.
    expect(canonical.computedConsensusRank).toBe(2);
    expect(computed.canonicalConsensusRank).toBe(2);
    expect(computed.rank).toBe(2);
    expect(computed.computedConsensusRank).toBe(1);
  });

  it("mixed offense + IDP rows sort by backend canonicalConsensusRank", () => {
    // Backend already ranks offense + IDP together in the unified
    // board.  The materializer preserves that order.
    const data = {
      playersArray: [
        withStamps({ displayName: "QB Star", position: "QB", values: { finalAdjusted: 9000, rawComposite: 9000, overall: 9000 }, canonicalSiteValues: { ktc: 9000 } }, 2, 9900),
        withStamps({ displayName: "DL Star", position: "DL", values: { finalAdjusted: 6000, rawComposite: 6000, overall: 6000 }, canonicalSiteValues: { idpTradeCalc: 5800 } }, 1, 9999),
        withStamps({ displayName: "LB Star", position: "LB", values: { finalAdjusted: 5000, rawComposite: 5000, overall: 5000 }, canonicalSiteValues: { idpTradeCalc: 4000 } }, 3, 9000),
      ],
    };
    const rows = buildRows(data);
    expect(rows[0].name).toBe("DL Star");
    expect(rows[1].name).toBe("QB Star");
    expect(rows[2].name).toBe("LB Star");
    expect(rows[0].canonicalConsensusRank).toBe(1);
    expect(rows[1].canonicalConsensusRank).toBe(2);
    expect(rows[2].canonicalConsensusRank).toBe(3);
  });

  it("IDP players without a backend rank land at the end with null rank", () => {
    // An IDP row the backend could not rank (no source values at
    // all) still materializes, but with canonicalConsensusRank=null.
    // buildRows sorts null-rank rows to the end.
    const data = {
      playersArray: [
        withStamps({ displayName: "Real DL", position: "DL", values: { finalAdjusted: 5000, rawComposite: 5000, overall: 5000 }, canonicalSiteValues: { idpTradeCalc: 5000 } }, 1, 9999),
        {
          displayName: "Mystery DL",
          position: "DL",
          values: { finalAdjusted: 100, rawComposite: 100, overall: 100 },
          canonicalSiteValues: {},
          canonicalConsensusRank: null,
          rankDerivedValue: null,
          sourceRanks: {},
        },
      ],
    };
    const rows = buildRows(data);
    expect(rows[0].name).toBe("Real DL");
    expect(rows[1].name).toBe("Mystery DL");
    expect(rows[1].canonicalConsensusRank).toBeNull();
    expect(rows[1].rankDerivedValue).toBeFalsy();
  });
});

// ── fetchDynastyData response normalization (production regression) ──

describe("fetchDynastyData", () => {
  afterEach(() => {
    globalThis.fetch = undefined;
    _resetBaseContractCache();
  });

  it("normalizes unwrapped Python backend contract to { ok, source, data }", async () => {
    // Simulate Python backend returning raw contract (no { ok, source, data } wrapper)
    const rawContract = {
      version: 4,
      date: "2026-04-07",
      scrapeTimestamp: "2026-04-07T21:14:51",
      players: { "Josh Allen": { _composite: 8500, _sites: 6 } },
      playersArray: [{ displayName: "Josh Allen", position: "QB", values: { overall: 8500 } }],
      playerCount: 1,
      dataSource: { type: "scrape", path: "/data/latest", loadedAt: "2026-04-07T21:15:00Z" },
    };
    globalThis.fetch = async () => ({ ok: true, json: async () => rawContract });

    const result = await fetchDynastyData();
    expect(result.ok).toBe(true);
    expect(result.source).toBe("backend:scrape");
    expect(result.data).toBe(rawContract);
    expect(result.data.players).toBeDefined();
    expect(result.data.playersArray).toBeDefined();
  });

  it("passes through already-wrapped Next.js route response", async () => {
    const wrapped = {
      ok: true,
      source: "backend:http://127.0.0.1:8000/api/data?view=app",
      data: {
        players: { "Josh Allen": { _composite: 8500 } },
        version: 4,
      },
    };
    globalThis.fetch = async () => ({ ok: true, json: async () => wrapped });

    const result = await fetchDynastyData();
    expect(result.ok).toBe(true);
    expect(result.source).toBe("backend:http://127.0.0.1:8000/api/data?view=app");
    expect(result.data.players).toBeDefined();
  });

  it("normalizes unwrapped contract without dataSource to date-based source", async () => {
    const rawContract = {
      version: 4,
      date: "2026-04-07",
      players: { "Josh Allen": { _composite: 8500 } },
    };
    globalThis.fetch = async () => ({ ok: true, json: async () => rawContract });

    const result = await fetchDynastyData();
    expect(result.ok).toBe(true);
    expect(result.source).toBe("contract:2026-04-07");
    expect(result.data).toBe(rawContract);
  });

  it("buildRows produces rows from unwrapped backend contract (production regression)", () => {
    const rawContract = {
      version: 4,
      date: "2026-04-07",
      players: {
        "Josh Allen": {
          _composite: 8500,
          _rawComposite: 8500,
          _finalAdjusted: 9100,
          _sites: 6,
          _canonicalSiteValues: { ktc: 8500 },
          _canonicalConsensusRank: 1,
          rankDerivedValue: 9999,
        },
      },
      sleeper: { positions: { "Josh Allen": "QB" } },
    };

    const rows = buildRows(rawContract);
    expect(rows.length).toBe(1);
    expect(rows[0].name).toBe("Josh Allen");
    expect(rows[0].pos).toBe("QB");
    expect(rows[0].values.full).toBe(9999);
  });
});

// ── Unsupported position exclusion ──────────────────────────────────

describe("unsupported positions excluded from buildRows", () => {
  const UNSUPPORTED = ["OL", "OT", "OG", "C", "G", "T", "LS", "K", "P"];

  it("excludes all unsupported positions from legacy path", () => {
    const players = {};
    const positions = {};
    for (const pos of UNSUPPORTED) {
      const name = `Test ${pos}`;
      players[name] = {
        _composite: 7000,
        _rawComposite: 7000,
        _finalAdjusted: 7000,
        _sites: 1,
        position: pos,
        _canonicalSiteValues: { ktc: 7000 },
        _canonicalConsensusRank: 500,
        rankDerivedValue: 500,
      };
      positions[name] = pos;
    }
    // Add one supported player as anchor
    players["Real QB"] = {
      _composite: 9000,
      _rawComposite: 9000,
      _finalAdjusted: 9000,
      _sites: 1,
      position: "QB",
      _canonicalSiteValues: { ktc: 9000 },
      _canonicalConsensusRank: 1,
      rankDerivedValue: 9999,
    };
    positions["Real QB"] = "QB";

    const rows = buildRows({ players, sleeper: { positions } });
    const names = rows.map((r) => r.name);
    expect(names).toContain("Real QB");
    for (const pos of UNSUPPORTED) {
      expect(names).not.toContain(`Test ${pos}`);
    }
  });

  it("excludes unsupported positions from playersArray path", () => {
    const playersArray = [
      {
        displayName: "OL Guy",
        position: "OL",
        assetClass: "offense",
        sourceCount: 1,
        values: { rawComposite: 7000, finalAdjusted: 7000, overall: 7000 },
        canonicalSiteValues: { ktc: 7000 },
        canonicalConsensusRank: null,
      },
      {
        displayName: "Real WR",
        position: "WR",
        assetClass: "offense",
        sourceCount: 1,
        values: { rawComposite: 8000, finalAdjusted: 8000, overall: 8000 },
        canonicalSiteValues: { ktc: 8000 },
        canonicalConsensusRank: 1,
      },
    ];
    const rows = buildRows({ playersArray });
    expect(rows.length).toBe(1);
    expect(rows[0].name).toBe("Real WR");
  });

  it("supported positions still rank correctly", () => {
    const supported = ["QB", "RB", "WR", "TE", "DL", "LB", "DB"];
    const playersArray = supported.map((pos, i) => ({
      displayName: `Player ${pos}`,
      position: pos,
      assetClass: pos === "DL" || pos === "LB" || pos === "DB" ? "idp" : "offense",
      sourceCount: 1,
      values: { rawComposite: 9000 - i * 100, finalAdjusted: 9000 - i * 100, overall: 9000 - i * 100 },
      canonicalSiteValues: { ktc: 9000 - i * 100 },
      canonicalConsensusRank: i + 1,
    }));
    const rows = buildRows({ playersArray });
    expect(rows.length).toBe(supported.length);
    for (const pos of supported) {
      expect(rows.find((r) => r.pos === pos)).toBeDefined();
    }
  });

  it("unsupported positions are dropped before materialization", () => {
    // An OL row with a backend stamp should still be excluded — the
    // frontend ``classifyPos`` filter runs before stamp checks.
    const players = {
      "OL Star": {
        _composite: 9999,
        _rawComposite: 9999,
        _finalAdjusted: 9999,
        _sites: 1,
        position: "OL",
        _canonicalSiteValues: { ktc: 9999 },
        _canonicalConsensusRank: 500,
        rankDerivedValue: 500,
      },
      "Real QB": {
        _composite: 5000,
        _rawComposite: 5000,
        _finalAdjusted: 5000,
        _sites: 1,
        position: "QB",
        _canonicalSiteValues: { ktc: 5000 },
        _canonicalConsensusRank: 1,
        rankDerivedValue: 9999,
      },
    };
    const rows = buildRows({
      players,
      sleeper: { positions: { "OL Star": "OL", "Real QB": "QB" } },
    });
    // OL excluded entirely from rows
    expect(rows.find((r) => r.name === "OL Star")).toBeUndefined();
    // QB should be rank 1
    const qb = rows.find((r) => r.name === "Real QB");
    expect(qb).toBeDefined();
    expect(qb.canonicalConsensusRank).toBe(1);
  });
});

// ── normalizePos punter mapping ─────────────────────────────────────

describe("normalizePos punter mapping", () => {
  it("maps P → K", () => {
    expect(normalizePos("P")).toBe("K");
  });
});

// ── IDP multi-position priority (DL > DB > LB) ─────────────────────

describe("resolveIdpPosition (IDP multi-position priority)", () => {
  // Import lazily so this block doesn't interfere with the shared
  // fetch mock at the top of the file.
  let resolveIdpPosition;
  beforeAll(async () => {
    ({ resolveIdpPosition } = await import("@/lib/dynasty-data"));
  });

  it("collapses DL+LB to DL no matter which side or notation", () => {
    expect(resolveIdpPosition("DL", "LB")).toBe("DL");
    expect(resolveIdpPosition("DL/LB")).toBe("DL");
    expect(resolveIdpPosition(["DL", "LB"])).toBe("DL");
    expect(resolveIdpPosition("LB,DL")).toBe("DL");
    expect(resolveIdpPosition("LB|DL")).toBe("DL");
  });

  it("collapses LB+DB to DB", () => {
    expect(resolveIdpPosition("LB", "DB")).toBe("DB");
    expect(resolveIdpPosition("LB/CB")).toBe("DB");
    expect(resolveIdpPosition(["OLB", "S"])).toBe("DB");
    expect(resolveIdpPosition("LB,CB")).toBe("DB");
    expect(resolveIdpPosition("LB|CB")).toBe("DB");
  });

  it("DL beats DB", () => {
    expect(resolveIdpPosition("DL", "DB")).toBe("DL");
    expect(resolveIdpPosition("DE", "CB")).toBe("DL");
  });

  it("exclusive LB stays LB", () => {
    expect(resolveIdpPosition("LB")).toBe("LB");
    expect(resolveIdpPosition("OLB")).toBe("LB");
    expect(resolveIdpPosition(["LB"])).toBe("LB");
  });

  it("non-IDP inputs return empty string", () => {
    expect(resolveIdpPosition("QB")).toBe("");
    expect(resolveIdpPosition(["WR", "RB"])).toBe("");
    expect(resolveIdpPosition(null)).toBe("");
    expect(resolveIdpPosition("")).toBe("");
    expect(resolveIdpPosition([])).toBe("");
  });

  it("refuses LB when any non-IDP token is mixed in", () => {
    // Product rule: LB only when exclusively LB-eligible.
    expect(resolveIdpPosition("QB", "LB")).toBe("");
    expect(resolveIdpPosition(["QB", "LB"])).toBe("");
    expect(resolveIdpPosition("QB/LB")).toBe("");
    expect(resolveIdpPosition("LB,WR")).toBe("");
    expect(resolveIdpPosition("LB|TE")).toBe("");
  });

  it("DL and DB still win even with non-IDP context", () => {
    expect(resolveIdpPosition("QB", "DL")).toBe("DL");
    expect(resolveIdpPosition("WR", "CB")).toBe("DB");
    expect(resolveIdpPosition("TE", "EDGE")).toBe("DL");
  });

  it("normalizePos routes IDP multi-positions through the priority", () => {
    expect(normalizePos("DL/LB")).toBe("DL");
    expect(normalizePos("LB/CB")).toBe("DB");
    expect(normalizePos("LB,CB")).toBe("DB");
    expect(normalizePos("LB")).toBe("LB");
    // Non-IDP multi-strings fall through to the single-token path.
    expect(normalizePos("QB")).toBe("QB");
  });
});

describe("source vendor grouping", () => {
  it("maps every multi-board vendor's sub-sources to the same vendor id", () => {
    // DLF ships four sibling boards; they must all fold back to "dlf".
    expect(vendorForSource("dlfSf")).toBe("dlf");
    expect(vendorForSource("dlfIdp")).toBe("dlf");
    expect(vendorForSource("dlfRookieSf")).toBe("dlf");
    expect(vendorForSource("dlfRookieIdp")).toBe("dlf");

    // Flock vet board is mapped.  The rookie sibling
    // (flockFantasySfRookies) is still on PR #188 — the vendor map
    // intentionally omits it until that merges so this test stays in
    // lockstep with ``main``.
    expect(vendorForSource("flockFantasySf")).toBe("flock");

    // FBG and DraftSharks each publish SF + IDP — same vendor.
    expect(vendorForSource("footballGuysSf")).toBe("footballGuys");
    expect(vendorForSource("footballGuysIdp")).toBe("footballGuys");
    expect(vendorForSource("draftSharks")).toBe("draftSharks");
    expect(vendorForSource("draftSharksIdp")).toBe("draftSharks");

    // FantasyPros SF + IDP — same vendor.  Fitzmaurice is a separate
    // FP article with its own scrape path and display-invariant
    // identity, so it stands alone.
    expect(vendorForSource("fantasyProsSf")).toBe("fantasyPros");
    expect(vendorForSource("fantasyProsIdp")).toBe("fantasyPros");
    expect(vendorForSource("fantasyProsFitzmaurice")).toBe(
      "fantasyProsFitzmaurice",
    );
  });

  it("falls back to the source key itself for single-board vendors", () => {
    expect(vendorForSource("ktc")).toBe("ktc");
    expect(vendorForSource("idpTradeCalc")).toBe("idpTradeCalc");
    expect(vendorForSource("dynastyDaddySf")).toBe("dynastyDaddySf");
    expect(vendorForSource("dynastyNerdsSfTep")).toBe("dynastyNerdsSfTep");
    expect(vendorForSource("yahooBoone")).toBe("yahooBoone");
  });

  it("returns empty string for empty/undefined source keys", () => {
    expect(vendorForSource("")).toBe("");
    expect(vendorForSource(undefined)).toBe("");
    expect(vendorForSource(null)).toBe("");
  });

  it("handles unknown source keys by returning them unchanged", () => {
    // A new source added to the backend before the vendor map is
    // updated must still show up as its own row (single-board
    // fallback), never crash.
    expect(vendorForSource("newExperimentalSource")).toBe(
      "newExperimentalSource",
    );
  });

  it("exports explicit display labels for every multi-board vendor", () => {
    const multiBoardVendors = new Set(Object.values(SOURCE_VENDORS));
    for (const vendor of multiBoardVendors) {
      expect(SOURCE_VENDOR_LABELS[vendor]).toBeTruthy();
    }
  });

  it("every SOURCE_VENDORS key corresponds to a registered source", () => {
    // Prevents typos / stale entries in the vendor map when sources
    // get renamed on the backend.
    const registeredKeys = new Set(RANKING_SOURCES.map((s) => s.key));
    for (const key of Object.keys(SOURCE_VENDORS)) {
      expect(registeredKeys.has(key)).toBe(true);
    }
  });
});
