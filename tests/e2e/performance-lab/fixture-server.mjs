import http from "node:http";
import { gzipSync } from "node:zlib";
import { createHash } from "node:crypto";
import fs from "node:fs";
import path from "node:path";
const output = path.resolve(process.env.PERF_LAB_OUTPUT || "output/playwright");
fs.mkdirSync(output, { recursive: true });

// Local integration fixture only: every identity/value is synthetic. It tests
// client behavior and transport mechanics, never real board quality or latency.
const sources = ["ktcCrowdTradesSfTep", "fantasyCalc"];
let rows = Array.from({ length: 120 }, (_, i) => {
  const position = ["QB", "RB", "WR", "TE", "LB"][i % 5];
  const value = 9800 - i * 60;
  return {
    readModelKey: createHash("sha256").update(`lab-${i}`).digest("hex"), playerId: null,
    displayName: `Lab Player ${String(i + 1).padStart(3, "0")}`, canonicalName: `Lab Player ${String(i + 1).padStart(3, "0")}`,
    position, team: ["KC", "BUF", "DET"][i % 3], age: 22 + i % 8, rookie: i % 9 === 0, yearsExp: i % 8,
    assetClass: position === "LB" ? "idp" : "offense", canonicalConsensusRank: i + 1, canonicalTierId: Math.floor(i / 20) + 1,
    rankDerivedValue: value, displayValue: value, rawComposite: value, sourceCount: 2,
    canonicalSiteValues: Object.fromEntries(sources.map((key) => [key, value])),
    sourceRanks: Object.fromEntries(sources.map((key) => [key, i + 1])),
    effectiveSourceRanks: Object.fromEntries(sources.map((key) => [key, i + 1])),
    sourceRankMeta: Object.fromEntries(sources.map((key) => [key, { valueContribution: value, appliedWeight: 1, effectiveWeight: 1, method: "lab_fixture", sourceScope: "overall", diagnostic: `synthetic audit for row ${i} `.repeat(10) }])),
    sourceAudit: { reason: "fully_matched", expectedSources: sources, matchedSources: sources, unmatchedSources: [], matchedDetails: {}, diagnostic: `synthetic identity explanation ${i} `.repeat(20) },
    confidenceBucket: "high", confidenceLabel: "Lab fixture", marketBreadthAgreementIndex: 0.9,
    rankChange: 1, rankHistory: [{ date: "2026-09-01", rank: i + 2 }, { date: "2026-09-09", rank: i + 1 }],
    pickDetails: null, hillValueSpread: 2, marketDispersionCV: 0.1,
  };
});
let generation = "lab-generation-a";
const sleeper = { teams: [{ owner_id: "lab-owner-a", name: "Lab Team A", players: rows.slice(0, 10).map((r) => r.displayName), roster_id: 1 }, { owner_id: "lab-owner-b", name: "Lab Team B", players: rows.slice(10, 20).map((r) => r.displayName), roster_id: 2 }], league: { season: "2026", settings: { teams: 12 }, roster_positions: ["QB", "RB", "WR", "TE"] } };
let canonical = { schemaVersion: 1, contractVersion: 1, date: "2026-09-10", scrapeTimestamp: "2026-09-10T18:00:00Z", playerCount: rows.length,
  meta: { readModelGeneration: generation, leagueKey: "lab", sleeperDataReady: true, payloadView: "rankings" },
  sites: sources.map((key) => ({ key })), sleeper, playersArray: rows,
  rankingsOverride: { isCustomized: false }, valuationBasis: "market", currentDraftYear: 2026, pickAliases: {},
  dataFreshness: {}, methodology: {}, hillCurves: {},
};
let prepared = structuredClone(canonical);
for (const row of prepared.playersArray) {
  for (const key of ["sourceAudit", "pickDetails", "hillValueSpread", "marketDispersionCV"]) delete row[key];
  row.sourceRankMeta = Object.fromEntries(Object.entries(row.sourceRankMeta).map(([key, meta]) => [key,
    Object.fromEntries(["valueContribution", "appliedWeight", "effectiveWeight", "method"].map((field) => [field, meta[field]])),
  ]));
}
let catalog = { ...canonical, meta: { ...canonical.meta, payloadView: "catalog" }, playersArray: rows.map((r) => Object.fromEntries(["readModelKey", "playerId", "displayName", "canonicalName", "position", "team", "assetClass", "canonicalConsensusRank", "rankDerivedValue", "displayValue"].map((key) => [key, r[key]]))) };
// Explicit private replay is local-only; reports contain counts/bytes, never rows.
const replayDirectory = process.env.PERF_LAB_REPLAY;
const serializedViews = new WeakMap();
let trade = prepared;
let playerIndex = null;
if (replayDirectory) {
  const directory = path.resolve(replayDirectory);
  if (!directory.split(path.sep).includes("private_serving")) throw new Error("Replay must remain under private_serving");
  const manifest = JSON.parse(fs.readFileSync(path.join(directory, "replay.json"), "utf8"));
  const loadView = (name) => {
    const raw = fs.readFileSync(path.join(directory, manifest.views[name].file));
    const value = JSON.parse(raw);
    const gzip = fs.readFileSync(path.join(directory, manifest.views[name].gzipFile));
    if (createHash("sha256").update(raw).digest("hex") !== manifest.views[name].sha256) throw new Error("Replay hash mismatch");
    serializedViews.set(value, { raw, gzip });
    return value;
  };
  canonical = loadView("array");
  prepared = loadView("rankings");
  trade = loadView("trade");
  catalog = loadView("catalog");
  rows = prepared.playersArray;
  generation = manifest.generation;
  playerIndex = JSON.parse(fs.readFileSync(path.join(directory, manifest.playerIndexFile), "utf8"));
}
let variant = "prepared";
// direct-gzip mirrors nginx routing /api to the backend; next-proxy exercises
// the real Next bridge, which exposes a decoded response on this local server.
let transport = process.env.PERF_LAB_TRANSPORT || "next-proxy";
let detailDelay = 0;
let frontendPort = 3081;

