# Source voting: consensus, not duplication (2026-10-19)

Two owner directives of 2026-10-19, both P0:

* "Correct source voting and consensus methodology" (the consensus directive);
* "Universal source voting and freshness policy", issued later the same day. It
  wins where they conflict. Its parts in this PR's lane are the DLF IDP restore,
  the cross-provider family check, the per-source eligibility facts, and the
  health / coverage documentation. The 30-day freshness schedule belongs to the
  freshness lane (CQ-64) and the outlier-filter fix to the outlier lane (CQ-65).

Both are captured in `docs/OWNER_REQUESTED_TODO.md` (V1–V10 of the 2026-10-19
entry). The coordinator's records lane copies them verbatim under `docs/owner/`.

**Policy.**

* Agreement between DIFFERENT providers is consensus, not duplication.
* Only credible shared-DATA-lineage evidence may merge votes: one feed republishing
  another, a vendor-stated derivation, or identical raw values.
* Numerical or rank similarity alone never removes, caps or haircuts a vote.
* Approved same-provider protections stay. For example, DLF Rank, DLF Values and
  both DLF IDP boards split DLF's one cap.
* Every legitimate source votes. Agreement and disagreement are both not grounds
  for removing a vote.

This record covers PR #1817 as reworked, its evidence, and the system-wide audit.
It supersedes the D2/D3 parts of `IDP_SOURCE_INDEPENDENCE_CLOSEOUT_2026-10-18.md`.

Agent-OS-Receipt: cdca1dca8385f70c0989302dece8d1bd4ce4843c

## Decisions and flags

