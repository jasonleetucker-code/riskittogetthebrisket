// ── RANKINGS — UNIFIED BOARD ─────────────────────────────────────────────────
// This file (frontend/lib/dynasty-data.js) is the canonical frontend home for:
//   • rankToValue()         — Hill-style rank-to-value formula (offline fallback)
//   • computeUnifiedRanks() — per-source rank → normalize → unified overall sort
//   • OVERALL_RANK_LIMIT    — overall board cap (800)
//
// The backend authority is src/api/data_contract.py (_compute_unified_rankings).
//
// !! When changing ranking logic, formula constants, or eligibility rules !!
// !! you MUST update BOTH files and BOTH test suites to stay in sync.     !!
//   • JS tests:     frontend/__tests__/dynasty-data.test.js
//   • Python tests: tests/api/test_rankings_our_rank.py
// ─────────────────────────────────────────────────────────────────────────────

const OFFENSE = new Set(["QB", "RB", "WR", "TE"]);
const IDP = new Set(["DL", "DE", "DT", "LB", "DB", "CB", "S", "EDGE"]);
// Positions that may never enter the ranked board or user-facing surfaces.
const UNSUPPORTED = new Set(["OL", "OT", "OG", "C", "G", "T", "LS"]);

export function normalizePos(pos) {
  const p = String(pos || "").toUpperCase();
  if (["DE", "DT", "EDGE", "NT"].includes(p)) return "DL";
  if (["CB", "S", "FS", "SS"].includes(p)) return "DB";
  if (["OLB", "ILB"].includes(p)) return "LB";
  if (p === "P") return "K";
  return p;
}

export function classifyPos(pos) {
  const p = normalizePos(pos);
  if (OFFENSE.has(p)) return "offense";
  if (IDP.has(p)) return "idp";
  if (p === "PICK") return "pick";
  if (p === "K" || UNSUPPORTED.has(p)) return "excluded";
  return "other";
}

// Positions eligible for the unified board.  Mirrors
// `_RANKABLE_POSITIONS` in src/api/data_contract.py.  PICK is included
// here because KTC prices rookie picks natively and the overall_offense
// scope admits them.
const RANKABLE = new Set(["QB", "RB", "WR", "TE", "DL", "LB", "DB", "PICK"]);

// ── Source scope tokens (mirror src/canonical/idp_backbone.py) ──────
// See src/canonical/idp_backbone.py for the authoritative definitions.
// These MUST stay in sync with VALID_SOURCE_SCOPES on the backend.
export const SOURCE_SCOPE_OVERALL_OFFENSE = "overall_offense";
export const SOURCE_SCOPE_OVERALL_IDP = "overall_idp";
export const SOURCE_SCOPE_POSITION_IDP = "position_idp";

// Translation method tokens — also mirror the Python constants.
export const TRANSLATION_DIRECT = "direct";
export const TRANSLATION_EXACT = "exact";
export const TRANSLATION_INTERPOLATED = "interpolated";
export const TRANSLATION_EXTRAPOLATED = "extrapolated";
export const TRANSLATION_FALLBACK = "fallback";

const IDP_POSITION_GROUPS = ["DL", "LB", "DB"];
const OFFENSE_POSITIONS = new Set(["QB", "RB", "WR", "TE"]);
const IDP_POSITIONS_SET = new Set(IDP_POSITION_GROUPS);

// Scope eligibility predicate — mirrors _scope_eligible() in
// src/api/data_contract.py.  A row only receives a rank from a source
// if its position falls within the source's scope.
function scopeEligible(pos, scope, positionGroup) {
  const p = String(pos || "").toUpperCase();
  if (scope === SOURCE_SCOPE_OVERALL_OFFENSE) {
    return OFFENSE_POSITIONS.has(p) || p === "PICK";
  }
  if (scope === SOURCE_SCOPE_OVERALL_IDP) {
    return IDP_POSITIONS_SET.has(p);
  }
  if (scope === SOURCE_SCOPE_POSITION_IDP) {
    return Boolean(positionGroup) && p === String(positionGroup).toUpperCase();
  }
  return false;
}

