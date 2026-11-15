// The /trade meter half of `measure_fairness_band_change.py --compare v1-v2`
// (fairness_bands_v2, owner decisions 2026-10-20).  Read-only: it runs the
// frontend library itself -- the same adjustedSideTotals / classifyGap the
// meter renders -- on the pinned packages the Python script hands it.
//
//   node --no-warnings scripts/measure_fairness_band_meter.mjs <inputs.json> <out.json>
//
// inputs: [{gave: number[], got: number[]}]  (side A = gives, side B = receipts)
// output: [{v1, v2}]  v1 = band on the larger ADJUSTED side (retired),
//                     v2 = band on sideTotalsFairnessBase (the committed rule).
import { readFileSync, writeFileSync } from "node:fs";
import { classifyGap } from "../frontend/lib/fairness-bands.js";
import { adjustedSideTotals, sideTotalsFairnessBase } from "../frontend/lib/trade-logic.js";

const [, , inPath, outPath] = process.argv;
const pairs = JSON.parse(readFileSync(inPath, "utf8"));
const side = (values) => values.map((v, i) => ({ name: `p${i}`, values: { full: v } }));
const out = pairs.map(({ gave, got }) => {
  const totals = adjustedSideTotals(side(gave), side(got), "full");
  const gap = totals[0].adjusted - totals[1].adjusted;
  return {
    v1: classifyGap(gap, Math.max(totals[0].adjusted, totals[1].adjusted)).level,
    v2: classifyGap(gap, sideTotalsFairnessBase(totals)).level,
  };
});
writeFileSync(outPath, `${JSON.stringify(out)}\n`);
