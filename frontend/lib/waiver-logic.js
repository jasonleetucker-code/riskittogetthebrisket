/**
 * Waiver Add/Drop comparison logic — pure helpers for the /waivers page.
 *
 * Mirrors the structure of ``draft-logic.js::nominationCandidates``:
 * deterministic, tiebreaker-aware, side-effect-free.  Lives outside any
 * React component so the full surface is testable in Vitest with no
 * DOM/contexts.
 *
 * Mental model: we compare every UNROSTERED player (the "free agent
 * pool") against every player on the SELECTED team's roster, ranked by
 * canonical ``rankDerivedValue``.  An addable FA beats at least one
 * roster player on raw value; a droppable roster player is beaten by
 * at least one addable FA.  Picks (``assetClass === "pick"``) are
 * never addable, never droppable — they belong to the rookie-draft
 * pipeline, not waivers.
 *
 * Rookie toggle handling:
 *   off — pool = unrostered AND not rookie-flagged
 *   on  — pool = unrostered ∪ all rookie-flagged players (rookies on
 *         other rosters get a ``rosteredBy`` annotation; UI shows them
 *         as read-only comparison rows because they aren't actually
 *         waiverable mid-season).  This matters because today's
 *         pre-draft window has the entire rookie class still on
 *         pre-draft team workspaces — ignoring them would gut the
 *         page during the window the user cares about most.
 *
 * Name matching: backend keys roster ownership off
 * ``str(name).strip().lower()`` (``src/trade/waiver.py::_normalize_name``).
 * We match the same way so future server-side companion logic and
 * the frontend agree byte-for-byte.
 */

// ── Tier thresholds (raw rankDerivedValue gaps) ─────────────────────────
// Calibrated to the canonical 0–9999 scale.  Players sit roughly:
//   QB1 elite      ~8500
//   WR1            ~7500
//   bench filler   ~1500
//   waiver dart    ~500
// A ``smash`` add is a 2000-point swing — typically a starter for a
// bench player.  ``strong`` is a clear bench-for-bench upgrade (1000+).
// ``considering`` is meaningful but small (250+).  ``marginal`` sits
// below that floor.
const UPGRADE_TIER_THRESHOLDS = Object.freeze({
  smash: 2000,
  strong: 1000,
  considering: 250,
});

// Drop confidence mirrors the upgrade tiers from the drop side: a
// 2000+ gap means dropping this player nets a starter-tier replacement,
// so it's an obvious drop.
const DROP_CONFIDENCE_THRESHOLDS = Object.freeze({
  obvious: 2000,
  reasonable: 1000,
  risky: 250,
});

const UPGRADE_TIER_RANK = Object.freeze({
  smash: 4,
  strong: 3,
  considering: 2,
  marginal: 1,
});

const VALID_POSITION_FILTERS = new Set([
  "ALL", "QB", "RB", "WR", "TE", "DL", "LB", "DB", "K",
]);

// ── Public helpers ──────────────────────────────────────────────────────

/**
 * Lowercase + trim, parity with backend ``_normalize_name``.  Empty/
 * null/undefined collapse to ``""``.
 */
export function normalizeName(s) {
  return String(s == null ? "" : s).trim().toLowerCase();
}

/**
 * Build a normalized ``Set`` of every player rostered in the league.
 * The caller memoizes on the ``sleeperTeams`` reference; this function
 * runs in O(N) over all team players combined.
 *
 * Returns an empty Set when ``sleeperTeams`` is missing/null/empty so
 * callers can always treat the return value as a Set without
 * defensive null checks.
 */
export function buildOwnedNameSet(sleeperTeams) {
  const out = new Set();
  if (!Array.isArray(sleeperTeams)) return out;
  for (const t of sleeperTeams) {
    const players = Array.isArray(t?.players) ? t.players : [];
    for (const name of players) {
      const norm = normalizeName(name);
      if (norm) out.add(norm);
    }
  }
  return out;
}

/**
 * Build a Map<normalizedName, teamName> so we can annotate rookies
 * that are pre-drafted to another team with their owner.  Used only
 * when the rookie toggle is on.
 */
export function buildOwnerByName(sleeperTeams) {
  const out = new Map();
  if (!Array.isArray(sleeperTeams)) return out;
  for (const t of sleeperTeams) {
    const teamName = String(t?.name || "").trim();
    const players = Array.isArray(t?.players) ? t.players : [];
    for (const name of players) {
      const norm = normalizeName(name);
      if (norm && !out.has(norm)) out.set(norm, teamName);
    }
  }
  return out;
}

