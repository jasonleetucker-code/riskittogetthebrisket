"use client";

import { useMemo, useState } from "react";
import { useApp } from "@/components/AppShell";
import { useTeam } from "@/components/useTeam";
import { useNews } from "@/components/useNews";
import { PageHeader, EmptyState } from "@/components/ui";
import { filterByScope, timeAgo } from "@/lib/news-service";
import { itemPlayerNames, normalizePlayerNameKey } from "@/lib/player-name-match";
import { buildPlayerMetaIndex, filterByPlayerFacets } from "@/lib/news-filters";

// ── Filter option sets ───────────────────────────────────────────────────
// Scope reuses the exact roster-scoping model from the terminal
// TeamNewsFeed: relevance is scored by useNews/rankByRelevance against
// the selected team's roster + the league-wide player pool, then
// filterByScope slices on the score.
const SCOPE_TABS = [
  { key: "roster", label: "My Roster" },
  { key: "league", label: "League" },
  { key: "all", label: "All" },
];

const POSITION_OPTIONS = [
  { key: "ALL", label: "All" },
  { key: "QB", label: "QB" },
  { key: "RB", label: "RB" },
  { key: "WR", label: "WR" },
  { key: "TE", label: "TE" },
  { key: "DL", label: "DL" },
  { key: "LB", label: "LB" },
  { key: "DB", label: "DB" },
];

const MAX_ITEMS = 100;

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

// Map normalized player-name key → { team, family } from the live
// contract rows so news items can be filtered by NFL team / position
// even though NewsItems only carry player names.
function usePlayerMeta(rows) {
  return useMemo(() => buildPlayerMetaIndex(rows), [rows]);
}

function FilterPills({ options, value, onChange, ariaLabel }) {
  return (
    <div
      role="tablist"
      aria-label={ariaLabel}
      style={{ display: "flex", flexWrap: "wrap", gap: 4 }}
    >
      {options.map((opt) => {
        const active = opt.key === value;
        return (
          <button
            key={opt.key}
            role="tab"
            aria-selected={active}
            onClick={() => onChange(opt.key)}
            className={active ? "button" : "button-outline"}
            style={{
              fontSize: "0.74rem",
              padding: "4px 10px",
              minHeight: 32,
              opacity: active ? 1 : 0.78,
            }}
          >
            {opt.label}
          </button>
        );
      })}
    </div>
  );
}

