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
 *
 * ── Name-key families — the JS registry ─────────────────────────────
 *
 * There is more than one name key on the frontend, deliberately. They
 * are NOT interchangeable: a Set built with one is never hit by
 * another. This list is the single JS-side statement of which key is
 * which; its Python counterpart is the module docstring of
 * `src/utils/name_clean.py`.
 *
 * 1. STRICT / canonical — `normalizePlayerNameKey` (this module).
 *    Consumers: the news-by-player index and news filters
 *    (`lib/news-filters.js`, `app/news/page.jsx`) and the BDVM
 *    "Fund gap" column join on /rankings and /draft (`lib/bdvm.js`).
 *    Every one of those looks up rows a backend keyed with
 *    `normalize_player_name`, so this is a REAL cross-language pair —
 *    move both or neither. Pinned by the shared fixture
 *    `tests/fixtures/name_key_cases.json`
 *    (`__tests__/name-key-parity.test.js` +
 *    `tests/utils/test_name_key_parity.py`).
 *    `lib/dynasty-data.js` carried a second, drifted copy of this
 *    (missing the apostrophe rule, zero production callers); it was
 *    deleted on 2026-07-29.
 *
 * 2. COMPACT — `lib/waiver-logic.js::normalizeNameCompact`. Lowercase,
 *    drop every non-`[a-z0-9]` character including spaces. For the
 *    claim desk's LOCAL joins and typeahead only. Does NOT strip
 *    generational suffixes, and is NOT the twin of Python's
 *    `compact_name_key` despite looking identical (`str.isalnum()` is
 *    Unicode-aware and keeps "é"; this drops it). Nothing joins across
 *    that boundary.
 *
 * 3. LOOSE / trim — `lib/waiver-logic.js::normalizeName`. `trim()` +
 *    `toLowerCase()`. Byte-parity with
 *    `src/trade/waiver.py::_normalize_name`; keys the league
 *    roster-ownership Sets. Swapping it for family 1 changes which
 *    players are filtered out of the waiver add pool ("Marvin Harrison
 *    Jr." from Sleeper would newly collide with the contract's "Marvin
 *    Harrison"); swapping it for family 2 breaks the documented
 *    backend parity. See the warning on `normalizeNameCompact`.
 *
 * 4. HISTORY-LOG key — `lib/value-history.js::buildHistoryLookup`, a
 *    `"Name::scope"` split with trim+lowercase on both halves. Its
 *    backend counterpart is
 *    `src/api/source_history.py::_norm_name_key`, which produces the
 *    payload it reads.
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

/**
 * Player display names mentioned on a news item — reads the rich
 * ``players`` list first, falling back to the flat
 * ``impactedPlayers`` alias.
 */
export function itemPlayerNames(item) {
  if (Array.isArray(item?.players) && item.players.length > 0) {
    return item.players.map((p) => (typeof p === "string" ? p : p?.name));
  }
  if (Array.isArray(item?.impactedPlayers)) return item.impactedPlayers;
  return [];
}

/**
 * Coarse position family for facet/disambiguation comparisons —
 * first token of the position string, uppercased ("DL/EDGE" → "DL").
 */
export function positionFamily(pos) {
  return String(pos || "")
    .toUpperCase()
    .split("/")[0]
    .trim();
}

/**
 * Disambiguating metadata a news item carries for the mention whose
 * name normalizes to ``key``: ``{ family, team }`` when the mention
 * object has ``position``/``pos`` and/or ``team``/``nflTeam`` fields
 * (the backend's service-level enrichment stamps these from the live
 * contract), or ``null`` for name-only tags.  Exported so
 * ``news-filters`` evaluates facets against the same identity
 * contract the per-player lookup uses.
 */
export function mentionMetaFor(item, key) {
  const players = Array.isArray(item?.players) ? item.players : [];
  for (const p of players) {
    if (!p || typeof p === "string") continue;
    if (normalizePlayerNameKey(p.name) !== key) continue;
    // A mention the tagger flagged as ambiguous (its matched text
    // could refer to more than one known player — e.g. a
    // punctuation-stripped article slug) is treated as name-only
    // regardless of any other fields: its identity is a guess, not
    // a stamp.
    if (p.ambiguous) return null;
    const family = positionFamily(p.position || p.pos);
    const team = String(p.team || p.nflTeam || "").toUpperCase().trim();
    return family || team ? { family, team } : null;
  }
  return null;
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
 *
 * Name collisions (the repo documents CJ Allen the LB vs C.J. Allen
 * the WR in ``src/utils/name_clean.py``) share one index key, so an
 * optional ``context`` from the requesting row disambiguates:
 *
 * * ``{ position/family, team }`` — items whose mention carries
 *   identity metadata (the backend stamps position/team onto
 *   mentions at aggregation time) that CONTRADICTS the context are
 *   dropped.
 * * ``{ playerMeta }`` — the ``news-filters`` meta index over the
 *   live pool.  When it shows the normalized key maps to MULTIPLE
 *   distinct pool players, a name-only mention is AMBIGUOUS and is
 *   suppressed from this per-player surface.  Tradeoff, on purpose:
 *   for ambiguous names, a false negative on a player page beats
 *   attributing another player's news — the item stays visible in
 *   the general feeds (News tab, activity), which don't filter
 *   per-player.
 *
 * Name-only mentions for UNAMBIGUOUS names are always kept — with a
 * single pool identity there's nothing to misattribute, and
 * over-filtering would lose real news.
 */
export function lookupPlayerNews(index, name, context) {
  if (!(index instanceof Map)) return [];
  const key = normalizePlayerNameKey(name);
  if (!key) return [];
  const items = index.get(key) || [];
  const family = positionFamily(context?.family || context?.position);
  const team = String(context?.team || "").toUpperCase().trim();
  const metaIndex =
    context?.playerMeta instanceof Map ? context.playerMeta : null;
  const candidates = metaIndex ? metaIndex.get(key) : null;
  const ambiguous = Array.isArray(candidates) && candidates.length > 1;
  if (!family && !team && !ambiguous) return items;
  return items.filter((item) => {
    const meta = mentionMetaFor(item, key);
    if (!meta) {
      // Name-only mention: keep only when the live pool has a single
      // identity behind this key (see the tradeoff note above).
      return !ambiguous;
    }
    if (meta.family && family && meta.family !== family) return false;
    if (meta.team && team && meta.team !== team) return false;
    return true;
  });
}

/**
 * One-shot convenience for server components: filter a raw item list
 * down to the items mentioning ``name`` (optionally disambiguated by
 * the same ``context`` contract as ``lookupPlayerNews``), newest
 * first.
 */
export function newsItemsForPlayer(items, name, context) {
  return lookupPlayerNews(buildNewsIndexByPlayer(items), name, context);
}

/**
 * Index the backend's per-player digests (``playerDigests``) by
 * normalized name key.  Each value is a LIST — name-collision twins
 * produce separate digest entries distinguished by position.
 */
export function buildDigestIndex(digests) {
  const out = new Map();
  if (!Array.isArray(digests)) return out;
  for (const d of digests) {
    const key = normalizePlayerNameKey(d?.player);
    if (!key) continue;
    const list = out.get(key);
    if (list) list.push(d);
    else out.set(key, [d]);
  }
  return out;
}

/**
 * Resolve THE digest for a specific player row.  With one candidate
 * behind the key it wins outright; with several (collision twins),
 * the caller's position picks the matching identity — and without a
 * usable position the lookup returns null rather than guessing.
 */
export function lookupPlayerDigest(index, name, { position } = {}) {
  if (!(index instanceof Map)) return null;
  const list = index.get(normalizePlayerNameKey(name)) || [];
  if (list.length === 0) return null;
  if (list.length === 1) return list[0];
  const family = positionFamily(position);
  if (!family) return null;
  return list.find((d) => positionFamily(d?.position) === family) || null;
}
