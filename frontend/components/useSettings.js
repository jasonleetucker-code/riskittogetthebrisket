"use client";

import { useCallback, useEffect, useState, useSyncExternalStore } from "react";
import { SETTINGS_KEY } from "@/lib/trade-logic";

// ── Default Settings (single source of truth) ──────────────────────────
export const SETTINGS_DEFAULTS = {
  lamStrength: 1.0,
  scarcityStrength: 0.35,
  leagueFormat: "superflex",
  tepMultiplier: 1.15,
  rankingsSortBasis: "full",
  showLamCols: false,
  showSiteCols: false,
  pickCurrentYear: 2026,
  siteWeights: {},
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
