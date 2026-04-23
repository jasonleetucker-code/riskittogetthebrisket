"use client";

import { useMemo, useState } from "react";
import { useApp } from "@/components/AppShell";
import { useTeam } from "@/components/useTeam";
import { useRankHistory } from "@/components/useRankHistory";
import { useNews } from "@/components/useNews";
import {
  evaluateRoster,
  SIGNAL_META,
  SIGNALS,
} from "@/lib/signal-engine";
import Panel from "./Panel";

const FILTER_ORDER = [
  SIGNALS.RISK,
  SIGNALS.SELL,
  SIGNALS.MONITOR,
  SIGNALS.STRONG_HOLD,
  SIGNALS.BUY,
  SIGNALS.HOLD,
];

const DEFAULT_FILTERS = new Set([SIGNALS.RISK, SIGNALS.SELL, SIGNALS.MONITOR, SIGNALS.BUY]);

export default function BuySellHold() {
  const { rows, rawData, openPlayerPopup } = useApp();
  const { selectedTeam } = useTeam();
  const { history, loading: historyLoading } = useRankHistory({ days: 30 });

  const sleeperTeams = rawData?.sleeper?.teams;
  const leagueNames = useMemo(() => {
    const names = [];
    if (!Array.isArray(sleeperTeams)) return names;
    for (const t of sleeperTeams) {
      if (Array.isArray(t?.players)) names.push(...t.players);
    }
    return names;
  }, [sleeperTeams]);

  const [filters, setFilters] = useState(new Set(DEFAULT_FILTERS));
  const [expandedId, setExpandedId] = useState(null);

  const rosterNames = selectedTeam?.players || [];
  const news = useNews({ rosterNames, leagueNames });

  // useNews returns its items already scored for the rule engine —
  // no per-component re-ranking needed.
  const scoredNews = news.scored;

  const verdicts = useMemo(
    () =>
      evaluateRoster({
        rows,
        selectedTeam,
        history,
        newsItems: scoredNews,
      }),
    [rows, selectedTeam, history, scoredNews],
  );

  const counts = useMemo(() => {
    const c = Object.fromEntries(FILTER_ORDER.map((s) => [s, 0]));
    for (const v of verdicts) c[v.verdict.signal] = (c[v.verdict.signal] || 0) + 1;
    return c;
  }, [verdicts]);

  const visible = useMemo(
    () => verdicts.filter((v) => filters.has(v.verdict.signal)),
    [verdicts, filters],
  );

  function toggleFilter(sig) {
    setFilters((prev) => {
      const next = new Set(prev);
      if (next.has(sig)) next.delete(sig);
      else next.add(sig);
      if (next.size === 0) {
        // Don't allow empty — reset to defaults.
        return new Set(DEFAULT_FILTERS);
      }
      return next;
    });
  }

  const emptyReason = (() => {
    if (!selectedTeam) return "Pick a team to see roster signals.";
    if (historyLoading && news.loading) return "Loading signals…";
    if (verdicts.length === 0) return "No rows resolved for this roster.";
    if (visible.length === 0) return "No signals match the active filters.";
    return null;
  })();

  return (
    <Panel
      title="Signals"
      subtitle="Rule-driven Buy / Sell / Hold per roster player"
      className="panel--signals"
    >
      <div className="signal-filters" role="group" aria-label="Filter by signal">
        {FILTER_ORDER.map((sig) => {
          const meta = SIGNAL_META[sig];
          const active = filters.has(sig);
          return (
            <button
              key={sig}
              type="button"
              className={`signal-filter signal-filter--${meta.tone}${active ? " is-active" : ""}`}
              onClick={() => toggleFilter(sig)}
              aria-pressed={active}
            >
              <span>{meta.label}</span>
              <span className="signal-filter-count">{counts[sig] || 0}</span>
            </button>
          );
        })}
      </div>

      {emptyReason && (
        <div className="signal-empty" role="status">{emptyReason}</div>
      )}

      {!emptyReason && (
        <ul className="signal-list">
          {visible.map((entry) => (
            <SignalCard
              key={entry.row.name}
              entry={entry}
              expanded={expandedId === entry.row.name}
              onToggleExpand={() =>
                setExpandedId((prev) => (prev === entry.row.name ? null : entry.row.name))
              }
              onOpenPlayer={() => openPlayerPopup?.(entry.row.name)}
            />
          ))}
        </ul>
      )}
    </Panel>
  );
}

function SignalCard({ entry, expanded, onToggleExpand, onOpenPlayer }) {
  const { context, verdict } = entry;
  const meta = SIGNAL_META[verdict.signal];
  const volLabel = context.volatility?.label ?? "—";

  return (
    <li className={`signal-card signal-card--${meta.tone}`}>
      <div className="signal-card-top">
        <button type="button" className="signal-card-name-btn" onClick={onOpenPlayer} title={`Open ${context.name}`}>
          <span className="signal-card-name">{context.name}</span>
          <span className="signal-card-pos">{context.pos}</span>
          <span className="signal-card-value">{context.value.toLocaleString()}</span>
        </button>
        <span className={`signal-badge signal-badge--${meta.tone}`}>{meta.label}</span>
      </div>
      <div className="signal-card-rationale">{verdict.reason}</div>
      <div className="signal-card-chips">
        <Chip label="7d" value={fmtSignedInt(context.trend7)} tone={toneOf(context.trend7)} />
        <Chip label="30d" value={fmtSignedInt(context.trend30)} tone={toneOf(context.trend30)} />
        <Chip label="Vol" value={volLabel.toUpperCase()} tone={volTone(volLabel)} />
        {context.newsCount > 0 && (
          <Chip
            label="News"
            value={context.newsCount}
            tone={context.alertCount > 0 ? "down" : context.positiveImpactCount > 0 ? "up" : "flat"}
          />
        )}
        {verdict.fired.length > 1 && (
          <button
            type="button"
            className="signal-card-more"
            onClick={onToggleExpand}
            aria-expanded={expanded}
          >
            {expanded ? "Hide" : `Why (${verdict.fired.length})`}
          </button>
        )}
      </div>
      {expanded && verdict.fired.length > 0 && (
        <ul className="signal-card-chain" aria-label="Firing rule chain">
          {verdict.fired.map((r, i) => (
            <li key={r.id} className="signal-card-chain-item">
              <span className="signal-card-chain-step">{i + 1}.</span>
              <span className={`signal-badge signal-badge--${SIGNAL_META[r.signal]?.tone || "flat"} signal-badge--sm`}>
                {SIGNAL_META[r.signal]?.label || r.signal}
              </span>
              <span className="signal-card-chain-reason">{r.reason}</span>
              <span className="signal-card-chain-tag">{r.tag}</span>
            </li>
          ))}
        </ul>
      )}
    </li>
  );
}

function Chip({ label, value, tone = "flat" }) {
  return (
    <span className={`signal-chip signal-chip--${tone}`}>
      <span className="signal-chip-label">{label}</span>
      <span className="signal-chip-value">{value}</span>
    </span>
  );
}

function fmtSignedInt(v) {
  if (v == null || !Number.isFinite(v)) return "—";
  if (v === 0) return "·";
  return v > 0 ? `+${v}` : `${v}`;
}

function toneOf(v) {
  if (v == null || !Number.isFinite(v) || v === 0) return "flat";
  return v > 0 ? "up" : "down";
}

function volTone(label) {
  if (label === "low") return "up";
  if (label === "high") return "down";
  if (label === "med") return "warn";
  return "flat";
}
