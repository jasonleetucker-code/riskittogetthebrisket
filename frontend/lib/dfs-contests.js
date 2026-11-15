/**
 * dfs-contests.js — display helpers for the DFS contest editor.
 *
 * Separate from lib/dfs.js so they ship in the lazily loaded ContestPanel
 * chunk, not the /dfs page chunk. Display only: every number comes from
 * /api/dfs/contests* (src/dfs/contests.py); nothing here computes money.
 */

/** Integer cents → "$1,000.50" without floating-point money. Null stays null. */
export function formatCents(cents) {
  if (cents === null || cents === undefined || !Number.isInteger(cents)) return null;
  const neg = cents < 0;
  const abs = Math.abs(cents);
  const dollars = Math.floor(abs / 100).toLocaleString("en-US");
  return `${neg ? "-" : ""}$${dollars}.${String(abs % 100).padStart(2, "0")}`;
}

const ECONOMICS_COPY = {
  raked: "Raked",
  overlay: "Overlay (guaranteed, prizes exceed fees collected)",
  underfilled_not_guaranteed: "Underfilled and not guaranteed — prizes may shrink",
  underfilled_guarantee_unknown: "Underfilled; guarantee unknown — no overlay claimed",
  field_unknown: "Rake needs the current entry count",
  empty_contest: "No entries yet",
  free_contest: "Free contest — rake does not apply",
  ticket_entry: "Ticket entry — cash rake not computed",
  prize_value_unknown: "A non-cash prize has no stated value",
  unknown: "Unknown",
};

export function economicsCopy(state) {
  return ECONOMICS_COPY[state] || "Unknown";
}

const SHAPE_COPY = {
  head_to_head: "Head-to-head",
  fifty_fifty: "50/50",
  double_up: "Double-up",
  multiplier: "Multiplier",
  tournament: "Tournament (GPP)",
  unknown: "Unknown shape",
};

export function shapeLabel(shape) {
  return SHAPE_COPY[shape] || "Unknown shape";
}

/** Presets that fit a derived payout shape (shape-agnostic presets always fit). */
export function presetsForShape(presets, shape) {
  return (presets || []).filter((p) => p.dimensions?.payoutShape === "any" || p.dimensions?.payoutShape === shape);
}

export const EMPTY_CONTEST_FORM = {
  name: "",
  platformContestId: "",
  entryMethod: "cash",
  entryFee: "",
  capacity: "",
  currentEntries: "",
  guaranteed: "unknown",
  maxEntriesPerUser: "",
  existingUserEntries: "",
  tieRule: "unknown",
  payoutText: "",
  hypothetical: false,
};

/** Contest form → API payload. Blank stays absent (unknown), never 0. */
export function contestPayload(form, { platform, sport, format }) {
  const blankToNull = (v) => (v === "" || v === undefined ? null : v);
  return {
    name: form.name,
    platform,
    sport,
    format,
    platformContestId: blankToNull(form.platformContestId),
    entryMethod: form.entryMethod,
    entryFee: form.entryMethod === "free" ? null : blankToNull(form.entryFee),
    capacity: blankToNull(form.capacity),
    currentEntries: blankToNull(form.currentEntries),
    guaranteed: form.guaranteed === "yes" ? true : form.guaranteed === "no" ? false : null,
    maxEntriesPerUser: blankToNull(form.maxEntriesPerUser),
    existingUserEntries: blankToNull(form.existingUserEntries),
    tieRule: form.tieRule,
    ladderSource: form.hypothetical ? "hypothetical" : "entered",
    payoutText: form.payoutText,
  };
}

/** Stored contest (cents, snake_case) → editable form strings. */
export function contestToForm(c) {
  const money = (cents) => (cents === null || cents === undefined ? "" : (formatCents(cents) || "").replace(/[$,]/g, ""));
  const num = (v) => (v === null || v === undefined ? "" : String(v));
  const ladder = (c.ladder || [])
    .filter((b) => b.kind === "cash")
    .map((b) => `${b.min_rank === b.max_rank ? b.min_rank : `${b.min_rank}-${b.max_rank}`} ${money(b.prize_cents)}`)
    .join("\n");
  return {
    name: c.name || "",
    platformContestId: c.platform_contest_id || "",
    entryMethod: c.entry_method || "cash",
    entryFee: c.entry_method === "free" ? "" : money(c.entry_fee_cents),
    capacity: num(c.capacity),
    currentEntries: num(c.current_entries),
    guaranteed: c.guaranteed === true ? "yes" : c.guaranteed === false ? "no" : "unknown",
    maxEntriesPerUser: num(c.max_entries_per_user),
    existingUserEntries: num(c.existing_user_entries),
    tieRule: c.tie_rule || "unknown",
    payoutText: ladder,
    hypothetical: c.ladder_source === "hypothetical",
    // The paste format carries cash prizes only. A stored ticket / non-cash
    // band cannot round-trip through it, so the panel refuses to re-save
    // such a contest from the form rather than silently dropping the band.
    nonCashBands: (c.ladder || []).filter((b) => b.kind !== "cash").length,
  };
}
