import { chromium } from "playwright";
import { createRequire } from "node:module";
import { createHash } from "node:crypto";
import fs from "node:fs";
import path from "node:path";
const output = path.resolve(process.env.PERF_LAB_OUTPUT || "output/playwright");
fs.mkdirSync(output, { recursive: true });
const require = createRequire(import.meta.url);
const { expect } = require("@playwright/test");
const { SEL, awaitStreamSettled } = require("../helpers/journey.js");
const origin = "http://127.0.0.1:3082";
const browser = await chromium.launch({ executablePath: process.env.PW_CHROMIUM_PATH || undefined, headless: true });
const report = { scope: "local production-build browser integration; synthetic 120-row fixture; no production latency claim", browser: await browser.version(), buildFlag: "NEXT_PUBLIC_PREPARED_READ_MODELS=1", cases: [], comparisons: {} };
const hash = (text) => createHash("sha256").update(text).digest("hex");
const forbidden = (paths) => paths.filter((p) => /^\/api\/(?:data|dynasty-data)$/.test(p));
const canonicalByViewport = new Map();
let currentPage;

async function open(path, viewport) {
  const context = await browser.newContext({ viewport, acceptDownloads: true });
  await context.request.post(`${origin}/api/test/create-session`);
  await context.addInitScript(() => { localStorage.setItem("next_active_league_v1", "lab"); localStorage.setItem("next_settings_v2", JSON.stringify({ selectedTeam: "Lab Team A", selectedTeamTouched: true })); });
  const page = await context.newPage(); currentPage = page;
  const paths = [], errors = [];
  page.on("request", (req) => { const url = new URL(req.url()); if (url.pathname.startsWith("/api/")) paths.push(url.pathname); });
  page.on("pageerror", (err) => errors.push(err.message));
  const cdp = await context.newCDPSession(page);
  await cdp.send("Network.enable"); await cdp.send("Network.setBlockedURLs", { urls: ["https://*"] });
  await page.goto(`${origin}${path}`, { waitUntil: "domcontentloaded" });
  return { context, page, paths, errors };
}

async function csv(page, name) {
  const pending = page.waitForEvent("download");
  pending.catch(() => {});
  await page.getByRole("button", { name, exact: true }).click();
  const download = await pending;
  const stream = await download.createReadStream();
  const chunks = []; for await (const chunk of stream) chunks.push(chunk);
  return Buffer.concat(chunks).toString("utf8");
}

async function metrics(page) {
  return page.evaluate(() => {
    const nav = performance.getEntriesByType("navigation")[0];
    const api = performance.getEntriesByType("resource").filter((r) => new URL(r.name).pathname.startsWith("/api/read-models/"));
    return { usefulObservationMs: Math.round(performance.now()), documentCount: document.querySelectorAll("html").length,
      preparedResponses: api.map((r) => ({ endpoint: new URL(r.name).pathname.replace(/\/players\/[^/]+$/, "/players/[key]"), encodedBytes: r.encodedBodySize, decodedBytes: r.decodedBodySize, transferBytes: r.transferSize, responseMs: Math.round(r.responseEnd - r.startTime) })), ttfbMs: Math.round(nav.responseStart) };
  });
}

