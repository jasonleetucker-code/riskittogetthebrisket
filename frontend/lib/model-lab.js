/**
 * Model Lab — display materializer for `GET /api/model-lab` (IC-6).
 *
 * The backend (`src/model_registry/model_lab.py`, AL-0b / IC-5) is the one
 * owner of every fact this page shows: champion / challenger rows, lab
 * states, AL-0 verdicts, gate results, what is served and how to roll it
 * back.  This module only RESHAPES that payload for rendering — it decides
 * no state, re-derives no verdict, computes no metric and invents no count.
 * Same relationship `buildRows` has with the canonical contract.
 *
 * MISSING IS NEVER ZERO.  The backend writes every field as observed data
 * or as an explicit state block — `{state: "unobserved" | "not_applicable" |
 * "unmeasured", reason}`.  A state block is carried through to the renderer
 * untouched (it renders as its label plus the backend's reason), never
 * coerced to 0, "—" or an empty cell.  A genuine `0`, `[]` or `{}` is data
 * and renders as such.
 *
 * READ-ONLY.  Nothing here (or anywhere in the Model Lab UI) builds a
 * request other than a GET of the Lab itself.  Evaluation is not
 * activation: promotion, apply and rollback happen outside the Lab, under
 * each family's own promotion authority.
 */

/** The backend's state-block vocabulary (`model_lab.is_state_block`). */
export const STATE_BLOCK_LABELS = Object.freeze({
  unobserved: "Unobserved",
  not_applicable: "Not applicable",
  unmeasured: "Unmeasured",
});

/** Lab states in the backend's fixed order — the fallback when a payload omits `labStates`. */
export const DEFAULT_LAB_STATES = Object.freeze([
  "CHAMPION",
  "SHADOW",
  "HELD",
  "REJECTED",
  "INSUFFICIENT_EVIDENCE",
  "RETIRED",
]);

const LAB_STATE_LABELS = Object.freeze({
  CHAMPION: "Champion",
  SHADOW: "Shadow",
  HELD: "Held",
  REJECTED: "Rejected",
  INSUFFICIENT_EVIDENCE: "Insufficient evidence",
  RETIRED: "Retired",
});

export const READ_ONLY_NOTE =
  "Read-only. The Model Lab shows evidence; it cannot promote, apply or roll back. " +
  "Any change runs outside the Lab under the family's own promotion authority.";

/**
 * Mirror of `model_lab.is_state_block`: a known state AND a non-empty reason.
 * An object that merely has a `state` key (e.g. receipts' `"observed"`) is
 * ordinary data.
 */
export function isStateBlock(value) {
  return Boolean(
    value &&
      typeof value === "object" &&
      !Array.isArray(value) &&
      Object.prototype.hasOwnProperty.call(STATE_BLOCK_LABELS, value.state) &&
      String(value.reason ?? "").trim(),
  );
}

export function stateBlockLabel(block) {
  return STATE_BLOCK_LABELS[block?.state] || "Unobserved";
}

export function labStateLabel(state) {
  return LAB_STATE_LABELS[state] || String(state);
}

/**
 * `rowsPerHoldoutBoard` -> "Rows per holdout board".  Only plain lower-camel
 * keys are humanized; anything else (`rmse[FantasyCalc]`,
 * `C1_conservative_reliability`, a board name) is a backend identifier and
 * is shown verbatim.
 */
export function humanizeKey(key) {
  const k = String(key);
  if (!/^[a-z][a-zA-Z0-9]*$/.test(k)) return k;
  const spaced = k.replace(/([a-z0-9])([A-Z])/g, "$1 $2").toLowerCase();
  // Keep well-known acronyms legible.
  const fixed = spaced
    .replace(/\bal0\b/g, "AL-0")
    .replace(/\bsha\b/g, "SHA")
    .replace(/\bsha256\b/g, "SHA-256")
    .replace(/\bid\b/g, "ID")
    .replace(/\bids\b/g, "IDs");
  return fixed.charAt(0).toUpperCase() + fixed.slice(1);
}

