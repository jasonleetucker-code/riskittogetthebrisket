/**
 * Second Opinions — each source's view of THIS trade, on one basis, under
 * OUR active package model.
 *
 * Owner package 2026-10-17 (SECOND_OPINIONS_CANONICAL_FALLBACK_SPEC):
 *
 *   resolved value per (source, asset) =
 *     the source's NORMALIZED comparable value (`sourceRankMeta[key]
 *       .valueContribution`, canonical 1-9999 basis) when it published one
 *       and that observation is eligible (it contributed to the blend), else
 *     Chase Upside's EXACT published canonical value (`values.full` /
 *       `rankDerivedValue` — never the user's override), else
 *     UNPRICED (the comparison is INCOMPLETE; never zero).
 *
 *   then the ACTIVE package model (`packageAdjustPair` via
 *   `valueAdjustmentFromSideArrays`) runs ONCE on the assembled packages —
 *   the same model as the headline, so a row answers "who wins if we use
 *   this source's prices and our adjustment", not "what that site's own
 *   calculator says".
 *
 * ONE BASIS. Every source is read on the normalized basis, KTC Crowd /
 * Trades and DLF included, so a fallback value and a source value are
 * always the same unit and nothing native is ever summed with anything
 * canonical. Vendor-native numbers (KTC's own value, DLF's ~0-300 atomic
 * value) are kept as a diagnostic column only — DLF hundreds can never be
 * added to canonical thousands, and KTC-native is not canonical (median
 * ratio 1.091, drifting with board depth).
 *
 * TRUTHFUL VOTES. A row with any fallback is a HYBRID_ESTIMATE: shown, with
 * per-asset provenance, never an independent vote — two sources filling the
 * same missing linebacker with OUR value must not read as two agreeing
 * opinions. A row with no source coverage at all is CHASE_ONLY_BASELINE (our
 * own numbers; diagnostic only). Only FULL_SOURCE rows vote, one vote per
 * correlation family.
 */

/** The unit systems a Second Opinions number can be in. */
export const VALUE_BASIS = {
  /** Chase Upside's canonical board value (`rankDerivedValue`), 1-9999. */
  CANONICAL: "CANONICAL_1_9999",
  /** A vendor signal after canonical normalization (`valueContribution`). */
  NORMALIZED_VENDOR: "NORMALIZED_VENDOR_1_9999",
  /** A vendor's own published value — diagnostic only, never summed. */
  VENDOR_NATIVE: "VENDOR_NATIVE",
  /** No comparable number exists. Never a quantity — never zero. */
  MISSING: "MISSING",
  /** A positional ordinal + tier with no value scale (Signals' public
   *  boards). Compatible with NOTHING — never summed, never a vote. */
  POSITIONAL_RANK_ONLY: "POSITIONAL_RANK_ONLY",
};

/**
 * Bases that may be summed inside one package. CANONICAL and NORMALIZED_VENDOR
 * are the same 1-9999 comparison space (every registered source's
 * `valueContribution` lands inside it); vendor-native and rank-only bases are
 * compatible with nothing — never summed.
 */
const COMPATIBLE = {
  [VALUE_BASIS.CANONICAL]: new Set([
    VALUE_BASIS.CANONICAL,
    VALUE_BASIS.NORMALIZED_VENDOR,
  ]),
  [VALUE_BASIS.NORMALIZED_VENDOR]: new Set([
    VALUE_BASIS.CANONICAL,
    VALUE_BASIS.NORMALIZED_VENDOR,
  ]),
};

export function basesAreCompatible(a, b) {
  return Boolean(COMPATIBLE[a]?.has(b));
}

function positive(value) {
  const n = Number(value);
  return Number.isFinite(n) && n > 0 ? n : null;
}

/**
 * Chase Upside's PUBLISHED canonical value for a row, or null. Deliberately
 * not `customValue`: a manual override changes the user's own headline, never
 * what we claim a source would see (owner spec: fallback defaults to the
 * published canonical value).
 */
