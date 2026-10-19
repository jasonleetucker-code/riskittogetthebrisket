# D2 evidence gate: preregistration (2026-10-19)

Owner ruling on PR #1817 (2026-10-19): Decision 2, the IDP-scoped shared
correlation cap, is approved in principle. Its measured maximum IDP value
reduction of about 70.1% needs **independent validation before activation**.
D2 activates (flag `idp_shared_correlation_cap` default ON) only if **every gate
G1–G5 passes**. Otherwise it ships default OFF, and the results record names each
gate that failed. Independence standards are not weakened to avoid value movement.

This file holds the criteria and the exact procedure. It was committed **before any
gate result was computed**, and its criteria are not edited afterwards. Results go
to a separate record:

* `docs/sources/evidence/D2_EVIDENCE_GATE_2026-10-19/results.json`;
* the D2 section of `docs/sources/IDP_SOURCE_INDEPENDENCE_CLOSEOUT_2026-10-18.md`.

If an input turns out to be unavailable, or a procedure step cannot run as written,
the results record that as a **deviation**, together with its consequence for the
gate. The criterion itself is not rewritten. The coordinator's gate wording
(G1–G5) is quoted first under each gate; the operational procedure follows.

Agent-OS-Receipt: cdca1dca8385f70c0989302dece8d1bd4ce4843c

## Builds and boards

The flag set has four switches. Three are the closeout decisions: D2
`idp_shared_correlation_cap`, D3 `idptc_offense_vote_excluded` and D4
`dlf_values_rank_hill_vote`. The fourth, TW `two_way_alt_evidence_rules`, is the
two-way boost's voting-evidence defect fix, which is split out of D2 on this PR.
D5 is the `fantasyProsIdp` freshness style in `config/sources/freshness_v1.json`;
it is config, not a flag.

* **Baseline** = D2 off, D3 off, D4 off, TW **on**, D5 as configured.
* **Treatment** = baseline plus D2 on.
* So "under D2" means treatment versus baseline, with exactly one switch changed.

Every build goes through the canonical pipeline: `build_api_data_contract`, using
`src/api/value_replay.build` for archive replays. Boards:

* **B-golden**: `tests/fixtures/golden/input_export.json.gz` with the working tree's
  `CSVs/site_raw` and `data/scrape_state`. These are identical to merge base
  `ef91a6cc0c`. The board is dated 2026-08-04, so on it both D2 members vote on
  defensive rows.
* **B-current**: the newest complete archive
  (`tests/archive_fixtures.newest_complete_raw_payload`, expected
  `dynasty_export_20261019_003315.zip`). It is replayed through the contract's
  `csv_root` seam on the closeout convention: `CSVs/site_raw` and
  `data/scrape_state` as committed by the commit that added the archive, overlaid
  with the archive's own `site_raw`. Two variants:
  * **B-current-prod**: production freshness weighting (expected: The IDP Show
    withheld);
  * **B-current-engaged**: `source_freshness_weighting` off, so both D2 members vote
    at base weight. This is the state on the day the vendor republishes; the
    closeout tests use the same state.

## G1 Lineage

> The IDPTC IDP board and the IDP Show IDP-only board have the same order
> (Spearman ≥ 0.99 and ≥ 95% identical relative order) on every archived board
> since 2026-10-10 where both are present, and on the current board.

**Boards.**

* Every `exports/archive/dynasty_export_YYYYMMDD_*.zip` with `YYYYMMDD ≥ 20261010`.
  * IDPTC is the archive's `site_raw/idpTradeCalc.csv`.
  * The IDP-only Show board is `CSVs/site_raw/idpShow.csv` in the tree of the
    commit that added the archive (closeout replay convention; archives do not
    carry it).
* Plus the current board: the working tree's `CSVs/site_raw/idpTradeCalc.csv` and
  `CSVs/site_raw/idpShow.csv`.
* "Both present" means both files exist with at least one row. A board where either
  file is missing is reported as not present and skipped.

**Join.**

* Players are matched by `data_contract._canonical_match_key(name)`.
* IDPTC keeps its highest value per key. The Show board keeps its best (lowest) rank
  per key, since it lists some players twice.
