/**
 * trade-war-room — request building and presentation for the Trade War Room.
 *
 * DISPLAY ONLY.  Every recommendation, value, VA gap, best-ball impact,
 * lineup-entry rate and roster-capacity state is read verbatim from
 * `POST /api/trade/analyze` (`src/trade/analyze_trade.py`, the one decision
 * owner).  Nothing here scores, weighs or re-derives a trade — the same
 * materializer relationship `buildRows` has with the canonical contract.
 *
 * What lives here:
 *   - `tradeRequestForTeam`: which side of a two-side trade the selected team
 *     GIVES.  The ONE mapping both "Simulate impact" and the War Room use, so
 *     the two can never disagree about which way a trade points.
 *   - `analyzeRequestKey` / `validAnalyzePayload`: request identity, so a late
 *     answer for an earlier trade, team, league or mode can never publish.
 *   - formatters and labels.  Missing stays missing: formatters return null and
 *     callers render a word, never "0".
 */

/**
 * The ONE top-line decision (TC-C) is the backend's
 * (`src/trade/trade_decision.py`): the page renders `decision.headlineText`
 * verbatim and keys only a TONE off `decision.headline`.  No text is built
 * here.
 */
export const DECISION_TONES = {
  YES: "positive",
  NO: "negative",
  NO_TOO_CLOSE: "neutral",
  NOT_ENOUGH_EVIDENCE: "warning",
};

/** Strategy override choices sent as `teamGoal` (owner decision 2). `null` = infer. */
export const STRATEGY_CHOICES = [
  { value: "auto", label: "Automatic" },
  { value: "WIN_NOW", label: "Win now" },
  { value: "BALANCED", label: "Balanced" },
  { value: "LONG_TERM", label: "Long-term" },
];

const STRATEGY_SOURCE_WORDS = {
  user: "your choice",
  posture: "from your competitive posture",
  posture_no_evidence: "posture has no measured evidence, so balanced",
  posture_unknown: "posture unknown — choose a strategy",
  asset_only: "not used in Asset-only analysis",
};

/**
 * The backend's own strategy sentence (inferred classification, strategy used
 * and why), rendered verbatim; the source words are only a fallback for a
 * packet that carries no reasoning.
 */
export function strategySummary(strategy) {
  if (!strategy) return null;
  if (strategy.reasoning) return strategy.reasoning;
  const why = STRATEGY_SOURCE_WORDS[strategy.source] || strategy.source || "";
  return strategy.label ? `${strategy.label} (${why})` : why;
}

/** The graded leaning under the headline (the v2 recommendation). */
export const RECOMMENDATION_LABELS = {
  MAKE: "Make the trade",
  LEAN_MAKE: "Lean make",
  TOO_CLOSE: "Too close / depends",
  LEAN_PASS: "Lean pass",
  PASS: "Pass",
};

export const RECOMMENDATION_TONES = {
  MAKE: "positive",
  LEAN_MAKE: "positive",
  TOO_CLOSE: "neutral",
  LEAN_PASS: "negative",
  PASS: "negative",
};

const PICK_NAME = /\d{4}/;

/**
 * Which side of a two-side trade is the selected team's — the side it GIVES.
 *
 *   explicit   the user said so (``explicitSide`` 0 / 1); always wins;
 *   roster     one side holds strictly more of the team's rostered assets;
 *   ambiguous  a tie, including 0-0 (the team owns none of the assets, or the
 *              same number on both sides): ``side: null``.  NEVER assumed.
 *
 * TC-A / UX audit P0-5: a 0-0 tie used to resolve silently to Side A, so the
 * War Room analysed "For Jason… PASS" on a picks-only trade Jason owned
 * nothing in, while no side card carried the "You" badge.  One resolver for
 * the War Room, Simulate impact and the "You" badge, so they cannot disagree.
 */
