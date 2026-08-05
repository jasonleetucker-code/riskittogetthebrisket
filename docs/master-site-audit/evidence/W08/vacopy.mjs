import fs from "node:fs";
import { buildRows } from "/home/user/riskittogetthebrisket/frontend/lib/dynasty-data.js";
import { adjustedSideTotals } from "/home/user/riskittogetthebrisket/frontend/lib/trade-logic.js";
const data = JSON.parse(fs.readFileSync(new URL("./contract.json", import.meta.url).pathname,"utf8"));
const rows = buildRows(data).filter(r=>r.values.full>0);
const rnd=(()=>{let s=4242; return ()=>{s=(s*1103515245+12345)&0x7fffffff; return s/0x7fffffff;};})();
const pick=()=>rows[Math.floor(rnd()*rows.length)];
let more=[], equal=[], fewer=0, tot=0;
for(let n=0;n<50000;n++){
  const na=1+Math.floor(rnd()*4), nb=1+Math.floor(rnd()*4);
  const A=[],B=[],seen=new Set();
  while(A.length<na){const p=pick(); if(seen.has(p.name))continue; seen.add(p.name); A.push(p);}
  while(B.length<nb){const p=pick(); if(seen.has(p.name))continue; seen.add(p.name); B.push(p);}
  const t=adjustedSideTotals(A,B,"full");
  const ri = t[0].adjustment>0?0:(t[1].adjustment>0?1:-1);
  if(ri<0) continue;
  tot++;
  const rc=[na,nb][ri], oc=[na,nb][1-ri];
  if(rc>oc) more.push({A:A.map(x=>`${x.name}:${x.values.full}`),B:B.map(x=>`${x.name}:${x.values.full}`),recipient:ri?"B":"A",recipientPieces:rc,otherPieces:oc,va:Math.round(t[ri].adjustment)});
  else if(rc===oc) equal.push({A:A.map(x=>`${x.name}:${x.values.full}`),B:B.map(x=>`${x.name}:${x.values.full}`),recipient:ri?"B":"A",pieces:rc,va:Math.round(t[ri].adjustment)});
  else fewer++;
}
console.log("VA fired:",tot,"| recipient had FEWER pieces:",fewer,`(${(100*fewer/tot).toFixed(1)}%)`,
            "| EQUAL pieces:",equal.length,`(${(100*equal.length/tot).toFixed(1)}%)`,
            "| MORE pieces:",more.length,`(${(100*more.length/tot).toFixed(1)}%)`);
more.sort((a,b)=>b.va-a.va);
console.log("VA to the side with MORE pieces, top 3:", JSON.stringify(more.slice(0,3),null,1));
equal.sort((a,b)=>b.va-a.va);
console.log("VA on EQUAL-count trade, top 2:", JSON.stringify(equal.slice(0,2),null,1));
fs.writeFileSync("va-recipient.json", JSON.stringify({tot,fewer,equal:equal.length,more:more.length,moreTop:more.slice(0,20),equalTop:equal.slice(0,20)},null,1));
