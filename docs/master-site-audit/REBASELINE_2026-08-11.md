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

## W02-F003 — the market corridor clamp

**STILL REPRODUCES, and the rate rose.** Remeasured, not fixed.

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

## W02-F003 — the IDP market corridor clamp

**REPAIRED IN B3.** Reproduced first on a fresh pin (code `2449af9ac`,
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

Still open after B3: the anchor is still a voter on the remaining 9.7%;
the confidence-bucket dependency is now LIVE for the first time (the band
that decides clamps is derived per bucket); C17's OFFENSE half; the IDP
master's 1.552× fit-scale claim; W30-F023.

## Not done here

- `verify_closure.py --rerun` over the 338 safe reproductions. It needs the full stack
  (156 commands hit `127.0.0.1:8000`; 35 hardcode a scratchpad path from a dead session) and
  the tool does **not** diff output against `expected`, so every rerun needs manual
  adjudication. That is the next session's first job.
- The 77 unsafe-to-rerun reproductions still need the hand-checked worklist
  `REPAIR_PROTOCOL.md` calls for.
- The C01–C43 and U01–U06 trackers under `docs/audits/` remain unmapped to W-ids.
