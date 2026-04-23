"use client";

import { RANKING_SOURCES } from "@/lib/dynasty-data";

/**
 * Three opinionated starting points for the 13-source weight
 * tuner.  Users who don't want to hand-tune each site can pick
 * one of these and drag individual sliders from there.
 *
 * Preset semantics
 * ────────────────
 *
 *   "balanced"  — every enabled source weighted at 1.0.  Equivalent
 *                 to the registry defaults.  Maps to ``siteWeights
 *                 === {}`` so the overrides endpoint doesn't even
 *                 round-trip — this is the fastest mode.
 *
 *   "market"    — lean on retail consensus (KTC, IDPTC) by giving
 *                 them 2.0 weight and halving all expert sources.
 *                 Use when you trade with leaguemates who look at
 *                 KTC.  The board reads closer to what they'll
 *                 negotiate against.
 *
 *   "expert"    — lean on expert consensus (Fitzmaurice, Boone,
 *                 DLF, FP, Football Guys, Draft Sharks, Dynasty
 *                 Nerds, Dynasty Daddy) at 1.5×; halve retail.
 *                 Use when you want the board to reflect where the
 *                 consensus *thinks* a player should be, independent
 *                 of retail market positioning.
 *
 *   "custom"    — not a preset, returned from ``detectActivePreset``
 *                 when siteWeights doesn't match any named preset.
 *
 * Every preset emits ``{ include: true, weight: <float> }`` entries
 * for EVERY source — explicit is better than implicit when the
 * user flips presets mid-session (we don't want a half-applied
 * preset leaving some sources at their previous weight).
 */

export const WEIGHT_PRESETS = {
  balanced: {
    key: "balanced",
    label: "Balanced",
    description: "Every source weighted equally.  No overrides.",
  },
  market: {
    key: "market",
    label: "Market (retail-lean)",
    description:
      "Retail (KTC, IDPTC) × 2.0, experts × 0.5.  Matches what leaguemates see.",
  },
  expert: {
    key: "expert",
    label: "Expert consensus",
    description:
      "Expert sources × 1.5, retail × 0.5.  Contrarian vs retail market.",
  },
};

/**
 * Expand a preset key into the ``siteWeights`` shape the override
 * endpoint expects.
 */
export function presetToWeights(key) {
  if (key === "balanced") return {};
  const out = {};
  for (const source of RANKING_SOURCES) {
    const isRetail = !!source.isRetail;
    let weight = 1.0;
    if (key === "market") {
      weight = isRetail ? 2.0 : 0.5;
    } else if (key === "expert") {
      weight = isRetail ? 0.5 : 1.5;
    }
    out[source.key] = { include: true, weight };
  }
  return out;
}

/**
 * Detect which preset (if any) the current ``siteWeights`` matches.
 * Returns ``"balanced" | "market" | "expert" | "custom"``.
 *
 * Empty ``siteWeights`` → balanced.  Otherwise we compare the full
 * shape against each preset's expanded output.  Tolerant of small
 * float jitter (within 0.01).
 */
export function detectActivePreset(siteWeights) {
  const sw = siteWeights && typeof siteWeights === "object" ? siteWeights : {};
  if (Object.keys(sw).length === 0) return "balanced";
  // If every entry matches balanced defaults (include: true, weight:
  // 1.0), that's effectively balanced even though the dict isn't
  // empty — a user who cleared-via-refresh stays classified.
  const looksBalanced = Object.values(sw).every(
    (v) => v && v.include !== false && (v.weight == null || Math.abs(v.weight - 1.0) < 0.01),
  );
  if (looksBalanced) return "balanced";
  for (const presetKey of ["market", "expert"]) {
    if (matchesPreset(sw, presetToWeights(presetKey))) {
      return presetKey;
    }
  }
  return "custom";
}

function matchesPreset(sw, expected) {
  const keys = new Set([...Object.keys(sw), ...Object.keys(expected)]);
  for (const k of keys) {
    const a = sw[k] || {};
    const b = expected[k] || {};
    if (Boolean(a.include) !== Boolean(b.include)) return false;
    const wa = a.weight == null ? 1.0 : Number(a.weight);
    const wb = b.weight == null ? 1.0 : Number(b.weight);
    if (!Number.isFinite(wa) || !Number.isFinite(wb)) return false;
    if (Math.abs(wa - wb) > 0.01) return false;
  }
  return true;
}
