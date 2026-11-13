const { test, expect } = require("@playwright/test");
const AxeBuilder = require("@axe-core/playwright").default;
const fs = require("node:fs");
const path = require("node:path");
const output = path.resolve("output/playwright");
fs.mkdirSync(output, { recursive: true });

test("rankings filters, sort, format boards, CSV and URL return journey", async ({
  page,
}) => {
  await page.goto("/rankings");
  await page.getByLabel("Search players").fill("Vale");
  await expect(page.locator("tbody tr")).toHaveCount(1);
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export CSV" }).click();
  const file = await download;
  expect(file.suggestedFilename()).toContain("SYNTHETIC");
  expect(fs.readFileSync(await file.path(), "utf8")).toContain("Darius Vale");
  await page.getByLabel("League format").selectOption("1QB");
  await expect(page.locator(".value-cell")).toHaveText("9,880");
  await page.getByRole("link", { name: "Darius Vale" }).click();
  await expect(page.locator(".player-value>strong")).toHaveText("9,880");
  await page.getByRole("link", { name: "Malcolm Reed" }).click();
  await page.getByRole("link", { name: "Back to rankings" }).click();
  await expect(page.getByLabel("Search players")).toHaveValue("Vale");
  await expect(page.getByLabel("League format")).toHaveValue("1QB");
  await page.getByRole("button", { name: "Reset", exact: true }).click();
  await page.getByRole("button", { name: "VALUE" }).click();
  await expect(
    page.locator("tbody tr").first().locator(".value-cell"),
  ).toHaveText("2,234");
  await page.getByRole("button", { name: "VALUE" }).click();
  await expect(
    page.locator("tbody tr").first().locator(".value-cell"),
  ).toHaveText("9,860");
  await page.getByRole("button", { name: "SOURCE SPREAD" }).click();
  await expect(
    page.getByRole("columnheader", { name: "SOURCE SPREAD" }),
  ).toHaveAttribute("aria-sort", "ascending");
  await page.getByRole("button", { name: "SOURCE SPREAD" }).click();
  await expect(
    page.getByRole("columnheader", { name: "SOURCE SPREAD" }),
  ).toHaveAttribute("aria-sort", "descending");
});
test("comparison caps selection at three and dialog restores focus", async ({
  page,
}) => {
  await page.goto("/rankings");
  for (const name of [
    "Darius Vale",
    "Elias Brooks",
    "Malcolm Reed",
    "Julian Cross",
  ])
    await page.getByLabel(`Compare ${name}`, { exact: true }).click();
  await expect(page.locator("tbody input:checked")).toHaveCount(3);
  await expect(page.getByRole("status")).toContainText("up to three");
  const trigger = page.getByRole("button", { name: "Compare players" });
  await trigger.click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(trigger).toBeFocused();
});
test("player research ranges, keyboard inspection, tabs and honest trade seam", async ({
  page,
}) => {
  await page.goto("/players/demo-01");
  await page.getByRole("button", { name: "30D", exact: true }).click();
  await expect(page.locator(".history-chart")).not.toContainText("2026-10-04");
  const slider = page.getByRole("slider", { name: "Inspect history point" });
  await slider.focus();
  await page.keyboard.press("Home");
  await expect(slider).toHaveAttribute("aria-valuetext", "2026-10-18, 9,620");
  await page.getByRole("tab", { name: "Overview" }).focus();
  await page.keyboard.press("ArrowRight");
  await expect(page.getByRole("tab", { name: "Scouting" })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  await page.getByRole("tab", { name: "Projections" }).click();
  await expect(page.locator(".projection")).toContainText("11.4");
  await page.getByRole("button", { name: "Explore a trade" }).click();
  await expect(page.getByRole("dialog")).toContainText(
    "fairness are unavailable",
  );
  await page.keyboard.press("Escape");
  await page.goto("/players/demo-05");
  await page.getByRole("tab", { name: "Projections" }).click();
  await expect(page.getByRole("tabpanel")).toContainText(
    "Projection unavailable",
  );
  await page.goto("/players/demo-64");
  await expect(page.locator(".player-value>strong")).toHaveText("Unavailable");
});
test("news filtering, source detail, timeline and missing-player report navigation", async ({
  page,
}) => {
  await page.goto("/news");
  await page.getByLabel("Search news").fill("Vale");
  await expect(page.locator(".news-view")).toContainText("2 STORIES");
  await page.getByRole("button", { name: "Read the report & context" }).click();
  await expect(page.getByRole("dialog")).toContainText(
    "fictional demonstration source",
  );
  await page.keyboard.press("Escape");
  await page
    .getByRole("button", { name: "Player timelines", exact: true })
    .click();
  await expect(page.locator(".timeline-grid>section")).toHaveCount(1);
  await page.goto("/players/demo-64");
  await page.getByRole("button", { name: /No player-specific report/ }).click();
  await expect(page).toHaveURL(/\/news$/);
});
test("state demonstrations recover, invalid route is explicit, no horizontal overflow at zoom", async ({
  page,
}) => {
  for (const state of ["Loading", "Empty", "Unavailable"]) {
    await page.goto("/rankings");
    await page.getByLabel("Demo state").selectOption(state);
    await expect(page.locator(".state-panel")).toBeVisible();
    await page.locator(".state-panel button").click();
    await expect(page.locator("table")).toBeVisible();
  }
  await page.getByLabel("Demo state").selectOption("Stale");
  await expect(page.getByRole("status").first()).toContainText(
    "source coverage from Nov 01",
  );
  await page.goto("/players/unknown");
  await expect(
    page.getByRole("heading", { name: "Player not found." }),
  ).toBeVisible();
  await page.setViewportSize({ width: 720, height: 900 });
  await page.goto("/news");
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});
test("mobile filters, detail expansion and keyboard dialog containment", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/rankings");
  await page.getByRole("button", { name: "More filters" }).click();
  await page.getByLabel("Movement · 7 days").selectOption("Fallers");
  await expect(page.locator("tbody tr").first()).toContainText("Malcolm Reed");
  await page.getByRole("button", { name: "Details for Malcolm Reed" }).click();
  await expect(page.locator(".mobile-detail")).toContainText("Source spread");
  await page.getByRole("button", { name: "Compare 0", exact: true }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  for (let i = 0; i < 6; i++) {
    await page.keyboard.press("Tab");
    expect(
      await page.evaluate(() => !!document.activeElement.closest("dialog")),
    ).toBe(true);
  }
  await page.keyboard.press("Escape");
  await page.goto("/news");
  await page.getByRole("button", { name: "Refine the desk" }).click();
  await page
    .getByLabel("Relevance", { exact: true })
    .selectOption("Demo roster");
  await expect(page.locator(".news-view")).toContainText("6 STORIES");
});
test("records local input-to-render measurement", async ({ page }) => {
  await page.goto("/rankings");
  await page.evaluate(() => {
    const input = document.querySelector('input[aria-label="Search players"]');
    input.addEventListener(
      "input",
      () => {
        window.__inputStart = performance.now();
        const observer = new MutationObserver(() => {
          requestAnimationFrame(() =>
            requestAnimationFrame(() => {
              window.__inputRender = performance.now() - window.__inputStart;
              observer.disconnect();
            }),
          );
        });
        observer.observe(document.querySelector("tbody"), {
          childList: true,
          subtree: true,
        });
      },
      { once: true },
    );
  });
  await page.getByLabel("Search players").fill("Vale");
  await expect(page.locator("tbody tr")).toHaveCount(1);
  await page.waitForFunction(() => Number.isFinite(window.__inputRender));
  fs.writeFileSync(
    path.join(output, "interaction-metrics.json"),
    JSON.stringify(
      {
        inputToSecondFrameMs: await page.evaluate(() => window.__inputRender),
        note: "Local Chromium, warm production build, no CPU/network throttling; not production INP.",
      },
      null,
      2,
    ),
  );
});
for (const width of [1440, 768, 390])
  for (const [screen, url] of [
    ["rankings", "/rankings"],
    ["player", "/players/demo-01"],
    ["news", "/news"],
  ]) {
    test(`render ${screen} ${width}, accessibility and local-only traffic`, async ({
      page,
    }) => {
      const external = [],
        errors = [];
      page.on("request", (r) => {
        if (!new URL(r.url()).hostname.match(/^(127\.0\.0\.1|localhost)$/))
          external.push(r.url());
      });
      page.on("pageerror", (e) => errors.push(e.message));
      await page.addInitScript(() => {
        window.__vitals = { lcpMs: null, cls: 0, shifts: [] };
        new PerformanceObserver((list) => {
          for (const e of list.getEntries())
            window.__vitals.lcpMs = e.startTime;
        }).observe({ type: "largest-contentful-paint", buffered: true });
        new PerformanceObserver((list) => {
          for (const e of list.getEntries())
            if (!e.hadRecentInput) {
              window.__vitals.cls += e.value;
              window.__vitals.shifts.push({
                value: e.value,
                time: e.startTime,
                sources: e.sources.map((s) => ({
                  node: s.node?.tagName,
                  className: s.node?.className,
                  previous: s.previousRect.toJSON(),
                  current: s.currentRect.toJSON(),
                })),
              });
            }
        }).observe({ type: "layout-shift", buffered: true });
      });
      await page.setViewportSize({ width, height: width === 390 ? 844 : 1000 });
      await page.emulateMedia({ reducedMotion: "reduce" });
      await page.goto(url);
      await page.evaluate(() => document.fonts.ready);
      await page.waitForTimeout(200);
      // Capture load metrics before full-page screenshots resize the viewport
      // and before axe injects instrumentation into the document.
      const metrics = await page.evaluate(() => ({
        vitals: { ...window.__vitals },
        measurementWindowMs: performance.now(),
        navigation: performance.getEntriesByType("navigation").map((n) => ({
          domContentLoaded: n.domContentLoadedEventEnd,
          duration: n.duration,
          transferSize: n.transferSize,
        })),
        resources: performance.getEntriesByType("resource").map((r) => ({
          name: new URL(r.name).pathname,
          transferSize: r.transferSize,
          duration: r.duration,
        })),
      }));
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
      ).toBe(true);
      await page.screenshot({
        path: path.join(output, `${screen}-${width}.png`),
        fullPage: true,
      });
      await page.screenshot({
        path: path.join(output, `${screen}-${width}-viewport.png`),
      });
      const result = await new AxeBuilder({ page })
        .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
        .analyze();
      fs.writeFileSync(
        path.join(output, `${screen}-${width}-axe.json`),
        JSON.stringify(result.violations, null, 2),
      );
      expect(result.violations).toEqual([]);
      expect(external).toEqual([]);
      expect(errors).toEqual([]);
      fs.writeFileSync(
        path.join(output, `${screen}-${width}-metrics.json`),
        JSON.stringify(metrics, null, 2),
      );
    });
  }
