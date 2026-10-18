# Draft Data workbook — forensic map and parity record (Batch A)

**Status:** evidence record for the draft-valuation automation workstream
(`docs/draft/DRAFT_VALUATION_WORKSTREAM.md`). It describes the owner's
spreadsheet and how the canonical module reproduces it. It authorizes nothing.

**Source.** The owner's `Draft Data` Google Sheet (ID
`17wa6qdZ1Y8ckb4TIVZ4_C71g0skvtk9UZy43zSFzRlA`), exported as xlsx. The copy
analysed here has sha256 `50d130e5a34d0bb4c2b7ae02cf8dc2bc5a03081263e17a869ba8f8c2eb1dce88`
(121,728 bytes, sheets `Draft Data` and `Inflation`). The owner's
implementation package (`chase_upside_draft_goldens_2026-10-17.json`) names
the same sha256.

**Fixtures** (all under `tests/fixtures/draft_valuation/`):

| file | what it is |
|---|---|
| `workbook_2026_10_17.json` | every non-empty cell of both sheets: formula text verbatim plus cached value, a structured view of rows 2-73, `M1` and the totals row, and the source sha256. Cut by `scripts/draft_valuation_extract_workbook.py` |
| `workbook_2026_10_17_inputs.json` | only the formula inputs: column B, the F/G/H curves, `M1`, the budget |
| `package_goldens_2026_10_17.json` | byte copy of the owner package goldens (sha256 `77d6886f…5b6`) |
| `workbook_2026_10_17_libreoffice_recalc.json` | the unmodified formulas recalculated by LibreOffice Calc 24.2.7.2 at full double precision |
| `rank_tie_cases_libreoffice.json` | constructed exact RANK ties, evaluated by LibreOffice using the workbook's own I/J/K/D formula text |

**Precision note.** A Google Sheets export caches formula results to **10
significant digits** (`<v>0.6356720614</v>` in the XML). Real-valued columns
(C, E, J) are compared at that precision against the cache, and to within
1e-11 against the LibreOffice recalculation. Integer and half-dollar columns
(D, I, K, L) are compared exactly.

## 1. Parity results

| comparison | C | D | E | I | J | K | L |
|---|---|---|---|---|---|---|---|
| canonical `curve.py` vs workbook cache | 72/72 | 72/72 | 72/72 | 72/72 | 72/72 | 72/72 | 72/72 |
| independent reference vs workbook cache | 72/72 | 72/72 | 72/72 | 72/72 | 72/72 | 72/72 | 72/72 |
| canonical vs LibreOffice full recalc | max \|Δ\| 4.8e-13 | 72/72 | max \|Δ\| 3.3e-13 | 72/72 | max \|Δ\| 2.5e-14 | 72/72 | 72/72 |
| canonical vs owner package goldens | 72/72 | 72/72 | 72/72 | 72/72 | 72/72 | 72/72 | 72/72 |
| package goldens vs workbook cache (B-L, every row) | 0 disagreements | | | | | | |

Also matched exactly: the P2:AA7 grid, AB2:AB7 round totals, P8:AA8 slot
totals, AB8 = 1200, AD1 = 1 (production and reference), and, through the
reference only: Q45:Q116, owners R45:R116, T30:T41, team totals U63:U74,
U75 = 1200, Q117 = 1200 and the orphan cell M123 = 133.

Run `python scripts/draft_valuation_parity_report.py` to reproduce the
numbers in sections 1 and 6. The tests are in `tests/draft_valuation/`.

## 2. Column-by-column map — `Draft Data` rows 2-73

`i` = 0-based pick index (row `i + 2`); `r = INT(i/12)` = 0-based round.
Formulas are quoted from row 3 (whitespace removed). Row 2 is the same
formula except where noted.