// ── Internal helpers ────────────────────────────────────────────────────

function rowValue(row) {
  // Prefer ``rankDerivedValue`` (the canonical 0-9999 stamp).  Fall
  // back to ``values.full`` which ``buildRows`` already prefers when
  // the backend stamp is present anyway.  Anything not finite ⇒ 0,
  // which gets filtered out below.
  const v = Number(row?.rankDerivedValue);
  if (Number.isFinite(v) && v > 0) return v;
  const v2 = Number(row?.values?.full);
  return Number.isFinite(v2) && v2 > 0 ? v2 : 0;
}

function rowAssetClass(row) {
  return String(row?.assetClass || "").toLowerCase();
}

function rowPosition(row) {
  return String(row?.pos || row?.position || "").toUpperCase();
}

function rowName(row) {
  return String(row?.name || row?.displayName || "").trim();
}

/**
 * Classify an upgrade by raw value gap.  Higher gap = stronger label.
 */
export function classifyUpgradeTier(netGain) {
  const g = Number(netGain) || 0;
  if (g >= UPGRADE_TIER_THRESHOLDS.smash) return "smash";
  if (g >= UPGRADE_TIER_THRESHOLDS.strong) return "strong";
  if (g >= UPGRADE_TIER_THRESHOLDS.considering) return "considering";
  return "marginal";
}

/**
 * Classify drop confidence by the gap to the BEST replacement.  Same
 * thresholds as upgrade tiers, different label set so the UI can use
 * the language naturally ("obvious drop" vs "reasonable drop").
 */
export function classifyDropConfidence(netGain) {
  const g = Number(netGain) || 0;
  if (g >= DROP_CONFIDENCE_THRESHOLDS.obvious) return "obvious";
  if (g >= DROP_CONFIDENCE_THRESHOLDS.reasonable) return "reasonable";
  if (g >= DROP_CONFIDENCE_THRESHOLDS.risky) return "risky";
  return "hold";
}

/**
 * Find the LOWEST-value roster player still beaten by ``addValue``.
 * That's the realistic drop — we don't drop a starter if we have a
 * benchwarmer that's also worse.  Returns null if no roster player is
 * beaten.
 *
 * ``rosterValuesSorted`` must be ascending by value with stable
 * tiebreakers; the first row whose value is < addValue is the answer.
 */
function findBestDropMatch(addValue, rosterValuesSorted) {
  if (!Array.isArray(rosterValuesSorted) || rosterValuesSorted.length === 0) {
    return null;
  }
  // First-from-the-bottom whose value < addValue.
  for (const r of rosterValuesSorted) {
    if (rowValue(r) < addValue) return r;
  }
  return null;
}

/**
 * Find the HIGHEST-value addable player who beats this roster player.
 * That's the best possible replacement.  Returns null if no addable
 * beats them.
 *
 * ``addableSortedByValueDesc`` must be descending by value with stable
 * tiebreakers.
 */
function findBestReplacement(rosterValue, addableSortedByValueDesc) {
  if (!Array.isArray(addableSortedByValueDesc)) return null;
  for (const a of addableSortedByValueDesc) {
    if (rowValue(a) > rosterValue) return a;
  }
  return null;
}

// ── Pool construction ───────────────────────────────────────────────────

/**
 * Apply the rookie toggle + idpEnabled gate + asset-class filter to
 * get the candidate pool.  Returns an array of objects:
 *   { row, isRookie, rosteredBy }
 *
 *   rosteredBy == null  → truly addable (waiver/FA)
 *   rosteredBy != null  → rookie on someone else's roster (read-only)
 */
