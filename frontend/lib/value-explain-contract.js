// lib/value-explain-contract.js — labels and selectors for the backend
// per-player value explanation (value-explain/v2).
//
// The copy owner for value explanation is lib/value-explainers.js; this
// module holds only the v2 contract's enum labels, split out so they ship
// in the Player File's lazily loaded explanation chunk instead of the chunk
// Rankings shares. Same rules as that file.
//
// ``GET /api/players/{player}/value-explain`` (owner:
// src/api/source_weighting_explain.py::player_explain) answers, per row,
// WHICH estimator produced the value, whether vote-share attribution is
// exact, a leave-one-out, and per source three clocks, the freshness
// treatment applied and why a non-voter was excluded. The helpers below
// only LABEL those backend enums and select fields — no value, weight,
// share, rank or confidence is computed here. An enum this file does not
// know renders as its raw string, never as a guess.

import { sourceLabel } from "./value-explainers";

export const VALUE_EXPLAIN_V2 = "value-explain/v2";

export const ESTIMATOR_PATH_LABELS = {
  flat_count_aware_blend: "Count-aware weighted blend of every voting source",
  anchor_plus_alpha_shrinkage: "Anchor blend with shrinkage toward the anchor (the IDP rule)",
  off_cap_value_only: "Value only — past the official rank limit, no per-source stamps",
  no_breakdown: "No per-source breakdown is published for this row",
  direct_market_blend: "Pick — blend of the pick markets",
  rookie_pool_tether: "Pick — inherits the value of the rookie at this draft slot",
  derived_year_step: "Pick — derived from the nearest priced year",
  derived_round_step: "Pick — derived from the same year's nearest priced round",
  derived_uniform_tier_ev: "Pick — average of its year-and-round tiers",
  alias_suppressed: "Pick — an alias of another pick row",
  unavailable: "Pick — no value available",
  pick_unknown_provenance: "Pick — provenance not published",
};

export const ESTIMATOR_RUNG_LABELS = {
  no_voters: "no source voted",
  passthrough: "one source — its value passes straight through",
  weighted_mean: "weighted mean of two sources",
  weighted_mean_median_untrimmed: "weighted mean-median of 3–4 sources, untrimmed",
  weighted_mean_median_trimmed: "weighted mean-median of 5+ sources, extremes trimmed",
};

export const ESTIMATOR_OVERRIDE_LABELS = {
  two_way_player_boost: "Two-way player boost — value set from the player's other-position market",
  rookie_pool_tether: "Rookie-slot tether — value inherited from the rookie at this slot",
};

export const SOURCE_STATUS_LABELS = {
  voting: "Voting",
  excluded_stale_or_unhealthy: "Not voting",
  hampel_outlier: "Not voting",
  superseded_by_family: "Not voting",
};

export const FRESHNESS_TREATMENT_LABELS = {
  full_weight: "Full weight",
  down_weighted: "Down-weighted for age",
  excluded: "Excluded",
  unknown: "Freshness not measured",
};

/** The three clocks, kept apart, plus the broad-change clock. */
export const SOURCE_CLOCK_LABELS = {
  lastFetchedAt: "Last fetched",
  publishedAsOf: "Published / as of",
  lastConfirmedChangeAt: "Last confirmed change",
  lastBroadChangeAt: "Last broad change",
};

const FRESHNESS_CLOCK_LABELS = {
  lastBroadDatasetChangeAt: "its last broad change",
  upstreamPublishedAt: "the source's own publication date",
};

const LEAVE_ONE_OUT_REASON_LABELS = {
  not_applicable:
    "only computed for offense rows — IDP and pick values come from an anchor or pick path a simple re-run cannot reproduce",
  no_voters: "no source voted on this row",
  mismatch:
    "the stamped sources did not reproduce the published blend, so a re-run would not be trustworthy",
  fewer_than_two_voters: "it needs at least two voting sources",
};

/** Plain-language reason a source did not vote; null for a voter. */
export function exclusionReasonLabel(reason, status) {
  if (reason == null || reason === "") {
    return status && status !== "voting" ? "reason not published" : null;
  }
  const r = String(reason);
  if (r === "freshness_or_health_zero_weight") return "too stale or unhealthy to carry weight";
  if (r === "superseded_by_family") return "superseded by another member of its provider family";
  if (r === "outlier:hampel") return "dropped as an outlier (Hampel filter)";
  if (r.startsWith("outlier:")) return `dropped as an outlier (${r.slice("outlier:".length)})`;
  return r;
}

export function freshnessClockLabel(clock) {
  if (!clock) return null;
  return FRESHNESS_CLOCK_LABELS[clock] || String(clock);
}

