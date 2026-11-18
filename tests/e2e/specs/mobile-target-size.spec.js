/**
 * Task 10 (audit-remediation 2026-11-18) — primary touch controls reach a
 * 44x44 CSS px target at 390px.
 *
 * THE DEFECT: the design-system controls were 32px (buttons, inputs,
 * selects) and 24px (segmented options, info triggers) with no
 * coarse-pointer enlargement, and the 390px axe scans covered ~12 route
 * families. axe's `target-size` rule is a WCAG 2.2 rule outside the
 * 2.0/2.1 A/AA tag set a11y-axe.spec.js ratchets on, so nothing measured it.
 * The repair is the `@media (pointer: coarse), (max-width: 480px)` block at
 * the end of `frontend/app/ds.css`.
 *
 * WHAT THIS ASSERTS, and why it is split in two:
 *
 *   HARD (fails the run)  every visible design-system control —
 *       `.ds-btn`, `.ds-input`, `.ds-select`, `.ds-tab`,
 *       `.ds-segmented__option` — measures at least 44px in BOTH
 *       dimensions. These are the controls the enlargement owns, so a
 *       shortfall is a regression of that block, not a legacy page.
 *
 *   REPORTED (annotation, never fails)  every other interactive element
 *       (legacy `.btn`, page-local buttons, native checkboxes, icon
 *       controls) below 44px is listed in the test annotations and an
 *       attached JSON, with those under the WCAG 2.5.8 AA floor (24px)
 *       called out. The legacy per-page controls are migrated route by
 *       route (UI Lane 6) and were not baselined on a real device while
 *       this was written; turning them into a hard gate without a baseline
 *       would fail on debt this change did not introduce. The report is the
 *       baseline to ratchet from.
 *
 * EXEMPTIONS (WCAG 2.5.8 exceptions), both applied to the REPORT and to
 * the hard group alike:
 *   - inline: an <a> that sits inside a sentence (its parent has other
 *     text) — "the target is in a sentence or its size is otherwise
 *     constrained by the line-height of non-target text";
 *   - equivalent: a control whose <label> (wrapping or `for=`) is itself
 *     a larger target is measured as the label's box, since a tap on the
 *     label activates it.
 * Also skipped: not rendered / zero-size, aria-hidden, off-screen skip
 * links, and the 1px visually-hidden file inputs.
 *
 * THE CONTROL: the probe is run first against known geometry (a 20px
 * design-system button must be flagged, an inline link must not be).
 * An instrument that cannot see a 20px button would make every route
 * pass vacuously — same posture as mobile-type-floor.spec.js.
 *
 * Emulation: the mobile projects run hasTouch + isMobile, so
 * `(pointer: coarse)` matches in Chromium; `(max-width: 480px)` covers
 * engines that do not surface it for emulated viewports.
 */
const { test, expect } = require("../helpers/auth-fixture");
const {
  pageUrl,
  awaitStreamSettled,
  isMobileProject,
} = require("../helpers/journey");

const MOBILE = { width: 390, height: 844 };
const TARGET_PX = 44;
const AA_FLOOR_PX = 24;
// Sub-pixel layout can land at 43.98; a real shortfall is never that close.
const EPSILON = 0.5;

const HARD_SELECTOR = [
  ".ds-btn",
  ".ds-input",
  ".ds-select",
  ".ds-tab",
  ".ds-segmented__option",
].join(",");

const INTERACTIVE_SELECTOR = [
  "button",
  "a[href]",
  "input:not([type=hidden])",
  "select",
  "textarea",
  '[role="button"]',
  '[role="tab"]',
  '[role="radio"]',
  '[role="checkbox"]',
  '[role="switch"]',
  '[role="menuitem"]',
].join(",");

/**
 * Runs IN the page. Returns `{ measured, hardFailures, belowTarget }`.
 * `measured` is the count of targets actually measured, so a page that
 * never rendered cannot read as clean (MISSING IS NEVER ZERO).
 */
const SCAN_TARGETS = ({ hardSelector, interactiveSelector, targetPx, floorPx, eps }) => {
  const describe = (el) => {
    const cls = String(el.className && el.className.baseVal !== undefined ? el.className.baseVal : el.className || "")
      .trim()
      .split(/\s+/)
      .filter(Boolean)
      .slice(0, 3)
      .join(".");
    const label = (
      el.getAttribute("aria-label") ||
      el.textContent ||
      el.getAttribute("placeholder") ||
      el.getAttribute("name") ||
      ""
    )
      .replace(/\s+/g, " ")
      .trim()
      .slice(0, 40);
    return `${el.tagName.toLowerCase()}${cls ? "." + cls : ""} "${label}"`;
  };
  const hidden = (el) => {
    if (el.closest('[aria-hidden="true"], [hidden], [inert]')) return true;
    const s = getComputedStyle(el);
    return s.display === "none" || s.visibility === "hidden" || Number(s.opacity) === 0;
  };
  const inlineInSentence = (el) => {
    if (el.tagName !== "A") return false;
    if (getComputedStyle(el).display !== "inline") return false;
    const parent = el.parentElement;
    if (!parent) return false;
    const around = (parent.textContent || "").replace(el.textContent || "", "").trim();
    return around.length > 0;
  };
  const box = (el) => {
    // A native control inside / for= a label is activated by tapping the
    // label: measure the larger of the two boxes.
    let r = el.getBoundingClientRect();
    const labels = el.labels ? Array.from(el.labels) : [];
    for (const l of labels) {
      const lr = l.getBoundingClientRect();
      if (lr.width * lr.height > r.width * r.height) r = lr;
    }
    return r;
  };

  let measured = 0;
  const hardFailures = [];
  const belowTarget = [];
  const seen = new Set();
  for (const el of document.querySelectorAll(interactiveSelector)) {
    if (seen.has(el)) continue;
    seen.add(el);
    if (hidden(el)) continue;
    const r = box(el);
    if (r.width <= 1 || r.height <= 1) continue; // visually-hidden inputs
    if (r.right < 0 || r.left > window.innerWidth) continue; // off-screen skip links
    if (inlineInSentence(el)) continue;
    measured++;
    const w = Math.round(r.width * 10) / 10;
    const h = Math.round(r.height * 10) / 10;
    const short = w < targetPx - eps || h < targetPx - eps;
    if (!short) continue;
    const entry = {
      what: describe(el),
      size: `${w}x${h}`,
      belowAAFloor: w < floorPx || h < floorPx,
    };
    if (el.matches(hardSelector)) hardFailures.push(entry);
    else belowTarget.push(entry);
  }
  return { measured, hardFailures, belowTarget };
};

