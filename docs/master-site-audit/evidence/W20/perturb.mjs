import fs from "fs";
import { analyzeLeaguePhases } from "/home/user/riskittogetthebrisket/frontend/lib/team-phase.js";
const c = JSON.parse(fs.readFileSync("contract.json","utf8"));
const base = Object.entries(c.players).map(([name,v])=>({name, rankDerivedValue: v.rankDerivedValue||0, age: v.age}));
const teamsOf = (r)=>Object.fromEntries(analyzeLeaguePhases(c,r).teams.map(t=>[t.name,t.phase.label]));
const b = teamsOf(base);
const roster = new Set((c.sleeper.teams.find(t=>t.name==="Collin").players||[]).map(s=>s.toLowerCase()));
function mut(fn){ return base.map(r=> roster.has(r.name.toLowerCase()) ? fn({...r}) : r); }
const scen = {
  "base": base,
  "Collin ages -4y": mut(r=>{ if(r.age) r.age = r.age-4; return r; }),
  "Collin ages +4y": mut(r=>{ if(r.age) r.age = r.age+4; return r; }),
  "Collin value +50%": mut(r=>{ r.rankDerivedValue = Math.round(r.rankDerivedValue*1.5); return r; }),
  "Collin value -50%": mut(r=>{ r.rankDerivedValue = Math.round(r.rankDerivedValue*0.5); return r; }),
  "Collin value x10": mut(r=>{ r.rankDerivedValue = Math.round(r.rankDerivedValue*10); return r; }),
};
for (const [k,rows] of Object.entries(scen)) {
  const t = teamsOf(rows);
  const diff = Object.keys(b).filter(n=>b[n]!==t[n]).map(n=>`${n}:${b[n]}->${t[n]}`);
  console.log(k.padEnd(20), "Collin="+t["Collin"].padEnd(10), "changed:", diff.join(", ")||"(none)");
}
