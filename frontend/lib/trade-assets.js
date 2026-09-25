/**
 * trade-assets — identity and quantity of the assets on a trade side.
 *
 * Owner requirement T-NEW-02 / #1415 (scope row C3-CALC-01).  The trade
 * calculator must distinguish three things the display label cannot:
 *
 *   1. a REPEATABLE market-reference asset — a board pick row such as
 *      "2027 Mid 1st" chosen generically.  It is a price reference
 *      (C1-ID-02's ``mpick:*`` concept), not an owned asset, so a side may
 *      carry it any number of times and every copy counts;
 *   2. a UNIQUE owned league pick — a pick carrying the canonical owned
 *      identity ``pick:<leagueKey>:<season>:r<N>:o<rid>`` minted by
 *      ``src/identity/picks.py`` and stamped on
 *      ``sleeper.teams[].pickDetails[].assetId``.  Two of them may render
 *      the same label ("2027 Mid 1st") and both stay addable; the SAME id
 *      can never be counted twice;
 *   3. a UNIQUE player — one board row is one real player (the board
 *      quarantines duplicate canonical identities), so the board row key
 *      is the player's identity inside the calculator.
 *
 * STATE MODEL — one side entry per COPY.  ``side.assets`` stays an array
 * of board-row-shaped entries; a generic pick with quantity 3 is three
 * entries.  Chosen over a ``quantity`` field because every existing
 * consumer (Value Adjustment, flows, stack moves, source breakdown, ROS
 * fit, BDVM check, simulator payloads, CSV) already iterates
 * ``side.assets`` and so counts each copy with no change; a quantity
 * field would have to be expanded at every one of those call sites and
 * any site that forgot would silently undercount.  The UI GROUPS entries
 * by ``tradeEntryKey`` to render one line with a ``− N +`` control.
 *
 * Nothing here parses, mints or compares pick labels: identity comes from
 * the backend-stamped ``assetId`` or from the board row itself.  Nothing
 * here values anything either — rows keep their canonical board values.
 */

/** True for an entry carrying a canonical owned league-pick identity. */
export function isOwnedPickEntry(entry) {
  return Boolean(entry && entry.assetId);
}

/**
 * True when the same entry may appear more than once in a trade.
 *
 * Only board PICK rows without an owned identity repeat.  Players never
 * do, and an owned pick never does — its whole point is that it is one
 * specific asset.  Asset type alone does not decide it: a pick WITH an
 * ``assetId`` is unique.
 */
export function isRepeatableEntry(entry) {
  if (!entry) return false;
  return entry.assetClass === "pick" && !entry.assetId;
}

/**
 * The identity of one side LINE: the owned-pick id when there is one,
 * otherwise the board row key.  Destinations, value overrides, grouping
 * and remove-one all key on this — never on the display label, which two
 * distinct owned picks can share.
 */
export function tradeEntryKey(entry) {
  if (!entry) return "";
  if (entry.assetId) return String(entry.assetId);
  return String(entry.name ?? "");
}

/** Label to SHOW for an entry.  Ownership stays visible on owned picks. */
export function tradeEntryLabel(entry) {
  if (!entry) return "";
  return String(entry.assetLabel || entry.name || "");
}

function assetsOf(side) {
  if (Array.isArray(side)) return side;
  return Array.isArray(side?.assets) ? side.assets : [];
}

/** Keys of every UNIQUE (non-repeatable) entry anywhere in the trade. */
export function uniqueKeysInTrade(sides) {
  const out = new Set();
  for (const side of sides || []) {
    for (const entry of assetsOf(side)) {
      if (!isRepeatableEntry(entry)) out.add(tradeEntryKey(entry));
    }
  }
  return out;
}

/**
 * May ``entry`` be added to the trade?  A repeatable entry always may; a
 * unique one only while its identity is not already on ANY side (a player
 * cannot be both given and received, and an owned pick cannot be counted
 * twice).
 */
