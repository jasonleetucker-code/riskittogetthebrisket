"use client";

/**
 * MatchupHero — section 1 of Game Day: the selected fantasy team against its
 * opponent, as one compact scoreboard.
 *
 * Renders, verbatim from `GET /api/matchup/intel`:
 *   Score now        side.pointsBanked — the canonical best-ball lineup
 *                    over points already scored (live); side.actualScore,
 *                    the host's total, is the final score of record and is
 *                    shown beside ours whenever the two differ
 *   Projected finish side.outcome.expectedFinalBestBall (mean of the
 *                    OPTIMIZED best-ball total over simulation draws), with
 *                    outcome.projectedP10–projectedP90 as its 80% range
 *   Win chance       side.outcome.winMatchupPct
 *   Beat median      side.outcome.beatMedianPct (only where the league plays
 *                    a median game — lineage.medianEnabled === true)
 *   Projected margin team.outcome.expectedMarginVsOpponent
 *   state            payload.mode -> Upcoming / Live / Final
 *   freshness        payload.freshness (U5) when present, else lineage
 *
 * A withheld probability shows its NAMED reason in words, never a number.
 * An absent score is "Unavailable", never 0.0.
 */

import { Banner, Button, StatusIndicator } from "@/components/ds";
import {
  formatPct,
  formatPoints,
  freshnessLine,
  marginText,
  matchupStateLabel,
  withheldProbabilityReasons,
} from "@/lib/game-day-view";
import styles from "./game-day.module.css";

const STATE_TONE = { live: "info", final: "neutral", pregame: "neutral" };

function ScoreCell({ side, mode }) {
  if (mode === "pregame") return null;
  const lineup = side?.actualLineup;
  // LIVE: the score is the best-ball lineup of points already scored —
  // `pointsBanked` (= actualLineup.total, the canonical lineup owner's
  // answer). Sleeper's own in-progress team total can lag its player
  // points (measured in the real TNF capture: 0.0 beside a 3.77 lineup), so
  // it is shown beside ours when they differ, never silently preferred.
  // FINAL: the host's final total is the result of record.
  const banked = lineup ? (side?.pointsBanked ?? lineup.total ?? null) : null;
  const primaryValue = mode === "final" ? side?.actualScore : lineup ? banked : side?.actualScore;
  const value = formatPoints(primaryValue);
  const host = formatPoints(side?.actualScore);
  const notes = [];
  if (value === null && lineup?.missingPlayerIds?.length) {
    const known = formatPoints(lineup.knownSubtotal);
    notes.push(
      `Scoring missing for ${lineup.missingPlayerIds.length}${known ? ` · known ${known}` : ""}`,
    );
  } else if (lineup?.lineupState === "not_started") {
    notes.push("No players have played yet");
  }
  const secondary = mode === "final" ? formatPoints(banked) : host;
  if (value !== null && secondary !== null && secondary !== value) {
    notes.push(mode === "final" ? `Best-ball lineup ${secondary}` : `Sleeper shows ${secondary}`);
  }
  return (
    <td className={styles.numCell}>
      {value !== null ? (
        <span className={styles.bigNum}>{value}</span>
      ) : (
        <span className={styles.withheldWord}>Unavailable</span>
      )}
      {notes.map((n) => (
        <span key={n} className={styles.numNote}>
          {n}
        </span>
      ))}
    </td>
  );
}

function OutcomeCells({ side, mode, medianShown }) {
  if (mode === "final") {
    return (
      <td className={styles.numCell}>
        <span className={styles.midNum}>{side?.result || "—"}</span>
        {!side?.result ? <span className={styles.numNote}>Result unavailable</span> : null}
      </td>
    );
  }
  const o = side?.outcome;
  const paused = <span className={styles.withheldWord}>{mode === "live" ? "Paused" : "Unavailable"}</span>;
  const finish = formatPoints(o?.expectedFinalBestBall);
  const lo = formatPoints(o?.projectedP10);
  const hi = formatPoints(o?.projectedP90);
  const win = formatPct(o?.winMatchupPct);
  let median = null;
  if (medianShown) {
    const pct = formatPct(o?.beatMedianPct);
    median = pct ? (
      <span className={styles.midNum}>{pct}</span>
    ) : o ? (
      <span className={styles.withheldWord}>Not verified</span>
    ) : (
      paused
    );
  }
  return (
    <>
      <td className={styles.numCell}>
        {finish ? <span className={styles.midNum}>{finish}</span> : paused}
        {finish && lo && hi ? (
          <span className={styles.numNote}>{`80% range ${lo}–${hi}`}</span>
        ) : null}
      </td>
      <td className={styles.numCell}>{win ? <span className={styles.midNum}>{win}</span> : paused}</td>
      {medianShown ? <td className={styles.numCell}>{median}</td> : null}
    </>
  );
}

