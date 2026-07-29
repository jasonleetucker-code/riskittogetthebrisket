"use client";

import { useMemo, useState } from "react";
import { useApp } from "@/components/AppShell";
import { useTeam } from "@/components/useTeam";
import { useNews } from "@/components/useNews";
import {
  Badge,
  Banner,
  Button,
  EmptyState,
  Input,
  PageHeader,
  Panel,
  SegmentedControl,
  Select,
  SkeletonText,
  StatTile,
  Tabs,
  tabPanelId,
} from "@/components/ds";
import { filterByScope, timeAgo } from "@/lib/news-service";
import {
  itemPlayerNames,
  normalizePlayerNameKey,
  positionFamily,
} from "@/lib/player-name-match";
import {
  buildMentionButtons,
  buildPlayerMetaIndex,
  filterByPlayerFacets,
} from "@/lib/news-filters";
import styles from "./news.module.css";

// ── NEWS (Redesign R3) ───────────────────────────────────────────────
// Digest-first: the page opens on "By player" — the synthesized answer
// to "who is in the news and what changed" — with the raw chronological
// feed one tab away.  Everything the pre-R3 page did is preserved:
// scope relevance scoring (roster / league / all), player search, NFL
// team + position + source facets, the conjunction-per-mention facet
// rule, ambiguity-safe player linking, and the fail-fast unavailable
// state (no fixture fallback, ever).
//
// Data notes that drive the design:
//   • The service applies a hard 7-day cutoff, so this page is always
//     "this week" — the window is stated once, in the header.
//   • Digests exist only for players with 2+ stories inside that
//     window (src/news/digest.py), so the Stories tab is never empty
//     when Digests is — the empty state says exactly that.

const VIEW_TABS = [
  { id: "players", label: "By player" },
  { id: "stories", label: "Stories" },
];

const SCOPE_OPTIONS = [
  { value: "roster", label: "My roster" },
  { value: "league", label: "League" },
  { value: "all", label: "All" },
];

const POSITION_OPTIONS = ["QB", "RB", "WR", "TE", "DL", "LB", "DB"];

const MAX_ITEMS = 100;

// Severity → Badge tone. Direction/urgency never rides on color alone:
// the badge carries the word too.
const SEVERITY_TONE = { alert: "negative", watch: "warning", info: "neutral" };

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

