"use client";

import { useMemo } from "react";
import { RANKING_SOURCES } from "@/lib/dynasty-data";
import { percentageGap } from "@/lib/trade-logic";

/**
 * TradeFairnessExplanation — 1-2 sentence prose summary that lives
 * between the TradeMeter (verdict bar) and the TradeSourceBreakdown
 * (per-vendor table).  Operationalises the source-disagreement
 * signal we already compute: instead of leaving the user to scan a
 * 12-row vendor table to figure out *why* the trade is fair (or
 * unfair), this card states it directly.
 *
 * Behaviour
 * ─────────
 * Even trades (gap < 3%):
 *   "Sources broadly agree this trade is fair.  Biggest single
 *    disagreement: KTC has Side A up by 800."
 *
 * Lean trades (gap ≥ 3%) with one big driver and no real dissent:
 *   "Side A leans by 8%.  KTC is the biggest driver — they have
 *    Side A up by 1,400."
 *
 * Lean trades with a notable dissenter:
 *   "Side A leans by 8%.  KTC is the biggest driver (Side A +1,400);
 *    DLF disagrees and has Side B winning by 600."
 *
 * The math reads ``sourceRankMeta[key].valueContribution`` from the
 * backend stamps — same field ``TradeSourceBreakdown`` uses, so the
 * narrative can never disagree with the table below.
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
        return "Sources broadly agree — every covered board has this trade close to even.";
      }
      const winnerLabel = biggest.gap > 0 ? labelA : labelB;
      return `Sources broadly agree this trade is fair. Biggest single disagreement: ${biggest.label} has ${winnerLabel} up by ${Math.round(Math.abs(biggest.gap)).toLocaleString()}.`;
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
      return `${winnerLabel} leans by ${pctGap}%. The advantage comes from cumulative differences across sources rather than one big driver.`;
    }

    const driver = aligned[0];
    let parts = [
      `${winnerLabel} leans by ${pctGap}%.`,
      `${driver.label} is the biggest driver — they have ${winnerLabel} up by ${Math.round(Math.abs(driver.gap)).toLocaleString()}.`,
    ];

    if (dissenting.length > 0) {
      const dissenter = dissenting[0];
      parts.push(
        `${dissenter.label} disagrees and has ${otherLabel} winning by ${Math.round(Math.abs(dissenter.gap)).toLocaleString()}.`,
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
