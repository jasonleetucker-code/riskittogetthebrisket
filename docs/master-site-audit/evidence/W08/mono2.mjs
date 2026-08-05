import fs from "node:fs";
import { buildRows } from "/home/user/riskittogetthebrisket/frontend/lib/dynasty-data.js";
import { adjustedSideTotals, verdictFromGap, meterVerdict } from "/home/user/riskittogetthebrisket/frontend/lib/trade-logic.js";
const data = JSON.parse(fs.readFileSync(new URL("./contract.json", import.meta.url).pathname,"utf8"));
const rows = buildRows(data).filter(r=>r.values.full>0);
const rnd = (()=>{let s=777; return ()=>{s=(s*1103515245+12345)&0x7fffffff; return s/0x7fffffff;};})();
const pick=()=>rows[Math.floor(rnd()*rows.length)];
const hits=[]; const flips=[];
let n2=0;
for (let n=0;n<40000;n++){
  const na=1+Math.floor(rnd()*3), nb=1+Math.floor(rnd()*3);
  const A=[],B=[]; const seen=new Set();
  while(A.length<na){const p=pick(); if(seen.has(p.name))continue; seen.add(p.name); A.push(p);}
  while(B.length<nb){const p=pick(); if(seen.has(p.name))continue; seen.add(p.name); B.push(p);}
  let extra=pick(); let g=0; while(seen.has(extra.name)&&g++<20) extra=pick();
  if(seen.has(extra.name))continue;
  n2++;
  const t0=adjustedSideTotals(A,B,"full"); const g0=t0[0].adjusted-t0[1].adjusted;
  const t1=adjustedSideTotals([...A,extra],B,"full"); const g1=t1[0].adjusted-t1[1].adjusted;
  if(g1<g0-1e-6){
    const rec={A:A.map(x=>`${x.name}:${x.values.full}`),B:B.map(x=>`${x.name}:${x.values.full}`),
      extra:`${extra.name}:${extra.values.full}`,gapBefore:Math.round(g0),gapAfter:Math.round(g1),
      loss:Math.round(g0-g1),
      meterBefore:meterVerdict(Math.abs(g0)).label, meterAfter:meterVerdict(Math.abs(g1)).label,
      sizes:[na,nb]};
    hits.push(rec);
    if(rec.meterBefore!==rec.meterAfter) flips.push(rec);
  }
}
hits.sort((a,b)=>b.loss-a.loss);
console.log("sampled:",n2,"violations:",hits.length,"verdict-label flips:",flips.length);
console.log("worst 3:",JSON.stringify(hits.slice(0,3),null,1));
console.log("flip examples:",JSON.stringify(flips.slice(0,4),null,1));
// size distribution
const c={}; for(const h of hits){const k=h.sizes.join('v'); c[k]=(c[k]||0)+1;}
console.log("violation by (|A|v|B|) before adding:",JSON.stringify(c));
fs.writeFileSync("monotonicity-full.json", JSON.stringify({sampled:n2,violations:hits.length,flips:flips.length,worst:hits.slice(0,30),flipExamples:flips.slice(0,30),bySize:c},null,1));
// re-scan for non-1v1 violations only
