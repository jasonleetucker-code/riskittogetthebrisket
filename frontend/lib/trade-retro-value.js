/**
 * trade-retro-value — value each side of a historical trade AS OF the
 * date it went through.
 *
 * Three distinct questions, and conflating them is the defect this module
 * exists to avoid (``docs/TRADE_HISTORY_AGING_SPEC.md``, restated in
 * CLAUDE.md § "Trade History — three distinct questions"):
 *
 *   Current Grade    — this trade under today's canonical values.
 *   At-the-Time      — the closest valid observation AT OR BEFORE the trade.
 *   How It Aged      — the difference between the two.
 *
 * The only thing that makes "How It Aged" a measurement rather than a
 * decoration is that the at-the-time total is composed exclusively of
 * as-of evidence.  Substitute a current value into it — for a pick, for a
 * player with no coverage, for a trade with no date — and the difference
 * collapses toward zero and the surface renders "Stable": a badge that
 * reads as a measured finding and is in fact the absence of one.
 *
 * So, four rules, each of which this file previously broke:
 *
 * 1. **Never a future observation.**  ``pointAt`` returns the closest
 *    sample at or before ``asOfMs``, or nothing.  It used to fall back to
 *    the EARLIEST sample when the trade predated coverage — with no
 *    distance cap and no direction constraint, so a 2024 trade was priced
 *    with 2026 numbers and stamped ``rankHistory`` as though observed.
 * 2. **A missing historical value is not the current value.**  Uncovered
 *    items carry ``val: null`` with a reason and are EXCLUDED from the
 *    total, never replaced by ``item.val``.
 * 3. **Picks need first-class historical values.**  We do not record them
 *    per pick, so picks are ``unavailable`` here.  They used to be priced
 *    at today's number, which for a picks-only trade made ``verdictDelta``
 *    exactly 0 by construction.
 * 4. **An incomplete at-the-time total may not be compared to a complete
 *    current one.**  Any uncovered item on either side ⇒ ``unknown`` with
 *    ``insufficientEvidence``, not a smaller number.
 *
 * The reason vocabulary is the canonical one from ``src/history/asof.py``
 * (C1-U4), deliberately, so the two surfaces name the same states.  That
 * module is also where this computation BELONGS — it owns as-of reads with
 * real fidelity labels and a permanent pre-2026-07-14 floor, and this is a
 * second implementation of the same question.  Migrating it is Trade
 * History work, which is not currently authorized; refusing to overstate in
 * the meantime is not.
 *
 * Inputs
 * ------
 *   trade           — the analyzed trade record from
 *                     analyzeSleeperTradeHistory (.sides[].items[].name)
 *   tradeTimestamp  — epoch ms of the trade.  Non-finite ⇒ refuse.
 *   historyLookup   — function (name) → [{date, rank, val}]
 */
import { valueFromRank } from "@/lib/value-history";

/** Canonical missing reasons — mirrors ``src/history/asof.py``. */
export const REASON_NO_PRIOR = "no_prior_observation";
export const REASON_PICK_HISTORY = "pick_history_not_recorded";
export const REASON_UNDATED = "undated_trade";

/**
 * The observation closest to ``asOfMs`` from BELOW, or ``null``.
 *
 * A future observation can never answer an as-of question, so there is no
 * fallback here and deliberately no "nearest either way" — that is the same
 * defect class ``src/picks/site_pick_map.py`` had to remove (C1-U6-D1),
 * where an unpublished year was answered with a neighbouring year's row and
 * the fabrication then authenticated itself.
 */
function pointAt(history, asOfMs) {
  if (!Array.isArray(history) || history.length === 0) return null;
  if (!Number.isFinite(asOfMs)) return null;
  let best = null;
  for (const point of history) {
    const t = Date.parse(point?.date);
    if (!Number.isFinite(t)) continue;
    const rank = Number(point?.rank);
    if (!Number.isFinite(rank) || rank <= 0) continue;
    if (t > asOfMs) continue;
    if (!best || t > best.t) best = { t, point };
  }
  return best?.point || null;
}

