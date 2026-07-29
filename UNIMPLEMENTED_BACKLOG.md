# Chase Upside — Everything Discussed But Not Implemented

**Compiled:** 2026-07-27 · **`main` at compile time:** `d224e15de`
**Scope:** every item raised across this session that is not on `main` today.

This is deliberately exhaustive and includes things that were **considered and
correctly rejected** — because "we decided not to" is information the next person
needs as much as "we haven't got to it." Rejected items are marked and carry the
reason, so nobody re-litigates them from scratch.

**How to read the status column:**

| status | meaning |
|---|---|
| NOT STARTED | no code exists |
| BUILT, NOT WIRED | code exists and is tested, but nothing calls it |
| PARTIAL | some of it shipped, the rest did not |
| REJECTED | investigated and deliberately not done — reason recorded |
| OPERATOR ONLY | needs access or a decision I do not have |

---

## Read this first: much of this file is already superseded

**Updated 2026-07-28 ~00:15.** This document was compiled against `main` at
`d224e15de` and was stale within the hour — a parallel session had a large
amount of work in flight that it could not see. Treat every status below as a
claim about a `main` that no longer exists, and check the PR column before
picking anything up.

> **2026-07-29 audit:** two entries were not merely stale but actively
> misleading, and have been corrected in place (struck through, with the
> evidence): **§1.1**, which called itself "the highest risk item in this
> file" on the grounds that `/api/valuation/league-adjusted` had zero HTTP
> tests (it has 22), and **§2.1**, which said the TE basis conversion was
> not wired (it shipped 2026-07-27 and defaults on). A backlog that
> misreports risk is worse than no backlog: anyone triaging this file
> would have started with a non-problem. The remaining entries were not
> re-verified one by one — treat them with the same suspicion.

