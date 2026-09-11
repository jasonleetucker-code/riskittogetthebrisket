// Opt-in attribution only. Acceptance runs compile this flag off and never
// install the browser collector. No data, settings, URLs or identifiers enter it.
export const PERFORMANCE_LAB_BUILD = process.env.NEXT_PUBLIC_PERFORMANCE_LAB === "1";
const SCOPES = new Set(["shell", "auth", "settings", "legacy", "rankings", "trade", "catalog", "table"]);
const PHASES = new Set([
  "module", "hydrate-commit", "render-start", "render-end", "commit", "probe-start", "probe-end",
  "read-start", "read-end", "hydrated", "prefetch", "gate-ready", "fetch-join", "fetch-cache",
  "fetch-start", "headers", "body-start", "body-end", "parse-start", "parse-end", "fetch-end",
  "publish", "materialize-start", "materialize-end", "materialize-cache", "width-start", "width-end",
  "profile-mount", "profile-update", "profile-nested-update",
]);

export function performanceLabEnabled() {
  return PERFORMANCE_LAB_BUILD && typeof window !== "undefined" && window.__CHASE_PERFORMANCE_LAB?.enabled === true;
}

export function performanceLabMark(phase, scope = "shell", numbers = {}) {
  if (!performanceLabEnabled() || !PHASES.has(phase) || !SCOPES.has(scope)) return;
  const collector = window.__CHASE_PERFORMANCE_LAB;
  if (!Array.isArray(collector.events) || collector.events.length >= 4000) return;
  const event = { phase, scope, timeMs: performance.now() };
  for (const key of ["actualDuration", "baseDuration", "startTime", "commitTime", "rows"]) {
    if (Number.isFinite(numbers[key])) event[key] = numbers[key];
  }
  collector.events.push(event);
}

export function performanceLabProfile(_id, phase, actualDuration, baseDuration, startTime, commitTime) {
  performanceLabMark(`profile-${phase}`, "shell", { actualDuration, baseDuration, startTime, commitTime });
}

export async function performanceLabJson(response, scope) {
  if (!performanceLabEnabled()) return response.json();
  performanceLabMark("body-start", scope);
  const text = await response.text();
  performanceLabMark("body-end", scope);
  performanceLabMark("parse-start", scope);
  try {
    return JSON.parse(text);
  } finally {
    performanceLabMark("parse-end", scope);
  }
}
