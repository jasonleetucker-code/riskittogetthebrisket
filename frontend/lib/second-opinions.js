/**
 * Second Opinions — the value basis, made explicit.
 *
 * WHY THIS MODULE EXISTS
 * ----------------------
 * `TradeSourceBreakdown` sums a vendor's per-asset values and feeds the
 * arrays to a NONLINEAR Value Adjustment. That is only meaningful if
 * every number in one array is in the same unit system.
 *
 * It was not. The uncovered-asset fallback read
 * `effectiveValue(row, valueMode)`, i.e. `row.values[valueMode]`, and
 * `valueMode` is the Trade Calculator's DISPLAY toggle. Flipping a
 * diagnostic control to "Raw" swapped the fallback to the legacy
 * scraper composite while the vendor's own numbers stayed canonical.
 *
 * NUMERIC RANGE EQUALITY IS NOT UNIT COMPATIBILITY. Measured on the
 * tracked 2026-08-14 board:
 *
 *   rawComposite / canonical    n=805   median 1.063
 *                                       p10 0.915   p90 1.262
 *                                       min 0.266   max 2.082
 *
 * Both are "roughly 0-9999"; substituting one for the other is wrong by
 * up to a factor of two on one row.
 *
 * So the resolver returns a BASIS with every number, and the caller may
 * only sum values that share one. A comment cannot fail a build; a
 * basis mismatch here can.
 *
 * WHY KTC IS DIFFERENT, AND WHY WE DO NOT IMPUTE INTO IT
 * ------------------------------------------------------
 * KTC's covered assets deliberately use KTC-NATIVE values, because the
 * V13 Value Adjustment formula and its empirical suppression thresholds
 * were calibrated against them. Dropping a canonical value into that
 * array would only be valid if canonical and KTC-native were
 * interchangeable. Measured over the 385 players carrying both:
 *
 *   KTC native / canonical      median 1.091   min 0.400   max 1.491
 *     top of board (>=7000)     median 0.947   (n=28)
 *     middle (3000-7000)        median 1.027   (n=103)
 *     tail (<3000)              median 1.142   (n=254)
 *
 * The relationship is not identity and not a constant — it drifts
 * monotonically with board depth, so the error's DIRECTION depends on
 * where the player sits. Inside a nonlinear VA whose suppression
 * thresholds compare raw differences, that is not a rounding concern.
 *
 * A calibrated canonical -> KTC-native crosswalk might be defensible
 * later, but it would need to be derived, monotonic, tested and honest
 * about extrapolation — and the owner ruling forbids inventing a
 * multiplier to get there. Until that exists, an asset KTC does not
 * cover makes KTC's opinion INCOMPLETE. We do not fabricate KTC's view
 * of a player it never published.
 */

/** The unit systems a Second Opinions number can be in. */
export const VALUE_BASIS = {
  /** Chase Upside's canonical board value (`rankDerivedValue`), 1-9999. */
  CANONICAL: "CANONICAL_1_9999",
  /** A vendor signal after canonical normalization (`valueContribution`). */
  NORMALIZED_VENDOR: "NORMALIZED_VENDOR_1_9999",
  /** KTC's own published value, the basis KTC package math is calibrated on. */
  KTC_NATIVE: "KTC_NATIVE",
  /** Another vendor's own published atomic value; comparable only within that vendor. */
  VENDOR_NATIVE: "VENDOR_NATIVE",
  /** No comparable number exists. Never a quantity — never zero. */
  MISSING: "MISSING",
};

/**
 * Bases that may be summed together inside one vendor's package array.
 *
 * `CANONICAL` and `NORMALIZED_VENDOR` are both the canonical 1-9999
 * comparison space — verified per source on the live board: all 21
 * registered sources' `valueContribution` lands inside 1-9999 with
 * median ratio to canonical between 0.874 and 1.196.
 *
 * `KTC_NATIVE` is its own island by construction, which is the point.
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
  [VALUE_BASIS.KTC_NATIVE]: new Set([VALUE_BASIS.KTC_NATIVE]),
  [VALUE_BASIS.VENDOR_NATIVE]: new Set([VALUE_BASIS.VENDOR_NATIVE]),
  [VALUE_BASIS.MISSING]: new Set(),
};

export function basesAreCompatible(a, b) {
  return Boolean(COMPATIBLE[a]?.has(b));
}

function positive(value) {
  const n = Number(value);
  return Number.isFinite(n) && n > 0 ? n : null;
}

/**
 * Chase Upside's canonical value for a row, or null.
 *
 * Reads `values.full` — which the materializer sets from
 * `rankDerivedValue` — and falls back to the stamp itself. Deliberately
 * NOT `effectiveValue`, which takes a display mode, and NOT
 * `displayValue`, which returns 0 for an unpriced row. Here the
 * difference between "worth nothing" and "not priced" is the whole
 * point, so this returns null and the caller reports it.
 */