| item | outcome | flag (default) | rollback |
|---|---|---|---|
| D2: IDP Trade Calculator / IDP Show shared cap | **withdrawn, mechanism deleted** (row-scoped correlation rules, their flag, the haircut and B11 plumbing, the build stamp). Its only basis was rank similarity. Both providers vote as separate families at their approved weights. The similarity stays a diagnostic (below) | none | n/a: nothing to roll back |
| D3: IDP Trade Calculator offense vote exclusion | **withdrawn, mechanism deleted**. Its offense votes are main's (434 offense rows on the current board, identical to main). No current republication evidence (below) | none | n/a |
| D4: DLF Values rank → Hill, offense-only `dlf` member splitting DLF's cap | **released**: every Decision 4 gate re-passed on the current board (below) | `dlf_values_rank_hill_vote` (**ON**) | `RISKIT_FEATURE_DLF_VALUES_RANK_HILL_VOTE=0`. Decision fields return to the prior board. The source stays registered and displayed, so the payload is not byte for byte |
| D5: FantasyPros IDP on its upstream clock | **kept**, and now under its own flag (independent control) | `fantasypros_idp_upstream_clock` (**ON**) | `RISKIT_FEATURE_FANTASYPROS_IDP_UPSTREAM_CLOCK=0` (the configured `styleFlag` drops the style) |
| Two-way boost: alt-family evidence | **correctness fix**: a two-way player's alt value is what a real member of that family with the same votes gets | `two_way_alt_evidence_rules` (**ON**) | `RISKIT_FEATURE_TWO_WAY_ALT_EVIDENCE_RULES=0` (the prior boost, byte for byte) |
| D1: DLF IDP / DLF Rookie IDP owner-policy hold | **policy hold rescinded; restore approved by the owner and implemented, HELD AT RELEASE** (re-applied 2026-10-19, temporary): under the incumbent outlier filter the restore drops 31 valid Draft Sharks IDP / FantasyPros IDP / IDPTC votes on 30 rows (IDP moves up to 54%, none from DLF's own vote), which the directive forbids. Lifts when the outlier interaction is corrected (CQ-65) or the owner accepts the moves (see "DLF IDP restore: implemented, held at release") | `dlf_offense_only_vote` (**ON** = hold in force; OFF = DLF IDP votes) | `RISKIT_FEATURE_DLF_OFFENSE_ONLY_VOTE=0` + restart lifts the hold (the approved restore) |
| Cross-provider families resting on similarity only | **none exist**, so no correction flag was added. The two cross-provider groupings rest on documented data lineage (audit below) | none | n/a |
| Per-source eligibility facts | **new stamp** `sourceVotingEligibility` on the contract, for the freshness lane's 26-source audit generator (below) | none (diagnostic, decides nothing) | n/a |

**All flags off** means `dlf_values_rank_hill_vote`, `two_way_alt_evidence_rules`
and `fantasypros_idp_upstream_clock` at 0 and the DLF IDP hold re-applied
(`dlf_offense_only_vote` at 1). In that state:

* on the current production board and on the golden board, every row's value, rank,
  tier, confidence bucket, confidence label and voting-source set is identical to
  main `b08f7230d1`;
* "Decision fields identical" is the precise claim, not "byte for byte": DLF Values
  stays registered and displayed (`canonicalSiteValues`, `sourceNativeValues`, the
  methodology source list).

**D5.** With the DLF IDP hold kept it moves no value: FantasyPros IDP is then the
only non-anchor subgroup voter on its rows, and a lone member's weight does not move
a weighted mean. With DLF IDP voting (the restore, held at release) there is a second
non-anchor voter, and the lower FantasyPros IDP weight (mean 0.5675 → 0.1752)
reaches values. Measured on the current board, the restore with D5 on vs off (the
reusable `--scenario` mode; `evidence/SOURCE_VOTING_CONSENSUS_2026-10-19/d5_on_top_of_defaults.json`):

* 134 IDP rows and 6 picks move;
* median 0.36%, p90 0.89%, max 1.51% (Josh Sweat);
* 4 confidence flips;
* no offense row moves.

## Two-way fix

`_apply_two_way_player_boost` used to read raw `canonicalSiteValues`. That had two
effects:

* a quarantined, policy-held, seasonally inactive or user-disabled source still
  priced Travis Hunter through the alt-family side door;
* its board-value ladder carried the real members' own 30% haircuts into the alt
  value.

Under the flag, the alt value is now built like a real member's:

* **Votes and vote values.** `_two_way_alt_votes` takes each source's own pre-blend
  vote on real members of the family (the stamped `valueContribution`),
  interpolated at the player's observation.
  * Vote values are never board values, so the haircut applies exactly once.
  * A position no real member's vote brackets is untranslated, because Phase 1
    produced no vote there. Examples: no bridge, no family ladder, beyond the
    ladder, a rookie exclusion.
* **Weights.** These come from `_observation_vote_weight`, the blend loop's single
  per-(row, source) weight owner. The main loop calls it too, so the two cannot
  drift. Inactive or held sources do not vote and are not present; a weight of 0 is
  withheld; a positive weight votes.
* **Blend.** `_two_way_alt_center` applies the incumbent's outlier filter, family
  cap and hierarchical anchor blend, using the same functions in the same order.
* **Haircut.** One present B10 family (voting or withheld, the haircut's own rule)
  keeps 0.30, once.
* **Withdrawal.** With no voting alt source, the boost withdraws. The audit stamp
  stays and lists the withheld sources.

The independent verification findings of `eb44b5421f` are all addressed:

| finding | resolution |
|---|---|
| 1. D5 rollback not byte-identical | D5 has its own flag. All flags off is decision-identical on both boards, labels included |
| 2. Payload claims overstated | wording changed to "decision fields identical"; DLF Values stays registered |
| 3. Double haircut | vote values, not board values; pinned against a real DB twin on the one-family board (`test_the_alt_value_equals_a_real_twins_value`) |
| 4. Partial vote gate | weights from the shared owner. Phase-1 drops are read from the owner's output (no member vote at that position means untranslated). A voting source needs only two bracketing member votes, not a three-point ladder |
| 5. Flat vs anchor blend | the hierarchical anchor blend, through the same owners. The default-off challengers (joint, rank-space, n3 outlier filters, sparse estimator) are not mirrored |
| 6. Missing audit stamp | a withdrawn stamp (`withdrawn`, `withdrawnReason`, `freshnessExcludedSources`) |
| 7. Quarantine line | a withheld copy is present evidence for the alt exactly as for a real row; pinned against a quarantined twin |
| 8. Ceiling check lost | both fixtures: three families, and the one-family shape where every defender is haircut. The rollback path's known one-family defect is pinned explicitly |
| 9. Hunter's offense value | the two-way rules never touch the primary value (real board and unit tests). The `test_idptc_cutoff_readiness` exemption requires that the cutoff removed `idpTradeCalc` from his alt votes |

Travis Hunter in each scenario:

* **Current board** (IDP Show withheld): main 3738. S2 (old D2/D3) 3599. S3 and
  S5 with the DLF IDP hold kept: 3599. The withheld IDP Show copy leaves his DB
  value, with two present families and no haircut. S5 with the restore (DLF IDP
  voting, a third family): 3493.
* **Golden board** (both providers vote): main 4618. Old D2 2266, from the merged
  lineage plus the haircut on the alt. S3 and S5 hold kept: 4732, from two
  families, no haircut, the real-member blend. S5 with the restore: 4513.

## Scenarios versus production main

These come from `scripts/source_voting_consensus_evidence.py` (committed, re-runnable).
Pins:

* main: `b08f7230d1`;
* old PR: `eb44b5421f`;
* current board: `exports/latest/dynasty_data_2026-10-19.json`, sha256
  `b639608f…`, with the 2026-10-19 CSVs;
* golden board: `tests/fixtures/golden/input_export.json.gz`, sha256 `f7ab141e…`.
  Dated 2026-08-04, so IDP Show votes on it.

Every scenario reads identical inputs; only code and flags differ.

The scenarios:

* **S1** is main.
* **S2** is the old PR's D2 + D3, with D4 off and the D5 style unset.
* **S3** is both IDP providers voting plus the two-way fix.
* **S4** is S3 with the IDP Trade Calculator's offense votes. D3 is deleted, so S4
  is the same build as S3; identity is confirmed by the vote count, which equals
  main's.
* **S5 hold kept** is S3 + D4 + D5: the consensus directive's combined policy.
* **DLF IDP restore alone** is every PR flag off except the hold rescission.
  "DLF restored with the cross-provider family correction" is the same build,
  because no correction exists to apply.
* **S5 combined defaults** was this PR's production defaults when measured: S3 +
  D4 + D5 + the DLF IDP restore. Since the release hold (below) the release
  defaults are **S5 hold kept**; the S5 row stays as the measurement of the
  approved restore.
* Sources above their approved weight, and families above one provider's
  authority: 0 in every scenario, main included.

#### current

| scenario | values moved | offense | IDP | picks | median / p90 / p99 / max \|Δ\| (offense) | median / p90 / p99 / max \|Δ\| (IDP) | top-50 / top-200 in-out | confidence flips | haircut gained / lost | Travis Hunter | over approved weight |
|---|---|---|---|---|---|---|---|---|---|---|---|
| S0 all PR flags off | 0 | 0 | 0 | 0 | — | — | 0 / 0 | 0 | 0 / 0 | 3738 → 3738 | 0 src, 0 fam |
| S2 old D2+D3 | 491 | 431 | 0 | 60 | 1.196 / 2.976 / 6.053 / 12.96% | — | 1 / 3 | 59 | 0 / 0 | 3738 → 3599 | 0 src, 0 fam |
| S3/S4 revised (both IDP providers + two-way fix) | 1 | 1 | 0 | 0 | 3.719 / 3.719 / 3.719 / 3.72% | — | 0 / 0 | 0 | 0 / 0 | 3738 → 3599 | 0 src, 0 fam |
| D4 alone | 335 | 299 | 0 | 36 | 0.286 / 1.659 / 3.92 / 5.13% | — | 1 / 1 | 22 | 0 / 0 | 3738 → 3738 | 0 src, 0 fam |
| D5 alone | 0 | 0 | 0 | 0 | — | — | 0 / 0 | 0 | 0 / 0 | 3738 → 3738 | 0 src, 0 fam |
| DLF IDP restore alone | 219 | 1 | 179 | 39 | 7.491 / 7.491 / 7.491 / 7.49% | 1.487 / 13.895 / 46.428 / 53.81% | 2 / 5 | 58 | 0 / 0 | 3738 → 3458 | 0 src, 0 fam |
| S5 combined, DLF IDP hold kept (TW + D4 + D5) | 336 | 300 | 0 | 36 | 0.288 / 1.669 / 3.92 / 5.13% | — | 1 / 1 | 22 | 0 / 0 | 3738 → 3599 | 0 src, 0 fam |
| **S5 combined defaults (TW + D4 + D5 + DLF IDP restore)** | 542 | 300 | 179 | 63 | 0.288 / 1.669 / 3.943 / 6.55% | 1.891 / 13.895 / 45.844 / 53.86% | 2 / 6 | 78 | 0 / 0 | 3738 → 3493 | 0 src, 0 fam |

All PR flags off vs main: identical = True (every decision-field difference count is 0: True). IDP Trade Calculator offense votes: {'DLF_restore_only': 434, 'S1_main': 434, 'S2_old_d2_d3': 0, 'S3_revised': 434, 'S5_combined': 434}. Main itself: 0 sources / 0 families above approved weight.

S2 old D2+D3 — largest movers: Adam Trautman (TE) 1188→1342 (+12.96%); Jahdae Walker (WR) 1114→1016 (-8.8%); Gabe Davis (WR) 1022→1086 (+6.26%); Phil Mafah (RB) 1016→1079 (+6.2%); Deshaun Watson (QB) 2445→2593 (+6.05%); Efton Chism (WR) 1392→1475 (+5.96%)
  top50 in ['Harold Fannin'] out ['Bo Nix']; top200 in ['2029 Mid 2nd', 'Emmett Johnson', 'Ollie Gordon'] out ['AJ Barner', 'Dalton Schultz', "Wan'Dale Robinson"]
  confidence: {'offense:high->medium': 9, 'offense:low->medium': 16, 'offense:medium->high': 11, 'offense:medium->low': 23}
  positions: PICK 60 (med -0.365%, max 2.4%), QB 67 (med -0.03%, max 6.05%), RB 116 (med -0.767%, max 6.2%), TE 77 (med -0.527%, max 12.96%), WR 171 (med -0.898%, max 8.8%)
  source vote changes: dlfSf: rows 277→274, mean w 0.9302→0.9294; draftSharks: rows 316→310, mean w 1.0→1.0; fantasyProsFitzmaurice: rows 291→291, mean w 0.5052→0.5069; fantasyProsSf: rows 406→405, mean w 0.6453→0.6457; idpTradeCalc: rows 905→473, mean w 0.8442→0.8242; ktcCrowdSfTep: rows 505→501, mean w 1.0→1.0

S3/S4 revised (both IDP providers + two-way fix) — largest movers: Travis Hunter (WR) 3738→3599 (-3.72%)
  top50 in [] out []; top200 in [] out []
  confidence: {}
  positions: WR 1 (med -3.719%, max 3.72%)
  source vote changes: 

D4 alone — largest movers: Theo Johnson (TE) 2164→2053 (-5.13%); Evan Engram (TE) 2181→2095 (-3.94%); DeMario Douglas (WR) 1607→1544 (-3.92%); Ja'Tavion Sanders (TE) 2018→1950 (-3.37%); Xavier Hutchinson (WR) 1389→1433 (+3.17%); Darren Waller (TE) 2223→2154 (-3.1%)
  top50 in ['Harold Fannin'] out ['Bryce Young']; top200 in ['Emmett Johnson'] out ['Dalton Schultz']
  confidence: {'offense:high->medium': 5, 'offense:low->medium': 5, 'offense:medium->high': 8, 'offense:medium->low': 4}
  positions: PICK 36 (med 0.059%, max 1.87%), QB 52 (med -0.054%, max 2.2%), RB 84 (med -0.037%, max 2.25%), TE 44 (med -0.295%, max 5.13%), WR 119 (med -0.161%, max 3.92%)
  source vote changes: dlfRookieSf: rows 57→57, mean w 0.6498→0.4476; dlfSf: rows 277→280, mean w 0.9302→0.4782; dlfValuesSfTep: rows None→318, mean w None→0.5266; draftSharks: rows 316→312, mean w 1.0→1.0; dynastyNerdsSfTep: rows 280→282, mean w 1.0→1.0; fantasyProsFitzmaurice: rows 291→293, mean w 0.5052→0.5068; fantasyProsSf: rows 406→405, mean w 0.6453→0.6432; flockFantasySf: rows 401→400, mean w 1.0→1.0; idpTradeCalc: rows 905→901, mean w 0.8442→0.8441; ktcCrowdSfTep: rows 505→502, mean w 1.0→1.0; yahooBoone: rows 344→342, mean w 1.0→1.0

DLF IDP restore alone — largest movers: Trevin Wallace (LB) 1916→885 (-53.81%); Myles Garrett (DL) 3597→5267 (+46.43%); CJ Allen (LB) 3918→2162 (-44.82%); T.J. Watt (DL) 2418→3431 (+41.89%); Josiah Trotter (LB) 2390→3379 (+41.38%); Will Anderson (DL) 4395→5966 (+35.75%)
  top50 in ['Aidan Hutchinson', 'Will Anderson'] out ['Bo Nix', 'Bryce Young']; top200 in ['Anthony Hill', 'Danielle Hunter', 'Josiah Trotter', 'Laiatu Latu', 'T.J. Watt'] out ['AJ Barner', 'Barrett Carter', 'CJ Allen', 'DeMarvion Overshown', "Wan'Dale Robinson"]
  confidence: {'idp:low->medium': 39, 'idp:medium->low': 19}
  positions: DB 36 (med -0.419%, max 13.04%), DL 82 (med 1.499%, max 46.43%), LB 61 (med -0.94%, max 53.81%), PICK 39 (med -0.314%, max 5.44%), WR 1 (med -7.491%, max 7.49%)
  source vote changes: dlfIdp: rows None→170, mean w None→0.9471; dlfRookieIdp: rows None→29, mean w None→0.6897; draftSharksIdp: rows 320→302, mean w 1.0→1.0; fantasyProsIdp: rows 249→239, mean w 0.5675→0.5675; idpTradeCalc: rows 905→902, mean w 0.8442→0.8443

S5 combined, DLF IDP hold kept (TW + D4 + D5) — largest movers: Theo Johnson (TE) 2164→2053 (-5.13%); Evan Engram (TE) 2181→2095 (-3.94%); DeMario Douglas (WR) 1607→1544 (-3.92%); Travis Hunter (WR) 3738→3599 (-3.72%); Ja'Tavion Sanders (TE) 2018→1950 (-3.37%); Xavier Hutchinson (WR) 1389→1433 (+3.17%)
  top50 in ['Harold Fannin'] out ['Bryce Young']; top200 in ['Emmett Johnson'] out ['Dalton Schultz']
  confidence: {'offense:high->medium': 5, 'offense:low->medium': 5, 'offense:medium->high': 8, 'offense:medium->low': 4}
  positions: PICK 36 (med 0.059%, max 1.87%), QB 52 (med -0.054%, max 2.2%), RB 84 (med -0.037%, max 2.25%), TE 44 (med -0.295%, max 5.13%), WR 120 (med -0.161%, max 3.92%)
  source vote changes: dlfRookieSf: rows 57→57, mean w 0.6498→0.4476; dlfSf: rows 277→280, mean w 0.9302→0.4782; dlfValuesSfTep: rows None→318, mean w None→0.5266; draftSharks: rows 316→312, mean w 1.0→1.0; dynastyNerdsSfTep: rows 280→282, mean w 1.0→1.0; fantasyProsFitzmaurice: rows 291→293, mean w 0.5052→0.5068; fantasyProsIdp: rows 249→249, mean w 0.5675→0.1752; fantasyProsSf: rows 406→405, mean w 0.6453→0.6432; flockFantasySf: rows 401→400, mean w 1.0→1.0; idpTradeCalc: rows 905→901, mean w 0.8442→0.8441; ktcCrowdSfTep: rows 505→502, mean w 1.0→1.0; yahooBoone: rows 344→342, mean w 1.0→1.0

S5 combined defaults (TW + D4 + D5 + DLF IDP restore) — largest movers: Trevin Wallace (LB) 1916→884 (-53.86%); Myles Garrett (DL) 3597→5246 (+45.84%); CJ Allen (LB) 3918→2171 (-44.59%); T.J. Watt (DL) 2418→3436 (+42.1%); Josiah Trotter (LB) 2390→3379 (+41.38%); Will Anderson (DL) 4395→5980 (+36.06%)
  top50 in ['Aidan Hutchinson', 'Will Anderson'] out ['Bo Nix', 'Bryce Young']; top200 in ['Anthony Hill', 'Danielle Hunter', 'Josiah Trotter', 'Laiatu Latu', 'Nick Bosa', 'T.J. Watt'] out ['AJ Barner', 'Barrett Carter', 'CJ Allen', 'Dalton Schultz', 'DeMarvion Overshown', "Wan'Dale Robinson"]
  confidence: {'idp:low->medium': 39, 'idp:medium->low': 17, 'offense:high->medium': 5, 'offense:low->medium': 5, 'offense:medium->high': 8, 'offense:medium->low': 4}
  positions: DB 36 (med -0.576%, max 12.6%), DL 82 (med 1.908%, max 45.84%), LB 61 (med -1.234%, max 53.86%), PICK 63 (med 0.041%, max 5.44%), QB 52 (med -0.054%, max 2.2%), RB 84 (med -0.037%, max 2.25%), TE 44 (med -0.295%, max 5.13%), WR 120 (med -0.161%, max 6.55%)
  source vote changes: dlfIdp: rows None→170, mean w None→0.9471; dlfRookieIdp: rows None→29, mean w None→0.6897; dlfRookieSf: rows 57→57, mean w 0.6498→0.4476; dlfSf: rows 277→280, mean w 0.9302→0.4782; dlfValuesSfTep: rows None→318, mean w None→0.5266; draftSharks: rows 316→312, mean w 1.0→1.0; draftSharksIdp: rows 320→302, mean w 1.0→1.0; dynastyNerdsSfTep: rows 280→282, mean w 1.0→1.0; fantasyProsFitzmaurice: rows 291→293, mean w 0.5052→0.5068; fantasyProsIdp: rows 249→239, mean w 0.5675→0.1752; fantasyProsSf: rows 406→405, mean w 0.6453→0.6432; flockFantasySf: rows 401→400, mean w 1.0→1.0; idpTradeCalc: rows 905→898, mean w 0.8442→0.8442; ktcCrowdSfTep: rows 505→502, mean w 1.0→1.0; yahooBoone: rows 344→342, mean w 1.0→1.0

#### golden

| scenario | values moved | offense | IDP | picks | median / p90 / p99 / max \|Δ\| (offense) | median / p90 / p99 / max \|Δ\| (IDP) | top-50 / top-200 in-out | confidence flips | haircut gained / lost | Travis Hunter | over approved weight |
|---|---|---|---|---|---|---|---|---|---|---|---|
| S0 all PR flags off | 0 | 0 | 0 | 0 | — | — | 0 / 0 | 0 | 0 / 0 | 4618 → 4618 | 0 src, 0 fam |
| S2 old D2+D3 | 757 | 422 | 265 | 70 | 1.666 / 4.132 / 9.577 / 50.93% | 3.863 / 70.0 / 70.061 / 70.08% | 1 / 6 | 185 | 29 / 0 | 4618 → 2266 | 0 src, 0 fam |
| S3/S4 revised (both IDP providers + two-way fix) | 1 | 1 | 0 | 0 | 2.469 / 2.469 / 2.469 / 2.47% | — | 0 / 0 | 0 | 0 / 0 | 4618 → 4732 | 0 src, 0 fam |
| D4 alone | 338 | 294 | 0 | 44 | 0.34 / 2.294 / 5.144 / 6.42% | — | 1 / 0 | 21 | 0 / 0 | 4618 → 4618 | 0 src, 0 fam |
| D5 alone | 0 | 0 | 0 | 0 | — | — | 0 / 0 | 0 | 0 / 0 | 4618 → 4618 | 0 src, 0 fam |
| DLF IDP restore alone | 232 | 1 | 177 | 54 | 14.335 / 14.335 / 14.335 / 14.34% | 0.943 / 3.163 / 34.449 / 39.94% | 2 / 1 | 73 | 0 / 0 | 4618 → 3956 | 0 src, 0 fam |
| S5 combined, DLF IDP hold kept (TW + D4 + D5) | 339 | 295 | 0 | 44 | 0.34 / 2.411 / 5.144 / 6.42% | — | 1 / 0 | 21 | 0 / 0 | 4618 → 4732 | 0 src, 0 fam |
| **S5 combined defaults (TW + D4 + D5 + DLF IDP restore)** | 540 | 295 | 177 | 68 | 0.34 / 2.294 / 5.144 / 6.42% | 0.943 / 3.163 / 34.449 / 39.94% | 2 / 1 | 94 | 0 / 0 | 4618 → 4513 | 0 src, 0 fam |

All PR flags off vs main: identical = True (every decision-field difference count is 0: True). IDP Trade Calculator offense votes: {'DLF_restore_only': 432, 'S1_main': 432, 'S2_old_d2_d3': 0, 'S3_revised': 432, 'S5_combined': 432}. Main itself: 0 sources / 0 families above approved weight.

S2 old D2+D3 — largest movers: L'Jarius Sneed (DB) 1133→339 (-70.08%); Andrew Wingard (DB) 1116→334 (-70.07%); Cam Taylor-Britt (DB) 1149→344 (-70.06%); Noah Sewell (LB) 1209→362 (-70.06%); Ty'Ron Hopper (LB) 1112→333 (-70.05%); Ivan Pace (LB) 1516→454 (-70.05%)
  top50 in ['Kyren Williams'] out ['Omarion Hampton']; top200 in ['Chris Bell', 'Daiyan Henley', 'DeMarvion Overshown', 'Eli Raridon', 'Jacory Croskey-Merritt', 'Tremaine Edmunds'] out ['Brian Branch', 'Josh Hines-Allen', 'Laiatu Latu', 'Nate Landman', 'Travis Hunter', 'Tuli Tuipulotu']
  confidence: {'idp:low->medium': 2, 'idp:medium->low': 98, 'offense:high->medium': 2, 'offense:low->medium': 20, 'offense:medium->high': 15, 'offense:medium->low': 48}
  positions: DB 95 (med 0.254%, max 70.08%), DL 91 (med -2.688%, max 70.02%), LB 79 (med 0.471%, max 70.06%), PICK 70 (med -0.807%, max 5.07%), QB 65 (med -0.088%, max 7.15%), RB 115 (med -0.632%, max 9.58%), TE 70 (med -0.244%, max 11.64%), WR 172 (med -1.187%, max 50.93%)
  source vote changes: dlfSf: rows 280→281, mean w 0.9292→0.9294; draftSharks: rows 323→322, mean w 1.0→1.0; dynastyNerdsSfTep: rows 282→281, mean w 1.0→1.0; fantasyProsFitzmaurice: rows 294→295, mean w 0.5051→0.5051; fantasyProsSf: rows 399→399, mean w 0.6353→0.6341; idpShowCombined: rows 646→640, mean w 1.0→0.7656; idpTradeCalc: rows 886→467, mean w 0.9194→0.5258; ktcCrowdSfTep: rows 470→472, mean w 1.0→1.0; ktcTradesSfTep: rows 473→476, mean w 1.0→1.0; yahooBoone: rows 338→337, mean w 0.9108→0.9108

S3/S4 revised (both IDP providers + two-way fix) — largest movers: Travis Hunter (WR) 4618→4732 (+2.47%)
  top50 in [] out []; top200 in [] out []
  confidence: {}
  positions: WR 1 (med 2.469%, max 2.47%)
  source vote changes: 

D4 alone — largest movers: Elijah Sarratt (WR) 2117→1981 (-6.42%); Jalen McMillan (WR) 2111→1986 (-5.92%); Colby Parkinson (TE) 2216→2102 (-5.14%); Tyrone Tracy (RB) 1948→1854 (-4.83%); Jarquez Hunter (RB) 1503→1434 (-4.59%); Tez Johnson (WR) 1632→1558 (-4.53%)
  top50 in ['Emeka Egbuka'] out ['Breece Hall']; top200 in [] out []
  confidence: {'offense:high->medium': 3, 'offense:low->medium': 8, 'offense:medium->high': 4, 'offense:medium->low': 6}
  positions: PICK 44 (med -0.042%, max 2.74%), QB 49 (med -0.036%, max 2.95%), RB 83 (med -0.024%, max 4.83%), TE 43 (med -0.179%, max 5.14%), WR 119 (med -0.239%, max 6.42%)
  source vote changes: dlfRookieSf: rows 56→56, mean w 0.6353→0.4469; dlfSf: rows 280→283, mean w 0.9292→0.4785; dlfValuesSfTep: rows None→313, mean w None→0.5158; draftSharks: rows 323→321, mean w 1.0→1.0; fantasyProsFitzmaurice: rows 294→295, mean w 0.5051→0.5051; fantasyProsSf: rows 399→399, mean w 0.6353→0.6341; idpShowCombined: rows 646→642, mean w 1.0→1.0; idpTradeCalc: rows 886→885, mean w 0.9194→0.9193; ktcCrowdSfTep: rows 470→471, mean w 1.0→1.0; otcffbSf: rows 424→425, mean w 1.0→1.0; pfkDynasty: rows 444→443, mean w 1.0→1.0; yahooBoone: rows 338→337, mean w 0.9108→0.9108

DLF IDP restore alone — largest movers: Gabe Jacas (DL) 1262→1766 (+39.94%); Will Anderson (DL) 4421→5944 (+34.45%); Rueben Bain (DL) 2879→1921 (-33.28%); Jared Verse (DL) 3096→3807 (+22.97%); Aidan Hutchinson (DL) 4793→5560 (+16.0%); Travis Hunter (WR) 4618→3956 (-14.34%)
  top50 in ['Aidan Hutchinson', 'Will Anderson'] out ['Breece Hall', 'Parker Washington']; top200 in ['Jamien Sherwood'] out ['Danielle Hunter']
  confidence: {'idp:low->medium': 14, 'idp:medium->high': 48, 'idp:medium->low': 11}
  positions: DB 34 (med -0.563%, max 6.33%), DL 80 (med 0.994%, max 39.94%), LB 63 (med -0.239%, max 12.17%), PICK 54 (med -0.625%, max 4.06%), WR 1 (med -14.335%, max 14.34%)
  source vote changes: dlfIdp: rows None→169, mean w None→0.9467; dlfRookieIdp: rows None→29, mean w None→0.6897; draftSharksIdp: rows 299→294, mean w 1.0→1.0; fantasyProsIdp: rows 237→235, mean w 0.9788→0.9788; idpShowCombined: rows 646→644, mean w 1.0→1.0; idpTradeCalc: rows 886→884, mean w 0.9194→0.9192

S5 combined, DLF IDP hold kept (TW + D4 + D5) — largest movers: Elijah Sarratt (WR) 2117→1981 (-6.42%); Jalen McMillan (WR) 2111→1986 (-5.92%); Colby Parkinson (TE) 2216→2102 (-5.14%); Tyrone Tracy (RB) 1948→1854 (-4.83%); Jarquez Hunter (RB) 1503→1434 (-4.59%); Tez Johnson (WR) 1632→1558 (-4.53%)
  top50 in ['Emeka Egbuka'] out ['Breece Hall']; top200 in [] out []
  confidence: {'offense:high->medium': 3, 'offense:low->medium': 8, 'offense:medium->high': 4, 'offense:medium->low': 6}
  positions: PICK 44 (med -0.042%, max 2.74%), QB 49 (med -0.036%, max 2.95%), RB 83 (med -0.024%, max 4.83%), TE 43 (med -0.179%, max 5.14%), WR 120 (med -0.213%, max 6.42%)
  source vote changes: dlfRookieSf: rows 56→56, mean w 0.6353→0.4469; dlfSf: rows 280→283, mean w 0.9292→0.4785; dlfValuesSfTep: rows None→313, mean w None→0.5158; draftSharks: rows 323→321, mean w 1.0→1.0; fantasyProsFitzmaurice: rows 294→295, mean w 0.5051→0.5051; fantasyProsSf: rows 399→399, mean w 0.6353→0.6341; idpShowCombined: rows 646→642, mean w 1.0→1.0; idpTradeCalc: rows 886→885, mean w 0.9194→0.9193; ktcCrowdSfTep: rows 470→471, mean w 1.0→1.0; otcffbSf: rows 424→425, mean w 1.0→1.0; pfkDynasty: rows 444→443, mean w 1.0→1.0; yahooBoone: rows 338→337, mean w 0.9108→0.9108

S5 combined defaults (TW + D4 + D5 + DLF IDP restore) — largest movers: Gabe Jacas (DL) 1262→1766 (+39.94%); Will Anderson (DL) 4421→5944 (+34.45%); Rueben Bain (DL) 2879→1921 (-33.28%); Jared Verse (DL) 3096→3807 (+22.97%); Aidan Hutchinson (DL) 4793→5560 (+16.0%); Jamien Sherwood (LB) 2581→2895 (+12.17%)
  top50 in ['Aidan Hutchinson', 'Will Anderson'] out ['Breece Hall', 'Jack Campbell']; top200 in ['Jamien Sherwood'] out ['Danielle Hunter']
  confidence: {'idp:low->medium': 14, 'idp:medium->high': 48, 'idp:medium->low': 11, 'offense:high->medium': 3, 'offense:low->medium': 8, 'offense:medium->high': 4, 'offense:medium->low': 6}
  positions: DB 34 (med -0.563%, max 6.33%), DL 80 (med 0.994%, max 39.94%), LB 63 (med -0.239%, max 12.17%), PICK 68 (med -0.433%, max 3.95%), QB 49 (med -0.036%, max 2.95%), RB 83 (med -0.024%, max 4.83%), TE 43 (med -0.179%, max 5.14%), WR 120 (med -0.239%, max 6.42%)
  source vote changes: dlfIdp: rows None→169, mean w None→0.9467; dlfRookieIdp: rows None→29, mean w None→0.6897; dlfRookieSf: rows 56→56, mean w 0.6353→0.4469; dlfSf: rows 280→283, mean w 0.9292→0.4785; dlfValuesSfTep: rows None→313, mean w None→0.5158; draftSharks: rows 323→321, mean w 1.0→1.0; draftSharksIdp: rows 299→294, mean w 1.0→1.0; fantasyProsFitzmaurice: rows 294→295, mean w 0.5051→0.5051; fantasyProsIdp: rows 237→235, mean w 0.9788→0.9788; fantasyProsSf: rows 399→399, mean w 0.6353→0.6341; idpShowCombined: rows 646→640, mean w 1.0→1.0; idpTradeCalc: rows 886→883, mean w 0.9194→0.9191; ktcCrowdSfTep: rows 470→471, mean w 1.0→1.0; otcffbSf: rows 424→425, mean w 1.0→1.0; pfkDynasty: rows 444→443, mean w 1.0→1.0; yahooBoone: rows 338→337, mean w 0.9108→0.9108

**Investigating the extreme changes.** Every mover above 3% falls into one of
four groups:

* **S2 (old D2/D3).** The offense movers are D3: the IDP Trade Calculator vote
  removed, as measured in the 2026-10-18 record (Adam Trautman +13%). The IDP
  movers at −70% are D2's merge plus the haircut (below).
* **S3.** Only Hunter.
* **D4 / S5 hold kept.** The offense movers are D4's DLF Values votes. Largest:
  Theo Johnson −5.1% on the current board, Elijah Sarratt −6.4% on golden.
  * There are no IDP moves.
  * Picks move only through the rookie-pool tether or a tier alias.
  * The confidence flips are offense rows where DLF Values joined the DLF family.
* **DLF IDP restore.** The IDP movers. Every move above 30% is the outlier filter
  dropping another source's vote, never DLF's own opinion (next section).
* **D5.** 0 values.

## DLF IDP restore (universal directive, item 1)

> **Held at release (2026-10-19).** Everything in this section measures the
> approved restore with the hold lifted. It is implemented but not released: the
> hold is back ON by default, for the reason this section's own decomposition
> shows. See "DLF IDP restore: implemented, held at release" below.

**Change.** With `dlf_offense_only_vote` OFF, `dlfIdp` and
`dlfRookieIdp` vote again, as members of the one `dlf` B10 family, so DLF Rank,
DLF Values, DLF Rookie and both IDP boards still share one provider's cap:

* sources above approved weight: 0 in every scenario;
* families above one provider: 0 in every scenario.

The hold mechanism is kept. With it in force (now the default), decision fields
return to main's (the S0 identity above).

On the current board DLF IDP votes on 171 rows and DLF Rookie IDP on 29.

**Moves split by cause.** `dlf_restore_decomposition` classifies every value the
restore moved, with the hold re-applied as the baseline:

* **DLF's own vote.** A DLF IDP board gained a vote on the row, and no other
  source's outlier verdict changed.
* **Outlier-filter side effect.** Another source's vote was newly dropped (or
  kept) by the Hampel filter. The extra voter changed the panel the filter runs
  on: at n ≥ 4 the filter switches on, and the median and MAD move.
* **Pick tether.** A current-year slot pick re-tethered to the merged rookie pool,
  which includes IDP rookies.
* **Other.** Everything else; here, only Travis Hunter's two-way value.

| cause | current: rows | current: median / p90 / max \|Δ\| | current: > 30% | golden: rows | golden: median / p90 / max \|Δ\| | golden: > 30% |
|---|---|---|---|---|---|---|
| DLF's own vote | 149 | 1.02 / 2.71 / 4.27% | 0 | 163 | 0.79 / 2.18 / 3.32% | 0 |
| outlier-filter side effect | 30 | 16.8 / 44.82 / 53.81% | 7 | 14 | 10.75 / 34.45 / 39.94% | 3 |
| pick tether | 39 | 0.8 / 4.57 / 5.44% | 0 | 54 | 0.77 / 2.7 / 4.06% | 0 |
| other (Travis Hunter) | 1 | 7.49% | 0 | 1 | 14.34% | 0 |

Votes of OTHER sources the outlier filter newly dropped:

* current: `draftSharksIdp` 18, `fantasyProsIdp` 10, `idpTradeCalc` 3;
* golden: `draftSharksIdp` 6, `fantasyProsIdp` 3, `idpShowCombined` 2,
  `idpTradeCalc` 3, with 3 votes newly kept.

DLF's own vote was never the dropped one on a row that moved more than 30%. Every
such row:

| board | player | value | the outlier filter newly drops |
|---|---|---|---|
| current | Trevin Wallace (LB) | 1916 → 885 (−53.8%) | `draftSharksIdp` |
| current | Myles Garrett (DL) | 3597 → 5267 (+46.4%) | `draftSharksIdp` |
| current | CJ Allen (LB) | 3918 → 2162 (−44.8%) | `draftSharksIdp` |
| current | T.J. Watt (DL) | 2418 → 3431 (+41.9%) | `draftSharksIdp` |
| current | Josiah Trotter (LB) | 2390 → 3379 (+41.4%) | `draftSharksIdp`, `fantasyProsIdp` |
| current | Will Anderson (DL) | 4395 → 5966 (+35.8%) | `draftSharksIdp` |
| current | Aidan Hutchinson (DL) | 4802 → 6422 (+33.7%) | `draftSharksIdp` |
| golden | Gabe Jacas (DL) | 1262 → 1766 (+39.9%) | `idpTradeCalc` |
| golden | Will Anderson (DL) | 4421 → 5944 (+34.5%) | `draftSharksIdp`, `idpShowCombined` |
| golden | Rueben Bain (DL) | 2879 → 1921 (−33.3%) | `idpShowCombined`, `idpTradeCalc` |

**Finding.** DLF's opinion entering the blend moves no player by more than 4.3%.
Every 33–54% move is the outlier-filter interaction the universal directive names
in item 6: a valid opinion, most often Draft Sharks IDP, is rejected once DLF
makes the panel large enough for the filter to run. These 30 (current) and 14
(golden) rows are the outlier lane's test set (CQ-65).

**Release posture.** The outlier lane's fix is not releasable (its challenger
fails its preregistered adversarial gates), so the hold's default went back to
True, as this paragraph provided for. See the next section.