function buildCandidatePool({
  rows,
  ownedNameSet,
  ownerByName,
  myRosterNameSet,
  includeRookies,
  idpEnabled,
}) {
  const out = [];
  if (!Array.isArray(rows)) return out;
  for (const row of rows) {
    if (!row) continue;
    if (rowAssetClass(row) === "pick") continue;
    if (!idpEnabled && rowAssetClass(row) === "idp") continue;
    if (rowValue(row) <= 0) continue;
    const norm = normalizeName(rowName(row));
    if (!norm) continue;
    if (myRosterNameSet.has(norm)) continue;  // never compare against self
    const owned = ownedNameSet.has(norm);
    const isRookie = Boolean(row.rookie);
    if (owned) {
      if (!includeRookies) continue;
      if (!isRookie) continue;
      // Rookie on another team — show as read-only with owner annotation.
      out.push({
        row,
        isRookie: true,
        rosteredBy: ownerByName.get(norm) || null,
      });
    } else {
      // Truly unrostered.  Respect rookie toggle.
      if (!includeRookies && isRookie) continue;
      out.push({ row, isRookie, rosteredBy: null });
    }
  }
  return out;
}

// ── Stable comparators ─────────────────────────────────────────────────

function byValueDescThenName(a, b) {
  const va = rowValue(a.row != null ? a.row : a);
  const vb = rowValue(b.row != null ? b.row : b);
  if (vb !== va) return vb - va;
  const na = rowName(a.row != null ? a.row : a);
  const nb = rowName(b.row != null ? b.row : b);
  return na.localeCompare(nb);
}

function byValueAscThenName(a, b) {
  const va = rowValue(a.row != null ? a.row : a);
  const vb = rowValue(b.row != null ? b.row : b);
  if (va !== vb) return va - vb;
  const na = rowName(a.row != null ? a.row : a);
  const nb = rowName(b.row != null ? b.row : b);
  return na.localeCompare(nb);
}

// ── Best Moves + Best Unique Upgrade Set ───────────────────────────────

/**
 * Top-N (add, drop) pairs by net gain, deduped by add.
 *
 * The dedup matters: without it the top of the list reads "Add
 * Egbuka, drop Boyd" / "Add Egbuka, drop Pollard" / "Add Egbuka,
 * drop Cleveland" — same FA three times because every drop sits
 * below his value.  Showing each add ONCE (with its best drop, the
 * lowest-value roster player still beaten) collapses the noise.
 *
 * ``addable`` is the enriched addable list (with bestDrop, netGain
 * already attached).  We filter ``rosteredBy != null`` because those
 * rookies aren't actually addable — they're read-only comparison
 * rows.
 */
export function computeBestMoves(addable, { limit = 20 } = {}) {
  if (!Array.isArray(addable)) return [];
  const movable = addable.filter((a) => !a.rosteredBy && a.bestDrop);
  // ``addable`` is already sorted by netGain desc; preserve that order.
  return movable.slice(0, limit).map((a) => ({
    add: a.row,
    drop: a.bestDrop,
    netGain: a.netGain,
    addValue: rowValue(a.row),
    dropValue: rowValue(a.bestDrop),
    upgradeTier: a.upgradeTier,
    position: rowPosition(a.row),
    isRookie: a.isRookie,
  }));
}

/**
 * Greedy unique pair-up.  Sort addable desc, droppable asc; pair
 * 1↔1, 2↔2, … while ``add.value > drop.value``.  Stop when no add
 * still beats its corresponding drop.
 *
 * Filters out ``rosteredBy != null`` adds since they aren't real
 * adds.  This is the "if I had unlimited claims, what's the optimal
 * single-pass slate?" view — answers the user's main question when
 * the addable pool genuinely contains 10+ upgrades.
 */
export function computeBestUniqueUpgradeSet(addable, droppable) {
  if (!Array.isArray(addable) || !Array.isArray(droppable)) return [];
  const adds = addable
    .filter((a) => !a.rosteredBy)
    .slice()
    .sort(byValueDescThenName);
  const drops = droppable.slice().sort(byValueAscThenName);
  const out = [];
  const n = Math.min(adds.length, drops.length);
  for (let i = 0; i < n; i++) {
    const av = rowValue(adds[i].row);
    const dv = rowValue(drops[i].row);
    if (av <= dv) break;
    out.push({
      add: adds[i].row,
      drop: drops[i].row,
      addValue: av,
      dropValue: dv,
      netGain: av - dv,
      isRookie: adds[i].isRookie,
    });
  }
  return out;
}

// ── Filters ────────────────────────────────────────────────────────────

