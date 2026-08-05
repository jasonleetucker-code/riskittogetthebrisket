import * as DL from "/home/user/riskittogetthebrisket/frontend/lib/draft-logic.js";
import fs from "node:fs";
const cap = JSON.parse(fs.readFileSync("/tmp/dc-auth.json","utf8"));
let ws = DL.mergeDraftCapitalTeams(DL.createDefaultWorkspace(), cap.teamTotals, {picks:cap.picks, mode:"force"}).workspace;
const sorted=[...cap.picks].sort((a,b)=>a.overallPick-b.overallPick);
const incoming = sorted.filter(p=>p.rookieName).map(p=>({
  name:p.rookieName, preDraft:Number(p.rookieKtcValue), pos:String(p.rookiePos||"").toUpperCase()||undefined,
  ktcDollar:p.rookieKtcDollar??null, idpTradeCalcDollar:p.rookieIdpDollar??null}));
ws = DL.replacePlayerPool(ws, incoming).workspace;
const s = DL.computeDraftStats(ws);
const nom = DL.nominationCandidates(s,{limit:100});
console.log("nominationCandidates (vendor overrates us) count =", nom.length, "of", s.enrichedPlayers.length);
console.log("  top5:", nom.slice(0,5).map(x=>`${x.player.name} ${x.vendorLabel} $${x.vendorDollar} vs $${x.ourDollar}`));
const bv = DL.bestValueOnBoard(s,{limit:10});
console.log("\nbestValueOnBoard n=",bv.length);
console.log("  rows:", bv.map(x=>`${x.player.name} ${x.vendorLabel} our$${x.ourDollar} vend$${x.vendorDollar} gapPct=${(x.gapPct*100).toFixed(0)}%`));
// how many KTC-covered offense rows qualify (our > vendor)?
const offQual = s.enrichedPlayers.filter(p=>p.ktcDollar>0 && p.preDraft - p.ktcDollar >= 1);
console.log("\noffense rows where OUR board > KTC by >= $1:", offQual.length);