| col | header | formula (verbatim) | meaning | outputs / used by | repo equivalent | discrepancies |
|---|---|---|---|---|---|---|
| A | PICK | constants 1.01 … 6.12 | slot label, stored as a NUMBER (1.1 shows as "1.10") | row identity | `curve.iter_labels` formats `R.SS` explicitly | numeric label, so 1.10 and 1.1 are the same number |
| B | VALUE | constants | rookie-value input per pick. Σ = **180,036.5**. **Not** descending: 16 places where the next row is higher (1.03 > 1.02, 1.05 > 1.04, 1.08 > 1.07, 1.10 > 1.09, 2.02 > 2.01, 2.10 > 2.09, 3.01 > 2.12, 3.04 > 3.03, 3.05 > 3.04, 3.06 > 3.05, 3.10 > 3.09, 3.11 > 3.10, 4.02 > 4.01, 4.07 > 4.06, 5.05 > 5.04, 5.07 > 5.06) | C (decay share and decay rate) | `CurveResult.rows[i].rookie_value`; frozen as `config/draft_valuation/frozen_inputs/2026_spreadsheet_baseline.json` | a source-order anomaly, not a rounding defect. A new class's values must be sorted on purpose (Batch B) |
| F | 2025 | constants | 2025 rookie-draft dollar curve, Σ = 1200, half-dollar, non-increasing | E | `config/draft_valuation/historical_curves/dynasty_main/2025.json` | header is a year, so position is not identity — snapshots key by year |
| G | 2024 | constants | 2024 curve, Σ = 1200 | E | `historical_curves/dynasty_main/2024.json` | — |
| H | 2026 | constants | 2026 curve, Σ = 1200 | E | `historical_curves/dynasty_main/2026.json` | not the same quantity as column B (owner decision 2026-10-18) |
| E | Spine | `=(MEDIAN(F3:H3)+AVERAGE(F3:H3))/2` | per-slot historical anchor. Σ = **1196.75** (not normalised, by design) | C (spine share) | `curve.spine_from_curves`, exact `Fraction` | `server._read_sheet_spine_and_floor` reads the CACHED E (10 digits) and its docstring says "2023–2025"; the spine years are 2024/2025/2026 |
| C | Decay | `=1+--(INT((ROW()-ROW($B$2))/12)=4)+(1200-84)*(0.6*((B3+0)*EXP(-(MAX(0.03,MIN(0.08,0.6*_xlfn.STDEV.S($B$2:$B$7)/AVERAGE($B$2:$B$7))))*(ROW()-ROW($B$2)))*(1-0.2*EXP(-0.12*(ROW()-ROW($B$2)))))/SUMPRODUCT(($B$2:$B$73+0)*EXP(-(MAX(0.03,MIN(0.08,0.6*_xlfn.STDEV.S($B$2:$B$7)/AVERAGE($B$2:$B$7))))*(ROW($B$2:$B$73)-ROW($B$2)))*(1-0.2*EXP(-0.12*(ROW($B$2:$B$73)-ROW($B$2)))))+0.4*(((E3-1)*(E3>1))/SUMPRODUCT(($E$2:$E$73-1)*($E$2:$E$73>1))))` | real-valued dollars: floor $1 (+$1 in round 5) plus $1,116 split 60% by decayed rookie value, 40% by spine excess over $1. Decay rate `k = clamp(0.6·STDEV.S(B2:B7)/AVERAGE(B2:B7), 0.03, 0.08)`; weight `B_i·e^(−k·i)·(1−0.2·e^(−0.12·i))`. Σ C = 1200 (to 60 digits) | I, J | `curve.compute_curve` (Decimal, 60 digits) | the decay head is the FIRST six rows, which here are also the six largest values; `1200-84` is a literal (84 = 72 + 12 floor dollars), derived from params in code |
| I | Floors | `=ROUNDDOWN(C3*2,0)` | floored half-dollar units | J, K, K's residual | `allocate_units` | — |
| J | Fractions | `=C3*2-I3` | fractional half-unit remainder | K (RANK) | `allocate_units` | — |
| K | Monotone Rounded | row 3+: `=MIN(I3+--(RANK(J3,$J$2:$J$73,0)<=1200*2-SUM($I$2:$I$73)),IF(INT((ROW()-ROW($C$2))/12)=4,4,IF(INT((ROW()-ROW($C$2))/12)=5,2,10^9)),K2)`; row 2: `=I2+--(RANK(J2,$J$2:$J$73,0)<=1200*2-SUM($I$2:$I$73))` | award one unit to every pick whose remainder RANK is within the residual (RANK ties share a rank), then cap round 5 at 4 units ($2) and round 6 at 2 ($1), and never exceed the previous pick | D, D's residual | `allocate_units` | `_rookie_dollars_from_values` breaks RANK ties by row order, so it awards exactly the residual where the sheet over-awards (section 5) |
| M1 | (12) | constant | **protected rounding parameter**: how many top picks share the post-cap residual | D | `CurveParams.carry_picks` | — |
| D | New Values | `=(K3+IF(ROW()-ROW($K$2)<$M$1,QUOTIENT(1200*2-SUM($K$2:$K$73),$M$1)+--(ROW()-ROW($K$2)<MOD(1200*2-SUM($K$2:$K$73),$M$1)),0))/2` | final dollars: the residual `S = 2400 − ΣK` goes to the first M1 picks, `QUOTIENT(S,M1)` each plus one more for the first `MOD(S,M1)` | L | `allocate_units` → `final_units / 2` | `QUOTIENT` truncates toward zero; Python `//` floors. Equal for S ≥ 0; `_rookie_dollars_from_values` uses `//` |
| L | Final Dollar Per Pick | `=D3` | the published per-pick dollars, Σ = 1200 | grid P2:AA7; `server._parse_draft_xlsx` reads L2:L73 as `pick_values_l` | `CurveResult.dollars` | — |
| D74 / L74 | | `=Sum(D2:D73)` / `=D74` | 1200 | — | `CurveResult.total_dollars` | — |
| F74:H74 | | constants 1200 | typed totals, not formulas | — | snapshot loader recomputes the sum | typed, so they would not catch an edited curve |

