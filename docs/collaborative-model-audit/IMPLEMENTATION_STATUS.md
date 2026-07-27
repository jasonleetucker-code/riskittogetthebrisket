# Implementation status

**Branch:** `claude/fantasy-football-audit-53l3g7` · **Base:** `a6edd364`
**Baseline suite:** 4075 passed, 0 failed (`pytest -m "not livedata"`)

---

## Landed

| # | Change | Finding | Tests |
|---|---|---|---|
| WS-0 | `LOCKSTEP_SETUP.md` no longer names a third party's IP as the production target | S | — (doc) |
| WS-0 | Four runbooks + `HANDOFF.md` + `CURRENT_STATE.md` repointed off the lapsed domain | S | — (doc) |
| WS-0 | Bare-IP `:80` block: health-only over plain HTTP, everything else 301s to HTTPS | S | `tests/api/test_nginx_bare_ip_block.py` (6) |
| WS-1 | Dead projection branch collapsed; `RankedRow.projection_value` documented honestly | A | `tests/ros/test_projection_value_is_not_consumed.py` (4) |
| WS-1 | `rosValue` no longer described as "points" in `gameplan.py` | A | — |
| WS-1 | `marginalPoints` → `marginalStrengthIndex` (alias kept) | A | existing |
| WS-1 | `replacement_gap` → `replacement_level` (alias kept) | C residual | existing |
| WS-1 | Four stale `1.25` comments + the conftest `bonus_rec_te` contradiction | F | — |
| WS-2 | KTC TE++ uplift curve measured, fitted, config'd | F | `tests/league_intel/test_te_premium_measurement.py` (15) |
| WS-2 | `measure_league_te_premium` — all TE-touching keys, not just `bonus_rec_te` | F | same |
| WS-3 | **Finder migrated onto `rankDerivedValue`** | K | `tests/trade/test_finder_canonical_board.py` (12) |
| WS-3 | Thresholds re-derived by measured `k`, not ported | K | existing, made threshold-relative |
| WS-3 | 202 unpriced assets counted + warned rather than vanishing | K | same |
| WS-3 | Negative-delta comment corrected; summary sign fixed | L | same |
| WS-3 | Dead `MAX_PACKAGE_SIZE` / `PARTIAL_MARKET_MAX_RANK` removed | — | same |
| WS-4 | `tradePartnerFitScoreRange` published; bounds derived from the caps | J | `tests/roster_intel/test_partner_reachable_range.py` (12) |
| WS-4 | `need`/`window` double entry documented at the assembly site | J | same |
| WS-4 | Window `probabilities` → `affinities` (alias kept) | H | same |
| WS-4 | Window `notes` restored to the `gameplan` projection | H | same |

**49 new tests.** Every one was observed failing against the defect it guards before the
fix landed; the ROS trio was additionally mutation-tested.

---

## Built but deliberately NOT wired — TE

The KTC TE++ curve and the league-scoring measurement both exist, are tested, and change
nothing in the live value path yet.

**Why staged.** You asked for measured scoring plus KTC's TE++ curve. Measuring produced
a result worth seeing before it ships — and a correction to my own first pass.

* The league starts **two mandatory TE starters**, with TE also FLEX/SFLEX eligible. The
  target basis is therefore **TE++**, which is what the blend already assumes.
* KTC's measured TE++ uplift is **1.209–2.053**, rank-dependent. The live flat **1.15**
  sits below that entire range.
* So non-TEP boards are lifted **too little**, and correcting it moves TE values **UP**.

*(A first pass measured demand from scoring keys alone, found no `bonus_rec_te`, and
concluded the opposite — that values should come down. That confused the scoring
mechanism with the structural demand. Retracted; see `CLAIM_REGISTRY.md` finding F.)*

**The 1.368-vs-1.319 cross-workstream conflict is resolved and was never a conflict.**
Running the LI workstream's own `measure_paired_te_premium` against today's contract
returns 1.3187 with byte-identical controls — the same number this audit measured off the
raw CSVs, by a different path. The 1.368 figure is the April 2026-04-28 baseline fixture;
`tests/league_intel/test_calibration.py:347-360` records both. Three months of real board
drift, not a methodological disagreement. See EXP-8. Nothing about the staged curve
changes.

The remaining work is a live value move on the default board, so CLAUDE.md rule 4
requires verifying downstream effects across rankings, sorting, filtering, exports and
trade math before it ships.

**What wiring it needs:**
1. Route the two axes into `_compute_unified_rankings` at the existing per-source TE
   multiplier site (`data_contract.py:6849-6855`).
2. Produce a board-wide before/after TE delta artifact.
3. Update `tests/league_intel/test_te_premium_invariants.py`, whose source-text guard
   pins the current expression.

---

## Deferred, with the reason

| Finding | Why |
|---|---|
| **P** source families | Real gap. But changing confidence buckets moves a user-visible field on every player. Correct first step is measuring pairwise source correlation from CSVs already on disk — clusters should be measured, not assumed from publisher names. |
| **Q** persisted actuals | Confirmed. The right first move is persisting what is already fetched, not a database migration; a store with nothing in it enables no backtesting. |
| **A** true weekly-points utility | Blocked twice: dead projection branch (now documented) and the nflverse 2025 404. Needs Q first. |
| **E** removal-cost surplus | Sound redesign, changes a live output, wants the same before/after harness F-6 got. |
| **N** mixed-market posture | Three engines hold three defensible postures. Choosing needs a product decision, not a code fix. `finder.py`'s sum is now at least documented. |
| **R** agent orchestration | Organisational, not a code defect. |

---

## Rejected

**Finding O — KTC's VA applied to `rankDerivedValue`.**
Reported by a sub-reviewer as significant: KTC's scale-sensitive VA (`t = 10041`)
applied to the internal board at `angle.py:778`, `angle.py:1253`, `suggestions.py:690`.

*Conclusion:* call sites real, severity overstated. `rankDerivedValue` tops at 9999
against KTC's 10000/10041 — 0.4% apart — so `(value/t)^1.3` behaves almost identically.
The unvalidated part is curvature, not scale.

*Reason for rejection:* changing a formula whose inputs are within half a percent of what
it was built for trades a documented assumption for an undocumented one.

**Sub-reviewer's `server.py:9223` insecure-cookie finding.**
It is `/api/test/create-session`, double-env-gated and 404 in production. Informational.

---

## Not deployed

Nothing here has been deployed. The nginx change in particular is a production topology
change requiring:

* `grep -rn '169\.58\.50\.224'` on the repo (done — clean)
* `/var/log/nginx/access.log` checked for `Host: 169.58.50.224` (operator only)
* confirmation that no **external** monitor still probes the IP (operator only)

After this change a stray probe on any path other than `/api/health` shows up as a 301
rather than a silent cleartext success, so the failure mode is visible either way.
