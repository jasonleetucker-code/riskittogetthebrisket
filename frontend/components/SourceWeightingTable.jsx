"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  Badge,
  DataTable,
  FailureState,
  InfoTip,
  Panel,
  SkeletonTable,
  StatusIndicator,
} from "@/components/ds";
import { classifyContractFailure } from "@/lib/contract-failure";
import { RANKING_SOURCES } from "@/lib/dynasty-data";
import {
  formatFactor,
  formatHours,
  stateStatus,
  stateSummary,
  weightingRows,
} from "@/lib/source-weighting";

/**
 * SourceWeightingTable — the freshness VERDICT per source, from the backend.
 *
 * Reads GET /api/sources/weighting (src/api/source_weighting_explain.py),
 * which arranges what the canonical pipeline already stamped: each source's
 * content age against its OWN expected cadence, the freshness factor that
 * produces, health, coverage, and the base → effective weight the blend
 * actually applied.  Nothing here recomputes a factor or picks an age
 * threshold — the status column is the backend's `state`.
 *
 * Why it exists: the Source Health page only showed FETCH recency with fixed
 * 4h/12h bands.  A fetch that succeeds against a vendor that has not
 * published in weeks looks green there, and a source the pipeline has
 * quarantined (freshness below its cutoff, so it casts no vote) was
 * invisible.  This table shows both.
 */

const LABELS = Object.fromEntries(
  (RANKING_SOURCES || []).map((s) => [s.key, s.displayName || s.columnLabel || s.key]),
);
// Not a registered voter, so not in RANKING_SOURCES.
LABELS.ktcCrowdTradesSfTep = LABELS.ktcCrowdTradesSfTep || "KeepTradeCut Market (benchmark)";

async function fetchWeighting() {
  try {
    const res = await fetch("/api/sources/weighting", {
      credentials: "same-origin",
      headers: { "Cache-Control": "no-store" },
    });
    const body = await res.json().catch(() => null);
    if (!res.ok) return { data: null, failure: classifyContractFailure(res.status, body) };
    return { data: body, failure: null };
  } catch (err) {
    return {
      data: null,
      failure: classifyContractFailure(null, { message: err?.message }),
    };
  }
}

const COLUMNS = [
  {
    key: "label",
    header: "Source",
    sortable: true,
    // Long vendor names wrap so the state column stays on screen at phone
    // width (DataTable cells do not wrap by default).
    render: (r) => (
      <span style={{ whiteSpace: "normal", display: "inline-block", minWidth: "9rem" }}>
        {r.label}
        {r.subset && r.subset !== "players" ? (
          <span className="muted"> · {r.subset}</span>
        ) : null}{" "}
        {r.isBenchmark ? <Badge tone="outline">benchmark</Badge> : null}
      </span>
    ),
  },
  {
    key: "state",
    header: "Freshness state",
    sortable: true,
    sortAccessor: (r) => r.stateRank,
    render: (r) => {
      const s = stateStatus(r.state);
      return <StatusIndicator status={s.status}>{s.label}</StatusIndicator>;
    },
    headerInfo:
      "The pipeline's own verdict: content age measured against this source's expected publishing cadence. Quarantined sources cast no vote.",
  },
  {
    key: "contentHours",
    header: "Content age",
    numeric: true,
    sortable: true,
    render: (r) => (
      <span>
        {formatHours(r.contentHours)}
        <span className="muted"> / {formatHours(r.expectedHours)}</span>
      </span>
    ),
    headerInfo:
      "Time since the source's content last changed, against the cadence it is expected to publish on. Fetching a page that has not changed does not make it fresh.",
  },
  {
    key: "fetchedHours",
    header: "Fetched",
    numeric: true,
    sortable: true,
    hideBelow: "md",
    render: (r) => formatHours(r.fetchedHours),
    headerInfo: "Time since our last successful fetch — a separate clock from content age.",
  },
  {
    key: "freshness",
    header: "Freshness",
    numeric: true,
    sortable: true,
    hideBelow: "sm",
    render: (r) => formatFactor(r.freshness),
  },
  {
    key: "coverageFactor",
    header: "Coverage",
    numeric: true,
    sortable: true,
    hideBelow: "lg",
    render: (r) => formatFactor(r.coverageFactor),
  },
  {
    key: "effectiveWeight",
    header: "Weight",
    numeric: true,
    sortable: true,
    hideBelow: "sm",
    render: (r) =>
      r.isBenchmark ? (
        <span className="muted">no vote</span>
      ) : (
        <span>
          {formatFactor(r.effectiveWeight)}
          <span className="muted"> / {formatFactor(r.baseWeight)}</span>
        </span>
      ),
    headerInfo:
      "Effective / base weight: base × freshness × health × coverage. Family caps then limit correlated sources to one provider's authority.",
  },
  {
    key: "votingRows",
    header: "Rows voting",
    numeric: true,
    sortable: true,
    hideBelow: "md",
    render: (r) => (r.votingRows == null ? "—" : r.votingRows.toLocaleString()),
  },
];

export default function SourceWeightingTable() {
  const [state, setState] = useState({ loading: true, data: null, failure: null });

  const load = useCallback(async () => {
    setState((s) => ({ ...s, loading: true }));
    const out = await fetchWeighting();
    setState({ loading: false, ...out });
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const rows = useMemo(() => weightingRows(state.data, { labels: LABELS }), [state.data]);
  const summary = useMemo(() => stateSummary(rows), [rows]);

  return (
    <Panel
      title="Freshness and weighting"
      headingLevel={2}
      subtitle="Each source's content freshness against its own publishing cadence, and the weight the blend actually gave it."
    >
      {state.loading && !state.data ? <SkeletonTable rows={8} /> : null}
      {state.failure ? (
        <FailureState failure={state.failure} onRetry={load} context="source weighting" />
      ) : null}
      {state.data ? (
        <>
          <p className="muted" data-testid="source-weighting-summary" style={{ marginBottom: 8 }}>
            {summary.map((s, i) => (
              <span key={s.state}>
                {i ? " · " : ""}
                <strong>{s.count}</strong> {s.label.toLowerCase()}
              </span>
            ))}
            {state.data.asOf ? <> · board as of {state.data.asOf}</> : null}
          </p>
          <DataTable
            columns={COLUMNS}
            rows={rows}
            rowKey="id"
            caption="Per-source freshness state, content age, fetch age, freshness factor, coverage and applied weight"
            density="compact"
            defaultSort={{ key: "state", direction: "asc" }}
            emptyState={<p className="muted">The loaded board publishes no source weighting.</p>}
          />
          <p className="muted" style={{ marginTop: 10, fontSize: "0.72rem" }}>
            {state.data.formula || "effective = base × freshness × health × coverage"}
            {state.data.configVersion ? ` · config ${state.data.configVersion}` : ""}
            {state.data.curve ? ` · curve ${state.data.curve}` : ""}
            {state.data.applied === false ? " · freshness weighting is switched OFF (diagnostic only)" : ""}
            <InfoTip label="per-player breakdowns">
              <p>
                To see how these sources combine for one player — each source&apos;s raw and
                normalised value, its age, weight and contribution — open the player&apos;s file
                from the <Link href="/rankings">rankings board</Link> and expand the value
                explanation.
              </p>
            </InfoTip>
          </p>
        </>
      ) : null}
    </Panel>
  );
}
