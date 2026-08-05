import fs from "fs";
import { buildRows } from "./lib/dynasty-data.js";
import { computePortfolio } from "./lib/portfolio-insights.js";
const c = JSON.parse(fs.readFileSync("contract.json","utf8"));
const term = JSON.parse(fs.readFileSync("w20/term-468418790212759552.json","utf8"));
const rows = buildRows(c);
const team = c.sleeper.teams.find(t=>t.name==="Jason");
const local = computePortfolio({rows, selectedTeam:{...team, ownerId:team.ownerId}, rawData:c, history:{}, rosterSettings:{rosterPositions:c.sleeper.rosterPositions}});
const server = term.portfolio;
const merged = {...local, totalValue: server.totalValue ?? local.totalValue, byPosition: server.byPosition||local.byPosition};
console.log(JSON.stringify({
  localTotal: Math.round(local.totalValue), serverTotal: server.totalValue,
  local_starter: Math.round(local.starterValue), local_bench: Math.round(local.benchValue),
  local_pickValue: Math.round(local.pickValue), local_pickCount: local.pickCount,
  RENDERED_TotalValue: merged.totalValue,
  RENDERED_legend_sum: Math.round(local.starterValue+local.benchValue+local.pickValue),
  RENDERED_byPosition_PICK: merged.byPosition.PICK,
  local_byPosition_PICK: local.byPosition.PICK,
},null,1));