export function resolveTeamSide(sides, rosterNames, explicitSide = null) {
  if (!Array.isArray(sides) || sides.length !== 2) return { side: null, basis: "ambiguous" };
  if (explicitSide === 0 || explicitSide === 1) return { side: explicitSide, basis: "explicit" };
  const owned = rosterNames instanceof Set ? rosterNames : new Set(rosterNames || []);
  const scores = sides.map((s) =>
    (s.assets || []).reduce((n, a) => n + (owned.has(a.name) ? 1 : 0), 0),
  );
  if (scores[0] === scores[1]) return { side: null, basis: "ambiguous" };
  return { side: scores[0] > scores[1] ? 0 : 1, basis: "roster" };
}

/**
 * The simulate/analyze body for the selected team.  The side it GIVES comes
 * from ``resolveTeamSide``: explicit choice, else roster evidence; with no
 * evidence either way it returns ``null`` — the caller asks the user rather
 * than assuming a side.  Owned picks send their ownership
 * label AND their canonical owned id (``pickAssetIdsIn`` / ``pickAssetIdsOut``,
 * parallel to the pick lists, ``null`` for a generic pick): the backend checks
 * the id against the canonical ownership record, debits the team only for a
 * pick it actually holds, and reports one it does not (Wave A).  A generic
 * pick carries no id and never debits a real pick.
 */
export function tradeRequestForTeam(sides, rosterNames, teamName, explicitSide = null) {
  if (!Array.isArray(sides) || sides.length !== 2 || !teamName) return null;
  const { side: mySide, basis: sideBasis } = resolveTeamSide(sides, rosterNames, explicitSide);
  if (mySide == null) return null;
  const otherSide = mySide === 0 ? 1 : 0;
  const label = (a) => (a.assetId && a.assetLabel ? a.assetLabel : a.name);
  const playersOut = [];
  const picksOut = [];
  const pickAssetIdsOut = [];
  for (const a of sides[mySide].assets || []) {
    if (PICK_NAME.test(String(a.name || ""))) {
      picksOut.push(label(a));
      pickAssetIdsOut.push(a.assetId ? String(a.assetId) : null);
    } else playersOut.push(a.name);
  }
  const playersIn = [];
  const picksIn = [];
  const pickAssetIdsIn = [];
  for (const a of sides[otherSide].assets || []) {
    if (PICK_NAME.test(String(a.name || ""))) {
      picksIn.push(label(a));
      pickAssetIdsIn.push(a.assetId ? String(a.assetId) : null);
    } else playersIn.push(a.name);
  }
  return {
    teamName,
    playersIn,
    playersOut,
    picksIn,
    picksOut,
    pickAssetIdsIn,
    pickAssetIdsOut,
    mySide,
    sideBasis,
  };
}

/** Identity of one analysis question: trade, team, league and mode. */
export function analyzeRequestKey(request, leagueKey, useTeamContext, teamGoal = null) {
  if (!request) return "";
  return JSON.stringify([
    leagueKey || "",
    request.teamName || "",
    useTeamContext !== false,
    // The strategy override is part of the question (owner decision 2).
    teamGoal || "",
    [...request.playersIn].sort(),
    [...request.playersOut].sort(),
    [...request.picksIn].sort(),
    [...request.picksOut].sort(),
    // The owned-pick ids are part of the question: two picks that share a
    // label are different trades.
    (request.pickAssetIdsIn || []).map((x) => x || "").sort(),
    (request.pickAssetIdsOut || []).map((x) => x || "").sort(),
  ]);
}

/**
 * A 200 is only an answer to THIS question when it echoes the league, the
 * mode and a packet.  Anything else is refused rather than rendered.
 */
export function validAnalyzePayload(
  body,
  { leagueKey = "", useTeamContext = true } = {},
) {
  if (!body || typeof body !== "object" || Array.isArray(body)) return false;
  const analysis = body.analysis;
  if (!analysis || typeof analysis !== "object") return false;
  if (!RECOMMENDATION_LABELS[analysis.recommendation]) return false;
  // The ONE top-line decision must be present and recognised; it is rendered,
  // never reconstructed from the lenses.
  const decision = analysis.decision;
  if (!decision || !DECISION_TONES[decision.headline] || !decision.headlineText) return false;
  if (!analysis.lenses || typeof analysis.lenses !== "object") return false;
  if (leagueKey && body.leagueKey && body.leagueKey !== leagueKey) return false;
  const applied = body.teamContext?.applied;
  if (typeof applied !== "boolean" || applied !== (useTeamContext !== false))
    return false;
  return true;
}

