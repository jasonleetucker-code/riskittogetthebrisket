// ── Value explainers — the ONE owner of player-value explanation copy ──
//
// Rankings and the Player File both have to answer, from the UI, what a
// player's value means, rank vs value, dynasty value vs projection, why
// league / scoring context matters, what confidence (and missing
// confidence) means, how fresh the value is and where it came from.
// Before this module those answers were hand-maintained in five places
// (a column tooltip, a stat-tile badge, a fallback string, the methodology
// list and the popup's value chain) and four of them had drifted onto
// retired methodology — "2+ sources, tight agreement (spread ≤30)" for
// confidence, "the blend penalized source disagreement" for the retired
// λ·MAD penalty, "measured on the backend's spread signal".
//
// Rules for this file:
//   * It EXPLAINS; it decides nothing. No value, rank, confidence level or
//     freshness factor is computed here — every number shown comes from a
//     backend stamp (row fields, `methodology`, `sourceWeighting`,
//     `dataFreshness`). The helpers below only select and label them.
//   * Every sentence describes CURRENT released behaviour, verified against
//     the canonical owner named in the section's `owner` field. No future
//     plans, no superseded logic. When the owner changes, change this file
//     and the two surfaces follow.
//   * Parameters the backend publishes are read from the contract rather
//     than restated (rank limit, scale, freshness formula), so the prose
//     cannot advertise a number the board is not held to.
//
// The per-player backend explanation (GET /api/players/{p}/value-explain,
// value-explain/v2) has its enum labels in lib/value-explain-contract.js —
// split out so they ship only in the Player File's lazily loaded
// explanation chunk instead of in the chunk Rankings shares. Same rules.
//
// Canonical owners: src/api/data_contract.py::_compute_unified_rankings
// (value), src/api/confidence.py (confidence), src/sources/freshness.py +
// config/sources/freshness_v1.json (freshness weighting),
// docs/sources/SOURCE_FRESHNESS_WEIGHTING.md (methodology record).

import { RANKING_SOURCES } from "./dynasty-data";

// ── Source keys that are published on the contract but never vote ──────
// Mirrors ``_NON_VOTING_SOURCE_CSV_KEYS`` in src/api/data_contract.py
// (parity pinned by __tests__/value-explainers.test.js, which reads the
// Python source). ``ktc`` / ``ktcSfTep`` are historical market fallbacks;
// ``ktcCrowdTradesSfTep`` is the KTC Market BENCHMARK — KTC's own
// published Crowd+Trades number, compared against, never blended.
export const NON_VOTING_SOURCE_KEYS = new Set([
  "ktc",
  "ktcSfTep",
  "ktcCrowdTradesSfTep",
]);

export function isNonVotingSourceKey(key) {
  return NON_VOTING_SOURCE_KEYS.has(String(key || ""));
}

