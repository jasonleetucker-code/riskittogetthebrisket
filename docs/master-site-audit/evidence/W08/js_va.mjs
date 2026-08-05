import fs from "node:fs";
import { ktcAdjustPackage } from "/home/user/riskittogetthebrisket/frontend/lib/trade-logic.js";
const fx = JSON.parse(fs.readFileSync("/home/user/riskittogetthebrisket/scripts/ktc_va_observations.json","utf8"));
const out = fx.observations.map((o,i)=>{
  const r = ktcAdjustPackage(o.team1Values||[], o.team2Values||[]);
  return {i, value:r.displayed?r.value:0, side:r.displayed?r.side:0};
});
fs.writeFileSync("js_va.json", JSON.stringify(out));
console.log("js results:", out.length);
