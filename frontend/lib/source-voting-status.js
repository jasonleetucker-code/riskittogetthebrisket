// Shape the per-source VOTING STATUS block for Source Health and Settings.
//
// Owner directive 2026-10-19 "Universal Source Voting and Freshness Policy"
// §8: every source shows Source, Last Updated, Freshness, Voting Weight and
// Status, with a plain-English reason and expandable detail.
//
// The block is produced by the backend (src/sources/voting_status.py) and
// reaches the frontend two ways, both carrying the identical object:
//   * `votingStatus` on GET /api/sources/weighting (Source Health);
//   * `sourceVotingStatus` on the canonical contract (Settings, via the
//     already-loaded board — no second fetch).
//
// This module labels and formats.  It decides NOTHING: the status, the
// freshness percentage, the effective weight, the days since update and the
// reason are the backend's, read verbatim.  No age threshold, no weight
// product and no freshness step is computed here.  Absent values stay absent
// ("Not measured" / "Unknown"), never 0 — MISSING IS NEVER ZERO.
//
// The status → label map lives HERE and nowhere else in the frontend.  The
// server's own `statusLabel` wins whenever it is present; this map is the
// fallback for an entry that carries only the status code.

export const VOTING_STATUS = Object.freeze({
  ACTIVE_100: "active_100",
  ACTIVE_75: "active_75",
  ACTIVE_50: "active_50",
  ACTIVE_25: "active_25",
  STALE: "stale",
  DATA_ISSUE: "data_issue",
  SEASONAL: "seasonal",
  TESTING: "testing",
});

/** The owner's exact plain labels (directive §8). */
export const VOTING_STATUS_LABELS = Object.freeze({
  active_100: "Active — 100%",
  active_75: "Active — 75%",
  active_50: "Active — 50%",
  active_25: "Active — 25%",
  stale: "Stale — Not Voting",
  data_issue: "Data Issue — Not Voting",
  seasonal: "Seasonal — Not Voting",
  testing: "Testing — Not Voting",
});

/** Display order: voting sources first (strongest vote first), then the
 *  not-voting groups. */
export const VOTING_STATUS_ORDER = Object.freeze([
  "active_100",
  "active_75",
  "active_50",
  "active_25",
  "stale",
  "data_issue",
  "seasonal",
  "testing",
]);

// StatusIndicator tone.  Secondary to the label TEXT, which carries the
// meaning on its own (never colour alone).  A seasonal pause and a test-mode
// hold are not failures, so they are neutral.
const STATUS_TONE = Object.freeze({
  active_100: "positive",
  active_75: "positive",
  active_50: "warning",
  active_25: "warning",
  stale: "negative",
  data_issue: "negative",
  seasonal: "neutral",
  testing: "neutral",
});

/** The block's freshness rule identifier for the owner's weekly schedule. */
export const STEP_SCHEDULE_ID = "v2_step_schedule";

const BASIS_LABELS = Object.freeze({
  publisher_timestamp: "the date the publisher says it last updated",
  content_change_observed: "the last time we saw its rankings actually change",
  unknown: "no genuine update has been observed yet",
  not_tracked_at_board_time: "update tracking did not cover this board's date",
});

const COVERAGE_LABELS = Object.freeze({
  offense: "Offense",
  idp: "IDP",
  rookie: "Rookie",
  combined: "Offense + IDP",
});

// Why a source's rows were not counted (`notVotingRows` keys, from each
// row's `sourceRankMeta`).  An unrecognised key is shown as itself.
const NOT_VOTING_REASON_LABELS = Object.freeze({
  outlier_filter: "Set aside by the outlier filter",
  freshness_or_health_zero_weight: "Too old, or the download was unusable",
  superseded_by_family: "Counted through another source from the same provider",
  not_contributed: "Not used in the blend",
  zero_weight: "Carried no weight",
});

// ── Outlier integrity v2: observation categories (owner directive
// 2026-10-20 §10) ──────────────────────────────────────────────────────────
//
// The backend (src/api/source_integrity.py) stamps every observation it
// tested with a `category` and a `primaryReason`; this map only LABELS them.
// It decides nothing and never upgrades or downgrades a category.  A
// legitimate dissent ("valid_but_disagreeing") is still a voting observation
// and must never read as corrupt or invalid.  Held observations read as
// "held pending confirmation", never as corrupt.

