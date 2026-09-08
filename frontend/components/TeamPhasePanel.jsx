"use client";

import { useMemo } from "react";
import Link from "next/link";
import { Badge, DataTable, Panel } from "@/components/ds";
import { FailureState } from "@/components/ds/FailureState";
import { EmptyState, LoadingState } from "@/components/ui";
import { useRosterIntelligence } from "@/components/useRosterIntelligence";
import { useUserState } from "@/components/useUserState";
import { teamStrengthLadder } from "@/lib/roster-intelligence";
import { analyzeLeaguePhases } from "@/lib/team-phase";

// Semantic signal tokens (--positive/--warning/--negative), not the
// legacy --green/--amber/--red hex triplet — those are a SEPARATE,
// uncalibrated color system (globals.css) from the CVD-validated
// market-semantic tokens ds/Badge's Movement/StatusIndicator already
// use everywhere else. Same up/warn/down meaning, one signal palette.
const TONE_COLOR = {
  up: "var(--positive)",
  warn: "var(--warning)",
  down: "var(--negative)",
};
const TONE_BADGE = {
  up: "positive",
  warn: "warning",
  down: "negative",
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

  const columns = [
    {
      key: "name",
      header: "Team",
      sortable: true,
      accessor: (t) => t.name,
      render: (t) => {
        const isMe = myOwnerId && t.ownerId === myOwnerId;
        return (
          <span style={{ fontWeight: isMe ? 700 : 500 }}>
            {t.ownerId ? (
              <Link
                href={`/league/franchise/${encodeURIComponent(t.ownerId)}`}
                style={{ color: "var(--accent)", textDecoration: "none" }}
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
          </span>
        );
      },
    },
    {
      key: "phase",
      header: "Phase",
      sortable: true,
      accessor: (t) => t.phase.label,
      render: (t) => <Badge tone={TONE_BADGE[t.phase.tone] || "neutral"}>{t.phase.label}</Badge>,
    },
    {
      key: "totalValue",
      header: "Team Strength",
      numeric: true,
      sortable: true,
      accessor: (t) => t.totalValue,
      render: (t) => fmtValue(t.totalValue),
    },
    {
      key: "medianAge",
      header: "Core age",
      numeric: true,
      sortable: true,
      accessor: (t) => t.medianAge,
      render: (t) => fmtAge(t.medianAge),
    },
  ];

  return (
    <Panel
      title="Win-now vs Rebuild"
      subtitle={`Each team classified by Team Strength (meaningful core) × value-weighted core age, against the league medians (${fmtValue(analysis.leagueMedians.value)} strength · ${fmtAge(analysis.leagueMedians.age)} age).`}
    >
      {myRow && (
        <div
          style={{
            padding: "var(--space-3)",
            borderRadius: "var(--radius-2)",
            border: "1px solid var(--border-default)",
            marginBottom: "var(--space-3)",
          }}
        >
          <div style={{ fontSize: "0.74rem", color: "var(--text-tertiary)" }}>You are:</div>
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

      <DataTable
        columns={columns}
        rows={analysis.teams}
        rowKey={(t) => t.ownerId || t.name}
        caption="League teams classified by Team Strength and value-weighted core age into win-now vs. rebuild phases."
        density="compact"
        defaultSort={{ key: "totalValue", direction: "desc" }}
      />

      {myPartnerships.length > 0 && (
        <div style={{ marginTop: "var(--space-3)" }}>
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
                    style={{ color: "var(--accent)" }}
                  >
                    {otherName}
                  </Link>
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </Panel>
  );
}