export default function NewsPage() {
  const { rows, rawData, openPlayerPopup } = useApp();
  const { selectedTeam } = useTeam();
  const leagueNames = useLeagueNames(rawData?.sleeper?.teams);
  const rosterNames = selectedTeam?.players || [];
  const news = useNews({ rosterNames, leagueNames });
  // Map normalized player-name key → candidate {team, family} metas
  // from the live board, so name-only news items can still be faceted.
  const playerMeta = useMemo(() => buildPlayerMetaIndex(rows), [rows]);

  const [view, setView] = useState("players");
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
  const teamOptions = useMemo(() => {
    const teams = new Set();
    for (const metas of playerMeta.values()) {
      for (const m of metas) {
        if (m.team) teams.add(m.team);
      }
    }
    return [...teams].sort();
  }, [playerMeta]);

  const rosterKeys = useMemo(
    () => new Set(rosterNames.map(normalizePlayerNameKey).filter(Boolean)),
    [rosterNames],
  );
  const leagueKeys = useMemo(
    () => new Set(leagueNames.map(normalizePlayerNameKey).filter(Boolean)),
    [leagueNames],
  );

  // ── Digest view: the same facet vocabulary over per-player digests.
  const filteredDigests = useMemo(() => {
    let list = Array.isArray(news.digests) ? news.digests : [];
    if (scope === "roster") {
      list = list.filter((d) => rosterKeys.has(normalizePlayerNameKey(d.player)));
    } else if (scope === "league") {
      list = list.filter((d) => {
        const key = normalizePlayerNameKey(d.player);
        return rosterKeys.has(key) || leagueKeys.has(key);
      });
    }
    if (teamFilter !== "ALL") {
      list = list.filter((d) => String(d.team || "").toUpperCase() === teamFilter);
    }
    if (posFilter !== "ALL") {
      list = list.filter((d) => positionFamily(d.position) === posFilter);
    }
    if (sourceFilter !== "ALL") {
      const wanted = sourceOptions.find((s) => s.key === sourceFilter)?.label;
      list = list.filter(
        (d) => Array.isArray(d.sources) && wanted && d.sources.includes(wanted),
      );
    }
    const q = query.trim();
    if (q) {
      const qKey = normalizePlayerNameKey(q);
      list = list.filter((d) => {
        const key = normalizePlayerNameKey(d.player);
        return (
          (qKey && key.includes(qKey)) ||
          String(d.player || "").toLowerCase().includes(q.toLowerCase())
        );
      });
    }
    return list;
  }, [
    news.digests,
    scope,
    rosterKeys,
    leagueKeys,
    teamFilter,
    posFilter,
    sourceFilter,
    sourceOptions,
    query,
  ]);

  // ── Stories view: scope relevance → player facets → source → search.
  const filteredStories = useMemo(() => {
    let items = filterByScope(news.scored, scope);
    // Team + position must be satisfied by a SINGLE mention at once —
    // see filterByPlayerFacets for the conjunction-per-mention rule.
    items = filterByPlayerFacets(items, { teamFilter, posFilter, playerMeta });
    if (sourceFilter !== "ALL") {
      items = items.filter((item) => String(item?.provider || "") === sourceFilter);
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

  // ── Coverage strip: what the desk is actually looking at.
  const coverage = useMemo(() => {
    const items = news.items || [];
    let alerts = 0;
    let rosterHits = 0;
    for (const item of items) {
      if (item?.severity === "alert") alerts += 1;
      const names = itemPlayerNames(item);
      if (names.some((n) => rosterKeys.has(normalizePlayerNameKey(n)))) {
        rosterHits += 1;
      }
    }
    return {
      stories: items.length,
      digests: (news.digests || []).length,
      alerts,
      rosterHits,
      sources: (news.providersUsed || []).length || sourceOptions.length,
    };
  }, [news.items, news.digests, news.providersUsed, rosterKeys, sourceOptions]);

  const activeCount =
    view === "players" ? filteredDigests.length : filteredStories.length;
  const totalCount = view === "players" ? coverage.digests : coverage.stories;
  const isFiltered = activeCount !== totalCount;

  return (
    <div className={styles.page}>
      <PageHeader
        eyebrow="News"
        title="News"
        description="Every source, deduplicated and combined per player. Rolling 7-day window."
      />

      {news.unavailable && (
        <Banner tone="negative" title="News unavailable">
          {news.reason === "fetch_failed"
            ? "Could not reach the news endpoint. Check your connection and reload."
            : "The news backend is temporarily unavailable. This page recovers on its own once it responds — nothing here is cached or simulated."}
        </Banner>
      )}

      {!news.unavailable && (
        <div className={styles.coverage}>
          <StatTile label="Stories" value={news.loading ? "—" : coverage.stories} />
          <StatTile label="Players covered" value={news.loading ? "—" : coverage.digests} />
          <StatTile
            label="Alerts"
            value={news.loading ? "—" : coverage.alerts}
            meta={coverage.alerts > 0 ? "injury / status" : "none this week"}
          />
          <StatTile
            label="On your roster"
            value={news.loading ? "—" : coverage.rosterHits}
            meta={selectedTeam?.name || "no team selected"}
          />
          <StatTile label="Sources live" value={news.loading ? "—" : coverage.sources} />
        </div>
      )}

      <Panel flush>
        <div className={`news-controls ${styles.controls}`}>
          <Tabs
            tabs={VIEW_TABS}
            active={view}
            onChange={setView}
            label="News view"
            idPrefix="news-view"
          />
          <div className={styles.controlsSpacer} />
          <SegmentedControl
            options={SCOPE_OPTIONS}
            value={scope}
            onChange={setScope}
            label="Relevance scope"
          />
        </div>
        <div className={`news-controls ${styles.controls}`}>
          <Input
            type="search"
            className={styles.controlsSearch}
            placeholder="Search player or headline…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            aria-label="Search news by player or headline"
          />
          <Select
            className={styles.controlsSelect}
            value={teamFilter}
            onChange={(e) => setTeamFilter(e.target.value)}
            aria-label="Filter by NFL team"
          >
            <option value="ALL">All teams</option>
            {teamOptions.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </Select>
          <Select
            className={styles.controlsSelect}
            value={posFilter}
            onChange={(e) => setPosFilter(e.target.value)}
            aria-label="Filter by position"
          >
            <option value="ALL">All positions</option>
            {POSITION_OPTIONS.map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </Select>
          <Select
            className={styles.controlsSelect}
            value={sourceFilter}
            onChange={(e) => setSourceFilter(e.target.value)}
            aria-label="Filter by source"
          >
            <option value="ALL">All sources</option>
            {sourceOptions.map((s) => (
              <option key={s.key} value={s.key}>
                {s.label}
              </option>
            ))}
          </Select>
        </div>

        <div
          id={tabPanelId("news-view", view)}
          role="tabpanel"
          aria-label={view === "players" ? "Player digests" : "All stories"}
          tabIndex={-1}
        >
          {news.loading && <FeedSkeleton />}

          {!news.loading && news.unavailable && (
            <EmptyState
              title="No news to show"
              description="The feed is offline right now — it will fill back in automatically."
            />
          )}

          {!news.loading && !news.unavailable && view === "players" && (
            <DigestList
              digests={filteredDigests}
              hasAny={coverage.digests > 0}
              scope={scope}
              onPlayerClick={openPlayerPopup}
              onShowStories={() => setView("stories")}
            />
          )}

          {!news.loading && !news.unavailable && view === "stories" && (
            <StoryList
              items={filteredStories}
              scope={scope}
              onPlayerClick={openPlayerPopup}
            />
          )}
        </div>

        {!news.loading && !news.unavailable && activeCount > 0 && (
          <PanelFootnote
            count={activeCount}
            total={totalCount}
            filtered={isFiltered}
            view={view}
          />
        )}
      </Panel>
    </div>
  );
}

function PanelFootnote({ count, total, filtered, view }) {
  const noun = view === "players" ? "player" : "story";
  return (
    <p className={styles.footnote}>
      Showing <span className={styles.digestCount}>{count}</span>
      {filtered ? ` of ${total}` : ""} {count === 1 ? noun : `${noun}s`} · last 7 days
    </p>
  );
}

// ── Digest list ──────────────────────────────────────────────────────
function DigestList({ digests, hasAny, scope, onPlayerClick, onShowStories }) {
  if (digests.length === 0) {
    return (
      <EmptyState
        title={hasAny ? "No players match these filters" : "No player digests yet"}
        description={
          hasAny
            ? scope === "roster"
              ? "None of your rostered players have multiple stories this week. Widen the scope or clear a filter."
              : "Clear a filter to see the players who are in the news."
            : "A digest appears once a player has two or more stories inside the 7-day window. The Stories tab has everything that came in."
        }
        action={
          <Button variant="secondary" onClick={onShowStories}>
            View all stories
          </Button>
        }
      />
    );
  }
  return (
    <ul className={styles.feed}>
      {digests.map((d) => (
        <DigestRow
          key={`${d.player}-${d.position || ""}`}
          digest={d}
          onPlayerClick={onPlayerClick}
        />
      ))}
    </ul>
  );
}

function DigestRow({ digest, onPlayerClick }) {
  const tone = SEVERITY_TONE[digest.severity] || "neutral";
  const sources = Array.isArray(digest.sources) ? digest.sources : [];
  return (
    <li className={`news-digest-row ${styles.digest}`}>
      <div className={styles.digestIdentity}>
        <button
          type="button"
          className={styles.digestPlayer}
          onClick={() => onPlayerClick?.(digest.player)}
          title={`Open ${digest.player}`}
        >
          {digest.player}
        </button>
        <span className={styles.digestIdentityMeta}>
          {digest.position ? (
            <span className={styles.digestPos}>{digest.position}</span>
          ) : null}
          {digest.team ? <span className={styles.digestPos}>{digest.team}</span> : null}
        </span>
        <span className={styles.digestIdentityMeta}>
          <span className={styles.digestCount}>{digest.storyCount}</span> stories ·{" "}
          {timeAgo(digest.latestTs)}
        </span>
      </div>
      <div className={styles.digestBody}>
        {digest.severity ? (
          <span className={styles.meta}>
            <Badge tone={tone}>{digest.severity}</Badge>
          </span>
        ) : null}
        <p className={styles.digestSummary}>{digest.summary}</p>
        {sources.length > 0 && (
          <p className={styles.digestSources}>Sources: {sources.join(" · ")}</p>
        )}
      </div>
    </li>
  );
}

// ── Story list ───────────────────────────────────────────────────────
function StoryList({ items, scope, onPlayerClick }) {
  if (items.length === 0) {
    return (
      <EmptyState
        title="No matching stories"
        description={
          scope === "roster"
            ? "No roster-relevant headlines match these filters. Widen the scope or clear a filter."
            : "No headlines match these filters. Try clearing the search or a facet."
        }
      />
    );
  }
  return (
    <ul className={styles.feed}>
      {items.map((item) => (
        <StoryRow
          key={item.id || `${item.ts}-${item.headline}`}
          item={item}
          onPlayerClick={onPlayerClick}
        />
      ))}
    </ul>
  );
}

function StoryRow({ item, onPlayerClick }) {
  // Every mentioned player gets a button; __matchedOn only drives the
  // roster/league/general emphasis.
  const mentions = buildMentionButtons(item);
  const tone = SEVERITY_TONE[item.severity] || "neutral";
  const rosterRelevant = item.__relevance >= 100;
  return (
    <li
      className={`news-story-row ${styles.story} ${
        rosterRelevant ? styles.storyRoster : ""
      }`.trim()}
    >
      <div className={styles.meta}>
        <span className={styles.metaTime}>{timeAgo(item.ts)}</span>
        <span className={styles.metaSource}>
          {item.providerLabel || item.provider || "—"}
        </span>
        {item.severity ? <Badge tone={tone}>{item.severity}</Badge> : null}
        {item.kind ? <span>{item.kind}</span> : null}
      </div>
      <h3 className={styles.headline}>
        {item.url ? (
          <a
            className={styles.headlineLink}
            href={item.url}
            target="_blank"
            rel="noopener noreferrer"
            title="Open source article"
          >
            {item.headline}
          </a>
        ) : (
          item.headline
        )}
      </h3>
      {item.body ? <p className={styles.body}>{item.body}</p> : null}
      {mentions.length > 0 && (
        <div className={styles.mentions}>
          {mentions.map((m) => (
            <button
              key={m.name + m.scope}
              type="button"
              className={`${styles.mention} ${
                m.scope === "roster"
                  ? styles.mentionRoster
                  : m.scope === "league"
                    ? styles.mentionLeague
                    : ""
              }`.trim()}
              onClick={() => onPlayerClick?.(m.name)}
              title={`Open ${m.name}`}
            >
              {m.name}
            </button>
          ))}
        </div>
      )}
    </li>
  );
}

function FeedSkeleton({ rows = 6 }) {
  return (
    <ul className={styles.feed} aria-hidden="true">
      {Array.from({ length: rows }).map((_, i) => (
        <li key={i} className={styles.story}>
          <SkeletonText lines={2} />
        </li>
      ))}
    </ul>
  );
}
