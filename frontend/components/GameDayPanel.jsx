"use client";

/**
 * GameDayPanel — the canonical Game Day surface.
 *
 * The private counterpart to /league's public preview. That one is
 * head-to-head record and recent form, which are facts about the past.
 * This one is projections, win and beat-median probabilities, the expected
 * best-ball lineup and roster weaknesses — proprietary decision
 * intelligence under CLAUDE.md §5, which is why it lives on a private
 * route and reads a `no-store` endpoint.
 *
 * DISPLAY ONLY. Every number here is read from `GET /api/matchup/intel`
 * verbatim; nothing is recomputed, re-ranked or re-derived, the same
 * materializer relationship `buildRows` has with the canonical contract.
 *
 * Scheduled, LIVE, and FINAL are derived from the API payload. Actual scores
 * and the canonical current lineup remain visible when probability must be
 * withheld for missing evidence or the unresolved in-progress player policy.
 * A missing projection never becomes 50% or zero.
 */

import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { LoadingState, NflTeamLogo } from "@/components/ui";
import { EmptyState, FailureState, Panel } from "@/components/ds";
import { useUserState } from "@/components/useUserState";

function pct(value) {
  return value === null || value === undefined ? null : `${value.toFixed(1)}%`;
}

function points(value) {
  return value === null || value === undefined ? null : value.toFixed(1);
}

//: The Game Day state machine, spec §6/§7. It is DERIVED from the payload,
//: never from the clock: `mode: "pregame"` is what the resolver returns for a
//: week the resolver reports as unplayed. Reading a wall clock here would be
//: a second answer to "has the week started".
const STATE_SCHEDULED = "SCHEDULED";
const STATE_LIVE = "LIVE";

function StateBadge({ state, label: labelOverride }) {
  const label =
    labelOverride ??
    (state === STATE_SCHEDULED ? "Scheduled · pregame" : state === STATE_LIVE ? "Live" : state);
  return (
    <span
      style={{
        display: "inline-block",
        fontSize: "0.62rem",
        textTransform: "uppercase",
        letterSpacing: "0.08em",
        padding: "2px 8px",
        borderRadius: 999,
        border: "1px solid var(--border-bright)",
        color: "var(--subtext)",
        marginBottom: 8,
      }}
    >
      {label}
    </span>
  );
}

function Card({ title, subtitle, children }) {
  return (
    <section className="ds-panel" style={{ marginBottom: 16 }}>
      <div className="ds-panel__body">
        {title && <h2 style={{ margin: "0 0 2px", fontSize: "1rem" }}>{title}</h2>}
        {subtitle && (
          <p style={{ margin: "0 0 10px", fontSize: "0.8rem", color: "var(--subtext)" }}>
            {subtitle}
          </p>
        )}
        {children}
      </div>
    </section>
  );
}

function SideHeadline({ side, label }) {
  const outcome = side?.outcome;
  const win = pct(outcome?.winMatchupPct);
  return (
    <div style={{ flex: "1 1 220px", minWidth: 200 }}>
      <div
        style={{
          fontSize: "0.64rem",
          textTransform: "uppercase",
          letterSpacing: "0.08em",
          color: "var(--subtext)",
        }}
      >
        {label}
      </div>
      <div style={{ fontSize: "1.02rem", fontWeight: 800, marginTop: 2 }}>
        {side?.displayName || "—"}
      </div>
      <div style={{ fontSize: "0.74rem", color: "var(--subtext)" }}>{side?.teamName || ""}</div>
      <div style={{ fontSize: "1.6rem", fontWeight: 800, marginTop: 8 }}>
        {win ?? <span style={{ fontSize: "0.9rem", fontWeight: 600 }}>No projection</span>}
      </div>
      {outcome && (
        <div style={{ fontSize: "0.72rem", color: "var(--subtext)", marginTop: 2 }}>
          {points(outcome.projectedMean)} projected · {points(outcome.projectedP10)}–
          {points(outcome.projectedP90)} range
        </div>
      )}
      {outcome?.beatMedianPct !== null && outcome?.beatMedianPct !== undefined ? (
        <div style={{ fontSize: "0.72rem", color: "var(--subtext)" }}>
          {pct(outcome.beatMedianPct)} to beat the league median
        </div>
      ) : outcome ? (
        <div style={{ fontSize: "0.72rem", color: "var(--subtext)" }}>
          Median game: {outcome.beatMedianState}
        </div>
      ) : null}
    </div>
  );
}

