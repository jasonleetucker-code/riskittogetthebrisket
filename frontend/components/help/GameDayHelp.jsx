"use client";

/**
 * GameDayHelp — the ONE copy owner for what Game Day's headline numbers
 * mean.  Every sentence describes current released behaviour; the code that
 * makes each one true:
 *
 *   Score now        src/ros/game_day_week.py — the lineup over points
 *                    already banked: best-ball leagues re-solve the optimal
 *                    lineup (src/ros/lineup.py), managed leagues use the
 *                    submitted starters.  Scores of record are Sleeper's
 *                    player points (src/ros/game_day_live.py).
 *   Projected finish src/ros/game_day_sim.py — mean of the simulated final
 *                    totals; P10–P90 is the 80% range.  The served draw
 *                    count is matchup_intel.DEFAULT_DRAWS (2,000 today, NOT
 *                    game_day_sim's 10,000 default) and Data info prints
 *                    the real number, so this copy states no count.  Remaining
 *                    production = weekly projection (locked at kickoff;
 *                    preseason average as the fallback) × share of
 *                    regulation left (game_day_week.py).  Players are drawn
 *                    independently (sim_calibration.draw_from_mean).
 *   Win chance       game_day_sim.py — strictly above the opponent in the
 *                    same draw; ties tracked separately.
 *   Beat median      game_day_sim.py — strictly above that draw's median
 *                    of every team's score; only when the league's median
 *                    game is verified on (lineage.medianEnabled).
 *   Pausing          src/api/matchup_intel.py can_simulate — ANY rostered
 *                    player in the league with an unknown game state, or a
 *                    game whose progress cannot be stated (overtime, delay,
 *                    stale feed, missing clock), pauses the whole
 *                    league-week simulation.
 *   Live state       game_day_live.py — ESPN scoreboard when reachable;
 *                    finals from the nflverse schedule; a game past kickoff
 *                    with neither is UNKNOWN, never assumed in progress.
 *
 * Calibration: docs/GAME_DAY_PROBABILITY_SPEC.md §5/§13 — the percentages
 * must earn trust against real results; pregame predictions are archived
 * (docs/game-day/C5_GD_02_PREDICTION_ARCHIVE.md) and no calibration result
 * has been published yet, which is why the copy says so.
 */

import { HelpModal, InfoTip } from "@/components/ds";

/** Best ball re-picks the lineup; a managed league counts submitted starters. */
function lineupWords(bestBall) {
  if (bestBall === true) return "the best possible lineup from your roster (best ball)";
  if (bestBall === false) return "the starters submitted on Sleeper";
  return "the league's lineup (best ball or submitted starters, per league settings)";
}

export function ScoreNowTip({ bestBall, className }) {
  return (
    <InfoTip label="Score now" className={className}>
      <p>
        Points already scored this week, counted for {lineupWords(bestBall)}. This is
        observed, not projected. If Sleeper&apos;s own team total differs it is shown
        beside it; once the week is final, Sleeper&apos;s total is the result of record.
      </p>
    </InfoTip>
  );
}

export function ProjectedFinishTip({ bestBall, className }) {
  return (
    <InfoTip label="Projected finish" className={className}>
      <p>
        The average final score over thousands of simulated weeks (the exact count is under
        Data info): points already scored plus
        each player&apos;s remaining projection, counted for {lineupWords(bestBall)}.
        The 80% range is the 10th to 90th percentile of those simulations.
      </p>
      <p>
        Remaining projection = the weekly projection, locked at kickoff (or the preseason
        average when there is no weekly line), times the share of the game still to play. Players are simulated independently, so outcomes that
        move together inside one NFL game are not modelled.
      </p>
    </InfoTip>
  );
}

export function WinChanceTip({ className }) {
  return (
    <InfoTip label="Win chance" className={className}>
      <p>
        The share of those simulated weeks in which this team finishes strictly ahead of
        its opponent. Ties are counted separately, so the two teams&apos; chances can add
        up to slightly under 100%.
      </p>
      <p>
        It is a model estimate. Pregame predictions are archived so they can be checked
        against real results, but that check has not been published yet.
      </p>
    </InfoTip>
  );
}

export function BeatMedianTip({ className }) {
  return (
    <InfoTip label="Beat median" className={className}>
      <p>
        Shown only in leagues that play an extra weekly game against the league median.
        In each simulated week the median of every team&apos;s score is recomputed, and
        this is the share of weeks this team finishes strictly above it — landing exactly
        on it is a tie, not a win.
      </p>
      <p>
        &quot;Unverified&quot; means the host&apos;s median rule for this league could not
        be confirmed (for example with an odd number of teams).
      </p>
    </InfoTip>
  );
}

/** Whole-page method: observed vs projected, live states, pauses. */
export function GameDayHowItWorks() {
  return (
    <HelpModal title="How Game Day works" label="How this works">
      <h3>Observed vs projected</h3>
      <p>
        <strong>Score now</strong>, a player&apos;s <strong>Scored</strong> points and a
        final <strong>Result</strong> are observed facts from Sleeper.{" "}
        <strong>Projected finish</strong>, <strong>Win chance</strong>,{" "}
        <strong>Beat median</strong>, <strong>Left</strong> and every lineup percentage
        are projections from one simulation of the whole league&apos;s week.
      </p>

      <h3>Lineups</h3>
      <p>
        In a best-ball league the lineup is re-picked to be the best possible one, both
        for points already scored and in every simulated week. In a managed league the
        starters submitted on Sleeper are what count. The league type is shown under
        Data info.
      </p>

      <h3>Live, delayed, stale and unavailable</h3>
      <ul>
        <li>
          Game status comes from a live scoreboard feed when it is reachable, and final
          results also come from the NFL schedule. When neither says what happened to a
          game past its kickoff, that game&apos;s status is <strong>unknown</strong> — it
          is never assumed to be in progress.
        </li>
        <li>
          <strong>Paused</strong>: while any rostered player in the league has an unknown
          game status, or a game&apos;s progress can&apos;t be stated (overtime, a delay,
          a stale feed or a missing clock), the forecast pauses for every team — each
          team&apos;s score feeds the same simulation. Points already scored still show.
        </li>
        <li>
          <strong>Computing</strong>: scores are real; the forecast has not finished yet.
        </li>
        <li>
          <strong>Stale</strong>: the numbers are older than their refresh budget for this
          part of the week. <strong>Partial</strong> or <strong>degraded</strong> means a
          source failed, a stat correction is pending, or the data is behind; Data info
          lists every source and its age.
        </li>
        <li>
          <strong>Unavailable</strong> means no number can be stated. It is never shown as
          0.
        </li>
      </ul>

      <h3>Win chance and median</h3>
      <p>
        Win chance is the share of simulated weeks in which this team finishes strictly
        ahead of its opponent. Beat median, shown only in leagues with a weekly median
        game, is the share of the same simulated weeks it finishes strictly above that
        week&apos;s league median. Both are model estimates whose accuracy against real
        results has not been published yet.
      </p>

      <p>
        Game Day only reads your league. It never sets a lineup or makes a move on
        Sleeper.
      </p>
    </HelpModal>
  );
}
