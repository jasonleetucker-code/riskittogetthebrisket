"use client";

import { useCallback, useSyncExternalStore } from "react";
import { SETTINGS_KEY } from "@/lib/trade-logic";

// ── Default Settings (single source of truth) ──────────────────────────
// Covers all tuning parameters needed by every surface:
// trade calculator, rankings, edge, roster dashboard, league, settings page.
export const SETTINGS_DEFAULTS = {
  // League format
  leagueFormat: "superflex",         // "superflex" | "standard"

  // Value adjustment strengths
  lamStrength: 1.0,                  // 0..1 — league adjustment multiplier intensity
  scarcityStrength: 0.35,            // 0..1 — position scarcity premium
  tepMultiplier: 1.15,               // 1.0..1.5 — TE premium boost for non-TEP sites

  // Trade calculator
  alpha: 1.678,                      // star player bonus exponent (1.4..1.9)
  tolerance: 0.05,                   // trade tolerance threshold
  zScoreEnabled: true,               // advanced value blending toggle
  zFloor: -2.0,                      // z-score floor
  zCeiling: 4.0,                     // z-score ceiling

  // Rankings display
  rankingsSortBasis: "full",         // "full" | "raw" | "scoring" | "scarcity"
  showLamCols: false,                // show LAM detail columns in rankings
  showSiteCols: false,               // show per-site value columns in rankings

  // Pick settings
  pickCurrentYear: 2026,
  pickYearDisc1: 0.85,               // +1 year discount
  pickYearDisc2: 0.72,               // +2 year discount

  // Ranking conversion (advanced)
  rankOffset: 27,
  rankDivisor: 28,
  rankExponent: -0.66,

  // IDP ranking conversion (advanced)
  idpAnchor: 6250,
  idpRankOffset: 15,
  idpRankDivisor: 16,
  idpRankExponent: -0.72,

  // Site weights — per-site { include, weight, max, tep }
  siteWeights: {},

  // UI preferences
  compactMode: false,                // compact table view
  mobilePowerMode: true,             // full desktop workflows on mobile

  // Trade history
  tradeHistoryWindowDays: 120,       // rolling window for trade analysis

  // Selected team (global)
  selectedTeam: "",                  // Sleeper team name selection
};

// ── localStorage helpers ────────────────────────────────────────────────
function readSettings() {
  try {
    const raw = localStorage.getItem(SETTINGS_KEY);
    if (raw) return { ...SETTINGS_DEFAULTS, ...JSON.parse(raw) };
  } catch { /* ignore */ }
  return { ...SETTINGS_DEFAULTS };
}

function writeSettings(settings) {
  try {
    localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings));
  } catch { /* ignore */ }
}

// ── Subscribers for cross-component sync ────────────────────────────────
let listeners = new Set();
let cached = null;

function subscribe(cb) {
  listeners.add(cb);
  return () => listeners.delete(cb);
}

function getSnapshot() {
  if (cached === null) cached = readSettings();
  return cached;
}

function getServerSnapshot() {
  return SETTINGS_DEFAULTS;
}

function notify(next) {
  cached = next;
  for (const cb of listeners) cb();
}

// Listen for storage events from other tabs
if (typeof window !== "undefined") {
  window.addEventListener("storage", (e) => {
    if (e.key === SETTINGS_KEY) {
      notify(readSettings());
    }
  });
}

/**
 * Hook to read and write user settings.
 * Changes are synced across all components using this hook.
 */
export function useSettings() {
  const settings = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);

  const update = useCallback((key, value) => {
    const next = { ...getSnapshot(), [key]: value };
    writeSettings(next);
    notify(next);
  }, []);

  const updateSiteWeight = useCallback((siteKey, field, value) => {
    const prev = getSnapshot();
    const weights = { ...prev.siteWeights };
    weights[siteKey] = { ...(weights[siteKey] || {}), [field]: value };
    const next = { ...prev, siteWeights: weights };
    writeSettings(next);
    notify(next);
  }, []);

  const reset = useCallback(() => {
    writeSettings(SETTINGS_DEFAULTS);
    notify({ ...SETTINGS_DEFAULTS });
  }, []);

  return { settings, update, updateSiteWeight, reset };
}
