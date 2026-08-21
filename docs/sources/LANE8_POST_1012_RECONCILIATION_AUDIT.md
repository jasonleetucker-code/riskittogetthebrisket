# Lane 8 — post-#1012 re-audit (V1-133/134/135, V1-23, #1001/V1-136, #983)

Owner directive: "V1 70% SPRINT" — re-audit the bridge architecture and
#1001/#983 against **current shipping main** now that #1012
(`0a5267d06`, "IDP Show: the combined Top-700 board becomes the sole
voting source") is merged. Four independent tasks, reported
independently. **No production code changed by this audit** — all
mutation proofs below were performed in an isolated git worktree
(`/tmp/main-audit`, detached at `origin/main`), confirmed RED, then
restored, confirmed via `git diff --stat` returning empty each time.
This working branch (`claude/lane8-v1-136-idpshow-audit`) itself only
gained this document plus a WORK_CLAIMS row and a PR-body correction —
no `src/` change.

---

## TASK A — V1-133 / V1-134 / V1-135 re-audit

**What #1012 actually changed, verified by reading its diff
(`git diff 62a35d2db 0a5267d06`):** `idpShowCombined` replaces `idpShow`
as the provider family's sole voting key, registered
`is_cross_market=True` + `needs_shared_market_translation=False`. It
therefore **never enters the Phase 1 bridge/translation seam
(`src/bridges/*`) at all** — it routes through the separate, pre-existing
(previously-dormant) Phase 1c `csv_rank_cross_market_keys` pre-pass,
which restores a cross-market source's own native combined-pool rank
directly. `config/bridges/bridges_v1.json` is untouched. This means
V1-133/134/135's actual subject matter — the bridge/ladder mechanism —
is **structurally unaffected** by #1012; what changes is the volume and
quality of real IDP evidence flowing around it (see Task B).

### V1-133 — Multi-bridge cross-position translation: **CLOSURE_READY**

- Production owner: `src/bridges/assess.py::assess_bridges`,
  `src/bridges/ladder.py::build_bridge_ladder`, wired at
  `src/api/data_contract.py` Phase 0 (`if True:` block, ~line 8397).
- **Mutation 1** (family dedup): disabled
  `if descriptor.family in set(claimed_families):` in
  `assess.py` → `TestOneFamilyIsOneOpinion::
  test_a_second_bridge_from_one_family_does_not_count_twice` RED.
  Restored, GREEN (18/18 `tests/bridges/test_bridge_capability.py`).
- **Live/pinned board effect**, measured against the real
  2026-08-20T23:05Z archive (`dynasty_export_20260820_230504.zip`, 1,111
  rows post-build, taken ~2h after #1012 merged, so it includes real
  `idpShowCombined` data):

  | scenario | IDP top-100 | max IDP value | votes withheld | ladder |
  |---|---|---|---|---|
  | baseline (healthy) | 7 | 5,926 | 0 | available, `idpTradeCalc` |
  | `idpTradeCalc` excluded | 10 | 5,270 | 0 | available, **`draftSharks`** takes over |
  | `idpTradeCalc` + `draftSharks` both excluded | 5 | 4,473 | 168 (`dlfIdp`) + 187 (`fantasyProsIdp`) | **unavailable** |

  No trace of #950's defect signature (661 untranslated votes / 9,999 IDP
  value / 29 IDP-in-top-100) in any scenario — the worst case (every
  declared bridge gone) correctly withholds rather than fabricates, which
  is V1-134's property measured on the same run (see below).
- Provider-family one-vote: proven by the mutation above, plus directly
  observed on the real board — `idpShowCombined`'s `correlation_group`
  is `"idpShow"`, and it is the ONLY registered member of that family
  (the old `idpShow` key is fully unregistered — confirmed absent from
  both `_RANKING_SOURCES` and `_SOURCE_CSV_PATHS`).

### V1-134 — No/unproven bridge fails closed: **CLOSURE_READY**