export function publishedCanonicalValueOf(row) {
  if (!row) return null;
  return positive(row.values?.full) ?? positive(row.rankDerivedValue);
}

/** Why a source does — or does not — price one asset. */
export const ASSET_COVERAGE = {
  NATIVE: "NATIVE",
  OUT_OF_SCOPE: "OUT_OF_SCOPE",
  NOT_PUBLISHED: "NOT_PUBLISHED",
  UNRESOLVED: "UNRESOLVED",
};

/** Registry scope → the asset class it admits. */
const SCOPE_ASSET_CLASS = {
  overall_offense: "offense",
  overall_idp: "idp",
};

/**
 * Does any of the vendor's DECLARED scopes admit this asset class?
 * Returns null when the registry cannot say (no declared scope, or an
 * asset class the registry does not model, such as picks) — unknown is
 * never "out of scope".
 */
export function vendorAdmitsAssetClass(subs, assetClass) {
  const declared = [];
  for (const sub of subs) {
    if (!sub?.scope) return null;
    declared.push(sub.scope, ...(sub.extraScopes || []));
  }
  if (declared.length === 0) return null;
  if (assetClass !== "offense" && assetClass !== "idp") {
    return assetClass === "excluded" ? false : null;
  }
  return declared.some((s) => SCOPE_ASSET_CLASS[s] === assetClass);
}

/** Where a resolved value came from. */
export const OPINION_ORIGIN = {
  SOURCE: "SOURCE",
  CHASE_UPSIDE_FALLBACK: "CHASE_UPSIDE_FALLBACK",
  UNPRICED: "UNPRICED",
};

/** Why Chase Upside's value stood in for the source. */
export const FALLBACK_REASON = {
  OUT_OF_SCOPE: "OUT_OF_SCOPE",
  NOT_PUBLISHED: "NOT_PUBLISHED",
  STALE_OR_HELD: "STALE_OR_HELD",
  NOT_ON_BOARD: "NOT_ON_BOARD",
  CANONICAL_VALUE_UNAVAILABLE: "CANONICAL_VALUE_UNAVAILABLE",
};

export const FALLBACK_REASON_LABEL = {
  OUT_OF_SCOPE: "outside this source's coverage",
  NOT_PUBLISHED: "not published by this source",
  STALE_OR_HELD: "source value held, stale or excluded from our blend",
  NOT_ON_BOARD: "not on the board",
  CANONICAL_VALUE_UNAVAILABLE: "no Chase Upside value either",
};

/**
 * The source's eligible normalized value for one asset, averaged over the
 * covering sub-boards of one tier (main boards win over rookie boards).
 * An observation that did not contribute to our blend (stale, zero weight,
 * held, outlier-rejected) is not eligible: it is reported as held, never
 * silently used and never counted as a source opinion.
 */
function eligibleSourceValue(row, subs) {
  let sum = 0;
  let n = 0;
  let held = false;
  for (const sub of subs) {
    const meta = row?.sourceRankMeta?.[sub.key];
    const v = positive(meta?.valueContribution);
    if (!v) continue;
    if (meta.contributedToBlend === false || meta.appliedWeight === 0) {
      held = true;
      continue;
    }
    sum += v;
    n += 1;
  }
  return { value: n > 0 ? sum / n : null, held };
}

/** The vendor's own published number, when one exists — diagnostic only. */
export function nativeVendorValueOf(row, subs) {
  for (const sub of subs) {
    const v =
      positive(row?.sourceNativeValues?.[sub.key]) ??
      (sub.isRankSignal === false
        ? positive(row?.canonicalSites?.[sub.key])
        : null);
    if (v) return v;
  }
  return null;
}

/**
 * Resolve one asset for one source: source value, else Chase Upside's exact
 * published value, else unpriced.
 *
 * Returns `{value, basis, origin, reason, sourceValue, fallbackValue,
 * nativeValue}`; `value` is null exactly when `origin` is UNPRICED.
 */