export function canonicalValueOf(row) {
  if (!row) return null;
  const override = positive(row.customValue);
  if (override) return override;
  return positive(row.values?.full) ?? positive(row.rankDerivedValue);
}

/**
 * The value one vendor contributes for one asset.
 *
 * Returns `{value, basis, imputed, unresolved}`. `value` is null
 * whenever `basis` is MISSING — a caller cannot accidentally add it.
 *
 * @param {object}  row          board row
 * @param {object[]} mainSubs    the vendor's main sub-boards
 * @param {object[]} rookieSubs  the vendor's rookie sub-boards
 * @param {boolean} useKtcNative    true for the KTC vendor only
 * @param {boolean} useVendorNative true when a vendor-literal atomic value is required
 * @param {boolean} impute          "fill uncovered pieces with our value"
 */
export function resolveVendorAssetValue({
  row,
  mainSubs = [],
  rookieSubs = [],
  useKtcNative = false,
  useVendorNative = false,
  impute = true,
}) {
  const covered = (subs) => {
    let sum = 0;
    let n = 0;
    for (const sub of subs) {
      const v = useKtcNative
        ? (positive(row?.rawSourceValues?.[sub.key]) ??
          positive(row?.canonicalSites?.[sub.key]))
        : useVendorNative
          ? positive(row?.sourceNativeValues?.[sub.key])
          : positive(row?.sourceRankMeta?.[sub.key]?.valueContribution);
      if (v) {
        sum += v;
        n += 1;
      }
    }
    return n > 0 ? sum / n : null;
  };

  const basis = useKtcNative
    ? VALUE_BASIS.KTC_NATIVE
    : useVendorNative
      ? VALUE_BASIS.VENDOR_NATIVE
      : VALUE_BASIS.NORMALIZED_VENDOR;

  // Main boards win over rookie-specialty boards: once a rookie is
  // promoted onto the main board, the rookie board is a pre-draft
  // artifact rather than the vendor's current opinion.
  const main = covered(mainSubs);
  if (main) return { value: main, basis, imputed: false, unresolved: false };
  const rookie = covered(rookieSubs);
  if (rookie)
    return { value: rookie, basis, imputed: false, unresolved: false };

  if (!impute) {
    // Strict mode: report what the vendor literally says. That is an
    // absence, not a zero — the caller decides how to present a vendor
    // that covers only part of the trade.
    return {
      value: null,
      basis: VALUE_BASIS.MISSING,
      imputed: false,
      unresolved: true,
    };
  }

  if (useKtcNative || useVendorNative) {
    // Native vendor units are not interchangeable with Chase Upside's
    // canonical 1-9999 scale. Imputing here would manufacture a vendor
    // opinion and, for non-KTC vendors, can mix scales such as DLF's
    // ~0-300 atomic values with canonical thousands.
    return {
      value: null,
      basis: VALUE_BASIS.MISSING,
      imputed: false,
      unresolved: true,
    };
  }

  const canonical = canonicalValueOf(row);
  if (!canonical) {
    // The vendor does not cover it and neither do we. Missing is not
    // zero; the vendor's opinion of this trade is incomplete.
    return {
      value: null,
      basis: VALUE_BASIS.MISSING,
      imputed: false,
      unresolved: true,
    };
  }
  return {
    value: canonical,
    basis: VALUE_BASIS.CANONICAL,
    imputed: true,
    unresolved: false,
  };
}

