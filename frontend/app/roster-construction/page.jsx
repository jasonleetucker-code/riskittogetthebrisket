"use client";

// ── /roster-construction — Roster Construction V1 ────────────────────────
//
// Owner directive 2026-10-30 (flag `roster_construction`, default OFF).  Pick
// any team in a dynasty league and read how its roster actually produces, what
// dynasty value it holds, and where the two disagree.  DISPLAY ONLY: every
// number comes from GET /api/roster-construction
// (src/api/roster_construction_api.py), which composes the exact lineup
// solver.  This file formats that payload and computes no points, rank, value,
// lineup or legality (the no-frontend-engine rule).
//
// GATED: the page renders nothing but "not available" unless the backend
// serves the route (flag off -> 503 feature_disabled).  It is linked from
// nowhere (not in lib/nav-model.js) and is a private page (absent from
// lib/public-routes.js, so frontend/middleware.js's auth gate covers it).
//
// Reports and explains.  Never submits, schedules or recommends a transaction.

import { lazy, Suspense, useEffect, useState } from "react";
import {
  EmptyState,
  FailureState,
  Field,
  PageHeader,
  Panel,
  Select,
  SkeletonTable,
} from "@/components/ds";
import { useLeague } from "@/components/useLeague";
import { useRosterConstructionGate } from "@/components/roster-construction/useRosterConstructionGate";
import styles from "./roster-construction.module.css";

// The whole analysis body is its own lazy chunk, so while the flag is off (or
// no team is picked) it costs this page nothing.
const RosterConstructionPanel = lazy(
  () => import("@/components/roster-construction/RosterConstructionPanel"),
);

function NotAvailable() {
  return (
    <div
      className={`main-shell ${styles.page}`}
      data-testid="roster-construction-unavailable"
    >
      <EmptyState title="This page is not available." />
    </div>
  );
}

// The gate probe's failure arrives as a raw {status, body}; classify it here
// without importing lib/roster-construction (that module stays lazy).
function probeFailure(f) {
  const code = f?.body && typeof f.body === "object" ? String(f.body.error || "") : "";
  const status = Number(f?.status) || 0;
  if (status === 401) {
    return { kind: "auth", code, message: "Sign in to use Roster Construction." };
  }
  if (status === 0) {
    return { kind: "offline", message: "Couldn't reach Roster Construction." };
  }
  const reason = f?.body && typeof f.body === "object" ? f.body.reason : null;
  const base =
    code === "data_not_ready"
      ? "The league data for this view is not ready yet."
      : code
        ? `Unavailable (${code}).`
        : "Unavailable.";
  const message = reason
    ? `${base.replace(/\.$/, "")} — ${String(reason).replace(/_/g, " ")}.`
    : base;
  return { kind: status >= 500 ? "unavailable" : "degraded", code, message };
}

export default function RosterConstructionPage() {
  const { leagues, selectedLeagueKey, setLeague, loading: leaguesLoading } =
    useLeague();
  const leagueKey = selectedLeagueKey || "";
  const [season, setSeason] = useState("");
  const [rosterId, setRosterId] = useState("");
  const { gate, overview, failure } = useRosterConstructionGate({
    leagueKey,
    season,
  });

  // A team id belongs to one league's roster history; never carry it across.
  useEffect(() => {
    setRosterId("");
    setSeason("");
  }, [leagueKey]);

  if (gate === "closed") return <NotAvailable />;
  if (!leaguesLoading && !leagueKey) {
    return (
      <div className={`main-shell ${styles.page}`}>
        <EmptyState
          title="No league configured"
          description="Roster Construction needs an active dynasty league."
        />
      </div>
    );
  }
  if (gate === "unknown") {
    return (
      <div className={`main-shell ${styles.page}`} aria-busy="true">
        <SkeletonTable rows={8} columns={5} />
      </div>
    );
  }

  const teams = Array.isArray(overview?.teams) ? overview.teams : [];
  const seasons = Array.isArray(overview?.availableSeasons)
    ? overview.availableSeasons.map(String)
    : [];
  const team = teams.find((t) => String(t.rosterId) === String(rosterId));

  return (
    <div
      className={`main-shell ${styles.page} psi-editorial`}
      data-testid="roster-construction"
    >
      <PageHeader
        eyebrow="Intel"
        title="Roster Construction"
        description="How a team's roster actually produces, what dynasty value it holds at each position, and where the two disagree. Evidence only; nothing here recommends a trade."
      />

      <Panel dense>
        <div className={styles.controls}>
          {leagues.length > 1 ? (
            <Field label="League" id="rc-league">
              <Select
                id="rc-league"
                value={leagueKey}
                onChange={(e) => setLeague(e.target.value)}
              >
                {leagues.map((l) => (
                  <option key={l.key} value={l.key}>
                    {l.displayName || l.key}
                  </option>
                ))}
              </Select>
            </Field>
          ) : null}
          {teams.length ? (
            <Field label="Team" id="rc-team">
              <Select
                id="rc-team"
                value={rosterId}
                onChange={(e) => setRosterId(e.target.value)}
              >
                <option value="">Pick a team</option>
                {teams.map((t) => (
                  <option key={t.rosterId} value={String(t.rosterId)}>
                    {t.label || t.managerLabel || `Roster ${t.rosterId}`}
                  </option>
                ))}
              </Select>
            </Field>
          ) : null}
          {seasons.length > 1 ? (
            <Field label="Season" id="rc-season">
              <Select
                id="rc-season"
                value={season || String(overview?.season || "")}
                onChange={(e) => setSeason(e.target.value)}
              >
                {seasons.map((s) => (
                  <option key={s} value={s}>
                    {s}
                  </option>
                ))}
              </Select>
            </Field>
          ) : null}
        </div>
      </Panel>

      {failure ? (
        <FailureState failure={probeFailure(failure)} context="Roster Construction" />
      ) : null}

      {!failure && !teams.length ? (
        <EmptyState
          title="No teams to choose from"
          description="The backend did not return a team list for this league."
        />
      ) : null}

      {teams.length ? (
        <Suspense fallback={<SkeletonTable rows={8} columns={6} />}>
          <RosterConstructionPanel
            leagueKey={leagueKey}
            rosterId={rosterId}
            season={season || undefined}
            validWeeks={team?.validWeeks}
          />
        </Suspense>
      ) : null}
    </div>
  );
}