// ── Explanation sections (short → detail → methodology owner) ──────────
//
// `short` is what an InfoTip shows beside the number. `detail` paragraphs
// are the expandable version (HelpModal). `owner` names the canonical
// methodology source a reader (or maintainer) can check it against.
export const VALUE_EXPLAINERS = {
  value: {
    title: "What Our Value means",
    short:
      "Our Value is the canonical dynasty value on a 1–9,999 scale — one number per player, the same number Rankings, the Trade Calculator and the Player File read. Higher is more valuable.",
    detail: [
      "It blends every registered dynasty source that covers the player. Value-based markets (KTC Crowd, KTC Trades, IDP Trade Calculator) vote with their own values rescaled to 9,999; ranking sources are converted from rank to value through the Hill curve so the two kinds are comparable.",
      "The votes are combined with a count-aware weighted mean-median, so a single outlying source moves it little. A player (not a pick) backed by only one evidence family keeps 30% of the blended value — the single-source haircut.",
      "If you change source weights, the same backend pipeline recomputes the board with your weights; the Custom mix badge on Rankings says when that is active.",
    ],
    owner: "src/api/data_contract.py — _compute_unified_rankings",
  },
  rankVsValue: {
    title: "Rank vs value",
    short:
      "Rank (#) is the player's place on the board sorted by value; value is how much. Two neighbours can be a few points or a whole tier apart — the value tells you which.",
    detail: [
      "Rank is an ordinal. Value is the magnitude it is sorted from. Use value to judge a trade; use rank to find a player.",
      "Only the top of the board receives an official rank. Players past the rank limit can still carry a value; Rankings lists them below in value order with a display position, which is not an official rank.",
      "Position rank (e.g. QB3) is the same ordering within one position. Tier breaks mark natural value cliffs detected on the board.",
      "Consensus is the mean of each source's effective rank. It is a diagnostic, not the rank: the rank comes from the blended value, which weighs sources differently.",
    ],
    owner: "src/api/data_contract.py — OVERALL_RANK_LIMIT, canonicalTierId",
  },
  dynastyVsProjection: {
    title: "Dynasty value vs projection",
    short:
      "Our Value is a long-horizon dynasty market value, not a points projection. Rest-of-season outlook and projections are separate numbers and never change it.",
    detail: [
      "Only sources verified as dynasty boards feed this value. Redraft, rest-of-season, weekly and DFS rankings are never blended into it — even from a provider we otherwise use.",
      "Rest-of-season strength and realized points (short-term) and BDVM fundamentals (a separate projection-based value) appear in their own sections, labelled as such. They explain the player; they do not re-price him.",
    ],
    owner: "CLAUDE.md — Source-domain boundaries",
  },
  leagueContext: {
    title: "League and scoring context",
    short:
      "Scoring decides which board you see; your league decides ownership, roster fit and recommendations. League roster scarcity is not applied to this value.",
    detail: [
      "The board is built for one scoring setup. Leagues are allowed to share it only when their actual scoring settings are proven identical; if yours cannot be proven identical, the site declines to serve this board for it instead of guessing.",
      "Tight-end values are placed on one TE-premium basis for every league. Your league's own TE premium does not re-price the board.",
      "What changes with your league: who owns the player, his place on your roster, and the trade, waiver and lineup advice built on top of this value.",
    ],
    owner: "CLAUDE.md — Rankings vs. league context; W18-F001",
  },
  confidence: {
    title: "What confidence means",
    short:
      "Confidence rates the evidence behind the value, not the player. The level is the weakest of five checks, and the label names the checks holding it back.",
    detail: [
      "The unit of evidence is a provider family — boards from the same provider or built from the same crowd count once.",
      "Five checks: independence (how many families voted), coverage (how many of the families that could have covered the player did), freshness (how many are current), applicability (how many reached the player without an approximating translation) and agreement (how many price close to the published value).",
      "Nothing averages: many sources cannot make up for stale or disagreeing evidence. 'Low — limited by freshness' means freshness is the check at Low.",
      "Draft picks use their own rule: how closely the pick markets agree.",
    ],
    owner: "src/api/confidence.py",
  },
  missingConfidence: {
    title: "When confidence is missing",
    short:
      "'None' is not a low grade — it means there was no evidence to grade. An unpriced player has no value at all, never zero.",
    detail: [
      "'None — unpriced': no canonical value exists for this asset. It is shown as not priced, never as 0.",
      "'None — priced but not assessed': the asset carries a value, but no evidence family voted on it.",
      "A value derived rather than observed — for example a future pick valued from a neighbouring year or round — is graded Low, and its label says what it was derived from.",
      "A quarantined row was degraded by a data-quality flag: its confidence is lowered, not raised, and it is kept visible rather than removed.",
    ],
    owner: "src/api/confidence.py — CONFIDENCE_BASES",
  },
  freshness: {
    title: "How fresh the value is",
    short:
      "A source's influence fades as its content ages past its own normal publishing rhythm. Fetching an unchanged board does not make it fresher.",
    detail: [
      "Two clocks answer different questions. Last fetched is when we last downloaded a source successfully. Content as of is when the source's own board last changed — that is what ages it.",
      "Each source keeps full weight for one normal publishing interval — learned from its own change history where there is enough, a configured starting value where there is not. After that its weight fades smoothly, converging to about half per further missed interval.",
      "A stale source can still appear in the breakdown, but with less say in the value. Far enough past its rhythm it stops voting entirely — listed as not voting, never counted as zero.",
      "When a player's sources keep noticeably less than their usual authority (from staleness, health or coverage), or one source carries most of the weight, the row is marked Degraded or Severely degraded. Separately, a source whose last fetch is past its budget, or whose content has lost more than half its weight to age, does not count as fresh evidence in the confidence freshness check.",
    ],
    owner: "src/sources/freshness.py; docs/sources/SOURCE_FRESHNESS_WEIGHTING.md",
  },
  provenance: {
    title: "Where the information came from",
    short:
      "Every source that voted is listed with its contribution. KTC Market is shown as a benchmark only — KTC Crowd and KTC Trades are the two KTC inputs that vote.",
    detail: [
      "The source breakdown lists each registered dynasty source whose value voted for this player, on the shared 1–9,999 scale (a vendor's native number in brackets where it differs). Sources that did not vote — too stale, or dropped as an outlier — are listed under source freshness instead.",
      "KTC Market — KTC's own published Crowd+Trades number — is compared against our value to find market gaps. It is never blended in.",
    ],
    owner: "src/sources/ktc_market.py; src/api/data_contract.py — _RANKING_SOURCES",
  },
};