function ActualSide({ side, final }) {
  if (!side) return null;
  const lineup = side.actualLineup;
  return (
    <div style={{ flex: "1 1 280px", minWidth: 0 }}>
      <h3>{side.displayName}</h3>
      <p>{final ? "Final score" : "Current score"}: {points(side.actualScore) ?? "Unavailable"}
        {final && side.result ? ` · ${side.result}` : ""}</p>
      <p>{final ? "Final" : "Current"} optimal lineup: {points(lineup?.total) ?? "Incomplete scoring coverage"}</p>
      {lineup?.missingPlayerIds?.length > 0 && <p>Scoring unavailable for {lineup.missingPlayerIds.length} players. Known lineup subtotal: {points(lineup.knownSubtotal) ?? "Unavailable"}.</p>}
      <table style={{ width: "100%", fontSize: "0.8rem" }}>
        <thead><tr><th>Slot</th><th>Player</th><th>Points</th></tr></thead>
        <tbody>{lineup?.slots?.map(s => <tr key={s.slotIndex}><td>{s.slot}</td><td>{s.name}</td><td>{points(s.points) ?? "Unavailable"}</td></tr>)}</tbody>
      </table>
      {!final && <>
        <h4>Player status and remaining possibilities</h4>
        <p>Eligible upcoming and in-progress players can still displace the current best-ball lineup. Unknown game states remain unresolved.</p>
        {side.remainingLineupPossibilities?.length > 0 && <ul>{side.remainingLineupPossibilities.map(player => <li key={`swing-${player.playerId}`}>
          {player.name} · {player.currentOptimal ? "currently holding an optimal slot" : "can displace the current lineup"} · eligible at {player.eligibleSlots.map(s => s.slot).join(", ")}
        </li>)}</ul>}
        <ul>{side.players?.map(player => <li key={player.playerId}>
          {player.name} · {player.state.replaceAll("_", " ")} · banked {points(player.pointsScored) ?? "unknown"}
          {player.state === "not_started" ? ` · remaining estimate ${points(player.projectedRemaining) ?? "unavailable"}` : ""}
          {player.state === "in_progress" ? (player.projectedRemaining != null ? ` · remaining (time-prorated) ${points(player.projectedRemaining)}` : " · remaining production unavailable (no reliable game-progress evidence)") : ""}
        </li>)}</ul>
      </>}
    </div>
  );
}

