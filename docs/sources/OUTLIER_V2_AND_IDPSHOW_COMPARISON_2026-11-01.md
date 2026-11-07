# Outlier integrity V2 four-arm comparison and IDP Show board comparison (2026-11-01)

**Status:** read-only comparative evaluation under owner decision D5 (2026-11-01). No flag,
config, freshness setting, hold or production value was changed. PR #1884's branch was not
modified. Every build ran in a local process; flags were toggled in-process only.
**Agent-OS-Receipt:** 47a8b19fff9d06da9b1a651aab5fb92f1e16d5f6
**Evidence:** [`evidence/outlier_v2_comparison_2026-11-01.json`](evidence/outlier_v2_comparison_2026-11-01.json)

## 1. Recommendation (owner-ready)

| decision | recommendation | why (numbers below) |
|---|---|---|
| Activate outlier integrity V2 / V2.1 | **HOLD** | PR #1884's own verdict is MORE RESEARCH REQUIRED: mandatory safety gates fail (wrong player, AD3, cold-start safety, performance, two FAILED_SELECTIONs). On this board, with no history, V2.1 excluded only 3 votes. It removed the incumbent's false rejections, but it supplied almost no statistical protection of its own. |
| Release DLF IDP + DLF Rookie IDP + D4 (DLF Values offense) | **HOLD** (D5 unchanged) | With the incumbent filter the release causes 32 new rejections of other providers' votes. All 32 are plausible, and IDP rows move up to 33.5%. Under V2.1 the same release is bounded: IDP max 3.9%, offense max 5.7%, picks max 3.6%. So the release is safe only together with a V2 that passes its gates. |
| Switch the IDP Show vote from the combined board to the IDP-only board | **HOLD, and gate it on V2 like DLF IDP** (answers open decision D-A in `IDP_SOURCE_AUTHORITY_2026-10-28.md` with "yes") | With no filter, elite IDP rows barely move (Myles Garrett 3,510 → 3,505). With the incumbent filter they move 30–52%, because 33 Draft Sharks IDP / FantasyPros IDP votes get dropped. V2.1 kept 25/25 such votes on the DEV board. The IDP-only board is itself 23 days old now (v2 schedule 0.25). |
| Freshness schedule v2 | **keep OFF** (owner-held) | Computed only, not applied. It would zero FantasyPros IDP (v1 gives 0.171), raise IDP Trade Calculator (0.198 → 0.5), halve Yahoo/Boone and quarter Fitzmaurice. |
| Before any evaluation of record | rebase #1884 on `main` | On the same board, the PR head with flags off differs from current `main` on 66 rows: 49 IDP rows (mostly ±1), 15 tethered 2026 picks, and 2 offense rows. Akheem Mesidor moves −2.6%. |

**Bottom line.** The data support the V2 direction. The incumbent filter, not the DLF sources,
causes the large moves, and it already throws away plausible votes today (arm A). But nothing
here clears V2 for activation, so every hold stays.

## 2. Frozen input and provenance

| item | value |
|---|---|
| `main` | `47afa2f09f0d6ac6de76b838dc1c979e365671e8` (2026-11-01T15:33Z) |
| PR #1884 head | `58ed2ff8016b0c837616a9f96e224e143e890fcb` (clean detached worktree) |
| four-arm board | `dynasty_export_20260930_130404.zip` (V2.1 DEV / E_DEV, "G2dev")<br>add commit `10c9d7429a`<br>zip sha256 `59338ef0…cede7e`<br>payload sha256 `8e5c0f24…53000f`<br>both hashes match `POPULATIONS.json` |
| four-arm harness | the PR's own `src/robust_filter_shadow/oiv21_dev.build`<br>CSVs materialized at the add commit; dataset state replayed to the cut |
| V2.1 thresholds | exploratory candidates rebuilt exactly as `select3` writes them: ε 0.01, k_c 4, τ_C ln 6 (`devContinuation`; τ_C and B3 are FAILED_SELECTION) |
| history | NO-HISTORY (history lane empty; B4 and B3a abstain) |
| Sleeper directory | none |
| IDP Show board | `dynasty_export_20261020_121619.zip` (pinOB)<br>payload sha256 `67f6d56e…1d31ce`<br>built with `main` code<br>its `idpShow.csv` blob `d7aa2473` is identical to today's |
| determinism | A, C and D rebuilt: playersArray sha256 identical |

