import * as DL from "/home/user/riskittogetthebrisket/frontend/lib/draft-logic.js";
function mk(myBud, rivalBud){const ws=DL.createDefaultWorkspace();return {...ws,settings:{...ws.settings,myTeamIdx:0},
 teams:[{name:"Me",initialBudget:myBud,initialSlots:6,feedBudget:myBud},{name:"Rival",initialBudget:rivalBud,initialSlots:6,feedBudget:rivalBud}],
 players:[{id:"a",rank:1,name:"A",preDraft:60},{id:"b",rank:2,name:"B",preDraft:35},{id:"c",rank:3,name:"C",preDraft:30}],
 picks:[],tags:{},targetBoard:[],parSheet:[],nominations:[]};}
console.log("myBud rivalBud  BA    topCompMax  rowsReturned");
for (const [m,r] of [[100,100],[110,100],[150,100],[300,100],[100,300],[100,60],[100,20]]) {
  const s=DL.computeDraftStats(mk(m,r));
  console.log(`${m}\t${r}\t${s.budgetAdvantage}\t$${s.topCompetitorMax}\t${DL.nextBestTargets(s,{limit:10}).length}`);
}