Travis Hunter: DLF IDP becomes a third family on his DB side. His alt value goes
3599 → 3493 on the current board and 4732 → 4513 on golden; two families or more,
so no haircut either way.

The restore also moves picks only through the tether (39 current, 54 golden, each
≤ 5.4%) and flips 58 (current) / 73 (golden) confidence buckets.

## DLF IDP restore: implemented, held at release

**Decision (2026-10-19).** The owner's universal source-voting directive approves
restoring `dlfIdp` / `dlfRookieIdp`. The same directive says: "Do not allow
restoring DLF to create unexplained 40–50% player-value changes", "Correct the IDP
outlier-filter interaction", and that material outlier-filter changes need
reproducible comparisons, adversarial testing and independent validation before
production activation. Its rule for a change that fails its evidence: "hold that
specific change without blocking unrelated validated improvements."

The outlier lane (branch `claude/outlier-filter-disagreement`, head `a575a526bb`,
preregistration `b579a5fdd5`) reports, on this PR's board:

* the incumbent Hampel filter newly drops 31 valid other-source IDP votes on 30
  rows (Draft Sharks IDP 18, FantasyPros IDP 10, IDPTC 3; LB 20, DL 9, DB 2),
  producing 7 IDP moves of 34–54%, none from DLF's own vote;
