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
  tepMultiplier: 1.15,               // 1.0..1.5 — TE premium boost for non-TEP sites

  // Rankings display
  rankingsSortBasis: "full",         // "full" | "raw"
  // Source-site columns are on by default on mobile AND desktop.  The
  // rankings table always renders the per-source value + rank cells;
  // this toggle lets power users hide them to focus on the consensus
  // value column.  Historically this defaulted to false but we never
  // wired the toggle to the table render, so the setting was dead and
  // mobile hid the columns via CSS regardless.  Default ON is the
  // canonical behavior — see rankings/page.jsx for the render gate.
  showSiteCols: true,

  // Pick settings
  pickCurrentYear: 2026,

  // Legacy: per-site override map — no longer editable from the UI.
  // Preserved so old localStorage payloads deserialize cleanly; the
  // ranking engine ignores this map entirely.  Delete after a few
  // releases once every user's cache has rolled over.
  siteWeights: {},

  // Trade history
  tradeHistoryWindowDays: 365,       // rolling 1-year window for trade analysis

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

  const reset = useCallback(() => {
    writeSettings(SETTINGS_DEFAULTS);
    notify({ ...SETTINGS_DEFAULTS });
  }, []);

  return { settings, update, reset };
}
