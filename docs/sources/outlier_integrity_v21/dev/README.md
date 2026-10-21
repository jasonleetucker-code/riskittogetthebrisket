# Outlier integrity V2.1: dev-stage (exploratory) evaluation

**Status: EXPLORATORY / DEV ONLY. Not a gate of record, not Stage 2, 3 or 4.**
Every number here comes from the 79 DEV boards of
[`../manifests/POPULATIONS.json`](../manifests/POPULATIONS.json) (V2's E_BASELINE + E_DEV).
No R pin, no SPENT board (V2's held-out boards stay spent) and no archive added after
T0 (the sealed fresh held-out set) was read. Nothing was activated: every new flag stays
OFF, the DLF IDP hold stays ON, D4 and freshness v2 stay OFF. No curve, Hill constant,
weight, family, cap, freshness rule, VA, `geom_q078_v1` or trade code changed. No
mandatory threshold was changed. Every execution choice is logged in
[`../DEVIATIONS.md`](../DEVIATIONS.md) (V21-C34, V21-D1 .. D18) before the result it
affects was read, with two recorded exceptions (V21-D16, V21-D17, both logged before the
re-run they motivated was read).

Agent-OS-Receipt: cb64f74cf4d2763aa16d55ba0d6350f585a2a42f

## Dev-stage readiness verdict

**NOT READY for the Stage 2 freeze as registered. If Stage 2 and Stage 4 ran on this code,
the registered verdict would be MORE RESEARCH REQUIRED (or BLOCKED if the identity
prerequisites are not live by 2026-11-04).** The DEV evidence already fails criteria
1 (wrong player, AD3), 2 (AD2-N), 3 (cold-start safety on L4), 13 (production-like
memory) and 16 (two FAILED_SELECTIONs), independent of the held-out data.

What does work on DEV: the injected-value gates under real prior history (AD1a-d, AD4)
pass on both dev gate boards; every legitimate vote the incumbent newly drops when DLF IDP,
D4 or both vote is kept (DLF IDP 652 / 652, D4 92 / 92, combined 744 / 744 pairs on 44 E_DEV boards, with and without history);
clean-board false exclusions stay under 0.21% with no board-level false positive; H1, H3,
H4, H2-SYN, INJ-H1, INJ-SEG and INJ-DUP pass; the flag-off board is byte-identical to
`origin/main` on 4 / 4 DEV boards; the contract-size budget is met.

## Scorecard against the registered criteria (DEV analogues)

| # | criterion | DEV result | dev reading |
|---|---|---|---|
| 1 | gate of record, ARRIVING (G1dev / G2dev) | AD1a 96.0 / 98.0%, AD1b 95.5 / 98.0%, AD1c 99.7 / 99.7%, AD1d 100 / 100%, AD4 100 / 100%; **wrong player (AD2 as registered) 53.2 / 46.9%**; **AD3 4 / 16** on the registered seam (9 / 16 and 8 / 16 on V2's priced seam) | **FAIL** (wrong player, AD3) |
| 2 | structural gates | **AD2-N 25.0 / 20.0%** (needs 100%); INJ-H1 102 / 102 and 104 / 104 withheld, 0 fires unmodified; INJ-SEG board proof on both; INJ-DUP holds (644 / 695 cases) | **FAIL** (AD2-N) |
| 3 | cold-start safety (L4, NO-HISTORY) | **716 drops** of 113,480 L4 votes with the directory; 586 without | **FAIL** (see below) |
| 4 | required runs | NO-HISTORY gates, AD2-ID, AD2-SUR, INJ-DUP and V2-RPC run in full; PERSISTENT run on a stratified subsample (V21-D18): 1.7-58% G1dev / 3.3-78% G2dev, every lost case voting through P-4 persistence or P-3's content-distinct release | run (reported, not a gate; full PERSISTENT run is Stage 4) |
| 5 | identity prerequisites live | U2 / U2b / U3 / VID are on this branch only, not on `main`, not in the refresh | **BLOCKED** until merged and live before 2026-11-04T00:00Z |
| 6 | regression retention | R-pin L1-L3 not run (Stage 3). DEV analogue: DLF IDP 652 / 652, D4 92 / 92, both 744 / 744 retained in C, C′, C″ under ARRIVING and NO-HISTORY | analogue passes; Stage 3 pending |
| 7 | labelled cases | H1 22 / 22 withheld, 0 fires on boards with a ladder; H3 replaced by the CSV copy (B2 row proof, 837 → 7,674); H4 no IDPTC exclusion; H2-SYN proof, healthy twin none; N1-N5 0 hard findings | pass |
| 8 | clean-board false exclusions | max 0.20% (ARRIVING) / 0.19% (NO-HISTORY) of voting observations on 22 clean E_DEV boards; 0 board-level false positives (V2: 2, KTC Crowd B0) | pass |
| 9 | accuracy and stability (M1 / M4) | not run (held-out metric) | Stage 4 |
| 10 | attribution of ≥ 10% movers | 590 / 598 attributed to a named vote change; 8 are tethered current-year picks (2026 Pick 1.10, 2.11) whose change comes through the rookie tether, which the dev tool does not trace | evaluator gap (named) |
| 11 | flag-off identity | byte-identical to `origin/main` 00cdab7d5e on 4 / 4 DEV boards (clock fields stripped); V2.1 / hold-lock / identity test files pass (640 passed) | pass (dev) |
| 12 | properties | §9 property tests pass in the targeted suite | full suite at Stage 4 |
| 13 | performance | committed configuration: wall 1.15 / 1.20×, RSS +46.6 MB; **production-like (directory + candidate thresholds): wall 1.10 / 1.25×, RSS +58.1 MB** | **FAIL** in the production-like configuration (RSS > +50 MB); wall margin thin |
| 14 | contract size | full 1.0107×, gzip 1.0142×, delta 1.0011× | pass |
| 15 | transparency | 0 votes that passed A and B carry an invalid §10 category (ARRIVING and NO-HISTORY, 79 boards) | pass (dev) |
| 16 | selection | ε 0.01; k_c 4 (τ_c at the ln 1.5 floor everywhere); **B3 FAILED_SELECTION; τ_C FAILED_SELECTION** | **FAIL** |
| 17 | process | seal intact; deviations logged | holds so far |
| 18 | independent review | not run at dev stage | Stage 5 |

## Exploratory selection (prereg §3.6; `SELECTION_EXPLORATORY.json`, not frozen)

* **ε (B2) = 0.01**: no board proof on any healthy DEV capture at any grid point (R14 reading, with the V21-C34 numerator fix).
* **τ_board**: per (source, class) SD over E_DEV, as V2.
* **B3 (n_min, ρ_min, τ_gross): FAILED_SELECTION, both ways.**
  * As first run, B4 active during the selection injections (V21-C17 provisional thresholds): 0 clean hard flags at every grid point, but only 540-543 / 1,132 injections flagged, because B4 holds the corrupted votes one by one and the segments fall below n_min / R2's 20 rows.
  * With B4 abstaining, V2's phase order (V21-D16): 1,129 / 1,132 at every grid point; the 3 misses are `ktcCrowdSfTep` on its first DEV board (2026-09-09, no baseline), the same structural miss V2 recorded.
* **k_c = 4**: false-hold rate ≤ 0.04% on every clean board at every k_c; content-distinct (P-1) MADs put τ_c at the ln 1.5 floor everywhere.
* **τ_C: FAILED_SELECTION.** Under ARRIVING every grid point catches AD1a 97.6%, AD1b 97.4%, AD1c 99.8%, AD1d 100%, AD4 100% (B4 does the catching, so τ_C does not move them), but the cold-start constraint (zero L4 drops under NO-HISTORY) holds at no grid point (726 / 716 / 716 drops at ln 4 / ln 5 / ln 6, after the V21-D17 measurement fix). Development continued at ln 6 (fewest drops), labelled `devContinuation`, not a selection.
* **Cost of ln 6 at cold start**: V2.1-NOHIST is weaker than V2-NOHIST (frozen at ln 4) on the value gates (AD1a 66.6 / 55.3% vs 86.8 / 80.0%; AD1b 13.5 / 13.9% vs 43.3 / 46.7%).

## Gates on the dev boards (`evaluation.json` → `gates`)

ARRIVING (the gate of record's analogue) and NO-HISTORY (reported), material cases only,
pass = excluded by a layer or own-board move < 0.10 log. G1dev / G2dev:

| gate | bar | incumbent | V1 | V2 (frozen) | **V2.1 ARRIVING** | V2.1 NO-HIST | V2-RPC ARRIVING | V2-RPC NO-HIST |
|---|---|---|---|---|---|---|---|---|
| AD1a ×5 | 90% | 76.4 / 80.0 | 93.3 / 92.7 | 98.5 / 98.0 | **96.0 / 98.0** | 66.6 / 55.3 | 99.7 / 98.7 | 87.1 / 85.0 |
| AD1b ×0.2 | 90% | 48.2 / 47.7 | 66.1 / 64.6 | 96.7 / 98.0 | **95.5 / 98.0** | 13.5 / 13.9 | 98.8 / 99.0 | 58.8 / 76.4 |
| AD1c ×20 | 95% | 77.9 / 79.1 | 99.4 / 99.7 | 99.7 / 99.7 | **99.7 / 99.7** | 93.1 / 92.3 | 100 / 100 | 96.0 / 95.0 |
| AD1d ×0.05 | 95% | 59.5 / 57.8 | 96.8 / 87.9 | 100 / 100 | **100 / 100** | 96.4 / 93.5 | 100 / 100 | 99.2 / 98.3 |
| AD2 wrong player | 90% | 43.3 / 43.1 | 19.9 / 12.3 | 53.9 / 47.7 | **53.2 / 46.9** | 6.4 / 3.1 | 53.2 / 46.9 | 17.7 / 12.3 |
| AD4 spike | 95% | 88.2 / 87.7 | 100 / 100 | 100 / 100 | **100 / 100** | 71.6 / 72.6 | 100 / 100 | 82.4 / 75.3 |

V2 and V2-RPC under ARRIVING read their own DEV lanes. Material cases: G1dev 326 / 245 / 349 /
252 / 141 / 102; G2dev 300 / 195 / 339 / 232 / 130 / 73. Batch contamination: the known
Travis Hunter two-way coupling only (≤ 3 batches of 159, up to 0.77 log on G2dev).

**AD3 (wrong scale, 16 boards).** Registered seam (CSV edited before Layer A): 4 / 16 for
V2 and V2.1 in both variants; only `reversed` is flagged. As V21-D4 predicted, ranks ×2 /
×5 and values ×0.01 on these rank-signal boards are re-ranked away before any vote: the
`none` board does not move at all (0.0 log), so the corruption is invisible and harmless
by construction and 16 / 16 is unreachable as registered. **This is a registration defect
the owner must decide before the Stage 2 freeze.** On V2's priced seam: V2.1 9 / 16
(G1dev) and 8 / 16 (G2dev) ARRIVING, 4 / 16 NO-HISTORY; V2 14 / 16 and 12 / 16. The
V2.1 misses are ranks ×5 and values ×0.01, whose votes B4 holds one by one (they never
vote) so the segment falls below n_min and B3 raises no board flag: B4 pre-empts B3 (the
same interaction as the B3 selection).

**Wrong player.**

* AD2 as registered (no identity evidence): 53.2 / 46.9% ARRIVING, B4 catching about half; Layer A cannot fire by construction.
* **AD2-ID** (the swapped entry carries the swapped player's own published fields): V2.1 ARRIVING 68.4 / 60.2% overall; **90.6 / 92.5% where the source publishes identity fields** (64 / 40 cases), 47.8 / 44.6% on name-only sources (69 / 83). NO-HISTORY 39.8 / 26.0% (with fields 76.6 / 70.0%). U3 columns do not exist on DEV boards, so every name-only board stays name-only here.
* **AD2-SUR** (synthetic U2 autocomplete capture): 100% caught (230 / 225 material), **but the control with the TRUE value is refused 665 / 665 and 649 / 649**: under U2 every correct autocomplete-fallback capture is refused (`identity_unresolved:low_evidence_rung`), because the scraper's autocomplete path records no published field to agree with. Once U2 is live, every IDPTC autocomplete-fallback episode would remove IDPTC's votes wholesale.
* **AD2-N**: 25.0% (G1dev, 40 cases) / 20.0% (G2dev, 50 cases), name-only 0%. The registered "same-group Sleeper homonyms the source cannot tell apart → UNRESOLVED" rule reads homonyms from BOARD ROWS only (`_v2_homonyms_of`); an off-board Sleeper homonym (e.g. the two active Byron Youngs, both DL) is never consulted, so the entry is attributed to the board row.

## Cold-start safety on L4 (NO-HISTORY; `evaluation.json` → `coldStart`)

L4 = every vote on the H4, N1, N2, N3 and N5 DEV boards (H3 row and H1 untranslated votes on
H1-labelled boards excluded) plus the N4 and N6 rules on all 79 boards. **716 drops with the
directory, 586 board-rows-only; 0 votes mis-labelled with an invalid category.** By class
(with directory):

| class | drops | what it is |
|---|---|---|
| B1 `normalization_untranslated` (dlfRookieSf, flockFantasySfRookies) | 505 | the H1 mechanism (no rookie ladder reference) on the E_BASELINE H4 / N5 boards, which H1's label does not cover. A deterministic B1 proof; exemption-eligible only after an independent reviewer verifies it from the archive. |
| A1 `identity_contradicted:sleeper_id` | 82 | **DynastyNerds publishes wrong or placeholder Sleeper ids** (Eli Stowers 8128 and Tory Horton 11639 are "Player Invalid" in the directory; Zay Flowers 8133 vs 9997; TreVeyon Henderson 12513 vs 12529). The name, position, team and value are the right player's: legitimate votes dropped. Absent without the directory (R11 is what reaches these ids). |
| A `identity_contradicted:age` | 57 | **DraftSharks ages run about one year ahead** of the Sleeper birth date (Tank Bigsby 25.1 vs 24.08; Tanner Koziol 23.7 vs 22.67), just past R5's fixed τ_age = 1.0. Legitimate votes. 9 remain without the directory. |
| A4 `identity_unresolved:ambiguous_in_source` | 53 | a source listing one name twice without disambiguating evidence: flock (Cole Payton ×2), OTC (Kyle Williams), IDP Show (Byron Murphy ×2 DL; Justin Jefferson ×2 both labelled LB, one of which appears to carry the WR's rank-13 value). At least some are legitimate votes (a duplicate listing of one player); each needs review. |
| A3 `identity_contradicted:position_family` | 18 | draftSharksIdp entries on the WR Justin Jefferson row (the incumbent joins an IDP entry onto the WR): plausibly correct refusals; need review. |
| Layer C `extreme_uncorroborated_tail` | 1 | Austin Ekeler, KTC Crowd 133 (2026-09-28): a gross dissent with a corroborated reference, no deterministic contradiction. |

N4: 0 zero-value yahooBoone votes on any board (the one yahooBoone exclusion is an A3
refusal on the Michael Carter DB row, not a zero read). N6: 0 hard quarantines.

## The DLF failure on every E_DEV board (directive §6, DEV analogue)

`chain` records, 44 E_DEV boards: pairs the incumbent newly drops when DLF IDP (B vs A),
D4 (B′ vs A′) or both (B″ vs A) vote, DLF's own votes excluded:

| restoration | newly dropped by the incumbent | kept by V2.1 ARRIVING (C) | kept by V2.1 NO-HISTORY |
|---|---|---|---|
| DLF IDP | 652 | **652** | **652** |
| D4 | 92 (boards with a DLF Values CSV) | **92** | **92** |
| both | 744 | **744** | **744** |

§6 boards on G1dev and G2dev (`evaluation.json` → `boards`; ARRIVING and NO-HISTORY agree):
on G2dev the incumbent ALREADY drops Draft Sharks IDP on Myles Garrett, T.J. Watt,
CJ Allen, Danielle Hunter and Trevin Wallace in A (IDP Show voted then), and V2.1 (D, the
filter change alone) keeps those votes: Garrett 5,275 → 3,789, Watt 3,306 → 2,475,
CJ Allen 3,050 → 4,087, Hunter 3,004 → 2,406, Wallace 1,292 → 1,989. With DLF IDP (B) the
incumbent also drops Draft Sharks / IDP Show on Hutchinson (4,845 → 6,411) and Will
Anderson (4,446 → 5,928); C keeps them (4,845, 4,446). LaJohntay Wester's Flock vote, dropped
by the incumbent in A, votes under V2.1 (775 → 930). D vs A on G2dev: 95 rows move ≥ 1%,
18 ≥ 10%; 146 incumbent filter drops become votes; 2 Draft Sharks age and 4 DynastyNerds
Sleeper-id refusals are the only new exclusions (the cold-start classes above).

## PERSISTENT (P-5; V21-D7 / D18)

The same corruption also carried by the source's 3 prior content-distinct datasets, with
every board of that span rebuilt so B4 (including its hour cap) and P-1..P-4 act as they
would (V21-D7). Dev subsample: ≤ 60 material cases per gate, seed 2034 (V21-D18). V2.1 only.

| gate | bar | G1dev PERSISTENT | G2dev PERSISTENT | caught ARRIVING, not PERSISTENT (G1dev / G2dev) |
|---|---|---|---|---|
| AD1a ×5 | 90% | 18.3% | 36.7% | 42 / 38 |
| AD1b ×0.2 | 90% | 6.7% | 8.3% | 52 / 53 |
| AD1c ×20 | 95% | 31.7% | 58.3% | 41 / 25 |
| AD1d ×0.05 | 95% | 18.3% | 78.3% | 49 / 13 |
| AD2 wrong player | 90% | 1.7% | 3.3% | 31 / 25 |
| AD4 spike | 95% | 18.3% | 55.0% | 49 / 27 |

**P-5 mechanism** for every case caught under ARRIVING and not under PERSISTENT:
`persistent_gross_dissent` (P-4: persistence-confirmed while still beyond τ_C; votes,
alerted, never silent) 160 on G1dev / 46 on G2dev; `kept_dissent`, i.e. B4 no longer held
the vote (the corrupted value had become the source's accepted baseline through P-3's
registered release, reproduction on ≥ 3 content-distinct datasets spanning ≥ 72 h) and
Layer C kept it as a dissent, 96 / 129; plain accepted baseline 6 / 6;
`voting_name_only_identity` 2 / 0. No case was released by the cap alone
(`released_by_cap` 0). On G1dev `idpShowCombined` had only 1 prior dataset and the KTC
Crowd / Trades boards none, so those cases ran with what DEV holds.

This is the registered failure mode (prereg §13: "P-3 lets a persistent corruption vote
after the cap (flagged, never silent)"), now measured: a corruption that persists across
four vendor publications is accepted as the vendor's view. Property 18 (no self-confirmation
from re-reads or from held observations) is enforced by the unit tests; the dev run shows
no case voted through a cap release alone; acceptance came through P-3's content-distinct
reproduction rule or P-4 persistence.

## Performance and contract size (`perf/`)

| configuration | wall ratio | RSS delta | full | gzip | delta |
|---|---|---|---|---|---|
| as committed (no directory, V2's frozen thresholds) | 1.15 / 1.20 | +46.6 MB | 1.0106 | 1.0132 | 1.0010 |
| production-like (directory + candidate thresholds) | 1.10 / **1.25** | **+58.1 MB** | 1.0107 | 1.0142 | 1.0011 |
| budget | ≤ 1.25 | ≤ +50 MB | ≤ 1.02 | ≤ 1.02 | ≤ 1.02 |

The Sleeper directory index adds about 11.5 MB of peak RSS and puts the production
configuration over budget; the wall ratio is noisy on this shared host.

## What remains before the held-out Stage 4

1. **Repairs to the cold-start failures (decision-affecting, so before Stage 2, each a
   logged deviation, and an owner question where a fixed constant is involved):**
   vendor Sleeper ids that resolve to a placeholder or contradict name + position + team
   (A1 on DynastyNerds); the DraftSharks age offset against τ_age = 1.0 (R5's constant was
   fixed a priori, so changing it needs the owner); A4 on name-only duplicate listings; the
   B1 label scope for E_BASELINE rookie boards (or an independent review that clears those
   505 as B1-proven); the Layer C cold-start drop (Ekeler) against O-1's "never drops a
   legitimate vote".
2. **AD2-N**: consult the identity owner's Sleeper directory for same-group homonyms, as
   registered; today only board rows are read.
3. **U2 autocomplete false refusals**: a correct autocomplete capture is always refused.
   Either the scraper records the position the autocomplete text shows, or the rule changes;
   it must be settled before U2 ships.
4. **AD3 registration defect** (owner decision): on the registered pre-Layer-A seam, three of
   the four kinds cannot change a vote, so 16 / 16 is unreachable; and on V2's seam B4
   pre-empts B3's board flag. Needs a recorded owner decision on the seam and on whether a
   B4 hold of every corrupted vote counts as "flagged before voting".
5. **Wrong-player gate**: AD2 as registered tops out near 50% (B4 only). O-2 (gate on AD2-ID)
   is still open; even AD2-ID clears 90% only where the source publishes identity fields.
6. **Selection**: B3 fails on a source's first board (no baseline) and τ_C fails the cold-start
   constraint; both are registered FAILED_SELECTIONs, so READY FOR APPROVAL is unreachable for
   this registration unless the underlying causes are fixed and logged before Stage 2.
7. **Identity prerequisites live**: U2, U2b, U3 and VID merged, deployed and running in the
   automated refresh before **2026-11-04T00:00Z** (the G1 date); otherwise BLOCKED.
8. **PERSISTENT residual** (reported, not a gate): a corruption that persists across four
   vendor publications becomes the source's accepted view and votes (P-3 / P-4, alerted).
   The owner should see this measured residual before any activation decision.
9. **Performance**: bring the production-like RSS within +50 MB (the directory index) and
   restore wall-time margin.
10. **Stage 2 freeze** (`config/sources/outlier_integrity_v21.json` + evaluator frozen) and
   **Stage 3** (L1-L3 on pin2015 / pin0527 / pinOB, §6 boards on the R pins, criteria 13-14
   on pin2015, the full hard gate, frontend suite, 24,024 identity parity). Evaluator gaps
   to close first: tether-aware attribution, the full PERSISTENT run.
11. **Stage 4** once: earliest **2026-11-25T00:00Z** (the last H_TARGET board, prereg §5.3),
    if ≥ 56 complete H_ORIGIN boards on ≥ 20 UTC days with ≥ 7 per week-block exist by
    2026-11-18; otherwise the window extends a day at a time, at most 14 days (latest
    2026-12-09T00:00Z), then INSUFFICIENT.

## Reproduce

All commands from the repository root with full git history; records go to
`data/oiv21_dev/` (gitignored). `--directory` is the Sleeper directory snapshot (V21-D2).

```bash
D=--directory=/path/to/nfl_players.json
python scripts/oiv21_dev.py $D collect          # Stage-2-shaped input pass, provisional thresholds
python scripts/oiv21_dev.py $D select1
python scripts/oiv21_dev.py $D collect_b3off && python scripts/oiv21_dev.py $D select1b   # V21-D16
python scripts/oiv21_dev.py $D kc && python scripts/oiv21_dev.py $D select2
python scripts/oiv21_dev.py $D tauc && python scripts/oiv21_dev.py $D select3
python scripts/oiv21_dev.py $D chain
for b in dynasty_export_20260909_211525.zip dynasty_export_20260930_130404.zip; do
  for v in ARRIVING NOHIST; do python scripts/oiv21_dev.py $D gates --board $b --variant $v; done
  python scripts/oiv21_dev.py $D persistent --board $b --per-gate 60
  python scripts/oiv21_dev.py $D boards --board $b
done
python scripts/oiv21_dev.py $D coldstart
python scripts/oiv21_dev.py $D evaluate
python scripts/oiv21_perf.py dynasty_export_20260930_130404.zip OUT.json
```
