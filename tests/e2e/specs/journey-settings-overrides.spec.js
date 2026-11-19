/**
 * Critical journey: the settings Ranking Sources panel and the withdrawn
 * custom source mix.
 *
 * The single-source-of-truth override path (see CLAUDE.md): a custom source
 * mix rides POST /api/rankings/overrides — there is NO frontend ranking
 * engine.  Custom source weighting is WITHDRAWN (#875,
 * `_SOURCE_OVERRIDES_DISABLED` in src/api/data_contract.py), because a
 * user-weighted board published under rankDerivedValue is a second
 * canonical valuation truth.
 *
 * Since PR #2224 /settings says so instead of pretending otherwise: the
 * Ranking Sources panel states that custom mixes are switched off, its
 * include controls are disabled (the registry default) and point at that
 * statement, the weight inputs are gone, and the Status column is the
 * backend's own `sourceVotingStatus` — not a browser-computed "Live"/"Idle"
 * from per-row coverage.  Until then these tests waited for that
 * browser-computed "Live" and clicked an operable include toggle; both
 * asserted the defect the PR removed.
 *
 * A device can still carry a saved mix (the /rankings Sources popover
 * writes one, and so did every pre-withdrawal /settings), and that mix
 * still rides the override POST.  The round-trip is asserted end-to-end
 * from such a saved mix: the response must carry the withdrawal contract —
 * an explicit warning, no custom mix reported active, the switched-off
 * source still blended — /settings must say the saved mix is not applied,
 * and the rankings page must NOT show the custom-mix badge.
 *
 * Auth: test-only session fixture (skips when E2E_TEST_SECRET unset).
 * State: settings live in localStorage — each test gets a fresh browser
 * context, so a seeded mix never leaks between tests.
 */
const { test, expect } = require("../helpers/auth-fixture");
const {
  gotoRankingsBoard,
  attachConsoleGuards,
  boardRowCount,
  pageUrl,
} = require("../helpers/journey");

// frontend/lib/trade-logic.js::SETTINGS_KEY — where useSettings keeps this
// device's preferences, `siteWeights` (the custom source mix) among them.
const SETTINGS_KEY = "next_settings_v2";
// The panel's own statement (settings/page.jsx::CUSTOM_MIX_OFF_NOTE).
const CUSTOM_MIX_OFF = "Custom source mixes are switched off";

