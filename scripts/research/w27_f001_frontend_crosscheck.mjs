// W27-F001 research cross-check: run the REAL frontend edge helpers over the
// pinned research fixture and print what each surface would show.
//
// Research only: imports the production modules read-only and writes nothing.
// Usage:  node scripts/research/w27_f001_frontend_crosscheck.mjs [fixture.json]
//
// The Python harness (w27_f001_idp_edge_benchmark.py) transcribes
// idpMarketAction / marketActionDisclosed; this script is the ground truth it
// is compared against (tests/scripts/test_w27_f001_idp_edge_benchmark.py).
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const repo = resolve(here, "..", "..");
const fixturePath =
  process.argv[2] ||
  resolve(repo, "tests", "scripts", "fixtures", "w27_f001_idp_edge_rows.json");

const helpers = await import(resolve(repo, "frontend", "lib", "display-helpers.js"));
const filters = await import(resolve(repo, "frontend", "lib", "player-filters.js"));
const thresholds = await import(resolve(repo, "frontend", "lib", "thresholds.js"));

const fixture = JSON.parse(readFileSync(fixturePath, { encoding: "utf-8" }));

// Contract row -> the fields buildRows forwards to these helpers.  Every
// non-pick row gets a rank in buildRows (backend rank, else a display
// ordinal), so `rank` is always truthy here, as it is in the browser.
function toFrontendRow(r, i) {
  return {
    name: r.displayName,
    pos: r.position,
    rank: r.canonicalConsensusRank || 10000 + i,
    assetClass: r.assetClass,
    quarantined: !!r.quarantined,
    rankDerivedValue: r.rankDerivedValue,
    values: { full: r.rankDerivedValue },
    ktcMarket: r.ktcMarket ?? null,
    marketGapDirection: String(r.marketGapDirection || "none"),
    marketGapValueRatio: r.marketGapValueRatio ?? null,
    sourceRanks: r.sourceRanks || {},
    effectiveSourceRanks: r.effectiveSourceRanks || {},
    sourceRankMeta: r.sourceRankMeta || {},
  };
}

// Verbatim copy of frontend/app/edge/page.jsx::idpGapOf (not exported there).
function idpGapOf(action) {
  const m = action.title?.match(/~(\d+) ordinal/);
  return m ? Number(m[1]) : 0;
}

const rows = fixture.idpRows.map(toFrontendRow);
// useDynastyData hands /edge rows in board order (rankDerivedValue desc); the
// fixture is already sorted that way by the extractor.
const perRow = {};
for (const row of rows) {
  const action = helpers.idpMarketAction(row);
  perRow[row.name] = {
    idpMarketAction: action.label,
    idpMarketKind: action.kind,
    rankingsEdge: helpers.marketActionDisclosed(row).label,
    filterBuy: filters.rowMatches(row, { edge: "buy" }),
    filterSell: filters.rowMatches(row, { edge: "sell" }),
    inIdpPanelPopulation: helpers.isIdpInTopByIdptc(row, 200),
    idpGapParsed: idpGapOf(action),
    title: action.title,
  };
}

// The two /edge IDP panels, reproduced with the page's own steps.
const eligible = rows.filter(helpers.isEligibleForAnalysis);
const idpEligible = eligible.filter((r) => helpers.isIdpInTopByIdptc(r, 200));
function panel(kind) {
  return idpEligible
    .map((r) => ({ row: r, action: helpers.idpMarketAction(r) }))
    .filter(({ action }) => action.kind === kind)
    .map(({ row, action }) => ({ name: row.name, gap: idpGapOf(action), title: action.title }))
    .sort((a, b) => b.gap - a.gap)
    .slice(0, thresholds.EDGE_PREMIUM_LIMIT);
}

const counts = (key) =>
  Object.values(perRow).reduce((acc, v) => {
    acc[v[key]] = (acc[v[key]] || 0) + 1;
    return acc;
  }, {});

const out = {
  rows: rows.length,
  idpMarketAction: counts("idpMarketAction"),
  rankingsEdge: counts("rankingsEdge"),
  filterBuyMatches: Object.values(perRow).filter((v) => v.filterBuy).length,
  filterSellMatches: Object.values(perRow).filter((v) => v.filterSell).length,
  titlesContainingOrdinal: Object.values(perRow).filter((v) => /ordinal/.test(v.title || "")).length,
  rowsWithNonZeroParsedGap: Object.values(perRow).filter((v) => v.idpGapParsed !== 0).length,
  sellPanel: panel("sell"),
  buyPanel: panel("buy"),
  perRow,
};
process.stdout.write(JSON.stringify(out, null, 1) + "\n");
