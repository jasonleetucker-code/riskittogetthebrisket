# Autonomous Engineering Org — Canonical Execution Plan

Maintained by the main orchestrator session. This file IS the unified plan,
ownership model, git/integration policy, and dashboard. Update on every
material change. Supersedes ad-hoc per-track instructions.

**Last dashboard rebuild: 2026-07-26 ~22:10 UTC, against `origin/main` =
`ec60cdb0e`.** Statuses in §1 and §6 were rebuilt from artifacts — merged
SHAs, open PR numbers, pushed branches — rather than carried forward from
prior text. Anything that could not be tied to an artifact was downgraded
to *not started*. If you are reading this well after that timestamp,
re-verify before relying on §1, §5 or §6; the rules sections (§2, §2a,
§2b, §2c, §3) are durable and do not expire.

Target: **comprehensively functional, integrated, polished product in ~1
week** (by ~2026-08-02). Optimize for the final integrated system, not
constant main-branch stability.

## 1. Workstreams & ownership (one owner each)

**Dashboard rebuilt from artifacts 2026-07-26 ~22:10 UTC**, against
`origin/main` = `ec60cdb0e`. Status vocabulary is now strict and every
cell must cite the artifact that earns it:

- **Done** → a merged commit SHA on `main`.
- **In review** → an open PR number.
- **In progress** → a pushed branch name.
- **Not started** → everything else, regardless of prior claims.

Statuses that could not be tied to one of those were downgraded, not
carried forward. Fifteen PRs merged today and the previous dashboard
predated nearly all of them.

