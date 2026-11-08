# CW-40 P1 re-adjudication, BATCH M1 (value pipeline / sources / scoring identity)

Fresh adjudication of 17 master-site-audit P1 findings the 2026-11-06 recount could not adjudicate
(`master_audit_recount.json` ran each August repro and never compared its output to the claim), against `main`
at `17d8bd7290` (2026-11-07). Same method as `CW40_P0_ADJUDICATION.md`, `CW40_P1_OPEN_ADJUDICATION.md` and
`CW40_P1_UNADJUDICATED.md`: offline and deterministic only. The board is built by the real
`build_api_data_contract` from the PINNED tracked archive `exports/archive/dynasty_export_20261106_194518.zip`
(never `exports/latest`, never a live board); scoring/identity checks use the committed fixtures under
`docs/master-site-audit/evidence/`; everything else is a pure function on synthetic inputs or a source-shape scan.
All new tests live in `tests/api/test_audit_cw40_batch_m1_regression.py` (32 pass, 6 strict xfail).
Nothing here changes served behaviour, values, thresholds or methodology; no source file is edited; CLAUDE.md is
not edited.

| id | verdict | evidence (current file:line) | test | smallest repair / gate |
|---|---|---|---|---|
| W02-F001 | CLOSED_VERIFIED | `data_contract.py:12173` `_curve_for_rank` routes by the stamped `rankCoordinatePool`; `canonical/rank_coordinates.py:115,138` | `test_w02_f001_*` (2) + `tests/api/test_curve_routing_coordinate_pool.py` | none |
| W02-F002 | CLOSED_VERIFIED | consequence of F001; `idpTradeCalc` ejected on 0 of 222 Hampel-eligible IDP rows on the pinned board (was 52/177) | `test_w02_f002_*` + `test_hampel_filter.py::TestLiveBoardIdpAnchorEjectionRate` | none |
| W02-F003 | CLOSED_VERIFIED | clamp deleted (no symbol in `data_contract.py`); replaced by `_detect_blend_integrity_violations` (`:7611`), flag in `_QUARANTINE_FLAGS` (`:382`) | `test_w02_f003_*` (3) + `test_blend_integrity.py::TestTheCorridorIsGone` | none |
| W03-F004 | CLOSED_VERIFIED | `confidence.py:265` `assess_confidence` (overall = weakest of 5 axes); 890/890 pinned-board rows satisfy it | `test_w03_f004_*` (2) + `test_confidence_gate_oracle.py::test_losing_a_family_to_withheld_never_raises_anything` | none |
| W05-F001 | CLOSED_VERIFIED | `server.py:2173,2471` publish `registered_sources` + registry-keyed `source_counts`; `SourceHealthStrip.jsx:208-216` prefers them | `test_w05_f001_*` (2) + `test_source_health_population.py`, `source-health-strip.test.jsx` | none |
| W05-F003 | PARTIAL | header probe still 4 sources (`data_contract.py:5707`); header-only CSV `if not csv_lookup: continue` (`:6125`); zero rows now a hard `source_missing` for every registry key (`:17674-17725`) | 2 control passes + 2 strict xfail | extend probe to every source; emit `source_empty:<key>`; gate: contract-health lane change, no valuation effect |
| W05-F004 | PARTIAL | ktcSfTep floor 400 (`data_contract.py:1447`); zero-check covers all 27 registry keys; 9 of 27 still have no thin floor | `test_w05_f004_*` (1 pass, 1 strict xfail) | add 9 floors at ~80% of observed baselines; gate: owner/evidence (new `source_below_floor` warnings, can flip `degraded`) |
| W05-F006 | PARTIAL | KTC Crowd/Trades now vote on 36 generic picks; 72 slot picks are `rookie_pool_tether`; picks still have 2 providers; stale `dlfRookieSf` comment `data_contract.py:2233` | `test_w05_f006_*` (2 pass, 1 strict xfail) | correct the comment (doc-only); wider pick voting is source-voting methodology, owner-gated |
| W12-F008 | CLOSED_VERIFIED | `_compute_market_gap` (`data_contract.py:4764`) = model vs KTC Market (`sources/ktc_market.py:123`); source-vs-source retail/expert split deleted | `test_w12_f008_*` (2) + `test_market_gap_independence.py` | none |
| W13-F001 | PARTIAL | realized path scores bands via PBP supplement (`realized_points.py:735-760,984`; `bdvm/baseline.py:125-130`; `scripts/bdvm_build_baseline.py:123-137`); projected lines still score none (disclosed in `unscored`) | `test_w13_f001_*` (3 pass, 1 strict xfail) | measured per-player reception-depth shape; gate: value-moving, owner-gated |
| W18-F001 | CLOSED_VERIFIED | `league_registry.py:776,830`, `server.py:2975,3038`, `sleeper_scoring.py:114` | `test_w18_f001_*` (3) + `test_scoring_compatibility.py` | none |
| W18-F002 | CLOSED_VERIFIED | `sleeper_overlay.py:1564` `merge_cross_league_sleeper_block`; `server.py:5348-5372` | `test_w18_f002_*` (2) + `test_cross_league_overlay_coherence.py` | none |
| W18-F003 | PARTIAL | three original defects closed (renamed columns, bands via PBP, kickers); residual host disagreement is the DD-11 / #1938 IDP set | `test_w18_f003_*` (2) | none from this batch; #1938 stays owner-reserved |
| W21-F001 | OPEN | `injury_impact.py:302-336` + `terminal.py:1662-1680`: one item's severity still multiplies `rankDerivedValue` | 1 control pass + 1 strict xfail | delete `injuryAdjustedValue` or route via BDVM module inputs; owner methodology |
| W29-F001 | CLOSED_VERIFIED | `offenseOnlyRankDerivedValue` absent from every row and from `src/`; `suggestions.py:236,2358` | `test_w29_f001_*` (2) + `test_one_canonical_value_per_asset.py` | none |
| W29-F002 | CLOSED_VERIFIED | lens withdrawn, `server.py:6101-6116`; `apply_valuation_factors` deleted | `test_w29_f002_*` + `test_canonical_value_invariance.py`, `test_valuation_mode_threading.py` | none |

