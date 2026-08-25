/**
 * V1-109 / W26-F017 — the /rankings watchlist star is actually tappable.
 *
 * THE DEFECT, measured at 390x844 (evidence/V1-109/RE_MEASUREMENT_2026-08-24.md,
 * re-reproduced 2026-08-25 on the current tree): the per-row watchlist
 * star buttons render at 17x13px — the worst interactive targets on
 * /rankings, repeated once per row, failing not just WCAG 2.5.5 (44x44)
 * but WCAG 2.5.8 AA (24x24) in BOTH dimensions.
 *
 * WHY THE REPAIR IS INVISIBLE TO getBoundingClientRect. Growing the
 * button would change row height, and row height is load-bearing for the
 * V1-106 windowing (useRowWindow measures real row blocks) — that row is
 * VERIFIED and frozen. So the repair is hit-area expansion: a centered,
 * invisible ::after pseudo-element on the button (board.module.css
 * .watchStar), which enlarges what a finger can hit without moving a
 * single laid-out box. The border box stays 17x13, which is exactly why
 * the V1-109 re-measurement pass declined to ship this without hit-area
 * instrumentation: a rect-based instrument cannot tell the repair from a
 * no-op.
 *
 * THE INSTRUMENT, therefore: document.elementFromPoint. From each star's
 * visual center we walk outward 1px at a time along both axes and count
 * the contiguous span of points that still hit-test to that button (a
 * point over the pseudo-element resolves to its originating element).
 * That is the browser's own answer to "where can a tap land", and it sees
 * pseudo-element hit areas, sibling occlusion and stacking — everything a
 * rect cannot.
 *
 * THE BAR is WCAG 2.5.8 AA (24x24), not 44x44, and that is honest rather
 * than lenient: board rows repeat every ~34px, so two 44px-tall zones on
 * adjacent rows necessarily overlap and the later row's zone wins the
 * contested strip. The pseudo-element is 44x44; the GUARANTEED effective
 * area is 44 wide by ~row-height tall. Asserting 44x44 effective would
 * demand taller rows — the exact change V1-106 forbids.
 *
 * Cross-row integrity travels with the expansion: each star's own center
 * must still resolve to that star, so one row's enlarged zone may never
 * swallow its neighbour's control (the failure mode where every tap
 * toggles the wrong player).
 */
const { test, expect } = require("../helpers/auth-fixture");
const { gotoRankingsBoard } = require("../helpers/journey");

const MOBILE = { width: 390, height: 844 };
const MIN_HIT_PX = 24; // WCAG 2.5.8 AA — see header for why not 44.
const STARS_TO_MEASURE = 3;

/**
 * Runs IN the page. For up to `max` watchlist-star buttons fully inside
 * the viewport, measures the contiguous hit-test extent through the
 * button's visual center along both axes.
 */
const MEASURE_STARS = (max) => {
  const hits = (btn, x, y) => {
    const el = document.elementFromPoint(x, y);
    return el === btn || btn.contains(el);
  };
  const stars = Array.from(
    document.querySelectorAll('button[aria-label$="watchlist"]'),
  ).filter((btn) => {
    const r = btn.getBoundingClientRect();
    // Fully on-screen with margin for the probe walk, and below any
    // pinned header chrome.
    return (
      r.width > 0 &&
      r.height > 0 &&
      r.left > 50 &&
      r.right < window.innerWidth - 50 &&
      r.top > 150 &&
      r.bottom < window.innerHeight - 150
    );
  });
  const out = [];
  for (const btn of stars.slice(0, max)) {
    const r = btn.getBoundingClientRect();
    const cx = r.left + r.width / 2;
    const cy = r.top + r.height / 2;
    const centerHits = hits(btn, cx, cy);
    let left = 0;
    let right = 0;
    let up = 0;
    let down = 0;
    if (centerHits) {
      // Contiguous runs, capped at 40px per direction (the pseudo is 44).
      while (left < 40 && hits(btn, cx - (left + 1), cy)) left++;
      while (right < 40 && hits(btn, cx + (right + 1), cy)) right++;
      while (up < 40 && hits(btn, cx, cy - (up + 1))) up++;
      while (down < 40 && hits(btn, cx, cy + (down + 1))) down++;
    }
    out.push({
      label: (btn.getAttribute("aria-label") || "").slice(0, 50),
      rect: { w: Math.round(r.width), h: Math.round(r.height) },
      centerHits,
      hitW: left + right + 1,
      hitH: up + down + 1,
    });
  }
  return out;
};

test.describe("mobile 390px: rankings watchlist stars have a real hit area", () => {
  test.use({ viewport: MOBILE, isMobile: true, hasTouch: true });

  test("/rankings — each star's effective (elementFromPoint) hit area is at least 24x24", async ({
    authedPage,
  }) => {
    await authedPage.setViewportSize(MOBILE);
    await gotoRankingsBoard(authedPage);

    // At 390px the header + controls fill the first screen and the board's
    // rows start below the fold (measured: first star at y=1161 in an
    // 844px viewport). elementFromPoint only answers for on-screen points,
    // so bring the rows to the middle of the viewport first, then give the
    // V1-106 windowing a beat to settle the newly mounted rows.
    await authedPage.evaluate(() => {
      const el = document.querySelector('button[aria-label$="watchlist"]');
      if (el) el.scrollIntoView({ block: "center" });
    });
    await authedPage.waitForTimeout(600);

    const stars = await authedPage.evaluate(MEASURE_STARS, STARS_TO_MEASURE);

    // Non-vacuity: a board with no measurable stars proves nothing. The
    // windowed board mounts ~40 rows, each with a star; if none qualify
    // the page (or the selector) has changed and this test must say so
    // rather than pass on an empty sample.
    expect(
      stars.length,
      "expected at least " +
        `${STARS_TO_MEASURE} watchlist star buttons fully in the viewport — ` +
        "an empty sample would make this test vacuous",
    ).toBeGreaterThanOrEqual(STARS_TO_MEASURE);

    for (const s of stars) {
      // Specificity: the star's own center resolves to that star. This is
      // both the non-vacuous half of the probe and the guard against one
      // row's expanded zone swallowing its neighbour's control.
      expect(
        s.centerHits,
        `${s.label}: the button's own center does not hit-test to it — ` +
          "something is stacked over the control",
      ).toBe(true);
      expect(
        s.hitW,
        `${s.label}: effective hit width ${s.hitW}px < ${MIN_HIT_PX}px ` +
          `(border box ${s.rect.w}x${s.rect.h}) — the 17x13 star defect (W26-F017)`,
      ).toBeGreaterThanOrEqual(MIN_HIT_PX);
      expect(
        s.hitH,
        `${s.label}: effective hit height ${s.hitH}px < ${MIN_HIT_PX}px ` +
          `(border box ${s.rect.w}x${s.rect.h}) — the 17x13 star defect (W26-F017)`,
      ).toBeGreaterThanOrEqual(MIN_HIT_PX);
    }
  });
});
