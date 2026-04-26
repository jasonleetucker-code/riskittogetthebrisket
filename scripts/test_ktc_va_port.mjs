#!/usr/bin/env node
// Regression check for the KTC VA algorithm port.
//
// Loads scripts/ktc_va_observations.json (139 captured trades with
// KTC's displayed VA + recipient side) and compares against the
// ported ktcAdjustPackage in frontend/lib/trade-logic.js.
//
// Reports per-topology RMS error and per-trade misses > 200 absolute.
//
// Run: node scripts/test_ktc_va_port.mjs

import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(__dirname, "..");
const fixturePath = resolve(repoRoot, "scripts/ktc_va_observations.json");
const tradeLogicPath = resolve(repoRoot, "frontend/lib/trade-logic.js");

// Dynamic import the trade-logic module
const { ktcAdjustPackage } = await import(`file://${tradeLogicPath}`);

const fixture = JSON.parse(readFileSync(fixturePath, "utf8"));
const observations = fixture.observations;

const byTopology = {};
let totalSqErr = 0;
let totalCount = 0;
let nFires = 0;
let nFiresMatched = 0;
let nSilent = 0;
let nSilentMatched = 0;
const misses = [];

for (const obs of observations) {
  const a = obs.team1Values || [];
  const b = obs.team2Values || [];
  const observedVA1 = obs.valueAdjustmentTeam1 || 0;
  const observedVA2 = obs.valueAdjustmentTeam2 || 0;
  const observedVA = observedVA1 || observedVA2;
  const observedSide = observedVA1 > 0 ? 1 : observedVA2 > 0 ? 2 : 0;

  const result = ktcAdjustPackage(a, b);
  const portedVA = result.displayed ? result.value : 0;
  const portedSide = result.displayed ? result.side : 0;

  const sqErr = Math.pow(portedVA - observedVA, 2);
  totalSqErr += sqErr;
  totalCount += 1;

  const topo = obs.topology || "?";
  if (!byTopology[topo]) {
    byTopology[topo] = { count: 0, sqErr: 0, sumAbsObserved: 0 };
  }
  byTopology[topo].count += 1;
  byTopology[topo].sqErr += sqErr;
  byTopology[topo].sumAbsObserved += observedVA;

  if (observedVA > 0) {
    nFires += 1;
    if (portedVA > 0 && portedSide === observedSide) nFiresMatched += 1;
  } else {
    nSilent += 1;
    if (portedVA === 0) nSilentMatched += 1;
  }

  const absDiff = Math.abs(portedVA - observedVA);
  if (absDiff > 200) {
    misses.push({
      label: obs.label,
      topo,
      observedVA,
      observedSide,
      portedVA,
      portedSide,
      absDiff,
      a,
      b,
    });
  }
}

console.log(`\nKTC VA port regression — ${totalCount} observations\n`);
console.log(`Overall RMS error:           ${Math.sqrt(totalSqErr / totalCount).toFixed(1)}`);
console.log(`Fires matched (recipient ok): ${nFiresMatched}/${nFires} (${(nFiresMatched/nFires*100).toFixed(1)}%)`);
console.log(`Silent matched (correctly suppressed): ${nSilentMatched}/${nSilent} (${(nSilentMatched/nSilent*100).toFixed(1)}%)`);

console.log(`\nPer-topology RMS:`);
const topos = Object.keys(byTopology).sort();
for (const t of topos) {
  const x = byTopology[t];
  const rms = Math.sqrt(x.sqErr / x.count);
  const meanObserved = x.sumAbsObserved / x.count;
  const relPct = meanObserved > 0 ? (rms / meanObserved * 100).toFixed(0) : "-";
  console.log(`  ${t.padEnd(8)} n=${String(x.count).padStart(2)}  RMS=${rms.toFixed(0).padStart(5)}  meanVA=${meanObserved.toFixed(0).padStart(5)}  RMS/meanVA=${relPct}%`);
}

console.log(`\nWorst misses (|portedVA - observedVA| > 200):`);
misses.sort((x, y) => y.absDiff - x.absDiff);
for (const m of misses.slice(0, 15)) {
  console.log(`  ${m.label.padEnd(20)} topo=${m.topo}  observed=${m.observedVA}@${m.observedSide}  ported=${m.portedVA}@${m.portedSide}  diff=${m.absDiff}`);
  console.log(`    A=[${m.a.join(",")}]`);
  console.log(`    B=[${m.b.join(",")}]`);
}
if (misses.length > 15) {
  console.log(`  ... and ${misses.length - 15} more`);
}
console.log(`\nTotal misses >200: ${misses.length}/${totalCount}`);
