"use client";

import { useEffect, useMemo, useState } from "react";
import { useApp } from "@/components/AppShell";
import { useAuthContext } from "@/app/AppShellWrapper";
import { useTeam } from "@/components/useTeam";
import { useNews } from "@/components/useNews";
import { useReconciledSignals } from "@/components/useReconciledSignals";
import { Badge } from "@/components/ds";
import {
  lineageText,
  selectTickerVerdicts,
  sellScopeText,
  unobservedEmitters,
} from "@/lib/signal-ticker";
import { selectTickerAlerts, timeAgo } from "@/lib/news-service";
import styles from "./market-ticker.module.css";

/**
 * Homepage Buy/Sell ticker (C6-SIG-02, #784, inventory 4.3).
 *
 * PRESENTATION ONLY over the one Buy/Sell owner, the C6-SIG-01 reconciler
 * (`/api/signals/reconciled`).  BUY items are league-wide; SELL items are
 * limited to the selected team's roster; a conflict renders as a conflict;
 * withheld players never appear.  Every rule lives in `lib/signal-ticker.js`
 * and decides no verdict.
 *
 * Inventory 4.3 recorded this strip as "existing, wrong source": it used to
 * show rank movers from a page-local `computeMovers`.  Rank movers still have
 * their own panel on this page (MoversPanel, `/api/terminal` movers); the
 * ticker now carries canonical verdicts instead.  News alerts keep their
 * interleaved slots — they are not verdicts and are labelled as alerts.
 *
 * Private: the reconciler 401s without a session, so the lane renders only
 * for an authenticated private shell and fails closed (no verdicts) on any
 * auth refusal.
 */

// Under this many slots a looping marquee reads as static, so the slots
// render in place without animation (never hidden — a real verdict is not
// "quiet").
const MIN_ANIMATED = 3;
// Whole-strip cap: roster SELL/CONFLICT first, then BUYs fill the rest.
const TICKER_LIMIT = 20;

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

function freshnessText(payload, now) {
  const at = payload?.contract?.generatedAt || payload?.contract?.scrapeTimestamp;
  const age = typeof at === "string" ? timeAgo(at, now) : null;
  const market = payload?.contract?.marketFreshness?.state;
  const base = age && age !== "—" ? `Board ${age} ago` : "Board age unknown";
  if (market === "stale") return `${base} · market data stale`;
  if (market !== "fresh") return `${base} · market freshness unknown`;
  return base;
}

function quietMessage(status, payload) {
  if (status === "league_mismatch") {
    return "Buy/Sell signals unavailable — they were built for a different league.";
  }
  if (status === "loading" || status === "idle") return "Loading Buy/Sell signals…";
  if (status === "unauthorized") return "Sign in to see Buy/Sell signals.";
  if (status === "unavailable") return "Buy/Sell signals unavailable — board data not ready.";
  if (status === "error") return "Buy/Sell signals unavailable right now.";
  const missing = unobservedEmitters(payload).length;
  return missing > 0
    ? `No Buy/Sell verdicts to show — ${missing} signal source${missing === 1 ? "" : "s"} did not run.`
    : "No Buy/Sell verdicts to show.";
}

