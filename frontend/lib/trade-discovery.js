// Trade discovery vocabulary — owner directive 2026-10-18 (Trade Finder
// meaningful discovery).  ONE module every /arbitrage view reads.
//
// The server owns the filters' meaning (src/trade/discovery.py): Target
// Quality is applied during candidate generation to INCOMING players over the
// canonical overall rank (canonicalConsensusRank); Players to target narrows
// the incoming pool before enumeration; the sorts order what the engines
// already qualified.  This module only names the options, shapes the request
// and words the results.  The one local use is the client-side research table
// (Player-Level Inefficiencies), which filters backend-stamped rows — it
// recomputes no value and no rank.
//
// OFFENSE_POSITIONS / DEFENSE_POSITIONS mirror the canonical owners
// (src/utils/name_clean.POSITION_ALIASES + src/ros/lineup slot eligibility)
// and are held in lockstep by tests/trade/test_trade_discovery_parity.py.

export const TARGET_QUALITY_OPTIONS = [
  { value: "top100", label: "Top 100", limit: 100 },
  { value: "top250", label: "Top 250", limit: 250 },
  { value: "top500", label: "Top 500", limit: 500 },
  { value: "all", label: "All Players", limit: null },
];
export const DEFAULT_TARGET_QUALITY = "top250";

export const PLAYER_SCOPE_OPTIONS = [
  { value: "both", label: "Both" },
  { value: "offense", label: "Offense" },
  { value: "defense", label: "Defense (IDP)" },
];
export const DEFAULT_PLAYER_SCOPE = "both";

export const DISCOVERY_SORT_OPTIONS = [
  { value: "most_impactful", label: "Most impactful" },
  { value: "absolute_gain", label: "Largest value gain" },
  { value: "percentage_edge", label: "Highest % edge" },
  { value: "incoming_rank", label: "Highest-ranked incoming" },
];
export const DEFAULT_DISCOVERY_SORT = "most_impactful";

/** Research-table sorts (Player-Level Inefficiencies). */
export const TABLE_SORT_OPTIONS = [
  { value: "absolute", label: "Largest absolute opportunity" },
  { value: "percentage", label: "Highest % edge" },
  { value: "rank", label: "Canonical rank" },
];
export const DEFAULT_TABLE_SORT = "absolute";

// Canonical position families (pinned to Python by a parity test).
export const OFFENSE_POSITIONS = ["QB", "RB", "WR", "TE"];
export const DEFENSE_POSITIONS = [
  "CB",
  "DB",
  "DE",
  "DL",
  "DT",
  "ED",
  "EDGE",
  "FS",
  "IDL",
  "ILB",
  "LB",
  "MLB",
  "NT",
  "OLB",
  "S",
  "SAF",
  "SS",
];

const OFFENSE = new Set(OFFENSE_POSITIONS);
const DEFENSE = new Set(DEFENSE_POSITIONS);

function tokenGroup(token) {
  const t = String(token || "").trim().toUpperCase();
  if (!t) return "unknown";
  if (t === "PICK") return "pick";
  if (OFFENSE.has(t)) return "offense";
  if (DEFENSE.has(t)) return "defense";
  return "unknown";
}

/**
 * "offense" | "defense" | "pick" | "unknown".  A multi-position string
 * resolves only when every part agrees; an offense + defense mix is unknown —
 * never silently offense.  Mirrors src/trade/discovery.player_group.
 */
export function playerScopeGroup(position) {
  const raw = String(position ?? "").trim().toUpperCase();
  if (!raw || raw === "?") return "unknown";
  const parts = raw.split(/[/,|\s]+/).filter(Boolean);
  if (parts.length <= 1) return tokenGroup(raw);
  const groups = new Set(parts.map(tokenGroup));
  groups.delete("unknown");
  return groups.size === 1 ? [...groups][0] : "unknown";
}

export function qualityLimit(value) {
  return TARGET_QUALITY_OPTIONS.find((o) => o.value === value)?.limit ?? null;
}

export function qualityLabel(value) {
  return TARGET_QUALITY_OPTIONS.find((o) => o.value === value)?.label || value;
}

/** Levels broader than ``value``, narrowest first (one-click expansion). */
export function broaderQualityOptions(value) {
  const i = TARGET_QUALITY_OPTIONS.findIndex((o) => o.value === value);
  return i < 0 ? [] : TARGET_QUALITY_OPTIONS.slice(i + 1);
}

export function defaultDiscovery() {
  return {
    targetQuality: DEFAULT_TARGET_QUALITY,
    playersToTarget: DEFAULT_PLAYER_SCOPE,
    sort: DEFAULT_DISCOVERY_SORT,
    minIncomingValue: "",
  };
}

/** The ``discovery`` request object every discovery route accepts. */
export function discoveryRequest(state) {
  const s = state || defaultDiscovery();
  const out = {
    targetQuality: s.targetQuality || DEFAULT_TARGET_QUALITY,
    playersToTarget: s.playersToTarget || DEFAULT_PLAYER_SCOPE,
    sort: s.sort || DEFAULT_DISCOVERY_SORT,
  };
  const min = Number(s.minIncomingValue);
  if (Number.isFinite(min) && min >= 1 && min <= 9999) {
    out.minIncomingValue = Math.round(min);
  }
  return out;
}

/** A short summary of the active filters, for headings and empty states. */
export function discoverySummary(state) {
  const s = state || defaultDiscovery();
  const scope =
    PLAYER_SCOPE_OPTIONS.find((o) => o.value === s.playersToTarget)?.label ||
    "Both";
  const min = Number(s.minIncomingValue);
  const minText =
    Number.isFinite(min) && min >= 1 ? ` · min ${Math.round(min).toLocaleString()}` : "";
  return `${qualityLabel(s.targetQuality)} · ${scope}${minText}`;
}

const EMPTY_TEXT = {
  no_target_in_players_to_target:
    "No opponent rosters a player in the selected Players to target group in this scan.",
  no_target_meets_quality:
    "No opponent player in this scan meets Target Quality. Broaden it to search deeper.",
  no_package_within_target_quality:
    "Every package that brings back a player inside Target Quality failed the board-gain, plausibility or market rules.",
  no_upgrade_within_target_quality:
    "No legitimate Golden Upgrade brings back a player inside Target Quality.",
  locked_player_outside_players_to_target:
    "A locked player is outside Players to target. Unlock him or switch Players to target.",
};

/** The server's own empty-state wording, or this vocabulary's fallback. */
export function discoveryEmptyText(reason, detail) {
  return detail || EMPTY_TEXT[reason] || null;
}

/** "#89 · 4,261" for a canonical rank + value; unknown stays unknown. */
export function rankValueLine(rank, value) {
  const r = Number.isFinite(rank) && rank > 0 ? `#${rank}` : "unranked";
  const v = Number.isFinite(value) ? Math.round(value).toLocaleString() : "—";
  return `${r} · ${v}`;
}

export function fmtSignedPctValue(pct) {
  if (!Number.isFinite(pct)) return "—";
  return `${pct > 0 ? "+" : ""}${pct.toFixed(1)}%`;
}

export function fmtSignedValue(v) {
  if (!Number.isFinite(v)) return "—";
  return `${v > 0 ? "+" : ""}${Math.round(v).toLocaleString()}`;
}
