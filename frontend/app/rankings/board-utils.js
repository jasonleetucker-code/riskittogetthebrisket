import { VOTE_STATE_LABELS, sourceVoteState } from "@/lib/source-vote-state";
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
// ── Per-observation provenance (sources that declare it) ─────────────
//
// Signals Fantasy (owner addendum 2026-10-03) votes from a NATIVE VALUE:
// the rank it votes with is DERIVED from Signals' own value ordering, and
// the owner requires the column to say so — plus the native value, the
// VALUE vs RANK-fallback basis, the dataset, the format and the as-of.
// Every input is a backend stamp; nothing here ranks or prices anything:
//
//   basis    — native value stamped (``sourceNativeValues``) => the vote is
//              the VALUE and its rank was derived from the value ordering;
//              rank stamped without a value => the RANK fallback (a
//              published cross-position rank).  The backend writes the
//              native value only for VALUE observations, so the two
//              states cannot be confused.
//   asOf     — the source's content clock from ``rawData.sourceWeighting``
//              (the vendor's own publication stamp), with its state.
//   dataset / format — registry metadata (``observationDataset`` /
//              ``observationFormat`` on the RANKING_SOURCES entry).
//
// Returns null for sources without declared provenance or rows the source
// did not list (missing is never zero — the caller renders "—").
export function sourceObservation(row, src, rawData) {
  if (!src?.observationDataset) return null;
  const nativeVal = row?.sourceNativeValues?.[src.key];
  const origRank = row?.sourceOriginalRanks?.[src.key];
  const hasNative = nativeVal != null && Number.isFinite(Number(nativeVal));
  const hasRank = origRank != null && Number.isFinite(Number(origRank));
  if (!hasNative && !hasRank) return null;
  const subset =
    rawData?.sourceWeighting?.sources?.[src.key]?.subsets?.players || null;
  // A collected-but-held board (backend ``privateSourceAvailability``:
  // ``votes: false`` with ``heldFromVote`` / ``rolledBack``) is shown, never
  // presented as a vote.
  const avail = rawData?.privateSourceAvailability?.[src.key] || null;
  const voting = avail ? avail.votes !== false : null;
  const voteState = sourceVoteState(avail);
  const shadow = row?.sourceShadowMeta?.[src.key] || null;
  const meta = row?.sourceRankMeta?.[src.key] || null;
  return {
    voting,
    voteState,
    voteLabel: VOTE_STATE_LABELS[voteState] || null,
    voteExplanation: voteStateExplanation(voteState, src),
    heldReason:
      avail?.heldFromVote || (avail?.rolledBack ? "rolled back" : null),
    family: src.positionGroup || null,
    familyNote:
      src.correlationGroup && src.correlationGroup !== src.key
        ? `Shares one provider's authority with its ${src.correlationGroup} family (family-capped)`
        : null,
    excludedReason: meta?.hampelDropped
      ? "outlier (dropped by the per-row filter)"
      : null,
    shadow: shadow
      ? {
          familyRank: shadow.familyRank ?? null,
          translatedRank: shadow.translatedRank ?? null,
          wouldContribute: shadow.wouldContribute ?? null,
          withheldReason: shadow.withheldReason || null,
        }
      : null,
    basis: hasNative ? "VALUE" : "RANK",
    basisLabel: hasNative ? "native value" : "rank fallback",
    rankLabel: hasRank
      ? `#${Number(origRank)} ${
          hasNative
            ? src.observationRankLabel || "value-ordered rank (derived)"
            : "published rank"
        }`
      : null,
    nativeValue: hasNative ? Number(nativeVal) : null,
    dataset: src.observationDataset,
    format: src.observationFormat || null,
    asOf: subset?.sourceDataAsOf || null,
    state: subset?.state || null,
  };
}

// Vote-state names come from the one shared reader (lib/source-vote-state).
export { VOTE_STATE_LABELS, sourceVoteState };

