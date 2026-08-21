# V1-35 — metric separation and duplicate-owner audit

**Row:** `V1-35` · **Lane:** L1 Roster Intelligence · **Required evidence
level:** EVIDENCE-L1 · **Status entering this audit:** `NOT STARTED`

**Binding source** — `docs/OWNER_REQUESTED_TODO.md` decision 69, verbatim:

> **Total Asset Value, Meaningful Roster Strength, Exact Starting Lineup,
> Depth Value, Power Ranking, Playoff Probability and Championship
> Probability stay distinct** in the model and the UI. They may not be
> collapsed into one generic team score.

Seven named quantities. This audit asks, of every production consumer:
*is this the same concept as another, a legitimately different quantity,
a stale duplicate, or a compatibility adapter?*

**It does not consolidate things because they contain the word
"strength".** Two of the entries below are correctly separated today and
are recorded as such precisely so nobody "fixes" them.

---

## 0. The headline finding

> **Six live production answers to "how good is this team" exist on six
> different units — and the module documented as "THE canonical Team
> Strength owner" is the one nobody renders.**

`src/roster_intel/strength.py` opens with "the canonical Team Strength
owner". `grep -rn "roster/intelligence" frontend/` returns **zero
hits**: no page, hook or bridge route fetches it. Meanwhile
`frontend/lib/nav-model.js:147` labels **`/rosters`** as "Team Strength",
and `/rosters` renders a client-side composite with no server
equivalent.

This is the V1 contract's own false-green test failing —
*"is the intended production consumer actually using the canonical
implementation, with truthful data semantics?"* — and it is why V1-31
cannot claim EVIDENCE-L4 no matter how correct the owner is.

**The repair is a frontend change on `/rosters`, which is Claude 6's
lane.** It is handed over in §3, not made here.

---

## 1. Census

Verified file-by-file at `fd70515`. "Rendered?" means a frontend
fetch/render path exists, not merely that the route responds.

| # | concept | canonical owner | quantity · unit | production path | rendered? | classification |
|---|---|---|---|---|---|---|
| 1 | Canonical asset value | `src/api/data_contract.py::_compute_unified_rankings` → `rankDerivedValue` | dynasty market value · **1–9999** | `/api/data` and every engine | yes | **canonical** |
| 2 | Exact starting lineup | `src/ros/lineup.py::solve_optimal_assignment` | assignment + score · **unit-agnostic** (score is in whatever unit the pool carries) | contract stamp `sleeper.teams[].optimalLineup` | yes, via `starter-slots.js::fillLineup` | **canonical** |
| 3 | Meaningful Roster Strength | `src/roster_intel/strength.py::build_team_strength` | Σ `rankDerivedValue` over the meaningful core · **1–9999 scale, uncapped in aggregate** | `src/api/roster_intelligence.py:259` → `GET /api/roster/intelligence` | **NO — zero frontend fetchers** | **canonical, UNCONSUMED** |
| 4 | Team Weakness / need priority | `src/roster_intel/weakness.py::build_team_weakness` | rung status vs `k × teamCount` · **ordinal, not a score** | same endpoint, `:261` | **NO** | **canonical, UNCONSUMED** |
| 5 | ROS team strength | `src/ros/team_strength.py::compute_team_strength` | `teamRosStrength` · **0–100 log-rank production index** | `data/ros/team_strength/<key>.json` → `/api/public/league/rosTeamStrength` | yes — "ROS Strength" tab | **legitimate different quantity** |
| 6 | Power ranking | v2 `src/ros/power_v2.py` (live) · v1 `src/public_league/power.py` | v2 `power_score` **0–1 weighted percentile** · v1 `power` **0–100** | `public_contract.py` → one Power tab, switched by `useRosPowerRankings` | v2 yes, v1 dormant | **duplicate — cross-lane (V1-52)** |
| 7 | Playoff probability | `src/ros/playoff_sim.py::simulate_playoff_odds` · `src/public_league/playoff_odds.py::compute_playoff_odds` | probability **0–1** | both registered in `public_contract.py` | yes | **duplicate — cross-lane (V1-51)** |
| 8 | Championship probability | `src/ros/championship.py::simulate_championship_odds` | probability **0–1**; `expectedFinish` **seed 1..N** | `public_contract.py:150` → "Championship" tab | yes | **canonical** |
| 9 | `/api/gameplan` | `src/api/gameplan.py` | mixed, units policed in its own docstring; `marketEdge` deliberately `null` | `server.py:6797` | **NO — DISCONNECTED** (`feature_flags.py:235`) | **compatibility adapter** |
| 10 | `/api/terminal` `totalValue` | `src/api/terminal.py::build_terminal_payload` | Σ `rankDerivedValue` over the **whole roster** · 1–9999 | `server.py:11944` → `useTerminal.js`, `PortfolioSummary.jsx` | yes | **legitimate different quantity** = decision 69's *Total Asset Value* |
| A | `/rosters` value breakdown | `frontend/lib/league-analysis.js::buildAllTeamSummaries` | Σ 1–9999 by position group | `/rosters` | yes | **materializer — consumes the server's `optimalLineup`, computes no new concept** |
| B | `/rosters` tier score | `frontend/lib/league-analysis.js:1224` | `starterValue×0.7 + depthValue×0.2 − pickValue×0.1` | `/rosters`, Contender/Mid-Tier/Rebuilder | yes | **STALE DUPLICATE — decision-69 violation** |
| C | `/phases` classifier | `frontend/lib/team-phase.js` | `strengthTotal` × `valueWeightedCoreAge` → 4 labels | `/phases` | yes | **RETIRED (H-2 closed) — was duplicate concept, client-only; inputs now canonical** |
| D | BDVM roster | `src/bdvm/roster.py::analyze_rosters` | `starterFpg` · **projected fantasy points per game** | `/api/bdvm/roster`, flag `bdvm_engine` on | endpoint yes | **legitimate different quantity** |

