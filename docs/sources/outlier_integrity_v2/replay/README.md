# Outlier integrity v2: historical replay (directive §7; preregistration Stages 2–4)

Agent-OS-Receipt: cb64f74cf4d2763aa16d55ba0d6350f585a2a42f

**Label: archived inputs rebuilt through one replay code revision; NOT what production served.**
Every board is rebuilt with #1847's procedure (`scripts/joint_filter_shadow.py`: the archive's
payload, `CSVs/site_raw` as committed with the archive overlaid with its own copies, per-source
dataset state replayed from git to the archive's add time), on the frozen manifests of the
preregistration (`../manifests/`, every zip and payload sha256 checked). The V2 history lane is
rebuilt from V2's OWN decisions in add-commit order; nothing is read from production.

Preregistration: `../../OUTLIER_INTEGRITY_V2_PREREGISTRATION.md` (commit `3c69945723`).
Execution clarifications, all logged before the results they affect: `../DEVIATIONS.md` S1–S16.
V1's preregistration and its NOT ELIGIBLE verdict are untouched.

## Order of work (each step a commit on `claude/outlier-integrity-v2`)

| step | what | populations read | commit |
|---|---|---|---|
| Stage 2 | threshold selection by the registered rules; `../FROZEN_THRESHOLDS.json` | E_BASELINE + E_DEV only | `3d34ceeded` |
| Stage 3 | R constraints + performance at the frozen thresholds (`stage3_r/`) | R pins | `458dc15797` |
| exploratory | full comparator replay of E_DEV at the frozen thresholds (`exploratory_e_dev/`) | E only | code `d1ff711ae0` |
| **Stage 4** | **the one held-out run**: V_HELDOUT (61) + I_INDEPENDENT (7), and the §7 gates on the registered V gate board (`stage4_heldout/`) | V, I (once) | code **`8c33447d0a`**, clean tree |

Stage 4 was started exactly once (`data/oiv2_replay/stage4/_STAGE4_STARTED.json`: code
`8c33447d0a`, clean tree, thresholds file sha256 `e0569bef…`); no rerun was needed or made. The only
code difference between the exploratory run and Stage 4 is the INJ-SEG grouping (V/I-only tooling,
S16). Every Stage 4 record carries the same code SHA, a clean-tree flag and the same thresholds
hash (`stage4_heldout/evaluation.json` → `identity`). Per-board records are gitignored
(`data/oiv2_replay/`); their sha256 are in each evaluation's `perBoard[].recordSha256`.

Comparators on every scored board (prereg §2.2, §6.1): incumbent (board A), V1, V2 (board D),
V2-NOHIST, V2+D1, and the restoration boards B, C, B′, C′, B″, C″. V2-RPC was not implemented in
Stage 1 and is not run (S13); no other candidate was added.

Reproduce (full git history; ~1 h on 4 cores, sequential builds):

```bash
python scripts/oiv2_replay.py run --populations E_DEV --tag explore_e
python scripts/oiv2_replay.py run --populations V,I --tag stage4        # refuses a 2nd start
python scripts/oiv2_replay.py evaluate --tag stage4 --populations V,I --out evaluation.json
python scripts/oiv2_gates.py --board dynasty_export_20261018_114711.zip --stage4-gate-of-record --report-v1 --out g.json
python scripts/oiv2_gates.py --board dynasty_export_20261018_114711.zip --stage4-gate-of-record --report-v1 \
    --history-file data/oiv2_replay/stage4/_history/dynasty_export_20261018_114711.json.gz --out g_arriving.json
```

## Stage 2: what the registered rules selected (E only)