* the disagreement-preserving challenger keeps 31/31 but FAILS its preregistered
  adversarial gates (AD1b 58% vs 90%, AD1d 92.6% vs 95%, AD2 15% vs 90%), so it
  stays OFF.

So the restore stays implemented behind `dlf_offense_only_vote`, and the hold is
re-applied as a **temporary release hold**: default ON, published as
`heldFromVote: owner_policy_dlf_idp_restore_held_pending_outlier_fix` with a
decision string naming the approval and the lift condition. It is not an
indefinite exclusion. It lifts (`RISKIT_FEATURE_DLF_OFFENSE_ONLY_VOTE=0` + restart,
or a reviewed default flip) when the outlier interaction is corrected (CQ-65) or
the owner accepts the moves. D4, D5 and the two-way fix ship ON.

**Evidence** (re-measured after merging main `dc900f2493`; code `dd0d536992`;
current board `exports/latest/dynasty_data_2026-10-19.json` sha256 `3ef54acd…`,
golden `tests/fixtures/golden/input_export.json.gz`; every scenario reads the same
inputs). Produced with `scripts/source_voting_consensus_evidence.py --scenario`
and cross-checked with `scripts/golden_board.py` + `scripts/board_diff.py`.
Files: `evidence/SOURCE_VOTING_CONSENSUS_2026-10-19/release_hold_vs_main_{current,golden}.json`,
`restore_vs_release_defaults_{current,golden}.json`,
`release_defaults_attribution_{current,golden}.json`.

