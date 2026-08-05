# Historical Data Gaps

*Master site audit, deliverable section 11. Sources: W19 (public league), W04 (historical
snapshots and backtesting), W17 (ROS vintage). Every number below traces to a finding id in
`docs/master-site-audit/findings.json` or to a file under `docs/master-site-audit/evidence/`.
Priorities quoted are the **published** (post-verification) ones; where a verifier rescoped or
overturned an author's claim, that is stated inline.*

---

## The headline

**The platform holds three seasons of league history and zero history of its own board.**

Those are two different problems with two different fixes.

1. **League history** (Sleeper-derived: matchups, rosters, transactions, drafts) is real,
   week-level, and verifies against Sleeper to the hundredth of a point (W19-F010). Its gaps are
   *filters and labels* — a hardcoded exclusion list, hardcoded copy strings, and awards
   manufactured from an unplayed season — not missing data. Most of it is fixable in code with
   the data already on hand.
2. **Model history** does not exist at all. No archived export contains `rankDerivedValue`,
   `canonicalConsensusRank`, `confidenceBucket` or `sourceRanks` — 0 of 129 archives
   (W04-F009). There is therefore **no record anywhere of any board this site ever served**, and
   every "historical" backtest in `reports/` reconstructs a board by blending *today's* source
   CSVs into a weeks-old payload. That is not a labelling problem; it is a class of evidence the
   repo does not possess.

---

## 1. What history the platform actually holds

| Store | Span held | Depth | Finding |
|---|---|---|---|
| Sleeper league chain (`src/public_league/snapshot.py`) | 2024, 2025, 2026 | week-level matchups, starters, `players_points`, rosters, transactions, drafts | W19-F017 |
| `exports/archive/*.zip` | 2026-07-14 → 2026-08-04, 129 snapshots | raw scraper composite only; **3 of 21 source CSVs** bundled (`ktc`, `ktcSfTep`, `idpTradeCalc`) | W04-F006, W04-F009 |
| `CSVs/site_raw/*.csv` | **today only** — rewritten in place by every scrape | 21 sources, no history | W04-F006 |
| `data/raw/` | frozen 2026-04-03 → 04-08 | 22 sources; no directory at all for `otcffb`, `pfkDynasty`, `fantasyNavigator` | W04-F006 |
| `config/model_registry/hill_scope_masters.json` | v1, v2 (champion), v3 (rejected 2026-08-04) | params + a recorded criterion, **not** the bytes it was scored on | W04-F006, W04-F015 |
| `data/ros/aggregate/history` | 2026-04-28 → 2026-08-04, 98 days | 796 files, 857 MB, all tracked in git | W17-F013 |
| `exports/narratives/` | one file pair: 2025 week 17, matchup 1 | 2 files total | W19-F014 |

Re-run the export inventory: `ls exports/archive/*.zip | wc -l` → 129;
`ls data/ros/aggregate/history | wc -l && du -sh data/ros/aggregate/history` → 796 / 857M
(both re-confirmed at audit time).

### What is genuinely solid

- **Week-level ownership join exists and is used.** Records, awards and the player-journey page
  all attribute points via that week's `starters` / `players_points` and that week's `roster_id`
   — not current roster membership. All 8 positional player records match Sleeper to 0.01;
  `/league/player/6794` renders a real ownership arc (Jason → MaKayla → Brent). *(W19-F010,
  Implemented and verified.)* This is the hard part of historical attribution and it is right.
- **Trade grading arithmetic reproduces exactly.** The prior audit's `alpha=1.65` threshold
  mismatch is gone from the tree; recomputed grades are byte-identical to served grades
  (pctGap −27.866 / +27.866). *(W19-F009, Implemented and verified.)*
- **Every one of the 21 `/league` tabs and all 10 dynamic deep-link routes render real content**,
  and every miss path degrades with a specific honest message rather than a 404 or a blank
  ("No recap for 2026 week 1 — the week may not be scored yet"). *(W19-F015.)*
- **ROS aggregate freshness is fine and is reported honestly.** `data/ros/aggregate/latest.json`
  was 4.9 h old against the 2026-08-04 board, all 5 sources `ok`, and `/tools/ros-data-health`
  says so. The prior audit's staleness claim does not reproduce. *(W17-F004 — an explicit
  refutation of PRIOR-A19-F06 at the aggregate level.)*
