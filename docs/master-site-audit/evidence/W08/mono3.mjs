import fs from "node:fs";
import { buildRows } from "/home/user/riskittogetthebrisket/frontend/lib/dynasty-data.js";
import { adjustedSideTotals, meterVerdict } from "/home/user/riskittogetthebrisket/frontend/lib/trade-logic.js";
const data = JSON.parse(fs.readFileSync(new URL("./contract.json", import.meta.url).pathname,"utf8"));
const rows = buildRows(data).filter(r=>r.values.full>0);
const rnd=(()=>{let s=999; return ()=>{s=(s*1103515245+12345)&0x7fffffff; return s/0x7fffffff;};})();
const pick=()=>rows[Math.floor(rnd()*rows.length)];
const hits=[];
for(let n=0;n<60000;n++){
  const na=2+Math.floor(rnd()*2), nb=2+Math.floor(rnd()*2);
  const A=[],B=[],seen=new Set();
  while(A.length<na){const p=pick(); if(seen.has(p.name))continue; seen.add(p.name); A.push(p);}
  while(B.length<nb){const p=pick(); if(seen.has(p.name))continue; seen.add(p.name); B.push(p);}
  let extra=pick(),g=0; while(seen.has(extra.name)&&g++<20) extra=pick();
  if(seen.has(extra.name))continue;
  const t0=adjustedSideTotals(A,B,"full"), g0=t0[0].adjusted-t0[1].adjusted;
  const t1=adjustedSideTotals([...A,extra],B,"full"), g1=t1[0].adjusted-t1[1].adjusted;
  if(g1<g0-1e-6) hits.push({A:A.map(x=>`${x.name}:${x.values.full}`),B:B.map(x=>`${x.name}:${x.values.full}`),
    extra:`${extra.name}:${extra.values.full}`,gapBefore:Math.round(g0),gapAfter:Math.round(g1),loss:Math.round(g0-g1),
    adjBefore:t0.map(t=>Math.round(t.adjustment)),adjAfter:t1.map(t=>Math.round(t.adjustment)),
    meterBefore:meterVerdict(Math.abs(g0)).label,meterAfter:meterVerdict(Math.abs(g1)).label});
}
hits.sort((a,b)=>b.loss-a.loss);
console.log("non-1v1 (2-3 per side) violations:",hits.length,"of 60000");
console.log(JSON.stringify(hits.slice(0,4),null,1));
fs.writeFileSync("monotonicity-multi.json", JSON.stringify(hits.slice(0,40),null,1));
