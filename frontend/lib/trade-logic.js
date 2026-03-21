/**
 * Pure trade calculator logic — extracted from app/trade/page.jsx
 * for testability. No React dependencies.
 */

export const VALUE_MODES = [
  { key: "full", label: "Fully Adjusted" },
  { key: "raw", label: "Raw" },
  { key: "scoring", label: "Scoring" },
  { key: "scarcity", label: "Scarcity" },
];

export const STORAGE_KEY = "next_trade_workspace_v1";
export const RECENT_KEY = "next_trade_recent_assets_v1";

export function verdictFromGap(gap) {
  const abs = Math.abs(gap);
  if (abs < 200) return "Near even";
  if (abs < 600) return "Lean";
  if (abs < 1200) return "Strong lean";
  return "Major gap";
}

export function colorFromGap(gap) {
  if (Math.abs(gap) < 200) return "";
  return gap > 0 ? "green" : "red";
}

export function sideTotal(side, valueMode) {
  return side.reduce((sum, r) => sum + Number(r.values?.[valueMode] || 0), 0);
}

export function tradeGap(sideA, sideB, valueMode) {
  return sideTotal(sideA, valueMode) - sideTotal(sideB, valueMode);
}

export function addAssetToSide(side, row) {
  if (!row) return side;
  if (side.some((r) => r.name === row.name)) return side;
  return [...side, row];
}

export function removeAssetFromSide(side, name) {
  return side.filter((r) => r.name !== name);
}

export function isAssetInTrade(sideA, sideB, name) {
  return sideA.some((r) => r.name === name) || sideB.some((r) => r.name === name);
}

export function serializeWorkspace(sideA, sideB, valueMode, activeSide) {
  return {
    valueMode,
    activeSide,
    sideA: sideA.map((r) => r.name),
    sideB: sideB.map((r) => r.name),
  };
}

export function deserializeWorkspace(parsed, rowByName) {
  if (!parsed || typeof parsed !== "object") return null;
  const valueMode = VALUE_MODES.some((m) => m.key === parsed.valueMode)
    ? parsed.valueMode
    : "full";
  const activeSide = parsed.activeSide === "B" ? "B" : "A";
  const sideA = Array.isArray(parsed.sideA)
    ? parsed.sideA.map((n) => rowByName.get(n)).filter(Boolean)
    : [];
  const sideB = Array.isArray(parsed.sideB)
    ? parsed.sideB.map((n) => rowByName.get(n)).filter(Boolean)
    : [];
  return { valueMode, activeSide, sideA, sideB };
}

export function addRecent(recentNames, name) {
  return [name, ...recentNames.filter((x) => x !== name)].slice(0, 20);
}

export function filterPickerRows(rows, sideA, sideB, query, filter) {
  const inTrade = new Set([...sideA, ...sideB].map((r) => r.name));
  const q = query.trim().toLowerCase();
  let list = rows.filter((r) => !inTrade.has(r.name));
  if (filter !== "all") list = list.filter((r) => r.assetClass === filter);
  if (q) list = list.filter((r) => r.name.toLowerCase().includes(q));
  return list.slice(0, 80);
}
