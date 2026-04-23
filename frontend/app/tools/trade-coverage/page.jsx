"use client";

import { useEffect, useMemo, useState } from "react";
import { useApp } from "@/components/AppShell";
import { useTeam } from "@/components/useTeam";
import { PageHeader, LoadingState, EmptyState } from "@/components/ui";

/**
 * Trade Coverage Audit — internal diagnostic view.
 *
 * For every Sleeper team in the live contract, hit /api/terminal
 * with their ownerId and surface:
 *
 *   - The raw ``delta{7,30,90,180}dDetail`` block per team, showing
 *     ``rosterAware`` / ``tradesSeen`` / ``tradesApplied`` / ``reason``
 *     / ``coverageFraction``
 *   - An aggregate row (counts of teams at each coverage/roster-aware
 *     state) so gaps in the Sleeper trade feed show up at a glance
 *
 * Useful when debugging why a team's Δ30d came back null or why the
 * rosterAware flag didn't trip: you can see which teams had trades
 * in the window and which didn't, at a glance.
 *
 * Auth-gated implicitly — an anonymous terminal fetch returns the
 * public slice with no team aggregates, so we show an empty state
 * when the first fetch comes back ``authenticated: false``.
 */

async function fetchTerminalFor(ownerId, windowDays = 180) {
  const params = new URLSearchParams();
  params.set("team", ownerId);
  params.set("windowDays", String(windowDays));
  const res = await fetch(`/api/terminal?${params.toString()}`, {
    credentials: "same-origin",
    headers: { "Cache-Control": "no-store" },
  });
  if (!res.ok && res.status !== 503) throw new Error(`${res.status}`);
  return res.json();
}

