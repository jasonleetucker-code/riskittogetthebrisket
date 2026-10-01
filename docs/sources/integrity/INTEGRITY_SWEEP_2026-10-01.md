# Ingestion / lineage integrity sweep — 2026-10-01 (Batch 3 Unit G)

Owner requirement (Section G): accuracy cannot exceed input integrity. This sweep
re-checks, for every voting family, what the value pipeline otherwise takes on trust:
game type and format per endpoint, parser output against the live page, identity joins,
duplicates, coverage, native rank/value meaning, stale handling, change clocks, cadence,
lineage, and whether the board applies to offense, IDP, rookies and picks.

**Evidence only.** Nothing here changes a vote, a weight or a value. Methodology changes
(weights, admitting or removing voters, family assignments) appear only as
**recommendations** in §8.

Evidence classes. **proven** = vendor statement, payload structure or code. **measured** =
a statistic on real boards; it shows dependence, never common ancestry. **suspected** =
plausible, with no proof. Lineage pairs use the four durable categories defined in
`config/sources/source_lineage.json::categories` and `src/sources/source_census.py`
(§3a).

| pin | value |
|---|---|
| instrument | `scripts/audit/lineage_integrity_sweep.py` (new; tests `tests/sources/test_lineage_integrity_sweep.py`) |
| machine-readable result | `docs/sources/integrity/INTEGRITY_SWEEP_2026-10-01.json` (schema `lineage-integrity-sweep/v1`) |
| code base | `origin/main` `455ff0104` + this branch |
| inputs | `CSVs/site_raw/*.csv`, `data/scrape_state/*_dataset.json` and git history of both. The identity join is rebuilt through the live contract from `exports/latest/dynasty_data_2026-09-30.json` |
| as of | 2026-10-01T15:00Z (history window 120 days; clock honesty 30 days) |
| live-page checks | one-time public requests on 2026-10-01 (§0). Nothing captured was committed. |

## 0. Network log (bounded and polite; nothing committed)

Every request was public and unauthenticated. None returned 401, 403 or a captcha. No
paywall or login was bypassed: no IDP Show article body, no DLF, no Draft Sharks.

- **IDP Trade Calculator:** homepage, `script.js`, and the Apps Script feed it names (3 requests).
- **FantasyCalc, Dynasty Daddy, Fantasy Navigator, OTC, Flock:** the public value APIs, plus Flock `PROSPECTS_SF` (6 requests).
- **KTC:** one `dynasty-rankings` page.
- **Yahoo:** two Boone seed URLs, following their redirects.
- **FantasyPros:** the Fitzmaurice September and October articles, plus four October Datawrapper datasets.
- **The IDP Show:** the public Substack archive listing and public post metadata for its two dynasty posts. Also the chart-version check for chart `U8I37`, which mirrors the fetcher's own resolver.

## 1. Headline findings

1. **The IDP Trade Calculator mostly re-publishes other boards. This is measured, not vendor-stated.**
   - **Offense:** at each broad offense batch, its non-TE values equal KTC's base superflex crowd values from a capture 2–6 days earlier. 2026-06-06: 286 of 357 values exactly equal, all 357 within 1%. 2026-08-28: 212 of 359 equal, all 359 within 1%.
   - **IDP:** its ordering matches The IDP Show's IDP-only board exactly or nearly (0.00–0.04% of pairs out of order) within 1–6 hours of each IDP Show publication (07-21, 08-20, 08-26), then drifts through small edits of its own.
   - **Consequences.** Its offense vote is a lagged copy of KTC Crowd that sits outside the `ktcCrowd` family cap. Its IDP vote likely sends IDP Show's opinion a second time. And the Hill GLOBAL and IDP trainers that use it re-teach KTC and IDP Show (§3).
