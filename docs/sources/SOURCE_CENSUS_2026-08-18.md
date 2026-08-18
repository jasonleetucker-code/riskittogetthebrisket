# Source-network census — 2026-08-18

**Status:** measured, not asserted. Every number below was taken from the repository and a
contract built from the newest raw payload during the post-merge C-Series audit. Directive §12–§18.

**Scope note.** The canonical population is `src/api/data_contract.py::_RANKING_SOURCES` — **21**
production ranking sources, all `game_type: DYNASTY`. No source votes that is not in that list.

---

## 1. No surface reports the production population

Five surfaces publish something source-shaped. **Four of them are correct for their own purpose**,
and the honest finding is narrower than "they disagree": **none of them is a census of the 21
production voters**, and two of them speak different vocabularies.

| surface | reports | is that right? |
|---|---|---|
| `raw.sites` | **2** — `ktc`, `idpTradeCalc` | **Yes** — the inline-scraped sites, with `max` and `playerCount`. The 19 CSV-loaded sources legitimately are not here. |
| `coverageAudit.expectedSites` | **2** — `{offense:['ktc'], idp:['idpTradeCalc']}` | **Yes.** These are `TOP_OFF_EXPECTED_SITE_KEYS` / `TOP_IDP_EXPECTED_SITE_KEYS` — the two **backbone anchors**. Its consumer `server.py::_missing_expected_sites` (audit O-3) asks *"did we lose an anchor?"*, not *"are all sources healthy?"* |
| `settings.sourceRunSummary.sources` | **14** | Correct as a record of **scraper runs** — but in a different vocabulary (see below). |
| `scripts/check_source_health.py` | **21 + sleeper** | **Yes, and this one is the population-correct surface** — measured 20 fresh / 2 stale / 0 soft-stale = 22 = the 21 registry sources plus `sleeper`. |
| `_RANKING_SOURCES` (canonical) | **21** | the definition |

### What is actually wrong

1. **No published surface answers "how are the 21 doing?"** `check_source_health` knows, but it is a
   CI script writing annotations — not `/api/status`, not `/tools/source-health`, not the contract.
   A reader of the product's own health surfaces cannot see the production population.
2. **Two vocabularies, no mapping.** `sourceRunSummary` names *scraper runs*
   (`DLF_LocalCSV`, `Flock`, `DraftSharks_IDP`); the registry names *source keys*
   (`dlfSf`, `dlfRookieSf`, `dlfIdp`, `dlfRookieIdp`, `flockFantasySf`, …). One run name covers up
   to four registry keys. Nothing maps between them, so a per-source disposition cannot round-trip
   and a run-level "complete" cannot be decomposed into which boards actually arrived.
3. **The legacy `ktc` alias.** `raw.sites` and `expectedSites` say `ktc`; the registry says
   `ktcSfTep`; the contract carries **both** (`ktc` appears in `canonicalSiteValues` as a
   non-registry key). Three spellings of one provider across three surfaces.

**Correction, recorded rather than quietly fixed.** An earlier draft of this census said *"coverage
is measured against 2 of 21 — nineteen sources could vanish without moving a coverage number."*
That reads as a defect in `expectedSites` and it is **wrong**: that surface is an anchor-loss
detector and 2 is its correct population. The defect is the *absence* of a 21-source surface, not
the presence of a 2-source one.

## 2. Independence — 21 sources are 13 families

§17: separate CSVs from one provider are **not** independent votes. Measured assignment:

| family | members | note |
|---|---|---|
| `dlf` | 4 — `dlfSf`, `dlfRookieSf`, `dlfIdp`, `dlfRookieIdp` | SF / rookie / IDP / rookie-IDP boards from one provider |
| `fantasyPros` | 3 — `fantasyProsSf`, `fantasyProsIdp`, `fantasyProsFitzmaurice` | SF, IDP and the Fitzmaurice board are one provider |
| `draftSharks` | 2 — `draftSharks`, `draftSharksIdp` | offense + IDP are one provider, per §17 |
| `flockFantasy` | 2 — `flockFantasySf`, `flockFantasySfRookies` | board + rookies from one provider |
| `ktc` | 2 — `ktcSfTep`, `fantasyNavigatorSf` | `fantasyNavigatorSf` is KTC-derived and correctly grouped |
| *(singletons)* | 8 | each its own family |

**13 independent families**, not 21. This is what the confidence gate's independence axis
counts, and it is assigned correctly today — no repair needed. Recorded because the count is easy
to get wrong by reading the source list instead of the family list.

---

## 3. Per-source census

