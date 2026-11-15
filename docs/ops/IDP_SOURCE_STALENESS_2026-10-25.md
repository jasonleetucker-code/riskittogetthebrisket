# IDP source staleness: why 352 rows are freshness-low (2026-10-25)

**Status:** evidence report plus one collector fix. No freshness threshold, weight, vote,
`source_freshness_schedule_v2` or held source flag was changed.
**Agent-OS-Receipt:** cb64f74cf4d2763aa16d55ba0d6350f585a2a42f

## 1. Answer

On the served board (`exports/archive/dynasty_export_20261025_120337.zip`, as-of
`2026-10-25T12:03:37Z`) 352 of 1,107 rows have `confidenceAxes.freshness == "low"`.
All 352 are IDP (132 DL, 115 DB, 105 LB), out of 429 IDP rows (32 of those carry no
evidence at all). The cause on that board is **vendor staleness**, in three places:

* IDP Trade Calculator has not published since 2026-10-10.
* FantasyPros IDP's experts last updated on 2026-09-04.
* The IDP Show's voting (combined) chart has not changed since 2026-08-19. It is
  withheld, and a withheld family still counts against every share axis.

Every collector that feeds those three was succeeding when the board was built, and every
clock reads what the vendor states. **There is no clock misread and no configuration
error behind the 352.**

A different, genuine **collector defect** started 4h45m after that board: the Scheduled
Data Refresh stopped running every browser-driven fetcher (KTC, IDP Trade Calculator,
DraftSharks) because the floating `ubuntu-latest` label moved to Ubuntu 26.04. It does
not explain the 352, but it is why nothing can recover, and it freezes the one IDP
family that is still fresh (section 5). This branch fixes it.

## 2. Reproduction and attribution