// Order the long-form "How this value works" dialog reads in.
export const VALUE_EXPLAINER_ORDER = [
  "value",
  "rankVsValue",
  "dynastyVsProjection",
  "leagueContext",
  "confidence",
  "missingConfidence",
  "freshness",
  "provenance",
];

// ── Confidence ──────────────────────────────────────────────────────────

const CONFIDENCE_SHORT = { high: "High", medium: "Med", low: "Low", none: "None" };

// What produced a row's bucket — one line per ``CONFIDENCE_BASES`` entry
// in src/api/confidence.py. Unknown bases fall through to no note.
const CONFIDENCE_BASIS_NOTES = {
  evidence_gate: "Graded by the five evidence checks.",
  pick_dispersion: "Graded by how closely the pick markets agree.",
  // The derived bases are stamped bucket "low" by the backend (not
  // "none"): a derived value carries a grade, and says how it was made.
  derived_round_step: "Value derived from the same year's nearest priced round, so it is graded Low.",
  derived_year_step: "Value derived from the nearest priced year, so it is graded Low.",
  derived_rookie_tether: "Value inherited from the rookie at this draft slot.",
  derived_tier_values: "Value derived from tier values, so it is graded Low.",
  derived_two_way_boost: "Value set from the player's other-position market.",
  unpriced: "No canonical value exists for this asset.",
  no_evidence: "A value exists, but no evidence family voted on it.",
  quarantine_degraded: "Lowered by a data-quality flag.",
};

function rawOf(row) {
  return row?.raw && typeof row.raw === "object" ? row.raw : {};
}

/**
 * Everything a surface needs to SHOW a row's confidence — selected from
 * backend stamps, never derived. `level` is the backend bucket ("none"
 * stays "none": missing evidence is not a low grade).
 */
export function confidenceDisplay(row) {
  const raw = rawOf(row);
  const bucket = String(row?.confidenceBucket || raw.confidenceBucket || "").toLowerCase();
  const level = CONFIDENCE_SHORT[bucket] ? bucket : "none";
  const label = String(row?.confidenceLabel || raw.confidenceLabel || "").trim();
  const reasons = Array.isArray(row?.confidenceReasons)
    ? row.confidenceReasons
    : Array.isArray(raw.confidenceReasons)
      ? raw.confidenceReasons
      : [];
  const axesSrc = row?.confidenceAxes || raw.confidenceAxes;
  const axes = axesSrc && typeof axesSrc === "object" ? axesSrc : null;
  const basis = String(row?.confidenceBasis || raw.confidenceBasis || "") || null;
  return {
    level,
    short: CONFIDENCE_SHORT[level],
    // The backend label already names the binding axis ("Low — limited
    // by freshness"). With no label we say so rather than invent a rule.
    label: label || (level === "none" ? "None — not assessed" : CONFIDENCE_SHORT[level]),
    reasons: reasons.filter((r) => typeof r === "string" && r.trim()),
    axes,
    basis,
    basisNote: basis ? CONFIDENCE_BASIS_NOTES[basis] || null : null,
  };
}