| constant | selected | how | note |
|---|---|---|---|
| τ_age | 1 | smallest grid value with 0 contradictions on id-verified joins | **vacuous**: no age-publishing source carries a Sleeper id (S15) |
| ε (B2) | 0.01 | smallest with no board proof on healthy E captures | healthy captures give m_g = 0.000 exactly |
| τ_board | per (source, class), SD 0.004–0.08 | sample SD of the class median residual | B3a fires at the ln 1.25 floor almost everywhere |
| n_min / ρ_min / τ_gross | 20 / 0.0 / ln 4 | **FAILED_SELECTION** | all 8 settings: 0 clean hard flags but 1,121 / 1,124 injections caught; the 3 misses are `ktcCrowdSfTep` on its first board (no history baseline). Registered consequence: the run cannot reach READY FOR APPROVAL |
| k_c | 4 | smallest k_c with false holds ≤ 0.5% on every clean E_DEV board | consecutive same-player Δu MAD is 0–0.019, so τ_c = ln 1.5 in every cell for every k_c; max false-hold rate 0.04% |
| τ_C | ln 4 | largest grid value catching ≥ 95% of cold-start ×20 and ×0.05 | **infeasible**: ln 4 91.8% / 91.0%, ln 5 89.9% / 90.9%, ln 6 89.1% / 90.7%; the floor is used |

## Stage 3: R constraints at the frozen thresholds (`stage3_r/`)

31 / 31 IDP votes retained in C and C″ on pin2015 and pin0527; the D4 rule set (20 votes) retained
in C′ and C″; C deterministic. **Criterion 11 fails**: V2-ON build 1.69× the incumbent (limit
1.25×); RSS +22 MB (limit +50 MB, passes).

## The seven directive §5 gates — complete layered system, registered V gate board (Stage 4)

`dynasty_export_20261018_114711` (seed 2033), every corrupted observation injected after pricing and
before every integrity layer (T4). **NO-HISTORY is the gate of record** (no O-1 / O-2 owner record
exists). ARRIVING (real prior history from the replayed lane) is reported, never the gate.

| gate | bar | material cases | incumbent | V1 | **V2 NO-HISTORY (gate)** | V2 ARRIVING (reported) |
|---|---|---|---|---|---|---|
| AD1a ×5 | 90% | 275 | 16.4% | 87.6% | **53.1% FAIL** | 97.2% |
| AD1b ×0.2 | 90% | 200 | 1.5% | 52.0% | **26.5% FAIL** | 95.5% |
| AD1c ×20 | 95% | 304 | 24.0% | 93.8% | **70.1% FAIL** | 100% |
| AD1d ×0.05 | 95% | 229 | 4.4% | 84.3% | **67.7% FAIL** | 100% |
| AD2 wrong player | 90% | 126 | 8.7% | 14.3% | **9.5% FAIL** | 48.8% (FAIL) |
| AD4 single-source spike | 95% | 89 | 0.0% | 91.0% | **62.9% FAIL** | 100% |
| AD3 wrong scale | 16 / 16 | 16 boards | — | — | **4 / 16 FAIL** (only `reversed`) | 12 / 16 (FAIL: on every `values ×0.01` board the corrupted votes are excluded one by one — 284/284, 402/403, 389/389, 246/249 — but B3 raises no board flag) |

Why the numbers look like this on this board: IDP Show is freshness-excluded on 2026-10-18, so most
material cases sit on rows with exactly **three** voting families. The incumbent never filters a
three-vote row (min n 4: 0–2% in that band, 100% at 4+ families). V2's Layer C needs two OTHER
providers within ln 2 of each other before it may remove anything; on three-provider rows that
reference is often absent, and without history neither B4 nor persistence can act, so V2-NOHIST
catches 51–64% in the three-family band and 100% at 4+ families for ×20 / ×0.05. With real history
(ARRIVING) B4 holds the corrupted observation on 94–100% of cases. Wrong-player swaps carry no
identity evidence by construction (AD2 as registered); B4 catches about half of them with history.
Batch contamination: Travis Hunter only (7 of 167 batches, ≤ 0.64 log), the known two-way coupling.

Not run (S13): AD2-ID, AD2-SUR, AD2-N as injections, INJ-DUP end to end, the PERSISTENT variant;
the gates on the newest I board belong to Stage 5 (end of the shadow window).

Also measured (every V and I board):

