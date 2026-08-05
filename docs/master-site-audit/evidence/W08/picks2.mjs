import fs from "node:fs";
import { buildRows } from "/home/user/riskittogetthebrisket/frontend/lib/dynasty-data.js";
import { resolvePickRow } from "/home/user/riskittogetthebrisket/frontend/lib/trade-logic.js";
const data = JSON.parse(fs.readFileSync(new URL("./contract.json", import.meta.url).pathname,"utf8"));
const rows = buildRows(data);                     // REAL row objects
const lookup = new Map(rows.map(r=>[r.name.toLowerCase(), r]));
const aliases = data.pickAliases;

const gen = rows.find(r=>r.name==="2026 Mid 1st");
console.log("row '2026 Mid 1st':", JSON.stringify({
  name:gen.name, full:gen.values.full, raw:gen.values.raw,
  pickGenericSuppressed: gen.pickGenericSuppressed,
  rawNested: gen.raw?.pickGenericSuppressed,
  hasKey: Object.prototype.hasOwnProperty.call(gen,'pickGenericSuppressed')
}));
console.log("legacy dict '2026 Mid 1st' pickGenericSuppressed =", data.players["2026 Mid 1st"].pickGenericSuppressed);

const cases = ["2026 1st","2026 2nd","2026 3rd","2026 Mid 1st","2026 1.06","2027 1st","2027 Mid 1st"];
for (const c of cases) {
  const r = resolvePickRow(c, lookup, aliases);
  console.log(`resolvePickRow(${JSON.stringify(c)}) -> ${r?r.name:"null"}  value=${r?r.values.full:"-"}`);
}

// League-wide: how many roster picks resolve to a 0-value row?
let zero=0, tot=0, byTeam={};
for (const t of data.sleeper.teams){
  let z=0;
  for (const label of t.picks||[]) {
    tot++;
    const r = resolvePickRow(label, lookup, aliases);
    if (!r || !(r.values.full>0)) { zero++; z++; }
  }
  byTeam[t.name]=z+"/"+ (t.picks||[]).length;
}
console.log("league roster picks resolving to value 0:", zero, "of", tot, JSON.stringify(byTeam));