export function canAddEntry(sides, entry) {
  if (!entry || !tradeEntryKey(entry)) return false;
  if (isRepeatableEntry(entry)) return true;
  return !uniqueKeysInTrade(sides).has(tradeEntryKey(entry));
}

/** Number of copies of ``key`` on one side (or across sides when given an array of sides). */
export function countEntries(assetsOrSides, key) {
  const list = Array.isArray(assetsOrSides) ? assetsOrSides : [];
  let n = 0;
  for (const item of list) {
    if (item && Array.isArray(item.assets)) {
      n += countEntries(item.assets, key);
    } else if (tradeEntryKey(item) === key) {
      n += 1;
    }
  }
  return n;
}

/**
 * Remove ONE copy of ``key`` (the last one) and leave any others.
 * Returns the same array when the key is absent.
 */
export function removeOneEntry(assets, key) {
  const list = Array.isArray(assets) ? assets : [];
  for (let i = list.length - 1; i >= 0; i -= 1) {
    if (tradeEntryKey(list[i]) === key) {
      return [...list.slice(0, i), ...list.slice(i + 1)];
    }
  }
  return list;
}

/**
 * Group a side's entries into display lines, first-occurrence order.
 * ``count`` is the quantity; a unique entry always has count 1 unless the
 * state is corrupt, in which case the count shows it rather than hiding it.
 */
export function groupSideEntries(assets) {
  const groups = [];
  const byKey = new Map();
  for (const entry of Array.isArray(assets) ? assets : []) {
    const key = tradeEntryKey(entry);
    const existing = byKey.get(key);
    if (existing) {
      existing.count += 1;
      continue;
    }
    const group = { key, entry, count: 1, repeatable: isRepeatableEntry(entry) };
    byKey.set(key, group);
    groups.push(group);
  }
  return groups;
}

/**
 * Enforce the uniqueness rule over whole-trade entry lists, first
 * occurrence wins.  Used wherever a trade arrives in bulk (share link,
 * saved workspace, KTC import) rather than through ``canAddEntry``.
 * Repeatable entries all survive.
 *
 * @param {object[][]} sideEntryLists — one entry array per side
 * @returns {object[][]}
 */
export function dedupeUniqueAcrossSides(sideEntryLists) {
  const seen = new Set();
  return (sideEntryLists || []).map((list) =>
    (Array.isArray(list) ? list : []).filter((entry) => {
      if (!entry) return false;
      if (isRepeatableEntry(entry)) return true;
      const key = tradeEntryKey(entry);
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    }),
  );
}

/**
 * An owned league pick as a side entry: the board row that prices it plus
 * the canonical owned identity and the ownership label.  A pickDetail
 * WITHOUT an ``assetId`` (unregistered league, older contract) cannot
 * prove which pick it is, so it becomes a plain repeatable market entry —
 * an unproven identity is not upgraded to a unique one.
 */
export function ownedPickEntry(row, detail) {
  if (!row) return null;
  const assetId = String(detail?.assetId || "").trim();
  const label = String(detail?.label || "").trim();
  if (!assetId) return label ? { ...row, assetLabel: label } : row;
  return { ...row, assetId, assetLabel: label || row.name };
}

/**
 * Every pick a Sleeper team holds, as side entries.
 *
 * @param {object} team — a ``sleeper.teams[]`` element
 * @param {(label: string) => object|null} resolveRow — label → board row
 *        (the page passes the existing ``resolvePickRow`` resolver)
 */
