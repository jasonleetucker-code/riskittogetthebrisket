const ROUTES = new Set([
  "/", "/rankings", "/trade", "/draft", "/waivers", "/rosters", "/bdvm",
  "/league", "/league-comparison", "/game-day", "/players/compare", "/login",
  "/settings", "/more", "/news", "/trending", "/trades", "/edge", "/finder",
  "/angle", "/arbitrage", "/phases", "/intel", "/consensus-edge",
  "/market/sharp-tracker", "/market/sharp-roster-percentage",
]);
const METRICS = new Set(["LCP", "INP", "CLS", "FCP", "TTFB"]);
const NAVIGATION_TYPES = new Set(["navigate", "reload", "back-forward", "back-forward-cache", "prerender", "restore"]);

/** Only fixed route names cross the telemetry boundary, never entity IDs. */
export function vitalsRouteTemplate(pathname) {
  const path = String(pathname || "").split(/[?#]/, 1)[0].replace(/\/$/, "") || "/";
  if (ROUTES.has(path)) return path;
  if (/^\/players\/[^/]+$/.test(path)) return "/players/[playerId]";
  if (/^\/rankings\/(qb|rb|wr|te|dl|lb|db|idp|rookies)$/i.test(path)) return "/rankings/[position]";
  return null;
}

export function webVitalsPayload(metric, { route, device = "unknown" } = {}) {
  if (!METRICS.has(metric?.name) || !Number.isFinite(metric?.value) || metric.value < 0) return null;
  if (!ROUTES.has(route) && route !== "/players/[playerId]" && route !== "/rankings/[position]") return null;
  if (typeof metric.id !== "string" || !/^[a-zA-Z0-9_-]{1,64}$/.test(metric.id)) return null;
  return {
    name: metric.name,
    value: metric.value,
    id: metric.id,
    route,
    navigationType: NAVIGATION_TYPES.has(metric.navigationType) ? metric.navigationType : "navigate",
    device: ["desktop", "mobile"].includes(device) ? device : "unknown",
  };
}