| injection | requirement | result |
|---|---|---|
| INJ-H1: both rookie-ladder references disabled | 100% of rookie votes withheld; 0 fires on unmodified boards | **68 / 68 boards, 0 fires: PASS** |
| INJ-SEG: IDPTC payload, 70% of rows shifted per position group | B2 board proof on 100% of boards | **3 / 68: FAIL** — by construction (S16: 30% unshifted rows have Δ = 0, so the sign share stays below the registered 80%); the 3 are the H2 boards, already proven |

## Labelled historical cases (prereg §8)

| case | required | V2 result | incumbent / V1 |
|---|---|---|---|
| **H1** rookie boards voting untranslated within-class ranks (22 E_DEV boards) | withheld by B1 on 22 / 22 | **22 / 22**: every `dlfRookieSf` and `flockFantasySfRookies` observation withheld as `normalization_untranslated` (2,701 votes); 0 fires on boards where the ladder reference exists | incumbent removed them row by row as outliers; V1's board screen excluded them (counted as false positives under V1's frozen rule, which stands) |
| **H2** IDPTC partial-fallback format switch (Oct 7 09:25, Oct 8 14:12, Oct 16 13:40) | B2 board proof 3 / 3 | **3 / 3**: proven in 6–7 position groups (|m_g| 0.14–0.21, sign share 0.86–1.00); 391 / 411 / 423 payload values replaced by the vendor's same-run CSV value, 5–7 withheld (no CSV row); 0 IDPTC votes dropped by Layer C | incumbent dropped 82 / 90 / 88 IDPTC votes as outliers; **V1 dropped 1 / 2 / 1** |
| **H3** IDPTC autocomplete wrong player (Justin Jefferson ~800 vs ~7,500) | excluded or held where it occurs | **caught on all 3**: Oct 8 773 → 7,372 and Oct 16 951 → 7,638 replaced by the CSV copy (B2 row proof); Aug 3 837 → 7,674 the same (`checks/h3_h4_e_baseline_check.out.txt`) | incumbent and V1 drop it as an outlier |
| **H4** the same fallback with correct values (Aug 3, Aug 6) | nothing quarantined except the H3 row | **pass**: 0 IDPTC integrity exclusions; the only change on Aug 3 is the H3 row replacement | — |
| H5 FantasyPros IDP extension instability (soft) | reported | 0 `segment_break_unproven` advisories at the frozen thresholds | — |
| H6 FantasyPros IDP duplicate names | A4 refusal rate | 0 A4 refusals of `fantasyProsIdp` (C4 keeps one person listed on two pages) | — |
| N1–N5 controls | no hard quarantine | **0** hard findings on every scored and chain board | — |
| N6 benign coverage changes | no hard quarantine | the 14 hard findings on N6-listed sources are all `ktcCrowdSfTep` B0 findings (below), unrelated to the N6 coverage changes themselves | — |

### Why V1 missed the October IDPTC anomaly, and what V2 does instead

The anomaly is a **mixed-direction, moderate** shift in the scraper payload's IDPTC values (an
offense 1QB-scale fallback): per position group QB −0.14 to −0.18, RB / WR / TE +0.17 to +0.21,
DL / LB / DB +0.17 to +0.19 in log value, measured payload-vs-CSV on the same run.

* **V1's board screen** compares a source's votes with the leave-source-out consensus per
  (source, asset class), and flags only |median signed deviation| > ln 1.5 (0.405) or median
  |deviation| > ln 2 (0.693). On the three boards its IDPTC offense statistics were median signed
  −0.20 / −0.22 / −0.22 and median absolute 0.26 / 0.29 / 0.30; IDP 0.10 / 0.10 / 0.05 and
  0.21 / 0.22 / 0.28. Every one is below both limits: the shift is too small for a consensus-relative
  test whose tolerance must absorb legitimate disagreement, and pooling QB (−) with RB / WR / TE (+)
  into one offense statistic dilutes it further. V1 therefore removed only 1–2 votes.