/**
 * Every traded asset the analysis could not price, by name: not on the board
 * (``unresolvedIn/Out``) or on it but unpriced (``unpricedIn/Out``, TC-A).
 * The market lens leaves them out of the package math -- never as 0 -- and
 * the War Room must say so rather than drop them silently.
 */
export function notPricedNames(analysis, payload) {
  const market = analysis?.lenses?.market?.detail || {};
  const out = [];
  const add = (xs) => {
    for (const x of xs || []) {
      const n = String(x || "").trim();
      if (n && !out.includes(n)) out.push(n);
    }
  };
  add(payload?.unresolvedIn);
  add(payload?.unresolvedOut);
  add(market.unresolvedIn);
  add(market.unresolvedOut);
  add(market.unpricedIn);
  add(market.unpricedOut);
  return out;
}

/**
 * The basis notice for a surface that prices on the canonical board while the
 * builder holds user value overrides (TC-A, UX audit P0-7).  The meter and its
 * Monte Carlo panel apply overrides; Analyze (War Room) and Simulate impact
 * price server-side on canonical ``rankDerivedValue`` and do not.  Until
 * TC-C unifies the basis, every such surface says so instead of silently
 * disagreeing with the meter.  ``null`` when there is nothing to disclose.
 *
 * (User source weights need no notice: the server ignores them and serves the
 * canonical board -- ``normalize_source_overrides``, disabled 2026-08-14 --
 * so they move no surface.)
 */
export function overrideBasisNotice(overrideCount) {
  const n = Number(overrideCount);
  if (!Number.isFinite(n) || n <= 0) return null;
  return (
    `Uses canonical board values — your ${n} value override${n === 1 ? "" : "s"} in the ` +
    `builder ${n === 1 ? "is" : "are"} not applied here, so these numbers can differ from the meter's.`
  );
}

/**
 * The calculator's own two-side totals (`adjustedSideTotals`, the canonical
 * package Value Adjustment the meter shows) in the market lens's shape, for
 * the selected team: the side it GIVES is `mySide`.  The War Room shows this
 * at once while the personalized analysis runs (owner directive 2026-10-19,
 * Part 4) -- a trade-value summary only, never a YES / NO -- and replaces it
 * with the analysis's own market lens when that arrives.  `null` when the
 * totals or the side are missing: an unpriced or unknown side is never 0.
 */
export function valueSummaryFromSideTotals(sideTotals, mySide) {
  if (!Array.isArray(sideTotals) || sideTotals.length !== 2) return null;
  if (mySide !== 0 && mySide !== 1) return null;
  const send = sideTotals[mySide];
  const recv = sideTotals[mySide === 0 ? 1 : 0];
  const ok = (t) =>
    t && [t.raw, t.adjustment, t.adjusted].every((v) => typeof v === "number" && Number.isFinite(v));
  if (!ok(send) || !ok(recv)) return null;
  return {
    receivingValue: recv.raw,
    sendingValue: send.raw,
    receivingValueAdjustment: recv.adjustment,
    sendingValueAdjustment: send.adjustment,
    rawGap: recv.raw - send.raw,
    vaAdjustedGap: recv.adjusted - send.adjusted,
  };
}

/**
 * The War Room's immediate trade-value summary for the selected team, built
 * from EXACTLY the totals the calculator headline shows (`sideTotals`: the
 * canonical package dispatch over the builder's per-asset values, value
 * overrides included) and the headline's own evaluation gate
 * (`tradeEvaluationState`).
 *
 *   null                     no team side, or nothing to summarise
 *   { unpriced: [names] }    some asset has no board value and no override:
 *                            no total is shown (MISSING IS NEVER ZERO)
 *   { ...totals, overridesApplied }   the market-lens-shaped totals
 *
 * Never recomputes over the bare sides: an asset the board does not price but
 * the user priced counts at the user's value, exactly as in the headline.
 */