function applyAddableFilters(list, filters) {
  if (!filters) return list;
  const pos = String(filters.position || "ALL").toUpperCase();
  const minGain = Number(filters.minGain) || 0;
  const strength = String(filters.upgradeStrength || "all").toLowerCase();
  return list.filter((a) => {
    if (pos !== "ALL" && rowPosition(a.row) !== pos) return false;
    if (minGain > 0 && (a.netGain || 0) < minGain) return false;
    if (strength === "smash" && a.upgradeTier !== "smash") return false;
    if (strength === "strong"
        && a.upgradeTier !== "smash"
        && a.upgradeTier !== "strong") {
      return false;
    }
    return true;
  });
}

function applyDroppableFilters(list, filters) {
  if (!filters) return list;
  const pos = String(filters.position || "ALL").toUpperCase();
  return list.filter((d) => {
    if (pos !== "ALL" && rowPosition(d.row) !== pos) return false;
    return true;
  });
}

// ── Main orchestrator ──────────────────────────────────────────────────

/**
 * Run the full waiver-vs-roster comparison and return everything the
 * page needs in a single shot.  Pure: same inputs ⇒ same outputs.
 *
 * Inputs:
 *   rows            — useDynastyData rows (override-aware)
 *   myRosterNames   — selectedTeam.players (display-name strings)
 *   sleeperTeams    — rawData.sleeper.teams (drives ownership set)
 *   includeRookies  — boolean rookie toggle
 *   idpEnabled      — selectedLeague.idpEnabled
 *   filters         — { position, minGain, upgradeStrength }
 *
 * Output shape — see file header for field meanings:
 *   {
 *     addable:               [{ row, value, isRookie, rosteredBy?,
 *                               bestDrop, netGain, betterCount,
 *                               upgradeTier }, …]
 *     droppable:             [{ row, value, bestReplacement, netGain,
 *                               betterAvailableCount, dropConfidence }, …]
 *     bestMoves:             [{ add, drop, netGain, upgradeTier,
 *                               position, isRookie, addValue, dropValue }, …]
 *     bestUniqueUpgradeSet:  [{ add, drop, addValue, dropValue, netGain,
 *                               isRookie }, …]
 *     summary:               { bestAddable, bestGain, addableCount,
 *                              droppableCount, rookieAddCount,
 *                              rosterSize, freeAgentPoolSize }
 *   }
 */
