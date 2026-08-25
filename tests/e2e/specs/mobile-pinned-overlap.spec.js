/**
 * V1-109 / W26-F015 — a pinned bottom tray is not covered by the FAB.
 *
 * THE DEFECT, measured at 390x844 on 2026-08-24 before the fix:
 *
 *   .trade-sticky-tray   y 714  h 74  full width  z-index 35
 *   .screenshot-fab      y 734  44x44 at x 334    z-index 900
 *
 * The FAB sat ENTIRELY INSIDE the tray, occluding its right-hand 44x44
 * corner. Both are anchored to the same bottom baseline, so the base
 * rule's +16px lift never cleared a 74px tray — it parked the FAB in the
 * middle of it. That is the audit's "sticky verdict bar is clipped by a
 * floating action button", still reproducing two rounds of feature work
 * later.
 *
 * WHY AN E2E TEST AND NOT A UNIT TEST.
 * The defect is pure layout: two `position: fixed` boxes, a z-index, a
 * `calc()` with `env(safe-area-inset-bottom)`, and a media query whose
 * outcome depends on SOURCE ORDER within globals.css. jsdom computes
 * none of that — it would report both boxes at 0x0 and pass. Only a real
 * engine laying out the real stylesheet can see this.
 *
 * The first attempt at the fix is why the source-order note matters: the
 * mobile override was placed in the `@media (max-width: 768px)` block at
 * ~line 1880, which loses on source order to the identically-specific
 * base rule at ~3150. Overlap fell only 44x44 -> 44x30, because mobile
 * silently took the desktop offset and dropped the 56px nav term. This
 * test is what caught the difference between "moved" and "fixed".
 *
 * SCOPE: this asserts the INVARIANT (no two pinned elements overlap),
 * not the specific offset. A future redesign may move either element
 * anywhere it likes; what it may not do is put one on top of the other.
 */
const { test, expect } = require("../helpers/auth-fixture");
const { pageUrl, awaitStreamSettled } = require("../helpers/journey");

const MOBILE = { width: 390, height: 844 };

/** Rects of every visible position:fixed/sticky box, in the page. */
const PINNED = () => {
  const out = [];
  for (const el of document.querySelectorAll("body *")) {
    const s = getComputedStyle(el);
    if (s.position !== "fixed" && s.position !== "sticky") continue;
    if (s.display === "none" || s.visibility === "hidden" || Number(s.opacity) === 0) continue;
    if (el.closest('[aria-hidden="true"]')) continue;
    const r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) continue;
    out.push({
      name: `${el.tagName.toLowerCase()}.${String(el.className || "").trim().split(/\s+/)[0] || "(none)"}`,
      x: Math.round(r.x),
      y: Math.round(r.y),
      w: Math.round(r.width),
      h: Math.round(r.height),
    });
  }
  return out;
};

function overlaps(boxes) {
  const found = [];
  for (let i = 0; i < boxes.length; i++) {
    for (let j = i + 1; j < boxes.length; j++) {
      const a = boxes[i];
      const b = boxes[j];
      const ox = Math.min(a.x + a.w, b.x + b.w) - Math.max(a.x, b.x);
      const oy = Math.min(a.y + a.h, b.y + b.h) - Math.max(a.y, b.y);
      // >1px, so adjacent sticky table headers sharing a border edge do
      // not register as an occlusion. The real defect measured 44x44.
      if (ox > 1 && oy > 1) {
        found.push(`${a.name} x ${b.name} — ${ox}x${oy}px`);
      }
    }
  }
  return found;
}

test.describe("mobile 390px: pinned chrome does not occlude itself", () => {
  test.use({ viewport: MOBILE, isMobile: true, hasTouch: true });

  test("/trade — the sticky tray is not covered by the screenshot FAB", async ({ authedPage }) => {
    await authedPage.setViewportSize(MOBILE);
    await authedPage.goto(pageUrl("/trade"), { waitUntil: "domcontentloaded" });
    await awaitStreamSettled(authedPage);
    // The tray is the subject; if it never rendered, this test would pass
    // vacuously — which on a layout assertion reads as a clean result for
    // a page that has no tray at all.
    await expect(authedPage.locator(".trade-sticky-tray")).toHaveCount(1);
    await expect(authedPage.locator(".screenshot-fab")).toHaveCount(1);

    const boxes = await authedPage.evaluate(PINNED);
    const bad = overlaps(boxes);
    expect(
      bad,
      `Pinned elements overlap at 390x844: ${bad.join("; ")}. ` +
        `One is covering the other — see the header of this spec.`,
    ).toEqual([]);
  });
});
