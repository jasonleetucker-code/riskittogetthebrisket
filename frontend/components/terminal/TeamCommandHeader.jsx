"use client";

import { useMemo } from "react";
import { useApp } from "@/components/AppShell";
import { useTeam } from "@/components/useTeam";
import { useLeague } from "@/components/useLeague";
import { useRankHistory } from "@/components/useRankHistory";
import { useTerminal } from "@/components/useTerminal";
import { computeTeamValueSeries, valueFromRank } from "@/lib/value-history";
import { Movement, PageHeader, StatTile } from "@/components/ds";
import TeamValueChart from "./TeamValueChart";
import styles from "./terminal.module.css";

/**
 * Team Command Header — identity anchor + live aggregates (R3).
 *
 * Owns the dashboard's single <h1> via ds PageHeader, and renders the
 * aggregates as StatTiles with ds Movement carrying every delta — the
 * ASCII ▲/▼ glyphs are gone, direction now rides a real arrow plus an
 * announced label ("up 340").
 *
 * Aggregates come from two sources, in priority order:
 *   1. Server (``/api/terminal.teamAggregates``) — authoritative for
 *      roster-aware deltas, includes coverage detail
 *      (``delta*dDetail`` with ``rosterAware``, ``coverageFraction``,
 *      ``resolved``, ``expected``, ``reason``).
 *   2. Local fallback via ``computeTeamValueSeries`` — used only when
 *      the server returned nothing for the team (terminal endpoint
 *      errored, or the user is anonymous).
 *
 * When a delta is null because of low history coverage the tile still
 * renders, with the coverage fraction as its meta line and the full
 * explanation on hover — "32% cov" beats a bare em-dash.
 */

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

// Pretty-print a delta detail block from the terminal payload for the
// tile's hover title: coverage, trade-aware flag, and the reason the
// value is null (if applicable).
function formatDeltaTooltip(detail) {
  if (!detail) return undefined;
  const pct = Number(detail.coverageFraction);
  const pctLabel = Number.isFinite(pct) ? `${Math.round(pct * 100)}%` : "?";
  const trade = detail.rosterAware
    ? `${detail.tradesApplied} trade(s) applied`
    : detail.tradesSeen > 0
      ? "no trades touched your roster in this window"
      : "no trades in this window";
  const base = `Coverage: ${pctLabel} (${detail.resolved || 0}/${detail.expected || 0}). ${trade}.`;
  if (detail.value == null) {
    const reason =
      {
        low_history_coverage: "Insufficient rank history for a reliable number.",
        no_trades: "",
        no_trades_for_owner: "",
        applied: "",
      }[detail.reason || ""] || "";
    return reason ? `${base} ${reason}` : base;
  }
  return base;
}

function nullHint(detail) {
  if (!detail || detail.value != null) return undefined;
  if (detail.reason === "low_history_coverage") {
    const pct = Math.round((Number(detail.coverageFraction) || 0) * 100);
    return `${pct}% cov`;
  }
  return undefined;
}

/** One delta tile: Movement when we have a number, a coverage hint
 *  when we don't. */
function DeltaTile({ label, value, detail }) {
  return (
    <StatTile
      label={label}
      value={value == null ? "—" : formatValue(Math.abs(value))}
      movement={
        value == null || value === 0 ? null : (
          <Movement delta={value} srLabel={`${label}: ${value > 0 ? "up" : "down"} ${Math.abs(value).toLocaleString()}`} />
        )
      }
      meta={nullHint(detail)}
      title={formatDeltaTooltip(detail)}
    />
  );
}

