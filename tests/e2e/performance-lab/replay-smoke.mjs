import { fullReplayBytes } from "./replay-envelope.mjs";
// Private semantic checks only. No screenshots, traces, row text or timing claims.
import { createHash } from "node:crypto";
import { createRequire } from "node:module";
import { pathToFileURL } from "node:url";
import fs from "node:fs";
import path from "node:path";
import http from "node:http";
import { gunzipSync } from "node:zlib";
import { buildRows } from "../../../frontend/lib/dynasty-data.js";
import { searchTradeAssets, isTradeableBoardRow } from "../../../frontend/lib/trade-logic.js";
const hash = (value) => createHash("sha256").update(value).digest("hex");
const fail = () => { throw new Error("private_replay_parity_failed"); };
const transports = ["next-proxy", "direct-gzip"];
const viewports = { mobile: { width: 390, height: 844 }, desktop: { width: 1366, height: 900 } };
export function casePlan() {
  return transports.flatMap((transport) => Object.keys(viewports).flatMap((viewport) => ["/rankings", "/trade"].flatMap((route) => ["full", "prepared"].map((variant) => ({ transport, viewport, route, variant })))));
}
export function validateControl(actual, requested) {
  if (actual?.privateReplay !== true || ![3081, 3084].includes(requested.frontendPort) || !transports.includes(requested.transport) || !["full", "prepared"].includes(requested.variant)) fail();
  for (const key of ["variant", "transport", "frontendPort"]) if (actual[key] !== requested[key]) fail();
  return true;
}
const failureStages = new Set(["control", "manifest", "wire", "context", "response", "materialization", "render", "export", "filter", "popup", "aggregate"]);
export function safeFailure(_error, stage) {
  return { errorType: "semantic_failure", ...(failureStages.has(stage) ? { failureStage: stage } : {}) };
}
export function safeRenderObservation(check, observation) {
  const checks = new Set(["stream-settled", "initial-row", "initial-fixed", "resize-fixed", "resize-widths", "trade-selection"]);
  const result = checks.has(check) ? { renderCheck: check } : {};
  for (const field of ["rows", "pageErrors"]) {
    const value = observation?.[field];
    if (Number.isInteger(value) && value >= 0 && value <= 20000) result[field] = value;
  }
  if (Number.isFinite(observation?.tableWidth) && observation.tableWidth >= 0 && observation.tableWidth <= 10000000) result.tableWidth = observation.tableWidth;
  if (Array.isArray(observation?.widths) && observation.widths.length <= 64 && observation.widths.every((n) => Number.isFinite(n) && n >= 0 && n <= 10000000)) result.widths = observation.widths;
  return result;
}
export function selectedCells(diagnosticCell) {
  if (diagnosticCell === undefined || diagnosticCell === null) return casePlan();
  if (!/^(?:[0-9]|1[0-5])$/.test(String(diagnosticCell))) fail();
  return [casePlan()[Number(diagnosticCell)]];
}
export function finalDisposition(cases, diagnosticCell) {
  if (diagnosticCell === undefined || diagnosticCell === null) return aggregateParity(cases);
  const requested = selectedCells(diagnosticCell);
  if (cases.length !== 1 || key(cases[0]) !== key(requested[0]) || cases[0].passed !== true) fail();
  return { passed: false, diagnosticOnly: true, diagnosticPassed: true, cases: 1 };
}
const key = (cell) => [cell.transport, cell.viewport, cell.route, cell.variant].join("|");
export function sourceBreakdownDigest(rows, identityDigest) {
  if (!/^[a-f0-9]{64}$/.test(identityDigest) || !Array.isArray(rows) || rows.length < 1 || rows.length > 64) fail();
  const keys = new Set();
  for (const row of rows) {
    if (!Array.isArray(row) || row.length !== 3 || typeof row[0] !== "string" || !row[0] || row[0].length > 128 || keys.has(row[0]) || typeof row[1] !== "string" || !row[1] || row[1].length > 512 || typeof row[2] !== "string" || row[2].length > 1024) fail();
    keys.add(row[0]);
  }
  return { count: rows.length, digest: hash(JSON.stringify(rows)), identityDigest };
}
export function aggregateParity(cases) {
  const plan = casePlan();
  if (!Array.isArray(cases) || cases.length !== plan.length || new Set(cases.map(key)).size !== plan.length) fail();
  const digest = (item) => item && Number.isInteger(item.count) && item.count > 0 && /^[a-f0-9]{64}$/.test(item.digest);
  const csv = (item) => item && Number.isInteger(item.lines) && item.lines > 1 && /^[a-f0-9]{64}$/.test(item.sha256);
  for (const cell of plan) {
    const current = cases.find((item) => key(item) === key(cell));
    if (!current?.passed || !digest(current.universe) || !csv(current.initial) || !digest(current.popup) || !/^[a-f0-9]{64}$/.test(current.popup.identityDigest)) fail();
    if (cell.route === "/rankings" && !csv(current.filtered)) fail();
    if (cell.variant !== "prepared") continue;
    const baseline = cases.find((item) => key(item) === key({ ...cell, variant: "full" }));
    for (const field of ["universe", "initial", "popup", ...(cell.route === "/rankings" ? ["filtered"] : [])]) if (JSON.stringify(current[field]) !== JSON.stringify(baseline[field])) fail();
    if (cell.route === "/rankings") {
      const a = current.geometry, b = baseline.geometry;
      if (!a || !b || a.widths.length !== b.widths.length || !a.widths.length) fail();
      if (![...a.widths, ...b.widths, a.tableWidth, b.tableWidth].every((n) => Number.isFinite(n) && n >= 0)) fail();
      if (a.widths.some((n, index) => Math.abs(n - b.widths[index]) > 1) || Math.abs(a.tableWidth - b.tableWidth) > 1) fail();
    }
  }
  return { passed: true, cases: cases.length };
}
export function consumerUniverse(payload, route) {
  const rows = buildRows(payload);
  if (!rows.length) fail();
  const eligible = route === "/trade" ? rows.filter(isTradeableBoardRow) : rows;
  if (!eligible.length) fail();
  if (route === "/trade") for (const row of eligible) {
    if (!searchTradeAssets(rows, row.name, new Set(), rows.length).some((candidate) => candidate === row)) fail();
  }
  // Actual materialized consumer fields, not raw payload aliases. Compare every
  // eligible asset including those not selected in the bounded UI interaction.
  const identities = eligible.map((row) => [
    row.name, row.playerId ?? null, row.assetClass ?? null, row.pos ?? null,
    row.team ?? null, row.values?.raw ?? null, row.values?.full ?? null,
    row.rankDerivedValue ?? null, row.canonicalConsensusRank ?? null,
    row.blendedSourceRank ?? null,
  ]);
  return { rows, eligible, summary: { count: eligible.length, digest: hash(JSON.stringify(identities)) } };
}
export function validateRepresentation(wire, expectedRaw, expectedGzip, transport) {
  if (wire.status !== 200 || !transports.includes(transport) || !gunzipSync(expectedGzip).equals(expectedRaw)) fail();
  if (transport === "direct-gzip") {
    if (wire.encoding !== "gzip" || !wire.body.equals(expectedGzip)) fail();
  } else if (wire.encoding !== null || !wire.body.equals(expectedRaw)) fail();
  return true;
}
async function wireBytes(url) {
  return new Promise((resolve, reject) => {
    const request = http.get(url, { headers: { cookie: "jason_session=lab-only", "accept-encoding": "gzip" }, timeout: 20000 }, (response) => {
      const chunks = []; let bytes = 0;
      response.on("data", (chunk) => { bytes += chunk.length; if (bytes > 20000000) response.destroy(new Error("bounded_response")); else chunks.push(chunk); });
      response.on("error", reject);
      response.on("end", () => resolve({ status: response.statusCode, encoding: response.headers["content-encoding"] || null, body: Buffer.concat(chunks) }));
    });
    request.on("error", reject); request.on("timeout", () => request.destroy(new Error("bounded_timeout")));
  });
}
async function csv(page, button, expect) {
  const pending = page.waitForEvent("download");
  await page.getByRole("button", { name: button, exact: true }).click();
  const download = await pending;
  try {
    const stream = await download.createReadStream(); if (!stream) fail();
    const chunks = []; for await (const chunk of stream) chunks.push(chunk);
    const bytes = Buffer.concat(chunks); expect(bytes.length).toBeGreaterThan(0);
    return { sha256: hash(bytes), lines: bytes.toString("utf8").split("\n").length };
  } finally { await download.delete(); }
}
async function geometry(page) {
  return page.locator(".ds-table").first().evaluate((table) => ({ widths: [...table.querySelectorAll("thead th")].map((th) => th.getBoundingClientRect().width), tableWidth: table.getBoundingClientRect().width }));
}
export async function main() {
  const require = createRequire(import.meta.url);
  const { chromium } = await import("playwright");
  const { expect } = require("@playwright/test");
  const { SEL, awaitStreamSettled } = require("../helpers/journey.js");
  const origin = "http://127.0.0.1:3082";
  const output = path.resolve(process.env.PERF_LAB_OUTPUT || "data/private_serving/lab/replay-semantic");
  const replay = path.resolve(process.env.PERF_LAB_REPLAY || "");
  if (![output, replay].every((p) => p.split(path.sep).includes("private_serving"))) fail();
  const manifest = JSON.parse(fs.readFileSync(path.join(replay, "replay.json"), "utf8"));
  if (typeof manifest.playerIndexFile !== "string" || path.basename(manifest.playerIndexFile) !== manifest.playerIndexFile) fail();
  const indexBytes = fs.readFileSync(path.join(replay, manifest.playerIndexFile));
  const playerIndex = JSON.parse(indexBytes);
  const frontendPort = Number(process.env.PERF_LAB_FRONTEND_PORT || 3081);
  const report = { scope: "Private same-build full/prepared semantic parity; two explicit transports; no timing acceptance", cases: [], passed: false };
  report.playerIndexSha256 = hash(indexBytes);
  let browser, failureStage = "manifest", renderCheck;
  const diagnosticCell = process.env.PERF_LAB_DIAGNOSTIC_CELL;
  report.diagnosticOnly = diagnosticCell !== undefined;
  try {
    browser = await chromium.launch({ executablePath: process.env.PW_CHROMIUM_PATH || undefined });
    for (const cell of selectedCells(diagnosticCell)) {
      report.failedCell = { ...cell }; renderCheck = undefined;
      const requested = { variant: cell.variant, transport: cell.transport, frontendPort };
      failureStage = "control";
      const control = await fetch(`${origin}/__lab/control?${new URLSearchParams({ ...requested, detailDelay: 0 })}`);
      if (!control.ok) fail(); validateControl(await control.json(), requested);
      const endpoint = cell.route === "/rankings" ? "/api/read-models/rankings" : "/api/read-models/trade/context";
      failureStage = "manifest";
      const view = manifest.views[cell.variant === "full" ? "array" : cell.route === "/rankings" ? "rankings" : "trade"];
      if (!view || ![view.file, view.gzipFile].every((f) => typeof f === "string" && path.basename(f) === f)) fail();
      const sourceRaw = fs.readFileSync(path.join(replay, view.file));
      const sourceGzip = fs.readFileSync(path.join(replay, view.gzipFile));
      if (hash(sourceRaw) !== view.sha256 || !gunzipSync(sourceGzip).equals(sourceRaw)) fail();
      const preparedView = manifest.views[cell.route === "/rankings" ? "rankings" : "trade"];
      if (!preparedView || path.basename(preparedView.file) !== preparedView.file) fail();
      const preparedRaw = fs.readFileSync(path.join(replay, preparedView.file));
      if (hash(preparedRaw) !== preparedView.sha256) fail();
      const fullShape = cell.variant === "full" ? fullReplayBytes(sourceRaw, sourceGzip, manifest.generation, playerIndex, JSON.parse(preparedRaw)) : null;
      const expectedRaw = fullShape?.raw || sourceRaw;
      const expectedGzip = fullShape?.gzip || sourceGzip;
      failureStage = "wire";
      const wire = await wireBytes(`${origin}${endpoint}`);
      validateRepresentation(wire, expectedRaw, expectedGzip, cell.transport);
      failureStage = "context";
      const context = await browser.newContext({ viewport: viewports[cell.viewport], acceptDownloads: true });
      let page, errors = 0, forbidden = 0;
      try {
        await context.request.post(`${origin}/api/test/create-session`);
        page = await context.newPage();
        page.on("pageerror", () => errors++);
        page.on("request", (req) => { if (/^\/api\/(data|dynasty-data)$/.test(new URL(req.url()).pathname)) forbidden++; });
        const cdp = await context.newCDPSession(page); await cdp.send("Network.enable"); await cdp.send("Network.setBlockedURLs", { urls: ["https://*"] });
        failureStage = "response";
        const responsePromise = page.waitForResponse((res) => new URL(res.url()).pathname === endpoint && res.status() === 200);
        await page.goto(`${origin}${cell.route}`);
        const response = await responsePromise;
        const decoded = await response.body(); if (!decoded.equals(expectedRaw)) fail();
        failureStage = "materialization";
        const universe = consumerUniverse(JSON.parse(decoded), cell.route);
        failureStage = "render";
        renderCheck = "stream-settled";
        await awaitStreamSettled(page);
        let initial, filtered, initialGeometry, sourceColumns, popupIdentity;
        if (cell.route === "/rankings") {
          renderCheck = "initial-row";
          await expect(page.locator(SEL.boardRow).first()).toBeVisible({ timeout: 20000 });
          const showAll = page.getByRole("button", { name: /^Show all/ }); if (await showAll.count()) await showAll.click();
          renderCheck = failureStage === "render" && renderCheck === "resize-fixed" ? "resize-fixed" : "initial-fixed";
          await expect(page.locator(".ds-table").first()).toHaveCSS("table-layout", "fixed");
          failureStage = "export";
          initial = await csv(page, "Export CSV", expect); expect(initial.lines).toBeGreaterThan(500);
          initialGeometry = await geometry(page);
          await page.getByRole("button", { name: /^Columns/ }).click();
          await page.getByRole("checkbox", { name: "Show source columns", exact: true }).check();
          await page.getByRole("button", { name: /^Columns/ }).click();
          sourceColumns = await page.locator(".ds-table thead th").count();
          expect(await csv(page, "Export CSV", expect)).toEqual(initial);
          failureStage = "render";
          const expandedGeometry = await geometry(page);
          await page.setViewportSize(viewports[cell.viewport === "mobile" ? "desktop" : "mobile"]);
          await page.setViewportSize(viewports[cell.viewport]); renderCheck = "resize-fixed";
          renderCheck = failureStage === "render" && renderCheck === "resize-fixed" ? "resize-fixed" : "initial-fixed";
          await expect(page.locator(".ds-table").first()).toHaveCSS("table-layout", "fixed");
          renderCheck = "resize-widths";
          await expect.poll(async () => (await geometry(page)).widths.every((width, index) => Math.abs(width - expandedGeometry.widths[index]) <= 1)).toBe(true);
          failureStage = "filter";
          await page.getByRole("combobox", { name: "Position filter", exact: true }).selectOption("QB");
          filtered = await csv(page, "Export CSV", expect); expect(filtered.lines).toBeLessThan(initial.lines);
          failureStage = "popup";
          await page.locator(SEL.boardRow).first().locator("td").first().click();
          if (cell.viewport === "mobile") await expect(page.locator(".rankings-mobile-source-row")).toBeVisible();
          const popupName = (await page.locator(SEL.playerName).first().innerText()).trim();
          const matches = universe.rows.filter((row) => row.name === popupName);
          if (matches.length !== 1) fail();
          popupIdentity = hash(JSON.stringify([matches[0].name, matches[0].playerId, matches[0].pos, matches[0].assetClass]));
          await page.locator(SEL.playerName).first().click();
        } else {
          renderCheck = "trade-selection";
          const players = universe.eligible.filter((row) => row.assetClass !== "pick"); if (players.length < 2) fail();
          const selected = [players[0], players.at(-1)];
          for (const [index, row] of selected.entries()) {
            const input = page.locator(".trade-side-search-input").nth(index);
            await input.fill(row.name);
            await page.locator(".trade-side-search-result").filter({ has: page.getByText(row.name, { exact: true }) }).first().click();
            const remove = page.getByRole("button", { name: `Remove ${row.name} from Side ${index === 0 ? "A" : "B"}`, exact: true });
            await expect(remove).toBeVisible();
            if (index === 1) { await remove.click(); await expect(remove).toHaveCount(0); await input.fill(row.name); await page.locator(".trade-side-search-result").filter({ has: page.getByText(row.name, { exact: true }) }).first().click(); }
          }
          failureStage = "export";
          initial = await csv(page, "CSV", expect);
          failureStage = "popup";
          popupIdentity = hash(JSON.stringify([selected[0].name, selected[0].playerId, selected[0].pos, selected[0].assetClass]));
          await page.getByRole("button", { name: selected[0].name, exact: true }).first().click();
        }
        await expect(page.getByRole("dialog").getByText("Source Breakdown", { exact: true })).toBeVisible();
        const sourceRows = await page.getByRole("dialog").getByText("Source Breakdown", { exact: true }).locator("..").evaluate((section) => [...section.querySelectorAll('[class*="sourceRow"]')].map((row) => {
          const label = row.querySelector('[class*="sourceLabel"]');
          const value = row.querySelector('[class*="sourceValue"]');
          return [label?.getAttribute("title") || "", value?.textContent?.trim() || "", value?.getAttribute("title") || ""];
        }));
        const popup = sourceBreakdownDigest(sourceRows, popupIdentity);
        if (errors || forbidden) fail();
        report.cases.push({ ...cell, frontendPort, passed: true, universe: universe.summary, canonicalRows: JSON.parse(decoded).playersArray.length, initial, ...(filtered ? { filtered, geometry: initialGeometry, sourceColumns } : {}), popup, popupScope: "complete-rendered-source-breakdown", popupSourceVisible: true, pageErrors: errors, forbiddenGlobalReads: forbidden, wire: { encoding: wire.encoding, bytes: wire.body.length, sha256: hash(wire.body), scope: cell.variant === "full" ? (cell.transport === "direct-gzip" ? "lab-derived-gzip" : "lab-derived-next-decoded") : (cell.transport === "direct-gzip" ? "producer-gzip" : "next-decoded") }, decoded: { bytes: decoded.length, sha256: hash(decoded) }, source: { rawSha256: hash(sourceRaw), gzipSha256: hash(sourceGzip), rows: JSON.parse(sourceRaw).playersArray.length }, envelope: cell.variant === "full" ? "lab-derived-full-envelope-and-identity" : "producer-prepared" });
      } catch (error) {
        if (failureStage === "render") {
          let observation = { pageErrors: errors };
          if (page && !page.isClosed()) {
            try {
              const numeric = await page.evaluate(() => {
                const table = document.querySelector(".ds-table");
                return { rows: document.querySelectorAll(".ds-table tbody tr").length, tableWidth: table?.getBoundingClientRect().width, widths: table ? [...table.querySelectorAll("thead th")].slice(0, 64).map((th) => th.getBoundingClientRect().width) : [] };
              });
              observation = { ...numeric, pageErrors: errors };
            } catch { /* Missing observation stays absent. */ }
          }
          report.renderObservation = safeRenderObservation(renderCheck, observation);
        }
        throw error;
      } finally { await context.close(); }
    }
    failureStage = "aggregate";
    const disposition = finalDisposition(report.cases, diagnosticCell);
    report.passed = disposition.passed;
    if (disposition.diagnosticOnly) report.diagnosticPassed = disposition.diagnosticPassed;
    delete report.failedCell;
  } catch { Object.assign(report, safeFailure(null, failureStage)); process.exitCode = 1; }
  finally {
    if (browser) await browser.close();
    fs.mkdirSync(output, { recursive: true });
    fs.writeFileSync(path.join(output, "private-replay-correctness.json"), JSON.stringify(report, null, 2));
    console.log(JSON.stringify({ passed: report.passed, cases: report.cases.length, ...(report.errorType ? safeFailure() : {}) }));
  }
}
if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  main().catch(() => { console.log(JSON.stringify(safeFailure())); process.exitCode = 1; });
}
