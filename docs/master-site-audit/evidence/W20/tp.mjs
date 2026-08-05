import fs from "fs";
import { analyzeLeaguePhases } from "/home/user/riskittogetthebrisket/frontend/lib/team-phase.js";
const c = JSON.parse(fs.readFileSync("contract.json","utf8"));
// buildRows-equivalent: rows need name, rankDerivedValue, age
const rows = Object.entries(c.players).map(([name,v])=>({name, rankDerivedValue: v.rankDerivedValue||0, age: v.age}));
const res = analyzeLeaguePhases(c, rows);
console.log(JSON.stringify({leagueMedians:res.leagueMedians, teams:res.teams.map(t=>({name:t.name,ownerId:t.ownerId,phase:t.phase.label,totalValue:t.totalValue,medianAge:t.medianAge})), partnerships:res.partnerships},null,1));
