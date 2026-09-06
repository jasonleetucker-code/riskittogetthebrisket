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
 * The states are the design. This endpoint has three non-error outcomes a
 * generic "failed to load" would flatten into one, and each means
 * something different to a manager:
 *
 *   • `week_in_progress` (409) — the games have started. Pregame
 *     intelligence is no longer the question, and that is a STATE, not a
 *     failure.
 *   • priced — the full answer.
 *   • unpriced — the matchup and rosters are real, but no projection
 *     snapshot covered them, so there is no probability. It renders the
 *     matchup and says why the numbers are missing. It NEVER shows 50%.
 */

import { useCallback, useEffect, useState } from "react";
import { LoadingState } from "@/components/ui";
import { EmptyState, FailureState } from "@/components/ds";
import { useUserState } from "@/components/useUserState";

function pct(value) {
  return value === null || value === undefined ? null : `${value.toFixed(1)}%`;
}

function points(value) {
  return value === null || value === undefined ? null : value.toFixed(1);
}

//: The Game Day state machine, spec §6/§7. It is DERIVED from the payload,
//: never from the clock: `mode: "pregame"` is what the resolver returns for a
//: week the host reports as unplayed, and a 409 `week_in_progress` is the host
//: saying scoring has begun. Reading a wall clock here would be a second
//: answer to "has the week started", and the host's is the only one that
//: counts.
const STATE_SCHEDULED = "SCHEDULED";
const STATE_LIVE = "LIVE";

function StateBadge({ state }) {
  const label =
    state === STATE_SCHEDULED ? "Scheduled · pregame" : state === STATE_LIVE ? "Live" : state;
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
  // why they sum to ~100% and why they are only rendered when the median
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
      subtitle="The four mutually exclusive outcomes, from the same simulated draws as the two headline numbers."
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

export default function GameDayPanel() {
  const [state, setState] = useState({ status: "loading", payload: null, error: null });

  // SELECTED-TEAM CONTEXT (W1-25). `useUserState().selectedTeam` is the
  // switcher's own answer and the same one /rosters and /phases read.
  // Without it this panel fell back to the backend's session inference,
  // which is a DIFFERENT question — "who is signed in" rather than "which
  // team did you pick" — so switching teams left the matchup unchanged.
  const { state: userState } = useUserState();
  const selectedOwnerId = userState?.selectedTeam?.ownerId
    ? String(userState.selectedTeam.ownerId)
    : "";

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

  return (
    <div>
      <Card
        title={`Week ${p.week} · ${p.season}`}
        subtitle="Win probability from the canonical league-week simulation. Private — not shown on the public league page."
      >
        <StateBadge state={p.mode === "pregame" ? STATE_SCHEDULED : p.mode} />
        <div style={{ display: "flex", flexWrap: "wrap", gap: 20 }}>
          <SideHeadline side={team} label="Your team" />
          {opponent ? (
            <SideHeadline side={opponent} label="Opponent" />
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

      <JointOutcomes outcome={team?.outcome} />

      <Card
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
      </Card>

      <Lineage lineage={p.lineage} />
    </div>
  );
}
