// board-utils.js — pure helpers shared by the rankings page, its table
// cells, the expanded source-audit panel, and the copy/CSV exporters.
// No React, no fetching — verbatim extraction from the pre-R2 page so
// the display/export contract is unchanged.

// ── Source cell formatter ────────────────────────────────────────────
//
// Unified formatting for every per-source cell the rankings table
// renders — both the desktop column cells and the mobile chip strip
// beneath each player row.  Every source (rank-signal or value-based)
// lives on one common 1-9,999 scale in the UI: the backend stamps a
// ``valueContribution`` for every matched source (rank sources route
// through the Hill curve, value sources rescale linearly), and this
// helper renders that number as the primary cell label with the
// effective rank on the shared board shown in parentheses.  Returns:
//
//   hasVal    — true if the source contributed a value for this player
//   primary   — the 9,999-scale ``valueContribution`` for the source
//   rankLabel — the effective rank on the shared board, `#`-prefixed
//   title     — hover tooltip explaining the cell (includes the
//               source's original pre-translation rank when it differs
//               from the effective rank, e.g. rookie / shared-market).
//
// Mirror the display format between desktop and mobile by always
// using this helper so both surfaces show `value (#rank)` consistently.
export function formatSourceCell(row, src) {
  const rawVal = row?.canonicalSites?.[src.key];
  // valueContribution is the backend's 9999-scale normalized value
  // (source's top player = 9999, others scale linearly).  For sources
  // whose native value range is already 0-9999 (KTC, IDPTC, DD-SF)
  // this is effectively rawVal; for sources like Yahoo/Boone whose
  // native range is 0-~141, this is the rescaled value so every
  // value column in the UI lives on the same scale.
  const normalizedVal = row?.sourceRankMeta?.[src.key]?.valueContribution;
  // Rank-signal sources stamp a synthetic encoding into canonicalSites
  // (``_RANK_TO_SYNTHETIC_VALUE_OFFSET - rank * 100`` in the backend) that
  // the pipeline uses only for ordering — it is NOT a 1-9,999 contribution.
  // Require a real ``valueContribution`` for those sources so a legacy
  // payload without the stamp shows an honest "—" instead of a
  // six-digit synthetic number mislabeled as a normalized value.
  const hasNormalized =
    normalizedVal != null && Number.isFinite(Number(normalizedVal));
  const hasRaw = rawVal != null && Number.isFinite(Number(rawVal));
  const hasVal = hasNormalized || (!src.isRankSignal && hasRaw);
  const effectiveRank = row?.sourceRanks?.[src.key];
  const origRank = row?.sourceOriginalRanks?.[src.key];
  // Vendor-native value for rank-signal sources (FantasyCalc crowd
  // value, OTC 0-100, PFK 0-9999, ...) — real numbers on the vendor's
  // own scale, stamped in sourceNativeValues.  Shown in the tooltip;
  // never as the primary cell (mixed vendor scales in one column
  // would be misleading).
  const nativeVal = row?.sourceNativeValues?.[src.key];
  const hasNative = nativeVal != null && Number.isFinite(Number(nativeVal));
  const nativeSuffix = hasNative
    ? `, native value ${Number(nativeVal).toLocaleString()}`
    : "";

  if (!hasVal) {
    // The source may still have LISTED the player (rank/native known)
    // even when no valueContribution stamp survives — say so honestly
    // instead of claiming the player wasn't listed.
    const listed = effectiveRank != null || origRank != null || hasNative;
    if (listed) {
      return {
        hasVal: false,
        primary: "—",
        rankLabel: effectiveRank != null ? `#${effectiveRank}` : "—",
        title: `${src.displayName}: no normalized contribution${
          effectiveRank != null ? `, effective rank #${effectiveRank}` : ""
        }${origRank != null ? `, original rank #${origRank}` : ""}${nativeSuffix}`,
      };
    }
    return {
      hasVal: false,
      primary: "—",
      rankLabel: "—",
      title: `${src.displayName} did not list this player`,
    };
  }

  // Every source renders its 9,999-scale valueContribution as the
  // primary cell label — the same number the blend averages into the
  // final Hill value.  Value-based sources may fall back to the raw
  // site value on legacy payloads that predate the valueContribution
  // stamp (their raw value IS on a monotonic value scale, just not yet
  // rescaled to 9,999); rank-signal sources intentionally do not fall
  // back because their raw canonicalSites entry is a synthetic rank
  // encoding, not a value.
  const displayVal = hasNormalized ? normalizedVal : rawVal;
  const primary = Math.round(Number(displayVal)).toLocaleString();
  const rankLabel = effectiveRank != null ? `#${effectiveRank}` : "—";
  const origRankSuffix =
    origRank != null && origRank !== effectiveRank
      ? `, original rank #${origRank}`
      : "";
  return {
    hasVal: true,
    primary,
    rankLabel,
    title: `${src.displayName}: value ${primary}${
      effectiveRank != null ? `, effective rank #${effectiveRank}` : ""
    }${origRankSuffix}${nativeSuffix}`,
  };
}

/** Export cell pair for one source — mirrors formatSourceCell for the
 * Copy/CSV paths (value contribution, else raw for value sources). */
export function exportSourceCells(row, src) {
  const contrib = Number(row.sourceRankMeta?.[src.key]?.valueContribution);
  const raw = row.canonicalSites?.[src.key];
  const valCell = Number.isFinite(contrib)
    ? Math.round(contrib)
    : !src.isRankSignal && raw != null && Number.isFinite(Number(raw))
      ? Math.round(Number(raw))
      : "";
  const rankCell = row.sourceRanks?.[src.key] ?? "";
  return [valCell, rankCell];
}