const WITHHELD_REASON_TEXT = {
  no_family_ladder: "no shared-market ladder for this family",
  beyond_family_ladder: "deeper than the market's own list for this family",
  not_a_within_family_rank: "no within-family value to translate",
};

export function withheldReasonText(reason) {
  return reason ? WITHHELD_REASON_TEXT[reason] || reason : null;
}

/** Why a collected Signals board is not voting, in the owner's words. */
export function voteStateExplanation(voteState, src) {
  const fam = src?.positionGroup;
  if (voteState === "shadow" && fam) {
    return (
      `Signals ranks this player within ${fam}. Its IDP values are position-family ` +
      "normalized and do not establish a DL/LB/DB shared price scale. Calculator is " +
      "currently translating this information in shadow before allowing it to affect " +
      "canonical values."
    );
  }
  if (voteState === "held") {
    return "Collected and shown; a declared methodology hold keeps it out of the blend.";
  }
  if (voteState === "rolled_back") {
    return "Switched off by the operator's rollback flag; its evidence stays visible.";
  }
  return null;
}

/** One-line provenance string for a cell tooltip / chip title. */
export function sourceObservationText(obs) {
  if (!obs) return "";
  const parts = [
    obs.voting === false ? obs.voteLabel || "collected, NOT voting" : null,
    obs.basis === "VALUE"
      ? `native value ${obs.nativeValue.toLocaleString()} (VALUE)`
      : "RANK fallback",
    obs.rankLabel,
    `${obs.dataset} dataset`,
    obs.format,
    obs.asOf
      ? `as of ${String(obs.asOf).slice(0, 10)}${obs.state ? ` (${obs.state})` : ""}`
      : null,
    obs.shadow?.wouldContribute != null
      ? `would contribute ${Number(obs.shadow.wouldContribute).toLocaleString()} (shadow)`
      : null,
    obs.shadow?.withheldReason
      ? `shadow withheld: ${withheldReasonText(obs.shadow.withheldReason)}`
      : null,
    obs.excludedReason,
  ].filter(Boolean);
  return parts.join(" · ");
}

export function formatSourceCell(row, src, rawData) {
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
  const observation = sourceObservation(row, src, rawData);
  const nativeSuffix = observation
    ? ` · ${sourceObservationText(observation)}`
    : hasNative
      ? `, native value ${Number(nativeVal).toLocaleString()}`
      : "";

  if (!hasVal) {
    // The source may still have LISTED the player (rank/native known)
    // even when no valueContribution stamp survives — say so honestly
    // instead of claiming the player wasn't listed.
    const listed = effectiveRank != null || origRank != null || hasNative;
    if (listed) {
      // A collected source that is not voting (Signals IDP in shadow) still
      // has something true to show in its column: the within-family rank it
      // published, labelled with its state — never a contribution it did
      // not cast.
      const mutedText =
        observation && observation.voting === false && origRank != null
          ? `${observation.family || "#"}${Number(origRank)} · ${
              observation.voteState === "shadow" ? "shadow" : "not voting"
            }`
          : null;
      return {
        hasVal: false,
        mutedText,
        primary: "—",
        rankLabel: effectiveRank != null ? `#${effectiveRank}` : "—",
        title: `${src.displayName}: no normalized contribution${
          effectiveRank != null ? `, effective rank #${effectiveRank}` : ""
        }${!observation && origRank != null ? `, original rank #${origRank}` : ""}${nativeSuffix}`,
        observation,
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
  // A source with declared provenance names its rank in the observation
  // text ("value-ordered rank (derived)"), never as a bare "original rank".
  const origRankSuffix =
    !observation && origRank != null && origRank !== effectiveRank
      ? `, original rank #${origRank}`
      : "";
  return {
    hasVal: true,
    primary,
    rankLabel,
    title: `${src.displayName}: value ${primary}${
      effectiveRank != null ? `, effective rank #${effectiveRank}` : ""
    }${origRankSuffix}${nativeSuffix}`,
    observation,
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