- **Mutation 2** (PENDING guard): disabled the
  `if descriptor.comparability == bridge_states.PENDING:` branch in
  `assess.py` → 3 tests RED (`test_pending_does_not_vote`,
  `test_a_pending_bridge_is_still_capable_and_still_refused`,
  `test_an_unusable_bridge_does_not_claim_its_family`). Restored, GREEN.
- **Mutation 3** (vote-withholding `continue`): replaced the `continue`
  at `data_contract.py:8724` (current-main line number) with a fallback
  that lets the rank vote anyway →
  `test_with_no_bridge_at_all_the_vote_is_withheld` and
  `test_no_idp_only_source_is_ever_priced_on_the_global_master` RED.
  Restored, GREEN.
- Live board (table above): with every declared bridge excluded, 355
  votes are explicitly withheld (`withheldNoBridge: {"dlfIdp": 168,
  "fantasyProsIdp": 187}`) — **never zero-fabricated, never
  untranslated-into-combined-space**. `dynastyDealer` (comparability
  `PENDING`) correctly reports `NOT_COMPARABLE` in every scenario,
  including the healthy one — it has never voted and #1012 did not
  change that.

### V1-135 — Ordinal/cardinal semantics preserved: **CLOSURE_READY**

- `_VALUE_BASED_SOURCES` (the ONLY two sources ever allowed a
  raw/site-max value-direct path) is unchanged by #1012:
  `{"ktcSfTep", "idpTradeCalc"}`. Confirmed `idpShowCombined` and
  `dlfIdp` are NOT members.
- **Mutation 4**: added `"dlfIdp"` to `_VALUE_BASED_SOURCES`. This did
  **not** trip `tests/api/test_dlf_source.py` (its assertions check
  aggregate `rankDerivedValue`, which the idpTradeCalc vote's lower
  contribution masks) — a real test-sensitivity gap worth naming, but
  **it was caught**: `tests/api/test_curve_routing_coordinate_pool.py`'s
  `TestFixtureIsCapableOfDetectingTheDefect`,
  `TestSameCoordinatePoolPricesIdentically`, and
  `TestTranslatedIdpRankUsesSharedMarketCurve` all went RED (60
  mispriced rows reported, e.g. "Idp Vet 001/dlfIdp: rank 2 → 9999"
  — the exact historical defect signature). Restored, GREEN
  (17/17). Direct inspection under the live mutation confirmed the
  mechanism precisely: `dlfIdp`'s `effectiveRank` was correctly
  translated (11), but `valueContributionPath` became `"value_direct"`
  and `valueContribution` became exactly `9999` — rank masquerading as
  vendor value at the per-source level, invisible in the blended
  aggregate but caught by the dedicated curve-routing test file.
- **One honest residual note, not a blocker**: the guard is a hardcoded
  Python frozenset with test coverage, not a registry-level structural
  impossibility (e.g. no `is_cardinal` registry flag cross-checked
  against `needs_shared_market_translation`/`is_cross_market` at import
  time). A future edit CAN still make this mistake; it just won't ship
  silently, because the curve-routing test file catches it. Recorded as
  a low-priority hardening opportunity, not a REMAINING_GAP for V1-135
  itself — the property holds today and is test-enforced.

---

## TASK B — V1-23 support: does W02-F001/F002 still reproduce post-#1012?

Measured directly against the same real 2026-08-20T23:05Z archive
(1,111 rows, 398 IDP rows).

### W02-F001 (IDP-only sources scored on the wrong curve/scope master): **does not reproduce — fixed, unrelated to #1012**

`_curve_for_rank` routes on the row's stamped `rankCoordinatePool`
(`"shared_market"` → the GLOBAL Hill master via `curve_for_pool`), not
on the source's own declared scope. A translated IDP specialist's rank
is stamped `rankCoordinatePool: "shared_market"` during Phase 1
translation, so it is priced on the same curve as every other
shared-market row — confirmed structurally and by the same
`TestTranslatedIdpRankUsesSharedMarketCurve` mutation-proof used in
Task A. This fix predates #1012 and #1012 does not touch it.

