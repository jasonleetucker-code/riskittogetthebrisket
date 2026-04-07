// ── RANKINGS SINGLE SOURCE OF TRUTH ──────────────────────────────────────────
// This file (frontend/lib/dynasty-data.js) is the canonical home for:
//   • rankToValue()     — Hill-style rank-to-value formula
//   • computeKtcRanks() — KTC-only rank assignment (top 500, integer ranks)
//   • KTC_RANK_LIMIT    — hard cap (500)
//
// The Static legacy frontend has a parallel implementation in:
//   Static/js/runtime/10-rankings-and-picks.js (_rankToValue, KTC_LIMIT, buildFullRankings)
//
// !! When changing ranking logic, formula constants, or eligibility rules !!
// !! you MUST update BOTH files and BOTH test suites to stay in sync.     !!
//   • JS tests:     frontend/__tests__/dynasty-data.test.js
//   • Python tests: tests/api/test_rankings_our_rank.py (cross-checks both files)
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
  const scoring = Number(player._scoringAdjusted ?? raw) || raw;
  const scarcity = Number(player._scarcityAdjusted ?? scoring) || scoring;
  // Prefer 1–9999 display value; fall back to internal calibrated value
  const display = Number(player._canonicalDisplayValue ?? 0) || 0;
  const internal = Number(player._finalAdjusted ?? player._leagueAdjusted ?? scarcity) || scarcity;
  const full = display || internal;
  return {
    raw: Math.round(raw),
    scoring: Math.round(scoring),
    scarcity: Math.round(scarcity),
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
// falls back to computedConsensusRank (frontend row.rank from sort order).
export function resolvedRank(row) {
  return row?.canonicalConsensusRank ?? row?.rank ?? Infinity;
}

// ── Rank-to-value curve (OFFLINE FALLBACK ONLY) ───────────────────────
// PRIMARY authority: src/api/data_contract.py (_compute_ktc_rankings) stamps
// ktcRank + rankDerivedValue onto the API response using rank_to_value() in
// src/canonical/player_valuation.py.  This function is only invoked when the
// backend fields are absent (stale data, offline mode, unit tests).
//
// MUST stay byte-for-byte identical to _rankToValue() in:
//   Static/js/runtime/10-rankings-and-picks.js (~line 407)
//
// Formula: value = max(1, min(9999, round(1 + 9998 / (1 + ((rank-1)/45)^1.10))))
//   • rank 1  → 9999 (exact; denominator = 1)
//   • midpoint (rank 45) → ~5000
//   • Hill-style: flatter at top, longer tail than inverse-power
//
// Tests enforcing body-equality: tests/api/test_rankings_our_rank.py
//   TestFormulaAgreement::test_fallback_formula_bodies_are_identical
export function rankToValue(rank) {
  if (!rank || rank <= 0) return 0;
  return Math.max(1, Math.min(9999, Math.round(1 + 9998 / (1 + Math.pow((rank - 1) / 45, 1.10)))));
}

// ── KTC-only rank assignment ──────────────────────────────────────────
// Assigns integer ktcRank to the top KTC_RANK_LIMIT players sorted by
// KTC trade value descending.  Only players with:
//   • a valid positive canonicalSites.ktc value
//   • a resolved, non-"?" position (picks excluded)
// are eligible.  Players outside the limit get ktcRank = null.
const KTC_RANK_LIMIT = 500;

function computeKtcRanks(rows) {
  const eligible = rows.filter((r) => {
    if (!r.pos || r.pos === "?" || r.pos === "PICK") return false;
    const ktcVal = Number(r.canonicalSites?.ktc);
    return Number.isFinite(ktcVal) && ktcVal > 0;
  });

  // Sort by KTC value descending (highest value = rank 1)
  eligible.sort((a, b) => Number(b.canonicalSites.ktc) - Number(a.canonicalSites.ktc));

  // Assign integer rank and compute our value for top N.
  // Prefer backend-computed ktcRank / rankDerivedValue when present in r.raw
  // (set by _compute_ktc_rankings in src/api/data_contract.py — the single
  // source of truth for the formula).  Fall back to rankToValue() only when
  // the backend fields are absent (stale data, offline fallback).
  eligible.slice(0, KTC_RANK_LIMIT).forEach((r, i) => {
    const backendRank  = Number(r.raw?.ktcRank);
    const backendValue = Number(r.raw?.rankDerivedValue);
    r.ktcRank = (Number.isInteger(backendRank) && backendRank > 0) ? backendRank : (i + 1);
    r.rankDerivedValue = (Number.isFinite(backendValue) && backendValue > 0) ? backendValue : rankToValue(r.ktcRank);
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
        player?.values?.finalAdjusted ?? player?.values?.overall ?? player?.values?.scarcityAdjusted ?? 0
      ) || 0;
      const values = {
        raw: Number(player?.values?.rawComposite ?? 0) || 0,
        scoring: Number(player?.values?.scoringAdjusted ?? player?.values?.rawComposite ?? 0) || 0,
        scarcity: Number(
          player?.values?.scarcityAdjusted ?? player?.values?.scoringAdjusted ?? player?.values?.rawComposite ?? 0
        ) || 0,
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
          scoring: Math.round(values.scoring),
          scarcity: Math.round(values.scarcity),
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

    computeKtcRanks(rows);
    // Sort: KTC-ranked players first (by ktcRank ascending), then unranked by backend value.
    // values.full is NOT overwritten by rankDerivedValue — backend display values stay authoritative.
    // rankDerivedValue remains available on the row for rankings "Our Value" display.
    rows.sort((a, b) => {
      const ra = a.ktcRank ?? Infinity;
      const rb = b.ktcRank ?? Infinity;
      if (ra !== rb) return ra - rb;
      return (b.values.full || 0) - (a.values.full || 0);
    });
    rows.forEach((r, i) => { r.rank = i + 1; });
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

  computeKtcRanks(rows);
  // Sort: KTC-ranked players first (by ktcRank ascending), then unranked by backend value.
  // values.full is NOT overwritten — backend display values stay authoritative.
  rows.sort((a, b) => {
    const ra = a.ktcRank ?? Infinity;
    const rb = b.ktcRank ?? Infinity;
    if (ra !== rb) return ra - rb;
    return (b.values.full || 0) - (a.values.full || 0);
  });
  rows.forEach((r, i) => { r.rank = i + 1; });
  return rows;
}

export async function fetchDynastyData() {
  const res = await fetch("/api/dynasty-data", { cache: "no-store" });
  if (!res.ok) {
    const txt = await res.text();
    throw new Error(`Failed to load dynasty data: ${res.status} ${txt}`);
  }
  return res.json();
}
