import * as DL from "/home/user/riskittogetthebrisket/frontend/lib/draft-logic.js";

let ws = DL.createDefaultWorkspace();
let stats = DL.computeDraftStats(ws);
console.log("=== PRISTINE ===");
console.log("myTeam", stats.myTeamName, "myRemaining", stats.myRemaining,
  "myInitialSlots", stats.myInitialSlots, "mySlotsRemaining", stats.mySlotsRemaining,
  "slotPressure", stats.slotPressure, "phaseMult", stats.phaseMultiplier,
  "BA", stats.budgetAdvantage, "inflation", stats.inflation, "topCompMax", stats.topCompetitorMax);
const love = stats.enrichedPlayers[0];
console.log("Love:", {preDraft: love.preDraft, inflatedFair: love.inflatedFair,
  myMaxBid: love.myMaxBid, myWinningBid: love.myWinningBid, enforceUpTo: love.enforceUpTo});

// --- Spend down my budget to near zero, then check bid recs ---
// My team idx 0 has $417. Buy 5 players at high prices.
const buys = [["jeremiyah-love",130],["fernando-mendoza",100],["makai-lemon",88],
              ["carnell-tate",80],["jordyn-tyson",15]];
let ws2 = ws;
for (const [pid, amt] of buys) ws2 = DL.recordPick(ws2, {playerId: pid, teamIdx: 0, amount: amt});
let s2 = DL.computeDraftStats(ws2);
console.log("\n=== AFTER 5 PICKS, $413 SPENT ===");
console.log("myRemaining", s2.myRemaining, "mySlotsRemaining", s2.mySlotsRemaining,
  "slotPressure", s2.slotPressure, "phaseMult", s2.phaseMultiplier, "BA", s2.budgetAdvantage,
  "inflation", s2.inflation.toFixed(4), "topCompMax", s2.topCompetitorMax);
const styles = s2.enrichedPlayers.find(p=>p.id==="sonny-styles");
console.log("Sonny Styles:", {preDraft: styles.preDraft, inflatedFair: styles.inflatedFair,
  myMaxBid: styles.myMaxBid, myWinningBid: styles.myWinningBid, enforceUpTo: styles.enforceUpTo});
console.log("BID EXCEEDS MY REMAINING?", styles.myWinningBid, ">", s2.myRemaining, "=>",
  styles.myWinningBid > s2.myRemaining);
console.log("bidStatus at $" + (s2.myRemaining + 20) + ":", DL.bidStatus(styles, s2.myRemaining+20));
console.log("nextBestTargets:", DL.nextBestTargets(s2, {limit:5}).map(t=>
  `${t.player.name} ev=${t.ev.toFixed(1)} win=$${t.player.myWinningBid} fair=$${t.player.inflatedFair}`));

// --- Exceed slot count: 7 picks with only 6 slots ---
let ws3 = ws2;
ws3 = DL.recordPick(ws3, {playerId:"sonny-styles", teamIdx:0, amount:1});
ws3 = DL.recordPick(ws3, {playerId:"caleb-downs", teamIdx:0, amount:1});
let s3 = DL.computeDraftStats(ws3);
console.log("\n=== 7 PICKS vs 6 SLOTS ===");
console.log("picksCount", s3.teamStats[0].picksCount, "initialSlots", s3.myInitialSlots,
  "slotsRemaining", s3.mySlotsRemaining, "slotPressure", s3.slotPressure,
  "phaseMult", s3.phaseMultiplier, "myRemaining", s3.myRemaining,
  "effBudget(mine)", s3.teamStats[0].effectiveBudget, "mdv", s3.teamStats[0].mdv);