`votes` = rows carrying a positive `canonicalSiteValues` entry on the built contract.
`fetch age` = `data/scrape_state/<key>_last_success`.

**Correction, 2026-08-18 — that predicate undercounts sign-bearing sources.** `> 0` drops
legitimately NEGATIVE vendor values, and DraftSharks IDP publishes them (its `3D Value +` column
runs down to −38). Measured against `sourceRankMeta` — the sources that actually voted in the
blend, sign-agnostic — `draftSharksIdp` is **269**, not the 143 in the table below. Every other
row moves by less, in the same direction: `ktcSfTep` 502 → 421, `idpTradeCalc` 911 → 768,
`fantasyNavigatorSf` 454 → 367, `dlfRookieSf` 112 → 54.

The two quantities answer different questions — "did this source publish a value here" versus
"did it vote in the blend here" — and the second is the one source *health* wants, so
`_build_source_health_snapshot` counts off `sourceRankMeta` (S-1, below). The table is left as
measured rather than restated, with this note beside it.

| source | scope | game type | family | votes | fetch age | disposition |
|---|---|---|---|---|---|---|
| `idpTradeCalc` | overall_idp | DYNASTY | `idpTradeCalc` | 911 | 1.9h | ACTIVE — HEALTHY |
| `ktcSfTep` | overall_offense | DYNASTY | `ktc` | 502 | 1.9h | ACTIVE — HEALTHY |
| `fantasyProsSf` | overall_offense | DYNASTY | `fantasyPros` | 474 | 1.9h | ACTIVE — HEALTHY |
| `pfkDynasty` | overall_offense | DYNASTY | `pfkDynasty` | 472 | 1.9h | ACTIVE — HEALTHY |
| `fantasyNavigatorSf` | overall_offense | DYNASTY | `ktc` | 454 | 1.9h | ACTIVE — HEALTHY |
| `otcffbSf` | overall_offense | DYNASTY | `otcffbSf` | 425 | 1.9h | ACTIVE — HEALTHY |
| `flockFantasySf` | overall_offense | DYNASTY | `flockFantasy` | 412 | 1.9h | ACTIVE — HEALTHY |
| `yahooBoone` | overall_offense | DYNASTY | `yahooBoone` | 402 | 1.9h | ACTIVE — HEALTHY |
| `draftSharks` | overall_offense | DYNASTY | `draftSharks` | 399 | 0.0h | ACTIVE — HEALTHY |
| `fantasyCalc` | overall_offense | DYNASTY | `fantasyCalc` | 385 | 1.9h | ACTIVE — HEALTHY |
| `dynastyDaddySf` | overall_offense | DYNASTY | `dynastyDaddySf` | 368 | 1.9h | ACTIVE — HEALTHY |
| `idpShow` | overall_idp | DYNASTY | `idpShow` | 349 | 0.8h | ACTIVE — HEALTHY |
| `fantasyProsFitzmaurice` | overall_offense | DYNASTY | `fantasyPros` | 299 | 1.9h | ACTIVE — HEALTHY |
| `dynastyNerdsSfTep` | overall_offense | DYNASTY | `dynastyNerdsSfTep` | 293 | 1.9h | ACTIVE — HEALTHY |
| `dlfSf` | overall_offense | DYNASTY | `dlf` | 285 | 0.9h | ACTIVE — HEALTHY |
| `dlfIdp` | overall_idp | DYNASTY | `dlf` | 171 | 0.9h | ACTIVE — HEALTHY |
| `fantasyProsIdp` | overall_idp | DYNASTY | `fantasyPros` | 148 | 1.9h | ACTIVE — HEALTHY |
| `draftSharksIdp` | overall_idp | DYNASTY | `draftSharks` | 143 | 0.0h | ACTIVE — HEALTHY |
| `dlfRookieSf` | overall_offense | DYNASTY | `dlf` | 112 | 0.9h | ACTIVE — HEALTHY |
| `flockFantasySfRookies` | overall_offense | DYNASTY | `flockFantasy` | 76 | 1.9h | ACTIVE — HEALTHY |
| `dlfRookieIdp` | overall_idp | DYNASTY | `dlf` | 29 | 0.9h | ACTIVE — HEALTHY |

**All 21 are now `ACTIVE — HEALTHY`.** The two DraftSharks boards were `ACTIVE — DEGRADED`
when this census was taken — last successful dynasty fetch **303h** (12.6 days) — and were
repaired the same day by #894; see S-4 below. The diagnosis rested on
`draftSharksRos_last_success` being **1.8h** while the dynasty stamps sat at 303h: the ROS
fetch is a different endpoint and always worked, so "DraftSharks" looked healthy at a glance.

