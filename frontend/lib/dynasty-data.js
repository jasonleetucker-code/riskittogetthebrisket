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

export function normalizePos(pos) {
  const p = String(pos || "").toUpperCase();
  if (["DE", "DT", "EDGE", "NT"].includes(p)) return "DL";
  if (["CB", "S", "FS", "SS"].includes(p)) return "DB";
  if (["OLB", "ILB"].includes(p)) return "LB";
  return p;
}

export function classifyPos(pos) {
  const p = normalizePos(pos);
  if (OFFENSE.has(p)) return "offense";
  if (IDP.has(p)) return "idp";
  if (p === "PICK") return "pick";
  return "other";
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
// It mirrors the backend logic: rank each player within their source,
// convert to normalized value via rankToValue(), then sort all players
// into one unified board by that normalized value.
const OVERALL_RANK_LIMIT = 800;
const SOURCE_KEYS = ["ktc", "idpTradeCalc"];

function computeUnifiedRanks(rows) {
  // Per-source ordinal ranking
  const sourceRanks = new Map(); // row index -> { sourceKey: ordinalRank }

  for (const sourceKey of SOURCE_KEYS) {
    const eligible = [];
    rows.forEach((r, idx) => {
      if (!r.pos || r.pos === "?" || r.pos === "PICK" || r.pos === "K") return;
      const val = Number(r.canonicalSites?.[sourceKey]);
      if (Number.isFinite(val) && val > 0) eligible.push({ idx, val });
    });
    eligible.sort((a, b) => b.val - a.val);
    eligible.forEach((e, rank) => {
      if (!sourceRanks.has(e.idx)) sourceRanks.set(e.idx, {});
      sourceRanks.get(e.idx)[sourceKey] = rank + 1;
    });
  }

  // Compute normalized value and collect for unified sort
  const ranked = [];
  for (const [idx, ranks] of sourceRanks) {
    const normValues = Object.values(ranks).map((r) => rankToValue(r));
    const blended = normValues.reduce((s, v) => s + v, 0) / normValues.length;
    ranked.push({ idx, blended, ranks });
  }
  ranked.sort((a, b) => b.blended - a.blended || rows[a.idx].name.localeCompare(rows[b.idx].name));

  // Assign unified ranks — prefer backend values when present
  ranked.slice(0, OVERALL_RANK_LIMIT).forEach((entry, i) => {
    const r = rows[entry.idx];
    const backendRank = Number(r.raw?.canonicalConsensusRank || r.canonicalConsensusRank);
    const backendValue = Number(r.raw?.rankDerivedValue);

    // Blended source rank: mean of the per-source ordinal ranks (with decimals)
    const sourceRankValues = Object.values(entry.ranks);
    const blendedSourceRank = sourceRankValues.reduce((s, v) => s + v, 0) / sourceRankValues.length;

    r.canonicalConsensusRank = (Number.isInteger(backendRank) && backendRank > 0)
      ? backendRank : (i + 1);
    r.rankDerivedValue = (Number.isFinite(backendValue) && backendValue > 0)
      ? backendValue : Math.round(entry.blended);
    r.sourceRanks = entry.ranks;
    r.blendedSourceRank = blendedSourceRank;
    r.sourceCount = sourceRankValues.length;

    // Backward compat
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
      if (pos === "K") continue;

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
    if (pos === "K") continue;

    const values = inferValueBundle(player);
    const canonicalSites = player._canonicalSiteValues && typeof player._canonicalSiteValues === "object" ? player._canonicalSiteValues : {};

    rows.push({
      name,
      pos: pos || "?",
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
