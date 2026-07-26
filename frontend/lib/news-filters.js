/**
 * news-filters — pure helpers behind the /news page's player-level
 * facet filters (NFL team + position).
 *
 * NewsItems only carry player names, so facet filtering resolves
 * each mention against the live contract rows via the normalized
 * name index and then requires a SINGLE mention to satisfy every
 * active facet simultaneously (conjunction per mention, disjunction
 * across mentions).  Evaluating facets independently across the
 * whole mention list would let an article mentioning a DAL WR and a
 * NYG QB pass a combined DAL+QB filter even though no DAL QB is
 * mentioned.
 *
 * Kept free of "use client" so it stays unit-testable in the fast
 * node vitest project.
 */

import {
  itemPlayerNames,
  normalizePlayerNameKey,
  positionFamily,
} from "./player-name-match";

/**
 * Map normalized player-name key → ARRAY of { team, family } metas
 * from the live contract rows.  ``family`` is the first token of the
 * position (``DL/EDGE`` → ``DL``); ``team`` is the uppercase NFL
 * team code.
 *
 * The value is a list, not a single meta: two distinct live players
 * can normalize to the same name key (the repo documents CJ Allen
 * the LB vs C.J. Allen the WR in ``src/utils/name_clean.py``).
 * Keeping only the first row would silently hand one player's news
 * the other's facets — every colliding row's meta is kept as a
 * candidate instead (deduped on team+family).
 */
export function buildPlayerMetaIndex(rows) {
  const meta = new Map();
  if (!Array.isArray(rows)) return meta;
  for (const r of rows) {
    const key = normalizePlayerNameKey(r?.name);
    if (!key) continue;
    const family = positionFamily(r?.pos);
    const team = String(r?.raw?.team || "").toUpperCase().trim();
    const list = meta.get(key);
    if (!list) {
      meta.set(key, [{ team, family }]);
    } else if (!list.some((m) => m.team === team && m.family === family)) {
      list.push({ team, family });
    }
  }
  return meta;
}

/**
 * Player buttons to render for a news item: EVERY mentioned player,
 * not just the roster/league-matched subset.
 *
 * ``__matchedOn`` (stamped by ``rankByRelevance``) is used only to
 * STYLE the buttons — roster/league mentions get their scope class,
 * everyone else renders as ``general``.  Deriving the button list
 * from ``__matchedOn`` itself (the previous behaviour) mislabeled
 * items as "General" with no popup link whenever the mention list
 * didn't survive scoring, even though ``item.players`` was
 * populated.  Deduped on the normalized name key.
 *
 * @returns {Array<{name: string, scope: string}>}
 */
export function buildMentionButtons(item) {
  const matched = Array.isArray(item?.__matchedOn) ? item.__matchedOn : [];
  const scopeByKey = new Map();
  for (const m of matched) {
    const key = normalizePlayerNameKey(m?.name);
    if (key && !scopeByKey.has(key)) scopeByKey.set(key, m.scope || "general");
  }
  const out = [];
  const seen = new Set();
  for (const name of itemPlayerNames(item)) {
    const key = normalizePlayerNameKey(name);
    if (!key || seen.has(key)) continue;
    seen.add(key);
    out.push({ name, scope: scopeByKey.get(key) || "general" });
  }
  return out;
}

/**
 * Filter items by NFL team and/or position family.
 *
 * An item passes when at least ONE mentioned player satisfies ALL
 * active facets at once — conjunction within a candidate meta,
 * disjunction across a mention's candidate metas (name-collision
 * players carry several) and across mentions.  With both facets at
 * "ALL" the input is returned untouched.  Items whose mentions can't
 * be resolved against the live board are dropped whenever any facet
 * is active.
 */
export function filterByPlayerFacets(
  items,
  { teamFilter = "ALL", posFilter = "ALL", playerMeta } = {},
) {
  if (!Array.isArray(items)) return [];
  if (teamFilter === "ALL" && posFilter === "ALL") return items;
  const index = playerMeta instanceof Map ? playerMeta : new Map();
  const metaSatisfies = (m) =>
    (teamFilter === "ALL" || m.team === teamFilter) &&
    (posFilter === "ALL" || m.family === posFilter);
  return items.filter((item) =>
    itemPlayerNames(item).some((n) => {
      const candidates = index.get(normalizePlayerNameKey(n));
      return Array.isArray(candidates) && candidates.some(metaSatisfies);
    }),
  );
}
