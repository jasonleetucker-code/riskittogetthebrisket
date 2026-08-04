import * as DL from "/home/user/riskittogetthebrisket/frontend/lib/draft-logic.js";
import fs from "node:fs";
// F16: DEFAULT_ROOKIES sum
const s = DL.DEFAULT_ROOKIES.reduce((a,p)=>a+p.preDraft,0);
console.log("DEFAULT_ROOKIES sum =", s, "(comment claims 1200)");
console.log("DEFAULT_TEAMS budget sum =", DL.DEFAULT_TEAMS.reduce((a,t)=>a+t.initialBudget,0));

// F11: hydrateWorkspace field retention
let ws = DL.createDefaultWorkspace();
const {workspace: w2} = DL.replacePlayerPool(ws, [
  {name:"Test Guy", preDraft: 50, pos:"LB", ktcDollar: 60, idpTradeCalcDollar: 55, assetClass:"idp"},
]);
console.log("\nbefore hydrate:", JSON.stringify(w2.players[0]));
const rehydrated = DL.hydrateWorkspace(JSON.parse(JSON.stringify(w2)));
console.log("after hydrate: ", JSON.stringify(rehydrated.players[0]));

// F01: nextBestTargets ordering vs preDraft ordering on pristine board
let st = DL.computeDraftStats(ws);
const nbt = DL.nextBestTargets(st, {limit: 10}).map(t=>t.player.name);
const byPre = [...st.enrichedPlayers].sort((a,b)=>b.preDraft-a.preDraft).slice(0,10).map(p=>p.name);
console.log("\nnextBestTargets:", nbt);
console.log("preDraft desc:  ", byPre);
console.log("identical order?", JSON.stringify(nbt)===JSON.stringify(byPre));

// F03: inflation at end of draft
const cap = JSON.parse(fs.readFileSync("/tmp/dc-auth.json","utf8"));
let w = DL.mergeDraftCapitalTeams(ws, cap.teamTotals, {picks:cap.picks, mode:"force"}).workspace;
let cur = w;
const ids = DL.computeDraftStats(cur).enrichedPlayers.map(p=>p.id);
const trace=[];
for (let i=0;i<ids.length;i++){
  cur = DL.recordPick(cur, {playerId: ids[i], teamIdx: i%12, amount: Math.max(1, Math.round(DL.DEFAULT_ROOKIES[i].preDraft*0.9))});
  if (i%10===9 || i>=66) {
    const s2 = DL.computeDraftStats(cur);
    const nx = s2.enrichedPlayers.find(p=>!p.drafted);
    trace.push([i+1, +s2.inflation.toFixed(3), nx? [nx.name, nx.preDraft, nx.inflatedFair, nx.myMaxBid] : null]);
  }
}
console.log("\npicks | inflation | [next undrafted, preDraft, inflatedFair, maxBid]");
for (const t of trace) console.log(t[0], t[1], JSON.stringify(t[2]));