### W02-F002 (Hampel filter ejects `idpTradeCalc` as HIGH outlier): **NOT structurally fixed — but its reproduction rate collapsed from #1012, and that distinction matters**

The documented historical baseline (`FEATURE_STATUS_MATRIX.md`) was
**29.4%** of Hampel-eligible IDP rows, **52 of 52** in the HIGH
direction. Measured fresh on the current real board:

| metric | value |
|---|---|
| IDP rows | 398 |
| Hampel-eligible | 398 |
| `idpTradeCalc` ejected | **2 (0.5%)** |
| direction of both ejections | HIGH (same direction as the historical defect) |
| median # sources voting per IDP row | **3.5** (range 0–6) |

`_hampel_filter_per_player` itself is **unchanged** — a plain
median/MAD filter with **no anchor-awareness**, exactly as documented.
The 29.4%→0.5% collapse is **not** because anyone fixed the filter; it
is because `idpShowCombined` added a genuine 5th independent
cross-market-adjacent vote to most IDP rows (a real board row now
typically carries `idpTradeCalc, dlfIdp, idpShowCombined,
fantasyProsIdp, draftSharksIdp` — 5 sources instead of a much smaller
set), which gives the median/MAD statistic a far more stable,
`idpTradeCalc`-agreeing population to compute over. **Do not report
this as "W02-F002 fixed."** The two residual cases (Byron Young, Nick
Herbig) are the tell: in both, `idpTradeCalc` is still ejected for being
unusually bullish relative to the other 4 sources' consensus — the
identical failure mode, just now rare because it takes real
disagreement from 4+ other sources simultaneously rather than 1–2 to
trigger it. **The remaining defect for Claude 5:** the Hampel filter
still has no concept of "this source is the designated cross-market
anchor and should not be ejected on symmetric grounds" — that repair
(if ever authorized) is still not done; #1012 only diluted its
probability of firing.

### Is IDP source translation now coherent?

Yes, per Task A. `idpShowCombined` bypasses translation entirely (its
own rank already lives in shared-market coordinates); `dlfIdp` and
`fantasyProsIdp` still translate through the `idpTradeCalc`/`draftSharks`
bridge exactly as before, confirmed unaffected.

### Does any old IDP-only source still enter the shared market incorrectly?

No. `idpShow` (the old key) is confirmed fully unregistered — absent
from `_RANKING_SOURCES` and `_SOURCE_CSV_PATHS`. The only surviving
references to the string `"idpShow"` are (a) a diagnostic-only freshness
budget (`_SOURCE_MAX_AGE_HOURS["idpShow"] = 24`, tracked because the
plain board is still fetched, never read for voting) and (b) the
`correlation_group: "idpShow"` label on `idpShowCombined`'s own entry
(the family name, not a second voting key). Neither can vote.

---

## TASK C — #1001 / V1-136 audit against post-#1012 reality

**Finding, severity: material.** #1001's branch
(`claude/lane8-v1-136-idpshow-audit`) merged `origin/main` at
`44f6bb750`, which was **before PR #1008** (the "widest chart" /
`--combined` flag work) landed, let alone #1012. Slice 3 (the
failure-state instrumentation, commit `136340964`) was then written
against that stale copy of `scripts/fetch_idpshow.py`. Confirmed by
diff (`git diff origin/main claude/lane8-v1-136-idpshow-audit --
scripts/fetch_idpshow.py`): **my branch's copy of this file has zero
mentions of "combined" anywhere** — `_extract_all_chart_ids`,
`_pick_widest_chart`, `COMBINED_ARTICLE_URL`, `COMBINED_OUT_PATH`, the
`--combined` CLI flag, the tab-delimiter sniffing, and the
`Name`/`Rank`/`Position` header aliases for the combined board's schema
are **all absent from my branch** relative to current main.

