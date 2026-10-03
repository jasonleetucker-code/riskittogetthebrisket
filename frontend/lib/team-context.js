/**
 * team-context — the ONE client source of truth for "Use Team Context" (#842).
 *
 * The backend owner is `src/trade/team_context.py`: every trade route
 * (`/api/trade/simulate`, `/api/trade/analyze`, `/api/trade/finder`,
 * `/api/trade/suggestions`, `/api/angle/*`) reads the same `useTeamContext`
 * body field, defaults to ON, and stamps a `teamContext` block saying which
 * team dimensions it included, excluded or could not compute.
 *
 * This module is the client half of that contract and nothing else:
 *   - one persisted preference, so /trade, the War Room, /arbitrage and share
 *     links agree (a share link's mode still wins for that page load);
 *   - the request field, attached in one place;
 *   - the words.  "Asset-Only Analysis" and "not included in this verdict" are
 *     the supersession's own wording, used verbatim everywhere.
 *
 * No trade math lives here.  Storage is a per-viewer convenience: every read
 * and write is guarded, and a missing/blocked store is the default (ON).
 */

import { useCallback, useEffect, useState } from "react";

export const TEAM_CONTEXT_STORAGE_KEY = "riskit_use_team_context_v1";

export const TEAM_CONTEXT_LABEL = "Team Context";
export const ASSET_ONLY_LABEL = "Asset-Only Analysis";
export const EXCLUDED_NOTE = "Not included in this verdict";

export const TEAM_CONTEXT_OPTIONS = [
  { value: "team", label: "Team context" },
  { value: "asset", label: "Asset only" },
];

/** Only an explicit boolean false turns team context off — the server rule. */
export function normalizeTeamContext(raw) {
  return raw === false ? false : true;
}

export function readTeamContextPreference() {
  try {
    if (typeof window === "undefined") return true;
    const raw = window.localStorage.getItem(TEAM_CONTEXT_STORAGE_KEY);
    return raw === "asset" ? false : true;
  } catch {
    return true;
  }
}

export function writeTeamContextPreference(useTeamContext) {
  try {
    if (typeof window === "undefined") return;
    window.localStorage.setItem(
      TEAM_CONTEXT_STORAGE_KEY,
      normalizeTeamContext(useTeamContext) ? "team" : "asset",
    );
  } catch {
    /* blocked storage: the preference simply does not persist */
  }
}

/**
 * `[useTeamContext, setUseTeamContext, adoptForThisPage]`.
 *
 * Starts ON on the server render and adopts the stored preference after
 * mount, so hydration never mismatches.  `setUseTeamContext` is the user's
 * choice and persists; `adoptForThisPage` applies a share link's mode to the
 * page that opened it WITHOUT overwriting the viewer's own preference.
 */
export function useTeamContextPreference() {
  const [value, setValue] = useState(true);
  useEffect(() => {
    setValue((prev) => (prev === true ? readTeamContextPreference() : prev));
  }, []);
  const set = useCallback((next) => {
    const v = normalizeTeamContext(next);
    setValue(v);
    writeTeamContextPreference(v);
  }, []);
  const adopt = useCallback((next) => {
    setValue(normalizeTeamContext(next));
  }, []);
  return [value, set, adopt];
}

/** The request body with the mode attached — the one place it is added. */
export function withTeamContext(body, useTeamContext) {
  return { ...(body || {}), useTeamContext: normalizeTeamContext(useTeamContext) };
}

/** Human mode line for a response's `teamContext` block (or the requested mode). */
export function teamContextModeLabel(block, requested = true) {
  if (block && typeof block === "object" && typeof block.applied === "boolean") {
    return block.applied ? TEAM_CONTEXT_LABEL : ASSET_ONLY_LABEL;
  }
  return normalizeTeamContext(requested) ? TEAM_CONTEXT_LABEL : ASSET_ONLY_LABEL;
}

const STATE_WORDS = {
  included: "Included in this verdict",
  context: "Shown as context — not a vote",
  excluded_by_mode: EXCLUDED_NOTE,
  unavailable: "Unavailable",
  not_applicable: "Not used here",
};

/** Rows for a "what team context did" list.  Labels are the server's. */
export function teamContextDimensionRows(block) {
  const dims = Array.isArray(block?.dimensions) ? block.dimensions : [];
  return dims.map((d) => ({
    key: String(d.dimension || ""),
    label: String(d.label || d.dimension || ""),
    state: String(d.state || ""),
    stateText: STATE_WORDS[d.state] || String(d.state || ""),
    reason: d.reason ? String(d.reason).replace(/_/g, " ") : null,
    included: d.includedInVerdict === true,
  }));
}

/** True when a team-context block a surface shows was excluded from the verdict. */
export function isExcludedFromVerdict(block) {
  return Boolean(block && typeof block === "object" && block.includedInVerdict === false);
}
