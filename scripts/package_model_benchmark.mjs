/**
 * Package-model shape benchmark (owner VA package 2026-10-17, PR 4).
 *
 * SHAPE-STRESS ONLY — synthetic value arrays sampled from committed source
 * CSVs.  Not real-trade accuracy, not a trained parameter, and nothing here
 * changes a value or promotes a model.  Promotion of the GEOM challenger is a
 * separate owner decision on held-out evidence
 * (docs/valuation/PACKAGE_MODEL_EVALUATION_2026-10-17.md).
 *
 * Uses the ACTUAL repository functions — ``ktcAdjustPackage`` (incumbent),
 * ``packageAdjustPair`` (the sitewide dispatch, both registered models) and
 * ``geomPackageUtility`` — never a re-port.
 *
 * Runs, all deterministic:
 *   1. reproduction — the owner's 100,000-case same-case audit, byte-for-byte
 *      the sampling of ``trade-adjustment-bias-benchmark.mjs`` (seed 20261017,
 *      10 shapes x 10,000, raw gap <= 30%, ties within 1%);
 *   2. extension — >= 250,000 further cases: three new seeds on the same
 *      shapes, a full-roster population (offense + IDP + picks from the IDP
 *      Trade Calculator board), 10+-piece shapes, near ties and large gaps;
 *   3. stress — seeded property suite (seed 98231): adding a positive asset,
 *      raising an existing asset, side swap, permutation, positive scaling,
 *      1-v-1 = raw.
 *
 * Usage: node scripts/package_model_benchmark.mjs [--out DIR] [--quick]
 */
import fs from "node:fs";
import path from "node:path";
import { createHash } from "node:crypto";
import { fileURLToPath } from "node:url";
import {
  PACKAGE_MODEL_IDS,
  geomPackageUtility,
  ktcAdjustPackage,
  packageAdjustPair,
} from "../frontend/lib/trade-logic.js";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const args = process.argv.slice(2);
const quick = args.includes("--quick");
const outIdx = args.indexOf("--out");
const outDir = path.resolve(
  root,
  outIdx >= 0 ? args[outIdx + 1] : "docs/valuation/evidence/package_model_2026-10-17",
);

// ── sources ──────────────────────────────────────────────────────────────
function loadValues(rel, { min = 500, max = 10000 } = {}) {
  const csvPath = path.join(root, rel);
  const raw = fs.readFileSync(csvPath, "utf8");
  const lines = raw.trim().split(/\r?\n/);
  const columns = lines.shift().split(",").map((x) => x.trim());
  const vi = columns.indexOf("value");
  if (vi < 0) throw new Error(`${rel}: expected a value column`);
  const values = lines.map((l) => Number(l.split(",")[vi])).filter((v) => v >= min && v <= max);
  if (values.length < 50) throw new Error(`${rel}: not sufficiently populated`);
  return { rel, sha256: createHash("sha256").update(raw).digest("hex"), values };
}

// ── models ───────────────────────────────────────────────────────────────
const RAW = (a) => a.reduce((s, v) => s + v, 0);
const geom = (q) => (a) =>
  a
    .slice()
    .sort((x, y) => y - x)
    .reduce((s, v, i) => s + v * q ** i, 0);
const lp = (p) => (a) => a.reduce((s, v) => s + v ** p, 0) ** (1 / p);
const UTILITY = {
  RAW,
  TOP_20: (a) => 0.8 * RAW(a) + 0.2 * Math.max(...a),
  TOP_35: (a) => 0.65 * RAW(a) + 0.35 * Math.max(...a),
  GEOM_70: geom(0.7),
  GEOM_72: geom(0.72),
  GEOM_75: geom(0.75),
  GEOM_78: geom(0.78),
  GEOM_80: geom(0.8),
  GEOM_82: geom(0.82),
  GEOM_85: geom(0.85),
  GEOM_88: geom(0.88),
  GEOM_90: geom(0.9),
  LP_130: lp(1.3),
  LP_140: lp(1.4),
  LP_150: lp(1.5),
  LP_170: lp(1.7),
  HYBRID_50: (a) => 0.5 * RAW(a) + 0.5 * lp(1.5)(a),
};
// The owner's original 12 challengers (reproduction run reports exactly these).
const OWNER_MODELS = [
  "RAW", "TOP_20", "TOP_35", "GEOM_75", "GEOM_78", "GEOM_80", "GEOM_82", "GEOM_85",
  "LP_130", "LP_150", "LP_170", "HYBRID_50",
];

