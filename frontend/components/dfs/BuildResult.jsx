"use client";

/**
 * BuildResult — a finished build: status, disclosures, each lineup (with its
 * outcome range), player exposure, the portfolio summary and the export /
 * entry-file actions.  Split out of the /dfs page chunk (React.lazy): it only
 * renders after a build, and the page chunk has a hard budget.  Display only.
 */

import React, { Suspense, lazy, useState } from "react";
import { Banner, Button, DataTable, StatusIndicator } from "@/components/ds";
import { errorMessage, formatPoints, formatSalary, statusCopy, statusTone } from "@/lib/dfs";
import styles from "./dfs-workspace.module.css";

const EntriesExport = lazy(() => import("./EntriesExport"));
const PortfolioSummary = lazy(() => import("./PortfolioSummary"));
const ContestModel = lazy(() => import("./ContestModel"));

function LineupTable({ lineup, cap }) {
  const columns = [
    { key: "slot", header: "Slot", sortable: false },
    { key: "name", header: "Player", sortable: false },
    { key: "team", header: "Team", sortable: false, hideBelow: "sm", render: (p) => `${p.team}${p.opponent ? ` v ${p.opponent}` : ""}` },
    { key: "salary", header: "Salary", numeric: true, sortable: false, render: (p) => formatSalary(p.salary) },
    {
      key: "projection",
      header: "Proj",
      numeric: true,
      sortable: false,
      // The slot's multiplier (Showdown captain 1.5×) is shown, never hidden in the number.
      render: (p) => {
        const base = p.ownerOverride != null ? p.ownerOverride : p.projection;
        const shown =
          p.slotMultiplier && p.slotMultiplier !== 1
            ? `${formatPoints(p.slotProjection)} (${formatPoints(base)} × ${p.slotMultiplier})`
            : formatPoints(p.slotProjection ?? p.projection);
        return p.ownerOverride != null ? `${shown} · yours` : shown;
      },
    },
  ];
  return (
    <div className={styles.lineup}>
      <DataTable
        caption={`Lineup ${lineup.index}: ${formatPoints(lineup.projection)} projected points, ${formatSalary(lineup.salary)} of ${formatSalary(cap)}`}
        columns={columns}
        rows={lineup.players}
        rowKey={(p) => `${p.slot}-${p.playerId}`}
        density="compact"
      />
      {lineup.outcome?.state === "available" ? (
        <p className={styles.note}>
          Likely range {formatPoints(lineup.outcome.p10)}–{formatPoints(lineup.outcome.p90)} points (p10–p90, from your
          imported ranges; players treated as independent, so stacks swing more).
        </p>
      ) : null}
      <p className={styles.lineupTotals}>
        <span>
          Projected <strong className="ds-mono">{formatPoints(lineup.projection)}</strong>
        </span>
        <span>
          Salary <strong className="ds-mono">{formatSalary(lineup.salary)}</strong>
        </span>
        <span>
          Remaining <strong className="ds-mono">{formatSalary(lineup.salaryRemaining)}</strong>
        </span>
      </p>
    </div>
  );
}

/**
 * Fetch-then-save, not a bare <a download>: an export can be refused at
 * export time (rule set superseded, lineup no longer valid), and a plain
 * link would save that JSON refusal as if it were the CSV.
 */
function ExportButton({ buildId }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const onClick = async () => {
    setBusy(true);
    setError(null);
    try {
      const res = await fetch(`/api/dfs/builds/${buildId}/export`, { credentials: "same-origin", cache: "no-store" });
      if (!res.ok) {
        let body = null;
        try {
          body = await res.json();
        } catch {
          body = null;
        }
        setError(errorMessage(body, "Export refused."));
        return;
      }
      const blob = await res.blob();
      const disposition = res.headers.get("content-disposition") || "";
      const name = /filename="([^"]+)"/.exec(disposition)?.[1] || `${buildId}.csv`;
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = name;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch {
      setError("The export could not be downloaded.");
    } finally {
      setBusy(false);
    }
  };
  return (
    <>
      <Button variant="primary" onClick={onClick} loading={busy}>
        Download upload CSV
      </Button>
      {error ? (
        <Banner tone="negative" title="Export refused">
          {error}
        </Banner>
      ) : null}
    </>
  );
}