const INSTANT_RE = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:\d{2})$/;

/** True for a timezone-aware ISO instant (the only kind the backend passes through). */
export function isInstantString(value) {
  return typeof value === "string" && INSTANT_RE.test(value.trim());
}

/**
 * Display form of an instant: `2026-10-08 06:53 UTC`.  Formatting only — the
 * raw string is kept by the renderer for the `<time dateTime>` attribute.
 */
export function formatInstant(value) {
  if (!isInstantString(value)) return null;
  const d = new Date(value.trim());
  if (Number.isNaN(d.getTime())) return null;
  const iso = d.toISOString();
  return `${iso.slice(0, 10)} ${iso.slice(11, 16)} UTC`;
}

/** ON / OFF / Unobserved for one flag record — an unreadable flag is never OFF. */
export function flagWord(flag) {
  if (!flag || typeof flag !== "object") return "Unobserved";
  if (flag.enabled === true) return "ON";
  if (flag.enabled === false) return "OFF";
  return "Unobserved";
}

/**
 * The flags a family's `productionState` names, in the backend's order.
 *
 * The backend SPREADS `_flag_state()` into `productionState`, so a flag that
 * could not be read makes the whole record look like a state block —
 * `{flag, state: "unobserved", reason, ...siblings}`.  That record is still
 * a flag record with siblings, so the `flags` list (the #1708 shape) and the
 * single top-level `flag` (the shape on main) are read BEFORE any state-block
 * test; only a bare block with no flag at all yields no flags.  The list
 * wins over the top-level flag, so a flag is never listed twice.
 */
export function productionFlags(productionState) {
  if (!productionState || typeof productionState !== "object" || Array.isArray(productionState)) {
    return [];
  }
  const asFlag = (f) => ({
    flag: String(f.flag),
    word: flagWord(f),
    reason: isStateBlock(f) ? String(f.reason) : null,
  });
  if (Array.isArray(productionState.flags)) {
    return productionState.flags.filter((f) => f && typeof f === "object" && f.flag).map(asFlag);
  }
  if (productionState.flag) return [asFlag(productionState)];
  return [];
}

/**
 * What is served now, as the backend states it: the first of `servedNote`,
 * `served`, `servedPath`, `servedSide` that is present (string or state
 * block).  Read before any state-block test, for the same reason as
 * `productionFlags`.  A bare state block with no flag (e.g. a failed
 * builder) is returned as itself; otherwise `null` means the flags carry
 * the answer.
 */
export function servedStatement(productionState) {
  if (!productionState || typeof productionState !== "object") return null;
  for (const key of ["servedNote", "served", "servedPath", "servedSide"]) {
    const v = productionState[key];
    if (typeof v === "string" && v.trim()) return v;
    if (isStateBlock(v)) return v;
  }
  if (isStateBlock(productionState) && !productionState.flag) return productionState;
  return null;
}

/**
 * A state block's sibling fields — everything but `state` / `reason` — or
 * `null` when it has none.  A spread record such as
 * `{flag, state: "unobserved", reason, modelVersion, ...}` is a state PLUS
 * evidence; the evidence must stay visible beside the badge.
 */
export function stateBlockExtras(value) {
  if (!isStateBlock(value)) return null;
  const extras = Object.fromEntries(
    Object.entries(value).filter(([k]) => k !== "state" && k !== "reason"),
  );
  return Object.keys(extras).length ? extras : null;
}

/** `champion.version`, or the state block that stands in for it. */
export function championVersion(champion) {
  if (isStateBlock(champion)) return champion;
  if (!champion || typeof champion !== "object") {
    return { state: "unobserved", reason: "the payload carries no champion block" };
  }
  const v = champion.version;
  if (v === undefined || v === null) {
    return { state: "unobserved", reason: "the champion block carries no version" };
  }
  return v;
}

