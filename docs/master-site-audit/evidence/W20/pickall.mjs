import fs from "fs";
import { buildRows } from "./lib/dynasty-data.js";
import { computePortfolio } from "./lib/portfolio-insights.js";
import { buildTeamValueBreakdown, buildPlayerMetaMap } from "./lib/league-analysis.js";
const c = JSON.parse(fs.readFileSync("contract.json","utf8"));
const rows = buildRows(c); const meta = buildPlayerMetaMap(rows);
let ta=0, tb=0, tot=0, unres=0;
console.log("team".padEnd(10),"picks","portfolio-insights","league-analysis","diff");
for (const team of c.sleeper.teams) {
  const local = computePortfolio({rows, selectedTeam:team, rawData:c, history:{}, rosterSettings:{rosterPositions:c.sleeper.rosterPositions}});
  const br = buildTeamValueBreakdown(team, meta, rows, "full", c.pickAliases, c.sleeper.rosterPositions);
  const a=Math.round(local.pickValue), b=Math.round(br.byGroup.PICKS);
  ta+=a; tb+=b; tot+=team.picks.length; unres+=local.unresolved.length;
  console.log(team.name.padEnd(10), String(team.picks.length).padStart(5), String(a).padStart(18), String(b).padStart(15), String(b-a).padStart(6));
}
console.log("TOTAL".padEnd(10), String(tot).padStart(5), String(ta).padStart(18), String(tb).padStart(15), String(tb-ta).padStart(6), "unresolvedNames", unres);
