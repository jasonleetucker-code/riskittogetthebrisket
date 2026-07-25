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

import { itemPlayerNames, normalizePlayerNameKey } from "./player-name-match";

/**
 * Map normalized player-name key → { team, family } from the live
 * contract rows.  ``family`` is the first token of the position
 * (``DL/EDGE`` → ``DL``); ``team`` is the uppercase NFL team code.
 */
export function buildPlayerMetaIndex(rows) {
  const meta = new Map();
  if (!Array.isArray(rows)) return meta;
  for (const r of rows) {
    const key = normalizePlayerNameKey(r?.name);
    if (!key || meta.has(key)) continue;
    const family = String(r?.pos || "").toUpperCase().split("/")[0];
    const team = String(r?.raw?.team || "").toUpperCase().trim();
    meta.set(key, { team, family });
  }
  return meta;
}

/**
 * Filter items by NFL team and/or position family.
 *
 * An item passes when at least ONE mentioned player satisfies ALL
 * active facets at once.  With both facets at "ALL" the input is
 * returned untouched.  Items whose mentions can't be resolved
 * against the live board are dropped whenever any facet is active.
 */
export function filterByPlayerFacets(
  items,
  { teamFilter = "ALL", posFilter = "ALL", playerMeta } = {},
) {
  if (!Array.isArray(items)) return [];
  if (teamFilter === "ALL" && posFilter === "ALL") return items;
  const index = playerMeta instanceof Map ? playerMeta : new Map();
  return items.filter((item) => {
    const metas = itemPlayerNames(item)
      .map((n) => index.get(normalizePlayerNameKey(n)))
      .filter(Boolean);
    if (metas.length === 0) return false;
    return metas.some(
      (m) =>
        (teamFilter === "ALL" || m.team === teamFilter) &&
        (posFilter === "ALL" || m.family === posFilter),
    );
  });
}
