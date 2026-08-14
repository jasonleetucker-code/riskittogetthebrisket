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
  /** KTC's own published value, the basis V13 VA was calibrated on. */
  KTC_NATIVE: "KTC_NATIVE",
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
 * @param {boolean} useKtcNative true for the KTC vendor only
 * @param {boolean} impute       "fill uncovered pieces with our value"
 */
export function resolveVendorAssetValue({
  row,
  mainSubs = [],
  rookieSubs = [],
  useKtcNative = false,
  impute = true,
}) {
  const covered = (subs) => {
    let sum = 0;
    let n = 0;
    for (const sub of subs) {
      const v = useKtcNative
        ? (positive(row?.rawSourceValues?.[sub.key]) ??
          positive(row?.canonicalSites?.[sub.key]))
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

  if (useKtcNative) {
    // See the module docstring: canonical is not interchangeable with
    // KTC-native (median 1.091, drifting 0.947 -> 1.142 across board
    // depth, range 0.400-1.491). Imputing here would manufacture a KTC
    // opinion on a player KTC never published, inside a nonlinear VA.
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
