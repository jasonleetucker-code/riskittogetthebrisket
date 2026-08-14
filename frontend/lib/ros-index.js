/**
 * ROS value index — the ONE join between `/api/ros/player-values` and
 * contract board rows.
 *
 * ── Why this file exists ───────────────────────────────────────────────
 * `PlayerPopup.jsx` and `RosTradeFitPanel.jsx` each carried their own
 * copy of "fetch the ROS payload, index it by name, look a row up", and
 * both copies indexed by the RAW `canonicalName` string:
 *
 *     map[p.canonicalName] = {...}                     // build
 *     map[row.canonicalName || row.displayName]        // lookup
 *
 * Those two vocabularies do not agree. `data/ros/aggregate/latest.json`
 * stores `canonicalName` lowercased AND apostrophe-stripped — 1068 of
 * its 1084 rows read like `jamarr chase`, `jahmyr gibbs` — and
 * `src/ros/api.py` serves `payload["players"]` verbatim, so the wire
 * format carries those keys. Board rows carry the contract's display
 * name: `Ja'Marr Chase`, `A.J. Brown`.
 *
 * Measured against the tracked snapshot on 2026-07-30, exact-string:
 *
 *     12 of 1075 board rows joined.  1.1%.
 *
 * And the 12 that joined were exactly the 16 wrongly-cased rows that
 * `UNIMPLEMENTED_BACKLOG.md` §9 #18 files as a data defect — i.e. the
 * only rows that worked were the malformed ones.
 *
 * The failure was not a blank. `PlayerPopup` renders "ROS · no data
 * yet" with `title="No ROS source ranked this player today."` — a
 * confident, specific, false claim about most of the board. Downstream,
 * `_tagsForPlayer` short-circuits on `rosValue == null` so none of the
 * nine ROS tags ever fired, and `RosTradeFitPanel` drops its whole
 * panel when nothing is tagged, so /trade's ROS section was invisible
 * on essentially every trade.
 *
 * ── Which name key, and why it is not just `.toLowerCase()` ────────────
 * `lib/player-name-match.js` documents a four-family name-key registry
 * and warns against swapping families. Measured over the same 1075
 * board rows:
 *
 *     exact string (what shipped)                        12   (1.1%)
 *     family 3  normalizeName (trim+lowercase)          802  (74.6%)
 *     family 2  normalizeNameCompact                    849  (79.0%)
 *     family 1  normalizePlayerNameKey                  849  (79.0%)
 *
 * A bare lowercase leaves 47 players broken, because it cannot see
 * through the stripped apostrophe. Families 1 and 2 tie on recovery, so
 * the tiebreak is provenance: family 1 is the documented twin of
 * Python's canonical key, pinned by the shared fixture
 * `tests/fixtures/name_key_cases.json`, while family 2's own docstring
 * says it is for local joins and typeahead and is explicitly NOT
 * backend parity. Family 1 it is.
 *
 * The registry warns that family 1 strips generational suffixes and can
 * therefore collide "Marvin Harrison Jr." into "Marvin Harrison".
 * Measured on this data: ZERO collisions on the contract side. The risk
 * is real in general and absent here.
 *
 * 849 is the ceiling, not a shortfall: the remaining 226 board rows
 * genuinely have no row in the ROS aggregate. For those, "No ROS source
 * ranked this player today" is finally a true sentence.
 */

import { normalizePlayerNameKey } from "@/lib/player-name-match";
import {
  ROS_ELITE_PERCENTILE,
  ROS_STRONG_PERCENTILE,
  ROS_DEPTH_BAND_LOW_PERCENTILE,
  ROS_SELLER_PERCENTILE_GAP,
} from "./thresholds";

/**
 * Pick a winner when two ROS rows collapse to one key.
 *
 * Family 1 produces six collisions on the live aggregate, and they are
 * precisely the six case-duplicate rows backlog §9 #18 already names:
 * cam bynum, cam skattebo, cam ward, mitch tinsley, nate landman,
 * tank dell. Each exists twice, once lowercased and once Title Case,
 * carrying DIFFERENT values from different source sets.
 *
 * Last-write-wins would make the choice an artifact of payload order.
 * It already did, and it chose badly: Cam Skattebo rendered 37.72 from
 * a DraftSharks-only row while his fuller row — 28.74, from
 * fantasyProsRosSf + ffc2qbAdp — never displayed.
 *
 * So: most sources wins, then highest confidence, then highest value.
 * Breadth of agreement beats a single vendor, which is the same
 * principle the main board's blend already encodes.
 *
 * This makes the duplicates DETERMINISTIC. It does not fix them — the
 * data defect stays open, and fixing it upstream is what finally
 * removes this function.
 */
function preferRow(a, b) {
  if (!a) return b;
  if (!b) return a;
  const score = (r) => [
    Number(r.sourceCount) || 0,
    Number(r.confidence) || 0,
    Number(r.rosValue) || 0,
  ];
  const [as, ac, av] = score(a);
  const [bs, bc, bv] = score(b);
  if (bs !== as) return bs > as ? b : a;
  if (bc !== ac) return bc > ac ? b : a;
  return bv > av ? b : a;
}

