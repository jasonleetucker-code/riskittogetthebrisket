/**
 * dfs.js — pure helpers for the /dfs workspace.
 *
 * A materializer only: every number shown on /dfs (lineups, totals, solver
 * status, readiness) is computed by the backend (`src/dfs/`).  Nothing here
 * ranks players, estimates projections or re-derives a lineup.
 *
 * Missing is never zero: a null projection renders as "No projection" and is
 * never summed, sorted as 0, or coerced.
 */

export const SPORTS = [
  { value: "nfl", label: "NFL" },
  { value: "nba", label: "NBA" },
  { value: "nhl", label: "NHL" },
  { value: "mma", label: "MMA" },
];

export const PLATFORMS = [
  { value: "draftkings", label: "DraftKings" },
  { value: "fanduel", label: "FanDuel" },
];

export const FORMAT_LABELS = {
  classic: "Classic",
  showdown_captain: "Showdown Captain",
  single_game_mvp: "Single Game MVP",
};

const READINESS = {
  money_ready: { label: "Verified rules", status: "positive" },
  research_only: { label: "Research only — rules unverified", status: "warning" },
  not_implemented: { label: "Not available yet", status: "neutral" },
};

export function readinessCopy(readiness) {
  return READINESS[readiness] || { label: "Unknown readiness", status: "neutral" };
}

/** Capability rows for one sport × platform, in registry order. */
export function capabilitiesFor(matrix, sport, platform) {
  return (matrix || []).filter((r) => r.sport === sport && r.platform === platform);
}

/** The rule set a capability row names, or null. */
export function rulesetFor(capabilities, row) {
  if (!row || !row.ruleset || !capabilities) return null;
  return (capabilities.rulesets || []).find((r) => r.key === row.ruleset) || null;
}

export function formatSalary(n) {
  if (typeof n !== "number" || !Number.isFinite(n)) return "—";
  return `$${n.toLocaleString("en-US")}`;
}

export function formatPoints(v) {
  if (v === null || v === undefined || !Number.isFinite(Number(v))) return null;
  return Number(v).toFixed(2);
}

/** Points per $1,000 of salary; null when either side is missing. */
export function pointsPerK(athlete) {
  const p = athlete?.projection;
  const s = athlete?.salary;
  if (p === null || p === undefined || !s) return null;
  return p / (s / 1000);
}

export function positionsIn(athletes) {
  const seen = [];
  for (const a of athletes || []) {
    for (const p of a.positions || []) if (!seen.includes(p)) seen.push(p);
  }
  return seen;
}

export function filterAthletes(athletes, { position = "ALL", query = "", hideUnprojected = false } = {}) {
  const q = query.trim().toLowerCase();
  return (athletes || []).filter((a) => {
    if (position !== "ALL" && !(a.positions || []).includes(position)) return false;
    if (hideUnprojected && (a.projection === null || a.projection === undefined)) return false;
    if (q && !`${a.name} ${a.team}`.toLowerCase().includes(q)) return false;
    return true;
  });
}

/** Lock/exclude are mutually exclusive: setting one clears the other. */
export function setPlayerRule(rules, playerId, rule) {
  const locks = new Set(rules.locks);
  const excludes = new Set(rules.excludes);
  locks.delete(playerId);
  excludes.delete(playerId);
  if (rule === "lock") locks.add(playerId);
  if (rule === "exclude") excludes.add(playerId);
  return { locks: [...locks], excludes: [...excludes] };
}

function wholeOrNull(raw) {
  if (raw === "" || raw === null || raw === undefined) return null;
  const n = Number(raw);
  return Number.isInteger(n) ? n : NaN;
}

/**
 * Owner form state → the backend constraint payload.  Returns
 * `{ payload, errors }`; errors are field-keyed messages, and the payload is
 * only meaningful when `errors` is empty.  Percentages are entered 0–100 and
 * sent as fractions.
 */