## 3. Everything else on the sheet

| range | formula (verbatim, row-relative) | meaning | read by the app? | notes |
|---|---|---|---|---|
| O1:AA1, O2:O7 | labels | grid headings | no | — |
| P2:AA7 | `=INDEX($L$1:$L$73,2+(ROW()-ROW($P$2))*12+(COLUMN()-COLUMN($P$2)))` | L reshaped round × slot | `_parse_draft_xlsx` reads it as `pick_dollars` | the `12` is a literal |
| AB2:AB7 | `=SUM(P2:AA2)` | round totals 827.5 / 231 / 74 / 31.5 / 24 / 12 | no | — |
| P8:AA8, AB8 | `=SUM(P2:P7)`, `=SUM(AB2:AB7)` | per-slot totals (180, 144.5, …, 54.5); 1200 | no | a slot's total is a team's capital when it owns every round of that slot |
| AD1 | `=1200/SUM($P$2:$AA$7)` | rescale guard; exactly 1 | via Q | a guard, not a second model |
| M123 | `=ROUNDDOWN(C2,0)+--((1+SUMPRODUCT(--(($C$2:$C$73-ROUNDDOWN($C$2:$C$73,0))>(C2-ROUNDDOWN(C2,0))))+SUMPRODUCT(--(($C$2:$C$73-ROUNDDOWN($C$2:$C$73,0))=(C2-ROUNDDOWN(C2,0))),--(ROW($C$2:$C$73)<ROW())))<=1200-SUMPRODUCT(ROUNDDOWN($C$2:$C$73,0)))` | **orphan**: a whole-dollar largest-remainder rounding of C2 (value 133) | **no** — nothing references it | it was moved from row 2 (its references still point at C2), so `ROW()<123` is always true and its tie-break counts the cell itself — a latent off-by-one. Inventory only |
| O29:Y29 | headers | Standings / Owner / Pick # / Override Owner / Owner (Final) / Round / Original Owner / New Owner / Key | — | — |
| O30:P41 | constants | standings rank 1-12 → owner first name (Ed, Brent, Joey, MaKayla, Ty, Kich, Eric, Collin, Roy, Jason, Blaine, Joel) | `_parse_draft_xlsx` reads P/R (`slot_to_original`) | hand-entered; rank 1 picks last |
| R30:R41 | constants 12 … 1 | pick slot = 13 − rank | yes | the `13` is a literal |
| S30:S41 | empty | per-SLOT owner override | via R45 | an override applies to every round of that slot AND beats the trade table |
| T30:T41 | `=IF(S30<>"",S30,INDEX($P$30:$P$41,MATCH(13-R30,$O$30:$O$41,0)))` | final owner per slot | via R45 | — |
| V30:X… | empty | traded picks: Round / Original Owner / New Owner | via R45 | no trades recorded on the sheet |
| Y30:Y81 | `=TEXT(V30,"0")&"|"&TRIM(W30)` | trade key; blank rows give `"0|"` | via R45 | R45 looks keys up in **Y30:Y202 / X30:X202, which overlap the player list at rows 137-217** (positions in Y, names in X). A position string can never match an `N|Owner` key, so it is harmless today — but the ranges collide |
| O45:O116 | `=INT((ROW()-ROW($O$45))/12)+1` | round | `_parse_draft_xlsx` | — |
| P45:P116 | `=MOD(ROW()-ROW($P$45),12)+1` | slot | yes | — |
| Q45:Q116 | `=INDEX($P$2:$AA$7,O45,P45)*$AD$1` | pick dollars | yes | identical to L with AD1 = 1 |
| R45:R116 | `=IF(INDEX($S$30:$S$41,MATCH(P45,$R$30:$R$41,0))<>"",INDEX($T$30:$T$41,MATCH(P45,$R$30:$R$41,0)),IFERROR(INDEX($X$30:$X$202,MATCH(TEXT(O45,"0")&"|"&TRIM(INDEX($P$30:$P$41,MATCH(13-P45,$O$30:$O$41,0))),$Y$30:$Y$202,0)),INDEX($P$30:$P$41,MATCH(13-P45,$O$30:$O$41,0))))` | current owner: slot override, else traded-pick lookup by `round|original owner`, else the original owner | yes (overlaid by Sleeper `/traded_picks`) | first-name keys; an override silences a recorded trade |
| Q117 | `=SUM(Q30:Q116)` | 1200 | no | — |
| T62:U74 | `=SUMIF($R$45:$R$116,T63,$Q$45:$Q$116)` | team capital by first name | `_parse_draft_xlsx` reads T/U as `wb_team_totals` | joins by display name |
| U75 | `=SUM(U30:U74)` | 1200 | no | — |
| W137:Z217 | constants | a 2026 rookie list: Rank / Player / Pos and a `Composite` column | `server._parse_csv_rookies` reads columns 22-25 of the CSV export | **misaligned**: `Composite` starts two rows above the names (Z138 = 6817 sits on no player; rank 1 Jeremiyah Love reads 5103); ranks 2 and 77 are missing. **And the parser returns 0 rookies on the current CSV**, because the export writes `1.0` / `5103.0` and the parser calls `int()` on them — so the KTC-rookie CSV fallback in `_get_ktc_rookies` is dead |
| `Inflation` A1:I73 | `F=IF($D2>0,"",$C2*$L$14)`, `G=IF($D2>0,"",MIN($L$8,$C2*$L$14*(1+($L$11-1)*$L$16)))`, `H=IF($D2<>"","",IFERROR(MIN($L$8,$C2*$L$14*$L$27),""))`, I = value-vs-fair label | live-auction bidding tool over 72 named players: PreDraft$ (C, Σ 1200, per-player, **not** the pick curve: Love 139 vs pick 1.01 134.5), Final Price (D), Mine? (E), inflated fair price, my max bid, enforce-up-to | no | inventory only — never substitute it for pick valuation. I2 uses a ±10/30% band while I3:I73 use ±$2 — two different rules in one column |
| `Inflation` K1:L27 | e.g. `L4='Draft Data'!U63`, `L14=IF(L13>0,L6/L13,1)`, `L16` aggression ladder, `L27` 0.8 | settings: total $1200, 12 teams, my starting $ (Joel's U63), spent, remaining, budget advantage, inflation factor, aggression, enforce % | no | the only cross-sheet reference in the workbook |

## 4. Worked example — pick 1.01 through every column

Inputs: B2 = 7,580; F2/G2/H2 = 125.5 / 122.5 / 134.0.

1. **E2** = (MEDIAN 125.5 + AVERAGE 127.3333…)/2 = **126.41666…** (exact
   `(251/2 + 382/3)/2`).
2. **Decay rate.** B2:B7 = 7580, 5598.5, 5649, 5074.5, 5076, 4965; mean
   5,657.1667, sample sd 985.6111; 0.6 × 985.6111 / 5,657.1667 = 0.10453 →
   clamped to **k = 0.08**.
3. **Decay share.** w₀ = 7580 × e⁰ × (1 − 0.2) = 6,064; Σw over 72 picks =
   49,192.9186; share = **0.1232697749**.
4. **Spine share.** E2 − 1 = 125.41667; Σ max(E − 1, 0) = 1,124.75 (60 picks
   have E > 1); share = **0.1115062607**.
5. **C2** = 1 + 1116 × (0.6 × 0.1232697749 + 0.4 × 0.1115062607) =
   **133.3178360307** (cache 133.317836, LibreOffice 133.317836030722).
6. **I2** = ROUNDDOWN(266.6357, 0) = **266**; **J2** = **0.6356720614**.
7. **Residual after floors** = 2400 − ΣI = 2400 − 2369 = **31**. J2 ranks 23rd
   of 72, within 31, so it earns one unit: **K2** = 267 (no cap, no predecessor
   on row 2).
8. **Residual after caps** = 2400 − ΣK = 2400 − 2383 = **17**: the 31 awards
   less 17 units the round-5 picks cannot keep (their $2 floor puts I at 5,
   but round 4 ends at 4 units and K may not rise, so twelve picks drop from
   5 to 4 and five lose their award). QUOTIENT(17, 12) = 1, MOD(17, 12) = 5:
   picks 1.01-1.05 get 2 carry units, 1.06-1.12 get 1.
9. **D2** = (267 + 2)/2 = **$134.50**; **L2** = $134.50.

A round-5 pick for contrast: 5.01 has B = 1,917, C = 2.9573814249, I = 5,
J = 0.9148 (rank 5, awarded), cap 4, previous K = 4 → K = 4 → **$2.00**.
Round 6: 6.01 C = 1.1401, I = 2, rank 41 (not awarded), cap 2 → **$1.00**.

Two parts of the formula never bind on these inputs: the decay clamp hides the
head size and coefficient, and monotonicity hides the round-5/6 caps (round 4
already ends at $2). Their parity is therefore proved on seeded random inputs
where they do bind (`test_caps_and_decay_head_are_exercised_somewhere`), and
every one of ten formula mutations is detected
(`test_a_mutated_formula_is_detected`).

## 5. RANK ties — what the spreadsheet actually does (audit D8)

`RANK(J, J-range, 0)` gives equal values the same rank. Measured with
LibreOffice on constructed C vectors (exactly representable multiples of
1/8, so every engine sees identical ties), using the workbook's own I/J/K/D
formula text:

* **tie inside the award set** (two J = 0.75, residual 2): harmless, total
  exactly $1,200. Production matches LibreOffice on all 72 picks.
* **tie at the cutoff** (three J = 0.5 at rank 1, residual 2): the sheet
  awards 3 units, ΣK = 2401, the post-cap residual is −1, `QUOTIENT(-1,12)` =
  0 and `MOD(-1,12)` = 11, so the first 11 picks gain a half-dollar and the
  sheet publishes **D74 = $1,206**. Production reproduces those exact numbers
  (`allocate_units(check=False)`) and **refuses** the result
  (`CurveInvariantError`) instead of publishing it.

`_rookie_dollars_from_values` breaks the same tie by row order and awards only
2 units, so it would publish $1,200 with a different distribution from the
sheet. On real inputs an exact tie is a measure-zero event (the real-valued C
involves `exp`; the workbook's smallest decision margin is 0.0019 half-units,
and 0 of 250 random cases came within 1e-9), but a tie-break that both totals
$1,200 and deviates from the sheet is a methodology choice — see UNRESOLVED in
the workstream record. Google Sheets itself was not available to this session;
LibreOffice follows the same documented RANK semantics.

## 6. The legacy `server.py::_rookie_dollars_from_values`

Measured by executing the function's own source (lifted with `ast`, nothing
imported from `server`) against the spine it would read:

| scenario | result |
|---|---|
| A. workbook column B in sheet order | **72/72** match the workbook's L; total $1,200 |
| B. column B sorted descending (how the server feeds board values) vs the canonical module on the same input | 72/72 |
| C. sorted B vs the workbook's published L | 53/72; 19 differ, max \|Δ\| $2.50 (1.07: 57.0 vs 54.5; 1.09: 48.0 vs 46.0; 1.08: 52.0 vs 53.5; …). Not a formula difference — the sheet's B is unsorted |
| D. workbook unreadable (its flat `[1.0]*n` spine fallback) | 28/72; 44 differ, max \|Δ\| $22.50 (1.12: 58.0 vs 35.5; 1.01: 121.0 vs 134.5; 2.01: 18.0 vs 29.5). The 40% spine term vanishes and the carry dumps the residual on the first 12 picks — a plausible-looking wrong curve |
| E. 60 values (vendor lists shorter than 72) | returns 60 dollars totalling $1,200, the last twelve all $2 (no round 6 at all); the canonical module refuses fewer than 72 |

Other differences, by reading: it reads the 10-digit cached E rather than
computing it (no decision changes on this fixture); a non-positive head mean
silently becomes `decay_rate = 0.05` where the sheet errors; `r5_bonus_count`
is returned and never used; RANK ties and negative residuals as in section 5;
its docstring names the spine years 2023-2025. Not changed in this batch — a
later batch swaps it onto the canonical module.