/**
 * Index `/api/ros/player-values` rows by canonical name key.
 *
 * Accepts the payload's `players` array. Rows without a usable name are
 * skipped rather than indexed under "" — an empty key would swallow
 * every unnamed row into one bucket and then answer lookups for other
 * unnamed rows with it.
 */
export function buildRosIndex(players) {
  const index = new Map();
  for (const p of players || []) {
    const key = normalizePlayerNameKey(p?.canonicalName);
    if (!key) continue;
    const entry = {
      rosValue: p.rosValue,
      // Standing within the WHOLE ROS pool, stamped by the backend.
      // Never recomputed here — the response is truncated to `limit`.
      rosPercentile: p.rosPercentile ?? null,
      rosRank: p.rosRankOverall,
      rosRankPosition: p.rosRankPosition,
      confidence: p.confidence,
      volatilityFlag: !!p.volatilityFlag,
      staleFlag: !!p.staleFlag,
      tier: p.tier,
      // Kept for the tie-break only; not rendered.
      sourceCount: p.sourceCount,
    };
    index.set(key, preferRow(index.get(key), entry));
  }
  return index;
}

/**
 * The ROS entry for a board row, or null.
 *
 * Tries every name field the row might carry rather than picking one.
 * The two call sites disagreed on the order — PlayerPopup used
 * `canonicalName || displayName || name`, RosTradeFitPanel used
 * `canonicalName || name || displayName` — and that difference is
 * invisible until a row has two of them set to different strings. Try
 * each in turn and the ordering question stops existing.
 */
export function rosEntryForRow(index, row) {
  if (!index || typeof index.get !== "function" || !row) return null;
  for (const raw of [row.canonicalName, row.displayName, row.name]) {
    const key = normalizePlayerNameKey(raw);
    if (!key) continue;
    const hit = index.get(key);
    if (hit) return hit;
  }
  return null;
}

// ── Context tags — the ONE implementation ────────────────────────────
//
// `PlayerPopup.jsx` and `RosTradeFitPanel.jsx` each carried a verbatim
// copy of this classifier, and one of them still carried the comment
// "Stays in sync via the parity test (PR-future)" — a parity test that
// was never written. Duplicating it is what let W29-F005 survive review
// three times (twice here, once in `src/ros/tags.py`).
//
// The Python owner is `src/ros/tags.py::tags_for_player`; this mirrors
// it and `tests/ros/test_tag_parity.py` fails the build when the two
// disagree. Same mirror+parity mechanism as the ranking-source registry
// and `frontend/lib/thresholds.js`.
//
// Every strength gate is a STANDING within the ROS pool, not a level of
// the raw 0-100 `rosValue` index. See the B9b note in thresholds.js for
// what the absolute constants measured before the conversion.

const _IDP_TAG_POSITIONS = new Set(["DL", "DE", "DT", "EDGE", "LB", "DB", "S", "CB"]);
const _VET_AGE_BY_POS = {
  QB: 32, RB: 26, WR: 29, TE: 30,
  DL: 30, DE: 30, DT: 30, EDGE: 30, LB: 29, DB: 29, S: 29, CB: 29,
};

/**
 * Context tags for one player.
 *
 * `rosPercentile` and `dynastyPercentile` are 0-100 with 100 = best,
 * each measured within its OWN population. No tags without
 * `rosPercentile`: every gate is a standing, and a standing cannot be
 * derived from one player. Returning none is the honest answer.
 */
export function tagsForPlayer({
  position,
  age,
  rosValue,
  rosPercentile,
  rosRank,
  dynastyPercentile,
  volatilityFlag,
}) {
  const tags = [];
  if (rosValue == null || rosValue <= 0) return tags;
  if (rosPercentile == null) return tags;

  const pos = String(position || "").toUpperCase().split("/")[0];
  const isIdp = _IDP_TAG_POSITIONS.has(pos);
  const isStrong = rosPercentile >= ROS_STRONG_PERCENTILE;
  const isElite = rosPercentile >= ROS_ELITE_PERCENTILE;
  const isStarterCaliber = rosRank != null && rosRank <= 100;
  const isTopIdp = isIdp && rosRank != null && rosRank <= 50;
  const vetAge = _VET_AGE_BY_POS[pos];
  const veteran = age != null && vetAge != null && age >= vetAge;
  const young = age != null && age <= 24;

  if (veteran && isStrong) tags.push("Win-now target");
  if (isElite && isStarterCaliber && !isIdp) tags.push("Contender upgrade");
  if (
    veteran &&
    isStrong &&
    dynastyPercentile != null &&
    rosPercentile - dynastyPercentile >= ROS_SELLER_PERCENTILE_GAP
  ) {
    tags.push("Seller cash-out");
  }
  if (young && !isStrong) tags.push("Rebuilder hold");
  if (veteran && isStrong && !isStarterCaliber) tags.push("Avoid unless contending");
  if (
    !isStarterCaliber &&
    rosPercentile >= ROS_DEPTH_BAND_LOW_PERCENTILE &&
    rosPercentile < ROS_STRONG_PERCENTILE
  ) {
    tags.push("Depth spike option");
  }
  if (volatilityFlag && isStarterCaliber) tags.push("Best-ball boost");
  if (isTopIdp) tags.push("IDP contender target");
  if (!isStrong && !young) tags.push("Injury/bye cover");
  return tags;
}
