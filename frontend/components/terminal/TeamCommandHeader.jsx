"use client";

import { useMemo } from "react";
import { useApp } from "@/components/AppShell";
import { useTeam } from "@/components/useTeam";
import { useRankHistory } from "@/components/useRankHistory";
import {
  computeTeamValueSeries,
  valueFromRank,
} from "@/lib/value-history";
import TeamValueChart from "./TeamValueChart";

function Stat({ label, value, hint, tone }) {
  return (
    <div className={`tc-stat${tone ? ` tc-stat--${tone}` : ""}`}>
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

/**
 * Team Command Header — identity anchor + live aggregates.
 *
 * Sums roster Hill-curve values at t=now and at t=N days ago to
 * produce the "Team Value" + Δ stats.  Tier distribution bucketizes
 * current roster values using the same cutoffs as the Portfolio
 * Summary panel.  All math lives in ``lib/value-history.js`` so the
 * team-value chart component can share it.
 */
export default function TeamCommandHeader() {
  const { rows } = useApp();
  const { selectedTeam, needsSelection, loading: teamLoading, privateDataEnabled } = useTeam();
  const { history, loading: historyLoading } = useRankHistory({ days: 30 });

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

  const { totalValue, tierCounts } = useMemo(() => {
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

  const { delta7, delta30 } = useMemo(() => {
    if (!selectedTeam?.players?.length || !history) {
      return { delta7: null, delta30: null };
    }
    const series = computeTeamValueSeries({
      rosterNames: selectedTeam.players,
      history,
      valueFromRank,
    });
    if (series.length < 2) return { delta7: null, delta30: null };

    const latest = series[series.length - 1];

    function deltaOver(days) {
      const cutoff = latest.t - days * 86400_000;
      const baseline = series.find((p) => p.t >= cutoff);
      if (!baseline || baseline === latest) return null;
      return latest.value - baseline.value;
    }
    return { delta7: deltaOver(7), delta30: deltaOver(30) };
  }, [selectedTeam, history]);

  const tierLabel = tierCounts
    ? `${tierCounts.elite}·${tierCounts.high}·${tierCounts.mid}·${tierCounts.depth}`
    : "—";

  const chartReady = Boolean(selectedTeam?.players?.length);

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
            hint={totalValue == null && historyLoading ? "…" : undefined}
          />
          <Stat
            label="Δ 7d"
            value={formatDelta(delta7)}
            tone={delta7 == null ? null : delta7 > 0 ? "up" : delta7 < 0 ? "down" : null}
          />
          <Stat
            label="Δ 30d"
            value={formatDelta(delta30)}
            tone={delta30 == null ? null : delta30 > 0 ? "up" : delta30 < 0 ? "down" : null}
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
