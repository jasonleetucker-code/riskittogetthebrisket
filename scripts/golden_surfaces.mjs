/**
 * Capture the JS decision surfaces the board harness cannot see.
 *
 * WHY THIS EXISTS
 * ---------------
 * `scripts/golden_board.py` captures the backend contract, which is
 * where values live — but roughly half the audit's Critical findings
 * are decisions made in `frontend/lib/`: the trade verdict, the
 * fairness bands, the auction bid. A change there moves what the user
 * is told while every board number stays identical, so the board diff
 * reports "no change" and the regression ships.
 *
 * This emits the same `{rows: {key: {...}}}` shape as the board
 * capture so `scripts/board_diff.py` can diff it with no second
 * differ (`--value-field` / `--label-fields`).
 *
 * Run standalone, or via `scripts/golden_surfaces.py`, which merges
 * this with the Python-side surfaces into one file:
 *
 *     node scripts/golden_surfaces.mjs
 *
 * ADDING A SURFACE
 * ----------------
 * Add an entry to `SURFACES`. Keep each one a PURE call over a fixed
 * input grid — no clock, no network, no filesystem — or the capture
 * differs from itself and the diff is worthless. Surfaces are added by
 * the batch that needs to measure them rather than all up front:
 * inventing a fixture for a page nobody is editing yet produces a
 * fixture that encodes a guess about the shape of the fix.
 */

import {
  meterVerdict,
  percentageGap,
  verdictFromGap,
  colorFromGap,
} from "../frontend/lib/trade-logic.js";

/**
 * Trade pairs spanning the scale, including the two the audit
 * reproduced (T-2): a bench trade that is 81% lopsided and reads
 * FAIR, and a blockbuster that is 4% apart and reads SLIGHT EDGE.
 * The scale-invariance pairs — (500,180) vs (9000,3240), same ratio —
 * are the release gate: identical ratio must mean identical verdict.
 */
const TRADE_PAIRS = [
  [420, 80],
  [9000, 8650],
  [500, 180],
  [9000, 3240],
  [100, 100],
  [1200, 1000],
  [4000, 2000],
  [9999, 1],
  [350, 0],
  [0, 350],
  [6000, 9000],
  [8000, 8000],
];

function tradeVerdictRows() {
  const rows = {};
  for (const [a, b] of TRADE_PAIRS) {
    const gap = a - b;
    const abs = Math.abs(gap);
    const meter = meterVerdict(abs);
    rows[`trade_verdict/A=${a},B=${b}`] = {
      // The numeric the diff tracks: the gap the bands are applied to.
      value: gap,
      gapPercent: percentageGap(a, b),
      meterLabel: meter.label,
      meterLevel: meter.level,
      verdictFromGap: verdictFromGap(gap),
      colorFromGap: colorFromGap(gap),
      // Which side the meter's colour names as ahead. T-1 is that this
      // and the flow arithmetic disagree about what a side's pile means,
      // so recording it makes the inversion visible in a diff.
      meterFavours: gap === 0 ? "even" : gap > 0 ? "A" : "B",
    };
  }
  return rows;
}

const SURFACES = {
  trade_verdict: tradeVerdictRows,
};

function main() {
  const rows = {};
  for (const [name, fn] of Object.entries(SURFACES)) {
    Object.assign(rows, fn());
  }
  process.stdout.write(JSON.stringify({ rows }, null, 1));
}

main();