function send(req, res, data, status = 200, headers = {}) {
  const serialized = serializedViews.get(data);
  const raw = serialized?.raw || Buffer.from(JSON.stringify(data));
  const etag = `"${createHash("sha256").update(raw).digest("hex").slice(0, 24)}"`;
  if (req.headers["if-none-match"] === etag && status === 200) { res.writeHead(304, { etag, "Cache-Control": "private, no-cache" }); res.end(); return; }
  const body = serialized?.gzip || gzipSync(raw);
  res.writeHead(status, { "Content-Type": "application/json", "Content-Encoding": "gzip", "Content-Length": body.length, "Cache-Control": status < 400 ? "private, no-cache" : "no-store", etag, ...headers });
  res.end(body);
}

async function api(req, res) {
  const url = new URL(req.url, "http://localhost");
  const path = url.pathname;
  if (path === "/__lab/control") { variant = url.searchParams.get("variant") || variant; detailDelay = Number(url.searchParams.get("detailDelay") || 0); if (["next-proxy", "direct-gzip"].includes(url.searchParams.get("transport"))) transport = url.searchParams.get("transport"); if ([3081, 3084].includes(Number(url.searchParams.get("frontendPort")))) frontendPort = Number(url.searchParams.get("frontendPort")); return send(req, res, { variant, detailDelay, transport, frontendPort, rows: rows.length, privateReplay: Boolean(replayDirectory) }); }
  if (path === "/api/test/create-session") return send(req, res, { ok: true }, 200, { "Set-Cookie": "jason_session=lab-only; Path=/; HttpOnly; SameSite=Lax" });
  if (path === "/api/auth/status") return send(req, res, { authenticated: Boolean(req.headers.cookie?.includes("jason_session=lab-only")), features: {}, isAdmin: false });
  if (path === "/api/user/state") return send(req, res, { state: { activeLeagueKey: "lab", selectedTeam: { ownerId: "lab-owner-a", name: "Lab Team A" }, watchlist: [] } });
  if (path === "/api/leagues") return send(req, res, { leagues: [{ key: "lab", name: "Lab League", active: true, scoringProfileKey: "lab" }], defaultKey: "lab", userDefaultKey: "lab" });
  if (path === "/api/health" || path === "/api/status") return send(req, res, { has_data: true, status: "healthy", stale: false });
  if (path.startsWith("/api/read-models/")) {
    if (!req.headers.cookie?.includes("jason_session=lab-only")) return send(req, res, { error: "unauthenticated" }, 401);
    if (path.endsWith("/players/catalog")) return send(req, res, catalog);
    if (path === "/api/read-models/rankings" || path === "/api/read-models/trade/context") return send(req, res, variant === "full" ? canonical : path.includes("/trade/") ? trade : prepared);
    const key = path.split("/").at(-1);
    const row = playerIndex ? playerIndex[key] : rows.find((r) => r.readModelKey === key);
    if (!row) return send(req, res, { error: "not_found" }, 404);
    if (url.searchParams.get("generation") !== generation) return send(req, res, { error: "generation_changed" }, 409);
    if (detailDelay) await new Promise((resolve) => setTimeout(resolve, detailDelay));
    return send(req, res, { schemaVersion: 1, generation, player: { ...row, readModelKey: key }, meta: { ...prepared.meta } });
  }
  if (path === "/api/rankings/overrides") return send(req, res, { mode: "delta", meta: { readModelGeneration: generation }, rankingsDelta: { playerKey: "displayName", players: [], activePlayerIds: rows.map((r) => r.displayName) }, rankingsOverride: { isCustomized: false } });
  if (path === "/api/data" || path === "/api/dynasty-data") return send(req, res, canonical);
  if (path === "/api/news") return send(req, res, { items: [], playerDigests: [], providersUsed: [] });
  if (path === "/api/draft-capital") return send(req, res, { season: "2026", teams: [], picks: [] });
  if (path === "/api/league-comparison") return send(req, res, { meta: { version: "synthetic-lab" }, similarity: { score: 100, label: "Lab fixture" }, positions: {}, summary: {}, warnings: [] });
  if (path === "/api/telemetry/web-vitals") return send(req, res, { ok: true });
  if (path.startsWith("/api/bdvm/")) return send(req, res, { error: "bdvm_disabled", detail: "Disabled in synthetic lab" }, 503);
  if (path.startsWith("/api/")) return send(req, res, { error: "synthetic_lab_unavailable" }, 503);
  return false;
}

