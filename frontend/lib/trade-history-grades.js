/**
 * trade-history-grades — the three Trade History questions for /trades,
 * all under ONE package model (owner package 2026-10-17,
 * SITEWIDE_TRADE_ADJUSTMENT_AND_HISTORY_INTEGRATION):
 *
 *   Current Grade — this trade's assets at TODAY's canonical values
 *                   (``analyzeRawTrade`` in lib/league-analysis.js, which
 *                   reaches the Value Adjustment through ``packageAdjustPair``);
 *   At-the-Time   — the SAME assets at the latest value the canonical
 *                   temporal ledger knew strictly before the trade, graded
 *                   on the backend by the same function and the same
 *                   resolver the public /league activity grade uses
 *                   (``POST /api/trades/asof-grades`` →
 *                   ``src/api/trade_history_asof.py``);
 *   How It Aged   — the change in this side's ADJUSTED net (raw + package
 *                   adjustment), today minus at-the-time, same model, same
 *                   assets (owner decision 2026-10-17).
 *
 * This replaces ``trade-retro-value.js``, which re-derived at-the-time
 * values from the rank-history feed by player NAME, refused every pick, and
 * compared RAW nets while the grade beside it was adjusted — a second
 * implementation of a question ``src/history`` owns.
 *
 * Missing is never zero.  An at-the-time side the ledger cannot fully price
 * is "unavailable" with a reason; a current side with any asset today's
 * board cannot price makes aging unavailable too (comparing an incomplete
 * total with a complete one measures the gap, not the aging).
 */
import { parsePickToken } from "@/lib/trade-logic";

/** ±200 adjusted-value band for "stable".  A PRIOR (TRADE_HISTORY_AGING_SPEC
 *  §5 named the old raw-net ±200 as evidence-gated); kept, labelled, until
 *  it is calibrated. */
export const AGING_STABLE_BAND_PRIOR = 200;

export const AGING = Object.freeze({
  AGED_WELL: "aged_well",
  AGED_POORLY: "aged_poorly",
  STABLE: "stable",
  UNAVAILABLE: "unavailable",
});

export const AGING_LABEL = Object.freeze({
  aged_well: "Aged well",
  aged_poorly: "Aged poorly",
  stable: "Stable",
  unavailable: "Aging unavailable",
});

const ROUND_NUMBER = {
  "1st": 1,
  "2nd": 2,
  "3rd": 3,
  "4th": 4,
  "5th": 5,
  "6th": 6,
};

/** A stable per-trade key: Sleeper's transaction id, else the list index.
 *  (The retired code keyed by an ``a.id`` no analysis entry carries, so
 *  every card read the same trade's aging.) */
export function tradeKey(analysis, index) {
  const id = String(analysis?.trade?.transactionId || "").trim();
  return id ? `tx:${id}` : `idx:${index}`;
}

/** Epoch ms of the trade, or null — never "now". */
export function tradeInstantMs(analysis) {
  const explicit = Number(analysis?.trade?.timestamp);
  return Number.isFinite(explicit) && explicit > 0 ? explicit : null;
}

/** One trade item → the public-activity asset shape the ledger resolver
 *  reads.  Picks carry only (season, round): the generic grade, the same
 *  rule the public /league grade uses (owner decision 2026-10-17). */
export function itemToAsset(item) {
  const name = String(item?.name || "").trim();
  if (item?.isPick) {
    const parsed = parsePickToken(name);
    const round = parsed ? ROUND_NUMBER[parsed.round] : null;
    if (!parsed || !round)
      return { kind: "pick", label: name, season: null, round: null };
    return { kind: "pick", label: name, season: Number(parsed.year), round };
  }
  return {
    kind: "player",
    playerId: item?.playerId || "",
    playerName: name,
    position: item?.pos || "",
  };
}

/** The ``POST /api/trades/asof-grades`` body for a list of analyzed trades. */
export function buildAsofRequest(analyzed) {
  return {
    trades: (analyzed || []).map((a, i) => ({
      id: tradeKey(a, i),
      createdAt: tradeInstantMs(a),
      sides: (a.sides || []).map((s) => ({
        receivedAssets: (s.got || []).map(itemToAsset),
        sentAssets: (s.gave || []).map(itemToAsset),
      })),
    })),
  };
}

/** ``{tradeKey: sides[]}`` from the endpoint response. */
export function indexAsofResponse(payload) {
  const out = new Map();
  for (const t of payload?.trades || []) {
    if (t && t.id != null)
      out.set(String(t.id), Array.isArray(t.sides) ? t.sides : []);
  }
  return out;
}

/**
 * How one side aged.  ``current`` is the analyzed side (today's board);
 * ``atTime`` the endpoint's side for the same index.  Same model on both
 * (the backend stamps ``packageModel``; ``modelMatches`` says whether the
 * client's active model is the one the backend used).
 */
export function sideAging(current, atTime, { modelMatches = true } = {}) {
  if (!modelMatches)
    return {
      verdict: AGING.UNAVAILABLE,
      reason: "package_model_mismatch",
      delta: null,
    };
  if (!atTime || atTime.available !== true) {
    return {
      verdict: AGING.UNAVAILABLE,
      reason: atTime?.reason || "at_time_unavailable",
      delta: null,
    };
  }
  if (!current || Number(current.unresolvedAssets) > 0) {
    return {
      verdict: AGING.UNAVAILABLE,
      reason: "unpriced_today",
      delta: null,
    };
  }
  const now = Number(current.netAdjusted);
  const then = Number(atTime.netAdjusted);
  if (!Number.isFinite(now) || !Number.isFinite(then)) {
    return {
      verdict: AGING.UNAVAILABLE,
      reason: "non_finite_net",
      delta: null,
    };
  }
  const delta = now - then;
  const verdict =
    delta > AGING_STABLE_BAND_PRIOR
      ? AGING.AGED_WELL
      : delta < -AGING_STABLE_BAND_PRIOR
        ? AGING.AGED_POORLY
        : AGING.STABLE;
  return { verdict, reason: null, delta };
}

export const AGING_REASON_TEXT = Object.freeze({
  no_historical_evidence:
    "an asset has no recorded value before the trade date",
  invalid_trade_instant: "the trade's date is unknown",
  history_ledger_missing: "historical values are not available on this server",
  at_time_unavailable: "at-the-time values not loaded",
  unpriced_today: "an asset has no value on today's board",
  package_model_mismatch:
    "today's and at-the-time grades used different package models",
  non_finite_net: "a net value could not be computed",
});