`votes` in the table above are as-measured at census time and are not restated here; the
refreshed boards moved 418 canonical values (p50 0.2%, p90 1.0%, max 6.9%) — classified in
`docs/sources/DRAFTSHARKS_DYNASTY_INGESTION_REPAIR.md` §5.

---

## 4. Non-registry paths and their dispositions

| path | disposition | evidence |
|---|---|---|
| `KTC_WaiverDB` (scraper producer) | **SUPERSEDED — RETIRED** | Second parser of the same inline array; `scripts/fetch_crowd_faab.py` is the live owner. Retired in #897. |
| `KTC_TradeDB` (scraper producer) | **FUTURE — NOT PRODUCTION** | Zero consumers — the list reached only `len()`. Deferred to C4-U3 / `C4-MTL-02`, which carries the measured live shape. Retired in #897. |
| `ktcCrowd` contract block | **RETIRED** | Appeared in **0 of 173** committed export archives, decompressed. |
| `ktcIdMap` contract block | **RETIRED** | Also 0 of 173; no consumer in any language. |
| `src/adapters/ktc_crowd_faab.py` | **SUPERSEDED — RETIRED** | Fed a second recommender input whose only output duplicated a row the live engine already emits. |

### KTC crowd-FAAB — production proof (§11), 2026-08-18