Tally (16 findings plus the W02 family note, which is one proof rather than a finding): 10 CLOSED_VERIFIED,
5 PARTIAL, 1 OPEN (W21-F001), 0 UNVERIFIABLE, 0 standalone REQUIRES_OWNER_DECISION (the PARTIAL and OPEN repairs
are owner/evidence-gated as stated per row).

## W02-F001 (IDP-only sources priced on the IDP-slice Hill master) - CLOSED_VERIFIED

**Claim.** `needs_shared_market_translation` rewrote an IDP-only source's rank into combined-pool coordinates,
but `_curve_for_source` routed it to the IDP master fit on idpTradeCalc's IDP-only slice, so it voted about 48%
of the anchor's value at the identical effective rank.

**Live path now.** `data_contract.py:12150-12184`: the curve is chosen from the pool the rank actually lives in
(`rankCoordinatePool`, stamped by whichever Phase-1 pass established the effective rank), with the source's
declared native pool only as the no-stamp fallback. The percentile denominator is the one fixed reference N
(`:12186`). Owner: `src/canonical/rank_coordinates.py`.

**Evidence.** Pinned board, every IDP `rank_hill` source against `idpTradeCalc` on the same row: median
contribution ratio 1.30 (idpShowCombined), 1.15 (fantasyProsIdp), 1.24 (draftSharksIdp), against the defective
0.46-0.49. Every `sharedMarketTranslated` rank carries `rankCoordinatePool == "shared_market"`.

**Tests.** New `test_w02_f001_translated_idp_votes_sit_near_the_anchor_not_at_half_of_it` and
`..._every_translated_rank_is_stamped_with_the_shared_market_pool`; existing and still green:
`tests/api/test_curve_routing_coordinate_pool.py` (17 tests, synthetic through `build_api_data_contract`).

## W02-F002 (Hampel ejects the IDP market anchor) - CLOSED_VERIFIED

**Claim.** `idpTradeCalc` was Hampel-dropped on 29.4% of eligible IDP rows, 52 of 52 for being HIGH.

**Live path now.** `_hampel_filter_per_player` (`data_contract.py:10995`) is unchanged in kind. The August
rate was the symptom of W02-F001 (three mispriced translated votes dragged the median so the correct anchor read
as the outlier); the REBASELINE note recorded it resolved as a consequence.

