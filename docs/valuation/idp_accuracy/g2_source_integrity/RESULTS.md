# Workstream G2: IDP source-integrity evaluation — results

**Status:** RESEARCH_ONLY / TESTED. SHADOW: no served value, rank, vote, weight, flag, lineage entry or deployment
changed. The preregistration is commit `0c81b7f77`. The evaluator is commit `9622ea48e`. The single held-out run and
the development records were committed exactly as produced in `7ed123139`. Deviations D1–D5 are in
[`DEVIATIONS.md`](DEVIATIONS.md). D4 (review cleanup: registered injection floors enforced, E1 with lineage, B-gates
emitted by the evaluator, seal checked before any archive read) re-ran the held-out board once:
`evidence/heldout_20261020_173527_rerun_D4.json`. **No verdict changed**, and the gate tables below quote that
record's `eGates` / `bGates` verdicts.

Agent-OS-Receipt: cb64f74cf4d2763aa16d55ba0d6350f585a2a42f

**Reproduce:**

```bash
python scripts/research_idp_source_integrity_g2.py --board dynasty_export_20261020_173527.zip --role heldout --out OUT.json
python scripts/research_idp_source_integrity_g2.py --exploratory --board dynasty_export_20261020_173527.zip --role heldout --out D1b.json
python -m pytest tests/robust_filter_shadow/test_idp_source_integrity_g2.py -q
```

* The served build is about 1.4 s and the evaluation about 0.07 s.
* `evaluation.digest` is `4ac384fc298b…` and the served panel digest is `1188401bebdc…`.
  * E1 covers the evaluation only: two evaluations of one panel, with voting status, content clocks and lineage,
    give `4ac384fc298b…` (the original record's E1 omitted lineage and printed `ed3525f267bc…`, a different input;
    fixed in D4).
  * The panel's reproducibility is shown separately: the D4 rerun rebuilt the board in a new process and got the same
    served and dlfRestored panel and evaluation digests as the original record.

## 0. Read this first

The held-out set is **one board**, `dynasty_export_20261020_173527` (preregistration §2). It is the only tracked
archive that Outlier Integrity V2 and the IDP lanes never read and that the V2.1 seal does not cover. At its refresh
commit only `draftSharksIdp.csv` differs from the development boards. For IDP Trade Calculator, FantasyPros IDP, DLF
IDP, DLF Rookie IDP and both IDP Show boards, every B-gate result below **replicates** the development boards on a fresh
build: same CSV bytes, new offense context. It is **not** independent evidence. A prospective held-out set (boards
added on or after 2026-12-09) is registered and not yet run.

## 1. Evaluator validity (E-gates): 11 / 11 PASS

| gate | result |
|---|---|
| E1 determinism | PASS (one digest over two evaluations, `4ac384fc298b…`) |
| E2 vendor family | PASS 30 / 30 (registered count 30 met) |
| E3 Sleeper id | PASS 20 / 20 (registered count 20 met) |
| E4 shared vendor entry | PASS 20 / 20 (registered count 20 met) |
| E5 segment scale ×5 / ×0.2 | PASS 18 / 18 (no clean segment shifted) |
| E6 single-vote corruption ×8 | PASS recall 1.000 (200 votes, registered count met); clean extreme rate 0.0015 (limit 0.05) |
| E7 wrong-player swap (≥ 4× apart) | PASS on the registered point estimate: 19 / 21 = 0.905 ≥ 0.80. **21** swaps, just above the INSUFFICIENT floor of 20 (now enforced in code). Wilson 95 % lower bound **0.711**, below 0.80, so the pass is not established at 95 % confidence |
| E8 rank inversion | PASS 20 / 20 (registered count 20 met) |
| E9 stale stamp | PASS |
| E10 runtime | PASS 0.065 s |
| E11 rank-basis restart | PASS 5 / 5 sources |

**What this does and does not establish.**

* The diagnostic finds injected identity, family, normalization, segment-scale, staleness and gross single-vote
  errors on this board.
* It cannot see a corruption smaller than ×3 on a three-provider row.
* It cannot see a swap between players valued within 3× of each other.
* It cannot evaluate rows with fewer than three providers. That is 271 of 946 votes (29 %), concentrated in the deep
  tail.
* That is the same blind spot that sank V2. G2 does not claim to close it; it reports it.

## 2. Board integrity (B-gates), served held-out build: 6 PASS / 2 FAIL