export default function BuildResult({ build, ruleset, athletes }) {
  const r = build.result;
  const conflict = r.shortfall?.conflict;
  return (
    <div className={styles.result}>
      <div className={styles.resultHead}>
        <StatusIndicator status={statusTone(r.status)}>
          {r.status.replaceAll("_", " ")} · {r.built} of {r.requested}
        </StatusIndicator>
        {build.researchOnly ? <StatusIndicator status="warning">Research only</StatusIndicator> : null}
        <span className={styles.meta}>
          Highest projected points · not contest-evaluated · {build.solver} · {r.elapsedMs} ms
        </span>
      </div>
      <p className={styles.note}>{statusCopy(r.status, r.built)}</p>
      {build.disclosures?.length ? (
        <Banner tone="info" title={build.contest ? `Built for: ${build.contest.name}` : build.preset ? `Built for: ${build.preset.label}` : "What this build is"}>
          <ul className={styles.list}>
            {build.disclosures.map((d) => (
              <li key={d}>{d}</li>
            ))}
          </ul>
        </Banner>
      ) : null}
      {r.built > 1 ? <p className={styles.note}>{build.methodNote}</p> : null}
      {r.shortfall ? (
        <Banner
          tone={r.built ? "warning" : "negative"}
          title={r.built ? `${r.shortfall.missing} lineup(s) short` : "No lineup could be built"}
        >
          {conflict?.described?.length ? (
            <>
              <p>These of your constraints cannot all hold together with the official rules:</p>
              <ul className={styles.list}>
                {conflict.described.map((d) => (
                  <li key={d}>{d}</li>
                ))}
              </ul>
              <p>Nothing was relaxed. Remove or loosen one of them and build again.</p>
            </>
          ) : conflict?.message ? (
            <p>{conflict.message}</p>
          ) : (
            <p>Reason: {String(r.shortfall.reason || "unknown").replaceAll("_", " ")}.</p>
          )}
        </Banner>
      ) : null}
      {r.minimumExposureUnmet?.length ? (
        <Banner tone="warning" title="Minimum exposure not reached">
          <ul className={styles.list}>
            {r.minimumExposureUnmet.map((u) => (
              <li key={u.playerId}>
                {u.name}: in {u.count} of the built lineups, minimum {u.min} of {r.requested}.
              </li>
            ))}
          </ul>
        </Banner>
      ) : null}
      {r.excludedUnprojected?.length ? (
        <p className={styles.note}>
          {r.excludedUnprojected.length} player(s) without a projection were left out — missing is never scored as
          zero.
        </p>
      ) : null}
      {r.lineups.map((lu) => (
        <LineupTable key={lu.index} lineup={lu} cap={ruleset?.salaryCap} />
      ))}
      {r.built > 1 ? (
        <DataTable
          caption="Player exposure across the built lineups"
          columns={[
            { key: "name", header: "Player" },
            { key: "count", header: "Lineups", numeric: true },
            { key: "share", header: "Share", numeric: true, render: (x) => `${Math.round((x.share || 0) * 100)}%` },
            { key: "min", header: "Min", numeric: true, render: (x) => (x.min == null ? "—" : x.min) },
            { key: "cap", header: "Cap", numeric: true, render: (x) => (x.cap == null ? "—" : x.cap) },
          ]}
          rows={r.exposure}
          rowKey={(x) => x.playerId}
          density="compact"
          defaultSort={{ key: "count", direction: "desc" }}
        />
      ) : null}
      {r.portfolio ? (
        <Suspense fallback={null}>
          <PortfolioSummary portfolio={r.portfolio} />
        </Suspense>
      ) : null}
      {r.built ? (
        <Suspense fallback={null}>
          <ContestModel build={build} snapshotId={build.snapshot?.id} athletes={athletes} />
        </Suspense>
      ) : null}
      {r.built ? (
        <div className={styles.exportRow}>
          <ExportButton buildId={build.buildId} />
          <p className={styles.note}>
            {build.ruleset.exportVerification === "verified"
              ? "Format verified against the platform template."
              : "Upload format not yet verified against an official platform template — check it before uploading."}{" "}
            Downloading submits nothing; you upload it yourself.
          </p>
        </div>
      ) : null}
      {r.built && build.ruleset?.key?.startsWith("draftkings.") ? (
        <Suspense fallback={null}>
          <EntriesExport buildId={build.buildId} />
        </Suspense>
      ) : null}
      <details className={styles.provenance}>
        <summary>Provenance and limits</summary>
        <dl className={styles.facts}>
          <div>
            <dt>Build</dt>
            <dd className="ds-mono">{build.buildId}</dd>
          </div>
          <div>
            <dt>Rule set</dt>
            <dd className="ds-mono">{build.ruleset.key}</dd>
          </div>
          <div>
            <dt>Snapshot</dt>
            <dd className="ds-mono" title={build.snapshot.contentHash}>
              {build.snapshot.contentHash.slice(0, 12)}
            </dd>
          </div>
          <div>
            <dt>Constraints</dt>
            <dd className="ds-mono">{build.constraintsHash.slice(0, 12)}</dd>
          </div>
          <div>
            <dt>Built</dt>
            <dd className="ds-mono">{new Date(build.createdAt).toLocaleString()}</dd>
          </div>
        </dl>
        <ul className={styles.list}>
          {build.limits.map((l) => (
            <li key={l}>{l}</li>
          ))}
        </ul>
      </details>
    </div>
  );
}
