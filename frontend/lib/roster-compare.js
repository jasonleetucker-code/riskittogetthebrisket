/**
 * roster-compare — pure helpers for the franchise-page comparison panel.
 *
 * Kept in lib (not the JSX component) so the totals math can be unit-
 * tested without rendering React.  Bucket assignment matches the
 * backend's family map in src/trade/waiver.py — a single source of
 * truth for "which positions roll up to which family."
 */

export const POSITION_FAMILIES = Object.freeze([
  { key: "QB", label: "QB", positions: ["QB"] },
  { key: "RB", label: "RB", positions: ["RB", "FB"] },
  { key: "WR", label: "WR", positions: ["WR"] },
  { key: "TE", label: "TE", positions: ["TE"] },
  { key: "DL", label: "DL", positions: ["DL", "DT", "DE", "EDGE", "NT"] },
  { key: "LB", label: "LB", positions: ["LB", "ILB", "OLB", "MLB"] },
  { key: "DB", label: "DB", positions: ["DB", "CB", "S", "FS", "SS"] },
]);

export function familyForPos(pos) {
  const p = String(pos || "").toUpperCase();
  for (const f of POSITION_FAMILIES) {
    if (f.positions.includes(p)) return f.key;
  }
  return null;
}

export function buildValueIndex(rows) {
  const ix = new Map();
  for (const r of rows || []) {
    const name = String(r?.name || "").toLowerCase();
    if (!name) continue;
    const value = Number(r?.rankDerivedValue || r?.values?.full || 0);
    const pos = String(r?.pos || "").toUpperCase();
    ix.set(name, { value: Number.isFinite(value) ? value : 0, pos });
  }
  return ix;
}

export function totalsByFamily(playerNames, valueIndex) {
  const totals = Object.fromEntries(
    POSITION_FAMILIES.map((f) => [f.key, { total: 0, count: 0 }]),
  );
  for (const name of playerNames || []) {
    const entry = valueIndex.get(String(name).toLowerCase());
    if (!entry) continue;
    const fam = familyForPos(entry.pos);
    if (!fam) continue;
    totals[fam].total += entry.value;
    totals[fam].count += 1;
  }
  return totals;
}

export function grandTotal(byFamily) {
  let sum = 0;
  for (const fam of Object.values(byFamily || {})) {
    sum += fam?.total || 0;
  }
  return sum;
}
