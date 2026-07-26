# Autonomous Engineering Org — Canonical Execution Plan

Maintained by the main orchestrator session. This file IS the unified plan,
ownership model, git/integration policy, and dashboard. Update on every
material change. Supersedes ad-hoc per-track instructions.

Target: **comprehensively functional, integrated, polished product in ~1
week** (by ~2026-08-02). Optimize for the final integrated system, not
constant main-branch stability.

## 1. Workstreams & ownership (one owner each)

| WS | Workstream | Owner (agent) | Branch | Scope (exclusive) | Status |
|---|---|---|---|---|---|
| A | Redesign R2 — rankings + profiles | design custodian | claude/redesign-r2-rankings | frontend/app/rankings/, PlayerPopup, ds/ additions | **MERGED** `9ccdecea` |
| B | Redesign R3 — dashboard, news, market surfaces | design custodian (builder reassigned) | claude/redesign-r3-surfaces | frontend/app/{page,news,edge,finder}/ | PR #551 — **both P2 fixed** (`a7f2f0d1`, `4cccfd84`); 56 files / 1178 tests green, 13 budgets pass |
| C | Redesign R4 — draft war room + trade surfaces | design custodian (builder reassigned) | claude/redesign-r4-warroom | frontend/app/{draft,trade,trades,angle,waivers}/ | PR #552 — code fixed (`203849d9`), **PR body corrected**: aria-sort claim scoped and now true, FAAB v2 contention stated as a NEW feature, counts re-measured at `1563e527` |
| D | Redesign R5 — perf/a11y/mobile sweep + dead-CSS purge | design custodian | claude/redesign-r5-polish | global CSS, cross-page | Blocked by B+C |
| E | League Intelligence LI-1..LI-8 | league-intel agent | claude/league-intel-foundation (continuous) | src/league_intel/, config/league_intel/, tests/league_intel/, coordinated: registry.json, src/ros/lineup.py | PR #550 open, blockers **cleared** (`4e3e0d95`); LI-7 non-TE axes done (`2617e09e`) — 385 tests green, end-to-end no-op proven with `==` on 500+ real rows. **TE axis still blocked on paired-board evidence** (correctly — it is the one number not yet defensible) |
| F | LI-9 UI (valuation-mode toggle) | design custodian | (into R5 or own) | R1 shell TopBar + getActiveValue adoption | Blocked by E(LI-4)+A |
| G | E2E safety net upkeep | e2e agent | claude/e2e-r1-reconcile | tests/e2e/ | In progress — **suite has never had a verified end-to-end pass**; top board risk |
| H | Identity sweep close-out | identity agent | claude/identity-sweep | identity joins (re-scoped post-merges) | #547 merged; residual aggregate-join defect handed to WS-H by PR #550 (6 duplicate rows, 40/666 join failures) |
| I | Ops: refresh/deploy/intel cron, VPS | orchestrator | main (dispatch only) | workflows, monitoring | Steady; intel 401 user-blocked (issue #545) |
| R | Fresh-eyes review | reviewer agent | read-only | PR comments | Running on #551 + #552 |

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

## 5. One-week backward plan

- **Now–Sun**: R2 lands; R3+R4 launch in parallel; LI-1/2 PR + review;
  LI agent continues LI-3+4+5 on the same branch (one batched PR).
- **Mon–Tue**: mid-week integration window #1 (R3, R4, LI batch, E2E).
  LI-6/7 build; F (toggle) starts once LI-4 + R-pages merged.
- **Wed–Thu**: LI-7 guardrailed values live behind toggle (default
  consensus); R5 sweep; LI-8 sim extension; golden backtests.
- **Fri–Sat**: final integration window — full-suite + E2E + visual pass,
  perf, docs, release checklist, deploy, VPS apply notes for user.

## 6. Open merge blockers

**PR #550 (WS-E) — RESOLVED 2026-07-26 (`4e3e0d95`).** All three blockers
cleared: PR body headline corrected (old `TE 0` / "overstated 46%" lines
explicitly retracted rather than quietly deleted), `replacement.py`
docstring corrected with a KNOWN LIMITATION section plus a warning at
`measure_endogenous_starters` itself, and the ADR restructured so the
endpoint asymmetry leads. Retained below as the record of what was wrong
and why.

**Orchestrator decision — the `src/ros/lineup.py` fix is NOT being pulled
forward** ahead of the Jul 29 window, despite the load-bearing numbers
being unverifiable on main until #550 merges. Rationale: the production
impact is bounded — composite team-strength values move but **rank order
is unchanged across all 12 teams**, so Pick Projector output is stable
today — and splitting a coordinated-territory file out of a batched branch
risks more than three days of earlier verifiability buys. Anyone needing to
cross-check the flex/TE figures before the window should check out
`claude/league-intel-foundation` rather than expect main to reproduce them.
Revisit if a second workstream is actually blocked on verification.

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
`players_points` treated as 0; the exact optimizer + `fantasy_positions`
fix is **branch-only, so none of this is reproducible on main today**.

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

## 7. Risks

Risks: credit outages (mitigated: liveness tick auto-resumes agents);
LI golden validation may hit Sleeper stats-API gaps (fallback documented
in LI-2 instructions); intel cron stays red until user runs the
journalctl step (issue #545) — not on the critical path.
