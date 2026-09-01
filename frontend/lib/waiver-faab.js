/**
 * waiver-faab.js — render-time join between the /waivers board rows
 * (client-computed by ``lib/waiver-logic.js``) and the backend FAAB
 * bids on ``POST /api/waiver/suggestions``.
 *
 * WHY THIS FILE EXISTS
 * ────────────────────
 * ``computeWaiverAnalysis`` is a pure comparison over contract rows.
 * Contract rows carry values, not bids, so every move it produces has
 * a blank FAAB cell.  The dollar figures live in
 * ``src/trade/faab_engine.py`` and reach the client only on the
 * suggestions endpoint's candidate rows
 * (``WaiverCandidate.to_dict`` → ``bid: {aggressive, reasonable,
 * lowball}``).
 *
 * This module INDEXES and LOOKS UP those numbers.  It computes no bid
 * arithmetic of any kind — not a scale, not a cap, not a fallback.
 * The deleted ``computeFaabHint`` (see the closing note in
 * ``waiver-logic.js``) is exactly what this must not become: a row
 * with no backend bid renders a placeholder, never a locally derived
 * number.
 *
 * Same shape as the BDVM "Fund gap" join on /rankings
 * (``lib/bdvm.js::buildBdvmIndex`` / ``bdvmEntryForRow``): build an
 * index from an optional payload, return ``null`` when there is
 * nothing joinable, and let the caller treat "no index" and "endpoint
 * unavailable" identically — the column silently renders "—".
 *
 * NAME KEY
 * ────────
 * ``normalizeName`` from ``waiver-logic.js`` (family 3, LOOSE/trim),
 * NOT ``normalizePlayerNameKey``.  Both sides of this join already key
 * that way — the backend candidate names come from the same
 * ``playersArray`` rows ``buildRows`` materializes, and the module's
 * owned/my-roster Sets use it — so using anything else here would put
 * a third key into one page for no gain.  See the ``normalizeName``
 * docstring for why the strict key is wrong for waivers specifically
 * (it collapses generational suffixes).
 */

import { familyOf } from "@/lib/position-family";
import { normalizeName } from "@/lib/waiver-logic";