export default function TeamCommandHeader() {
  const { rows } = useApp();
  const {
    selectedTeam,
    needsSelection,
    loading: teamLoading,
    privateDataEnabled,
    leagueMismatch,
  } = useTeam();
  // League eyebrow: only meaningful once a second league exists.
  const { selectedLeague, leagues } = useLeague();
  const { history, loading: historyLoading } = useRankHistory({ days: 30 });
  const { teamAggregates: serverAggregates, loading: terminalLoading } = useTerminal({
    // Hold the fetch until team identity resolves from the contract
    // (prevents the discarded ownerId:"" duplicate call).
    skip: teamLoading,
    ownerId: String(selectedTeam?.ownerId || ""),
    teamName: selectedTeam?.name || "",
    windowDays: 30,
  });

  let teamName;
  if (leagueMismatch) {
    // The user switched to a league whose roster data isn't loaded yet
    // (single-instance deployments). Rankings still work; the header
    // says so rather than rendering stale team info.
    teamName = "Roster data not ready for this league";
  } else if (needsSelection) {
    teamName = "Pick your team";
  } else if (selectedTeam?.name) {
    teamName = selectedTeam.name;
  } else if (teamLoading) {
    teamName = "Loading team…";
  } else if (!privateDataEnabled) {
    teamName = "Team data unavailable";
  } else {
    teamName = "No team data";
  }

  const showLeagueEyebrow = Array.isArray(leagues) && leagues.length >= 2;
  const leagueLabel = selectedLeague?.displayName || selectedLeague?.key || "";
  const eyebrow =
    showLeagueEyebrow && leagueLabel ? `My team · ${leagueLabel}` : "My team";

  const rowByName = useMemo(() => {
    const m = new Map();
    if (!Array.isArray(rows)) return m;
    for (const r of rows) m.set(String(r.name).toLowerCase(), r);
    return m;
  }, [rows]);

  const { totalValue: localTotal, tierCounts: localTiers } = useMemo(() => {
    if (!selectedTeam?.players?.length) return { totalValue: null, tierCounts: null };
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
  const tierCounts = serverAggregates?.tiers != null ? serverAggregates.tiers : localTiers;
  const delta7 = serverAggregates?.delta7d != null ? serverAggregates.delta7d : delta7Local;
  const delta30 =
    serverAggregates?.delta30d != null ? serverAggregates.delta30d : delta30Local;
  const delta90 = serverAggregates?.delta90d ?? null;
  const delta180 = serverAggregates?.delta180d ?? null;

  const tierLabel = tierCounts
    ? `${tierCounts.elite || 0}·${tierCounts.high || 0}·${tierCounts.mid || 0}·${tierCounts.depth || 0}`
    : "—";

  const chartReady = Boolean(selectedTeam?.players?.length);
  const valueLoading = totalValue == null && (historyLoading || terminalLoading);

  return (
    <section aria-label="Team command bar">
      <PageHeader eyebrow={eyebrow} title={teamName} />
      <div className={styles.commandStats} aria-label="Team aggregates">
        {/* Say WHICH total this is. The Portfolio panel below composes
            draft picks back in, so it reports a bigger number for the
            same team — 22.5% of a portfolio on the live snapshot. Two
            unlabelled totals reading differently on one screen is the
            defect (audit W20-F003 / W30-F017); two labelled ones are
            two facts. `valueBasis` is stamped by /api/terminal, and the
            local fallback sums the same player-only set. */}
        <StatTile
          label="Team value"
          value={valueLoading ? "…" : formatValue(totalValue)}
          meta={valueLoading ? undefined : "players only — picks in Portfolio"}
          size="lg"
        />
        <DeltaTile label="Δ 7d" value={delta7} detail={serverAggregates?.delta7dDetail} />
        <DeltaTile label="Δ 30d" value={delta30} detail={serverAggregates?.delta30dDetail} />
        <DeltaTile label="Δ 90d" value={delta90} detail={serverAggregates?.delta90dDetail} />
        <DeltaTile
          label="Δ 180d"
          value={delta180}
          detail={serverAggregates?.delta180dDetail}
        />
        <StatTile label="Tiers" value={tierLabel} meta="elite·high·mid·depth" />
      </div>
      {/* Slot is ALWAYS mounted with the chart's height reserved —
          conditionally mounting the whole block inserted 60px+margin
          above the ticker/rail/grid when the team resolved, shifting
          the entire dashboard. */}
      <div className={styles.commandChart} style={{ minHeight: 60 }}>
        {chartReady && <TeamValueChart width={560} height={60} showSummary={false} />}
      </div>
    </section>
  );
}