function ktcScores(A, B) {
  const adj = ktcAdjustPackage(A, B);
  return [RAW(A) + (adj.side === 1 ? adj.value : 0), RAW(B) + (adj.side === 2 ? adj.value : 0)];
}
// Dispatch (production code path) adjusted totals for a registered model.
function dispatchScores(A, B, modelId) {
  const r = packageAdjustPair(A, B, { modelId });
  const va = r.displayed ? r.value : 0;
  return [RAW(A) + (r.side === 1 ? va : 0), RAW(B) + (r.side === 2 ? va : 0)];
}

function win(a, b) {
  return Math.abs(a - b) <= 0.01 * Math.max(a, b) ? 0 : Math.sign(a - b);
}

function lcg(seed) {
  let state = seed >>> 0;
  return () => {
    state = (Math.imul(state, 1664525) + 1013904223) >>> 0;
    return state / 4294967296;
  };
}

// ── one sampled run ──────────────────────────────────────────────────────
function newStats() {
  return {
    cases: 0, sideA: 0, sideB: 0, ties: 0,
    unequal: 0, fewer: 0, more: 0, fewerTie: 0,
    hiKnown: 0, hiWins: 0, hiLoses: 0,
    nearCases: 0, nearFewer: 0, nearMore: 0,
    sameKTC: 0, diffRaw: 0, swapFail: 0,
    flipRawAtoB: 0, flipRawBtoA: 0,
    byShape: {}, byGap: {},
  };
}

const GAP_BINS = [
  [0, 0.05, "0-5%"],
  [0.05, 0.1, "5-10%"],
  [0.1, 0.2, "10-20%"],
  [0.2, 0.3, "20-30%"],
  [0.3, 0.45, "30-45%"],
  [0.45, 0.6, "45-60%"],
];
const gapBin = (g) => (GAP_BINS.find(([lo, hi]) => g >= lo && g <= hi) || [0, 0, "other"])[2];