**Evidence.** Pinned board: 0 of 222 Hampel-eligible IDP rows eject `idpTradeCalc`.

**Tests.** New `test_w02_f002_idp_anchor_is_not_ejected_at_scale` (pinned archive, deterministic). The existing
`test_hampel_filter.py::TestLiveBoardIdpAnchorEjectionRate` asserts the same bar but reads `exports/latest`, which
the 2-hourly refresh rewrites, so it was not relied on here.

## W02-F003 (corridor clamp) - CLOSED_VERIFIED, deleted, protected invariant pinned

**Claim.** The per-bucket P90 machinery was inert (0.15 cap bound on 100% of clamps) and rewrote 43.3% of ranked
IDP rows to exactly idpTradeCalc x 0.85 or x 1.15.

**Deletion proved.** `_apply_market_corridor_clamp`, `_market_anchor_for_row`, `_MARKET_ANCHOR_BY_ASSET_CLASS`,
`_MARKET_CORRIDOR_PERCENTILE`, `_MARKET_CORRIDOR_MIN_BUCKET_N` and
`_MARKET_CORRIDOR_MAX_BAND_BY_ASSET_CLASS` have no attribute on `data_contract`; `grep` over `src/` and
`server.py` finds no `_MARKET_CORRIDOR` or `_apply_market_corridor_clamp` reference. On the pinned board 0 of 377
IDP rows sit within 1 of anchor x 0.85 or x 1.15.

**Invariant it protected, and where it is pinned now.** The clamp's purpose was "a published value must not leave
the range its own sources justify". That is now `_detect_blend_integrity_violations` (`data_contract.py:7611`):
detection only, no coercion, flag `blend_integrity_violation` in `_QUARANTINE_FLAGS` (`:382`) so the row is
quarantined and confidence degrades, plus a hard build-level validator error. Pinned board: 0 rows flagged.

**Tests.** New `test_w02_f003_corridor_machinery_is_gone_from_the_module`,
`..._no_idp_row_is_snapped_to_anchor_times_085_or_115`, `..._the_protected_invariant_is_the_blend_hull_and_it_is_enforced`;
existing `tests/api/test_blend_integrity.py` (`TestTheCorridorIsGone`, `TestTheInvariantDetectsImpossibility`,
`TestTheViolationActuallyAbstains`).

## W03-F004 (confidenceBucket rises when sources disappear) - CLOSED_VERIFIED

**Claim.** Source count entered only as a >=2 gate; the label was a pure function of the percentile spread,
computed only over sources that ranked the player, so deleting a source usually narrowed it and raised the
label on 237 of 679 rows.

**Live path now.** `src/api/confidence.py:265` `assess_confidence`: five axes over B10 provider FAMILIES
(independence, coverage, freshness, applicability, agreement); overall is the weakest axis; coverage's denominator
is what could have been observed, so a lost family stays eligible (CW-47: withheld evidence is seated in every
share denominator and credited nothing). `sourceRankPercentileSpread` is still published but does not decide.

**Evidence.** Pinned board: 890 of 890 non-pick rows with a full axis map satisfy bucket == weakest axis; the
function body names neither `sourceRankPercentileSpread` nor a percentile-spread local.

**Tests.** New `test_w03_f004_*` (2). Existing, read and relied on: `tests/api/test_confidence_gate.py`
(`test_case_d_removing_the_outlier_does_not_promote_confidence`, `TestMonotonicity`) and
`tests/api/test_confidence_gate_oracle.py` (`test_losing_a_family_to_withheld_never_raises_anything`,
`test_deleting_a_family_never_raises_count_axes_or_when_it_was_good`; seeded sweeps of the August replay).

## W05-F001 (/tools/source-health lists 4 of 21; IDPTC renders 0) - CLOSED_VERIFIED

**Claim.** Rows came from the scraper's four run names; the count lookup was case-mismatched so IDPTradeCalc
rendered 0 rows; the 22-entry per-source freshness map was fetched and unused.

**Live path now.** `server.py:2173` `_build_source_health_snapshot` publishes `registered_sources` (the registry,
27 keys today) and `source_counts` keyed by registry key (`:2267-2286`, `:2471-2484`), with unknown vs zero kept
apart (`unmeasured_sources`). `SourceHealthStrip.jsx:208-216` takes rows from `registered_sources`, preferring it
to `runtime.enabled_sources`; per-row age reads `health.sources` (`:226-250`), so `idpTradeCalc` is looked up under
its own key.