/**
 * WHY A VENDOR COVERS — OR DOES NOT COVER — ONE ASSET
 * ----------------------------------------------------
 * "Incomplete" used to be the only word for every gap, so a trade with
 * one linebacker read "KTC: Incomplete" exactly as a trade whose KTC
 * row had failed to load would. Those are different statements: KTC
 * publishes no IDP at all (its registry scope is offense), which is a
 * fact about the vendor, not a hole in our data.
 *
 * Per (vendor, asset) the answer is one of:
 *
 *   NATIVE         the vendor published a value for this asset.
 *   OUT_OF_SCOPE   the vendor's DECLARED registry scope does not admit
 *                  this asset class (an offense-only board and an IDP
 *                  player). Only declared scopes can prove this; a
 *                  vendor with no declared scope, or a pick (the
 *                  registry declares no pick coverage), is never
 *                  out of scope by assumption.
 *   NOT_PUBLISHED  in scope, but no value for this asset. `detail` says
 *                  whether the backend EXPECTED the vendor to match it
 *                  (`sourceAudit.unmatchedSources`) or not.
 *   UNRESOLVED     there is no board row to ask about.
 *
 * `imputed` is separate from the status: an imputed piece is still
 * NOT_PUBLISHED / OUT_OF_SCOPE by the vendor — our value filled the
 * arithmetic, it did not become the vendor's opinion.
 */
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
    // Kickers and other unsupported positions are admitted by no
    // declared scope; picks and unknown classes are not modelled.
    return assetClass === "excluded" ? false : null;
  }
  return declared.some((s) => SCOPE_ASSET_CLASS[s] === assetClass);
}

/** The coverage status of one resolved asset for one vendor. */
export function assetCoverage({ row, subs = [], resolution }) {
  if (!row) {
    return { status: ASSET_COVERAGE.UNRESOLVED, imputed: false, detail: null };
  }
  const imputed = Boolean(resolution?.imputed);
  if (resolution && resolution.value != null && !imputed) {
    return { status: ASSET_COVERAGE.NATIVE, imputed: false, detail: null };
  }
  if (vendorAdmitsAssetClass(subs, row.assetClass) === false) {
    return {
      status: ASSET_COVERAGE.OUT_OF_SCOPE,
      imputed,
      detail: row.assetClass,
    };
  }
  const unmatched = row.sourceAudit?.unmatchedSources;
  const expected =
    Array.isArray(unmatched) && subs.some((s) => unmatched.includes(s.key));
  return {
    status: ASSET_COVERAGE.NOT_PUBLISHED,
    imputed,
    detail: expected ? "expected_unmatched" : "not_published",
  };
}

/**
 * How one vendor's row may be read, from its per-asset coverage.
 *
 *   COUNTED         every piece native: a real vendor opinion. The only
 *                   state that may enter the tally.
 *   ESTIMATE        some pieces are in scope but unpublished and were
 *                   filled with our value: shown, labelled, never
 *                   counted — part of that "opinion" is ours.
 *   NOT_APPLICABLE  covered pieces exist but the rest are outside the
 *                   vendor's declared scope (KTC and an IDP player): the
 *                   vendor cannot have an opinion on this trade.
 *   INCOMPLETE      an in-scope gap nothing filled, or an unresolved
 *                   piece.
 *   NO_COVERAGE     the vendor published nothing for any piece. Any
 *                   total it would show is 100% our own value, so the
 *                   row is not a second opinion at all.
 */
export const VENDOR_VERDICT = {
  COUNTED: "COUNTED",
  ESTIMATE: "ESTIMATE",
  NOT_APPLICABLE: "NOT_APPLICABLE",
  INCOMPLETE: "INCOMPLETE",
  NO_COVERAGE: "NO_COVERAGE",
};

export function vendorVerdict(coverageBySide, sideSummaries = []) {
  const all = coverageBySide.flat();
  const counts = {
    total: all.length,
    native: 0,
    outOfScope: 0,
    notPublished: 0,
    unresolved: 0,
    imputed: 0,
  };
  const outOfScopeClasses = new Set();
  for (const c of all) {
    if (c.imputed) counts.imputed += 1;
    if (c.status === ASSET_COVERAGE.NATIVE) counts.native += 1;
    else if (c.status === ASSET_COVERAGE.OUT_OF_SCOPE) {
      counts.outOfScope += 1;
      if (c.detail) outOfScopeClasses.add(c.detail);
    } else if (c.status === ASSET_COVERAGE.NOT_PUBLISHED)
      counts.notPublished += 1;
    else counts.unresolved += 1;
  }
  const summaryIncomplete = sideSummaries.some((s) => s?.incomplete);
  let state;
  if (counts.total === 0 || counts.native === 0) {
    state = VENDOR_VERDICT.NO_COVERAGE;
  } else if (counts.native === counts.total && !summaryIncomplete) {
    state = VENDOR_VERDICT.COUNTED;
  } else if (counts.outOfScope > 0) {
    state = VENDOR_VERDICT.NOT_APPLICABLE;
  } else if (counts.unresolved > 0 || summaryIncomplete) {
    state = VENDOR_VERDICT.INCOMPLETE;
  } else {
    state = VENDOR_VERDICT.ESTIMATE;
  }
  return { state, counts, outOfScopeClasses: [...outOfScopeClasses].sort() };
}

