import fs from "node:fs";
import { adjustedSideTotals, tradeGapAdjusted, verdictFromGap, meterVerdict } from "/home/user/riskittogetthebrisket/frontend/lib/trade-logic.js";
const rows = JSON.parse(fs.readFileSync("rows.json","utf8"));
const byName = new Map(rows.map(r=>[r.name,r]));
const priced = rows.filter(r=>r.values===undefined? false : true);
const R = (n) => { const r = byName.get(n); if(!r) throw new Error("missing "+n); return {name:r.name,pos:r.pos,assetClass:r.assetClass,values:{full:r.full,raw:r.raw}}; };
// build ~20 trades from real, priced assets
const pool = rows.filter(r=>r.full>0).sort((a,b)=>b.full-a.full);
const off = pool.filter(r=>r.assetClass==="offense");
const idp = pool.filter(r=>r.assetClass==="idp");
const picks = pool.filter(r=>r.assetClass==="pick");
const mk = (a,b)=>({A:a.map(R),B:b.map(R)});
const trades=[];
for (let i=0;i<8;i++){
  trades.push(mk([off[i].name],[off[i+1].name, off[i+30].name]));
}
for (let i=0;i<4;i++){
  trades.push(mk([off[i*3].name, picks[i].name],[off[i*3+5].name, idp[i].name]));
}
for (let i=0;i<4;i++){
  trades.push(mk([idp[i].name],[idp[i+1].name, picks[i+3].name]));
}
for (let i=0;i<4;i++){
  trades.push(mk([off[i].name, off[i+10].name, picks[i].name],[off[i+2].name, idp[i+2].name, picks[i+6].name, off[i+60].name]));
}
const out=[];
let asym=0;
for (const t of trades){
  const fwd = adjustedSideTotals(t.A,t.B,"full",null,null);
  const rev = adjustedSideTotals(t.B,t.A,"full",null,null);
  const gapF = fwd[0].adjusted - fwd[1].adjusted;
  const gapR = rev[1].adjusted - rev[0].adjusted; // same orientation
  const ok = Math.abs(gapF-gapR) < 1e-9;
  if(!ok) asym++;
  out.push({A:t.A.map(x=>`${x.name}=${x.values.full}`),B:t.B.map(x=>`${x.name}=${x.values.full}`),
    fwd:{rawA:fwd[0].raw,adjA:fwd[0].adjustment,rawB:fwd[1].raw,adjB:fwd[1].adjustment,gap:gapF,verdict:verdictFromGap(gapF)},
    rev:{rawA:rev[1].raw,adjA:rev[1].adjustment,rawB:rev[0].raw,adjB:rev[0].adjustment,gap:gapR,verdict:verdictFromGap(gapR)},
    symmetric:ok});
}
console.log("trades:",out.length,"asymmetric:",asym);
for (const o of out) if(!o.symmetric) console.log(JSON.stringify(o,null,1));
fs.writeFileSync("symmetry.json", JSON.stringify(out,null,1));
console.log(JSON.stringify(out.slice(0,3),null,1));
