/**
 * /dfs — populated-state accessibility and the core owner journey.
 *
 * WHY THIS EXISTS
 * ───────────────
 * Lane 6 (docs/ui/UI_PARALLEL_LEDGER.md, row /dfs) records that the DFS
 * workspace had component tests but no real-browser accessibility evidence.
 * A scan of an empty page is not accessibility evidence (contract §13), so
 * every scan below runs only after real content is on screen.
 *
 * DATA
 * ────
 * The slate is the repo's SYNTHETIC DraftKings NFL fixture
 * (tests/dfs/fixtures/synthetic_dk_nfl_classic_*.csv — invented teams AAA..FFF
 * and "Syn …" names), pasted into the import box exactly as an owner pastes a
 * salary file. Nothing here touches a real platform or live data, and every
 * build is research-only by construction (the rule sets are unverified).
 *
 * WHAT IS CHECKED
 * ───────────────
 *   axe WCAG 2.0/2.1 A+AA   zero violations: honest "not available" state
 *                           (MMA), imported slate, built lineup
 *   journey                 import → player pool → Optimal Lineup → a legal
 *                           lineup with the upload-CSV action, labelled
 *                           not contest-evaluated
 *   keyboard                Lock is a real toggle button (aria-pressed)
 *   mobile                  no page-level horizontal scroll with the slate
 *                           loaded (only table regions may scroll)
 */
const fs = require("node:fs");
const path = require("node:path");
const { test, expect } = require("../helpers/auth-fixture");
const AxeBuilder = require("@axe-core/playwright").default;
const { pageUrl, isMobileProject } = require("../helpers/journey");

const WCAG = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"];
const FIX = path.resolve(__dirname, "../../dfs/fixtures");
const SALARIES = fs.readFileSync(path.join(FIX, "synthetic_dk_nfl_classic_salaries.csv"), "utf8");
const PROJECTIONS = fs.readFileSync(path.join(FIX, "synthetic_dk_nfl_classic_projections.csv"), "utf8");

test.setTimeout(180_000);

async function scan(page, testInfo, name) {
  const results = await new AxeBuilder({ page }).withTags(WCAG).analyze();
  await testInfo.attach(`${name}-axe`, {
    body: JSON.stringify(results.violations, null, 2),
    contentType: "application/json",
  });
  expect(
    results.violations.map((v) => ({ id: v.id, impact: v.impact, nodes: v.nodes.slice(0, 3).map((n) => `${n.target.join(" ")} — ${(n.failureSummary || "").replace(/\s+/g, " ").slice(0, 200)}`) })),
    `${name}: axe WCAG A/AA violations`,
  ).toEqual([]);
}

async function openWorkspace(page) {
  await page.goto(pageUrl("/dfs"));
  await expect(page.getByRole("heading", { level: 1, name: "DFS Workspace" })).toBeVisible({ timeout: 60_000 });
  // Capabilities loaded: the readiness badge is the first server-derived content.
  await expect(page.getByText(/Research only — rules unverified|Not available yet/).first()).toBeVisible({ timeout: 30_000 });
}

test("an unsupported sport shows an honest state, not fake controls", async ({ authedPage: page }, testInfo) => {
  await openWorkspace(page);
  await page.getByRole("radio", { name: "MMA" }).click();
  await expect(page.getByText(/MMA on DraftKings is not available yet/)).toBeVisible({ timeout: 15_000 });
  await expect(page.getByRole("button", { name: "Import slate" })).toHaveCount(0);
  await scan(page, testInfo, "dfs-not-available");
});

test("import a slate, build the optimal lineup, and keep the page accessible", async ({ authedPage: page }, testInfo) => {
  await openWorkspace(page);
  await page.getByRole("radio", { name: "NFL" }).click();
  await page.getByRole("radio", { name: "DraftKings" }).click();
  await page.getByLabel("Salary CSV text").fill(SALARIES);
  await page.getByLabel("Projection CSV text").fill(PROJECTIONS);
  await expect(page.getByText("Detected: DraftKings · NFL · Classic")).toBeVisible({ timeout: 15_000 });
  await page.getByRole("button", { name: "Import slate" }).click();

  const pool = page.getByRole("table", { name: /Slate player pool/ });
  await expect(pool).toBeVisible({ timeout: 30_000 });
  await expect(pool.getByRole("row")).not.toHaveCount(1); // header only would mean nothing imported
  await scan(page, testInfo, "dfs-slate-imported");

  // Lock is a genuine toggle, operable from the keyboard.
  const lock = page.getByRole("button", { name: /^Lock Syn / }).first();
  await lock.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("button", { name: /^Unlock Syn / }).first()).toHaveAttribute("aria-pressed", "true");

  if (isMobileProject(testInfo)) {
    const report = await page.evaluate(() => {
      const el = document.scrollingElement;
      const vw = el.clientWidth;
      // Elements that stick out past the viewport, excluding anything inside a
      // region that is allowed to scroll sideways (overflow-x auto/scroll).
      const insideScroller = (node) => {
        for (let p = node.parentElement; p; p = p.parentElement) {
          const ox = getComputedStyle(p).overflowX;
          if (ox === "auto" || ox === "scroll") return true;
        }
        return false;
      };
      const offenders = [];
      for (const node of document.querySelectorAll("main *")) {
        const r = node.getBoundingClientRect();
        if (r.right > vw + 1 && !insideScroller(node)) {
          const cls = typeof node.className === "string" ? node.className.split(" ")[0] : "";
          offenders.push(`${node.tagName.toLowerCase()}${cls ? "." + cls : ""} right=${Math.round(r.right)}`);
        }
      }
      return { overflow: el.scrollWidth - vw, offenders: offenders.slice(0, 8) };
    });
    expect(report.overflow, `page-level horizontal scroll on mobile; widest: ${report.offenders.join(", ")}`).toBeLessThanOrEqual(1);
  }

  await page.getByRole("button", { name: "Optimal Lineup" }).click();
  await expect(page.getByRole("button", { name: "Download upload CSV" })).toBeVisible({ timeout: 60_000 });
  await expect(page.getByText(/^Highest projected points · not contest-evaluated/)).toBeVisible();
  await expect(page.getByRole("table", { name: /^Lineup 1:/ })).toBeVisible();
  await scan(page, testInfo, "dfs-lineup-built");
});
