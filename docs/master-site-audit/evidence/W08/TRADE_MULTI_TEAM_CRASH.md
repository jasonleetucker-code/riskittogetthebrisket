# /trade multi-team crash — `defaultDestination` was never imported

**Class:** live production crash, frontend. **Status at time of writing:** REPAIRED.
**Workstream:** W08 (trade calculator). Reported by the owner from a live mobile session;
reproduced and root-caused here on current HEAD rather than accepted from the report.

---

## 1. Symptom

Opening `/trade` and going to three or more teams — or reloading the page with a saved
3+-side workspace — throws and drops the page into its error boundary:

```
ReferenceError: Can't find variable: defaultDestination      (WebKit wording)
ReferenceError: defaultDestination is not defined            (V8 wording)
```

The whole 3+-team feature is unreachable. This is broader than the owner's report suggested:
the report described a mobile/WebKit crash, which reads like a browser-specific rendering
problem. It is neither mobile-specific nor WebKit-specific — see §4.

## 2. Reproduction

Two independent paths, both in `frontend/__tests__/components/trade-multi-team-destinations.test.jsx`:

**(a) Hydration.** Seed `localStorage["next_trade_workspace_v1"]` with a three-side workspace
that has at least one asset staged on any side, then load `/trade`. The workspace-hydration
effect (`page.jsx:527`) seeds a destination per staged asset and throws.

**(b) Add Team.** Load `/trade` with a two-side workspace and one asset staged, then click
**Add team**. `addTeam` (`page.jsx:994`) seeds an explicit destination for every already-staged
asset and throws.

The staged asset is load-bearing in both. `addTeam`'s seeding loop is
`for (const asset of s.assets)`, so an **empty** board never reaches the call — the first
version of the regression test passed for that reason and was wrong. A reproduction that
starts from an empty board will not fail.

Verified RED against the unfixed page: 2 failed / 1 passed, throwing at `page.jsx:356` and
`page.jsx:993` (pre-fix line numbers). Path (b) also reproduces in a real browser on the
production build — see §7; path (a) does not, and §7 says why.

## 3. Root cause

`defaultDestination` is exported from `frontend/lib/trade-logic.js:1391` and was called at
nine sites in `frontend/app/trade/page.jsx` — 356, 527, 613, 856, 994, 1020, 1027, 1166, 1584
(post-fix numbering) — **without ever being imported**.

It is an un-imported *free variable*, not a bad named import. That distinction is the whole
reason this shipped:

* A bad named import fails at module evaluation, so the page never renders and any smoke test
  catches it.
* A free variable is compiled to a plain identifier lookup. Bundlers resolve it as a global at
  runtime, so the module loads cleanly, `/trade` renders, two-team trades work perfectly, and
  the `ReferenceError` is thrown only when a call site actually executes.

Every one of the nine call sites is behind either multi-side routing or per-asset destination
seeding, so the two-team path — which is what every existing test and every smoke check
exercises — never touches it.

### When it was introduced

