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
        : "about what those scores average against an equally likely opponent";
  return (
    `${actual} head-to-head wins. The same weekly scores average ${expected} ` +
    `against an equally likely opponent each week (${impact} schedule wins — ${tail}).`
  );
}

/** Record sort key: win share with ties as half, so 5-1 ranks above 5-3. */
export function recordSortValue(row) {
  const r = row?.officialRecord;
  if (!r) return null;
  const games = r.wins + r.losses + r.ties;
  return games ? (r.wins + 0.5 * r.ties) / games : null;
}

/** "1 game not counted" when games were excluded for this team. */
export function excludedNote(row) {
  const weeks = Array.isArray(row?.excludedWeeks) ? row.excludedWeeks : [];
  if (weeks.length === 0) return null;
  const n = weeks.length;
  return `${n} game${n === 1 ? "" : "s"} not counted (week${n === 1 ? "" : "s"} ${weeks.join(", ")})`;
}

/** "Bye: week 5" when the team had no head-to-head game in a finalized week. */
export function byeNote(row) {
  const weeks = Array.isArray(row?.byeWeeks) ? row.byeWeeks : [];
  if (weeks.length === 0) return null;
  return `Bye: week${weeks.length === 1 ? "" : "s"} ${weeks.join(", ")}`;
}

/**
 * One team's row from the published block (``luck.scheduleImpact``), or null.
 * A lookup only: the block is the canonical contract, nothing is recomputed.
 */
export function teamRowFor(block, season, ownerId) {
  // Orphan rosters carry ownerId null: a missing id must never match them.
  if (!ownerId) return null;
  const contract = block?.bySeason?.[String(season)];
  if (!contract || !Array.isArray(contract.teams)) return null;
  return contract.teams.find((t) => t.ownerId === ownerId) || null;
}

/** Honest copy for every non-complete contract state, by its actual reason. */
export function stateNotice(contract) {
  if (!contract) return { tone: "info", text: "Schedule impact is not available yet." };
  switch (contract.state) {
    case "complete":
      return null;
    case "failed":
      return { tone: "warning", text: "Schedule impact could not be calculated right now." };
    case "partial": {
      const missing = Array.isArray(contract.teamsWithoutEvaluableGames)
        ? contract.teamsWithoutEvaluableGames.length
        : 0;
      return {
        tone: "warning",
        text:
          "Some games could not be evaluated (a score or a matchup row is missing), so they are " +
          "left out; each affected team is marked." +
          (missing ? ` ${missing} team${missing === 1 ? " has" : "s have"} no countable game.` : ""),
      };
    }
    case "unsupported":
      return {
        tone: "warning",
        text:
          "This league's format (more than one game per team in a week) is not supported " +
          "by this model yet, so no schedule impact is shown.",
      };
    case "unavailable":
    default:
      if (contract.reason === "no_finalized_weeks") {
        return {
          tone: "info",
          text: "No finished regular-season weeks yet — schedule impact appears once a week is final.",
        };
      }
      return { tone: "info", text: "No game in this season could be evaluated, so no schedule impact is shown." };
  }
}

// ── Milestone B: timing_only_v1 (same opponents, different weeks) ─────────

/** Integer percent for a probability; "<1%" / ">99%" instead of a false 0/100. */
export function fmtShare(p) {
  if (!isNum(p)) return "—";
  if (p > 0 && p < 0.005) return "<1%";
  if (p < 1 && p > 0.995) return ">99%";
  return `${Math.round(p * 100)}%`;
}

/** Win credits exactly: whole numbers bare, half credits (ties) as "5.5". */
export function fmtExactCredits(v) {
  if (!isNum(v)) return "—";
  return Number.isInteger(v) ? String(v) : v.toFixed(1);
}

/** Big exact counts, e.g. 6,227,020,800. */
export function fmtCount(n) {
  return isNum(n) ? Math.round(n).toLocaleString("en-US") : "—";
}

/** Honest copy for the season-level timing block's non-complete states. */
export function timingNotice(timing) {
  if (!timing) return { tone: "info", text: "The week-order view is not available for this season." };
  if (timing.state === "complete") return null;
  if (timing.state === "failed") {
    return { tone: "warning", text: "The week-order view could not be calculated right now." };
  }
  if (timing.reason === "no_finalized_weeks") {
    return { tone: "info", text: "No finished weeks yet — the week-order view appears once a week is final." };
  }
  if (timing.reason === "too_many_weeks_for_exact") {
    return {
      tone: "info",
      text: "This season has more finished weeks than the exact week-order count supports, so it is not shown.",
    };
  }
  if (timing.reason === "structural_issues" || timing.reason === "missing_score") {
    return {
      tone: "warning",
      text: "Some weeks have a missing score or matchup row, so week orders cannot be compared this season.",
    };
  }
  return { tone: "info", text: "This season's format is not supported by the week-order view." };
}

/** One reading for a team's timing-only row, from backend numbers only. */
export function timingReading(row) {
  const t = row?.timingOnly;
  if (!t || t.state !== "complete" || !isNum(row.actualH2HCredits)) return null;
  const actual = fmtCredits(row.actualH2HCredits, row.h2hTies ? 1 : 0);
  return (
    `Same opponents, weeks reordered: these scores average ${fmtCredits(t.expectedCredits)} ` +
    `head-to-head wins (at least 80% of orderings: ${fmtCredits(t.central80?.low, 1)}–${fmtCredits(t.central80?.high, 1)}). ` +
    `Against the actual ${actual}, ${fmtShare(t.probAboveActual)} of orderings give more wins and ` +
    `${fmtShare(t.probBelowActual)} give fewer.`
  );
}
