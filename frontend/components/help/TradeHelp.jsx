"use client";

/**
 * TradeHelp — the ONE copy owner for what /trade's numbers mean.
 *
 * Every sentence here describes CURRENT released behaviour and names the
 * code that makes it true (the PR that added this file carries the
 * statement → code table).  If the math changes, this file changes with it;
 * a second explanation of the same concept somewhere else on /trade is a
 * second owner and will drift.
 *
 *   Sides           frontend/lib/trade-logic.js computeSideFlowAssets —
 *                   in a 2-team trade every asset on a side goes to the
 *                   OTHER side, so a side lists what that team SENDS.
 *   Package value   trade-logic.js effectiveValue / sideTotal — the sum of
 *                   each asset's `values[valueMode]` ("Our Value" = the
 *                   canonical board value, `rankDerivedValue`).
 *   Value Adj.      trade-logic.js ktcAdjustPackage (JS) and
 *                   src/trade/ktc_va.py (Python, used by the War Room).
 *   Verdict bands   trade-logic.js meterVerdict (350 / 900 / 1,800) and
 *                   percentageGap (<3% shown as even).
 *   War Room        src/trade/analyze_trade.py — market / roster /
 *                   feasibility lenses, rule table, unavailable dimensions.
 *   Capacity        src/trade/roster_capacity.py.
 *
 * Nothing on /trade writes to Sleeper: there is no trade/roster mutation
 * endpoint in server.py and the only Sleeper bridge route is GET-only.
 */

import { Suspense, lazy } from "react";
import { HelpModal, InfoTip, SkeletonText } from "@/components/ds";

const TradeVerdictHelpBody = lazy(() => import("./TradeVerdictHelpBody"));

/** One sentence, reused wherever the page states that nothing executes. */
export const RECOMMENDATION_ONLY_TEXT =
  "Recommendations only — this site never proposes, sends or accepts a trade on Sleeper. You make any trade yourself.";

/**
 * Value Adjustment, at the side total where the "+ VA" figure appears.
 * That total is right-aligned, so the popover grows leftward
 * (`ds-infotip--end`) — anchored left it ran off a 390px screen.
 */
export function ValueAdjustmentTip() {
  return (
    <InfoTip label="Value Adjustment (VA)" className="ds-infotip--end">
      <p>
        A premium for concentrated value: one great asset is worth more than
        several lesser ones adding up to the same raw total. Each side&apos;s
        pieces are ranked best-first; the second-best counts at 78%, the third
        at about 61%, and so on (geometric Value Adjustment, q = 0.78). The side
        whose package loses less to that discount is credited the difference —
        usually the side with fewer, better pieces, but it can fire on
        equal-count trades too.
      </p>
      <p>
        Never applied to a 1-for-1. Adjusted total = raw + VA, so the adjusted
        gap is the difference in discounted package value. The draft-capital
        stack effect is experimental and not calibrated, so it is shown
        separately and is not included in the total or the verdict.
      </p>
    </InfoTip>
  );
}

/** The verdict meter's full explanation — a button beside the meter. */
export function TradeVerdictHelp() {
  return (
    <HelpModal title="How the trade verdict works" label="How the verdict works">
      <Suspense fallback={<SkeletonText lines={6} />}>
        <TradeVerdictHelpBody />
      </Suspense>
    </HelpModal>
  );
}
