/**
 * DataInfoBody — the content of Game Day section 5 (the collapsed "Data
 * info" panel): where every number above came from, in the backend's own
 * lineage. Loaded on first open (see DataInfo.jsx).
 *
 *   projections   lineage.weeklyProjection (sourceLabel, state, asOf,
 *                 observedAt), projectionBasisCounts + projectionBasisLabels,
 *                 projectionFamiliesContributing — "1 projection family",
 *                 never "ensemble" when only one family contributes;
 *                 preseasonProjectionSource named as the FALLBACK it is
 *   live state    lineage.liveGameState + gameStateLimitation
 *   scoring       side.uncoveredScoringKeys (no projection covers them) and
 *                 players' imputedScoringKeys (OUR estimate, labelled so)
 *   method        remainingProductionMethod, leverageDefinition
 *   simulation    lineage.simulation (modelVersion, draws, computed at)
 *   freshness     payload.freshness (U5 collector): state + every reason,
 *                 as-of / age / stale budget, generation, refresh running,
 *                 and one row per source {status, fetchedAt, observedAt
 *                 (+ basis), ageSeconds} — a failed source is shown failed
 */

import { DataTable } from "@/components/ds";
import { formatAge, formatDateTime, freshnessReasonText } from "@/lib/game-day-view";
import styles from "./game-day.module.css";


const FRESHNESS_LABEL = {
  current: "Current",
  partial: "Partial",
  degraded: "Degraded",
  stale: "Stale",
};

const SERVED_FROM = {
  collector_generation: "Shared live collector (cached generation)",
  request_compute: "Computed on request (no collector generation)",
};

const SOURCE_LABEL = {
  espnScoreboard: "ESPN scoreboard (quarter / clock / status)",
  sleeperLeague: "Sleeper league, rosters, matchups",
  sleeperLiveStats: "Sleeper live stat lines",
  weeklyProjections: "Weekly projections (RotoWire via Sleeper)",
  nflverseSchedule: "NFL schedule (nflverse cache)",
  preseasonProjection: "Preseason projection (fallback)",
};

const BASIS_LABEL = {
  fetch_time: "fetch time",
  provider_updated_at: "provider's update time",
  cache_write_time: "cache write time",
};

function SourceTable({ sources }) {
  const rows = Object.entries(sources || {}).map(([key, src]) => ({ key, ...src }));
  if (!rows.length) return "No per-source detail reported.";
  return (
    <DataTable
      caption="Game Day data sources and their freshness"
      rowKey="key"
      density="compact"
      rows={rows}
      columns={[
        { key: "source", header: "Source", render: (r) => SOURCE_LABEL[r.key] || r.source || r.key },
        {
          key: "status",
          header: "Status",
          render: (r) => (
            <span className={r.status === "ok" ? undefined : styles.unverified}>
              {r.status || "unknown"}
              {r.error ? ` (${r.error})` : r.reason ? ` (${r.reason})` : ""}
            </span>
          ),
        },
        {
          key: "observed",
          header: "Observed",
          render: (r) =>
            r.observedAt
              ? `${formatDateTime(r.observedAt)}${r.observedAtBasis ? ` · ${BASIS_LABEL[r.observedAtBasis] || r.observedAtBasis}` : ""}`
              : "—",
        },
        {
          key: "age",
          header: "Age",
          numeric: true,
          render: (r) => formatAge(r.ageSeconds) ?? "—",
        },
      ]}
    />
  );
}

function familiesText(n) {
  if (typeof n !== "number") return "Unknown";
  if (n === 0) return "No weekly projection family contributed";
  if (n === 1) return "1 projection family";
  return `${n} independent projection families, averaged with equal weight`;
}

function liveStateText(live) {
  if (!live) return "Not reported";
  const at = formatDateTime(live.observedAt);
  switch (live.state) {
    case "observed":
      return `ESPN scoreboard observed${at ? ` ${at}` : ""}${live.stale ? " — STALE (older than the freshness budget)" : ""}`;
    case "disabled":
      return "Live game feed switched off — game status comes from the schedule only";
    case "week_mismatch":
      return `Live feed described a different week (${live.reason || "reason not given"})`;
    default:
      return `Live game feed unavailable${live.reason ? ` (${live.reason})` : ""}`;
  }
}

function union(players, key) {
  const out = new Set();
  for (const p of players || []) for (const k of p?.[key] || []) out.add(k);
  return [...out].sort();
}

