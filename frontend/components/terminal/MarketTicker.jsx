"use client";

import { useEffect, useMemo, useState } from "react";
import { useApp } from "@/components/AppShell";
import { useTeam } from "@/components/useTeam";
import { useNews } from "@/components/useNews";
import {
  computeMovers,
  formatChange,
} from "@/lib/market-movers";
import { selectTickerAlerts } from "@/lib/news-service";

const SCOPE_OPTIONS = [
  { key: "roster", label: "My Roster" },
  { key: "league", label: "League" },
  { key: "top150", label: "Top 150" },
];

// Minimum meaningful movers before we'll render the strip at all.
// Under 3 items the loop looks static; we show the empty state instead.
const MIN_RENDERABLE = 3;

function useLeagueNames(sleeperTeams) {
  return useMemo(() => {
    const names = [];
    if (!Array.isArray(sleeperTeams)) return names;
    for (const t of sleeperTeams) {
      if (Array.isArray(t?.players)) names.push(...t.players);
    }
    return names;
  }, [sleeperTeams]);
}

function usePrefersReducedMotion() {
  const [reduced, setReduced] = useState(false);
  useEffect(() => {
    if (typeof window === "undefined" || !window.matchMedia) return undefined;
    const mql = window.matchMedia("(prefers-reduced-motion: reduce)");
    const update = () => setReduced(!!mql.matches);
    update();
    mql.addEventListener?.("change", update);
    return () => mql.removeEventListener?.("change", update);
  }, []);
  return reduced;
}

export default function MarketTicker() {
  const { rows, rawData, openPlayerPopup } = useApp();
  const { selectedTeam } = useTeam();
  const sleeperTeams = rawData?.sleeper?.teams;
  const leagueNames = useLeagueNames(sleeperTeams);
  const reducedMotion = usePrefersReducedMotion();

  const [scope, setScope] = useState("roster");
  const [paused, setPaused] = useState(false);

  // Single shared news fetch via the module-level cache in
  // useNews — ticker + news feed + signals + scouting all read
  // from the same 60s-TTL store, so mounting the whole landing
  // page issues exactly one /api/news request instead of four.
  const rosterNames = selectedTeam?.players || [];
  const newsState = useNews({ rosterNames, leagueNames });

  const movers = useMemo(
    () =>
      computeMovers({
        rows,
        selectedTeam,
        sleeperTeams,
        scope,
        limit: 20,
      }),
    [rows, selectedTeam, sleeperTeams, scope],
  );

  const alerts = useMemo(() => {
    if (newsState.loading || newsState.items.length === 0) return [];
    return selectTickerAlerts(newsState.scored, { limit: 3 });
  }, [newsState]);

  // Interleave: drop every 5th ticker slot with an alert, so the
  // strip reads as "moves + moves + moves + moves + alert" visually.
  const items = useMemo(() => {
    const out = [];
    let a = 0;
    for (let i = 0; i < movers.length; i++) {
      out.push({ kind: "mover", data: movers[i], key: `m-${movers[i].key}` });
      if ((i + 1) % 5 === 0 && a < alerts.length) {
        const al = alerts[a];
        out.push({ kind: "alert", data: al, key: `a-${al.id}` });
        a += 1;
      }
    }
    // Append any leftover alerts at the tail so they still get a slot.
    while (a < alerts.length) {
      out.push({ kind: "alert", data: alerts[a], key: `a-${alerts[a].id}` });
      a += 1;
    }
    return out;
  }, [movers, alerts]);

  const scopeLabel =
    SCOPE_OPTIONS.find((o) => o.key === scope)?.label || "Roster";

  if (items.length < MIN_RENDERABLE) {
    return (
      <div className="ticker ticker--quiet" role="region" aria-label="Market ticker">
        <div className="ticker-scope">
          <span className="ticker-scope-label">Scope</span>
          <div className="ticker-scope-tabs" role="tablist">
            {SCOPE_OPTIONS.map((o) => (
              <button
                key={o.key}
                type="button"
                role="tab"
                aria-selected={scope === o.key}
                className={`ticker-scope-tab${scope === o.key ? " is-active" : ""}`}
                onClick={() => setScope(o.key)}
              >
                {o.label}
              </button>
            ))}
          </div>
        </div>
        <div className="ticker-quiet-msg">
          Market quiet in {scopeLabel.toLowerCase()} — fewer than {MIN_RENDERABLE} moves since last update.
        </div>
      </div>
    );
  }

  // Duplicate the items once so CSS marquee loops seamlessly.  Setting
  // ``aria-hidden`` on the clone keeps AT from double-announcing.
  const animate = !reducedMotion && !paused;

  return (
    <div
      className={`ticker${animate ? " ticker--live" : ""}`}
      role="region"
      aria-label="Market ticker"
      onMouseEnter={() => setPaused(true)}
      onMouseLeave={() => setPaused(false)}
    >
      <div className="ticker-scope">
        <span className="ticker-scope-label">Scope</span>
        <div className="ticker-scope-tabs" role="tablist">
          {SCOPE_OPTIONS.map((o) => (
            <button
              key={o.key}
              type="button"
              role="tab"
              aria-selected={scope === o.key}
              className={`ticker-scope-tab${scope === o.key ? " is-active" : ""}`}
              onClick={() => setScope(o.key)}
            >
              {o.label}
            </button>
          ))}
        </div>
      </div>
      <div className="ticker-strip">
        <ul
          className={`ticker-track${animate ? " ticker-track--animated" : ""}`}
          style={animate ? { animationDuration: `${Math.max(30, items.length * 4)}s` } : undefined}
        >
          {items.map((it) => (
            <TickerSlot
              key={it.key}
              item={it}
              onPlayerClick={(name) => {
                if (typeof openPlayerPopup === "function") openPlayerPopup(name);
              }}
            />
          ))}
          {/* Cloned track for seamless marquee.  Hidden from AT. */}
          {animate &&
            items.map((it) => (
              <TickerSlot
                key={`clone-${it.key}`}
                item={it}
                ariaHidden
                onPlayerClick={(name) => {
                  if (typeof openPlayerPopup === "function") openPlayerPopup(name);
                }}
              />
            ))}
        </ul>
      </div>
    </div>
  );
}

