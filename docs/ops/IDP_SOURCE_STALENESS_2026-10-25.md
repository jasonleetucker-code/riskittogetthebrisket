# IDP source staleness: evidence report (2026-10-25)

**Status:** evidence only. No threshold, weight, vote, flag or held source was changed.
**Question:** why do 352 of 1,107 rows on the committed board `exports/latest`
(`dynasty_data_2026-10-25.json`, board as-of `2026-10-25T12:03:37Z`) carry
`confidenceAxes.freshness == "low"`, which makes `/trade` withhold their values?

**Answer:** every voting IDP family except DraftSharks is past the confidence
freshness floor because **the vendors have not published new dynasty IDP opinions**.
Every collector is succeeding, and the clocks read what the vendors actually state.
There is no code, collector or configuration defect to fix here. The remaining levers
are vendor behaviour and owner-held IDP voters (DLF IDP, Signals IDP), and both are
outside this lane.

## 1. Reproduction

I rebuilt the contract from the committed raw payload with `build_api_data_contract`
on `origin/main` `a20de7020`. All 352 freshness-low rows are IDP: 132 DL, 115 DB,
105 LB. That is 352 of the 429 IDP rows.

A row's freshness axis counts a voting family as fresh only when its fetch is inside
`maxAgeHours` **and** its content-freshness factor is at least
`freshForConfidence = 0.5` (`config/sources/freshness_v1.json`; applied in
`data_contract._family_evidence_for_row`). The axis is HIGH only when at least 75% of
the voting families are fresh (`config/confidence/gate_v1.json`).

| stale voting families on the row | fresh voting families | rows |
|---|---|---|
| `idpTradeCalc` + `fantasyProsIdp` | `draftSharksIdp` | 242 |
| `idpTradeCalc` | none | 54 |
| `idpTradeCalc` | `draftSharksIdp` | 34 |
| `idpTradeCalc` + `fantasyProsIdp` | none | 20 |
| `fantasyProsIdp` | none | 2 |

IDP Trade Calculator is the stale family on **350 of the 352** rows. FantasyPros IDP
is stale on 264.

## 2. Per-source verdicts

| source (family) | last genuine content change | last successful fetch | budget / clock | factor on this board | verdict |
|---|---|---|---|---|---|
| `idpTradeCalc` (idpTradeCalc) | players: broad change **2026-10-10T20:25Z** (later changes are 1-row name churn on 10-14/15/16); picks: 2026-10-10 | 2026-10-25T12:03Z (fetch fresh) | row-level clock, E clamped to [48, 240] h | 0.42–0.46 (row age about 370 h) | **GENUINELY_STALE_VENDOR** |
| `fantasyProsIdp` (fantasyPros) | experts' newest update **2026-09-04T02:34Z** (vendor-stated); our CSV changed broadly on 2026-10-23 when FantasyPros moved from 2 included experts to 6 | 2026-10-25T16:50Z (fetch fresh) | `EXPLICIT_UPSTREAM_TIMESTAMP` under owner decision D5 (`fantasypros_idp_upstream_clock` ON) | 0.24 (about 1,233 h) | **GENUINELY_STALE_VENDOR** (clock read correctly) |
| `draftSharksIdp` (draftSharks) | 2026-10-24T05:09Z (broad) | 2026-10-25T12:06Z | row-level clock, E in [12, 96] h | 0.62 (about 31 h), counts as fresh | healthy, not a cause |
| `idpShowCombined` (idpShow) | Datawrapper `U8I37` v4, `lastModifiedAt` **2026-08-19** | 2026-10-25T20:32Z (box timer, success) | `EXPLICIT_UPSTREAM_TIMESTAMP` | 0.0, quarantined, does not vote | **GENUINELY_STALE_VENDOR** (non-voting, so not in the 352) |
| `dlfIdp` / `dlfRookieIdp` (dlf) | 2026-10-24 / 2026-10-18 | box timer, success at 2026-10-25T20:27Z | fresh (100%) | held from voting | not stale. **Owner hold** (`dlf_offense_only_vote`; outlier-filter V2). Out of scope |
| `signalsIdp{Dl,Lb,Db}` (fantasyCalc) | vendor `asOf` 2026-10-21T15:05Z (box journal) | box `dynasty-signals-values`, success at 2026-10-25T19:18Z | `not_provisioned` where the committed board is built (by design) | held (`PRIVATE_SOURCE_VOTE_HOLDS`, vote flags default OFF) | not a staleness defect. **Owner hold**. Out of scope |

