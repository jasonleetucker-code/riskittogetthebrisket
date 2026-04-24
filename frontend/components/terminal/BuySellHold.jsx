"use client";

import { useMemo, useState } from "react";
import { useApp } from "@/components/AppShell";
import { useTeam } from "@/components/useTeam";
import { useRankHistory } from "@/components/useRankHistory";
import { useNews } from "@/components/useNews";
import { useUserState } from "@/components/useUserState";
import { useTerminal } from "@/components/useTerminal";
import {
  evaluateRoster,
  SIGNAL_META,
  SIGNALS,
} from "@/lib/signal-engine";
import Panel from "./Panel";

const DISMISSAL_TTL_MS = 7 * 24 * 60 * 60 * 1000;

function signalKey(name, tag) {
  return `${String(name).trim()}::${String(tag || "unknown").trim()}`;
}

function aliasSignalKey(sleeperId, tag) {
  const sid = String(sleeperId || "").trim();
  if (!sid) return "";
  return `sid:${sid}::${String(tag || "unknown").trim()}`;
}

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
  const { selectedTeam, selectedLeagueKey } = useTeam();
  const { history, loading: historyLoading } = useRankHistory({ days: 30 });
  const {
    state: userState,
    dismissSignal,
    restoreSignal,
    serverBacked,
  } = useUserState();
  // Server-side signals carry ``injuryImpact`` + ``injuryAdjustedValue``
  // fields that the client-side ``evaluateRoster`` can't produce
  // (news rulebook lives in Python).  We merge by name into the
  // local verdicts below so every card renders the injury chip
  // when applicable.
  const { signals: serverSignals } = useTerminal({
    ownerId: String(selectedTeam?.ownerId || ""),
    teamName: selectedTeam?.name || "",
    windowDays: 30,
  });
  const injuryByName = useMemo(() => {
    const m = new Map();
    for (const s of serverSignals || []) {
      if (!s?.name || !s?.injuryImpact) continue;
      m.set(String(s.name).toLowerCase(), {
        impact: s.injuryImpact,
        adjustedValue: s.injuryAdjustedValue,
      });
    }
    return m;
  }, [serverSignals]);

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
  const [showDismissed, setShowDismissed] = useState(false);

  // Build a sleeperId lookup from rawData.players so dismissal
  // records can carry the stable alias.
  const sleeperIdByName = useMemo(() => {
    const m = new Map();
    const legacy = rawData?.players;
    if (legacy && typeof legacy === "object") {
      for (const name of Object.keys(legacy)) {
        const p = legacy[name];
        const sid = p?._sleeperId || p?.sleeperId;
        if (sid) m.set(String(name).toLowerCase(), String(sid));
      }
    }
    return m;
  }, [rawData]);

  // Per-league dismissals take precedence over the legacy flat map.
  // ``useTeam().selectedLeagueKey`` tells us which league's bucket
  // to read; for pre-migration users on the default league the flat
  // map is used as a fallback so their existing dismissals carry
  // over.  ``useLeague`` can't be imported here without pulling a
  // larger context cycle — we read the active league key off the
  // team hook which already resolves it.
  const dismissedMap = useMemo(() => {
    const leagueKey = selectedTeam ? selectedLeagueKey : "";
    const byLeague = userState?.dismissedSignalsByLeague;
    if (leagueKey && byLeague && typeof byLeague === "object") {
      const bucket = byLeague[leagueKey];
      if (bucket && typeof bucket === "object") return bucket;
    }
    return userState?.dismissedSignals || {};
  }, [userState?.dismissedSignalsByLeague, userState?.dismissedSignals, selectedLeagueKey, selectedTeam]);

  const rosterNames = selectedTeam?.players || [];
  const news = useNews({ rosterNames, leagueNames });

  // useNews returns its items already scored for the rule engine —
  // no per-component re-ranking needed.
  const scoredNews = news.scored;

  const rawVerdicts = useMemo(
    () =>
      evaluateRoster({
        rows,
        selectedTeam,
        history,
        newsItems: scoredNews,
      }),
    [rows, selectedTeam, history, scoredNews],
  );

  // Attach dismissal state.  A signal is dismissed when EITHER the
  // display-name key (``<name>::<tag>``) OR the rename-resistant
  // alias (``sid:<sleeperId>::<tag>``) has an entry with
  // expiresAt > now.  Two keys so a later rename doesn't un-dismiss.
  const now = Date.now();
  const verdicts = useMemo(() => {
    return rawVerdicts.map((v) => {
      const name = v.row?.name || v.context?.name || "";
      const tag = v.verdict?.tag || "unknown";
      const primary = signalKey(name, tag);
      const sid = sleeperIdByName.get(String(name).toLowerCase()) || "";
      const alias = aliasSignalKey(sid, tag);
      const primaryExp = Number(dismissedMap[primary] || 0);
      const aliasExp = alias ? Number(dismissedMap[alias] || 0) : 0;
      const expiresAt = Math.max(primaryExp, aliasExp);
      const injury = injuryByName.get(String(name).toLowerCase()) || null;
      return {
        ...v,
        signalKey: primary,
        aliasSignalKey: alias,
        sleeperId: sid,
        dismissedUntil: expiresAt || null,
        dismissed: expiresAt > now,
        injuryImpact: injury?.impact || null,
        injuryAdjustedValue: injury?.adjustedValue ?? null,
      };
    });
  }, [rawVerdicts, dismissedMap, sleeperIdByName, now]);

  const counts = useMemo(() => {
    const c = Object.fromEntries(FILTER_ORDER.map((s) => [s, 0]));
    for (const v of verdicts) {
      if (v.dismissed && !showDismissed) continue;
      c[v.verdict.signal] = (c[v.verdict.signal] || 0) + 1;
    }
    return c;
  }, [verdicts, showDismissed]);

  const visible = useMemo(
    () =>
      verdicts.filter((v) => {
        if (v.dismissed && !showDismissed) return false;
        return filters.has(v.verdict.signal);
      }),
    [verdicts, filters, showDismissed],
  );

  const dismissedCount = useMemo(
    () => verdicts.filter((v) => v.dismissed).length,
    [verdicts],
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
      actions={
        dismissedCount > 0 ? (
          <button
            type="button"
            className={`panel-tab${showDismissed ? " is-active" : ""}`}
            onClick={() => setShowDismissed((v) => !v)}
            title={
              serverBacked
                ? "Dismissals sync across your devices"
                : "Dismissals saved locally (sign in to sync)"
            }
          >
            {showDismissed ? "Hide dismissed" : `Dismissed (${dismissedCount})`}
          </button>
        ) : null
      }
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
              key={entry.signalKey || entry.row.name}
              entry={entry}
              expanded={expandedId === (entry.signalKey || entry.row.name)}
              onToggleExpand={() =>
                setExpandedId((prev) =>
                  prev === (entry.signalKey || entry.row.name)
                    ? null
                    : entry.signalKey || entry.row.name,
                )
              }
              onOpenPlayer={() => openPlayerPopup?.(entry.row.name)}
              onDismiss={() => {
                const key = entry.aliasSignalKey || entry.signalKey;
                dismissSignal(key, DISMISSAL_TTL_MS, {
                  aliasSleeperId: entry.sleeperId || undefined,
                  aliasDisplayName: entry.row.name || undefined,
                });
              }}
              onRestore={() => {
                if (entry.signalKey) restoreSignal(entry.signalKey);
                if (entry.aliasSignalKey) restoreSignal(entry.aliasSignalKey);
              }}
            />
          ))}
        </ul>
      )}
    </Panel>
  );
}