try {
  for (const [viewportName, viewport] of [["desktop", { width: 1366, height: 900 }], ["mobile", { width: 390, height: 844 }]]) {
    for (const variant of ["full", "prepared"]) {
      await fetch(`${origin}/__lab/control?variant=${variant}&detailDelay=350`);
      const run = await open("/rankings", viewport); const { page, context, paths, errors } = run;
      await expect(page.locator(SEL.boardRow).first()).toBeVisible({ timeout: 20000 });
      await awaitStreamSettled(page);
      const initialMetrics = await metrics(page);
      const initialCsv = await csv(page, "Export CSV");
      expect(initialCsv.split("\n").length).toBeGreaterThan(50);
      expect(initialCsv.split("\n")[0]).toContain("FC,FC Rank");
      const baselineKey = `${viewportName}-rankings`;
      if (variant === "full") canonicalByViewport.set(baselineKey, initialCsv);
      else expect(initialCsv).toBe(canonicalByViewport.get(baselineKey));
      await page.getByRole("button", { name: /^Columns/ }).click();
      await page.getByRole("checkbox", { name: "Show source columns", exact: true }).check();
      await page.getByRole("button", { name: /^Columns/ }).click();
      const shownColumnCount = await page.locator(".ds-table thead th").count();
      expect(await csv(page, "Export CSV")).toBe(initialCsv);
      await page.getByRole("button", { name: /^Columns/ }).click();
      await page.getByRole("checkbox", { name: "Show source columns", exact: true }).uncheck();
      await page.getByRole("button", { name: /^Columns/ }).click();
      expect(await page.locator(".ds-table thead th").count()).toBeLessThan(shownColumnCount);
      expect(await csv(page, "Export CSV")).toBe(initialCsv);
      await page.getByRole("textbox", { name: "Search the board" }).fill("Player 00");
      await expect.poll(async () => page.locator(SEL.playerName).count()).toBe(10);
      expect(await page.locator(SEL.playerName).count()).toBeGreaterThan(0);
      const filteredCsv = await csv(page, "Export CSV");
      expect(filteredCsv.split("\n").length).toBeLessThan(initialCsv.split("\n").length);
      await page.getByRole("combobox", { name: "Position filter", exact: true }).selectOption("QB");
      await expect.poll(async () => page.locator(SEL.playerName).count()).toBe(2);
      await page.locator(SEL.boardRow).first().locator("td").first().click();
      await expect(page.getByText("Loading source details…")).toBeVisible();
      await expect(page.getByText("All expected sources matched")).toBeVisible();
      if (viewportName === "mobile") await expect(page.locator(".rankings-mobile-source-row")).toBeVisible();
      await page.locator(SEL.playerName).first().click();
      await expect(page.getByRole("dialog")).toBeVisible();
      await expect(page.getByRole("button", { name: "Close player details", exact: true })).toBeVisible();
      await expect(page.getByRole("dialog").getByText("Source Breakdown", { exact: true })).toBeVisible();
      expect(paths.filter((p) => /\/read-models\/players\/[a-f0-9]+$/.test(p))).toHaveLength(1);
      await page.getByRole("button", { name: "Close player details", exact: true }).click();
      await page.keyboard.press("Control+k");
      await page.getByRole("combobox", { name: "Search players, picks, and pages" }).fill("Lab Player 001");
      await expect(page.locator(".shell-palette-option-name").first()).toHaveText("Lab Player 001");
      expect(paths).not.toContain("/api/read-models/players/catalog");
      await page.keyboard.press("Escape");
      if (variant === "prepared") await page.screenshot({ path: path.join(output, `rankings-${viewportName}.png`) });
      expect(forbidden(paths)).toEqual([]); expect(errors).toEqual([]);
      report.cases.push({ route: "/rankings", viewport: viewportName, variant, passed: true, csvRows: initialCsv.split("\n").length - 1, csvSha256: hash(initialCsv), filtering: true, sourceVisibilityDoesNotChangeExport: true, fullSourceAudit: true, popup: true, globalSearchOwnUniverse: true, forbiddenFullReads: 0, errors: 0, metrics: initialMetrics });
      await context.close();
    }
    for (const tradeVariant of ["full", "prepared"]) {
    await fetch(`${origin}/__lab/control?variant=${tradeVariant}&detailDelay=350`);
    const { page, context, paths, errors } = await open("/trade", viewport);
    await expect(page.locator(".trade-side-search-input").first()).toBeVisible({ timeout: 20000 });
    await awaitStreamSettled(page);
    const initialMetrics = await metrics(page);
    await page.locator(".trade-side-search-input").first().fill("Lab Player 001");
    await expect(page.locator(".trade-side-search-result").first()).toBeVisible();
    await page.locator(".trade-side-search-result").first().click();
    await expect(page.getByRole("button", { name: "Remove Lab Player 001 from Side A" })).toBeVisible();
    const tradeCsv = await csv(page, "CSV");
    expect(tradeCsv).toContain("Lab Player 001");
    if (tradeVariant === "full") canonicalByViewport.set(`${viewportName}-trade`, tradeCsv);
    else expect(tradeCsv).toBe(canonicalByViewport.get(`${viewportName}-trade`));
    await page.getByRole("button", { name: "Lab Player 001", exact: true }).first().click();
    await expect(page.getByRole("button", { name: "Close player details", exact: true })).toBeVisible();
    await expect(page.getByRole("dialog").getByText("Source Breakdown", { exact: true })).toBeVisible();
    expect(forbidden(paths)).toEqual([]); expect(errors).toEqual([]);
    report.cases.push({ route: "/trade", viewport: viewportName, variant: tradeVariant, passed: true, picker: true, csv: true, csvSha256: hash(tradeCsv), popupFullSourceBody: true, forbiddenFullReads: 0, errors: 0, metrics: initialMetrics });
    await context.close();
    }
  }
  await fetch(`${origin}/__lab/control?variant=prepared&detailDelay=0`);
  const { page, context, paths, errors } = await open("/league-comparison", { width: 1366, height: 900 });
  await expect(page.getByRole("button", { name: "Improved", exact: true })).toBeVisible({ timeout: 20000 });
  expect(paths.filter((p) => p.startsWith("/api/read-models/"))).toEqual([]);
  await page.keyboard.press("Control+k");
  await page.getByRole("combobox", { name: "Search players, picks, and pages" }).fill("Lab Player 001");
  await expect(page.locator(".shell-palette-option-name").first()).toHaveText("Lab Player 001");
  expect(paths.filter((p) => p === "/api/read-models/players/catalog")).toHaveLength(1);
  await page.locator(".shell-palette-option").first().click();
  await expect(page.getByRole("button", { name: "Close player details", exact: true })).toBeVisible();
  await expect(page.getByRole("dialog").getByText("Source Breakdown", { exact: true })).toBeVisible();
  expect(forbidden(paths)).toEqual([]); expect(errors).toEqual([]);
  report.cases.push({ route: "/league-comparison", passed: true, zeroInitialGlobalReads: true, firstIntentCatalogRequests: 1, fullPopup: true, errors: 0 });
  await context.close();
  report.passed = true;
} catch (error) {
  report.passed = false; report.failure = error.message;
  if (currentPage && !currentPage.isClosed()) {
    report.failurePageText = (await currentPage.locator("body").innerText()).slice(0, 5000);
    await currentPage.screenshot({ path: path.join(output, "browser-failure.png") }).catch(() => {});
  }
  process.exitCode = 1;
} finally {
  fs.writeFileSync(path.join(output, "prepared-browser-evidence.json"), JSON.stringify(report, null, 2));
  console.log(JSON.stringify({ passed: report.passed, cases: report.cases.length, failure: report.failure?.slice(0, 800) }, null, 2));
  await browser.close();
}