// ── IDP backbone construction ───────────────────────────────────────
// Mirrors build_backbone_from_rows() in src/canonical/idp_backbone.py.
// Walks every row, keeps IDP entries with a positive value in the
// backbone source, sorts descending, and records per-position-group
// ladders of overall-IDP ranks.
function buildIdpBackbone(rows, sourceKey) {
  const ladders = {};
  for (const pg of IDP_POSITION_GROUPS) ladders[pg] = [];
  if (!sourceKey) return { ladders, depth: 0 };

  const eligible = [];
  rows.forEach((r) => {
    const pos = String(r?.pos || "").toUpperCase();
    if (!IDP_POSITIONS_SET.has(pos)) return;
    const val = Number(r?.canonicalSites?.[sourceKey]);
    if (!Number.isFinite(val) || val <= 0) return;
    eligible.push({ val, pos, name: String(r?.name || "") });
  });
  eligible.sort((a, b) => b.val - a.val || a.name.toLowerCase().localeCompare(b.name.toLowerCase()));

  let depth = 0;
  eligible.forEach((e, i) => {
    const overall = i + 1;
    if (ladders[e.pos]) ladders[e.pos].push(overall);
    depth = overall;
  });
  return { ladders, depth };
}

// ── Position-rank translation ───────────────────────────────────────
// Mirrors translate_position_rank() in src/canonical/idp_backbone.py.
// Translates a within-position rank (e.g. DL4) into a synthetic
// overall-IDP rank using the backbone ladder.  Integer ranks inside
// the ladder are exact anchors; fractional ranks interpolate linearly;
// ranks past the tail extrapolate with the average of the last few
// steps; empty ladders fall back to a pass-through.
function translatePositionRank(positionRank, ladder) {
  if (!Array.isArray(ladder) || ladder.length === 0) {
    const safe = Math.max(1, Math.round(Math.max(1, Number(positionRank) || 1)));
    return { rank: safe, method: TRANSLATION_FALLBACK };
  }

  let pr = Number(positionRank);
  if (!Number.isFinite(pr) || pr < 1) pr = 1;

  const n = ladder.length;
  // Integer exact anchor
  if (pr === Math.floor(pr) && pr >= 1 && pr <= n) {
    return { rank: Math.max(1, ladder[pr - 1]), method: TRANSLATION_EXACT };
  }
  // Interpolation inside the ladder
  if (pr >= 1 && pr <= n) {
    const lowIdx = Math.floor(pr) - 1;
    const frac = pr - Math.floor(pr);
    const low = ladder[lowIdx];
    const high = ladder[Math.min(lowIdx + 1, n - 1)];
    const synthetic = low + (high - low) * frac;
    return { rank: Math.max(1, Math.round(synthetic)), method: TRANSLATION_INTERPOLATED };
  }
  // Extrapolation past the tail
  let step;
  if (n === 1) {
    step = Math.max(1, ladder[0]);
  } else {
    const tail = Math.min(5, n - 1);
    let sum = 0;
    for (let i = 1; i <= tail; i++) sum += ladder[n - i] - ladder[n - i - 1];
    step = Math.max(1, sum / tail);
  }
  const overshoot = pr - n;
  let synthetic = Math.round(ladder[n - 1] + step * overshoot);
  if (synthetic <= ladder[n - 1]) synthetic = ladder[n - 1] + 1;
  return { rank: Math.max(1, synthetic), method: TRANSLATION_EXTRAPOLATED };
}

// Coverage-aware blend weight — mirrors coverage_weight() in
// src/canonical/idp_backbone.py.  Shallow positional lists get scaled
// down linearly; full-board sources keep their declared weight.
const MIN_FULL_COVERAGE_DEPTH = 60;
function coverageWeight(declaredWeight, depth) {
  const w = Math.max(0, Number(declaredWeight) || 0);
  if (depth === null || depth === undefined) return w;
  const d = Number(depth);
  if (!Number.isFinite(d)) return w;
  if (d <= 0) return 0;
  const factor = Math.min(1, d / Math.max(1, MIN_FULL_COVERAGE_DEPTH));
  return w * factor;
}

export function inferValueBundle(player = {}) {
  const raw = Number(player._rawComposite ?? player._rawMarketValue ?? player._composite ?? 0) || 0;
  // Prefer 1–9999 display value; fall back to internal calibrated value
  const display = Number(player._canonicalDisplayValue ?? 0) || 0;
  const internal = Number(player._finalAdjusted ?? player._composite ?? raw) || raw;
  const full = display || internal;
  return {
    raw: Math.round(raw),
    full: Math.round(full),
  };
}

export function getSiteKeys(data) {
  const sites = Array.isArray(data?.sites) ? data.sites : [];
  return sites.map((s) => String(s?.key || "")).filter(Boolean);
}