**Tests.** New `test_w05_f001_idptradecalc_count_is_looked_up_under_its_registry_key` (synthetic coverage map: 911
rows read back as 911) and `..._page_rows_come_from_registered_sources_not_scraper_run_names`; existing
`tests/api/test_source_health_population.py` and `frontend/__tests__/components/source-health-strip.test.jsx`
(population cases).

## W05-F003 (zero-row / renamed-header CSV is silent) - CLOSED 2026-11-08

Closed by the universal probe + `source_empty` / `no_usable_rows` / `schema_mismatch` named errors (`source_ingest_failure:` source-health kind); see `docs/sources/SOURCE_ROW_FLOORS.md`. The historical analysis below is retained.

**Claim.** Only file-missing appends a parse error; a header-only CSV and a vendor header rename on 18 of 22
sources vanish with `sourceParseErrors == []`.

**Still true.** The schema probe is hard-coded to `dlfSf`, `dlfIdp`, `fantasyProsIdp`, `fantasyProsSf`
(`data_contract.py:5707`); a renamed header on `ktcSfTep` or `idpTradeCalc` falls through and returns an empty
lookup with no error; a header-only CSV hits `if not csv_lookup: continue` (`:6125`).

**What changed.** The consequence is no longer invisible. Zero rows on the BUILT board is now a hard
`source_missing:<key>` error for every registered source (`:17674-17725`, audit F-15, pinned by
`tests/api/test_registered_voter_zero_check.py`), so a source that silently vanished fails the full lane. What is
still missing is the earlier, more specific signal (`schema_mismatch` / `source_empty` in `sourceParseErrors`) and
partial-schema drift that leaves some rows parsing.

**Tests.** Controls that pass: renamed header on `dlfSf` -> `schema_mismatch`; missing file -> `file_not_found`;
`source_missing` population is the registry. Strict xfail: renamed header on `ktcSfTep` reports nothing; header-only
`ktcSfTep` reports nothing (`tmp_path` CSVs through the real `_enrich_from_source_csvs`).

**Smallest repair / gate.** Make the probe universal (at least one name-alias column and one rank/value-alias
column per source) and emit `source_empty:<key>` for a cleanly parsed zero-row CSV, both as additive
`sourceParseErrors` entries. Pure ingestion-health change, no value effect; gate is the existing structural lane
(a warning, so a structural lane remains green).

## W05-F004 (sources with no row-count floor) - CLOSED 2026-11-08

Closed: all nine floors added from git-history evidence (`scripts/derive_source_row_floors.py`, `docs/sources/SOURCE_ROW_FLOORS.md`). The historical analysis below is retained.

**Claim.** 9 of 21 registered sources had no floor; deleting `ktcSfTep` left `contractHealth` healthy.

**Closed.** `ktcSfTep` has a floor of 400 (`data_contract.py:1447`) and, independent of any floor, every
registered key is zero-checked (`:17674`, F-10 / F-15); the August "delete the retail anchor, stay healthy" repro is
pinned by `tests/api/test_retail_anchor_row_floor.py`.

**Still true.** The registry is now 27 keys and 9 declare no THIN floor: `dlfRookieIdp`, `dlfRookieSf`,
`dlfValuesSfTep`, `fantasyCalc`, `fantasyNavigatorSf`, `fantasyProsSf`, `flockFantasySfRookies`, `otcffbSf`,
`pfkDynasty`. For them `source_below_floor` can never fire; only total loss is caught.

**Tests.** `test_w05_f004_retail_anchor_now_has_a_floor_and_zero_is_a_hard_error` (pass);
`test_w05_f004_every_registered_source_declares_a_thin_floor` (strict xfail naming the 9).

**Smallest repair / gate.** Add the nine floors at about 80% of an observed baseline (config-only,
`config/weights/source_row_floors.json`). New floors can add `source_below_floor` warnings and, at two or more, flip
`degraded`, so the numbers are an evidence/owner call, not a drive-by.

## W05-F006 (only 2 of 21 sources vote on picks; slot picks single-source) - PARTIAL