export function warRoomValueSummaryFor({
  sideTotals,
  mySide,
  evaluation,
  overrideCount = 0,
} = {}) {
  if (mySide !== 0 && mySide !== 1) return null;
  if (!evaluation || evaluation.state === "empty") return null;
  if (evaluation.state === "incomplete") {
    const names = (evaluation.unpriced || []).map((u) => String(u?.name || "An asset"));
    return { unpriced: names.length ? names : ["An asset"] };
  }
  const totals = valueSummaryFromSideTotals(sideTotals, mySide);
  if (!totals) return null;
  const n = Number(overrideCount);
  return { ...totals, overridesApplied: Number.isFinite(n) && n > 0 };
}

// ── Formatting ───────────────────────────────────────────────────────────
//
// ROUNDING RULES (explicit, pinned by `trade-war-room-plain.test.js`):
//   trade value      the nearest whole point (`Math.round`), en-US thousands
//                    separators; a signed figure is the sign of the rounded
//                    value plus its magnitude, so "+1,440" and "1,440 ahead"
//                    always carry the same digits.
//   points per week  ONE decimal, the MAGNITUDE rounded half away from zero
//                    (`roundTenth`), the sign carried separately -- so −5.65
//                    and +5.65 both read 5.7, and the signed figure and the
//                    sentence ("about 5.7 fewer points") can never disagree.
//   percentages      the nearest whole percent.

/** |value| to one decimal, half away from zero; a float-noise guard keeps
 *  5.65 (stored as 5.6499999…) on the side a reader expects. */
export function roundTenth(value) {
  if (typeof value !== "number" || !Number.isFinite(value)) return null;
  return Math.round(Math.abs(value) * 10 + 1e-9) / 10;
}

export function formatSignedPpg(value) {
  const mag = roundTenth(value);
  if (mag == null) return null;
  if (mag === 0) return "±0.0";
  return `${value > 0 ? "+" : "−"}${mag.toFixed(1)}`;
}

export function formatPpg(value) {
  const mag = roundTenth(value);
  if (mag == null) return null;
  return `${value < 0 && mag > 0 ? "−" : ""}${mag.toFixed(1)}`;
}

export function formatPctPoint(value) {
  if (typeof value !== "number" || !Number.isFinite(value)) return null;
  return `${Math.round(value)}%`;
}

export function formatValue(value) {
  if (typeof value !== "number" || !Number.isFinite(value)) return null;
  return Math.round(value).toLocaleString("en-US");
}

export function formatSignedValue(value) {
  if (typeof value !== "number" || !Number.isFinite(value)) return null;
  const r = Math.round(value);
  if (r === 0) return "±0";
  return `${r > 0 ? "+" : "−"}${Math.abs(r).toLocaleString("en-US")}`;
}

// ── Lens summaries (labels only — every number is the packet's) ──────────

const UNAVAILABLE_WORDS = {
  asset_only_mode: "Not included in Asset-Only analysis",
  no_team_selected: "Pick your team to see roster impact",
  no_team_selected_or_uncomputable: "Pick your team to see roster impact",
  partial_projection_coverage: "Not counted — a traded player has no projection",
  season_unresolved: "No current-season projection applies",
  no_remaining_fantasy_weeks: "No fantasy weeks remain this season",
  impact_missing: "The lineup estimate came back without a number",
  roster_settings_missing: "This league's roster settings are missing",
  starter_slots_unresolved: "This league's starting slots did not resolve",
  projection_basis_no_projection_snapshot:
    "No league-scored projection snapshot yet",
  projection_basis_scoring_card_missing:
    "This league's scoring card is missing",
  roster_capacity_unavailable: "Your roster limit could not be checked",
  uncertain:
    "Can't tell yet — who is on your taxi squad is unknown, so the number of cuts is uncertain",
  unknown_limit: "This league's roster limit is unknown",
  no_priced_assets_either_side: "Neither side has a priced asset",
  not_computed: "Not computed",
  league_bundle_not_warm: "League roster intelligence is still loading",
  team_not_in_league_bundle:
    "This team is not in the league's roster intelligence",
  roster_snapshot_missing: "No roster snapshot for this league yet",
  starter_slots_missing: "This league's starting slots are not configured",
  trade_ledger_not_built:
    "The recorded-trade ledger is not built on the server",
  trade_ledger_unavailable: "The recorded-trade ledger could not be read",
  no_identifiable_assets:
    "No asset in this trade could be identified in the trade ledger",
  comparables_error: "Comparable trades could not be computed right now",
};

