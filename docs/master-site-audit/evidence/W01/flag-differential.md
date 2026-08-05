# W01 — Feature-flag reachability, tested at runtime

`src/api/feature_flags.py` ships a self-documenting `_GATE_STATUS` table
classifying each of its **15** registered flags as `LIVE`, `SCRIPT_ONLY`,
`UNREACHABLE` or `NO_GATE`. It claims **7 of 15 cannot affect a request**.

That is a claim about the running server, so I tested it against a running
server rather than re-reading the import graph.

## Method

A second FastAPI process was booted on **port 8001** using the same
scrape-neutralised launcher pattern as the audit harness
(`scratchpad/w01_launcher.py` — `server.run_scraper` replaced before
uvicorn starts, so nothing is scraped and no `data/` file is rewritten).
**Port 8000 was never touched.** Nothing outside
`docs/master-site-audit/` and the scratchpad was written.

Four boots:

| boot | env | purpose |
|---|---|---|
| **A** | defaults | baseline |
| **B** | all **7** claimed-inert flags forced ON | the test |
| **C** | defaults, second cold boot | control for boot-state drift |
| **TE** | `RISKIT_FEATURE_TE_BASIS_CONVERSION=0` | positive control |

25 endpoints were captured per boot (`flag-probe-index.txt`). A
same-process double capture established the **noise floor**: the only
fields that move between two identical requests are `generatedAt`,
`checkedAt`, `asOf`, `ageHours`, `cacheHit` and the live Sleeper trending
news items.

## Result 1 — the 7 inert flags are inert. Claim CONFIRMED.

Boot A (defaults) vs boot B (`espn_injury_feed`, `usage_signals`,
`depth_chart_validation`, `value_confidence_intervals`,
`positional_tiers`, `unified_id_mapper`, `dynamic_source_weights` all
`=1`):

```
rows compared                                        1092
rows with a changed rankDerivedValue                    0
rows with a changed canonicalConsensusRank              0
new fields appearing in playersArray                    0
fields disappearing from playersArray                   0
```

Artifact: `flag-differential-rankvalues.json`.

The only non-timestamp difference across the whole 12 MB `view=full`
contract was `players.*.rankChange` (621 non-zero → 0). Boot **C**
(defaults again) reproduces the same 0, which proves `rankChange` is a
function of how many rank-history snapshots the process has accumulated
since boot, **not** of any flag.

`/api/status` does differ between A and B — because it reports
`effective_flags()`, which includes the flipped values. That is the flag
being *reported*, not the flag *doing* anything, and the payload carries
`gateStatus` beside `enabled`, so the endpoint is honest about the
distinction.

The repo's own static measurement agrees:
`tests/api/test_feature_flag_reachability.py` — 36 passed in 44.7 s on
`.venv` Python 3.11.15. Independently confirmed by importing `server` and
observing that **no `src.nfl_data.*` and no `src.news.usage_signals`
module is in `sys.modules`** after import.

## Result 2 — all 8 LIVE flags demonstrably change a response

| flag | proof | observed |
|---|---|---|
| `consensus_edge` | `GET /api/consensus-edge/top` | **503 `feature_disabled` → 200** with a real 325-player board (`playersScored: 325`, `modelVersion ce.2026-08-04.v0-shadow`) |
| `bdvm_engine` | `GET /api/bdvm/values`, `/api/bdvm/roster` | **200 → 503 `feature_disabled`** |
| `realized_points_api` | `GET /api/player/4046/realized` | **200 → 503 `feature_disabled`** |
| `monte_carlo_trade` | `POST /api/trade/simulate-mc` | **200 → 503 `feature_disabled`** |
| `te_basis_conversion` | `GET /api/data?view=full` | **135 of 1092 rows change `rankDerivedValue`** (82 TE + 50 PICK + 3 collateral); 627 rows change `canonicalConsensusRank`. Pat Freiermuth 2484 → 2091 (−15.8 %). Artifact `te-basis-flag-effect.json`. |
| `idp_scoring_fit` | `GET /api/valuation/league-adjusted` | **293 of 709 factors change** (Aidan Hutchinson 1.09776 → 1.05343; Alex Anzalone 0.979705 → 1.019694) |
| `reception_scoring_fit` | same call, flipped together | same 293-factor delta (the two axes are disjoint by position, both reach `build_board_adjustments`) |
| `nfl_data_ingest` | static | `server.py:4424` and `:11241` lazily `from src.nfl_data import ingest`; gate is inside `src/nfl_data/ingest.py`. Reachable, but its effect is unobservable in this container because `nfl_data_py` is deliberately absent and nflverse egress is blocked — *pre-declared non-finding*. |

## One stale detail, not a defect

The docstrings in `feature_flags.py` and
`tests/api/test_feature_flag_reachability.py` both say "of **13**
registered flags, 7 could not affect a request". `_DEFAULTS` now holds
**15**. The ratio 7/15 is still correct and the per-flag classification
is current — only the total in the prose is stale.

## Reproduction

```bash
# port 8000 is left alone throughout
SP=<scratchpad>
$SP/w01_boot.sh $SP/def.log                       # boot A/C: defaults
$SP/w01_flagprobe.sh 8001 $SP/flagA
$SP/w01_kill.sh
$SP/w01_boot.sh $SP/flip.log \
  RISKIT_FEATURE_ESPN_INJURY_FEED=1 RISKIT_FEATURE_USAGE_SIGNALS=1 \
  RISKIT_FEATURE_DEPTH_CHART_VALIDATION=1 RISKIT_FEATURE_VALUE_CONFIDENCE_INTERVALS=1 \
  RISKIT_FEATURE_POSITIONAL_TIERS=1 RISKIT_FEATURE_UNIFIED_ID_MAPPER=1 \
  RISKIT_FEATURE_DYNAMIC_SOURCE_WEIGHTS=1
$SP/w01_flagprobe.sh 8001 $SP/flagB
# then diff playersArray (displayName, rankDerivedValue, canonicalConsensusRank)
```