function SideRow({ side, role, mode, medianShown, selected }) {
  return (
    <tr className={selected ? styles.selectedRow : undefined}>
      <th scope="row" className={styles.sideCell}>
        <span className={styles.sideRole}>{role}</span>
        <span className={styles.sideName}>{side?.displayName || "—"}</span>
        {side?.teamName && side.teamName !== side.displayName ? (
          <span className={styles.sideTeamName}>{side.teamName}</span>
        ) : null}
      </th>
      <ScoreCell side={side} mode={mode} />
      <OutcomeCells side={side} mode={mode} medianShown={medianShown} />
    </tr>
  );
}

export default function MatchupHero({ payload, refreshing, onRefresh }) {
  const p = payload || {};
  const mode = p.mode;
  const team = p.team;
  const opponent = p.opponent;
  const medianShown = mode !== "final" && p.lineage?.medianEnabled === true;
  const fresh = freshnessLine(p);
  const withheld = withheldProbabilityReasons(p);
  const margin = marginText(
    team?.outcome?.expectedMarginVsOpponent,
    team?.displayName,
    opponent?.displayName,
  );
  const outcome = team?.outcome;
  const joint = [
    ["Win both", outcome?.jointTwoZeroPct],
    ["Win matchup, miss median", outcome?.jointOneOneH2hPct],
    ["Lose matchup, beat median", outcome?.jointOneOneMedianPct],
    ["Lose both", outcome?.jointZeroTwoPct],
  ].filter(([, v]) => typeof v === "number");

  return (
    <section className={styles.hero} aria-labelledby="game-day-hero-title">
      <div className={styles.heroStatus}>
        <StatusIndicator status={STATE_TONE[mode] || "neutral"}>{matchupStateLabel(mode)}</StatusIndicator>
        <span id="game-day-hero-title" className={styles.heroEyebrow}>
          Week {p.week} · {p.season}
        </span>
        <span className={fresh.stale ? styles.heroStale : undefined}>{fresh.text}</span>
        <span className={styles.heroStatusSpacer} />
        {onRefresh ? (
          // Not `loading`: that disables the button, and disabling a focused
          // control drops keyboard focus mid-refresh.
          <Button size="sm" variant="ghost" onClick={onRefresh} aria-busy={refreshing || undefined}>
            {refreshing ? "Updating…" : "Refresh"}
          </Button>
        ) : null}
      </div>

      <table className={styles.scoreboard}>
        <caption>
          Week {p.week} matchup: {team?.displayName || "selected team"}
          {opponent ? ` versus ${opponent.displayName}` : ", no scheduled opponent"}
        </caption>
        <thead>
          <tr>
            <th scope="col">Team</th>
            {mode !== "pregame" ? <th scope="col">{mode === "final" ? "Final score" : "Score now"}</th> : null}
            {mode === "final" ? (
              <th scope="col">Result</th>
            ) : (
              <>
                <th scope="col">Projected finish</th>
                <th scope="col">Win chance</th>
                {medianShown ? <th scope="col">Beat median</th> : null}
              </>
            )}
          </tr>
        </thead>
        <tbody>
          <SideRow side={team} role="Selected team" mode={mode} medianShown={medianShown} selected />
          {opponent ? (
            <SideRow side={opponent} role="Opponent" mode={mode} medianShown={medianShown} />
          ) : null}
        </tbody>
      </table>

      {!opponent ? <p className={styles.note}>No scheduled opponent this week.</p> : null}

      {withheld.length ? (
        <Banner tone="warning" title={mode === "live" ? "Win chance paused" : "Win chance unavailable"}>
          {withheld.map((line) => (
            <p key={line}>{line}</p>
          ))}
          {mode === "live" ? (
            <p>Points already scored are shown; nothing is estimated for football we cannot see.</p>
          ) : null}
        </Banner>
      ) : null}

      {mode !== "final" && (margin || joint.length) ? (
        <dl className={styles.heroFacts}>
          {margin ? (
            <div>
              <dt>Projected margin</dt>
              <dd>{margin}</dd>
            </div>
          ) : null}
          {typeof outcome?.tieMatchupPct === "number" && outcome.tieMatchupPct > 0 ? (
            <div>
              <dt>Tie</dt>
              <dd>{formatPct(outcome.tieMatchupPct)}</dd>
            </div>
          ) : null}
          {joint.map(([label, value]) => (
            <div key={label}>
              <dt>{label}</dt>
              <dd>{formatPct(value)}</dd>
            </div>
          ))}
        </dl>
      ) : null}

      {mode === "final" && p.recapUrl ? (
        <p className={styles.note}>
          <a href={p.recapUrl}>Week {p.week} articles and recap</a>
        </p>
      ) : null}
    </section>
  );
}
