import fs from "fs";
import { buildRows } from "./lib/dynasty-data.js";
import { buildPlayerMetaMap, buildAllTeamSummaries } from "./lib/league-analysis.js";
const c = JSON.parse(fs.readFileSync("contract.json","utf8"));
const rows = buildRows(c);
console.error("rows", rows.length, JSON.stringify(rows[0]).slice(0,300));
const meta = buildPlayerMetaMap(rows);
const rp = c.sleeper.rosterPositions;
const out = {};
for (const scope of ["full","players","starters"]) {
  const t = buildAllTeamSummaries(c.sleeper.teams, meta, rows, scope, c.pickAliases, rp);
  out[scope]=t.map(x=>({name:x.name,total:Math.round(x.total),pickCount:x.pickCount,picksValued:x.pickDetails.length,unavail:x.starterSlotsUnavailable,byGroup:Object.fromEntries(Object.entries(x.byGroup).map(([k,v])=>[k,Math.round(v)]))}));
}
console.log(JSON.stringify(out,null,1));