export const INTEGRITY_CATEGORY_LABELS = Object.freeze({
  voting_normally: "Voting normally",
  valid_but_disagreeing: "Voting — disagrees with other sources",
  invalid_player_identity: "Not voting — could not confirm this is the same player",
  source_format_error: "Not voting — the source file was malformed",
  normalization_scale_error: "Not voting — the source's scale could not be converted reliably",
  stale_source: "Not voting — too old, or the download was unusable",
  broken_feed: "Not voting — the feed capture was broken",
  missing_observation: "No observation from this source",
  temporarily_held_by_policy: "Held pending confirmation or by policy",
  rejected_by_integrity_rule:
    "Set aside — extreme and uncorroborated by any other provider, with no history yet",
});

// Reason code (or the prefix before ":" / "@") → category, the label-side
// mirror of `OBSERVATION_REASON_CATEGORY` in src/sources/voting_status.py
// (re-exported as `REASON_CATEGORY` by src/api/source_integrity.py) (parity pinned
// by tests/api/test_outlier_integrity_v2_layer_c.py).  Used only to LABEL a
// reason that arrives without its category (e.g. a `notVotingRows` key).
export const INTEGRITY_REASON_CATEGORY = Object.freeze({
  voting: "voting_normally",
  voting_name_only_identity: "voting_normally",
  // V2.1 (default OFF): votes that still count, with an advisory.
  voting_team_unconfirmed: "voting_normally",
  format_minor_discordance: "voting_normally",
  segment_too_small: "voting_normally",
  released_by_cap: "voting_normally",
  kept_dissent: "valid_but_disagreeing",
  segment_break_unproven: "valid_but_disagreeing",
  persistent_gross_dissent: "valid_but_disagreeing",
  identity_contradicted: "invalid_player_identity",
  source_format_error: "source_format_error",
  normalization_untranslated: "normalization_scale_error",
  normalization_dependency_unavailable: "normalization_scale_error",
  normalization_scale_error: "normalization_scale_error",
  normalization_direction_error: "normalization_scale_error",
  withheld_no_bridge: "normalization_scale_error",
  freshness_or_health_zero_weight: "stale_source",
  broken_feed: "broken_feed",
  held_pending_confirmation: "temporarily_held_by_policy",
  identity_unresolved: "temporarily_held_by_policy",
  dlf_offense_only_vote: "temporarily_held_by_policy",
  dlf_values_rank_hill_vote: "temporarily_held_by_policy",
  policy_vote_hold: "temporarily_held_by_policy",
  extreme_uncorroborated_tail: "rejected_by_integrity_rule",
});

/** The category of a reason code (exact, else its prefix), or null. */
export function integrityReasonCategory(code) {
  const c = text(code);
  if (!c) return null;
  if (INTEGRITY_REASON_CATEGORY[c]) return INTEGRITY_REASON_CATEGORY[c];
  for (const sep of [":", "@"]) {
    const head = c.split(sep, 1)[0];
    if (INTEGRITY_REASON_CATEGORY[head]) return INTEGRITY_REASON_CATEGORY[head];
  }
  return null;
}

/** Plain label for a category; an unknown category is shown as itself. */
export function integrityCategoryLabel(category) {
  const c = text(category);
  if (!c) return null;
  return INTEGRITY_CATEGORY_LABELS[c] || c;
}

/**
 * Label for one observation's integrity block (`sourceRankMeta[k].integrity`):
 * the backend's own category first, else the category of its primary reason.
 * Null when the observation carries no block (V2 off) — nothing is assumed.
 */
export function integrityLabel(integrity) {
  if (!integrity || typeof integrity !== "object") return null;
  const category = text(integrity.category) || integrityReasonCategory(integrity.primaryReason);
  return category ? integrityCategoryLabel(category) : null;
}

function finite(n) {
  return typeof n === "number" && Number.isFinite(n);
}

function text(v) {
  return typeof v === "string" && v.trim() ? v.trim() : null;
}

/**
 * The label for one entry: the server's `statusLabel` when present, else the
 * owner label for its status code, else the code itself (an unknown code is
 * shown as itself rather than mapped onto a reassuring label).
 */
export function statusLabelFor(entry) {
  const server = text(entry?.statusLabel);
  if (server) return server;
  const code = text(entry?.status);
  if (code && VOTING_STATUS_LABELS[code]) return VOTING_STATUS_LABELS[code];
  return code || "Unknown status";
}

export function statusTone(status) {
  return STATUS_TONE[status] || "neutral";
}

/** True for the four Active statuses. */
export function isActiveStatus(status) {
  return (
    status === "active_100" ||
    status === "active_75" ||
    status === "active_50" ||
    status === "active_25"
  );
}