function runSampled({ label, values, valuesMore = null, shapes, perShape, seed, gapMin = 0, gapMax = 0.3, models }) {
  const rng = lcg(seed);
  const methods = { KTC: null, ...Object.fromEntries(models.map((m) => [m, UTILITY[m]])) };
  const stats = Object.fromEntries(Object.keys(methods).map((k) => [k, newStats()]));
  let cases = 0;
  let dispatchGeomSignMismatch = 0;
  let dispatchKtcMismatch = 0;
  for (const [na, nb] of shapes) {
    let accepted = 0;
    let attempted = 0;
    while (accepted < perShape) {
      if (++attempted > perShape * 2000) throw new Error(`${label}: unable to sample ${na}v${nb}`);
      // ``valuesMore`` (big shapes): the side with more pieces draws from the
      // lower part of the distribution — a stud-for-depth trade — otherwise
      // ten random pieces always dwarf one and nothing is near-balanced.
      const poolA = valuesMore && na > nb ? valuesMore : values;
      const poolB = valuesMore && nb > na ? valuesMore : values;
      const A = Array.from({ length: na }, () => poolA[Math.floor(rng() * poolA.length)]);
      const B = Array.from({ length: nb }, () => poolB[Math.floor(rng() * poolB.length)]);
      const rA = RAW(A);
      const rB = RAW(B);
      const baseMax = Math.max(rA, rB);
      const gap = Math.abs(rA - rB) / baseMax;
      if (gap > gapMax || gap < gapMin) continue;
      accepted++;
      cases++;
      const rawW = win(rA, rB);
      const [ka, kb] = ktcScores(A, B);
      const kw = win(ka, kb);
      // Production dispatch must agree with the reference functions exactly.
      const [da, db] = dispatchScores(A, B, PACKAGE_MODEL_IDS.KTC_2026_04);
      if (da !== ka || db !== kb) dispatchKtcMismatch++;
      const [ga, gb] = dispatchScores(A, B, PACKAGE_MODEL_IDS.GEOM_Q078_V1);
      const uDiff = geomPackageUtility(A) - geomPackageUtility(B);
      if (Math.abs(ga - gb - uDiff) > 1.0) dispatchGeomSignMismatch++;
      for (const [name, fn] of Object.entries(methods)) {
        const [a, b] = fn ? [fn(A), fn(B)] : [ka, kb];
        const [ba, bb] = fn ? [fn(B), fn(A)] : ktcScores(B, A);
        const w = win(a, b);
        const row = stats[name];
        const key = `${na}v${nb}`;
        row.cases++;
        row.sideA += w === 1;
        row.sideB += w === -1;
        row.ties += w === 0;
        row.sameKTC += w === kw;
        row.diffRaw += w !== rawW;
        row.swapFail += w !== -win(ba, bb);
        if (rawW === 1 && w === -1) row.flipRawAtoB++;
        if (rawW === -1 && w === 1) row.flipRawBtoA++;
        const sh = row.byShape[key] ?? { cases: 0, fewer: 0, more: 0, tie: 0 };
        sh.cases++;
        const bin = gapBin(gap);
        const gb2 = row.byGap[bin] ?? { cases: 0, flips: 0, fewer: 0, unequal: 0 };
        gb2.cases++;
        gb2.flips += rawW !== 0 && w === -rawW;
        const topA = Math.max(...A);
        const topB = Math.max(...B);
        if (topA !== topB) {
          row.hiKnown++;
          const t = topA > topB ? 1 : -1;
          row.hiWins += w === t;
          row.hiLoses += w === -t;
        }
        if (na !== nb) {
          const con = na < nb ? 1 : -1;
          row.unequal++;
          row.fewer += w === con;
          row.more += w === -con;
          row.fewerTie += w === 0;
          sh.fewer += w === con;
          sh.more += w === -con;
          sh.tie += w === 0;
          gb2.unequal++;
          gb2.fewer += w === con;
          if (gap <= 0.05) {
            row.nearCases++;
            row.nearFewer += w === con;
            row.nearMore += w === -con;
          }
        }
        row.byShape[key] = sh;
        row.byGap[bin] = gb2;
      }
    }
  }
  const pct = (n, d) => (d ? Number(((100 * n) / d).toFixed(2)) : null);
  const models_ = Object.fromEntries(
    Object.entries(stats).map(([k, v]) => [
      k,
      {
        cases: v.cases,
        sideA: pct(v.sideA, v.cases),
        sideB: pct(v.sideB, v.cases),
        tie: pct(v.ties, v.cases),
        fewer: pct(v.fewer, v.unequal),
        more: pct(v.more, v.unequal),
        higherSingle: pct(v.hiWins, v.hiKnown),
        nearRawFewer: pct(v.nearFewer, v.nearCases),
        nearRawMore: pct(v.nearMore, v.nearCases),
        nearRawCases: v.nearCases,
        ktcMatch: pct(v.sameKTC, v.cases),
        rawVerdictDifferent: pct(v.diffRaw, v.cases),
        flipsRawAToB: v.flipRawAtoB,
        flipsRawBToA: v.flipRawBtoA,
        sideSwapFailures: v.swapFail,
        byShape: Object.fromEntries(
          Object.entries(v.byShape).map(([s, r]) => [
            s,
            { cases: r.cases, fewer: pct(r.fewer, r.cases), more: pct(r.more, r.cases), tie: pct(r.tie, r.cases) },
          ]),
        ),
        byRawGap: Object.fromEntries(
          Object.entries(v.byGap).map(([b, r]) => [
            b,
            { cases: r.cases, rawWinnerFlippedPct: pct(r.flips, r.cases), fewerWinsPct: pct(r.fewer, r.unequal) },
          ]),
        ),
      },
    ]),
  );
  return {
    label, seed, cases, perShape,
    shapes: shapes.map(([a, b]) => `${a}v${b}`),
    rawGapWindow: [gapMin, gapMax],
    dispatchKtcMismatch, dispatchGeomGapMismatch: dispatchGeomSignMismatch,
    models: models_,
  };
}

