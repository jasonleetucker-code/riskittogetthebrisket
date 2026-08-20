"use client";

import { useEffect, useMemo, useState } from "react";
import { useApp } from "@/components/AppShell";
import { useTeam } from "@/components/useTeam";
import { useNews } from "@/components/useNews";
import { Movement, SegmentedControl } from "@/components/ds";
import { computeMovers } from "@/lib/market-movers";
import { selectTickerAlerts, timeAgo } from "@/lib/news-service";
import styles from "./market-ticker.module.css";

const SCOPE_OPTIONS = [
  { value: "roster", label: "My Roster" },
  { value: "league", label: "League" },
  { value: "top150", label: "Top 150" },
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

// Freshness ticks once a minute so the "as of" label stays honest
// without re-rendering on every animation frame.
function useNow(intervalMs = 60000) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), intervalMs);
    return () => clearInterval(id);
  }, [intervalMs]);
  return now;
}

export default function MarketTicker() {
  const { rows, rawData, openPlayerPopup } = useApp();
  const { selectedTeam } = useTeam();
  const sleeperTeams = rawData?.sleeper?.teams;
  const leagueNames = useLeagueNames(sleeperTeams);
  const reducedMotion = usePrefersReducedMotion();
  const now = useNow();

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

  // Backend-stamped freshness, verbatim — never a client-computed
  // "just now" until a real timestamp is missing.
  const freshness =
    typeof rawData?.generatedAt === "string" ? timeAgo(rawData.generatedAt, now) : null;

  const scopeSwitch = (
    <div className={styles.rail}>
      <span className={styles.railLabel}>Scope</span>
      <SegmentedControl
        label="Ticker scope"
        value={scope}
        onChange={setScope}
        options={SCOPE_OPTIONS}
      />
      {freshness ? (
        <span className={styles.freshness}>Updated {freshness} ago</span>
      ) : null}
    </div>
  );

  if (items.length < MIN_RENDERABLE) {
    const scopeLabel =
      SCOPE_OPTIONS.find((o) => o.value === scope)?.label || "Roster";
    return (
      <div className={`${styles.ticker} ${styles.quiet}`} role="region" aria-label="Market ticker">
        {scopeSwitch}
        <div className={styles.quietMsg}>
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
      className={styles.ticker}
      role="region"
      aria-label="Market ticker"
      onMouseEnter={() => setPaused(true)}
      onMouseLeave={() => setPaused(false)}
    >
      {scopeSwitch}
      <div className={styles.strip}>
        <ul
          className={`${styles.track}${animate ? ` ${styles.trackAnimated}` : ""}`}
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
    return (
      <li
        className={`${styles.item} ${m.onRoster ? styles.itemRoster : ""}`.trim()}
        aria-hidden={ariaHidden || undefined}
      >
        <button
          type="button"
          className={styles.itemTrigger}
          onClick={() => onPlayerClick?.(m.name)}
        >
          {m.onRoster && (
            <span className={styles.itemDot} aria-hidden="true">
              ●
            </span>
          )}
          <span className={styles.itemLabel}>{m.name}</span>
          <span className={styles.itemPos}>{m.pos}</span>
          <Movement delta={m.change} confidence={m.confidence} />
        </button>
      </li>
    );
  }

  // Alert
  const a = item.data;
  const firstPlayer = Array.isArray(a.players) ? a.players[0]?.name : null;
  const sevClass =
    a.severity === "watch"
      ? styles.itemAlertSevWatch
      : a.severity === "info"
        ? styles.itemAlertSevInfo
        : "";
  return (
    <li className={`${styles.item} ${styles.itemAlert}`} aria-hidden={ariaHidden || undefined}>
      <button
        type="button"
        className={styles.itemTrigger}
        onClick={() => firstPlayer && onPlayerClick?.(firstPlayer)}
        title={a.headline}
      >
        <span className={`${styles.itemAlertTag} ${sevClass}`.trim()}>
          {a.severity.toUpperCase()}
        </span>
        <span className={styles.itemHeadline}>{a.headline}</span>
      </button>
    </li>
  );
}