test.describe("journey: settings ranking sources @desktop-only", () => {

  test("settings lists every registered ranking source, says custom mixes are off, and shows the backend's voting status", async ({ authedPage: page }) => {
    // Authoritative registry size from the backend.
    const regRes = await page.request.get("/api/rankings/sources");
    expect(regRes.status()).toBe(200);
    const registry = await regRes.json();
    const sources = registry.sources || registry;
    const registeredCount = Array.isArray(sources)
      ? sources.length
      : Object.keys(sources).length;
    expect(registeredCount).toBeGreaterThan(3);

    // The backend's per-source voting report: the contract's
    // `sourceVotingStatus` block (src/sources/voting_status.py), served here
    // as `votingStatus` from the same loaded contract the page reads.  The
    // Status column must show exactly these labels.
    const weightingRes = await page.request.get("/api/sources/weighting");
    expect(weightingRes.status(), "the source voting report must be served").toBe(200);
    const votingSources = ((await weightingRes.json()).votingStatus?.sources || []).filter(
      (e) => e && typeof e.key === "string" && e.key,
    );
    expect(
      votingSources.length,
      "the board must report per-source voting status",
    ).toBeGreaterThan(3);
    const backendLabels = votingSources.map((e) => [e.key, String(e.statusLabel || "").trim()]);

    await page.goto(pageUrl("/settings"), { waitUntil: "domcontentloaded" });
    await expect(page.locator("body")).toContainText(/Ranking Sources/i, { timeout: 30_000 });

    // Scoped to the Ranking Sources panel (the one its section button
    // controls): the collapsed Rest-of-Season section keeps its own source
    // table, with the same classes, in the DOM.
    const sectionButton = page.getByRole("button", { name: /^Ranking Sources/ });
    const panelId = await sectionButton.getAttribute("aria-controls");
    expect(panelId, "the Ranking Sources section names the panel it controls").toBeTruthy();
    const section = page.locator(`[id="${panelId}"]`);
    // One row per registered dynasty source.
    const rows = section.locator(".settings-sources-table tbody > tr");
    await expect(rows).toHaveCount(registeredCount, { timeout: 30_000 });

    // The panel states why nothing in it can be changed, and a fresh device
    // has no saved mix to warn about.
    await expect(section.getByTestId("custom-mix-off-note")).toContainText(CUSTOM_MIX_OFF);
    await expect(section.getByTestId("saved-source-mix")).toHaveCount(0);

    // Settled state: the Status column shows the BACKEND's label for every
    // source the voting report covers, and a source it does not cover says
    // so (or states its private vote state) — never a browser-computed
    // "Live"/"Idle", and never still "Loading…".  The old wait for "Live"
    // passed on per-row coverage, which says a source has a value on a row,
    // not that it voted.  Polled as one comparison: the page polls the
    // board, so it never goes idle.
    const nonVotingLabel =
      /Shadow — not voting|Collected — not voting|Rolled back — not voting|Unavailable/;
    await expect
      .poll(
        () =>
          rows.evaluateAll(
            (trs, [labels, nonVotingSrc]) => {
              const byKey = new Map(labels);
              const nonVoting = new RegExp(nonVotingSrc);
              const mismatches = [];
              for (const tr of trs) {
                const key = (tr.getAttribute("data-testid") || "").replace(/^settings-src-row-/, "");
                const cell = tr.querySelector(`[data-testid="settings-src-status-${key}"]`);
                const status = (cell?.textContent || "").replace(/\s+/g, " ").trim();
                if (byKey.has(key)) {
                  if (status !== byKey.get(key)) {
                    mismatches.push({ key, status, expected: byKey.get(key) });
                  }
                } else if (status !== "Not reported" && !nonVoting.test(status)) {
                  mismatches.push({ key, status, expected: "Not reported, or a vote state" });
                }
              }
              return mismatches;
            },
            [backendLabels, nonVotingLabel.source],
          ),
        {
          message: "the Status column must show the backend's sourceVotingStatus label for every source",
          timeout: 30_000,
        },
      )
      .toEqual([]);

    // Every row offers the include control, OR states why it cannot: a
    // private source that does not vote on this host (Signals / DLF private
    // boards when not provisioned) shows its vote state instead of a control
    // (settings/page.jsx, lib/source-vote-state.js).  The include control is
    // the registry DEFAULT and is NOT operable: disabled, its name says
    // custom mixes are switched off, and it is described by the panel's
    // statement.  No row carries an editable weight.  One DOM snapshot, so a
    // re-render cannot land between two counts.
    const snapshot = await rows.evaluateAll(
      (trs, offText) =>
        trs.map((tr) => {
          const toggles = [
            ...tr.querySelectorAll('input.settings-src-toggle[aria-label^="Include "]'),
          ];
          return {
            key: (tr.getAttribute("data-testid") || "").replace(/^settings-src-row-/, ""),
            toggles: toggles.length,
            operable: toggles.filter((t) => !t.disabled).length,
            explained: toggles.filter((t) => {
              const described = (t.getAttribute("aria-describedby") || "")
                .split(/\s+/)
                .filter(Boolean)
                .map((id) => document.getElementById(id)?.textContent || "")
                .join(" ");
              return (
                /custom mixes are switched off/i.test(t.getAttribute("aria-label") || "") &&
                described.includes(offText)
              );
            }).length,
            weightInputs: tr.querySelectorAll('input[type="number"], input.weight-input').length,
            text: tr.innerText.replace(/\s+/g, " ").trim(),
          };
        }),
      CUSTOM_MIX_OFF,
    );
    expect(snapshot).toHaveLength(registeredCount);
    const unexplained = snapshot.filter((r) => r.toggles !== 1 && !nonVotingLabel.test(r.text));
    expect(unexplained, "source rows with neither an include control nor a vote state").toEqual([]);
    expect(snapshot.filter((r) => r.toggles === 1).length).toBeGreaterThan(3);
    expect(
      snapshot.filter((r) => r.operable > 0).map((r) => r.key),
      "no include control may be operable while custom source mixes are switched off",
    ).toEqual([]);
    expect(
      snapshot.filter((r) => r.toggles !== r.explained).map((r) => r.key),
      "every include control must say why it cannot be changed",
    ).toEqual([]);
    expect(
      snapshot.filter((r) => r.weightInputs > 0).map((r) => r.key),
      "no source weight may be editable while custom source mixes are switched off",
    ).toEqual([]);
  });

  test("a saved source mix round-trips, and the withdrawn custom mix is ignored rather than applied", async ({ authedPage: page }) => {
    // Each overrides POST rebuilds the full blend server-side on a
    // memo miss (CPU-seconds per call), and this journey triggers it
    // twice — once from /settings, once when /rankings rehydrates.
    // Give the whole round-trip more than the default budget.
    test.setTimeout(180_000);
    const guard = attachConsoleGuards(page);

    // Collect the app's base-contract fallback warnings from the START of
    // the journey.  This listener used to be attached further down, after
    // the first round-trip had already been asserted — so it watched an
    // arbitrary window that began once the thing it was diagnosing had
    // already succeeded.  Its output is now folded into the badge failure
    // message below, which is the only place it is read.
    const fallbackWarnings = [];
    page.on("console", (msg) => {
      if (msg.type() !== "warning") return;
      const text = msg.text() || "";
      if (text.includes("/api/rankings/overrides") || text.includes("falling through to base contract")) {
        fallbackWarnings.push(text);
      }
    });

    // The withdrawal contract below is asserted in registry-KEY vocabulary
    // (`rankingsOverride.enabledSources` carries registry keys).
    const regRes = await page.request.get("/api/rankings/sources");
    expect(regRes.status()).toBe(200);
    const registrySources = ((await regRes.json()).sources || []).filter(Boolean);
    const disabledKey = registrySources.find(
      (s) => typeof s.key === "string" && s.key,
    )?.key;
    expect(disabledKey, "the registry must name at least one source key").toBeTruthy();

    // A saved mix with one registered source switched off: the
    // `siteWeights` shape the /rankings Sources popover (and every
    // pre-withdrawal /settings toggle) writes.  /settings no longer offers an
    // operable control that writes it, so the mix is put where a returning
    // device carries it: this device's settings in localStorage.  Merged, so
    // anything already stored survives; idempotent on every navigation.
    await page.addInitScript(
      ([storageKey, key]) => {
        try {
          const raw = window.localStorage.getItem(storageKey);
          const parsed = raw ? JSON.parse(raw) : {};
          const stored = parsed && typeof parsed === "object" ? parsed : {};
          const weights =
            stored.siteWeights && typeof stored.siteWeights === "object"
              ? stored.siteWeights
              : {};
          stored.siteWeights = { ...weights, [key]: { include: false } };
          window.localStorage.setItem(storageKey, JSON.stringify(stored));
        } catch {
          // Storage unavailable: the POST wait below times out and says so.
        }
      },
      [SETTINGS_KEY, disabledKey],
    );

    // The round-trip contract: loading /settings with the saved mix must
    // fire POST /api/rankings/overrides and it must succeed.  60s budget:
    // the POST only fires after useDynastyData's base-contract fetch
    // (~5 MB) settles, which can take a while on a busy runner.
    const [overridesResponse] = await Promise.all([
      page.waitForResponse(
        (res) =>
          res.url().includes("/api/rankings/overrides") &&
          res.request().method() === "POST",
        { timeout: 60_000 },
      ),
      page.goto(pageUrl("/settings"), { waitUntil: "domcontentloaded" }),
    ]);
    expect(
      overridesResponse.status(),
      "overrides endpoint should answer the saved mix successfully",
    ).toBe(200);

    // /settings names the saved mix, says it is not applied, offers to clear
    // it, and states that custom mixes are switched off.
    await expect(page.getByTestId("saved-source-mix")).toContainText(
      "It is not applied to any value",
      { timeout: 30_000 },
    );
    await expect(
      page.getByRole("button", { name: "Clear saved source mix" }),
    ).toBeEnabled();
    await expect(page.getByTestId("custom-mix-off-note")).toContainText(CUSTOM_MIX_OFF);

    // Read the delta by REPLAYING the captured body through the API
    // request context — deliberately NOT `overridesResponse.json()`.
    // Playwright's `.json()` waits for the browser to finish loading
    // the response body, and the app drains this ~4.7 MB body only
    // after its base-contract fetch resolves
    // (dynasty-data.js::_postOverridesAndMerge); when it falls through
    // to the base contract instead, the body is never consumed,
    // `.json()` has no timeout of its own, and the test burns its whole
    // budget — the 180s retry hang in E2E runs 140/142.  The replay
    // posts the byte-identical body straight to the backend: the memo
    // key is derived from the request's normalized inputs, so the
    // replay is served from the same slot the page's own POST
    // populated, with no dependence on the page draining anything.
    const postData = overridesResponse.request().postData();
    expect(postData, "the saved-mix POST must carry a JSON body").toBeTruthy();
    const overridesUrl = new URL(overridesResponse.url());
    const replay = await page.request.post(
      overridesUrl.pathname + overridesUrl.search,
      {
        headers: { "content-type": "application/json" },
        data: postData,
        timeout: 60_000,
      },
    );
    expect(
      replay.status(),
      "replaying the captured overrides body against the backend should succeed",
    ).toBe(200);
    const delta = await replay.json();

    // The delta payload really is a delta carrying recomputed
    // per-player rows.  (The assertion this replaces counted `delta`'s
    // top-level keys after falling through `delta.players ||
    // delta.playersDelta || delta` — neither key exists on the delta
    // shape, so it was vacuously green on any non-empty response.)
    expect(delta.mode, "the ?view=delta response must be a delta").toBe(
      "delta",
    );
    expect(Array.isArray(delta.rankingsDelta?.players)).toBe(true);
    expect(delta.rankingsDelta.players.length).toBeGreaterThan(50);

    // The withdrawal contract (#875, `_SOURCE_OVERRIDES_DISABLED` in
    // src/api/data_contract.py): user source weighting must not mint a
    // second canonical board.  The endpoint accepts the saved mix, but
    // 1) it says explicitly that the weighting was ignored,
    expect(
      delta.warnings || [],
      "the overrides response must state that custom weighting is withdrawn",
    ).toEqual(
      expect.arrayContaining([
        expect.stringContaining("custom source weighting is disabled"),
      ]),
    );
    // 2) it reports no custom mix as active,
    const rankingsOverride = delta.rankingsOverride || {};
    expect(
      rankingsOverride.isCustomized,
      "no custom mix may be reported as active",
    ).toBe(false);
    // 3) and the switched-off source stays in the blend.
    expect(
      rankingsOverride.enabledSources || [],
      "the disabled source must still be blended — the override is ignored, not applied",
    ).toContain(disabledKey);

    // The rankings board must still render, and /rankings must re-fire
    // its own overrides POST on hydration — the round-trip machinery is
    // intact even though the weighting itself is withdrawn.
    //
    // This block used to `test.skip` when the badge never appeared AND
    // the app had logged its base-contract fallback warning.  That reads
    // as honest — the first round-trip IS hard-asserted above — but
    // docs/e2e-assertion-audit.md measured the skip firing ROUTINELY,
    // reason "...Failed to fetch".  A product degradation that reports as
    // a green skip is the one thing tests/e2e/README.md's convention 5
    // forbids: "Skip cleanly on absent INFRA — never on absent DATA."  A
    // degraded overrides endpoint is the product failing, not absent
    // infrastructure.
    //
    // The audit's own remedy was "a floor on consecutive skips, or
    // removal once the endpoint is reliable".  Playwright keeps no
    // cross-run state, so a consecutive-skip floor means a new counter
    // in e2e.yml — more machinery than the thing it guards, firing a day
    // late, and a second place where "green" gets computed.
    //
    // So: removal, with a MORE specific assertion in its place rather
    // than a weaker one.  /rankings fires its OWN overrides POST during
    // hydration; that second round-trip is what the badge depends on and
    // what the skip was silently forgiving.  Assert it directly, so a
    // failure says "the second overrides POST returned 503" instead of
    // "badge missing, cause unknown".  The underlying fragility is
    // docs/e2e-assertion-audit.md §3.3 — the Next proxy routes' hard 3s
    // abort — which is product-side and not this spec's to hide.
    //
    // Note this also restores guard.assertClean() below: test.skip()
    // throws, so on the skip path every browser console error collected
    // on this journey was discarded too.
    // NOTE: only `.status()` is read off this response — it is
    // header-derived and safe.  Its BODY is deliberately never read:
    // see the replay note above for why `.json()` on a page-initiated
    // overrides response can hang for the whole test budget.
    const rehydrateOverrides = page
      .waitForResponse(
        (res) =>
          res.url().includes("/api/rankings/overrides") &&
          res.request().method() === "POST",
        { timeout: 90_000 },
      )
      .catch(() => null);

    const rows = await gotoRankingsBoard(page);
    // WINDOWED BOARD: `rows.count()` counts MOUNTED rows, and since #912
    // the board mounts roughly a viewport's worth (~28) instead of all
    // ~1,100.  Asserting >50 mounted rows would now fail on a correct
    // board.  `boardRowCount` reads the table's published `aria-rowcount`,
    // which is the true logical total — the quantity this assertion was
    // always about.  `rows.count() > 0` keeps the separate claim that
    // something is actually on screen.
    expect(await boardRowCount(page)).toBeGreaterThan(50);
    expect(await rows.count(), "no board rows mounted").toBeGreaterThan(0);

    const rehydrateResponse = await rehydrateOverrides;
    expect(
      rehydrateResponse,
      "/rankings should re-fire the overrides POST on hydration — without it the custom mix is never applied",
    ).not.toBeNull();
    expect(
      rehydrateResponse.status(),
      "the /rankings-side overrides round-trip should also recompute successfully",
    ).toBe(200);

    // The custom-mix badge must NOT appear: the backend ignored the
    // weighting, so showing the badge would claim a custom board that
    // was never produced.  (This spec asserted the badge VISIBLE until
    // #875 withdrew custom weighting — the stale expectation behind the
    // failures in E2E runs 140/142.)  10s wait: the board rendered and
    // the rehydrate POST completed above, so anything that would mount
    // the badge has already happened.
    const badge = page.locator('[aria-label="Custom source mix active"]').first();
    const badgeVisible = await badge
      .waitFor({ state: "visible", timeout: 10_000 })
      .then(() => true)
      .catch(() => false);
    expect(
      badgeVisible,
      `the custom-mix badge must NOT appear while source weighting is withdrawn — showing it would claim an override the backend ignored${
        fallbackWarnings.length > 0
          ? ` — the app logged a base-contract fallback: ${fallbackWarnings[0]}`
          : ""
      }`,
    ).toBe(false);

    guard.assertClean();
  });
});