function Lineup({ side }) {
  const lineup = side?.expectedLineup;
  if (!lineup || !lineup.slots?.length) {
    return (
      <EmptyState
        title={`No expected lineup for ${side?.displayName || "this team"}`}
        description="No projection covered enough of this roster to fill the league's starting slots."
      />
    );
  }
  return (
    <div>
      <table style={{ width: "100%", fontSize: "0.82rem", borderCollapse: "collapse" }}>
        <thead>
          <tr style={{ textAlign: "left", color: "var(--subtext)" }}>
            <th style={{ padding: "4px 6px" }}>Slot</th>
            <th style={{ padding: "4px 6px" }}>Player</th>
            <th style={{ padding: "4px 6px", textAlign: "right" }}>Proj</th>
          </tr>
        </thead>
        <tbody>
          {lineup.slots.map((s) => (
            <tr key={`${s.slot}-${s.slotIndex}`}>
              <td style={{ padding: "4px 6px", color: "var(--subtext)" }}>{s.slot}</td>
              <td style={{ padding: "4px 6px" }}>{s.name}</td>
              <td style={{ padding: "4px 6px", textAlign: "right" }}>
                {points(s.projectedPoints)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <div style={{ fontSize: "0.78rem", marginTop: 6 }}>
        Total {points(lineup.projectedTotal)}
      </div>
      {lineup.unpricedPlayerIds?.length > 0 && (
        <div style={{ fontSize: "0.72rem", color: "var(--subtext)", marginTop: 4 }}>
          {lineup.unpricedPlayerIds.length} rostered player
          {lineup.unpricedPlayerIds.length === 1 ? "" : "s"} had no projection and were left out of
          this lineup rather than counted as zero.
        </div>
      )}
    </div>
  );
}

function JointOutcomes({ outcome }) {
  // Spec §8. Optional presentation, NOT another prediction engine: these
  // four come from the same draws as the two headline numbers, which is
  // why ties are excluded from these win/loss buckets and why they are only rendered when the median
  // leg is actually live. A median-disabled league gets nothing here
  // rather than a four-way split of a two-way week.
  const rows = [
    ["2-0 week", outcome?.jointTwoZeroPct, "win the matchup and beat the median"],
    ["1-1 via matchup", outcome?.jointOneOneH2hPct, "win the matchup, miss the median"],
    ["1-1 via median", outcome?.jointOneOneMedianPct, "lose the matchup, beat the median"],
    ["0-2 week", outcome?.jointZeroTwoPct, "lose both"],
  ];
  if (rows.every(([, v]) => v === null || v === undefined)) return null;
  return (
    <Card
      title="How the week can land"
      subtitle="Win/loss outcomes from the same simulation. Draws with a matchup or median tie are excluded, so these may total less than 100%."
    >
      <table style={{ width: "100%", fontSize: "0.82rem", borderCollapse: "collapse" }}>
        <tbody>
          {rows.map(([label, value, hint]) => (
            <tr key={label}>
              <td style={{ padding: "4px 6px", fontWeight: 700 }}>{label}</td>
              <td style={{ padding: "4px 6px", color: "var(--subtext)" }}>{hint}</td>
              <td style={{ padding: "4px 6px", textAlign: "right", fontWeight: 700 }}>
                {pct(value) ?? "—"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </Card>
  );
}

function ArchiveNote({ archive }) {
  // W1-26 asks for the archive timestamp, and the reason it is here is
  // that the pregame archive is the ONLY record of what was knowable
  // before the outcome. "Nothing captured" and "could not read the
  // archive" are different facts and are rendered as different sentences.
  if (!archive) return null;
  if (archive.state === "captured") {
    return (
      <div style={{ fontSize: "0.75rem", color: "var(--subtext)", marginTop: 8 }}>
        Pregame state archived {archive.capturedAt} for {archive.teamsCaptured} team
        {archive.teamsCaptured === 1 ? "" : "s"}
        {archive.captureKinds?.length ? ` (${archive.captureKinds.join(", ")})` : ""}.
      </div>
    );
  }
  if (archive.state === "unreadable") {
    return (
      <div style={{ fontSize: "0.75rem", color: "var(--subtext)", marginTop: 8 }}>
        Pregame archive could not be read ({archive.reason}). This is not the same as nothing
        having been captured.
      </div>
    );
  }
  return (
    <div style={{ fontSize: "0.75rem", color: "var(--subtext)", marginTop: 8 }}>
      No pregame state archived for this week yet. Once the week scores, what was knowable
      beforehand is not recoverable.
    </div>
  );
}

function Lineage({ lineage }) {
  if (!lineage) return null;
  const cov = lineage.estimateCoverage || {};
  const sim = lineage.simulation;
  return (
    <Card
      title="Where these numbers come from"
      subtitle="Every figure above is produced by a canonical owner and copied here. This is what it was built on."
    >
      {lineage.gameStateLimitation && <p>{lineage.gameStateLimitation}</p>}
      {lineage.sleeperFetchedAt && <p>Host data fetched {new Date(lineage.sleeperFetchedAt * 1000).toISOString()}</p>}
      {lineage.gameEvidence && <details><summary>Game-state source observations</summary><ul>{Object.entries(lineage.gameEvidence).map(([team, g]) => <li key={team}>{team}: {g.state} · {g.source} · observed {g.observedAt ? new Date(g.observedAt * 1000).toISOString() : "timestamp unavailable"}</li>)}</ul></details>}
      <dl style={{ fontSize: "0.78rem", margin: 0, display: "grid", gap: 6 }}>
        <div>
          <dt style={{ color: "var(--subtext)" }}>Projection source</dt>
          <dd style={{ margin: 0 }}>
            {lineage.projectionSource || "none — no projection snapshot was available"}
          </dd>
        </div>
        {lineage.projectionHorizonNote && (
          <div>
            <dt style={{ color: "var(--subtext)" }}>Horizon</dt>
            <dd style={{ margin: 0 }}>{lineage.projectionHorizonNote}</dd>
          </div>
        )}
        <div>
          <dt style={{ color: "var(--subtext)" }}>Coverage</dt>
          <dd style={{ margin: 0 }}>
            {cov.priced ?? "—"} of {cov.active ?? "—"} active players priced
          </dd>
        </div>
        <div>
          <dt style={{ color: "var(--subtext)" }}>League rules</dt>
          <dd style={{ margin: 0 }}>
            {lineage.bestBall ? "Best ball" : "Managed lineups"} ·{" "}
            {lineage.medianEnabled === true
              ? "median game on"
              : lineage.medianEnabled === false
                ? "median game off"
                : "median game unverified"}{" "}
            · slots from {lineage.starterSlotSource || "unknown"}
          </dd>
        </div>
        {sim && (
          <div>
            <dt style={{ color: "var(--subtext)" }}>Simulation</dt>
            <dd style={{ margin: 0 }}>
              {sim.modelVersion} · {sim.draws} draws · points model {sim.pointsModelSource}
              {sim.thresholdSemanticsVerified === false && (
                <>
                  {" "}
                  ·{" "}
                  <strong>
                    median threshold uses &ldquo;{sim.thresholdSemantics}&rdquo; and is NOT verified
                    against the host
                  </strong>
                </>
              )}
            </dd>
          </div>
        )}
      </dl>
    </Card>
  );
}

//: nflSlate's game-state vocabulary matches `GameEvidence.state`
//: (`src/ros/game_day_week.py`), NOT the matchup-level SCHEDULED/LIVE pair
//: above -- a different, per-game axis, so it gets its own label map rather
//: than overloading STATE_SCHEDULED/STATE_LIVE.
const NFL_GAME_STATE_LABELS = {
  not_started: "Scheduled",
  in_progress: "Live",
  completed: "Final",
  unknown: "Status unknown",
};

function formatKickoff(epochSeconds) {
  if (epochSeconds === null || epochSeconds === undefined) return null;
  try {
    return new Intl.DateTimeFormat("en-US", {
      weekday: "short",
      month: "short",
      day: "numeric",
      hour: "numeric",
      minute: "2-digit",
      timeZone: "America/New_York",
      timeZoneName: "short",
    }).format(new Date(epochSeconds * 1000));
  } catch {
    return null;
  }
}

function GamePlayerLine({ player }) {
  const scoreText =
    player.state === "not_started"
      ? `projected ${points(player.projectedRemaining) ?? "unavailable"}`
      : player.state === "in_progress"
        ? `live ${points(player.pointsScored) ?? "0.0"}` +
          (player.projectedRemaining != null
            ? ` · remaining (time-prorated) ${points(player.projectedRemaining)}`
            : " · remaining unavailable")
        : player.state === "completed"
          ? `final ${points(player.pointsScored) ?? "unavailable"}`
          : "status unknown";
  return (
    <li style={{ fontSize: "0.8rem" }}>
      {player.name}
      {player.fantasyPositions?.length ? ` · ${player.fantasyPositions.join("/")}` : ""} ·{" "}
      {scoreText}
    </li>
  );
}

function NflGameCard({ game, team, opponent }) {
  const kickoff = formatKickoff(game.kickoffAt) || "Kickoff time unavailable";
  const mine = game.players.filter((p) => p.side === "team");
  const theirs = game.players.filter((p) => p.side === "opponent");

  // The complete real schedule includes every game, so an irrelevant one
  // (nobody from this matchup plays in it) still renders -- just compactly,
  // rather than as an empty expanded card, so the games that matter stay
  // visually prominent.
  if (mine.length === 0 && theirs.length === 0) {
    return (
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 8,
          padding: "6px 4px",
          fontSize: "0.78rem",
          color: "var(--subtext)",
        }}
      >
        <span style={{ minWidth: 190 }}>{kickoff}</span>
        <NflTeamLogo team={game.awayTeam} size={16} showAbbr />
        <span>@</span>
        <NflTeamLogo team={game.homeTeam} size={16} showAbbr />
      </div>
    );
  }

  return (
    <Panel
      title={
        <span style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <NflTeamLogo team={game.awayTeam} size={20} showAbbr />
          <span>@</span>
          <NflTeamLogo team={game.homeTeam} size={20} showAbbr />
        </span>
      }
      subtitle={kickoff}
      actions={
        <StateBadge state={game.state} label={NFL_GAME_STATE_LABELS[game.state] || game.state} />
      }
      style={{ marginBottom: 10 }}
    >
      <div style={{ display: "flex", flexWrap: "wrap", gap: 20 }}>
        {mine.length > 0 && (
          <div style={{ flex: "1 1 220px", minWidth: 200 }}>
            <h4
              style={{
                fontSize: "0.72rem",
                textTransform: "uppercase",
                letterSpacing: "0.06em",
                color: "var(--subtext)",
                margin: "0 0 4px",
              }}
            >
              {team?.displayName || "Your team"}
            </h4>
            <ul style={{ margin: 0, paddingLeft: 16 }}>
              {mine.map((p) => (
                <GamePlayerLine key={p.playerId} player={p} />
              ))}
            </ul>
          </div>
        )}
        {theirs.length > 0 && (
          <div style={{ flex: "1 1 220px", minWidth: 200 }}>
            <h4
              style={{
                fontSize: "0.72rem",
                textTransform: "uppercase",
                letterSpacing: "0.06em",
                color: "var(--subtext)",
                margin: "0 0 4px",
              }}
            >
              {opponent?.displayName || "Opponent"}
            </h4>
            <ul style={{ margin: 0, paddingLeft: 16 }}>
              {theirs.map((p) => (
                <GamePlayerLine key={p.playerId} player={p} />
              ))}
            </ul>
          </div>
        )}
      </div>
    </Panel>
  );
}

function NflSlateSection({ slate, team, opponent }) {
  if (!slate) return null;
  if (slate.scheduleState !== "available") {
    return (
      <Card title="This week's NFL slate">
        <p style={{ fontSize: "0.82rem", color: "var(--subtext)" }}>
          NFL schedule unavailable
          {slate.scheduleUnavailableReason ? ` (${slate.scheduleUnavailableReason})` : ""}.
        </p>
      </Card>
    );
  }
  return (
    <Card
      title="This week's NFL slate"
      subtitle="Every real NFL game this week, in true kickoff order, with this matchup's players grouped under the game they're playing in."
    >
      {slate.games.map((game) => (
        <NflGameCard key={game.gameId} game={game} team={team} opponent={opponent} />
      ))}
      {slate.byeWeek?.length > 0 && (
        <p style={{ fontSize: "0.78rem", color: "var(--subtext)", marginTop: 10 }}>
          On bye this week: {slate.byeWeek.map((p) => p.name).join(", ")}.
        </p>
      )}
      {slate.unattributed?.length > 0 && (
        <p style={{ fontSize: "0.78rem", color: "var(--subtext)", marginTop: 4 }}>
          Could not match to an NFL game: {slate.unattributed.map((p) => p.name).join(", ")}.
        </p>
      )}
    </Card>
  );
}

export default function GameDayPanel() {
  const [state, setState] = useState({ status: "loading", payload: null, error: null });

  // SELECTED-TEAM CONTEXT (W1-25). `useUserState().selectedTeam` is the
  // switcher's own answer and the same one /rosters and /phases read.
  // Without it this panel fell back to the backend's session inference,
  // which is a DIFFERENT question — "who is signed in" rather than "which
  // team did you pick" — so switching teams left the matchup unchanged.
  const { state: userState } = useUserState();
  // An explicit `?team=<ownerId>` WINS over the switcher.
  //
  // Two reasons, and the second is the one that made this necessary. It
  // makes the page linkable per team, which the endpoint has always
  // supported (`/api/matchup/intel?team=`) while the page did not. And it
  // is the only way a session that has selected no team — a guest pass in
  // the production-verification workflow, say — can see this surface for a
  // REAL team at all; without it such a session gets "No team selected"
  // and the page cannot be verified for anyone.
  //
  // Explicit-over-implicit is also the same precedence the backend
  // resolver uses (query param, then session, then registry default), so
  // the page and the endpoint agree about who wins.
  const searchParams = useSearchParams();
  const urlOwnerId = String(searchParams?.get("team") || "").trim();
  const selectedOwnerId =
    urlOwnerId ||
    (userState?.selectedTeam?.ownerId ? String(userState.selectedTeam.ownerId) : "");

  const load = useCallback(async () => {
    setState({ status: "loading", payload: null, error: null });
    try {
      const qs = selectedOwnerId ? `?team=${encodeURIComponent(selectedOwnerId)}` : "";
      const res = await fetch(`/api/matchup/intel${qs}`, { cache: "no-store" });
      const body = await res.json().catch(() => ({}));
      if (res.ok) {
        setState({ status: "ok", payload: body, error: null });
        return;
      }
      // The error CODE is the state. Collapsing 409 into a generic failure
      // is what would make "the games have started" look like a bug.
      setState({ status: "error", payload: null, error: { httpStatus: res.status, ...body } });
    } catch (err) {
      setState({ status: "error", payload: null, error: { error: "network", detail: String(err) } });
    }
  }, [selectedOwnerId]);

  useEffect(() => {
    load();
    const timer = setInterval(load, 60000);
    return () => clearInterval(timer);
  }, [load]);

  if (state.status === "loading") {
    return <LoadingState message="Loading this week's matchup..." />;
  }

  if (state.status === "error") {
    const code = state.error?.error;
    // These three are STATES, not faults, and `EmptyState` is the quiet
    // voice for them. Routing them through a failure primitive would tell
    // a manager something is broken when the honest answer is "the games
    // started", "the host has not said", or "pick a team".
    if (code === "week_in_progress") {
      return (
        <div>
          <StateBadge state={STATE_LIVE} />
          <EmptyState
            title="This week has already started"
            description="Pregame intelligence is only meaningful before kickoff. Live in-game probabilities need a game-state feed this site does not yet carry, so nothing is shown rather than a pregame number presented as a live one."
          />
        </div>
      );
    }
    if (code === "clock_unavailable") {
      return (
        <EmptyState
          title="The host has not stated the current week"
          description="Sleeper did not report a season and week, and guessing one would describe a different week than your league is playing."
        />
      );
    }
    if (code === "team_required" || code === "team_not_found") {
      return (
        <EmptyState
          title="No team selected"
          description="Pick your team from the switcher above, or pass ?team= on this URL."
        />
      );
    }
    // Anything else IS a fault, and `FailureState` is the primitive that
    // keeps "signed out", "declining for a reason" and "not answering"
    // from rendering identically. The server's own words come first.
    return (
      <FailureState
        failure={{
          kind:
            state.error?.httpStatus === 401
              ? "auth"
              : state.error?.httpStatus === 503
                ? "degraded"
                : state.error?.error === "network"
                  ? "offline"
                  : "error",
          code: state.error?.error,
          message: state.error?.message || state.error?.detail || "",
        }}
        onRetry={load}
        variant="block"
        context="this week's matchup"
      />
    );
  }

  const p = state.payload || {};
  const team = p.team;
  const opponent = p.opponent;
  const final = p.mode === "final";
  const scored = p.mode === "live" || final;
  const subtitle = final
    ? "Final scoring and optimal lineup from canonical league owners."
    : scored
      ? "Current scoring and remaining-week evidence. Private — not shown on the public league page."
      : "Win probability from the canonical league-week simulation. Private — not shown on the public league page.";

  return (
    <div>
      <Card
        title={`Week ${p.week} · ${p.season}`}
        subtitle={subtitle}
      >
        <StateBadge state={p.mode === "pregame" ? STATE_SCHEDULED : p.mode?.toUpperCase()} />
        <div style={{ display: "flex", flexWrap: "wrap", gap: 20 }}>
          {scored ? <ActualSide side={team} final={final} /> : <SideHeadline side={team} label="Your team" />}
          {opponent ? (
            scored ? <ActualSide side={opponent} final={final} /> : <SideHeadline side={opponent} label="Opponent" />
          ) : (
            <div style={{ flex: "1 1 220px", alignSelf: "center", color: "var(--subtext)" }}>
              No scheduled opponent this week.
            </div>
          )}
        </div>
        <ArchiveNote archive={p.lineage?.archive} />
        {p.notes?.length > 0 && (
          <ul
            style={{
              fontSize: "0.75rem",
              color: "var(--subtext)",
              marginTop: 12,
              paddingLeft: 18,
            }}
          >
            {p.notes.map((n) => (
              <li key={n}>{n}</li>
            ))}
          </ul>
        )}
      </Card>

      {p.probabilityState === "LIVE_PROGRESS_UNAVAILABLE" && <p>Live probabilities unavailable: in-progress remaining production could not be estimated (no reliable game-progress evidence). Actual scoring is preserved.</p>}
      {p.probabilityState === "GAME_STATE_OR_SCORING_UNAVAILABLE" && <p>Live probabilities unavailable: game-state or scoring evidence is incomplete.</p>}
      {scored && !final && team?.outcome && <Card title="Remaining-week probabilities"><SideHeadline side={team} label="Your team" /></Card>}

      <NflSlateSection slate={p.nflSlate} team={team} opponent={opponent} />

      {final && p.recapUrl && <p><a href={p.recapUrl}>Week {p.week} articles and recap</a> · Recap appears here after the canonical manual article workflow publishes it.</p>}
      {!final && <JointOutcomes outcome={team?.outcome} />}

      {!scored && <Card
        title="Expected best-ball lineup"
        subtitle="The lineup your mean projection implies. The simulation re-solves this on every draw, so no single lineup is the answer — this is the one to plan against."
      >
        <div style={{ display: "flex", flexWrap: "wrap", gap: 24 }}>
          <div style={{ flex: "1 1 280px", minWidth: 260 }}>
            <h3 style={{ fontSize: "0.8rem", margin: "0 0 6px" }}>{team?.displayName}</h3>
            <Lineup side={team} />
          </div>
          {opponent && (
            <div style={{ flex: "1 1 280px", minWidth: 260 }}>
              <h3 style={{ fontSize: "0.8rem", margin: "0 0 6px" }}>{opponent.displayName}</h3>
              <Lineup side={opponent} />
            </div>
          )}
        </div>
      </Card>}

      <Lineage lineage={p.lineage} />
    </div>
  );
}