export default function DataInfoBody({ payload }) {
  if (!payload) return null;
  const lineage = payload.lineage || {};
  const weekly = lineage.weeklyProjection || {};
  const sim = lineage.simulation;
  const cov = lineage.estimateCoverage || {};
  const labels = lineage.projectionBasisLabels || {};
  const counts = lineage.projectionBasisCounts || {};
  const allPlayers = [...(payload.team?.players || []), ...(payload.opponent?.players || [])];
  const imputed = union(allPlayers, "imputedScoringKeys");
  const imputedPlayers = allPlayers.filter((p) => (p.imputedScoringKeys || []).length).length;
  const uncovered = [
    ...new Set([
      ...(payload.team?.uncoveredScoringKeys || []),
      ...(payload.opponent?.uncoveredScoringKeys || []),
    ]),
  ].sort();
  const freshness = payload.freshness && typeof payload.freshness === "object" ? payload.freshness : null;
  const archive = lineage.archive;

  return (
    <dl className={styles.facts}>
      <dt>Weekly projections</dt>
      <dd>
        {weekly.sourceLabel || "Weekly source"} —{" "}
        {weekly.state === "ok"
          ? `as of ${formatDateTime(weekly.asOf) || "time not stated"}, fetched ${formatDateTime(weekly.observedAt) || "time not stated"}; each player's line is locked at his game's kickoff`
          : `not in use (${weekly.state || "unknown"}${weekly.reason ? `: ${weekly.reason}` : ""})`}
      </dd>

      <dt>Projection families</dt>
      <dd>{familiesText(lineage.projectionFamiliesContributing)}</dd>

      <dt>Projection basis</dt>
      <dd>
        {Object.keys(counts).length ? (
          <ul className={styles.factList}>
            {Object.entries(counts).map(([basis, n]) => (
              <li key={basis}>
                {labels[basis] || basis}: {n} player{n === 1 ? "" : "s"}
              </li>
            ))}
          </ul>
        ) : (
          "No player has a projection"
        )}
        {lineage.preseasonProjectionSource ? (
          <span className={styles.muted}>
            {" "}
            Fallback source: {lineage.preseasonProjectionSource} (preseason full-season average,
            not a current-week forecast).
          </span>
        ) : null}
      </dd>

      <dt>Coverage</dt>
      <dd>
        {cov.priced ?? "—"} of {cov.active ?? "—"} active players in the league have a projection
      </dd>

      <dt>Live game state</dt>
      <dd>
        {liveStateText(lineage.liveGameState)}
        {lineage.gameStateLimitation ? (
          <span className={styles.numNote}>{lineage.gameStateLimitation}</span>
        ) : null}
      </dd>

      <dt>Scoring coverage</dt>
      <dd>
        {uncovered.length
          ? `No projection covers these league scoring categories: ${uncovered.join(", ")}.`
          : "Every scoring category this league pays is covered by a projection."}
        {imputed.length
          ? ` Our estimate (not the provider's) fills ${imputed.join(", ")} for ${imputedPlayers} player${imputedPlayers === 1 ? "" : "s"}.`
          : ""}
      </dd>

      <dt>Remaining production</dt>
      <dd>{lineage.remainingProductionMethod || "Not stated"}</dd>

      <dt>Key-game definition</dt>
      <dd>{lineage.leverageDefinition || "Not stated"}</dd>

      <dt>Simulation</dt>
      <dd>
        {sim
          ? `${sim.modelVersion} · ${sim.draws} draws · computed ${formatDateTime(sim.cacheComputedAt) || "time not stated"}${
              sim.thresholdSemanticsVerified === false
                ? ` · median threshold "${sim.thresholdSemantics}" not verified against the host`
                : ""
            }`
          : "Not run for this view"}
      </dd>

      <dt>League rules</dt>
      <dd>
        {lineage.bestBall ? "Best ball" : "Managed lineups"} ·{" "}
        {lineage.medianEnabled === true
          ? "median game on"
          : lineage.medianEnabled === false
            ? "median game off"
            : "median game unverified"}
        {lineage.teamCount ? ` · ${lineage.teamCount} teams` : ""}
      </dd>

      <dt>Host data fetched</dt>
      <dd>{formatDateTime(lineage.sleeperFetchedAt) || "Time not stated"}</dd>

      {freshness ? (
        <>
          <dt>Freshness</dt>
          <dd data-freshness-state={freshness.state}>
            <strong>{FRESHNESS_LABEL[freshness.state] || freshness.state || "Unknown"}</strong>
            {" · "}
            {freshness.asOf ? `as of ${formatDateTime(freshness.asOf)}` : "as-of time unknown"}
            {typeof freshness.payloadAgeSeconds === "number"
              ? ` · ${formatAge(freshness.payloadAgeSeconds)} old when served`
              : ""}
            {typeof freshness.staleAfterSeconds === "number"
              ? ` · stale after ${formatAge(freshness.staleAfterSeconds)} (${freshness.phase || "phase unknown"} phase)`
              : ""}
            {freshness.refreshInProgress
              ? ` · refresh running since ${formatDateTime(freshness.refreshStartedAt) || "an unknown time"}`
              : ""}
            {(freshness.reasons || []).length ? (
              <ul className={styles.factList}>
                {freshness.reasons.map((r) => (
                  <li key={r}>{freshnessReasonText(r)}</li>
                ))}
              </ul>
            ) : null}
          </dd>

          <dt>Served from</dt>
          <dd>
            {SERVED_FROM[freshness.servedFrom] || freshness.servedFrom || "Not stated"}
            {freshness.generationId ? (
              <span className={styles.numNote}>Generation {freshness.generationId}</span>
            ) : null}
            <span className={styles.numNote}>
              Inputs computed {formatDateTime(freshness.generationComputedAt) || "time not stated"} ·
              simulation {formatDateTime(freshness.simulationComputedAt) || "not run"}
            </span>
          </dd>

          <dt>Sources</dt>
          <dd>
            <div className={styles.wrapTable}>
              <SourceTable sources={freshness.sources} />
            </div>
          </dd>
        </>
      ) : (
        <>
          <dt>Freshness</dt>
          <dd>Not reported by this server — the collector freshness block is absent.</dd>
        </>
      )}

      <dt>Pregame archive</dt>
      <dd>
        {archive?.state === "captured"
          ? `Captured ${formatDateTime(archive.capturedAt) || archive.capturedAt} for ${archive.teamsCaptured} team${archive.teamsCaptured === 1 ? "" : "s"}`
          : archive?.state === "unreadable"
            ? `Could not be read (${archive.reason}) — not the same as nothing captured`
            : "Nothing archived for this week yet"}
      </dd>

      {payload.notes?.length ? (
        <>
          <dt>Notes</dt>
          <dd>
            <ul className={styles.factList}>
              {payload.notes.map((n) => (
                <li key={n}>{n}</li>
              ))}
            </ul>
          </dd>
        </>
      ) : null}
    </dl>
  );
}