export default function NewsPage() {
  const { rows, rawData, openPlayerPopup } = useApp();
  const { selectedTeam } = useTeam();
  const leagueNames = useLeagueNames(rawData?.sleeper?.teams);
  const rosterNames = selectedTeam?.players || [];
  const news = useNews({ rosterNames, leagueNames });
  const playerMeta = usePlayerMeta(rows);

  const [scope, setScope] = useState("all");
  const [query, setQuery] = useState("");
  const [teamFilter, setTeamFilter] = useState("ALL");
  const [posFilter, setPosFilter] = useState("ALL");
  const [sourceFilter, setSourceFilter] = useState("ALL");

  // Source options from whatever the live feed actually contains.
  const sourceOptions = useMemo(() => {
    const byKey = new Map();
    for (const item of news.items) {
      const key = String(item?.provider || "").trim();
      if (!key || byKey.has(key)) continue;
      byKey.set(key, String(item?.providerLabel || key));
    }
    return [...byKey.entries()]
      .map(([key, label]) => ({ key, label }))
      .sort((a, b) => a.label.localeCompare(b.label));
  }, [news.items]);

  // NFL team options from the live board (stable regardless of feed).
  // Each index entry is a LIST of candidate metas (name-collision
  // players carry several).
  const teamOptions = useMemo(() => {
    const teams = new Set();
    for (const metas of playerMeta.values()) {
      for (const m of metas) {
        if (m.team) teams.add(m.team);
      }
    }
    return [...teams].sort();
  }, [playerMeta]);

  const filtered = useMemo(() => {
    let items = filterByScope(news.scored, scope);

    // Team + position must be satisfied by a SINGLE mention at once —
    // see filterByPlayerFacets for the conjunction-per-mention rule.
    items = filterByPlayerFacets(items, { teamFilter, posFilter, playerMeta });

    if (sourceFilter !== "ALL") {
      items = items.filter(
        (item) => String(item?.provider || "") === sourceFilter,
      );
    }

    const q = query.trim().toLowerCase();
    if (q) {
      const qKey = normalizePlayerNameKey(q);
      items = items.filter((item) => {
        const text = `${item?.headline || ""}\n${item?.body || ""}`.toLowerCase();
        if (text.includes(q)) return true;
        return itemPlayerNames(item).some((n) => {
          const key = normalizePlayerNameKey(n);
          return key && qKey && key.includes(qKey);
        });
      });
    }

    return items.slice(0, MAX_ITEMS);
  }, [news.scored, scope, teamFilter, posFilter, sourceFilter, query, playerMeta]);

  return (
    <section>
      <PageHeader
        title="News"
        subtitle="Aggregated player news, articles, and trending signals across every source."
      />

      {news.unavailable && (
        <div
          className="card"
          role="alert"
          style={{
            borderColor: "var(--red)",
            marginBottom: "var(--space-md)",
          }}
        >
          <strong style={{ color: "var(--red)" }}>News unavailable</strong>
          <div className="muted" style={{ fontSize: "0.78rem", marginTop: 4 }}>
            {news.reason === "fetch_failed"
              ? "Could not reach the news endpoint. Check your connection and reload."
              : "The news backend is temporarily unavailable. This page will recover once it responds again — nothing is cached or simulated."}
          </div>
        </div>
      )}

      <div className="card" style={{ marginBottom: "var(--space-md)" }}>
        <div
          style={{
            display: "flex",
            flexWrap: "wrap",
            gap: 12,
            alignItems: "center",
          }}
        >
          <FilterPills
            options={SCOPE_TABS}
            value={scope}
            onChange={setScope}
            ariaLabel="News scope"
          />
          <input
            type="search"
            className="input"
            placeholder="Search player or headline…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            aria-label="Search news by player or headline"
            style={{ flex: "1 1 220px", minWidth: 180 }}
          />
          <select
            className="select"
            value={teamFilter}
            onChange={(e) => setTeamFilter(e.target.value)}
            aria-label="Filter by NFL team"
            style={{ minWidth: 110 }}
          >
            <option value="ALL">All teams</option>
            {teamOptions.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
          <select
            className="select"
            value={sourceFilter}
            onChange={(e) => setSourceFilter(e.target.value)}
            aria-label="Filter by source"
            style={{ minWidth: 140 }}
          >
            <option value="ALL">All sources</option>
            {sourceOptions.map((s) => (
              <option key={s.key} value={s.key}>
                {s.label}
              </option>
            ))}
          </select>
        </div>
        <div style={{ marginTop: 10 }}>
          <FilterPills
            options={POSITION_OPTIONS}
            value={posFilter}
            onChange={setPosFilter}
            ariaLabel="Filter by position"
          />
        </div>
      </div>

      <div className="card">
        {news.loading && <NewsSkeleton rows={6} />}

        {!news.loading && news.unavailable && (
          <EmptyState
            title="No news to show"
            message="The feed is offline right now — try again in a few minutes."
          />
        )}

        {!news.loading && !news.unavailable && filtered.length === 0 && (
          <EmptyState
            title="No matching news"
            message={
              scope === "roster"
                ? "No roster-relevant headlines match these filters. Widen the scope or clear a filter."
                : "No headlines match these filters. Try clearing the search or filters."
            }
          />
        )}

        {!news.loading && !news.unavailable && filtered.length > 0 && (
          <ul className="news-feed">
            {filtered.map((item) => (
              <NewsRow
                key={item.id || `${item.ts}-${item.headline}`}
                item={item}
                onPlayerClick={openPlayerPopup}
              />
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}

function NewsRow({ item, onPlayerClick }) {
  const matched = Array.isArray(item.__matchedOn) ? item.__matchedOn : [];
  const sevClass = `news-item--sev-${item.severity || "info"}`;
  const rosterClass = item.__relevance >= 100 ? " news-item--roster" : "";

  return (
    <li className={`news-item ${sevClass}${rosterClass}`}>
      <div className="news-item-meta">
        <span className="news-item-time">{timeAgo(item.ts)}</span>
        <span className="news-item-provider">
          {item.providerLabel || item.provider || "—"}
        </span>
        {item.severity && (
          <span
            className={`news-item-severity news-item-severity--${item.severity}`}
          >
            {item.severity}
          </span>
        )}
      </div>
      <h3 className="news-item-headline">
        {item.url ? (
          <a
            href={item.url}
            target="_blank"
            rel="noopener noreferrer"
            style={{ color: "inherit", textDecoration: "none" }}
            title="Open source article"
          >
            {item.headline}
          </a>
        ) : (
          item.headline
        )}
      </h3>
      {item.body && <p className="news-item-body">{item.body}</p>}
      <div className="news-item-foot">
        {matched.length > 0 ? (
          <div className="news-item-players">
            {matched.map((m) => (
              <button
                key={m.name + m.scope}
                type="button"
                className={`news-item-player news-item-player--${m.scope}`}
                onClick={() => onPlayerClick?.(m.name)}
                title={`Open ${m.name}`}
              >
                {m.name}
              </button>
            ))}
          </div>
        ) : (
          <span className="news-item-players-empty">General</span>
        )}
        {item.kind && <span className="news-item-kind">{item.kind}</span>}
      </div>
    </li>
  );
}

function NewsSkeleton({ rows = 4 }) {
  return (
    <ul className="news-feed news-feed--skeleton" aria-hidden="true">
      {Array.from({ length: rows }).map((_, i) => (
        <li key={i} className="news-item news-item--skeleton">
          <div className="news-item-meta">
            <span className="skeleton-line skeleton-line--xs" />
            <span className="skeleton-line skeleton-line--xs" />
          </div>
          <span className="skeleton-line skeleton-line--wide" />
          <span className="skeleton-line skeleton-line--wide" />
        </li>
      ))}
    </ul>
  );
}