---

## 2. Findings

### F-1 — `scoreTeamTiers` is a collapsed generic team score (decision-69 violation)

`frontend/lib/league-analysis.js:1224`, verbatim:

```js
const score = starterValue * 0.7 + depthValue * 0.2 + (pickValue > 0 ? -pickValue * 0.1 : 0);
```

It merges three of decision 69's seven — Exact Starting Lineup (via
`starterValue`), Depth Value, and part of Total Asset Value — into one
number, then terciles it into Contender / Mid-Tier / Rebuilder. **Pick
capital is a penalty**: a rebuilding team's draft assets *lower* its
score, which is a strategy judgement encoded as arithmetic.

There is **no server equivalent of this formula anywhere**. The weights
0.7 / 0.2 / −0.1 appear in no config, no ADR and no owner decision.

It does consume the canonical lineup correctly (`fillLineup` with the
server's `optimalLineup`), so the defect is the composite, not the
lineup.

* **Canonical owner:** `src/roster_intel/strength.py` (`total` /
  `starterValue` / `reserveValue`, published separately) plus
  `src/roster_intel/window.py` for the contend/rebuild judgement.
* **Retirement path:** in §3, handoff **H-1**.

### F-2 — the canonical Team Strength and Team Weakness owners have no consumer

`GET /api/roster/intelligence` is HTTP-reachable and correct, and no
frontend code fetches it. The two capabilities V1-31 and V1-32 name are
implemented and invisible.

Consequence for the V1 ledger, stated precisely: V1-31 and V1-32 require
**EVIDENCE-L2**, which this audit's sibling test suite now supplies, so
the missing consumer does **not** block their required level. It blocks
any future L4 claim, and it means the product's visible "Team Strength"
is F-1's formula. Both facts belong in the row notes.

* **Retirement path:** handoff **H-1** (same change closes both).

### F-3 — `/phases` is a third client-side team classifier — CLOSED (V1-31 discovery-guard PR)

`frontend/lib/team-phase.js` classified teams Win-now / Contender /
Mixed / Rebuild from a client-side top-25 `rankDerivedValue` sum × a raw
per-player age lookup, scanning `rawData.sleeper.teams` directly (the
duplicate value/age computation this finding names).

Not the same defect as F-1: this was a legitimate concept computed in
the wrong place, rather than an invented composite, so the fix is
narrower than H-1's — the classification RULE (value vs. league median,
age vs. league median → 4 quadrants) and the trade-partner
complementarity scoring are unchanged; only the two INPUT axes were
redirected onto canonical sources already served league-wide by
`GET /api/roster/intelligence` (`payload.leagueContext`, via
`lib/roster-intelligence.js::teamStrengthLadder`):

    value  <- strengthTotal          (src/roster_intel/strength.py, row 1.1)
    age    <- valueWeightedCoreAge   (src/roster_intel/age_portfolio.py, row 1.6)

`window.py`'s CompetitiveWindow was NOT used — it is not reachable
league-wide today (only per-team, via the disconnected `/api/gameplan`),
and redirecting the classification RULE itself onto it would need new
backend surface plus a decision on how its contend/rebuild states map
onto the 4-way Win-now/Contender/Mixed/Rebuild labels, which is a
product question outside a duplicate-consolidation unit's scope, not a
retirement this audit can close on its own.