/**
 * The voting-status block from either carrier, or null.
 *   * GET /api/sources/weighting → `payload.votingStatus`
 *   * the canonical contract     → `payload.sourceVotingStatus`
 */
export function votingStatusBlock(payload) {
  if (!payload || typeof payload !== "object") return null;
  const block = payload.votingStatus ?? payload.sourceVotingStatus ?? null;
  return block && typeof block === "object" ? block : null;
}

/**
 * Is there anything honest to render?  `reason` distinguishes a board built
 * before the block existed (`absent`) from a malformed or empty one.
 */
export function votingStatusAvailability(block) {
  if (!block || typeof block !== "object") return { available: false, reason: "absent" };
  if (!Array.isArray(block.sources)) return { available: false, reason: "malformed" };
  if (block.sources.length === 0) return { available: false, reason: "empty" };
  return { available: true, reason: null };
}

/** ISO → "Oct 10, 2026" in UTC (the backend's clock).  Null → null. */
export function formatUpdateDate(iso) {
  if (!iso) return null;
  const t = Date.parse(iso);
  if (!Number.isFinite(t)) return null;
  return new Date(t).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    timeZone: "UTC",
  });
}

/** The backend's whole-day count → "today" / "1 day ago" / "8 days ago". */
export function formatDaysAgo(days) {
  if (!finite(days)) return null;
  if (days <= 0) return "today";
  return `${days} day${days === 1 ? "" : "s"} ago`;
}

/** 75 → "75%".  Null stays null (rendered as "Not measured"/"Unknown"). */
export function formatPct(pct) {
  if (!finite(pct)) return null;
  const rounded = Math.round(pct * 10) / 10;
  return `${Number.isInteger(rounded) ? rounded.toFixed(0) : rounded.toFixed(1)}%`;
}

/** 0.75 → "0.75".  Null → "—" (unknown is not zero). */
export function formatWeight(w) {
  return finite(w) ? w.toFixed(2) : "—";
}

export function basisLabel(basis) {
  return BASIS_LABELS[basis] || (basis ? String(basis) : BASIS_LABELS.unknown);
}

export function coverageLabel(coverage) {
  return COVERAGE_LABELS[coverage] || (coverage ? String(coverage) : null);
}

export function notVotingReasonLabel(reason) {
  if (NOT_VOTING_REASON_LABELS[reason]) return NOT_VOTING_REASON_LABELS[reason];
  const category = integrityReasonCategory(reason);
  return category ? integrityCategoryLabel(category) : String(reason);
}

function lastUpdatedText(iso, basis) {
  const date = formatUpdateDate(iso);
  if (date) return date;
  return basis === "not_tracked_at_board_time" ? "Not tracked" : "Unknown";
}

function freshnessText(pct, basis) {
  const label = formatPct(pct);
  if (label) return label;
  return basis === "not_tracked_at_board_time" ? "Not measured" : "Unknown";
}

function count(n) {
  return finite(n) ? n : null;
}