* **V2's B2** does not compare a vendor with other vendors. It compares the scraper's payload copy of
  IDPTC with the vendor's own same-run CSV, per position group: on a healthy capture the two agree
  closely (no board proof at ε = 0.01 on any of the 77 healthy E captures; typically m_g = 0.000 exactly), so a 0.14–0.21 shift that is consistent within
  six or seven groups is a deterministic provenance proof, independent of anyone's opinion. The
  payload values are then replaced by the CSV values (missing CSV → withheld, never zero), which
  also repairs the H3 wrong-player row. The third episode (Oct 16) is caught the same way.

## The DLF failure on every held-out board (directive §6, generalised)

On every V and I board, the pairs the incumbent newly drops when DLF IDP votes (B vs A, DLF's own
votes excluded) and when D4 votes (B′ vs A′) — and V2's fate for each (`stage4_heldout/dlf_restore_pairs.json`):

| restoration | incumbent newly drops (68 boards) | V2 keeps | not kept |
|---|---|---|---|
| DLF IDP (B → C) | 1,623 (31 on every board) | **1,623** | 0 |
| D4 (B′ → C′) | 1,123 | **1,102** | 21 — all `ktcCrowdSfTep` votes refused by **B0** on the boards where its CSV carries 1–2 rank/value-discordant rows (below), not by Layer C |
| both (B″ → C″) | 2,746 | 2,725 | the same 21 |