| board | scenario vs main | values moved | offense (p50 / p90 / p99 / max \|Δ\|) | IDP moved (p50 / p90 / p99 / max \|Δ\|) | IDP ≥ 30% | picks (max) | confidence flips | haircut gained / lost | top-50 in / out | top-200 in / out | Travis Hunter |
|---|---|---|---|---|---|---|---|---|---|---|---|
| current | (b) release defaults (hold ON) | 344 | 303 (0.28 / 1.44 / 3.77 / 4.73%) | **0** | **0** | 41 (2.17%), all tether | 25, all offense | 0 / 0 | Harold Fannin / 2028 Early 1st | 0 / 0 | 3740 → 3599 |
| current | (c) hold lifted (restore) | 547 | 303 (max 6.6%) | 180 (1.91 / 13.29 / 47.54 / 54.36%) | 8 | 64 (7.45%) | 80 (55 IDP) | 0 / 0 | Aidan Hutchinson, Will Anderson / 2028 Early 1st, Bryce Young | 6 / 6 | 3740 → 3493 |
| current | all PR flags off | 0 | — | 0 | 0 | 0 | 0 | 0 / 0 | — | — | 3740 → 3740 |
| golden | (b) release defaults (hold ON) | 337 | 295 (0.35 / 2.21 / 5.35 / 6.47%) | **0** | **0** | 42 (3.40%), all tether | 22, all offense | 0 / 0 | Emeka Egbuka / Carnell Tate | Rueben Bain / Chig Okonkwo (rank only) | 4619 → 4732 |
| golden | (c) hold lifted (restore) | 539 | 295 (max 6.47%) | 177 (0.90 / 2.90 / 34.48 / 39.94%) | 3 | 67 (4.86%) | 97 (75 IDP) | 0 / 0 | Aidan Hutchinson, Will Anderson / Breece Hall, Carnell Tate | Jamien Sherwood / Chig Okonkwo | 4619 → 4513 |
| golden | all PR flags off | 0 | — | 0 | 0 | 0 | 0 | 0 / 0 | — | — | 4619 → 4619 |

* **All PR flags off = main, byte for byte.** `golden_board.py` captures of main
  and of this head with every PR flag off (hold ON, D4 / D5 / two-way OFF) are
  byte-identical on both boards; `board_diff.py --expect-no-value-change` passes.
* **Every release-default move is explained** (attribution builds, each flag alone
  against all-off): D4 alone moves 343 (current) / 336 (golden) values, the
  two-way fix moves Travis Hunter only, D5 moves 0 values, and D4 + two-way
  together move exactly the release-default count (344 / 337). No IDP value moves;
  picks move only through the rookie-pool tether. Sources above approved weight 0,
  families above one provider 0. `Rueben Bain`'s golden top-200 entry is a rank
  effect of offense values moving; his value is unchanged.