// ── stress suite ─────────────────────────────────────────────────────────
function runStress({ seed, cases }) {
  const rng = lcg(seed);
  const int = (lo, hi) => lo + Math.floor(rng() * (hi - lo + 1));
  const gapFns = {
    KTC: (A, B) => {
      const [a, b] = ktcScores(A, B);
      return a - b;
    },
    GEOM_78_dispatch: (A, B) => {
      const [a, b] = dispatchScores(A, B, PACKAGE_MODEL_IDS.GEOM_Q078_V1);
      return a - b;
    },
    GEOM_78: (A, B) => UTILITY.GEOM_78(A) - UTILITY.GEOM_78(B),
    HYBRID_50: (A, B) => UTILITY.HYBRID_50(A) - UTILITY.HYBRID_50(B),
    LP_150: (A, B) => UTILITY.LP_150(A) - UTILITY.LP_150(B),
  };
  const fail = Object.fromEntries(
    Object.keys(gapFns).map((k) => [
      k,
      { addToA_worsensA: 0, addToB_worsensB: 0, raiseB_worsensB: 0, sideSwap: 0, permutation: 0, scale: 0, oneVsOneNotRaw: 0 },
    ]),
  );
  // Integer outputs (KTC rounds) get a 1-point slack; utilities are exact up to float.
  const eps = (name) => (name.startsWith("KTC") || name.endsWith("dispatch") ? 1 : 1e-6);
  const examples = { KTC: [] };
  for (let c = 0; c < cases; c++) {
    const A = Array.from({ length: int(1, 4) }, () => int(500, 9999));
    const B = Array.from({ length: int(1, 4) }, () => int(500, 9999));
    const add = int(1, 3000);
    const raise = int(1, 2000);
    const bi = int(0, B.length - 1);
    const Braised = B.map((v, i) => (i === bi ? v + raise : v));
    const scaleK = [0.5, 2][c % 2];
    for (const [name, gap] of Object.entries(gapFns)) {
      const e = eps(name);
      const g = gap(A, B);
      const f = fail[name];
      if (gap([...A, add], B) < g - e) {
        f.addToA_worsensA++;
        if (name === "KTC" && examples.KTC.length < 5) examples.KTC.push({ A, B, addToA: add });
      }
      if (gap(A, [...B, add]) > g + e) f.addToB_worsensB++;
      if (gap(A, Braised) > g + e) f.raiseB_worsensB++;
      if (Math.abs(gap(B, A) + g) > e) f.sideSwap++;
      if (Math.abs(gap([...A].reverse(), [...B].reverse()) - g) > e) f.permutation++;
      const gs = gap(A.map((v) => v * scaleK), B.map((v) => v * scaleK));
      if (Math.abs(gs - scaleK * g) > Math.max(2 * e, 1e-6 * Math.abs(g)) * (1 + scaleK)) f.scale++;
      if (A.length === 1 && B.length === 1 && Math.abs(g - (A[0] - B[0])) > e) f.oneVsOneNotRaw++;
    }
  }
  return { seed, cases, definition: STRESS_DEFINITION, failures: fail, ktcAddToAExamples: examples.KTC };
}

const STRESS_DEFINITION =
  "Each case: |A|,|B| ~ U{1..4}, values ~ U{500..9999}; add ~ U{1..3000}; raise ~ U{1..2000} on one random B asset; " +
  "scale factor alternates 0.5 / 2. gap = adjusted A - adjusted B. Failures: adding to A lowers gap; adding to B raises gap; " +
  "raising a B asset raises gap; swap does not negate; reversing order changes gap; scaled gap != k*gap; 1v1 gap != raw gap. " +
  "Integer-rounded outputs (KTC, dispatch) get 1 point of slack.";

// ── named pathologies (exact, pinned in tests/valuation_math) ────────────
function named() {
  const rows = [
    [[7200], [6000]],
    [[7200], [6000, 1]],
    [[7200], [6000, 500]],
    [[9000], [8500]],
    [[9000], [8500, 1]],
    [[8200], [5500, 4900]],
    [[9000], Array(12).fill(2000)],
    [[9000], Array(12).fill(2500)],
  ];
  return rows.map(([A, B]) => {
    const [ka, kb] = ktcScores(A, B);
    const [ga, gb] = dispatchScores(A, B, PACKAGE_MODEL_IDS.GEOM_Q078_V1);
    return {
      A: A.length > 4 ? `${A.length}x${A[0]}` : A,
      B: B.length > 4 ? `${B.length}x${B[0]}` : B,
      rawGap: RAW(A) - RAW(B),
      ktcAdjustedGap: ka - kb,
      geom78AdjustedGap: ga - gb,
      geom78Utilities: [Math.round(UTILITY.GEOM_78(A)), Math.round(UTILITY.GEOM_78(B))],
    };
  });
}

