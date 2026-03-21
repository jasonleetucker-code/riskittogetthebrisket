import { buildRows, getSiteKeys } from "./dynasty-data";
import { loadDynastySource } from "./dynasty-source";

function safeDateLabel(data) {
  return String(data?.scrapeTimestamp || data?.date || data?.generatedAt || "").trim() || "n/a";
}

function summarizeRows(rows) {
  let offense = 0;
  let idp = 0;
  let picks = 0;
  for (const row of rows) {
    const pos = String(row?.pos || "").toUpperCase();
    if (["QB", "RB", "WR", "TE"].includes(pos)) offense += 1;
    else if (["DL", "LB", "DB"].includes(pos)) idp += 1;
    else if (pos === "PICK") picks += 1;
  }
  return {
    total: rows.length,
    offense,
    idp,
    picks,
  };
}

export async function getDynastyFrontendData() {
  const sourceResult = await loadDynastySource();
  if (!sourceResult?.ok || !sourceResult.data) {
    return {
      ok: false,
      error: sourceResult?.error || "Failed to load dynasty source data.",
      source: sourceResult?.source || null,
      diagnostics: sourceResult?.diagnostics || null,
      rows: [],
      siteKeys: [],
      summary: { total: 0, offense: 0, idp: 0, picks: 0 },
      scrapeTimestamp: null,
      generatedAt: new Date().toISOString(),
    };
  }

  const rows = buildRows(sourceResult.data, { includeRaw: false });
  return {
    ok: true,
    source: sourceResult.source,
    diagnostics: sourceResult?.diagnostics || null,
    rawData: sourceResult.data,
    rows,
    siteKeys: getSiteKeys(sourceResult.data),
    summary: summarizeRows(rows),
    scrapeTimestamp: safeDateLabel(sourceResult.data),
    generatedAt: new Date().toISOString(),
  };
}

export async function getTradeCalculatorData() {
  const base = await getDynastyFrontendData();
  if (!base.ok) return base;

  const sleeper = base.rawData?.sleeper && typeof base.rawData.sleeper === "object" ? base.rawData.sleeper : {};
  const teams = Array.isArray(sleeper.teams) ? sleeper.teams : [];
  const trades = Array.isArray(sleeper.trades) ? sleeper.trades : [];
  const ktcIdMap = base.rawData?.ktcIdMap && typeof base.rawData.ktcIdMap === "object" ? base.rawData.ktcIdMap : {};
  return {
    ...base,
    teams,
    trades,
    ktcIdMap,
    leagueContext: {
      leagueName: String(sleeper.leagueName || "").trim() || null,
      leagueId: String(sleeper.leagueId || "").trim() || null,
    },
  };
}