export default function TradeCoveragePage() {
  const { rawData, loading: appLoading } = useApp();
  const { availableTeams, loading: teamLoading } = useTeam();

  const [perTeam, setPerTeam] = useState({});
  const [progress, setProgress] = useState({ done: 0, total: 0 });
  const [authOk, setAuthOk] = useState(true);

  useEffect(() => {
    if (appLoading || teamLoading) return;
    if (!availableTeams || availableTeams.length === 0) return;

    let cancelled = false;

    async function run() {
      setProgress({ done: 0, total: availableTeams.length });
      for (const team of availableTeams) {
        if (cancelled) return;
        const ownerId = String(team.ownerId || "");
        if (!ownerId) continue;
        try {
          const payload = await fetchTerminalFor(ownerId, 180);
          if (payload?.authenticated === false) {
            setAuthOk(false);
          }
          if (cancelled) return;
          setPerTeam((prev) => ({
            ...prev,
            [ownerId]: { team, payload, error: null },
          }));
        } catch (err) {
          if (cancelled) return;
          setPerTeam((prev) => ({
            ...prev,
            [ownerId]: { team, payload: null, error: err?.message || "fetch_failed" },
          }));
        }
        setProgress((p) => ({ ...p, done: p.done + 1 }));
      }
    }
    run();
    return () => {
      cancelled = true;
    };
  }, [availableTeams, appLoading, teamLoading]);

  const rows = useMemo(() => {
    return Object.values(perTeam).map(({ team, payload, error }) => {
      const aggs = payload?.teamAggregates || {};
      return {
        ownerId: String(team?.ownerId || ""),
        name: team?.name || "(unnamed)",
        playerCount: Array.isArray(team?.players) ? team.players.length : 0,
        totalValue: aggs.totalValue ?? null,
        rosterAware: !!aggs.rosterAware,
        d7: aggs.delta7dDetail || null,
        d30: aggs.delta30dDetail || null,
        d90: aggs.delta90dDetail || null,
        d180: aggs.delta180dDetail || null,
        error,
      };
    });
  }, [perTeam]);

  const summary = useMemo(() => {
    let rosterAwareCount = 0;
    let withTradesCount = 0;
    let lowCoverageCount = 0;
    let errorCount = 0;
    for (const r of rows) {
      if (r.error) errorCount += 1;
      if (r.rosterAware) rosterAwareCount += 1;
      const seen = (r.d30?.tradesSeen || 0) + (r.d90?.tradesSeen || 0);
      if (seen > 0) withTradesCount += 1;
      const lowCoverage =
        (r.d30?.reason === "low_history_coverage") ||
        (r.d90?.reason === "low_history_coverage") ||
        (r.d180?.reason === "low_history_coverage");
      if (lowCoverage) lowCoverageCount += 1;
    }
    return {
      total: rows.length,
      rosterAwareCount,
      withTradesCount,
      lowCoverageCount,
      errorCount,
    };
  }, [rows]);

  if (appLoading || teamLoading) {
    return <LoadingState message="Loading team list…" />;
  }
  if (!availableTeams || availableTeams.length === 0) {
    return (
      <div className="card">
        <PageHeader
          title="Trade Coverage Audit"
          subtitle="Per-team roster-aware delta coverage for the last 180 days."
        />
        <EmptyState
          title="No teams loaded"
          message="Sleeper league data hasn't hydrated yet. Try reloading once the scrape has landed."
        />
      </div>
    );
  }
  if (!authOk && progress.done > 0) {
    return (
      <div className="card">
        <PageHeader title="Trade Coverage Audit" subtitle="Internal diagnostic" />
        <EmptyState
          title="Sign in required"
          message="This audit calls /api/terminal for every team, which needs an authenticated session. Sign in and reload."
        />
      </div>
    );
  }

  return (
    <section>
      <div className="card">
        <PageHeader
          title="Trade Coverage Audit"
          subtitle="Per-team roster-aware delta coverage for the last 180 days."
        />

        <div className="trade-coverage-summary">
          <SummaryStat label="Teams scanned" value={`${progress.done}/${progress.total}`} />
          <SummaryStat label="Roster-aware deltas" value={`${summary.rosterAwareCount}/${summary.total}`} />
          <SummaryStat label="Had trades in window" value={`${summary.withTradesCount}/${summary.total}`} />
          <SummaryStat label="Low-coverage deltas" value={`${summary.lowCoverageCount}/${summary.total}`} tone={summary.lowCoverageCount > 0 ? "warn" : "flat"} />
          <SummaryStat label="Fetch errors" value={summary.errorCount} tone={summary.errorCount > 0 ? "down" : "flat"} />
        </div>

        <div className="trade-coverage-table">
          <div className="trade-coverage-head" aria-hidden="true">
            <span>Team</span>
            <span>Total Value</span>
            <span>Players</span>
            <span>Roster-aware</span>
            <span>Δ 7d</span>
            <span>Δ 30d</span>
            <span>Δ 90d</span>
            <span>Δ 180d</span>
          </div>
          <ul className="trade-coverage-body">
            {rows.map((r) => (
              <li key={r.ownerId} className="trade-coverage-row">
                <span className="trade-coverage-cell trade-coverage-cell--name">
                  <span className="trade-coverage-team-name">{r.name}</span>
                  <span className="trade-coverage-team-owner muted">{r.ownerId}</span>
                </span>
                <span className="trade-coverage-cell">
                  {r.totalValue != null ? r.totalValue.toLocaleString() : "—"}
                </span>
                <span className="trade-coverage-cell">{r.playerCount}</span>
                <span className={`trade-coverage-cell trade-coverage-flag trade-coverage-flag--${r.rosterAware ? "on" : "off"}`}>
                  {r.rosterAware ? "YES" : "no"}
                </span>
                <DeltaCell detail={r.d7} />
                <DeltaCell detail={r.d30} />
                <DeltaCell detail={r.d90} />
                <DeltaCell detail={r.d180} />
              </li>
            ))}
          </ul>
        </div>

        {progress.done < progress.total && (
          <p className="muted" style={{ fontSize: "0.72rem", marginTop: 10 }}>
            Loading {progress.done + 1} of {progress.total}…
          </p>
        )}
      </div>
    </section>
  );
}

function SummaryStat({ label, value, tone = "flat" }) {
  return (
    <div className={`trade-coverage-summary-stat trade-coverage-summary-stat--${tone}`}>
      <span className="trade-coverage-summary-label">{label}</span>
      <span className="trade-coverage-summary-value">{value}</span>
    </div>
  );
}

function DeltaCell({ detail }) {
  if (!detail) {
    return <span className="trade-coverage-cell">—</span>;
  }
  const value = detail.value;
  const pct = Number(detail.coverageFraction);
  const coverageLabel = Number.isFinite(pct) ? `${Math.round(pct * 100)}%` : "?";
  const title = [
    value == null ? `value: null (${detail.reason || "unknown"})` : `value: ${value}`,
    `coverage: ${detail.resolved || 0}/${detail.expected || 0} = ${coverageLabel}`,
    `rosterAware: ${!!detail.rosterAware}`,
    `trades: ${detail.tradesApplied || 0} applied of ${detail.tradesSeen || 0} seen`,
    detail.pastDate ? `vs ${detail.pastDate}` : null,
  ].filter(Boolean).join("\n");
  return (
    <span className="trade-coverage-cell trade-coverage-cell--delta" title={title}>
      <span className="trade-coverage-delta-value">
        {value != null ? (value > 0 ? `+${value}` : value).toString() : "—"}
      </span>
      <span className="trade-coverage-delta-cov muted">
        {coverageLabel}{detail.rosterAware ? " · 🔁" : ""}
      </span>
    </span>
  );
}