/** `lastEvaluation.at` (+ `by`), or the state block that stands in for it. */
export function lastEvaluated(lastEvaluation) {
  if (isStateBlock(lastEvaluation)) return { at: lastEvaluation, by: null };
  if (!lastEvaluation || typeof lastEvaluation !== "object") {
    return {
      at: { state: "unobserved", reason: "the payload carries no lastEvaluation block" },
      by: null,
    };
  }
  const at =
    lastEvaluation.at === undefined || lastEvaluation.at === null
      ? { state: "unobserved", reason: "the evaluation records no instant" }
      : lastEvaluation.at;
  return { at, by: typeof lastEvaluation.by === "string" ? lastEvaluation.by : null };
}

/**
 * Per-state counts in the payload's lab-state order, read VERBATIM from the
 * family's `challengerStates` (the backend counts; this does not).  Returns
 * the state block when the family's states are unobserved.
 */
export function challengerStateCounts(family, labStates = DEFAULT_LAB_STATES) {
  const states = family?.challengerStates;
  if (isStateBlock(states)) return states;
  if (!states || typeof states !== "object") {
    return { state: "unobserved", reason: "the payload carries no challengerStates block" };
  }
  const order = Array.isArray(labStates) && labStates.length ? labStates : DEFAULT_LAB_STATES;
  const known = order.filter((s) => Object.prototype.hasOwnProperty.call(states, s));
  const extra = Object.keys(states).filter((s) => !order.includes(s));
  return [...known, ...extra].map((s) => ({ state: s, label: labStateLabel(s), count: states[s] }));
}

/** The challenger rows (or the state block standing in for them). */
export function challengerRows(family) {
  const rows = family?.challengers;
  if (isStateBlock(rows)) return rows;
  if (!Array.isArray(rows)) {
    return { state: "unobserved", reason: "the payload carries no challengers list" };
  }
  return rows;
}

/**
 * Display selection of challenger rows: one lab state (or all), newest first
 * (the backend lists them oldest first).  Selection only — the rows are the
 * backend's own objects.
 */
export function selectChallengers(rows, state = "ALL") {
  if (!Array.isArray(rows)) return [];
  const picked = state === "ALL" ? rows : rows.filter((r) => r && r.state === state);
  return [...picked].reverse();
}

/** The families list, or `null` when the payload has none (malformed). */
export function familiesOf(payload) {
  return payload && Array.isArray(payload.families) ? payload.families : null;
}

export function findFamily(payload, id) {
  const families = familiesOf(payload) || [];
  return families.find((f) => f && f.family === id) || null;
}

/** One list row per family — every cell a backend value or state block. */
export function familyListRows(payload) {
  const families = familiesOf(payload) || [];
  const labStates = payload?.labStates;
  return families
    .filter((f) => f && typeof f === "object" && f.family)
    .map((f) => ({
      id: String(f.family),
      name: typeof f.name === "string" && f.name ? f.name : String(f.family),
      domain: f.domain,
      champion: championVersion(f.champion),
      states: challengerStateCounts(f, labStates),
      lastEvaluated: lastEvaluated(f.lastEvaluation),
      decision: f.decisionReason,
      flags: productionFlags(f.productionState),
      served: servedStatement(f.productionState),
    }));
}

/** Families whose builder failed, as `[{family, error}]`. */
export function builderErrors(payload) {
  const errs = payload?.builderErrors;
  if (!errs || typeof errs !== "object") return [];
  return Object.entries(errs).map(([family, error]) => ({ family, error: String(error) }));
}

/** Domains the Lab says it does not cover, as `[{domain, reason}]`. */
export function notCovered(payload) {
  const rows = payload?.notCovered;
  return Array.isArray(rows) ? rows.filter((r) => r && typeof r === "object") : [];
}

/** Family ids are snake_case on the backend; anything else is not one. */
export function isFamilyId(value) {
  return typeof value === "string" && /^[a-z0-9_]{1,64}$/.test(value);
}