export function resolveOpinionAsset({ row, mainSubs = [], rookieSubs = [] }) {
  const subs = [...mainSubs, ...rookieSubs];
  if (!row) {
    return {
      value: null,
      basis: VALUE_BASIS.MISSING,
      origin: OPINION_ORIGIN.UNPRICED,
      reason: FALLBACK_REASON.NOT_ON_BOARD,
      sourceValue: null,
      fallbackValue: null,
      nativeValue: null,
    };
  }
  const nativeValue = nativeVendorValueOf(row, subs);
  const main = eligibleSourceValue(row, mainSubs);
  const rookie = main.value
    ? { value: null, held: false }
    : eligibleSourceValue(row, rookieSubs);
  const sourceValue = main.value ?? rookie.value;
  if (sourceValue) {
    return {
      value: sourceValue,
      basis: VALUE_BASIS.NORMALIZED_VENDOR,
      origin: OPINION_ORIGIN.SOURCE,
      reason: null,
      sourceValue,
      fallbackValue: null,
      nativeValue,
    };
  }
  const reason =
    main.held || rookie.held
      ? FALLBACK_REASON.STALE_OR_HELD
      : vendorAdmitsAssetClass(subs, row.assetClass) === false
        ? FALLBACK_REASON.OUT_OF_SCOPE
        : FALLBACK_REASON.NOT_PUBLISHED;
  const canonical = publishedCanonicalValueOf(row);
  if (!canonical) {
    return {
      value: null,
      basis: VALUE_BASIS.MISSING,
      origin: OPINION_ORIGIN.UNPRICED,
      reason: FALLBACK_REASON.CANONICAL_VALUE_UNAVAILABLE,
      sourceValue: null,
      fallbackValue: null,
      nativeValue,
    };
  }
  return {
    value: canonical,
    basis: VALUE_BASIS.CANONICAL,
    origin: OPINION_ORIGIN.CHASE_UPSIDE_FALLBACK,
    reason,
    sourceValue: null,
    fallbackValue: canonical,
    nativeValue,
  };
}

/**
 * How one source's comparison may be read.
 *
 *   FULL_SOURCE          every piece priced by the source: a genuine opinion,
 *                        eligible to vote (one vote per family).
 *   HYBRID_ESTIMATE      at least one piece is Chase Upside's value: a numeric
 *                        estimate, shown and labelled, never a vote.
 *   CHASE_ONLY_BASELINE  the source priced nothing here: the numbers are ours
 *                        alone — diagnostic, never an opinion.
 *   INCOMPLETE           a piece nobody can price: no numeric verdict.
 */
export const OPINION_STATE = {
  FULL_SOURCE: "FULL_SOURCE",
  HYBRID_ESTIMATE: "HYBRID_ESTIMATE",
  CHASE_ONLY_BASELINE: "CHASE_ONLY_BASELINE",
  INCOMPLETE: "INCOMPLETE",
};

export function opinionCounts(resolutionsBySide) {
  const all = resolutionsBySide.flat();
  const counts = { total: all.length, source: 0, fallback: 0, unpriced: 0 };
  for (const r of all) {
    if (r.origin === OPINION_ORIGIN.SOURCE) counts.source += 1;
    else if (r.origin === OPINION_ORIGIN.CHASE_UPSIDE_FALLBACK)
      counts.fallback += 1;
    else counts.unpriced += 1;
  }
  return counts;
}

export function opinionState(counts) {
  if (counts.total === 0 || counts.unpriced > 0)
    return OPINION_STATE.INCOMPLETE;
  if (counts.source === 0) return OPINION_STATE.CHASE_ONLY_BASELINE;
  if (counts.fallback > 0) return OPINION_STATE.HYBRID_ESTIMATE;
  return OPINION_STATE.FULL_SOURCE;
}

