import * as DL from "/home/user/riskittogetthebrisket/frontend/lib/draft-logic.js";
import fs from "node:fs";

const cap = JSON.parse(fs.readFileSync("/tmp/dc-auth.json","utf8"));
const slotMap = DL.slotsByTeamFromPicks(cap.picks);
console.log("=== TRUE per-team pick counts from live /api/draft-capital ===");
console.log([...slotMap.entries()].sort((a,b)=>b[1]-a[1]));

let ws = DL.createDefaultWorkspace();
const merged = DL.mergeDraftCapitalTeams(ws, cap.teamTotals, {picks: cap.picks, mode:"force"});
console.log("\n=== initialSlots AFTER merge (what the app believes) ===");
console.log(merged.workspace.teams.map(t=>[t.name, t.initialBudget, t.initialSlots]));

let w = merged.workspace;
// select Russini Panini as my team
const idx = w.teams.findIndex(t=>t.name==="Russini Panini");
w = {...w, settings:{...w.settings, myTeamIdx: idx}};
let s = DL.computeDraftStats(w);
console.log("\nmyInitialSlots(app) =", s.myInitialSlots, " TRUE =", slotMap.get("russini panini"));
console.log("totalInitialSlots(app) =", s.totalInitialSlots, " TRUE =", cap.picks.length);

// Simulate 6 picks -> slotPressure
const pool = s.enrichedPlayers.slice(0,6).map(p=>p.id);
let w2 = w;
for (const pid of pool) w2 = DL.recordPick(w2, {playerId:pid, teamIdx:idx, amount:1});
let s2 = DL.computeDraftStats(w2);
console.log("\n=== after 6 x $1 picks (25 real picks still to make) ===");
console.log("mySlotsRemaining", s2.mySlotsRemaining, "slotPressure", s2.slotPressure,
  "phaseMultiplier", s2.phaseMultiplier, "myRemaining", s2.myRemaining,
  "topCompetitorMax", s2.topCompetitorMax);
const nxt = s2.enrichedPlayers.find(p=>!p.drafted);
console.log("next player:", nxt.name, "fair", nxt.inflatedFair, "maxBid", nxt.myMaxBid,
  "winningBid", nxt.myWinningBid);
console.log("recommendation:", DL.playerRecommendation(nxt, s2));
console.log("teamStats mdv (mine):", s2.teamStats[idx].mdv, "effectiveBudget:", s2.teamStats[idx].effectiveBudget);