export const CONFIDENCE_AXIS_LABELS = {
  independence: "Independence",
  coverage: "Coverage",
  freshness: "Freshness",
  applicability: "Applicability",
  agreement: "Agreement",
};

// ── Freshness ───────────────────────────────────────────────────────────

export const SOURCE_FRESHNESS_STATE_LABELS = {
  ON_SCHEDULE: "On schedule",
  OVERDUE: "Overdue",
  STALE: "Stale",
  SEVERELY_STALE: "Severely stale",
  QUARANTINED: "Not voting — too stale",
};

export const ROW_WEIGHT_STATE_LABELS = {
  NORMAL: "Normal",
  DEGRADED: "Degraded",
  SEVERELY_DEGRADED: "Severely degraded",
  INSUFFICIENT_DATA: "Insufficient data",
};

/** "7m ago" / "6h ago" / "3d ago" for an ISO instant; null when unparseable. */
export function formatAgo(iso, now = Date.now()) {
  if (!iso) return null;
  const then = new Date(iso).getTime();
  if (!Number.isFinite(then)) return null;
  const secs = Math.round((now - then) / 1000);
  if (!Number.isFinite(secs)) return null;
  if (secs < 60) return `${Math.max(0, secs)}s ago`;
  if (secs < 3600) return `${Math.round(secs / 60)}m ago`;
  if (secs < 86_400) return `${Math.round(secs / 3600)}h ago`;
  return `${Math.round(secs / 86_400)}d ago`;
}

/** Hours → "5h" / "3.2d"; null for a missing age (never "0h"). */
export function formatHours(hours) {
  const h = Number(hours);
  if (hours == null || !Number.isFinite(h) || h < 0) return null;
  if (h < 48) return `${Math.round(h)}h`;
  return `${(h / 24).toFixed(1)}d`;
}

/**
 * The two board-level clocks. `builtAt` is when this board was assembled
 * (``dataFreshness.generatedAt``); `scrapedAt` is the scrape run it was
 * built from (``scrapeTimestamp`` — also the instant source ages are
 * measured at). They differ whenever the board is rebuilt without a new
 * scrape, e.g. after a restart.
 */
export function boardClocks(rawData) {
  const builtAt = rawData?.dataFreshness?.generatedAt || rawData?.generatedAt || null;
  const scrapedAt = rawData?.scrapeTimestamp || rawData?.sourceWeighting?.asOf || null;
  return { builtAt, scrapedAt };
}

const SOURCE_LABELS = Object.fromEntries(
  RANKING_SOURCES.map((s) => [s.key, s.columnLabel || s.displayName || s.key]),
);

/** Short display label for a registered source key; the key itself otherwise. */
export function sourceLabel(key) {
  return SOURCE_LABELS[key] || (key == null ? "" : String(key));
}

function subsetFor(row, sourceEntry) {
  const subsets = sourceEntry?.subsets || {};
  if (row?.assetClass === "pick" || row?.pos === "PICK") {
    return subsets.picks || subsets.players || null;
  }
  return subsets.players || null;
}

/**
 * Per-source freshness for ONE row: which sources voted, with how much
 * weight, and the two clocks behind each. Selected from
 * ``row.sourceRankMeta`` (row-level weight + row-level freshness when it
 * was reduced), ``rawData.sourceWeighting`` (the source's content clock
 * and state) and ``rawData.dataFreshness.sourceTimestamps`` (last fetch).
 * Freshness-quarantined sources are listed as not voting — never dropped
 * silently, never shown as zero.
 */
