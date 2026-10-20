"use client";

/**
 * TradeVerdictHelpBody — the body of "How the trade verdict works".
 *
 * Code-split out of TradeHelp.jsx: the modal renders nothing while closed,
 * so this ~4 KB of copy loads on first open instead of sitting in the
 * /trade page chunk (which has a hard per-page budget).  The copy owner is
 * still TradeHelp.jsx — see its header for the statement → code map.
 */

import { RECOMMENDATION_ONLY_TEXT } from "./TradeHelp";

export default function TradeVerdictHelpBody() {
  return (
    <>
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
        Every asset counts its canonical board value — the same 1–9,999
        number Rankings shows. A side&apos;s <strong>Raw</strong> total is the
        plain sum of those values, before Value Adjustment. An asset the board
        does not price is unknown, not worthless: its side is marked
        &quot;Incomplete&quot; and no verdict is given until it is priced (type
        a value on its row to price it yourself).
      </p>

      <h3>Value Adjustment</h3>
      <p>
        A premium for concentrated value, generally credited to the side
        sending the better individual pieces. Each side&apos;s pieces are ranked
        best-first and each further piece counts at 78% of the one before it
        (geometric Value Adjustment, q = 0.78); the side that loses less to
        that discount is credited the difference. Never on a 1-for-1. Adjusted
        total = raw + VA. When you pick each side&apos;s team for a trade with picks, a
        draft-capital stack effect is shown under the meter as experimental
        context: it is not calibrated, and it is not included in the totals or
        the verdict.
      </p>

      <h3>The verdict</h3>
      <ul>
        <li>
          The badge grades the adjusted gap (raw + VA) as a share of the
          bigger package&apos;s depth-discounted value (each piece after the
          first counted at 78% of the one before it, the same discount the
          Value Adjustment uses):{" "}
          <strong>FAIR</strong> under 3.5% (or under 250 points),{" "}
          <strong>SLIGHT EDGE</strong> under 9%, <strong>UNFAIR</strong> under
          18%, <strong>LOPSIDED</strong> beyond that. The same bands are used
          everywhere on the site. They are an owner-approved starting point
          (version 2), to be checked against real market trades after launch.
        </li>
        <li>
          Because the bands are relative, a 300-point gap is FAIR between two
          stars and LOPSIDED between two bench players; the badge and the
          percentage always agree.
        </li>
        <li>
          This verdict compares package value only. It does not know your
          roster.
        </li>
      </ul>

      <h3>Trade War Room — what it does to your team</h3>
      <p>
        With your team selected, the War Room gives one recommendation and answers three separate
        questions, without averaging them:
      </p>
      <ul>
        <li>
          <strong>Trade value</strong> — how much value you receive and send, after Value
          Adjustment. It prices the assets at their board values, so value overrides typed in the
          builder are not applied there. It uses the same fairness bands as the badge.
        </li>
        <li>
          <strong>Impact on your team</strong> — how many more or fewer points per week the best
          legal lineup your roster can field is projected to score (as best ball), using
          rest-of-season projections under your league&apos;s scoring.
        </li>
        <li>
          <strong>Does it fit your roster?</strong> — whether the result fits your roster limit,
          and who would have to be cut. Draft picks do not use roster spots; an unknown limit is
          reported as unknown, never as room.
        </li>
      </ul>
      <p>
        The recommendation is one of <strong>Yes, make the trade</strong>, <strong>No</strong>,{" "}
        <strong>No, too close</strong> (a near tie with complete evidence), or{" "}
        <strong>Not enough evidence</strong> when something material is missing (an unpriced or
        unheld asset, a stale or quarantined value, an unknown roster or posture) — it names what
        is missing instead of guessing. It comes from a fixed rule table, not a weighted score.
        Your strategy (win now, balanced or long-term) is inferred from your competitive posture
        and can be changed; it only decides which answer wins when trade value and your lineup
        disagree. A trade with no legal roster cleanup is a No. Confidence is a label naming what
        limits it, never a probability. Switch to <strong>Asset only</strong> to decide on trade
        value alone. While the personalized analysis runs, the War Room shows the calculator&apos;s
        trade value at once and gives no recommendation until the analysis answers.
      </p>

      <h3>Why two even packages can land differently</h3>
      <p>
        Equal package value can still help one team and hurt another: an
        incoming player may start every week for one roster and sit on the
        bench behind a better player on another, a trade can force a cut on a
        full roster, and it can open or close a positional hole. That is what
        Impact on your team and Does it fit your roster? answer — package value
        never changes because of who receives it.
      </p>

      <h3>What is uncertain or not included</h3>
      <ul>
        <li>
          Your team&apos;s competitive direction (contender, retooling or
          rebuilding) sets the strategy but is never counted as a vote, and
          comparable real trades are shown for reference when the trade ledger
          has some — they never change the recommendation. Not included yet:
          the change in this season&apos;s playoff and title odds, and measured
          value-uncertainty ranges. The War Room lists what is left out under
          &quot;Sources, simulations and methodology&quot;.
        </li>
        <li>
          The Monte Carlo check, where shown, assumes a ±15% range around any
          value with no measured range (today that is nearly all of them); it
          is not the chance the trade works out.
        </li>
        <li>
          A traded player with no league-scored projection makes the Impact on
          your team answer partial, and it then does not count toward the
          recommendation.
        </li>
      </ul>

      <p>{RECOMMENDATION_ONLY_TEXT}</p>
    </>
  );
}
