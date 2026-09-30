"use client";

import { useMemo } from "react";
import { RANKING_SOURCES } from "@/lib/dynasty-data";
import { percentageGap } from "@/lib/trade-logic";

/**
 * WHAT THE NUMBERS ARE (corrected 2026-09-29).  The headline percentage is
 * the adjusted gap (raw + VA) between the two PACKAGES (each side lists what it
 * sends, so the bigger package is the side giving up more).  The per-source
 * figures are RAW sums of `sourceRankMeta[key].valueContribution` — no
 * Value Adjustment — and every contributing source key is cited on its own
 * (correlated sources are not collapsed into one family here).  The copy
 * says both things instead of implying the per-source numbers are the
 * verdict's own basis.  The previous docstring claimed this read "the same
 * field TradeSourceBreakdown uses"; the breakdown prefers native KTC/DLF
 * values, so the two can differ.
 *
 * TradeFairnessExplanation — 1-2 sentence prose summary that lives
 * between the TradeMeter (verdict bar) and the TradeSourceBreakdown
 * (per-vendor table).  Operationalises the source-disagreement
 * signal we already compute: instead of leaving the user to scan a
 * 12-row vendor table to figure out *why* the trade is fair (or
 * unfair), this card states it directly.
 *
 * Behaviour (rounded gap under 3% = "within 3%"; otherwise a lean):
 *   even  — "The packages are within 3% after adjustments. Biggest
 *            single-source difference (raw, …): KTC values Side A's
 *            package 800 higher."
 *   lean  — "Side A's package is worth 8% more after adjustments. KTC is
 *            the biggest driver — it values Side A's package 1,400 higher
 *            (raw)." plus, when one exists, the strongest dissenter.
 *
 * Reads ``sourceRankMeta[key].valueContribution`` (raw, per source key).
 *
 * Render conditions
 * ─────────────────
 * Renders nothing when:
 *   * sides is not a 2-team comparison (3+-team rendering is more
 *     nuanced; intentionally scoped out for now)
 *   * both sides total to zero (no assets yet)
 *   * no source has both sides covered with a meaningful contribution
 */

const REGISTRY_BY_KEY = (() => {
  const out = {};
  for (const s of RANKING_SOURCES) out[s.key] = s;
  return out;
})();

// A source needs at least this much absolute gap before we'd cite it
// as "the biggest disagreement" or "the biggest driver".  Below this
// threshold the disagreement is just noise from rounding or
// minor-rank disagreement on a deep player.
const MIN_NOTABLE_GAP = 200;

function sourceLabel(key) {
  const def = REGISTRY_BY_KEY[key];
  return def?.columnLabel || def?.displayName || key;
}

function sumSideContribution(assets, key) {
  let total = 0;
  for (const a of assets || []) {
    const meta = a?.sourceRankMeta || {};
    const v = Number(meta[key]?.valueContribution);
    if (Number.isFinite(v) && v > 0) total += v;
  }
  return total;
}

function buildPerSourceGaps(sideA, sideB) {
  const sourceSet = new Set();
  for (const a of [...(sideA?.assets || []), ...(sideB?.assets || [])]) {
    const meta = a?.sourceRankMeta || {};
    for (const k of Object.keys(meta)) {
      if (Number(meta[k]?.valueContribution) > 0) sourceSet.add(k);
    }
  }
  const out = [];
  for (const key of sourceSet) {
    const a = sumSideContribution(sideA?.assets, key);
    const b = sumSideContribution(sideB?.assets, key);
    // Require both sides to have at least one contribution from this
    // source before we'd cite it.  A source that ranks only one side's
    // pieces (e.g. KTC has Side A's player but not Side B's) is a
    // coverage gap, not a disagreement worth narrating.
    if (a <= 0 || b <= 0) continue;
    out.push({
      key,
      label: sourceLabel(key),
      gap: a - b,
      sideASum: a,
      sideBSum: b,
    });
  }
  return out;
}

export default function TradeFairnessExplanation({ sides, sideTotals }) {
  const sentence = useMemo(() => {
    if (!Array.isArray(sides) || sides.length !== 2) return null;
    const [sideA, sideB] = sides;

    const totalA = Number(sideTotals?.[0]?.adjusted) || 0;
    const totalB = Number(sideTotals?.[1]?.adjusted) || 0;
    if (totalA <= 0 && totalB <= 0) return null;

    const labelA = sideA?.label ? `Side ${sideA.label}` : "Side A";
    const labelB = sideB?.label ? `Side ${sideB.label}` : "Side B";

    const overallGap = totalA - totalB;
    const pctGap = percentageGap(totalA, totalB);
    const overallSign = overallGap === 0 ? 0 : overallGap > 0 ? 1 : -1;

    const perSource = buildPerSourceGaps(sideA, sideB);
    if (perSource.length === 0) return null;

    // Sort by absolute gap descending for "biggest disagreement"
    const byMagnitude = [...perSource].sort(
      (a, b) => Math.abs(b.gap) - Math.abs(a.gap),
    );

    if (pctGap < 3) {
      // Even — call out the biggest single source-level disagreement
      // so the user knows *which* board would tip it if they trusted
      // a single source over the blend.
      const biggest = byMagnitude[0];
      if (!biggest || Math.abs(biggest.gap) < MIN_NOTABLE_GAP) {
        return "The packages are within 3% after adjustments, and every covered source has them close to even.";
      }
      const winnerLabel = biggest.gap > 0 ? labelA : labelB;
      return `The packages are within 3% after adjustments. Biggest single-source difference (raw, before Value Adjustment): ${biggest.label} values ${winnerLabel}'s package ${Math.round(Math.abs(biggest.gap)).toLocaleString()} higher.`;
    }

    // Lean trade — driver = source most aligned with the overall
    // direction; dissenter = strongest opposing source.
    const winnerLabel = overallGap > 0 ? labelA : labelB;
    const otherLabel = overallGap > 0 ? labelB : labelA;

    const aligned = perSource
      .filter((s) => Math.sign(s.gap) === overallSign && Math.abs(s.gap) >= MIN_NOTABLE_GAP)
      .sort((a, b) => Math.abs(b.gap) - Math.abs(a.gap));
    const dissenting = perSource
      .filter((s) => Math.sign(s.gap) === -overallSign && Math.abs(s.gap) >= MIN_NOTABLE_GAP)
      .sort((a, b) => Math.abs(b.gap) - Math.abs(a.gap));

    if (aligned.length === 0) {
      // Edge case: overall gap exists but no individual source has a
      // gap aligned with it (could happen with weights / VA effects).
      return `${winnerLabel}'s package is worth ${pctGap}% more after adjustments. No single source drives it; the difference comes from Value Adjustment or small differences across sources.`;
    }

    const driver = aligned[0];
    let parts = [
      `${winnerLabel}'s package is worth ${pctGap}% more after adjustments.`,
      `${driver.label} is the biggest driver — it values ${winnerLabel}'s package ${Math.round(Math.abs(driver.gap)).toLocaleString()} higher (raw).`,
    ];

    if (dissenting.length > 0) {
      const dissenter = dissenting[0];
      parts.push(
        `${dissenter.label} disagrees and values ${otherLabel}'s package ${Math.round(Math.abs(dissenter.gap)).toLocaleString()} higher.`,
      );
    }

    return parts.join(" ");
  }, [sides, sideTotals]);

  if (!sentence) return null;

  return (
    <div className="trade-fairness-explanation" role="note">
      <span className="trade-fairness-explanation-icon" aria-hidden="true">
        💡
      </span>
      <p className="trade-fairness-explanation-text">{sentence}</p>
    </div>
  );
}