| commit | date | effect |
|---|---|---|
| `5bddb3def` | 2026-04-21 | feature lands ("Add per-asset destination routing for 3+-team trades", #209) — **import present** |
| `45c48cb2a` | 2026-04-23 | import present |
| `c7b6492f4` | 2026-05-19 | import present (line 35 of the `@/lib/trade-logic` block) |
| **`49e005b2a`** | **2026-07-26** | **"Redesign R4: draft war room + trade surfaces" (#552) — deletes `defaultDestination,` from the import block and one of the call sites; nine call sites survive** |

The redesign removed one call site and the import together, which is the signature of an
unused-import cleanup that only accounted for the call it had just deleted. `/trade` has been
broken for 3+ teams since 2026-07-26.

`8560e9bcc` ("fix(trade): the search box offers the current rookie class again") was the
suspect, being this engagement's most recent touch of the file. It is exonerated: the crash
reproduces at `8560e9bcc~1` and that commit does not touch `defaultDestination` at all.

## 4. Affected path — what is and is not browser-specific

Nothing about this is engine-specific. An undeclared identifier reference is a `ReferenceError`
in every ECMAScript engine; V8 and JavaScriptCore differ only in the message string. The owner
saw it on mobile/WebKit because that is where they were, not because of where it fires.

Nor is it environment-specific in the way a build error would be: `npm run build` compiles the
page cleanly **before and after** the fix, because a bundler cannot distinguish an intended
global from a forgotten import. The production build passing is not evidence here.

## 5. Regression test

`frontend/__tests__/components/trade-multi-team-destinations.test.jsx` (3 tests). It renders
the real `TradePage` and clicks the real **Add team** button, capturing `window.onerror` and
React's error-boundary `console.error` reports, then asserts nothing mentioning
`defaultDestination` escaped.

It is deliberately **not** a grep for the import line. A source-text assertion would pass the
moment someone re-added the symbol under a different name or re-broke a different call site;
driving the component fails on the actual `ReferenceError`.

The third test pins the other direction — `trade-logic` still exports a
`defaultDestination(sideIdx, sideCount)` implementing circular next-side routing — so if the
helper is renamed or dropped, the failure names itself instead of surfacing as an opaque import
error.

**Gap this exposes, not closed here:** no E2E spec covers a multi-team trade at all
(`tests/e2e/specs/journey-trade.spec.js` and the mobile specs are two-team only). That absence
is why a fully broken feature survived two and a half weeks of green CI. Adding multi-team E2E
coverage is real work and belongs to the E2E track, not to a one-line hotfix.

## 6. Fix

One line: `defaultDestination,` restored to the `@/lib/trade-logic` import block in
`frontend/app/trade/page.jsx`. No behavior was redesigned and no call site was changed — the
nine call sites were always correct, and the helper they wanted always existed.

## 7. Verification

| check | result |
|---|---|
| new regression tests | 3/3 pass (RED→GREEN; 2 failed pre-fix) |
| trade-area vitest suites | 7 files / 255 tests pass |
| full frontend vitest | 121 files / 2,010 tests pass / 0 fail |
| `npm run build` | green, every route bundle under budget |
| live browser, production build, mobile viewport | RED before / GREEN after — see below |

### Browser verification — RED → GREEN on the real stack

`trade_multiteam_browser_check.mjs` (this directory) drives the **real production Next build**
served over the real stack — `next start` on the built bundle, backend on `:8000` with the
scraper suppressed, a minted E2E session, assets seeded from the live contract's own top two
board rows. Chromium at the `mobile-chromium` viewport (390×844, `isMobile`, `hasTouch`).

Run against the **unfixed** bundle (fix stashed, `next build` re-run), the Add-team path:

```
[GlobalError] Unhandled client error: ReferenceError: defaultDestination is not defined
  at .../_next/static/chunks/2osj083w7k4dd.js:1:51272
  at Array.map (<anonymous>)
```

`sawErrorBoundary: true`, `thirdSidePresent: false` — the third team never materialises.
Re-run against the **fixed** bundle (fix restored, rebuilt, server restarted): zero
`defaultDestination` errors, no error boundary, `thirdSidePresent: true`. Same harness, same
stack, same data.

One honest discrepancy worth recording: path **(a), hydration, does not reproduce in the real
browser** — only in jsdom. In jsdom the mocked `useDynastyData` returns board rows
synchronously, so hydration reaches the seeding branch on first render. Against the live stack
`/api/data` is asynchronous, so the first hydration pass sees an empty board, skips the loop,
and the assets are resolved later by a path that does not seed. Path (a) is therefore a genuine
code path guarded by a race the live network happens to win, not a second independent
production reproduction. **The browser evidence for this defect is path (b).**

### What is *not* verified

WebKit is **not installable in this container** — `/opt/pw-browsers` carries Chromium only, and
the repo's WebKit projects (`mobile-390`, `mobile-430`) are documented local-only extras that CI
never runs (`.github/workflows/e2e.yml:303`, `prod-e2e-smoke.yml:111`). The owner's exact
browser path is therefore **not** independently reproduced here. Given §4 — an ES-level
`ReferenceError` with no engine-specific behaviour beyond the message string — Chromium evidence
is strong, but it is Chromium evidence and is labelled as such rather than presented as
mobile/WebKit proof.

## 8. Registry

New defect, not present in `findings.json` (generated 2026-08-05 at `8b88623f`). It postdates
the audit's own reconnaissance by design — it was found by the owner in production during this
engagement. Recorded in `REBASELINE_2026-08-11.md` under new defects found this session.
