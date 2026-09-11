// Private replay parity; retain only hashes/counts/geometry and generic failures.
import { chromium } from "playwright";
import { createRequire } from "node:module";
import { createHash } from "node:crypto";
import fs from "node:fs";
import path from "node:path";
const require = createRequire(import.meta.url);
const { expect } = require("@playwright/test");
const { SEL, awaitStreamSettled } = require("../helpers/journey.js");
const origin = "http://127.0.0.1:3082";
const output = path.resolve(process.env.PERF_LAB_OUTPUT || "output/playwright");
fs.mkdirSync(output, { recursive: true });
const browser = await chromium.launch({ executablePath: process.env.PW_CHROMIUM_PATH || undefined });
const report = { scope: "Private replay browser correctness only; no production data values retained", cases: [], passed: false };
const baselines = new Map();
async function csv(page) {
  const pending = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export CSV", exact: true }).click();
  const download = await pending;
  const stream = await download.createReadStream();
  const chunks = []; for await (const chunk of stream) chunks.push(chunk);
  const data = Buffer.concat(chunks);
  const result = { sha256: createHash("sha256").update(data).digest("hex"), lines: data.toString("utf8").split("\n").length };
  await download.delete();
  return result;
}
async function geometry(page) {
  return page.locator(".ds-table").first().evaluate((table) => ({ widths: [...table.querySelectorAll("thead th")].map((th) => th.getBoundingClientRect().width), tableWidth: table.getBoundingClientRect().width }));
}
try {
  for (const [viewport, size] of [["mobile", { width: 390, height: 844 }], ["desktop", { width: 1366, height: 900 }]]) {
    for (const frontendPort of [3084, 3081]) {
      await fetch(`${origin}/__lab/control?variant=prepared&transport=direct-gzip&detailDelay=0&frontendPort=${frontendPort}`);
      const context = await browser.newContext({ viewport: size, acceptDownloads: true });
      await context.request.post(`${origin}/api/test/create-session`);
      const page = await context.newPage();
      const errors = [];
      const detailStatuses = [];
      page.on("response", (response) => { if (/\/api\/read-models\/players\/[a-f0-9]+$/.test(new URL(response.url()).pathname)) detailStatuses.push(response.status()); });
      const forbidden = [];
      page.on("pageerror", (error) => errors.push(error.name));
      page.on("request", (req) => { if (/^\/api\/(data|dynasty-data)$/.test(new URL(req.url()).pathname)) forbidden.push("global-read"); });
      const cdp = await context.newCDPSession(page);
      await cdp.send("Network.enable"); await cdp.send("Network.setBlockedURLs", { urls: ["https://*"] });
      await page.goto(`${origin}/rankings`);
      await expect(page.locator(SEL.boardRow).first()).toBeVisible({ timeout: 20000 });
      await awaitStreamSettled(page);
      await expect(page.locator(".ds-table").first()).toHaveCSS("table-layout", "fixed");
      // The existing CSV contract exports displayRows; Show all explicitly
      // includes every eligible row before comparing the full-board export.
      const showAll = page.getByRole("button", { name: /^Show all/ });
      if (await showAll.count()) await showAll.click();
      await expect(page.locator(".ds-table").first()).toHaveCSS("table-layout", "fixed");
      const initial = await csv(page);
      expect(initial.lines).toBeGreaterThan(500);
      const initialGeometry = await geometry(page);
      if (frontendPort === 3084) baselines.set(viewport, { initial, initialGeometry });
      else {
        expect(initial).toEqual(baselines.get(viewport).initial);
        initialGeometry.widths.forEach((width, index) => expect(width).toBeCloseTo(baselines.get(viewport).initialGeometry.widths[index], 0));
      }
      await page.getByRole("button", { name: /^Columns/ }).click();
      await page.getByRole("checkbox", { name: "Show source columns", exact: true }).check();
      await page.getByRole("button", { name: /^Columns/ }).click();
      const sourceColumns = await page.locator(".ds-table thead th").count();
      expect(await csv(page)).toEqual(initial);
      await page.setViewportSize(viewport === "mobile" ? { width: 1366, height: 900 } : { width: 390, height: 844 });
      await page.setViewportSize(size);
      await expect(page.locator(".ds-table").first()).toHaveCSS("table-layout", "fixed");
      await page.getByRole("combobox", { name: "Position filter", exact: true }).selectOption("QB");
      const filtered = await csv(page);
      expect(filtered.lines).toBeLessThan(initial.lines);
      if (frontendPort === 3084) baselines.get(viewport).filtered = filtered;
      else expect(filtered).toEqual(baselines.get(viewport).filtered);
      await page.locator(SEL.boardRow).first().locator("td").first().click();
      if (viewport === "mobile") await expect(page.locator(".rankings-mobile-source-row")).toBeVisible();
      await page.locator(SEL.playerName).first().click();
      report.partial = { viewport, frontendPort, initial, filtered, detailStatuses, dialogs: await page.getByRole("dialog").count(), sourceSections: await page.getByText("Source Breakdown", { exact: true }).count() };
      await expect(page.getByRole("dialog").getByText("Source Breakdown", { exact: true })).toBeVisible();
      expect(errors).toEqual([]); expect(forbidden).toEqual([]);
      report.cases.push({ viewport, frontendPort, passed: true, initial, filtered, initialGeometry, sourceColumns, fullPopup: true, errors: errors.length, forbiddenFullReads: forbidden.length });
      await context.close();
    }
  }
  report.passed = true;
} catch (error) {
  // Never serialize assertion text: it can contain private player content.
  report.errorType = error.name || "Error"; report.failureLocation = error.stack?.match(/replay-smoke\.mjs:\d+:\d+/)?.[0] || null; process.exitCode = 1;
} finally {
  await browser.close();
  fs.writeFileSync(path.join(output, "private-replay-correctness.json"), JSON.stringify(report, null, 2));
  console.log(JSON.stringify({ passed: report.passed, cases: report.cases.length, errorType: report.errorType, failureLocation: report.failureLocation }));
}
