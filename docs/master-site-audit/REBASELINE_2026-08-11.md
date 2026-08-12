# Re-baseline at HEAD — 2026-08-11

`NEXT_STEPS.md` was written at the close of PR #722 and is still the live directive for
*what to repair next*. This file records what changed about the **measurements** underneath
it, because the registry was generated at a commit that no longer sits on `main` and several
of its verdicts no longer describe HEAD.

Measured on `claude/dynasty-audit-consolidation-e75vdy` at `4ac9b22` (== `origin/main`).

## Test baseline — the wave-D verification debt is PAID

`NEXT_STEPS.md` opened with "run the full suite; this is the one thing I would not skip",
because repair wave D shipped without one. Both suites are now measured on a quiescent tree:

| suite | result | previous figure |
|---|---|---|
| `pytest tests/ -q` | **7,001 passed / 0 failed** / 25 skipped / 633 subtests, 583s | 6,553 passed (post wave C) |
| `vitest run` (frontend) | **119 files / 2,003 tests passed / 0 failed** | 1,866–1,870 |

Toolchain: python 3.11.15 in `.venv` via `scripts/setup.sh` (CI-parity preflight green),
node 22.22.2, vitest 4.1.10. No failures anywhere, so wave D's ten unvalidated commits are
retroactively clean. The later figures in this file (120 files / 2,004) include this
session's own additions.

## The clone was shallow, and it mattered

A fresh checkout arrives with 50 commits (boundary `764ebbb`). Every audit SHA — including
`8b88623f`, which generated `findings.json` — was unresolvable, which reads exactly like the
squash having destroyed them. After `git fetch --unshallow` (4,878 commits):

- all 85 claiming commits resolve again;
- `origin/claude/fantasy-football-master-audit-umvex5` survives on the remote and contains
  every one of them, `8b88623f` included;
- `8b88623f` is confirmed **not** an ancestor of `main` — the squash is real, and
  `origin/main..HEAD` genuinely carries no trailers.

So the claim signal was never recoverable from `main`, and the fix is
`claims-frozen-2026-08-05.json` + the amended `verify_closure.py` (see that commit). Anyone
re-running audit tooling on a fresh clone must unshallow first or every git-derived signal
lies.

## W31-F001 — REFUTED AS PRESCRIBED, re-scoped

`NEXT_STEPS.md` flagged this as "one open defect worth fixing early" with the repair given as
`git rm --cached` on `data/sleeper_last_good.json` and `data/scrape_state/`. **Do not do
that.** The tracking is deliberate and load-bearing:

- `.github/workflows/scheduled-refresh.yml:489` force-adds `data/scrape_state/` every 2h in a
  step that runs even when the scrape fails, precisely so per-fetcher freshness stamps survive
  partial failures;
- `:562` syncs `data/sleeper_last_good.json` in the data-refresh commit loop;
- `:605` dispatches the deploy on `automated data refresh|freshness stamps`, so untracking
  these files freezes production's `source_health` on the previous deploy's timestamps — the
  "44h-stale-everywhere" outage the hardening was written for.

An untrack would also be undone within 2h by the next `git add -f`.

The *observation* stands — a deployed checkout goes dirty within minutes of boot and
`git pull --ff-only` fails there. The root cause is that the **prod backend** writes to paths
CI owns. The real repair is to reroute the running server's runtime writes to an untracked
location (or teach the deploy to reset those paths), which is M-sized and touches `server.py`
— currently claimed by the live `claude/bridge-timeout-root-cause` session, so it is deferred
rather than attempted.

## Registry corrections found this session

Verified at HEAD by reading the code, not by trusting a status field:

| finding | registry says | HEAD says |
|---|---|---|
| W08-F004 | claimed closed by `00a3ce2c` | **was still live** — all four `/^2026\b/` sites present. `00a3ce2c` is on the audit branch whose code half never reached `main` (PR #745 lifted only the docs). Now genuinely fixed and re-claimed. |
| W11-F006 | open | **live and confirmed**, now fixed. |
| W10-F003 | "Missing: there is no perfect-draft optimizer" | `src/draft/` + `frontend/lib/perfect-draft.js` contain a full budget-knapsack optimizer with displacement and cut ladders; `CLAUDE.md` documents it at length. Needs re-verification against the spec's requirements, not a from-scratch build. |
| W26-F004 | open-unsafe-to-rerun | mechanism (nflverse actuals fetched then discarded) is fixed at HEAD by the snapshot guard in `src/api/bdvm_api.py:178-182`. |
| W31-F001 | open, fix = `git rm --cached` | prescribed fix refuted (above). |

The general lesson, and the reason the spec insists on it: **the registry is stale in both
directions.** `00a3ce2c`'s claims are the sharpest case — a commit whose code half was
abandoned still marks findings closed. Verify per finding at HEAD before scheduling any repair.

## New defect found this session — /trade was broken for 3+ teams

Not in `findings.json`, because it postdates the audit's reconnaissance: the owner hit it in
production during this engagement. Full write-up in
`evidence/W08/TRADE_MULTI_TEAM_CRASH.md`; the short version:

`frontend/app/trade/page.jsx` called `defaultDestination` at nine sites without importing it.
`49e005b2a` (2026-07-26, "Redesign R4", #552) deleted the import together with the one call site
it had just removed, and missed the other nine. Because an un-imported free variable compiles to
a global lookup rather than a link error, `/trade` loaded fine and two-team trades worked
perfectly — the `ReferenceError` fired only on the 3+-team paths, so the whole multi-team
feature had been dead for two and a half weeks under green CI.

Two things this says about the test estate, beyond the one-line fix:

- **No E2E spec exercises a multi-team trade.** `journey-trade.spec.js` and the mobile specs are
  two-team only. That gap is precisely what let a fully broken feature ship.
- **A production build proves nothing about free variables.** `npm run build` was green before
  and after; a bundler cannot tell a forgotten import from an intended global.

Reproduced RED and verified GREEN in Chromium at the mobile viewport against the real production
build (`evidence/W08/trade_multiteam_browser_check.mjs`). WebKit — the owner's actual browser —
is not installable in this container, so that exact path stays labelled unverified rather than
claimed.

## W30-F023 (new) — the p=1.0 clamp collapses 289 distinct IDP ranks

**OPEN. Measured, not repaired.** Recorded here rather than in
`findings.json`, which was generated at `8b88623f` and is not regenerated by
this engagement.

`rank_to_percentile` saturates `p` at 1.0, so every rank past
`PERCENTILE_REFERENCE_N` (500) receives an identical percentile and an
identical value from that source — while `OVERALL_RANK_LIMIT` publishes to
800. On the live contract's `sourceRanks`, 877 of 7,130 served observations
(12.3%) sit on the clamp, touching 487 of 1,095 board rows.

It is an IDP pathology, not a board-wide one:

| source | clamped/obs | distinct ranks collapsed onto one value |
|---|---|---|
| `idpTradeCalc` | 399/899 (44.4%) | **289** |
| `draftSharksIdp` | 203/318 (63.8%) | 203 |
| `idpShow` | 202/347 (58.2%) | 202 |
| `draftSharks` | 26/411 (6.3%) | 26 |
| every other source | 0 | — |

Independent of any challenger — it is live under the champion today. Full
analysis, including the proof that continuous extrapolation and a
transformed deeper N are the same thing through the served range, is in
`evidence/W30/B1_2_COORDINATE_TAIL_GOVERNANCE_EVIDENCE.md` §2–§3.

**Not marked closed by that analysis.** No production code changed. Two
facts a repair will need: the clamp is enforced in *two* places
(`rank_to_percentile` and again inside `percentile_to_value` at line 484),
and board impact is non-monotone in per-source value because the post-blend
IDP stages are relative — a row can rise when its clamped peers fall.

### B4 outcome (2026-08-11) — BLOCKED BY A CANONICAL DEPENDENCY

Everything above this heading is B1.2's record on **B1.2's pin** and is left
standing as written. The numbers below are B4's, on **B4's pin**
(`dynasty_data_2026-08-11.json` sha256 `8fb6ede274171aee…`); the two are
different experiments and are not interchangeable. Full decision:
`evidence/W30/B4_TAIL_DECISION.md`.

**Two corrections to the population, both narrowing it.**

*Withdrawn — B4's own first measurement.* B4 initially reported **703 of
6,322 observations (11.1%) touching 348 of 1,092 rows**, counting any
stamped `effectiveRank > 500` as saturated. That is wrong: value-direct
sources price from the raw site value and never reach `percentile_to_value`.
Withdrawn explicitly, and the specific claim withdrawn with it — *"208
distinct `idpTradeCalc` opinions priced as one number"* — is false, because
none of `idpTradeCalc`'s live contributions take the rank-Hill path at all.
The B1.2 table above has the same shape (it attributes 289 collapsed ranks
to `idpTradeCalc`), and it stays as B1.2's record; B4's path-gated figure is
the one a repair should be measured against.

*Path-gated figure.* **421 of 5,146 rank-Hill observations past rank 500
(8.18%), touching 254 of 1,092 board rows.** `idpTradeCalc` contributes
**zero** — 779 stamped ranks, all value-direct. Its deep ranks remain real
as the shared-market translation backbone, which is a translation role, not
a flattened contribution.

*Served-row distinction (added 2026-08-11).* All **254 of 254** touched rows
are served. `254 / 1,092` mixes published rows with 352 the board never
serves and understates the user-visible rate; against the 740 served rows it
is **34.3%**, and per position DB 79.8%, DL/EDGE 75.2%, LB 53.8%.

**Two facts the entry above got right, and two it did not have.** The clamp
count is **four**, not two — `rank_to_percentile`, `percentile_to_value`,
the holdout scorer's standalone `hill()` and the fit's `_hill`. And the
deepest rank-Hill rank consumed by a *served* row is **877**, past
`OVERALL_RANK_LIMIT`, so the board limit is not a defensible saturation
point for the source-coordinate domain.

**Selected policy: bounded at rank 903**, the deepest rank any source
publishes (corroborated at `src/api/source_history.py:352-353`). Continuous
extrapolation is observationally identical on this board — max |delta| 0
over ranks 1..877 — and is refused only on "missing is never zero": it
resolves rank 50,000 to 72 with no evidence behind it.

**Not applied.** Setting the boundary makes the B3 corridor clamp four rows
carrying five or more sources and three rows in the top third of the IDP
board — both of which B3's own repair criteria forbid — and flips three
clamps to direction `up`. The mechanism is **W02-F015/#794** (all 27 clamps
anchor on `idpTradeCalc`, itself one of the row's voters) and
**W02-F016/#795** (the band is the board's own P90 drift, so removing the
saturation inflation narrows it 0.63 → 0.46 and tightens the corridor onto
rows it never targeted). W30-F023 is therefore **not separable** from those
two residuals on this board, and B4 may not reopen B3.

**What did land, behaviour-preserving:** the four clamps now defer to one
owner (`src/canonical/tail_policy.py`) — a W30-F008-class repair, verified
identical on all 1,092 rows — and `valueContributionPath` is recorded from
the branch taken instead of re-derived. The W30-F023 assertions ship as
`xfail(strict=True)`, so setting the boundary turns them into errors and
forces a deliberate re-decision.

---

### VERIFIED FIXED 2026-08-12 — boundary **904**, not 903

Everything above is the *blocked* state and is preserved as written. Two
things changed it, and the second was not expected.

**The blocker is gone.** #799 (merge `52d48b6e5`) removed the market
corridor outright, resolving W02-F015/#794, W02-F016/#795 and
W02-F017/#796. There is no corridor for a tail change to disturb.

**903 was wrong, and it was never measured.** Every occurrence of 903 in
the tree was prose — a comment at `src/api/source_history.py:353` and a
docstring sentence in `test_source_history_rank_encodings.py`, whose own
guard uses 2,000. Nothing computed it. Replaying the 17 compatible
historical days with current code gives deepest-observed-rank per day of
784, 785, 898×5, 899, 900×5, 901×2, 903, **904** — the maximum from
`idpTradeCalc` on 2026-07-28. **903 would have re-saturated a rank the
evidence has actually seen** (headroom −1). The quantity moves with source
coverage, so a single board could never have decided it, which is how the
original number went unchallenged.

The boundary covers value-direct ranks deliberately: the value-direct
fallback is live code (suppressed source, out-of-range value, or missing
value routes a row to the curve), so stopping at the deepest rank-Hill
rank (882) would re-saturate the band above it the moment that branch
takes traffic. Same reasoning the prior round used to reject 877 — sound
reasoning, wrong number.

Fresh reproduction on board `dynasty_data_2026-08-12.json`: **421 of 5,143
rank-Hill observations past 500, touching 254 rows, all 254 served —
34.32% of the served board** (DL/EDGE 97, DB 87, LB 49). Remeasured, not
carried over.

Repair: `tail_policy.TAIL_SATURATION_RANK = 904`. Head preserved exactly
(max deviation **0** at every rank 1–500 on all three routed masters);
ranks 501–904 go from 1 distinct value to 395/327/271. Board impact: 245
values changed, median 64 / max 196, **top 50/100/200 membership
unchanged**, served cut 740 → 740. All 245 movers attributed — 215 direct,
30 via a *demonstrated* rookie→merged-pool→pick-tether chain (36 rookies
down, 30 picks down, every one of them 2026, the tethered year), **0
unexplained**. Blend-integrity detector silent under both policies and on
all 17 historical days.

The `xfail(strict=True)` markers came off deliberately, which is what they
were there to force. Four tests elsewhere that pinned the saturated
behaviour as correct were re-decided with reasoning recorded in each.

Known residual, named: because the boundary is the observed maximum, a
board on which a source reaches 905 will saturate there. Far smaller than
W30-F023 and the honest alternative to inventing a margin.

Full evidence: `evidence/W30/B4F_TAIL_FINAL.md`. Superseded blocked
experiment preserved unchanged at `evidence/W30/B4_TAIL_DECISION.md`.

## W30-F024 (new) — the model registry could overwrite its own history

**FIXED this session.** `load_or_seed_registry` treated any `RegistryError`
from `load()` as "no registry exists" and responded by seeding a fresh v1
champion and saving over the file. `load()` raises that error for a missing
file *and* for any structural failure of an existing one, so a registry that
merely failed validation was replaced by a one-version seed — destroying
every recorded promotion, rejection and rollback.

Observed live: an experimental guard made `load()` raise, and inside one
test run `config/model_registry/hill_scope_masters.json` went
`championVersion` 2 → 1 and versions `[1,2,3]` → `[1]`. Restored from git.

Third instance of `ARCHITECTURE_HANDOFF` invariant 6 — "tools must not
destroy the evidence they maintain" — whose own note said to assume a third
existed. Pinned by `tests/model_registry/test_registry_self_destruction.py`.

## W02-F001 — IDP-only sources scored on the wrong scope master

**FIXED in B2.** Reproduced on a fresh pinned baseline before anything
changed (code `a5ff76b09`, board `dynasty_data_2026-08-11.json`
sha256₁₆ `a495c049fa69f141`, 1,092 rows, 24 source CSVs hashed), then
repaired root-cause-first and remeasured.

The root cause is not "IDP sources are routed wrongly". It is that
`_curve_for_source` picked the master from the source's **registry
declaration**, which describes the source's native coordinates and says
nothing about the crosswalks the pipeline runs before the curve sees the
rank. Two independent paths reach the wrong master:

* the three `needs_shared_market_translation` sources (`dlfIdp`,
  `idpShow`, `fantasyProsIdp`), lifted onto the backbone's combined
  offense+IDP ladder in Phase 1;
* `dlfRookieIdp`, whose within-class rookie rank Phase 1d translates
  through `idpTradeCalc`'s ranks — also shared-market — with none of the
  three flags involved.

`src/canonical/rank_coordinates.py` is now the single owner: a rank
belongs to the pool of the ladder it was translated through, each pass
stamps `rankCoordinatePool`, and the curve follows the pool. No source
name appears in the routing. Hill constants unchanged; champion still
registry v2.

The registry's recorded "~48% of the anchor" was a flat number for a
strongly rank-dependent gap (IDP÷GLOBAL 1.00 at rank 1, 0.87 at 50, 0.69
at 100, 0.35 at 500). Measured effect of the repair on the pinned board:
per-source contributions +111% to +186% median on 578 rows; 247 of 786
comparable served values changed, median |6.0%|, p90 15.6%; the top-100
offense/IDP/pick balance is **unchanged** at 85/9/6; and **26 IDP rows
re-entered the served top-800 window** (Devon Witherspoon, Malaki Starks,
Leonard Williams, Josh Sweat, Mason Graham …) displacing 26 deep-tail
offense/pick rows — the priced-row count is identical on both sides, so
totals alone would have rendered that as "no change".

`REPAIR_ROADMAP.md:1492`'s instruction never to ship the GLOBAL re-route
alone rests on a verifier statistic of `0.92 / 0.92 / 1.29 / 1.32`
per-source medians against the anchor, "wider than the control band".
**Not reproduced on this baseline**: the four post-repair medians are
0.949 / 0.940 / 0.931 / 0.893, spanning 0.056 inside an offense control
band spanning 0.292. Three of the four have n ≤ 5, and the earlier
verifier measured a different board, so this is recorded as "not
reproduced here" rather than "was wrong". The roadmap's second ground —
the IDP master's 1.552× fit-scale claim — is **untested in B2** and now
prices zero rows on the default board (every live IDP rank is
shared-market after the repair), but stays live on backbone-disabled
override boards. Open.

Full evidence: `evidence/W02/B2_CURVE_ROUTING_EVIDENCE.md`. Pinned by
`tests/api/test_curve_routing_coordinate_pool.py` (15 tests; 6 RED → all
green).

### W02-F001b (new) — `sharedMarketTranslated` recorded intent, not outcome

**FIXED in B2, same commit.** The field was stamped
`needs_shared_market and scope == overall_idp` — the registry's promise.
When the backbone is absent `translate_position_rank` returns the raw
rank with `method == "fallback"` and the field still read `True`. A
provenance field that lies exactly when provenance matters, and the field
any coordinate-aware routing would naturally key on. Now stamped from the
translation outcome.

## W02-F002 — Hampel ejects the IDP market anchor

**RESOLVED AS A CONSEQUENCE OF W02-F001, in magnitude.** Remeasured on
the post-B2 board rather than fixed independently, as the finding's own
`dependencies` field requires.

| | ejected / eligible | rate | HIGH |
|---|---|---|---|
| baseline | 50 / 164 | 30.5% | 50/50 |
| post-B2 | 4 / 190 | **2.1%** | 4/4 |

The baseline reproduces the registry's 29.4% / 52-of-52. The mechanism
was F001's: three mispriced votes dragged the per-player median far
enough that the correctly-priced anchor read as the outlier. The
finding's `expected` is "a low single-digit percentage, with drops in
both directions" — 2.1% meets the magnitude half.

**PARTIALLY REMAINS, in direction**: the four survivors are still all
HIGH. At n = 4 that is not evidence of a mechanism, so it justifies no
Hampel change; recorded so a later phase can test it across boards.

## W02-F003 — the IDP market corridor clamp

Two stages, recorded in order. **B2 remeasured it and did not fix it**; **B3 repaired it.** Read both — the B2 numbers are attached to the B2 pin and were not recomputed on B3's board.

### B2 — STILL REPRODUCES, and the rate rose. Remeasured, not fixed.

| | clamped | of ranked IDP rows | capped by max band | on the band edge | up / down |
|---|---|---|---|---|---|
| baseline | 131 | 43.2% of 303 | 131/131 (100%) | 131/131 (100%) | 57 / 74 |
| post-B2 | 183 | **55.6%** of 329 | 183/183 (100%) | 183/183 (100%) | **23 / 160** |

Both recorded symptoms are intact: the per-bucket P90 machinery is inert
(every clamp is capped by the 0.15 hard band, and 0.15 is the only
`bandPct` observed), and every clamped row lands exactly on
`anchor × (1 ± 0.15)`.

Two new facts. The rate **rose** — F001 was masking part of the binding,
not causing it. And the direction **flipped**: the corrected blend now
sits above the anchor far more often than below, so the corridor is
mostly acting as a *ceiling* on IDP value. That is the opposite of the
"containing the IDP calibration runaway" rationale its own comments still
give — a rationale CLAUDE.md already records as stale, since the
calibration post-pass it names was removed. Strongest B3 candidate.

### B3 — REPAIRED.

Reproduced first on a fresh pin (code `2449af9ac`,
board `dynasty_data_2026-08-11.json` sha256₁₆ `8fb6ede274171aee`, a
DIFFERENT board from B2's — the B2 numbers stay attached to the B2 pin).
The finding reproduced identically: 183/329 ranked IDP rows clamped
(55.6%), 100% capped by the hard band, 100% on the band edge, only
`bandPct` 0.15, 23 up / 160 down.

Root cause: a hard constant overrode the board-derived per-bucket P90
band. Empirical bands were 0.5183–0.6504 against a 0.15 cap in every
bucket, all above the minimum-sample threshold, so the derived number was
computed and discarded 183 times out of 183 — and 55.6% of the ranked IDP
board was served at exactly `idpTradeCalc × 0.85` or `× 1.15`.

The cap's stated purpose predeceased it. The corridor was built
2026-04-21 (#198) to contain the IDP calibration post-pass; that pass was
retired 2026-04-23 (#251), two days later. The cap arrived 2026-05-02
(#375/#376), nine days after that. The hazard it names is now covered
without an anchor by the single-source haircut (#496).

Mandatory anchor-lineage check: all four IDP anchor-chain members are
voting sources in the blend the corridor clamps, the fallback never
fires, and `idpTradeCalc` was the anchor on **183/183** clamped rows while
also voting on **183/183**. Its contribution is 0.721× the median of the
other sources on those rows, which is why 160 of 183 clamps pulled values
down.

Repair: remove the IDP entry from
`_MARKET_CORRIDOR_MAX_BAND_BY_ASSET_CLASS`, not retune it — criterion 6
was low sensitivity to arbitrary constants, and 0.15 decided every clamp.
Measured against candidates B/C/D/E on the same pin: the same code then
clamps 32 rows (9.7%), all in the board tail, none with five or more
sources, flat across confidence buckets (8.3/10.0/9.8% vs the capped
63.9/45.8/60.7% — which was **inverted**, overriding the board's
best-supported rows at the highest rate). Board composition barely moves:
top-100 IDP 9 either way, top-200 43 → 41, top-400 130 either way.

Not claimed: the empirical machinery was never dead (a tighter synthetic
board reaches it, pinned by test), and the corridor is not removed —
candidate E was measured alongside and the tail rail is what the corridor
was designed for. Residual recorded: the band is derived from the drift
it bounds, so a board that drifted as a whole would widen its own band.

Full evidence: `evidence/W02/B3_MARKET_CORRIDOR_EVIDENCE.md`. Pinned by
`tests/api/test_market_corridor_characterization.py` (15) plus the
rewritten cap tests in `tests/api/test_market_corridor_clamp.py` (31).

Still open after B3, and now tracked with their own identities rather
than as prose inside a closed finding: **W02-F015 / #794** (the anchor is
still a voter on the remaining 9.7%), **W02-F016 / #795** (the band is
derived from the drift it bounds), **W02-F017 / #796** (confidence-bucket
correctness is now a live dependency). W30-F023 is tracked as **#797**. Also still open and unchanged by B3: C17's OFFENSE half,
the IDP master's 1.552× fit-scale claim, and W30-F023.

## W02-F018 (new) — the export bundle is incomplete, but git history is not

**CORRECTED 2026-08-11, and the correction reverses the conclusion.**
Verdict: **A. HISTORICAL GIT REPLAY AVAILABLE** — no collection wait is
required.

The original entry read "the export bundle does not retain the inputs
needed to audit board-over-board behaviour" and concluded that ~2 weeks of
new boards had to be collected. The first clause is true. **The conclusion
does not follow from it and is withdrawn**: the export bundle is one
retention mechanism, and git history is another. All 24 per-source CSVs
are committed at every automated refresh.

The archive-ZIP finding stands as originally measured: `exports/archive/*.zip`
carries 2 of the 21 voting sources' CSVs, so rebuilding an archived board
reproduces ~90% of today's inputs under a historical filename. Any
cross-board claim derived that way is unsound, and the one this pass
derived was withdrawn.

**What the correction found**, via `evidence/W02/cd_historical_replay.py`:

| | |
|---|---|
| refresh commits scanned | 1,099 over 140 distinct days |
| **usable days** (all 22 required inputs present) | **17** — 2026-07-26 → 2026-08-11 |
| partial days | 123 — 2026-03-25 → 2026-07-25 |
| unusable days | 0 |

Partial days are missing sources that **did not yet exist**, not sources
that were lost: `fantasyNavigatorSf` and `pfkDynasty` are absent on 123
days, `otcffbSf` on 51, `fantasyCalc` on 49. Those days are replayable
only against a smaller source set, which is a different pipeline
population and not directly comparable.

**A near-repeat of the same error, recorded because it is the more useful
lesson.** The first matrix returned 14 refresh commits over 2 days, which
would have supported the original conclusion. That was an artifact of a
**shallow clone** (145 commits, oldest 2026-08-10) — the exact trap this
document already warns about under "The clone was shallow, and it
mattered". After `git fetch --unshallow`, the same query returns 1,099
commits over 140 days. Both errors have one shape: concluding *absence*
from an incomplete view without checking whether the view was complete.

**Temporal independence is measured, not assumed**: 7-15 of 22 sources
change between consecutive usable days, and **zero** transitions are
byte-identical. Replayed board row counts move 973-1095 and IDP
populations 276-359 — variation the contaminated archive test could not
produce.

Three inputs the replay had to neutralise, found by *instrumenting* a real
build rather than reading the source, and each of which would have
silently contaminated a historical run:

* every build **reads and writes** `data/snapshots/ranks_last.json`;
* every build makes a **live network call** to `api.sleeper.app`, which
  derives `tep_multiplier` from the league's `bonus_rec_te` and therefore
  **affects values** — unpinned, every historical replay would have used
  *today's* league scoring;
* 22 market-data CSVs are read, not 21 and not 24 (`draftSharksRos*` are
  never read on this path).

Remaining limitation, stated rather than hidden: 17 days is one market
regime (late-July to mid-August, no live NFL games). That bounds
generalisation; it does not bound availability, which is what this finding
was about.

Evidence: `evidence/W02/CD_CORRIDOR_DECISION.md` §6,
`evidence/W02/cd_input_manifest.py`, `cd_historical_replay.py`,
`cd_historical_metrics.py` + reports.

## W02-F018 — original entry, superseded by the correction above

**OPEN. Found by the corridor dependency pass, 2026-08-11.** It is the
concrete blocker on closing #794/#795, so it is recorded as its own item
rather than as a caveat inside them.

`exports/archive/*.zip` carries **2 of the 21 voting sources' CSVs**
(`idpTradeCalc`, `ktcSfTep`). `build_api_data_contract` reads the other
19 from the working tree, so rebuilding an archived board reproduces
roughly 90% of *today's* inputs under a historical filename.

Measured consequence: rebuilding 14 archived exports spanning
2026-07-14 → 2026-08-10 produced 359 rows and a P90 band of 0.6201 on
nearly every one. That near-identity reads as remarkable stability and is
actually contamination. Any cross-board claim derived this way — the
corridor pass initially derived one, and withdrew it — is unsound.

Why it blocks the corridor decision specifically: every candidate
replacement whose reference is *external to the board being policed*
(historical drift distribution, change-point rail) needs a real
board-over-board distribution to be characterised, and none can be
recovered from what is retained. The corridor pass had to fabricate a
reference constant to score its change-point candidate at all, and
withdrew that too.

Cheap to fix and worth doing before the next corridor pass: archive all
21 voting-source CSVs in the export bundle, or persist a per-build drift
summary. Roughly two weeks of genuinely independent boards is enough to
measure a replacement detector's false-positive rate honestly.

Evidence: `evidence/W02/CD_CORRIDOR_DECISION.md` §6,
`evidence/W02/cd_hull_historical.txt`.

## W02-F015 (new) — the corridor anchor is also a voter

**= GitHub issue [#794](https://github.com/jasonleetucker-code/riskittogetthebrisket/issues/794).**
The issue is the owner-facing identity and takes precedence; this entry is
the audit-registry row for the same item, not a second one. Anything that
closes one closes the other.

**OPEN. Measured in B3, deliberately not repaired there.** Recorded here
rather than in `findings.json`, which was generated at `8b88623f` and is
not regenerated by this engagement.

`idpTradeCalc` is the IDP corridor's market anchor *and* a voting source
in the blend the corridor constrains — as are all three fallback anchors
(`dlfIdp`, `idpShow`, `fantasyProsIdp`). On the B3 pin it was the anchor
on **183/183** clamped rows and also voted on **183/183**; the fallback
chain never fired. So it received a direct contribution and then a
post-blend veto over the result.

B3 removed the hard second-bite (the veto covered 55.6% of the ranked IDP
board; it now covers **9.7%**) but **did not establish anchor
independence**, and that was outside its authorization. Whether the
corridor should anchor on a leave-one-out blend, on a genuinely external
source, or on something else is a design question with no measured answer
yet.

One measurement constraint a repair will hit: `idpTradeCalc` is also the
IDP **backbone**, so a whole-board leave-it-out rebuild is not "the same
model minus one vote" — it empties the shared-market ladder and changes
every other IDP source's coordinates. B3's isolate was the stamped
per-source vote share (0.721× the median of the other sources on clamped
rows), not the rebuild.

Evidence: `evidence/W02/B3_MARKET_CORRIDOR_EVIDENCE.md` §2, §9. Pinned as
a fact by `tests/api/test_market_corridor_characterization.py
::test_every_idp_anchor_is_a_voting_source_in_the_blend_it_clamps`.

**CD pass outcome (2026-08-11): CONFIRMED, and stronger than B3 stated.**
Not merely "the anchor is also a voter" — **no independent anchor is
constructible from this tree at all.** Exactly one loaded source does not
vote (`ktc`) and it is offense-only, while the corridor clamps IDP only;
every source covering IDP votes. The stage-3 median fallback is a median
over that same chain, so it is a second statistic of the same voters.
Quantified on the CD pin: all 32 clamps anchor on `idpTradeCalc`, which
votes on all 32; the anchor's share of the row goes from a median 1/3 in
the blend to 1.0 after the clamp, because a clamped value is
`anchor x (1 +/- band)` — a pure function of the anchor. The value move
itself is currently modest (median 2.0%, max 10.7%). Evidence:
`evidence/W02/CD_CORRIDOR_DECISION.md` §1.


**CLOSED 2026-08-11 by removal.** The corridor is gone, so no anchor sets a post-blend value. Measured before removal on 17 independent days: the anchor was also a voter on 539 of 539 clamped rows, always `idpTradeCalc`. `_market_anchor_for_row` and `_MARKET_ANCHOR_BY_ASSET_CLASS` are deleted; a test pins their absence so the mechanism cannot grow back as a second value-setting vote. Evidence: `evidence/W02/CD_CORRIDOR_DECISION.md` §7a.

## W02-F016 (new) — the corridor band is derived from the drift it bounds

**= GitHub issue [#795](https://github.com/jasonleetucker-code/riskittogetthebrisket/issues/795)** — same item, one identity each side.

**OPEN. A property of the empirical design, not of the B3 removal.**

After B3 the corridor's band is the P90 of `|value − anchor| / anchor`
computed per confidence bucket *on the board being clamped*. A board that
drifted **as a whole** would therefore widen its own acceptable band and
catch nothing — the mechanism cannot distinguish "this row is an outlier"
from "everything moved together".

This is why B3 kept the `_MARKET_CORRIDOR_MAX_BAND_BY_ASSET_CLASS`
facility in place rather than deleting it: the empty dict is a deliberate
state, not dead code awaiting cleanup.

What a repair would need that does not exist today: an anchor for the
band that is not the current board — a historical drift distribution, a
cross-league comparison, or a declared tolerance with stated provenance.
Any of those is a modelling decision requiring its own evidence, and
inventing a second hand-set constant is precisely what B3's criterion 6
rejected.

Evidence: `evidence/W02/B3_MARKET_CORRIDOR_EVIDENCE.md` §7, and the
comment at the constant itself.

**CD pass outcome (2026-08-11): CONFIRMED as a tautology, not a tuning
defect.** A percentile threshold cuts the worst 10% of whatever
distribution it is handed. Scaling every IDP value by f with anchors
untouched fires the IDENTICAL 32 rows at a flat 9.7% for every f from 1.0
to 10.0, the band scaling 0.6201 -> 15.2005: a 10x board-wide error is
invisible. Inverting it, inflating a fraction q of rows 3x gives 100%
detection at q<=10% and then 50.8% / 25.2% / 12.5% at q = 20/40/80%,
because capacity is fixed at ~33 rows however much is broken. So the band
is a fixed-rate outlier trimmer, not a catastrophic-error rail. Evidence:
`evidence/W02/CD_CORRIDOR_DECISION.md` §2.


**CLOSED 2026-08-11 by removal.** The self-derived P90 is deleted along with every `_MARKET_CORRIDOR_*` constant. The replacement has no band: `_BLEND_HULL_EPSILON` is 1e-9 float slack, pinned by a test to stay below 1e-6, and a second test rejects any percentile/bucket vocabulary reappearing in the detector body.

## W02-F017 (new) — confidence-bucket correctness is now a live dependency

**= GitHub issue [#796](https://github.com/jasonleetucker-code/riskittogetthebrisket/issues/796)** — same item, one identity each side.

**OPEN, and NEW as of B3 — the dependency did not exist before.**

The corridor derives its band per `confidenceBucket`. Before B3 the hard
cap overrode that number on every row, so bucket quality could not affect
production: B3's §7 analysis is explicit that the corridor was *not*
blocked by confidence work for exactly that reason. After B3 the
bucket-derived band decides every clamp, so **confidence-bucket semantics
now control production corridor behaviour for the first time**.

Concretely, on the B3 pin the three bands differ materially — medium
0.5183, low 0.6316, high 0.6504 — so which bucket a row lands in changes
whether it is clamped.

Cross-reference, do not duplicate: `W03-F004` tracks confidence-bucket
correctness itself (tooltip honesty now, a coverage term in the bucket
next). This entry exists because that finding acquired a **new consumer**
and its severity to the served board changed; it should be read alongside,
not instead of, W03-F004.

Note also the inversion B3 measured under the old policy — clamp rate by
bucket ran high 63.9% / medium 45.8% / low 60.7%, i.e. non-monotone in
confidence. Post-repair it is 8.3 / 10.0 / 9.8%, which is flat rather than
ordered. A band system that is *meant* to be confidence-graded producing a
flat outcome is worth understanding before anyone tunes it.

**CD pass outcome (2026-08-11): CONFIRMED incoherent; the recommendation
is abstention, not tuning.** On the CD pin the bands are ordered
*backwards* — high 0.6504 (n=36), low 0.6316 (n=174), medium 0.5183
(n=119) — so a HIGH-confidence row is permitted MORE disagreement than a
MEDIUM one, and high-confidence rows drift further from the anchor
(median 0.2071) than medium ones (0.0980). Total spread is 0.1321, so the
dependency is also doing little work for the complexity it carries. No
bucket constant was touched: the finding is that a replacement corridor
should decline to confidence-grade at all until the bucket methodology is
independently validated, which resolves the dependency by removing it
rather than by making the rates look attractive. Evidence:
`evidence/W02/CD_CORRIDOR_DECISION.md` §3.


**CLOSED 2026-08-11 as a corridor dependency.** Nothing in the value path reads a confidence bucket any more, so bucket correctness no longer gates production values; a test asserts bucket value cannot change enforcement. #796 remains open as a *display/metadata* question — it was never tuned here.

## W02-F019 (new) — correlated-source anomalies are covered by nothing

**= GitHub issue [#804](https://github.com/jasonleetucker-code/riskittogetthebrisket/issues/804)** — same item, one identity each side.

**Status: open. Pre-existing, and NOT created by the corridor removal.**

Injecting anomalies at the source CSVs and rebuilding the whole pipeline
(`evidence/W02/cd_upstream_defense.py`), single-source failures are well
handled — a source at ×5 or ×20 is absorbed by Hampel plus the
count-aware blend (≤1.7% blend movement), and an anchor source at ×5 is
caught outright by the declared-range check (0.0%). **Correlated
multi-source failures are not**: three or four sources moving together
move the blend by a median 5.7% and a maximum of **48%**, and *neither*
the retired market corridor *nor* the blend-integrity hull invariant
fires — both at 0 of 6 victims.

The reason is structural rather than a tuning miss. The hull invariant
asks whether a blend left the range of its own contributions; if every
contribution moves together the blend moves with them and stays inside.
The corridor anchored on `idpTradeCalc`, one of the correlated voters, so
its band moved too. And there is no independent arbiter to appeal to —
every IDP-covering source votes in the blend.

Recorded as its own finding so the gap outlives the corridor pass. It
does **not** reopen W02-F015/F016/F017, does **not** justify restoring
the corridor (which fired 0/6 in exactly these scenarios), and must not
be closed by inventing source weights ahead of a measurement of which
sources actually move together. Limitation on the evidence: 17
independent **offseason** days; correlated-source behaviour during live
games is unobserved.

## Not done here

- `verify_closure.py --rerun` over the 338 safe reproductions. It needs the full stack
  (156 commands hit `127.0.0.1:8000`; 35 hardcode a scratchpad path from a dead session) and
  the tool does **not** diff output against `expected`, so every rerun needs manual
  adjudication. That is the next session's first job.
- The 77 unsafe-to-rerun reproductions still need the hand-checked worklist
  `REPAIR_PROTOCOL.md` calls for.
- The C01–C43 and U01–U06 trackers under `docs/audits/` remain unmapped to W-ids.
