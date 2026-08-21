# Claude 13 — C8/C9/C10 Mass Implementation Delivery Log

**Branch:** `claude/cseries-premium-public-closure`
**Scope:** C8 (Performance / Premium Sports Intelligence UI), C9 (Public / Storytelling),
C10 (Closure — non-methodology).


> **Two batch series, one lane, two sessions.** This log was created independently in
> two Claude 13 sessions and reconciled at Integration on 2026-08-20 when both reached
> `main`. **Batches 1-3** are the C8/C9/C10 mass-build campaign (merged as #965);
> **Batches A1-A5** are the PSI reference-route migration (#984). Neither series
> supersedes the other and neither was rewritten to look like one sequence - the
> numbering collision is real history, not an error to tidy away.

## Owner authorization (governance record)

The live governance state at campaign start (`docs/EXECUTION_PLAN.md` §0, `docs/
VERSION_1_COMPLETION_CONTRACT.md`, `docs/WORK_CLAIMS.md`, all reconciled through 2026-08-20)
describes a **V1 Completion Sprint** organized into six lanes, not the C1–C10 numbering this
campaign brief uses. Under that structure, nearly all of this brief — Public League Experience v3,
Wrapped, Upside Report, Share Renderer, Awards v2, and route-by-route Premium UI migration beyond
Rankings — is explicitly classified **POST-V1**, and `EXECUTION_PLAN.md` §6 lists several of these
by name under "do not opportunistically begin." A separate session additionally holds an **open**
`WORK_CLAIMS.md` claim on Lane 6 ("premium-UI V1 repair queue," branch
`claude/premium-ui-migration-ltldy0`), explicitly scoped to repairs only, not a route reskin.

I raised this conflict to the user (owner) before writing any code. **The owner explicitly
authorized proceeding with the full C8/C9/C10 brief now**, on these conditions, recorded here
verbatim in substance:

1. POST-V1 capabilities remain POST-V1 in `VERSION_1_COMPLETION_CONTRACT.md` — this campaign does
   not reclassify them as V1 REQUIRED merely by building them early, and does not add them to the
   V1 denominator.
2. Do not overwrite or concurrently edit files covered by the active Lane 6 repair-only claim
   (exact list below). If a later unit genuinely needs one of those files, that unit is marked
   `BLOCKED_BY_ACTIVE_CLAIM` and work continues on another dependency-ready unit instead — the
   whole campaign does not stop for one occupied file.
3. Claude 5 remains Integration Authority and sole merge owner; Claude 8 remains owner of the
   source/cross-position bridge program; this campaign never self-merges.
4. This authorization is recorded here, in `docs/cseries-delivery/CLAUDE_13.md`, and NOT by
   independently rewriting the canonical V1 denominator or reclassifying POST-V1 capabilities in
   `VERSION_1_COMPLETION_CONTRACT.md` — those are Integration Authority's files. The required
   governance delta is instead reported to Claude 5 in each batch's `READY_FOR_INTEGRATION` note
   (see "Governance delta owed to Claude 5" below).
5. No broad concurrent edits to the CE registry or other one-writer governance registries.

**Lane 6 repair-only claim — exact excluded file list** (from `docs/WORK_CLAIMS.md`, branch
`claude/premium-ui-migration-ltldy0`, re-checked at the start of each batch below for drift):
`src/api/compact_view.py`, `server.py` (one comment), `frontend/lib/device-profile.js`,
`frontend/lib/dynasty-data.js` (comments only), `frontend/scripts/check-bundle-sizes.mjs`,
`frontend/__tests__/bundle-budget-gate.test.js`, `frontend/components/SourceHealthStrip.jsx`,
`frontend/app/tools/source-health/page.jsx`, `frontend/app/globals.css`,
`frontend/__tests__/components/source-health-strip.test.jsx`, `frontend/app/draft/page.jsx`,
`frontend/app/draft/draft.css`, `frontend/__tests__/a11y-clickable-keyboard.test.js`,
`frontend/__tests__/a11y-failure-not-empty.test.js`, `frontend/components/AppShell.jsx`,
`frontend/app/rosters/page.jsx`, `frontend/scripts/measure-route-baselines.mjs`,
`tests/api/test_compact_view*.py`, `tests/e2e/specs/api-view-parity.spec.js`.

This claim does NOT reserve the entire C8/C9/C10 program — only the files it names. Work outside
that set proceeds immediately.

## Governance delta owed to Claude 5

**Already reconciled — no delta needed.** `docs/EXECUTION_PLAN.md` §0 was updated (by another
session, ahead of this campaign's first commit) with a full **"POST-V1 C-SERIES MASS-BUILD
CAMPAIGN — AUTHORIZED BY THE OWNER, 2026-08-20"** section that records exactly this authorization
in more detail than the owner's message to me did: the five-lane map (`Claude 13 — C8 + C9 + C10`),
the "build broadly, integrate narrowly" rule, the explicit non-reclassification of POST-V1 items,
the Lane-6-claim boundary ("repair-only, protects the exact files it names — not all of
C8/C9/C10"), and the "Claude 5 is the only merge authority" rule. This matches every condition the
owner gave me. I have nothing further to hand Claude 5 on the authorization question itself.

`docs/VERSION_1_COMPLETION_CONTRACT.md` needs no status-field changes from this authorization
alone — POST-V1 items stay POST-V1 (I do not edit that file; only Claude 5 edits its §3). Individual
batches below may note when a capability they touch has a corresponding V1 row, without changing
its status.

## PR A / PR B authorization (governance record)

The owner explicitly authorized a real, production-capable migration of two reference routes —
Dynasty Rankings and a new Universal Player Profile — onto the "Premium Sports Intelligence"
editorial visual direction (`docs/PREMIUM_SPORTS_INTELLIGENCE_DESIGN_NORTH_STAR.md`), using two
attached reference screenshots as the visual source of truth. This supersedes the direction's
previous "preparation only" posture and is an explicit continuation of the owner override already
recorded for the broader C8/C9/C10 campaign earlier this session.

**Governance gap, recorded honestly.** As of this session's most recent check of the canonical
docs: `docs/VERSION_1_COMPLETION_CONTRACT.md` still lists `C8-PSI-02` / `R-PREMIUM` ("Premium
migration of the high-use routes") as `NOT STARTED`, and `docs/EXECUTION_PLAN.md` §6 still names
"Premium route migration" under "do not opportunistically begin." Unlike the earlier C8/C9/C10
authorization (found already reconciled into `EXECUTION_PLAN.md` §0 before that work began), **this
specific authorization has not yet been written into the canonical record.** The owner's
instruction directly anticipates this ("Claude 5 will reconcile the canonical execution/governance
record. Do not independently rewrite the V1 completion contract") — I am proceeding on that basis
per explicit instruction, not editing either canonical doc myself, and recording the exact delta
here for Claude 5.

**PR #965 stays frozen.** This work started on a fresh branch, `claude/psi-reference-routes`, off
`origin/main` — not off `claude/cseries-premium-public-closure` — per explicit instruction not to
keep piling unrelated work onto #965.

## Design decisions made during implementation (not verbatim from the brief)

- **Font**: the brief asked for "major serif editorial display typography" but also "do not add an
  external font dependency merely to imitate a screenshot unless the repository already has a
  supported/legal mechanism for it." The app's only font mechanism is `next/font/local` with
  checked-in `woff2` assets, specifically because the build environment can't reach
  `fonts.googleapis.com`. **Decision: the new `--font-display` token is a system serif stack**
  (`Georgia, Cambria, "Times New Roman", Times, serif`) — no new asset, no license risk. This is a
  real, visible gap versus the screenshot's distinctive display serif, and is called out here
  rather than silently accepted — swappable later via the same mechanism if the owner
  supplies/approves a licensed font file.
- **Token scoping mechanism**: rather than a whole-app theme flip or an all-new token namespace,
  the editorial palette is a new `.psi-editorial` CSS class that re-maps the SAME semantic alias
  names (`--surface-0`, `--text-primary`, `--accent`, etc.) every `ds/` component already consumes
  exclusively — the same mechanism `[data-theme="light"]` already uses, just scoped to a class
  instead of the whole document. Every existing `ds/` primitive (Panel, DataTable, Button, Badge…)
  therefore renders correctly in the new palette with zero component changes, and a migrated route
  reverts to the terminal palette instantly by removing one class — matching the north star's own
  "route-by-route, reversible" migration method (§8) exactly.
- **Every color WCAG-computed, not eyeballed** (matching this file's own existing discipline):
  text ≥4.5:1 on every surface (worst case, the nested `surface-2`), accent/market-direction marks
  ≥3:1, the screenshot's visible "thin black rule" separators get a genuinely near-ink
  `--border-strong` rather than a token reused from elsewhere at the wrong weight. The existing
  `--data-up`/`--data-down` terminal values were validated only against dark surfaces and measured
  below the 3:1 mark floor on this scope's nested surface (2.75/2.94:1) — re-derived rather than
  inherited, darker blue/orange in the same CVD-safe hue family, verified ≥4.5:1+ everywhere.
  22 tests in `tokens-contract.test.js` (8 new) pin these ratios so a future edit can't silently
  regress them.

## Batch log

### Series 1 - C8/C9/C10 mass-build campaign (#965)


_(Updated at the end of each batch — what shipped, what was verified, what's deliberately not
claimed.)_

### Setup — done

- Branch `claude/cseries-premium-public-closure` created from `origin/main` @ `daf3c981`.
- This delivery doc created; `docs/WORK_CLAIMS.md` row added for Batch 1.

### Batch 1 (C8-PSI-01 / C8-A11Y-01) — Chase Upside Market Ticker — `FEATURE_GREEN`, `READY_FOR_INTEGRATION`

Elevated the existing `frontend/components/terminal/MarketTicker.jsx` (live on `/`) to Premium
Sports Intelligence quality, rather than forking a second ticker — building a parallel surface
would itself be the "two competing Premium UI implementations" defect this campaign is told to
avoid.

**Plan revision, recorded honestly:** the original plan (see the approved plan file) assumed
switching the ticker's data source to `/api/terminal`'s server-computed `movers.*` block and
threading `confidenceBucket` through `src/api/terminal.py::_compute_movers()`. Reading the actual
code first (this repo's own non-negotiable rule) found that unnecessary: `MarketTicker.jsx` already
reads the full materialized contract (`rows` from `useApp()`), and every row already carries
`confidence` (`marketBreadthAgreementIndex ?? marketConfidence`, null-safe) — the exact field
`ds/Badge`'s `Movement`/`Confidence` components are built to consume. So the whole batch stayed
frontend-only, with a smaller diff than planned and zero backend changes.

**What shipped:**
- `frontend/lib/market-movers.js::computeMovers()` passes `confidence` through per mover, guarded
  against `Number(null) === 0` silently coercing an unmeasured row into a confident zero (caught by
  a RED test before the fix — `frontend/__tests__/market-movers.test.js`).
- `frontend/components/terminal/MarketTicker.jsx`: scope switch moved from a hand-rolled
  `role="tablist"` to `ds/SegmentedControl` (a filter over one list, not tabpanels — this repo's own
  documented rule); raw colored deltas moved to `ds/Badge`'s `<Movement>` (arrow + magnitude +
  confidence ticks, `--data-up`/`--data-down` tokens); added a freshness affordance from the
  contract's own `generatedAt`, formatted with the existing `timeAgo()` helper
  (`frontend/lib/news-service.js`) rather than a new one.
- `frontend/components/terminal/market-ticker.module.css` (new): structural/layout rules only —
  delta color and scope-switch styling now live in `ds.css` via the primitives, so nothing
  duplicates `globals.css` (which is untouched — it's the active Lane 6 claim's file).
- `frontend/__tests__/a11y-tab-roles.test.js`: de-listed `MarketTicker.jsx` from its baseline
  (2 → 0 `role="tab"` sites), per that test's own designed ratchet — leaving a fixed file's stale
  entry in place is what the test exists to catch.

**Verified:**
- New test suite green (5 tests): confidence pass-through, null-not-zero, filtering, sort order.
- Full frontend suite green: 143 test files / 2,245 tests (including the new file), zero
  regressions.
- `next build` completes cleanly (the three `TypeError`s in the build log are pre-existing static
  pre-render attempts against `/api/public/league*` with no backend running in this sandbox — not
  from this change; unaffected by anything in this batch).

**Deliberately NOT claiming:**
- `src/api/terminal.py` / `/api/terminal`'s `movers.*` block. The research that informed this
  campaign flagged `computeMovers()` as a client-side duplicate of `_compute_movers()` — that
  observation still stands and is worth fixing, but this batch didn't need to touch it to close the
  ticker's real gaps, so it's left as a named follow-up rather than an unnecessary risk.
- Any change to `frontend/app/globals.css` (Lane 6-claimed) — the now-orphaned `.ticker*` rules
  there are dead CSS after this change but are left in place; whoever next has clearance to touch
  `globals.css` should remove them.
- A manual browser check. Attempted: this sandbox has no Python backend environment prepared at
  all (no `fastapi`/`uvicorn`/`pytest` installed — matches the SessionStart health check's own
  "pytest collection failed"), and `pip install -r requirements.txt` fails independently of this
  change on a native-build error in the `http-ece` package (a `setuptools`/`distutils`
  `install_layout` incompatibility, unrelated to anything in this batch). Did not spend further
  budget fighting an unrelated packaging failure to visually verify a CSS/component change already
  covered by 5 targeted + 2,240 existing automated tests and a clean production `next build`. This
  is a real gap, not a silent claim of success — flagging it per CLAUDE.md's own instruction to say
  so explicitly rather than claim a UI verification that didn't happen. A `run`-skill pass in an
  environment with a working Python install would close it before this ships.

### Batch 2 (C9-HIST-01) — Franchise continuity: retirement stops erasing history

**Owner decision recorded first, before writing code.** The scope manifest's stated defect
("2024 declares ten teams but carries only eight standings rows, and retired-owner mappings
hard-coded rather than derived") turned out not to be an oversight — `src/public_league/
identity.py`'s `_RETIRED_OWNER_IDS` filter was a previous DELIBERATE design, with its own
dedicated, explicitly-reasoned test suite (`tests/public_league/test_identity_retirement.py`),
that fully erased a retired owner's participation from every season, including past seasons where
they were a legitimate active roster. That's what produces the count mismatch: a season's declared
`numTeams` (from Sleeper's `total_rosters`) stayed correct while `season_standings()` silently
dropped any retired owner's row via the same "orphaned roster" path used for rosters with no
owner_id at all.

Reversing an intentional, tested privacy/product decision is not a bug fix I should make
unilaterally, so I asked the owner which way C9-HIST-01 should resolve it before touching any code.
**Decision: restore historical rows, hide retired owners only from current-facing UI (dropdowns/
directories).**

**What shipped** (`src/public_league/identity.py`):
- `Manager` gained `is_retired: bool` — a flag, not a filter baked into construction.
- `build_manager_registry()` no longer skips a retired owner's roster/alias/`roster_to_owner` entry
  for any season; it flags `is_retired` on the `Manager` instead. Their real historical
  participation (standings rows, archive rows, career stats, matchup attribution) is restored.
- `ManagerRegistry.ordered_managers(include_retired: bool = False)` is the new exclusion point —
  used by `to_public_list()` (unchanged default behavior: still excludes retired owners from the
  public managers directory) and by anything else that wants the forward-facing list. A caller that
  genuinely wants the all-time roster can pass `include_retired=True`.

**Downstream consumers audited, not assumed correct:**
- `archives.py::_manager_index` and `franchise.py`'s per-owner index/detail build, plus
  `overview.py`'s league-vitals manager count — all read `by_owner_id` or `ordered_managers()`
  directly and needed no change: the franchise leaderboard and league-vitals counters are
  inherently historical/all-time views, so restoring retired owners to them is the correct outcome,
  not a side effect to guard against.
- `src/ros/power_v2.py::_enumerate_owner_ids` **did** need a fix — its docstring explicitly says it
  builds "the authoritative active-owner registry" for a CURRENT power-rankings table and relies on
  `by_owner_id` excluding retired owners. Since that dict no longer excludes them, this is exactly
  the "current UI" case the owner's decision says should still filter — changed to
  `{m.owner_id for m in snapshot.managers.ordered_managers()}`, preserving the original exclusion
  semantics with the new API instead of the raw dict.
- `matchup_recap.py`'s existing "unresolved owner" fallback (`retired:{league}:{rid}` synthetic id,
  "Former manager" label) is unaffected in mechanism — it still fires correctly for genuine orphans
  (no `owner_id` at all) — but now fires LESS often: a retired owner's own historical matchups
  resolve to their real name instead of the placeholder. Updated its stale inline comment and the
  stale docstring in `tests/public_league/test_matchup_unresolved_owner.py` (that test's actual
  assertions were already orphan-construction-based and needed no logic change).

**Test suite rewritten, not just patched**, since the old file pinned the now-reversed contract as
correct: `tests/public_league/test_identity_retirement.py` — 8 tests, including a full
`metrics.season_standings()` end-to-end test reproducing the exact manifest symptom (a season with
2 retired-owner rosters among 4 now produces 4 standings rows, matching `numTeams`, not 2).

**Verified:**
- New/rewritten test file: 8/8 passing.
- `tests/public_league/` + `tests/ros/test_power_v2.py`: 398 passed, 31 skipped (pre-existing
  skips), zero regressions.
- `ruff check` clean on every touched file; `ruff format` applied to the one file it flagged
  (whitespace only).
- Full `pytest tests/ -m "not livedata"` sweep (started before the commit, finished after):
  **9,537 passed, 53 skipped, 0 failures**, 16m7s. Confirms zero regressions across the whole
  backend from both Batch 2 and Batch 3's changes (this log covers commits through Batch 3, since
  they landed while the sweep was still running).

**Deliberately NOT claiming:**
- Any UI/frontend surface for this (that's `/league`'s existing rendering of these same backend
  fields — no frontend change needed or made).
- Public League Experience v3 (`C9-V3-01`) — this repair is a stated *precondition* for it per the
  scope manifest, not the feature itself.
- Whether an individual retired owner's OWN franchise page should be directly *linked* from
  anywhere now that it resolves correctly — out of scope; only the underlying data/count defect is
  fixed here.

### Batch 3 (C10-CLOSE-02) — Dead-code / duplicate-owner census re-verification

**Documentation-and-audit batch, not a deletion batch** — the outcome changed direction mid-batch
on real evidence, recorded honestly below rather than smoothed over.

**Two governance corrections with hard evidence, both improvements to the record:**

1. **`C3-VA-01` / dead-code-map `D-032`** — the manifest and census both described "5
   implementations" of KTC's Value Adjustment, one installed by an import-time monkeypatch, with a
   rounding divergence. Direct code read confirms `src/trade/market_value_adjustment.py` is now a
   0-computation re-export of `src/trade/ktc_va.py` (the second Python port was collapsed
   2026-08-18, matching what `CLAUDE.md`'s trade-engine section already says), and
   `tests/public_league/test_trade_grade_parity.py` (8 tests / 50 subtests) passes green,
   confirming `src/public_league/trade_grading.py`'s remaining separate Python port is
   parity-guarded against both `ktc_va.py` and the JS port — the monkeypatch, the rounding bug and
   the dead V12/V13 exports are ALL fixed. Corrected both `docs/C_SERIES_SCOPE_MANIFEST.md`'s
   `C3-VA-01` row (owner-map summary + detail row) and `dead-code-map.csv`'s `D-032` to state the
   true current count (2 Python ports, not 5) and explicitly leave the one open question — whether
   `trade_grading.py` should still collapse into `ktc_va.py` — to Lane 2 (Claude 9, C3 trade
   substrate), since that is a methodology call outside this campaign's C10 mandate ("do NOT
   independently activate adaptive source weighting or change model methodology").

2. **A systemic finding about the census itself, discovered by nearly acting on it.** Before
   deleting anything, I checked each candidate's test suite for a reason it might be intentionally
   kept — and found real ones on the first two rows checked:
   - `D-120` (`src/api/chat.py`, disposition "deprecate") — `tests/api/
     test_chat_layers_are_consistently_wired.py` (added after this census row was written) is a
     live, passing guard whose own docstring says: "recorded rather than deleted — it becomes
     valuable the moment the product decision goes the other way." Deleting it would have broken a
     deliberate, already-implemented decision.
   - `D-112` (`/draft-capital` nav-title mapping, disposition "deprecate") — `frontend/__tests__/
     nav-model.test.js` and `public-routes.test.js` document and pin it as a legacy **routing-layer
     308 redirect** declared in `next.config.mjs` (no page directory needed), kept explicitly
     public. "No `app/draft-capital/` directory" was never evidence of dead code once a route can
     be declared outside `app/`.

   **Both corrected in `dead-code-map.csv` with the actual evidence.** Given a 2-for-2 false-positive
   rate on the first two rows actually re-checked, I stopped attempting deletions in this session —
   the census (`docs/master-site-audit/evidence/W30/`) is measurably stale relative to work that has
   landed since it was generated, and its "deprecate"/"replace" dispositions cannot be trusted
   without the same per-row check (test suite + routing config, not just an import grep) before
   acting on any of them. Recorded as an explicit warning in both corrected rows so the next person
   re-verifies rather than deletes on the strength of the old disposition alone.

3. **`CLOSURE_STATUS.md` / `closure.json` (the separate, older W##-F### audit-finding tracker) —
   regenerated, then reverted.** Ran `tools/verify_closure.py` (its own header says "regenerate
   rather than hand-edit"); the fresh run reported `open: 269` vs. the committed `268`, with
   `W11-F006` dropping out of "claimed closed." Investigated rather than trusted: direct code read
   of `frontend/components/waivers/ManualAddDrop.jsx:300-312` confirms the described defect (wrong
   envelope-key unwrap) **is fixed** — the code correctly reads `data?.data ?? null` with a comment
   citing `W11-F006` by name. The drop is a tooling artifact: `verify_closure.py` derives "claimed"
   status partly from a live `git log origin/main..HEAD` trailer scan, and this sandbox's shallow/
   narrow git history doesn't contain the historical commit whose trailer previously satisfied it.
   Regenerating from here would have made the tracker **less** accurate, not more, so I reverted
   both files (`git checkout --`) rather than commit a worse snapshot. The correct fix — adding
   `W11-F006` to the frozen `claims-frozen-2026-08-05.json` ledger with its real closing commit — was
   not completed: this sandbox's shallow clone made the commit sha unreliable to determine, and
   guessing wrong would corrupt a load-bearing file. Flagged here rather than attempted.

**Deliberately NOT claiming:**
- Any deletion of dead code — the two candidates checked both turned out to be deliberately kept;
  no further candidates were attempted this batch given that result.
- Resolution of any other `C10-CLOSE-02` DUPLICATED row (`C2-REPL-01`, `C2-STR-01`, `C2-WEAK-01`,
  `C3-PKG-01`, `C3-EQ-01`, `C5-POW-01`, `C5-PLAY-01`, `C6-SIG-01`) — these are live, still-duplicated
  engines owned by other lanes' methodology, not documentation drift; out of my non-methodology C10
  mandate.
- Fixing `W11-F006`'s frozen-ledger entry — flagged for Claude 5 (Integration Authority already owns
  the audit tooling) with a full, non-shallow git history to determine the real commit sha.
- The remaining un-rechecked `D-121`–`D-129` dead-module rows — explicitly named as needing the same
  per-row guard-test check before any action, not verified further in this batch.

**Verified:** the two corrected findings' underlying guard tests re-run green (`test_chat_layers_are_
consistently_wired.py` 3/3, `test_trade_grade_parity.py` 8/8+50 subtests, `nav-model.test.js` +
`public-routes.test.js` 42/42). No source code changed in this batch — documentation/CSV only.

### Series A - PSI reference-route migration (#984)


### Setup — done

- Branch `claude/psi-reference-routes` created from `origin/main`.
- This delivery doc created (fresh copy — see the note at the top about reconciling with #965's
  copy at merge time).
- `docs/WORK_CLAIMS.md` row added for PR A.

### Batch A1 (C8-PSI-02) — Editorial token layer — done

**What shipped:**
- `frontend/app/tokens.css`: new additive `.psi-editorial` scope (see "Design decisions" above for
  the mechanism and the exact palette). Does not touch any existing dark/light token or
  `globals.css` — purely additive, verified by the existing "stays additive" contract test plus a
  new one scoped to this block.
- `frontend/components/ds/token-contract.js`: new `PSI_EDITORIAL_REQUIRED` export listing the
  tokens this scope must define, mirroring `LIGHT_THEME_REQUIRED`'s existing pattern.
- `frontend/__tests__/components/ds/tokens-contract.test.js`: 8 new tests — required-token
  presence, no-primitives-redefined, additive-only, and 5 WCAG contrast assertions (accent on
  worst surface, text-on-accent, text-primary on all 4 surfaces, data-up/data-down mark floor on
  all 4 surfaces, border-strong reads as a real rule).

**Verified:**
- `tokens-contract.test.js`: 22/22 passing (14 pre-existing + 8 new).
- Full frontend suite: 142 test files / 2,243 tests passing, zero regressions.

**Deliberately NOT claiming:**
- A licensed display serif font (system stack used instead — see "Design decisions").
- Any component/page actually USING the new scope yet — that's Batch A2 (shell) and A3
  (Rankings). This batch is tokens only, so it's inert until a page opts in via the class.

### Batch A2 (C8-PSI-01) — Shell restyle — done

**Finding that reshaped this batch:** `frontend/app/shell.css` (the app chrome stylesheet —
`TopBar`, `MobileChrome`, nav dropdowns, the mobile drawer, the command palette) turned out to
already consume ONLY semantic token aliases, zero raw hex, matching the same discipline as
`ds.css`. It is also **not** on the Lane 6 claim's path list (only `globals.css` is). That means
applying the new `.psi-editorial` class to the shell's root elements re-skins the ENTIRE header —
brand, nav, search, account menu, mobile tab bar, drawer, dropdowns — automatically, with **zero
CSS rewrite needed**. This is exactly the payoff the token architecture was built for, so the
batch became much smaller than planned: no new CSS modules, no shell.css rewrite, just scoping +
one small monogram tweak.

**What shipped:**
- `frontend/components/shell/TopBar.jsx`: `.psi-editorial` added to the `<header>` root (covers
  the nav dropdowns and the System menu too, since they render inline, not via a portal —
  verified, no `createPortal` anywhere in this tree). Brand mark glyph changed from a bare "▪" to
  "CU" text (still `aria-hidden`, the accessible name is still "Chase Upside" from the link's own
  text), to match the screenshot's compact monogram-block treatment.
- `frontend/components/shell/MobileChrome.jsx`: `.psi-editorial` added to `MobileTopBar`'s
  `<header>` and `MobileTabBar`'s `<nav>`. The menu `Drawer` is a JSX **sibling** of the tab bar
  (not a descendant), so it needed the class passed explicitly via its own `className` prop
  (`Drawer` already supports one) rather than inheriting it.
- `frontend/app/shell.css`: one small additive rule,
  `.psi-editorial .shell-brand-mark` — a bordered 22px square rendering "CU" in the new serif
  display face, scoped so it doesn't touch the terminal shell's existing plain-glyph treatment if
  the class were ever removed from a route.
- **This is a global, immediate change**: `TopBar`/`MobileChrome` are the one persistent shell
  rendered on every route, so every page's header/nav now shows the editorial palette right away,
  while unmigrated page BODIES stay on the terminal palette until their own route migrates. This
  is a deliberate, temporary seam — the north star's own "route-by-route, reversible" method says
  a split state during migration is expected, only says not to leave it split *indefinitely* — and
  matches the brief's own success condition ("open the app and immediately see the migration has
  begun").

**Verified:**
- `TopBar.test.jsx`: 20/20 passing, unchanged (no test asserted the literal "▪" glyph).
- Full frontend suite: 142 test files / 2,243 tests, zero regressions.

**Deliberately NOT claiming:**
- Any change to `AppShell.jsx` (claimed by Lane 6, and confirmed not to need touching — it's
  behavior/context only, no styling lives there).
- Any change to `globals.css` (claimed).
- A rewrite of the nav's information architecture — every existing nav item, group, gating rule
  and keyboard/focus behavior is untouched; only the palette changed.

### Batch A3 (C8-PSI-02) — Rankings visual migration — done

**Finding that reshaped this batch, same as A2:** `frontend/app/rankings/board.module.css` is
already 100% token-driven — zero raw hex, zero `rgba()` (verified by grep before writing a line).
Applying `.psi-editorial` to the page root re-skins the entire table (rank/player/value/source
cells, filters, rails, trust strip) automatically. The real work was finding and closing the small
number of places the page reached OUTSIDE the token system, into legacy `globals.css` classes this
Lane-6 claim forbids editing.

**What shipped:**
- `frontend/app/rankings/page.jsx`: `.psi-editorial` added to the page root `<section>`. Three
  legacy-class leaks closed by adding local replacements to `board.module.css` and swapping the
  className references (never editing `globals.css`):
  - `button-reset` (hardcoded `--border`/`--cyan`, both pre-R0 legacy names invisible to the new
    scope) → new `.resetButton`, a genuine reset (no background/border) rather than the legacy
    rule's incidental box — matches the screenshot's plain inline typography for player names,
    watch stars and values.
  - `rankings-player-name` (legacy `--cyan` hover) → new `.playerName`, same behavior, hover color
    now `--accent`.
  - `muted` (legacy `--muted` token) → new `.muted`, now `--text-tertiary`.
  - `custom-mix-badge` audited and left AS-IS: verified its own declared properties (font-family,
    size, spacing, a brightness-filter hover) are all color-neutral: it layers onto `ds-badge
    ds-badge--warning`, which is already fully token-driven.
- **Hero treatment**: eyebrow now reads "Chase Upside Consensus / Updated {relative time}" —
  reusing the page's own existing `relativeUpdated` freshness derivation (`rawData?.dataFreshness`
  → `generatedAt`), not a new computation. `<h1>` stays the literal string `"Rankings"` — see the
  naming-canon note below for why "The Dynasty Board" is NOT the `<h1>`. Description became "The
  Dynasty Board — unified dynasty rankings, offense + IDP blended by consensus rank." (existing
  product language, "The Dynasty Board" folded in as editorial branding rather than a new claim).
  New `.hero` class + a scoped `:global(.ds-page-header__title)` compound selector in
  `board.module.css` gives just this page's title a serif `--font-display` face at
  `--font-size-3xl` (the existing scale's largest step — no ninth size invented) — `ds.css`'s
  shared `PageHeader` styling is untouched for every other page.
- **"Format summary" (real league Superflex/TEP/IDP label) deliberately omitted**: no canonical
  field for this was found readily available on this page (checked `useLeague()`,
  `useTeam()`) in the time budget for this batch. Rather than guess or fabricate a label,
  omitted — a real gap, named per the owner's own instruction rather than silently skipped.

**Naming-canon course-correction, caught by the test suite (not by inspection):** the first attempt
set the literal `<h1>` to "The Dynasty Board", which broke `page-title-canon.test.jsx` — this repo
pins nav label ≡ page `<h1>` deliberately (its docstring cites a real 2026-07-29 regression this
guard now catches). Changing the canon would mean changing `nav-model.js`'s desktop nav link label
too — an app-wide copy change well beyond "Rankings page visual migration," and out of scope for
this batch. Reverted to keep `<h1>` as the canon "Rankings" and moved the editorial name into the
description instead. Recorded here because a plan-vs-actual note belongs beside the code, not
silently corrected away.

**Legacy badge system, NOT touched, documented rather than silently left:** `lib/display-helpers.js`
(`posBadgeClass`, `confBadgeClass`, `marketEdge`/`marketAction`) all return legacy `globals.css`
class names (`badge-cyan`, `badge-amber`, `badge-green`, `badge-red`, `edge-buy`, `edge-sell`) for
position/confidence/edge badges throughout the table, audit panel and edge rail. `board.module.css`'s
OWN header comment already names this as an acknowledged, deferred concern ("Badge/tier/audit-grid
colors stay on their legacy global classes until the R5 CSS purge") — not something this batch
introduced. These badges are self-contained colored chips (not transparent), so they remain fully
legible, just visually inconsistent with the new palette rather than broken. Migrating this whole
shared badge system onto `ds/Badge` is real work spanning multiple pages beyond Rankings and is
correctly a separate, dedicated unit (the repo's own planned "R5 CSS purge"), not silent scope creep
here. Same disposition for the mobile-source-strip/audit-row expanded-drawer background wash
(`rankings-mobile-source-row`/`rankings-audit-row`) — near-transparent legacy tints, low visual
impact, same acknowledged-deferred class.

**Verified:**
- Full frontend suite: 142 test files / 2,243 tests, zero regressions (including
  `page-title-canon.test.jsx` after the h1 correction above).
- `next build` (both the default Turbopack builder and `--webpack`, since the bundle-budget script
  needs the latter): clean, zero new errors (same three pre-existing `/api/public/league*`
  `TypeError`s from no backend running in this sandbox, unrelated to this diff).
- Bundle budget: `/rankings/page` 66.6 KB / 75 KB (8.4 KB headroom) — all 14/14 budgeted pages
  pass.

**Deliberately NOT claiming:**
- The legacy badge system migration and the mobile-source-row/audit-row background tint (see
  above) — named, deferred, not silently dropped.
- The "format summary" league line (see above).
- Real browser/visual verification and the axe a11y suite — that's Batch A4.

### Batch A4 — Real browser verification + axe a11y — done

Unlike the earlier ticker batch (which gave up on browser verification entirely), this batch got a
real backend + frontend stack running in-sandbox: `pip install fastapi pytest httpx
beautifulsoup4 uvicorn` (full `requirements.txt` fails on an unrelated native-build error in
`http-ece`, worked around by installing only what `server.py` needed to boot), `uvicorn server:app`
with `ALLOW_DEFAULT_LOGIN_DEV=1`, `next build --webpack` + `next start`. The scrape pipeline itself
can't run here (`ModuleNotFoundError: playwright` for the Python side), so `data/dynasty_data_<date>.json`
was seeded from the repo's own tracked `exports/latest/` archive (real, previously-produced
canonical data — not fabricated) so the board would render real values rather than an empty/degraded
state. A Playwright script logged in via `POST /api/auth/login` directly against the backend
(`ctx.request.post`, sharing cookies with `page` — the app's local dev setup has no Next.js bridge
route for `/api/auth/login`, since production relies on nginx proxying `/api/*` straight to the
backend, a layer absent from a bare `next start`) and screenshotted `/rankings` and `/` at both
1366×900 and 390×844.

**Two real rendering bugs found and fixed by this verification, both invisible from source reading
alone:**

1. **Full-bleed background.** `.psi-editorial` on `.page` only repaints elements that reference the
   scoped tokens — it doesn't repaint `.page` itself, and the app shell's `.main-shell` padding
   (`globals.css`, claimed) left the old dark terminal surface visible as a frame around the whole
   migrated section on every side (worst on mobile: a ~6px dark band directly under the header).
   Fixed by painting `.page`'s own background/color explicitly and cancelling `.main-shell`'s
   padding with matching negative margins at every one of its breakpoints (1024/768/420/360px,
   mirroring its exact token/literal values) — without editing that claimed file. Commit `11c69e7d`.

2. **Real axe-core color-contrast failures — 187 nodes on first scan.** All traced to legacy
   `globals.css` classes (`.badge-cyan/-green/-red/-amber`, `.rankings-tier-badge`, the tier
   separator label, the league switcher) reading legacy tokens (`--cyan`, `--subtext`, `--text`,
   `--border`, …) directly — tokens calibrated for the dark terminal canvas that A3's "leave the
   legacy badge system deferred" note above did NOT anticipate would actually fail contrast once
   the CANVAS under them changed, only that they'd look "visually inconsistent." Fixed in four
   rounds, each re-verified by re-running the real scan (not assumed from math alone, though the
   math is recorded too, since two rounds were literal fractions-of-a-point misses axe would catch
   and eyeballing would not):
   - `.psi-editorial` in `tokens.css` now remaps every legacy COLOR alias to the already-validated
     semantic token carrying the same role (`--cyan`→`--accent` per OD-05's own "cyan IS the
     accent" rule, `--text`→`--text-primary`, etc.) — structural legacy tokens (spacing/radius/
     font/layout) deliberately left alone.
   - Three of the four `badge-*` classes ALSO hardcode their own background/border literals (not
     `var()`-driven), unreachable by the token remap: `.badge-amber`'s `#c9a9ff` text was
     1.5-2.0:1 on cream; its background independently dragged an otherwise-fixed text color down to
     3.4-4.4:1. `.badge-cyan`/`.badge-red`'s remapped-to-matching-hue backgrounds individually
     measured 4.49:1 (tinting a light backdrop *toward* a dark foreground's own hue erodes their
     contrast — an effect the old, mismatched blue/red tints had accidentally been immune to).
     `.posRank`'s opacity-based de-emphasis (already patched twice by earlier work for the OLD
     accent) depends on whatever it composites against and stopped clearing 4.5:1 once the color
     underneath changed; replaced with a fixed `--text-secondary`. All fixed via
     `.page :global(.badge-*)` overrides in `board.module.css` — higher specificity than
     `globals.css`'s bare classes, so no edit to that claimed file.
   - `--text-tertiary` itself was `#6e6353` (4.44:1 on the worst surface) — A1's own comment called
     this "still AA at body sizes," which is not a real WCAG exception. Darkened one step to
     `#6b6151` (4.60:1).
   - Added a new pinning test (`text-secondary and text-tertiary clear 4.5:1 on every surface`) so
     this exact class of regression — a token-only check that never asserted the specific pairing
     an axe scan actually renders — can't silently reopen. Commit `3acd6347`.

**This revises A3's "legacy badge system, NOT touched" note above**: it is still not migrated onto
`ds/Badge` (that remains real, separate, deferred work spanning multiple pages), but its four
color/background/border values ARE now overridden specifically for contrast, scoped to this page
only via `:global()`, without touching `globals.css`.

**Real screenshots captured and reviewed** (not claimed without evidence — this sandbox DID launch
a real Chromium, contrary to the earlier ticker batch): `/rankings` desktop 1366×900, full-page
scroll, mobile 390×844, and the shell header via `/` mobile — all authenticated, all rendering real
canonical board data (Josh Allen #1 at 9,991, Brock Bowers #2, real tier groupings, real trust-strip
counts). Confirmed: cream editorial surface full-bleed at every breakpoint, serif italic hero,
burnt-red accent nav/badges/eyebrow, `/` (unmigrated Home) correctly still dark-terminal below its
now-editorial shared header — proving the migration is scoped per-route rather than a global theme
flip. Screenshots were viewed in this session, not just captured; not attached to this file (binary,
and this doc is meant to stay reviewable as text) — Claude 5/the owner can reproduce them from this
recipe or ask for them to be sent directly.

**Verified:**
- axe-core (`@axe-core/playwright`, WCAG 2.0/2.1 A+AA tags) against `/rankings` desktop + mobile,
  authenticated, real data: **0 violations** after the last fix (started at 187 nodes / 1 violation
  type). Run directly rather than through `tests/e2e/specs/a11y-axe.spec.js`'s full baseline-ratchet
  harness, which needs `E2E_TEST_MODE`/`E2E_TEST_SECRET` env the backend wasn't booted with in this
  session — the scan itself is the same `@axe-core/playwright` engine and WCAG tag set that spec
  uses, just invoked directly against this session's authenticated context. Recommend Integration
  re-run the real harness for the baseline-file bookkeeping once a full E2E-provisioned backend is
  available.
- One finding is confirmed **pre-existing and out of this PR's scope**:
  `.scouting-insight-badge--down`/`--warn` on `/` — present identically in every scan run this
  batch (before AND after every fix above), on unmigrated dark-terminal Home page content this
  branch's scope does not touch. Not fixed here; named for whoever owns that surface.
- Full frontend suite: 142 test files / 2,245 tests (2 new since A3, both in
  `tokens-contract.test.js`), zero regressions.
- `next build --webpack`: clean.
- Bundle budget: `/rankings/page` 66.6 KB / 75 KB (8.4 KB headroom, unchanged from A3) — all 14/14
  budgeted pages pass.

**Deliberately NOT claiming:**
- The full `tests/e2e/specs/a11y-axe.spec.js` baseline-ratchet run (env-gated, see above) — the
  underlying scan it would run was done directly instead, but the baseline-file bookkeeping that
  spec owns was not touched or updated.
- Player Profile (PR B) verification — separate batch, not started.
- The pre-existing Home-page finding named above.

### Batch A5 — PR A handoff — done

**PR opened**: [#984](https://github.com/jasonleetucker-code/riskittogetthebrisket/pull/984),
base `main`, head `claude/psi-reference-routes`. Ready for review, not a draft. Subscribed to PR
activity per the standing subscription rule — CI failures and review comments on this PR will be
investigated and either fixed, escalated, or reported here as they arrive.

**Status: FEATURE_GREEN / READY_FOR_INTEGRATION.** `docs/WORK_CLAIMS.md`'s claim row updated with
the A4 findings and commit SHAs, status changed to reflect this. Not self-merged, per the owner's
explicit instruction — Claude 5 remains Integration Authority.

**Commits on this branch** (chronological): editorial token layer → shell restyle → Rankings
migration → full-bleed background fix → axe-core contrast fixes → delivery-doc/work-claims
updates. Each batch is its own commit, reviewable independently.

**What Claude 5 (or the owner) still needs to do, not something this session can do itself:**
- Reconcile `C8-PSI-02` in `docs/VERSION_1_COMPLETION_CONTRACT.md` and §6 of
  `docs/EXECUTION_PLAN.md` — see the governance-gap note at the top of this file.
- Visual review of the screenshots against the two reference screenshots (not attached to this
  repo file; reproducible via the recipe in the A4 section above, or ask this session/a
  continuation of it to send them directly).
- Optionally re-run the full `tests/e2e/specs/a11y-axe.spec.js` baseline-ratchet harness with a
  properly `E2E_TEST_MODE`-provisioned backend, for the baseline-file bookkeeping the direct scan
  in A4 didn't touch.

**Next**: PR B (Universal Player Profile / "Player File") — stacked on this branch per the
approved plan, starting from Batch B1 (extracting reusable sections from `PlayerPopup.jsx`).

### Batch B1–B3 (C8-PSI-02) — Universal Player Profile ("Player File") — done

While this batch was starting, Claude 5 began reconciling PR A (#984) with `main` on this same
branch (merge commit `41ae6c7a`, "Reconcile PR A (#984) with main — Integration, one planned
pass"). **Deviation from the plan, recorded rather than silently worked around**: the plan called
for PR B to be a separate PR stacked on top of PR A's branch. Since Integration was actively
reconciling `claude/psi-reference-routes` in real time, branching off it mid-reconciliation and
later reconciling a second time risked more disruption than it avoided, so PR B's commit landed
directly on the same branch (merged in cleanly after PR A's commit — verified zero diff on PR B's
own files between before and after the merge). **PR #984 now carries both PR A and PR B**; its
title and description were updated to say so explicitly rather than leaving the description
describing only half the diff. Claude 5 can still split them at merge time with full context —
this is a branch-topology choice, not a decision that they must be merged together.

**What shipped (B1 — extraction):**
`frontend/components/PlayerPopup.jsx` — `RosContextSection`, `IntelContextSection`,
`PlayerNewsSection` exported (were local-only; `PlayerContextSection`/`RealizedPointsSection`
were already exported). `computeValueChain` exported (already existed as a plain function).
Three previously-inline `useMemo` bodies — ownership/position-rank lookup, per-source value
breakdown, and the consensus-narrative derivation — pulled out to standalone exported functions
(`computeOwnership`, `computeSiteDetails`, `computeConsensusText`) since the new page needs the
identical derivation; `PlayerPopup` now calls the same functions instead of carrying a second
copy. This is genuine value-bearing logic (not presentation), extracted verbatim — no behavior
changed. Verified: `PlayerPopup.test.jsx`'s 6 tests pass unchanged before and after.

**What shipped (B2 — new route):**
`frontend/app/players/[playerId]/page.jsx` + `player-file.module.css`. Row lookup mirrors
`/players/compare`'s `findRow` pattern — Sleeper `playerId` first, case-insensitive name fallback.
Hero (eyebrow "Player File / {POS} — {TEAM}", real name/age/team/years-exp, real ownership line
via `computeOwnership` — no fabricated jersey number), summary strip (real value/overall rank/
position rank/confidence/sources — position rank is a display ordinal over the full ranked pool,
same technique as Rankings' own `positionRankByName`, not a new rank computation), five
`ds/Tabs`-based sections:
- **Overview** — edge signal, value chain (`computeValueChain`), 180-day rank-history chart
  (`PlayerRankHistoryChart`, reused as-is — renders its own honest "Value history unavailable"
  when there's no series, verified live in this sandbox since the seeded snapshot has none).
- **Market** — source breakdown (`computeSiteDetails`) + consensus narrative
  (`computeConsensusText`), same data PlayerPopup shows.
- **Trades** — **no canonical per-player trade-history data source exists in this codebase**
  (checked: the trade engines compute live suggestions/simulations, none persist a queryable
  per-player ledger). Honest "Trade history not available" state instead of a fabricated history
  or a standalone "Trade Desk" button — `EXECUTION_PLAN.md` §6 lists "Trade Desk" itself as not
  yet authorized, and the owner's brief separately warned against fabricating exactly this button.
- **Performance** — `RosContextSection` + `PlayerContextSection` + `RealizedPointsSection`,
  verbatim.
- **Intel** — `IntelContextSection` + `PlayerNewsSection`, verbatim.

**Actions, verified against what's real before wiring** (per the brief's explicit "if it doesn't
exist, don't build a fake button" instruction): checked `/trade` and `/arbitrage` (the real KTC
arbitrage finder — `/finder` turned out to be a legacy redirect shim to `/rankings?screen=...`,
not a standalone page) for any player-seeding query param. Neither has one. So "Open in Trade
Calculator" is a plain, honestly-labeled navigation link — not a claim that the calculator opens
pre-loaded with this player. "Compare" reuses `/players/compare`'s existing real `?p1=` seeding
(confirmed by reading that page's own `useEffect`). No "Find buyers"/arbitrage action was added:
an unseeded link to a generic board would misrepresent itself as player-specific.

`PlayerPopup.jsx` gained one new button ("Full profile", linking to the new route by playerId
then name) in its identity-actions row — otherwise completely unchanged. It stays the quick-view
drawer; it was not gutted into a stub, since every existing call site and its own tests depend on
its current content.

Not in the naming canon (`naming-canon.js`): a per-entity detail route reached only via a player
link has no static canon title to pin (its `<h1>` is the player's own name, which varies per
player) — same relationship `/league/player/[playerId]` already has to the public nav.

**What shipped (B3 — verification), same rigor as A4:**
- Full suite: 143 test files / 2,255 tests (post-merge with `main`), 0 regressions.
- `next build --webpack`: clean.
- Real axe-core scan (WCAG 2.0/2.1 A+AA), authenticated, real canonical data (Josh Allen — #1
  overall, QB1, 14 sources, real ownership "Blaine · QB1 on roster"): **0 violations** on desktop,
  mobile, AND the not-found state, on the first scan — no legacy `globals.css` class is touched
  anywhere in this page (every element is a `ds/` primitive already proven token-correct by A4's
  fixes), so none of A4's four rounds of fixes had anything to re-discover here.
- Real Chromium screenshots captured and reviewed: the happy path at both breakpoints, all five
  tabs individually (Overview/Market/Trades/Performance/Intel), and the loading/failure/not-found
  states.
- **One real bug found and fixed by that verification**: the loading/failure/error/not-found early
  returns rendered OUTSIDE the `.psi-editorial`-scoped section — only the happy-path return was
  wrapped — so a not-found link showed the OLD dark terminal palette instead of the migrated one.
  Caught by an actual screenshot of the not-found state, not by inspection; fixed by wrapping
  every return path in the same scoped section, then re-verified.

**Deliberately NOT claiming:**
- A trimmed-down PlayerPopup ("slim quick-view/launcher" per the brief's aspiration) — it gained a
  launcher link but kept every existing section; trimming its content is separate, riskier
  follow-up work with many existing dependents, not required to ship real value now.
- The Trades tab's underlying feature — an honest gap, not a stub for later completion in this
  batch.
- The full `a11y-axe.spec.js` baseline-ratchet harness run — same reason as A4.

### Batch B4 — PR B handoff — done

No separate PR opened — see the deviation note at the top of this section. PR #984's title/body
updated to describe both PR A and PR B; `docs/WORK_CLAIMS.md`'s existing claim row extended with
the B1-B3 files and findings. Status: **FEATURE_GREEN / READY_FOR_INTEGRATION** for both PRs A and
B together. Not self-merged. Still subscribed to #984's activity from A5.
