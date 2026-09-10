// Run before and after a rendering candidate. Compare the resulting widths,
// alongside the full browser-lab CSV/filter/popup/source-control assertions.
import { chromium } from "playwright";
import { createRequire } from "node:module";
import fs from "node:fs";
import path from "node:path";
const require = createRequire(import.meta.url);
const { expect } = require("@playwright/test");
const { SEL, awaitStreamSettled } = require("../helpers/journey.js");
const output = path.resolve(process.env.PERF_LAB_OUTPUT || "output/playwright");
fs.mkdirSync(output, { recursive: true });
const origin = "http://127.0.0.1:3082";
await fetch(`${origin}/__lab/control?variant=prepared&detailDelay=0`);
const browser = await chromium.launch({ executablePath: process.env.PW_CHROMIUM_PATH || undefined });
const evidence = { scope: "Synthetic rankings geometry and row-window reachability", cases: [] };
async function geometry(page) {
  return page.locator(".ds-table").first().evaluate((table) => ({
    widths: [...table.querySelectorAll("thead th")].map((th) => th.getBoundingClientRect().width),
    tableWidth: table.getBoundingClientRect().width,
    scrollWidth: table.parentElement.scrollWidth,
    wrapWidth: table.parentElement.clientWidth,
    mountedRows: table.querySelectorAll('tbody tr[aria-rowindex]').length,
    trueRowCount: Number(table.getAttribute("aria-rowcount")),
    maxRowIndex: Math.max(...[...table.querySelectorAll('tbody tr[aria-rowindex]')].map((tr) => Number(tr.getAttribute("aria-rowindex")))),
  }));
}
try {
  for (const [name, viewport] of [["desktop", { width: 1366, height: 900 }], ["mobile", { width: 390, height: 844 }]]) {
    const context = await browser.newContext({ viewport });
    await context.request.post(`${origin}/api/test/create-session`);
    const page = await context.newPage();
    await page.goto(`${origin}/rankings`);
    await expect(page.locator(SEL.boardRow).first()).toBeVisible();
    await awaitStreamSettled(page);
    await expect(page.locator(".ds-table").first()).toHaveCSS("table-layout", "fixed");
    const initial = await geometry(page);
    expect(initial.trueRowCount).toBe(121);
    expect(initial.mountedRows).toBeLessThan(120);
    await page.locator(".ds-table").first().evaluate((table) => window.scrollTo(0, table.getBoundingClientRect().bottom + scrollY - innerHeight + 100));
    await expect.poll(async () => (await geometry(page)).maxRowIndex).toBe(121);
    const bottom = await geometry(page);
    initial.widths.forEach((width, i) => expect(bottom.widths[i]).toBeCloseTo(width, 0));
    await page.locator(".ds-table").first().evaluate((table) => { table.parentElement.scrollLeft = table.parentElement.scrollWidth; });
    const horizontal = await page.locator(".ds-table").first().evaluate((table) => table.parentElement.scrollLeft);
    if (initial.scrollWidth > initial.wrapWidth + 1) expect(horizontal).toBeGreaterThan(0);
    await page.setViewportSize(name === "desktop" ? { width: 390, height: 844 } : { width: 1366, height: 900 });
    await page.evaluate(() => window.scrollTo(0, 0));
    await expect.poll(async () => (await geometry(page)).widths.filter((w) => w > 0).length).not.toBe(initial.widths.filter((w) => w > 0).length);
    await page.setViewportSize(viewport);
    await expect.poll(async () => (await geometry(page)).widths.filter((w) => w > 0).length).toBe(initial.widths.filter((w) => w > 0).length);
    await expect(page.locator(".ds-table").first()).toHaveCSS("table-layout", "fixed");
    const restored = await geometry(page);
    initial.widths.forEach((width, i) => expect(restored.widths[i]).toBeCloseTo(width, 0));
    evidence.cases.push({ viewport: name, passed: true, initial, bottom, horizontalScrollLeft: horizontal, restored });
    await context.close();
  }
  evidence.passed = true;
} catch (error) {
  evidence.passed = false; evidence.error = error.message; process.exitCode = 1;
} finally {
  fs.writeFileSync(path.join(output, "geometry.json"), JSON.stringify(evidence, null, 2));
  console.log(JSON.stringify(evidence));
  await browser.close();
}