function TickerSlot({ item, ariaHidden, onPlayerClick }) {
  if (item.kind === "mover") {
    const m = item.data;
    const direction = m.change > 0 ? "up" : "down";
    return (
      <li
        className={`ticker-item ticker-item--mover ticker-item--${direction}${
          m.onRoster ? " ticker-item--roster" : ""
        }`}
        aria-hidden={ariaHidden || undefined}
      >
        <button
          type="button"
          className="ticker-item-trigger"
          onClick={() => onPlayerClick?.(m.name)}
          title={`${m.name} — rank change ${m.change > 0 ? "+" : ""}${m.change}`}
        >
          {m.onRoster && <span className="ticker-item-dot" aria-hidden="true">●</span>}
          <span className="ticker-item-label">{m.name}</span>
          <span className="ticker-item-pos">{m.pos}</span>
          <span className="ticker-item-delta">{formatChange(m.change)}</span>
        </button>
      </li>
    );
  }

  // Alert
  const a = item.data;
  const firstPlayer = Array.isArray(a.players) ? a.players[0]?.name : null;
  return (
    <li
      className={`ticker-item ticker-item--alert ticker-item--sev-${a.severity}`}
      aria-hidden={ariaHidden || undefined}
    >
      <button
        type="button"
        className="ticker-item-trigger"
        onClick={() => firstPlayer && onPlayerClick?.(firstPlayer)}
        title={a.headline}
      >
        <span className="ticker-item-alert-tag">{a.severity.toUpperCase()}</span>
        <span className="ticker-item-headline">{a.headline}</span>
      </button>
    </li>
  );
}