export default function MarketTicker() {
  const { rawData, openPlayerPopup, privateDataEnabled } = useApp();
  const { authenticated } = useAuthContext();
  const { selectedTeam, selectedLeagueKey, loading: teamLoading } = useTeam();
  const sleeperTeams = rawData?.sleeper?.teams;
  const leagueNames = useLeagueNames(sleeperTeams);
  const reducedMotion = usePrefersReducedMotion();
  const now = useNow();
  const [paused, setPaused] = useState(false);

  // Private verdicts only for a signed-in private shell; wait for team
  // identity so one request is made for the team actually selected.
  const enabled = Boolean(privateDataEnabled) && authenticated === true && !teamLoading;
  const signals = useReconciledSignals({
    enabled,
    leagueKey: selectedLeagueKey || "",
    ownerId: selectedTeam?.ownerId ? String(selectedTeam.ownerId) : "",
    teamName: selectedTeam?.ownerId ? "" : selectedTeam?.name || "",
  });
  const verdictsVisible = signals.status === "ok" && authenticated === true;
  // Anything short of a signed-in private shell reads as "sign in" — never
  // as "no verdicts", which would be a claim about the market.
  const displayStatus =
    Boolean(privateDataEnabled) && authenticated === true ? signals.status : "unauthorized";

  // Single shared news fetch via the module-level cache in useNews.
  const rosterNames = selectedTeam?.players || [];
  const newsState = useNews({ rosterNames, leagueNames });

  const selection = useMemo(
    () =>
      verdictsVisible
        ? selectTickerVerdicts(signals.payload, {
            selectedTeam,
            selectedLeagueKey: selectedLeagueKey || "",
            limit: TICKER_LIMIT,
          })
        : null,
    [verdictsVisible, signals.payload, selectedTeam, selectedLeagueKey],
  );

  const alerts = useMemo(() => {
    if (newsState.loading || newsState.items.length === 0) return [];
    return selectTickerAlerts(newsState.scored, { limit: 3 });
  }, [newsState]);

  // Interleave: every 5th slot is an alert, as before.
  const items = useMemo(() => {
    const verdicts = selection?.items || [];
    const out = [];
    let a = 0;
    for (let i = 0; i < verdicts.length; i++) {
      out.push({ kind: "verdict", data: verdicts[i], key: verdicts[i].key });
      if ((i + 1) % 5 === 0 && a < alerts.length) {
        out.push({ kind: "alert", data: alerts[a], key: `a-${alerts[a].id}` });
        a += 1;
      }
    }
    // Leftover alerts only alongside verdicts — a strip of alerts alone
    // would read as the Buy/Sell ticker having nothing to say.
    while (verdicts.length > 0 && a < alerts.length) {
      out.push({ kind: "alert", data: alerts[a], key: `a-${alerts[a].id}` });
      a += 1;
    }
    return out;
  }, [selection, alerts]);

  const teamName = selectedTeam?.name || "";
  const rail = (
    <div className={styles.rail}>
      <span className={styles.railLabel}>Buy / Sell</span>
      {verdictsVisible && selection && !selection.leagueMismatch ? (
        <>
          <span className={styles.freshness}>{sellScopeText(selection.sellScope, teamName)}</span>
          <span className={styles.freshness}>{freshnessText(signals.payload, now)}</span>
        </>
      ) : null}
    </div>
  );

  const hasVerdicts = (selection?.items?.length || 0) > 0;
  if (!hasVerdicts) {
    return (
      <div
        className={`${styles.ticker} ${styles.quiet}`}
        role="region"
        aria-label="Buy/Sell ticker"
        aria-busy={displayStatus === "loading" || undefined}
      >
        {rail}
        <div className={styles.quietMsg}>
          {quietMessage(selection?.leagueMismatch ? "league_mismatch" : displayStatus, signals.payload)}
        </div>
      </div>
    );
  }

  const animate = !reducedMotion && !paused && items.length >= MIN_ANIMATED;
  const onPlayerClick = (name) => {
    if (typeof openPlayerPopup === "function") openPlayerPopup(name);
  };

  return (
    <div
      className={styles.ticker}
      role="region"
      aria-label="Buy/Sell ticker"
      onMouseEnter={() => setPaused(true)}
      onMouseLeave={() => setPaused(false)}
      onFocus={() => setPaused(true)}
      onBlur={() => setPaused(false)}
    >
      {rail}
      <div className={styles.strip}>
        <ul
          className={`${styles.track}${animate ? ` ${styles.trackAnimated}` : ""}`}
          style={animate ? { animationDuration: `${Math.max(30, items.length * 4)}s` } : undefined}
        >
          {items.map((it) => (
            <TickerSlot key={it.key} item={it} onPlayerClick={onPlayerClick} />
          ))}
          {/* Cloned track for the seamless marquee.  Hidden from AT and
              out of the tab order. */}
          {animate &&
            items.map((it) => (
              <TickerSlot key={`clone-${it.key}`} item={it} ariaHidden onPlayerClick={onPlayerClick} />
            ))}
        </ul>
      </div>
    </div>
  );
}

const VERDICT_BADGE = {
  buy: { tone: "positive", label: "BUY" },
  sell: { tone: "negative", label: "SELL" },
  // A conflict is neither direction; outline claims no market state.
  conflict: { tone: "outline", label: "CONFLICT" },
};

function lineageTitle(lineage) {
  if (!lineage) return undefined;
  const parts = [];
  if (lineage.sharedAncestry?.length) parts.push(`Shared lineage: ${lineage.sharedAncestry.join(", ")}`);
  if (lineage.collapsed) parts.push(`${lineage.collapsed} restatement(s) collapsed`);
  return parts.length ? parts.join(" · ") : undefined;
}

function TickerSlot({ item, ariaHidden, onPlayerClick }) {
  if (item.kind === "verdict") {
    const v = item.data;
    const badge = VERDICT_BADGE[v.kind];
    const lineage = lineageText(v.lineage);
    return (
      <li
        className={styles.item}
        aria-hidden={ariaHidden || undefined}
        data-verdict={v.kind}
      >
        <button
          type="button"
          className={styles.itemTrigger}
          onClick={() => onPlayerClick?.(v.name)}
          tabIndex={ariaHidden ? -1 : undefined}
          aria-label={`${badge.label} ${v.name}${lineage ? `, ${lineage}` : ""}`}
          title={lineageTitle(v.lineage)}
        >
          <Badge tone={badge.tone}>{badge.label}</Badge>
          <span className={styles.itemLabel}>{v.name}</span>
          {v.position ? <span className={styles.itemPos}>{v.position}</span> : null}
          {lineage ? <span className={styles.itemLineage}>{lineage}</span> : null}
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
        tabIndex={ariaHidden ? -1 : undefined}
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
