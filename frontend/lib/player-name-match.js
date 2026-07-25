/**
 * player-name-match — JS mirror of the backend's canonical player
 * name normalization plus the news-by-player index helpers.
 *
 * ``normalizePlayerNameKey`` reproduces
 * ``src/utils/name_clean.py::normalize_player_name`` step for step:
 *
 *   1. ASCII fold ("é" → "e", "ñ" → "n").
 *   2. Lowercase, trim.
 *   3. "&" → " and ".
 *   4. Apostrophes (curly + straight) removed WITHOUT inserting a
 *      space, so "Ja'Marr" and "JaMarr" collide on the same key.
 *   5. Generational suffixes (jr|sr|ii|iii|iv|v|dr) stripped.
 *   6. Remaining non-alphanumerics → spaces, whitespace collapsed.
 *   7. Adjacent single-letter tokens merged ("t j watt" → "tj watt").
 *
 * The backend's ``CANONICAL_NAME_ALIASES`` nickname table is NOT
 * mirrored here on purpose: news player mentions are tagged
 * server-side from the live contract's display names, so both sides
 * of every lookup already share the same vocabulary — the alias
 * table would only add a second source of truth that drifts.
 *
 * This module is deliberately free of "use client" so server
 * components (e.g. the public player-journey page) can import it.
 */

const SUFFIX_RE = /\b(jr|sr|ii|iii|iv|v|dr)\b\.?/gi;
const APOSTROPHE_RE = /[‘’‛ʼ']/g;
const NON_ALNUM_RE = /[^a-z0-9]+/g;

function asciiFold(value) {
  // NFKD splits accented characters into base + combining mark; the
  // second replace drops the marks (and any other non-ASCII), which
  // matches Python's ``encode("ascii", "ignore")``.
  return String(value)
    .normalize("NFKD")
    .replace(/[^\x00-\x7F]/g, "");
}

function collapseInitials(s) {
  const parts = s.split(" ").filter(Boolean);
  const result = [];
  let i = 0;
  while (i < parts.length) {
    if (parts[i].length === 1 && /[a-z]/.test(parts[i])) {
      let initials = parts[i];
      while (
        i + 1 < parts.length &&
        parts[i + 1].length === 1 &&
        /[a-z]/.test(parts[i + 1])
      ) {
        i += 1;
        initials += parts[i];
      }
      result.push(initials);
    } else {
      result.push(parts[i]);
    }
    i += 1;
  }
  return result.join(" ");
}

/**
 * Collapse a display name to the deterministic lookup key.
 * Returns "" for null/empty input.
 */
export function normalizePlayerNameKey(name) {
  if (!name) return "";
  let s = asciiFold(name).toLowerCase().trim();
  s = s.replace(/&/g, " and ");
  s = s.replace(APOSTROPHE_RE, "");
  s = s.replace(SUFFIX_RE, "");
  s = s.replace(NON_ALNUM_RE, " ").trim();
  s = s.replace(/\s+/g, " ");
  s = collapseInitials(s);
  return s;
}

function itemPlayerNames(item) {
  if (Array.isArray(item?.players) && item.players.length > 0) {
    return item.players.map((p) => (typeof p === "string" ? p : p?.name));
  }
  if (Array.isArray(item?.impactedPlayers)) return item.impactedPlayers;
  return [];
}

function itemTime(item) {
  const t = Date.parse(item?.ts || item?.publishedAt || "");
  return Number.isFinite(t) ? t : 0;
}

/**
 * Index news items by normalized player-name key.
 *
 * Unlike the previous latest-item-only map, every entry is the FULL
 * list of items mentioning that player, sorted newest-first, deduped
 * by item id.
 *
 * @param {Array} items — NewsItem list from ``/api/news``.
 * @returns {Map<string, Array>} normalized name key → items[].
 */
export function buildNewsIndexByPlayer(items) {
  const out = new Map();
  if (!Array.isArray(items) || items.length === 0) return out;
  const sorted = [...items].sort((a, b) => itemTime(b) - itemTime(a));
  for (const item of sorted) {
    const seenKeys = new Set();
    for (const rawName of itemPlayerNames(item)) {
      const key = normalizePlayerNameKey(rawName);
      if (!key || seenKeys.has(key)) continue;
      seenKeys.add(key);
      const list = out.get(key);
      if (list) {
        if (!list.some((it) => it.id && it.id === item.id)) list.push(item);
      } else {
        out.set(key, [item]);
      }
    }
  }
  return out;
}

/**
 * Look up every news item for a player by display name.
 * Always returns an array (empty when the player has no news).
 */
export function lookupPlayerNews(index, name) {
  if (!(index instanceof Map)) return [];
  const key = normalizePlayerNameKey(name);
  if (!key) return [];
  return index.get(key) || [];
}

/**
 * One-shot convenience for server components: filter a raw item list
 * down to the items mentioning ``name``, newest first.
 */
export function newsItemsForPlayer(items, name) {
  return lookupPlayerNews(buildNewsIndexByPlayer(items), name);
}
