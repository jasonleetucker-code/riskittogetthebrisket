"use client";

import { useMemo } from "react";
import { useApp } from "@/components/AppShell";
import { useTeam } from "@/components/useTeam";
import { useRankHistory } from "@/components/useRankHistory";
import { useTerminal } from "@/components/useTerminal";
import {
  computeTeamValueSeries,
  valueFromRank,
} from "@/lib/value-history";
import TeamValueChart from "./TeamValueChart";

function Stat({ label, value, hint, tone, title }) {
  return (
    <div
      className={`tc-stat${tone ? ` tc-stat--${tone}` : ""}`}
      title={title}
    >
      <span className="tc-stat-label">{label}</span>
      <span className="tc-stat-value">{value}</span>
      {hint && <span className="tc-stat-hint">{hint}</span>}
    </div>
  );
}

function tierBucket(value) {
  if (value >= 8500) return "elite";
  if (value >= 6500) return "high";
  if (value >= 3000) return "mid";
  return "depth";
}

function formatValue(v) {
  if (!Number.isFinite(v)) return "—";
  return v.toLocaleString();
}

function formatDelta(d) {
  if (!Number.isFinite(d) || d === 0) return "·";
  const abs = Math.abs(d).toLocaleString();
  return d > 0 ? `▲ ${abs}` : `▼ ${abs}`;
}

// Pretty-print a delta detail block from the terminal payload for a
// hover-tooltip on each Δ stat.  Shows the coverage, trade-aware
// flag, and the reason the value is null (if applicable).
function formatDeltaTooltip(detail) {
  if (!detail) return undefined;
  const pct = Number(detail.coverageFraction);
  const pctLabel = Number.isFinite(pct) ? `${Math.round(pct * 100)}%` : "?";
  const trade = detail.rosterAware
    ? `${detail.tradesApplied} trade(s) applied`
    : detail.tradesSeen > 0
    ? `no trades touched your roster in this window`
    : "no trades in this window";
  const base = `Coverage: ${pctLabel} (${detail.resolved || 0}/${detail.expected || 0}). ${trade}.`;
  if (detail.value == null) {
    const reason = {
      low_history_coverage: "Insufficient rank history for a reliable number.",
      no_trades: "",
      no_trades_for_owner: "",
      applied: "",
    }[detail.reason || ""] || "";
    return reason ? `${base} ${reason}` : base;
  }
  return base;
}

/**
 * Team Command Header — identity anchor + live aggregates.
 *
 * Aggregates come from two sources, in priority order:
 *   1. Server (``/api/terminal.teamAggregates``) — authoritative
 *      for roster-aware deltas, includes coverage detail
 *      (``delta*dDetail`` with ``rosterAware``, ``coverageFraction``,
 *      ``resolved``, ``expected``, ``reason``).
 *   2. Local fallback via ``computeTeamValueSeries`` — used only
 *      when the server didn't return values for the team (e.g.
 *      terminal endpoint errored, or user is anonymous).
 *
 * When a delta is null because of low history coverage, the Δ stat
 * still renders with a tooltip that explains why so the user sees
 * "Insufficient history (32% coverage)" instead of a bare "—".
 */