// ── Rank precedence helper ────────────────────────────────────────────
// Single source of truth for rank resolution across all frontend surfaces.
// canonicalConsensusRank (backend-authored) wins when present; otherwise
// falls back to computedConsensusRank (sort-order rank assigned in buildRows).
export function resolvedRank(row) {
  return row?.canonicalConsensusRank ?? row?.computedConsensusRank ?? Infinity;
}

// ── Rank-to-value curve (OFFLINE FALLBACK ONLY) ───────────────────────
// PRIMARY authority: src/api/data_contract.py (_compute_unified_rankings)
// stamps canonicalConsensusRank + rankDerivedValue onto the API response
// using rank_to_value() in src/canonical/player_valuation.py.  This
// function is only invoked when backend fields are absent (stale data,
// offline mode, unit tests).
//
// Formula: value = max(1, min(9999, round(1 + 9998 / (1 + ((rank-1)/45)^1.10))))
//   • rank 1  → 9999 (exact; denominator = 1)
//   • midpoint (rank 45) → ~5000
//   • Hill-style: flatter at top, longer tail than inverse-power
//
// Tests: tests/api/test_rankings_our_rank.py
export function rankToValue(rank) {
  if (!rank || rank <= 0) return 0;
  return Math.max(1, Math.min(9999, Math.round(1 + 9998 / (1 + Math.pow((rank - 1) / 45, 1.10)))));
}

// ── Unified ranking (frontend fallback) ──────────────────────────────
// The backend (_compute_unified_rankings in data_contract.py) is the
// authoritative source for canonicalConsensusRank and rankDerivedValue.
// This function is only invoked as a fallback when backend fields are
// absent (stale data, offline mode).
//
// The logic mirrors the backend scope-aware pipeline end-to-end:
//   1. Build the IDP backbone ladder from the designated backbone
//      source (the first overall_idp source with isBackbone=true).
//   2. For each registered source, rank only rows eligible under its
//      scope (overall_offense / overall_idp / position_idp).  Position-
//      only sources translate their raw rank into a synthetic overall-
//      IDP rank via the backbone ladder.
//   3. Convert each effective rank through rankToValue(), then blend
//      sources using a coverage-aware weighted mean so shallow lists
//      never overpower deep boards.
//   4. Sort the unified board and stamp canonicalConsensusRank plus
//      transparency metadata (sourceRanks, sourceRankMeta, confidence,
//      market gap, anomaly flags, backward-compat ktcRank/idpRank).
//
// Source registry — keep in sync with `_RANKING_SOURCES` in
// src/api/data_contract.py.  Adding a new position-only source is a
// purely declarative change (add an entry here and on the backend).
const OVERALL_RANK_LIMIT = 800;
const RANKING_SOURCES = [
  {
    key: "ktc",
    displayName: "KeepTradeCut",
    scope: SOURCE_SCOPE_OVERALL_OFFENSE,
    positionGroup: null,
    depth: null,
    weight: 1.0,
    isBackbone: false,
  },
  {
    key: "idpTradeCalc",
    displayName: "IDP Trade Calculator",
    scope: SOURCE_SCOPE_OVERALL_IDP,
    positionGroup: null,
    depth: null,
    weight: 1.0,
    isBackbone: true,
  },
];

// Legacy export retained for any consumer that previously imported
// the flat source-key list.  New callers should use RANKING_SOURCES.
const SOURCE_KEYS = RANKING_SOURCES.map((s) => s.key);