**This is the one real (class-B, code-level) conflict** — every other
file #1001 touches (`docs/sources/*.md`, `tests/api/test_dlf_source.py`,
`tests/sources/test_idpshow_acquisition_state.py`, `docs/WORK_CLAIMS.md`)
has zero overlap with #1012's file list. `deploy/idpshow_fetch_and_push.sh`
was changed by #1012 but never touched by #1001 at all — no conflict, no
action needed there.

### Exact stale assumptions, and exact reconciliation instructions for Claude 5

1. **Old idpShow key.** #1001's Slice 1 audit and Slice 3's framing both
   describe `idpShow.csv`'s acquisition as V1-136's open question. That
   framing is now incomplete: #1012 made "which board votes" a **settled
   owner decision** (`idpShowCombined`, permanently), not a pending one.
   The plain board's continued fetch is now diagnostic-only, same
   posture as `draftSharksRosSf.csv`. **Reconciliation:** reword Slice
   1's "no new wiring needed" framing to note the vote question is now
   closed by #1012, and that Slice 3's instrumentation target should
   shift priority (next point).

2. **Combined board — the actual conflict.** Reconcile
   `scripts/fetch_idpshow.py` starting from **current main's copy**
   (which has the `--combined` machinery), not from #1001's branch.
   Re-apply Slice 3's instrumentation pattern (`_persist_outcome`,
   `AcquisitionOutcome` construction, `_now`/`_rel` helpers) onto BOTH
   `main()`'s return points: the plain-board path (already covered by
   #1001's diff, mechanically reapplies cleanly) **and** the
   `--combined` branch's return points, which #1001 has never seen and
   currently has ZERO outcome-instrumentation on either branch — main's
   own `--combined` row-floor check today is a bare
   `print(...); return 2` with no `AcquisitionOutcome` at all. Closing
   this is now the higher-priority half of V1-136, since
   `idpShowCombined` is the board that actually votes.

3. **Status path.** #1001's `STATUS_PATH =
   data/scrape_state/idpShow_last_status.json` and `SOURCE_KEY =
   "idpShow"` are singular, but `deploy/idpshow_fetch_and_push.sh` (per
   #1012) now invokes the fetcher **twice** — plain, then `--combined` —
   as two separate process runs. Two invocations writing the same status
   file means the second silently overwrites the first's outcome.
   **Reconciliation:** make `STATUS_PATH`/`SOURCE_KEY` board-aware,
   derived from the parsed `--combined` flag at the top of `main()` —
   mirroring the existing `idpShow_last_success` /
   `idpShowCombined_last_success` split `deploy/idpshow_fetch_and_push.sh`
   already uses for its freshness stamps. Two files:
   `idpShow_last_status.json` (plain/diagnostic) and
   `idpShowCombined_last_status.json` (voting board).

4. **Acquisition row floor.** Main's `_IDPSHOW_COMBINED_ROW_FLOOR = 450`
   (inside the `--combined` branch) has no counterpart in #1001's
   instrumentation, since that branch didn't exist in #1001's copy.
   **Reconciliation:** wrap that check's failure with
   `AcquisitionOutcome(state=SCHEMA_CHANGED, reason="row_count_below_floor", ...)`
   the same way #1001 already did for the plain board's own floor
   (`_IDPSHOW_ROW_FLOOR = 150`).

5. **Family semantics.** No correction needed beyond point 1 — there is
   exactly one registered voting member of the `idpShow` correlation
   group (`idpShowCombined`), consistent with the one-family-one-vote
   invariant #1001's own audit already checked for.

**#1001's own tests** (`tests/sources/test_idpshow_acquisition_state.py`,
20 tests) currently cover only the plain-board path (the one that no
longer votes). Once the `--combined` path's instrumentation is added per
point 2, that test file needs a parallel or parametrized pass covering
`main(["--combined"])`'s outcome states, especially the newly-instrumented
`SCHEMA_CHANGED`/`row_count_below_floor` case above, which is untested by
anyone today (neither #1001 nor #1012's own merge added a test for it).

**Not rebased here, per instruction.** This document is the reconciliation
map; the actual merge/rebase of `scripts/fetch_idpshow.py` is left to
Claude 5, since it requires deciding how to compose two independently-
written change sets against the same function bodies, not a mechanical
`git merge`.

---

## TASK D — #983 permanent invariant, post-#1012 test reconciliation

Fetched `#983`'s branch (`claude/v1-pending-does-not-vote`, still at
`41b9fb886`, unchanged) and overlaid its two new test files onto the
current-main worktree to measure directly (no branch of my own was
modified; #983 is a different lane's PR per `docs/WORK_CLAIMS.md`
convention).