**Why the newest payload was NOT used (deviation from the brief).** The newest archive,
`dynasty_export_20261101_065453`, and every archive after T0 (2026-10-20T20:00:30Z) are sealed:
they form the V2.1 preregistered fresh held-out set (prereg §5.3, `HELDOUT_RULE.json`). The rule
reads: "no V2.1 or incumbent build, score, injection or descriptive scan may read an H board"
before the Stage 4 run. Building these arms on it would spend that held-out set. So I froze the
newest DEV board V2.1 may read (G2dev).

The IDP Show comparison does not use V2.1, so it ran on pinOB: the newest pre-T0 board, which
already carries today's IDP-only board.

Cross-check: my arm counts reproduce the PR's committed G2dev NO-HISTORY record:

| quantity | committed record | this run |
|---|---|---|
| newly dropped votes | 32 | 32 |
| C″ vs A, rows moved ≥ 1% | 202 | 201 |
| D vs A, rows moved ≥ 1% | 95 | 94 |

The 1-row gaps come from the Sleeper directory, which the committed run used and this one did
not.

## 3. Four arms (one board, same data, weights and config)

* **A:** incumbent sources + incumbent Hampel.
* **B:** proposed sources (`dlfIdp`, `dlfRookieIdp`, `dlfValuesSfTep`/D4 voting) + incumbent.
* **C:** proposed sources + V2.1.
* **D:** V2.1 with the held sources still held.

### 3.1 Rejected votes and their classification

