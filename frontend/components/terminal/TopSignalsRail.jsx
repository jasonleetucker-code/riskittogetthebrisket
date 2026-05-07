"use client";

import { useMemo } from "react";
import { useApp } from "@/components/AppShell";
import { useTeam } from "@/components/useTeam";
import { useRankHistory } from "@/components/useRankHistory";
import { useNews } from "@/components/useNews";
import { useUserState } from "@/components/useUserState";
import { evaluateRoster, SIGNALS } from "@/lib/signal-engine";

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

  return (
    <button
      type="button"
      className={`top-signal-card top-signal-card--${tone}`}
      onClick={() => onOpen?.(name)}
      aria-label={`${tone === "down" ? "Sell" : "Buy"} signal: ${name}`}
      title={evidence || name}
    >
      <div className="top-signal-card-head">
        <span className={`top-signal-card-tag top-signal-card-tag--${tone}`}>
          {tone === "down" ? "SELL" : "BUY"}
        </span>
        {Number.isFinite(delta) && delta !== 0 && (
          <span className={`top-signal-card-delta top-signal-card-delta--${delta < 0 ? "down" : "up"}`}>
            {delta > 0 ? "▲" : "▼"} {Math.abs(delta)} ranks · 30d
          </span>
        )}
      </div>
      <div className="top-signal-card-name">{name}</div>
      <div className="top-signal-card-meta">
        {pos && <span className="top-signal-card-pos">{pos}</span>}
        {team && <span className="muted">· {team}</span>}
        {value && <span className="muted">· {value}</span>}
      </div>
      {evidence && (
        <div className="top-signal-card-evidence">
          {evidence}
        </div>
      )}
    </button>
  );
}

export default function TopSignalsRail() {
  const { rows, openPlayerPopup } = useApp();
  const { selectedTeam, selectedLeagueKey } = useTeam();
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

  // Render nothing when there's nothing actionable.  The full
  // ``BuySellHold`` panel below still surfaces RISK/MONITOR/HOLD —
  // this rail intentionally focuses on the two clear "trade now"
  // categories.
  if (!selectedTeam) return null;
  if (!hasAny) return null;

  return (
    <section className="top-signals-rail" aria-label="Top trade signals for your roster">
      <div className="top-signals-rail-header">
        <span className="top-signals-rail-title">This week's top moves</span>
        <span className="top-signals-rail-subtitle muted">
          Top 3 buy / sell candidates from your roster
        </span>
      </div>
      <div className="top-signals-rail-grid">
        {sells.map((v) => (
          <SignalCard
            key={`sell-${v.row?.name}`}
            entry={v}
            tone="down"
            onOpen={openPlayerPopup}
          />
        ))}
        {buys.map((v) => (
          <SignalCard
            key={`buy-${v.row?.name}`}
            entry={v}
            tone="up"
            onOpen={openPlayerPopup}
          />
        ))}
      </div>
    </section>
  );
}