**Claim.** `ktcSfTep` voted on 36 generic tier picks, `idpTradeCalc` on 96, nothing else; all 72 slot picks were
`sourceCount == 1` anchored on IDPTC although a KTC value sat in `canonicalSiteValues`; `dlfRookieSf` pick stamps
were written and never read.

**Closed.** Pinned board: `ktcCrowdSfTep` and `ktcTradesSfTep` now vote on the 36 generic tier picks beside
`idpTradeCalc` (both KTC inputs and IDPTC; nothing else votes). All 72 current-year slot picks are
`pickValueProvenance.class == "rookie_pool_tether"`, i.e. they inherit the merged rookie pool by owner design
(Phase 5.2b), not a single vendor's number.

**Still true.** Pick voting is exactly two PROVIDERS (KTC, IDPTC), a documented posture (CLAUDE.md "Confidence"
section, owner directive 2026-10-07). `dlfRookieSf` writes a synthetic `Pick R.SS` stamp onto 61 pick rows'
`canonicalSiteValues` while appearing in no pick row's `sourceRankMeta`, and the registry comment
(`data_contract.py:2233-2235`) still says that value "flows into pick rankDerivedValue directly".

**Tests.** Passes: slot picks tethered; KTC votes on picks and the voter set is exactly the two providers. Strict
xfail: the `dlfRookieSf` pick stamp is either a vote or no longer claimed.

**Smallest repair / gate.** Correcting the stale comment (or dropping the dead write) is doc/dead-code only.
Adding more pick voters is source-voting methodology and stays owner/evidence-gated.

## W12-F008 (KTC on both sides of "KTC vs expert consensus") - CLOSED_VERIFIED

**Claim.** `_compute_market_gap` averaged KTC-derived `fantasyNavigatorSf` into the expert mean and treated
`idpTradeCalc` as an expert while calling it the retail IDP authority elsewhere.

**Live path now.** The source-vs-source split is gone. `_compute_market_gap` (`data_contract.py:4764`) delegates to
`src/sources/ktc_market.py:123`: our model value (`rankDerivedValue`) against canonical KTC Market, value space
(owner directive 2026-09-23). The frontend reads the stamped `marketGapDirection` / `marketGapValueRatio`
(`display-helpers.js:100-133`); the IDP comparison survives only as the explicitly named "IDPTC vs IDP experts"
alternate (`idpMarketEdge`). `_retail_source_keys()` (`:3617`) is exactly the two KTC inputs.

**Residual, by owner design, not a defect here.** The model value includes KTC Crowd/Trades votes and is then
compared to KTC Market; the owner ruled that definition and `docs/sources/` records the disclosure.

**Tests.** New `test_w12_f008_market_gap_is_model_vs_ktc_market_not_source_vs_source` and
`..._fantasy_navigator_and_idptc_cannot_move_the_market_side`; existing
`tests/api/test_market_gap_independence.py`.

## W13-F001 (BDVM "exact league scoring" drops six reception-yardage-band rules) - PARTIAL

**Claim.** `realized_points.py`, the only scorer the baseline used, read none of `rec_0_4` ... `rec_40p`
(0.17-1.92 per catch on the live card) and emitted no diagnostic; WR fundamentals understated 19.7%, TE 22.0%.

**Closed (realized/baseline lane).** Nflverse weekly rows cannot carry the bands, so a play-by-play supplement
(`pbp_weekly.py`, attached under `PBP_SUPPLEMENT_ROW_KEY`, allow-listed at `realized_points.py:735-760`, merged at
`:984`) supplies them and the canonical dot product scores them. BDVM's baseline (`bdvm/baseline.py:125-130`),
actuals (`bdvm/actuals.py:128`) and `scripts/bdvm_build_baseline.py:123-137` attach it. A row without the
supplement now REPORTS the six rules as `unscored` rather than dropping them. Whether the production box has the
play-by-play artifact built is not checkable offline (UNVERIFIABLE here).

**Still true (projection lane).** A projected stat line (Clay / IDP Show / manual CSV) scores none of the six;
`scoring_census.py:146-151` classes them unsupported vocabulary and
`bdvm/scoring.py` returns them in `PerGameScore.unscored` (disclosed, not hidden). Replacing that with a measured
per-player reception-depth shape is explicitly "a separate, value-moving unit" (`synthetic_splits.py` docstring).

