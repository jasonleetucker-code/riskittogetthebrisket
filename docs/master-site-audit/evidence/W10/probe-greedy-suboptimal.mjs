import * as DL from "/home/user/riskittogetthebrisket/frontend/lib/draft-logic.js";
function mk(myBud, rivalBud) {
  const ws = DL.createDefaultWorkspace();
  return {...ws, settings:{...ws.settings, myTeamIdx:0},
    teams:[{name:"Me",initialBudget:myBud,initialSlots:3,feedBudget:myBud},
           {name:"Rival",initialBudget:rivalBud,initialSlots:3,feedBudget:rivalBud}],
    players:[{id:"a",rank:1,name:"A",preDraft:60},{id:"b",rank:2,name:"B",preDraft:35},
             {id:"c",rank:3,name:"C",preDraft:30},{id:"d",rank:4,name:"D",preDraft:1}],
    picks:[],tags:{},targetBoard:[],parSheet:[],nominations:[]};
}
// CASE 1: balanced field, BA == 1
let s = DL.computeDraftStats(mk(65,65));
console.log("CASE 1 balanced (BA=%s): nextBestTargets returns %d rows", s.budgetAdvantage, DL.nextBestTargets(s,{limit:10}).length);

// CASE 2: I am richer -> list is non-empty. Budget $65, 3 slots.
s = DL.computeDraftStats(mk(65,20));
console.log("\nCASE 2 my$65 rival$20  BA=%s topCompMax=$%d inflation=%s", s.budgetAdvantage, s.topCompetitorMax, s.inflation.toFixed(3));
const list = DL.nextBestTargets(s,{limit:10});
for (const t of list) console.log(`  ${t.player.name} preDraft=$${t.player.preDraft} ev=${t.ev.toFixed(2)} fair=$${t.player.inflatedFair} WIN-AT=$${t.player.myWinningBid}`);
console.log("  order == preDraft-descending order?",
  JSON.stringify(list.map(t=>t.player.name)) === JSON.stringify([...s.enrichedPlayers].sort((a,b)=>b.preDraft-a.preDraft).slice(0,list.length).map(p=>p.name)));
let bud=65, got=[], val=0;
for (const t of list) { const p=t.player.myWinningBid; if (p<=bud){bud-=p;got.push(t.player.name);val+=t.player.preDraft;} }
console.log("  follow list top-down at Win-at prices:", got, "spent $"+(65-bud), "board value $"+val);
console.log("  OPTIMAL feasible subset under $65 (knapsack over Win-at prices): see below");
// brute force
const items = s.enrichedPlayers.map(p=>({n:p.name, c:p.myWinningBid, v:p.preDraft}));
let best={v:-1};
for(let m=0;m<(1<<items.length);m++){
  let c=0,v=0,k=0,ns=[];
  for(let i=0;i<items.length;i++) if(m&(1<<i)){c+=items[i].c;v+=items[i].v;k++;ns.push(items[i].n);}
  if(c<=65 && v>best.v) best={v,c,ns,k};
}
console.log("  BRUTE-FORCE OPTIMUM:", best.ns, "cost $"+best.c, "board value $"+best.v);
console.log("  SHORTFALL:", best.v - val, "board dollars left on the table");