Verdicts are the evaluator's `bGates` output in the D4 rerun (`summary`: passed 6, failed 2), scoped to the seven
registered IDP sources. The offense source `fantasyNavigatorSf`, observed once on an IDP row and never voting, is
outside every gate (`nonIdpSourcesObserved`; explained in DEVIATIONS).

| gate | result | detail |
|---|---|---|
| B1 identity | **FAIL** | 8 DEFECT findings (6 `vendor_family_mismatch`, 2 `dual_listing_wrong_family`), adjudicated in §3 |
| B2 normalization | PASS | 0 translation inversions, 0 value inversions, 0 non-positive votes, 0 `rank_basis_mixed` on any IDP source |
| B3 stale | **FAIL** | `fantasyProsIdp`: `vendor_stamp_older_than_broad_change`, lag 475 h (§4 M1). Every other source is consistent |
| B4 attribution | PASS | 1 extreme vote, `unexplained_extreme_dissent` (Jacob Rodriguez, FantasyPros, u = −1.17); 0 corroborated data errors |
| B5 false exclusions | PASS | 0 on the served build. No IDP row reaches the filter's minimum of 4 votes |
| B6 segments | PASS | max \|median u\| 0.23 (IDP Trade Calculator, DB and LB), limit 0.92 |
| B7 missing never zero | PASS | 0 priced rows without a vote, 0 non-positive values. 10 quarantined `no_valid_source_values` rows stay unpriced |
| B8 lineage | PASS | every IDP source maps to a provider. Recorded relations: `dlf-same-provider`, `idptc-idpshow-dependence` (measured), `idptc-idpshow-suspected-ancestry` (suspected), `rookie-ladder-borrows-reference-scale` (proven). No cap is implied: none is shared data lineage between VOTING providers |

**Predictions:**

* **P1, confirmed.** With the DLF IDP hold turned off in-process, the incumbent filter drops **31 votes on IDP rows
  that carry no structural defect**: Draft Sharks 17, FantasyPros 10, IDP Trade Calculator 3, DLF 1. That is the V2
  root cause (31 drops: DS 18 / FP 10 / IDPTC 3) on a fresh build. 0 of the 31 carry an identity, family,
  normalization or staleness defect.
* **P2, confirmed.** Draft Sharks is an LB-dominant combined list: LB slope 1.21, DL 3.17, DB 3.96 at k = 24. There
  are no cross-family collisions once vendor ties are excluded, so it is `familyDominanceOnly`, **not** a mixed rank
  basis.

**The dynasty-lane analogue of PR #1997.**

* No dynasty IDP source shows a rank-basis discontinuity (B2, E11 sensitivity confirmed).
* There **is** a coverage discontinuity, defect G2-D1 below.

## 3. Data-integrity defects found (each with evidence)

Severity is the effect on today's served values. Inputs are the CSVs at refresh `c2b44022f0` and the held-out build.