**Classification rule** (independent of the filter's statistic):

* **INVALID**:
  * the value is missing, non-finite, ≤ 0 or > 9999; or
  * an IDP-only source votes on an offense row; or
  * the vote is an untranslated rookie rank.
* Otherwise the vote is compared with the nearest pre-filter vote of a **different correlation
  family** on the same row:
  * **LEGIT_CORROBORATED**: within 2×;
  * **LEGIT_DISSENT**: 2–4×;
  * **UNDETERMINED_EXTREME**: more than 4×, or no other family on the row.
* A filter identity verdict with no structural invalidity is **UNVERIFIED_IDENTITY_CLAIM**.

| arm | votes rejected / observations | offense / IDP | corroborated | dissent | invalid | unverified identity |
|---|---|---|---|---|---|---|
| A | 146 / 7,545 (1.9%) | 118 / 28 | 142 | 4 | 0 | 0 |
| B | 166 / 8,064 (2.1%) | 125 / 41 | 163 | 3 | 0 | 0 |
| C | 3 / 8,064 (+1 non-vote refusal) | 2 / 1 | 0 | 0 | 1 (non-vote) | 3 |
| D | 3 / 7,545 (+1 non-vote refusal) | 2 / 1 | 0 | 0 | 1 (non-vote) | 3 |

* **The incumbent's rejections.** By source in A: Draft Sharks 44, Draft Sharks IDP 17,
  Yahoo/Boone 13, PFK 10, FantasyPros IDP 10, KTC Crowd 9 and others. No incumbent rejection
  was structurally invalid.
* **The incumbent's blind spot.** The incumbent kept every invalid or ambiguous observation that
  V2.1 refused.
* **V2.1's three refusals** are `identity_unresolved:ambiguous_in_source`:
  * IDP Show on Justin Jefferson (WR), 7,531;
  * IDP Show on Byron Murphy, 2,603;
  * Flock on Cole Payton, 1,432.

  Each sits within 1.01–1.06× of another provider, so they are probably legitimate duplicates.
  This is the cold-start class A4 that the PR already reports.
* **V2.1's non-vote refusal** is the Draft Sharks IDP entry on the WR Justin Jefferson row. It
  is genuinely invalid, but it never reached the vote.
* **Restoration-induced drops.** With the incumbent, restoring DLF newly rejects 32 votes of
  other providers (DLF's own excluded). All 32 are LEGIT_CORROBORATED: Draft Sharks IDP 7,
  IDP Trade Calculator 4, FantasyPros IDP 3, FantasyPros SF 3, PFK 3, IDP Show 2, FantasyCalc 2,
  Fantasy Navigator 2, KTC Trades 2, KTC Crowd 2, Draft Sharks 1, Fitzmaurice 1. **V2.1 retains
  32 / 32.**

### 3.2 Value, rank and membership changes against arm A

The percentages are the absolute % change over the rows that moved. Ranks are board-wide, so
a single IDP move shifts every rank below it; read "rank ≥ 10" as the material count.

| comparison | class | rows moved | ≥ 1% | ≥ 5% | ≥ 10% | median % | p90 % | max % (row) | rank Δ ≥ 10 |
|---|---|---|---|---|---|---|---|---|---|
| B vs A | offense | 311 | 54 | 3 | 0 | 0.28 | 1.70 | 5.7 (Tanner McKee) | 19 |
| B vs A | IDP | 177 | 84 | 11 | 10 | 0.91 | 3.09 | 33.5 (Cedric Gray) | 43 |
| C vs A | offense | 321 | 95 | 6 | 1 | 0.46 | 2.18 | 20.0 (LaJohntay Wester) | 39 |
| C vs A | IDP | 178 | 95 | 17 | 17 | 1.16 | 4.00 | 78.2 (Kool-Aid McKinstry) | 52 |
| D vs A | offense | 76 | 54 | 4 | 1 | 1.41 | 2.89 | 20.0 (LaJohntay Wester) | 14 |
| D vs A | IDP | 28 | 27 | 22 | 17 | 17.3 | 42.3 | 78.2 (Kool-Aid McKinstry) | 24 |
| **C vs D** (restoration under V2.1) | offense | 310 | 46 | 3 | 0 | 0.26 | 1.40 | 5.7 (Tanner McKee) | 22 |
| **C vs D** | IDP | 176 | 79 | 0 | 0 | 0.84 | 2.45 | 3.9 (Gabe Jacas) | 33 |
| C vs B (filter, sources restored) | IDP | 35 | 34 | 23 | 23 | 18.7 | 36.2 | 78.2 | 25 |

**Top-200 membership changes against A** (4 / 5 / 4 players entering and leaving):

| arm | entered | left |
|---|---|---|
| B | Jamien Sherwood, Jonathon Brooks, Josiah Trotter, Rhamondre Stevenson | Byron Young, Eli Raridon, Michael Pittman, Zach Charbonnet |
| C | Antonio Williams, Jamien Sherwood, Jonathon Brooks, Laiatu Latu, Rhamondre Stevenson | Byron Young, Danielle Hunter, Derwin James, T.J. Watt, Zach Charbonnet |
| D | Antonio Williams, Chris Godwin, Jamien Sherwood, Rhamondre Stevenson | Byron Young, Danielle Hunter, Derwin James, T.J. Watt |

**Attribution of the large moves**, per vote; full detail in `moverAttribution` in the evidence
file.

* **B's IDP moves are the incumbent's reaction to DLF, not DLF's own vote:**
  * Cedric Gray: Draft Sharks IDP 6,227 and FantasyPros IDP 4,811 dropped;
  * Will Anderson and Aidan Hutchinson: Draft Sharks IDP and IDP Show dropped;
  * Josiah Trotter: Draft Sharks IDP 1,609 and FantasyPros IDP 1,863 dropped;
  * Jamien Sherwood and Nick Herbig: IDP Trade Calculator dropped.
* **D's moves are V2.1 restoring votes the incumbent rejects today, without DLF:**
  * Kool-Aid McKinstry 1,026 → 1,828 (Draft Sharks IDP 2,790 restored);
  * Trevin Wallace 1,292 → 1,989;
  * Jamien Sherwood 2,288 → 3,493;
  * CJ Allen 3,050 → 4,087;
  * Myles Garrett 5,275 → 3,789 (Draft Sharks IDP 1,947 restored);
  * T.J. Watt 3,306 → 2,475;
  * LaJohntay Wester 775 → 930 (Flock 1,923 restored).
* **Cost of D on the current board.** Arm D isolates the filter change, so this is what V2.1
  alone would cost or repair on today's source set: 17 IDP rows move by 10% or more.

### 3.3 Picks (indirect effects)

| comparison | pick rows moved | which | max |
|---|---|---|---|
| B vs A | 66 | all `2026 Pick x.yy`, provenance `rookie_pool_tether` | 6.5% (2026 Pick 3.04) |
| C vs A | 65 | all 2026 tether | 7.0% (2026 Pick 1.12) |
| D vs A | 29 | all 2026 tether | 7.1% (2026 Pick 1.12) |
| C vs D | 63 | all 2026 tether | 3.6% (2026 Pick 1.08) |

* **Synthetic and future picks:** 0 rows moved in every arm. No 2027–2029 vendor-priced or
  `derived_year_step` / `derived_round_step` / generic row moved.
* **How the moves reach picks:** every pick move travels through the current-year rookie-pool
  tether, from rookie value changes such as Jacob Rodriguez, Sonny Styles and Caleb Downs. The
  per-row list is in the evidence file.

### 3.4 Coverage and confidence

| arm | IDP priced / ranked | IDP families per row: median (distribution) | IDP confidence high / medium / low | offense confidence high / medium / low |
|---|---|---|---|---|
| A | 396 / 297 | 3 (1:41, 2:72, 3:99, 4:184) | 0 / 201 / 195 | 135 / 216 / 145 |
| B | 396 / 297 | 4 (…, 4:122, 5:112) | 43 / 162 / 191 | 138 / 218 / 140 |
| C | 396 / 297 | 4 (…, 4:96, 5:145) | 48 / 136 / 212 | 129 / 227 / 140 |
| D | 396 / 297 | 4 (…, 4:211) | 0 / 189 / 207 | 126 / 224 / 146 |

* **Priced counts are unchanged** in every arm: offense 496, IDP 396, picks 132. No row changed
  between priced and unpriced.
* **V2.1 lowers confidence on contested rows** (D: 12 IDP rows medium → low). That is the
  intended "disagreement lowers confidence, not voting power" behaviour.

## 4. IDP Show: IDP-only board vs the combined board

**Inputs.** pinOB with `main` code. The what-if re-points the single `idpShowCombined` family
key at `CSVs/site_raw/idpShow.csv`, with the retired entry's semantics:

* scope `overall_idp`, no offense scope;
* shared-market translation through IDP Trade Calculator's ladder;
* depth 350.

The family still casts one vote. The combined board's stale dataset clock was removed for the
emulated board, and its weight was set by override to:

* v1 0.868 (C4 at the vendor date, as of the board);
* v2 0.75;
* 1.0.

The three weights give practically identical results, so the table shows v1.

**Sanity check.** The emulated board votes on 347 IDP rows and 0 offense rows. It reproduces the
2026-10-28 report's Hutchinson 6,422.

| quantity | combined (I0) | IDP-only, incumbent (I1) | IDP-only, no filter (attribution) |
|---|---|---|---|
| votes rejected by the filter | 102 (all offense) | 135 (102 offense + 33 IDP) | — |
| newly rejected IDP votes of other providers | — | 33: Draft Sharks IDP 22, FantasyPros IDP 11. 28 corroborated, 5 dissent, 0 invalid | 0 |
| IDP rows moved (≥ 1 / ≥ 5 / ≥ 10%) | — | 363 (202 / 62 / 43); p90 24.5% | 360 (185 / 34 / 21); p90 4.8% |
| ranked IDP rows, largest moves | — | Garrett +51.8%, CJ Allen −46.4%, T.J. Watt +44.7%, Sherwood −40.6%, Hutchinson +36.1% | Garrett 3,510 → 3,505, Hutchinson 4,718 → 4,718 |
| deep single-source rows +150% or more (haircut switch, not the filter) | — | 16 (e.g. Marques Sigle 234 → 828) | same 16 |
| IDP median `retainedAuthority` | 0.563 | 0.807 | — |
| IDP confidence medium / low | 121 / 276 | 214 / 183 | — |
| pick rows moved | — | 56, all `2027 Pick` rookie-pool tether (the current class on that board); max 9.8% (2027 Pick 1.08); 0 future-year | — |
| top 200 | — | in: Van Ginkel, Byron Young, Danielle Hunter, Derwin James, Latu, Bosa, Watt; out: Barrett Carter, Braelon Allen, CJ Allen, Overshown, Sherwood, Edmunds, Woody Marks | — |

**With V2.1 (DEV board G2dev, PR code, weight 1.0).** This board carries the IDP-only content
from before the 2026-10-08 republication.

* With the incumbent, the switch newly rejects 25 other-provider votes (23 corroborated, 2
  dissent).
* **V2.1 retains 25 / 25.**
* V2.1's own rejections: 3 identity refusals.

**Finding.** The IDP-only board is the fresher IDP Show opinion, and with no filter it changes
elite IDP rows by about 2% at most. The large swings come from the incumbent filter, through the
same synthetic-tie / MAD-collapse mechanism as DLF IDP. FantasyPros IDP and the IDP-only board
both translate to 6,227 on Hutchinson through IDP Trade Calculator's ladder. The switch should
therefore be gated on V2 exactly like DLF IDP. The 16 haircut-switch rows are a separate
single-source-haircut effect and need their own review.

## 5. Vendor clocks against fetch time, and what v2 WOULD do

As of 2026-11-01T15:45Z, from `data/scrape_state` through `src/sources/freshness.assess_source`.
Computed only; nothing applied.

| source | genuine content / publication evidence | last fetch | v1 factor (in force) | v2 factor (held OFF) |
|---|---|---|---|---|
| dlfIdp (held) | content change observed 2026-11-01 14:27 (no vendor timestamp; the clock is the observed change) | 11-01 14:27 | 1.0 | 1.0 |
| dlfRookieIdp (held) | content change 2026-10-30 22:27 | 11-01 14:27 | 1.0 | 1.0 |
| dlfValuesSfTep (D4 held) | content change 2026-11-01 12:27 (cadence 24 h) | 11-01 14:27 | 1.0 | 1.0 |
| dlfSf | content change 2026-10-31 14:27 | 11-01 14:27 | 1.0 | 1.0 |
| idpShowCombined (voting) | vendor `U8I37` v4 `lastModifiedAt` 2026-08-19 17:50 (74 days) | 11-01 14:32 | 0 (quarantined) | 0 |
| idpShow IDP-only (not registered) | vendor `PP0IJ` v18: `publishedAt` 2026-10-09 13:14, `lastModifiedAt` 10-09 21:24; content first changed in our CSV 10-17; 23 days. No dataset state is recorded: registering it today would read as *not tracked* = 1.0 unless the upstream clock is consumed | 11-01 14:32 | ≈ 0.33 (C4, 168 h seed) | 0.25 |
| draftSharksIdp | content change 2026-11-01 15:33 | 11-01 15:33 | 1.0 | 1.0 |
| fantasyProsIdp | vendor `last_updated_ts` 2026-09-04 02:34 (58 days) | 11-01 15:33 | 0.171 | **0** |
| idpTradeCalc | content change 2026-10-10 20:25 (21 days) | 11-01 15:30 | 0.198 | **0.5** |
| yahooBoone | content change 2026-10-14 | 11-01 15:33 | 1.0 | **0.5** |
| fantasyProsFitzmaurice | content change 2026-10-02 | 11-01 15:33 | 1.0 | **0.25** |

**Fetch time is not freshness.** Every fetch is within the last few hours, while IDP Show
(combined), FantasyPros IDP and IDP Trade Calculator have not genuinely changed in 3–10 weeks.

**What v2 would do on IDP rows today.** IDP voting would be:

| source | v2 weight |
|---|---|
| Draft Sharks IDP | 1.0 |
| IDP Trade Calculator | 0.5 |
| FantasyPros IDP | 0 |
| IDP Show | 0 |
| DLF | held |

That leaves two weighted IDP families. Whether that is better is an owner question; it stays OFF.

## 6. Could not be computed locally (missing is not zero)

1. **The newest payload (2026-11-01).** It is sealed held-out data (V2.1 prereg §5.3). Needs
   either the Stage 4 run (earliest 2026-11-25, one run at one SHA) or an explicit owner waiver
   logged in `docs/sources/outlier_integrity_v21/DEVIATIONS.md` before use.
2. **The ARRIVING (with-history) variant.** It needs the PR's `oiv21_dev.py chain` pass over all
   44 E_DEV boards to build the V2.1 history lane, plus a Sleeper directory snapshot (`--directory`).
   The PR's committed record for this same board shows 32 → 32 retained in that variant too.
3. **Frozen V2.1 thresholds.** They do not exist: Stage 2 recorded FAILED_SELECTION for τ_C and
   B3. Every C/D number uses exploratory candidates.
4. **Ground truth for "legitimate vs invalid".** The rule in §3.1 is a plausibility screen. It
   cannot see a wrong-player or scale error whose value lands within 2× of another provider; that
   needs injected-corruption gates (the PR's AD1–AD4) and identity evidence (U2/U2b/U3/VID,
   which must be live before 2026-11-04 or the V2.1 verdict is BLOCKED).
5. **IDP Show what-if fidelity.** It emulates a retired registry entry:
   * the identity / position mapping of `idpShow.csv` was not audited (350 rows, 347 joined);
   * its freshness is emulated by a weight override;
   * V2.1 was not run on pinOB (an R pin, reserved for Stage 3), only on the DEV board, which
     holds the older IDP-only content.
6. **Flag-off parity with current `main`.** It fails on 66 rows, because the PR head is behind
   `main`. A rebase plus a fresh flag-off identity check is needed before any evaluation of
   record.
7. **Tier changes.** They are reported in the evidence file but are dominated by board-wide
   re-tiering, so per-row tier attribution was not attempted.

## 7. Reproduce

The helper scripts are kept out of the repo; they live in the session scratchpad:
`arms_build.py`, `arms_analyze.py`, `gi_analyze.py`, `idpshow_build.py`, `idpshow_analyze.py`,
`clocks.py`, `make_evidence.py`.

* **Four arms.** In a detached worktree of `58ed2ff801`, run
  `python arms_build.py dynasty_export_20260930_130404.zip OUT A,Anf,B,Bnf,C,D`, then
  `python arms_analyze.py OUT OUT/analysis.json`.
* **IDP Show.** From `main` `47afa2f09f`, run
  `python idpshow_build.py dynasty_export_20261020_121619.zip OUT 0.868 0.75`.
* **Cost.** Each build takes about 2–3 s on this host.
