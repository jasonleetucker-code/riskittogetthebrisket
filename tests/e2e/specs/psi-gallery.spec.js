/** Populated PSI reference, keyboard/axe and visual evidence on real viewports. */
const { test, expect } = require("../helpers/auth-fixture");
const { pageUrl, awaitStreamSettled } = require("../helpers/journey");
const AxeBuilder = require("@axe-core/playwright").default;
const TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"];

async function ready(page) {
  await page.goto(pageUrl("/design"), { waitUntil: "domcontentloaded" });
  await awaitStreamSettled(page);
  await expect(page.getByTestId("psi-gallery")).toBeVisible();
  await expect(page.getByRole("heading", { level: 1, name: "Design system" })).toBeVisible();
  await expect(page.getByRole("table", { name: /Fixture value board/ }).locator("tbody tr")).toHaveCount(5);
  await page.evaluate(() => document.fonts.ready);
}

async function noPageOverflow(page) {
  const sizes = await page.evaluate(() => ({
    document: document.documentElement.scrollWidth,
    viewport: document.documentElement.clientWidth,
  }));
  expect(sizes.document, "Only the controlled table region may scroll horizontally").toBeLessThanOrEqual(sizes.viewport + 1);
}

async function scan(page, testInfo, name) {
  const results = await new AxeBuilder({ page }).withTags(TAGS).analyze();
  await testInfo.attach(name + "-axe", {
    body: JSON.stringify(results.violations, null, 2), contentType: "application/json",
  });
  expect(results.violations, name + " must have no WCAG A/AA violations").toEqual([]);
}

async function image(page, testInfo, name, fullPage = false) {
  const file = testInfo.outputPath(`${name}.png`);
  await page.screenshot({ path: file, fullPage, animations: "disabled" });
  await testInfo.attach(name, { path: file, contentType: "image/png" });
}

test("PSI gallery: populated reference, table access and desktop/phone evidence", async ({ authedPage: page }, testInfo) => {
  const errors = [];
  page.on("pageerror", error => errors.push(error.message));
  const started = Date.now();
  await ready(page);
  const usefulMs = Date.now() - started;
  await expect(page.getByRole("main")).toHaveCount(1);
  await expect(page.getByText("Fixtures only")).toBeVisible();
  await noPageOverflow(page);
  const scope = await page.getByTestId("psi-gallery").evaluate(element => {
    const style = getComputedStyle(element);
    return { surface: style.getPropertyValue("--surface-0").trim(), accent: style.getPropertyValue("--accent").trim(), display: style.getPropertyValue("--font-display").trim() };
  });
  expect(scope.surface).toBe("#f2ebdd");
  expect(scope.accent).toBe("#a3341c");
  expect(scope.display).toContain("Georgia");
  await scan(page, testInfo, "populated");
  await image(page, testInfo, "reference-top");
  await image(page, testInfo, "reference-full", true);

  const table = page.getByRole("table", { name: /Fixture value board/ });
  await table.scrollIntoViewIfNeeded();
  await expect(table.getByText("Justin Jefferson", { exact: true })).toBeVisible();
  await table.getByRole("button", { name: "Value", exact: true }).click();
  await expect(table.getByRole("columnheader", { name: "Value", exact: true })).toHaveAttribute("aria-sort", "ascending");
  await page.getByRole("radiogroup", { name: "Density" }).getByRole("radio", { name: "Compact" }).click();
  await expect(table).toHaveClass(/ds-table--compact/);
  const region = table.locator("..");
  await region.evaluate(node => { node.scrollLeft = node.scrollWidth; });
  await expect(table.getByRole("columnheader", { name: "Trend", exact: true })).toBeInViewport();
  await noPageOverflow(page);
  await image(page, testInfo, "table-secondary-fields");
  await testInfo.attach("measurement-context", {
    body: JSON.stringify({ sha: process.env.EVIDENCE_SHA || "unrecorded", origin: page.url(), viewport: page.viewportSize(), usefulMs, context: "CI built reference; not production SLO proof", scope }, null, 2),
    contentType: "application/json",
  });
  expect(errors).toEqual([]);
});

test("PSI gallery: accessible modal/drawer and keyboard focus under reduced motion", async ({ authedPage: page }, testInfo) => {
  const errors = [];
  page.on("pageerror", error => errors.push(error.message));
  await page.emulateMedia({ reducedMotion: "reduce" });
  await ready(page);
  for (const [button, title, name] of [
    ["Open modal", "Trade proposal example", "modal"],
    ["Open drawer", "Justin Jefferson", "drawer"],
  ]) {
    const opener = page.getByRole("button", { name: button, exact: true });
    await opener.focus();
    await page.keyboard.press("Enter");
    const dialog = page.getByRole("dialog", { name: title, exact: true });
    await expect(dialog).toBeVisible();
    await page.keyboard.press("Tab");
    expect(await dialog.evaluate(node => node.contains(document.activeElement))).toBe(true);
    await noPageOverflow(page);
    if (name === "drawer") {
      const chart = dialog.getByRole("img", { name: "Jefferson 6-week value trend" });
      const chartWidth = await chart.evaluate(node => node.getBoundingClientRect().width);
      const bodyWidth = await dialog.evaluate(node => node.clientWidth);
      expect(chartWidth).toBeLessThanOrEqual(bodyWidth);
    }
    await scan(page, testInfo, name);
    await image(page, testInfo, name);
    await page.keyboard.press("Escape");
    await expect(dialog).toHaveCount(0);
    await expect(opener).toBeFocused();
  }
  expect(errors).toEqual([]);
});