**Tests.** Passes: live card still pays all six; supplement attached -> +4.50 points (`0.17 + 0.42 + 2x0.67 + 0.92
+ 1.92`); without it the six are in `unscored`; projection path discloses them. Strict xfail: a projected WR line
scores them.

**Smallest repair / gate.** Fit a per-player reception-depth shape from play-by-play and apply it to projected
receptions. Changes BDVM fundamental values (not `rankDerivedValue`), so it needs the owner's methodology and
blast-radius gates.

## W18-F001 (scoringProfile label decides cross-league compatibility) - CLOSED_VERIFIED

**Claim.** Both leagues carry `superflex_tep15_ppr1` while their host cards differ on 35 of 48 shared keys, so
`/api/data?leagueKey=dynasty_new` served dynasty_main's board.

**Live path now.** Compatibility is `league_registry.leagues_share_scoring` (`:830`) over
`scoring_fingerprint_for_league` (`:776`) -> `sleeper_scoring.scoring_fingerprint` (`:114`, `None` rather than a
hash of `{}` when there is no card), gated in `server.py::_scoring_identity_error` (`:3038`) against the contract's
own `meta.scoringFingerprint` (`_contract_scoring_fingerprint`, `:2975`). Merged B6, PR #810.

**Evidence.** Committed fixtures: the registry still hands both leagues the same label; the two real cards produce
different fingerprints and differ on at least 30 shared keys.

**Tests.** New `test_w18_f001_*` (3); existing `tests/api/test_scoring_compatibility.py` (label-equal /
scoring-different must not share, stale and wrong-season snapshots prove nothing, stamp must agree with card).

## W18-F002 (cross-league overlay stamps sleeperDataReady on a chimera) - CLOSED_VERIFIED

**Claim.** `server.py` carried the loaded league's scoring, roster positions and settings forward under the
requested league's teams and set `sleeperDataReady = True` unconditionally.

**Live path now.** `sleeper_overlay.merge_cross_league_sleeper_block` (`:1564`) is the one owner; readiness is
`league_config_is_complete` (`:1483`) of the REQUESTED league's own config; league-specific fields are absent, not
inherited, when it is missing. `server.py:5348-5372` stamps `bool(sleeper_matches or cross_league_ready)`.

**Tests.** New `test_w18_f002_chimera_cannot_be_published_ready` and `..._the_server_stamps_readiness_from_the_merge_result`;
existing `tests/api/test_cross_league_overlay_coherence.py` (including the complete-config definition).

## W18-F003 (realized_points disagrees with the host on 36% of player-weeks) - PARTIAL

**Claim.** The scorer never read the six reception-distance rules, mapped `pass_int` / `pass_sack` / `fum_lost` to
nflverse columns that no longer exist, and had no kicker scoring.

**Closed.** `_SIMPLE_KEYS` now tries the live column first (`passing_interceptions`, `sacks_suffered`,
`fumbles_lost_total`); the bands arrive through the play-by-play supplement (see W13-F001); kicker rules score
(`fgm_yds`, `xpm`, banded `fgm_*`). Pinned by new `test_w18_f003_*` and, deeper,
`tests/nfl_data/test_realized_points_host_truth.py` (host-arithmetic tests on committed 2025 fixtures; 63 pass with
`test_individual_special_teams.py`).

**Residual, a different defect set.** The CW-08 parity census (#2069; `DECISIONS.md` DD-11) measured the
nflverse path on `main` at 91.8% (3,743 of 4,077 player-weeks, 2026 weeks 1-8) against Sleeper-awarded points, and
96.4% with PR #1938's `realized_points.py` (IDP scorer defects 01-03 and a special-teams tackle double pay).
Those are not the three original claims, #1938 is owner-reserved (DD-11 recommends promotion after a blast-radius
measurement), and this batch neither merges nor touches it. The 36% figure is therefore stale; the live gap is about
8% of player-weeks and owned by #1938.

## W21-F001 (contract-extension headline multiplies Bijan's value by 0.9616) - OPEN

**Claim.** `apply_injury_impact` goes headline -> keyword severity -> base % x position x age x decay and writes
`adjustedValue = rankDerivedValue x adjustedPct`, with no structured claim, source quality, corroboration or
module input.