2. **IDP Trade Calculator picks and the IDP Show board: genuine vendor non-publication (proven).**
   - **Picks are not a parser or fetch defect.** The live Apps Script feed today matches our CSV exactly on all 84 pick rows. The 36 tier picks last changed 2026-08-28. The 48 "2026 Pick R.SS" slot picks have not changed since our first observation (2026-04-16), and 1.01 = 8013 < 1.02 = 8323.
   - **These frozen 2026 slot rows decide the draft year.** They are what makes `derive_current_draft_year_from_names` resolve the current draft year to 2026 (owner horizon decision #1442).
   - **The IDP Show combined board:** chart `U8I37` is still on v4 (v5 returns 404). Every post since 2026-08-29 is weekly, rest-of-season or betting content, so no dynasty board has been republished. Clocks are honest.
3. **Stale preservation conflicts with an owner record (owner decision needed).**
   - **The conflict.** Section G says a valid stale observation keeps voting with reduced authority and is never removed merely for staleness. But `freshness_v1.json::quarantineBelow = 0.02` (part of the 2026-09-23 directive) drops an observation once age / cadence ≥ 7.51 under curve C4.
   - **When it bites, at current cadences:**
     - IDP Trade Calculator picks and offense: 2026-10-09 13:10Z. Picks would then rest on KTC Crowd and Trades alone — two modes of one payload.
     - `idpShowCombined` (the IDP Show family's only vote): 2026-10-11 07:38Z.
     - `flockFantasySfRookies`: 2026-12-01.
4. **The IDP Show combined board is a vendor-declared aggregate (proven).**
   - **What the vendor says.** Its public post subtitle says it is built from "startup ADP and the best dynasty rankings in the industry". So it aggregates unnamed boards; it is not one analyst's board (it was recorded as `single_expert`).
   - **Game type is now proven from the vendor's own post titles.** Both posts are titled as dynasty rankings, rather than proven from the URL slug the registry cites (patch P4).
5. **Some recorded lineage was refreshed.** The method excludes both members of a pair from the consensus (§3).
   - **Fantasy Navigator:** its "KTC-derived values" claim is not supported by measurement: residual +0.04 with KTC Crowd and 0 equal values, against +0.60 with FantasyPros SF.
   - **OTC vs base KTC:** the +0.891 from 2026-07-27 is not reproduced (now −0.20). The old instrument's consensus contained several KTC copies.
   - **PFK vs KTC Crowd:** +0.687, the strongest offense pair in the matrix.
   - **KTC Crowd vs Trades:** first measured at +0.615.
6. **Clocks are honest (measured).** Over 30 days, no byte-only CSV change moved a data clock for any source: 0 events coincided with a version whose meaningful content was unchanged. Every recorded event matches a real content change, except two timing mismatches of more than 3 hours (one each for PFK and FantasyPros SF).
7. **Three objective defects were fixed, with failing-first tests:**
   - FantasyPros IDP duplicate identities;
   - the Fitzmaurice silent 1QB / non-TEP format fallback;
   - stale statements: the IDP Show "votes NOTHING" comment, the Fantasy Navigator docstring and the KTC writer docstring.
8. **Flock's rookie board came back empty today.** `PROSPECTS_SF` returned `data: []` with `subscribed: false`. We cannot tell withdrawal from a new subscriber gate, and we did not bypass it. The 2026-09-05 board keeps voting at falling freshness (0.62).

## 2. Per-family table

Identity counts come from the contract rebuild (`identityJoin` in the JSON):
- **CSV ids:** distinct contract match keys in the CSV.
- **attached:** keys that reached at least one board row.
- **not attached:** an upper bound on identity misses. It also counts vendor rows outside our board universe, such as deep-tail veterans.
- **dup / amb:** duplicate keys in the CSV, and board rows with an ambiguous CSV entry.

Cadence is the observed p75 of closed broad-change intervals, against the declared `[minHours, maxHours]`. Clock honesty is measured over 30 days.

| family | sources | format proven per endpoint? | parser == page? | identity: CSV ids / attached / not / dup / amb | coverage (board rows: off / idp / pick / rookie) | native semantics | stale behaviour | clocks honest? | cadence obs p75 vs declared | lineage (category) | applicability |
|---|---|---|---|---|---|---|---|---|---|---|---|
| ktcCrowd | `ktcCrowdSfTep`, `fantasyNavigatorSf` | KTC: superflex / TE++ / dynasty are **hard-coded constants**, not read from the page (sf=true URL; the payload carries every TEP level). FN: `rank_type == dynasty` and `roster_type == sf_value` **checked per row**. FN's TE premium is unverified | KTC: live page 500 rows; 495 shared with the 09-30 capture (5 tail swaps); same fields. FN: 769 / 769 rows, same identities | KTC 500 / 499 / 1 / 0 / 0. FN 769 / 455 / 314 (deep tail) / 0 / 0 | KTC 462 / 0 / 36 / 68. FN 449 / 0 / 0 / 64 | KTC: native 0–9999 value (value-direct). FN: native value, voted as a competition rank (457 tied rows) | Fresh (SNAPSHOT, 12 h) | yes; 2 KTC versions had no event (sampling) | KTC 6.3 h < min 12 (min binds: polling-limited, by design). FN 26.9 h within bounds | KTC↔FN **PROVEN_COMMON_ANCESTRY** (data-source credit) with order dependence ≈ 0 | offense, picks (KTC), rookies |
| ktcTrades | `ktcTradesSfTep` | as KTC Crowd (same payload, `vftValue`) | live 500; same set | 500 / 499 / 1 / 0 / 0 | 462 / 0 / 36 / 68 | native value (vft) | fresh | yes | 6.3 h (min binds) | Crowd↔Trades **PROVEN_COMMON_ANCESTRY** + measured +0.615 | offense, picks |
| idpTradeCalc | `idpTradeCalc` | **The feed carries every format** (`value_1qb/sf/tep/sftep`). The site and our parser both read `value_sftep` first. Dynasty is evidenced only by its pricing of future picks | **yes**: 0 value differences on 899 shared rows. Our CSV is the top 900 by value (`SITE_CAP_COMBINED`) of 1,024 live rows. Two vendor name collisions (Justin Jefferson WR/LB, Byron Murphy DT/CB) are collapsed to the higher value by the scraper | 899 / 896 / 3 / 1 (Demario / DeMario Douglas, same value) / 1 | 432 / 376 / 24 / 121 | native 0–9999, one cross-market scale | **Offense rows unchanged since 08-28** (authority 0.061). **Picks:** tiers since 08-28, slots since ≤04-16 (0.059). IDP current | yes | players 159 h (within); picks 1128 h > max 240 (max binds) | **MEASURED** KTC value identity (offense); **MEASURED** IDP Show lead-lag (IDP) | offense / IDP / picks / rookies — but see lineage |
| dlf | `dlfSf`, `dlfRookieSf`, `dlfIdp`, `dlfRookieIdp` | Login-gated; not re-fetched in this sweep (DLF claim). The registry asserts dynasty per board | not checked live (paywall); the CSV `rank` is DLF's expert **average** rank (fractional, 13% integer); the value column is empty | SF 286/286/0; RSF 58/58; IDP 172/172; RIDP 30/30 | SF 286 / – / – / 40; RSF 57 (+58 synthetic "2026 Pick" rows); IDP 166; RIDP 30 | expert-average rank → rank → Hill | current (SF changed 09-30, RSF 09-29, IDP 09-24, RIDP 09-29) | yes | SF 47.5 h; RSF 54.5; IDP **174 > max 168**; RIDP 321 | regular↔rookie **MEASURED** +0.607 (n=40), not a re-cut | `dlfRookieSf` also stamps 58 "2026 Pick R.SS" rows (rookie-ordinal → slot), which Phase 1 excludes from voting |
| idpShow | `idpShowCombined` (voter); `idpShow` (non-voting) | **Dynasty now proven from the vendor's post titles** (public metadata), not the URL slug | Login-gated; HEALTHY 665-row fetches daily. Upstream `lastModifiedAt` 2026-08-19, chart v4 | 662 / 658 / 4 / 3 (Travis Hunter two-way; Byron Murphy and Justin Jefferson collisions) / 3 | 356 / 301 / 0 / 100 | combined ordinal rank (1–667, 5 gaps) → GLOBAL Hill | SEVERELY_STALE 0.051; **quarantine 2026-10-11** | yes (no change since acquisition) | no closed interval (seed 168 h) | combined board is a **vendor-declared aggregate** (proven). Combined↔IDP-only measured +0.796 | offense + IDP + rookies |
| dynastyNerdsSfTep | same | URL path `/dynasty-rankings/sf-tep/` (not re-fetched) | not re-fetched | 294 / 294 / 0 | 294 / – / – / 48 | rank 1–294; native value up to 10256 (53 tied-value rows carry distinct ranks) | current (09-11, monthly) | yes | 356 h within | ↔Fitzmaurice **MEASURED** +0.643 | offense |
| fantasyCalc | same | `isDynasty=true&numQbs=2&ppr=1` (format in the query) | live 395 rows, 381 shared (tail churn ±15/day) | 397 / 390 / 7 / 0 | 390 / 65 rookies | native value, voted as rank (40 tied) | fresh | yes; 2 versions without an event | 5.9 h < min 12 (min binds) | ↔DD **MEASURED** +0.635 | offense |
| dynastyDaddySf | same | `market=14` (format not self-described) | live 381; 378 shared | 381 / 381 / 0 | 380 / 65 | native value; **73 tied-value rows get distinct ranks** (open defect) | fresh | yes | 5.6 h (min binds) | ↔FC **MEASURED** | offense |
| otcffbSf | same | `format=sf`; payload echoes `format: sf` | live 370 / 370, same identities | 370 / 369 / 1 | 369 / 61 | 0–100 value, voted as rank (176 tied) | fresh | yes | 24.5 h within | ↔FC **MEASURED** +0.511; ↔KTC not reproduced (−0.20) | offense |
| pfkDynasty | same | **No format parameter.** Superflex vs 1QB unverified; dynasty from the table name | not re-fetched | 496 / 460 / 36 (deep tail) | 455 / 64 | own 0–9999 value; **vendor rank and tier discarded**, ordering recomputed from value | fresh | yes (1 timing mismatch) | 60 h within | ↔KTC Crowd **MEASURED** +0.687 | offense |
| fantasyPros | `fantasyProsSf`, `fantasyProsIdp`, `fantasyProsFitzmaurice` | SF: `dynasty-superflex.php` (URL only). IDP: four dynasty pages. Fitz: October article proven to carry the `SF Value` / `TEP Value` columns | Fitz: our parser on the live October charts gives 50/88/115/46 rows (299); the CSV is still the September board (October published today). SF / IDP not re-fetched | SF 397/387/10. IDP 283/257/26/**16 dup**/16 amb (fixed). Fitz 297/297/0 | SF 384 off; IDP 251; Fitz 297 | SF: integer ECR rank. IDP: `effectiveRank`, 180 of 299 interpolated from positional pages. Fitz: 0–100 value → competition rank (218 tied) | current | yes | SF 16 h < **min 48** (min binds → freshness lenient); IDP 253 h; Fitz 713 h | SF↔Fitz **SUSPECTED** (residual −0.04) | offense / IDP |
| flockFantasy | `flockFantasySf`, `flockFantasySfRookies` | `format=superflex` / `PROSPECTS_SF`; the payload echoes `format`. Dynasty assumed. **Prospects board empty today** | veteran live 436 / 436 (same set; expert `lastUpdated` stamps per row) | Sf 435/408/27/1 (two "Cole Payton" rows); R 48/47/1 | 407 / 66; R 47 | expert-average rank (fractional) | Sf fresh; R STALE 0.62 (quarantine 2026-12-01) | yes (10 byte-only versions, none moved a clock) | Sf 52 h; R 314 h | Sf↔R **MEASURED** +0.194; all 48 rookies are on the veteran board | offense, rookies (R borrows KTC Crowd's rookie-ladder scale) |
| yahooBoone | same | Seed URLs redirect to the **2026-09-03** QB/RB articles (live check), and the format columns (2QB, TE Prem.) are proven by the fetcher | **yes**: RB table 100 = CSV 100; QB 80 = 80 | 410 / 388 / 22 | 387 / 68 | 0–141 value → competition rank (314 tied) | current (monthly) | yes | 852 h within | – | offense |
| draftSharks | `draftSharks`, `draftSharksIdp` | URL path `te-premium-superflex` (dynasty assumed). League scoring proven per pass. **The shared offense/IDP scale is not re-proven per run** | login-gated; not re-fetched | Off 391/375/16; IDP 408/319/89/1 | 372 / 318 IDP | 3D Value+ (negatives allowed), pooled into one combined rank; `Rank` column is the fetcher's own; Team column empty | fresh | yes (38 byte-only versions, none moved a clock) | 18 h / 28 h within | Off↔IDP **PROVEN_COMMON_ANCESTRY** (one DOM); contrarian | offense / IDP / rookies |

**Cross-position applicability.** Only the IDP Trade Calculator, `idpShowCombined` and
the combined Draft Sharks rank place offense and IDP on one ordering. The first follows
two other boards. The second is an aggregate. The third rests on an unverified shared
scale. "No independent IDP reference" (CLAUDE.md step 10) is now sharper: the main IDP
backbone follows IDP Show.

**Rookie applicability.** DLF and Flock rookie boards contribute ORDER only. Their
spacing is KTC Crowd's offense rookie ladder (DLF IDP rookies use the IDP Trade
Calculator's), by code (`ROOKIE_LADDER_PAIRS`).

**Pick applicability.** Only two markets price picks: KTC (Crowd and Trades, one
payload) and the IDP Trade Calculator, whose pick rows are stale (above).

## 3. Named open questions

| question | answer | class |
|---|---|---|
| **IDP Trade Calculator:** offense / IDP / pick clocks and pick sourcing | **Clocks.** Offense rows last changed 2026-08-28 (435 of 437 in one batch). IDP rows changed through 2026-09-23. Tier picks changed 2026-08-28; slot picks are frozen since at least 2026-04-16. **Pick sourcing.** Sheet2 holds the 48 slot picks and Sheet3 the 36 tier picks; the parser reads `value_sftep`, as the site does. **Root cause: genuine non-publication.** A live fetch matches all 84 pick values exactly, so it is not a parser or fetch-path defect. **Lineage.** Offense batches are KTC base-SF copies (value identity); the IDP ordering follows the IDP Show IDP-only board (lead-lag) | proven (live identity); measured (lineage) |
| **DLF:** board freshness, native Values, rookie relationship | **Freshness.** All four boards are current (changed 09-24 to 09-30; fetch stamps today). dlfIdp's observed p75 (174 h) slightly exceeds the declared max (168 h). **Values.** `dlfValuesSfTep` is non-voting and current (five daily changes since 09-25). Its residual vs DLF Rank is +0.704, so the two are distinct quantities. The picks audit CSV `dlfValuesSfTepPicks.csv` is **header-only (0 rows)** although the Values page carries picks; we did not touch it (DLF claim). **Rookie boards.** These are separate expert rankings: 40 of 58 overlap the SF board, with 7.4% discordant pairs and residual +0.607. They stay in one family | measured |
| **IDP Show:** dynasty cadence vs weekly/redraft content; game type; "votes NOTHING" comment | **Cadence.** The dynasty board has not been republished: chart v4 (lastModified 08-19), and posts since 08-29 are weekly / rest-of-season / betting. Offseason cadence was ~9–12 days (4 versions 07-15→08-19). Weekly content is a different game type and is correctly never ingested. **Game type.** Dynasty is now proven by the vendor's post titles. **The comment was stale** and is fixed. The `source_inventory.py` "IDP-only cut" reason is also wrong (patch P3) | proven |
| **Fantasy Navigator:** KTC lineage | KTC data-source use is proven (ids and the site credit). Its ordering does not track KTC: residual +0.038 vs Crowd (n=428), 0 of 437 values equal. Its strongest dependence is FantasyPros SF (+0.597). Category: PROVEN_COMMON_ANCESTRY of inputs, with near-zero measured order dependence | proven + measured |
| **FantasyCalc vs Dynasty Daddy** | Residual +0.635 (n=366), stable from +0.677 on 08-04. Values are not copies (≤1.1% equal at any 4-day lag) | measured |
| **PFK vs KTC** | Residual +0.687 vs Crowd (n=439), the largest in the offense matrix, and +0.382 vs Trades. Not copies (1 of 447 equal; different scale). Ancestry stays suspected | measured |
| **Draft Sharks:** offense/IDP separation and semantics | One DOM, split by `data-fantasy-position` into two CSVs. Each family is collected through the page's own filter and merged on vendor `data-key`. **What votes:** the pooled 3D Value+ across both CSVs, re-ranked into one combined rank on the GLOBAL Hill. The `Rank` column is the fetcher's 1..N, not the vendor's. **Gap:** the cross-family scale is never verified per run (the overlap is measured within each family only) | proven (code) |
| **FantasyPros consensus / Fitzmaurice** | Same provider, one B10 family. Leave-pair-out residual −0.039 (n=290): effectively independent. The earlier −0.61 came from a consensus containing both boards. Nesting is unproven → SUSPECTED_DEPENDENCE. Fitzmaurice format fallback fixed (§5) | measured / suspected |
| **Flock:** regular / rookie semantics | Both are fractional expert-average ranks from one API, and all 48 rookies are also on the veteran board. The rookie board is a different endpoint (`PROSPECTS_SF`), translated onto KTC Crowd's rookie ladder. Residual vs the veteran board +0.194. **Today the prospects board returns empty** | measured / proven (code) |
| **KTC Crowd vs Trades** (never measured) | **First measurement.** Residual +0.615 (n=449). Spearman 0.966 on the CSVs, 0.969 on the live page, 0.981 in the top 150. 1 of 464 values identical. Trades/Crowd ratio: median 1.003, p10 0.865, p90 1.328 | measured |

### 3a. Four-category pair reconciliation (owner requirement)

The categories are canonical in `config/sources/source_lineage.json::categories` and
`src/sources/source_census.py::LINEAGE_CATEGORIES`. `validate_lineage` enforces their
rules:
- **PROVEN_COMMON_ANCESTRY** needs a supporting `proven` relation.
- **MEASURED_DEPENDENCE** needs a supporting `measured` relation plus method, window and n.
- **INDEPENDENT_NO_EVIDENCE** may not contradict a supporting relation.
- **A null category** means UNKNOWN and must carry its reason.
- **Every pair** states its consequence for family capping, Hill holdouts, source-quality evaluation, Hill training and completed-trade evaluation.

The full text lives in `pairReconciliation`.

| pair | category | key evidence (2026-10-01) | family cap | Hill holdout (C20 stays OPEN while holdouts vote) | Hill training | source-quality eval | completed-trade eval |
|---|---|---|---|---|---|---|---|
| KTC Crowd ↔ Fantasy Navigator | PROVEN_COMMON_ANCESTRY (inputs) | ids + site credit; order residual +0.038 | same family; keep | FN cannot be an independent holdout while KTC trains | never alongside KTC | leave-family-out | inherited agreement with KTC-platform trades |
| KTC ↔ PFK | MEASURED_DEPENDENCE | +0.687 / +0.382, n=439 | separate families → counted twice; review | PFK holdout flattered (1.64x) | don't promote PFK while KTC trains | leave-lineage-out | evaluate with KTC jointly |
| FantasyCalc ↔ Dynasty Daddy | MEASURED_DEPENDENCE | +0.635, n=366 | separate; review | FC holdout while DD trains: not independent | one market shape taught once | leave-pair-out | not two confirmations |
| FantasyPros ↔ Fitzmaurice | SUSPECTED_DEPENDENCE | −0.039, n=290 (too weak) | same provider family; may discard signal | none | Fitz native values = H3 channel | separate | none |
| DLF regular ↔ rookie | MEASURED_DEPENDENCE | +0.607, n=40; 7.4% discordant | one family; correct | none | rookie spacing borrowed from KTC Crowd / IDPTC | one family | DLF once |
| Draft Sharks offense ↔ IDP | PROVEN_COMMON_ANCESTRY | one DOM (code) | one family; correct | none | GLOBAL "DraftSharks-Combined" rests on the unproven shared scale | score separately | none |
| KTC Crowd ↔ KTC Trades | PROVEN_COMMON_ANCESTRY | one payload; +0.615 | two families by directive; review | none | Crowd trains, Trades doesn't | leave-provider-out | **Trades vs KTC Trade Database is in-sample** |
| IDP Trade Calculator ↔ IDP Show | MEASURED_DEPENDENCE | +0.992 (IDP-only, n=243); lead-lag | IDP Show possibly counted twice; review | none | IDP master trains on IDPTC IDP ≈ IDP Show | leave-lineage-out | not independent of IDP Show |
| IDP Trade Calculator ↔ KTC (offense) | MEASURED_DEPENDENCE | batch value identity, n=357 | stale KTC copy outside the cap | none | GLOBAL "IDPTradeCalc" re-teaches KTC | never each other's target | inherited |
| Signals ↔ market families | **UNKNOWN** (null) | pending authenticated data (Unit H); not guessed | none (non-voting) | must not be a holdout | never | excluded | excluded |

## 4. Cross-cutting measurements

- **Change clocks (30 days).** Every source had 0 byte-only versions coinciding with an event. Byte-only versions are common, because CSV bytes change while the meaningful content does not:
  - Draft Sharks 38, Draft Sharks IDP 37, FantasyPros SF 15, Flock 10, FN 2, FP IDP 2, DLF Values 2.
  - Meaningful content is the dataset-state owner's own definition (`dataset_integrity.parse_board`); none of these moved a clock.
  - Pre-2026-09 dataset history was backfilled at coarser sampling: some May git versions of the DLF rookie boards have no event. The live process has matched 1:1 since then.
- **Rank boards: insertion vs re-evaluation.** Order-preserving changes (players entering or leaving with no reordering) are rare: Flock 12 of 111 events, and only 1 with ≥5 rank shifts. Insert/remove shifts do not materially inflate the broad-change clock.
- **Where a declared cadence bound binds.**
  - **minHours binds** for KTC (×3), FantasyCalc and Dynasty Daddy. This is by design (polling-limited).
  - **FantasyPros SF: freshness is lenient.** It changes every 16 h at p75, but `minHours` = 48.
  - **maxHours binds** for dlfIdp (174 > 168) and for IDP Trade Calculator picks (1128 > 240).
- **Stale preservation** (finding 3): last-known observations do keep voting, and they recover automatically on genuine publication (`dataset_state` keeps the last valid content). But they are **dropped at freshness < 0.02**, which contradicts the Section G wording.

## 5. Defects fixed on this branch (failing-first tests)

| defect | fix | test |
|---|---|---|
| FantasyPros IDP wrote 16 dual-listed edge rushers twice, with two effective ranks | `scripts/fetch_fantasypros_idp.py::_build_rows`: one row per player, keeping the better effective rank (the entry the contract already served, so no vote changes). **The next fetch drops 16 rows once**, which the dataset state will record as one parser-change event | `tests/scripts/test_fetch_fantasypros_idp.py::TestOneObservationPerPlayer` |
| Fitzmaurice fell back per row to 1QB `Trade Value` (QB) and the non-premium value (TE) under a superflex / TE-premium source | `scripts/fetch_fantasypros_fitzmaurice.py`: the format column is chosen once per chart from the header. If QB or TE lacks it, `FormatColumnMissing` is raised and last-good is preserved. A blank cell is dropped. October live charts parse identically (50/88/115/46) | `tests/adapters/test_fitzmaurice_scraper.py` (4 new) |
| `fetch_idpshow.py` said the voting board "votes NOTHING" and carried a 250-row measurement | comment rewritten | `test_idpshow_fetcher_no_longer_says_the_voting_board_votes_nothing` |
| `fetch_fantasynavigator.py` asserted that FN's values are KTC-derived | docstring states proven input use plus the measured non-identity | — |
| `ktc_value_sources.write_capture_artifacts` said Crowd/Trades "do not register votes" | docstring corrected (they are registered inputs since 2026-09-23) | — |

## 6. Open defects (recorded in `source_lineage.json::defects`)

- **`fantasypros-idp-anchored-inside-combined-range`**: 24 players absent from the 119-row combined page are interpolated to ranks 89–119. Methodology question.
- **`idptc-autocomplete-case-duplicate`**: no value impact. Lives in `Dynasty Scraper.py`.
- **`idptc-frozen-current-year-slot-picks`**: genuine vendor state. It drives the observed draft year (#1442).
- **`flock-prospects-board-empty`**
- **`fitzmaurice-datawrapper-version-pinned`**
- **`draftsharks-team-column-empty`**
- **`contract-stale-source-comments`**: patches P1/P2/P4/P5 below.
- **`dynastydaddy-ties-ranked-ordinally`**: still open (73 rows today).
- **`idpshow-inventory-reason-contradiction`**: patch P3.
- **Not recorded as defects (out of scope or claimed):**
  - **DLF Values picks:** the audit CSV is header-only (DLF claim).
  - **KTC:** format constants are hard-coded rather than observed. Recommend asserting them from the payload's `superflexValues` / `tepp` keys.

## 7. Patch descriptions for files owned by other lanes

These files belong to other lanes, so they get strict-xfail guards (`raises=AssertionError`) in
`tests/sources/test_lineage_integrity_sweep.py`. Each guard flips to XPASS, and so fails
under strict mode, once the patch lands. Remove the marker in the same patch.

- **P1 — `src/api/data_contract.py`, the Phase 1c comment above `csv_rank_cross_market_keys`.** Replace "DORMANT AS OF 2026-07-29 … this set is currently EMPTY and the block below never executes" with: *active since 2026-08-20; its only member is `idpShowCombined`, a rank-signal cross-market source that votes its own combined CSV rank on the GLOBAL Hill*. Guard: `test_contract_phase_1c_comment_does_not_claim_the_set_is_empty`.
- **P2 — `data_contract.py`, the rookie-ladder comment block in the pre-pass.** Two lines say "→ KTC Crowd+Trades ladder" for `dlfRookieSf` and `flockFantasySfRookies`. Change both to "→ KTC Crowd (`ktcCrowdSfTep`) ladder", matching `ROOKIE_LADDER_PAIRS`. Guard: `test_contract_rookie_ladder_comment_names_the_crowd_ladder_it_uses`.
- **P3 — `scripts/source_inventory.py:72`.** Replace the `idpShow` reason with: *"IDP-only two-expert consensus board from the same provider as the voting idpShowCombined (a different quantity, not a re-cut); voting both would count one provider twice"*. Also update the census lineage evidence. Guard: `test_source_inventory_does_not_call_idpshow_a_cut_of_the_combined_board`.
- **P4 — `data_contract.py`, the `idpShowCombined` registry `game_type_evidence`.** Replace the URL-path argument with: *the vendor's post title, "Combined IDP + Offense Dynasty Rankings" (public post metadata, read 2026-10-01); the publisher's weekly and rest-of-season posts are separate and not fetched*. This makes the claim comply with CLAUDE.md's "never inferred from a URL fragment".
- **P5 — `data_contract.py` comments, no behaviour change:**
  - the `fantasyProsFitzmaurice` and `yahooBoone` registry comments describe value-direct voting, but both vote as rank since PR #216;
  - the `fantasyProsIdp` path comment claims the fetcher writes a `Rank` alias column, but it reads `effectiveRank`;
  - the `draftSharks` comments still say "single offense-combined DOM" and "the 0-100 absolute scale is irrelevant". The second is wrong because the combined re-rank pools both scales.

## 8. Recommendations (methodology — owner decision; not implemented)

1. **Resolve the stale-preservation conflict before 2026-10-09.**
   - **The choice:** either restate Section G as "dropped below freshness 0.02", or replace the quarantine with a floor (for example, keep the vote at the 0.02 authority).
   - **What is at stake:** on 10-09 the IDP Trade Calculator picks leave the pick blend, which then rests on KTC alone.
2. **Cap the IDP Trade Calculator's lineage.**
   - **Options for its offense vote:** count it inside `ktcCrowd` for offense rows, or exclude its offense vote. It is a KTC copy, today down-weighted only because it is stale; the next batch copy restores it to about 1.0.
   - **IDP:** decide whether its IDP vote and `idpShowCombined` share an IDP-scoped cap.
   - **Hill training:** stop training GLOBAL and IDP Hill on it as if it were independent (Unit D manifest).
3. **PFK and FantasyCalc are not independent holdouts.** C20 stays open. Unit D's family-aware holdouts should exclude PFK while KTC trains, and FantasyCalc while Dynasty Daddy trains.
4. **KTC Trades vs the KTC Trade Database (Unit I).** The comparison is in-sample; never use it as validation of Trades.
5. **Lower FantasyPros SF `minHours`** (48 → about 16–24) so its freshness reflects its observed cadence.
6. **Reclassify `idpShowCombined`** as `derived_aggregate` in evaluation designs (done in the lineage registry). Treat it as correlated with every board.
7. **Add a WITHDRAWN acquisition state for a well-formed empty board** (Flock prospects), distinct from a fetch failure.
8. **Assert KTC format from the payload** rather than from constants. Add per-run scale proof for the Draft Sharks combined rank.

## 9. Reproduce

```
PYTHONUTF8=1 python scripts/audit/lineage_integrity_sweep.py --as-of 2026-10-01T15:00:00Z \
    --payload exports/latest/dynasty_data_2026-09-30.json \
    --out docs/sources/integrity/INTEGRITY_SWEEP_2026-10-01.json
python -m pytest tests/sources/test_lineage_integrity_sweep.py -q
```

The live-page checks in §0 are not part of the instrument: they are network-bound and
time-dependent. Their results are recorded in this document only.

## 10. UNRESOLVED

- **Not re-verified live:** DLF, Draft Sharks, IDP Show and Dynasty Nerds parser-vs-page, because they are login-gated or out of bounds.
- **Not checked:** the Fantasy Navigator site's KTC credit was not re-read; it is the existing 2026-07-25 record.
- **Not determinable without the owner's session:** whether the IDP Show IDP-only post edit on 2026-09-04 changed its data.
- **Not determinable:** whether Flock's empty prospects board is a withdrawal or a new subscriber gate.
- **Owner decisions pending:** the stale-preservation conflict and the family-cap and holdout recommendations (§8).
- **`notAttached` is an upper bound:** identity misses are not separated from out-of-universe vendor rows.
