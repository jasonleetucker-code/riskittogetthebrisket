"use client";

/**
 * AwardsHelp — the ONE methodology explanation for the public /league
 * awards.  Each award's one-line `description` stays owned by the backend
 * (`AWARD_DESCRIPTIONS` in src/public_league/awards.py, printed verbatim on
 * the card); this file owns only the HOW, and every line is read from that
 * module as it runs on main today:
 *
 *   VORP awards      _vorp_rows / _REPLACEMENT_BAND_SIZE (5) — regular-season
 *                    starter points minus replacement-level points per game
 *                    for the games started.
 *   League MVP       _league_mvp_gate — playoff field (current standings
 *                    in-season, the actual winners bracket once final) plus
 *                    the record rule.  Owner correction 2026-09-29: ".500 or
 *                    better" (the gate moves to winPct >= 0.5 in the separate
 *                    correction PR; this copy is written to that rule).
 *   Manager of Year  _manager_of_the_year_scores — 30/25/15/15/15 composite,
 *                    min-max scaled, NO record or playoff gate.  The unified
 *                    replacement (PR #1513) is not merged and is not
 *                    described here.
 *   Leader vs final  seasonStatus === "complete" is final — the same rule
 *                    the franchise page's "Awards won" uses
 *                    (src/public_league/franchise.py).
 *
 * Public page: this describes retrospective, factual methodology only — no
 * private values, forecasts or edges.
 */

import { HelpModal } from "@/components/ds";

export function AwardsHowItWorks() {
  return (
    <HelpModal title="How the awards are decided" label="How awards work">
      <h3>Leader or final</h3>
      <p>
        Until Sleeper marks a season complete, the name on an award is the current
        leader, not the winner — it can still change, including in an award&apos;s
        history. A franchise page counts an award as won only once its season is
        complete.
      </p>

      <h3>Player awards</h3>
      <ul>
        <li>
          <strong>MVPs and rookies</strong> rank by value over replacement: the
          player&apos;s regular-season points while in a starting lineup, minus what a
          replacement-level player at his position would have scored in the same number
          of starts. Replacement level is the per-game average of the five rostered
          players just below the starter cutoff at that position.
        </li>
        <li>
          <strong>League MVP</strong> also requires his fantasy team to be in the playoff
          field — current standings during the season, the actual bracket once it is set
          — with a record of .500 or better. Offensive and Defensive MVP and the rookie
          awards have no team requirement.
        </li>
        <li>
          <strong>Top QB, RB, WR, TE, K, DL, LB, DB</strong>: most regular-season points
          scored while in a starting lineup at that position.
        </li>
        <li>
          <strong>Playoff MVP</strong>: the champion&apos;s starter with the most playoff
          value over replacement.
        </li>
      </ul>

      <h3>Manager and team awards</h3>
      <ul>
        <li>
          <strong>Manager of the Year</strong>: a weighted score — 30% final finish, 25%
          regular-season win rate, 15% points scored, 15% trade impact, 15% waiver impact —
          each scaled across the league. It has no record or playoff requirement. This
          formula is under review; it is the one in use today.
        </li>
        <li>
          <strong>Regular-Season Crown</strong>: best record (then points scored).{" "}
          <strong>Points King</strong>: most points scored.
        </li>
        <li>
          <strong>Trader of the Year</strong>: points your incoming players scored for you
          after each trade, minus what the players you sent scored for their new team —
          bench points included. <strong>Best Trade</strong> is the single largest such
          gain.
        </li>
        <li>
          <strong>Waiver King</strong>: points your pickups scored in your starting lineup
          after you added them.
        </li>
        <li>
          <strong>Weekly Hammer</strong>: most weekly top scores.{" "}
          <strong>Silent Assassin</strong>: best win rate in games decided by 10 points or
          fewer (at least four).{" "}
          <strong>Mr. Consistent</strong>: steadiest weekly scoring among playoff teams
          (every team before the bracket exists).
        </li>
        <li>
          <strong>Highest / Lowest Single Week</strong> and <strong>Bad Beat</strong>{" "}
          (highest score in a loss) include playoff weeks.
        </li>
        <li>
          <strong>Top Offense / Defense / NFL Team</strong>: regular-season starter
          points; the NFL-team award groups players by their current NFL team.
        </li>
        <li>
          <strong>Best Rebuild</strong>: the biggest year-over-year climb in points and
          record rank, plus draft picks held and rookies added.{" "}
          <strong>Rivalry of the Year</strong>: the pair of managers whose meetings score
          highest, weighting playoff meetings and close games.
        </li>
      </ul>

      <p>
        When no one has a qualifying result yet, the card says &quot;Not yet awarded&quot;
        and why, rather than naming a winner with a zero.
      </p>
    </HelpModal>
  );
}
