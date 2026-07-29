/**
 * bdvm.js — pure display helpers for the /bdvm Fundamentals surface.
 *
 * BDVM (src/bdvm/) is the projection-driven FUNDAMENTAL value concept,
 * served by GET /api/bdvm/values|roster|trades behind the bdvm_engine
 * feature flag. It is compared against the market board, never merged
 * into it. This module only reshapes backend payloads for rendering —
 * every number here is backend-computed (fundamentals, trade values,
 * market gaps, signals, the 0-100 score). Sorting rows by a
 * backend-stamped column and numbering them is table UX, not ranking
 * math: the same rule that makes buildRows a pure materializer.
 */

import { normalizePlayerNameKey } from "@/lib/player-name-match";

export const BDVM_STRATEGIES = [
  { value: "balanced", label: "Balanced" },
  { value: "contender", label: "Contender" },
  { value: "rebuilder", label: "Rebuilder" },
  { value: "risk_neutral", label: "Risk-neutral" },
];

export const BDVM_SURPLUS_MODES = [
  { value: "option", label: "Option value E[max(0, X−R)]" },
  { value: "truncated", label: "Truncated max(0, μ−R)" },
  { value: "plain", label: "Plain μ−R" },
];

/**
 * Classify a non-2xx BDVM response into the states the page renders
 * distinctly. The three 503 variants carry different `error` codes and
 * MUST be told apart: flag-off is an expected configuration, not a
 * failure.
 *
 * Returns null for 2xx; otherwise { kind, message } with kind one of
 * "disabled" | "not_ready" | "unavailable" | "auth" | "error".
 */
export function classifyBdvmFailure(status, body) {
  if (status >= 200 && status < 300) return null;
  const code = body && typeof body === "object" ? body.error : "";
  const message =
    (body && typeof body === "object" && (body.message || body.detail)) || "";
  if (status === 503 && code === "feature_disabled") {
    return { kind: "disabled", message: "" };
  }
  if (status === 503 && code === "data_not_ready") {
    return { kind: "not_ready", message };
  }
  if (status === 503 && code === "bdvm_unavailable") {
    return { kind: "unavailable", message };
  }
  if (status === 401) {
    return { kind: "auth", message: "Sign in to view fundamentals." };
  }
  return { kind: "error", message: message || `HTTP ${status}` };
}

