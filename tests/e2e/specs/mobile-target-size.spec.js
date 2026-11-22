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
 *   RATCHETED (fails on a NEW offender)  every other interactive element
 *       (legacy `.btn`, page-local buttons, native checkboxes, icon
 *       controls) under the WCAG 2.5.8 AA floor (24px) is compared, per
 *       route, with `tests/e2e/mobile-target-baseline.json`.  A target whose
 *       signature is not in that route's list FAILS the run, named in the
 *       error; a baseline signature this run did not see is reported as
 *       STALE (annotation) so the list only shrinks — the same contract as
 *       tests/e2e/skip-accounting.js.  Stale never fails: the baseline is the
 *       union over the phone engines CI runs (Chromium mobile-chromium and
 *       WebKit mobile-390), whose text metrics differ by a pixel or two.
 *       A signature is the element's tag + first classes (CSS-module hashes
 *       stripped) + type/role, anchored to the nearest classed ancestor when
 *       the element has none — never its text, so a nightly snapshot refresh
 *       that renames players cannot create a "new" offender.
 *
 *   REPORTED (annotation, never fails)  targets between 24px and 44px —
 *       the AAA target — are listed with an attached JSON.  The legacy
 *       per-page controls are migrated route by route (UI Lane 6).
 *
 * EXEMPTIONS (WCAG 2.5.8 exceptions), both applied to the REPORT and to
 * the hard group alike:
 *   - inline: an <a> that sits inside a sentence (its parent has other
 *     text) — "the target is in a sentence or its size is otherwise
 *     constrained by the line-height of non-target text";
 *   - equivalent: a control whose <label> (wrapping or `for=`) is itself
 *     a better target (a larger shorter side) is measured as the label's
 *     box, since a tap on the label activates it.
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
const fs = require("node:fs");
const path = require("node:path");
const { test, expect } = require("../helpers/auth-fixture");
const {
  pageUrl,
  awaitStreamSettled,
  contractFixture,
} = require("../helpers/journey");

const BASELINE_PATH = path.join(__dirname, "..", "mobile-target-baseline.json");