// ── Competitive Posture (#840 / C7-POST-01) — labels only ────────────────

const POSTURE_WORDS = {
  PUSH: "Push — prioritise this season's title equity",
  HOLD: "Hold — keep options open; the read is close",
  // Owner decision 2026-10-18: RETOOL is its own classification (strategy
  // BALANCED), never a rebuilder.
  RETOOL: "Retool — balance current production with younger value around the core",
  REBUILD: "Rebuild — prioritise future value and draft capital",
};
const POSTURE_ORDER = ["PUSH", "HOLD", "RETOOL", "REBUILD"];

function formatShare(value) {
  if (typeof value !== "number" || !Number.isFinite(value)) return null;
  return `${Math.round(value * 100)}%`;
}

/** The posture lens as display text.  Every number is the packet's. */
export function postureSummary(lens) {
  if (!lens || !lens.available) {
    return {
      available: false,
      reasonText: unavailableText(lens?.unavailableReason),
    };
  }
  const d = lens.detail || {};
  const probs = d.probabilities || {};
  const timing = d.components?.timing || {};
  const noEvidence = d.evidence === "none";
  return {
    available: true,
    label: d.label || null,
    noEvidence,
    headline: noEvidence
      ? "Hold — no competitiveness evidence yet"
      : POSTURE_WORDS[d.label] || d.label || "—",
    confidence: formatShare(d.confidence),
    split: POSTURE_ORDER.filter((k) => typeof probs[k] === "number").map(
      (k) => ({
        label: k,
        pct: formatShare(probs[k]),
      }),
    ),
    timing:
      timing.phase === "offseason"
        ? "Offseason"
        : timing.phase === "post_deadline"
          ? "After the trade deadline"
          : typeof timing.week === "number"
            ? `Week ${timing.week}${timing.tradeDeadlineWeek ? ` of a week-${timing.tradeDeadlineWeek} deadline` : ""}`
            : "Season timing unknown",
    ownFirst:
      d.components?.ownFirstRoundPickHeld === true
        ? "Holds its own next first-round pick"
        : d.components?.ownFirstRoundPickHeld === false
          ? "Does not hold its own next first-round pick"
          : "Own first-round pick: unknown",
    parameterStatus: d.parameterStatus || null,
    notes: Array.isArray(d.notes) ? d.notes : [],
  };
}

/**
 * The comparable-real-trades lens (TC-09) as display rows.  Reference only:
 * the lens never votes and never moves confidence, so this renders beside the
 * answer, not inside it.  Every number is the packet's.
 */
export function comparablesSummary(lens) {
  if (!lens || !lens.available) {
    return {
      available: false,
      reasonText: unavailableText(lens?.unavailableReason),
    };
  }
  const d = lens.detail || {};
  const rows = (d.comparableTrades || []).map((t, i) => ({
    key: `${t.occurredDate || "undated"}-${i}`,
    date: t.occurredDate || "Date unknown",
    similarity:
      typeof t.similarity === "number" && Number.isFinite(t.similarity)
        ? `${Math.round(t.similarity * 100)}% similar`
        : null,
    reasons: (t.reasons || []).filter(Boolean),
  }));
  const below = typeof d.belowMinScore === "number" ? d.belowMinScore : 0;
  return {
    available: true,
    rows,
    emptyText: rows.length
      ? null
      : below
        ? `${below} recorded trade${below === 1 ? "" : "s"} shared an asset but resembled this package too little to list.`
        : "No recorded trade in the sample shares an asset with this package.",
    scanCapped: d.scanCapped === true,
  };
}

export function unavailableText(reason) {
  if (!reason) return "Unavailable";
  return (
    unavailableWords(reason) ||
    `Unavailable (${String(reason).replace(/_/g, " ")})`
  );
}