Read-only SSH probe, run
[`32129757659`](https://github.com/jasonleetucker-code/riskittogetthebrisket/actions/runs/32129757659),
against the deployed tree. No credential reached the agent; secrets and league names are
masked in the public log by the workflow.

*(The first dispatch, `32120625936`, was **cancelled** — it collided with the
`production-deploy` concurrency group. That was repaired in #904; this is the first run that
produced output.)*

| § | check | measured |
|---|---|---|
| 1 | timer unit | **present**, **enabled**, **active** |
| 1 | last service run / result | **0 (ok)** / **success** |
| 1 | last trigger · next elapse | 2026-08-18 11:26:12 CEST · 14:27:42 CEST |
| 2 | `src/sources/ktc_identity.py` on the box | **present** |
| 2 | producer consumes the owner | **yes** |
| 2 | retired crowd path removed | **yes** |
| 3 | identity source | `allPlayerSearchValues` — the search index, not the 500-row value board |
| 3 | index size | **1,961 players / 36 picks** |
| 3 | raw feed rows | 200 |
| 3 | **claims resolved to a player** | **200 / 200** |
| 3 | rows emitted by the producer | 200 |
| 3 | rows with an unreadable format | **0** |
| 4 | `dynasty_main` accumulated history | 702 persisted rows · 199 players priced · **148 $0 bids retained** |
| 4 | `dynasty_new` accumulated history | 561 persisted rows · 179 players priced · **129 $0 bids retained** |

Verdict: *"timer present, repaired code deployed, every claim resolved"*.

Two details worth keeping. The identity source is the **search index** (1,961 players), not
the 500-row value board — which is why resolution is 200/200 rather than partial. And the
retained **$0 bids** confirm the live path is `faab_history`, not `faab_analytics`: the latter
gates its median on `bid > 0`, and 41–77% of real adds cost nothing.
| `footballGuys` / `footballGuysSf` / `footballGuysIdp` | **RETIRED — orphaned stamps** | **No registry entry, no CSV, no consumer.** `_last_success` stamps are **2049h** (85 days) old. Survives only in comments and `source_gap:` explanation strings in `data_contract.py`. |
| `draftSharksRos` | **ACTIVE — NOT A DYNASTY VOTER** | Fetches fine (1.8h). ROS is the seasonal lane and must never enter dynasty valuation (C1-U9 / source-domain boundary). |
| `sleeper` | **ACTIVE — HEALTHY** | League/roster substrate, not a ranking voter. 1.9h. |

### FootballGuys — a finding, not just cleanup

The stale stamps are inert: `check_source_health` derives its population from the registry
(measured: 20 fresh + 2 stale = 22 = 21 registry + sleeper), so FootballGuys is not counted and
does not produce a false alarm. What is **not** inert is that `data_contract.py` still carries
`source_gap:` strings explaining certain players as *"only ranked by FootballGuys IDP"*. Those
explanations name a source that no longer exists, so the stated reason for those coverage gaps is
stale. Repair: drop the orphaned stamps and re-derive or re-word the affected `source_gap:` text.

---

## 5. Game type — fails closed

All 21 production voters carry `game_type: DYNASTY` with `game_type_evidence` naming why, per
C1-U9. `UNKNOWN` is not `DYNASTY`; `draftSharksRos` is the live example of a reachable feed that
is deliberately **not** a dynasty voter.

---

## 6. Open items

| # | item | state |
|---|---|---|
| S-1 | Publish a **21-source** health surface. `check_source_health` already knows the right population; `/api/status`, `/tools/source-health` and the contract do not. Do **not** widen `expectedSites` — it is an anchor-loss detector and 2 is correct for it | **REPAIRED 2026-08-18.** Measured first: `/api/status` reported `total_sources: 2` because its denominator was the 2-row `sites` list, and `/tools/source-health` rendered 2 rows because it listed `source_runtime.enabled_sources` (`["KTC", "IDPTradeCalc"]` — the scraper's own run names, which do not case-fold onto registry keys). Population now comes from `get_ranking_source_keys()`; counts from the served board's `sourceRankMeta`; a registered source contributing nothing is named in `missing_sources`, and one we have no measurement for is `unmeasured_sources` rather than accused of silence. `expectedSites` untouched and pinned. Audit finding **F-7** |
| S-2 | Map scraper-run names ↔ registry keys so a disposition round-trips and a run-level "complete" decomposes into which boards arrived | **OPEN — now measured, and it has a consequence.** `KTC_TEP` is a sub-product held in `FULL_DATA`, not a member of `active_sites`, so `sites_meta` never emits `ktcSfTep` and it is absent from `raw.sites` entirely. The scrape-promotion gate `server.py::_missing_expected_sites` therefore *cannot* watch it — `_reported_rows` would find no row count — which is why `coverageAudit.expectedSites.offense` names `ktc`, the display-only non-voter. Audit finding **F-10** is this defect seen from the consequence end: losing the entire TE++ board moved 444 of 468 offense rows while every gate said healthy. F-10 closed the contract floor and the scraper site_raw floor; the `raw.sites` half is still open and is the actual S-2 work |
| S-2b | ~~Collapse the `ktc` / `ktcSfTep` spelling split~~ | **RE-DIAGNOSED 2026-08-18 — the premise was wrong.** There is no spelling split: `ktc` and `ktcSfTep` are two genuinely different KTC boards (standard SF vs TE++ level 2), read from two real CSVs, plucked from one API response. `ktcSfTep` is the blend voter; `ktc` was dropped from the blend on 2026-04-28 as a KTC double-count and survives ONLY to populate `canonicalSiteValues` for the arbitrage finder and the per-source row on /trade. Collapsing them would have deleted a display source and, worse, would have made the wrong one look canonical. The real defect is that the guards pointed at the non-voter — F-10 — not that the names disagree. Disposition: `ktc` = **ACTIVE — HEALTHY (non-voting, but NOT display-only)** — measured, it covers 501 rows shared with `ktcSfTep` **plus 60 pick rows `ktcSfTep` does not cover at all**, and both `src/trade/finder.py` and `src/bdvm/market.py` read `("ktcSfTep", "ktc")` in that order, so on those 60 picks `ktc` is the only KTC market answer either engine has; `ktcSfTep` = **ACTIVE — HEALTHY (sole retail blend voter)** |
| S-3 | Health vocabulary must distinguish vendor-unchanged / stale / fetch-failed / parser-failed / credential / blocked / retired / future / archive-only | **OPEN** |
| S-4 | DraftSharks dynasty fetch | **CLOSED 2026-08-18** — #894 merged (`77f037ef2`); production `scheduled-refresh` run `32123775865` green, stamps 303.5h → 0.03h, tracking issue #765 auto-closed. Record: `docs/sources/DRAFTSHARKS_DYNASTY_INGESTION_REPAIR.md` |
| S-5 | Drop orphaned FootballGuys stamps; fix stale `source_gap:` explanations | **REPAIRED 2026-08-18.** Far larger than "stale strings": **18 of 52** `SINGLE_SOURCE_ALLOWLIST` entries named FootballGuys as the SOLE ranker of a top-board player, and none was true — 2 players were off the board, 14 were not single-source (Zavion Thomas carried **13** sources), and the 2 that were single-source were carried by `draftSharks` / `fantasyProsSf`. Removing all 18 leaves the contract `ok: True`, so they guarded nothing. Also normalised three prefix-grammar classes (`ktc_only` used the grammar backwards; `dynastyNerds` / `flock` resolved to nothing) and untracked the three orphaned stamps. Guarded by `tests/api/test_single_source_allowlist_integrity.py`, mutation-proven. Audit finding **F-8** |
| S-6 | Freshness policy: is stale evidence still a full-weight vote? | **OWNER DECISION REQUIRED** — no approved rule found in the authority hierarchy; inventing decay during an audit is forbidden (§15) |