Focus rows on the newest I board (`20261020_052241`, values A → B → C): Trevin Wallace 1953 → 885 →
1955; Myles Garrett 3528 → 5266 → 3466; Aidan Hutchinson 4747 → 6422 → 4752; CJ Allen 4015 → 2164 →
4054; T.J. Watt 2378 → 3431 → 2398; Josiah Trotter 2354 → 3379 → 2465; Will Anderson 4330 → 5967 →
4375; Danielle Hunter 2322 → 3041 → 2308; Jared Verse 2662 → 2662 (DLF's own vote dropped) → 2788.
In B the incumbent removes Draft Sharks (Trotter also FantasyPros); in C every one of those votes
counts. Theo Johnson: Draft Sharks votes 3001 here and the incumbent keeps it in B′ (2184 → 2105 is
DLF Values' own vote), as on both R pins; the owner-cited 3182 case is on the #1817 lane's board and is
covered by the frozen-panel test.

## Held-out metrics (V ∪ I, 68 boards)

| metric | result | criterion |
|---|---|---|
| M1 P1 (h = 7, V2-disputed units) | −0.00104 [−0.00105, −0.00103], n 12,299 — closer than the incumbent | **INSUFFICIENT**: 12 origin days but only **2** week-blocks (≥ 4 required); the shadow window (Stage 5) is required anyway |
| M1 by class | offense −0.00129 (n 12,246); **IDP +0.055 [0.032, 0.064] (n 53), worse** | reported |
| M4 board stability ratio V2 / incumbent | 1.033 [0.952, **1.305**] (IDP 1.015 [0.944, 1.069]; offense 1.056 [0.963, 1.372]) | **fails** (upper 95 > 1.10) |
| clean-board false exclusions (65 boards not H2/H3) | non-deterministic reasons > 0.5% on **2** boards (5.8%: the B3a class quarantine below); including deterministic-pending-review reasons, 8 boards up to 8.7% (B0 `ktcCrowdSfTep` + its rookie-ladder dependants) | **fails** (≤ 0.5% on every board) |
| board-level false positives | B3a class quarantine of `idpTradeCalc` / offense on 2026-10-10 09:05 and 16:00 decided on **2 rows**; B0 source quarantine of `ktcCrowdSfTep` on 7 V / I boards for 1–2 discordant rows (`discordantRows` 1–2 of 464) | **fails** pending the reviewer's structural-change check; the B3a pair cannot be a true positive (2 rows, no structural change recorded) |
| criterion 9: rows moving ≥ 10% (V2 vs incumbent) | 902 movers: 884 attributed to named vote changes, 18 derived far-future picks (no per-row vote; they follow moved anchors), **0 unattributed** | pass |
| top causes | Draft Sharks IDP restored from an incumbent drop 534; KTC Crowd B0 refusal 85; Draft Sharks IDP `identity_contradicted:age` 48; Draft Sharks offense restored 31 | — |

Exploratory E_DEV (same code, frozen thresholds; development only, decides nothing): P1 −0.00067
[−0.00159, −0.00008] (n 37,273, 37 days, 6 blocks; IDP +0.044, n 204), M4 1.026 [0.995, 1.074],
616 ≥ 10% movers all attributed or derived picks, 0 board-level B2/B3 false positives but the same B0
`ktcCrowdSfTep` refusals on 2 boards.

## Defects this replay surfaced (reported, not tuned — any change spends the registration)

1. **B0 is brittle**: "zero rank/value discordance" (C10) quarantines all of `ktcCrowdSfTep` (≈ 460
   votes per board, plus ≈ 104 rookie-ladder dependants) for 1–2 discordant vendor rows on 7 V / I
   and 2 E boards. Twenty-one of the D4-restored votes are lost this way.
2. **B3a has no minimum row count**: a class quarantine of IDPTC offense (≈ 430 votes) was decided on
   2 rows with a leave-source-out reference.
3. **τ_age = 1 from an empty evidence set** refuses ≈ 5 name-only joins per board (Draft Sharks IDP
   is the main source), counted as false exclusions.
4. **Three-provider rows**: without history, Layer C cannot act on most of them (gates above); the
   held-out board makes this dominant because IDP Show was stale.
5. **INJ-SEG vs B2** are inconsistent by construction (S16).
6. **Performance**: 1.69× the incumbent build (criterion 11).

## Criteria (prereg §11) and verdict

| # | criterion | result |
|---|---|---|
| 1 | §7 gates (gate of record) | **FAIL** (all seven; AD2-N / INJ-SEG also not met) |
| 2 | 31 IDP votes in C / C″, D4 set in C′ / C″ (R pins) | pass (Stage 3); on V / I the D4 generalisation loses 21 votes to B0 |
| 3 | H1 22 / 22, H2 3 / 3, H3 every board, H4 | **pass** |
| 4 | N1–N6 no hard quarantine | N1–N5 pass; N6-listed source `ktcCrowdSfTep` hit by B0 (defect 1) |
| 5 | M1 minimum sample and P1 ≤ +0.005; M4 ≤ 1.10 | **fail** (M1 INSUFFICIENT; M4 upper 1.305) |
| 6 | OFF state byte-identical | not re-measured here (thresholds are read only with the master flag on; Stage 1 evidence stands) |
| 7 | existing mandatory tests | targeted V2 / filter / identity suites pass (532 + 159); full suite is CI's |
| 8 | clean-board false exclusions ≤ 0.5%, zero board-level FPs | **fail** |
| 9 | ≥ 10% movers attributed | pass |
| 10 | §9 properties | Stage 1 tests pass; not re-run here |
| 11 | performance | **fail** (1.69×) |
| 12 | independent review | not yet run |

Stage 2 also recorded FAILED_SELECTION (B3b) and an infeasible τ_C.

**Verdict for this registration: MORE RESEARCH REQUIRED.** Criteria 1, 5, 8 and 11 fail, M1 is
INSUFFICIENT, and Stage 2 recorded FAILED_SELECTION; the shadow window (Stage 5) and the independent
review have not run. A successor needs a new preregistration and fresh held-out boards (§11.1).
Nothing here recommends activation: DLF IDP, DLF Rookie IDP and D4 stay held, V2 stays default OFF.

What the evidence does support, for the successor's design: V2's layered integrity checks catch the
real historical failures (H1 22/22, H2 3/3 including the October format switch V1 missed, H3 on
every board) and never remove the legitimate dissenting votes the incumbent removes when DLF votes
(1,623 / 1,623 on every held-out board); its failures are B0 / B3a brittleness, cold-start
three-provider rows, wrong-player swaps with no identity evidence, and build time.
