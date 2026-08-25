/**
 * V1-109 / W26-F017 — "type as small as 9.0px ships on three pages".
 *
 * THE DEFECT, measured at 390x844 (evidence/V1-109/RE_MEASUREMENT_2026-08-24.md,
 * re-reproduced 2026-08-25 on the current tree):
 *
 *   /rankings  9.0px x~36 (value bands, chips) + 9.2px (position ranks)
 *   /rosters   9.0-9.9px (portfolio bar labels, legend, buy/sell counts)
 *   /draft     9.3px x72 ("NEED" chips)
 *
 * The re-measurement pass recorded this WITHOUT repairing it because the
 * type scale was a token decision gated on owner decision OD-05. OD-05 is
 * RESOLVED (2026-08-18, docs/DESIGN-SYSTEM.md) and V1-110 shipped the
 * ramp: an 8-step scale whose floor is --font-size-2xs = 11px, with the
 * explicit rule "no micro-type below --font-size-2xs". The repair raises
 * every sub-10px size on these three routes onto that token.
 *
 * THE ASSERTION BAR is 10px, not 11px, and the difference is deliberate:
 * the audit's own verdict drew the defect line at the ~9px band — /trade
 * ships 10.2px type and was NOT named a type-floor defect page. The
 * legacy 0.66/0.68rem sizes (10.56/10.88px) are app-wide conventions
 * whose migration onto the ramp is V1-110's per-page R-phase work, not
 * this defect. Everything this repair TOUCHED sits at 11px; what this
 * test forbids is any visible text below 10px — i.e. the micro-type
 * class the audit named — ever shipping on these routes again.
 *
 * THE CONTROL: the probe is exercised against known geometry first (a
 * page with one 9px span). An instrument that cannot see a 9px span
 * would make every route below pass vacuously — the repo has been burned
 * by an instrument measuring itself before (#760), so the self-check is
 * not optional. Same posture as measure-mobile-usability.mjs.
 */
const { test, expect } = require("../helpers/auth-fixture");
const {
  pageUrl,
  gotoRankingsBoard,
  awaitStreamSettled,
} = require("../helpers/journey");

const MOBILE = { width: 390, height: 844 };
const MIN_FONT_PX = 10; // the audit's defect line — see header.

/**
 * Runs IN the page. Returns every visible element that renders its own
 * text below `minPx`, plus the count of text elements checked (so a page
 * that never rendered cannot read as clean — MISSING IS NEVER ZERO).
 */
const SCAN_TYPE = (minPx) => {
  const isHidden = (el) => {
    if (el.closest('[aria-hidden="true"]')) return true;
    const s = getComputedStyle(el);
    if (s.display === "none" || s.visibility === "hidden" || Number(s.opacity) === 0)
      return true;
    const r = el.getBoundingClientRect();
    return r.width === 0 || r.height === 0;
  };
  const offenders = [];
  let checked = 0;
  for (const el of document.querySelectorAll("body *")) {
    if (isHidden(el)) continue;
    const hasOwnText = Array.from(el.childNodes).some(
      (n) => n.nodeType === 3 && n.textContent.trim().length > 0,
    );
    if (!hasOwnText) continue;
    checked += 1;
    const px = parseFloat(getComputedStyle(el).fontSize);
    if (!Number.isFinite(px) || px >= minPx) continue;
    offenders.push({
      px: Math.round(px * 10) / 10,
      el: `${el.tagName.toLowerCase()}.${String(el.className || "")
        .trim()
        .split(/\s+/)
        .slice(0, 2)
        .join(".")}`,
      sample: el.textContent.trim().slice(0, 30),
    });
  }
  // Collapse per (px, el) so a per-row offender reports once with a count.
  const grouped = new Map();
  for (const o of offenders) {
    const key = `${o.px}|${o.el}`;
    if (!grouped.has(key)) grouped.set(key, { ...o, count: 0 });
    grouped.get(key).count += 1;
  }
  return { checked, offenders: Array.from(grouped.values()) };
};

