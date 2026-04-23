"use client";

import { useMemo } from "react";
import { useApp } from "@/components/AppShell";
import { useTeam } from "@/components/useTeam";
import { useRankHistory } from "@/components/useRankHistory";
import { useNews } from "@/components/useNews";
import {
  computePortfolio,
  computeInsights,
  computeRosterChips,
  computePlayerBlurb,
} from "@/lib/portfolio-insights";
import Panel from "./Panel";

const INSIGHT_CARDS = [
  { key: "bestAsset",   label: "Best Asset",   tone: "up" },
  { key: "biggestRisk", label: "Biggest Risk", tone: "down" },
  { key: "tradeChip",   label: "Trade Chip",   tone: "warn" },
  { key: "buyLow",      label: "Buy-Low Target", tone: "flat" },
];

function formatValue(v) {
  if (!Number.isFinite(v)) return "—";
  return v.toLocaleString();
}

/**
 * Scouting / Intel — the front-office analyst panel.
 *
 * Everything here is rule-driven:
 *   - Four named insight cards (best / risk / chip / buy-low), each
 *     citing the exact metric that earned the call.
 *   - Roster-level chip row: rising, falling, high-vol count, median
 *     age, rookie-value share.
 *   - Per-player intel list showing concrete blurbs for a rotating
 *     subset of the roster — pulled via computePlayerBlurb so no
 *     prose is fabricated.
 *
 * Buy-low target is LEAGUE-wide (not on my roster) — a natural GM
 * "next to go acquire" recommendation, not a roster-filter echo.
 */
export default function ScoutingIntel() {
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

  const rosterNames = selectedTeam?.players || [];
  const news = useNews({ rosterNames, leagueNames });

  const portfolio = useMemo(
    () => computePortfolio({ rows, selectedTeam, rawData, history }),
    [rows, selectedTeam, rawData, history],
  );

  const insights = useMemo(
    () =>
      computeInsights({
        portfolio,
        rows,
        selectedTeam,
        newsItems: news.scored,
      }),
    [portfolio, rows, selectedTeam, news.scored],
  );

  const rosterChips = useMemo(
    () => computeRosterChips(portfolio),
    [portfolio],
  );

  // Pick 5 players for the per-player intel feed: ones with the
  // strongest signal (biggest |trend7|, highest vol, extremes).
  const intelFeed = useMemo(() => {
    if (!portfolio?.rosterValues?.length) return [];
    const ranked = [...portfolio.rosterValues]
      .map((p) => ({
        ...p,
        _salience:
          Math.abs(p.trend7 ?? 0) * 2 +
          (p.volLabel === "high" ? 8 : p.volLabel === "med" ? 3 : 0) +
          (p.isRookie ? 2 : 0),
      }))
      .sort((a, b) => b._salience - a._salience);
    return ranked.slice(0, 5);
  }, [portfolio]);

  if (!selectedTeam) {
    return (
      <Panel title="Scouting" subtitle="Data confidence + anomalies" className="panel--scouting">
        <div className="scouting-empty">Pick a team to see intel.</div>
      </Panel>
    );
  }

  const loading = historyLoading && !portfolio;

  return (
    <Panel
      title="Scouting"
      subtitle="Roster-level intel + four named reads"
      className="panel--scouting"
      collapsible
      defaultCollapsed={false}
    >
      {/* ── Roster chip row ── */}
      {rosterChips.length > 0 && (
        <div className="scouting-roster-chips" role="group" aria-label="Roster summary">
          {rosterChips.map((c) => (
            <span key={c.label} className={`scouting-chip scouting-chip--${c.tone}`}>
              <span className="scouting-chip-label">{c.label}</span>
              <span className="scouting-chip-value">{c.value}</span>
            </span>
          ))}
        </div>
      )}

      {/* ── Four insight cards ── */}
      <div className="scouting-insights" role="list">
        {INSIGHT_CARDS.map((card) => {
          const entry = insights?.[card.key];
          if (!entry) {
            return (
              <article
                key={card.key}
                className={`scouting-insight scouting-insight--${card.tone} scouting-insight--empty`}
                role="listitem"
              >
                <div className="scouting-insight-head">
                  <span className={`scouting-insight-badge scouting-insight-badge--${card.tone}`}>
                    {card.label}
                  </span>
                </div>
                <div className="scouting-insight-reason">
                  {loading ? "Loading…" : "No qualifying candidate in current data."}
                </div>
              </article>
            );
          }
          const p = entry.player;
          return (
            <article
              key={card.key}
              className={`scouting-insight scouting-insight--${card.tone}`}
              role="listitem"
            >
              <div className="scouting-insight-head">
                <span className={`scouting-insight-badge scouting-insight-badge--${card.tone}`}>
                  {card.label}
                </span>
                <button
                  type="button"
                  className="scouting-insight-player"
                  onClick={() => openPlayerPopup?.(p.name)}
                  title={`Open ${p.name}`}
                >
                  <span className="scouting-insight-name">{p.name}</span>
                  <span className="scouting-insight-meta">
                    {p.pos} · {formatValue(p.value)}
                  </span>
                </button>
              </div>
              <div className="scouting-insight-reason">{entry.reason}</div>
            </article>
          );
        })}
      </div>

      {/* ── Per-player intel feed ── */}
      {intelFeed.length > 0 && (
        <section className="scouting-intel-feed">
          <h3 className="scouting-intel-feed-title">Intel feed</h3>
          <ul className="scouting-intel-list">
            {intelFeed.map((p) => (
              <li key={p.name} className="scouting-intel-row">
                <button
                  type="button"
                  className="scouting-intel-trigger"
                  onClick={() => openPlayerPopup?.(p.name)}
                  title={`Open ${p.name}`}
                >
                  <span className="scouting-intel-name">{p.name}</span>
                  <span className="scouting-intel-pos">{p.pos}</span>
                  <span className="scouting-intel-blurb">{computePlayerBlurb(p)}</span>
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}

      {!news.loading && news.items.length === 0 && (
        <div className="scouting-note">News feed currently empty — intel uses portfolio metrics only.</div>
      )}
    </Panel>
  );
}