// Strict, like ``lib/bdvm.js::_num``: the backend emits JSON numbers,
// and a loose ``Number()`` would silently turn the ``null`` that means
// "not priced" / "not ranked" into 0 — the exact class of fake figure
// this whole module exists to avoid.
function _num(v) {
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

/**
 * A candidate's bid, or null when the backend declined to price it
 * (``to_dict`` emits ``bid: null`` when the engine returned nothing).
 * A bid object with no finite ``reasonable`` is treated as absent —
 * the headline number is what the column renders.
 */
function _entryFor(candidate) {
  const bid = candidate?.bid;
  if (!bid || typeof bid !== "object") return null;
  const reasonable = _num(bid.reasonable);
  if (reasonable == null) return null;
  return {
    reasonable,
    aggressive: _num(bid.aggressive),
    lowball: _num(bid.lowball),
    // Market-aware-only — null in ceiling-only mode (see
    // WaiverCandidate.to_dict on the backend). Powers the row redesign:
    // "Bid $X · Expected clearing $Y-$Z · Max I'd pay $M".
    clearing: _num(candidate?.clearing),
    clearingLow: _num(candidate?.clearingLow),
    clearingHigh: _num(candidate?.clearingHigh),
    maxRational: _num(candidate?.maxRational),
    objectiveDollars: _num(candidate?.objectiveDollars),
    confidence: typeof candidate?.confidence === "string" ? candidate.confidence : null,
    consensusValue: _num(candidate?.consensusValue),
    rank: _num(candidate?.rank),
    isRookie: Boolean(candidate?.isRookie),
    // The backend publishes the RAW contract position ("DE", "CB")
    // while board rows carry the family ``buildRows`` normalized them
    // to ("DL", "DB").  ``familyOf`` — the frontend's one coarse
    // position→family map — is applied to BOTH sides so the two
    // vocabularies meet.  Comparing the raw strings would make every
    // IDP row miss its bid silently.
    position: familyOf(candidate?.position),
  };
}

function* _candidates(payload) {
  // ``by_family`` is derived from ``by_position`` (same objects, family
  // buckets), so walking both is a superset with duplicates rather
  // than a conflict — first-wins insertion below makes it idempotent.
  // We walk both anyway so a payload carrying only one of the two
  // still joins.
  for (const group of ["by_position", "by_family"]) {
    const bucket = payload?.[group];
    if (!bucket || typeof bucket !== "object") continue;
    for (const items of Object.values(bucket)) {
      if (!Array.isArray(items)) continue;
      for (const c of items) yield c;
    }
  }
}

/**
 * Index a ``POST /api/waiver/suggestions`` payload for render-time
 * joins onto best-moves rows.
 *
 * Returns ``null`` for anything with no priced candidate in it —
 * a null/undefined payload, an error body, an empty board, or a board
 * where every candidate came back unpriced.  Callers therefore need
 * exactly one check.
 *
 * Two keys, both name-first:
 *   ``byNamePos`` — ``name|POS``, the precise key.  Used first because
 *       the offense/IDP universes genuinely contain distinct players
 *       sharing a display name (the same hazard
 *       ``buildTeamByPlayer`` carries its id-first lookup for).
 *   ``byName``    — the fallback for rows whose position doesn't line
 *       up.  SUPPRESSED when the payload holds two candidates of
 *       different positions under one name: an ambiguous mention gets
 *       no bid rather than a guessed one.
 */
export function buildWaiverBidIndex(payload) {
  const byName = new Map();
  const byNamePos = new Map();
  const ambiguous = new Set();

  for (const candidate of _candidates(payload)) {
    const entry = _entryFor(candidate);
    if (!entry) continue;
    const name = normalizeName(candidate?.name);
    if (!name) continue;
    const posKey = `${name}|${entry.position}`;
    if (!byNamePos.has(posKey)) byNamePos.set(posKey, entry);
    const seen = byName.get(name);
    if (!seen) byName.set(name, entry);
    else if (seen.position !== entry.position) ambiguous.add(name);
  }

  if (byName.size === 0) return null;
  // Global to the whole response, per src/trade/waiver.py::find_waiver_targets
  // — "market_aware" (real rival contention, this team's roster) or
  // "ceiling_only_estimate" (no resolvable team context — a fixed
  // fraction of the objective ceiling, never a recommendation).
  const methodology =
    typeof payload?.bidMethodology === "string" ? payload.bidMethodology : null;
  return { byName, byNamePos, ambiguous, methodology };
}

/**
 * Resolve a board row (a ``buildRows`` row — the ``add`` side of a
 * best-move) against a ``buildWaiverBidIndex`` result, or null.
 *
 * Never throws, never derives: returns the backend's bid object or
 * null.  A null index resolves nothing, which is what makes the
 * column vanish silently on any non-OK response.
 */
export function waiverBidForRow(index, row) {
  if (!index || !row) return null;
  const name = normalizeName(row?.name || row?.displayName);
  if (!name) return null;
  const hit = index.byNamePos.get(`${name}|${familyOf(row?.pos || row?.position)}`);
  if (hit) return hit;
  if (index.ambiguous.has(name)) return null;
  return index.byName.get(name) || null;
}

/**
 * Why a row has no bid. Reported, never inferred by the caller from a
 * null — the four situations below are genuinely different and the
 * board used to render all of them as one `—`.
 *
 *   `unavailable`         no index at all: no team picked, a league
 *                         mismatch, or the suggestions endpoint did
 *                         not answer. Nothing is wrong with the player.
 *   `team_context_missing`  a team WAS selected (the fetch only runs
 *                         then) but the backend could not resolve it
 *                         to a roster and fell back to
 *                         `ceiling_only_estimate` — a fixed fraction
 *                         of the objective ceiling with no rival
 *                         model, which must never be shown as a
 *                         recommendation. Wins over `priced` even
 *                         though a `bid` object genuinely exists on
 *                         the payload in this mode.
 *   `unpriced`     the index exists and this player is not priced in
 *                  it — either the engine declined him (`bid: null`)
 *                  or he is off the backend's per-position board.
 *   `ambiguous`    two candidates share this display name at different
 *                  positions, so no bid can be attributed to this row.
 *   `priced`       the backend stamped a market-aware figure.
 *
 * `unpriced` deliberately covers both "priced nothing" and "not on the
 * board": from the reader's seat they are the same fact — the backend
 * has no bid for this player — and splitting them would put a
 * distinction on screen that the payload cannot actually support (an
 * absent candidate and a `bid: null` candidate are indistinguishable
 * once `_entryFor` has dropped both).
 */
const BID_STATE_COPY = {
  unavailable: {
    label: "No bids",
    reason:
      "FAAB bids have not loaded for this board. Pick your team above — bids are " +
      "scaled to a specific manager's budget, so there is nothing to show until one " +
      "is selected.",
  },
  team_context_missing: {
    label: "Recommendation unavailable: team context missing",
    reason:
      "Your team could not be resolved to a current roster, so the market-aware bid " +
      "model (rival contention, your budget, your roster need) could not run. What " +
      "would otherwise show here is only a fixed fraction of the player's objective " +
      "ceiling with no rival model — not a recommendation — so it is withheld.",
  },
  unpriced: {
    label: "Not priced",
    reason:
      "The backend FAAB engine published no bid for this player. Its board is capped " +
      "per position, so players outside the cap are unpriced rather than worth zero.",
  },
  ambiguous: {
    label: "Ambiguous",
    reason:
      "Two different players share this name at different positions, so no bid can be " +
      "attributed to this row without guessing which one you mean.",
  },
};

/**
 * Like :func:`waiverBidForRow`, but says WHY when there is no bid.
 *
 * Returns ``{state, bid, label, reason}``. Computes nothing: the bid
 * object is the backend's, and every other field is a fixed string
 * chosen by ``state``.
 */
export function waiverBidStateForRow(index, row) {
  const withCopy = (state) => ({ state, bid: null, ...BID_STATE_COPY[state] });
  if (!index) return withCopy("unavailable");
  // A team was selected (the fetch that built this index only runs
  // then), but the backend fell back to the ceiling-only estimate — no
  // rival model ran, so nothing here is a recommendation. This check
  // comes before any name lookup because it applies to EVERY row in
  // the payload, not to whether this particular player has a bid.
  if (index.methodology && index.methodology !== "market_aware") {
    return withCopy("team_context_missing");
  }
  if (!row) return withCopy("unpriced");
  const name = normalizeName(row?.name || row?.displayName);
  if (!name) return withCopy("unpriced");
  const hit = index.byNamePos.get(`${name}|${familyOf(row?.pos || row?.position)}`);
  if (hit) return { state: "priced", bid: hit, label: "", reason: "" };
  if (index.ambiguous.has(name)) return withCopy("ambiguous");
  const byName = index.byName.get(name);
  if (byName) return { state: "priced", bid: byName, label: "", reason: "" };
  return withCopy("unpriced");
}