**Still true.** The mechanism is unchanged: `injury_impact.py:302-336` still returns `adjustedValue =
round(base_value x adjustedPct / 100)` from the single worst item, and `terminal.py:1662-1680` still stamps
`injuryImpact` / `injuryAdjustedValue` onto roster signals, rendered by `InjuryChip` (`BuySellHold.jsx`,
`PlayerPopup.jsx:935`). The recorded August item (`docs/master-site-audit/evidence/W21/api-news.json`,
`cbs-0e03f499b141`, severity alert / kind injury / impact negative) still takes Bijan from 9706 to 9333 offline.

**What improved.** The classifier half moved: `news/providers/_rss.py::classify` now labels that exact headline
`('watch', 'transaction', 'positive')`, and `compute_injury_discount` skips positive-impact items, so a FRESHLY
ingested copy would no longer be discounted. That fixes this headline, not the direct news-to-value path.

**Tests.** Control passes (classifier). Strict xfail `test_w21_f001_a_single_headline_never_reprices_a_value`:
`adjustedValue` must be `None` or 9706.

**Smallest repair / gate.** Either delete `injuryAdjustedValue` (news drives labels only) or route news the way
`src/bdvm/news_events.py` does (typed event, confidence, source reliability, cross-provider corroboration, module
input). Both change a displayed value and the second is a methodology build, so it is owner-gated (the cardinal
rule: news never multiplies a value directly).

## W29-F001 (two value concepts under one field in /api/trade/suggestions) - CLOSED_VERIFIED

**Live path now.** `offenseOnlyRankDerivedValue` is on no pinned-board row (`playersArray` or legacy `players`) and
no longer exists in `src/` outside one explanatory comment (`data_contract.py:16109`). `suggestions.PlayerAsset`
(`:236`) has no second-board field and `_serialize_player` (`:2358`) takes no mode argument; the substitution
cannot be re-added without failing a test. The B9a record in `B_SERIES_EXECUTION_LEDGER.md` matches.

**Tests.** New `test_w29_f001_*` (2); existing `tests/api/test_one_canonical_value_per_asset.py`
(`TestSuggestionsServeTheCanonicalValue`, `TestTheContractPublishesOneCanonicalBoard`).

## W29-F002 (leagueAdjusted lens stamped where legs are unadjusted) - CLOSED_VERIFIED

**Live path now.** The lens is withdrawn: the request is parsed, ignored and stamped
`valuationMode: "market"` with `valuationNote: "league_adjusted_withdrawn: not_canonical"` (`server.py:6101-6116`
and every lens-threaded endpoint). `apply_valuation_factors` is deleted from `data_contract`; `overlay.py` writes
only `experimentalLeagueAdjusted*` fields and never `rankDerivedValue`.

**Tests.** New `test_w29_f002_league_adjusted_lens_is_withdrawn_and_never_writes_a_canonical_field`; existing
`tests/api/test_canonical_value_invariance.py` (`TestDeviceLocalStateCannotSelectAMethodology`,
`TestTheExperimentalLensIsIsolated`) and `tests/api/test_valuation_mode_threading.py`.

## W02 family note (deleted mechanisms and the invariants they protected)

Two mechanisms the August W02 / W29 findings blamed were deleted rather than repaired: the market corridor clamp
and the offense-only second canonical board. Deletion alone proves nothing, so each deletion is paired with a pin
on the invariant it was meant to protect:

* clamp -> "a published blend never leaves the range of its own contributions" is
  `_detect_blend_integrity_violations` + quarantine (W02-F003 above), with no coercion and no self-derived band;
* offense-only board -> "one asset has one canonical value whatever else is in the trade" is
  `tests/api/test_one_canonical_value_per_asset.py` plus the structural absence guards added here (W29-F001).

## Reproducing

    python -m pytest tests/api/test_audit_cw40_batch_m1_regression.py -q      # 32 passed, 6 xfailed
    python -m pytest tests/test_explicit_text_encoding.py -q

The six strict xfails (W05-F003 x2, W05-F004, W05-F006, W13-F001, W21-F001) flip to failures the moment the
named repair lands, which is the signal to retire them and update this record.
