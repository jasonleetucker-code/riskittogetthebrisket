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
 * Which `/api/data` view the contract fetch should request.
 *
 *   Mobile / slow network → "compact"
 *   Desktop              → "array"
 *
 * BOTH views serve the same board.  That is a property this pair did
 * not have until 2026-08-18: "compact" pruned 14 fields the
 * materializer reads, so mobile rendered a different Flagged count, a
 * different confidence string and a different Consensus sort order
 * than desktop for the same player.  It now prunes only fields no
 * frontend consumer reads, pinned by
 * `tests/api/test_compact_view_consumer_parity.py`.
 *
 * Measured on a 1,109-row contract, gzip level 6 (2026-08-18):
 *
 *     full      13.09 MB raw   1,092.8 KB gz
 *     array      7.25 MB raw     631.8 KB gz   ← desktop
 *     compact    5.24 MB raw     491.0 KB gz   ← mobile
 *
 * "compact" was 735.0 KB gz before the repair — the LARGEST of the two
 * optimized views, because it carried the legacy `players` dict as well
 * as `playersArray` while "array" dropped it.  The relation is now
 * pinned by `tests/api/test_compact_view_byte_budget.py`; quoting a
 * stale absolute here is how a payload budget stops being one.
 *
 * Desktop deliberately does NOT use "app"/"runtime" (drops
 * `playersArray`, losing tier ids, confidence, and the audit fields
 * 20+ desktop surfaces render) or "compact" (prunes audit fields the
 * desktop rankings board and PlayerPopup show).  Row-parity against
 * the full view is pinned by `tests/api/test_array_view.py`.
 *
 * Historical note: this used to return "delta" for desktop, which is
 * NOT a valid `GET /api/data` view — the caller dropped it and the
 * request went out with no view param at all, silently serving the
 * full ~11.8MB payload to every desktop browser.
 */
export function preferredDataView() {
  if (isMobileProfile() || isSlowNetwork()) {
    return "compact";
  }
  return "array";
}