function computeUnifiedRanks(rows) {
  // ── Phase 0: Build the IDP backbone from the designated source ──
  const backboneSrc = RANKING_SOURCES.find(
    (s) => s.scope === SOURCE_SCOPE_OVERALL_IDP && s.isBackbone
  );
  const backbone = backboneSrc
    ? buildIdpBackbone(rows, backboneSrc.key)
    : { ladders: { DL: [], LB: [], DB: [] }, depth: 0 };

  // ── Phase 1: Per-source ordinal ranking within scope ──
  const sourceRanksByRow = new Map(); // row idx -> { sourceKey: effectiveRank }
  const sourceMetaByRow = new Map();  // row idx -> { sourceKey: metaDict }

  for (const src of RANKING_SOURCES) {
    const eligible = [];
    rows.forEach((r, idx) => {
      if (!RANKABLE.has(r.pos)) return;
      if (!scopeEligible(r.pos, src.scope, src.positionGroup)) return;
      const val = Number(r.canonicalSites?.[src.key]);
      if (!Number.isFinite(val) || val <= 0) return;
      eligible.push({ idx, val });
    });
    eligible.sort((a, b) => b.val - a.val);

    eligible.forEach((e, rank) => {
      const rawRank = rank + 1;
      let effectiveRank = rawRank;
      let method = TRANSLATION_DIRECT;

      if (src.scope === SOURCE_SCOPE_POSITION_IDP && src.positionGroup) {
        const ladder = backbone.ladders[String(src.positionGroup).toUpperCase()] || [];
        const translated = translatePositionRank(rawRank, ladder);
        effectiveRank = translated.rank;
        method = translated.method;
      }

      if (!sourceRanksByRow.has(e.idx)) sourceRanksByRow.set(e.idx, {});
      if (!sourceMetaByRow.has(e.idx)) sourceMetaByRow.set(e.idx, {});
      sourceRanksByRow.get(e.idx)[src.key] = effectiveRank;
      sourceMetaByRow.get(e.idx)[src.key] = {
        scope: src.scope,
        positionGroup: src.positionGroup || null,
        rawRank,
        effectiveRank,
        method,
        ladderDepth:
          src.scope === SOURCE_SCOPE_POSITION_IDP && src.positionGroup
            ? (backbone.ladders[String(src.positionGroup).toUpperCase()] || []).length
            : null,
        backboneDepth: src.scope === SOURCE_SCOPE_POSITION_IDP ? backbone.depth : null,
        depth: src.depth ?? null,
        weight: Number(src.weight) || 0,
      };
    });
  }

  // ── Phase 2-3: Coverage-aware weighted Hill-curve blend ──
  const srcByKey = new Map(RANKING_SOURCES.map((s) => [s.key, s]));
  const ranked = [];
  for (const [idx, ranks] of sourceRanksByRow) {
    const meta = sourceMetaByRow.get(idx) || {};
    let weightedSum = 0;
    let weightTotal = 0;
    for (const [sourceKey, effRank] of Object.entries(ranks)) {
      const srcDef = srcByKey.get(sourceKey) || {};
      const declaredWeight = Number(srcDef.weight ?? 1);
      const effectiveWeight = coverageWeight(declaredWeight, srcDef.depth ?? null);
      const value = rankToValue(effRank);
      weightedSum += value * effectiveWeight;
      weightTotal += effectiveWeight;
      if (meta[sourceKey]) {
        meta[sourceKey].valueContribution = Math.round(value);
        meta[sourceKey].effectiveWeight = Math.round(effectiveWeight * 10000) / 10000;
      }
    }
    let blended;
    if (weightTotal > 0) {
      blended = weightedSum / weightTotal;
    } else {
      const vals = Object.values(ranks).map((r) => rankToValue(r));
      blended = vals.length ? vals.reduce((s, v) => s + v, 0) / vals.length : 0;
    }
    ranked.push({ idx, blended, ranks, meta });
  }

  // ── Phase 4: Unified sort + stamp ──
  ranked.sort(
    (a, b) =>
      b.blended - a.blended ||
      String(rows[a.idx].name || "").localeCompare(String(rows[b.idx].name || ""))
  );

  ranked.slice(0, OVERALL_RANK_LIMIT).forEach((entry, i) => {
    const r = rows[entry.idx];
    const backendRank = Number(r.raw?.canonicalConsensusRank || r.canonicalConsensusRank);
    const backendValue = Number(r.raw?.rankDerivedValue);

    const sourceRankValues = Object.values(entry.ranks);
    const blendedSourceRank =
      sourceRankValues.reduce((s, v) => s + v, 0) / sourceRankValues.length;

    r.canonicalConsensusRank =
      Number.isInteger(backendRank) && backendRank > 0 ? backendRank : i + 1;
    r.rankDerivedValue =
      Number.isFinite(backendValue) && backendValue > 0
        ? backendValue
        : Math.round(entry.blended);
    r.sourceRanks = entry.ranks;
    r.sourceRankMeta = entry.meta;
    r.blendedSourceRank = blendedSourceRank;
    r.sourceCount = sourceRankValues.length;

    // Backbone fallback caution: any position_idp source that had to
    // translate with an empty ladder marks the whole row.
    r.idpBackboneFallback = Object.values(entry.meta).some(
      (m) => m && m.method === TRANSLATION_FALLBACK
    );

    const spread =
      sourceRankValues.length >= 2
        ? Math.max(...sourceRankValues) - Math.min(...sourceRankValues)
        : null;
    r.sourceRankSpread = r.raw?.sourceRankSpread ?? spread;
    r.isSingleSource = r.raw?.isSingleSource ?? sourceRankValues.length === 1;
    r.hasSourceDisagreement =
      r.raw?.hasSourceDisagreement ?? (spread !== null && spread > 80);
    r.marketGapDirection = r.raw?.marketGapDirection ?? "none";
    r.marketGapMagnitude = r.raw?.marketGapMagnitude ?? null;

    if (r.raw?.confidenceBucket) {
      r.confidenceBucket = r.raw.confidenceBucket;
      r.confidenceLabel = r.raw.confidenceLabel || "";
    } else if (sourceRankValues.length >= 2 && spread !== null) {
      if (spread <= 30) {
        r.confidenceBucket = "high";
        r.confidenceLabel = "High — multi-source, tight agreement";
      } else if (spread <= 80) {
        r.confidenceBucket = "medium";
        r.confidenceLabel = "Medium — multi-source, moderate spread";
      } else {
        r.confidenceBucket = "low";
        r.confidenceLabel = "Low — single source or wide disagreement";
      }
    } else {
      r.confidenceBucket = "low";
      r.confidenceLabel = "Low — single source or wide disagreement";
    }
    r.anomalyFlags = Array.isArray(r.raw?.anomalyFlags) ? r.raw.anomalyFlags : [];

    // Backward compat: consumers still read ktcRank / idpRank directly.
    if (entry.ranks.ktc) r.ktcRank = entry.ranks.ktc;
    if (entry.ranks.idpTradeCalc) r.idpRank = entry.ranks.idpTradeCalc;
  });
}

