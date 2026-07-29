"use client";

import { useMemo } from "react";
import { useApp } from "@/components/AppShell";
import { useTeam } from "@/components/useTeam";
import { useRankHistory } from "@/components/useRankHistory";
import { useNews } from "@/components/useNews";
import { useUserState } from "@/components/useUserState";
import { evaluateRoster, SIGNALS } from "@/lib/signal-engine";
import { Badge, Movement, Panel } from "@/components/ds";
import styles from "./terminal.module.css";

/**
 * TopSignalsRail — compact "your team's top moves this week" rail.
 *
 * Sits above the terminal grid so the FIRST thing a signed-in user
 * sees is something specific to their roster, not a generic ranking.
 * Surfaces the top 3 SELL + top 3 BUY signals from the same engine
 * the deeper ``BuySellHold`` panel uses.
 *
 * The full panel below remains the place for bulk filtering,
 * dismissal management, and signal evidence.  This rail is a
 * scannable headline: one row of cards each labelled ``SELL`` or
 * ``BUY``, tap to open the player popup.
 *
 * Renders nothing when:
 *   - no team is selected (the league switcher hasn't resolved)
 *   - the roster has zero matched rows
 *   - both buckets are empty after dismissal filtering
 *
 * Hook usage mirrors ``BuySellHold`` so the underlying
 * ``useTerminal`` cache primed by ``TerminalLayout`` is shared and
 * the only redundant work is the local ``evaluateRoster`` pass —
 * cheap (sort + categorize a roster's worth of rows).
 */

const TOP_PER_BUCKET = 3;

function isDismissed(name, tag, dismissedMap, now) {
  const key = `${String(name).trim()}::${String(tag || "unknown").trim()}`;
  const expiresAt = Number(dismissedMap?.[key] || 0);
  return expiresAt > now;
}

function valueDelta(verdict) {
  // Pull a "what changed" hint for the card subtitle.  ``context.delta30d``
  // (30-day rank delta) is set by ``buildContext`` in signal-engine.js
  // when history is available — surface it as a +/- number so the card
  // shows direction-of-change at a glance.
  const d = Number(verdict?.context?.delta30d);
  return Number.isFinite(d) ? d : null;
}

function valueLabel(verdict) {
  const v = Number(verdict?.context?.value);
  return Number.isFinite(v) && v > 0 ? Math.round(v).toLocaleString() : null;
}

function SignalCard({ entry, tone, onOpen }) {
  const name = entry?.row?.name || entry?.context?.name || "";
  const pos = String(entry?.row?.position || entry?.context?.position || "").toUpperCase();
  const team = entry?.row?.team || "";
  const value = valueLabel(entry?.verdict);
  const delta = valueDelta(entry?.verdict);
  const evidence = entry?.verdict?.evidence?.[0] || "";
  const isSell = tone === "down";

  return (
    <button
      type="button"
      className={`${styles.signalCard} ${isSell ? styles.signalCardSell : styles.signalCardBuy}`}
      onClick={() => onOpen?.(name)}
      aria-label={`${isSell ? "Sell" : "Buy"} signal: ${name}`}
      title={evidence || name}
    >
      <span className={styles.signalHead}>
        <Badge tone={isSell ? "negative" : "positive"}>{isSell ? "SELL" : "BUY"}</Badge>
        {Number.isFinite(delta) && delta !== 0 && (
          <Movement
            delta={delta}
            format={(m) => `${m} ranks · 30d`}
            srLabel={`${delta > 0 ? "up" : "down"} ${Math.abs(delta)} ranks over 30 days`}
          />
        )}
      </span>
      <span className={styles.signalName}>{name}</span>
      <span className={styles.signalMeta}>
        {pos && <span className={styles.signalPos}>{pos}</span>}
        {team && <span>· {team}</span>}
        {value && <span>· {value}</span>}
      </span>
      {evidence && <span className={styles.signalEvidence}>{evidence}</span>}
    </button>
  );
}