const MOBILE = { width: 390, height: 844 };
const TARGET_PX = 44;
const AA_FLOOR_PX = 24;
// Sub-pixel layout can land at 43.98; a real shortfall is never that close.
const EPSILON = 0.5;
// A NEW sub-24px signature fails only when some instance is below
// 24 - this.  Text rasterization differs between hosts and Chromium builds
// by a fraction of a pixel, so a target measured at 23.6px on a CI runner
// and 24.1px locally is jitter, not a regression; it is still reported.
const RATCHET_TOLERANCE_PX = 1;

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
  // Identity WITHOUT text: tag + first three classes (CSS-module hash
  // suffix `__xxxxx` stripped) + type / role.  A classless element is
  // anchored to its nearest classed ancestor so `td > a` on two different
  // tables stay distinct.  Text is never part of it: player names change
  // with every snapshot refresh and must not mint "new" offenders.
  const classes = (el) =>
    String(el.className && el.className.baseVal !== undefined ? el.className.baseVal : el.className || "")
      .trim()
      .split(/\s+/)
      .filter(Boolean)
      .slice(0, 3)
      .map((c) => c.replace(/__[A-Za-z0-9_+\/-]{5}$/, ""));
  const own = (el) => {
    const cls = classes(el);
    const type = el.getAttribute("type");
    const role = el.getAttribute("role");
    return (
      el.tagName.toLowerCase() +
      (cls.length ? "." + cls.join(".") : "") +
      (type ? `[type=${type}]` : "") +
      (role ? `[role=${role}]` : "")
    );
  };
  const signature = (el) => {
    if (classes(el).length) return own(el);
    let p = el.parentElement;
    while (p && p !== document.body && !classes(p).length) p = p.parentElement;
    return p && p !== document.body ? `${own(p)} > ${own(el)}` : own(el);
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
    // label: measure whichever box is the better target -- the larger
    // SHORTER side, then the larger area.  (Area alone picked a wide 19px
    // label over its own 34px slider on /settings.)
    const better = (a, b) => {
      const ma = Math.min(a.width, a.height);
      const mb = Math.min(b.width, b.height);
      return mb > ma || (mb === ma && b.width * b.height > a.width * a.height) ? b : a;
    };
    let r = el.getBoundingClientRect();
    const labels = el.labels ? Array.from(el.labels) : [];
    for (const l of labels) r = better(r, l.getBoundingClientRect());
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
      sig: signature(el),
      size: `${w}x${h}`,
      minSide: Math.min(w, h),
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
 * /auction*), extended (X-MOBILE-TOUCH) with the remaining daily-use pages
 * — /waivers, /league, /settings, /rosters, /game-day — and a player page.
 * Every entry is a real page route served by the offline E2E stack; the
 * auction room has no fixture offline so it is measured in its own sign-in
 * state.  A dynamic route is `{ key, resolve }`: `key` names it in the
 * baseline and the test title, `resolve` returns the concrete URL from the
 * committed snapshot and FAILS (never skips) when the snapshot lacks it.
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
  "/waivers",
  "/league",
  "/settings",
  "/rosters",
  "/game-day",
  {
    key: "/players/[playerId]",
    // The top-ranked player of the committed snapshot (the same fixture
    // a11y-axe.spec.js scans): its id changes with the snapshot, so the
    // baseline is keyed by the route family, never by an id.
    resolve: async (page) => {
      const { contract } = await contractFixture(page);
      const rows =
        Array.isArray(contract.playersArray) && contract.playersArray.length
          ? contract.playersArray.map((p) => ({ id: p?.playerId, rank: p?.canonicalConsensusRank }))
          : Object.values(contract.players || {}).map((p) => ({
              id: p?._sleeperId,
              rank: p?._canonicalConsensusRank,
            }));
      const ranked = rows
        .filter((r) => r.id && Number.isFinite(Number(r.rank)))
        .sort((a, b) => Number(a.rank) - Number(b.rank));
      expect(ranked.length, "contract must carry ranked players with a Sleeper id").toBeGreaterThan(0);
      return `/players/${encodeURIComponent(ranked[0].id)}`;
    },
  },
];

const routeKey = (route) => (typeof route === "string" ? route : route.key);

// ── Sub-24px ratchet (pure; no I/O except loadTargetBaseline) ─────────────

/** Structural validation of the baseline document.  Returns error strings. */
function validateTargetBaseline(doc, routeKeys) {
  if (!doc || typeof doc !== "object" || !doc.routes || typeof doc.routes !== "object") {
    return ["baseline must be an object with a `routes` map"];
  }
  const errors = [];
  if (
    !Array.isArray(doc.recordedOn) ||
    !doc.recordedOn.length ||
    doc.recordedOn.some((p) => typeof p !== "string" || !p)
  ) {
    errors.push("recordedOn must list the Playwright projects the baseline was measured on");
  }
  for (const key of routeKeys) {
    if (!Array.isArray(doc.routes[key])) {
      errors.push(`routes["${key}"] is missing — every measured route needs a list (empty = clean)`);
    }
  }
  for (const [key, sigs] of Object.entries(doc.routes)) {
    if (!routeKeys.includes(key)) errors.push(`routes["${key}"] names a route this spec no longer measures`);
    if (!Array.isArray(sigs)) continue;
    const seen = new Set();
    for (const sig of sigs) {
      if (typeof sig !== "string" || !sig.trim()) errors.push(`routes["${key}"] has a non-string entry`);
      else if (seen.has(sig)) errors.push(`routes["${key}"] lists "${sig}" twice`);
      seen.add(sig);
    }
  }
  return errors;
}

function loadTargetBaseline(file = BASELINE_PATH) {
  return JSON.parse(fs.readFileSync(file, "utf8"));
}