* **Restore vs release defaults** (`dlf_restore_decomposition`, current / golden):
  DLF's own vote moves 150 / 164 rows, max 5.75% / 3.32%, 0 above 30%; the
  outlier-filter side effect moves 30 / 13 rows, max 54.36% / 39.94%, 8 / 3 above
  30%; newly dropped other-source votes: current `draftSharksIdp` 18,
  `fantasyProsIdp` 10, `idpTradeCalc` 3; golden `draftSharksIdp` 5,
  `fantasyProsIdp` 3, `idpShowCombined` 2, `idpTradeCalc` 3. Rows ≥ 30% on the
  current board: Trevin Wallace −54.4%, Myles Garrett +47.5%, CJ Allen −45.5%,
  T.J. Watt +43.5%, Josiah Trotter +42.7%, Will Anderson +37.3%, Aidan Hutchinson
  +34.6%, Danielle Hunter +30.1% (today's CSVs add Danielle Hunter to the outlier
  lane's 7); every one is a Draft Sharks IDP (and for Trotter also FantasyPros
  IDP) vote the filter drops.

**Owner decision needed.** Either (1) keep the hold until a CQ-65 outlier fix
passes its preregistered and adversarial gates plus independent validation, then
lift it in a reviewed change; or (2) accept the measured restore moves as they are
and lift the hold now. Until one is chosen the hold stays, and nothing else in
this PR waits on it.

## Per-source eligibility facts: `sourceVotingEligibility`

The universal directive's item 5 asks for a 26-source audit. The freshness lane
owns the generator (CQ-64). This PR gives it the voting half as a stamped contract
block, `sourceVotingEligibility`, computed by `_source_voting_eligibility` from
the vote states the pipeline already decided. It decides nothing.

Per registered source:

* `provider` (from `source_lineage.json`), `family` and `familyBasis`:
  `own`, `same_provider`, or `cross_provider_lineage`;
* `scopes`, `rookieBoard`, `baseWeight`;
* `status` and `reason`: `voting`, `withheld` (freshness or health weight 0),
  `policy_held`, `seasonal_inactive`, `private_not_voting`,
  `disabled_by_override` or `no_observations`;
* `rollbackFlag` where an owner-policy flag controls the vote;
* `votingRows`, `excludedRows`, `meanAppliedWeight`.

The current board with the restore (hold lifted; at the release default
`dlfIdp` and `dlfRookieIdp` read `policy_held` with reason
`owner_policy_dlf_idp_restore_held_pending_outlier_fix`):

| status | sources |
|---|---|
| voting | `ktcCrowdSfTep`, `ktcTradesSfTep`, `idpTradeCalc`, `dlfSf`, `dlfRookieSf`, `dlfValuesSfTep`, `dlfIdp` (170 rows), `dlfRookieIdp` (29), `dynastyNerdsSfTep`, `fantasyCalc`, `otcffbSf`, `pfkDynasty`, `dynastyDaddySf`, `fantasyProsSf`, `fantasyProsIdp`, `fantasyProsFitzmaurice`, `flockFantasySf`, `yahooBoone`, `draftSharks`, `draftSharksIdp` |
| withheld (freshness weight 0) | `idpShowCombined` (656 rows), `fantasyNavigatorSf` (447 rows) |
| seasonal inactive | `flockFantasySfRookies` |
| private, not provisioned off the production box | `signalsSf`, `signalsIdpDl`, `signalsIdpLb`, `signalsIdpDb` |

The two withheld sources are withheld by today's cadence-relative freshness curve,
not by any voting rule. Whether they vote under the 30-day schedule is the
freshness lane's answer (CQ-64), and the production withholding is CQ-19.

## Health and coverage factors (documented, not changed)

The freshness weight is `base × freshness × health × coverage`. The universal
directive (item 7) wants every contribution explainable from base weight,
freshness, eligibility and quality, and family treatment, with any other factor
documented. Both factors live in freshness-lane files
(`src/sources/freshness.py`, `config/sources/freshness_v1.json`,
`src/sources/dataset_integrity.py`), so this PR documents them and recommends; it
changes neither.

**Health** is data validity, never fetch age (`dataset_integrity.py`):

| state | meaning | factor |
|---|---|---|
| HEALTHY | parsed, enough named rows, numeric signal present | 1.0 |
| DEGRADED | parsed but suspicious: name coverage < 95%, numeric coverage < 80%, duplicate names > 10%, zero values > 25% (value boards), or rows < 50% of the source's own rolling median | 0.5 |
| FAILED | not a usable board: HTML, CAPTCHA, login page, no recognisable columns, empty | 0.0 |

A DEGRADED or FAILED board moves no freshness clock, so a partial scrape never
reads as a publication.

**Coverage** is `rows / the source's own rolling median rows`, and the factor is
`min(1, coverage / 0.8)`. A board above 80% of its own history votes at full
weight; below that the weight scales down linearly.

**Today neither factor changes any vote.** Every measured source is HEALTHY.
Every coverage factor is 1.0 except `flockFantasySfRookies` (48 rows against a
median of 87, factor 0.69), which is seasonally inactive.