- **The best-ball lineup optimizer is exact**, not greedy-correct-by-accident: 360 randomized
  brute-force trials across three slot sets including non-laminar ones, zero deviations; all 12
  live lineups legal. *(W17-F006.)*

---

## 2. What the surfaces claim vs what is behind them

### 2.1 Two of ten 2024 franchises are erased from every "all-time" aggregate

`src/public_league/identity.py:31-35` asserts that retiring an owner is cosmetic — "no historical
rewrite is required". It is not cosmetic. Two retired owner ids held rosters 9 and 10 of the
10-roster 2024 league; `metrics.resolve_owner` returns `''` for them and every section does
`if not owner_id: continue`.

**Verified position (W19-F001, authored P0 → verified P1, rescoped):** the verifier could not
kill any part of the mechanism but corrected two of the author's numbers. The erasure is
**29 of 150 scored 2024 roster-weeks**, not the authored 34 of 170. 5 of 10 record categories
change when `_RETIRED_OWNER_IDS` is emptied; **3 change at rank #1**, each with the wrong holder:

| Published on `/league?tab=records` | Correct with the two franchises restored |
|---|---|
| lowest single week 177.25 | 164.79 |
| narrowest victory 1.25 | 0.77 |
| fewest points in a win 241.23 | 236.61 |

2025 and 2026 erase nothing (0 unresolved roster-weeks). The blast radius is 5 routes / 4 pages,
confined to the 2024 season and the all-time aggregates that span it.
Re-run: `.venv/bin/python` rebuild of the snapshot with `identity._RETIRED_OWNER_IDS =
frozenset()`, archived at `evidence/W19/retired-owner-diff-full.json`.

The payload-level signature is independently checkable with no Sleeper call: 2024 carries
`numTeams: 10` beside exactly **8** standings rows, and the History tab renders the 8-row table
with no caveat (W19-F002, P1). Re-confirmed at audit time:

```
curl -s http://127.0.0.1:8000/api/public/league/history | \
  .venv/bin/python -c "import json,sys;[print(s['season'],s['numTeams'],len(s['standings'])) for s in json.load(sys.stdin)['data']['seasons']]"
→ 2026 12 12 · 2025 10 10 · 2024 10 8
```

### 2.2 "All-time" is a rolling 3-season window that is true only by coincidence

`build_public_snapshot` walks the Sleeper `previous_league_id` chain capped at
`PUBLIC_MAX_SEASONS = 3`. The chain currently terminates on its own (the 2024 league returns
`previous_league_id '0'`), so window length 3 == league lifetime 3 and "all-time" happens to be
true. **Headroom is zero.** When the 2027 league is created the walk drops 2024 silently, every
"all-time" string becomes false, and no code, label or test will notice. There is no
`windowIsCompleteHistory` flag on the payload. *(W19-F017, P2.)*

### 2.3 Awards are manufactured from a season with zero scored games

The 2026 block (`weeksPlayed = 0`, Sleeper `last_scored_leg = null`) still emits **8 awards**,
every one with zero-valued evidence: "Points King: Jason, 0.0 PF", "Regular-Season Crown: Jason,
0-0", "League MVP: Justin Jefferson, 0.0 VORP". Six of eight go to Jason purely because the
all-zero sort has no tiebreak. The block stamps `hasPlayerScoring: true`, which is false in
substance. `awards.jsx:273` builds `historyByKey` with no `isComplete` filter, so the rendered
badges read "POINTS KING **3 yrs**" against "CHAMPION **2 yrs**" — the league has had exactly two
completed seasons. *(W19-F004, P1.)* Re-confirmed at audit time: `seasonStatus in_season`,
`hasPlayerScoring True`, 8 awards emitted.

### 2.4 Public playoff odds are binary for an unplayed season

With `weeksPlayed: 0`, seven owners get `playoffProbability` exactly 1.0 and five exactly 0.0 for
7 spots — `playoff_odds.py:639-642` substitutes a one-element pool `[100.0]` for owners with no
scored weeks, and `rng.choice` over one element is a point mass. `numSims` still reads 10000 and
nothing marks the owners unsimulated. An uninformative prior would be 7/12 = 0.583. The card is
currently shadowed by the `useRosPowerRankings` default but is one `/settings` click away.
*(W19-F008, P2.)*

### 2.5 The coverage window is mislabelled on six surfaces