const PROBE_ARGS = {
  hardSelector: HARD_SELECTOR,
  interactiveSelector: INTERACTIVE_SELECTOR,
  targetPx: TARGET_PX,
  floorPx: AA_FLOOR_PX,
  eps: EPSILON,
};

/**
 * Routes: the high-use set plus the families added to the 390px axe scan
 * in the same change (/draft, /arbitrage, /angle, /edge, /market/*,
 * /auction*). Every entry is a real page route; the auction room has no
 * fixture offline so it is measured in its own sign-in state.
 */
const ROUTES = [
  "/trade",
  "/rankings",
  "/draft",
  "/arbitrage",
  "/angle",
  "/edge",
  "/market/sharp-people",
  "/market/sharp-roster-percentage",
  "/market/sharp-tracker",
  "/market/trade-database",
  "/auction",
  "/auction/join",
  "/auction/notifications",
];

test.describe("mobile 390px: primary touch controls are at least 44x44", () => {
  test.use({ viewport: MOBILE, isMobile: true, hasTouch: true });

  test("the probe flags known-bad geometry and exempts inline links (control)", async ({
    page,
  }) => {
    await page.setContent(
      '<meta name="viewport" content="width=device-width">' +
        "<main>" +
        '<button class="ds-btn" style="width:20px;height:20px;padding:0;min-height:0;min-width:0">x</button>' +
        '<button class="ds-btn" style="width:60px;height:44px;padding:0">ok</button>' +
        '<button class="legacy" style="width:30px;height:30px">legacy</button>' +
        '<p>See the <a href="#a">methodology</a> for details.</p>' +
        "</main>",
    );
    const r = await page.evaluate(SCAN_TARGETS, PROBE_ARGS);
    expect(r.measured).toBe(3);
    expect(r.hardFailures).toHaveLength(1);
    expect(r.hardFailures[0].size).toBe("20x20");
    expect(r.belowTarget).toHaveLength(1);
    expect(r.belowTarget[0].belowAAFloor).toBe(false);
  });

  for (const route of ROUTES) {
    test(`${route} — design-system controls are >= 44px`, async ({ authedPage }, testInfo) => {
      test.skip(!isMobileProject(testInfo), "touch-target sizing is a phone-project assertion");
      await authedPage.setViewportSize(MOBILE);
      await authedPage.goto(pageUrl(route), { waitUntil: "domcontentloaded" });
      await awaitStreamSettled(authedPage);
      await authedPage.waitForLoadState("networkidle", { timeout: 3_000 }).catch(() => {});
      await authedPage
        .waitForFunction(() => !document.querySelector(".ds-skeleton, [aria-busy=\"true\"]"), null, {
          timeout: 10_000,
        })
        .catch(() => {});
      await authedPage.waitForTimeout(400);

      const result = await authedPage.evaluate(SCAN_TARGETS, PROBE_ARGS);

      // Non-vacuity: a page with no measurable control did not render.
      expect(
        result.measured,
        `${route}: no interactive targets were measurable — the page did not render`,
      ).toBeGreaterThan(0);

      if (result.belowTarget.length) {
        const aa = result.belowTarget.filter((e) => e.belowAAFloor);
        testInfo.annotations.push({
          type: "target-size-below-44",
          description:
            `${route}: ${result.belowTarget.length} non-ds target(s) < 44px ` +
            `(${aa.length} < 24px AA floor): ` +
            result.belowTarget
              .slice(0, 8)
              .map((e) => `${e.what} ${e.size}`)
              .join("; "),
        });
        await testInfo.attach("below-44-report.json", {
          body: JSON.stringify(result.belowTarget, null, 2),
          contentType: "application/json",
        });
      }

      expect(
        result.hardFailures,
        `${route}: design-system controls under 44px at 390px — the ` +
          "coarse-pointer block at the end of frontend/app/ds.css should " +
          `have enlarged them:\n${result.hardFailures
            .map((e) => `  ${e.what} ${e.size}`)
            .join("\n")}`,
      ).toEqual([]);
    });
  }
});
