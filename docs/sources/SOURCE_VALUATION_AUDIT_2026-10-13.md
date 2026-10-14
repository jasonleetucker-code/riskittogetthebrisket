# Source & valuation audit — 2026-10-13

**Status:** evidence record. **Product authority: none** — it changes no value, weight, flag or
methodology. Implementation authority stays with `docs/EXECUTION_PLAN.md` §0.
Agent-OS-Receipt: `cdca1dca8385f70c0989302dece8d1bd4ce4843c`

Prompted by an owner request to fix the KTC trade import, audit every data source end to end,
and prove that current source information actually reaches the values users see. Everything
below was measured on 2026-10-13 against `main` @ `38850a7c`, a contract built from
`exports/latest/dynasty_data_2026-10-13.json` (board as of 2026-10-13T16:30Z), and the existing
tools named in each section. Nothing was reconstructed from prose.

**Environment limit, stated once:** this was a cloud checkout, not the production box. The
private Signals store (`data/sources/signals/`) is box-local and absent here, so the four Signals
keys read `not_provisioned` in every local measurement; production carries `signalsSf` as an
active voter. The temporal ledger and box receipts were likewise unavailable. Production
re-verification items are listed at the end.

## 1. Repairs shipped from this audit

| PR | defect | root cause (evidence) | status |
|---|---|---|---|
| #1731 | KTC trade-URL import failed for every URL ("Failed to fetch KTC player map.") | KTC moved the calculator's player map into `<script type="application/json" id="ktc-players">`; `ktc_import`'s private `var playersArray = [` regex stopped matching → `RuntimeError` → generic 502. The live test skipped on *any* exception, so CI stayed green. Also: the import used the 500-row value board, not KTC's 2,011-row id index; the Next bridge dropped the session cookie (401 in dev/E2E). | open — fixed, verified in a live browser (5/5 assets) |
| #1732 | Yahoo Boone stale since 2026-10-09 | Boone's 2026-10-09 charts shrank (366 rows, was 410); the 400-row scraper floor rejected every run, so the board kept voting September content | open — floors re-pinned from measured counts |
| #1733 | Source Health page showed only fetch recency (4h/12h bands); quarantined sources invisible | `/api/sources/weighting` (the pipeline's freshness verdict) had no UI consumer | open — table added, PSI scope, a11y clean |

Same-class defects closed inside #1731 because they shared the root cause:
`scripts/check_ktc_health.py` and the `Dynasty Scraper.py` page-content fallback used the same
inline-only regex (the health probe would have reported a healthy KTC page as broken).

## 2. Source registry (every source, explicit role)

Population: the union of `_RANKING_SOURCES`, `_SOURCE_CSV_PATHS`, the non-voting list and every
`CSVs/site_raw/*.csv` (`scripts/source_inventory.py`). Freshness columns are the pipeline's own
verdict (`GET /api/sources/weighting` → `src/sources/freshness.py`): content age against the
source's expected cadence — **not** fetch age, which is reported separately in §3.

### 2a. Voting sources (model inputs)

