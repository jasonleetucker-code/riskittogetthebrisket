/**
 * Device / network profile detection — drives mobile-specific
 * payload, polling, and rendering decisions.
 *
 * Pure SSR-safe: all checks guard on `typeof window !== "undefined"`
 * so server-rendered output is stable (doesn't leak device state
 * into the HTML).
 */

const MOBILE_VIEWPORT_PX = 768;

/**
 * Returns true for small viewports OR low-memory devices.
 * Used to route /api/data requests to the compact view and
 * to reduce polling intervals.
 */
export function isMobileProfile() {
  if (typeof window === "undefined") return false;
  // Viewport-based — covers phones in portrait + smaller tablets.
  if (window.innerWidth && window.innerWidth < MOBILE_VIEWPORT_PX) {
    return true;
  }
  // navigator.deviceMemory is an advisory signal: <=4GB → treat
  // as mobile-class for perf purposes.  Missing → ignore.
  if (
    typeof navigator !== "undefined" &&
    typeof navigator.deviceMemory === "number" &&
    navigator.deviceMemory <= 4
  ) {
    return true;
  }
  return false;
}

/**
 * Effective connection type, when the browser exposes it:
 * "slow-2g" | "2g" | "3g" | "4g" | undefined
 */
export function effectiveConnectionType() {
  if (typeof navigator === "undefined") return undefined;
  const conn = navigator.connection || navigator.mozConnection || navigator.webkitConnection;
  return conn?.effectiveType;
}

/**
 * Returns true when the browser reports a slow connection
 * (2G/3G) — caller can skip charts / reduce fetch frequency.
 */
export function isSlowNetwork() {
  const t = effectiveConnectionType();
  return t === "slow-2g" || t === "2g" || t === "3g";
}

/**
 * Return `true` when the tab is currently in the foreground.
 * Safe during SSR (returns true).
 */
export function isTabVisible() {
  if (typeof document === "undefined") return true;
  return !document.hidden;
}

/**
 * Compute the appropriate polling interval for background data
 * (status, user state, rank deltas) given device + network profile.
 *
 *   Foreground desktop:     baseMs
 *   Foreground mobile:      baseMs × 2
 *   Foreground slow net:    baseMs × 3
 *   Background (hidden):    baseMs × 10  (or caller can skip entirely)
 */
export function adjustedPollingMs(baseMs, { when = "foreground" } = {}) {
  if (when === "background" || !isTabVisible()) {
    return baseMs * 10;
  }
  if (isSlowNetwork()) return baseMs * 3;
  if (isMobileProfile()) return baseMs * 2;
  return baseMs;
}

/**
 * Append `view=compact` to /api/data URLs on mobile so the
 * frontend gets the ~500KB pruned view instead of ~4MB full.
 * The frontend materializer ignores missing audit fields
 * gracefully (shape test pins the contract).
 */
export function preferredDataView() {
  if (isMobileProfile() || isSlowNetwork()) {
    return "compact";
  }
  return "delta";  // existing default
}
