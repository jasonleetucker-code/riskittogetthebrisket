// Synthetic local lab diagnostics. Only route templates, timing and byte counts
// are persisted. Run after other builds/tests stop; do not use production data.
import { chromium } from "playwright";
import { createRequire } from "node:module";
import fs from "node:fs";
import path from "node:path";
import { hasUsefulElement, buildMetricsInitScript } from "../../../frontend/scripts/route-baseline-support.mjs";
const require = createRequire(import.meta.url);
const frontendRequire = createRequire(new URL("../../../frontend/package.json", import.meta.url));
const { SEL } = require("../helpers/journey.js");
const output = path.resolve(process.env.PERF_LAB_OUTPUT || "output/playwright");
fs.mkdirSync(output, { recursive: true });
const origin = "http://127.0.0.1:3082";
await fetch(`${origin}/__lab/control?variant=prepared&detailDelay=0`);
const browser = await chromium.launch({ executablePath: process.env.PW_CHROMIUM_PATH || undefined, headless: true });
const report = { scope: "Synthetic local Next production-build lab; diagnostic samples, not production acceptance", cpu: 4, network: { latencyMs: 150, downloadBitsPerSecond: 1600000, uploadBitsPerSecond: 750000 }, readinessTimeoutMs: 10000, samples: [] };
const vitals = buildMetricsInitScript(fs.readFileSync(frontendRequire.resolve("next/dist/compiled/web-vitals"), "utf8"));
const durationKeys = ["ScriptDuration", "LayoutDuration", "RecalcStyleDuration", "TaskDuration"];
try {
  for (const route of [{ path: "/rankings", ready: SEL.boardRow }, { path: "/trade", ready: SEL.tradeControls }]) {
    const context = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
    await context.request.post(`${origin}/api/test/create-session`);
    await context.addInitScript({ content: vitals });
    await context.addInitScript(() => {
      window.__labLongTasks = [];
      new PerformanceObserver((list) => {
        window.__labLongTasks.push(...list.getEntries().map((entry) => ({ startMs: entry.startTime, durationMs: entry.duration })));
      }).observe({ type: "longtask", buffered: true });
    });
    const page = await context.newPage();
    const cdp = await context.newCDPSession(page);
    await cdp.send("Performance.enable");
    await cdp.send("Emulation.setCPUThrottlingRate", { rate: 4 });
    await cdp.send("Network.enable");
    await cdp.send("Network.emulateNetworkConditions", { offline: false, latency: 150, downloadThroughput: 1600000 / 8, uploadThroughput: 750000 / 8, connectionType: "cellular4g" });
    for (const state of ["cold", "warm"]) {
      await page.goto(`${origin}${route.path}`, { waitUntil: "commit", timeout: 10000 });
      let usefulMs = null;
      try {
        await page.waitForFunction(hasUsefulElement, route.ready, { timeout: 10000 });
        usefulMs = await page.evaluate(() => performance.now());
      } catch { /* Keep the same failed-readiness cutoff as the baseline. */ }
      await page.waitForLoadState("load", { timeout: 10000 }).catch(() => {});
      const details = await page.evaluate((ready) => {
        const entries = performance.getEntriesByType("resource");
        const safeName = (entry) => {
          const url = new URL(entry.name);
          if (url.origin !== location.origin) return "external-resource";
          if (url.pathname.startsWith("/_next/")) return `next-${entry.initiatorType}`;
          if (url.pathname.startsWith("/api/read-models/players/") && !url.pathname.endsWith("/catalog")) return "/api/read-models/players/[key]";
          if (url.pathname.startsWith("/api/")) return url.pathname;
          return "local-resource";
        };
        const resources = entries.map((entry) => ({ resource: safeName(entry), type: entry.initiatorType, startMs: entry.startTime, responseStartMs: entry.responseStart, endMs: entry.responseEnd, durationMs: entry.duration, encodedBytes: entry.encodedBodySize, decodedBytes: entry.decodedBodySize, transferBytes: entry.transferSize }));
        const groups = {};
        for (const r of resources) {
          const key = r.resource.startsWith("/api/") ? "api" : r.type;
          const group = groups[key] ||= { requests: 0, encodedBytes: 0, decodedBytes: 0, transferBytes: 0, lastEndMs: 0 };
          group.requests++; group.encodedBytes += r.encodedBytes; group.decodedBytes += r.decodedBytes; group.transferBytes += r.transferBytes; group.lastEndMs = Math.max(group.lastEndMs, r.endMs);
        }
        const nav = performance.getEntriesByType("navigation")[0];
        return { observedUntilMs: performance.now(), groups, apiWaterfall: resources.filter((r) => r.resource.startsWith("/api/")), slowestResources: resources.toSorted((a, b) => b.durationMs - a.durationMs).slice(0, 12), longTasks: window.__labLongTasks, vitals: window.__routeBaselineVitals, metricInitError: window.__routeBaselineInitError || null, markerCandidates: [...document.querySelectorAll(ready)].slice(0, 3).map((el) => ({ width: el.getBoundingClientRect().width, height: el.getBoundingClientRect().height, hiddenAncestor: Boolean(el.closest('[hidden], [aria-hidden="true"], [aria-busy="true"]')), skeleton: Boolean(el.querySelector('[class*="skeleton"], [role="progressbar"]')), hasText: Boolean(el.textContent?.trim()) })), navigation: { ttfbMs: nav.responseStart, dclMs: nav.domContentLoadedEventEnd, loadMs: nav.loadEventEnd || null } };
      }, route.ready);
      const after = Object.fromEntries((await cdp.send("Performance.getMetrics")).metrics.map((m) => [m.name, m.value]));
      // Chrome resets these duration counters on navigation; subtracting the
      // previous document would make warm samples incorrectly negative.
      const cpuMs = Object.fromEntries(durationKeys.map((key) => [key, after[key] * 1000]));
      report.samples.push({ route: route.path, state, usefulMs, ...details, cpuMs });
      console.log(JSON.stringify({ route: route.path, state, usefulMs: usefulMs == null ? null : Math.round(usefulMs), scripts: details.groups.script, api: details.groups.api, cpuMs }));
    }
    await context.close();
  }
} finally {
  fs.writeFileSync(path.join(output, "throttled-diagnostics.json"), JSON.stringify(report, null, 2));
  await browser.close();
}