/** One normalised display row per source, in the backend's (registry) order. */
export function votingStatusRows(block) {
  const sources = Array.isArray(block?.sources) ? block.sources : [];
  return sources
    .filter((e) => e && typeof e === "object")
    .map((e, i) => {
      const key = text(e.key) || `source-${i}`;
      const status = text(e.status);
      const basis = text(e.lastGenuineUpdateBasis);
      const rankIdx = VOTING_STATUS_ORDER.indexOf(status);
      const factors = e.weightFactors && typeof e.weightFactors === "object" ? e.weightFactors : {};
      const byUniverse =
        e.contributingByUniverse && typeof e.contributingByUniverse === "object"
          ? e.contributingByUniverse
          : {};
      const notVoting =
        e.notVotingRows && typeof e.notVotingRows === "object" ? e.notVotingRows : {};
      const picks = e.picks && typeof e.picks === "object" ? e.picks : null;
      const hold = e.voteHold && typeof e.voteHold === "object" ? e.voteHold : null;
      return {
        id: key,
        key,
        label: text(e.displayName) || key,
        provider: text(e.provider),
        family: text(e.family),
        coverage: text(e.coverage),
        coverageLabel: coverageLabel(text(e.coverage)),
        status,
        statusLabel: statusLabelFor(e),
        tone: statusTone(status),
        statusRank: rankIdx === -1 ? VOTING_STATUS_ORDER.length : rankIdx,
        voting: typeof e.voting === "boolean" ? e.voting : null,
        reason: text(e.reason),
        restoreRequirement: text(e.restoreRequirement),
        lastUpdated: text(e.lastGenuineUpdate),
        lastUpdatedLabel: lastUpdatedText(text(e.lastGenuineUpdate), basis),
        lastUpdatedBasis: basis,
        basisLabel: basisLabel(basis),
        daysSinceUpdate: finite(e.daysSinceUpdate) ? e.daysSinceUpdate : null,
        agoLabel: formatDaysAgo(e.daysSinceUpdate),
        freshnessPct: finite(e.freshnessPct) ? e.freshnessPct : null,
        freshnessLabel: freshnessText(e.freshnessPct, basis),
        baseWeight: finite(e.baseWeight) ? e.baseWeight : null,
        effectiveWeight: finite(e.effectiveWeight) ? e.effectiveWeight : null,
        meanAppliedWeight: finite(e.meanAppliedWeight) ? e.meanAppliedWeight : null,
        factors: {
          freshness: finite(factors.freshness) ? factors.freshness : null,
          health: finite(factors.health) ? factors.health : null,
          coverage: finite(factors.coverage) ? factors.coverage : null,
          applied: typeof factors.applied === "boolean" ? factors.applied : null,
        },
        playersContributing: count(e.playersContributing),
        picksContributing: count(e.picksContributing),
        contributing: {
          offense: count(byUniverse.offense),
          idp: count(byUniverse.idp),
          pick: count(byUniverse.pick),
        },
        notVotingRows: Object.entries(notVoting)
          .filter(([, n]) => finite(n) && n > 0)
          .map(([reason, n]) => ({ reason, label: notVotingReasonLabel(reason), count: n })),
        voteHold: hold
          ? {
              decision: text(hold.decision),
              reason: text(hold.reason),
              kind: text(hold.kind),
              rollbackFlag: text(hold.rollbackFlag),
            }
          : null,
        picks: picks
          ? {
              lastUpdatedLabel: lastUpdatedText(
                text(picks.lastGenuineUpdate),
                text(picks.lastGenuineUpdateBasis),
              ),
              agoLabel: formatDaysAgo(picks.daysSinceUpdate),
              basisLabel: basisLabel(text(picks.lastGenuineUpdateBasis)),
              freshnessLabel: freshnessText(picks.freshnessPct, text(picks.lastGenuineUpdateBasis)),
              effectiveWeight: finite(picks.effectiveWeight) ? picks.effectiveWeight : null,
            }
          : null,
        health: text(e.health),
      };
    });
}

/**
 * Count of sources per status, in display order, for the summary line.
 * The voting / registered totals are the backend's when it states them.
 *
 * Groups are keyed by status AND the label the row actually shows (the
 * server's `statusLabel`).  Under the owner step schedule those coincide.
 * Under the v1 cadence curve (in force while the step schedule is held) an
 * Active code is only a band and each row's label names its ACTUAL
 * percentage, so grouping by code alone would print a step label such as
 * "Active — 25%" for a source voting at 16.2%.
 */
export function votingStatusSummary(block, rows = votingStatusRows(block)) {
  const counts = new Map();
  for (const r of rows) {
    const status = r.status || "unknown";
    const label = text(r.statusLabel) || statusLabelFor({ status: r.status || null });
    const key = `${status}\u0000${label}`;
    const seen = counts.get(key);
    if (seen) seen.count += 1;
    else counts.set(key, { status, label, count: 1 });
  }
  const groups = [...counts.entries()]
    .map(([key, g]) => ({
      key,
      status: g.status,
      count: g.count,
      label: g.label,
      tone: statusTone(g.status),
      rank:
        VOTING_STATUS_ORDER.indexOf(g.status) === -1 ? 99 : VOTING_STATUS_ORDER.indexOf(g.status),
    }))
    .sort((a, b) => a.rank - b.rank);
  const votingCount = finite(block?.votingCount)
    ? block.votingCount
    : rows.filter((r) => r.voting === true).length;
  const registeredCount = finite(block?.registeredCount) ? block.registeredCount : rows.length;
  return {
    groups,
    votingCount,
    registeredCount,
    asOf: text(block?.asOf),
    asOfLabel: formatUpdateDate(text(block?.asOf)),
    freshnessApplied: typeof block?.freshnessApplied === "boolean" ? block.freshnessApplied : null,
    stepSchedule: block?.freshnessSchedule === STEP_SCHEDULE_ID,
  };
}