function _num(v) {
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

/**
 * Flatten /api/bdvm/values players for the board table, ordered by the
 * chosen strategy's trade value (backend-computed; we only sort and
 * number). Input payload is never mutated.
 */
export function buildBdvmValueRows(payload, strategy) {
  const players = Array.isArray(payload?.players) ? payload.players : [];
  const rows = players.map((p) => {
    const tv = p?.tradeValue || {};
    const market = p?.market || {};
    const quality = p?.quality || {};
    const projection = p?.projection || {};
    const range = p?.range || {};
    return {
      playerId: p?.playerId ?? p?.name ?? "",
      name: p?.name ?? "",
      position: p?.position ?? "",
      group: p?.group ?? "",
      age: _num(p?.raw?.age),
      fpg: _num(projection.fpg),
      anyProxy: Boolean(projection.anyProxy),
      sourceCount: _num(projection.sourceCount) ?? 0,
      tradeValue: _num(tv?.[strategy]),
      tradeValueAll: tv,
      marketValue: _num(market.marketValue),
      marketSource: market.marketSource ?? null,
      gap: _num(market.gap),
      signal: p?.signal?.signal ?? "",
      signalReason: p?.signal?.reason ?? "",
      score: _num(p?.dynastyScore0to100),
      confidenceLabel: quality.confidenceLabel ?? "",
      confidenceScore: _num(quality.confidenceScore),
      floor: _num(range.floor_p20),
      ceiling: _num(range.ceiling_p85),
    };
  });
  rows.sort((a, b) => (b.tradeValue ?? -1) - (a.tradeValue ?? -1));
  return rows.map((r, i) => ({ ...r, rank: i + 1 }));
}

/** Distinct lineup groups present, in board order, for the filter. */
export function bdvmGroupOptions(rows) {
  const seen = new Set();
  for (const r of rows) if (r.group) seen.add(r.group);
  const order = ["QB", "RB", "WR", "TE", "DL", "LB", "DB", "K"];
  const known = order.filter((g) => seen.has(g));
  const extra = [...seen].filter((g) => !order.includes(g)).sort();
  return [...known, ...extra];
}

/**
 * Flatten /api/bdvm/values picks, ordered by the chosen strategy's EV
 * (unparseable pick names sink to the bottom, still listed — they are
 * unpriced, not hidden).
 */
export function buildBdvmPickRows(payload, strategy) {
  const picks = Array.isArray(payload?.picks) ? payload.picks : [];
  const rows = picks.map((p) => {
    const dist = p?.distribution?.[strategy] || null;
    return {
      name: p?.name ?? "",
      ev: _num(dist?.ev),
      pHit: _num(dist?.p_hit),
      median: _num(dist?.median),
      ceiling: _num(dist?.ceiling),
      marketValue: _num(p?.market?.marketValue),
      marketSource: p?.market?.marketSource ?? null,
      yearsOut: _num(p?.yearsOut),
      unpriced: !p?.distribution,
      reason: p?.reason ?? "",
    };
  });
  rows.sort((a, b) => (b.ev ?? -1) - (a.ev ?? -1));
  return rows;
}

/** Flatten /api/bdvm/roster rosters for the strategy table. */
export function buildBdvmRosterRows(payload) {
  const rosters = Array.isArray(payload?.rosters) ? payload.rosters : [];
  return rosters.map((r) => ({
    key: String(r?.ownerId || r?.name || ""),
    name: r?.name ?? "",
    direction: r?.direction ?? "",
    strategy: r?.strategy ?? "",
    contender: _num(r?.capitals?.contender),
    balanced: _num(r?.capitals?.balanced),
    rebuilder: _num(r?.capitals?.rebuilder),
    nowFutureRatio: _num(r?.nowFutureRatio),
    valueWeightedAge: _num(r?.valueWeightedAge),
    starterFpg: _num(r?.starterFpg),
    assetCount: _num(r?.assetCount) ?? 0,
    pickCount: _num(r?.pickCount) ?? 0,
    assets: Array.isArray(r?.assets) ? r.assets : [],
  }));
}

/** Flatten /api/bdvm/trades packages for the double-positive table. */
export function buildBdvmTradeRows(payload) {
  const trades = Array.isArray(payload?.trades) ? payload.trades : [];
  return trades.map((t, i) => ({
    key: `${t?.from?.ownerId ?? ""}-${t?.to?.ownerId ?? ""}-${i}`,
    aName: t?.from?.name ?? "",
    aStrategy: t?.from?.strategy ?? "",
    aGives: Array.isArray(t?.from?.gives) ? t.from.gives : [],
    aGain: _num(t?.from?.gain),
    bName: t?.to?.name ?? "",
    bStrategy: t?.to?.strategy ?? "",
    bGives: Array.isArray(t?.to?.gives) ? t.to.gives : [],
    bGain: _num(t?.to?.gain),
    minGain: _num(t?.minGain),
    fairnessPct: _num(t?.marketFairnessPct),
    fairnessBasis: t?.fairnessBasis ?? "",
  }));
}

/**
 * Index /api/bdvm/values players for render-time joins onto board rows
 * (the /rankings gap column). playerId-first with a canonical
 * name-key fallback — the same id-then-name idiom the ownership join
 * uses. The name key is ``normalizePlayerNameKey`` (the JS mirror of
 * ``src/utils/name_clean.py::normalize_player_name``), NOT a bare
 * ``toLowerCase``: BDVM names come from the projection snapshot while
 * board rows come from the scrape contract, so punctuation/suffix/
 * accent variants ("D.J. Moore" vs "DJ Moore", "Kenneth Walker III"
 * vs "Kenneth Walker") are routine across the two vocabularies and a
 * raw lowercase key silently drops the gap column for them.
 * Returns null when the payload carries no joinable players, so
 * callers can treat "no index" and "endpoint unavailable" identically
 * (column vanishes).
 */
export function buildBdvmIndex(payload) {
  const players = Array.isArray(payload?.players) ? payload.players : [];
  const byId = new Map();
  const byName = new Map();
  for (const p of players) {
    const entry = {
      gap: _num(p?.market?.gap),
      marketValue: _num(p?.market?.marketValue),
      fundamental: _num(p?.tradeValue?.balanced),
      signal: p?.signal?.signal ?? "",
      signalReason: p?.signal?.reason ?? "",
    };
    const id = p?.playerId != null ? String(p.playerId).trim() : "";
    if (id) byId.set(id, entry);
    const name = normalizePlayerNameKey(p?.name);
    if (name) byName.set(name, entry);
  }
  return byId.size || byName.size ? { byId, byName } : null;
}

/** Resolve a board row against a buildBdvmIndex result (or null).
 * playerId wins outright; the canonical name key is only the fallback
 * for rows that carry no id (draft rows, legacy rows). */
export function bdvmEntryForRow(index, row) {
  if (!index || !row) return null;
  const id = String(row?.raw?.playerId ?? row?.playerId ?? "").trim();
  if (id && index.byId.has(id)) return index.byId.get(id);
  const name = normalizePlayerNameKey(row?.name);
  return (name && index.byName.get(name)) || null;
}

/** Rankings-page pill class for a BDVM signal — reuses the Edge
 * column's existing edge-buy/edge-sell/edge-hold styling so the two
 * market columns read as one visual language. */
export function bdvmSignalEdgeCss(signal) {
  switch (signal) {
    case "STRONG_BUY":
    case "BUY":
      return "edge-buy";
    case "SELL":
    case "STRONG_SELL":
      return "edge-sell";
    case "HOLD":
      return "edge-hold";
    default:
      return "";
  }
}

/** Badge tone for a market signal. Tones carry meaning: BUY/SELL are
 * market semantics; NO_MARKET is an absence, not a state. */
export function bdvmSignalTone(signal) {
  switch (signal) {
    case "STRONG_BUY":
    case "BUY":
      return "positive";
    case "SELL":
      return "warning";
    case "STRONG_SELL":
      return "negative";
    case "NO_MARKET":
      return "outline";
    default:
      return "neutral";
  }
}

/** Badge tone for a roster direction. Rebuild is a strategy, not a bad
 * outcome — info, never negative. */
export function bdvmDirectionTone(direction) {
  switch (direction) {
    case "contend":
      return "positive";
    case "rebuild":
      return "info";
    default:
      return "neutral";
  }
}

/** "1,234" for trade-scale values; em dash for absent (never 0-for-null). */
export function formatBdvmValue(v) {
  if (typeof v !== "number" || !Number.isFinite(v)) return "—";
  return Math.round(v).toLocaleString();
}

/** Signed gap: "+412" / "−93"; em dash when the market has no anchor. */
export function formatBdvmGap(v) {
  if (typeof v !== "number" || !Number.isFinite(v)) return "—";
  const rounded = Math.round(v);
  if (rounded > 0) return `+${rounded.toLocaleString()}`;
  if (rounded < 0) return `−${Math.abs(rounded).toLocaleString()}`;
  return "0";
}

/** One decimal, em dash for absent. */
export function formatBdvmDecimal(v, digits = 1) {
  if (typeof v !== "number" || !Number.isFinite(v)) return "—";
  return v.toFixed(digits);
}
