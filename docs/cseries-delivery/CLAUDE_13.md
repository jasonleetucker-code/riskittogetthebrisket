# Claude 13 — C8/C9/C10 Mass Implementation Delivery Log

**Branch:** `claude/cseries-premium-public-closure`
**Scope:** C8 (Performance / Premium Sports Intelligence UI), C9 (Public / Storytelling),
C10 (Closure — non-methodology).

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

## Batch log

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
- Full `pytest tests/ -m "not livedata"` sweep kicked off as an extra safety net beyond the
  directly-relevant suites above and was still running at commit time (this sandbox runs it slower
  than CI's ~700s). Not blocking the commit — the targeted suites already exercise every call site
  the diff touches or that reads its APIs (identity.py, matchup_recap.py, power_v2.py, and every
  test file under tests/public_league/). Will report the full-sweep result in a follow-up note if
  it surfaces anything the targeted runs didn't.

**Deliberately NOT claiming:**
- Any UI/frontend surface for this (that's `/league`'s existing rendering of these same backend
  fields — no frontend change needed or made).
- Public League Experience v3 (`C9-V3-01`) — this repair is a stated *precondition* for it per the
  scope manifest, not the feature itself.
- Whether an individual retired owner's OWN franchise page should be directly *linked* from
  anywhere now that it resolves correctly — out of scope; only the underlying data/count defect is
  fixed here.