`TeamPhasePanel.jsx` now reads `useRosterIntelligence()` (same hook
`/rosters`' `TeamStrengthCard.jsx` uses) instead of `useDynastyData()`.
Discovery guard: `frontend/__tests__/no-frontend-team-strength-methodology.test.js`
extended with a scan for `rankDerivedValue` / `useDynastyData(` /
`sleeper.teams` in `lib/team-phase.js` + `components/TeamPhasePanel.jsx`,
mutation-proven (a reintroduced raw-row read fails the guard; restored,
green).

* **Retirement path:** handoff **H-2** — closed.

### F-4 — two power engines and two playoff-odds engines

Confirmed at file level; both are pre-existing V1 rows (V1-52, V1-51)
and both are outside this lane.

* Power: `src/ros/power_v2.py` (0–1 composite, live by default —
  `useSettings.js:174` sets `useRosPowerRankings: true`) vs
  `src/public_league/power.py` (0–100, `100 × (0.50·PPG%ile +
  0.25·recent%ile + 0.25·allPlayWin%)`), swapped at
  `LeagueClient.jsx:413`.
* Playoff odds: `src/ros/playoff_sim.py::simulate_playoff_odds`
  (`playoff_seeds: int = 6`) vs
  `src/public_league/playoff_odds.py::compute_playoff_odds`
  (`playoff_spots: int | None`) — the parameter difference is the
  measured 7-vs-6-spots disagreement V1-51 records.

**No action taken here.** Both are Claude 3 / public-league files.
Recorded so V1-35's census is complete; retirement stays with V1-51/V1-52.

### F-5 — stale comment contradicting a live default

`frontend/app/league/LeagueClient.jsx:124` says `useRosPowerRankings` is
"false until validated per-user"; `frontend/components/useSettings.js:174`
defaults it **true**. A stale comment, not a defect. Flagged to Claude 6;
not fixed here.

---

## 3. Correctly separated — record, do not "fix"

Three boundaries already hold, and each is load-bearing enough that a
future tidy-up would be a regression.

| boundary | why it is right | where it is stated |
|---|---|---|
| `rosValue` (0–100 ROS production) vs `rankDerivedValue` (1–9999 dynasty) | different products on different horizons; `MASTER_PRODUCT_PLAN` §4.1: *"Team Strength is dynasty roster strength; it is not Power Ranking, Playoff Odds, or ROS production."* V1-50 pins the honesty of `rosValue` | `src/ros/aggregate.py:171`; `src/api/gameplan.py:37-56` polices the currencies and leaves `marketEdge` **`null`** rather than converting |
| `/api/terminal` `totalValue` (whole-roster portfolio) vs Team Strength `total` (meaningful core) | decision 69 names *both* — Total Asset Value **and** Meaningful Roster Strength. On a 58-man best-ball roster they are far apart by construction | `src/roster_intel/strength.py:20-27` names the distinction itself and publishes `full_roster_value` **beside** `total` |
| `src/roster_intel/engine.py` relays odds, never invents them | with no simulator output it returns `None` **with a note** naming why, instead of deriving probability from roster value — which would manufacture two of the seven quantities out of a third | `engine.py:352-372`; pinned by `tests/roster_intel/test_metric_separation.py` |

`/api/gameplan` is a **compatibility adapter**, not a duplicate: it reads
other owners' numbers, keeps their units separate in its own docstring,
and is DISCONNECTED (`src/api/feature_flags.py:235`). Nothing to retire
until something consumes it.

---

## 4. Cross-lane handoffs for Claude 5

Nothing in this section was edited. Each entry gives path, consumer,
current quantity, desired owner and the test that would close it.

### H-1 — retire the `/rosters` tier score onto the canonical owner (**Claude 6**)

| field | value |
|---|---|
| **path** | `frontend/lib/league-analysis.js::scoreTeamTiers` (formula at `:1224`) |
| **consumer** | `frontend/app/rosters/page.jsx:113`; nav labels this page "Team Strength" (`frontend/lib/nav-model.js:147`) |
| **current quantity** | client-only composite `starterValue×0.7 + depthValue×0.2 − pickValue×0.1`, tercile-bucketed |
| **desired owner** | `GET /api/roster/intelligence` — `strength.total`, `strength.starterValue`, `strength.reserveValue`, `strength.leagueRank` rendered as the separate quantities they are; contend/rebuild from `src/roster_intel/window.py`, not from a weighted sum |
| **test** | a frontend unit test asserting `/rosters` renders backend-stamped values and that `scoreTeamTiers` is gone; plus `tests/roster_intel/test_metric_separation.py::test_roster_intelligence_publishes_no_generic_team_score` extended to the rendered props |
| **note** | this single change closes **F-1 and F-2 together** and is what would let V1-31 / V1-32 reach EVIDENCE-L4 |

### H-2 — fold `/phases` onto the age-portfolio and strength owners — CLOSED

| field | value |
|---|---|
| **path** | `frontend/lib/team-phase.js`; `frontend/components/TeamPhasePanel.jsx` |
| **consumer** | `frontend/app/phases/page.jsx` |
| **quantity before** | top-25 `rankDerivedValue` total × median age → 4 labels, computed client-side from raw player rows |
| **quantity after** | `strengthTotal` (`src/roster_intel/strength.py`) × `valueWeightedCoreAge` (`src/roster_intel/age_portfolio.py`), read from `GET /api/roster/intelligence`'s `leagueContext` via `teamStrengthLadder`; same classification rule, canonical inputs |
| **not done** | folding the classification RULE itself onto `window.py`'s CompetitiveWindow — not reachable league-wide without new backend surface, and mapping its states onto 4 quadrant labels is a product decision outside this unit |
| **test** | `frontend/__tests__/team-phase.test.js` (6, incl. an unmeasured-input case), `frontend/__tests__/components/team-phase-panel.test.jsx` (4), `no-frontend-team-strength-methodology.test.js`'s extended raw-row-derivation guard (mutation-proven) |

### H-3 — V1-52 power engines (**Claude 3 / public league**) — census only

Recorded in F-4 for V1-35's completeness. Retirement belongs to V1-52
and is **not** requested by this audit.

### H-4 — V1-51 playoff-odds engines (**Claude 3 / public league**) — census only

As H-3, for V1-51.

### H-5 — stale comment (**Claude 6**, trivial)

`frontend/app/league/LeagueClient.jsx:124` contradicts
`useSettings.js:174`. One-line comment fix.

---

## 5. What this closes, and what it does not

**Closed at EVIDENCE-L1** by `tests/roster_intel/test_metric_separation.py`
(10 tests, all mutation-proven — see §6):

* no collapsed generic team score anywhere in the canonical roster payload;
* Meaningful Roster Strength and Total Asset Value separately named, with
  an absent portfolio reported as `null` rather than the core total;
* Exact Starting Lineup published as assignment, Team Strength as value,
  neither derivable from the other, and FLEX never a strength group;
* Depth Value published beside the total and partitioning it exactly;
* Playoff and Championship Probability relayed or `None` — never derived
  from roster value;
* the dynasty-value lane structurally cannot import the ROS-production
  modules (`team_strength`, `aggregate`, `power_v2`, `playoff_sim`,
  `championship`, `direction`).

**Not closed.** V1-35 says "in the model **and the UI**". This audit
closes the model half inside this lane and hands the UI half to Claude 6
as H-1/H-2. The row should read `IN PROGRESS` with the model half
evidenced, not `VERIFIED` — a green suite here is necessary and not
sufficient.

---

## 6. Evidence

| claim | how it was checked | result |
|---|---|---|
| no frontend fetcher for `/api/roster/intelligence` | `grep -rn "roster/intelligence" frontend/` | 0 hits |
| `scoreTeamTiers` formula | read `frontend/lib/league-analysis.js:1215-1250` | confirmed verbatim, incl. the pick penalty |
| nav labels `/rosters` "Team Strength" | read `frontend/lib/nav-model.js:143-152` | confirmed |
| roster_intel never imports ROS-production modules | AST scan of every `src/roster_intel/*.py` + `src/api/roster_intelligence.py` | 0 offenders; only `src.ros.lineup` (the canonical lineup owner, unit-agnostic) is imported |
| the import guard is not decoration | same detector run against `src/ros/api.py`, which does import `src.ros.team_strength` | detector fires |
| the collapsed-score walk is not decoration | injected a `teamScore` field into a synthetic payload | detector fires |
| the payload walk is not vacuous | asserted > 500 keys traversed on a real rebuilt contract | passes |
| two playoff engines exist | read both signatures | `playoff_seeds: int = 6` vs `playoff_spots: int \| None` |

Suite: `python -m pytest tests/roster_intel/test_metric_separation.py -q` →
**10 passed**, hard gate (`-m "not livedata"`), no network.