/**
 * The plain words for an unavailable reason, or null when the reason has
 * none -- for a caller writing its own sentence, which then omits the reason
 * rather than show a code ("not available (unavailable (impact missing))").
 */
export function unavailableWords(reason) {
  if (!reason) return null;
  if (UNAVAILABLE_WORDS[reason]) return UNAVAILABLE_WORDS[reason];
  if (String(reason).startsWith("error:"))
    return "Could not be computed right now";
  return null;
}

/** The player rows worth a line, in a stable reading order. */
// Availability beside a lineup share (owner master package 2026-10-17, P0):
// the share is over the league's REMAINING weeks, and a player who cannot
// play some of them says so — never a bare percentage that reads as health.
export function availabilityNote(player) {
  const a = player?.availability;
  if (!a || !Number.isFinite(a.weeks) || a.weeks <= 0) return null;
  if (a.eligibleWeeks === 0) return `Out all ${a.weeks} remaining weeks`;
  const parts = [];
  if (a.unavailableWeeks > 0)
    parts.push(`out ${a.unavailableWeeks} of ${a.weeks} weeks`);
  // Counts only: an absent count names nothing (never summed as zero).
  const unsure = [a.uncertainWeeks, a.unknownWeeks]
    .filter((n) => Number.isFinite(n))
    .reduce((acc, n) => acc + n, 0);
  if (unsure > 0) parts.push(`uncertain ${unsure}`);
  return parts.length ? parts.join(", ") : null;
}

export function simulatedWeeksLabel(basis) {
  const weeks = Array.isArray(basis?.weeks) ? basis.weeks : null;
  if (!weeks || !weeks.length) return null;
  return weeks.length === 1
    ? `week ${weeks[0]}`
    : `weeks ${weeks[0]}–${weeks[weeks.length - 1]}`;
}

export function rosterImpactRows(rosterDetail) {
  const order = {
    incoming: 0,
    outgoing: 1,
    forcedDrop: 2,
    promoted: 3,
    displaced: 4,
  };
  return [...(rosterDetail?.players || [])].sort(
    (a, b) =>
      (order[a.role] ?? 9) - (order[b.role] ?? 9) ||
      String(a.name).localeCompare(String(b.name)),
  );
}

/**
 * Holes and bye coverage (TC-B / TCM-H12) from the roster lens's
 * `lineupHoles` block (`src/roster_intel/best_ball_utility.py`), as display
 * text.  Returns null when the block is absent; an unmeasured side reads
 * "—", never 0.
 *   perWeek      "0.4 → 1.1 empty starting slots per week"
 *   bySlotAfter  "FLEX 0.6 · TE 0.5" (after the trade, largest first)
 *   noEligible   slots no rostered player can fill after the trade
 *   onlyUnprojected  slots only an unprojected player can fill after
 */
export function lineupHolesSummary(rosterDetail) {
  const h = rosterDetail?.lineupHoles;
  if (!h || typeof h !== "object") return null;
  const fmt = (v) => (typeof v === "number" && Number.isFinite(v) ? v.toFixed(1) : "—");
  const before = h.before || {};
  const after = h.after || {};
  const bySlot = after.emptyBySlot && typeof after.emptyBySlot === "object" ? after.emptyBySlot : null;
  const bySlotAfter = bySlot
    ? Object.entries(bySlot)
        .filter(([, v]) => typeof v === "number" && v > 0)
        .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
        .map(([slot, v]) => `${slot} ${v.toFixed(1)}`)
        .join(" · ")
    : null;
  return {
    perWeek: `${fmt(before.emptySlotsPerWeek)} → ${fmt(after.emptySlotsPerWeek)} empty starting slots per week`,
    delta: typeof h.emptySlotsPerWeekDelta === "number" ? h.emptySlotsPerWeekDelta : null,
    bySlotAfter: bySlotAfter || null,
    noEligible: Array.isArray(after.noEligiblePlayer) ? after.noEligiblePlayer : [],
    onlyUnprojected: Array.isArray(after.onlyUnprojected) ? after.onlyUnprojected : [],
  };
}