**Recommended answer** (for the freshness lane; zero impact on today's board):

* **Health: keep it, as the quality gate**, and map DEGRADED to "Data Issue — Not
  Voting" (factor 0) instead of 0.5. Then every displayed weight is base ×
  freshness step × family share, and every Data Issue reads as not voting. That
  matches the owner's status labels (V9), which have no partial-quality state.
* **Coverage: retire it as a multiplier.** Its only distinct band is 50–80% of a
  board's own history, because below 50% the board is already DEGRADED. It is not
  one of the directive's four explainable components, and a legitimately smaller
  board (a rookie list between classes) is not lower-quality evidence. If 50% is
  too loose a partial-scrape line, raise the row-collapse threshold so a partial
  scrape shows as a Data Issue rather than a silent 0.6–0.99 weight.

## Haircut investigation

L'Jarius Sneed went 1,133 → 339 under the old D2 because:

* his only voters were the IDP Trade Calculator and the IDP Show combined board:
  two providers, two B10 families;
* D2 merged them into one lineage, so the single-source haircut fired:
  1,133 × 0.30 = 340, published as 339 after rounding;
* the merge alone moved nothing, because scaling both members' weights equally
  leaves a weighted mean unchanged;
* the whole 70% is the haircut's step from two families to one.

Every other row the old D2 moved by more than 30% follows the same pattern. Causes:

* **(a) inappropriate grouping (the D2 merge)** triggered every defensive collapse;
* **(b) the haircut's 1 → 2 family step** set the magnitude, exactly 0.30;
* **(c) voting eligibility** contributed on 2 defenders. A held DLF IDP or DLF
  rookie IDP observation was present but not voting. Had DLF IDP voted, those rows
  would have kept two families even under D2. With the restore (hold lifted) they
  carry three families: Trenton Simpson 1369 → 1384 and Treydan Stukes
  1855 → 1816 on the current board (freshness off); 1154 → 1191 and 1518 → 1509
  on golden.

The one non-defensive row is Travis Hunter, through the alt-value haircut. Under the
corrected policy (S3, S5 hold kept) no row collapses, and every listed defender
keeps main's value. The "revised" column below keeps the DLF IDP hold so it
isolates the D2 grouping; `valueRevisedDlfRestored` in the evidence JSON adds the
restore.

**golden**: 30 rows; (a) grouping 29, (b) 0.30 step 29, (c) a not-voting observation present 3.

| player | pos | main (D2 off) | old D2 | revised | C × 0.30 | families main → old D2 | (c) present, not voting |
|---|---|---|---|---|---|---|---|
| L'Jarius Sneed | DB | 1133 | 339 | 1133 | 1133 × 0.30 = 340 | idpShow, idpTradeCalc → idpShow | — |
| Andrew Wingard | DB | 1116 | 334 | 1116 | 1116 × 0.30 = 335 | idpShow, idpTradeCalc → idpShow | — |
| Cam Taylor-Britt | DB | 1149 | 344 | 1149 | 1149 × 0.30 = 345 | idpShow, idpTradeCalc → idpShow | — |
| Noah Sewell | LB | 1209 | 362 | 1209 | 1210 × 0.30 = 363 | idpShow, idpTradeCalc → idpShow | — |
| Ivan Pace | LB | 1516 | 454 | 1516 | 1516 × 0.30 = 455 | idpShow, idpTradeCalc → idpShow | — |
| Shaun Dolac | LB | 1142 | 342 | 1142 | 1142 × 0.30 = 343 | idpShow, idpTradeCalc → idpShow | — |
| Tatum Bethune | LB | 1242 | 372 | 1242 | 1242 × 0.30 = 373 | idpShow, idpTradeCalc → idpShow | — |
| Ty'Ron Hopper | LB | 1112 | 333 | 1112 | 1112 × 0.30 = 334 | idpShow, idpTradeCalc → idpShow | — |
| Isaiah McDuffie | LB | 1325 | 397 | 1325 | 1325 × 0.30 = 398 | idpShow, idpTradeCalc → idpShow | — |
| Jack Kiser | LB | 1442 | 432 | 1442 | 1442 × 0.30 = 433 | idpShow, idpTradeCalc → idpShow | — |
| Michael Taaffe | DB | 1165 | 349 | 1165 | 1166 × 0.30 = 350 | idpShow, idpTradeCalc → idpShow | — |
| Shemar James | LB | 1275 | 382 | 1275 | 1276 × 0.30 = 383 | idpShow, idpTradeCalc → idpShow | — |
| Troy Dye | LB | 1128 | 338 | 1128 | 1128 × 0.30 = 338 | idpShow, idpTradeCalc → idpShow | — |
| Jaylon Carlies | DB | 1101 | 330 | 1101 | 1102 × 0.30 = 331 | idpShow, idpTradeCalc → idpShow | — |
| Junior Colson | LB | 1465 | 439 | 1465 | 1465 × 0.30 = 440 | idpShow, idpTradeCalc → idpShow | — |
| Treydan Stukes | DB | 1518 | 455 | 1518 | 1518 × 0.30 = 455 | idpShow, idpTradeCalc → idpShow | dlfRookieIdp |
| Ty Okada | DB | 1151 | 345 | 1151 | 1152 × 0.30 = 346 | idpShow, idpTradeCalc → idpShow | — |
| Derrick Moore | DL | 1981 | 594 | 1981 | 1982 × 0.30 = 595 | idpShow, idpTradeCalc → idpShow | — |
| Dorian Williams | LB | 1461 | 438 | 1461 | 1462 × 0.30 = 439 | idpShow, idpTradeCalc → idpShow | — |
| Kenneth Grant | DL | 1411 | 423 | 1411 | 1411 × 0.30 = 423 | idpShow, idpTradeCalc → idpShow | — |
| Trenton Simpson | LB | 1154 | 346 | 1154 | 1154 × 0.30 = 346 | idpShow, idpTradeCalc → idpShow | dlfIdp |
| Dane Belton | DB | 1127 | 338 | 1127 | 1128 × 0.30 = 338 | idpShow, idpTradeCalc → idpShow | — |
| Keionte Scott | DB | 1737 | 521 | 1737 | 1738 × 0.30 = 521 | idpShow, idpTradeCalc → idpShow | — |
| Nick Martin | LB | 1507 | 452 | 1507 | 1508 × 0.30 = 452 | idpShow, idpTradeCalc → idpShow | — |
| Shemar Stewart | DL | 1394 | 418 | 1394 | 1394 × 0.30 = 418 | idpShow, idpTradeCalc → idpShow | — |
| Caleb Banks | DL | 1440 | 432 | 1440 | 1440 × 0.30 = 432 | idpShow, idpTradeCalc → idpShow | — |
| Jack Sanborn | LB | 1150 | 345 | 1150 | 1150 × 0.30 = 345 | idpShow, idpTradeCalc → idpShow | — |
| Lathan Ransom | DB | 1513 | 454 | 1513 | 1514 × 0.30 = 454 | idpShow, idpTradeCalc → idpShow | — |
| Tyrice Knight | LB | 1173 | 352 | 1173 | 1174 × 0.30 = 352 | idpShow, idpTradeCalc → idpShow | — |
| Travis Hunter | WR | 4618 | 2266 | 4732 | n/a (alt haircut) | 12 families → 12 families | dlfIdp, dlfValuesSfTep, fantasyCalc, fantasyNavigatorSf |

**currentFreshnessOff**: 31 rows; (a) grouping 30, (b) 0.30 step 30, (c) a not-voting observation present 3.

| player | pos | main (D2 off) | old D2 | revised | C × 0.30 | families main → old D2 | (c) present, not voting |
|---|---|---|---|---|---|---|---|
| Andrew Wingard | DB | 1133 | 339 | 1133 | 1133 × 0.30 = 340 | idpShow, idpTradeCalc → idpShow | — |
| Cam Taylor-Britt | DB | 1133 | 339 | 1133 | 1133 × 0.30 = 340 | idpShow, idpTradeCalc → idpShow | — |
| L'Jarius Sneed | DB | 1133 | 339 | 1133 | 1133 × 0.30 = 340 | idpShow, idpTradeCalc → idpShow | — |
| Tatum Bethune | LB | 1213 | 363 | 1213 | 1213 × 0.30 = 364 | idpShow, idpTradeCalc → idpShow | — |
| Jaylon Carlies | DB | 1099 | 329 | 1099 | 1099 × 0.30 = 330 | idpShow, idpTradeCalc → idpShow | — |
| Junior Colson | LB | 1229 | 368 | 1229 | 1229 × 0.30 = 369 | idpShow, idpTradeCalc → idpShow | — |
| Dorian Williams | LB | 1466 | 439 | 1466 | 1466 × 0.30 = 440 | idpShow, idpTradeCalc → idpShow | — |
| Jack Kiser | LB | 1212 | 363 | 1212 | 1212 × 0.30 = 364 | idpShow, idpTradeCalc → idpShow | — |
| Trenton Simpson | LB | 1369 | 410 | 1369 | 1370 × 0.30 = 411 | idpShow, idpTradeCalc → idpShow | dlfIdp |
| Kenneth Grant | DL | 1412 | 423 | 1412 | 1412 × 0.30 = 424 | idpShow, idpTradeCalc → idpShow | — |
| Shaun Dolac | LB | 1165 | 349 | 1165 | 1166 × 0.30 = 350 | idpShow, idpTradeCalc → idpShow | — |
| Shemar Stewart | DL | 1392 | 417 | 1392 | 1392 × 0.30 = 418 | idpShow, idpTradeCalc → idpShow | — |
| Troy Dye | LB | 1125 | 337 | 1125 | 1125 × 0.30 = 338 | idpShow, idpTradeCalc → idpShow | — |
| Ty Okada | DB | 1195 | 358 | 1195 | 1195 × 0.30 = 358 | idpShow, idpTradeCalc → idpShow | — |
| Tyrice Knight | LB | 1135 | 340 | 1135 | 1135 × 0.30 = 340 | idpShow, idpTradeCalc → idpShow | — |
| Caleb Banks | DL | 1445 | 433 | 1445 | 1445 × 0.30 = 434 | idpShow, idpTradeCalc → idpShow | — |
| Jack Sanborn | LB | 1131 | 339 | 1131 | 1131 × 0.30 = 339 | idpShow, idpTradeCalc → idpShow | — |
| Michael Taaffe | DB | 1171 | 351 | 1171 | 1172 × 0.30 = 352 | idpShow, idpTradeCalc → idpShow | — |
| Nick Martin | LB | 1505 | 451 | 1505 | 1506 × 0.30 = 452 | idpShow, idpTradeCalc → idpShow | — |
| Noah Sewell | LB | 1171 | 351 | 1171 | 1172 × 0.30 = 352 | idpShow, idpTradeCalc → idpShow | — |
| Shemar James | LB | 1218 | 365 | 1218 | 1218 × 0.30 = 365 | idpShow, idpTradeCalc → idpShow | — |
| Treydan Stukes | DB | 1855 | 556 | 1855 | 1856 × 0.30 = 557 | idpShow, idpTradeCalc → idpShow | dlfRookieIdp |
| Willie Gay | LB | 1101 | 330 | 1101 | 1101 × 0.30 = 330 | idpShow, idpTradeCalc → idpShow | — |
| Derrick Moore | DL | 1978 | 593 | 1978 | 1978 × 0.30 = 593 | idpShow, idpTradeCalc → idpShow | — |
| Dane Belton | DB | 1344 | 403 | 1344 | 1344 × 0.30 = 403 | idpShow, idpTradeCalc → idpShow | — |
| Ivan Pace | LB | 1514 | 454 | 1514 | 1514 × 0.30 = 454 | idpShow, idpTradeCalc → idpShow | — |
| Lathan Ransom | DB | 1507 | 452 | 1507 | 1508 × 0.30 = 452 | idpShow, idpTradeCalc → idpShow | — |
| Isaiah McDuffie | LB | 1470 | 441 | 1470 | 1470 × 0.30 = 441 | idpShow, idpTradeCalc → idpShow | — |
| Keionte Scott | DB | 2020 | 606 | 2020 | 2020 × 0.30 = 606 | idpShow, idpTradeCalc → idpShow | — |
| Ty'Ron Hopper | LB | 1130 | 339 | 1130 | 1130 × 0.30 = 339 | idpShow, idpTradeCalc → idpShow | — |
| Travis Hunter | WR | 3736 | 2352 | 3714 | n/a (alt haircut) | 12 families → 12 families | dlfIdp, dlfValuesSfTep |


**Haircut census, current board.** 43 IDP rows and 5 offense rows carry the 30%
retention, identical in main and in S5 (with the DLF IDP restore). Only 1 of them has an observed but not
voting source: DJ Turner, a `fantasyNavigatorSf` name collision.

**Is the haircut itself flawed?** The step from one present family to two is the
rule's purpose: corroboration. Under the corrected policy it fires only on rows
that genuinely rest on one provider.

* **Discontinuity.** The rule is not continuous in the evidence. A second family at
  any weight lifts a row from 30% to full value.
* **Existing challenger.** That limitation already has a preregistered challenger:
  `sparse_evidence_estimator`, a censor-aware central estimate
  (`docs/valuation/evidence/sparse-evidence-2026-10-01/`). It failed its gate G2c:
  median challenger ÷ incumbent 3.335 against a ceiling of 2.0. So it stays off.
* **Decision.** The approved 30% rule stays in production. No new haircut rule or
  challenger is added here, because the measured collapses were caused by grouping,
  not by a new flaw.
* **Recommended follow-up.** Re-run that preregistered challenger on current data,
  not invent a second one.

## System-wide audit: cross-provider groupings

`config/sources/source_lineage.json` and the `_RANKING_SOURCES` correlation groups
were checked. Row-scoped rules: none remain, because D2's was deleted.

These families have one provider:

* `dlf`: Rank, Values, Rookie and both IDP boards;
* `draftSharks`;
* `fantasyPros`;
* `flockFantasy`;
* the KTC providers: `ktcCrowdSfTep` and `ktcTradesSfTep` are two families of one
  provider.

Same-provider grouping is the approved protection. The cross-provider groupings
are:

| family | member (provider) | documented basis | classification | board impact if split (current board) |
|---|---|---|---|---|
| `ktcCrowd` | `fantasyNavigatorSf` (Fantasy Navigator) | `fn-uses-ktc-data`: every row carries a `ktc_player_id`, and the site credits KeepTradeCut as a data source | **declared data lineage**, a vendor-credited data source, not similarity. Keep | 0 today: it is freshness-withheld on every row. With freshness rolled back it votes on 447 rows, and splitting would move 457 values (offense p50 0.38%, p90 1.9%, max 12.0%; Travis Homer +12.0%) |
| `fantasyCalc` | `signalsSf` (Signals Fantasy) | `signals-fantasycalc-app-composition`: Signals' own app code falls back to FantasyCalc's value (`dynastyValueMap ?? dynastyValue ?? fcValue`) and computes over a FantasyCalc fetch | **observed data-flow composition**. Not proven for the stored value (suspected), but stronger than similarity. Keep; review when the vendor states its ancestry | not measurable here: a private, box-local source, not provisioned off the production box. Owner addendum 2026-10-03 |
| `fantasyCalc` | `signalsIdpDl/Lb/Db` | same provider as `signalsSf`; held from voting | same-provider. FantasyCalc publishes no IDP, so on IDP rows the group is Signals alone | 0 (held) |

Measured-similarity relations that do **not** merge votes: they stay separate
families, which is correct under the directive. These are FantasyCalc–Dynasty Daddy,
OTC–FantasyCalc, OTC–Boone, Fitzmaurice–Nerds, Fantasy Navigator–FantasyPros, and
IDP Trade Calculator–IDP Show. They are used only for leave-lineage-out evaluation
and diagnostics.

**Candidates for correction (similarity-only vote merges): none.** No existing
family merges two providers on similarity alone. The weakest basis is Signals'
(suspected), and it is listed for review rather than correction.

**Universal directive, item 3.** It asks for a flag that gives each provider its
own family wherever a grouping is similarity-only. There is none, so no flag was
added, and the measured "impact if split" column above stands in for it. The two
documented-lineage groupings are kept and cited.

**The IDP Show counts once.** Only `idpShowCombined` is a registered voter. Its
IDP-only board is collected for diagnostics and never votes, so The IDP Show is
one provider and one vote.

## IDP Trade Calculator: republication evidence

The question is whether IDPTC republishes KTC's data.

* **Provider documentation.** There is none stating a derivation.
* **Identical raw values.** At two earlier offense batches, 2026-06-06 (286/357
  exact) and 2026-08-28 (212/359 exact), its values equalled KTC base-superflex
  captures from days earlier. That is republication evidence for those batches, at
  the time.
  * The batch voting since 2026-10-10 is not identical: at most 4 of 343–353 exact
    across 2026-09-25..10-18.
  * On the 2026-10-19 CSVs, 1 of 471 offense rows is exactly equal to KTC (base,
    Crowd TE++ or `ktcSfTep`), and 30–34 are within 1%.
* **Timestamps.** Uninformative. Both clocks are our fetch times, and KTC changes at
  almost every fetch, so every IDPTC broad change coincides with one.
* The median value ratio of 1.000 is similarity, not lineage.

**Finding: no current republication evidence.** The offense vote is restored
(main's).

**Recommended answer** to the remaining policy question. The directive covers it
("evaluate the appropriate existing family treatment"), so no new owner decision is
needed:

* add a per-batch exact-identity monitor as a diagnostic;
* treat any future value-identity batch as KTC-derived, routing it into the
  `ktcCrowd` family cap, never a removal.

That is a follow-up, not part of this PR.

## IDP provider similarity (diagnostic only)

Measured on the 2026-10-19 CSVs, on common players. It touches no vote, weight,
haircut or confidence denominator.

| pair | common players | Spearman | identical relative order |
|---|---|---|---|
| IDP Trade Calculator vs IDP Show IDP-only board | 349 | 0.986 | 99.5% |
| IDP Trade Calculator vs IDP Show combined board (the voter) | 653 | 0.886 | 86.0% |

## D4 activation gates (current board; thresholds as declared 2026-10-18)

| gate | criterion | measured | result |
|---|---|---|---|
| timestamps | content clock, ON_SCHEDULE, HEALTHY | SNAPSHOT; clock = last broad change 2026-10-18T12:27Z; age 16.9 h of 24 h; freshness 1.0; HEALTHY | pass |
| completeness | ≥ 300 rows, all of QB/RB/WR/TE, no non-positive value, no pick rows | 319 (QB 54, RB 91, TE 46, WR 128); 0; 0 | pass |
| longitudinal stability | ≥ 10 releases; consecutive Spearman ≥ 0.95; top-24 overlap ≥ 20 | 24 releases 2026-09-25 → 10-18; Spearman 0.986–1.000; overlap 22–24 | pass |
| top-player movement | top-50 max \|Δ\| ≤ 5%, ≤ 2 swaps, offense p90 ≤ 3% | 1.87%, 1 swap, p90 1.66% | pass |
| outlier diagnostic | Hampel drop ≤ 5% | 0.31% | pass |
| non-interference | offense votes only; 0 IDP moves; picks only via tether/alias | 319 offense votes; 0; 0 | pass |
| one DLF family | DLF family applied weight ≤ 1.0; no second DLF family | max 1.0; 0 rows | pass |
| geometric package model | 0 invariant failures; side flips ≤ 1% of 2,000 | `geom_q078_v1`: 0 failures; 3 flips (0.15%); 12 band crossings | pass |
| contract | structurally OK | OK, 0 structural / 0 source-health errors | pass |
| regression suite | the required suite green with the flag on | see Validation | pass |

## Validation

* `bash scripts/format_python_changes.sh`;
* `python scripts/check_decision_coercions.py` (committed head);
* `python scripts/check_planning_integrity.py`;
* `pytest -n 2 -m "not livedata" tests/api tests/canonical tests/sources tests/model_registry tests/consensus_edge tests/docs`;
* `scripts/validate_api_contract.py --lane structural` and `--lane full`: both
  exit 0 on the current board, `ok=True`, 0 errors. The 6 warnings are the
  private Signals sources (absent by design off the box) and the two
  freshness-withheld sources (`fantasyNavigatorSf`, `idpShowCombined`);
* all PR flags off vs main `b08f7230d1`: `scripts/golden_board.py` captures are
  byte-identical on the golden and the current board, and
  `scripts/board_diff.py --expect-no-value-change` passes on both.

The results are in the PR body.

## Completion result

* **STATUS:** DONE for implementation and evidence. The approved DLF IDP restore
  is implemented and held at release (hold default ON) pending the outlier fix or
  an owner decision. Production verification follows merge and deploy.
* **ACCEPTANCE:**
  * D2 and D3 withdrawn and deleted;
  * D4 gates re-passed;
  * D5 independently flagged;
  * the two-way fix behind its own flag, with every verification finding resolved;
  * the DLF IDP restore implemented behind its flag, under the DLF family cap, with
    its moves split into DLF's own vote and the outlier-filter side effect, and
    held at release because the side effect fails the directive's 40–50% rule;
  * no similarity-only cross-provider family (no correction needed);
  * the per-source `sourceVotingEligibility` stamp;
  * health and coverage documented with a recommendation;
  * reproducible, reusable scenarios, including DLF restore alone and on top of
    the combined policy;
  * all flags off is identical to main on both boards.
* **EVIDENCE:**
  * `scripts/source_voting_consensus_evidence.py` (`--scenario` / `--board` for
    any flag combination);
  * `docs/sources/evidence/SOURCE_VOTING_CONSENSUS_2026-10-19/results.json`;
  * `docs/sources/evidence/SOURCE_VOTING_CONSENSUS_2026-10-19/d5_on_top_of_defaults.json`;
  * `tests/api/test_source_independence_closeout.py`;
  * `tests/api/test_two_way_player_boost.py`;
  * `tests/api/test_idptc_cutoff_readiness.py`;
  * `tests/api/test_dlf_offense_only_vote.py`.
* **UNRESOLVED:**
  * the owner decision on the held DLF IDP restore (keep the hold until CQ-65, or
    accept the moves); the outlier fix itself (CQ-65): the 30 current-board and
    13 golden-board side-effect rows;
  * production verification of the deployed board;
  * `idpShowCombined` and `fantasyNavigatorSf` are withheld by today's
    cadence-relative freshness curve (freshness lane, CQ-64 / CQ-19);
  * the health / coverage recommendation awaits the freshness lane;
  * the IDPTC per-batch identity monitor (recommended follow-up);
  * a re-run of the preregistered sparse-evidence challenger on current data
    (recommended follow-up);
  * the Signals grouping's stored-value ancestry (vendor-unstated);
  * the two-way alt value does not mirror the default-off challengers.
* **NEXT_ACTION:** release-train integration of #1817 with the DLF IDP hold in
  force; deploy; then observe the DLF family weights, `sourceVotingEligibility`
  (DLF IDP `policy_held`) and Travis Hunter's `twoWayPlayerBoost` on production.
  Lift the hold in a later reviewed change once CQ-65 lands or the owner accepts
  the moves.
