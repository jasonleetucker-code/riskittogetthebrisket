"use client";

import { useMemo } from "react";
import Link from "next/link";
import { FailureState } from "@/components/ds/FailureState";
import { EmptyState, LoadingState } from "@/components/ui";
import { useRosterIntelligence } from "@/components/useRosterIntelligence";
import { useUserState } from "@/components/useUserState";
import { teamStrengthLadder } from "@/lib/roster-intelligence";
import { analyzeLeaguePhases } from "@/lib/team-phase";

const TONE_COLOR = {
  up: "var(--green)",
  warn: "var(--amber)",
  down: "var(--red)",
};

function fmtAge(a) {
  if (a == null || !Number.isFinite(a)) return "—";
  return a.toFixed(1);
}

function fmtValue(v) {
  if (v == null || !Number.isFinite(v)) return "—";
  return Math.round(v).toLocaleString();
}

/** Each refusal gets its own sentence — same posture as
 *  TeamStrengthCard's StrengthFailure, since this panel reads the same
 *  endpoint and can fail the same ways. */
function PhaseFailure({ failure }) {
  if (!failure) return null;
  const { kind, message } = failure;
  if (kind === "auth") {
    return <EmptyState title="Sign in to see league phases" message={message} />;
  }
  if (kind === "team_required") {
    return (
      <EmptyState
        title="Choose a team"
        message={
          message ||
          "Pick your team above to see league phases and your natural trade partners."
        }
      />
    );
  }
  if (kind === "team_not_found") {
    return (
      <EmptyState
        title="That team is not in this league"
        message={message || "Pick a different team above."}
      />
    );
  }
  if (kind === "not_ready") {
    return (
      <EmptyState
        title="League phases are not ready yet"
        message={
          message ||
          "The league's rosters have not been loaded on this server yet."
        }
      />
    );
  }
  if (kind === "league" || kind === "unavailable") {
    return (
      <FailureState
        failure={{ kind: "unavailable", message: message || "The roster intelligence service did not respond." }}
        context="League phases"
        variant="block"
      />
    );
  }
  return (
    <EmptyState
      title="League phases could not be measured"
      message={message || "An unexpected error occurred."}
    />
  );
}

export default function TeamPhasePanel() {
  const { state: userState } = useUserState();
  const myOwnerId = userState?.selectedTeam?.ownerId
    ? String(userState.selectedTeam.ownerId)
    : "";

  // Same canonical source `/rosters` uses (src/roster_intel/strength.py +
  // age_portfolio.py via GET /api/roster/intelligence). Team-scoped by
  // the endpoint's own contract (a team is needed to resolve "you are"),
  // but `leagueContext` — every team's strengthTotal/valueWeightedCoreAge —
  // is always included regardless of which team is asked.
  const { loading, data, failure } = useRosterIntelligence({ ownerId: myOwnerId });

  const analysis = useMemo(
    () => analyzeLeaguePhases(teamStrengthLadder(data, { myOwnerId })),
    [data, myOwnerId],
  );

  if (loading) {
    return (
      <p className="muted" style={{ fontSize: "0.72rem", margin: "8px 0" }}>
        Loading league rosters…
      </p>
    );
  }
  if (failure) {
    return <PhaseFailure failure={failure} />;
  }
  if (!analysis.teams.length) {
    return (
      <p className="muted" style={{ fontSize: "0.72rem", margin: "8px 0" }}>
        League phases unavailable — no Sleeper rosters in the active league&apos;s
        data. Sign in and pick your team on the league page.
      </p>
    );
  }

  const myRow = myOwnerId
    ? analysis.teams.find((t) => t.ownerId === myOwnerId)
    : null;
  const myPartnerships = myOwnerId
    ? analysis.partnerships.filter(
        (p) => p.winnerOwnerId === myOwnerId || p.rebuilderOwnerId === myOwnerId,
      )
    : [];

  return (
    <div className="card" style={{ marginTop: 10, display: "flex", flexDirection: "column", gap: 10 }}>
      <div>
        <h3 style={{ margin: 0, fontSize: "0.92rem" }}>Win-now vs Rebuild</h3>
        <p className="muted" style={{ fontSize: "0.7rem", margin: "4px 0 0" }}>
          Each team classified by Team Strength (meaningful core) × value-weighted core
          age, against the league medians ({fmtValue(analysis.leagueMedians.value)} strength ·{" "}
          {fmtAge(analysis.leagueMedians.age)} age).
        </p>
      </div>

      {myRow && (
        <div style={{ padding: 8, borderRadius: 4, border: "1px solid var(--border)" }}>
          <div style={{ fontSize: "0.74rem", color: "var(--subtext)" }}>You are:</div>
          <div style={{ display: "flex", alignItems: "baseline", gap: 8, flexWrap: "wrap" }}>
            <strong style={{ fontSize: "0.96rem", color: TONE_COLOR[myRow.phase.tone] }}>
              {myRow.phase.label}
            </strong>
            <span className="muted" style={{ fontSize: "0.74rem" }}>
              · strength {fmtValue(myRow.totalValue)} · core age {fmtAge(myRow.medianAge)}
            </span>
          </div>
        </div>
      )}

      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th style={{ textAlign: "left" }}>Team</th>
              <th style={{ textAlign: "left" }}>Phase</th>
              <th style={{ textAlign: "right" }}>Team Strength</th>
              <th style={{ textAlign: "right" }}>Core age</th>
            </tr>
          </thead>
          <tbody>
            {analysis.teams.map((t) => {
              const isMe = myOwnerId && t.ownerId === myOwnerId;
              return (
                <tr key={t.ownerId || t.name}>
                  <td style={{ fontWeight: isMe ? 700 : 500 }}>
                    {t.ownerId ? (
                      <Link
                        href={`/league/franchise/${encodeURIComponent(t.ownerId)}`}
                        style={{ color: "var(--cyan)", textDecoration: "none" }}
                      >
                        {t.name}
                        {isMe && (
                          <span className="muted" style={{ marginLeft: 6, fontSize: "0.66rem" }}>
                            (you)
                          </span>
                        )}
                      </Link>
                    ) : (
                      t.name
                    )}
                  </td>
                  <td>
                    <span
                      className="badge"
                      style={{
                        backgroundColor: "var(--surface-2)",
                        color: TONE_COLOR[t.phase.tone],
                        fontSize: "0.7rem",
                      }}
                    >
                      {t.phase.label}
                    </span>
                  </td>
                  <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>
                    {fmtValue(t.totalValue)}
                  </td>
                  <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>
                    {fmtAge(t.medianAge)}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {myPartnerships.length > 0 && (
        <div>
          <strong style={{ fontSize: "0.84rem" }}>Natural trade partners for you</strong>
          <ul style={{ margin: "4px 0 0 16px", padding: 0, fontSize: "0.78rem" }}>
            {myPartnerships.slice(0, 3).map((p) => {
              const otherName =
                p.winnerOwnerId === myOwnerId ? p.rebuilderName : p.winnerName;
              const otherId =
                p.winnerOwnerId === myOwnerId ? p.rebuilderOwnerId : p.winnerOwnerId;
              const direction =
                p.winnerOwnerId === myOwnerId
                  ? "buy older star talent from"
                  : "sell veterans to";
              return (
                <li key={otherId} style={{ marginBottom: 2 }}>
                  {direction}{" "}
                  <Link
                    href={`/league/franchise/${encodeURIComponent(otherId)}`}
                    style={{ color: "var(--cyan)" }}
                  >
                    {otherName}
                  </Link>
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </div>
  );
}