export function leaveOneOutReasonLabel(reason) {
  if (!reason) return "not available";
  return LEAVE_ONE_OUT_REASON_LABELS[reason] || String(reason);
}

function finiteOrNull(v) {
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

/**
 * Select what the v2 explanation view renders, from the payload alone.
 * Every number is the backend's; absent fields stay null (rendered as
 * "unknown" / "not published"), never 0. A pre-v2 payload is reported as
 * such rather than padded.
 */
export function valueExplainView(payload) {
  const p = payload && typeof payload === "object" ? payload : {};
  const version = typeof p.explainVersion === "string" ? p.explainVersion : null;
  const est = p.estimator && typeof p.estimator === "object" ? p.estimator : null;
  const attr = p.attribution && typeof p.attribution === "object" ? p.attribution : null;
  const loo = p.leaveOneOut && typeof p.leaveOneOut === "object" ? p.leaveOneOut : null;
  const sources = (Array.isArray(p.modelSources) ? p.modelSources : []).map((s) => {
    const clocks = s?.clocks && typeof s.clocks === "object" ? s.clocks : {};
    const treatment =
      s?.freshnessTreatment && typeof s.freshnessTreatment === "object" ? s.freshnessTreatment : {};
    const status = String(s?.status || "") || null;
    return {
      key: String(s?.source || ""),
      label: s?.source ? sourceLabel(s.source) : "unknown source",
      family: s?.family ? String(s.family) : null,
      familyLabel: s?.family ? sourceLabel(s.family) : null,
      status,
      voting: status === "voting",
      statusLabel: SOURCE_STATUS_LABELS[status] || status || "status not published",
      exclusionReason: s?.exclusionReason ?? null,
      exclusionLabel: exclusionReasonLabel(s?.exclusionReason, status),
      voteShare: finiteOrNull(s?.voteShare),
      contribution: finiteOrNull(s?.contribution),
      normalizedValue: finiteOrNull(s?.normalizedValue),
      // The backend stamps this per source; absent means we cannot claim
      // exactness either, so absent reads as approximate.
      contributionIsApproximate: s?.contributionIsApproximate !== false,
      treatment: treatment.treatment ? String(treatment.treatment) : "unknown",
      treatmentFactor: finiteOrNull(treatment.factor),
      treatmentState: treatment.state ? String(treatment.state) : null,
      clocks: Object.keys(SOURCE_CLOCK_LABELS).map((k) => ({
        key: k,
        label: SOURCE_CLOCK_LABELS[k],
        at: clocks[k] || null,
      })),
      judgedOn: freshnessClockLabel(clocks.judgedOn),
    };
  });
  return {
    version,
    isV2: version === VALUE_EXPLAIN_V2,
    player: p.player || null,
    modelValue: finiteOrNull(p.modelValue),
    breakdownAvailable: p.sourceBreakdownAvailable !== false && sources.length > 0,
    sources,
    estimator: est
      ? {
          path: est.path ? String(est.path) : null,
          pathLabel: est.path
            ? ESTIMATOR_PATH_LABELS[est.path] || String(est.path)
            : "estimator not published",
          rung: est.rung ? String(est.rung) : null,
          rungLabel: est.rung ? ESTIMATOR_RUNG_LABELS[est.rung] || String(est.rung) : null,
          voters: finiteOrNull(est.voters),
          haircut: est.singleSourceRetentionApplied === true,
          limitedEvidence: est.limitedEvidence ?? null,
          overrides: (Array.isArray(est.postBlendOverrides) ? est.postBlendOverrides : []).map(
            (o) => ESTIMATOR_OVERRIDE_LABELS[o] || String(o),
          ),
          anchorValue: finiteOrNull(est.anchorValue),
          alphaShrinkage: finiteOrNull(est.alphaShrinkage),
        }
      : null,
    // Exact ONLY when the backend says so; anything else is approximate.
    attributionExact: attr?.exact === true,
    attributionNote: attr?.note ? String(attr.note) : null,
    leaveOneOut: loo
      ? {
          available: loo.available === true,
          reason: loo.available === true ? null : leaveOneOutReasonLabel(loo.reason),
          // The backend labels it; the UI always says it regardless.
          nonAdditive: loo.nonAdditive !== false,
          publishedBlend: finiteOrNull(loo.publishedBlend),
          rows: (Array.isArray(loo.withoutEach) ? loo.withoutEach : []).map((r) => ({
            key: String(r?.source || ""),
            label: sourceLabel(r?.source),
            valueWithout: finiteOrNull(r?.valueWithout),
            delta: finiteOrNull(r?.delta),
          })),
        }
      : null,
  };
}

