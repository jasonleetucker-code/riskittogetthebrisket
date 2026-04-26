"use client";

import { useMemo, useState } from "react";
import { useApp } from "@/components/AppShell";
import { useTeam } from "@/components/useTeam";
import { useRankHistory } from "@/components/useRankHistory";
import {
  normalizePoints,
  computeWindowTrend,
  computeVolatility,
  buildHistoryLookup,
} from "@/lib/value-history";
import Panel from "./Panel";
import Sparkline from "./Sparkline";

const SCOPE_TABS = [
  { key: "roster", label: "My Roster" },
  { key: "league", label: "League" },
  { key: "top150", label: "Top 150" },
];

const WINDOW_TABS = [
  { key: "d7", label: "7d", days: 7 },
  { key: "d30", label: "30d", days: 30 },
  { key: "d90", label: "90d", days: 90 },
  { key: "d180", label: "180d", days: 180 },
];

const SORTS = {
  gain: { key: "gain", label: "Top Gainers" },
  loss: { key: "loss", label: "Top Fallers" },
  value: { key: "value", label: "By Value" },
  vol: { key: "vol", label: "Most Volatile" },
};

const MAX_ROWS = 40;

function toSet(names) {
  const s = new Set();
  if (!Array.isArray(names)) return s;
  for (const n of names) s.add(String(n).toLowerCase());
  return s;
}

export default function PlayerMarketMovement() {
  const { rows, rawData, openPlayerPopup } = useApp();
  const { selectedTeam } = useTeam();
  const sleeperTeams = rawData?.sleeper?.teams;

  const [scope, setScope] = useState("roster");
  const [windowKey, setWindowKey] = useState("d7");
  const [sortKey, setSortKey] = useState("gain");

  const windowDays = WINDOW_TABS.find((w) => w.key === windowKey)?.days || 7;
  const { history, loading: historyLoading, error: historyError } =
    useRankHistory({ days: Math.max(30, windowDays) });

  const rosterSet = useMemo(
    () => toSet(selectedTeam?.players),
    [selectedTeam],
  );
  const leagueSet = useMemo(() => {
    const s = new Set();
    if (!Array.isArray(sleeperTeams)) return s;
    for (const t of sleeperTeams) {
      if (Array.isArray(t?.players)) t.players.forEach((p) => s.add(String(p).toLowerCase()));
    }
    return s;
  }, [sleeperTeams]);

  const historyLookup = useMemo(() => buildHistoryLookup(history), [history]);

  const scoped = useMemo(() => {
    if (!Array.isArray(rows) || rows.length === 0) return [];
    if (scope === "roster") {
      return rows.filter((r) => rosterSet.has(String(r.name).toLowerCase()));
    }
    if (scope === "league") {
      return rows.filter((r) => leagueSet.has(String(r.name).toLowerCase()));
    }
    return rows.filter(
      (r) =>
        typeof r.canonicalConsensusRank === "number" &&
        r.canonicalConsensusRank > 0 &&
        r.canonicalConsensusRank <= 150,
    );
  }, [rows, scope, rosterSet, leagueSet]);

  const enriched = useMemo(() => {
    return scoped.map((r) => {
      // History keys are scoped ("Name::offense"); pass r.assetClass
      // so cross-universe name collisions resolve to the right series.
      const rawPts = historyLookup(r.name, r.assetClass);
      const points = normalizePoints(rawPts);
      const trend = computeWindowTrend(points, windowDays);
      const vol = computeVolatility(points, Math.max(30, windowDays));
      return {
        name: r.name,
        pos: r.pos || "?",
        value: Number(r.rankDerivedValue || r.values?.full || 0),
        rank: Number(r.canonicalConsensusRank) || null,
        confidence: Number(r.confidence) || 0,
        onRoster: rosterSet.has(String(r.name).toLowerCase()),
        points,
        trend,
        volatility: vol,
      };
    });
  }, [scoped, historyLookup, windowDays, rosterSet]);

  const sorted = useMemo(() => {
    const arr = [...enriched];
    if (sortKey === "gain") {
      arr.sort((a, b) => (b.trend ?? -Infinity) - (a.trend ?? -Infinity));
    } else if (sortKey === "loss") {
      arr.sort((a, b) => (a.trend ?? Infinity) - (b.trend ?? Infinity));
    } else if (sortKey === "vol") {
      arr.sort((a, b) => (b.volatility?.mad ?? -1) - (a.volatility?.mad ?? -1));
    } else {
      arr.sort((a, b) => b.value - a.value);
    }
    return arr.slice(0, MAX_ROWS);
  }, [enriched, sortKey]);

  const emptyReason = (() => {
    if (!Array.isArray(rows) || rows.length === 0) return "No player data loaded.";
    if (scope === "roster" && !selectedTeam) return "Pick a team to see your roster's movement.";
    if (sorted.length === 0) return "No players match this scope.";
    return null;
  })();

  return (
    <Panel
      title="Player Market Movement"
      subtitle={historyError ? "History unavailable" : "Real deltas from rank history"}
      className="panel--movement"
      actions={
        <div className="panel-tabs" role="tablist" aria-label="Window">
          {WINDOW_TABS.map((t) => (
            <button
              key={t.key}
              type="button"
              role="tab"
              aria-selected={windowKey === t.key}
              className={`panel-tab${windowKey === t.key ? " is-active" : ""}`}
              onClick={() => setWindowKey(t.key)}
            >
              {t.label}
            </button>
          ))}
        </div>
      }
    >
      <div className="pmm-controls">
        <nav className="pmm-scope" role="tablist" aria-label="Movement scope">
          {SCOPE_TABS.map((t) => (
            <button
              key={t.key}
              type="button"
              role="tab"
              aria-selected={scope === t.key}
              className={`pmm-scope-tab${scope === t.key ? " is-active" : ""}`}
              onClick={() => setScope(t.key)}
            >
              {t.label}
            </button>
          ))}
        </nav>
        <div className="pmm-sort">
          {Object.values(SORTS).map((s) => (
            <button
              key={s.key}
              type="button"
              className={`pmm-sort-chip${sortKey === s.key ? " is-active" : ""}`}
              onClick={() => setSortKey(s.key)}
            >
              {s.label}
            </button>
          ))}
        </div>
      </div>

      {emptyReason && (
        <div className="pmm-empty" role="status">
          {emptyReason}
        </div>
      )}

      {!emptyReason && (
        <div className="pmm-table">
          <div className="pmm-head" aria-hidden="true">
            <span className="pmm-col pmm-col--name">Player</span>
            <span className="pmm-col pmm-col--pos">Pos</span>
            <span className="pmm-col pmm-col--value">Value</span>
            <span className="pmm-col pmm-col--delta">Δ {windowDays}d</span>
            <span className="pmm-col pmm-col--spark">Trend</span>
            <span className="pmm-col pmm-col--vol">Vol</span>
          </div>
          <ul className="pmm-body">
            {sorted.map((row) => (
              <MoverRow
                key={row.name}
                row={row}
                historyLoading={historyLoading}
                onOpen={() => openPlayerPopup?.(row.name)}
              />
            ))}
          </ul>
        </div>
      )}
    </Panel>
  );
}