function offendersMessage(route, result) {
  const lines = result.offenders
    .map((o) => `  ${o.px}px x${o.count}  ${o.el}  "${o.sample}"`)
    .join("\n");
  return (
    `${route} ships text below ${MIN_FONT_PX}px at 390x844 (W26-F017):\n` +
    `${lines}\n` +
    "The design-system floor is --font-size-2xs (11px, docs/DESIGN-SYSTEM.md); " +
    "raise the offending size onto the token."
  );
}

async function scanRoute(page, route) {
  const result = await page.evaluate(SCAN_TYPE, MIN_FONT_PX);
  // Non-vacuity: every one of these routes renders hundreds of text
  // elements; a near-empty scan means the page never reached a useful
  // state, and "0 offenders on a page that did not render" must not read
  // as a clean result.
  expect(
    result.checked,
    `${route}: only ${result.checked} text elements were measurable — ` +
      "the page did not render enough to make this scan meaningful",
  ).toBeGreaterThan(50);
  expect(result.offenders, offendersMessage(route, result)).toEqual([]);
}

test.describe("mobile 390px: no micro-type below the audit's defect line", () => {
  test.use({ viewport: MOBILE, isMobile: true, hasTouch: true });

  test("the probe flags known-bad geometry (control)", async ({ page }) => {
    // The viewport meta matters: without it, mobile-emulated Chromium
    // lays the page out at 980px and text autosizing can inflate the 9px
    // span past the threshold — the control would then fail for a reason
    // that says nothing about the probe (same meta the
    // measure-mobile-usability.mjs control carries).
    await page.setContent(
      '<meta name="viewport" content="width=device-width">' +
        '<main><span style="font-size:9px">tiny</span><p>normal text</p>' +
        `${'<p>filler</p>'.repeat(60)}</main>`,
    );
    const result = await page.evaluate(SCAN_TYPE, MIN_FONT_PX);
    expect(result.checked).toBeGreaterThan(50);
    expect(result.offenders).toHaveLength(1);
    expect(result.offenders[0].px).toBe(9);
  });

  test("/rankings — no visible text below 10px", async ({ authedPage }) => {
    await authedPage.setViewportSize(MOBILE);
    await gotoRankingsBoard(authedPage);
    await scanRoute(authedPage, "/rankings");
  });

  test("/rosters — no visible text below 10px", async ({ authedPage }) => {
    await authedPage.setViewportSize(MOBILE);
    await authedPage.goto(pageUrl("/rosters"), { waitUntil: "domcontentloaded" });
    await awaitStreamSettled(authedPage);
    await expect(authedPage.locator("main table").first()).toBeVisible({
      timeout: 60_000,
    });
    await scanRoute(authedPage, "/rosters");
  });

  test("/draft — no visible text below 10px", async ({ authedPage }) => {
    await authedPage.setViewportSize(MOBILE);
    await authedPage.goto(pageUrl("/draft"), { waitUntil: "domcontentloaded" });
    await awaitStreamSettled(authedPage);
    await expect(authedPage.locator("main table").first()).toBeVisible({
      timeout: 60_000,
    });
    // The page's smallest type (the per-row "NEED" chips, 9.3px x72 in the
    // pre-repair measurement) mounts AFTER the first table renders, once
    // the roster-need computation lands. Scanning at first-table-visible
    // measured a page state where the offenders did not exist yet — a
    // pass that proves nothing. Settle the way the mobile-usability
    // instrument does (network idle + a beat), then best-effort wait for
    // the chips themselves; the .catch keeps a board that legitimately
    // has no roster needs from failing the wait, since the scan below is
    // still a valid (if weaker) statement about whatever rendered.
    await authedPage
      .waitForLoadState("networkidle", { timeout: 30_000 })
      .catch(() => {});
    await authedPage
      .locator(".draft-need-chip-row")
      .first()
      .waitFor({ timeout: 15_000 })
      .catch(() => {});
    await authedPage.waitForTimeout(1200);
    await scanRoute(authedPage, "/draft");
  });
});
