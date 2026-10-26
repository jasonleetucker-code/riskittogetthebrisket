// Temporary trade refinement — LOCK / EXCLUDE (C3-CON-03).
//
// Spec: docs/trade/TRADE_GENERATION_PREFERENCES_AND_REFINEMENT_SPEC.md §3-§4.
//
// * LOCK and EXCLUDE apply to OUTGOING players only and are mutually
//   exclusive per player: setting one clears the other.
// * They persist "until the user clears them" (§3.3) — across regeneration
//   and ordinary refreshes — so they live in localStorage, scoped to
//   (team, league, surface, context).  They are NEVER written to the
//   persistent trade-protection store (user_kv tradeConstraintsByLeague),
//   which is what keeps a temporary EXCLUDE from ever becoming a permanent
//   untouchable.
// * "Skip target" is the incoming-side search filter.  It is not a
//   constraint (constraints are outgoing-only) and is session state only:
//   it is kept in memory and never stored.
//
// The server validates and applies the request through the one constraint
// owner (src/trade/constraints.py); nothing here decides eligibility.

export const REFINEMENT_STORAGE_PREFIX = "rit.refinement.v1";
export const MAX_REFINEMENT_ASSETS = 25; // mirrors constraints.MAX_REFINEMENT_ASSETS

function clean(name) {
  return String(name ?? "").trim();
}

function keyOf(name) {
  return clean(name).toLowerCase();
}

export function emptyRefinement() {
  return { lock: [], exclude: [], skip: [] };
}

export function refinementKey({ owner, leagueKey, surface, context }) {
  return [
    REFINEMENT_STORAGE_PREFIX,
    clean(owner) || "anon",
    clean(leagueKey) || "default",
    clean(surface) || "trade",
    clean(context) || "all",
  ].join(":");
}

function sanitizeList(value) {
  if (!Array.isArray(value)) return [];
  const seen = new Set();
  const out = [];
  for (const raw of value) {
    if (typeof raw !== "string") continue; // a stored name is always a string
    const name = clean(raw);
    const k = name.toLowerCase();
    if (!name || seen.has(k)) continue;
    seen.add(k);
    out.push(name);
    if (out.length >= MAX_REFINEMENT_ASSETS) break;
  }
  return out;
}

// localStorage can throw (private mode, blocked storage); a refinement that
// cannot be read starts empty rather than breaking the page.
export function loadRefinement(storageKey) {
  try {
    const raw = window.localStorage.getItem(storageKey);
    if (!raw) return emptyRefinement();
    const parsed = JSON.parse(raw);
    const lock = sanitizeList(parsed?.lock);
    const lockKeys = new Set(lock.map(keyOf));
    const exclude = sanitizeList(parsed?.exclude).filter((n) => !lockKeys.has(keyOf(n)));
    return { lock, exclude, skip: [] };
  } catch {
    return emptyRefinement();
  }
}

export function saveRefinement(storageKey, refinement) {
  try {
    const payload = { lock: refinement.lock || [], exclude: refinement.exclude || [] };
    if (!payload.lock.length && !payload.exclude.length) {
      window.localStorage.removeItem(storageKey);
    } else {
      window.localStorage.setItem(storageKey, JSON.stringify(payload));
    }
  } catch {
    // Storage unavailable — the in-memory refinement still applies.
  }
}

function without(list, name) {
  const k = keyOf(name);
  return (list || []).filter((n) => keyOf(n) !== k);
}

function has(list, name) {
  const k = keyOf(name);
  return (list || []).some((n) => keyOf(n) === k);
}

export function refinementState(refinement, name) {
  if (has(refinement?.lock, name)) return "lock";
  if (has(refinement?.exclude, name)) return "exclude";
  if (has(refinement?.skip, name)) return "skip";
  return null;
}

// Toggling LOCK on a locked player clears it; on anything else it locks and
// removes any EXCLUDE — the two are never set together.
export function toggleLock(refinement, name) {
  const n = clean(name);
  if (!n) return refinement;
  if (has(refinement.lock, n)) return { ...refinement, lock: without(refinement.lock, n) };
  if ((refinement.lock || []).length >= MAX_REFINEMENT_ASSETS) return refinement;
  return {
    ...refinement,
    lock: [...(refinement.lock || []), n],
    exclude: without(refinement.exclude, n),
  };
}

export function toggleExclude(refinement, name) {
  const n = clean(name);
  if (!n) return refinement;
  if (has(refinement.exclude, n)) return { ...refinement, exclude: without(refinement.exclude, n) };
  if ((refinement.exclude || []).length >= MAX_REFINEMENT_ASSETS) return refinement;
  return {
    ...refinement,
    exclude: [...(refinement.exclude || []), n],
    lock: without(refinement.lock, n),
  };
}

export function toggleSkip(refinement, name) {
  const n = clean(name);
  if (!n) return refinement;
  if (has(refinement.skip, n)) return { ...refinement, skip: without(refinement.skip, n) };
  return { ...refinement, skip: [...(refinement.skip || []), n] };
}

export function hasRefinement(refinement) {
  return Boolean(
    refinement?.lock?.length || refinement?.exclude?.length || refinement?.skip?.length,
  );
}

// The wire shape `refinement: {lock, exclude}` the generated-trade routes
// validate with constraints.validate_refinement.  Skip never travels here.
export function toRequest(refinement) {
  return {
    lock: [...(refinement?.lock || [])].sort(),
    exclude: [...(refinement?.exclude || [])].sort(),
  };
}
