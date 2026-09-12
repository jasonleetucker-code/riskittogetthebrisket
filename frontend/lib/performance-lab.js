// Opt-in attribution only. Acceptance runs compile this flag off and never
// install the browser collector. No data, settings, URLs or identifiers enter it.
export const PERFORMANCE_LAB_BUILD = process.env.NEXT_PUBLIC_PERFORMANCE_LAB === "1";
const SCOPES = new Set(["shell", "auth", "settings", "legacy", "rankings", "trade", "catalog", "table"]);
const CONSUMERS = new Set(["shared", "shell", "rankings-page", "trade-page"]);
const NUMBERS = ["actualDuration", "baseDuration", "startTime", "commitTime", "rows"];
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

function increment(collector, key) {
  const previous = collector[key];
  collector[key] = Math.min(Number.MAX_SAFE_INTEGER,
    (Number.isSafeInteger(previous) && previous >= 0 ? previous : 0) + 1);
}

export function performanceLabMark(phase, scope = "shell", numbers = {}, consumer = null) {
  if (!performanceLabEnabled()) return;
  const collector = window.__CHASE_PERFORMANCE_LAB;
  if (!PHASES.has(phase) || !SCOPES.has(scope)
      || (consumer !== null && !CONSUMERS.has(consumer))
      || !numbers || typeof numbers !== "object" || Array.isArray(numbers)
      || !Array.isArray(collector.events)) {
    increment(collector, "invalidEvents");
    return;
  }
  if (collector.events.length >= 4000) {
    increment(collector, "droppedEvents");
    return;
  }
  const event = { phase, scope, timeMs: performance.now() };
  if (consumer !== null) event.consumer = consumer;
  for (const key of Object.keys(numbers)) {
    if (NUMBERS.includes(key) && Number.isFinite(numbers[key]) && numbers[key] >= 0) {
      event[key] = numbers[key];
    } else {
      increment(collector, "invalidFields");
    }
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