export default function TeamCommandHeader() {
  const { rows } = useApp();
  const { selectedTeam, needsSelection, loading: teamLoading, privateDataEnabled } = useTeam();
  const { history, loading: historyLoading } = useRankHistory({ days: 30 });
  const {
    teamAggregates: serverAggregates,
    loading: terminalLoading,
  } = useTerminal({
    ownerId: String(selectedTeam?.ownerId || ""),
    teamName: selectedTeam?.name || "",
    windowDays: 30,
  });

  let teamName;
  let nameVariant = "ready";
  if (needsSelection) {
    teamName = "Pick your team";
    nameVariant = "needs";
  } else if (selectedTeam?.name) {
    teamName = selectedTeam.name;
  } else if (teamLoading) {
    teamName = "Loading team…";
    nameVariant = "loading";
  } else if (!privateDataEnabled) {
    teamName = "Team data unavailable";
    nameVariant = "error";
  } else {
    teamName = "No team data";
    nameVariant = "error";
  }

  const rowByName = useMemo(() => {
    const m = new Map();
    if (!Array.isArray(rows)) return m;
    for (const r of rows) m.set(String(r.name).toLowerCase(), r);
    return m;
  }, [rows]);

  const { totalValue: localTotal, tierCounts: localTiers } = useMemo(() => {
    if (!selectedTeam?.players?.length) {
      return { totalValue: null, tierCounts: null };
    }
    const counts = { elite: 0, high: 0, mid: 0, depth: 0 };
    let total = 0;
    let coverage = 0;
    for (const name of selectedTeam.players) {
      const row = rowByName.get(String(name).toLowerCase());
      if (!row) continue;
      const v = Number(row.rankDerivedValue || row.values?.full || 0);
      if (!v) continue;
      total += v;
      counts[tierBucket(v)] += 1;
      coverage += 1;
    }
    if (coverage === 0) return { totalValue: null, tierCounts: null };
    return { totalValue: total, tierCounts: counts };
  }, [selectedTeam, rowByName]);

  const { delta7Local, delta30Local } = useMemo(() => {
    if (!selectedTeam?.players?.length || !history) {
      return { delta7Local: null, delta30Local: null };
    }
    const series = computeTeamValueSeries({
      rosterNames: selectedTeam.players,
      history,
      valueFromRank,
    });
    if (series.length < 2) return { delta7Local: null, delta30Local: null };

    const latest = series[series.length - 1];

    function deltaOver(days) {
      const cutoff = latest.t - days * 86400_000;
      const baseline = series.find((p) => p.t >= cutoff);
      if (!baseline || baseline === latest) return null;
      return latest.value - baseline.value;
    }
    return { delta7Local: deltaOver(7), delta30Local: deltaOver(30) };
  }, [selectedTeam, history]);

  // Prefer server aggregates; fall back to locals.
  const totalValue =
    serverAggregates?.totalValue != null ? serverAggregates.totalValue : localTotal;
  const tierCounts =
    serverAggregates?.tiers != null ? serverAggregates.tiers : localTiers;
  const delta7 =
    serverAggregates?.delta7d != null ? serverAggregates.delta7d : delta7Local;
  const delta30 =
    serverAggregates?.delta30d != null ? serverAggregates.delta30d : delta30Local;
  const delta90 = serverAggregates?.delta90d ?? null;
  const delta180 = serverAggregates?.delta180d ?? null;

  const tierLabel = tierCounts
    ? `${tierCounts.elite || 0}·${tierCounts.high || 0}·${tierCounts.mid || 0}·${tierCounts.depth || 0}`
    : "—";

  const chartReady = Boolean(selectedTeam?.players?.length);

  // Low-coverage hints — surface the coverage fraction when a
  // delta is null because history was insufficient.  Pulled from
  // the server's delta*dDetail block.
  const tip7 = formatDeltaTooltip(serverAggregates?.delta7dDetail);
  const tip30 = formatDeltaTooltip(serverAggregates?.delta30dDetail);
  const tip90 = formatDeltaTooltip(serverAggregates?.delta90dDetail);
  const tip180 = formatDeltaTooltip(serverAggregates?.delta180dDetail);

  function nullHint(detail) {
    if (!detail || detail.value != null) return undefined;
    if (detail.reason === "low_history_coverage") {
      const pct = Math.round((Number(detail.coverageFraction) || 0) * 100);
      return `${pct}% cov`;
    }
    return undefined;
  }

  return (
    <header className="tc-header panel panel--bare">
      <div className="tc-header-row">
        <div className="tc-header-identity">
          <span className="tc-header-eyebrow">My Team</span>
          <h1 className={`tc-header-team tc-header-team--${nameVariant}`}>{teamName}</h1>
        </div>
        <div className="tc-header-stats" aria-label="Team aggregates">
          <Stat
            label="Team Value"
            value={formatValue(totalValue)}
            hint={
              totalValue == null && (historyLoading || terminalLoading)
                ? "…"
                : undefined
            }
          />
          <Stat
            label="Δ 7d"
            value={formatDelta(delta7)}
            tone={delta7 == null ? null : delta7 > 0 ? "up" : delta7 < 0 ? "down" : null}
            title={tip7}
            hint={nullHint(serverAggregates?.delta7dDetail)}
          />
          <Stat
            label="Δ 30d"
            value={formatDelta(delta30)}
            tone={delta30 == null ? null : delta30 > 0 ? "up" : delta30 < 0 ? "down" : null}
            title={tip30}
            hint={nullHint(serverAggregates?.delta30dDetail)}
          />
          <Stat
            label="Δ 90d"
            value={formatDelta(delta90)}
            tone={delta90 == null ? null : delta90 > 0 ? "up" : delta90 < 0 ? "down" : null}
            title={tip90}
            hint={nullHint(serverAggregates?.delta90dDetail)}
          />
          <Stat
            label="Δ 180d"
            value={formatDelta(delta180)}
            tone={delta180 == null ? null : delta180 > 0 ? "up" : delta180 < 0 ? "down" : null}
            title={tip180}
            hint={nullHint(serverAggregates?.delta180dDetail)}
          />
          <Stat label="Tiers" value={tierLabel} hint="E·H·M·D" />
        </div>
      </div>
      {chartReady && (
        <div className="tc-header-chart">
          <TeamValueChart width={560} height={60} showSummary={false} />
        </div>
      )}
    </header>
  );
}