export function buildRows(data) {
  const players = data?.players || {};
  const playersArray = Array.isArray(data?.playersArray) ? data.playersArray : [];
  const posMap = data?.sleeper?.positions || {};
  const rows = [];

  if (playersArray.length) {
    for (const player of playersArray) {
      if (!player || typeof player !== "object") continue;
      const name = String(player.displayName || player.canonicalName || "").trim();
      if (!name) continue;
      const pos = normalizePos(player.position || "");
      const cls = classifyPos(pos);
      if (cls === "excluded") continue;

      // Prefer 1–9999 display value; fall back to internal calibrated value
      const displayVal = Number(player?.values?.displayValue ?? 0) || 0;
      const internalVal = Number(
        player?.values?.finalAdjusted ?? player?.values?.overall ?? 0
      ) || 0;
      const values = {
        raw: Number(player?.values?.rawComposite ?? 0) || 0,
        full: displayVal || internalVal,
      };

      const canonicalSites =
        player.canonicalSiteValues && typeof player.canonicalSiteValues === "object"
          ? player.canonicalSiteValues
          : {};

      rows.push({
        name,
        pos: pos || "?",
        team: String(player.team || ""),
        age: Number(player.age) || null,
        rookie: Boolean(player.rookie),
        assetClass: String(player.assetClass || classifyPos(pos || "?")),
        values: {
          raw: Math.round(values.raw),
          full: Math.round(values.full),
        },
        // siteCount: intentionally preserved — used by trade calculator and
        // other non-rankings views.  Rankings pages hide this column, but the
        // field must remain on the row contract.  Do NOT remove it.
        siteCount: Number(player.sourceCount || 0),
        confidence: Number(player.marketConfidence ?? 0),
        marketLabel: "",
        canonicalSites,
        canonicalConsensusRank: Number(player.canonicalConsensusRank) || null,
        canonicalTierId: Number(player.canonicalTierId) || null,
        // Trust/transparency fields — pass through from backend contract.
        // These are backend-authoritative; the frontend preserves them as-is.
        confidenceBucket: String(player.confidenceBucket || "none"),
        confidenceLabel: String(player.confidenceLabel || ""),
        anomalyFlags: Array.isArray(player.anomalyFlags) ? player.anomalyFlags : [],
        isSingleSource: Boolean(player.isSingleSource),
        hasSourceDisagreement: Boolean(player.hasSourceDisagreement),
        blendedSourceRank: player.blendedSourceRank ?? null,
        sourceRankSpread: player.sourceRankSpread ?? null,
        marketGapDirection: String(player.marketGapDirection || "none"),
        marketGapMagnitude: player.marketGapMagnitude ?? null,
        // Identity quality fields — backend-authoritative
        identityConfidence: Number(player.identityConfidence ?? 0.7),
        identityMethod: String(player.identityMethod || "name_only"),
        quarantined: Boolean(player.quarantined),
        raw: player,
      });
    }

    computeUnifiedRanks(rows);
    // Sort by unified canonicalConsensusRank (backend-authoritative when present).
    rows.sort((a, b) => {
      const ra = a.canonicalConsensusRank ?? Infinity;
      const rb = b.canonicalConsensusRank ?? Infinity;
      if (ra !== rb) return ra - rb;
      return (b.values.full || 0) - (a.values.full || 0);
    });
    rows.forEach((r, i) => {
      r.computedConsensusRank = i + 1;
      r.rank = r.canonicalConsensusRank ?? r.computedConsensusRank;
    });
    return rows;
  }

  for (const [name, player] of Object.entries(players)) {
    if (!player || typeof player !== "object") continue;
    const isPick = /\b(20\d{2})\s+(early|mid|late)?\s*(1st|2nd|3rd|4th|5th|6th|round|r\d|pick)/i.test(name) || /^20\d{2}\s+pick/i.test(name);
    const pos = isPick ? "PICK" : normalizePos(posMap[name] || player.position || "");
    if (classifyPos(pos) === "excluded") continue;

    const values = inferValueBundle(player);
    const canonicalSites = player._canonicalSiteValues && typeof player._canonicalSiteValues === "object" ? player._canonicalSiteValues : {};

    rows.push({
      name,
      pos: pos || "?",
      team: String(player.team || ""),
      age: Number(player.age) || null,
      rookie: Boolean(player._formatFitRookie),
      assetClass: classifyPos(pos || "?"),
      values,
      // siteCount: intentionally preserved — used by trade calculator and
      // other non-rankings views.  Rankings pages hide this column, but the
      // field must remain on the row contract.  Do NOT remove it.
      siteCount: Number(player._sites || 0),
      confidence: Number(player._marketReliabilityScore ?? 0),
      marketLabel: String(player._marketReliabilityLabel || ""),
      canonicalSites,
      canonicalConsensusRank: Number(player._canonicalConsensusRank) || null,
      canonicalTierId: Number(player._canonicalTierId) || null,
      // Trust/transparency fields — prefer backend-mirrored values from
      // the legacy dict; fall back to safe defaults.  computeUnifiedRanks()
      // may further overwrite these for ranked players.
      confidenceBucket: String(player.confidenceBucket || "none"),
      confidenceLabel: String(player.confidenceLabel || ""),
      anomalyFlags: Array.isArray(player.anomalyFlags) ? player.anomalyFlags : [],
      isSingleSource: Boolean(player.isSingleSource),
      hasSourceDisagreement: Boolean(player.hasSourceDisagreement),
      blendedSourceRank: player.blendedSourceRank ?? null,
      sourceRankSpread: player.sourceRankSpread ?? null,
      marketGapDirection: String(player.marketGapDirection || "none"),
      marketGapMagnitude: player.marketGapMagnitude ?? null,
      identityConfidence: Number(player.identityConfidence ?? 0.7),
      identityMethod: String(player.identityMethod || "name_only"),
      quarantined: Boolean(player.quarantined),
      raw: player,
    });
  }

  computeUnifiedRanks(rows);
  rows.sort((a, b) => {
    const ra = a.canonicalConsensusRank ?? Infinity;
    const rb = b.canonicalConsensusRank ?? Infinity;
    if (ra !== rb) return ra - rb;
    return (b.values.full || 0) - (a.values.full || 0);
  });
  rows.forEach((r, i) => {
    r.computedConsensusRank = i + 1;
    r.rank = r.canonicalConsensusRank ?? r.computedConsensusRank;
  });
  return rows;
}

export async function fetchDynastyData() {
  const res = await fetch("/api/dynasty-data", { cache: "no-store" });
  if (!res.ok) {
    const txt = await res.text();
    throw new Error(`Failed to load dynasty data: ${res.status} ${txt}`);
  }
  const json = await res.json();

  // The Next.js API route wraps the payload: { ok, source, data: <contract> }
  // The Python backend alias returns the raw contract: { players, playersArray, version, ... }
  // Normalize both shapes to { ok, source, data }.
  if (json && typeof json === "object" && !json.data && (json.players || json.playersArray)) {
    return {
      ok: true,
      source: json.dataSource?.type
        ? `backend:${json.dataSource.type}`
        : json.date
          ? `contract:${json.date}`
          : "backend",
      data: json,
    };
  }

  return json;
}
