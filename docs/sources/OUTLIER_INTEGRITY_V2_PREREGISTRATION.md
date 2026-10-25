# Outlier integrity v2: preregistration

**Registration only.** This document, the frozen population manifests under
`outlier_integrity_v2/manifests/` and the root-cause reproduction under
`outlier_integrity_v2/rootcause/` are committed **before** outlier-integrity-v2 ("V2") has
been implemented in the pipeline or evaluated on any board of the frozen populations. No V2
drop set, hold, quarantine, consensus, adversarial pass rate, stability figure or bootstrap
has been computed on any of them. **The criteria below may not change after this commit.**
If a definition must change, the change is reported as a deviation beside the original
(§16); the original rule is never silently replaced, and a deviation that loosens a gate
makes the run ineligible for a READY FOR APPROVAL verdict.

**V1 stands unchanged.** The preregistration of `outlier-corroborated-v1`
(`docs/valuation/evidence/outlier-disagreement-2026-10-19/PREREGISTRATION.md`, commit
`b579a5fdd5`) and its verdict, **NOT ELIGIBLE**, are not reinterpreted, re-scored or
re-labelled by anything here. In particular, V1's 22 rookie-board screen firings remain false
positives under V1's frozen rule. This document labels the same boards differently **for V2
only** (§8), with the label fixed before V2 is run.

**Held-out data is evaluated once** (§5.3, §16).

Authority: owner implementation directive 2026-10-20, "Fix the outlier filter and restore
DLF IDP voting", including its binding 10:20 UTC addendum (hold D4 for V2; D4 is a second
restoration target). The directive is recorded verbatim as
`docs/owner/OUTLIER_INTEGRITY_V2_DIRECTIVE_2026-10-20.md` by PR #1817 (open at this commit).
Also binding: the owner's Option 3 decision of 2026-10-20 (keep `dlf_offense_only_vote` ON;
never enable DLF IDP or V2 in production; activation only on explicit owner approval) and
the valuation invariants in `CLAUDE.md` (one canonical owner, missing is never zero, signal
independence, champion ≠ challenger, family caps). This document authorizes no activation.

Design: [`OUTLIER_INTEGRITY_V2_ARCHITECTURE.md`](OUTLIER_INTEGRITY_V2_ARCHITECTURE.md) (each
layer and why). Repo preregistration pattern followed:
`docs/valuation/evidence/joint-filter-shadow-2026-10-01/PREREGISTRATION.md` and its
successors.

Agent-OS-Receipt: cb64f74cf4d2763aa16d55ba0d6350f585a2a42f

---

## 0. What was seen before registration (disclosures)

None of the following is a V2 outcome on a frozen population, but each informed the design
and is declared so that no later reader mistakes it for independent evidence.

1. **Root cause** (`outlier_integrity_v2/rootcause/`): boards A / B / B-without-IDP-filter on
   pin2015 and pin0527 under the incumbent. 31 legitimate votes on 30 IDP rows dropped when
   DLF IDP votes (Draft Sharks 18, FantasyPros 10, IDP Trade Calculator 3); n = 4 MAD
   collapse; 1,000-point floor binding on 21 of 30 rows; DLF's own vote ≤ 5.5%.
2. **Candidate feasibility numbers** for all three designed candidates (structure-first,
   corroboration-first, reliability-prior) were computed on **pin2015 and pin0527**, including
   the nearest-other-provider distances of the 31 protected votes (maximum 1.17 in the vote
   coordinate). The Layer C floor τ_C ≥ ln 4 = 1.386 (§3.3) was chosen **knowing** those
   distances. pin2015 and pin0527 are therefore **must-pass constraints, never evidence**
   (population R, §5).
3. **The historical scan** (`manifests/HISTORY_CASES.json`) read 149 archives descriptively —
   including every V_HELDOUT board — to locate and label known failures. That is how the
   third IDP Trade Calculator episode (2026-10-16 13:40) was found. **V_HELDOUT is therefore
   not design-blind**: its labelled episodes (H2 boards; the October H3 rows) are stress tests
   labelled before design, not independent evidence. Every V_HELDOUT board was also part of
   V1's frozen 105-board evaluation population.
4. **V1's committed results** (`outlier-disagreement-2026-10-19/README.md`): M7 gate rates
   AD1a 93.7%, AD1b 58.3%, AD1c 97.9%, AD1d 92.6%, AD2 15.0%, AD4 100%, AD3 15/16; P1
   −0.0021; M4 1.014; 22 board-screen firings on the H1 boards.
5. **PR #1817's D4 measurement**: with `dlf_values_rank_hill_vote` ON the incumbent newly
   drops other sources' votes on 13 (current) / 14 (golden) offense rows; Theo Johnson
   −7.4% (Draft Sharks 3182 dropped).
6. The only boards with **no design contact of any kind** are the 7 I_INDEPENDENT boards
   (§5) and every archive added after this commit (the prospective shadow window, §5.4).

## 1. Question

> Does a layered validation pipeline — identity (A), source and normalization integrity
> (B), a scale-free legitimate-disagreement rule (C), and the unchanged confidence owner (D)
> — keep every legitimate vote the incumbent wrongly removes when DLF IDP, DLF Rookie IDP or
> DLF Values (D4) vote, while catching corrupted, misidentified, mis-normalized and
> malformed observations at the directive's §5 rates, without being less accurate or less
> stable than the incumbent?

## 2. Candidate and comparators

### 2.1 How the candidate was chosen (before any frozen-population evaluation)

