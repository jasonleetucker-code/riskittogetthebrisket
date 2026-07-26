"use client";

/**
 * news-service — client-side adapter for the news tab, landing-page
 * panels, and ticker alerts.
 *
 * Contract shape (NewsItem):
 *   { id, ts, provider, providerLabel, severity, kind,
 *     headline, body, players:[{name, impact}], url }
 *
 * Fetch strategy: backend only (``/api/news``).  Any failure — HTTP
 * error, 503, network — produces an explicit
 * ``{ unavailable: true, reason }`` state so every surface renders
 * an honest "news unavailable" treatment.  The previous silent
 * fallback to a bundled ``mock-news.json`` fixture is gone: it
 * masked real outages behind a stale 2026-04 snapshot.
 */

export const NEWS_SEVERITY = Object.freeze({
  alert: "alert",
  watch: "watch",
  info: "info",
});

const RELEVANCE = Object.freeze({
  ROSTER: 100,
  LEAGUE: 50,
  GENERAL: 10,
});

function normalize(s) {
  return String(s || "").trim().toLowerCase();
}

function toNameSet(names) {
  const set = new Set();
  if (!Array.isArray(names)) return set;
  for (const n of names) set.add(normalize(n));
  return set;
}

function resolveItems(raw) {
  if (!raw) return [];
  if (Array.isArray(raw.items)) return raw.items;
  if (Array.isArray(raw)) return raw;
  return [];
}

// The route's hard ``?limit=`` ceiling.  Every consumer shares ONE
// single-flighted fetch through useNews, and the News tab filters
// (team / position / source / search) run client-side over that
// payload — requesting anything less than the full window would let
// the server truncate away matching items before the filters ever
// see them (Codex P2).  The payload is still small (~100 compact
// items), so the smaller surfaces just slice locally.
export const NEWS_FETCH_LIMIT = 100;

/**
 * Fetch news items.  Backend only — failures surface as an explicit
 * unavailable state instead of silently serving stale fixture data.
 * @returns {Promise<{items, source, providersUsed, unavailable, reason}>}
 */
export async function fetchNews({ signal, limit = NEWS_FETCH_LIMIT } = {}) {
  try {
    const res = await fetch(`/api/news?limit=${encodeURIComponent(limit)}`, {
      credentials: "same-origin",
      signal,
    });
    if (res.ok) {
      const payload = await res.json();
      const items = resolveItems(payload);
      return {
        items,
        source: "backend",
        providersUsed: Array.isArray(payload?.providersUsed)
          ? payload.providersUsed
          : [],
        unavailable: false,
        reason: null,
      };
    }
    return {
      items: [],
      source: "backend",
      providersUsed: [],
      unavailable: true,
      reason:
        res.status === 404 || res.status === 503
          ? "backend_unavailable"
          : `backend_error_${res.status}`,
    };
  } catch (err) {
    if (err?.name === "AbortError") throw err;
    return {
      items: [],
      source: null,
      providersUsed: [],
      unavailable: true,
      reason: "fetch_failed",
    };
  }
}

/**
 * Tag each item with a relevance score based on roster + league
 * membership, then sort by (relevance desc, timestamp desc).
 *
 * An item with multiple players takes the MAX relevance across its
 * players — one roster-relevant mention is enough to promote it.
 */
export function rankByRelevance(items, { rosterNames, leagueNames } = {}) {
  const roster = toNameSet(rosterNames);
  const league = toNameSet(leagueNames);

  const scored = items.map((item) => {
    const players = Array.isArray(item.players) ? item.players : [];
    let relevance = RELEVANCE.GENERAL;
    let matchedOn = [];
    for (const p of players) {
      const n = normalize(p?.name);
      if (!n) continue;
      if (roster.has(n)) {
        relevance = Math.max(relevance, RELEVANCE.ROSTER);
        matchedOn.push({ name: p.name, scope: "roster" });
      } else if (league.has(n)) {
        relevance = Math.max(relevance, RELEVANCE.LEAGUE);
        matchedOn.push({ name: p.name, scope: "league" });
      } else {
        matchedOn.push({ name: p.name, scope: "general" });
      }
    }
    return { ...item, __relevance: relevance, __matchedOn: matchedOn };
  });

  scored.sort((a, b) => {
    if (b.__relevance !== a.__relevance) return b.__relevance - a.__relevance;
    return tsDesc(a.ts, b.ts);
  });

  return scored;
}

function tsDesc(a, b) {
  const ta = Date.parse(a) || 0;
  const tb = Date.parse(b) || 0;
  return tb - ta;
}

/**
 * Filter by scope: "roster" | "league" | "all".
 * Must be called AFTER ``rankByRelevance`` so scoping is consistent.
 */
export function filterByScope(scoredItems, scope) {
  if (!Array.isArray(scoredItems)) return [];
  if (scope === "roster") {
    return scoredItems.filter((i) => i.__relevance >= RELEVANCE.ROSTER);
  }
  if (scope === "league") {
    return scoredItems.filter((i) => i.__relevance >= RELEVANCE.LEAGUE);
  }
  return scoredItems;
}

/**
 * Compact relative time, e.g. "3m", "2h", "1d".  Stable and short
 * enough to sit in a timeline column.
 */
export function timeAgo(iso, now = Date.now()) {
  const t = Date.parse(iso);
  if (!Number.isFinite(t)) return "—";
  const seconds = Math.max(1, Math.floor((now - t) / 1000));
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h`;
  const days = Math.floor(hours / 24);
  if (days < 7) return `${days}d`;
  const weeks = Math.floor(days / 7);
  if (weeks < 5) return `${weeks}w`;
  const months = Math.floor(days / 30);
  return `${months}mo`;
}

/**
 * Pull high-severity roster-relevant items for the ticker alert
 * injection.  The ticker caller decides how to interleave these
 * with market-mover items; this function just filters + orders.
 */
export function selectTickerAlerts(scoredItems, { limit = 3 } = {}) {
  if (!Array.isArray(scoredItems)) return [];
  return scoredItems
    .filter(
      (i) =>
        i.severity === NEWS_SEVERITY.alert && i.__relevance >= RELEVANCE.ROSTER,
    )
    .slice(0, limit);
}
