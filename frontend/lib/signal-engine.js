"use client";

import {
  normalizePoints,
  computeWindowTrend,
  computeVolatility,
} from "@/lib/value-history";

/**
 * signal-engine — rule-driven Buy/Sell/Hold/Strong Hold/Monitor/Risk
 * classifier for roster players.
 *
 * Design requirements (from the product-logic brief):
 *   - No random labels: every signal is produced by a named rule
 *     whose boolean ``test`` evaluates known inputs.
 *   - Explainable: every rule carries a human ``reason`` and a
 *     stable machine ``tag`` so a follow-up card can render the
 *     chain of firing rules, not just the winner.
 *   - Deterministic collision resolution: rules have integer
 *     priorities; the highest-priority firing rule owns the signal.
 *
 * Inputs: value + rank + rankChange from the canonical contract row,
 * window trends (7d, 30d) from rank_history, MAD-based volatility
 * from rank_history, and news impact counts from the news service.
 * No score averaging — all logic is rule composition.
 */

export const SIGNALS = Object.freeze({
  RISK: "RISK",
  SELL: "SELL",
  MONITOR: "MONITOR",
  STRONG_HOLD: "STRONG_HOLD",
  BUY: "BUY",
  HOLD: "HOLD",
});

export const SIGNAL_META = Object.freeze({
  RISK:        { label: "Risk",        tone: "down",  order: 0 },
  SELL:        { label: "Sell",        tone: "down",  order: 1 },
  MONITOR:     { label: "Monitor",     tone: "warn",  order: 2 },
  STRONG_HOLD: { label: "Strong Hold", tone: "up",    order: 3 },
  BUY:         { label: "Buy",         tone: "up",    order: 4 },
  HOLD:        { label: "Hold",        tone: "flat",  order: 5 },
});

const RULES = [
  // ── RISK ────────────────────────────────────────────────────────
  {
    id: "risk.alert_negative_with_drop",
    signal: SIGNALS.RISK,
    priority: 100,
    test: (c) =>
      c.alertCount > 0 &&
      c.negativeImpactCount > 0 &&
      (c.trend7 ?? 0) <= -3,
    reason: (c) =>
      `Alert-severity injury or rumor alongside a 7d drop of ${fmtDelta(c.trend7)}.`,
    tag: "alert_with_drop",
  },
  {
    id: "risk.high_vol_with_drop",
    signal: SIGNALS.RISK,
    priority: 95,
    test: (c) =>
      c.volatility?.label === "high" && (c.trend7 ?? 0) <= -5,
    reason: (c) =>
      `High volatility (MAD ${c.volatility.mad.toFixed(1)}) with a steep 7d drop of ${fmtDelta(c.trend7)}.`,
    tag: "high_vol_drop",
  },

  // ── SELL ────────────────────────────────────────────────────────
  {
    id: "sell.sustained_downtrend",
    signal: SIGNALS.SELL,
    priority: 80,
    test: (c) =>
      (c.trend7 ?? 0) <= -3 && (c.trend30 ?? 0) <= 0,
    reason: (c) =>
      `7d trend ${fmtDelta(c.trend7)} continues a 30d trend of ${fmtDelta(c.trend30)}.`,
    tag: "sustained_downtrend",
  },
  {
    id: "sell.negative_news_high_vol",
    signal: SIGNALS.SELL,
    priority: 78,
    test: (c) =>
      c.negativeImpactCount > 0 && c.volatility?.label === "high",
    reason: (c) =>
      `Negative news with high volatility (MAD ${c.volatility.mad.toFixed(1)}) — market is punishing noise.`,
    tag: "neg_news_high_vol",
  },

  // ── MONITOR ─────────────────────────────────────────────────────
  {
    id: "monitor.alert_on_roster",
    signal: SIGNALS.MONITOR,
    priority: 65,
    test: (c) => c.alertCount > 0,
    reason: (c) =>
      `${c.alertCount} alert-severity headline${c.alertCount === 1 ? "" : "s"} — watch for follow-up.`,
    tag: "alert_present",
  },
  {
    id: "monitor.high_volatility",
    signal: SIGNALS.MONITOR,
    priority: 62,
    test: (c) => c.volatility?.label === "high",
    reason: (c) =>
      `High volatility (MAD ${c.volatility.mad.toFixed(1)}) — market can't settle on a price.`,
    tag: "high_vol",
  },
  {
    id: "monitor.low_conf_unstable",
    signal: SIGNALS.MONITOR,
    priority: 60,
    test: (c) =>
      c.confidence != null &&
      c.confidence < 0.35 &&
      (c.volatility?.label === "med" || Math.abs(c.trend7 ?? 0) >= 2),
    reason: (c) =>
      `Low market confidence (${(c.confidence * 100).toFixed(0)}%) plus recent movement.`,
    tag: "low_conf_unstable",
  },

  // ── STRONG HOLD ─────────────────────────────────────────────────
  {
    id: "strong.elite_stable",
    signal: SIGNALS.STRONG_HOLD,
    priority: 50,
    test: (c) =>
      c.value >= 7000 &&
      (c.trend30 ?? 0) >= 0 &&
      (c.volatility?.label === "low" || c.volatility?.label === "med"),
    reason: (c) =>
      `Elite value (${c.value.toLocaleString()}) with a non-negative 30d trend and non-high volatility.`,
    tag: "elite_stable",
  },

  // ── BUY ─────────────────────────────────────────────────────────
  {
    id: "buy.uptrend_not_volatile",
    signal: SIGNALS.BUY,
    priority: 40,
    test: (c) =>
      (c.trend7 ?? 0) >= 3 && c.volatility?.label !== "high",
    reason: (c) =>
      `7d trend of ${fmtDelta(c.trend7)} and volatility is ${c.volatility?.label ?? "—"}.`,
    tag: "uptrend_controlled",
  },
  {
    id: "buy.positive_news_rising",
    signal: SIGNALS.BUY,
    priority: 38,
    test: (c) =>
      c.positiveImpactCount > 0 && (c.rankChange ?? 0) > 0,
    reason: (c) =>
      `Positive news with rank rising ${fmtDelta(c.rankChange)} on the last scrape.`,
    tag: "pos_news_rising",
  },

  // ── HOLD (default) ─────────────────────────────────────────────
  // HOLD never fires as a rule — it's the fallback when nothing else does.
];

