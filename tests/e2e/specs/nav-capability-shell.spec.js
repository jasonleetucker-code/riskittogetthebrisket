/**
 * V1-131 — the capability gate, asserted on a REAL production build.
 *
 * WHY THIS EXISTS, and it is not a nice-to-have.
 * The first implementation of this feature threaded a `capabilities`
 * prop into `<CommandPalette>` from inside `InnerAppShell` — a component
 * that never received it. Every reference resolved to nothing and the
 * shell threw `ReferenceError: capabilities is not defined` the moment a
 * user pressed "/". The command palette stopped opening on every private
 * route.
 *
 * 2,363 frontend unit tests did not catch it, and could not have:
 * the component tests render `CommandPalette` directly and supply the
 * prop themselves, so the one thing that was broken — whether the prop
 * exists in the enclosing scope of the real shell — was exactly what
 * they stubbed out. The build was green too; a free variable is only an
 * error at runtime.
 *
 * So the guard has to be a browser, on a production build, pressing the
 * key. That is this file.
 *
 * WHAT IT ASSERTS
 *   1. the shell raises NO uncaught error on a private route;
 *   2. the "/" shortcut actually opens the palette;
 *   3. the gated destination is offered nowhere while it is unavailable;
 *   4. no second shell-level request to /api/consensus-edge/* — the
 *      request-budget half of V1-131, since V1-108 is VERIFIED and the
 *      whole reason the capability rides /api/auth/status is to avoid a
 *      per-page probe.
 *
 * SCOPE: gating and shell integrity only. Nothing here touches Consensus
 * Edge's methodology, scoring or flag default. If production ever runs
 * with the feature genuinely available, assertion 3 flips by design —
 * see the note on it.
 */
const { test, expect } = require("../helpers/auth-fixture");
const { pageUrl, awaitStreamSettled, isNavigationAbortedFetch } = require("../helpers/journey");

test.describe("V1-131: capability gate on the real shell", () => {
  test("the shell survives, the palette opens, and the gated page is not offered", async ({
    authedPage,
  }) => {
    const pageErrors = [];
    const consensusEdgeRequests = [];
    authedPage.on("pageerror", (err) => {
      if (!isNavigationAbortedFetch(err, authedPage)) pageErrors.push(String(err));
    });
    authedPage.on("request", (req) => {
      if (req.url().includes("/api/consensus-edge")) consensusEdgeRequests.push(req.url());
    });

    await authedPage.goto(pageUrl("/rankings"), { waitUntil: "domcontentloaded" });
    await awaitStreamSettled(authedPage);

    // 1. No uncaught error. This is the assertion that would have caught
    //    the InnerAppShell scope bug on the day it was written.
    expect(
      pageErrors,
      `Uncaught error(s) in the shell: ${pageErrors.join(" | ")}`,
    ).toEqual([]);

    // 2. The palette opens. Focus must leave any input first or the
    //    shortcut is swallowed by the focused field.
    //
    //    Wait for the shortcut to EXIST before pressing it.  The "/" listener
    //    is attached only once the client-side auth probe (/api/auth/status)
    //    resolves `authenticated === true`; the server-rendered HTML — and
    //    so the <h1> — is on screen before that.  Pressing "/" first is
    //    swallowed and never repeated, which is the intermittent V1-131
    //    failure (E2E Safety Net run 39465313078: the failure video shows
    //    the logged-out chrome for the first ~0.5 s, then the Search button;
    //    a throwaway spec delaying /api/auth/status by 1.5 s fails every
    //    time on origin/main and passes every time with this wait).  The
    //    readiness signal is the shell's own "Search" button: TopBar and
    //    MobileTopBar render it under the same condition that wires "/",
    //    and AppShell attaches the listener in a layout effect of that same
    //    commit, so a visible Search button means "/" works.
    await expect(
      authedPage.locator("header").getByRole("button", { name: "Search", exact: true }),
    ).toBeVisible({ timeout: 30_000 });
    await authedPage.locator("h1").first().click();
    await authedPage.keyboard.press("/");
    await expect(authedPage.getByLabel(/search players, picks/i)).toBeVisible({
      timeout: 10_000,
    });

    // 3. The gated destination is offered nowhere — menus, palette and
    //    site map all derive from one model, so one DOM-wide check
    //    covers the surfaces that are currently mounted.
    //
    //    Conditional on the capability the server actually publishes: if
    //    a future production state has Consensus Edge available, the
    //    correct assertion inverts. The invariant is AGREEMENT between
    //    what the server says and what the nav offers — never a flat
    //    "this link is absent".
    const available = await authedPage.evaluate(async () => {
      const res = await fetch("/api/auth/status");
      const body = await res.json();
      return body?.features?.consensusEdge?.available === true;
    });
    const links = authedPage.locator('a[href="/consensus-edge"]');
    if (available) {
      await expect(links.first()).toBeAttached();
    } else {
      await expect(links).toHaveCount(0);
    }

    // 4. No second shell-level probe was introduced.
    expect(
      consensusEdgeRequests,
      `The shell probed Consensus Edge directly: ${consensusEdgeRequests.join(", ")}. ` +
        `The capability rides /api/auth/status precisely so it does not.`,
    ).toEqual([]);
  });
});