| item below | status here | actually |
|---|---|---|
| §1.1 endpoint has zero tests | NOT STARTED · *highest risk* | **#591** — 17 tests, incl. the 400/503/404 routing contract and in-place-mutation guard |
| §1.2 hydration flash | NOT STARTED | **#591** — `useSettings` returns `hydrated`; also fixed a duplicate first fetch |
| §2.1 TE basis wiring | BUILT, NOT WIRED | **#591** — wired pre-blend; measured blast radius, 80 TEs up, median +14.27% |
| §4.2 persist player-week actuals | NOT STARTED · *the one open Tier-0 item* | **#591** — 22 weeks / 16,995 player-weeks persisted for 2025 |
| §8.2 `tep=3` vs `tepp` | NOT STARTED · latent | **#593** — half of it *was* live via the DOM fallback; see below |
| §6 ML / archetypes — "undecided" | NOT STARTED | largely **overtaken by BDVM v1** (#600, merged) — a projection-driven fundamental engine beside the market board, flag `bdvm_engine` OFF |
| §12 guard-that-cannot-fire (4 instances) | — | **five**, and the fifth was this repo's own health check. See ORCHESTRATION.md §6.15 |
| §1.3 server-side composition | NOT STARTED | **DONE** — `valuation_mode` rides the override POST; the endpoint narrows to leagueKey scope when the lens is asked for |
| §1.4 surface honesty (suggestions rail, `/draft`) | PARTIAL | **mostly DONE** — the lens now reaches every engine, not just the rankings page; see below |

One item the file **never contained at all**, because it was found after
compiling: the realized-points scoring aliases — added as §13 at the end.

Two entries carry findings that change what this file *says*, not just its
status:

- **§8.2 was not purely latent.** I recorded it as harmless-today because KTC
  returns every TEP level regardless of the parameter — which is true of the
  *payload* path. #593 measured the other path: `tep=3` changes the rendered
  DOM, and the last-resort DOM fallback reads exactly that and writes it to the
  base-SuperFlex `ktc` source. When that fallback fired it inflated every tight
  end by ~22% with no log line. My "latent, silent" was half right — silent,
  not latent.
- **§4.2 is bigger than persistence.** Repointing at the unified release
  (#589) also **renamed six columns**, and reading a renamed column yields
  zeros rather than an error. #591 found `realized_points.py`'s IDP scoring had
  been reading three dead columns — `idp_tkl` and both tackle bonuses scoring 0
  all season — in a module with no test coverage at all.

Corrected in place rather than by rewriting the sections, so the original
reading and what displaced it both stay legible.

---

## 1. The valuation toggle (LI-9) — PARTIAL

The toggle **works** and is merged (#586). It defaults to `market`, so nothing
changed for you until you flip it. These are the gaps.

### 1.1 Endpoint has zero tests — ~~NOT STARTED~~ **DONE — this entry was false**

> **CORRECTED 2026-07-29 audit.** This item claimed
> `GET /api/valuation/league-adjusted` had "no test coverage of the HTTP
> path at all" and called itself "the highest risk item in this file".
> That is not true and appears to have been stale when written:
> `tests/api/test_league_adjusted_endpoint.py` exists with **22 test
> functions** covering the route, and `tests/api/test_valuation_mode_threading.py`
> plus `tests/api/test_overrides_response_cache.py` also exercise the
> path. Nothing to do. Kept (struck through) rather than deleted so the
> correction is visible to anyone who read the old claim.

### 1.2 Hydration flash — NOT STARTED

`useSettings`' `getServerSnapshot()` returns defaults, so server-render and first paint
show **Market**, then hydration flips to the stored value and the board re-sorts
visibly. `frontend/app/trade/page.jsx:1279-1283` already documents this exact failure
mode for a different setting. Fix: gate the overlay fetch on a hydrated flag, or hold
the loading state until the first settings-resolved fetch lands.

### 1.3 Server-side composition — DONE

**Superseded 2026-07-28.** `POST /api/rankings/overrides?view=delta` accepts
`valuation_mode` and applies the factors inside the same build. The accepted cost
below was taken consciously: asking for the lens narrows that response from
scoring-profile scope to leagueKey scope, with the same 503 guard.

The original text follows.

**Today the combination is deliberately blocked, not silently wrong.** If you have
custom source weights active *and* switch to league-adjusted, the overlay is not
applied and a warning is logged.

The reason: the overlay's ranks are the ranks of `default_consensus × factor`, but the
correct answer is `overridden_consensus × factor`, which the server never computed. No
client-side sequencing fixes it — composing them yields a board where neither the
values nor the ranks correspond to anything.

**The fix** is to thread `valuation_mode` through the existing
`POST /api/rankings/overrides?view=delta` pipeline so the factors are applied inside
the same build, before the compact pass. `_DELTA_PLAYER_FIELDS` already carries every
field this changes, so the delta shape is unchanged.

**Accepted cost, to decide consciously:** `/api/rankings/overrides` becomes
league-scoped when `valuation_mode != "market"`, needing the same league-mismatch 503
guard `/api/gameplan` has, plus `leagueKey` in its cache key. That is a genuine
widening of that endpoint's contract.

### 1.4 Surface honesty — PARTIAL (the big half is DONE)

**Superseded 2026-07-28 for the engines.** The suggestions rail is no longer
"server-computed off the un-overlaid contract" — every league-scoped engine
endpoint takes `valuation_mode` and answers from the selected board, and every
one of them stamps back the board it ACTUALLY served (`valuationMode`, plus a
`valuationNote` when it degraded). See the `valuation_mode` section in CLAUDE.md
for the endpoint table and the four load-bearing rules.

Neither remaining bullet below is silent any more, contrary to what this
section said — the T1-e honesty pass (615b7082) already landed both:
`/draft` renders `ValueBasisNote` (`frontend/app/draft/page.jsx:4515`) and
`tradeWorkspaceToCSV` emits a `Value Basis` column
(`frontend/lib/trade-logic.js:1545`).

What is genuinely still open is smaller and different: **`/draft`'s numbers
stay on the market board even with the lens on.** It fetches `/api/data` and
`/api/draft-capital` directly rather than going through `buildRows`, so the
overlay never reaches it. It says so, which is the important half; the values
themselves are unthreaded. `/api/draft-capital` is a deliberate no-op for
picks (factor 1.0), but its `rookieKtcValue` is a *player* value and does move
under the lens.

Also settled, separately: **the adjusted board stays a toggle rather than
becoming the default.** That was measured, not assumed —
`docs/adjusted-board-backtest.md`.

The original text follows.

`rankChange` is nulled when the overlay is active (so "moved up N since the previous
scrape" is never printed next to an adjusted rank). The rest was not done:

- **Top Movers panel** (`frontend/app/rankings/page.jsx:531-540`) builds risers/fallers
  from `rankChange`. Because it's nulled, the panel goes **empty rather than false** —
  not wrong, but unhandled. It should be hidden.
- **Suggestions rail** (`frontend/app/trade/page.jsx:1296-1330`) is server-computed off
  the un-overlaid contract, so with the toggle on its recommendations silently disagree
  with the local trade math. Either thread the mode or label it.
- **`/draft`** (`frontend/app/draft/page.jsx:4049-4056`) reads values straight off the
  contract, bypassing `buildRows`, so it stays on market values with no indication.
  In or out is fine; silent is not.
- **Exports** — `tradeWorkspaceToCSV` emits adjusted values with no marker. A CSV of
  adjusted values is indistinguishable from a market one.

### 1.5 Status badge — NOT STARTED

A sibling to `CustomMixBadge` (`rankings/page.jsx:1007`) saying "this is not the
canonical board." Currently only the control itself indicates the state.

### 1.6 Precomputed warm cache — NOT STARTED

Every overlay fetch pays a live build; a cold league pays the ~1.35 s replacement
solve. `_warm_overlays_in_background` (`server.py:1550`) already warms other payloads
with bytes/gzip/etag caches. Pure performance — no correctness impact.

---

## 2. TE premium — BUILT, NOT WIRED

### 2.1 The TE basis wiring — ~~BUILT, NOT WIRED~~ **SHIPPED 2026-07-27**

> **CORRECTED 2026-07-29 audit.** This entry says the conversion is
> "deliberately not connected to `_compute_unified_rankings`" and that
> "the live path still uses the flat
> `_TE_BLANKET_NON_NATIVE_MULTIPLIER = 1.15`". Both are false as of
> 2026-07-27: the `te_basis_conversion` feature flag defaults **True**
> (`src/api/feature_flags.py:141`, classified LIVE), and
> `_compute_unified_rankings` calls `convert_te_value` in Phase 2a
> (`data_contract.py:6456-6467` resolves it, Phase 2a applies it). See
> ADR-015 in `docs/league-intelligence/DECISIONS.md`, CLAUDE.md step 5a,
> and `tests/api/test_te_basis_conversion.py`. The flat 1.15 survives
> only as the rollback path when the flag is off.
>
> The analysis below remains accurate as the RATIONALE for the change
> that shipped; only its status is wrong.

**The finding:** 1.15 sits **below the entire observed range** (1.209–2.053) of KTC's
measured TE++ uplift. It **under-corrects every tight end**. Wiring it moves TE values
**UP**.

**Insertion point** — both sessions independently reached the same conclusion: the
**pre-blend, per-source** site at `data_contract.py:6849-6855`. The blend already does
per-source TE alignment there; replacing a blanket constant with a measured curve at
the same point is not double-counting.

**Non-negotiables when wiring:**
- Preserve the KTC exemption (it's already on the TE++ basis — converting is a no-op).
- `adjustment.py::te_premium_axis` must stay `ABSENT`, so the post-blend axis and the
  blend never stack.
- Produce a board-wide before/after TE delta artifact.
- **No non-TE value may move.**
- Update the source-text guard in `tests/league_intel/test_te_premium_invariants.py`.
- Full rule-4 downstream sweep (UI, sorting, filtering, exports, league transforms).

**What unblocked it:** the ×1.319-vs-×1.368 conflict is **closed** (#587). There was
never a disagreement — ×1.368 is an April baseline, ×1.319 is July, and ADR-009 had
already recorded the drift. Four measurements across three independent code paths agree:
#585 at 1.3187, this session at 1.3187, #587 at 1.31869688 (running the LI workstream's
own function), and ADR-009's 1.3196 on the 07-26 scrape. Controls byte-identical
390/390.

### 2.2 Per-source TE alignment across all sources — NOT STARTED

Your idea, and it's sound: rather than one blanket multiplier for all non-TEP sources,
measure **each source's** implicit TE posture and use KTC's curve to close the residual
gap per source.

**The obstacle:** normally this needs a paired standard/TE-premium board per source, and
the survey found **only KTC has one**. FantasyPros' pair is rank-encoded and was
rejected (on a rank encoding every ratio compresses to ~1.0 *including the controls*, so
the validity check passes vacuously and certifies a meaningless number).

**The workaround, untested:** compare each source's TE-vs-non-TE relationship against
`ktc` *standard*, then apply KTC's measured TE++/standard curve to close the remaining
gap. This needs no paired variant per source.

**Hard gates required** — a cross-vendor ensemble was tried and failed once already: it
flipped sign depending on which boards were included, and a header-case bug silently
dropped a fourth board, making a wrong answer look clean. Reuse `calibration.py`'s
existing two conditions (controls-at-unity **and** genuine cardinal scale).
**Explicit exit: a source that fails the gates keeps the blanket constant.** No source
inherits KTC's curve by analogy.

### 2.3 `src/canonical/te_premium.py` — REJECTED (built, then discarded)

I built a complete measured-curve module this session: config, regeneration script, 30
tests, full suite green at 4105 passed, committed — then dropped it before pushing.

**Why:** it double-counted. The market anchor `ktcSfTep` **is** KTC's TE++ board, so the
blend already embeds the structural 2-TE premium. The module measured `ktcSfTep / ktc`
and proposed applying that ratio to a board already anchored on `ktcSfTep`.
`tests/league_intel/test_te_premium_invariants.py` exists specifically to prevent this.

**Do not resurrect it.** The correct insertion point is pre-blend (§2.1), not post-blend.

---

## 3. Scoring settings — NOT STARTED · **largest unexploited edge found**

Measured against your default-scoring baseline league `1328545898812170240`:
**91 of 146 scoring keys differ.** This is not a variant of default — it's a different
scoring philosophy, and no ranking source accounts for any of it.

### 3.1 Distance-banded receptions — the headline

| | baseline | yours |
|---|---|---|
| `rec` | **0.75 flat** | **0.08** |
| `rec_0_4` | 0.0 | 0.17 |
| `rec_5_9` | 0.0 | 0.42 |
| `rec_10_19` | 0.0 | 0.67 |
| `rec_20_29` | 0.0 | 0.92 |
| `rec_30_39` | 0.0 | 1.17 |
| `rec_40p` | 0.0 | **1.92** |

A ~10-yard catch scores 0.08 + 0.67 = **0.75**, identical to baseline. So the *mean* is
calibrated to 0.75 PPR, but the *distribution* is completely different: a checkdown back
earns ~0.25/catch while a deep threat earns ~2.00. **An 8× spread that every source you
ingest prices as a flat 0.75.**

Directly measurable — nflverse carries `receiving_air_yards`, `targets`,
`air_yards_share` per player-week, and those columns are now arriving after #589.

### 3.2 IDP inverts the market

| | baseline | yours |
|---|---|---|
| `idp_sack` | 4.55 | **2.92** ↓ |
| `idp_pass_def` | 2.11 | **5.32** ↑ 2.5× |
| `idp_tkl_loss` | 2.06 | **4.25** ↑ |
| `idp_qb_hit` | 1.08 | 2.13 ↑ |

Sacks are worth *less* here; coverage is worth *far* more. Every IDP board on the market
is built around edge rushers. Your league pays for coverage linebackers and ball-hawking
DBs.

### 3.3 Passing is accuracy-weighted

`pass_td` 5.0→6.0, `pass_int` −1.5→**−4.0**, plus `pass_cmp` 0.15, `pass_inc` −0.22,
`pass_sack` −1.0, `pass_int_td` −2.0. First downs 0 → 1.0 for RB/WR/TE (0.67 QB).

Note `bonus_fd_te` == `bonus_fd_wr` == `bonus_fd_rb`, which independently re-confirms
**no TE scoring premium** — and is exactly why TE demand must be read from roster
structure (2 TE starters), not scoring keys.

### 3.4 The gating question — PARTIALLY ANSWERED

A per-league scoring adjustment **was built and then removed**. `data_contract.py:7738`:

> LAM (League Adjustment Multiplier) and positional scarcity have been **fully removed**
> from the codebase. […] They are **stripped from ALL API responses**.

Deliberately removed *and* actively stripped is a strong prior it was found unsound.
The precise reason still needs the consolidation commit history.

**Exit condition stands: if the retirement reason still holds, document it and stop.**
Do not rebuild a retired system to rediscover why it was retired.

### 3.5 Remaining spike questions — NOT STARTED

- What in `src/scoring/` is live vs dead? Four call sites exist (`Dynasty Scraper.py:67`,
  `src/public_league/awards.py:1171`, two scripts). The package has `scoring_delta.py`
  (full stat taxonomy incl. first downs), `baseline_config.py`, `archetype_model.py`,
  `feature_engineering.py`, `replacement_level.py`, `backtest.py`, `tiering.py`.
- What fraction of the board can be assigned a historical stat mix? Rookies and low-snap
  players will have none — they must come out **ABSENT**, not shrunk toward a positional
  mean.
- What reference scoring do the sources actually price to? The baseline league is a
  *defensible* reference but "sources price to the default" is an **assumption, not a
  measurement**. State it as such.

---

## 4. The data foundation — PARTIAL

### 4.1 nflverse 2025 URL — **DONE** (#589)

Recorded here only because it was the blocker for everything above.
`fetch_weekly_stats([2025])` returned `[]` all season; now returns **19,421 rows**.

### 4.2 Persist player-week actuals — NOT STARTED · **the one open Tier-0 item**

Nothing writes fetched stats to durable storage, so **the system structurally cannot
backtest its own value changes**.

`src/nfl_data/ingest.py` already has `WeeklyStatRow` (:48) and `WeeklyDefensiveStatRow`
(:91); `fetch_weekly_stats` (:288) and `fetch_weekly_defensive_stats` (:317) now return
real data. The work is writing what they return to disk.

**Not a DB migration.** Follow the existing JSONL pattern —
`data/source_value_history.jsonl` (one JSON object per line) and
`data/ros/aggregate/history/{ISO-timestamp}.json`. Reuse the atomic-write helper the
snapshot store already has.

**Two things to check first:** `data/nfl_data_cache/` is an **empty directory** despite
being referenced as a TTL cache — decide if it's the right home or vestigial. And
`data/source_value_history.jsonl` **does exist** (92 KB), contrary to the prior handoff
listing it as production-only.

### 4.3 What backtesting is and isn't available

An important correction from this session. **Past-season data is usable and is most of
what you'd want:**

| what | data | backtestable |
|---|---|---|
| Scoring re-score under your rules | historical NFL stats | **now** |
| Reception-distance / IDP category edges | historical NFL stats | **now** |
| Our board's predictive accuracy | our own past outputs | thin — partly reconstructable |

Only the third is calendar-bound, because we didn't save our own historical board
values. Even that has workarounds — KTC publishes historical value charts.

---

## 5. Performance — NOT STARTED

You asked for this explicitly ("everything as fast as possible without sacrificing
anywhere else") and it never got done.

Measured earlier in the session, **before the R5 performance pass merged** — so
re-measure before optimizing:

- `/rankings` ~28.8 s
- `/trade` ~16.3 s
- The 5.6 MB contract fetched **twice**, the override delta **twice**, draft-capital
  **twice**
- Single uvicorn worker with no `workers` argument

The duplicate fetches are almost certainly real regardless of R5 and are the cheap win.

---

## 6. Machine learning / player archetypes — NOT STARTED

You asked "what happened to the whole machine learning engine we talked about with
player archetypes?"

`src/scoring/archetype_model.py` and `feature_engineering.py` exist. My recommendation
at the time was to **delete the dead archetype code**, and you said "whatever you
recommend" — but neither the deletion nor any revival happened. It is in the same
ambiguous state: present, largely uncalled, undecided.

This is worth an explicit decision rather than continued drift. It's also entangled with
§3 — if the scoring work proceeds, archetypes may become genuinely useful for assigning
stat mixes to players with thin histories.

---

## 7. Competitor-parity roadmap (PFK + Fantasy Navigator) — mostly DONE

Shipped earlier in the session: both sources ingested, player search/filters, FAAB v2,
Sleeper intel + Sharp Tracker, the News tab, Pick Projector, and the full R0–R5
redesign.

**Not done:**

- **Best-ball ADP ingestion** (Underdog) — NOT STARTED
- **Player contracts / snap-share data** — NOT STARTED. PFK has
  `pfk_player_contracts` and `pfk_player_season_snap_share`; nflverse has equivalents,
  and `snap_counts` is already in `_URL_TEMPLATES`.
- **Stats tab on the player popup** — NOT STARTED
- **Dispersal draft tool** — REJECTED, de-prioritized as not league-edge
- **Creators / polls** — REJECTED, same reason

---

## 8. Audit backlog (inherited from the collaborative audit)

### 8.1 Source-family confidence (Finding P) — NOT STARTED

`_compute_confidence_bucket` (`data_contract.py:1879-1909`) gates "high" confidence on
`source_count >= 2`, where `sourceCount` is a plain `len()`. **There is no notion of
source families anywhere in the codebase.**

Correlated clusters counted as fully independent: **DLF ×4, FantasyPros ×3, Flock ×2,
DraftSharks ×2**. A rookie WR appearing on four DLF/Flock entries reaches "high"
confidence off **two publishers** and escapes the 0.30 single-source haircut.

**Do measurement only first** — pairwise Spearman over shared players. The clustering
above is the *hypothesis*, not the finding.

### 8.2 `tep=3` vs `tepp` extraction — NOT STARTED · latent, silent

`Dynasty Scraper.py:1947` requests `?sf=true&tep=3` (**TE+++, level 3**) while
`_ktc_extract_tep` deliberately pulls `tepp` (**TE++, level 2**).

Harmless *today* only because KTC returns every level in the payload regardless of the
query parameter. If KTC ever filters by the requested level, `ktcSfTep.csv` silently
becomes TE+++ or empty **and no test would catch it**. An unguarded dependency on
undocumented upstream behaviour.

### 8.3 Mixed-market disclosure (Finding N) — NOT STARTED · needs a product decision

`finder.py` sums KTC-offense values with IDPTradeCalc-defender values with no
`marketsMixed` flag. `angle.py` documents a 6.2% overstatement from that class of sum.
Recommendation is **disclosure, not suppression** — the finder's premise needs a market
number.

### 8.4 Removal-cost surplus (Finding E) — NOT STARTED

Changes a live output; wants the F-6 before/after harness first.

### 8.5 True weekly-points ROS utility (Finding A) — NOT STARTED

Blocked on §4.2. `rosValue` is a normalized log-rank index (0–100), **not points**,
despite downstream field names (`lineupScore`, `startingLineupScore`) implying otherwise.

### 8.6 Agent orchestration reform (Finding R) — NOT STARTED, organizational

---

## 9. Known defects, open

| # | defect | status |
|---|---|---|
| 1 | **Forced public-league rebuild makes the whole API unresponsive** (§6.11) | FIXED 2026-07-28 (§14) — reproduced, mechanism was the failure path |
| 2 | `test_anchor_curve_extrapolation_monotone` **fails on `main`** — `Chase Young` ties at rank 107 against a strictly-increasing assertion. It's `livedata`-marked so **CI deselects it**: a real failure that is invisible | OPEN |
| 3 | `/league` SSR exceeds even a 5 s proxy timeout on a cold backend | FIXED 2026-07-28 (§14) — not a cold-start cost; 6.45s → 2.35s |
| 4 | `/league/activity` Trades filter | OPEN |
| 5 | `/api/chat` | FIXED 2026-07-28 (§14) — dead proxy removed; wiring chat still a product decision |
| 6 | `finder.py` has no UI caller | OPEN as a FEATURE (§14) — the "two implementations" description was wrong |
| 7 | 5 dead feature flags | OPEN |
| 8 | `auction_power.py` parity | OPEN |
| 9 | **43 of 208 `src/` modules unreachable** (~12,571 lines) | OPEN |
| 10 | `/api/draft-capital` returns 200 where 503 is expected | OPEN |
| 11 | Pick tethering untested | OPEN |
| 12 | Two tests that cannot fail | OPEN |
| 13 | D-5 isolation leak | OPEN |
| 14 | Sticky trade header | FIXED 2026-07-28 (§14) — no vertical anchor above 768px |
| 15 | `scripts/measure_te_demand_actuals.py:29` hardcodes a dead worktree path | OPEN |
| 16 | `scripts/measure_engine_value_divergence.py` hardcodes a dated default payload | OPEN |
| 17 | `deploy/apply_hardening.sh` reinstalls repo nginx config over the installed one and **is not wired to any workflow** — could revert certbot | CLOSED 2026-07-28 (§14) — standing policy + tripwire test |
| 18 | `data/ros/aggregate/latest.json` has **6 duplicate player rows** (same player in two naming conventions) and 16 rows with non-lowercase `canonicalName`; 40 of 666 rostered players fail to match | OPEN |

---

## 10. Operator-only — cannot be closed from a session

| item | what's needed |
|---|---|
| **nginx bare-IP deploy** | Confirm no external monitor probes the bare IP before applying. The change serves health-only over plaintext and 301s everything else to `https://chaseupside.com`. Merging does **not** deploy it — `deploy.yml` has no nginx reference and `apply_hardening.sh` isn't wired to any workflow. |
| **`IDPSHOW_SESSION_JSON` secret** | Add as a repo secret to let CI fetch IDP Show. Workflow is **pre-wired and inert** — absent, CI logs a skip and the prod systemd timer stays the only producer. Contents: the full JSON of your local `idpshow_session.json` (`connect.sid`, `AWSALBTG`, `AWSALBTGCORS`). |
| **`INTEL_REFRESH_TOKEN` rotation** | Unverified whether completed |
| **certbot renewal dry-run** | `ssh root@chaseupside.com "certbot renew --dry-run"` |
| **`grant-ssh-access.yml`** | Did it execute in its 33-minute window? Open since a prior session. |
| **Which TE calibration system survives** | `src/league_intel/te_premium.py` vs `src/league_intel/calibration.py` + `scripts/extract_te_calibration_pairs.py`. Duplicate solutions to one problem; no file collides today but they collide conceptually. |

---

## 11. Long-horizon, explicitly future

**Link any Sleeper account, pull that league's scoring, adjust rankings accordingly.**
Your stated eventual goal. Its prerequisite is exactly §3 + §4.2 — a working
scoring-delta engine plus persisted historical stat lines. Everything in those two
sections is a step toward it.

---

## 12. The pattern worth carrying forward

Four separate instances this session of **a guard that cannot fire** — recorded as
§6.15 in `docs/ORCHESTRATION.md`:

1. `test_url_templates_contain_expected_paths` asserted the substring `"player_stats"`,
   which the retired path satisfies right up until it 404s. Missed the nflverse rename
   for a whole season.
2. The TE double-count invariant was real and correct — but the module it would have
   caught was deliberately left unimported, so it had nothing to catch.
3. The `soft` staleness flag had no upper bound, so a lapsed cookie and a dead vendor
   looked identical forever.
4. The `stale-sources` alert issue had no path that could ever close it.
5. **The session-start health check measured filesystem mtime** and called it data
   freshness. Found and fixed while compiling this file, from its own false alarm.

**The tell is the same each time:** the guard's *stated* purpose and its *actual*
predicate differ, and nothing forces them to agree.

Instance 5 is worth expanding, because it is the first one that failed in **both**
directions at once and so shows the pattern more completely than the other four.

Remote sessions clone the repo fresh, which stamps every file with the checkout
time. So `stat -c %Y` answers "when did git write this?", never "when was this
data fetched":

- In a fresh clone every source reads **0h** and the `>12h` warning **cannot
  fire** — the pipeline could have been dead for months and this check would
  report clean. That is instances 1–4's failure mode.
- After a branch switch git rewrites only files that *differ*, so unchanged files
  keep an older mtime and read as stale when they are not. Measured 2026-07-27:
  `idpTradeCalc.csv` reported **49h against a real content age of 131h** — 82h
  under-reported — while `ktc.csv` reported 0h against 3h.

So it missed real outages *and* invented fake ones, and the fake one is what
exposed it: the reported 49h sent me looking for a scrape failure that did not
exist.

It was also watching the wrong artifact. `exports/latest/site_raw/` is a raw
mirror — `preflight.py::_seed_data_cache` copies `dynasty_data_*.json` and does
**not** copy `site_raw/`, so the pipeline, the E2E suite and production all read
the JSON. The 2h cron handles these three sources with `stamp_if_present` rather
than `run_fetcher`, so the mirror is written only by full scraper runs and
freezes for days with nothing wrong.

**A correction to my own first fix**, recorded because the error is the
instructive part. That pass measured the mirror's commit cadence and concluded
*"idpTradeCalc legitimately goes 5–20 days between updates in the offseason."*
The gaps are real — 6, 8, 12, 18, 23 days — but the attribution was wrong: that
is the cadence of **full scraper runs**, not of IDPTradeCalc publishing. I
measured the instrument and described the vendor. The right conclusion (don't
warn on it) came from the wrong premise, and would have survived indefinitely
because the output looked correct. ORCHESTRATION.md §6.12 had diagnosed this
correctly twelve hours earlier; I hadn't read it first.

The check now reads `scrapeTimestamp` from the contract — an internal content
stamp, so unlike mtime *or* commit dates it survives cloning and means the same
thing everywhere. Threshold from `config/source_staleness.json`. Per-source
health is reported as **coverage** (how many players carry a value), because
that is what a dead source changes and a line count is not.

Every degraded input had a path back to a confident "0h fresh", so all five are
pinned — and the second one is the point:

| path | result |
|---|---|
| healthy | 4h against 24h, silent |
| contract 99h old | **WARNING fires** |
| source dropped from `siteStats` | `ABSENT — source produced nothing this run` |
| `scrapeTimestamp` missing | `UNKNOWN`, not 0h |
| no contract file | `UNKNOWN` |

A fix for a guard that could not fire is worth nothing until you have watched
the new one fire.

**Three cheap checks, in order of value:**

1. *Can I make this test fail right now, deliberately?* If not, it isn't a test.
2. *What does the predicate actually assert, versus what the name and docstring claim?*
   Substring-vs-identity is the recurring gap.
3. *Does the alarm have an off switch, and the exemption an expiry?* Anything that can
   only accumulate will eventually be ignored.

---

## 13. §9 defect sweep — disposition, 2026-07-27

All 18 rows of §9 were worked. Nine were fixed and merged (#592, #596,
#599 and the PR carrying this note). The rest are recorded here with
what was actually measured, because several of §9's own descriptions did
not survive checking and re-deriving them cost more than fixing them.

**A standing caveat, earned the hard way:** §9 is reliable in KIND and
unreliable in NUMBER. Verified drift so far — "6 duplicate player rows"
(0 today), "40 of 666 fail to match" (36), "5 dead feature flags" (7),
"pick tethering untested" (tested, 15 tests, none of which CI ran),
"43 of 208 modules unreachable" (16 orphans / 2,044 lines, and 8 of
those are dynamically dispatched). Check each row before working it.

### Fixed

| # | What it actually was |
|---|---|
| 2 | `test_anchor_curve_extrapolation_monotone` — asserted strict monotonicity where ties are structural (#592) |
| 7 | "5 dead feature flags" — measured **7 of 13** unable to affect a request; classification moved into `_GATE_STATUS` as checkable data (#596) |
| 11 | "pick tethering untested" — 15 tests existed; `-m "not livedata"` collected **15 deselected, 0 run**. Pure-logic half split out so 9 now block (#599) |
| 12 | Two tests that could not fail — a `len(x) >= 0` tautology, and a weekday-dependent assertion accepting both outcomes (#599) |
| 15 | Script pinned to a deleted agent worktree (#599) |
| 16 | Default export path correct for exactly one day (#599) |
| 18 | ROS team-strength joined two uncanonicalised sides; 8 of 36 unmapped players recovered (#599) |
| 4 | `/league/activity` — `useMemo` sat *after* a conditional return, making the hook count data-dependent. Reordered |
| 8 | `auction_power` — Python "source of truth" and the JS the user actually sees had duplicate constants and no parity guard. Added |
| 13 | D-5 isolation leak — the test depended on ambient registry state; now establishes its own |

### Not fixed, and why

*(Superseded 2026-07-28 — every row below was reworked in the closing
sweep. See §14.)*

| # | Finding | Why it stayed open at the time |
|---|---|---|
| 5 | `/api/chat` | **Three layers dead**, confirmed: `src/api/chat.py` (351 lines) is not imported by `server.py`; `frontend/app/api/chat/route.js` proxies to a backend route that does not exist; and nothing in the UI calls the proxy. Wiring it is not a defect fix — it ships a streaming-LLM feature with an API-key dependency and per-request cost. That is a product decision. |
| 6 | `finder.py` has no UI caller | Recorded as "two competing implementations". **This description was wrong** — see §15. |
| 14 | Sticky trade header | Could not reproduce; "no defect was visible by inspection". **There was one** — see §15. |
| 1 | Forced public-league rebuild makes the API unresponsive | Marked "OPEN, unproven". Needs a live reproduction against a running backend. |
| 3 | `/league` SSR exceeds a 5s proxy timeout cold | A performance claim that needs live measurement against a cold backend. |
| 17 | `deploy/apply_hardening.sh` unwired | Confirmed: referenced only from `deploy/**/README.md`, never from `.github/workflows/`. Reinstalls the repo's nginx config over the installed one and could revert certbot. |

---

---

## 14. Realized-points scoring aliases — FOUND AFTER COMPILING, FIXED

Not in the original file: found on 2026-07-28 while reviewing #600, and worth
recording because the *shape* of the mistake generalises.

Sleeper publishes some scoring rules under two key names. `realized_points.py`
read only the canonical spelling, so any rule your league dumps under the alias
scored **zero, silently** — the key is simply absent from the settings dict, so
there is nothing to raise.

Measured against live 2025 data, both aliases are live in this league:

| alias in your dump | module read | value | 2025 points unscored | who it hits |
|---|---|---|---|---|
| `idp_pass_def` | `idp_pd` | 5.32 | **11,119** | cornerbacks |
| `idp_qb_hit` | `idp_hit` | 2.13 | **6,545** | edge rushers |

Top single players affected: Mike Jackson 23 PD (122 pts), Zach Allen 51 QB hits
(109 pts). For a CB whose realized season lands near 150–200 points, that is not
a rounding error.

**The generalisable part.** #600 fixed the first one — the key someone happened
to trip over — with a one-entry literal. `sleeper_ingest.KEY_ALIASES` already
enumerated **eight**. Half-fixing was not half-right, it was *differently*
wrong: PD is a corner stat and QB hits an edge stat, so correcting only PD tilts
DB up against DL by 11k points while the linemen stay owed 6.5k. **A partial
correction to a relative ranking introduces a bias that no correction does
not** — the arithmetic gets closer to true while the ordering gets further from
it.

Fixed by deriving the map from `KEY_ALIASES` rather than restating it, so the
ninth alias Sleeper adds is picked up by both layers at once. Six regression
tests, all observed failing against the one-entry version first.

Still open, and deliberately not guessed at: whether any of the other six
aliases go live if you ever change scoring, and whether the same
noticed-one-only pattern exists in the *offensive* keys. `KEY_ALIASES` shows no
genuine offensive aliases today, but that was not measured against a second
league's dump.

---

## 15. Closing sweep — the last six, 2026-07-28

All six remaining §9 rows were worked to a conclusion. Four were real
defects and are fixed; two are recorded as deliberate standing policy
with a tripwire. **Three of the six had descriptions that did not
survive measurement**, which is the same standing caveat §13 opened with
— §9 is reliable in KIND, not in NUMBER, and now demonstrably not always
in MECHANISM either.

| # | Outcome | What it actually was |
|---|---|---|
| 1 | **Fixed** | Real, and the mechanism is the *failure* path. Handlers resolve the snapshot inside `run_in_threadpool`, so each waiter holds an AnyIO worker token from the process-wide limiter that every other endpoint shares. The lock's dedup re-check only advances `fetched_at` on success, so with the vendor down it is unsatisfiable and every waiter re-attempts in turn. Measured with 8 concurrent `?refresh=1` against a 0.5s builder: **8 serial upstream attempts, 4.01s wall, 18.02 thread-seconds**, growing without limit in N. Fixed with a failure cooldown + a wait ceiling → **1 attempt, 0.50s, 4.00 thread-seconds**. |
| 3 | **Fixed** | Real, but **not a cold-start cost** — the recorded framing pointed at the wrong place. Warm `GET /api/public/league` measured 6.449 / 6.643 / 6.484s; cold `?refresh=1` measured 6.418s. The snapshot cache was irrelevant because `build_public_contract` runs on *every* request and took 7.26s by itself. Profiling found `PublicLeagueSnapshot.player_position` called **514,020 times per build** (`awards.py` re-walks every starter of every week of every season), re-running `resolve_idp_position` each time — 15.3s of a 19.3s cumulative. Memoized per snapshot: build **7.26s → ~2.3s**, endpoint **6.45s → 2.24-2.53s**, under the 5s timeout the defect named. Output verified identical modulo the contract's own embedded timestamps. |
| 5 | **Fixed** | Three layers confirmed dead. Wiring chat remains a product decision and was **not** made. What was fixed is the half-wired state: `frontend/app/api/chat/route.js` was a live user-facing route proxying to a backend route that does not exist, so it could only ever 404. Removed. `src/api/chat.py` is kept — it is the valuable half, and the reachability audit reports it as ORPHAN. A consistency test now fails on any *partial* wiring, in either direction. |
| 6 | **Description wrong** | `src/trade/finder.py` genuinely has no UI caller — that part holds. But `/finder` does **not** compute arbitrage client-side. Its five presets filter and sort the board on `sourceRankSpread` / `confidenceBucket` / `isSingleSource` / `rookie`; there is no market-versus-board comparison anywhere on the page. The only occurrence of "arbitrage" was a stale header comment calling it "the arbitrage blotter", and that one word is what produced the phantom second implementation — and with it the phantom product decision. Comment corrected, true state pinned. **Wiring the engine to a UI is a feature, not a defect fix, and is still open as such.** |
| 14 | **Fixed** | Reproducible, and the earlier "not visible by inspection" is explained. `.trade-sticky-tray` declared `position: fixed; left: 0; right: 0` with **no vertical offset**; the only rule supplying `bottom` sat in an `@media (max-width: 768px)` block. So the tray anchored correctly on phones and had `bottom: auto` — painted at its static position and pinned there — on every wider viewport. Grepping the class shows a `bottom` and reads as complete; you have to notice which block it is in. A scan now rejects any top-level `position: fixed` rule with no vertical anchor (`position: sticky` excluded — a frozen table column is correct without one). |
| 17 | **Standing policy + tripwire** | Confirmed unwired, and deliberately staying that way. Its mitigations are real but do not cover the case that matters: a config that reverts certbot's in-place edits is still *valid* nginx, so the script's own `nginx -t` guard passes and the site returns serving the wrong certificate paths. Kept operator-run. A test now fails if any workflow references it, so wiring it becomes a deliberate act rather than a line added during an unrelated change. |

**Pattern, continued from §12.** Two more instances of a guard whose
stated purpose and actual predicate differ, both found here: the
public-league lock documented as preventing a burst from "multiplying
work" (true only while the upstream is healthy — the exact condition
under which bursts do not happen), and a sticky-positioning rule whose
anchor lived at one breakpoint. Both read as complete at the point of
use.

**And one about measurement.** The first check of whether the #3 memo
changed output reported *different* — which, taken at face value, would
have reverted a correct 2.7x fix. The contract embeds wall-clock stamps
(`generatedAt`, `asOf`), so two runs of the *same* code never match
either. The control that caught it was comparing an implementation
against itself before comparing it against the alternative.
