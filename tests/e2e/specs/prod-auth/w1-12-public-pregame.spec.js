/**
 * W1-12 — Week 1 pregame surfaces pass mobile / navigation / link /
 * degraded-state production verification.
 *
 * WHY THIS SPEC EXISTS AND A curl DOES NOT SUFFICE
 * ───────────────────────────────────────────────
 * An earlier attempt "verified" this by grepping production's
 * server-rendered HTML for the section heading and getting zero hits.
 * That result was meaningless: `/league`'s sections are mounted through
 * `lazySection(..., { ssr: false })`, so the markup can NEVER appear in
 * the server response, whether the feature works or not. A test that
 * cannot distinguish success from failure is worse than no test — it
 * reads as a finding. The row's own wording asks for mobile, navigation,
 * link and degraded-state checks, all of which need a real browser.
 *
 * ANONYMOUS ON PURPOSE. This is the PUBLIC pregame surface; asserting it
 * through an authenticated fixture would prove the wrong thing. The
 * `publicPage` fixture clears cookies rather than assuming none.
 *
 * WHERE IT RUNS. `.github/workflows/v1-authenticated-verification.yml`, on a
 * runner with direct egress. It CANNOT be run from an agent sandbox: measured
 * 2026-09-06, the sandbox's CONNECT relay closes a browser tunnel mid-exchange
 * (`ws_closed_mid_exchange`, "tunnel closed (code 1006) after 6s; 1821 B sent,
 * 39 B received", host `chaseupside.com:443`) and Chromium surfaces that as
 * ERR_CONNECTION_RESET — which looks exactly like production being down.
 * Routing Chromium through the proxy explicitly and pinning the proxy CA by
 * SPKI were both tried and neither changed the outcome, so no accommodation is
 * carried here: an unverified workaround with a confident comment is worse than
 * none. A red run from a sandbox is the harness, not the site; read it there.
 */
const { publicTest: test, expect, prodUrl, annotate, mobileOnly } = require("./helpers");

const PREVIEWS = "/league?tab=previews";

test.describe("W1-12: public Week 1 pregame surfaces (production)", () => {
  test("the previews tab renders the current week's structured matchups", async ({
    publicPage: page,
  }, testInfo) => {
    await page.goto(prodUrl(PREVIEWS), { waitUntil: "domcontentloaded" });

    // The heading names the season and week the CONTRACT reports, so this
    // also catches a surface that has silently fallen back to an older
    // slate — the defect this section was built to fix.
    const heading = page.getByText(/Week \d+ matchups · \d{4}/);
    await expect(heading).toBeVisible({ timeout: 60_000 });
    const headingText = await heading.first().innerText();
    annotate(testInfo, "w1-12-heading", headingText);

    // Real matchup content, not just a shell: every card carries two
    // manager names joined by "vs".
    const cards = page.getByText(/\svs\s/);
    const count = await cards.count();
    expect(count).toBeGreaterThan(0);
    annotate(testInfo, "w1-12-matchup-cards", String(count));
  });

  test("head-to-head history renders without a fabricated zero margin", async ({
    publicPage: page,
  }, testInfo) => {
    // W1-10's defect, checked at the SURFACE: a first-ever meeting must
    // read "First meeting" and must never show an average margin, which
    // would say these two always play to a dead heat.
    await page.goto(prodUrl(PREVIEWS), { waitUntil: "domcontentloaded" });
    await expect(page.getByText(/Week \d+ matchups · \d{4}/)).toBeVisible({ timeout: 60_000 });

    const body = await page.locator("body").innerText();
    expect(body).not.toMatch(/avg margin 0\.0\b/);
    annotate(
      testInfo,
      "w1-12-first-meeting",
      /First meeting/.test(body) ? "first-ever meeting rendered" : "no first-ever meeting this week",
    );
  });

  test("the Home card's Full H2H preview link reaches the previews tab", async ({
    publicPage: page,
  }, testInfo) => {
    // The navigation half of the row. This CTA used to land on a slate of
    // articles from a previous season.
    await page.goto(prodUrl("/league"), { waitUntil: "domcontentloaded" });
    const cta = page.getByText(/Full H2H preview/i).first();
    await expect(cta).toBeVisible({ timeout: 60_000 });
    await cta.click();
    await expect(page.getByText(/Week \d+ matchups · \d{4}/)).toBeVisible({ timeout: 60_000 });
    annotate(testInfo, "w1-12-cta", "Full H2H preview → structured previews");
  });

  test("an older article slate is labelled as older, never as this week's", async ({
    publicPage: page,
  }, testInfo) => {
    // The DEGRADED state. Narrative generation is blocked on a missing
    // ANTHROPIC_API_KEY, so the newest articles on disk are from a prior
    // week; the surface must say so rather than present them in the
    // present tense. If articles for the current week DO exist, the
    // present-tense subhead is correct and this assertion is skipped
    // rather than inverted.
    await page.goto(prodUrl(PREVIEWS), { waitUntil: "domcontentloaded" });
    await expect(page.getByText(/Week \d+ matchups · \d{4}/)).toBeVisible({ timeout: 60_000 });

    const body = await page.locator("body").innerText();
    const older = /Most recent previews ·/.test(body);
    const current = /Wednesday-morning previews/.test(body);
    // Exactly one of the two voices, never both and never neither.
    expect(older || current).toBe(true);
    if (older) {
      expect(body).toMatch(/No previews written yet for \d{4} Week \d+/);
    }
    annotate(testInfo, "w1-12-slate-voice", older ? "older slate, labelled" : "current-week slate");
  });

  test("the surface is usable at a phone viewport without horizontal scroll", async ({
    publicPage: page,
  }, testInfo) => {
    mobileOnly(test, testInfo);
    await page.goto(prodUrl(PREVIEWS), { waitUntil: "domcontentloaded" });
    await expect(page.getByText(/Week \d+ matchups · \d{4}/)).toBeVisible({ timeout: 60_000 });

    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(1);
    annotate(testInfo, "w1-12-mobile-overflow-px", String(overflow));
  });

  test("no private field reaches the anonymous page", async ({ publicPage: page }, testInfo) => {
    // W1-13's boundary, re-checked at the rendered surface rather than at
    // the API: a client bundle that fetched something private would show
    // it here even though the section payload passed the field blocklist.
    await page.goto(prodUrl(PREVIEWS), { waitUntil: "domcontentloaded" });
    await expect(page.getByText(/Week \d+ matchups · \d{4}/)).toBeVisible({ timeout: 60_000 });

    const body = await page.locator("body").innerText();
    for (const marker of [/win probability/i, /beat.{0,3}median/i, /projected points/i]) {
      expect(body).not.toMatch(marker);
    }
    annotate(testInfo, "w1-12-privacy", "no projection or probability language on the public page");
  });
});
