# Workstream G2: IDP source-integrity evaluation — preregistration

**Status:** registration only. This commit adds no code and reads no held-out content. SHADOW RESEARCH: nothing here
changes a served value, rank, vote, weight, flag, Hill curve, bridge, freshness rule, lineage record or deployment.

**Authority:** `docs/owner/IDP_VALUATION_ACCURACY_DIRECTIVE_2026-10-25.md` (isolated shadow research) and
`docs/owner/IDP_MARKET_ACQUISITION_DIRECTIVE_2026-10-26.md` (research, read-only collection, additive diagnostics).
Owner-reserved, and not touched: Outlier Integrity V2 / V2.1 (#1884, #1921, #1938), the DLF IDP hold, Signals IDP
voting, the freshness v2 schedule. The ROS-lane DraftSharks rank-basis fix is PR #1997 and is not duplicated here.

Agent-OS-Receipt: cb64f74cf4d2763aa16d55ba0d6350f585a2a42f

## 1. Why a successor, and what it is

Outlier Integrity V2 ended **MORE RESEARCH REQUIRED** (`docs/sources/outlier_integrity_v2/OWNER_REPORT.md`). It tried
to decide which votes to drop. It could not reliably catch a corrupted value on a three-provider row without history,
it could not catch a wrong-player swap that carries no identity evidence, and it spent its held-out boards.

G2 is a **diagnostic**, not a filter. It drops nothing. For every IDP (row, source) observation it answers structural
questions first and treats disagreement last:

| check | question | evidence |
|---|---|---|
| identity | Does the row's Sleeper id name this player? Does the vendor entry it joined name this player and only this player? | contract `sleeper.idToPlayer`, `sourceAudit.matchedDetails`, the vendor CSV the build read |
| position family | Do the row, Sleeper and the vendor agree on DL / LB / DB, allowing Sleeper multi-eligibility? | `sleeper.positions`, `sleeper.fantasyPositions`, vendor position column |
| normalization | Is each source's rank translation monotone, its vote curve monotone, every vote positive? Is a per-position list mixed into a combined one (the PR #1997 defect class, checked here on the DYNASTY lane)? | `sourceRankMeta` |
| staleness | Does the pipeline's `lastGenuineUpdate` agree with when the CSV's rankings actually changed in git? | `sourceVotingStatus`, `git log` of the CSV |
| disagreement | For each provider, `u = ln(vote / median of the other providers)`. agree / dissent / extreme | votes, one per provider |
| error vs disagreement | An extreme vote is a DATA ERROR only when a structural defect on the same observation corroborates it; otherwise it is unexplained dissent for adjudication | the checks above |
| segment level | Is a whole (provider, family) segment shifted? | median `u` per segment |
| coverage | How many independent providers vote per row, by family and IDP rank band; how many carry their own level rather than a level translated through the shared-market backbone? | votes, `sharedMarketTranslated` |
| lineage | Is every IDP source registered to a provider; which recorded relations join them? | `config/sources/source_lineage.json` |
| false exclusions | Which non-voting observations were dropped by the outlier filter or quarantine with no structural defect? | `droppedSources`, `quarantined` |
| deep tail | Past IDP rank 216 (2 x 108 league-wide starters): single-provider share, tie plateaus, votes past tail saturation (904), non-positive values | the panel |

**Signal independence.** Votes are collapsed to one per PROVIDER (DLF IDP and DLF Rookie IDP are one opinion), and
different providers are never merged: agreement between providers is consensus
(`docs/sources/SOURCE_VOTING_CONSENSUS_2026-10-19.md`). Borrowing a scale (FantasyPros IDP and DLF IDP are priced
through the IDP Trade Calculator's player order) is reported as `ownLevel` coverage. It is not data lineage and caps
nothing. **Missing is never zero:** a non-voting observation is absent from every vote statistic, and a row with fewer
than three providers is `not_evaluable`, never zero disagreement.

## 2. Held-out set — and why it is one board

Every archive in `exports/archive/` falls into one of four groups:

1. **Read by Outlier Integrity V2:** 149 boards (its E_BASELINE, E_DEV, V_HELDOUT, I_INDEPENDENT, R_REGRESSION_PIN and
   EXCLUDED manifests), through `dynasty_export_20261020_052241`.
2. **Read by the IDP accuracy lanes A–H:** `dynasty_export_20260909_211525` and `dynasty_export_20261025_120337`.
3. **Sealed by the Outlier Integrity V2.1 preregistration:** every board added from T0 = 2026-10-20T20:00:30Z (commit
   `180d2463d2`) through the end of its held-out window. That window can extend to 2026-12-02, plus a 7-day H_TARGET,
   so the seal can last until **2026-12-09T00:00Z**. Its rule says any lane's source-integrity use of a sealed board
   must be logged as a V2.1 deviation. G2 does not spend another lane's held-out data, so the runner **refuses** every
   board in that interval.
4. **Unread and unsealed:** exactly one board, **`dynasty_export_20261020_173527.zip`**.
   * zip sha256 `a4da7124…9b105`, added by refresh `c2b44022f0` at 2026-10-20T17:38:56Z;
   * absent from every V2 manifest;
   * listed in V2.1's `POPULATIONS.json` as SPENT by name and hash only, which V2.1 never reads;
   * referenced by no IDP-lane record.

`BOARDS.json` registers it and the three development boards. Before this commit only these were read for it: git
object ids, commit times and the zip hash. No content scan.

**Its IDP inputs are mostly not new.** At its refresh commit, only `draftSharksIdp.csv` differs from the development
boards. `idpTradeCalc`, `fantasyProsIdp`, `dlfIdp`, `dlfRookieIdp`, `idpShowCombined` and `idpShow` are byte-identical
to their copies on the development boards (blob ids in `BOARDS.json`). The board is still a fresh BUILD: offense
sources moved, and with them the cross-market context. But for those six sources a held-out B-gate result is a
**replication**, not independent evidence, and the results must say so per source.

**Prospective held-out (H2):** complete boards added by the automated refresh on or after 2026-12-09T00:00Z. They are
not evaluated in this PR.

**Development boards** (all V2-spent): `dynasty_export_20261018_161125` (I_INDEPENDENT), `dynasty_export_20261019_201546`
(pin2015 R_PIN) and `dynasty_export_20261020_052241` (I_INDEPENDENT). The evaluator and every threshold below were
developed on them before this commit. That is disclosed in §5.

## 3. Builds

Each board is built in-process (`src/api/value_replay.build`) from its archive and the repository tree of its refresh
commit (`scripts/research_pinned_board.csv_tree`):

* **served**: registry defaults, DLF IDP hold ON. The gates are evaluated here.
* **dlfRestored**: `dlf_offense_only_vote` OFF inside the build process only. Reported: DLF's own votes and the
  incumbent filter's reaction to them. Nothing is persisted or activated.

## 4. Frozen thresholds and gates

The thresholds are `PREREGISTRATION.json::thresholds`, equal to `THRESHOLDS` in
`src/robust_filter_shadow/idp_source_integrity_g2.py`. A test pins the equality. Headline values:

* τ_agree = ln 2, τ_extreme = ln 3;
* a vote needs at least 2 other providers to be evaluable;
* τ_segment = ln 2.5 over at least 15 rows;
* rank-basis probe at k = 24 (low slope ≤ 1.25, high ≥ 2.0, collision share ≥ 0.25 or full segregation);
* stale tolerances 1 h (stamp after content) and 36 h (stamp before broad change);
* broad change ≥ 5 rows and ≥ 2 % (mirrors `config/sources/freshness_v1.json`).

**E-gates: evaluator validity.** Injected into the held-out served panel, seed 20261027. **All must pass for the
evaluation to be trusted.**

| gate | pass condition |
|---|---|
| E1 determinism | two evaluations give one digest |
| E2 vendor family | 30/30 injected out-of-eligibility vendor families flagged |
| E3 Sleeper id | 20/20 injected wrong-name ids flagged |
| E4 shared entry | 20/20 injected two-rows-one-vendor-entry joins flagged |
| E5 segment scale | ×5 and ×0.2 on every evaluable unshifted (provider, family) segment: all flagged |
| E6 row corruption | 200 single votes ×8 or ÷8, one per row, on rows with ≥ 3 providers: recall ≥ 0.90 **and** clean extreme rate ≤ 0.05 |
| E7 wrong-player swap | ≤ 100 swaps of one provider's votes between same-family rows whose votes differ ≥ 4×: recall ≥ 0.80. Fewer than 20 constructible swaps is INSUFFICIENT, never a pass |
| E8 rank inversion | 20/20 single translation inversions flagged |
| E9 stale stamp | the synthetic triple is classified exactly |
| E10 runtime | ≤ 60 s per evaluation |
| E11 rank-basis restart | restarting the deepest family of each evaluable source at 1..n is flagged |

**B-gates: held-out board integrity**, served build. A failure is a finding, never a reason to tune the evaluator.

| gate | pass condition |
|---|---|
| B1 identity | 0 identity DEFECT findings |
| B2 normalization | 0 inversions, 0 non-positive votes, 0 `rank_basis_mixed` |
| B3 stale | every IDP source with a vendor CSV is `consistent` or `not_evaluable` |
| B4 attribution | 0 extreme votes `data_error_corroborated` |
| B5 false exclusions | 0 candidates on the served build |
| B6 segments | 0 shifted segments |
| B7 missing never zero | 0 priced IDP rows without a vote; 0 non-positive published IDP values |
| B8 lineage | 0 IDP sources without a lineage provider |

**Predictions** (reported as confirmed / not confirmed):

* **P1.** dlfRestored yields ≥ 20 false-exclusion candidates. That would mean the V2 root cause replicates on a fresh
  build.
* **P2.** `draftSharksIdp` is `familyDominanceOnly` (an LB-heavy combined list), not `rank_basis_mixed`.

## 5. What the development boards already showed (disclosed before the held-out read)

* **E-gates:** E1–E11 pass on all three. E7 had only 22 constructible swaps, recall 0.909.
* **E6 calibration:** at τ_extreme = ln 4, ×8 recall was 0.815 and swap recall 0.26. Two things changed. τ_extreme
  moved to ln 3. The injectors were also fixed: the old versions could corrupt two providers on one row, which
  contaminated the leave-one-out median. These were calibration choices on development data. No mandatory
  acceptance threshold (E6 0.90, E7 0.80) was lowered.
* **Rank-basis probe:** the first version flagged Draft Sharks as mixed. Its LBs fill 24 of its first ~27 ranks, and
  its coarse 3D Value+ ties families together. A tie is now not a collision. Full segregation was added for boards
  whose IDP ranks start deep (cross-market lists).
* **Expected B-gate failures:**
  * B1, identity: 6 `vendor_family_mismatch` and 2 `dual_listing_wrong_family`.
  * B3, stale: `fantasyProsIdp` `vendor_stamp_older_than_broad_change`.
  * All other B-gates passed on development data. Because six of the seven IDP CSVs are byte-identical on the held-out
    board, the held-out B results for those sources are expected to replicate these.

## 6. Run discipline

* The held-out board is evaluated **once**, at the commit that adds the evaluator, from a clean tree. Every record is
  committed as produced.
* No evaluator or threshold change is allowed after the held-out read without a logged deviation in this directory.
  A deviation that loosens a gate is forbidden.
* Production impact: **none**. No flag, value, vote, weight, lineage entry or deployment changes.
