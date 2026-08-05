// W11 evidence — verbatim copy of frontend/lib/waiver-logic.js::computeFaabHint
// (+ its roundHalfUp) evaluated over an 800-point grid.  Emits JSON on stdout:
//   [[budget, value, topValueInPool, aggressive, reasonable, lowball], ...]
// Run: node docs/master-site-audit/evidence/W11/parity_grid.js
function roundHalfUp(value) {
  return Math.floor(value + 0.5);
}
function computeFaabHint(candidateValue, { leagueBudget = 100, topValueInPool = null } = {}) {
  const v = Number(candidateValue);
  if (!Number.isFinite(v) || v <= 0 || leagueBudget <= 0) {
    return { aggressive: 0, reasonable: 0, lowball: 0 };
  }
  const top = Math.max(v, Number(topValueInPool) || 0);
  const share = top > 0 ? v / top : 1.0;
  const aggressivePct = 0.05 + 0.25 * share;
  const aggressiveRaw = leagueBudget * aggressivePct;
  return {
    aggressive: Math.max(1, roundHalfUp(aggressiveRaw)),
    reasonable: Math.max(1, roundHalfUp(aggressiveRaw * 0.7)),
    lowball: Math.max(1, roundHalfUp(aggressiveRaw * 0.35)),
  };
}
const out = [];
const TOP = 9999;
for (const budget of [50, 100, 200, 1000]) {
  for (let i = 1; i <= 200; i++) {
    const val = Math.round(((TOP * i) / 200) * 100) / 100;
    const h = computeFaabHint(val, { leagueBudget: budget, topValueInPool: TOP });
    out.push([budget, val, TOP, h.aggressive, h.reasonable, h.lowball]);
  }
}
console.log(JSON.stringify(out));