function leaderOf(totals) {
  if (!totals.length) return { idx: null, marginPct: null, gap: 0 };
  let idx = 0;
  for (let i = 1; i < totals.length; i++) if (totals[i] > totals[idx]) idx = i;
  const runnerUp = totals
    .filter((_, i) => i !== idx)
    .reduce((m, v) => Math.max(m, v), 0);
  const gap = totals[idx] - runnerUp;
  if (gap < 1) return { idx: null, marginPct: 0, gap: 0 };
  return {
    idx,
    marginPct: totals[idx] > 0 ? (gap / totals[idx]) * 100 : 0,
    gap,
  };
}

/**
 * Evaluate one source's comparison: per-asset resolutions → state, raw
 * totals, OUR active package adjustment applied once, adjusted totals, raw and
 * adjusted leaders, and whether the adjustment flipped the leader.
 *
 * `adjust(sidesValues)` is the active model's per-side adjustment function
 * (`valueAdjustmentFromSideArrays`); injected so this module stays free of
 * the trade-logic import graph and the dispatch has one owner.
 */
export function evaluateOpinion(resolutionsBySide, adjust) {
  const counts = opinionCounts(resolutionsBySide);
  const state = opinionState(counts);
  const base = { state, counts, resolutionsBySide };
  if (state === OPINION_STATE.INCOMPLETE) {
    return {
      ...base,
      rawTotals: null,
      adjustments: null,
      adjustedTotals: null,
      rawLeaderIdx: null,
      leaderIdx: null,
      marginPct: null,
      swing: false,
    };
  }
  const sideValues = resolutionsBySide.map((rs) => rs.map((r) => r.value));
  const rawTotals = sideValues.map((vs) => vs.reduce((s, v) => s + v, 0));
  const adjustments = adjust(sideValues).map((v) => Number(v) || 0);
  const adjustedTotals = rawTotals.map((t, i) => t + adjustments[i]);
  const raw = leaderOf(rawTotals);
  const adjusted = leaderOf(adjustedTotals);
  return {
    ...base,
    rawTotals,
    adjustments,
    adjustedTotals,
    rawLeaderIdx: raw.idx,
    leaderIdx: adjusted.idx,
    marginPct: adjusted.marginPct,
    gap: adjusted.gap,
    swing: raw.idx !== adjusted.idx,
  };
}

/**
 * Two tallies that never mix.
 *
 *   independent — FULL_SOURCE rows only, one vote per correlation family; a
 *                 family whose members disagree is one "split". `eligible`
 *                 is the number of families that priced anything in this
 *                 trade (the denominator a reader needs).
 *   modeled     — HYBRID_ESTIMATE rows, the same one-per-family rule, labelled
 *                 as estimates: correlated fallbacks are not independent.
 *
 * `rows`: `{family, key, opinion: {state, leaderIdx}}`.
 */
export function tallyOpinions(rows, sideCount) {
  const independent = new Map();
  const modeled = new Map();
  const eligible = new Set();
  const counts = { full: 0, hybrid: 0, baseline: 0, incomplete: 0 };
  for (const r of rows) {
    const fam = r.family || r.key;
    const state = r.opinion?.state;
    const outcome = r.opinion?.leaderIdx == null ? "even" : r.opinion.leaderIdx;
    if (state === OPINION_STATE.FULL_SOURCE) {
      counts.full += 1;
      eligible.add(fam);
      if (!independent.has(fam)) independent.set(fam, new Set());
      independent.get(fam).add(outcome);
    } else if (state === OPINION_STATE.HYBRID_ESTIMATE) {
      counts.hybrid += 1;
      eligible.add(fam);
      if (!modeled.has(fam)) modeled.set(fam, new Set());
      modeled.get(fam).add(outcome);
    } else if (state === OPINION_STATE.CHASE_ONLY_BASELINE)
      counts.baseline += 1;
    else counts.incomplete += 1;
  }
  const fold = (families) => {
    const wins = Array.from({ length: sideCount }, () => 0);
    let even = 0;
    let split = 0;
    for (const outcomes of families.values()) {
      if (outcomes.size > 1) split += 1;
      else {
        const [only] = outcomes;
        if (only === "even") even += 1;
        else wins[only] += 1;
      }
    }
    return { wins, even, split, families: families.size };
  };
  return {
    independent: { ...fold(independent), eligible: eligible.size },
    modeled: fold(modeled),
    counts,
  };
}