export function teamPickEntries(team, resolveRow) {
  const out = [];
  if (!team || typeof resolveRow !== "function") return out;
  const details = Array.isArray(team.pickDetails) ? team.pickDetails : [];
  if (details.length) {
    for (const detail of details) {
      const row = resolveRow(detail?.label || detail?.baseLabel || "");
      const entry = ownedPickEntry(row, detail);
      if (entry) out.push(entry);
    }
    return out;
  }
  // No pickDetails: the plain label list still says how MANY picks share a
  // board row, just not which is which — so they stay repeatable entries.
  for (const label of Array.isArray(team.picks) ? team.picks : []) {
    const row = resolveRow(label);
    if (row) out.push({ ...row, assetLabel: String(label) });
  }
  return out;
}

/**
 * The subset of a team's picks still available to ADD to ``sideIdx``.
 *
 * Multiplicity-aware, so the equalizer can offer a team's second
 * "2027 Mid 1st" after its first is in the trade — but never a copy the
 * team does not hold:
 *   * an owned pick already anywhere in the trade is unavailable;
 *   * each GENERIC copy of a row already on this side stands for one of
 *     the team's picks of that row (which one is unknown), so it consumes
 *     one of them.
 */
// A copy COUNTER, not a value: a name never counted has been seen zero
// times.  Spelled out so it cannot be mistaken for (or become) a missing
// value coerced to a number.
function copiesCounted(counts, name) {
  return counts.has(name) ? counts.get(name) : 0;
}

export function availableTeamPickEntries(teamEntries, sides, sideIdx) {
  const inTradeIds = new Set();
  for (const side of sides || []) {
    for (const entry of assetsOf(side)) {
      if (isOwnedPickEntry(entry)) inTradeIds.add(String(entry.assetId));
    }
  }
  const genericOnSide = new Map();
  for (const entry of assetsOf((sides || [])[sideIdx])) {
    if (isRepeatableEntry(entry)) {
      genericOnSide.set(entry.name, copiesCounted(genericOnSide, entry.name) + 1);
    }
  }
  const consumed = new Map();
  const out = [];
  for (const entry of teamEntries || []) {
    if (!entry) continue;
    if (isOwnedPickEntry(entry) && inTradeIds.has(String(entry.assetId))) continue;
    const pending = copiesCounted(genericOnSide, entry.name);
    const used = copiesCounted(consumed, entry.name);
    if (used < pending) {
      consumed.set(entry.name, used + 1);
      continue;
    }
    out.push(entry);
  }
  return out;
}

/** Owned/team pick entries whose label or board name matches ``query``. */
export function searchPickEntries(entries, query, limit = 5) {
  const q = String(query || "")
    .trim()
    .toLowerCase();
  if (!q) return [];
  const out = [];
  for (const entry of entries || []) {
    if (!entry) continue;
    const hay = `${entry.assetLabel || ""} ${entry.name || ""}`.toLowerCase();
    if (hay.includes(q)) out.push(entry);
    if (out.length >= limit) break;
  }
  return out;
}

// ── Serialization ─────────────────────────────────────────────────────
//
// A persisted side entry is the board row NAME (string) for players and
// repeatable picks — identical to every payload written before this
// module existed, so old saved workspaces and old share links load
// unchanged — or ``{ name, assetId, label }`` for an owned pick.  Copies
// are persisted as repeated items.

export function serializeEntry(entry) {
  if (!entry) return null;
  if (!entry.assetId) return String(entry.name ?? "");
  const out = { name: String(entry.name ?? ""), assetId: String(entry.assetId) };
  if (entry.assetLabel) out.label = String(entry.assetLabel);
  return out;
}

/**
 * One persisted item back to an entry, or null when its board row is gone.
 * Values always come from today's board row, never from the payload.
 */
export function deserializeEntry(item, rowByName) {
  if (!rowByName || typeof rowByName.get !== "function") return null;
  if (typeof item === "string") return rowByName.get(item) || null;
  if (!item || typeof item !== "object") return null;
  const row = rowByName.get(String(item.name ?? ""));
  if (!row) return null;
  const assetId = String(item.assetId || "").trim();
  if (!assetId) return row;
  return { ...row, assetId, assetLabel: String(item.label || "") || row.name };
}