export function rowSourceFreshness(row, rawData) {
  if (!row) return [];
  const raw = rawOf(row);
  const meta = row.sourceRankMeta || raw.sourceRankMeta || {};
  const board = rawData?.sourceWeighting?.sources || {};
  const fetched = rawData?.dataFreshness?.sourceTimestamps || {};
  const excludedList = Array.isArray(raw.freshnessExcludedSources)
    ? raw.freshnessExcludedSources
    : Array.isArray(row.freshnessExcludedSources)
      ? row.freshnessExcludedSources
      : [];
  const excludedSet = new Set(excludedList);
  const out = [];
  const seen = new Set();
  const build = (key, m) => {
    const subset = subsetFor(row, board[key]);
    // The backend keeps a zero-weight (stale / unhealthy) observation in
    // sourceRankMeta with appliedWeight 0.0 and contributedToBlend false
    // — it did NOT vote, and its 0.0 is not a weight to display.
    const excluded = m?.contributedToBlend === false || excludedSet.has(key);
    const outlierDropped = !excluded && Boolean(m?.hampelDropped);
    // The compact view (src/api/compact_view.py _SLIM_SOURCE_RANK_META_FIELDS)
    // keeps only valueContribution / appliedWeight / effectiveWeight /
    // method per source, so the row-level freshness factor and the
    // outlier / exclusion stamps are ABSENT there — not "full freshness".
    // `weight` is stamped on every full-view entry, so it tells the views
    // apart; without it, row-level detail is unknown.
    const detailed = Boolean(m) && ("weight" in m || "freshness" in m || "contributedToBlend" in m);
    const rowFreshness = Number(m?.freshness);
    const applied = Number(m?.appliedWeight);
    const base = Number(m?.baseWeight ?? m?.weight ?? board[key]?.baseWeight);
    const boardAge = Number(subset?.ageHours);
    return {
      key,
      label: SOURCE_LABELS[key] || key,
      voting: !excluded && !outlierDropped,
      excluded,
      excludedReason: excluded ? m?.excludedReason || "freshness_or_health_zero_weight" : null,
      outlierDropped,
      // Family cap: correlated members of one provider family share one
      // provider's vote, so a fresh member can still carry < its base.
      familyShared: Number.isFinite(Number(m?.familyAdjustment)) && Number(m.familyAdjustment) < 1,
      appliedWeight: excluded ? null : Number.isFinite(applied) ? applied : null,
      baseWeight: Number.isFinite(base) ? base : null,
      // THIS ROW's freshness factor. The backend stamps it only when it
      // reduced the row's weight, so a voting row with no stamp voted at
      // full freshness (1). Board-level state can differ for batch-style
      // sources, whose rows age on their own clock.
      rowFreshness: excluded
        ? null
        : Number.isFinite(rowFreshness)
          ? rowFreshness
          : detailed
            ? 1
            : null,
      rowDetailAvailable: detailed,
      // Board-level (source) clock and state — what "content as of" means.
      boardState: subset?.state || null,
      boardAgeHours: Number.isFinite(boardAge) ? boardAge : null,
      contentAsOf: subset?.sourceDataAsOf || null,
      lastFetchedAt: fetched[key]?.mtime || null,
    };
  };
  for (const [key, m] of Object.entries(meta)) {
    if (isNonVotingSourceKey(key)) continue;
    seen.add(key);
    out.push(build(key, m));
  }
  for (const key of excludedList) {
    if (seen.has(key) || isNonVotingSourceKey(key)) continue;
    out.push(build(key, null));
  }
  return out.sort((a, b) => {
    if (a.voting !== b.voting) return a.voting ? -1 : 1;
    return (b.appliedWeight ?? -1) - (a.appliedWeight ?? -1);
  });
}

/** Row-level authority summary, or null when the backend stamped none. */
export function rowAuthority(row) {
  const raw = rawOf(row);
  const state = row?.sourceWeightState || raw.sourceWeightState || null;
  const retained = Number(row?.retainedAuthority ?? raw.retainedAuthority);
  if (!state && !Number.isFinite(retained)) return null;
  const dominant = row?.dominantSource || raw.dominantSource || null;
  const share = Number(row?.dominantSourceShare ?? raw.dominantSourceShare);
  return {
    state,
    stateLabel: state ? ROW_WEIGHT_STATE_LABELS[state] || state : null,
    retained: Number.isFinite(retained) ? retained : null,
    dominantSource: dominant,
    dominantLabel: dominant ? SOURCE_LABELS[dominant] || dominant : null,
    dominantShare: Number.isFinite(share) ? share : null,
  };
}