/**
 * @param {{sig:string, what:string, size:string, minSide:number}[]} offenders
 *        this run's sub-24px non-ds targets on one route
 * @param {string[]} baselineSigs that route's reviewed list
 * @returns {{added: object[], borderline: object[], stale: string[]}}
 *          `added`: the worst instance of each signature the baseline does
 *          not list, below the floor by more than the tolerance (FAILS);
 *          `borderline`: new signatures within the tolerance (reported);
 *          `stale`: baseline signatures this run did not see (reported).
 */
function compareToTargetBaseline(offenders, baselineSigs, { floor = AA_FLOOR_PX, tolerance = RATCHET_TOLERANCE_PX } = {}) {
  const known = new Set(baselineSigs);
  const worst = new Map();
  for (const o of offenders) {
    const prev = worst.get(o.sig);
    if (!prev || o.minSide < prev.minSide) worst.set(o.sig, o);
  }
  const fresh = [...worst.values()].filter((o) => !known.has(o.sig));
  const added = fresh.filter((o) => o.minSide < floor - tolerance);
  const borderline = fresh.filter((o) => o.minSide >= floor - tolerance);
  const stale = baselineSigs.filter((sig) => !worst.has(sig));
  return { added, borderline, stale };
}

test.describe("mobile 390px: primary touch controls are at least 44x44 @mobile-only", () => {
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
        '<div class="cell"><span><a href="#b" style="display:inline-block;height:16px">Player One</a></span></div>' +
        '<div class="cell"><span><a href="#c" style="display:inline-block;height:16px">Player Two</a></span></div>' +
        '<button class="page_close__Ab1_x" style="width:18px;height:18px;padding:0">x</button>' +
        // A wide, short label must not stand in for its taller control.
        '<div class="row"><label for="rng" style="display:inline-block;width:200px;height:18px">' +
        'A long slider label</label><input id="rng" type="range" style="width:60px;height:34px;margin:0"></div>' +
        "</main>",
    );
    const r = await page.evaluate(SCAN_TARGETS, PROBE_ARGS);
    expect(r.measured).toBe(7);
    expect(r.hardFailures).toHaveLength(1);
    expect(r.hardFailures[0].size).toBe("20x20");
    expect(r.belowTarget).toHaveLength(5);
    expect(r.belowTarget[0].belowAAFloor).toBe(false);
    const slider = r.belowTarget.find((e) => e.sig === "div.row > input[type=range]");
    expect(slider && slider.size).toBe("60x34");
    expect(slider.belowAAFloor).toBe(false);
    const aa = r.belowTarget.filter((e) => e.belowAAFloor);
    // Text never enters a signature: two players' links are ONE signature,
    // anchored to the nearest classed ancestor; a CSS-module hash is dropped.
    expect(aa.map((e) => e.sig)).toEqual(["div.cell > a", "div.cell > a", "button.page_close"]);
  });

  test("the sub-24px baseline is well-formed and the ratchet compares by signature (control)", () => {
    const keys = ROUTES.map(routeKey);
    expect(validateTargetBaseline(loadTargetBaseline(), keys)).toEqual([]);
    expect(
      validateTargetBaseline({ recordedOn: ["p"], routes: { "/x": ["a", "a"] } }, ["/x", "/y"]),
    ).toEqual([
      'routes["/y"] is missing — every measured route needs a list (empty = clean)',
      'routes["/x"] lists "a" twice',
    ]);
    expect(validateTargetBaseline({ routes: {} }, [])).toEqual([
      "recordedOn must list the Playwright projects the baseline was measured on",
    ]);
    const run = [
      { sig: "div.cell > a", what: 'a "One"', size: "60x16", minSide: 16 },
      { sig: "div.cell > a", what: 'a "Two"', size: "61x16", minSide: 16 },
      { sig: "button.close", what: 'button "x"', size: "18x18", minSide: 18 },
      { sig: "button.close", what: 'button "y"', size: "12x12", minSide: 12 },
      { sig: "label.jitter", what: 'label ""', size: "80x23.4", minSide: 23.4 },
    ];
    const { added, borderline, stale } = compareToTargetBaseline(run, ["div.cell > a", "span.gone"]);
    // The WORST instance represents a new signature.
    expect(added.map((o) => `${o.sig} ${o.size}`)).toEqual(["button.close 12x12"]);
    // Within the 1px tolerance: reported, never a failure.
    expect(borderline.map((o) => o.sig)).toEqual(["label.jitter"]);
    expect(stale).toEqual(["span.gone"]);
    expect(compareToTargetBaseline([], [])).toEqual({ added: [], borderline: [], stale: [] });
  });

  for (const route of ROUTES) {
    const key = routeKey(route);
    // Phone-only via the describe's @mobile-only tag (grepInvert on desktop-1366).
    test(`${key} — design-system controls are >= 44px`, async ({ authedPage }, testInfo) => {
      const url = typeof route === "string" ? route : await route.resolve(authedPage);
      await authedPage.setViewportSize(MOBILE);
      await authedPage.goto(pageUrl(url), { waitUntil: "domcontentloaded" });
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
        `${key}: no interactive targets were measurable — the page did not render`,
      ).toBeGreaterThan(0);

      if (result.belowTarget.length) {
        const aa = result.belowTarget.filter((e) => e.belowAAFloor);
        testInfo.annotations.push({
          type: "target-size-below-44",
          description:
            `${key}: ${result.belowTarget.length} non-ds target(s) < 44px ` +
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
        `${key}: design-system controls under 44px at 390px — the ` +
          "coarse-pointer block at the end of frontend/app/ds.css should " +
          `have enlarged them:\n${result.hardFailures
            .map((e) => `  ${e.what} ${e.size}`)
            .join("\n")}`,
      ).toEqual([]);

      // The AA ratchet: a sub-24px target the baseline does not list fails.
      const baseline = loadTargetBaseline();
      const { added, borderline, stale } = compareToTargetBaseline(
        result.belowTarget.filter((e) => e.belowAAFloor),
        baseline.routes[key] || [],
      );
      const project = testInfo.project.name;
      if (stale.length) {
        testInfo.annotations.push({
          type: "target-size-baseline-stale",
          description:
            `${key}: ${stale.length} baseline signature(s) not seen on ${project} — ` +
            "remove them from tests/e2e/mobile-target-baseline.json once no phone engine reports them: " +
            stale.join("; "),
        });
      }
      if (borderline.length) {
        testInfo.annotations.push({
          type: "target-size-new-within-tolerance",
          description:
            `${key}: new signature(s) within ${RATCHET_TOLERANCE_PX}px of the 24px floor on ${project}: ` +
            borderline.map((o) => `${o.sig} (${o.what} ${o.size})`).join("; "),
        });
      }
      // The baseline was MEASURED on `recordedOn` only.  Another engine
      // (WebKit renders native controls and text differently) reports its
      // new signatures instead of failing, until its run is folded in.
      if (!baseline.recordedOn.includes(project)) {
        if (added.length) {
          testInfo.annotations.push({
            type: "target-size-unbaselined-engine",
            description:
              `${key}: ${project} is not in the baseline's recordedOn; its sub-24px signatures ` +
              "absent from the baseline (fold them in, then add the project): " +
              added.map((o) => `${o.sig} (${o.what} ${o.size})`).join("; "),
          });
        }
        return;
      }
      expect(
        added.map((o) => `${o.sig}  (e.g. ${o.what} ${o.size})`),
        `${key}: NEW interactive target(s) under the 24px WCAG 2.5.8 AA floor at 390px. ` +
          "Enlarge them (frontend/app/ds.css coarse-pointer block, or the page's own CSS); " +
          "only a reviewed, deliberate exception belongs in tests/e2e/mobile-target-baseline.json",
      ).toEqual([]);
    });
  }
});
