/**
 * Display formatting for guest-pass expiry.
 *
 * A module rather than a private helper, because the private helper is
 * what broke: `GuestPassPanel` was extracted out of `/settings` and its two
 * calls to `fmtPassExpiry` went with it while the definition stayed behind
 * as dead code in `app/settings/page.jsx`.  `/admin` then reached the
 * global client-side error boundary with `Can't find variable:
 * fmtPassExpiry` on every load that had a pass to list (#779).
 *
 * Moving it here makes the function importable, testable on its own, and
 * — because a module-level export cannot be orphaned by extracting its
 * caller — unable to fail the same way twice.
 */

const MIN = 60;
const HOUR = 60 * MIN;

/**
 * Human-readable expiry for a unix-epoch SECONDS timestamp.
 *
 * Future  → relative ("in 45m" / "in 6h" / "in 3d"), because what an
 *           operator handing out a credential wants to know is how much
 *           longer it works.
 * Past    → the absolute local date/time, because "3 days ago" does not
 *           help you find the pass in a log.
 * Missing → an em dash.
 *
 * MISSING IS NEVER ZERO: `null`, `undefined`, a non-numeric value and a
 * non-positive epoch all return "—" rather than a date.  Epoch 0 is a real
 * instant, so rendering it would tell an operator the pass expired in 1970
 * instead of that the backend stamped nothing.
 *
 * @param {number|string|null|undefined} epoch unix seconds
 * @returns {string}
 */
export function fmtPassExpiry(epoch) {
  const seconds = Number(epoch);
  if (!Number.isFinite(seconds) || seconds <= 0) return "—";
  const ms = seconds * 1000;
  const remainingMin = Math.round((ms - Date.now()) / (MIN * 1000));
  if (remainingMin > 0 && remainingMin < 60) return `in ${remainingMin}m`;
  if (remainingMin > 0 && remainingMin < 60 * 24) {
    return `in ${Math.round(remainingMin / 60)}h`;
  }
  if (remainingMin > 0) {
    return `in ${Math.round(remainingMin / (60 * 24))}d`;
  }
  return new Date(ms).toLocaleString();
}
