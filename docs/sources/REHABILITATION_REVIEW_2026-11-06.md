# Source rehabilitation review, 2026-11-06

**Status:** review record. Entries in `config/sources/rehabilitation.json` updated (evidence, `reviewBy`, one new entry). No source voting membership, weight, flag, hold or freshness rule changed. Promotion to voting stays owner-gated.
**Agent-OS-Receipt:** 47a8b19fff9d06da9b1a651aab5fb92f1e16d5f6

Evidence read from the repo at `origin/main`: `data/scrape_state/<key>_dataset.json`, `_last_success`, `_upstream.json`, `_last_status.json`, `git log` of `CSVs/site_raw/<key>.csv`, `docs/owner/OWNER_DECISION_REGISTER.md`, `docs/sources/*`. Collector last success for every key below was 2026-11-06 ~12:30Z.

## 1. Per-plan review

| Source | State before to after | Evidence | Next trigger | reviewBy |
|---|---|---|---|---|
| `signalsIdpDl` / `Lb` / `Db` | shadow to shadow | Hold per owner D7 (`ODR-SIGNALS-IDP`, 2026-10-18; held 2026-10-19). No committed preregistration of a different candidate on main. Signals output is box-local (`data/sources/signals` absent), so a newer release than `6ec7bff6bd11` cannot be observed from the repo. | next Signals IDP release or a committed preregistration (event-based) | 2026-10-31 to **2026-12-01** (heartbeat; no dated owner gate exists) |
| `dlfIdp` | policy_held to policy_held | Collection healthy: content changed 2026-11-05T02:27Z (177 rows). Hold retained by owner decision 2026-11-06 `ODR-SR-DLF-IDP` (recorded on branch `claude/coord-remediation-inventory-2026-11-06`, not yet on main). Outlier-filter V2 gate not fired. | outlier V2 passes all mandatory gates, then explicit owner approval | 2026-10-31 to **2026-12-01** |
| `dlfRookieIdp` | policy_held to policy_held | CSV committed 2026-11-03; same hold and gate as `dlfIdp`. | as `dlfIdp` | 2026-10-31 to **2026-12-01** |
| `fantasyProsIdp` | degraded to degraded | `fantasyProsIdp_upstream.json`: vendor `publishedAt` still 2026-09-04 (page label 9/04); 6 of 6 experts now (older note said 2 of 6, corrected). Our content clock moved 2026-10-23 but the explicit upstream clock correctly ignores it. About 1,520 h old, SEVERELY_STALE, down-weighted. | vendor expert update | 2026-10-31 to **2026-12-01** |
| `idpShowCombined` | upstream_inactive to upstream_inactive | Collector HEALTHY (665 rows, 2026-11-06T12:32Z). `idpShowCombined_upstream.json`: chart U8I37 still v4, lastModifiedAt 2026-08-19, so the v5 trigger has not fired. About 1,890 h old, QUARANTINED automatically. IDP-only `idpShow` also healthy (350 rows), still non-voting per `IDP_SOURCE_AUTHORITY_2026-10-28.md` and `IDP_SHOW_LIBRARY_AUDIT_2026-11-01.md`. | vendor publishes v5+ | 2026-11-01 to **2026-11-15** (same provider decision date as the `idpShow` entry) |
| `fantasyNavigatorSf` | degraded to degraded | Fetch healthy; content unchanged since 2026-10-10T16:03Z (770 rows); CSV last committed 2026-10-26. About 645 h old, QUARANTINED automatically, as the entry predicted. | next vendor snapshot | 2026-11-07 to **2026-12-01** |
| `idpTradeCalc` | NO ENTRY to **degraded** (new) | See section 2. | vendor pick refresh, about 2026-11-09 to 2026-12-02 | **2026-12-04** |

`reviewBy` choices: `idpShowCombined` and `idpTradeCalc` follow a real dated or measured cadence. The other plans gate on events (a vendor publish or an owner decision) with no dated trigger, so their new `reviewBy` is a one-month heartbeat and says so. The event itself re-triggers review sooner.

`idpShowCombined`'s 1,891 h age quoted in CI is consistent: 2026-08-19 to 2026-11-06 is about 79 days.

## 2. IDPTC pick-board finding (no config change to weighting)

**Observation.** CI warns that `idpTradeCalc` picks are byte-identical for 26 days (budget 14 d), data 640 h old, SEVERELY_STALE.

**Is it vendor-side?** Yes. The fetch is fresh: the same source's players subset changed on 2026-11-06T02:56Z, so the collector and parser work. The picks subset's broad change history in `idpTradeCalc_dataset.json` is 2026-04-25, 06-06, 07-06, 08-28, 10-10 (gaps of 42, 30, 53 and 43 days; 144 rows moved on 10-10). Twenty-six days since 10-10 is inside the vendor's own gap range. This is vendor batch cadence, not a seasonal shutdown and not a collector fault. The 14-day content-staleness budget is therefore stricter than this vendor's behaviour; it is observability only, so this finding leaves the budget unchanged and flags it for the owner if the warning noise matters.

**Is it down-weighted correctly, never zeroed?** Yes, by existing machinery:
- `config/sources/freshness_v1.json` gives `idpTradeCalc` a learned interval clamped to `maxHours` 240 (the CI line reads 135.8 h normal), so the picks age reads about x4.7 and freshness is about 0.13 (SEVERELY_STALE).
- `src/sources/freshness.py` quarantines only below `quarantineBelow` 0.02. 0.13 is above it, so picks keep a reduced non-zero weight.
- Freshness is a weight on a vote. A stale value is never replaced by 0 and no pick is dropped (missing is not zero; stale is not current). Pick provenance stays `direct_market_blend` with KTC Crowd/Trades as the other provider.

**Observation, not acted on.** The 240 h clamp makes a vendor that publishes picks every 30-53 days read as roughly 4-5x overdue permanently between batches. Whether to widen the picks cadence is a freshness-methodology change and is left to the owner.

New entry `idpTradeCalc` records state `degraded`, no recovery action on our side, review 2026-12-04 (latest expected refresh, 2026-10-10 + 53 d).