| source | family | content age / expected (h) | state | freshness | effective weight | rows voting |
|---|---|---|---|---|---|---|
| `ktcCrowdSfTep` | ktcCrowd | 9.3 / 12 | ON_SCHEDULE | 1.00 | 1.00 | 501 |
| `ktcTradesSfTep` | ktcTrades | 9.3 / 12 | ON_SCHEDULE | 1.00 | 1.00 | 504 |
| `idpTradeCalc` | idpTradeCalc | 68.1 / 127.9 | ON_SCHEDULE | 1.00 | 1.00 | 898 |
| `dlfSf` | dlf | 0.0 / 84 | ON_SCHEDULE | 1.00 | 1.00 | 281 |
| `dlfRookieSf` | dlf | 94 / 68 | OVERDUE | 0.93 | 0.93 | 57 |
| `dlfIdp` | dlf | 110 / 168 | ON_SCHEDULE | 1.00 | 1.00 | 167 |
| `dlfRookieIdp` | dlf | 164 / 178 | ON_SCHEDULE | 1.00 | 1.00 | 29 |
| `idpShowCombined` | idpShow | **1,318.7 / 168** | **QUARANTINED** | **0.00** | **0.00** | **0** |
| `dynastyNerdsSfTep` | own | 45.2 / 722.6 | ON_SCHEDULE | 1.00 | 1.00 | 280 |
| `fantasyCalc` | fantasyCalc | 9.3 / 12 | ON_SCHEDULE | 1.00 | 1.00 | 387 |
| `otcffbSf` | own | 17.2 / 26.6 | ON_SCHEDULE | 1.00 | 1.00 | 375 |
| `fantasyNavigatorSf` | ktcCrowd | 72.4 / 25.9 | STALE | 0.45 | 0.45 | 447 |
| `pfkDynasty` | own | 9.3 / 75.4 | ON_SCHEDULE | 1.00 | 1.00 | 442 |
| `dynastyDaddySf` | own | 9.3 / 12 | ON_SCHEDULE | 1.00 | 1.00 | 389 |
| `fantasyProsSf` | fantasyPros | 68.1 / 48 | OVERDUE | 0.92 | 0.92 | 348 |
| `fantasyProsIdp` | fantasyPros | 474.6 / 253 | OVERDUE | 0.75 | 0.75 | 237 |
| `fantasyProsFitzmaurice` | fantasyPros | 267.2 / 737 | ON_SCHEDULE | 1.00 | 1.00 | 290 |
| `flockFantasySf` | flockFantasy | 68.1 / 40.2 | OVERDUE | 0.82 | 0.82 | 399 |
| `yahooBoone` | own | 956.9 / 840 | ON_SCHEDULE | 0.99 | 0.99 | 374 |
| `draftSharks` | draftSharks | 9.3 / 16 | ON_SCHEDULE | 1.00 | 1.00 | 321 |
| `draftSharksIdp` | draftSharks | 9.3 / 13.9 | ON_SCHEDULE | 1.00 | 1.00 | 300 |
| `flockFantasySfRookies` | flockFantasy | — | seasonally inactive (class 2026, since 10-01) | — | no vote | 0 |
| `signalsSf` | fantasyCalc | box-local | active on production; `not_provisioned` here | — | — | — |
| `signalsIdpDl/Lb/Db` | fantasyCalc | box-local | **held** (`PRIVATE_SOURCE_VOTE_HOLDS`, shadow) | — | no vote | 0 |

Base weight is 1.0 for every voter (`_RANKING_SOURCES`, policy). "Effective" is base × freshness
× health × coverage; B10 family caps then limit each correlation family to one provider's
authority (`cap_family_weights`).

### 2b. Ingested, deliberately non-voting

| source | role | why |
|---|---|---|
| `ktcCrowdTradesSfTep` (KTC Market) | benchmark | KTC's own Crowd+Trades composite — counting it would vote KTC twice (`src/sources/ktc_market.py`) |
| `ktc`, `ktcSfTep` | non-voting | calibration state / mirror of KTC Crowd — same opinion, not a vote |
| `idpShow` | non-voting | IDP-only cut of `idpShowCombined` |
| `dlfValuesSfTep` | non-voting | DLF Trade Analyzer values; measurement gate pending (owner directive 2026-09-24) |
| `dlfValuesSfTepPicks` | non-voting | pick-audit only (header-only CSV today) |
| `draftSharksRosSf/RosIdp` | barred | redraft / rest-of-season — seasonal lane only (source-domain boundary) |
| `signalsDynasty`, `signalsIdpDynasty` | second opinion | `/api/second-opinion/signals`, never a vote |

**DynastyProcess:** no registry key, fetcher, CSV or stamp exists — not integrated.

**DLF naming note.** The owner prompt describes "DLF Value removed; DLF Vote offense-only". In
this repository DLF contributes four *ranking* boards — `dlfSf`, `dlfRookieSf` (offense) and
`dlfIdp`, `dlfRookieIdp` (IDP) — sharing one family-capped vote; DLF *Values* is ingested and
held from voting. Nothing was changed here; if the owner's policy means DLF IDP boards should
stop voting, that is an explicit decision to record (OWNER_DECISION).

### 2c. Observed trades

`src/trade/market_trade_*`, `src/sources/ktc_trades.py`, the own-league and Sharp ledgers capture
dated trade evidence with format provenance. `src/api/data_contract.py` imports none of them:
**real trades do not move canonical values today.** That is by design (AL-P1's acceptance pins
"board hash unchanged"), and `src/model_registry/independent_validation.py` is where they are
meant to enter — as a preregistered *validation target*, not a vote. Package-trade value
extraction is not implemented.

## 3. Freshness, three clocks