export function buildConstraints(form, rules) {
  const errors = {};
  const payload = { locks: [...(rules?.locks || [])], excludes: [...(rules?.excludes || [])] };
  const lineups = wholeOrNull(form.lineups);
  if (lineups === null || Number.isNaN(lineups) || lineups < 1 || lineups > 150) {
    errors.lineups = "Enter a whole number from 1 to 150.";
  } else {
    payload.lineups = lineups;
  }
  const minUnique = wholeOrNull(form.minUnique);
  if (minUnique !== null) {
    if (Number.isNaN(minUnique) || minUnique < 1) errors.minUnique = "Enter a whole number of at least 1.";
    else payload.minUnique = minUnique;
  }
  const exposure = form.maxExposurePct === "" || form.maxExposurePct == null ? null : Number(form.maxExposurePct);
  if (exposure !== null) {
    if (!Number.isFinite(exposure) || exposure <= 0 || exposure > 100) errors.maxExposurePct = "Enter a percentage above 0 and at most 100.";
    else payload.maxExposure = exposure / 100;
  }
  for (const [key, field] of [
    ["salaryMin", "salaryMin"],
    ["maxPerTeam", "maxPerTeam"],
  ]) {
    const v = wholeOrNull(form[field]);
    if (v === null) continue;
    if (Number.isNaN(v) || v < 0) errors[field] = "Enter a whole number.";
    else payload[key] = v;
  }
  if (form.stack) {
    // Blank is not a count: the form starts at 1 / 0, so a blank field was
    // cleared on purpose and must be re-entered rather than guessed.
    const minSecondary = wholeOrNull(form.stackMin);
    const bringBack = wholeOrNull(form.stackBringBack);
    if (
      minSecondary === null ||
      bringBack === null ||
      Number.isNaN(minSecondary) ||
      Number.isNaN(bringBack) ||
      minSecondary < 0 ||
      bringBack < 0
    ) {
      errors.stack = "Enter whole numbers for both stack counts.";
    } else {
      payload.stacks = [
        {
          label: "QB stack",
          primary: ["QB"],
          secondary: form.stackSecondary?.length ? form.stackSecondary : ["WR", "TE"],
          minSecondary,
          bringBack,
        },
      ];
    }
  }
  return { payload, errors };
}

/** Exposure count a percentage cap allows for N lineups — floor, as the backend does. */
export function exposureCountFor(pct, lineups) {
  if (!Number.isFinite(pct) || !Number.isInteger(lineups) || lineups < 1) return null;
  return Math.floor((pct / 100) * lineups + 1e-9);
}

const STATUS_COPY = {
  optimal: "Optimal for this objective — the solver proved no higher projected total exists under these rules and constraints.",
  partial: "Fewer lineups than requested — see why below. Constraints were not relaxed.",
  timed_out_with_feasible_result: "Time budget reached. Lineups shown are valid but not proven optimal.",
  timed_out: "Time budget reached before any valid lineup was found.",
  infeasible: "No lineup satisfies every rule and constraint.",
  unavailable: "The solver could not produce a trustworthy result.",
};

export function statusCopy(status, built = 1) {
  if (status === "optimal" && built > 1) {
    return "Each lineup is optimal given the ones before it: no higher projected total exists for it under the rules, your constraints and the uniqueness/exposure limits set by earlier lineups. The set as a whole is built in sequence, not jointly optimized.";
  }
  return STATUS_COPY[status] || "Unknown solver status.";
}

/**
 * A single-lineup build ignores portfolio-only controls: an exposure cap of
 * p% over ONE lineup floors to zero appearances and would make every
 * unlocked player ineligible.
 */
export function singleLineupForm(form) {
  return { ...form, lineups: "1", maxExposurePct: "", minUnique: "" };
}

export function statusTone(status) {
  if (status === "optimal") return "positive";
  if (status === "partial" || status === "timed_out_with_feasible_result") return "warning";
  return "negative";
}

/** Structured backend error → one readable sentence. */
export function errorMessage(body, fallback = "Something went wrong.") {
  if (!body || typeof body !== "object") return fallback;
  return body.message || body.error || fallback;
}

export const STORAGE_KEY = "dfs.context.v1";

export function readStoredContext() {
  try {
    const raw = globalThis.localStorage?.getItem(STORAGE_KEY);
    if (!raw) return null;
    const v = JSON.parse(raw);
    return v && typeof v === "object" ? v : null;
  } catch {
    return null;
  }
}

export function writeStoredContext(ctx) {
  try {
    globalThis.localStorage?.setItem(STORAGE_KEY, JSON.stringify(ctx));
  } catch {
    /* storage unavailable (private mode) — the page works without it */
  }
}