function fmtDelta(v) {
  if (v == null || !Number.isFinite(v)) return "—";
  if (v === 0) return "·";
  return v > 0 ? `+${v}` : `${v}`;
}

/**
 * Evaluate the rules against a context and return a verdict plus the
 * full chain of firing rules (so the UI can display the "because"
 * sequence, not just the winner).
 */
export function evaluate(context) {
  const fired = RULES
    .filter((r) => {
      try { return !!r.test(context); }
      catch { return false; }
    })
    .sort((a, b) => b.priority - a.priority);

  if (fired.length === 0) {
    return {
      signal: SIGNALS.HOLD,
      primary: null,
      reason: "Stable — no movement, volatility, or news triggers.",
      tag: "default_hold",
      fired: [],
    };
  }

  const primary = fired[0];
  return {
    signal: primary.signal,
    primary,
    reason: primary.reason(context),
    tag: primary.tag,
    fired: fired.map((r) => ({
      id: r.id,
      signal: r.signal,
      tag: r.tag,
      reason: r.reason(context),
    })),
  };
}

/**
 * Build the per-player context the rule engine needs.
 */
export function buildContext({ row, historyPoints, newsItems }) {
  const points = Array.isArray(historyPoints) ? historyPoints : normalizePoints(historyPoints);
  const trend7 = computeWindowTrend(points, 7);
  const trend30 = computeWindowTrend(points, 30);
  const volatility = computeVolatility(points, 30);

  const items = Array.isArray(newsItems) ? newsItems : [];
  let alertCount = 0;
  let negativeImpactCount = 0;
  let positiveImpactCount = 0;
  for (const it of items) {
    if (it.severity === "alert") alertCount += 1;
    for (const p of it.players || []) {
      if (p?.impact === "negative") negativeImpactCount += 1;
      else if (p?.impact === "positive") positiveImpactCount += 1;
    }
  }

  return {
    name: row?.name,
    pos: row?.pos || "?",
    value: Number(row?.rankDerivedValue || row?.values?.full || 0),
    rank: Number(row?.canonicalConsensusRank) || null,
    rankChange: Number.isFinite(row?.rankChange) ? row.rankChange : null,
    confidence: Number.isFinite(row?.confidence) ? row.confidence : null,
    trend7,
    trend30,
    volatility,
    alertCount,
    negativeImpactCount,
    positiveImpactCount,
    newsCount: items.length,
  };
}

/**
 * Evaluate every roster player in one pass.  Returns an array of
 * {row, context, verdict} entries, sorted by signal priority so the
 * RISK/SELL items are at the top for scanability.
 */
export function evaluateRoster({ rows, selectedTeam, history, newsItems }) {
  if (!selectedTeam?.players?.length || !Array.isArray(rows)) return [];

  const rowByName = new Map();
  for (const r of rows) rowByName.set(String(r.name).toLowerCase(), r);

  const histLower = new Map();
  if (history && typeof history === "object") {
    for (const k of Object.keys(history)) {
      histLower.set(k.toLowerCase(), history[k]);
    }
  }

  const newsByPlayer = new Map();
  if (Array.isArray(newsItems)) {
    for (const it of newsItems) {
      for (const p of it.players || []) {
        const key = String(p?.name || "").toLowerCase();
        if (!key) continue;
        if (!newsByPlayer.has(key)) newsByPlayer.set(key, []);
        newsByPlayer.get(key).push(it);
      }
    }
  }

  const out = [];
  for (const name of selectedTeam.players) {
    const key = String(name).toLowerCase();
    const row = rowByName.get(key);
    if (!row) continue;
    const historyPoints = normalizePoints(histLower.get(key) || history?.[name]);
    const playerNews = newsByPlayer.get(key) || [];
    const context = buildContext({ row, historyPoints, newsItems: playerNews });
    const verdict = evaluate(context);
    out.push({ row, context, verdict, news: playerNews });
  }

  out.sort((a, b) => {
    const oa = SIGNAL_META[a.verdict.signal]?.order ?? 99;
    const ob = SIGNAL_META[b.verdict.signal]?.order ?? 99;
    if (oa !== ob) return oa - ob;
    return (b.context.value || 0) - (a.context.value || 0);
  });

  return out;
}