* Only keys present in both boards count, so this is the IDP subset of the
  full-roster IDPTC board.

**Order.**

* IDPTC orders players by value, descending; Show orders them by rank, ascending.

**Statistics, on the common set.**

* Spearman ρ, with average ranks for ties.
* Identical relative order: the share of unordered player pairs, among pairs not
  tied in either board, that both boards order the same way.

**Pass.**

* Every present board must have ρ ≥ 0.99, an identical-order share ≥ 0.95, and a
  common set of n ≥ 100 (a third of a ~300-row IDP board). A board below n = 100
  cannot evidence identical order and fails.
* G1 passes only if every present board passes.

## G2 Mechanism

> Every row moved by more than 10% under D2 moves ONLY because its independent
> lineages collapse to one and the existing single-source haircut applies, exactly
> as for a real one-lineage row. No row moves for any other reason. Enumerate all
> rows moved by more than 30%: show each one's sources, lineages before and after,
> and the arithmetic.

Evaluated on **B-golden** and **B-current-engaged**. A move is any row whose
`rankDerivedValue` differs between baseline and treatment, with relative size
`|Δ| / baseline`.

**G2a. Every moved row is reached by D2.** Each moved row must be one of:

1. a defensive row with non-empty `sharedLineageCaps` in the treatment;
2. a pick row whose `pickValueProvenance.class` is `rookie_pool_tether` or
   `alias_suppressed` (the closeout's explained-tether rule);
3. a two-way row (`_TWO_WAY_PLAYERS`) whose treatment `twoWayPlayerBoost` has
   non-empty `sharedLineageCaps`.

Any other moved row fails G2.

**G2b. Every row moved by more than 10% is the collapse plus the haircut.**

* For a **defensive row**, all of the following must hold:
  * baseline present lineages ≥ 2. Present lineages are the registry families of
    the voting sources plus the `freshnessExcludedSources`;
  * treatment present lineages = 1, counted on the D2 map: the two members are
    group `idpShow`;
  * baseline `singleSourceValuePenaltyApplied` is falsy, and the treatment one is
    true;
  * treatment `rankDerivedValue` equals `round(0.30 × C)` within ±2, where
    `C = anchorValue + alphaShrinkage × (subgroupBlendValue − anchorValue)`, read
    from the treatment row's own pre-haircut stamps. When `subgroupBlendValue` is
    null, `C = anchorValue`. ±2 absorbs the stamps' integer rounding. 0.30 is
    `_SINGLE_SOURCE_VALUE_RETENTION`, the factor a real one-lineage row takes.
* For a **two-way row**, all of the following must hold:
  * baseline audit `lineages` has ≥ 2 entries;
  * treatment audit has exactly one `lineages` entry, non-empty
    `sharedLineageCaps` and `singleSourceValuePenaltyApplied` true;
  * `altFamilyValue` = `round(0.30 × altFamilyValueBeforePenalty)` within ±1;
  * published value = `max(altFamilyValue, primaryFamilyValue)`.
* A **pick row** moved by more than 10% fails G2b.
* Every row moved by more than 30% is listed in the results with:
  * voting and withheld sources in both builds;
  * present lineages in both builds;
  * `C`, `0.30 × C` and the published value.

G2 passes only if G2a and G2b hold on both boards.

## G3 Independent reference

> On the affected IDP rows, rank agreement with references that do not vote must
> be no worse after D2 than before (Spearman difference ≥ −0.02), measured
> separately against each available reference: DLF IDP (held), Signals IDP
> families (held, if present in the archive), FantasyPros IDP (if not in the
> IDPTC/Show lineage). Report coverage n. If no independent reference covers at
> least 20 affected rows, G3 is UNEVALUABLE, which counts as FAIL.

Evaluated on **B-golden** and **B-current-engaged**.

**Affected rows.**

* Defensive rows with non-empty `sharedLineageCaps` in the treatment and a positive
  `rankDerivedValue` in both builds.

**References.**

* **R1, DLF IDP (`dlfIdp`).** Held by owner policy, so it does not vote.
* **R2, Signals IDP (`signalsIdpDl`, `signalsIdpLb`, `signalsIdpDb`).** Held; these
  are private, box-local boards. Used only if present on rows, with each row taking
  its own family's rank.
* **R3, FantasyPros IDP (`fantasyProsIdp`).** Eligible because
  `config/sources/source_lineage.json` records no relation between it and
  `idpTradeCalc`, `idpShow` or `idpShowCombined`. It **votes**, but it is outside
  the merged lineage and D2 leaves its vote unchanged. The results label it a
  voting reference with independent lineage.

**Reference rank.**

* Each reference's rank comes from the row's `sourceOriginalRanks[key]`.
* When that is absent, the rank is decoded from the synthetic
  `canonicalSiteValues[key]`.

**Statistic.**

* Spearman ρ between `rankDerivedValue` and the negated reference rank, with
  average ranks for ties.
* It is computed on the identical row set in both builds: affected rows that the
  reference covers. That set's size is the coverage n.
* Δ = ρ(treatment) − ρ(baseline).

**Pass.**

* On each board, at least one reference must have n ≥ 20; otherwise G3 is
  UNEVALUABLE on that board, which is a FAIL.
* Every reference with n ≥ 20 must have Δ ≥ −0.02.
* References with n < 20 are reported and do not decide.
* G3 passes only if it passes on both boards.

## G4 Rollback

> All flags off (the three closeout flags plus the new one) is byte-identical to
> main on the golden board and the newest-archive replay.

"Main" is merge base `ef91a6cc0c`, built from a temporary worktree of that commit.
"All off" means D2, D3, D4 and TW off.

**G4-a1: D5 style unset as well** (the closeout's "all four decisions off"
baseline). Two checks:

* B-golden: `scripts/board_diff.py` reports 0 values, 0 ranks and 0 labels.
* B-current-prod: every row's `rankDerivedValue`, `canonicalConsensusRank`,
  `canonicalTierId`, `confidenceBucket`, `confidenceLabel` and source-key set is
  identical.

**G4-a2: D5 as shipped.** On both boards:

* values, ranks and tiers are identical;
* every label difference is a confidence label on a row where `fantasyProsIdp`
  votes or is withheld.

G4 passes only if a1 and a2 hold on both boards.

## G5 Contract

> `validate_api_contract` structural and full lanes pass with D2 on. No new zero,
> unpriced or quarantine rows. Picks move only by an explained tether.

* **CLI lanes.** With `RISKIT_FEATURE_IDP_SHARED_CORRELATION_CAP=1`, both
  `scripts/validate_api_contract.py --lane structural` and `--lane full` exit 0 on
  their default input.
* **Row checks**, on B-golden, B-current-prod and B-current-engaged, comparing
  treatment with baseline:
  * no row priced in the baseline becomes unpriced (`rankDerivedValue` null) or 0;
  * no row becomes `quarantined`;
  * every moved pick carries the provenance class `rookie_pool_tether` or
    `alias_suppressed`;
  * `validate_api_data_contract(treatment)` has `structurallyOk` true, and its
    `sourceHealthErrors` equal the baseline's.

G5 passes only if every check holds.

## Release properties (required regardless of D2's default)

These come from the coordinator's split of the two-way fix out of D2:

* **P-a.** This is G4.
* **P-b.** With The IDP Show quarantined (B-current-prod), D2 on versus D2 off moves
  0 values, ranks or labels, with TW on and with TW off.
* **P-c.** TW alone versus all four off:
  * moves exactly the two-way rows whose alt evidence a withheld, held or disabled
    source (or the one-lineage haircut) changes;
  * on B-current-prod that is expected to be Travis Hunter alone;
  * on B-golden it is expected to be none.
  * Every moved row must be in `_TWO_WAY_PLAYERS`.

## Decision rule and reporting

* All of G1–G5 PASS: D2 defaults ON.
* Any gate FAILS or is UNEVALUABLE: D2 defaults OFF. The results record each failing
  gate, and the code and the rollback stay in place for a later release.
* Results are produced by `scripts/d2_evidence_gate.py`, committed after this file.
  Each result carries the code SHA, the archive and payload hashes, and the flag
  states of every build.
* `board_diff` is run for each flag alone and for the final default combination, on
  B-golden and B-current-prod. Every extreme mover is investigated in the closeout
  record.