function valueFromPoint(point) {
  if (!point) return null;
  const stamped = Number(point.val);
  if (Number.isFinite(stamped) && stamped > 0) return stamped;
  // Defensive: a snapshot that shipped without ``val`` (an older on-disk
  // entry the backend never back-filled) still carries a rank, and the rank
  // IS an as-of observation.  Deriving from it is an approximation of the
  // curve, not a substitution of a different date's evidence.  Documented
  // mismatch with the backend curves — see value-history.js::valueFromRank.
  const r = Number(point.rank);
  if (!Number.isFinite(r) || r <= 0) return null;
  return valueFromRank(r);
}

/**
 * Value one side of a trade as of ``asOfMs``.
 *
 * ``total`` sums the COVERED items only.  ``complete`` is false whenever
 * anything was left out, and a caller comparing this total to a current one
 * must read it — a partial at-the-time total against a complete current
 * total is not a measurement of aging, it is a measurement of coverage.
 */
export function valueSideAtTime(items, historyLookup, asOfMs) {
  const out = [];
  let total = 0;
  let uncovered = 0;
  if (!Array.isArray(items)) {
    return { total: 0, items: [], covered: 0, uncovered: 0, complete: true };
  }
  const dated = Number.isFinite(asOfMs);
  for (const it of items) {
    if (!it) continue;
    const miss = (reason) => {
      uncovered += 1;
      out.push({
        name: it.name,
        val: null,
        isPick: Boolean(it.isPick),
        source: "unavailable",
        reason,
      });
    };
    if (!dated) {
      miss(REASON_UNDATED);
      continue;
    }
    if (it.isPick) {
      // Pick valuation history is not recorded per pick.  Today's number is
      // not that pick's value on the trade date, and saying so is the whole
      // point — CLAUDE.md: "picks need first-class historical values rather
      // than a current-value substitute".
      miss(REASON_PICK_HISTORY);
      continue;
    }
    const stamped = valueFromPoint(pointAt(historyLookup ? historyLookup(it.name) : null, asOfMs));
    if (stamped == null) {
      miss(REASON_NO_PRIOR);
      continue;
    }
    out.push({ name: it.name, val: stamped, isPick: false, source: "rankHistory" });
    total += stamped;
  }
  return {
    total: Math.round(total),
    items: out,
    covered: out.length - uncovered,
    uncovered,
    complete: uncovered === 0,
  };
}

/**
 * "How It Aged" for one side of a 2-team trade — or an explicit refusal.
 *
 * ``verdict`` is ``"unknown"`` with ``insufficientEvidence: true`` whenever
 * the at-the-time total could not be completed, because the alternative is a
 * number that looks like a small delta and is really a missing one.
 *
 * The ±200 band is inherited, not derived.  CLAUDE.md records it as
 * evidence-gated rather than finished methodology; it is not this unit's to
 * settle, and it decides nothing once the evidence gate above has run.
 */
export function gradeRetro({ side, currentNet, asOfMs, historyLookup }) {
  if (!side) return null;
  const got = side.got || side.gotItems || [];
  const gave = side.gave || side.gaveItems || [];
  const atTradeGot = valueSideAtTime(got, historyLookup, asOfMs);
  const atTradeGave = valueSideAtTime(gave, historyLookup, asOfMs);
  const atTradeNet = atTradeGot.total - atTradeGave.total;

  const missing = [...atTradeGot.items, ...atTradeGave.items]
    .filter((i) => i.source === "unavailable")
    .map((i) => ({ name: i.name, reason: i.reason }));
  const insufficientEvidence = missing.length > 0;

  const comparable = !insufficientEvidence && Number.isFinite(currentNet);
  const verdictDelta = comparable ? currentNet - atTradeNet : null;
  let verdict = "unknown";
  if (verdictDelta != null) {
    if (verdictDelta > 200) verdict = "aged_well";
    else if (verdictDelta < -200) verdict = "aged_poorly";
    else verdict = "stable";
  }
  return {
    atTradeGot,
    atTradeGave,
    // Reported so the covered part stays inspectable — but NOT comparable to
    // ``currentNet`` when evidence is missing, which is what the flag says.
    atTradeNet,
    atTradeComplete: !insufficientEvidence,
    currentNet,
    verdictDelta,
    verdict,
    insufficientEvidence,
    missing,
  };
}
