# V1 70% sprint — Claude 1 (Roster Intelligence) report

**Date:** 2026-08-21. **Measured against:** `main` `0a5267d06` (fetched fresh
at the start of this pass). Denominator at that head: **65 / 136 = 47.8%**.

This lane does not promote rows — `docs/VERSION_1_COMPLETION_CONTRACT.md` is
Claude 5's alone to edit. Everything below is evidence + recommendation for
Integration to act on.

---

## Priority A — V1-32 closure audit

**Result: `V1_32_CLOSURE_READY`.**

The contract's row note (written at `bd7ae1f59`, 2026-08-20 22:55:49 UTC)
names one blocker: *"the backend single-owner discovery guard ... is #1004,
which is not on `main`."* That was true when written. **#1004 merged 31
minutes later**, at `25ec0826a` (2026-08-20 19:26:44 **-0400** = 23:26:44
UTC) — confirmed by `git merge-base --is-ancestor` and by
`tests/roster_intel/test_strength_weakness_single_owner.py` existing and
passing on `origin/main` today. The blocker is stale, not open.

Re-verified from scratch rather than trusted:

1. **L2 board evidence, re-run at current `main`** (`0a5267d06`) via
   `python scripts/verify_roster_intelligence.py --offline`:
   **216 rungs** (check 02, PASS, EVIDENCE-L1), **215 rung credits**
   (check 10, PASS, EVIDENCE-L2), **0 violations**, **11 passed / 0 failed
   / 2 UNMEASURABLE** — identical to the evidence already on record.
   (Two immaterial denominator drifts from board refresh: check 04's
   member count 374→371, check 08's unpriced count 86→84 — both are the
   live board moving, not this row's code.)

2. **The decisive mutation, reperformed with a real duplicate, not a
   string.** Wrote a TRACKED file,
   `src/league_intel/_v32_mutation_reproof.py`, outside
   `src/roster_intel/weakness.py`, containing a second `TeamWeakness`
   dataclass and a second `build_team_weakness()` that reimplements the
   real rung-threshold rule (`threshold_rank = rung * team_count`) against
   a roster list — an implementation-shaped duplicate, not a stub. `git
   add`ed (the guard scans tracked files only — an untracked probe is
   invisible to it, a mistake this lane has made and discarded before).
   Ran `tests/roster_intel/test_strength_weakness_single_owner.py`:
   **RED**, naming the exact file —
   `{'TeamWeakness': ['src/league_intel/_v32_mutation_reproof.py'],
   'build_team_weakness': [...]}`. Deleted the probe: **GREEN**, 5/5.
   Working tree confirmed clean afterward (`git status --short` empty).

3. **Semantics confirmed, not merely re-asserted:**
   - threshold ladder — `rung * teamCount`, unchanged, re-measured at 216
     rungs above;
   - no double-credit — check 10 re-measured at 215 rung credits, 0
     violations;
   - missing stays missing — `weakness.py`'s own contract (`unfilled` /
     `unknown` vs `unmet`, never coerced) is untouched; no code in this
     pass came near it;
   - **L2, not L4** — re-derived from primary sources in the prior PR
     (#1007) and re-confirmed here: `docs/VERSION_1_COMPLETION_CONTRACT.md`
     §2's own ladder puts a frontend consumer at L4, and V1-32's declared
     target level is L2. `grep -ri weakness frontend/` is still zero hits
     on current `main` — no frontend consumer exists, none is required,
     none was built.

**No code changes were needed or made for V1-32 itself in this pass** — the
guard, the owner, and the evidence were already correct on `main`; this was
re-verification.

**Recommendation to Claude 5:** promote V1-32 to `VERIFIED` at L2. Both
halves the row's own bar names — the retirement guard (now on `main` via
#1004) and the L2 board measurement (re-confirmed above, and durably
reproducible via #1007's `--offline` flag) — are satisfied and dated
2026-08-21.

---

## Priority B — PR #1002 × current-main conflict/semantic map

**Do not rebase, do not modify #1002.** This is a map, produced by
rehearsing the real merge in a disposable local branch
(`_scratch_1002_reconcile_rehearsal`, created off `origin/main`, merged
`origin/claude/v1-31-v1-32-strength-weakness-guards`, fully validated, then
discarded — nothing pushed, #1002 untouched).

### 1. Exact conflicting files

**Exactly one:** `config/coercion_baseline.json`. All 7 other files #1002
touches —

```
docs/roster-intelligence/V1_35_METRIC_SEPARATION_AUDIT.md
frontend/__tests__/components/team-phase-panel.test.jsx
frontend/__tests__/no-frontend-team-strength-methodology.test.js
frontend/__tests__/team-phase.test.js
frontend/app/phases/page.jsx
frontend/components/TeamPhasePanel.jsx
frontend/lib/team-phase.js
```

— are **untouched on `main` since #1002's base** (`d5b62aed4`), confirmed by
`git diff --stat d5b62aed4 origin/main -- <each path>` returning empty for
all seven, and by the rehearsed merge auto-resolving all seven with zero
conflict markers.

### 2. Which side must "win"

**Neither — this is the documented `coercion_baseline.json` double-edit
trap**, named in `CLAUDE.md` itself: *"two PRs that both touch
`config/coercion_baseline.json` merge cleanly and corrupt silently ...
The second one's candidate is built after the first lands, and its
baseline regenerated from that tree."* Here it does NOT merge silently —
GitHub reports `mergeable_state: "dirty"` — because both sides edit the
same line (line 3, the `"count"` field):

| side | change | line touched |
|---|---|---|
| `main` (independent, via #992 / V1-97) | `663 → 662` (removes one stale `src/public_league/activity.py` coercion) | line 3 only (plus line 417, no overlap with #1002) |
| `#1002` | `663 → 661` (removes two stale `frontend/lib/team-phase.js` coercions) | line 3 only (plus lines 184/186, no overlap with `main`'s line 417) |

Confirmed with `git diff -U0 ... -- config/coercion_baseline.json | grep
'^@@'` on each side independently — the array-line removals never overlap;
only the `"count"` line does.

### 3. Current-main changes that must be preserved

**One:** the `src/public_league/activity.py::out.append(float(valuation(asset)
or 0.0))` coercion removal, landed on `main` via **#992** (V1-97 /
`C3-REPLAY-01`, hindsight-leak fix in the public activity feed). Unrelated
to #1002's own work; must survive the merge intact. (Confirmed present in
the rehearsed merge result outside the conflict region.)

### 4. Exact mutation needed after reconciliation

**Do not hand-resolve the JSON.** Resolve the conflict markers by keeping
both sides' array-line removals (git already does this correctly — no
markers appear outside line 3), then regenerate the `"count"` field the
same way the file always must be regenerated:

```
python3 scripts/check_decision_coercions.py --write-baseline
```

Rehearsed and verified: this produces **`"count": 660`** — `663 − 1`
(`main`'s fix) `− 2` (#1002's two fixes) — matching hand arithmetic exactly,
because the script wrote it, not because a number was picked. Confirmed
`scripts/check_decision_coercions.py` (no flag) then reports `660 present,
660 accepted as debt` and exits clean.

### 5. Exact L2 consequence

**Structural zero — provably, not asserted.** `config/coercion_baseline.json`
is a pure lint-debt ledger consumed only by
`scripts/check_decision_coercions.py`; it is not read by
`_compute_unified_rankings`, any contract builder, or any runtime path.
`git diff --stat <merged-tree> origin/main -- '*.py'` is empty (matching
#1002's own PR body claim, now re-verified against current `main` too). The
only conflicting file is this non-runtime ledger — zero rows, zero ranks,
zero canonical values move.

**Post-merge validation, run in the rehearsal and confirmed:**
- The 3 frontend test files #1002 touches: **18/18 pass** on the merged
  tree (`vitest run __tests__/team-phase.test.js
  __tests__/components/team-phase-panel.test.jsx
  __tests__/no-frontend-team-strength-methodology.test.js`).
- `scripts/check_decision_coercions.py` clean after regenerating the
  baseline.

**Recommendation to Claude 5:** this is a mechanical, fully-rehearsed
reconciliation with a proven-correct resolution. No semantic judgment call
remains — apply steps 3–4 above verbatim when integrating #1002.

---

## Priority C — V1-94 deep audit

**Result: repair already correct on `main`; one verification gap found and
closed. PR:
[#1015](https://github.com/jasonleetucker-code/riskittogetthebrisket/pull/1015)
— `FEATURE_GREEN` / `READY_FOR_INTEGRATION`.**

Determined from current-main code, not the old #914 description:

- **The repair exists.** `src/api/team_assignment.py` models three
  distinct failure states — `no_current_season` / `no_rosters` (total,
  `available: False`) and `player_directory_unavailable` (partial,
  `available` stays `True`, `rosterScoringAvailable: False`) — and an
  explicit `_unavailable()` helper that names the cause rather than
  serving a bare empty list.
- **The intended consumer receives explicit availability.**
  `frontend/app/league/sections/team-assignment.jsx` branches on
  `data.available === false` first, then handles the healthy-empty case,
  then treats `available === undefined` (an old server response) as
  *unknown*, not healthy — never silently blank, never a fabricated
  diagnosis.
- **No current path converts missing/degraded to empty success**, checked
  at all three layers: the section builder itself (mutation-tested, see
  below); the aggregate assembly
  (`public_contract.py::build_section_payload` /
  `build_public_contract`, no swallowing `try/except` before
  `assert_public_payload_safe`); the HTTP route
  (`server.py::get_public_league`, a genuine exception returns 503 with an
  explicit error, never a fabricated 200).
- **The E2E fixture is non-vacuous.** Read
  `tests/e2e/specs/public-league.spec.js:577` in full: it asserts strict
  properties on both branches — `available:false` must name one of two
  machine-readable reasons and carry zero assignments; `available:true`
  must match the exact current-manager `ownerId` set from the same
  response's league header, enforce favorite-first ordering, and enforce
  that every non-favorite team ccleared the point threshold. Not a smoke
  test. (It runs in `prod-e2e-smoke.yml`, i.e. against production
  post-deploy — not the PR gate.)

**Mutation re-proof, twice:**

1. Reintroduced the literal #815 defect (`return {"assignments": []}` when
   `snapshot.current_season is None`) and ran the existing unit suite
   (`tests/api/test_team_assignment_availability.py` +
   `test_team_assignment.py`): **2 named REDs**
   (`test_no_current_season_is_unavailable_not_empty`,
   `test_build_section_no_current_season_returns_empty`). Restored: 37/37
   green.

**The genuine gap:** every existing test builds its `PublicLeagueSnapshot`
**by hand**. Nothing exercised the degraded path through the real
assembly pipeline (`build_public_snapshot` → `build_section_payload` →
`assert_public_payload_safe`) the way
`test_every_section_is_safe_on_its_own` already does for the healthy path.
Added two tests to `tests/public_league/test_public_contract.py`:

- a healthy-path check against the existing stub fixture (`available:
  True`, 4 real assignments);
- a degraded-path check where an **unknown league id** makes
  `sleeper_client.fetch_league` return `None`, which `build_public_snapshot`
  itself turns into zero seasons — a real degraded-fetch shape produced by
  the real code, not a hand-built dataclass — and confirms `available:
  False`, `unavailableReason: "no_current_season"`, `assignments: []`,
  surviving `assert_public_payload_safe`.

2. Reran the same mutation against this new file: **RED**
   (`KeyError: 'available'`) — confirming a regression here would be
   caught by the real-pipeline test too, not only the isolated unit test.
   Restored: green, `git diff` empty on `src/api/team_assignment.py`.

**No implementation change was made or needed.** This closes a
verification gap (the degraded path had never been proven through the
real pipeline), not a defect.

**Recommendation to Claude 5:** merge #1015, then promote V1-94 to
`VERIFIED` at L2 — L1 (mutation-tested, both isolated-unit and
real-pipeline levels) plus a measured statement of the contract's exact
behavior in both branches through the real pipeline satisfies the row's
own bar.

---

## V1 EASY WIN REPORT — CLAUDE 1

Every non-`VERIFIED` row whose **lane column reads `L1` (Roster
Intelligence)** in `docs/VERSION_1_COMPLETION_CONTRACT.md` §3, at
`main` `0a5267d06`. (Rows that merely *mention* "roster" but are
lane-owned elsewhere — V1-39/40/41/42/43/44, all lane `L2` Trade
Intelligence — are named at the end for completeness, not counted here;
claiming them would be exactly the second-owner problem this campaign
exists to prevent.) Age/Window/Portfolio **expansion** work (post-V1,
beyond V1-33's shipped basic index) is excluded per instruction.

| row | current status | required level | evidence already present | exact missing proof | classification | expected numerator points | blockers | PR/commit refs |
|---|---|---|---|---|---|---|---|---|
| **V1-32** | `IN PROGRESS` (stale note) | L2 | 216 rungs / 215 credits / 0 violations, re-measured today; single-owner guard on `main` since `25ec0826a`; mutation re-proof RED→GREEN this pass | none — row note is the only stale artifact | **READY_TO_VERIFY** | +1 | none | #1004 (merged), #1007 (merged), this report |
| **V1-94** | `IN PROGRESS` | L2 | repair correct on `main`; unit mutation RED→GREEN (37/37); new real-pipeline mutation RED→GREEN | none — closed this pass | **READY_TO_VERIFY** | +1 | none, pending PR merge | #1015 (open) |
| **V1-35** | `NOT STARTED` (stale — status text predates the merged retirement) | L1 | Backend: `tests/roster_intel/test_metric_separation.py` 10/10, mutation-proven, on `main` today. Frontend: `no-frontend-team-strength-methodology.test.js` 6/6 on `main` today — `scoreTeamTiers` is retired (`frontend/lib/league-analysis.js` carries only a `RETIRED` comment where it used to live) and `/rosters` renders `TeamStrengthCard.jsx`. Both halves of decision 69's "in the model **and** the UI" bar are met on `main` **right now**, independent of #1002 (which closes a *different* live duplicate, F-3/`/phases`, not a decision-69 violation — the audit's own §2 explicitly distinguishes "an invented composite" (F-1, closed) from "a legitimate concept computed in the wrong place" (F-3, not a collapse)) | none found in this pass — genuinely re-verified, not assumed | **READY_TO_VERIFY** | +1 | none | `tests/roster_intel/test_metric_separation.py`, `frontend/__tests__/no-frontend-team-strength-methodology.test.js`, both on `main` |
| **V1-27** | `IMPLEMENTED_UNVERIFIED` | L3 | L1 done (10/10 vs Sleeper truth); L2 done (§10a items 1/3a/5 PASS — 12/12 lineups, 4 hybrids correctly forbidden-slot-excluded) | items 2–3 need a credentialed run against the **deployed** endpoint (`ROSTER_VERIFY_COOKIE`); item 4 is `PARTIAL` for the same reason | **PRODUCTION_BLOCKED** | 0 (until a deploy + credentials are available to Integration) | needs prod auth this session does not hold | `docs/lineup/C2_U1_CANONICAL_LINEUP.md` §10a; `scripts/verify_roster_intelligence.py` (`--base-url` + `ROSTER_VERIFY_COOKIE` path, already built) |
| **V1-31** | `IN PROGRESS` | L2 | Owner built (#914, on `main`); F-3/H-2's live duplicate retirement (#1002, CI green, zero comments) proven mergeable with a fully-rehearsed, zero-ambiguity resolution (Priority B above); backend single-owner guard on `main` since #1004 | #1002 itself needs to land — a **mechanical** merge per the map above, not a decision | **SMALL_REPAIR** (mechanical merge only — no code judgment call remains) | +1 once #1002 lands | none — the map in Priority B is the complete remaining work | #1002 (open, frozen per instruction), #1004 (merged) |

**Not counted — lane `L2` (Trade Intelligence), named only so nobody
re-discovers them as "roster rows":** V1-39 (`VERIFIED` already), V1-40
(`IN PROGRESS`), V1-41/42/43 (`NOT STARTED`), V1-44 (`VERIFIED` already).
`C2-SIM-01`/`simulate_roster_change`/`pool_cut_ladder` are built in this
lane's own `src/roster_intel/` package, but the **V1 row crediting** for
roster simulation and capacity analysis is Trade Intelligence's per the
contract's own lane column and per `C2_CANONICAL_ROSTER_CHAIN.md` §14
("Capacity / forced drop — NOT here. `C3-CAP-01` is trade-owned").

### Realistic ceiling from this lane alone

L1 (Roster Intelligence) contains **9 rows total** (V1-27…V1-33, V1-35,
V1-94) — 5 already `VERIFIED`, 4 addressed this pass (3 `READY_TO_VERIFY`,
1 `SMALL_REPAIR` pending a mechanical merge, 1 `PRODUCTION_BLOCKED`). If
V1-32 / V1-94 / V1-35 promote and #1002 lands, this lane reaches **8/9**
— the ceiling is V1-27, genuinely blocked on production credentials this
session does not hold. That moves the repo-wide denominator from 65/136 to
at most **69/136 = 50.7%** — real progress, but the stated 70.6% campaign
target is not reachable from this lane alone; it spans L1–L8, and most of
the denominator (Trade/Season/Market/Frontend/Governance rows) sits
outside Roster Intelligence's scope. Reported honestly rather than
inflated.

---

## Handoff

- **V1-32**: `V1_32_CLOSURE_READY`. No PR needed — re-verification only,
  guard and evidence already on `main`.
- **V1-31 / PR #1002**: conflict map above. Frozen, untouched, exactly as
  instructed.
- **V1-94 / PR #1015**: `FEATURE_GREEN` / `READY_FOR_INTEGRATION`.
- **V1-35**: flagged `READY_TO_VERIFY` — no PR opened (pure status-staleness
  finding, no code or test gap); Claude 5's call on whether a status-only
  contract edit needs its own commit or rides with the V1-32/V1-94
  promotions.
- **V1-27**: `PRODUCTION_BLOCKED`, named so it isn't re-discovered as an
  open question — the tooling to close it (`scripts/verify_roster_intelligence.py
  --base-url ... --expect-sha ...`) already exists; it needs Integration's
  deploy access, not more Roster-lane work.

**FREEZE** — no further pushes to #1002 or #1004 (merged) from this lane.
#1015 stays open for its own CI/review cycle under the standard drive-to-green
posture (it is this lane's own PR).