**Good news: `test_bridge_consumer_boundary.py` is already reconciled
for PR B (#993).** Its `TestExactlyOneApprovedBridgeConsumer` class was
already rewritten (evidently by whoever built #983, or a prior
reconciliation pass) to assert the settled post-#993 invariant —
"exactly one approved consumer, `src/api/data_contract.py`, importing
only `assess_bridges` / `QUALIFIED` / `build_bridge_ladder` /
`load_bridge_descriptors` / `AcquisitionOutcome` / `UNAVAILABLE`" —
rather than the pre-#993 "zero consumers" tripwire its own docstring
says used to be the assertion. Ran clean: 26/27 passed (see next
finding for the one failure), confirming this file needs **no further
change for #1012** — #1012 does not touch `src/bridges/*` or add a
second bridge consumer, so the census is unaffected.

**One real, PRE-EXISTING failure found, unrelated to #1012 — isolated
by direct comparison.** `test_disabled_source_does_not_vote.py::
TestDisabledSourceMagnitudeIsInvisible::
test_several_disabled_sources_simultaneously_extreme` fails **identically**
on a worktree pinned to the commit immediately before #1012
(`62a35d2db`) and on current main (`0a5267d06`) — same assertion, same
diff shape (`"available": true` vs `"available": false` in the
`crossPositionBridges.ladder` block). This is **not** a #1012
regression and **not** part of the reconciliation Task D asked for; it
predates #1012 entirely. Recorded here because it lives inside #983's
own test suite and will block its CI regardless of #1012, but it is a
**separate, pre-existing defect** for #983's owner or Claude 5 to triage
on its own terms — disabling a source via `source_overrides={"include":
False}` does not appear to make that source's row-level
`canonicalSiteValues` fully invisible to bridge-capability measurement
in every combination tested, specifically when TWO sources are disabled
and BOTH carry injected extreme values simultaneously. Single-source
extreme-value cases in the same test file all pass; only the
"disable + extreme two sources at once" case fails.

### Post-#1012 test reconciliation Claude 5 needs (Task D's actual ask)

**None, beyond confirming the above.** #1012 does not add a second
bridge consumer, does not touch `src/bridges/*`, and does not change
`config/bridges/bridges_v1.json`. `idpShowCombined`'s new registry shape
(`is_cross_market=True`, `needs_shared_market_translation=False`) routes
around the bridge layer entirely (Task A), so it cannot become a second
consumer or a second bridge by construction — there is nothing in
`_APPROVED_CONSUMERS` or the bridge registry that needs updating for
#1012. The permanent invariant list stands exactly as stated in the
directive: exactly one approved canonical bridge consumer, no second
consumer, PENDING no vote, ORDINAL not CARDINAL, no valid bridge ⇒
specialist withheld, family dedup, missing != zero — every clause is
independently mutation-proved in Task A above, on current shipping main,
today.

**No `multi_bridge_ladder` activation performed or requested.** Flag
remains OFF, matching every prior instruction on this program.

**FREEZE.**
