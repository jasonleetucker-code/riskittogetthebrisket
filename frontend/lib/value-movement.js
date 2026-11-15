// lib/value-movement.js — labels and selectors for the backend
// "why did this value move" read (value-movement/v1).
//
// ``GET /api/players/{player}/value-movement`` (owner:
// src/history/movement.py::value_movement, adapted for one contract row by
// src/api/value_movement.py) answers, between the current board generation
// and the previous one, the CONTRIBUTING EVIDENCE the temporal ledger
// actually stores: canonical value/rank at both ends, per-source
// vendor-value deltas, sources that appeared or disappeared, the pipeline
// version at both ends, and every quantity the ledger does NOT store, named
// as unobserved. It is explicitly non-additive.
//
// Display-only: these helpers LABEL backend enums and SELECT fields. No
// value, delta, weight, share or rank is computed here — every number is the
// backend's, and an absent one stays null (rendered as "not recorded"),
// never 0. An enum this file does not know renders as its raw string.

import { sourceLabel } from "./value-explainers";

export const VALUE_MOVEMENT_V1 = "value-movement/v1";

export const MOVEMENT_STATUS_COPY = {
  ok: null,
  no_current_generation: "No board generation for this asset is recorded in the history ledger.",
  no_comparator: "There is no earlier board generation to compare against.",
  unkeyed: "This asset has no history key, so its movement cannot be looked up.",
};

export const MISSING_REASON_LABELS = {
  before_history_boundary: "the request is before the history floor — nothing earlier survives",
  no_prior_observation: "the ledger holds no earlier observation of this asset",
  no_prior_board_generation: "this is the first board generation the ledger holds",
  outside_max_age: "the nearest earlier observation is too old to compare",
  asset_has_no_history_key: "the asset could not be keyed for history",
};

export const SOURCE_MOVEMENT_LABELS = {
  moved: "Moved",
  unchanged: "Unchanged",
  appeared: "Appeared",
  disappeared: "Disappeared",
};

export const SOURCE_ROLE_LABELS = {
  model_input: "Model input",
  benchmark_not_a_vote: "Benchmark — not a vote",
  held_from_voting: "Held from voting",
};

export const FIDELITY_LABELS = {
  exact: "recorded that day",
  "nearest-prior": "latest earlier record",
  unavailable: "not recorded",
};

/** What an unrecorded source is doing on TODAY's board (backend-stamped). */
export const TODAY_ROLE_LABELS = {
  voted_today: "voted today",
  not_voting_today: "not voting today",
  vote_state_unpublished: "vote state not published",
  benchmark_not_a_vote: "benchmark — not a vote",
  held_from_voting: "held from voting",
};

export const ALIGNMENT_REASON_LABELS = {
  ledger_behind_served_board: "the history ledger has not recorded the board on screen yet",
  asset_absent_from_comparator_board:
    "this asset was not on the previous board, so the earlier value is its last recorded one before it",
};

export const GENERATION_MATCH_LABELS = {
  instant: null,
  date: "matched by date — the record carries no scrape time",
};

export const UNOBSERVED_LABELS = {
  sourceWeights: "Source weights",
  sourceFreshness: "Source freshness",
  voteState: "Which sources voted or were excluded",
  anomalyFlags: "Quarantine and anomaly flags",
  rankSignalSourceValues: "Values from rank-based sources",
};