### Evidence

**IDP Trade Calculator.** I fetched the public `https://idptradecalculator.com/` from
this machine on 2026-10-25. The page states **"Updated: 10/10/2026"**, which matches our
recorded broad change (`data/scrape_state/idpTradeCalc_dataset.json`, `rowChangedAt`:
569 player rows 2026-10-10, 229 rows 2026-10-09). The Scheduled Data Refresh runs are
all `success` (latest 40213486704). Issue #1065 (vendor content stale while acquisition
is healthy) still describes the situation. `check_source_health.py` reports
`content-stale: 0` for this source only because 1-row churn on 10-16 resets the 14-day
whole-dataset content budget. The row-level clock used for voting and confidence is
the stricter of the two, and it is correct.

**FantasyPros IDP.** I fetched the live `dynasty-idp.php` `ecrData` on 2026-10-25T20:48Z:
- `last_updated: "9/04"` and `last_updated_ts = 1788489264` (2026-09-04T02:34:24Z);
- all 6 experts are included;
- the per-expert `last_updated` values are 2026-09-04, 08-18, 07-19, 06-27, 06-07 and 06-05.

The newest expert opinion on the board is therefore from Sep 4. The 2026-10-23 broad
CSV change (`fantasyProsIdp_upstream.json`: `expertsIncluded` 2 → 6) re-blended older
opinions. No expert published anything new. `scripts/fetch_fantasypros_idp.py` has not
changed since 2026-10-17, so the change is on the vendor side, not in our collector.
The clock is the one the owner chose in D5 and it reads the vendor value correctly:
**not a misread.**

**IDP Show.** `https://datawrapper.dwcdn.net/U8I37/` serves v4, and v5 and v6 return
404. This is the same state recorded in `docs/sources/IDP_SHOW_RECOVERY_2026-10-17.md`
§2. The box timer `dynasty-idpshow-fetch` is healthy: `Result=success`, last commit
`a20de7020`, push succeeded, status `HEALTHY`, 665 rows. Collection is not the problem.

**Box inspection (read-only, 2026-10-25 about 21:50 CET).** I checked the
`dynasty-dlf-fetch`, `dynasty-idpshow-fetch` and `dynasty-signals-values` units: each
reports `Result=success` and `ExecMainStatus=0`, and its timer is scheduled. Box CSV
mtimes are current for `idpTradeCalc.csv`, `fantasyProsIdp.csv`, `draftSharksIdp.csv`,
`dlfIdp.csv` and `idpShow.csv`. `idpShowCombined.csv` was last modified 2026-08-21: the
fetch succeeds but the content is byte-identical, so it is not rewritten. One
cosmetic journal line repeats on each push:
`Identity file /home/dynasty/.ssh/github_deploy_key not accessible`. The push still
succeeds through another key, so it has no effect on freshness.

**Configuration.** The `freshness_v1.json` entries for these sources match the
documented, owner-approved state:
- `idpTradeCalc` [48, 240] h;
- `fantasyProsIdp` `EXPLICIT_UPSTREAM_TIMESTAMP` with `styleFlag` (D5);
- `draftSharksIdp` [12, 96] h;
- `idpShowCombined` `EXPLICIT_UPSTREAM_TIMESTAMP`.

`config/source_staleness.json` `contentStaleness` is `defaultDays: 14` with no per-source
override. Nothing is misconfigured relative to its recorded decision.

## 3. What would change the 352

None of these are actions for this lane.

1. **Vendor publication.** A new IDP Trade Calculator update would clear the stale
   family on 350 rows. By itself it lifts most rows only to 2 of 3 fresh, which is
   below the 75% HIGH line, because FantasyPros IDP would still be stale.
2. **Owner-held IDP voters.** DLF IDP is fresh today but held (outlier-filter V2 gate).
   Signals IDP is held behind its vote flags. Activating either one is an owner
   decision.
3. Freshness thresholds, `freshForConfidence`, the HIGH share line, and the v2 step
   schedule are owner-reserved. **Not touched.**

## 4. Result

STATUS: DONE (evidence report; no defect found, so no fix is in this PR)
UNRESOLVED:
- The production box builds its own board where Signals is provisioned. I did not
  measure the live `/api/data` freshness census, because that endpoint needs a login.
  The holds make Signals non-voting there too, so the cause should be the same.
- FantasyPros' 10-23 expert-panel re-inclusion is a borderline case: the content
  changed, but no expert published anything new. D5 treats it as not an update. That
  is recorded here for owner awareness, not reopened.