Three designs were scored by an independent judge against the directive (1–10 per
criterion; "false-negative risk" scored so higher means lower risk):

| criterion | structure-first (V2) | corroboration-first | reliability-prior |
|---|---|---|---|
| §2 layering | 9 | 9 | 8 |
| §5 thresholds | 7 | 5 | 7 |
| §6 keeps all 31 votes | 9 | 10 | 8 |
| false-negative risk | 7 | 5 | 7 |
| interpretability, determinism | 8 | 5 | 6 |
| uses evidence that exists | 7 | 6 | 8 |
| fit with the one canonical pipeline | 8 | 7 | 6 |
| minimal change to approved parts | 7 | 6 | 6 |
| **total / 80** | **62** | **53** | **56** |

The registered candidate is **`oiv2-sf+`**: structure-first, with grafts from
corroboration-first (payload-vs-CSV provenance, dependency propagation, provider-level
corroboration units, identity rules A2/A4/A5) and reliability-prior (B3a rank-mass
conservation; B4 "jump away from the reference"). Reasons are in the architecture document
§10.

### 2.2 Comparators (§7 of the directive)

| name | definition | role |
|---|---|---|
| **incumbent** | `data_contract._hampel_filter_per_player` (K 2.75, MAD, floor 1,000, n ≥ 4), unchanged | champion |
| **V1** | `outlier-corroborated-v1` (`outlier_disagreement_policy` ON), unchanged | prior challenger, reported |
| **V2** | §3, primary configuration (§3.6) | candidate |
| **V2-NOHIST** | V2 with the history lane empty: A + B0/B1/B2/B3b-direction + C cold-start rule | isolates history dependence; also the no-history gate variant (§7.1) |
| **V2+D1** | V2 with `integrity_holds_as_withheld` ON | separate evaluation of the confidence change D-1 (reported; activation separately owner-reserved) |
| **V2-RPC** | V2 with Layer C replaced by reliability-prior per-family error cells | scientific comparator only; never a candidate |

## 3. Algorithm (registered)

Coordinate: every non-pick vote v maps to **u = ln(10 + 500·p)** with
p = c·(9999/v − 1)^(1/s) on the row's scope master (IDP rows the IDP master, every other row
the OFFENSE master), as in V1. For rank-signal sources the effective-rank percentile is used
directly. A non-positive or non-finite vote has no coordinate and is never assessed or
dropped by C (it may still be refused by A or B on non-statistical grounds).

Order: freshness / health weighting → **A** → **B** → **C** → existing B10 family cap →
existing count-aware blend → **D** (existing confidence owner).

### 3.1 Layer A — identity (`identity_evidence_v2`)

Inside `src/identity/resolution.py::match_row_to_source_entry`; no second matcher, no fuzzy
rung on the board path. Inputs added by U1 (parse tuple carries published position, team,
age, vendor id, Sleeper id, rookie class, raw display name) and, where present, U2 stamps
(matching rung, page position, acquisition path, SF/TEP toggle state).

Verdicts, first match wins:

| verdict | conditions | effect |
|---|---|---|
| CONTRADICTED | A1 Sleeper / vendor id resolves to a different canonical player; A2 the raw name re-resolved through the owner gives a different player; A3 incompatible position group (allowed: CANONICAL_V2 group drift, EDGE ↔ DL/LB, `_TWO_WAY_PLAYERS` with #1817's alt-evidence rules); rookie-board entry outside that board's class; published age − Sleeper age > τ_age | refused (absent) |
| UNRESOLVED | A4 two entries of one source collapse on one key without disambiguating id / position / team (both refused; replaces "keep the higher value"); same-group Sleeper homonyms indistinguishable by the source; A5 fuzzy or surname rung without agreement on position AND (team OR id); team-only mismatch with no continuity in the source's own history | refused (absent), labelled held |
| VERIFIED | an id agrees, or name + position group + team agree | votes |
| NAME_ONLY | none of the above evidence available | votes, stamped `voting_name_only_identity` |

### 3.2 Layer B — source and normalization integrity

* **B0 format** (fixed rules, no statistics): existing `dataset_integrity` FAILED; schema /
  column error; non-numeric value where a value is declared; for value-plus-rank CSVs, vendor
  rank-vs-value Spearman ≠ −1 (FantasyPros IDP exempt). Blank / zero value columns of
  rank-signal sources (DLF, Yahoo/Boone) are never read as values.
* **B1 structural normalization** (`rookie_ladder_fail_closed`): a `ROOKIE_LADDER_PAIRS` vote
  whose method is not `rookie_ladder_translation_*` → withheld `normalization_untranslated`;
  IDP shared-market vote without a bridge → withheld (as today); value-direct source without
  a registered conversion → withheld; any vote translated through a B-quarantined backbone or
  ladder → `normalization_dependency_unavailable` (via `scale_integrity_lost` declarations).
* **B2 feed provenance** (`payload_provenance_guard`), for sources with payload and same-run
  CSV copies (idpTradeCalc, ktc, ktcSfTep): per position group,
  m_g = median ln(payload / CSV) over overlapping players with value ≥ 100.
  * board proof: (|m_g| > ε in ≥ 2 groups, each with ≥ 15 overlapping rows and ≥ 80% of rows
    sharing m_g's sign) OR a U2b stamp of SF or TEP off on any fallback capture;
  * row proof: |ln(payload / CSV)| > ln 2;
  * supporting only (never sufficient): payload count < 0.6 × trailing-5 median, fallback
    share > 0, `siteRawPreserved`;
  * on proof: proven payload values are absent; the existing CSV-fill rule supplies the CSV
    value, aged by freshness; no CSV → withheld.
* **B3 segment integrity**, baseline = median of the source's previous 3 accepted boards:
  * **B3a conservation** per (source, asset class): |Δ median residual vs leave-source-out
    reference| ≥ max(6·τ_board, ln 1.25) → `normalization_scale_error` (hard);
  * **B3b** per (source, asset class, position group) with n ≥ n_min: Spearman vs
    leave-source-out consensus ≤ ρ_min → `normalization_direction_error` (hard, needs no
    history); |median signed deviation − baseline| ≥ τ_gross → `normalization_scale_error`
    (hard); any smaller shift → kept + `segment_break_unproven` + advisory, unless B0/B1/B2
    proof exists for the same source build, in which case quarantined;
  * release only when the evidence returns within bounds; picks report-only.
* **B4 continuity** (needs the `source_rank` history lane, U4): an observation is **held**
  (`held_pending_confirmation:observation_discontinuity`) iff all of: (1) |Δu| vs the median
  of the source's last 3 accepted observations of the player > τ_c(source, depth band);
  (2) |u_now − ref| − |u_prior − ref| ≥ ln 1.5 and |u_now − ref| ≥ ln 2, ref = leave-provider-
  out reference; (3) no other provider within ln 1.25 of u_now; (4) no other provider's Δu has
  the same sign and ≥ 0.5 × the size. No prior observation → B4 abstains. Release: the next
  content-distinct fetch reproduces the value within τ_c, or another provider co-moves or
  comes within ln 1.25, or a cap of 2 content-distinct fetches / 48 hours (then the vote
  counts and a source-health alert is raised).

### 3.3 Layer C — legitimate disagreement (master flag `outlier_integrity_v2`)

Remove vote o only if ALL hold:

1. ≥ 3 providers on the row (`src/sources/source_census.provider_of`, from
   `config/sources/source_lineage.json`);
2. a corroborated reference: ≥ 2 providers other than o's, each within ln 2 of another of
   them, not formed solely by a translated vote and its own declared translation backbone;
3. min distance from u_o to any vote of another provider > τ_C;
4. o is not persistence-confirmed (≥ 2 consecutive accepted observations of this source for
   this player within τ_c of u_o);
5. o's family holds < 0.5 of the row's family-capped weight;
6. ≥ 2 providers survive (otherwise nothing is dropped on the row).

Simultaneous, pairwise, order-free. No MAD, no row-estimated scale, no 1,000-point floor.
Kept votes with nearest distance > ln 2 are stamped `kept_dissent`.

### 3.4 Layer D — confidence

`src/api/confidence.py` and `config/confidence/gate_v1.json` unchanged. A/B/C exclusions keep
the family eligible (coverage can only fall). The B11 lost-evidence replay uses V2. D-1 is
the separate comparator V2+D1.

### 3.5 Constants

**Fixed now (a priori):** coordinate offset 10 and N 500; corroboration distance ln 2; B4
away-from-reference ln 1.5 and ln 2; cross-sectional release ln 1.25; co-movement 0.5;
hold cap 2 content-distinct fetches or 48 h; persistence ≥ 2; dominance 0.5; ≥ 2 providers
survive; B2 row threshold ln 2, ≥ 15 rows, ≥ 80% sign, value ≥ 100; coverage support
0.6 × trailing-5 median; B3a floor ln 1.25 and multiplier 6; history window 3; τ_C hard floor
ln 4 (declared in §0.2 as derived from a contaminated board).

**Selected on E only** (E_BASELINE for baselines, E_DEV for every selection), with the
rule fixed here:

| constant | grid | selection rule |
|---|---|---|
| τ_age | {1, 1.5, 2} years | smallest value with 0 CONTRADICTED verdicts on Sleeper-id-verified joins over E_DEV |
| ε (B2) | {0.01, 0.02, 0.05} | smallest value with no board proof on any E board where the source's payload and CSV are from the same healthy capture (E_DEV and E_BASELINE excluding H3/H4 boards) |
| τ_board (B3a) | — | per (source, class): standard deviation over E_DEV of the class median residual; fire at max(6·τ_board, ln 1.25) |
| n_min, ρ_min, τ_gross (B3b) | n_min ∈ {10, 20}; ρ_min ∈ {0.0, 0.3}; τ_gross ∈ {ln 3, ln 4} | among settings with zero clean E_DEV segments flagged hard (H1 boards excluded from "clean"; N1/N2 boards included) and 100% of the E_DEV source-split AD3-style injections caught, the most conservative (largest n_min, smallest ρ_min, largest τ_gross, in that priority); no feasible setting → the lane records FAILED_SELECTION and the run cannot reach READY |
| τ_c(source, band) | k_c ∈ {4, 6, 8}; bands ≤ 50 / 51–150 / 151–400 / > 400 | τ_c = max(ln 1.5, k_c × 1.4826 × MAD of the source's own consecutive same-player Δu over E); choose the smallest k_c whose false-hold rate is ≤ 0.5% of votes on every clean E_DEV board, maximizing E-injection catch; none feasible → k_c = 8 and the false-hold criterion (§11 item 8) decides |
| τ_C | {ln 4, ln 5, ln 6} | the LARGEST value catching ≥ 95% of material cold-start ×20 and ×0.05 injections on E_DEV (seed 20261020); never below ln 4 |

E_DEV injections for B3 use **non-registered sources only** (dlfSf, draftSharksSf,
fantasyProsSf, ktcCrowdSfTep, idpTradeCalc offense, draftSharksIdp, idpTradeCalc IDP); the 4
AD3 sources (dynastyNerdsSfTep, flockFantasySf, fantasyCalc, fantasyProsIdp) are held-out
sources and are never injected during selection. Selection seed: **20261020**, E_DEV only.

The selected values are committed in `outlier_integrity_v2/FROZEN_THRESHOLDS.json` (Stage 2,
§5.3) with the E evidence that chose them, **before** any V, I or R run.

### 3.6 Primary evaluated configuration

`outlier_integrity_v2`, `identity_evidence_v2`, `payload_provenance_guard`,
`rookie_ladder_fail_closed`, `source_rank_history_record` **ON**; `integrity_holds_as_withheld`
**OFF** (D-1 is V2+D1). Every other flag at release defaults with the pins of §6. Evaluating
a configuration in replay requires no owner decision; activating any of these flags does
(§15). Where U2 / U2b / U3 stamps do not exist in an archive (every archive today), the
corresponding evidence is absent and the layer behaves as if the field were unpublished —
never inferred.

## 4. Assumptions

1. The archives' `site_raw` CSVs are the vendor's own preserved boards for that run; payload
   values are scraper-side observations (both as used by `value_replay.build`).
2. A correctly normalized rank board only redistributes rank mass between players (B3a).
3. A vendor's real view reproduces on the next content-distinct fetch, or other providers
   co-move with news; a transient fault reverts (B4 holds).
4. Declared translation lineage (`ROOKIE_LADDER_PAIRS`, the IDP shared-market crosswalk) is
   complete: a translated vote and its backbone are not independent corroboration.
5. Provider identity from `source_lineage.json` is correct; an unrecorded provider fails
   closed (the row's provider count does not count it as independent).
6. Today's code with historical inputs approximates, but is not, production history (the
   standing replay limitation).
7. A refused or held observation is absent evidence, never zero and never another player's
   value.

## 5. Populations, manifests and order of work

### 5.1 Frozen populations

Built by `outlier_integrity_v2/manifests/build_manifests.py --at 1511ca1d08` (read-only over
git objects; each board read from its add commit; the 140 boards of
`docs/valuation/evidence/idp-outlier-n3-2026-10-18/ARCHIVE_MANIFEST.json` hash-checked;
completeness of later boards by the same rule, `tests.archive_fixtures._degraded_critical_sources`).
`--check` reproduces the committed files byte for byte.

| population | boards | contents | use |
|---|---|---|---|
| **E_BASELINE** | 35 | every incomplete frozen board, 2026-07-14 → 08-17 (KTC_TradeDB / WaiverDB degraded) | history, continuity and τ baselines only; never scored |
| **E_DEV** | 44 | complete frozen boards 2026-08-18 → 09-30 | ALL threshold selection; holds H1 (22 boards), H5, N1, N2, N3 |
| **V_HELDOUT** | 61 | complete frozen boards 2026-10-01 → 10-18 (5 pruned from the tree, recovered from their add commits) | evaluated **once** with frozen thresholds; registered gate board `dynasty_export_20261018_114711` (seed 2033), prior `20261018_051224`; H2 / October H3 are stress tests, not independent evidence |
| **I_INDEPENDENT** | 7 now + prospective | `20261018_161125`, `_185952`, `_223931`, `20261019_003315`, `_140049`, `_235843`, `20261020_052241`; plus every archive added after this commit through the shadow window (§5.4) | final confirmation |
| **R_REGRESSION_PIN** | 3 pins | pin2015 (`dynasty_export_20261019_201546`, refresh `d9680440a5`, payload `3ef54acd…`); pin0527 (refresh `eb10d3e12d`, payload `b639608f…`, the same scrape as the excluded board); D4 on the newest I board | must-pass constraints only; never fit, never evidence |
| **EXCLUDED** | 1 | `dynasty_export_20261019_052349` | V1's diagnosis board |

Manifest file hashes are in Appendix A. Labelled historical cases (fixed now) are in
`manifests/HISTORY_CASES.json`; the regression set (the 31 IDP votes and the D4 rule) is in
`manifests/REGRESSION_SET.json`.

A missing or hash-mismatched board makes a run incomplete and is reported as such; it is
never silently replaced.

### 5.2 Seeds

Selection: **20261020**, E_DEV only. Registered gates: **2033**, on the V gate board and on
the newest I board, exactly as V1 (one voting source per row and case).

### 5.3 Stages (each a separate commit; the order is part of the registration)

| stage | content | may read |
|---|---|---|
| 0 | this preregistration | — |
| 1 | implementation behind default-OFF flags; unit and property tests on synthetic rows only; E development | synthetic, E |
| 2 | **threshold freeze**: `FROZEN_THRESHOLDS.json` + E selection evidence | E |
| 3 | R constraints (boards A–D, A′–D′, §6), scenario matrix, OFF-state byte identity, identity parity; D4 regression membership committed | R, synthetic |
| 4 | **one** V_HELDOUT + I(7) run at one code SHA with a clean tree; every record and result committed as produced | V, I |
| 5 | prospective shadow window ≥ 10 days, report-only; new archives appended to I with add-commit SHA and hashes; final M1 / M4 and the gate replication on the newest I board | I |
| 6 | verdict (§11), independent fresh-context review, owner decision packet | all |

Rules: no threshold or rule change after Stage 2. Stage 4 is run once; a rerun is allowed
only for an infrastructure failure (crash, incomplete record, hash mismatch) at the **same**
code SHA and thresholds, and the failed attempt is reported. Any decision-affecting code
change after Stage 2 spends this registration: the verdict can be at most MORE RESEARCH
REQUIRED, and a successor needs a new preregistration and fresh held-out boards. Bug fixes
that are byte-identical on every E and R decision are allowed and listed.

### 5.4 Prospective shadow window

From this commit's timestamp, every archive added to `main`'s `exports/archive/` that is not
in these manifests joins I_INDEPENDENT with its add-commit SHA, zip and payload sha256, and
completeness by the same rule. The window lasts at least 10 calendar days and closes at the
first daily boundary after that on which Stage 5 is run. Report-only: V2 never serves a value.

## 6. Builds, records and the §6 comparison boards

* **Rebuild procedure** (inherited, joint-filter preregistration §2): each board's payload;
  `CSVs/site_raw/` as committed with that archive overlaid with the archive's own
  `site_raw/`; per-source dataset state replayed from git history; freshness at the payload's
  `scrapeTimestamp`; `value_replay.build` → `build_api_data_contract(csv_root=…)`; one code
  SHA, clean tree; sharded, sequential builds (moderate memory).
* **Pinned flags on every build**: `source_freshness_weighting` ON, `source_family_cap` ON,
  `idp_deep_tail_native_challenger` OFF, joint / sparse / rank-space / per-vote / n3
  challengers OFF, release defaults otherwise.
* **History lane** for V2 builds: rebuilt from the archive sequence in chronological order
  (all manifest boards up to but excluding the evaluated board, degraded sources excluded),
  using V2's own acceptance decisions. Never read from production.
* **Record schema `oiv2-replay/v1`** (gitignored ledger, one record per board and build):
  code SHA + clean-tree flag, payload sha256, CSV and state tree hashes, flag snapshot, every
  constant, and per vote: source, provider, family, value, u, path, method, raw and effective
  rank, match decision and identity fields, payload and CSV copies, history baseline, every
  layer's verdict and reason, effective weight.

### 6.1 Comparison boards (identical frozen data, payloads, weights, configuration)

| board | DLF IDP (`dlf_offense_only_vote`) | D4 (`dlf_values_rank_hill_vote`) | filter |
|---|---|---|---|
| A | held (ON) | OFF | incumbent |
| B | restored (OFF) | OFF | incumbent |
| C | restored | OFF | V2 |
| D | held | OFF | V2 |
| A′ | held | OFF | incumbent (= A at release defaults) |
| B′ | held | ON | incumbent |
| C′ | held | ON | V2 |
| D′ | held | OFF | V2 (= D) |
| B″ | restored | ON | incumbent |
| C″ | restored | ON | V2 |

Built on pin2015 and pin0527 (R) and, for A / D / C / C″, on every V and I board. D4 builds
need code containing `dlf_values_rank_hill_vote` (PR #1817); if that code is not on the V2
branch's base by Stage 3, every D4 board is reported **BLOCKED (dependency)** and D4
readiness is unanswered — the IDP comparisons proceed.

For every pair (B vs A, C vs A, C vs B, D vs A, B′ vs A′, C′ vs A′, C″ vs A), report: votes
retained and rejected by source and asset class; every changed exclusion reason; value
changes (rows, median / p90 / p99 / max |Δ| by class); confidence bucket and axis changes;
source coverage and family representation; offense, IDP, two-way rows (Travis Hunter via
#1817's `_two_way_alt_center` routed through the V2 dispatcher), derived pick values
(including tethered current-year slots). Focus rows, each with the votes used before and
after, the votes the incumbent wrongly removed, and why V2 retains or rejects each: Trevin
Wallace, Myles Garrett, Aidan Hutchinson, CJ Allen, T.J. Watt, Josiah Trotter, Will
Anderson, Danielle Hunter, Jared Verse, Theo Johnson.

## 7. Adversarial gates and injection protocols

Built through the replay harness on the registered gate board with the complete layered
system (A + B + C + history), as directive §5 requires; the per-row emulator of V1 §4 is not
used for V2's gate decisions. Source rows: every row with ≥ 3 voting families on the gate
board. A case is **material** when |ln V_none(corrupt) − ln V_none(clean)| ≥ 0.10 (V_none = no
filter). V2 **passes** a case when the corrupted observation is excluded or held by any layer,
or |ln V(corrupt) − ln V(clean)| < 0.10.

### 7.1 History variants

| variant | history lane state for the corrupted source | status |
|---|---|---|
| **NO-HISTORY** | empty for every source (V2-NOHIST) — the conditions of V1's fixture | **gate of record** unless O-1 is recorded (§12) |
| **ARRIVING** | holds the source's clean observations from the prior manifest boards | gate only if O-1 is recorded before Stage 4; always reported |
| **PERSISTENT** | the same corruption also injected into the prior 3 boards | reported |

### 7.2 Cases

| id | corruption | bar (directive §5) |
|---|---|---|
| AD1a | one vote ×5 (cap 9,999) | ≥ 90% |
| AD1b | one vote ×0.2 | ≥ 90% |
| AD1c | one vote ×20 (cap) | ≥ 95% |
| AD1d | one vote ×0.05 (floor 1) | ≥ 95% |
| AD4 | single-source spike: consensus rank 150–400, one vote set to 9,000 | ≥ 95% |
| AD2 (as registered) | the vote replaced by the same source's vote for a player ≥ 100 consensus ranks away, no identity evidence | ≥ 90% — **gate of record unless O-2 is recorded**; missing evidence documented |
| AD2-ID | the swapped entry carries the swapped player's own published non-name fields (position, team, age, ids as that source publishes them); its name forced to the target's canonical name | ≥ 90% — gate only if O-2 is recorded before Stage 4; always reported, with name-only sources separately |
| AD2-SUR | a surname-rung capture with page position | reported |
| AD2-N | a real Sleeper same-group homonym pair | must be refused, never attributed (100%) |
| AD3 | 4 sources (dynastyNerdsSfTep, flockFantasySf, fantasyCalc offense; fantasyProsIdp IDP) × {ranks ×2, ranks ×5, values ×0.01, order reversed within the covered rows} | 16 / 16 boards flagged before voting |
| INJ-H1 | on every V board, the rookie-ladder reference marked inactive | 100% of dlfRookieSf, flockFantasySfRookies, dlfRookieIdp votes withheld; 0 fires on unmodified boards |
| INJ-SEG | a value-direct source: 70% of payload rows given per-position shifts of random sign, \|0.1–0.3\| log; CSV keeps the true values (E_DEV for development, V for evaluation) | B2 board proof on 100% of injected boards |
| INJ-DUP | synthetic rows with identical translated values from different boards | no band narrows; property holds |

Per-board V rates are reported. **Every gate is run twice: on the registered V gate board
(Stage 4) and on the newest I board at the end of the shadow window (Stage 5); both must
pass.** The incumbent's and V1's rates on the same fixtures, by family count (3, 4–5, ≥ 6),
are reported beside V2's. E1 and E2 end-to-end checks (V1 §4) are reported; E1 is a no-op by
construction (dense re-ranking of rank boards) and is stated as such.

## 8. Labelled historical cases (fixed now; `manifests/HISTORY_CASES.json`)

| case | label | required V2 outcome |
|---|---|---|
| H1 rookie ladder untranslated (22 E_DEV boards) | hard positive (replay construct) — V2 label only; V1's verdict untouched | withheld by B1 on 22 / 22 boards |
| H2 IDPTC partial-fallback format switch (3 V boards) | hard positive, stress | B2 board proof on 3 / 3 |
| H3 IDPTC surname wrong-player (Aug 3 degraded, Oct 8, Oct 16) | hard positive | Justin Jefferson's payload vote excluded or held on every board where it occurs |
| H4 same fallback, correct values (Aug 3, Aug 6) | control | no value quarantined except the H3 row |
| H5 FantasyPros IDP anchored-extension instability | soft label | reported separately, never in hard metrics; expected `segment_break_unproven` |
| H6 FantasyPros IDP duplicate / colliding names | latent | A4 refusal rate reported, with a false-refusal audit |
| N1–N6 | controls | no hard quarantine (N1: kept or advisory) |

## 9. Correctness properties (unit and property tests; offense and IDP)

All mandatory, on synthetic rows unless stated:

1. 2 agree + 1 dissents; 3 agree + 1 dissents — the owner example IDPTC 5,000 / FantasyPros
   5,100 / DLF 5,000 / Draft Sharks 3,000 keeps Draft Sharks.
2. 4+ materially different opinions: all kept (no corroborated reference).
3. 1–2 providers: C abstains; only A and B apply.
4. Identical synthetic values from different rank boards: cannot narrow any band; numerical
   similarity never merges providers.
5. Sparse and deep-tail values.
6. An invalid source whose wrong values agree with another source: caught only with an A or
   B signature — asserted as the named residual (test documents the miss, never fakes a
   catch).
7. A valid consistently contrarian source: kept on every board.
8. Broken positional conversion; missing curve or ladder → fail closed.
9. Wrong-player matches (A1, A2, A3, A4, A5, homonym).
10. Transient feed fault: held, released per §3.2 B4.
11. Family caps: `cap_family_weights` output identical given the same surviving set;
    `_RANKING_SOURCES` weights, correlation groups, Hill constants, freshness policy, Package
    VA and `geom_q078_v1` byte-identical (hash test).
12. **Order independence**: permuting source order, row order and dict insertion order
    yields identical decisions; identical results across `PYTHONHASHSEED` values.
13. **Determinism**: two builds of the same input are byte-identical.
14. **Monotonicity (restated)**: in a row meeting C's guards 1, 2 and 5, adding any vote never
    turns a retain into a drop. **Duplicate property**: a duplicate value under a new provider
    never narrows a band.
15. Missing is never zero: a refused, held or withheld observation never contributes 0.
16. Math consistency: every published value lies within its surviving contributions' hull
    (the existing blend-integrity detector stays silent on V2 builds of R, V and I).
17. Transparency (directive §10): every excluded, held or withheld vote carries exactly one
    primary reason that maps to one §10 category through `src/sources/voting_status.py`
    (coordinated with PR #1831); no reason is emitted unless its layer tested for it; a vote
    that passed A and B is never mapped to an invalid-identity, format, normalization or
    broken-feed category.

## 10. Metrics (V1 definitions, reused unchanged unless stated)

* **M1** held-out-source agreement — V1 PREREGISTRATION §4 verbatim, with "policy" = V2, its
  decision on the reduced panel R recomputed with the held-out family removed everywhere
  (references, segment baselines' leave-source-out terms; the history lane is the source's
  own and unaffected). Primary horizon h = 7; 7-day date blocks; 4,000 resamples; seed 2033.
  **Origins: V_HELDOUT ∪ I_INDEPENDENT (final, after the shadow window); targets may fall in
  either.** E_DEV M1 is reported for development and decides nothing. P1 = mean over
  V2-disputed units of L_V2 − L_incumbent. Minimum sample: ≥ 300 V2-disputed units from ≥ 10
  origin days covering ≥ 4 week-blocks; otherwise INSUFFICIENT.
* **M3** fate of disputed observations (V1 §4), reported.
* **M4** board stability (V1 §4) on consecutive V ∪ I days; ratio Σ V2 / Σ incumbent with a
  block-bootstrap interval; IDP and offense reported.
* **M5 / M6** exclusion census by layer, reason, source, class and board; value changes V2 vs
  incumbent and V2 vs V1 on every board and on the newest I board. **Every V or I row moving
  ≥ 10% is attributed to a named vote change** (which votes, which layer, which reason).
* **Clean-board false exclusions**: on every V and I board not labelled H2/H3, the count of A
  refusals + B hard quarantines (votes) + C drops + B4 holds, excluding existing policy holds
  and freshness. An exclusion counts as true only when its record shows a deterministic
  contradiction (A1/A2/A3, B0, B1 or B2 proof) and the independent reviewer confirms it from
  the archive; every other exclusion counts as false.
* **Board-level false positives**: every B2 board proof, B3a or B3b hard quarantine on a V or I
  board that is not a labelled positive counts as a true positive only when that source's CSV
  or payload for that board shows a recorded structural change against its neighbouring
  boards (row count, rank range, value scale, provenance conflict) — V1's rule; otherwise a
  false positive.
* **Performance** on pin2015, sequential: V2-ON build wall time and peak RSS against the
  incumbent build; history lane size.

## 11. Acceptance criteria (all mandatory)

| # | criterion |
|---|---|
| 1 | §7 gates pass under the gate-of-record variants (§7.1, §12) on the registered V gate board **and** on the newest I board: AD1a ≥ 90%, AD1b ≥ 90%, AD1c ≥ 95%, AD1d ≥ 95%, AD4 ≥ 95%, AD2 (as registered, or AD2-ID under O-2) ≥ 90%, AD2-N 100%, AD3 16 / 16, INJ-H1 100% with 0 fires on unmodified boards, INJ-SEG 100% |
| 2 | §6: all **31** IDP votes of `REGRESSION_SET.json` retained in boards C and C″ on pin2015 and pin0527, and all D4-set votes retained in C′ and C″. A Layer C drop or a B4 hold of any of them is a failure; an A CONTRADICTED or B proven-invalid verdict on one is a failure unless an independent reviewer verifies its evidence from the archive (then it is reported as new, independently verifiable evidence of an invalid observation). Theo Johnson's Draft Sharks vote (3182) is in the D4 set by rule |
| 3 | H1 22 / 22 boards; H2 3 / 3; H3 caught on every board where it occurs; H4 not quarantined except the H3 row |
| 4 | N1–N6: no hard quarantine (with the frozen thresholds) |
| 5 | M1 meets the minimum sample and P1 upper95 ≤ +0.005 (non-inferior to the incumbent); M4 ratio upper95 ≤ 1.10 |
| 6 | OFF state: every new flag OFF → default board byte-identical to the base (`golden_board` + `board_diff --expect-no-value-change`); `CONTRACT_CSV_JOIN_V1` 24,024 / 24,024 parity; V1 OFF and its tests unchanged |
| 7 | every existing mandatory test passes (pytest hard gate, frontend, API contract structural lane), including `tests/api/test_outlier_policy.py`, the Hampel and challenger tests, `src/robust_filter_shadow/adversarial.py` A1–A4b, and both hold-lock tests |
| 8 | clean-board false exclusions ≤ 0.5% of voting observations on **every** clean V and I board; zero board-level false positives |
| 9 | every V and I row moving ≥ 10% (V2 vs incumbent) attributed to a named vote change |
| 10 | all §9 properties pass |
| 11 | performance on pin2015: V2-ON build wall time ≤ 1.25 × the incumbent build, peak RSS ≤ incumbent + 50 MB |
| 12 | independent fresh-context review finds no blocking defect in algorithm, identity, provenance, methodology, numerical stability, weights, integration, performance or memory |

### 11.1 Verdict (exactly one, per directive §13 H)

| verdict | rule |
|---|---|
| **READY FOR APPROVAL** | every criterion 1–12 passes, the shadow window is complete, and no deviation loosened a gate |
| **MORE RESEARCH REQUIRED** | any criterion fails, M1 is INSUFFICIENT, Stage 2 recorded FAILED_SELECTION, or a decision-affecting change followed Stage 2. No retuning on V, I or R; a successor needs a new preregistration and fresh held-out data |
| **BLOCKED** | the evaluation cannot be completed for a reason outside the lane: a manifest board unrecoverable or hash-mismatched, a required dependency unmerged (D4 code), or evidence that exists only on the production server |

A failure never becomes an activation recommendation. Pass rates below a bar are reported as
failures, never relabelled.

## 12. Gate-variant decisions reserved to the owner (O-1 … O-5)

These do not change the criteria; they are the owner's choices among alternatives fixed
here, and they must be made **blind to held-out results**.

| id | question | default if no owner record | how it is recorded |
|---|---|---|---|
| O-1 | gate AD1 / AD3 on ARRIVING (real prior history) instead of NO-HISTORY | **NO-HISTORY is the gate** | an owner decision committed to the repository before the Stage 4 run commit |
| O-2 | gate wrong-player on AD2-ID instead of as-registered AD2 | **as-registered AD2 is the gate** | same |
| O-3 | `payload_provenance_guard` semantics (proven payload values absent; CSV fill supplies the vendor's board) | evaluated as registered; activation owner-reserved | activation decision (§15) |
| O-4 | `rookie_ladder_fail_closed` | evaluated as registered; activation owner-reserved | activation decision |
| O-5 | D-1 (`integrity_holds_as_withheld`, a confidence change) | evaluated only as V2+D1; activation owner-reserved | activation decision |

Every variant is reported whatever the gate. A decision recorded after the Stage 4 run
commit has no effect on this registration's verdict.

## 13. Expected results and failure modes (stated in advance, not evidence)

Predictions from the design pass (pin-based, contaminated, §0):

* §6: 31 / 31 IDP votes kept (nearest distances 0.66–1.17 < ln 4; most persistence-confirmed);
  board C ≈ board B-without-IDP-filter on IDP (max 5.5%); 17 / 17 D4 votes kept (Theo
  Johnson ≈ 2184 adjusted only by DLF Values' own vote). Board D vs A: IDP values ≈ unchanged,
  IDP confidence moves (B11 replay rejections 28 → ~0–2), ~95–99 offense drops restored with
  ~70–80 of 488 offense rows moving (a few deep rows > 30%, each to be attributed); Travis
  Hunter ≈ −7%.
* Gates, ARRIVING: AD1a 96–99%, AD1b 92–97%, AD1c / AD1d 98–100%, AD4 ≈ 100%, AD3 16 / 16.
  NO-HISTORY / PERSISTENT: AD1b ≈ 82% (**expected fail**), AD1a ≈ 93%, AD3 ≈ 12 / 16
  (**expected fail**).
* Wrong player: AD2 as registered ≈ 40–55% (**expected fail**); AD2-ID ≈ 60–75% overall
  (**expected fail** until U3 captures position and team on the 12 name-only boards, which
  can only be shown prospectively); AD2-SUR ≈ 100%; AD2-N 100%.
* H1 22 / 22; H2 3 / 3; H3 caught; N-controls clean; M1 ≈ V1 (non-inferior); M4 ≈ 1.01.
* **Expected verdict today: MORE RESEARCH REQUIRED** (wrong-player gate under every variant;
  AD1b and AD3 under NO-HISTORY).

Expected failure modes: name-only boards defeat Layer A; history-lane absence degrades V2 to
A + B0/B1/B2 + C (activation must fail closed on a readiness check); persistent corruption
that reproduces every fetch is protected by persistence and capped holds; correlated
multi-source anomalies are undetectable; holds delay the first mover on real news by one
fetch; thin TE / DB segments multiply comparisons (guarded by n_min and "non-gross needs
proof"); B2 cannot fire when one broken fetch corrupts both copies; the 0.5% false-hold budget
may be infeasible on high-churn coordinates.

## 14. Rollback

All six flags default OFF. Rollback = every V2 flag OFF and restart (flags are read once per
process). Disabled state = byte-identical incumbent board (criterion 6). The history lane is
record-only and can be left in place or deleted without affecting values.

## 15. Activation criteria (owner-reserved)

* No activation recommendation unless the verdict is READY FOR APPROVAL.
* Even then, activation of `outlier_integrity_v2` and each sub-flag (each a named change:
  identity owner, ingestion, normalization owner, history owner, confidence) requires the
  owner's explicit approval, after independent review and the ≥ 10-day shadow window.
* **DLF IDP / DLF Rookie IDP** (`dlf_offense_only_vote` OFF) and **D4**
  (`dlf_values_rank_hill_vote` ON) remain held until a separate owner approval. Their
  readiness report (directive §9) states: correct populations; DLF Rookie IDP translated
  through its ladder; DLF votes inside the one DLF family cap (never multiple DLF votes);
  DS / FP / IDPTC keep voting when valid; confidence reflects the added evidence; IDP values
  consistent; two-way players correct; downstream pick / trade values consistent; and the
  exact expected activation impact (boards C, C′, C″ vs A on the newest I board).
* V2 activation must fail closed on a readiness check of the history lane.
* Nothing in this lane merges, deploys, flips a production default, or dispatches a release
  candidate.

## 16. Deviations, reruns and held-out discipline

* Any departure from this document is logged in `outlier_integrity_v2/DEVIATIONS.md` with the
  original text, the change, the reason and the commit, before results that depend on it are
  read. A deviation that loosens any criterion makes READY FOR APPROVAL unreachable for this
  registration.
* V_HELDOUT and I are evaluated once (Stage 4, Stage 5). No threshold, rule or variant is
  chosen after looking at them.
* Original evidence (V1's records, the frozen manifest, archives) is never rewritten.

## 17. Sensitivities (report only)

| id | sensitivity |
|---|---|
| S1 | all 149 archives (E_BASELINE included) |
| S2 | offense and IDP separately |
| S3 | each held-out family separately |
| S4 | h = 0, 3, 14, 21 |
| S5 | V2 without B4 (no holds) |
| S6 | DLF excluded as a held-out family |
| S7 | episode-deduplicated origins |
| S8 | V2 with each layer removed in turn (A, B0–B2, B3, B4, C) |

---

## Appendix A — frozen manifest files (sha256 at this commit)

See `outlier_integrity_v2/manifests/MANIFEST_SHA256.txt`, generated by
`sha256sum` over every file in `outlier_integrity_v2/manifests/` and
`outlier_integrity_v2/rootcause/output/` at this commit, and `manifests/INDEX.json` for the
population files' own hashes and counts.