const ASSET_CLASS_WORDS = { idp: "IDP", offense: "offense", excluded: "kickers" };

/** Short human reason for a non-counted verdict. */
export function verdictReason({ state, counts, outOfScopeClasses }) {
  const n = counts.total;
  if (state === VENDOR_VERDICT.NOT_APPLICABLE) {
    const what = outOfScopeClasses.map((c) => ASSET_CLASS_WORDS[c] || c);
    return `Doesn't price ${what.join(" or ") || "this asset class"} (${counts.outOfScope} of ${n} piece${n === 1 ? "" : "s"})`;
  }
  if (state === VENDOR_VERDICT.INCOMPLETE) {
    if (counts.unresolved > 0 && counts.notPublished === 0) {
      return `${counts.unresolved} piece${counts.unresolved === 1 ? "" : "s"} not on the board`;
    }
    const gap = counts.notPublished + counts.unresolved;
    return `No value published for ${gap} of ${n} piece${n === 1 ? "" : "s"}`;
  }
  if (state === VENDOR_VERDICT.ESTIMATE) {
    return `${counts.imputed} of ${n} piece${n === 1 ? "" : "s"} use our value`;
  }
  return null;
}

/**
 * One vote per INDEPENDENT family, never per vendor row.
 *
 * Sources that share a `correlationGroup` (KTC Crowd + Fantasy
 * Navigator; FantasyPros + Fitzmaurice) are one body of evidence, so
 * they vote once. A family whose counted members disagree is one
 * "split" — not a vote for each side. Only COUNTED rows vote; every
 * other state is reported beside the tally, never inside it.
 *
 * `rows`: `{family, verdict: {state}, winnerIdx}` (winnerIdx null = even).
 */
export function tallySecondOpinions(rows, sideCount) {
  const families = new Map();
  const notCounted = { estimate: 0, notApplicable: 0, incomplete: 0 };
  for (const r of rows) {
    const state = r.verdict?.state;
    if (state === VENDOR_VERDICT.COUNTED) {
      const fam = r.family || r.key;
      if (!families.has(fam)) families.set(fam, new Set());
      families.get(fam).add(r.winnerIdx == null ? "even" : r.winnerIdx);
    } else if (state === VENDOR_VERDICT.ESTIMATE) notCounted.estimate += 1;
    else if (state === VENDOR_VERDICT.NOT_APPLICABLE)
      notCounted.notApplicable += 1;
    else if (state === VENDOR_VERDICT.INCOMPLETE) notCounted.incomplete += 1;
  }
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
  return { wins, even, split, families: families.size, notCounted };
}

/**
 * Fold per-asset resolutions into one side.
 *
 * Any unresolved asset makes the side incomplete. The values that DID
 * resolve are still returned so a caller can show partial evidence —
 * but `incomplete` is what stops a partial sum being published as a
 * verdict.
 */
export function summariseSide(resolutions) {
  const values = [];
  let imputed = 0;
  let native = 0;
  let unresolved = 0;
  let mixedBasis = false;
  let basis = null;

  for (const r of resolutions) {
    if (r.unresolved || r.value == null) {
      unresolved += 1;
      continue;
    }
    if (basis === null) basis = r.basis;
    else if (!basesAreCompatible(basis, r.basis)) mixedBasis = true;
    values.push(r.value);
    if (r.imputed) imputed += 1;
    else native += 1;
  }

  return {
    values,
    basis,
    imputed,
    native,
    unresolved,
    mixedBasis,
    incomplete: unresolved > 0 || mixedBasis,
  };
}