Last successful **fetch** (`data/scrape_state/<key>_last_success`, UTC): every scheduled source
2026-10-13 16:27–16:33, except `yahooBoone` 10-09 15:40 (§1, #1732), `idpShowCombined`/`idpShow`
10-07 20:32 (production timer + captcha-minted Substack cookie), `flockFantasySfRookies` 09-30
(seasonally inactive by design). A dry-run sweep of every credential-free scheduled fetcher
(FantasyCalc 396, Dynasty Daddy 394, OTCFFB 379, Fantasy Navigator 770, PFK 496, Flock 436,
FantasyPros SF 358 / IDP / Fitzmaurice 299) succeeded against live vendors.

**Fetch is not content.** The pipeline judges each source on content age (§2a), so a source we
fetch every two hours can still be stale — and is penalised automatically:

- **IDP Show** — vendor chart `lastModifiedAt 2026-08-19`; freshness 0.016 → below
  `quarantineBelow 0.02` → zero weight on every row. Correct per the owner decision "the freshness
  system itself must make a stale source lose authority". Even a repaired cookie would not make
  the content fresh; the vendor has not published since August.
- **Fantasy Navigator** — fetched 3h ago, content unchanged 72h against a 26h cadence → 0.45.
- **FantasyPros IDP** — content 20 days against an 11-day cadence → 0.75.

Before #1733 none of this was visible on the Source Health page.

## 4. Does source information reach the published value?

Traced per row through `sourceRankMeta` (applied weight, vote, Hampel drop, freshness exclusion)
on the built contract. Mean share of the applied vote, ranked rows:

| group | rows | mean voters | largest shares |
|---|---|---|---|
| QB | 54 | 12.7 | OTCFFB 9.3%, KTC Trades 9.1%, Dynasty Daddy 9.0%, PFK 8.9%, FantasyCalc 8.6%, IDPTC 8.3% |
| RB | 90 | 13.7 | IDPTC 8.5%, KTC Trades 8.4%, OTCFFB 8.4%, FantasyCalc 8.2%, Dynasty Daddy 8.2% |
| WR | 129 | 12.9 | KTC Trades 8.8%, PFK 8.8%, IDPTC 8.7%, OTCFFB 8.1%, FantasyCalc 8.1% |
| TE | 65 | 12.2 | KTC Trades 10.7%, PFK 10.6%, IDPTC 9.8%, Yahoo 8.2%, KTC Crowd 7.5% |
| **DL** | 102 | **3.4** | **IDPTC 31.7%**, Draft Sharks IDP 29.0%, FantasyPros IDP 19.7%, DLF IDP 19.6% |
| **LB** | 68 | **3.2** | **IDPTC 37.6%**, Draft Sharks IDP 21.4%, DLF IDP 20.6%, FantasyPros IDP 20.4% |
| **DB** | 84 | **3.1** | **IDPTC 34.4%**, Draft Sharks IDP 32.7%, FantasyPros IDP 23.0%, DLF IDP 9.9% |
| rookie | 113 | 9.3 | IDPTC 19.5%, Draft Sharks IDP 10.6%, Draft Sharks 7.2% |
| pick | 35 | 3.0 | KTC Crowd 33.3%, KTC Trades 33.3%, IDPTC 33.3% (two providers) |

Every functioning registered voter reaches values in its scope; no source is collected and
silently ignored. The two that cast no vote do so for stated reasons (IDP Show quarantined by
freshness; Signals IDP held in shadow).

### Example players (value-explain/v2, `src/api/source_weighting_explain.player_explain`)

Contributions are vote share × normalised value; the explainer states `attribution.exact: false`
because the trimmed/untrimmed mean-median rungs are not weighted means, and supplies a
non-additive leave-one-out instead — that is the honest representation, so this table reports
voters and leave-one-out rather than a sum that would not reconcile.

| group | asset | value (rank) | estimator rung | voters | confidence | largest leave-one-out |
|---|---|---|---|---|---|---|
| QB | Lamar Jackson | 8,486 (11) | trimmed mean-median | 15 | high | −Dynasty Nerds → 8,621 (+135) |
| RB | Ashton Jeanty | 7,952 (15) | trimmed mean-median | 15 | high | −Draft Sharks → 8,080 (+128) |
| WR | Puka Nacua | 9,323 (8) | trimmed mean-median | **9 of 15** | medium | 6 sources Hampel-dropped (see §5) |
| TE | Trey McBride | 9,511 (6) | trimmed mean-median | 13 | medium | −Fitzmaurice → 9,575 (+64) |
| DL | Will Anderson | 5,962 (41) | untrimmed mean-median | 3 | medium | Draft Sharks IDP Hampel-dropped (2,722); IDP Show quarantined |
| LB | Jack Campbell | 5,377 (56) | untrimmed mean-median | 4 | medium | IDP Show quarantined |
| DB | Kevin Winston | 3,180 (166) | untrimmed mean-median | 4 | low | sources span 1,510–3,796 |
| rookie | Fernando Mendoza | 5,448 (52) | trimmed mean-median | 15 | high | −FantasyCalc → 5,406 (−42) |
| pick | 2028 Early 1st | 5,416 (54) | untrimmed mean-median | 3 | high | KTC Crowd 5,488 / KTC Trades 5,068 / IDPTC 5,485 |

Any player can be inspected the same way on the Player File's value explanation or
`GET /api/players/{id}/value-explain`.

## 5. Valuation-quality findings (measured, not changed)

**F1 — Top-of-board outlier filter rejects the market sources.** On Puka Nacua the Hampel filter
dropped KTC Crowd, KTC Trades, IDPTC, Fitzmaurice, Yahoo and Draft Sharks: the rank-signal sources
convert to Hill-curve values compressed against the 9,999 ceiling (9,210–9,345), so their MAD is
tiny and the value-direct markets (7,873–8,184) read as outliers. Across the board:

| consensus rank | rows | rows with ≥1 market source dropped | median model vs KTC Market (normalised) |
|---|---|---|---|
| 1–24 | 24 | **7** | **+7.7%** |
| 25–50 | 26 | 0 | +2.9% |
| 51–100 | 46 | 0 | −4.6% |
| 101–200 | 91 | 0 | −6.1% |
| 201–400 | 187 | 3 | −12.8% |
| 401–800 | 331 | 3 | −11.7% |

This is a methodology question (outlier detection in a compressed value space), not a bug to
patch, and the owner directive is explicit that values are **not** tuned toward KTC Market. The
candidate challenger — Hampel computed in percentile/rank space, or value-direct market sources
judged against their own scale — belongs in the IC learning loop with a preregistered gate.
**OWNER_DECISION** to open it.

**F2 — IDP rests on ~3 voters, one carrying a third.** IDP rows average 3.1–3.4 voters and IDPTC
holds 32–38% of every IDP value, which is why IDP confidence sits at medium/low. Two IDP evidence
streams are currently out: IDP Show (quarantined — vendor stale since August) and the Signals IDP
boards (held, `signals_idp_shared_market` OFF pending promotion). Promoting Signals IDP through its
existing gate is the largest available IDP-evidence gain.

**F3 — Picks rest on two providers.** KTC Crowd + Trades are one provider; IDPTC is the other.
Already classified correctly by `assess_pick_confidence` (provider-level independence).

**F4 — Learned source weights do not beat equal weights.** The preregistered, leakage-safe
evaluation (`docs/valuation/evidence/source-quality-2026-10-01/REPORT_2026-09-30.md`, 21-day
horizon, 522,206 cells) found all three challengers — conservative reliability, asset-class
reliability, lead/lag authority — **below the materiality gate** (ΔMALE 0.0004–0.0013 vs 0.0022),
with pick markets not evaluable. Equal base weights stay; changing them would claim an accuracy
gain the evidence does not show. The asset-class challenger's IDP stratum (ΔMALE 0.0059) is the
one signal worth re-testing as data accumulates.

**F5 — Correlated signals are handled.** B10 families + `cap_family_weights` already cap
correlated members (e.g. Fantasy Navigator sits in the `ktcCrowd` family; KTC Market is a
benchmark; `ktc`/`ktcSfTep` are suppressed mirrors). No double counting found.

## 6. Ranked remaining opportunities

| # | item | expected accuracy gain | operational importance | complexity | cost | authority |
|---|---|---|---|---|---|---|
| 1 | Promote Signals IDP through its shadow gate (F2) | high for IDP | medium | low (gate exists) | none | evidence-gated, owner |
| 2 | Preregister an outlier-space challenger for the top of the board (F1) | medium, top-24 | medium | medium | none | OWNER_DECISION |
| 3 | Replace or retire IDP Show (vendor stale since 2026-08-19) | medium for IDP | low | low | none / new source needs approval | owner |
| 4 | Use observed trades as the independent validation target (Hill autopilot gate 7) | enables measured promotion | high | high | none | in plan (AL-P1 → validation) |
| 5 | Export URL `tep=0` (W08-F008) from the league's factual TEP | n/a (export fidelity) | low | low | none | authorized trade lane |
| 6 | `/trade` reads `team.picks || []` without the pick-ownership state | correctness of unknown | low | low | none | named follow-up in CLAUDE.md |

## 7. Not done, and why

- No production weight, Hill constant, flag or estimator change — not authorized
  ("activating a methodology/model/source before its preregistered evidence gate passes" is
  owner-gated) and not supported by evidence (F4).
- No new paid source; no access-restriction bypass. KTC access is the recorded F-EXT-01
  authorization; the import reads public pages only.
- IDP Show cookie refresh — a credential action; and the vendor content is stale regardless.

## 8. Production verification still owed

1. After #1731 deploys: one real import on the live site; check `data/sources/ktc/` gets its
   last-good copy.
2. After #1732 deploys: next scheduled refresh writes `yahooBoone.csv` with 2026-10-09 content
   and stamps `yahooBoone_last_success`.
3. After #1733 deploys: `/tools/source-health` lists the production rows (including `signalsSf`).
4. Re-run §4's share table on the production contract (Signals present).
