// Schedule Intelligence — display helpers for the canonical schedule-impact
// contract (src/public_league/schedule_impact.py).
//
// Pure formatting.  Every number here arrives from the backend contract;
// nothing in this file computes all-play, expected credits or schedule
// impact, and nothing may (one owner, no duplicate arithmetic).  The
// interpretation sentence only arranges backend numbers into words.

const MINUS = "−";

function isNum(v) {
  return typeof v === "number" && Number.isFinite(v);
}

/** Expected / actual win credits — fractional, never shown as a record. */
export function fmtCredits(v, dp = 1) {
  return isNum(v) ? v.toFixed(dp) : "—";
}

/** Signed win credits: "+0.9", "−0.4", "0.0" (never a bare "-0.0"). */
export function fmtSignedCredits(v, dp = 1) {
  if (!isNum(v)) return "—";
  const r = Number(v.toFixed(dp));
  if (r === 0) return (0).toFixed(dp);
  return `${r > 0 ? "+" : MINUS}${Math.abs(r).toFixed(dp)}`;
}

/** Direction of a rounded impact, for the sign glyph + token (never colour alone). */
export function impactDirection(v, dp = 1) {
  if (!isNum(v)) return "none";
  const r = Number(v.toFixed(dp));
  return r > 0 ? "up" : r < 0 ? "down" : "flat";
}

export function fmtRecord(wins, losses, ties) {
  if (![wins, losses].every((x) => Number.isInteger(x))) return "—";
  return ties ? `${wins}-${losses}-${ties}` : `${wins}-${losses}`;
}

export function fmtRate(v) {
  return isNum(v) ? `${Math.round(v * 100)}%` : "—";
}

/** The official (host) record, or "—" when the host did not report one. */
export function officialRecord(row) {
  const r = row?.officialRecord;
  return r ? fmtRecord(r.wins, r.losses, r.ties) : "—";
}

/** The median / league-average component, when it is actually known. */
export function medianRecord(row) {
  const m = row?.medianComponent;
  if (!m) return null;
  if (m.state === "complete") return fmtRecord(m.wins, m.losses, m.ties);
  return null;
}

export function teamLabel(row) {
  if (!row) return "—";
  if (row.teamName) return row.teamName;
  if (row.orphanRoster) return `Roster ${row.rosterId} (no manager)`;
  return row.displayName || "—";
}

/**
 * One plain-English reading, from backend numbers only.  States what was
 * measured, not what it says about the manager.
 */
export function interpretation(row) {
  if (!row || !isNum(row.actualH2HCredits) || !isNum(row.equalOpponentExpectedH2HCredits)) {
    return null;
  }
  const actual = fmtCredits(row.actualH2HCredits, row.h2hTies ? 1 : 0);
  const expected = fmtCredits(row.equalOpponentExpectedH2HCredits);
  const impact = fmtSignedCredits(row.scheduleImpact);
  const dir = impactDirection(row.scheduleImpact);
  const tail =
    dir === "up"
      ? "the schedule helped"
      : dir === "down"
        ? "the schedule cost them"
        : "about what those scores earn against an average opponent";
  return (
    `${actual} head-to-head wins. The same weekly scores average ${expected} ` +
    `against an equally likely opponent each week (${impact} schedule wins — ${tail}).`
  );
}

/** Honest copy for every non-complete contract state. */
export function stateNotice(contract) {
  if (!contract) return { tone: "info", text: "Schedule impact is not available yet." };
  switch (contract.state) {
    case "complete":
      return null;
    case "partial":
      return {
        tone: "warning",
        text:
          "Some games could not be evaluated (a score is missing), so they are left " +
          "out. Totals cover only the games shown.",
      };
    case "unsupported":
      return {
        tone: "warning",
        text:
          "This league's format (more than one game per team in a week) is not supported " +
          "by this model yet, so no schedule impact is shown.",
      };
    case "unavailable":
    default:
      return {
        tone: "info",
        text: "No finished regular-season weeks yet — schedule impact appears after week 1 is final.",
      };
  }
}