function SignalCard({ entry, expanded, onToggleExpand, onOpenPlayer, onDismiss, onRestore }) {
  const { context, verdict } = entry;
  const meta = SIGNAL_META[verdict.signal];
  const volLabel = context.volatility?.label ?? "—";

  return (
    <li
      className={`signal-card signal-card--${meta.tone}${
        entry.dismissed ? " signal-card--dismissed" : ""
      }`}
    >
      <div className="signal-card-top">
        <button type="button" className="signal-card-name-btn" onClick={onOpenPlayer} title={`Open ${context.name}`}>
          <span className="signal-card-name">{context.name}</span>
          <span className="signal-card-pos">{context.pos}</span>
          <span className="signal-card-value">{context.value.toLocaleString()}</span>
        </button>
        <span className={`signal-badge signal-badge--${meta.tone}`}>{meta.label}</span>
      </div>
      <div className="signal-card-rationale">{verdict.reason}</div>
      {entry.injuryImpact && (
        <InjuryChip impact={entry.injuryImpact} adjustedValue={entry.injuryAdjustedValue} />
      )}
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
        {entry.dismissed ? (
          <button
            type="button"
            className="signal-card-dismiss signal-card-dismiss--restore"
            onClick={onRestore}
            title="Resurface this signal"
          >
            Restore
          </button>
        ) : (
          <button
            type="button"
            className="signal-card-dismiss"
            onClick={onDismiss}
            title="Dismiss for 7 days"
          >
            Dismiss
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

/**
 * InjuryChip — shows the server-side injury impact so the signal
 * card explains WHY value dropped when news is the reason.
 *
 * The impact shape comes from ``src/api/injury_impact.py`` and
 * carries ``appliedDiscountPct`` + ``severity`` + ``headline`` +
 * ``offseasonSuppressed``.  We render:
 *
 *   - In-season: "⚠ -3.2% (alert) · ACL update" with a title
 *     tooltip showing the full rulebook math
 *   - Offseason: muted "Injury news (offseason — suppressed)"
 *     so the user sees the news exists but knows we didn't
 *     reprice them (dynasty-horizon rule)
 */
function InjuryChip({ impact, adjustedValue }) {
  if (!impact) return null;
  const offseason = !!impact.offseasonSuppressed;
  const discount = Number(impact.appliedDiscountPct) || 0;
  const severity = impact.severity || "";
  const headline = impact.headline || "";

  if (offseason) {
    return (
      <div
        className="signal-card-injury signal-card-injury--offseason"
        title={`News: ${headline}\n(Suppressed — NFL offseason; dynasty value unaffected)`}
      >
        <span aria-hidden="true">⚪</span>
        <span>Injury news · offseason (no reprice)</span>
      </div>
    );
  }
  const tooltipParts = [
    `Severity: ${severity || "unknown"}`,
    `Applied discount: ${discount.toFixed(2)}%`,
    `Adjusted value: ${Number.isFinite(Number(adjustedValue)) ? Number(adjustedValue).toLocaleString() : "—"}`,
    impact.headline ? `News: ${headline}` : null,
  ].filter(Boolean);
  return (
    <div
      className="signal-card-injury"
      title={tooltipParts.join("\n")}
      role="note"
    >
      <span aria-hidden="true">⚠</span>
      <span className="signal-card-injury-pct">-{discount.toFixed(discount < 1 ? 2 : 1)}%</span>
      {severity && (
        <span className="signal-card-injury-severity">{severity}</span>
      )}
      {headline && (
        <span className="signal-card-injury-headline">{headline}</span>
      )}
    </div>
  );
}