| WS | Workstream | Owner (agent) | Branch | Scope (exclusive) | Status |
|---|---|---|---|---|---|
| A | Redesign R2 — rankings + profiles | design custodian | claude/redesign-r2-rankings | frontend/app/rankings/, PlayerPopup, ds/ additions | **Done** — `9ccdecea6` (#549) |
| B | Redesign R3 — dashboard, news, market surfaces | design custodian | claude/redesign-r3-surfaces | frontend/app/{page,news,edge,finder}/ | **Done** — `253568bc4` (#551), 19:38 UTC |
| C | Redesign R4 — draft war room + trade surfaces | design custodian | claude/redesign-r4-warroom | frontend/app/{draft,trade,trades,angle,waivers}/ | **Done** — `49e005b2a` (#552), 20:04 UTC |
| D | Redesign R5 — perf/a11y/mobile sweep + dead-CSS purge | design custodian | claude/redesign-r5-polish | global CSS, cross-page | **In progress** — branch pushed, 17 commits / 33 files ahead of main, last push 21:37 UTC. No PR yet. Phase A (`/league` Card→Panel) and phase B (ROS sections, league-comparison) are on the branch only |
| E | League Intelligence LI-1..LI-8 | league-intel agent | claude/league-intel-foundation | src/league_intel/, config/league_intel/, tests/league_intel/, coordinated: registry.json, src/ros/lineup.py | **Done** — `608610c9d` (#550) lands LI-1..LI-8, 20:37 UTC; League Twin bridge + sim calibration `7cdc4070f` (#565), 21:15 UTC. The registry/`DEFAULT_STARTER_NEEDS` staleness is fixed in production (verified by direct read on main) |
| F | LI-9 UI (valuation-mode toggle) | design custodian | — | R1 shell TopBar + getActiveValue adoption | **Not started** — no branch, no PR. Its blockers (E, A) have both cleared, so it is now unblocked rather than blocked |
| G | E2E safety net upkeep | e2e agent | claude/e2e-r1-reconcile → claude/e2e-abort-guard | tests/e2e/ | **Done** — `e55f791b8` (#559), 20:38 UTC, which contains #554 in full (verified: `12cf9dceb` is an ancestor of the #559 head, so #554 was closed rather than merged). Assertion audit `ca41c981c` (#566), 21:40 UTC |
| H | Identity sweep close-out | identity agent | claude/identity-sweep | identity joins (re-scoped post-merges) | **Done** for #547 (`2aa7e56d4`). Residual aggregate-join defect handed over by #550 (6 duplicate rows, 40/666 join failures) is **not started** — no branch, no PR |
| I | Ops: refresh/deploy/intel cron, VPS | orchestrator | main (dispatch only) | workflows, monitoring | **Done** — deploy skip/reverse guard `998572713` (#560); auth status-timeout fix `1ec3311be` (#558); domain remediation + `grant-ssh-access.yml` deleted (`c534280db`). **Outstanding for the operator: still no TLS on the bare IP** |
| J | Roster & Trade Intelligence (additive on WS-E) | 3 agents, see below | claude/ws-j-* | src/roster_intel/, coordinated: src/trade/ | Engine **Done** — `4f9cb05b6` (#562), `783721534` (#563). **But it has no callers — see §6.3. "Merged" here does not mean "shipped."** F-1 rewiring of `angle.py` still open (§6.2); refit gate in progress (§6.1) |
| R | Fresh-eyes review | reviewer agent | read-only | PR comments | **Done** — #567 merged `ec60cdb0e` at 22:06 UTC. No PRs currently open |

Idle agents with retained domain context (resume, never cold-spawn):
intel, FAAB, playerctx, news, prod-hardening — reassigned as B/C owners or
LI contributors as checkpoints arrive.

## 2. Git & integration policy (REVISED — effective now)

Old mode (per-task PR, merge-on-green, ~13 merges/day) is retired. New:

1. **One branch per WORKSTREAM**, not per task. Batch logical commits;
   checkpoint-commit at least at each completed sub-milestone. Push
   regularly (container loss protection) — pushing ≠ PR.
2. **PR only at integration checkpoints** or when: cross-workstream
   contract must become canonical (e.g. LI registry fix), risk warrants a
   rollback boundary, or a workstream is complete.
3. **Two scheduled integration windows**: mid-week (~2026-07-29: R2+R3+R4
   merged in dependency order; LI-1..LI-4 merged; E2E reconciled) and
   final (~2026-08-01: everything; full-system validation).
4. Reviewer runs at integration windows (and on high-risk diffs), not per
   push. CI runs on PRs as before — fewer PRs = fewer runs.
5. Data-refresh/deploy automation on main is unaffected.
6. Safety: no destructive resets, no force-push on shared branches, no
   cross-agent file edits without registry entry, secrets untouched.

## 2a. Git mechanics that cost real time (2026-07-26)

Two process findings from today. Both are cheap to avoid and expensive
to hit.

**Squash-merge breaks ancestry — a rebase onto a squash-merged branch is
not a rebase.** When a PR is squash-merged, its branch head is *never*
an ancestor of `main`. Basing new work on that branch head and then
"catching up" to `main` produces a working tree that silently reverts
everything merged in between. This happened twice today and on the
second occasion nearly reverted three merged PRs (#552, #558, #560 —
thirty-plus files) inside what `git status` displayed as a four-file
docs change. The diff was a three-PR revert wearing a docs PR's
clothing.

Rebase onto `origin/main` directly, never onto another PR's branch, and
then run the check that catches it:

```
git diff --stat origin/main HEAD    # must show ONLY your own files
```

That check is the whole defence. It is one command, it is unambiguous,
and it is the reason #567 shipped as four files. Run it after every
rebase — #567 went through five while merges landed underneath it.

**ADR numbers collide because they are chosen at authoring time against
a base that moves before merge.** Two agents authoring concurrently both
pick "the next number" from the same starting state, and whoever merges
second is already wrong. This happened twice today (ADR-012 and
ADR-013); both were caught and hand-renumbered before merge, which is
why `main` reads clean and the collisions leave no artifact.

One collision *did* survive, across files: `docs/league-intelligence/DECISIONS.md`
carries **ADR-008** (replacement levels, from #550) and
`docs/roster-trade-intelligence/DECISIONS.md` carries a *different*
**ADR-008** (Continuous Improvement, from #564). Cross-file numbering
was never namespaced, so the per-file sequences collide by
construction.

**This wants a convention change, not a third manual renumber.** Options
worth ten minutes at the next window: namespace the prefix per document
(`LI-ADR-nnn`, `RTI-ADR-nnn`), or allocate at merge time rather than
authoring time. Renumbering by hand a third time is the one option that
guarantees a fourth.

## 2b. Standing evidentiary rule (all workstreams)

**An external check that agrees with a number derived under an assumption
is not evidence — it is the assumption reflected back.**

Recorded because it has now happened three times in the LI workstream
alone, each time looking like an independent source landing on our number:

1. FantasyPros "1.0015 premium" — artifact of scale compression; nearly
   certified a false calibration.
2. Naive-cut 1.239 "agreement" — the endpoint asymmetry, opposite sign.
3. 1.316 vs KTC's 1.320 (0.004 apart) — a *measured* league endpoint
   against an *assumed* reference.

Before citing agreement with an external source as corroboration, state
which side of the comparison is measured and which is assumed. If either
end rests on an assumption the external source does not share, the
agreement carries no information. This is the same failure mode as the
vacuous-pass gates ("controls at unity" when controls cannot move by
construction) and the self-caught vacuous checks — always ask what the
check would look like if the hypothesis were false.

The inverse form bites too: a condition that can never *fire*. LI-7
computed `projection_corroborated` from `applied` axes, where `applied`
requires `factor != 1.0` — while the corroboration axis carries factor 1.0
by design, so corroboration was structurally invisible and would have
silently discarded LI-6's entire contribution the day it arrived. It
surfaced only because a test asserted confidence should rise and it
didn't. **Write the test that fails if the mechanism is disconnected**,
not just the test that passes when it works.

**A named failure mode: an underfed fixture is indistinguishable from a
collapsed metric.** When a metric reads constant across every real
subject, there are two candidate explanations and they look identical
from the outside — the metric collapsed, or the harness never supplied
the input the metric needs. Check the second one first; it is cheaper
to rule out and, in this repo, has been the answer.

WS-J measured the competitive window across the 12 real rosters and
found the trajectory axis pinned at exactly 0.500 for every team, with
`productive_struggle` the most-likely state for none of them. That
reads as a broken classifier. It was a starved fixture: the test joined
rosters to the ROS aggregate, which carries no ages, while
`data/public_league/nfl_players_full.json` had been sitting in the repo
the whole time with 10,954 ages and 11,866 `fantasy_positions` entries.
Joining it moved trajectory to 0.196–0.684 and the window to all five
states. The first report went out claiming "no committed artifact
carries ages" — a data-gap finding that was really a harness bug, and
the more damaging error of the two because it would have sent someone
to build an ingestion path for data already present.

The `_positional_coverage` incident (100.00 for all 12 teams) is the
same shape from the other direction, which is exactly why the two
cannot be told apart by staring at the output. **Before reporting a
constant as a finding, prove the metric was fed** — assert the input
coverage the fixture achieved, not just the output it produced.

The inverse has teeth too: **a state that can never fire looks exactly
like a state that never happens.** `productive_struggle` was not rare
on this league, it was unreachable — one axis being inert made a whole
category structurally impossible, and no amount of staring at the
distribution would have shown that, because the other four states
summed to 1.0 and looked plausible. When a category never appears, ask
whether it *can* appear before concluding anything about the world.
The same logic condemned LI-7's `projection_corroborated` above.

A third form: the fix that reads correctly but cannot take effect. R3's
mobile-order restoration was **inert on first write** — a media query adds
no specificity, so `.col{display:contents}` inside `@media` and a bare
`.col{display:flex}` are both (0,1,0) and source order decides; the base
rule sat after the media block, so flex won at every width. The diff would
have reviewed as a correct restoration while rendering exactly like the
regression it fixed. Caught by running the new assertions against the
**pre-fix** stylesheet and requiring them to fail there. Adopt that as the
standard for any regression test: **a test that has never been observed
failing is not yet evidence.** The same pass also found the matcher
succeeding on the CSS *comments* documenting the rules rather than the
rules themselves — strip prose before asserting on source.

## 2c. Named failure mode: the guard that cannot take effect

**A fix or guard that reads correctly, reviews clean, and cannot
possibly run.** Four instances of this one shape landed on 2026-07-26.
It is now the most frequently recurring defect class in this repo, and
it is invisible to code review by construction: the diff is correct.
What is wrong is that the code is never reached, never parsed, never
selected, or never handed the data it reads.

The four, with what each actually cost:

**1. A workflow that could never parse.** `e2e.yml` carried
`E2E_PAGE_ORIGIN` twice in one mapping — same value, two complementary
comments, a merge artifact. GitHub Actions rejects a workflow with a
duplicate mapping key outright; ordinary YAML parsers silently keep the
last one, so every local sanity check passed. **All nine runs of this
workflow to date were startup failures with zero jobs** (verified:
`created_at == updated_at` on every run, and `list_workflow_jobs` on run
1 returns `total_count: 0`). A workflow that cannot start looks exactly
like one that starts and finds nothing wrong. Fixed in #559
(`e55f791b8`).

  *Two corrections to how this has been described.* The duplicate never
  existed on `main` — main's copy, from #543 (`63501a168`), has always
  had exactly one `E2E_PAGE_ORIGIN`, and #559's committed diff removes
  only a comment block, leaving the key line as unchanged context. The
  duplicate lived on the E2E branches; all seven run-head SHAs
  (`2a264e2f`, `deecf623`, `84b28a51`, `010e7795`, `12cf9dce`,
  `9f549b6a`, `1fcd0db9`) carry two occurrences. And the scheduled suite
  has indeed never run, but **not because of the duplicate**: `e2e.yml`
  triggers on `schedule` (cron `23 6 * * *`) and `workflow_dispatch`
  only, it landed on main at 07:06 UTC on 2026-07-26 — after that day's
  06:23 UTC slot — and scheduled runs execute from the default branch,
  whose file was always valid. **First scheduled run is due 2026-07-27
  06:23 UTC and will be the first real test of the nightly path.** Treat
  that run as unproven, not as a regression signal.

**2. A regression guard deselected by the step meant to run it.** Still
open; see §6.1. This is the live one.

**3. A fix reading a key nothing writes.** LI-8's hybrid-eligibility
correction built `RosterPlayer.fantasy_positions` from
`p["fantasyPositions"]`, but the producer never emitted that key. With
it empty, `eligible_positions()` falls back to `(position,)` and every
DL/LB hybrid is matched position-only — **the algorithm was fixed while
the data still expressed the bug.** An exact solve is only as good as
the eligibility it is handed. Worth 0.00–4.72 weekly points, mean 1.56,
on 10 of 12 rosters; the one roster with no multi-position players costs
exactly 0.00, and that control is what makes it a measurement rather
than noise.

  *Correction:* on `main` this never shipped. Producer and reader landed
  together in **#550** (`608610c9d`) — `src/ros/playoff_sim.py` has zero
  occurrences of `fantasyPositions` before that commit and four after.
  #565 (`7cdc4070f`) only refactored the read and carries the
  measurement; its diff shows the `_pluck` emission as a context line.
  The inert-fix episode was a pre-#550 branch state, caught before it
  reached production.

**4. A guard unloaded by the flag used to verify it.** Playwright's
`--reporter` CLI flag **replaces** the config's reporter array rather
than appending to it. Every local verification of #559's mid-run
stack-death guard had therefore silently unloaded the very guard being
verified — and *never invoked* and *invoked but quiet* produce
byte-identical output. Proven with a module-level probe. CI is
unaffected (neither `npm run e2e` nor `e2e.yml` passes the flag), and
the constraint is now documented as load-bearing. Documented in #566
(`ca41c981c`).

### The rule

**Verifying a guard requires proving it ran, not observing that it was
quiet.**

Silence is not evidence. A guard that never executed and a guard that
executed and found nothing emit the same thing: nothing. Every one of
the four above was "verified" by someone looking at a quiet output and
concluding the quiet meant health.

So the check must produce a *positive* trace:

- Assert the guard fired at least once — a module-level probe, a
  counter, a log line the test asserts on.
- Run the new assertion against the **pre-fix** state and require it to
  fail there. A test that has never been observed failing is not yet
  evidence.
- For CI gates, confirm the job actually executed: non-zero job count,
  non-zero collected-test count. `pytest` reporting `13 deselected, 0
  run` is a passing exit code and an empty check.
- When a flag or config controls whether the guard loads, verify under
  the exact invocation CI uses, not a convenient local one.

This sits directly alongside §2b's evidentiary rule and the
underfed-fixture finding above, and it is the same underlying question
in a third costume: **ask what the check would look like if the
hypothesis were false.** For a vacuous check the answer is "identical".
For a guard that never ran, the answer is also "identical". Both are
answered by demanding a positive trace rather than an absence.

## 3. Shared contracts (frozen unless custodian approves)

- **ds/ component APIs + tokens** (design custodian) — R3/R4 consume, may
  ADD primitives, must not mutate existing APIs.
- **nav-model.js** (design custodian) — single IA source; R3/R4 register
  routes only.
- **Data contract /api/data + buildRows purity** (orchestrator) — frozen;
  no client-side value math ever.
- **league_registry rosterSettings** (league-intel agent, LI-1) — being
  corrected; consumers verified in that PR; afterwards frozen.
- **Sleeper stat-key vocabulary** (ADR-005) — LI event schema.
- **getActiveValue() selector** (LI-4) — defined early so R-phase pages
  can adopt without waiting for the adjustment engine (no-op = consensus).
- High-conflict files: server.py (append-only sections per workstream),
  package.json/lockfile (single-owner edits, coordinate via registry),
  globals.css (R5 owns the purge; others additive only).

## 4. Dependency graph (critical path bold)

**R2 → (R3 ∥ R4) → R5 → final integration**
**LI-1/2 → LI-3 (lineup exactness) → LI-5 (replacement) → LI-7 (adjusted values)**
LI-4 (value schema/selector) → independent after LI-1; unlocks F.
LI-6 (projection re-scoring) after LI-2; feeds LI-7.
LI-8 (sim/League Twin ext) after LI-3; enhances trade UI (R4 seam: display-only).
G tracks A-D (SEL registry). H independent. I independent (user unblocks intel).

**Discharged as of 2026-07-26:** R2, R3, R4 and LI-1..LI-8 have all
merged, so the only live edge on the critical path is **R5 → final
integration** (WS-D, branch pushed, no PR). LI-4 has landed, which means
**F is unblocked and unstarted** — it is now the longest-dated piece of
unbegun work in the plan.

## 5. One-week backward plan

**Revised 2026-07-26 22:00 UTC.** Integration window #1 was scheduled for
Mon–Tue and effectively ran tonight instead — R2, R3, R4, the full LI
batch and E2E all merged on Sunday, roughly two days early. The plan
below is rewritten from that actual position rather than the original
projection.

- **~~Now–Sun~~ DONE**: R2 (`9ccdecea6`), R3 (`253568bc4`), R4
  (`49e005b2a`), LI-1..LI-8 (`608610c9d` + `7cdc4070f`), E2E
  (`e55f791b8` + `ca41c981c`), ops hardening (`998572713`,
  `1ec3311be`), WS-J engines (`4f9cb05b6`, `783721534`), model registry
  (`a5a8b8676`), engine-divergence measurement (`ec60cdb0e`). Fifteen
  PRs; see the merge ledger in §6.
- **Mon (next up)**: the three §6 open items, in this order —
  (1) land the refit gate from `claude/ws-j-refit-gate` so the weekly
  refit stops shipping unchecked constants (§6.1, has a branch, needs a
  PR); (2) rewire `angle.py` onto the single-market path (§6.2);
  (3) decide the surface for `src/roster_intel/` and wire it, or
  explicitly park it — right now it is merged code with no consumer
  (§6.3). Also: resolve the #555 page-proxy decision.
- **Tue–Wed**: WS-D R5 sweep lands (branch is 17 commits deep, needs a
  PR); F (LI-9 valuation-mode toggle) is now **unblocked** and unstarted
  — its dependencies E(LI-4) and A both merged; WS-H residual
  aggregate-join defect.
- **Thu–Fri**: golden backtests; the first real nightly E2E signal
  (first scheduled run 2026-07-27 06:23 UTC — treat it as unproven, not
  as a baseline).
- **Fri–Sat**: final integration window — full-suite + E2E + visual pass,
  perf, docs, release checklist, deploy, VPS apply notes for user.
  **Blocking for the operator: still no TLS on the bare IP.**

## 6. Open merge blockers

The three items below are the load-bearing open facts as of
`origin/main` = `ec60cdb0e`. Each was verified against the tree, not
carried forward from a claim. Everything after §6.4 is the historical
record of already-resolved blockers, retained deliberately.

### 6.1 The weekly Hill-curve refit still ships unvalidated constants — OPEN

**Status: open.** `.github/workflows/refit-hill-curves.yml` rewrites the
eight `HILL_*_C/S` constants in `src/canonical/player_valuation.py`,
commits them to `main`, and triggers a deploy. Its regression guard
cannot fail, for three independent reasons — and the third is the one
that matters:

1. **The pins are recomputed from the challenger.**
   `rebaseline_ktc_reconciliation` writes `pinned_ours = _hill(p, c_new,
   s_new)` and then measures against it, so the residual is zero by
   construction.
2. **KTC is itself a training source**, so the check shares the very
   assumption it is meant to test — §2b's exact shape.
3. **The guard never executes.** Verified on current `main`:
   `tests/conftest.py::_LIVEDATA_MODULES` contains
   `test_ktc_reconciliation.py` (line 87), and the workflow's test step
   runs `python -m pytest tests/ -q -m "not livedata"` (line 127). The
   guard is deselected by the very step meant to run it — 13 deselected,
   0 run. Constants reach production with no check of any kind.

This is instance 2 of §2c, and the only one still live. The repo
half-knew: the workflow's own comment says gating on the pins "is
circular", and that reasoning was used to justify *excluding* the check
rather than building a non-circular one.

**#564 (`a5a8b8676`) deliberately did NOT rewire the workflow.** It built
the infrastructure — `src/model_registry/` with provenance-stamped
versioning (sha256 per training input), a single champion pointer,
promote/reject/rollback as recorded operations, a CLI, and a held-out
criterion scoring four value-publishing dynasty boards the fit never
reads (`ktcSfTep` deliberately excluded as the same market maker as
KTC). Evaluation *raises* rather than returning a passing score when it
would be vacuous. Training and holdout disagree in direction on the same
move, which is the evidence it is not a rubber stamp. #564 changed no
live values: `player_valuation.py` is byte-identical and `apply
--dry-run` is a no-op against the shipped champion. The rewiring was
left out so it gets its own review.

**Rewiring is approved and in progress** on `claude/ws-j-refit-gate`
(`e1b97edfc`, pushed 21:42 UTC, one commit ahead of main, 8 files). It
removes the `-m "not livedata"` sweep, runs
`python -m pytest tests/model_registry/ -q`, records the held-out gate
result into `config/model_registry/`, and demotes promotion to a
recorded manual action (`scripts/model_registry.py promote` + `apply`).
**No PR open yet** — per §1's vocabulary this is *in progress*, not *in
review*.

Until that lands, treat every constant the weekly refit has shipped as
unvalidated. This is a statement about the 2026-07-26 build, not a
permanent property.

### 6.2 `src/trade/angle.py` is the last unrewired cross-market call site — OPEN

**Status: open.** ADR-010 ("cross-market packages are valued on ONE
market, or not at all") is **accepted**, the interface and suppression
path are built, and the rest of the codebase has moved to the
single-market path — `src/trade/finder.py` now gates per market
(`MARKET_TOP_N_FILTER`, `marketCoverage`, `KTC_TOP_N_FILTER` retained
only as a deprecated alias) and `src/api/data_contract.py` resolves
market per row. `angle.py` did not move.

Verified on current `main`. `angle.py::_market_source_for` routes each
*player* correctly (lines 100-101: `idpTradeCalc` for IDP, `ktcSfTep`
otherwise) — so the per-row market is already known. But
`_make_candidate` then sums `market_value` across a combo that is never
constrained to one market, and `market_gain_pct` gates candidate
visibility on that sum. **A mixed offense/IDP package has its fairness
gate computed by adding KTC points to IDPTC points.**

**This is true on both sides of the trade**, which the earlier writeup
did not say: the acquire side at lines 509 and 532-533, and the offer
side at lines 471-475 and again at 919-920 in the second generator. Both
sides are unconstrained, so a mixed package is mispriced coming and
going.

Until `angle.py` is rewired, mixed packages must be suppressed or
labelled — never silently ranked. "No defensible normalization is
possible yet" remains an accepted outcome.

Cross-market context that bounds the damage: KTC and IDPTradeCalc are
directly comparable, not incommensurable — pooled median `IDPTC/KTC`
**0.9997**, Spearman **0.990** on n=476 paired players. So the defect is
a correctness and auditability failure rather than a wild
mis-scaling. That is a reason to fix it cleanly, not a reason to defer.

### 6.3 `src/roster_intel/` has no callers — the engine is merged, the feature does not exist

**State this plainly, because "merged" is reading as "shipped" and it is
not.** WS-J's Roster Intelligence Engine landed in #562 (`4f9cb05b6`)
and the trade layer in #563 (`783721534`). Both are real, tested code.
**Nothing calls them.**

Verified: `git grep -l roster_intel`, excluding `src/roster_intel/` and
`tests/roster_intel/`, returns **only three documentation files** —
`docs/CLAUDE_SESSION_AUDIT_HANDOFF.md`, `docs/ORCHESTRATION.md` (this
file), and `docs/league-intelligence/DECISIONS.md`. There is:

- **no API endpoint** — nothing in `server.py`, no route in the
  contract,
- **no UI** — no frontend import, no page,
- **no `/gameplan`** — the surface this engine was built for does not
  exist,
- **no pipeline call** — nothing in `scripts/` or the data contract
  invokes it.

The engine is a library with exactly one consumer: its own test suite. A
green test suite over an uncalled package proves the code works and
proves nothing about the product. **Wiring it to a surface is
unstarted work, and no branch exists for it** — per §1's vocabulary,
*not started*.

This is a close cousin of §2c: code that reads correctly and cannot take
effect, differing only in that nothing is even attempting to reach it.

### 6.4 Historical record — resolved blockers

Everything below documents blockers already cleared. Retained because
the reasoning is load-bearing for future work, not because it is open.

**PR #550 (WS-E) — RESOLVED 2026-07-26 (`4e3e0d95`), MERGED as `608610c9d` at 20:37 UTC.** All three blockers
cleared: PR body headline corrected (old `TE 0` / "overstated 46%" lines
explicitly retracted rather than quietly deleted), `replacement.py`
docstring corrected with a KNOWN LIMITATION section plus a warning at
`measure_endogenous_starters` itself, and the ADR restructured so the
endpoint asymmetry leads. Retained below as the record of what was wrong
and why.

**Orchestrator decision — SUPERSEDED by the merge.** The decision not to
pull the `src/ros/lineup.py` fix forward ahead of the Jul 29 window is
now moot: #550 merged at 20:37 UTC on 2026-07-26, three days early. The
figures below **are** reproducible on `main` today, and
`claude/league-intel-foundation` is no longer the place to check them.
The rationale is retained only as the record of how the call was made
(bounded production impact — composite team-strength values move but
rank order was unchanged across all 12 teams, so Pick Projector output
was stable throughout).

**The original defect.** CI was green and LI-1..LI-5 otherwise sound, but
the number the PR led with was wrong and load-bearing: every replacement
level and scarcity figure rested on it.

`measure_endogenous_starters` runs the exact optimizer on `rosValue`, a
season-long **mean**. On a point estimate a TE can only take a flex slot if
its average beats the best spare RB/WR, which essentially never happens —
hence the claimed `FLEX: TE 0` and `TE 2.00/team`. Best ball pays for
weekly spikes, not averages, so the input collapses exactly the variance
the format monetizes. The optimizer is exact; the input is wrong.

Measured on **actual 2025 weekly scoring**, re-solved under the current
21-slot vector, the artifact is confirmed by two independent passes:

| | projection (`rosValue`) | weekly actuals |
|---|---|---|
| FLEX TE share | **0.0%** | **10.4%** (orchestrator pass: 11.8%) |
| TE started/team | **2.00** | **2.215** (orchestrator pass: 2.28) |

**The `3.79` depth figure was a red herring — do not propagate it.** It was
never `starters_per_team`; it was "marginal-weighted effective depth" from
the marginal best-ball probe (how many TEs carry value, not how many
start), and it had already been retired for a 2.08× churn confound. What
actually feeds `replacement.py:576` is `starters_per_team`, which for TE
was **2.00**. The real correction is **2.00 → 2.215**.

### The dominant error was neither: asymmetric endpoints

Resolved 2026-07-26 (`b6ec0ab6`). The premium compares a 1-TE reference
against our 2-TE league. Every figure to date measured the *league*
endpoint from data while **assuming the reference was 1.0 TE/team**. It is
not. Re-solving the 1-TE vector over the same weekly scores: TE won
**27.2%** of FLEX and teams started **1.608 TE/team**.

| basis | ref | league | median | TE1-12 |
|---|---|---|---|---|
| assumed 1.0 / naive 2.0 | TE12 | TE24 | 1.239 | 1.175 |
| assumed 1.0 / actual 2.215 | TE12 | TE27 | 1.316 | 1.214 |
| assumed 1.0 / rostership 2.71 | TE12 | TE33 | 1.416 | 1.252 |
| **symmetric 1.608 → 2.215** | **TE19** | **TE27** | **1.121** | **1.082** |
| *KTC measured* | | | *1.320* | *1.227* |

Structural demand change is **1.378×**, not 2.215× — an assumed reference
overstates it by **1.61×**. **Operative premium ≈1.12**, below every prior
figure. The 1.316 row sits 0.004 from KTC and **must not be read as
validation**: it pairs a measured league endpoint with an assumed
reference, so the agreement is an artifact of the asymmetry.

Decomposition this enables: if structure warrants ~1.12 and KTC charges
1.32, the residual ~1.18× is plausibly the **scoring** component of KTC's
TEP — the first quantitative support for axis ambiguity. Suggestive, not
established.

### Bias checks

- **Roster-era**: direction **up** (2026 5.42 vs 2025 5.02 TE/team), so the
  premium is marginally overstated. Within noise at n=12. WS-E's earlier
  "downward" claim was wrong and is retracted.
- **Exclusion**: measured, and it runs the *safe* way — the 12 skipped
  team-weeks carry **more** TEs (6.17 vs 5.02) and are short at K/IDP, so
  the sample skews TE-shallow and demand is if anything understated.

### Durable fix

Option (a) adopted and ADR'd: calibrate the depth constant from actual
weekly outcomes. Depth is a league-structure constant, history is the right
input, and it avoids stacking a second fitted layer — the Gaussian model in
`playoff_sim.py:248-265` is itself an approximation, and deriving a
structural constant through it would embed its error. Option (b) remains
correct for forward-looking per-player variance. The constant is
recomputed, not frozen.

### Remaining caveats

Single season; 2026 rules applied counterfactually to 2025 rosters; missing
`players_points` treated as 0. ~~The exact optimizer + `fantasy_positions`
fix is branch-only, so none of this is reproducible on main today.~~
**Corrected 2026-07-26:** both landed on `main` in #550 (`608610c9d`) and
this is now reproducible there.

Largest remaining lever is now a caveat rather than a measurement: the
reference endpoint assumes KTC's standard board targets a league like our
2025 one (superflex, 2 FLEX). A generic 1-TE league with one flex slot
would give TEs less flex opportunity, lower the reference, and raise the
premium again.

Fixtures are vendored into the WS-E branch (slimmed to
`roster_id`/`players`/`players_points`, 248K, plus a 751-player metadata
slice); the orchestrator's `measure_flex_allocation_actuals.py` is
superseded and deliberately left uncommitted.

### PR #551 / #552 — review findings open (reviewed 2026-07-26)

Both CI-green; preservation work largely verified clean (all 8 `/edge`
sections byte-equivalent through the regroup, `/finder` `defaultSort`
correct for all 5 presets, terminal `Panel`'s 8 consumers migrated, the
sticky-tray verdict bar genuinely equivalent, FAAB contention matching the
wire format). Remediation dispatched to the design custodian.

**Cross-PR merge hazard — highest priority.** Reproduced with
`git merge-file`: exit 1, conflict at `journey.js` lines 42-102; both PRs
insert into `SEL` at the same anchor. The trap is asymmetric — R4's side of
the conflict block carries its selectors, the closing `};` of `SEL`, *and*
the whole `const NAME = {...}` declaration, while R4's `module.exports`
edit adding `NAME,` is a separate hunk that **auto-merges cleanly**. The
natural resolution (keep R3's block, drop the apparent duplicate brace)
yields a file exporting `NAME` without defining it → `ReferenceError` at
`require()` → **every Playwright spec fails**, not just R4's. Vitest will
not catch it. No key collisions, so the correct fix is mechanical: keep
both blocks plus `NAME`. Pre-resolve on whichever branch merges second.

**#551 P2:** mobile/tablet dashboard order regressed
(`.terminal-col{display:contents}` + `order` rules gone, so <768px stacks
in DOM order — Portfolio/Scouting jump 6-7 → 1-2, reversing a decision
main's docstring spells out); `ScoutingIntel` silently lost its collapse
toggle (ds `Panel` has no `collapsible` prop, so the prop was dropped on
migration — compounds with the ordering regression). P3: ~90 lines of
orphaned `.panel*` CSS with the **live** `.panel-tabs`/`.panel-tab` rules
buried inside the dead block (R5 purge landmine).

**#552 P2:** the `aria-sort` claim is **false for `/draft`** —
`grep -c aria-sort` = 0, nine sortable columns are bare `<th>`s with
`onClick`, so keyboard users cannot sort the board; byte-identical to main,
so the code was preserved faithfully and it is the *claim* that is wrong.
FAAB v2 contention is a **new feature, not a rebuild** — no main frontend
file references `contention`/`perOpponent`/`topRival` and R4 changes zero
Python, so ~130 lines of new bid-guidance UI shipped under "preserved
verbatim" with **zero tests** (both branches sit at exactly 1165).

### Product defects surfaced by the E2E run (NOT E2E's to fix)

Found by PR #554's first real run. Status re-verified against `main`
2026-07-26 after #558 and #559 merged — **three of five are fixed**, and
the two that remain are deliberate.

- **FIXED (#558, `1ec3311be`) — `/waivers` and `/news` absent from the
  proxy's route list.** The hand-maintained mirror had drifted three
  separate times; at the time of the fix `/waivers`, `/news`, `/draft`,
  `/angle`, `/trending`, `/players/compare`, `/league-comparison`,
  `/idptc-rookies`, `/tools/ros-data-health`, `/rankings/[position]` and
  every `/league/*` subroute were 404ing through the backend while
  serving fine from Next. Replaced with a catch-all so Next owns page
  routing, plus `tests/api/test_page_route_coverage.py` to stop the
  drift recurring. **A hand-maintained mirror of another router's route
  table is a permanent drift trap** — that is the generalizable lesson.
- **FIXED (#558) — `useAuth` resolved to *unauthenticated* with no
  retry.** Now retries on a `[1000, 2000, 4000, 8000, 30000]` ms backoff
  and only commits an unauthenticated verdict on an authoritative
  response, in both directions. Covered by
  `frontend/__tests__/components/useAuth.retry.test.jsx`.
- **FIXED (#559, `e55f791b8`) — `critical-smoke`'s anonymous `/`
  check red on `main`.** Now asserts `/Brisket/i`, which is present in
  the shell on every route and auth state, rather than pinning marketing
  copy. **The "main's nightly E2E is EXPECTED-RED" caveat is withdrawn** —
  it no longer applies, and treating a future red nightly as expected
  would now hide a real regression. Note separately that the nightly has
  in fact never executed at all (§2c instance 1); the first scheduled run
  is due 2026-07-27 06:23 UTC.
- **STILL OPEN — the page proxy serves the ANONYMOUS shell to a signed-in
  session.** `/api/auth/status` returns `authenticated: true` while the
  page renders "Sign In". Root cause is now pinned rather than
  suspected: `_proxy_next` forwards **neither the request's cookies nor
  its query string**, so a page served through the backend renders
  logged-out and ignores `?tab=`. #558 deliberately did **not** fix this
  — its comment at `server.py:10706` says so explicitly: the change
  "makes the route list complete, not the proxy faithful." Whether to
  repair the proxy or declare it non-production-representative (nginx
  bypasses it in production) is tracked as **issue #555**. E2E works
  around it by routing page navigations via `pageUrl()`.
- **STILL OPEN — `/league` SSR exceeds the proxy's 5 s timeout**
  (`urllib.request.urlopen(req, timeout=5.0)`). Same territory as the
  above and folded into the same #555 decision.

### Sixth vacuous-check instance (§2b family)

Without `E2E_TEST_MODE` + its shared secret, **every signed-in spec skips
and the run reports green while testing nothing**. The strongest form yet:
not a check that passes when it shouldn't, but an entire suite that
reports success while asserting nothing. Config now supplies it, and
`global-setup.js` verifies sessions are genuinely unlocked before any spec
runs rather than trusting the flag.

**#566 (`ca41c981c`) then audited the whole family systematically** —
findings measured rather than reasoned. A vacuity probe re-tests each
assertion against the page with `<main>` deleted (simulating content
that never rendered); a wait probe measures how long each sentinel
actually blocks. **Two specs came back NOT vacuous, which is what makes
the positives mean anything.**

Three fixed:

- `critical-smoke` asserted `url.includes("/login") || body.length > 0`.
  The right side is true of any HTML page, so the disjunction is
  unfalsifiable — and it was **the only test claiming auth-gate
  coverage.** A test named "auth-gated routes redirect to /login" could
  not detect the auth gate opening. The gate is healthy today (302 to
  `/login`), so this was a latent hole rather than a live breach.
- `journey-news` skipped on 404 after `/news` shipped, so a route
  regression would report as a skip rather than a failure.
- `journey-trade` iterated `trades.slice(0, 5)` on a possibly-empty
  array, so "returns arbitrage trades" was green when the engine
  returned none — **exactly the regression #556 fixed.** The test could
  not have caught the bug it was named for.

A coverage floor now lands in the reporter: fails below 100 passed or
above 60 skipped, against the measured ~149/29 baseline. Verified in
both directions — it fires on a 1-test run and stays silent on a full
one, **because a guard that only ever fires is as useless as one that
never does.**

Not fixed, inventoried: five chrome-matching assertions, two specs still
waiting on the retired `/trades` sentinel, a snapshot locator that
renders regardless of content, and six skip gates. Written up in
`docs/e2e-assertion-audit.md`.

### Merge ledger — 2026-07-26 (verified against `git log origin/main`)

The mid-week integration window ran early and ran long: **fifteen PRs
merged today**, all confirmed present on `main` by merge SHA. Times are
UTC. The first fourteen:

| # | Merge SHA | WS | Title | Merged |
|---|---|---|---|---|
| #553 | `a8a9595eb` | I | session audit handoff, orchestration record, lost-domain remediation | 19:29 |
| #556 | `a2099f1b6` | J | Trade Finder: stop silently dropping every IDP player | 19:36 |
| #551 | `253568bc4` | B | Redesign R3 — dashboard, news, market surfaces | 19:38 |
| #552 | `49e005b2a` | C | Redesign R4 — draft war room + trade surfaces | 20:04 |
| #560 | `998572713` | I | CI: fail loudly when a deploy would skip or reverse shipped code | 20:05 |
| #558 | `1ec3311be` | I | fix(auth): transient status timeouts no longer sign users out | 20:06 |
| #561 | `6f97763b6` | I | docs: reconcile the independent audit from #557 | 20:29 |
| #550 | `608610c9d` | E | League Intelligence LI-1..LI-8 | 20:37 |
| #559 | `e55f791b8` | G | E2E: runnable suite, abort guard, an `e2e.yml` that can start | 20:38 |
| #564 | `a5a8b8676` | J | Continuous Improvement: model registry, held-out validation | 21:15 |
| #565 | `7cdc4070f` | E | LI-8 League Twin: trade-impact bridge | 21:15 |
| #562 | `4f9cb05b6` | J | WS-J Roster Intelligence Engine | 21:16 |
| #566 | `ca41c981c` | G | test(e2e): audit the "looks correct, checks nothing" family | 21:40 |
| #563 | `783721534` | J | WS-J Trade layer: target engines, partner fit, package generator | 21:48 |

**Closed without merging** (verified via the PR API, `merged: false`):

| # | Disposition |
|---|---|
| #554 | Closed 20:38:50 UTC — **contained in #559 in full.** Verified: `12cf9dceb` (#554's head) is an ancestor of the #559 branch head, so this is genuine containment, not an abandonment |
| #557 | Closed 20:09:34 UTC — **superseded by #561** (`6f97763b6`), which reconciles its audit findings into the session handoff |

**#567 merged at 22:06 UTC as `ec60cdb0e`** — fifteen for the day. It
measures the trade-engine value divergence (F-6 input, no fix) and
refutes its own prior §16.7 hypothesis about the corridor clamp. It
merged *while this dashboard rebuild was in flight*, which is itself the
§2a lesson landing for a third time today: this branch was rebased onto
`origin/main` and `git diff --stat origin/main HEAD` re-run to confirm
it still carried only its own file.

Its measured result is worth carrying into §6.2's eventual fix: the
board runs ~12% below the composite (k = 0.880 across 803 assets), so
migrating F-6 onto `rankDerivedValue` is **a recalibration, not a
swap** — `MIN_ASSET_VALUE`, `JUNK_THRESHOLD`, `ELITE_THRESHOLD` and
`MAX_BOARD_LOSS` all sit on a scale ~14% hot relative to the values they
would receive. And **194 assets clear `MIN_ASSET_VALUE` but have no
`canonicalConsensusRank` at all** — migrating naively deletes 162
players from the finder's universe. That must be a decision, not a
discovery.

**No PRs currently open.**

**In progress, no PR:**

| Branch | Head | Scope |
|---|---|---|
| `claude/ws-j-refit-gate` | `e1b97edfc` (21:42) | Refit rewiring — see §6.1 |
| `claude/redesign-r5-polish` | `bd0e3c9a0` (21:37) | WS-D R5 phases A+B — see §1 |

The `SEL`/`NAME` cross-PR merge hazard that dominated the earlier
queue is **discharged** — R3, R4 and the E2E branch all merged without
recurrence, and the `journey-trade.spec.js` import conflict resolved as
the predicted union of `SEL` + `pageUrl`.

**Timing note for future ticks:** `Validate PR` runs ~16 min on this repo
(four independent samples today). A run in progress for less than that is
normal, not hung — one agent misread a 2-minute-old run as 40 minutes and
nearly reported a stalled job.

### WS-J dispatch (2026-07-26 18:30) — all six agents active

| Agent | Assignment | Branch |
|---|---|---|
| league-intel | **Cross-market normalization** — gating | claude/league-intel-foundation |
| FAAB/trade | Roster Intelligence Engine | claude/ws-j-roster-intel |
| news/TEP | Partner fit + acceptance model | claude/ws-j-partner-fit |
| reviewer | Adversarial audit of the three trade engines | read-only |
| E2E | `useAuth` fix + proxy route list (#555) | claude/auth-proxy-fixes |
| design custodian | R5 purge plan + WS-J dashboard spec | claude/redesign-r5-polish |

**F-1 gates the package generator — still open, now tracked as §6.2.**
ADR-010 is accepted and the interface is built, but
`angle.py::_make_candidate` remains unrewired on both the offer and
acquire sides. See §6.2 for the verified line references and the
measured KTC↔IDPTC scale relation.

**The "unverified suspicion" is now confirmed and fixed.** It was handed
to the reviewer rather than asserted: that the top-150 quality filter
both trade engines enforce might exclude IDP entirely, making them
offense-only in practice. It did, for `finder.py` — KTC publishes no IDP
players, so every defender scored `ktc_value = None` and was dropped
before scoring, and in an IDP league the engine silently returned
offense-only results. Fixed in **#556** (`a2099f1b6`) with a per-market
gate: `MARKET_TOP_N_FILTER` ranks each asset within its own market
population, `marketCoverage` is emitted per market, and the engine warns
explicitly when an IDP league has no priced IDP assets. `suggestions.py`
was never actually consulting KTC despite the naming — its gate is the
blended board, renamed `BOARD_TOP_N_FILTER` / `_assign_board_ranks`,
with the `ktc*` names retained as deprecated aliases.

Recording the shape, because it is worth more than the fix: the
suspicion was filed as a suspicion, not an assertion, and it turned out
to be true. That is the correct handling of an unverified hypothesis and
it cost nothing to be wrong about.

### Ops incident closed (2026-07-26)

`riskittogetthebrisket.org` lapsed and now resolves to a third party.
Site rehomed to the bare IP over HTTP and healthy throughout — it was
never down. Three workflows had a hardcoded fallback to the lost domain;
`intel-refresh.yml` sent a bearer token there on every scheduled run.
Fallbacks removed, all three now fail loudly on an unset
`PROD_PUBLIC_URL`.

**#545 was two stacked bugs**, the first masking the second: wrong target,
*and* `INTEL_REFRESH_TOKEN` never present in the service environment at
all — which predates the domain loss and would have 401'd regardless.
Both fixed; crawl green in 2m10s.

Operator SSH access was also lost (VPS rebuilt 2026-07-20, no keys
carried over, provider key store is provisioning-only). Restored via a
one-shot dispatch-only workflow using the existing deploy credentials.
~~That workflow must be deleted~~ — **done, verified**:
`.github/workflows/grant-ssh-access.yml` was removed in `c534280db` and
is absent from `main`. It was a standing path to production shell for
anyone who could dispatch it.

Still outstanding for the operator: no TLS on the bare IP (login
credentials cross the network in plaintext until a new domain + certbot).

## 7. Risks

**Refreshed 2026-07-26 22:00 UTC.**

- **The weekly Hill-curve refit ships production constants nothing
  checks** (§6.1). Highest-severity open risk: it writes to `main` and
  triggers a deploy autonomously. Mitigation exists on a branch, unmerged.
- **`src/roster_intel/` is merged but unreachable** (§6.3). The risk is
  not technical but reporting: "the engine is merged" has already been
  read as "the feature exists."
- **`angle.py` prices mixed-market packages by adding KTC to IDPTC**
  (§6.2). Bounded by the measured ~1.000 scale relation, but wrong and
  unaudited.
- **The nightly E2E has never executed** (§2c instance 1). First
  scheduled run 2026-07-27 06:23 UTC. Until it produces one result, the
  suite's CI behaviour is unproven regardless of local green runs.
- **The page proxy renders signed-in sessions logged out** — issue #555,
  unresolved decision (repair vs. declare non-representative).
- **No TLS on the bare IP** — login credentials cross the network in
  plaintext until a new domain + certbot. Operator action.
- Credit outages (mitigated: liveness tick auto-resumes agents); LI
  golden validation may hit Sleeper stats-API gaps (fallback documented
  in LI-2 instructions).
- ~~Intel cron stays red until user runs the journalctl step (issue
  #545).~~ **Resolved** — crawl green in 2m10s; see the ops incident
  record in §6.4.