function MoverRow({ row, historyLoading, onOpen }) {
  const trend = row.trend;
  const direction = trend == null ? "flat" : trend > 0 ? "up" : trend < 0 ? "down" : "flat";
  const deltaLabel =
    trend == null ? "—" : trend === 0 ? "·" : trend > 0 ? `▲ ${trend}` : `▼ ${Math.abs(trend)}`;

  return (
    <li
      className={`pmm-row pmm-row--${direction}${row.onRoster ? " pmm-row--roster" : ""}`}
    >
      <button type="button" className="pmm-row-trigger" onClick={onOpen}>
        <span className="pmm-col pmm-col--name">
          {row.onRoster && <span className="pmm-row-dot" aria-hidden="true">●</span>}
          {row.name}
        </span>
        <span className="pmm-col pmm-col--pos">{row.pos}</span>
        <span className="pmm-col pmm-col--value">{formatValue(row.value)}</span>
        <span className="pmm-col pmm-col--delta">{deltaLabel}</span>
        <span className="pmm-col pmm-col--spark">
          {historyLoading ? (
            <span className="sparkline sparkline--loading" aria-hidden="true" />
          ) : (
            <Sparkline points={row.points} />
          )}
        </span>
        <span className="pmm-col pmm-col--vol">
          {row.volatility ? (
            <span
              className={`pmm-vol-pill pmm-vol-pill--${row.volatility.label}`}
              title={`MAD ${row.volatility.mad.toFixed(1)}`}
            >
              {row.volatility.label.toUpperCase()}
            </span>
          ) : (
            <span className="pmm-vol-pill pmm-vol-pill--none">—</span>
          )}
        </span>
      </button>
    </li>
  );
}

function formatValue(v) {
  if (!Number.isFinite(v)) return "—";
  if (v >= 1000) return v.toLocaleString();
  return String(v);
}