| id | defect | evidence | served impact | status |
|---|---|---|---|---|
| **G2-D1** | **The IDP board universe appears gated on IDP Trade Calculator membership.** Vendor entries ranked by a voting IDP provider other than IDPTC are absent from the board when IDPTC does not list them. The counts are entries on EITHER list (Draft Sharks or FantasyPros), not players that both providers rank | D1b (`evidence/exploratory_D1b_heldout_20261020_173527.json`, rule in DEVIATIONS D5: vendor FILE order; an unjoined entry is `absent` unless an IDP board row of the same family carries its name as any source's match or has its name key). **Draft Sharks**, file positions 1–150: 3 absent; 151–300: 24 by the rule, 23 after one hand adjudication (JT Tuimoloau is on the board as "Jaylahn Tuimoloau" through a scraper-side alias, G2-D2). **FantasyPros**, 299 rows, all inside 1–300: 1–150: 2 absent; 151–299: 27 absent. Total **29**. Six more unjoined FP entries are rookies that ARE on the board through other sources' joins, so they are not counted. The FP bands are vendor file order (its `effectiveRank` order). They are not a "combined" rank: `originalRank` is per position on 180 of the 299 rows. **Reconciling 23 / 28 / 29.** The first write-up's FP 23 came from bands sorted by `originalRank`, followed by a hand recount. The reviewer's 28 is what a name-key-only rule gives: it puts the CB Byron Murphy Jr. on the DT Byron Murphy row (the G2-D4 collision). The family-aware rule keeps him absent, which gives 29. **IDPTC check:** of the 26 DS + 29 FP = 55 absent entries (a player on both lists counts twice), the key test finds one per vendor in `idpTradeCalc.csv`, and both are false hits: "Byron Murphy" / "Byron Murphy Jr." (CBs) match the DT's IDPTC key (IDPTC has no position column). **0 of 55** are listed by IDPTC. Examples: D'Angelo Ponds (DS 99; FP `effectiveRank` 130), Maxwell Hairston (DS 87), Benjamin Morrison (DS 140), Germaine Pratt (FP 99), Jamel Dean (DS 299; FP 157), Kenny Moore II (FP 156), A.J. Terrell Jr. (FP 164) | Those players have no row: not unpriced-and-listed, simply absent. A CB that a dynasty provider ranks inside its top 150 cannot appear in rankings, rosters or trades | NEW. The universe-construction owner is outside this shadow lane. A methodology question as much as a defect (M3) |
| **G2-D2** | **Cross-source alias inconsistency.** The vendor name "JT Tuimoloau" joins the board row "Jaylahn Tuimoloau" for IDPTC but not for Draft Sharks | `draftSharksIdp.csv` line 287 (`JT Tuimoloau, DL`, rank 286); the board row's `matchedSources` are `["idpTradeCalc"]`, reason `structurally_single_source`, value 273 | One row is single-source (30 % haircut path) when two providers cover it | NEW |
| **G2-D3** | **`excludes_rookies: True` contradicts the data** for `fantasyProsIdp` (and `dlfIdp`) | FantasyPros IDP matches **12 of 70** rookie IDP rows (Arvell Reese, Caleb Downs, CJ Allen, David Bailey, …). DLF IDP matches 18 when the hold is off (Jacob Rodriguez DLF IDP rank 9). Neither is ever an `expectedSource` on a rookie | Values: none. Coverage and confidence: FantasyPros' silence on the other 58 rookies is not counted as missing evidence (coverage denominator), and the structural-single-source logic treats it as ineligible. Every IDP row is `low` today, so no bucket moves | NEW |
| **G2-D4** | **Same-name collision: a second player is missing.** CB Byron Murphy Jr. (MIN) has no board row. The board's only "Byron Murphy" is the DT (Sleeper 11668) | FP lists "Byron Murphy Jr., CB, MIN" at combined 162; DS lists "Byron Murphy, DB" at 254 beside "Byron Murphy II, DL" at 82. `idpShowCombined.csv` lists "Byron Murphy, DL" twice (rows 238 and 589). `sleeper.playerIds` holds one "Byron Murphy" | The CB is absent (G2-D1 class, plus a probable name-key collision). The DT's joins are correct: DS and FP chose the "II" entry. The IDP Show join is unresolvable but withheld (stale) | NEW. The cause needs the Sleeper directory (network) to confirm: UNRESOLVED |
| **G2-D5** | **Vendor position family outside the league's family** | Christian Elliss: `idpShowCombined` says DL, the same vendor's `idpShow` says LB, Sleeper says LB, so the vendor is internally inconsistent. Harold Landry: DS and IDP Show say DL, Sleeper LB. Baron Browning: DS DL / Sleeper LB. Oluwafemi Oladejo: DS LB / Sleeper DL. Tyree Wilson: FP DL / Sleeper LB | A vendor value built for another position is applied to this league's position. Size is not measured. IDP Show is withheld | NEW. Landry, Browning, Oladejo and Wilson have no `sleeper.fantasyPositions` entry, so their league eligibility is **unverifiable** (deviation D3) |
| **G2-D6** | **The FantasyPros dual listing takes a family the league does not allow** | Trey Hendrickson is DL-only in Sleeper. The FP vote uses the LB listing (combined 89) rather than the DL listing (combined 118), `rawRank` 89 in `sourceRankMeta` | Small: one row, FP vote 1,916 from the better listing | KNOWN, recorded in the `source_lineage.json` defects (dual-listing, fix deferred). G2 adds that for DL-only players the better listing is the inapplicable family |
| **G2-D7** | **Duplicate vendor entry.** `idpTradeCalc.csv` carries "Andru Phillips 864" and "Dru Phillips 864" (same player); "Joey Bosa 755" vanished in the same commit | Diff `f623436ae~1..f623436ae` (2026-10-16). The board row joins both names as candidates of one row | None today (identical values, one row). Correctly not counted as a broad publication | NEW, minor hygiene |

## 4. Methodology questions (owner decisions, not defects)

* **M1. FantasyPros IDP freshness clock.**
  * The pipeline clock is `min(vendor expert update, last broad change)` (closeout 2026-10-18). That gives
    2026-09-04 and freshness 15.9 %.
  * The CSV's vendor `originalRank` order changed broadly on **2026-09-23** (commit `36bace419`: about 290 rows,
    e.g. Roquan Smith and Jack Campbell swap 3 ↔ 4).
  * The vendor stamp therefore predates real content by about 20 days.
  * **Decision:** keep the conservative min rule, or let a verified broad change advance the clock.
  * The same staleness plausibly explains the one extreme dissent (rookie Jacob Rodriguez: FP LB 97 vs IDPTC 5,667
    and DS 14).