Six hardcoded copy strings say "the last 2 seasons" / "2-season window" while the live window is
3 and the page header on the same screen says "Last 3 dynasty seasons". The Trades tab renders
"191 completed trades across the last 2 seasons" — the 191 are 2024:29 + 2025:124 + 2026:38.
Eight Python docstrings carry the same stale figure. *(W19-F005, P2.)*

### 2.6 Superlatives mixes a today-snapshot with 3-season counts under a 2-season caption

`_roster_composition` reads `snapshot.current_season.rosters` and nothing else — every
qb/rb/wr/te/idp/rookie/rosterSize number is a point-in-time snapshot of today's 2026 rosters
(winner's rosterSize 58 == live Sleeper 58). The *same card* prints trades:14 / waivers:32, which
are genuine 3-season aggregates. Three different time bases, one caption, none of them matching
it. *(W19-F006, P2.)*

### 2.7 The media surface is one eight-month-old article pair

`find exports/narratives -type f` returns exactly 2 files (2025 week 17, matchup 1). Both the
Previews and Recaps tabs render them under present-tense copy with no staleness note and — this
is the sharper half — **no AI attribution on the tabs at all**. The deeper
`/league/articles/[season]/[week]` pages do attribute to Claude and stamp the model id; the two
most-visited entry points do not. Status: **Blocked by data** — the generator exists, the content
does not. *(W19-F014, P2.)*

### 2.8 ROS simulations run on the wrong season entirely

Not a missing-history problem — a *history-selection* bug, and the most damaging item in this
document. `_season_sort_key(season: str)` is handed a `SeasonSnapshot` **object** at all four ROS
call sites, `int()` raises `TypeError` inside the try/except, every season sorts equal, and
`sorted(...)[-1]` returns the **oldest** season of a newest-first list. The live sims therefore
run on **2024** (status `complete`, 8 owners). The whole 2025 season is loaded and ignored. Every
other module in the repo passes `s.season` correctly. *(W17-F001, P0, one-line fix at four
sites.)*

The user-visible consequence: on `/league?tab=rosTradeDeadline`, four managers who joined after
2024 are absent from the sim, and absence is coerced to a confident `0.0` playoff odds.
`classify_team` never reads `team_ros_strength_percentile` for the label. Brent — ranked **1 of
12**, strength percentile 100% — is rendered in the DOM as *"Seller — Sell aging win-now players.
Prioritize 2026/2027 picks and 23-or-younger upside."* *(W17-F002, P0.)*

**Both W17-F001 and W17-F002 are unverified**: no adversarial verifier verdict exists for either
(`evidence/verify/verdicts-B*.jsonl` covers 24 findings; these two are not among them). They
carry `confidence: high` from their author with a reproduction command and a rendered-DOM
artifact, but they have not been through the second pass that rescoped W19-F001 and overturned
W04-F001. Treat the P0 as authored, not adjudicated.

---

## 3. Backfillable, commissioner-entry, or unreconstructable

### 3.1 Backfillable from sources the platform already has

| Gap | Source | Finding |
|---|---|---|
| 2 erased 2024 franchises across records / history / streaks / luck | Sleeper archives already loaded — the rows are in the snapshot and thrown away at resolve time | W19-F001, W19-F002 |
| Multi-season roster composition for Superlatives | week-level `players` list on matchup entries, exactly as `player_journey._scoring_summary` already reads it | W19-F006 |
| A real Standings tab | `history.seasons[].standings` already in the payload (blocked for 2024 by W19-F001) | W19-F007 |
| Manager names in 4 of 7 Archives tables | `data.managers` is already in the same payload; 1,441 of 2,035 rows render raw 18-digit Sleeper owner ids instead | W19-F016 |
| Owner-specific award tags on archived trades | key on participant `ownerId` instead of the literal `''`; today all 153 tagged trades carry one of two team-less awards | W19-F013 |
| Seasons beyond the 3-season cap | raise `PUBLIC_MAX_SEASONS` and/or walk to `previous_league_id '0'` — the chain terminates, so nothing is lost today | W19-F017 |
| Current-season articles | the generator works; only content is absent | W19-F014 |

### 3.2 Needs commissioner / operator entry — no source exists

| Surface | State | Finding |
|---|---|---|
| **Money** (dues, payouts, entry fees) | zero code anywhere. `grep -rni 'constitution\|dues\|payout\|entry fee'` across `src/`, `frontend/app/`, `config/`, `server.py` returns nothing outside an unrelated `residues` variable | W19-F007 |
| **Constitution** | same zero-hit grep | W19-F007 |

8 of the 11 required public navigation entries exist and work; 3 do not (Standings, Money,
Constitution), and League Media ships renamed as two AI-article tabs. Money and Constitution have
no upstream feed at all — the smallest correct version is two static JSON files under `config/`
plus two read-only sections, populated by the commissioner.

### 3.3 Cannot be reconstructed at all

| What | Why | Finding |
|---|---|---|
| **The board served on any past date** | archives carry `_composite` / `_finalAdjusted` / `_rawComposite` only — 0 of 129 snapshots carry `rankDerivedValue`, and 18 of 21 voting sources have no archived CSV. Two of them (`pfkDynasty`, `fantasyNavigatorSf`) first entered the tree 2026-08-03, three weeks after the 2026-07-14 snapshot they "replay" | W04-F009 |
| **Any recorded holdout criterion** | the fingerprints record *which* bytes a version was fitted on; the bytes are gone. Champion v2's recorded 787.84 recomputes to **753.05** today — a −34.79 drift, 139% of the 25-point promotion margin | W04-F006 |
| **Pre-season-2024 league history** | the Sleeper chain terminates at `previous_league_id '0'`; there is nothing older to walk to | W19-F017 |
| **Realized-outcome validation of the market board** | requires board snapshots taken *before* a season. `src/model_registry/board_holdout.py`'s own docstring says the repo does not keep them | W04-F009 |

---

## 4. The labelling backlog — what must be marked before it is shown

The brief is explicit that public pages must not present missing history as complete. Each row
below is a specific rendered claim, the label it needs, and the finding that establishes it.

| # | Page / surface | The claim as rendered | Required label | Finding | Pri |
|---|---|---|---|---|---|
| 1 | `/league?tab=records`, `?tab=streaks` | "all-time" records | **partial** — 2 franchises excluded; 3 rank-1 records are wrong today | W19-F001 | P1 |
| 2 | `/league?tab=history` | 2024 standings, 8 rows | **partial** — `numTeams: 10`, 8 rendered; needs a `standingsIncomplete` flag | W19-F002 | P1 |
| 3 | `/league?tab=records`, `?tab=streaks` | "all-time" | **rolling-window** — `PUBLIC_MAX_SEASONS = 3`, headroom 0; stamp `windowIsCompleteHistory` | W19-F017 | P2 |
| 4 | `/league?tab=activity` | "Robbery"/"Fleeced" letter grades | **partial** — 224 of 1,708 asset slots (13.1%) price to 0.0 and are dropped from both the linear sum and the value adjustment, including 6× "2024 R1" and 14× "2025 R1"; 63 of 191 trades affected. Needs `unpricedAssetCount` per side, exactly as `src/trade/finder.py` already ships `metadata.assetsUnpricedByBoard` | W19-F003 | P1 |
| 5 | `/league?tab=awards` | 8 awards for 2026; "POINTS KING 3 yrs" | **unofficial** — gate on `weeksScored > 0`; filter `historyByKey` on completion | W19-F004 | P1 |
| 6 | `/league?tab=power` (odds card) | playoff probabilities 1.0 / 0.0 | **unofficial** — stamp `simulated: false`; an uninformative prior is 0.583 | W19-F008 | P2 |
| 7 | Trades / Headline records / Hall of Fame / Superlatives / rivalry + player deep links | "the last 2 seasons" | **corrected** — derive from `league.seasonsCovered` (3) | W19-F005 | P2 |
| 8 | `/league?tab=superlatives` | "across the 2-season window" | **relabel** — composition is a *current-roster* snapshot; transaction counts are 3-season | W19-F006 | P2 |
| 9 | `/league?tab=previews`, `?tab=recaps` | present-tense live media surface | **stale + AI-attributed** — 2 files, 2025 wk 17; tabs carry no AI attribution | W19-F014 | P2 |
| 10 | `/league?tab=archives` | Trades/Waivers/Matchups tables | **corrected** — 1,441 of 2,035 rows show raw Sleeper owner ids | W19-F016 | P2 |
| 11 | `/league?tab=archives` | trade "tags" | **corrected** — all 153 tagged trades carry team-less season awards belonging to no participant | W19-F013 | P3 |
| 12 | `/league?tab=rosTradeDeadline` | Buyer/Seller/Hold verdicts | **awaiting-backfill** — sim runs on 2024; 4 of 12 managers absent, coerced to 0.0. Distinguish absent from zero and render "no read" | W17-F001, W17-F002 | P0 (authored, unverified) |
| 13 | `/league?tab=rosChampionship` | "42.6%" championship odds | **partial** — no CI, no convergence field; measured run-to-run spread 2.25 pp over 10 runs at the shipped n=10000. `playoff_sim` stamps `converged: true` on a payload whose headline number it did not test | W17-F008 | P2 |
| 14 | `/league?tab=rosChampionship` | "6 playoff seeds · 2 byes" | **corrected** — the live 2026 league is `playoff_teams: 7`; the 2024 league it is actually simulating was 5. `championship.py:80` hardcodes a literal 6 while `:239` counts with the parameter | W17-F011 | P2 |
| 15 | `/league?tab=rosTeamStrength` | "72 / 18 / 5 / 5" component weights | **corrected** — the two terms advertised as 10% of the answer supply **0.23%** of the discrimination between teams (spreads 275.83 : 25.86 : 0.456 : 0.238 on a 298.54-point composite). A scale problem, not a weight problem | W17-F009 | P2 |
| 16 | `/tools/ros-data-health`, `/api/ros/sources` | `is_projection_source: True` on `draftSharksRosSf` | **corrected** — the `projection` column is empty in **all 1,285 rows across all five sources**. The ROS board is a rank blend, full stop | W17-F012 | P2 |
| 17 | `/league?tab=rosTradeDeadline` | page copy describing roster-age inputs | **corrected** — `ageProfile` is `{}` on all 12 live rows; `build_section` never passes `teams`, so the age-gated Strong Seller branch cannot fire | W17-F010 | P2 |

Two labelling items on the private side belong here too:

| # | Surface | Required label | Finding | Pri |
|---|---|---|---|---|
| 18 | `/api/data` and everything downstream (`/rankings`, `/trade`, `/draft`, `/terminal`) | **provenance stamp** — 1,092 served values carry no `modelVersion`, no `paramSetId`, no `asOf`. Given a saved payload there is no way to tell whether champion v1 or v2 produced it. BDVM already ships the correct pattern next door | W04-F011 | P2 |
| 19 | `reports/*.md` (7 committed) | **unvalidated** — see §5 | W04-F009, W04-F010 | P2 |

---

## 5. The model side: there is no historical record of the served board

This is the section with the widest consequences, because it invalidates a category of claim
rather than a number.

### 5.1 The archives do not contain the board

An archived export's player rows carry `_composite`, `_finalAdjusted`, `_rawComposite`,
`_canonicalSiteValues` and three site columns. They carry **no** `rankDerivedValue`, **no**
`canonicalConsensusRank`, **no** `confidenceBucket`, **no** `sourceRanks` — the entire canonical
blend output is absent from all 129 snapshots.

Every backtest therefore *reconstructs* a board by calling `build_api_data_contract(old_payload)`
— and that function reads its CSV-backed sources from `CSVs/site_raw/` at paths hardcoded in
`_RANKING_SOURCES`, **from disk, today**. Rebuilding the 2026-07-14 payload yields 1,092 rows
voted on by 21 sources, **18 of which have no representation in that archive at all**.

The verifier **strengthened** this finding (W04-F009, authored P1 → verified P2, rescoped): the
author asserted the 18 extra sources come from today's tree but had not proved they were absent
from the snapshot. They are — the archive's `_canonicalSiteValues` carries exactly three keys
across all 1,074 players (`idpTradeCalc` 814, `ktc` 464, `ktcSfTep` 464). And
`pfkDynasty.csv` / `fantasyNavigatorSf.csv` were first added to the tree on 2026-08-03, so they
could not have contributed to any board served on 2026-07-14 — yet they vote in its "replay".
The verifier's phrase: *an airtight temporal leak*. Verified blast radius: **7 reports
invalidated, 3 backtest scripts affected, 3 live constants with leaked provenance**
(`_ALPHA_SHRINKAGE`, `_MAD_PENALTY_LAMBDA`, `_PERCENTILE_REFERENCE_N`), **0 archived snapshots
carrying `rankDerivedValue`**.

Re-run:
```bash
.venv/bin/python -c "import sys,json,zipfile;sys.path.insert(0,'.');\
from src.api.data_contract import build_api_data_contract;\
z=zipfile.ZipFile('exports/archive/dynasty_export_20260714_233659.zip');\
p=json.loads(z.read('dynasty_data_2026-07-14.json'));\
print([n for n in z.namelist() if n.startswith('site_raw/')]);\
print('rankDerivedValue' in p['players'][list(p['players'])[0]]);\
c=build_api_data_contract(p);s=set();[s.update((r.get('sourceRanks') or {}).keys()) for r in c['playersArray']];print(len(s))"
```
→ `['site_raw/ktcSfTep.csv','site_raw/ktc.csv','site_raw/idpTradeCalc.csv']` · `False` · `21`.
Artifact: `evidence/W04/backtest-temporal-leakage.json`.

### 5.2 Consequence for every validation claim in the repo

| Claim, where it is made | Verified status |
|---|---|
| `player_valuation.py`: "16 archived snapshots … against `rankDerivedValue` on the **served** board" | **False.** Those 16 boards were never served; they are counterfactuals under today's constants and today's expert boards. W04-F009 |
| `reports/alpha_shrinkage_backtest_full.md` "Promote α = 0.00"; `reports/percentile_reference_n_backtest_full.md` "**Promote N=400**"; `reports/soft_fallback_*`; `reports/alpha_lambda_joint_*` | Recommendations produced by the leaked replay path, and measuring **day-to-day rank churn**, not accuracy. Live values are α = 0.10 and N = 500 — neither matches its report. W04-F008, W04-F009 |
| `reports/backtest_blend_params.md:8` "Lower = more stable = probably better-calibrated" | An unearned inference, upheld verbatim by the verifier. W04-F008 |
| `scripts/backtest_percentile_reference_n.py:212` "The design-choice justification … is **empirically validated**" | Self-refuted twelve lines earlier in the same file. W04-F010 |
| The temporal-leakage caveat itself | Present in **1 of 9** backtest scripts and **0 of 7** committed reports. The correction exists and did not travel. W04-F010 |
| `src/backtesting/harness.py` | **Scaffolded only** — zero production importers, and its definition of a "correct" trade is agreement with a later reading of the same board. W04-F014 |
| CLAUDE.md: the refit "scores it against dynasty boards the fit never reads" | Structurally true as to *shipping*: the refit workflow cannot write constants (`write_committed_constants` is imported by exactly one module, and the workflow stages only `git add config/model_registry/`), and the live curve is **bit-exact** to registry champion v2 across 4 scopes × 9 percentile points, max abs difference 0. W04-F016, **Implemented and verified** |
| CLAUDE.md: promotion is validation | **Partly false, per the verified position.** Only `HILL_PERCENTILE_C/S` are scored; the other constants ship on a version-level `qualified: true` / `confidence: measured` label. W04-F003 |

**Two author claims here were corrected and must not be quoted as authored:**

- **W04-F001 was OVERTURNED and is not published.** The author claimed the four "held-out" boards
  are live blend sources so the benchmark is not independent. The observation is literally true —
  all four are in `_RANKING_SOURCES` — but the verifier showed the inference is a category error:
  `holdout.py:251-265` loads each board's **raw CSV**, converts it to (percentile, value) pairs
  and RMSEs the Hill curve against them. It never reads the blended board, `rankDerivedValue`, or
  any pipeline output. The residual is a P3 documentation note (`ktcSfTep` excluded for
  KTC-derivation while `fantasyNavigatorSf`, `correlation_group='ktc'`, is included) measured to
  have **zero effect on the criterion**. Do not cite "the holdout is not independent".
- **W04-F003's "six of eight unscored constants" is FOUR.** `HILL_ROOKIE_PERCENTILE_C/S` are not
  routed (`routed: false`, stamped honestly on the contract) and reverting them changes 0 rows.
  The verified figure: reverting the four **live** unscored constants
  (`HILL_GLOBAL_PERCENTILE_C/S`, `IDP_HILL_PERCENTILE_C/S`) to v1 moves **521 of 1,092 contract
  rows, 85 of them by more than 10%**. Priority corrected P1 → P2. The defect stands: those four
  ship with no out-of-sample score under a version-level "measured" label.
- **W04-F008 was rescoped P1 → P3.** What survives: the four constant-tuning reports do all
  optimize rank churn, the "probably better-calibrated" line is unearned,
  `MIN_FULL_COVERAGE_DEPTH = 60` has no backtest, and there is no forward-looking outcome join
  for the market board. What died: "the constants are wrong". Monkeypatching
  `_PERCENTILE_REFERENCE_N` to the report's recommended 400 fails 9 of 13
  `tests/canonical/test_ktc_reconciliation.py` cases (rank 400 moves 996 → 794, a −20.4 pp swing
  against a ±10 pp band). The supportable claim is **"unvalidated against outcomes, which the
  repo says out loud"** — not "mis-set".

### 5.3 Related model-history defects

- **No recorded criterion is reproducible.** v1 819.73 → 791.68 today; v2 787.84 → **753.05**;
  v3 775.05 → 730.80. Re-run:
  `.venv/bin/python -c "…ModelRegistry.load('hill_scope_masters')… evaluate_offense_master(v.holdout['params']…)"`
  (full command in W04-F006; artifact `evidence/W04/holdout-reproduction.json`). Fix is cheap —
  the 21 `site_raw` CSVs total ~1 MB; archive them alongside each registry write.
- **A holdout board silently lost 24% of its rows in one day and the gate scored it anyway.**
  `otcffbSf.csv` went 454 → 347 priced rows between 2026-08-03 and 08-04; because
  `_percentile_pairs` uses `i/(n−1)`, every row's percentile coordinate moved, and the *same*
  curve now scores 853.52 where it scored 991.68. That one board contributes −34.54 of the
  −34.79 total criterion drift — **99.3%**. No warning, no skip, no registry note. `perSourceRows`
  is already persisted, so the guard is free. *(W04-F007, P2, new — not in the prior index.)*
- **The CLI compares unpaired criteria.** `model_registry.py validate` reads both stored criteria
  straight out of JSON — recorded 2026-07-28 and 2026-08-04 against different scrapes — the exact
  comparison `promotion.py`'s own docstring says invalidates a verdict. `validate 3` prints +12.8;
  the paired comparison today is **+22.25** against a 25-point margin with a ~1.5-point stated
  noise floor. The automated driver does it correctly; only the human-facing CLI is wrong.
  *(W04-F005, P2, unverified by a second pass.)*
- **The IDP Hill master's training set and application set do not intersect.** Fit from
  IDPTradeCalc-IDP + DraftSharks-IDP (neither of which consumes it — one votes value-direct, the
  other routes to GLOBAL), applied to `dlfIdp` / `dlfRookieIdp` / `idpShow` / `fantasyProsIdp`,
  four rank-signal sources that publish no values and contributed nothing to the fit.
  `|fit ∩ applied| = 0`. *(W04-F004, P2.)*
- **Confidence is one unvalidated agreement bucket and never shrinks a value.**
  `_compute_confidence_bucket` takes exactly two inputs (`sourceCount`,
  `sourceRankPercentileSpread`); `_marketConfidence` and `identityConfidence` sit on the same row
  and never combine into it. On the live board 448 of 1,092 rows (41.0%) are `low` and 113
  (10.3%) `high`. **Zero code paths let confidence discount `rankDerivedValue`** — it only
  reorders (a flat +2/+1/0 added to a sort key in `suggestions.py`, on thresholds that disagree
  with the contract's) and filters. No calibration measurement exists anywhere. Measuring it is
  blocked on §5.1. *(W04-F012, P2.)*
- **The refit audit trail is current** — a v3 challenger was fitted, scored against all four
  holdout boards, rejected for missing the margin by 2.6 points, and committed on 2026-08-04.
  The prior audit's "no entry since 2026-07-28" is **refuted at this HEAD**. *(W04-F015.)*

---

## 6. ROS history: retained forever, documented as rolling

`data/ros/aggregate/history` is documented as a "rolling 30-day archive". It holds **796 files
spanning 98 days (2026-04-28 → 2026-08-04), 857 MB, all tracked in git**, plus 4,653 tracked run
files under `data/ros/runs` — 5,463 tracked files under `data/ros` total. `scrape.py:615-616`
writes a fresh ~1.1 MB archive roughly every 3 hours and **no prune, cleanup or unlink exists
anywhere** under `src/ros/` or `scripts/`. The word "rolling" has no implementation.
*(W17-F013, P2; confirms PRIOR-A19-F18 and re-measures it — 796 snapshots vs the prior 792,
proving the mechanism is still running unbounded.)*
Re-run: `ls data/ros/aggregate/history | wc -l; du -sh data/ros/aggregate/history; grep -rn
'prune\|unlink\|cleanup' src/ros/` → 796 · 857M · nothing. Re-confirmed at audit time.

One vintage defect inside the aggregate that costs real accuracy: 6 casing-only duplicate rows
survive `normalize_player_name`, and the join in `team_strength.py` uses `by_name.setdefault`
over a `rosValue`-descending list — so it **always keeps the higher-valued row and discards the
better-supported one**. Cam Ward: 33.12 (sourceCount 1) kept, 21.18 (sourceCount 3) discarded.
5 of the 6 duplicated players are rostered on 5 different teams, each inflating that team's
starting-lineup score. The HANDOFF.md figure "40 of 666 unmatched" is stale — it is now **30 of
666**, because the `resolve_canonical_name` join fix landed. *(W17-F005, P2.)*

**The cardinal isolation rule holds.** No ROS value reaches `rankDerivedValue`, the trade
calculator or the rankings board — verified in both directions at runtime: zero `^(ros[A-Z]|ros_|
restOfSeason|teamRos)` keys at any depth of the live contract, zero `src.ros` imports in
`data_contract` / `trade` / `canonical`, and every `src/ros/` write resolves under
`data/ros`. The reverse coupling (`src/ros/lineup.py` imported by `roster_intel`,
`league_intel/replacement.py`, `api/gameplan.py`) is the shared **lineup optimizer**, a pure
function of slots and weights, not a ROS value. *(W17-F003, Implemented and verified;
`sh docs/master-site-audit/evidence/W17/isolation-check.sh`.)*

---

## 7. Repair order

1. **W17-F001** — one-line fix at four call sites (`key=lambda s: luck._season_sort_key(s.season)`),
   plus a preseason guard so a zero-game season returns honestly-unknown odds instead of falling
   back to a completed one. Unblocks W17-F002 and the trade-deadline verdicts. Size XS, P0.
2. **W19-F001 / W19-F002** — keep retired owners in `roster_to_owner` and filter them only at the
   display surfaces that need it. Fixes 3 wrong rank-1 records and unblocks a Standings tab.
3. **W19-F003, W19-F004** — unpriced-asset disclosure on trade grades (copy the posture
   `src/trade/finder.py` already ships) and a `weeksScored > 0` gate on awards. Both are
   "stop asserting things you don't know", not new data.
4. **Labels 3, 6–11, 13–17** — copy and flag work, no new data required.
5. **W04-F009 (1)(2)(3)** — write `playersArray` (or at minimum `rankDerivedValue` +
   `canonicalConsensusRank` + `confidenceBucket` + `sourceRanks`) into every export; archive all
   21 `site_raw` CSVs per snapshot (~1 MB); give `build_api_data_contract` an optional `site_raw`
   root so a replay reads the snapshot's own CSVs. **Until these land, no report in `reports/`
   should be cited as evidence** — and every one of them should say so on its face (W04-F010).
6. **W04-F011** — stamp `meta.modelVersion` / `paramSetId` / `modelAsOf` on every contract build.
   `_build_hill_curves_block` already imports the constants; it can import the registry pointer.
   This is what makes future history interpretable even before (5) is complete.
7. **Money / Constitution** — commissioner content entry. Nothing else unblocks them.

---

## 8. What this document could not establish

- **Whether the four live unscored Hill constants are mis-set**, as opposed to merely unmeasured.
  It cannot be tested from what is in `CSVs/site_raw` today: no GLOBAL or IDP value board exists
  outside `idpTradeCalc`, which is a training/anchor source. (W04-F003, verifier's
  `whatWouldSettleIt`.)
- **Whether the leaked backtests reached the wrong answer.** The leak is proven; the
  counterfactual is not computable, because the export that would settle it does not exist.
  (W04-F009.)
- **Whether W17-F001 / W17-F002 survive adversarial verification.** No verifier verdict was
  produced for either. They are the two P0s in this document and they are author-graded.
- **GitHub Actions run history** for the refit workflow (the prior audit's "6 of 13 scheduled runs
  failed"). Not checkable from this container; left unverified. (W04-F015.)
- **Per-source ROS freshness multipliers.** W17-F004 verified the *aggregate* freshness classifier
  only; PRIOR-A19-F06's per-source `staleFlag` claim was not attempted.
- **Whether the public holdout set predates the 2026-07-25 rank-signal switch.** Every file in the
  repo first appears in one squashed automated-refresh commit (891d1600, 2026-08-03), so the
  chronology cannot be checked here. (W04-F002, verifier note.)