## 7. Repo copies of the workbook

| artifact | relationship to the owner's copy |
|---|---|
| `CSVs/Draft Data.xlsx` (sha256 `12eb183d…a7c4`) | **0 cell differences** across 2,356 cells (formulas and cached values) on 2026-10-18; different bytes only (export container metadata). It is re-downloaded from the Google Sheet every two hours by `.github/workflows/scheduled-refresh.yml` |
| `CSVs/draft_data.csv` | the same workflow's `data_only` export of the `Draft Data` tab: **0 differences** over 1,002 rows / 1,739 non-empty cells. Values only — no formulas |

## 8. The owner package audit — verified claims

Checked against the workbook and `main` at `123a0be024`:

| audit claim | verdict |
|---|---|
| 72 rows; Σ B = 180,036.5; 16 adjacent increases | agree |
| F/G/H = 2025/2024/2026, each Σ $1,200 | agree |
| E Σ = $1,196.75 | agree |
| decay clips to 0.08; sd(B2:B7) ≈ 985.6111, mean ≈ 5,657.1667 | agree (ratio 0.10453) |
| C2 = 133.31783603; I2 = 266; J2 = 0.63567206; K2 = 267; D2 = L2 = 134.50 | agree |
| ΣK = 2,383; 17 half-units redistributed; one each to 12 picks plus one more to the first five | agree |
| 72/72 final dollars match; ΣD = ΣL = 1200 | agree |
| "maximum independent C-vs-export difference ~4.34e-8" | the package's own independent C carries the 10-digit cached spine (≤ 3.3e-8 error); exact C differs from the cache by at most **3.07e-8** and from LibreOffice by 4.8e-13. Not a defect, a precision note |
| 5.01 L = $2, 6.01 L = $1 | agree |
| `CSVs/Draft Data.xlsx` is a "local cached copy, no live Google sync" | **disagree** — `scheduled-refresh.yml` downloads the sheet every 2 hours and re-exports the CSV |
| the fallback renormalises picks of two seasons into one $1,200 pool | agree for `main` (`draft_capital_fallback.py` loops `(current_season, current_season + 1)`, one pool); open PR #1785 changes this |
| the workbook path keeps worksheet owners when `/traded_picks` fails | agree for `main` (`server.py` sets `traded = []`); open PR #1785 refuses the board instead |
| `_read_sheet_spine_and_floor` falls back to a flat spine | agree; measured in section 6 (D) |
| `_rookie_dollars_from_values` accepts fewer than 72 values | agree; measured in section 6 (E) |
| RANK ties may diverge from a stable-sort Python port | agree, and measured (section 5): the sheet itself publishes $1,206 |
| the decay uses the "top six" B values | the formula uses the FIRST six rows; on this fixture they are also the six largest |
| not mentioned by the audit | the orphan M123 cell, the X/Y lookup range overlapping the player list, the misaligned W137:Z217 list, and `_parse_csv_rookies` returning 0 rookies |

The 72-slot fixture is evidence for `dynasty_main` only. Owner scope
correction 2026-10-18: `dynasty_main` is the only league in scope; any other
league is "not configured" and the engine refuses it rather than adapting the
formula.