* **M2. DLF IDP restoration.** P1 shows the incumbent filter would drop 31 clean votes. The hold should stay until an
  owner-approved filter passes on fresh data. This replicates V2's case and does not activate anything.
* **M3. Universe policy (G2-D1).**
  * **Decision:** should an IDP player ranked by at least N voting dynasty providers enter the board when IDPTC does
    not list him?
  * Today the universe silently follows one provider. That clashes with signal independence: the other providers'
    consensus is discarded, not merely outvoted.
* **M4. Coverage limits are structural.**
  * No served IDP row has more than 3 voting providers.
  * Deep tail (IDP rank > 216): 70 of 181 rows are single-provider. LB 217+ has a median of 1 provider.
  * The median own-level provider count is 2: FantasyPros' level is translated through the IDPTC backbone.
  * This is reported, not capped. Borrowing a scale is not data lineage.
  * Draft Sharks' coarse integer 3D Value+ makes tie plateaus of up to 20 tail rows that share one vote.

## 5. Coverage table (served held-out)

Median voting providers / median own-level providers / single-provider rows, by IDP rank band:

| family | 1–36 | 37–108 | 109–216 | 217+ |
|---|---|---|---|---|
| DL | 3 / 2 / 0 of 9 | 3 / 2 / 1 of 30 | 3 / 2 / 0 of 54 | 2 / 2 / 21 of 57 |
| LB | 3 / 2 / 0 of 22 | 3 / 2 / 0 of 25 | 3 / 2 / 0 of 17 | 1 / 1 / 25 of 46 |
| DB | 3 / 2 / 0 of 5 | 3 / 2 / 2 of 17 | 3 / 2 / 0 of 37 | 2 / 2 / 24 of 78 |

D1b exploratory (deviation D5; supersedes the D1 table, whose FantasyPros bands were sorted by a per-position rank).
Unjoined entries / absent from the board, by vendor FILE-order band:

| source | 1–50 | 51–150 | 151–300 | 301+ |
|---|---|---|---|---|
| draftSharksIdp | 0 / 0 of 50 | 3 / 3 of 100 | 24 / 24 of 150 (1 is the JT Tuimoloau alias) | 62 / 62 of 109 |
| fantasyProsIdp | 0 / 0 of 50 | 2 / 2 of 100 | 33 / 27 of 149 | n/a |
| idpTradeCalc | 1 / 1 of 50 (Bam Knight, non-IDP) | 0 / 0 of 100 | 3 / 2 of 150 | 5 / 5 of 516 (incl. offense names and JT Tuimoloau) |
| idpShowCombined | 0 / 0 of 50 | 0 / 0 of 100 | 1 / 1 of 150 (JT Tuimoloau) | 1 / 1 of 8 |

IDPTC publishes no position column, so its list includes offense players and the "absent" there is not an IDP
universe statement.

DLF IDP, DLF Rookie IDP and the IDP Show IDP-only board are not evaluable on the served build: they are held or
non-voting, so they never join.

## 6. Not done / unresolved

* Independent evidence for six of the seven IDP CSVs needs the prospective set, boards on or after 2026-12-09. The
  owner could instead authorize reading V2.1-sealed boards with a V2.1 deviation entry. That is NOT done here.
* G2-D4's cause and G2-D1's code path (where the board universe admits IDP players) are not traced in code. The
  evidence is from data.
* G2-D5's value impact is not measured.
* Windows-only: `tests/docs/test_ui_parallel_governance.py` fails locally on path separators. It is unrelated, and its
  file is untouched.