const backend = http.createServer(async (req, res) => { try { const result = await api(req, res); if (result === false) { res.writeHead(404); res.end(); } } catch { res.writeHead(500); res.end(); } });
const localOnly = new Set(["/api/test/create-session", "/api/user/state", "/api/health", "/__lab/control"]);
const front = http.createServer(async (req, res) => {
  const pathname = new URL(req.url, "http://localhost").pathname;
  if (localOnly.has(pathname) || (transport === "direct-gzip" && pathname.startsWith("/api/"))) return api(req, res);
  const upstream = http.request({ hostname: "127.0.0.1", port: frontendPort, path: req.url, method: req.method, headers: req.headers }, (r) => { res.writeHead(r.statusCode, r.headers); r.pipe(res); });
  upstream.on("error", () => { res.writeHead(502); res.end(); }); req.pipe(upstream);
});
backend.listen(3083, "127.0.0.1"); front.listen(3082, "127.0.0.1");
const payloadSize = (value) => {
  const serialized = serializedViews.get(value);
  const raw = serialized?.raw || Buffer.from(JSON.stringify(value));
  return { decoded: raw.length, gzip: (serialized?.gzip || gzipSync(raw)).length };
};
fs.writeFileSync(path.join(output, "fixture-payload-sizes.json"), JSON.stringify({ scope: replayDirectory ? "Private replay; counts only, no production latency" : "Synthetic fixture only; not a production payload", rows: rows.length, full: payloadSize(canonical), prepared: payloadSize(prepared), catalog: payloadSize(catalog) }, null, 2));
console.log(JSON.stringify({ ready: true, backendPort: 3083, browserPort: 3082, frontendPort: 3081, privateReplay: Boolean(replayDirectory), rows: rows.length, transport }));