export function computeWaiverAnalysis({
  rows,
  myRosterNames,
  sleeperTeams,
  includeRookies = false,
  idpEnabled = true,
  filters = {},
} = {}) {
  // Guard: the validated empty-state path.  Empty inputs return a
  // fully-shaped empty result so the page can always destructure.
  const safeRows = Array.isArray(rows) ? rows : [];
  const safeMyRoster = Array.isArray(myRosterNames) ? myRosterNames : [];
  const safeFilters = filters && typeof filters === "object" ? filters : {};

  // Validate position filter — anything unknown collapses to ALL so a
  // bad URL param doesn't blank the page.
  const pos = String(safeFilters.position || "ALL").toUpperCase();
  if (!VALID_POSITION_FILTERS.has(pos)) safeFilters.position = "ALL";

  const ownedNameSet = buildOwnedNameSet(sleeperTeams);
  const ownerByName = buildOwnerByName(sleeperTeams);
  const myRosterNameSet = new Set(
    safeMyRoster.map(normalizeName).filter(Boolean),
  );

  // Roster rows: lookup my roster names → row objects.
  const rowByName = new Map();
  for (const r of safeRows) {
    const norm = normalizeName(rowName(r));
    if (norm && !rowByName.has(norm)) rowByName.set(norm, r);
  }
  const rosterRows = [];
  for (const name of safeMyRoster) {
    const r = rowByName.get(normalizeName(name));
    if (!r) continue;                              // name not in contract
    if (rowAssetClass(r) === "pick") continue;     // belt+suspenders
    if (rowValue(r) <= 0) continue;                // unranked / unfit
    rosterRows.push(r);
  }
  const rosterSortedAsc = rosterRows.slice().sort((a, b) => {
    const av = rowValue(a);
    const bv = rowValue(b);
    if (av !== bv) return av - bv;
    return rowName(a).localeCompare(rowName(b));
  });
  const rosterMin = rosterSortedAsc.length ? rowValue(rosterSortedAsc[0]) : 0;

  // Candidate pool (rookie toggle + idp gate + ownership).
  const pool = buildCandidatePool({
    rows: safeRows,
    ownedNameSet,
    ownerByName,
    myRosterNameSet,
    includeRookies: Boolean(includeRookies),
    idpEnabled: Boolean(idpEnabled),
  });

  // Addable list: pool entries whose value beats AT LEAST ONE roster
  // player.  When the roster is empty (rosterMin === 0), every
  // positive-value pool entry technically qualifies — but with no
  // roster to compare against there's no "drop" so the list is
  // pointless.  Return an empty list in that case.
  const enrichedAddable = [];
  if (rosterRows.length > 0) {
    for (const c of pool) {
      const v = rowValue(c.row);
      if (v <= rosterMin) continue;
      // Lowest-value roster player still beaten = realistic drop.
      const bestDrop = findBestDropMatch(v, rosterSortedAsc);
      if (!bestDrop) continue;  // shouldn't happen given v > rosterMin, but defensive
      const dropValue = rowValue(bestDrop);
      const netGain = v - dropValue;
      const betterCount = rosterRows.reduce(
        (acc, r) => acc + (rowValue(r) < v ? 1 : 0),
        0,
      );
      enrichedAddable.push({
        row: c.row,
        value: v,
        isRookie: c.isRookie,
        rosteredBy: c.rosteredBy,
        bestDrop,
        dropValue,
        netGain,
        betterCount,
        upgradeTier: classifyUpgradeTier(netGain),
      });
    }
  }
  enrichedAddable.sort((a, b) => {
    if (b.netGain !== a.netGain) return b.netGain - a.netGain;
    // Secondary: by upgrade-tier ranking (smash > strong > …).
    const ra = UPGRADE_TIER_RANK[a.upgradeTier] || 0;
    const rb = UPGRADE_TIER_RANK[b.upgradeTier] || 0;
    if (rb !== ra) return rb - ra;
    return rowName(a.row).localeCompare(rowName(b.row));
  });

  // Apply user filters AFTER full enrichment so the unfiltered list
  // is still available for summary stats.
  const filteredAddable = applyAddableFilters(enrichedAddable, safeFilters);

  // Droppable list: roster players beaten by any (truly-addable) FA.
  // Read-only rookies (``rosteredBy != null``) cannot actually drop
  // anything — exclude them from the threshold.
  const realAdds = filteredAddable.filter((a) => !a.rosteredBy);
  const realAddsDesc = realAdds.slice().sort((a, b) => b.value - a.value);
  const addableMax = realAdds.length ? realAdds[0].value : 0;

  const enrichedDroppable = [];
  for (const r of rosterSortedAsc) {
    const v = rowValue(r);
    if (v >= addableMax) continue;       // nothing beats this player
    const bestReplacement = findBestReplacement(v, realAddsDesc.map((a) => a.row));
    if (!bestReplacement) continue;
    const replacementValue = rowValue(bestReplacement);
    const netGain = replacementValue - v;
    const betterAvailableCount = realAdds.reduce(
      (acc, a) => acc + (a.value > v ? 1 : 0),
      0,
    );
    enrichedDroppable.push({
      row: r,
      value: v,
      bestReplacement,
      replacementValue,
      netGain,
      betterAvailableCount,
      dropConfidence: classifyDropConfidence(netGain),
    });
  }
  // Drop confidence sorts naturally with netGain desc — biggest gain
  // = most obvious drop.
  enrichedDroppable.sort((a, b) => {
    if (b.netGain !== a.netGain) return b.netGain - a.netGain;
    return rowName(a.row).localeCompare(rowName(b.row));
  });
  const filteredDroppable = applyDroppableFilters(enrichedDroppable, safeFilters);

  // Best moves + unique set are computed off the FILTERED lists so
  // user filters narrow them too.
  const bestMoves = computeBestMoves(filteredAddable);
  const bestUniqueUpgradeSet = computeBestUniqueUpgradeSet(
    filteredAddable,
    filteredDroppable,
  );

  const summary = {
    bestAddable: realAddsDesc[0]?.row || null,
    bestGain: bestMoves[0]?.netGain || 0,
    addableCount: realAdds.length,
    droppableCount: filteredDroppable.length,
    rookieAddCount: realAdds.reduce((a, x) => a + (x.isRookie ? 1 : 0), 0),
    rosterSize: rosterRows.length,
    freeAgentPoolSize: pool.filter((c) => !c.rosteredBy).length,
  };

  return {
    addable: filteredAddable,
    droppable: filteredDroppable,
    bestMoves,
    bestUniqueUpgradeSet,
    summary,
  };
}