// ── main ─────────────────────────────────────────────────────────────────
const ktc = loadValues("CSVs/site_raw/ktcCrowdSfTep.csv");
const idptc = loadValues("CSVs/site_raw/idpTradeCalc.csv");
const STD = [[1, 1], [1, 2], [1, 3], [1, 4], [2, 2], [2, 3], [2, 4], [3, 3], [3, 4], [4, 4]];
const BIG = [[1, 10], [2, 10], [3, 12], [5, 10], [1, 6], [2, 8]];
const per = quick ? 500 : 10000;
const ALL = Object.keys(UTILITY);

const runs = [];
runs.push(runSampled({ label: "reproduction_owner_100k", values: ktc.values, shapes: STD, perShape: per, seed: 20261017, models: OWNER_MODELS }));
for (const seed of [20261018, 20261019, 20261020]) {
  runs.push(runSampled({ label: `ktc_std_seed_${seed}`, values: ktc.values, shapes: STD, perShape: per, seed, models: ALL }));
}
runs.push(runSampled({ label: "full_roster_idptc_std", values: idptc.values, shapes: STD, perShape: per / 2, seed: 20261021, models: ALL }));
const sortedKtc = ktc.values.slice().sort((a, b) => a - b);
const ktcLower = sortedKtc.slice(0, Math.floor(sortedKtc.length * 0.5));
runs.push(runSampled({ label: "ktc_big_shapes_depth_from_lower_half", values: ktc.values, valuesMore: ktcLower, shapes: BIG, perShape: per / 2, seed: 20261022, gapMax: 0.3, models: ALL }));
runs.push(runSampled({ label: "ktc_near_ties_le5pct", values: ktc.values, shapes: STD, perShape: per / 4, seed: 20261023, gapMax: 0.05, models: ALL }));
runs.push(runSampled({ label: "ktc_large_gaps_30_60pct", values: ktc.values, shapes: STD, perShape: per / 4, seed: 20261024, gapMin: 0.3, gapMax: 0.6, models: ALL }));
const stress = runStress({ seed: 98231, cases: quick ? 3000 : 60000 });

const extensionCases = runs.slice(1).reduce((s, r) => s + r.cases, 0);
const result = {
  purpose: "SHAPE-STRESS only. Not real-trade accuracy, not a trained parameter, not a promotion.",
  generatedBy: "scripts/package_model_benchmark.mjs",
  sources: [ktc, idptc].map(({ rel, sha256, values }) => ({ path: rel, sha256, eligibleRows: values.length })),
  winTolerance: "within 1% of the larger evaluated package = even",
  reproductionCases: runs[0].cases,
  extensionCases,
  runs,
  stress,
  namedPathologies: named(),
};
fs.mkdirSync(outDir, { recursive: true });
const jsonPath = path.join(outDir, quick ? "benchmark_quick.json" : "benchmark.json");
fs.writeFileSync(jsonPath, JSON.stringify(result, null, 2) + "\n");

// Flat bias matrix CSV — one row per (run, model).
const header = [
  "run", "model", "cases", "sideA_pct", "sideB_pct", "tie_pct", "fewer_pct", "more_pct",
  "higher_single_pct", "near_fewer_pct", "near_more_pct", "ktc_match_pct", "raw_verdict_diff_pct",
  "flips_rawA_to_B", "flips_rawB_to_A", "swap_failures",
];
const csv = [header.join(",")];
for (const r of runs) {
  for (const [m, v] of Object.entries(r.models)) {
    csv.push([
      r.label, m, v.cases, v.sideA, v.sideB, v.tie, v.fewer, v.more, v.higherSingle,
      v.nearRawFewer, v.nearRawMore, v.ktcMatch, v.rawVerdictDifferent,
      v.flipsRawAToB, v.flipsRawBToA, v.sideSwapFailures,
    ].join(","));
  }
}
fs.writeFileSync(path.join(outDir, quick ? "bias_matrix_quick.csv" : "bias_matrix.csv"), csv.join("\n") + "\n");
const rep = runs[0].models;
console.log(
  JSON.stringify(
    {
      output: path.relative(root, jsonPath),
      reproductionCases: runs[0].cases,
      extensionCases,
      dispatchMismatches: runs.map((r) => [r.label, r.dispatchKtcMismatch, r.dispatchGeomGapMismatch]),
      reproduction: Object.fromEntries(["KTC", "GEOM_78", "HYBRID_50", "RAW"].map((k) => [k, { fewer: rep[k].fewer, more: rep[k].more, higherSingle: rep[k].higherSingle }])),
      stress: stress.failures,
    },
    null,
    2,
  ),
);