Rebuilt with `build_api_data_contract` from the archived raw payload (the freshness clock
is the payload's own `scrapeTimestamp`, never the wall clock), on `origin/main`
`c11c6d911`. The rebuild reproduces **352** exactly. For every low row I took the gate's
own numbers from `confidenceReasons` (families `n`, stale `s`, withheld seats `w`); the
axis is `fresh / (n + w)` and is LOW below 0.5. The stale set derived from
`sourceRankMeta[*].freshness < 0.5` agrees with the gate on all 352 rows.

| stale voting families | withheld seat | fresh families | rows |
|---|---|---|---|
| IDP Trade Calculator + FantasyPros | The IDP Show | DraftSharks | 222 |
| IDP Trade Calculator + FantasyPros | none | DraftSharks | 20 |
| IDP Trade Calculator | The IDP Show | DraftSharks | 34 |
| IDP Trade Calculator | The IDP Show | none (n=1) | 28 |
| IDP Trade Calculator | none | none (n=1) | 26 |
| IDP Trade Calculator + FantasyPros | The IDP Show | none (n=2) | 15 |
| IDP Trade Calculator + FantasyPros | none | none (n=2) | 5 |
| FantasyPros | none | none (n=1) | 2 |

Rows by stale source: IDP Trade Calculator **350**, FantasyPros IDP **264**, The IDP Show
seat **301**.

Analysis only (what the arithmetic would give, not a proposal), rows leaving LOW if:

| hypothetical | rows leaving LOW (of 352) |
|---|---|
| IDP Trade Calculator were fresh | 335 |
| FantasyPros IDP were fresh | 249 |
| both were fresh | 352 |
| The IDP Show seat were absent (nothing else changed) | 34 |

The IDP Show seat is real but is not the main driver. The unmerged report on
`claude/idp-source-staleness` said the IDP Show was "non-voting, so not in the 352".
That is wrong: a withheld family is seated in the denominator (owner directive
2026-10-07, "losing evidence never raises confidence"), which is why 301 of the 352 rows
carry the reason line `1 observed family did not reach the value ... idpShow`.

## 3. Per-source verdicts

"Budget" is the cadence curve in `config/sources/freshness_v1.json`; a family counts as
fresh for confidence only at factor >= `freshForConfidence` (0.5).

| source | last genuine content change | last successful fetch (stamp at repo HEAD, 2026-10-26) | budget / clock / factor on this board | verdict |
|---|---|---|---|---|
| `idpTradeCalc` | players: 2026-10-10T20:25Z (broad); later 1-row name churn only (10-14/15/16). Picks: 2026-10-10T20:25Z | 2026-10-25T12:03Z (see section 5) | row-level clock, E = 127.9 h learned (clamp 48-240 h); age 351.6 h (rows 370 h); factor 0.4626 (rows 0.424) | **GENUINELY_STALE_VENDOR** |
| `fantasyProsIdp` | experts' newest update 2026-09-04T02:34Z (vendor-stated) | 2026-10-26T00:44Z (HTTP fetch, healthy) | `EXPLICIT_UPSTREAM_TIMESTAMP` (owner D5), E = 325.5 h; age 1,233.5 h; factor 0.2408 | **GENUINELY_STALE_VENDOR** (clock read correctly) |
| `idpShowCombined` (voting board) | Datawrapper `U8I37` v4 `lastModifiedAt` 2026-08-19T17:50Z; post last updated 2026-06-22 | 2026-10-26T02:32Z (box timer, every 2 h) | `EXPLICIT_UPSTREAM_TIMESTAMP`, E = 168 h; age 1,602 h; factor 0.0, QUARANTINED, 0 voting rows, 655 rows seated | **GENUINELY_STALE_VENDOR** |
| `fantasyNavigatorSf` (offense only) | feed `_insert_date` 2026-10-09 (observed 2026-10-10T16:03Z) | 2026-10-26T00:44Z | row clock, E = 25.9 h; age 356 h; factor 0.0, QUARANTINED, 443 offense rows seated | **GENUINELY_STALE_VENDOR** |
| `draftSharksIdp` | 2026-10-24T05:09Z (broad) | **2026-10-25T12:06Z, then none** | E = 13.8 h; age 30.9 h; factor 0.624; counts as fresh | healthy on this board, **then COLLECTOR_BROKEN** (section 5) |
| `dlfIdp`, `dlfRookieIdp` | 2026-10-24 / 2026-10-18 | box timer, success | fresh, held from voting (`dlf_offense_only_vote`, outlier-filter V2) | not stale. Owner hold. Out of scope |
| `signalsIdp{Dl,Lb,Db}` | vendor `asOf` 2026-10-21 (box) | box `dynasty-signals-values` success | `not_provisioned` where this board is built; vote flags default OFF | not stale. Owner hold. Out of scope |

### Evidence

**IDP Trade Calculator.** Fetched `https://idptradecalculator.com/` on 2026-10-26: the page
carries a static `Updated: 10/10/2026`. I then pulled the public Apps Script feed behind
`script.js` and compared it with the committed `CSVs/site_raw/idpTradeCalc.csv` on
`value_sftep`: Sheet2 (picks) 48/48 identical, Sheet3 462/462 identical, Sheet1 354/355
identical. The single difference is a name collision (a Browns LB named Justin Jefferson
at 790, against the WR at 7,638 in the CSV), not drift. The vendor's current data **is**
our CSV. Dataset state: broad changes through 2026-10-10T20:25Z, then only 1-row name
churn. The learned cadence is a p75 over a bursty in-season sample (gaps 4.7 h to 281.5 h
inside 120 days), so the factor crosses the 0.5 floor at 2.618 x 127.9 h = 335 h, which
is about 2026-10-24. That is how a board that was fine on 10-23 became 352 rows on 10-25.

**FantasyPros IDP.** Fetched all four pages the collector reads (`dynasty-idp`, `-dl`,
`-lb`, `-db`) on 2026-10-26 and extracted `ecrData` with the collector's own extractor:
every page states `last_updated_ts = 1788489264` (2026-09-04T02:34:24Z), 6 of 6 experts
included. The six per-expert `last_updated` values in the page are 2026-06-05, 06-07,
06-27, 07-19, 08-18 and 09-04, so the page timestamp is the maximum and is correct. The
broad content change on 2026-10-23 (`expertsIncluded` 2 to 6) re-blended older opinions;
under D5 that is not an update. The clock reads the vendor value correctly.

**The IDP Show.** `datawrapper.dwcdn.net/U8I37/4/`: `lastModifiedAt` 2026-08-19T17:50:16Z,
`publishedAt` 2026-07-15; v5, v6 and v7 return 404. The public Substack API shows the
combined post last updated 2026-06-22. Box journal (read-only, 2026-10-26 03:32 CET):
`combined post embeds 2 chart(s): ['gNM2r', 'U8I37']`, widest chosen is `U8I37` v4 with
665 rows, metadata matches the above, push succeeded. `idpShowCombined.csv` on the box
is dated 2026-08-21 because the content is byte-identical and git does not rewrite it;
fetch freshness uses the `_last_success` stamp, so that mtime is not read as a fetch time.
The unit reports `Result=success`, `ExecMainStatus=0`; the cosmetic
`Identity file ... github_deploy_key not accessible` line does not stop the push.

**Fantasy Navigator.** `https://fantasy-navigator-latest.onrender.com/ranks?platform=sf`
(the collector's endpoint): newest `_insert_date` is 2026-10-09 (794 rows). Parsed with
the collector's own `_parse_players`, the live feed is 770 rows with **0 value
differences** from the committed CSV. The 2026-10-21 CSV commit only added the
`position,team` columns.

**Box (read-only).** `systemctl list-timers` shows `dynasty-dlf-fetch`,
`dynasty-idpshow-fetch` and `dynasty-signals-values` scheduled and firing on time (last
runs 03:27, 03:32 and 02:22 CET on 2026-10-26). I read the result of
`dynasty-idpshow-fetch` only: `Result=success`, `ExecMainStatus=0`. The FantasyPros,
Fantasy Navigator, IDP Trade Calculator and DraftSharks CSVs reach the box through
GitHub's Scheduled Data Refresh, not a box timer.

## 4. Things I checked and ruled out

* **Fetch time used as data time:** `_build_source_timestamps` prefers the
  `_last_success` stamp for fetch budgets, and content freshness comes from
  `data/scrape_state/*_dataset.json`, a separate clock. Neither is read as the other.
* **Upstream date parsed wrong:** FantasyPros (max of experts), Datawrapper
  (`lastModifiedAt`) and Fantasy Navigator (`_insert_date` vs observed change within a
  day) all agree with the vendor's own value.
* **Cadence or budget wrong for the vendor:** the entries match the recorded decisions
  (`idpTradeCalc` [48, 240] h, `fantasyProsIdp` D5, `draftSharksIdp` [12, 96] h,
  `idpShowCombined` upstream clock). `contentStaleness.defaultDays` is 14 with no
  override. Not touched.
* **`python scripts/check_source_health.py`:** contract source-health errors 0, fetch
  25 fresh / 0 stale, registered integrity 27 healthy; it warns on `idpShowCombined`,
  `fantasyNavigatorSf` and `fantasyProsIdp`. Its `content-stale: 0` is a weak signal: it
  measures byte-identity of the raw CSV, and the 2026-10-21 header rewrite plus the 1-row
  IDPTC churn reset that clock. The dataset-state clock, which is the one that votes,
  ignores both.

## 5. The collector defect (fixed in this branch)

**COLLECTOR_BROKEN: Scheduled Data Refresh browser fetchers, since 2026-10-25T16:49Z.**

| run | started (UTC) | runner image | Playwright chromium | browser sources stamped |
|---|---|---|---|---|
| 40191188142 | 10-25 11:59 | ubuntu-24.04 | installs, scrape works | yes, 12:03-12:06Z |
| 40213486704 | 10-25 16:49 | **ubuntu-26.04** | `ERROR: Playwright does not support chromium on ubuntu26.04-x64`; `BrowserType.launch: Executable doesn't exist` | **no** |
| 40234530064 | 10-25 21:14 | ubuntu-26.04 | same | no |
| 40250698149 | 10-26 00:43 | ubuntu-26.04 | same | no |

* `runs-on: ubuntu-latest` floated to 26.04. The locked Playwright (1.58.0) cannot
  install Chromium there.
* `python -m playwright install chromium 2>/dev/null || true` hid the install error. The
  scraper, DraftSharks and DraftSharks ROS then failed to launch a browser, the
  orchestrator restored last-good CSVs and (correctly) declined to stamp them
  (`Restored last-good board; NOT stamping ... _last_success`), and every run finished green.
* Effect, measured: `ktc`, `ktcSfTep`, `ktcCrowdSfTep`, `ktcTradesSfTep`,
  `ktcCrowdTradesSfTep`, `idpTradeCalc` last stamp 2026-10-25T12:03:37Z;
  `draftSharks` / `draftSharksIdp` 12:06:15Z. Nothing since. The HTTP-only fetchers
  (FantasyPros, Fantasy Navigator, DynastyDaddy, FantasyCalc, OTC, PFK, Yahoo) kept
  stamping. `exports/latest` last changed in commit `40f5dc569` at 12:07:01Z.
* Consequence for IDP: `draftSharksIdp` is the only fresh voting family on 276 of the
  352 rows and on all 45 non-low priced IDP rows (11 high, 34 medium). With no new scrape its content
  freshness falls below 0.5 about 36 h after its last change (2026-10-25T17:15Z); at a
  2026-10-26T03:00Z clock it is 0.327. Rebuilding the same payload with only that clock
  advanced gives freshness-low on **all 397 priced IDP rows** (from 352). That is an
  analysis of the arithmetic, not a served figure: the served board's own clock is its
  payload timestamp and the payload has not been re-exported.
* The staleness watchdog is not red yet because its fetch budget is 24 h (config
  `thresholds`); I expect it to start failing once those stamps pass 24 h, about
  2026-10-26T12:00Z. That is an inference from the config, not an observation.

**Fix (smallest, reversible):** pin the refresh job to `ubuntu-24.04` and make the
Chromium install failure loud but still non-fatal (`if ! python -m playwright install
chromium; then echo "::warning ..."; fi`, stderr kept). Pinned by
`tests/deploy/test_scheduled_refresh_playwright_runner.py`:

* the job's `runs-on` must not float and must be in an allowlist of images the locked
  Playwright supports (`ubuntu-22.04`, `ubuntu-24.04`);
* the install must not use `2>/dev/null` or `|| true`;
* behaviour, with a stub `python`: a failed install exits 0 and prints the
  `::warning title=Playwright chromium install failed::` annotation; a successful install
  prints no warning.

The two structural tests were run against the original workflow text and fail there as
expected.

**Not changed, named for follow-up:** other workflows run Playwright on `ubuntu-latest`
(`e2e.yml`, `prod-e2e-smoke.yml`, `v1-authenticated-verification.yml`,
`draftsharks-diagnostic.yml`). I did not examine or change them. Issue #1485 tracks a
Playwright bump that needs box-side verification; that, not this pin, is the long-term
route off 24.04.

## 6. Owner-level observations (no change made)

1. **IDP Show voting board versus its maintained board.** The vendor republished the
   IDP-only dynasty post on 2026-10-08 and our non-voting `idpShow.csv` changed on
   2026-10-17 (350 rows). The combined board, which is the family's only voter by the
   2026-08-20 decision, has not been republished since 2026-06-22. Switching the
   voting board is a voting change with its own gates (coverage, identity, lineage, owner
   approval; see `docs/sources/IDP_SHOW_RECOVERY_2026-10-17.md` section 3).
2. **IDP Trade Calculator's learned cadence** (127.9 h) comes from a burst of intra-day
   changes. At the `maxHours` clamp (240 h) the same 370 h age would give factor 0.88.
   That is the thresholds question reserved to the owner.
3. `acknowledgedFetchOutages.idpShowCombined` expired on 2026-10-23. The fetch is healthy
   now, so nothing depends on it.
4. DLF IDP (fresh) and Signals IDP are held; activating either is an owner decision and
   would add a fresh family to these rows.

## 7. Result

STATUS: DONE (diagnosis complete; collector fix implemented, not yet observed in production)
ACCEPTANCE: per-source verdicts with evidence and affected row counts; smallest fix plus
tests for a genuine collector defect; no change to thresholds, weights, voting, schedule
v2 or held flags.
EVIDENCE: board rebuild (352 reproduced); live vendor feeds and pages fetched 2026-10-26;
read-only box checks; four Scheduled Data Refresh run logs; `check_source_health.py`;
new tests pass, and fail on the original workflow.
UNRESOLVED:
* The fix has not run on GitHub. The proof is the first Scheduled Data Refresh after merge
  showing `ubuntu-24.04` and advancing `idpTradeCalc`, `draftSharksIdp` and `ktc*`
  `_last_success` stamps.
* The production `/api/data` freshness census was not measured (login-only). The rebuild
  matches the user-supplied 352.
* Other Playwright workflows on `ubuntu-latest` were not examined.
BLOCKERS: none.
NEXT_ACTION: merge the pin, dispatch Scheduled Data Refresh once, confirm the stamps.
