/**
 * V1-109 — mobile-desktop parity (mobile usability for roster-heavy
 * views) verified on the DEPLOYED production site at 390x844.
 *
 * The four named defects (`inv 9.3` / `MFB-67` / `MFB-93`, code-level
 * fixes shipped in `#1086` + `#1131`, mutation-proved LOCALLY in
 * `tests/e2e/specs/mobile-pinned-overlap.spec.js`,
 * `tests/e2e/specs/mobile-touch-targets.spec.js` and
 * `tests/e2e/specs/mobile-type-floor.spec.js`) had never been measured
 * against the real deployed site — the row's required level is **L4**,
 * a production-consumer statement, which none of those local specs can
 * make (they run against the sandboxed dev stack). This spec is that
 * missing production-evidence lane, reusing the exact same in-page
 * measurement instruments (copied verbatim from the local specs — same
 * geometry probes, same thresholds) against `https://chaseupside.com`
 * with a real authenticated session.
 *
 * Runs on prod-mobile only (390x844, isMobile, hasTouch — configured at
 * the project level in prod-auth.config.js).
 */
const { test, expect, prodUrl, annotate, mobileOnly } = require("./helpers");

const BOARD_ROW = ".ds-table-wrap table tbody tr.rankings-row-clickable";
const MIN_HIT_PX = 24; // WCAG 2.5.8 AA — see mobile-touch-targets.spec.js header.
const STARS_TO_MEASURE = 3;
const MIN_FONT_PX = 10; // the audit's defect line — see mobile-type-floor.spec.js header.

// ── shared in-page instruments, copied verbatim from the local specs ────

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
      if (ox > 1 && oy > 1) found.push(`${a.name} x ${b.name} — ${ox}x${oy}px`);
    }
  }
  return found;
}

const MEASURE_STARS = (max) => {
  const hits = (btn, x, y) => {
    const el = document.elementFromPoint(x, y);
    return el === btn || btn.contains(el);
  };
  const stars = Array.from(
    document.querySelectorAll('button[aria-label$="watchlist"]'),
  ).filter((btn) => {
    const r = btn.getBoundingClientRect();
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
  const grouped = new Map();
  for (const o of offenders) {
    const key = `${o.px}|${o.el}`;
    if (!grouped.has(key)) grouped.set(key, { ...o, count: 0 });
    grouped.get(key).count += 1;
  }
  return { checked, offenders: Array.from(grouped.values()) };
};

test.describe("V1-109: mobile usability (390x844) on the deployed production site", () => {
  test("/trade — the sticky verdict tray is not covered by the screenshot FAB", async ({
    prodPage: page,
  }, testInfo) => {
    mobileOnly(test, testInfo);
    await page.goto(prodUrl("/trade"), { waitUntil: "domcontentloaded" });
    // Two sides render by default (frontend/app/trade/page.jsx), so the
    // tray mounts on a cold load — no trade setup required. Non-vacuity:
    // if the tray never rendered, the overlap check below would pass on
    // an empty box list, which is not evidence of anything.
    await expect(page.locator(".trade-sticky-tray")).toHaveCount(1, { timeout: 60_000 });
    await expect(page.locator(".screenshot-fab")).toHaveCount(1);

    const boxes = await page.evaluate(PINNED);
    const bad = overlaps(boxes);
    annotate(testInfo, "pinned-boxes", JSON.stringify(boxes));
    annotate(testInfo, "states-observed", `trade-tray-overlap: ${bad.length === 0 ? "none" : bad.join("; ")}`);
    expect(
      bad,
      `Pinned elements overlap at 390x844 on production: ${bad.join("; ")} ` +
        "(W26-F017 tray/FAB occlusion regression)",
    ).toEqual([]);
  });

  test("/rankings — each watchlist star's effective hit area is at least 24x24", async ({
    prodPage: page,
  }, testInfo) => {
    mobileOnly(test, testInfo);
    await page.goto(prodUrl("/rankings"), { waitUntil: "domcontentloaded" });
    await expect(page.locator(BOARD_ROW).first(), "rankings board should render rows").toBeVisible({
      timeout: 90_000,
    });
    await page.evaluate(() => {
      const el = document.querySelector('button[aria-label$="watchlist"]');
      if (el) el.scrollIntoView({ block: "center" });
    });
    await page.waitForTimeout(600);

    const stars = await page.evaluate(MEASURE_STARS, STARS_TO_MEASURE);
    annotate(testInfo, "stars-measured", JSON.stringify(stars));

    expect(
      stars.length,
      `expected at least ${STARS_TO_MEASURE} watchlist star buttons fully in the ` +
        "viewport on production — an empty sample would make this test vacuous",
    ).toBeGreaterThanOrEqual(STARS_TO_MEASURE);

    for (const s of stars) {
      expect(
        s.centerHits,
        `${s.label}: the button's own center does not hit-test to it on production`,
      ).toBe(true);
      expect(
        s.hitW,
        `${s.label}: effective hit width ${s.hitW}px < ${MIN_HIT_PX}px on production ` +
          `(border box ${s.rect.w}x${s.rect.h}) — the 17x13 star defect (W26-F017)`,
      ).toBeGreaterThanOrEqual(MIN_HIT_PX);
      expect(
        s.hitH,
        `${s.label}: effective hit height ${s.hitH}px < ${MIN_HIT_PX}px on production ` +
          `(border box ${s.rect.w}x${s.rect.h}) — the 17x13 star defect (W26-F017)`,
      ).toBeGreaterThanOrEqual(MIN_HIT_PX);
    }
  });

  for (const route of ["/rankings", "/rosters", "/draft"]) {
    test(`${route} — no visible text below 10px on production`, async ({
      prodPage: page,
    }, testInfo) => {
      mobileOnly(test, testInfo);
      await page.goto(prodUrl(route), { waitUntil: "domcontentloaded" });
      if (route === "/rankings") {
        await expect(page.locator(BOARD_ROW).first()).toBeVisible({ timeout: 90_000 });
      } else {
        await expect(page.locator("main table").first()).toBeVisible({ timeout: 60_000 });
      }
      if (route === "/draft") {
        // The page's smallest type (per-row "NEED" chips) mounts after
        // the roster-need computation lands — best-effort wait, the same
        // posture as the local spec (a board with no roster needs is
        // still a valid, if weaker, statement about what rendered).
        await page.waitForLoadState("networkidle", { timeout: 30_000 }).catch(() => {});
        await page.locator(".draft-need-chip-row").first().waitFor({ timeout: 15_000 }).catch(() => {});
        await page.waitForTimeout(1200);
      }

      const result = await page.evaluate(SCAN_TYPE, MIN_FONT_PX);
      annotate(
        testInfo,
        "type-scan",
        `${route}: checked=${result.checked} offenders=${result.offenders.length}`,
      );
      expect(
        result.checked,
        `${route}: only ${result.checked} text elements were measurable on production — ` +
          "the page did not render enough to make this scan meaningful",
      ).toBeGreaterThan(50);

      const lines = result.offenders
        .map((o) => `  ${o.px}px x${o.count}  ${o.el}  "${o.sample}"`)
        .join("\n");
      expect(
        result.offenders,
        `${route} ships text below ${MIN_FONT_PX}px at 390x844 on production (W26-F017):\n` +
          `${lines}\n` +
          "The design-system floor is --font-size-2xs (11px, docs/DESIGN-SYSTEM.md).",
      ).toEqual([]);
    });
  }
});