/**
 * RANK-ONLY, NON-VOTING SECOND OPINIONS (Signals Fantasy, #1555)
 * ---------------------------------------------------------------
 * Some vendors publish no value at all — Signals' public dynasty boards
 * carry a POSITIONAL ordinal and a tier, nothing else. That evidence has
 * its own basis, `POSITIONAL_RANK_ONLY`, which is compatible with NOTHING:
 * it can never be summed, fed to Value Adjustment, imputed into, or enter
 * `tallyOpinions`. QB3 and RB3 are not on one ladder, so nothing here
 * orders across positions either.
 *
 * The backend (`GET /api/second-opinion/signals`, owner
 * `src/sources/signals.py`) does the identity join; this only looks rows up
 * and names the state. Missing is a state, never a rank.
 */

/** Payload-level state of a rank-only provider. */
export const RANK_ONLY_STATE = {
  OK: "ok",
  PARTIAL: "partial",
  NOT_COLLECTED: "not_collected",
  UNAVAILABLE: "unavailable",
};

export function rankOnlyProviderState(payload) {
  const s = payload?.status;
  if (s === RANK_ONLY_STATE.OK || s === RANK_ONLY_STATE.PARTIAL) return s;
  if (s === RANK_ONLY_STATE.NOT_COLLECTED) return s;
  return RANK_ONLY_STATE.UNAVAILABLE;
}

/** Which rank-only boards declare a population that admits this asset class. */
const RANK_ONLY_BOARD_CLASSES = { dynasty: "offense", "idp-dynasty": "idp" };

/**
 * One asset's rank-only opinion. Never carries a value; `votes` is always
 * false. Status reuses ASSET_COVERAGE:
 *   NATIVE        the vendor ranked this player (positional rank + tier)
 *   OUT_OF_SCOPE  no collected board's DECLARED population admits the
 *                 asset class (picks, kickers)
 *   NOT_PUBLISHED in scope, but no resolved row (unranked, or identity
 *                 quarantined server-side — never best-guessed)
 *   UNRESOLVED    no board row to ask about
 */
export function rankOnlyOpinionFor(row, payload) {
  const base = {
    basis: VALUE_BASIS.POSITIONAL_RANK_ONLY,
    value: null,
    votes: false,
    positionalRankOnly: true,
  };
  if (!row) return { ...base, status: ASSET_COVERAGE.UNRESOLVED, entry: null };
  const index = payload?.signalsPositionalRank || {};
  // The server only mints `name:` keys for board rows WITHOUT a playerId, so
  // the name key is consulted only for such rows: a row with a playerId that
  // did not resolve must never borrow a same-named player's rank.
  const entry = row.playerId
    ? index[`pid:${row.playerId}`] || null
    : index[`name:${row.name}`] || null;
  if (entry) return { ...base, status: ASSET_COVERAGE.NATIVE, entry };
  const boards = payload?.boards || {};
  const board = Object.keys(RANK_ONLY_BOARD_CLASSES).find(
    (b) => RANK_ONLY_BOARD_CLASSES[b] === row.assetClass,
  );
  if (!board) {
    return {
      ...base,
      status: ASSET_COVERAGE.OUT_OF_SCOPE,
      entry: null,
      detail: row.assetClass,
    };
  }
  const collected =
    boards[board] && boards[board].status !== RANK_ONLY_STATE.NOT_COLLECTED;
  return {
    ...base,
    status: ASSET_COVERAGE.NOT_PUBLISHED,
    entry: null,
    // "not collected" is OUR gap, not the vendor's silence — kept distinct.
    detail: collected ? "not_ranked_or_unresolved" : "not_collected",
  };
}
