import fs from "node:fs";
import { buildRows } from "/home/user/riskittogetthebrisket/frontend/lib/dynasty-data.js";
import { resolvePickRow } from "/home/user/riskittogetthebrisket/frontend/lib/trade-logic.js";
const data = JSON.parse(fs.readFileSync(new URL("./contract.json", import.meta.url).pathname,"utf8"));
const rows = buildRows(data);
const lookup = new Map(rows.map(r=>[r.name.toLowerCase(), r]));
const aliases = data.pickAliases;
const zeroLabels = {}; const okLabels={};
for (const t of data.sleeper.teams)
  for (const label of t.picks||[]) {
    const r = resolvePickRow(label, lookup, aliases);
    const key = `${label} -> ${r?r.name:"NULL"}`;
    if (!r || !(r.values.full>0)) zeroLabels[key]=(zeroLabels[key]||0)+1;
    else okLabels[key]=(okLabels[key]||0)+1;
  }
console.log("ZERO-VALUE roster picks:"); console.log(JSON.stringify(zeroLabels,null,1));
// distinct-name collapse across the whole league
let raw=0, distinct=0;
for (const t of data.sleeper.teams){
  const s=new Set();
  for (const label of t.picks||[]) { raw++; const r=resolvePickRow(label,lookup,aliases); if(r) s.add(r.name); }
  distinct+=s.size;
}
console.log("league raw picks:",raw,"distinct row names after resolution:",distinct,"collapsed:",raw-distinct);
fs.writeFileSync("pick-zero-and-collapse.json", JSON.stringify({zeroLabels, okLabels, raw, distinct},null,1));
