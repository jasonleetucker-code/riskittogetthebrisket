# Source-network census — 2026-08-18

**Status:** measured, not asserted. Every number below was taken from the repository and a
contract built from the newest raw payload during the post-merge C-Series audit. Directive §12–§18.

**Scope note.** The canonical population is `src/api/data_contract.py::_RANKING_SOURCES` — **21**
production ranking sources, all `game_type: DYNASTY`. No source votes that is not in that list.

---

## 1. The health surfaces disagree with each other and with the truth

This is the §14 defect, and it is worse than "one surface is stale" — there are **four**
populations across four surfaces and **none of them is the real one**:

| surface | population it reports | vocabulary |
|---|---|---|
| `raw.sites` | **2** — `ktc`, `idpTradeCalc` | source keys (legacy `ktc`, not `ktcSfTep`) |
| `coverageAudit.expectedSites` | **2** — `{offense:['ktc'], idp:['idpTradeCalc']}` | a **hardcoded literal**, not derived |
| `settings.sourceRunSummary.sources` | **14** | **scraper-run names** — `DLF_LocalCSV`, `Flock`, `DraftSharks_IDP` |
| `_RANKING_SOURCES` (canonical registry) | **21** | source keys |
| **actually voting in the contract** | **21** | source keys |

Two consequences worth stating separately:

* **Coverage is measured against 2 of 21.** `expectedSites` is a literal naming one offense and
  one IDP source, so nineteen sources can vanish without moving a coverage number.
* **The run summary speaks a different language from the registry.** `DLF_LocalCSV` covers four
  registry keys (`dlfSf`, `dlfRookieSf`, `dlfIdp`, `dlfRookieIdp`); `Flock` covers two;
  `DraftSharks` and `DraftSharks_IDP` are separate run names but **one** provider family. Nothing
  maps between the vocabularies, so a per-source disposition cannot round-trip.

Both must be reconciled onto the registry before the audit can claim the health layer is honest.

---

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
| `draftSharks` | overall_offense | DYNASTY | `draftSharks` | 399 | 303.1h | ACTIVE — DEGRADED |
| `fantasyCalc` | overall_offense | DYNASTY | `fantasyCalc` | 385 | 1.9h | ACTIVE — HEALTHY |
| `dynastyDaddySf` | overall_offense | DYNASTY | `dynastyDaddySf` | 368 | 1.9h | ACTIVE — HEALTHY |
| `idpShow` | overall_idp | DYNASTY | `idpShow` | 349 | 0.8h | ACTIVE — HEALTHY |
| `fantasyProsFitzmaurice` | overall_offense | DYNASTY | `fantasyPros` | 299 | 1.9h | ACTIVE — HEALTHY |
| `dynastyNerdsSfTep` | overall_offense | DYNASTY | `dynastyNerdsSfTep` | 293 | 1.9h | ACTIVE — HEALTHY |
| `dlfSf` | overall_offense | DYNASTY | `dlf` | 285 | 0.9h | ACTIVE — HEALTHY |
| `dlfIdp` | overall_idp | DYNASTY | `dlf` | 171 | 0.9h | ACTIVE — HEALTHY |
| `fantasyProsIdp` | overall_idp | DYNASTY | `fantasyPros` | 148 | 1.9h | ACTIVE — HEALTHY |
| `draftSharksIdp` | overall_idp | DYNASTY | `draftSharks` | 143 | 303.1h | ACTIVE — DEGRADED |
| `dlfRookieSf` | overall_offense | DYNASTY | `dlf` | 112 | 0.9h | ACTIVE — HEALTHY |
| `flockFantasySfRookies` | overall_offense | DYNASTY | `flockFantasy` | 76 | 1.9h | ACTIVE — HEALTHY |
| `dlfRookieIdp` | overall_idp | DYNASTY | `dlf` | 29 | 0.9h | ACTIVE — HEALTHY |

**All 21 are `ACTIVE — HEALTHY` except the two DraftSharks boards**, which are
`ACTIVE — DEGRADED`: last successful dynasty fetch **303h** (12.6 days). Repair in flight (#894).
Note `draftSharksRos_last_success` is **1.8h** — the ROS fetch works; only the *dynasty* board is
broken, which is the evidence the repair's diagnosis rests on.

---

## 4. Non-registry paths and their dispositions

| path | disposition | evidence |
|---|---|---|
| `KTC_WaiverDB` (scraper producer) | **SUPERSEDED — RETIRED** | Second parser of the same inline array; `scripts/fetch_crowd_faab.py` is the live owner. Retired in #897. |
| `KTC_TradeDB` (scraper producer) | **FUTURE — NOT PRODUCTION** | Zero consumers — the list reached only `len()`. Deferred to C4-U3 / `C4-MTL-02`, which carries the measured live shape. Retired in #897. |
| `ktcCrowd` contract block | **RETIRED** | Appeared in **0 of 173** committed export archives, decompressed. |
| `ktcIdMap` contract block | **RETIRED** | Also 0 of 173; no consumer in any language. |
| `src/adapters/ktc_crowd_faab.py` | **SUPERSEDED — RETIRED** | Fed a second recommender input whose only output duplicated a row the live engine already emits. |
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
| S-1 | Reconcile the four health populations onto the registry; make `expectedSites` derived, not a literal | **OPEN** |
| S-2 | Map scraper-run names ↔ registry keys so a disposition round-trips | **OPEN** |
| S-3 | Health vocabulary must distinguish vendor-unchanged / stale / fetch-failed / parser-failed / credential / blocked / retired / future / archive-only | **OPEN** |
| S-4 | DraftSharks dynasty fetch | repair in flight (#894) |
| S-5 | Drop orphaned FootballGuys stamps; fix stale `source_gap:` explanations | **OPEN** |
| S-6 | Freshness policy: is stale evidence still a full-weight vote? | **OWNER DECISION REQUIRED** — no approved rule found in the authority hierarchy; inventing decay during an audit is forbidden (§15) |