export default function TopSignalsRail() {
  const { rows, openPlayerPopup } = useApp();
  const { selectedTeam, selectedLeagueKey, loading: teamLoading } = useTeam();
  const { history } = useRankHistory({ days: 30 });
  const { state: userState } = useUserState();

  const rosterNames = selectedTeam?.players || [];
  const news = useNews({ rosterNames, leagueNames: [] });
  const scoredNews = news.scored;

  // Per-league dismissals take precedence over the legacy flat map.
  // Mirrors the precedence ``BuySellHold`` uses — keeps "I dismissed
  // this in the panel" honored at the rail too.
  const dismissedMap = useMemo(() => {
    const leagueKey = selectedTeam ? selectedLeagueKey : "";
    const byLeague = userState?.dismissedSignalsByLeague;
    if (leagueKey && byLeague && typeof byLeague === "object") {
      const bucket = byLeague[leagueKey];
      if (bucket && typeof bucket === "object") return bucket;
    }
    return userState?.dismissedSignals || {};
  }, [userState?.dismissedSignalsByLeague, userState?.dismissedSignals, selectedLeagueKey, selectedTeam]);

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

  const { sells, buys, hasAny } = useMemo(() => {
    const now = Date.now();
    const sellsAll = [];
    const buysAll = [];
    for (const v of verdicts) {
      const sig = v?.verdict?.signal;
      const tag = v?.verdict?.tag;
      const name = v?.row?.name || v?.context?.name || "";
      if (!name) continue;
      if (isDismissed(name, tag, dismissedMap, now)) continue;
      if (sig === SIGNALS.SELL) sellsAll.push(v);
      else if (sig === SIGNALS.BUY) buysAll.push(v);
    }
    return {
      sells: sellsAll.slice(0, TOP_PER_BUCKET),
      buys: buysAll.slice(0, TOP_PER_BUCKET),
      sellsRemaining: Math.max(0, sellsAll.length - TOP_PER_BUCKET),
      buysRemaining: Math.max(0, buysAll.length - TOP_PER_BUCKET),
      hasAny: sellsAll.length > 0 || buysAll.length > 0,
    };
  }, [verdicts, dismissedMap]);

  // While the team is still resolving, hold a height-stable placeholder
  // instead of nothing — this rail sits ABOVE the whole grid, so
  // popping in later shifted every panel below it (part of the
  // measured 0.72 CLS on /).  Once loaded-and-empty it still collapses
  // (a one-time settle) — reserving forever would leave a permanent
  // hole in the "act on this" lane.
  if (!selectedTeam) {
    return teamLoading ? (
      <div className={styles.railGrid} style={{ minHeight: 150 }} aria-hidden="true" />
    ) : null;
  }
  // Render nothing when there's nothing actionable.  The full
  // ``BuySellHold`` panel below still surfaces RISK/MONITOR/HOLD —
  // this rail intentionally focuses on the two clear "trade now"
  // categories.
  //
  // ``news.loading`` is part of the hold, not just the team: signals
  // are scored from news, so a team that resolves BEFORE the news
  // fetch lands computes hasAny=false, collapses the reserved slot,
  // and then re-expands when news arrives — shifting the entire grid
  // below it.  That second window was the residual 0.09 CLS on / after
  // the team-resolution hold was added.
  if (!hasAny) {
    return news.loading ? (
      <div className={styles.railGrid} style={{ minHeight: 150 }} aria-hidden="true" />
    ) : null;
  }

  return (
    <Panel
      title="This week's top moves"
      subtitle="Top 3 buy and sell candidates on your roster"
    >
      <div className={styles.railGrid}>
        {sells.map((v) => (
          <SignalCard key={`sell-${v.row?.name}`} entry={v} tone="down" onOpen={openPlayerPopup} />
        ))}
        {buys.map((v) => (
          <SignalCard key={`buy-${v.row?.name}`} entry={v} tone="up" onOpen={openPlayerPopup} />
        ))}
      </div>
    </Panel>
  );
}
