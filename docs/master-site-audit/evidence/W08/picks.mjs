import fs from "node:fs";
import { resolvePickRow, parsePickToken } from "/home/user/riskittogetthebrisket/frontend/lib/trade-logic.js";
const data = JSON.parse(fs.readFileSync(new URL("./contract.json", import.meta.url).pathname,"utf8"));
const rows = JSON.parse(fs.readFileSync("rows.json","utf8"));
const lookup = new Map(rows.map(r=>[r.name.toLowerCase(), r]));
const aliases = data.pickAliases;
const out = {};
for (const t of data.sleeper.teams) {
  const resolved = [];
  const unresolved = [];
  for (const label of t.picks||[]) {
    const r = resolvePickRow(label, lookup, aliases);
    if (r) resolved.push({label, row:r.name, value:r.full});
    else unresolved.push(label);
  }
  const distinct = new Set(resolved.map(x=>x.row));
  out[t.name] = {rawPicks:(t.picks||[]).length, resolved:resolved.length, distinctRows:distinct.size, unresolved};
}
console.log(JSON.stringify(out,null,1));
// detail for Jason
const jason = data.sleeper.teams.find(t=>t.name==="Jason");
const det = {};
for (let i=0;i<jason.picks.length;i++){
  const label = jason.picks[i];
  const d = jason.pickDetails[i];
  const r = resolvePickRow(label, lookup, aliases);
  const k = label;
  (det[k] = det[k] || []).push({orig:d.original_roster_id, owner:d.owner_roster_id, row:r?r.name:null, value:r?r.full:null});
}
console.log("JASON 2027 1st entries:", JSON.stringify(det["2027 1st"],null,1));
console.log("JASON 2026 1st entries:", JSON.stringify(det["2026 1st"],null,1));
fs.writeFileSync("pick-ownership.json", JSON.stringify({perTeam:out, jasonDetail:det},null,1));