function finiteOrNull(v) {
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

function end(e) {
  if (!e || typeof e !== "object") return null;
  return {
    date: e.observedDate || null,
    at: e.observedAt || null,
    fidelity: e.fidelity || null,
    fidelityLabel: e.fidelity ? FIDELITY_LABELS[e.fidelity] || String(e.fidelity) : null,
    value: finiteOrNull(e.value),
    rank: finiteOrNull(e.rank),
    tier: finiteOrNull(e.tier),
    confidence: e.confidence ? String(e.confidence) : null,
    pipelineVersion: e.pipelineVersion ? String(e.pipelineVersion) : null,
  };
}

function sourceEnd(e) {
  const x = e && typeof e === "object" ? e : {};
  const match = x.present === true && x.generationMatch ? String(x.generationMatch) : null;
  return {
    present: x.present === true,
    value: x.present === true ? finiteOrNull(x.value) : null,
    generationMatch: match,
    generationMatchNote: match ? (GENERATION_MATCH_LABELS[match] ?? match) : null,
    lastObservedDate: x.lastObservedDate || null,
    lastObservedAt: x.lastObservedAt || null,
  };
}

/** Whole-number formatting with an explicit sign; null stays null. */
export function formatSignedValue(n) {
  if (n == null || !Number.isFinite(n)) return null;
  const abs = Math.round(Math.abs(n)).toLocaleString("en-US");
  if (n > 0) return `+${abs}`;
  if (n < 0) return `−${abs}`;
  return "0";
}

/**
 * A recorded generation as "YYYY-MM-DD HH:MM UTC" when it carries a scrape
 * instant, else just its date. Formatting only; null stays null.
 */
export function formatGeneration(date, at) {
  if (at && typeof at === "string" && at.length >= 16) {
    const zoned = /([zZ]|[+-]\d\d:?\d\d)$/.test(at);
    if (zoned) {
      const t = new Date(at);
      if (!Number.isNaN(t.getTime())) {
        const iso = t.toISOString();
        return `${iso.slice(0, 10)} ${iso.slice(11, 16)} UTC`;
      }
    }
    return `${at.slice(0, 10)} ${at.slice(11, 16)}`;
  }
  return date || null;
}

export function formatValue(n) {
  if (n == null || !Number.isFinite(n)) return null;
  return Math.round(n).toLocaleString("en-US");
}

function alignmentView(a) {
  if (!a || typeof a !== "object") return null;
  const reasons = Array.isArray(a.reasons) ? a.reasons.map(String) : [];
  return {
    sameBoards: a.sameBoardsAsRankChange === true,
    rankChangeComparatorDate: a.rankChangeComparatorDate || null,
    reasons: reasons.map((r) => ALIGNMENT_REASON_LABELS[r] || r),
  };
}

/**
 * Select what the "Why it moved" view renders, from the payload alone.
 */
export function valueMovementView(payload) {
  const p = payload && typeof payload === "object" ? payload : {};
  const status = typeof p.status === "string" ? p.status : null;
  const change = p.change && typeof p.change === "object" ? p.change : null;
  const meth = p.methodology && typeof p.methodology === "object" ? p.methodology : null;
  const live = p.liveBoard && typeof p.liveBoard === "object" ? p.liveBoard : null;
  const ctx = p.currentContext && typeof p.currentContext === "object" ? p.currentContext : null;
  return {
    version: typeof p.schema === "string" ? p.schema : null,
    isV1: p.schema === VALUE_MOVEMENT_V1,
    status,
    ok: status === "ok",
    statusCopy: status in MOVEMENT_STATUS_COPY ? MOVEMENT_STATUS_COPY[status] : status,
    missingReason: p.missingReason || null,
    missingReasonLabel: p.missingReason
      ? MISSING_REASON_LABELS[p.missingReason] || String(p.missingReason)
      : null,
    historyFloor: p.historyFloor || null,
    // The backend labels it; the UI says it regardless.
    additive: p.additive === true,
    nonAdditiveNote: p.nonAdditiveNote ? String(p.nonAdditiveNote) : null,
    current: end(p.current),
    previous: end(p.previous),
    comparatorBoardDate: p.comparatorBoardDate || null,
    valueChange: change ? finiteOrNull(change.value) : null,
    rankChange: change ? finiteOrNull(change.rank) : null,
    tierChanged: change ? (change.tierChanged ?? null) : null,
    confidenceChanged: change ? (change.confidenceChanged ?? null) : null,
    pipelineVersionChanged: meth ? (meth.pipelineVersionChanged ?? null) : null,
    methodologyCovers: meth?.covers ? String(meth.covers) : null,
    sources: (Array.isArray(p.sources) ? p.sources : []).map((s) => ({
      key: String(s?.source || ""),
      label: s?.source ? sourceLabel(s.source) : "unknown source",
      status: s?.status ? String(s.status) : null,
      statusLabel: SOURCE_MOVEMENT_LABELS[s?.status] || String(s?.status || "unknown"),
      role: s?.role ? String(s.role) : null,
      roleLabel: s?.role ? SOURCE_ROLE_LABELS[s.role] || String(s.role) : null,
      previous: sourceEnd(s?.previous),
      current: sourceEnd(s?.current),
      delta: finiteOrNull(s?.delta),
    })),
    notObserved: (Array.isArray(p.sourcesNotObservedAtEitherGeneration)
      ? p.sourcesNotObservedAtEitherGeneration
      : []
    ).map((k) => sourceLabel(k)),
    unobserved: (Array.isArray(p.unobserved) ? p.unobserved : []).map((u) => ({
      key: String(u?.quantity || ""),
      label: UNOBSERVED_LABELS[u?.quantity] || String(u?.quantity || ""),
      reason: u?.reason ? String(u.reason) : null,
    })),
    liveBoardDate: live?.boardDate || null,
    liveBoardAt: live?.scrapeTimestamp || null,
    currentIsLiveBoard: p.currentGenerationIsLiveBoard ?? null,
    currentIsLiveBoardBasis: p.currentGenerationIsLiveBoardBasis || null,
    alignment: alignmentView(p.rankChangeAlignment),
    currentFlags: Array.isArray(ctx?.anomalyFlags) ? ctx.anomalyFlags.map(String) : [],
    currentQuarantined: ctx?.quarantined === true,
    unrecordedToday: (Array.isArray(ctx?.sourcesNotRecordedInLedger)
      ? ctx.sourcesNotRecordedInLedger
      : []
    ).map((u) => {
      // Older payloads listed bare keys; their role was never published.
      const key = typeof u === "string" ? u : String(u?.source || "");
      const role = typeof u === "string" ? "vote_state_unpublished" : String(u?.role || "");
      return {
        key,
        label: sourceLabel(key),
        role,
        roleLabel: TODAY_ROLE_LABELS[role] || role || "vote state not published",
      };
    }),
  };
}
