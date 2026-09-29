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

import { HelpModal, InfoTip } from "@/components/ds";

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
        A KeepTradeCut-style premium for concentrated value: one great asset is
        worth more than several lesser ones adding up to the same raw total. It
        is credited to the side sending the more concentrated package — usually
        the side with fewer, better pieces, but it can fire on equal-count
        trades too.
      </p>
      <p>
        Never applied to a 1-for-1, and not applied when it would be under
        3.3% of the two packages combined. Adjusted total = raw + VA, less any
        draft-capital stack effect listed under the meter.
      </p>
    </InfoTip>
  );
}

/** The verdict meter's full explanation — a button beside the meter. */
export function TradeVerdictHelp() {
  return (
    <HelpModal title="How the trade verdict works" label="How the verdict works">
      <h3>Reading the sides</h3>
      <p>
        Each side lists what that team <strong>sends</strong>. In a two-team
        trade, the side whose package is worth more is giving up more — the
        team on the other side receives that extra value. With three or more
        teams, each asset goes to the destination you pick, and each side shows
        what it gives, what it gets and the net.
      </p>

      <h3>Package value</h3>
      <p>
        With the value mode on <strong>Our Value</strong>, every asset counts
        its canonical board value — the same 1–9,999 number Rankings shows. A
        side&apos;s <strong>Raw</strong> total is the plain sum. An asset the
        board does not price adds 0 to the sum and the side is marked
        &quot;Incomplete&quot; — that means unknown, not worthless.
      </p>
      <p>
        The <strong>Raw</strong> value mode swaps in the older scraper
        composite, a different and larger scale. The verdict bands below are
        set on the board value, so read the verdict in Our Value.
      </p>

      <h3>Value Adjustment</h3>
      <p>
        A KeepTradeCut-style premium for concentrated value, generally
        credited to the side sending the better individual pieces. Never on a
        1-for-1, and not applied under 3.3% of the combined value. When you pick each side&apos;s team
        for a trade with picks, a draft-capital stack effect can also move the
        totals; it is listed under the meter.
      </p>

      <h3>The verdict</h3>
      <ul>
        <li>
          The badge grades the adjusted gap between the two packages:{" "}
          <strong>FAIR</strong> under 350, <strong>SLIGHT EDGE</strong> under
          900, <strong>UNFAIR</strong> under 1,800, <strong>LOPSIDED</strong>{" "}
          beyond that.
        </li>
        <li>
          The percentage is that gap as a share of the bigger package; under 3%
          it reads &quot;Even&quot;. Because one is absolute and one is
          relative, a small trade can show a large percentage beside a FAIR
          badge, and a large trade the reverse.
        </li>
        <li>
          This verdict compares package value only. It does not know your
          roster.
        </li>
      </ul>

      <h3>Trade War Room — what it does to your team</h3>
      <p>
        With your team selected, the War Room answers three separate
        questions and does not average them:
      </p>
      <ul>
        <li>
          <strong>Market</strong> — the package gap after Value Adjustment. It
          prices the assets at their board values, so value overrides, the Raw
          mode and the stack effect in the builder are not applied there. Its
          own &quot;even&quot; band is tighter (a gap under 256).
        </li>
        <li>
          <strong>Roster</strong> — expected points per week from the best
          legal lineup your roster can field (scored as best ball), before and
          after, using rest-of-season projections under your league&apos;s
          scoring.
        </li>
        <li>
          <strong>Feasibility</strong> — whether the result fits your roster
          limit, and who would have to be cut. Draft picks do not use roster
          spots; an unknown limit is reported as unknown, never as room.
        </li>
      </ul>
      <p>
        The recommendation (Make / Lean make / Too close / Lean pass / Pass)
        comes from a fixed rule table over those answers, not a weighted
        score. When Market and Roster point opposite ways it starts at
        &quot;Too close / depends&quot;; Feasibility can move the call one
        step, and a trade with no legal roster cleanup is never better than
        Too close. Switch to{" "}
        <strong>Asset only</strong> to drop the roster and feasibility answers.
      </p>

      <h3>Why two even packages can land differently</h3>
      <p>
        Equal package value can still help one team and hurt another: an
        incoming player may start every week for one roster and sit on the
        bench behind a better player on another, a trade can force a cut on a
        full roster, and it can open or close a positional hole. That is the
        Roster and Feasibility answers — package value never changes because of
        who receives it.
      </p>

      <h3>What is uncertain or not included</h3>
      <ul>
        <li>
          Not included yet: competitive posture (contender or rebuilder),
          current-season playoff odds, real comparable trades and measured
          value-uncertainty bands. The War Room lists them under &quot;How this
          was decided&quot;.
        </li>
        <li>
          The Monte Carlo check, where shown, assumes a ±15% range around each
          value because no measured range exists yet; it is not the chance the
          trade works out.
        </li>
        <li>
          A player with no league-scored projection makes the roster answer
          partial, and it then does not count toward the recommendation.
        </li>
      </ul>

      <p>{RECOMMENDATION_ONLY_TEXT}</p>
    </HelpModal>
  );
}
