import * as DL from "/home/user/riskittogetthebrisket/frontend/lib/draft-logic.js";
import fs from "node:fs";
const cap = JSON.parse(fs.readFileSync("/tmp/dc-auth.json","utf8"));
let ws = DL.createDefaultWorkspace();
ws = DL.mergeDraftCapitalTeams(ws, cap.teamTotals, {picks:cap.picks, mode:"force"}).workspace;
// live pool exactly as the /draft auto-sync builds it
const sorted=[...cap.picks].sort((a,b)=>a.overallPick-b.overallPick);
const incoming = sorted.filter(p=>p.rookieName).map(p=>({
  name:p.rookieName, preDraft:Number(p.rookieKtcValue), pos:String(p.rookiePos||"").toUpperCase()||undefined,
  ktcDollar:p.rookieKtcDollar??null, idpTradeCalcDollar:p.rookieIdpDollar??null}));
console.log("live pool n=",incoming.length,"sum preDraft=",incoming.reduce((a,p)=>a+p.preDraft,0));
ws = DL.replacePlayerPool(ws, incoming).workspace;
let cur=ws;
const ids = DL.computeDraftStats(cur).enrichedPlayers.map(p=>p.id);
for (let i=0;i<ids.length;i++){
  const pre = DL.computeDraftStats(cur).enrichedPlayers.find(p=>p.id===ids[i]).preDraft;
  cur = DL.recordPick(cur,{playerId:ids[i],teamIdx:i%12,amount:Math.max(1,Math.round(pre*0.9))});
  const s=DL.computeDraftStats(cur); const nx=s.enrichedPlayers.find(p=>!p.drafted);
  if (i>=60 && nx) console.log(`picks=${i+1} spent=${s.totalSpent} rem=${s.remainingLeague} inflation=${s.inflation.toFixed(2)} degraded=${s.inflationDegraded} | ${nx.name} pre=$${nx.preDraft} FAIR=$${nx.inflatedFair} MAX=$${nx.myMaxBid}`);
}
