# Sharp Roster Percentage — production activation

Everything for `/market/sharp-roster-percentage` is merged and tested.
What is **not** done is the part that can only happen on the box that
holds the data: the roster store starts empty, so the board reports
`cohort_building` and shows nothing until the crawl has run there.

Nothing here is a code change. Steps 1–5 are the activation; steps 6–7
are optional features that are inert by design until you supply an
input.

| Tag | Where |
|---|---|
| **[VPS]** | shell on the production box, as the app user |
| **[LOCAL]** | anywhere with a browser or a repo checkout |

Feature reference: `docs/sharp-roster-percentage/METHODOLOGY.md`.

---

## Why the board can't be finished from CI or a dev container

`GET /api/sharp/roster-percentage` reads `sharp_rosters` in
`data/intel/ledger.sqlite3` — a **local, gitignored** SQLite file on the
machine serving the API. The producer has to run where the reader lives.
Same reasoning as the BDVM and playerctx refresh timers.

---

## Starting state this runbook assumes

1. `main` is deployed (the feature merged via #710 and #723).
2. The Sharp Buy/Sell Tracker already works — i.e. `/api/sharp/cohort`
   reports `qualifiedManagers > 0`. **This board is downstream of the
   same cohort.** If the tracker is still "cohort building", this board
   will be honestly empty for exactly the same reason, and step 2 is
   where you find that out.

---

## 1. [VPS] Confirm the timer installed

`deploy.sh` runs `install-systemd-service.sh`, which installs
`dynasty-sharp-rosters.{service,timer}` when it is missing. It should
already be there after any deploy of `main`.

```bash
systemctl list-timers 'dynasty-sharp-rosters*'
systemctl cat dynasty-sharp-rosters.timer | head -20
```

**Checkpoint:** the timer exists and is scheduled for `05:50 UTC` daily.
If it is absent, re-run the installer:

```bash
cd /home/dynasty/trade-calculator
FORCE_SERVICE_INSTALL=false bash deploy/install-systemd-service.sh
```

---

## 2. [VPS] Confirm the cohort is non-empty

```bash
cd /home/dynasty/trade-calculator
source ~/.venvs/trade-calculator/bin/activate
python -c "from src.sharp import cohort; m,c = cohort.cohort_members(); print(len(m), c)"
```

**Checkpoint:** a non-zero count.

**If it is 0, stop here** — the roster crawl has nobody to collect for,
and an empty board is the correct output, not a bug. The fix is
upstream, in that order: `scripts/discover_sharp_graph.py` (finds
managers) → `scripts/crawl_sharp_records.py` (makes them scoreable).
Both have their own timers at 04:20 and 04:50 UTC.

---

## 3. [VPS] First roster crawl

```bash
python scripts/crawl_sharp_rosters.py --budget 3000
```

Costs 2 Sleeper calls per **league** (not per member, and not per
roster). Idempotent — re-running overwrites rather than inflating any
count, so it is safe to run repeatedly.

**Checkpoint:** `store.eligibleRosters > 0` in the JSON summary.

### Sizing `--budget`

Read `sleeper.leaguesRemaining` from the summary:

* `0` — the budget is keeping up. Leave the unit as shipped.
* stable non-zero across runs — raise `--budget` in
  `deploy/systemd/dynasty-sharp-rosters.service.template`. This is **not**
  something patience fixes on its own, though the crawl does rotate: it
  orders leagues never-collected-first, then oldest-first, so each run
  reaches leagues the last one did not.

Exit code `2` means "budget exhausted, work remaining" and is a normal
steady state on a large graph — the unit treats it as success.

---

## 4. [VPS] Run the audit against real data

This is the step that actually closes the audit requirement. Everything
verified pre-merge ran against a constructed fixture, plus one live
crawl of a graph grown fresh from the seeds — **never production's
accumulated cohort**.

```bash
python scripts/validate_sharp_roster_percentage.py --players 40
```

It re-derives every published number from the raw rows using code that
shares nothing with the engine, then diffs.

**Checkpoint:** all checks PASS, exit 0.

One check will fail on a bare run, by design:

```
[FAIL] contract_available_for_position_aware_checks
       NO CONTRACT — every position reads as unknown...
```

`latest_contract_data` is an in-process global of the running server, so
a standalone script cannot see it. Without positions, the **per-player
denominator** — the subtlest rule in the feature, the one that measures
a linebacker against IDP leagues only — is not exercised at all. To
audit it, pass a contract:

```bash
python scripts/validate_sharp_roster_percentage.py --players 40 --contract /path/to/contract.json
```

The file must contain `playersArray`. Note `exports/latest/dynasty_data_*.json`
is the **legacy** shape and will be rejected; build a real one with:

```python
import json
from src.api.data_contract import build_api_data_contract
raw = json.load(open("exports/latest/dynasty_data_<date>.json"))
json.dump(build_api_data_contract(raw), open("/tmp/contract.json", "w"))
```

**What "good" looks like** (from a real 12-roster / 6-manager run):

```
[PASS] denominator_matches_eligible_rosters   40/40 per-player denominators match
[PASS] counted_assets_resolve_to_a_known_player_identity   40/40 resolve
[PASS] board_coverage_of_rostered_players     36/40 priced; 4 unpriced
```

`board_coverage_of_rostered_players` is **informational**. Rostered
players outside our ranked pool (deep veterans, practice-squad bodies)
legitimately have no `rankDerivedValue`; they are reported as unpriced
rather than valued at zero.

---

## 5. Wait 24h, then confirm trends resolve

The 7d/30d/season columns read `n/a` until a **second** observation
exists — history is stored as spans, and one snapshot is not a trend.
This is why the timer is daily rather than weekly.

**Checkpoint:** after the second crawl, at least one row shows a
`thirtyDay` trend with `available: true`. Rows reading
`roster_population_changed` are correct when the cohort is still
growing — the delta is withheld rather than reporting cohort growth as
players gaining ownership.

### The number to watch afterwards

`transparency.rostersPerManager`. Sharps typically run several dynasty
teams, so a value near **1.0** means discovery has not reached their
other leagues yet — not that sharps own one team each. Coverage is
bounded by how far `discover_sharp_graph.py` has walked. It rises on its
own as the graph compounds.

---

## 6. [LOCAL] Optional — activate the FFPC half

FFPC contributes **zero rosters** today. The parser is correct and
test-pinned, and the collector already lifts roster contents with no
network calls; the gap is purely configuration. All ten seeds in
`config/sharp/ffpc_sources.json` are `LeagueHome.aspx` pages, which
yield transactions and standings but no roster table.

Add a roster-bearing URL for a configured league and the FFPC half
starts contributing on the next crawl. **No code change is needed.**

Caveat worth knowing: FFPC publishes no taxi/IR marking, so FFPC assets
are stored as `active`. That is the absence of a distinction, not a
claim that none are on taxi.

---

## 7. Optional — the sharp-vs-market columns

`marketRosterPct` and `sharpRosterAdvantage` are `null`, and two of the
six sort options rank nothing, because **no general-dynasty ownership
feed exists in this platform**. Every ranking source we ingest publishes
values or ranks; Sleeper's trending endpoint publishes 24-hour *add
counts* — a flow, not a stock. Converting one into the other would be
inventing the number, so the page says why instead.

To wire a real feed, register a provider:

```python
from src.sharp import roster_percentage
roster_percentage.set_market_ownership_provider(fn)  # ids -> {id: 0.0..1.0}
```

That is the whole integration; the board, the advantage column and both
sorts light up on their own.

---

## Known trap, unrelated to this feature

`tests/frontend/test_fixed_elements_have_a_vertical_anchor.py` does
`frontend.rglob("*.css")`, which sweeps in `frontend/.next/`. So **after
running `npm run build` locally, that suite fails** on hashed build
chunks with no defect behind it. `rm -rf frontend/.next` clears it.
CI never sees this (`.next` is gitignored and CI checks out clean).

Pre-existing, not caused by this feature, and worth fixing separately by
excluding build output from that glob.
