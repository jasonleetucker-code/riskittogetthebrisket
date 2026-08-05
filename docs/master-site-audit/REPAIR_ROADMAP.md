# Repair Roadmap

Deliverable sections **17 (Prioritized Repair Roadmap)** and **18 (Recommended Implementation
Sequence)** of the master site audit.

- Source of truth: `docs/master-site-audit/findings.json` — 431 published findings (+1 refuted
  and retained), audited commit `e96c06ef`, registry generated at `fb4a15a0`.
- Evidence: `docs/master-site-audit/evidence/<Wnn>/`, 45 adversarial verdicts under
  `evidence/verify/`, harness and limits in `EVIDENCE_LOG.md`.
- **Every severity in this document is the verified severity.** Adversarial verification changed
  22 of them, always downward (5× P0→P1, 2× P0→P2, 14× P1→P2, 2× P1→P3) and overturned one
  finding outright. Where an authored severity differed, it is named as `authored Pn` and never
  quoted as fact.
- This is a plan. Nothing here has been executed.

---

## How this document is organised

The audit filed 431 findings. It did not find 431 defects. Grouped by **root cause** — the line
of code or the missing concept that produces the symptom — the 431 findings collapse to **30 root
causes**, and the 9 surviving P0s collapse to **5**.

That regrouping is the point of this document. Nine P0 tickets would send nine people to nine
files. Five root causes send four people to four files and one to a formula.

| | count |
|---|---|
| Published findings | 431 |
| Root causes | 30 |
| Root causes carrying at least one P0 | 5 |
| Root causes carrying at least one P0 or P1 | 25 |
| Root causes whose highest member is P2 | 4 |
| Root causes whose highest member is P3 | 1 |
| P3 findings that are **verified-working records, not work** | 56 of 156 |

Every root cause is numbered `R1`…`R31` (R24 was merged into R1 during grouping; the label is
retired). Each finding is assigned to exactly one root cause; the assignment covers 431/431 with
no duplicates.

### Priority tiers

A root cause is placed in the tier of its **highest-severity member**, and each entry lists all
of its findings by tier. So the P2 section is short — 156 of the 180 P2 findings are the tail of
work already scheduled in the P0 and P1 tiers, and scheduling them separately would be
double-counting.

### Size scale

| size | meaning |
|---|---|
| XS | one function, under ~10 lines, no new concept |
| S | one file, or one constant plus its test |
| M | one subsystem, several files, an existing concept re-derived |
| L | crosses subsystems, or requires a new shared definition |
| XL | new subsystem, or a feature that does not exist yet |

### Root-cause index

| id | root cause | n | P0 | P1 | P2 | P3 |
|---|---|---|---|---|---|---|
| R1 | TEP default forces every request onto the override path | 10 | 3 | 2 | 4 | 1 |
| R2 | Market gap computed in raw ordinal rank space | 10 | 1 | 4 | 2 | 3 |
| R3 | ROS sims run on the oldest season; absence coerced to 0.0 | 16 | 3 | 0 | 8 | 5 |
| R4 | Draft slot count clamped to a pre-fetch default | 18 | 1 | 3 | 8 | 6 |
| R5 | FAAB blends raw dollars across three budget regimes | 22 | 1 | 5 | 7 | 9 |
| R6 | Percentile denominators and curve scopes disagree | 19 | 0 | 4 | 5 | 10 |
| R7 | One global top-N gate over a cross-class value scale | 15 | 0 | 5 | 6 | 4 |
| R8 | Draft picks are name-keyed second-class assets | 11 | 0 | 7 | 3 | 1 |
| R9 | Unpriced is coerced into a confident number | 10 | 0 | 6 | 1 | 3 |
| R10 | Preseason and zero-evidence states are not gated | 21 | 0 | 9 | 9 | 3 |
| R11 | Team direction, strength and power computed many ways | 16 | 0 | 5 | 10 | 1 |
| R12 | Auth, rate-limit and public-surface boundaries | 13 | 0 | 4 | 5 | 4 |
| R13 | Source ingestion failures are invisible | 29 | 0 | 3 | 17 | 9 |
| R14 | Identity resolution is name-based end to end | 16 | 0 | 2 | 8 | 6 |
| R15 | Exact-scoring engine is duplicated and lossy | 19 | 0 | 3 | 3 | 13 |
| R16 | League registry identity is hand-typed | 8 | 0 | 2 | 3 | 3 |
| R17 | Public-league identity filter erases franchises | 18 | 0 | 3 | 7 | 8 |
| R18 | News is joined and applied wrongly | 11 | 0 | 2 | 7 | 2 |
| R19 | Payload shape and cold-path cost | 12 | 0 | 4 | 6 | 2 |
| R20 | CI gates do not gate | 11 | 0 | 3 | 4 | 4 |
| R21 | No model provenance or historical board | 15 | 0 | 0 | 12 | 3 |
| R22 | Confidence is one unvalidated agreement bucket | 8 | 0 | 1 | 3 | 4 |
| R23 | Sharp cohort evidence is thin and unlabelled | 18 | 0 | 1 | 8 | 9 |
| R25 | Navigation, bridge coverage and dead surfaces | 16 | 0 | 1 | 8 | 7 |
| R26 | Documentation drift | 13 | 0 | 1 | 7 | 5 |
| R27 | Accessibility and mobile ergonomics | 6 | 0 | 0 | 5 | 1 |
| R28 | Trade value concepts collide under one field name | 20 | 0 | 6 | 7 | 7 |
| R29 | Insider Trading surfaces its own limits inconsistently | 15 | 0 | 0 | 4 | 11 |
| R30 | Consensus Edge is honest but half-wired | 10 | 0 | 0 | 3 | 7 |
| R31 | Unreachable modules, routes and scripts | 5 | 0 | 0 | 0 | 5 |
| | **total** | **431** | **9** | **86** | **180** | **156** |

---

# 17. Prioritized Repair Roadmap

## P0 — 9 findings, 5 root causes

Four of the five are one-file defects. Three of them are size S or XS.

---

### P0-1 · R1 — The TEP default forces every page load onto the override path

**Closes:** `W03-F001` (P0), `W07-F001` (P0), `W08-F001` (P0), `W07-F002` (P1), `W03-F010` (P1),
`W08-F012` (P2), `W07-F005` (P2), `W03-F003` (P2), `W08-F008` (P2), `W07-F009` (P3) — 10 findings.

**Problem.** `frontend/components/useSettings.js:35` sets `SETTINGS_DEFAULTS.tepMultiplier` to the
literal `1.15`, and `frontend/lib/dynasty-data.js:919-923` (`tepMultiplierIsCustomized`) returns
true for *any* finite number. So every session — including a browser with empty `localStorage` —
takes the override branch and POSTs `{"tep_multiplier":1.15}` to
`/api/rankings/overrides?view=delta` on every page load. `src/api/data_contract.py:6939`
(`if not tep_multiplier_is_override:`) gates the entire ADR-015 TE-basis conversion, so an
explicit value skips the measured base→TE++ curve (1.209 at the top of the board rising toward
2.05 down it) and substitutes the flat 1.15 that ADR-015 retired for sitting below the whole
observed range.

The verifier established the sharpest form of this: an **empty** body `{}` returns a
byte-identical board (0 rank, 0 tier, 0 value diffs), so it is the *presence* of the key, not its
value, that reprices 786 rows — posting the exact number the contract reports as its own default
changes the board (`W03-F001` verification, `evidence/W03/tep-board-divergence.json`).

**User impact.**
- 627 of 740 `canonicalConsensusRank` values, 654 tiers and 135 values differ between the rendered
  board and `GET /api/data` (`W03-F001`, verified to the digit).
- 82 TEs under-priced by up to **21.2 %**; Tyler Conklin renders at #666 / 1,142 where the API
  says #469 / 1,450 (`W07-F001`, `evidence/W07/te-divergence.json`).
- Every server-side engine — trade suggestions, arbitrage finder, angles, terminal, simulate,
  FAAB — prices from `latest_contract_data`, i.e. the *other* board.
  `/api/waiver/faab-recommend` answers `resolvedAddValue 1519.0` for Brevin Jordan in the same
  session the page shows **1,243** (`W07-F001`).
- The divergence is inside one viewport: `frontend/app/trade/page.jsx:94` takes rows from
  `useDynastyData` while `POST /api/trade/suggestions` on the same page answers from the canonical
  board (`W03-F001` verification).
- `AppShell.jsx:61` hydrates `useDynastyData` on every private page, so ~30 of 41 pages render the
  override board (`W07-F001` verification, blast radius corrected upward from 5).
- No warning is reachable. `/settings` labels the value **"Default 1.15x"** and its "Reset to
  default" button *writes* 1.15 (`W07-F002`); `readSettings()` at `useSettings.js:182-190` migrates
  a genuine `null` ("auto") up to 1.15 once and latches `tepDefaultV3Applied`, so users who were in
  auto mode were migrated out of it permanently. The "Custom Mix" badge
  (`rankings/page.jsx:170`) gates on `isCustomized`, which the backend stamps **false** for a
  tep-only override — structurally suppressed on exactly this state.
- Second-order: because `write_snapshot = not source_overrides` and a tep-only body yields
  `source_overrides == {}`, **every page load rewrites `data/snapshots/ranks_last.json`** with the
  1.15 board's ranks (`W03-F010`; md5 verified to change after one POST). The next scrape's
  rankChange arrows are measured against a baseline any page load can overwrite.

**Root cause.** Two definitions of "default": the UI's ("equals the shipped constant") and the
backend's ("key absent"). The backend half is deliberate and correct — an operator-typed
multiplier *should* bypass a measured curve. The defect is entirely that the frontend sends an
operator decision nobody made (`W07-F001` whatWorks).

**Required repair.**
1. `useSettings.js:35` → `tepMultiplier: null` (the documented sentinel).
2. Delete the `readSettings()` null→1.15 migration at `useSettings.js:182-190`.
3. `settings/page.jsx:425` "Reset to default" must clear the key, not write 1.15; the label at
   `:407` must stop calling an override "Default".
4. The slider writes a number only on a real user edit.
5. Independently, gate the snapshot write on request kind, not on truthiness of
   `source_overrides`: pass `write_snapshot=False` from every `/api/rankings/overrides` path
   (`W03-F010`).

**Dependencies.** None. Both halves are self-contained. This must land *before* any measurement of
R2, R6 or R9, because until it does, two boards exist and every measurement has to say which.

**Size.** **S** (steps 1–4 are three files; step 5 is one guard).

**Acceptance test.**
- `POST /api/rankings/overrides?view=delta` with `{"tep_multiplier": <tepMultiplierDerived>}` is
  byte-identical to the same POST with `{}` — 0 of 809 rows differ (`W08-F001` requiredRepair).
- With `localStorage` cleared, a `/rankings` load issues **no** `POST /api/*` (browser request
  interception per `AUDIT_PROTOCOL.md`).
- `md5(data/snapshots/ranks_last.json)` is unchanged after a page load.
- A row-for-row diff of the rendered board against `GET /api/data` returns 0 rank, 0 tier, 0 value
  differences.

---

### P0-2 · R2 — The market gap is computed in raw ordinal rank space

**Closes:** `W12-F002` (P0), `W27-F005` (P1), `W27-F001` (P1), `W12-F004` (P1), `W12-F008` (P1),
`W03-F006` (P2), `W30-F019` (P2) — plus 3 P3 records including two verified-working
(`W27-F008`, `W27-F009`) — 10 findings.

> **This is not closed by P0-1, and assuming it is would be the most expensive mistake in this
> roadmap.** `W12-F002`'s reproduction runs the real `buildRows` + `marketAction` against
> `curl http://127.0.0.1:8000/api/data` — the canonical board, *without* the TEP override in play
> — and still returns 32 of 35 top-250 TEs as SELL. `frontend/lib/display-helpers.js:160-166`
> takes plain arithmetic means of **raw ordinal ranks** with no percentile or within-position
> normalisation, even though `sourceRankMeta[*].percentile` is already stamped on every row
> (`W12-F002` verification). ADR-015's correction was inserted at the *value* stage only;
> `W27-F005` names the split explicitly — two different quantities share the name "market gap",
> and only one of them is basis-corrected. Fixing P0-1 restores the value-space curve and leaves
> the rank-space label untouched.

**Problem.** `ktcSfTep` is the only source flagged `is_retail` (`data_contract.py:1030`) and it is
an SF-TE++ board. The other 13–15 sources are mostly base-TE boards drawn from pools of unequal
depth (ktcSfTep 473 rows, idpTradeCalc 901, dlfSf 278, fantasyProsFitzmaurice 298). Differencing
raw ordinals across those pools measures format basis and pool depth, not opinion.

**User impact.**
- 65 of 73 TEs with a verb are SELL, 4 BUY. Inside the top 250: **32 SELL / 3 HOLD / 0 BUY, and
  all 32 top-250 SELL labels on the entire board are tight ends** (`W12-F002`,
  `evidence/W12/label-matrix.csv`). `/edge`'s Sell panel is 9 of 10 TEs.
- Kelce, Andrews, Hockenson, Kittle, Pitts and Goedert all carry SELL — into a TE-premium league,
  the format where TEs are worth most.
- The verifier widened this: the same mechanism inverts at QB (46 BUY vs 3 SELL of 71 analysed),
  because shallower expert pools compress every rank to a lower number. **≥111 players** carry a
  verb dominated by a measured basis or pool offset, not 65.
- The verifier also computed the full per-source matrix: **all 15 non-retail sources** rank TEs 31
  to 62 ordinal places worse relative to KTC than they rank QB/RB/WR, with zero exceptions. A
  per-player opinion difference cannot be unanimous across 15 independent boards in one position.
- `/rankings` carries **no** signal at all for any of the 398 IDP rows while `/edge` labels the
  same players from a second, parallel detector (`W27-F001`).
- `/edge`'s Buy and Sell panels rank and headline `sourceRankSpread` — total dispersion across all
  13 sources — under prose saying it is the KTC-vs-consensus gap (`W12-F004`).
- KTC sits on both sides of "KTC versus expert consensus", and `idpTradeCalc` is the "expert" on
  one page and the "market" on three others, because `is_retail` was never set on it and
  `s.get('is_retail')` returns `None` (`W12-F008`).

**Root cause.** The retail/expert taxonomy is a single ad-hoc boolean, and the comparison is done
in a coordinate system (raw ordinals over unequal pools) in which the two sides are not
commensurable. `_compute_market_gap` correctly excludes the retail source from the consensus mean,
so there is no trivial self-comparison — the defect is the units, not the design.

**Required repair.** Recompute the gap as a per-position residual in the already-stamped
`sourceRankMeta[*].percentile` space, or in basis-corrected value space (retail value vs blended
value, both on the tepp basis). Make the anchor **per market** — `idpTradeCalc` for IDP the way
`src/trade/finder.py:538` already does — and stamp `marketGapMarket` so one backend definition
serves `/rankings`, `/edge` and the popup. Derive the retail set from `correlation_group` plus an
explicit market-vs-expert field and give `idpTradeCalc` one role platform-wide. Interim, if the
rewrite is deferred: suppress the verb for TEs and say why, rather than shipping a signal that is
100 % one-directional.

**Dependencies.** Should land after P0-1 (so the measurement is taken against one board) and after
R6 if the gap moves to value space. Shares its anchor definition with R7's per-market gate.

**Size.** **M** for the per-market + percentile-space gap; **L** if the whole label spine (R10 /
`W12-F003`) is unified in the same change.

**Acceptance test.** The verifier states the falsifier directly: recompute the gap in
`sourceRankMeta[*].percentile` space and show whether the TE SELL concentration survives. Pass
condition — after the fix, SELL labels are distributed across positions roughly in proportion to
each position's share of the board (TEs are 73 of 911 analysed rows, ~8 %), and the top-250 SELL
set is no longer 32-of-32 one position. Second assertion: every IDP row carries a
`marketGapDirection` or an explicit "no market anchor" state, never a bare dash.

---

### P0-3 · R3 — ROS sims run on the oldest season, and absence is coerced to 0.0

**Closes:** `W17-F001` (P0), `W17-F002` (P0), `W20-F002` (P0), plus 8 P2 and 5 P3 ROS findings
(3 of which are verified-working: `W17-F003`, `W17-F004`, `W17-F006`) — 16 findings.

**Three P0 ids, two defects, and `W17-F002` and `W20-F002` are the same line found twice** by two
workstreams (`src/ros/trade_deadline.py:78`); `findings.json` records `duplicatesMerged: 0`, so
both are published.

**Defect A — the sort key (`W17-F001`, size XS).** `luck._season_sort_key(season: str)` does
`int(season)` inside `except (TypeError, ValueError): return 0`. All four ROS call sites
(`src/ros/playoff_sim.py:464,546,562`, `src/ros/power_v2.py:325`) hand it a `SeasonSnapshot`
**object**, so `int()` raises `TypeError`, the key is 0 for every season, `sorted()` is a stable
no-op on a newest-first list, and `[-1]` returns the **oldest** season. Live: the sims resolve
`current_season = 2024`, status `complete`, 8 owners — the whole 2025 season is loaded and
ignored. Every other module in the repo passes `s.season` correctly (`luck.py:193`,
`power.py:79`, `weekly_recap.py:613`); only `src/ros/` does not.

**Defect B — absence as measurement (`W17-F002` = `W20-F002`, size S).**
`po = float((playoffs.get(owner) or {}).get('playoffOdds') or 0.0)` cannot distinguish "missed the
playoffs" from "not in the simulated season". Four of twelve managers (Brent, Kich, Blaine,
jstuedle) joined after 2024, are absent from the 8-row sim, and receive a confident **0.0**.
`classify_team` (`src/ros/direction.py:104-108`) reads only playoff odds, championship odds and
roster age — it binds `strength_pct` and uses it **only in a summary f-string at line 120**, never
in the band ladder.

**User impact.** On `/league?tab=rosTradeDeadline`, rendered verbatim in a real browser:

> `Brent  0.0%  0.0%  100.0%  Seller  Sell aging win-now players. Prioritize 2026/2027 picks and
> 23-or-younger upside.`

Brent is rank 1 of 12, `teamRosStrength` 645.12, ROS strength percentile **100 %** — the strongest
roster in the league, told to sell its win-now players, with the 100.0 % printed in the column
immediately to the left of the word *Seller*. Collin (75th percentile) is also Seller; Roy (25th
percentile) is "Hold / Evaluate" because he made the 2024 playoffs. The page is a **public**
prefix (`frontend/lib/public-routes.js`) and reproduces anonymously at HTTP 200 — reach is wider
than the finding claimed. The only on-page disclaimer is a *scope* note ("does not affect dynasty
values or trade math"), not an accuracy one; the rendered DOM contains no "not simulated" / "no
read" / "coverage" string anywhere (`W20-F002` verification). The playoff and championship numbers
on the same page are a replay of a regular season that ended ~20 months ago.

`data/ros/sims/latest_playoff.json` and `data/ros/team_strength/latest.json` are git-tracked and
were written by commit `ad56b082` "chore: automated data refresh 2026-08-04" — production data,
not container state.

**Root cause.** A type mismatch swallowed by a bare `except`, and an `or 0.0` that turns absence
into a measurement. Both are the same underlying habit: a silent fallback where the honest answer
is "unknown".

**Required repair.**
1. `key=luck._season_sort_key` → `key=lambda s: luck._season_sort_key(s.season)` at all four call
   sites.
2. **Ship the preseason guard in the same change.** The verifier flags this explicitly: after
   step 1 the newest season (2026) has zero scored games, so without a guard the fix "turns a
   confidently wrong board into an empty one with no explanation" (`W17-F001`
   `whatWouldSettleIt`). This is the same guard R10 / `W30-F002` needs.
3. Return `None`, not `0.0`, for an owner with no sim row; render "not simulated"; surface sim
   coverage (8/12) on the section. `src/api/gameplan.py:807` already does exactly this —
   `oddsSource='owner_not_in_simulation'` with null odds (`W20-F002` whatWorks). Two modules read
   the same file; one is honest and one is not.
4. Either give `team_ros_strength_percentile` a real branch in `classify_team` or delete the
   parameter.

**Dependencies.** Step 2 is shared with R10. `rosPower` carries the identical sort defect at
`power_v2.py:325` but its affected component has effective weight 0 in preseason — latent today,
live once the season starts, so fix it now rather than rediscovering it in September.

**Size.** **XS** for defect A, **S** for defect B. Combined **S**.

**Acceptance test.**
- `sorted(snapshot.seasons, key=...)[-1].season == '2026'` on the live snapshot.
- With zero scored weeks, the ROS playoff and championship sections publish no odds and say so.
- Assert in a test that an owner absent from `data/ros/sims/latest_playoff.json` never receives a
  Buyer/Seller label (`W17-F002` `whatWouldSettleIt`).
- No rendered row shows a directional verb beside a `0.0%` that was never simulated.

---

### P0-4 · R4 — Draft slot count clamped to a pre-fetch default

**Closes:** `W10-F002` (P0), `W10-F001` (P1), `W10-F003` (P1), `W10-F004` (P1), plus 8 P2 and 6 P3
draft findings — 18 findings.

**Problem.** `frontend/lib/draft-logic.js:1427-1431` computes
`initialSlots = Math.min(feedSlots, DEFAULT_INITIAL_SLOTS)` with `DEFAULT_INITIAL_SLOTS = 6`
(`:53`) applied to the **live feed** branch — directly contradicting the constant's own docstring
at `:47-52`, which says the per-team count is pulled from `/api/draft-capital` and the default
applies only to a pristine pre-fetch workspace.

**User impact.** Live `/api/draft-capital` reports Russini Panini owning **31** of the league's 72
picks and CollinFoz 7; both clamp to 6, and total board slots collapse from 72 to 46. `myTeamIdx`
defaults to 0 and `DEFAULT_TEAMS[0]` is Russini Panini, so **the clamped team is the user's own
team on the default path**, auto-populated on mount with no button press. Rendered DOM: the Teams
panel prints `0/6` and `MDV $114` for a $685 / 31-pick team (true $/slot is $22.10, a 5.2×
error); the header prints `Pick 0 of 46` and `PHASE 6 of 6 slots`. After six picks the app
declares the draft over — slots 0, effective budget $0, phase multiplier pinned at its 1.5×
maximum — while $679 and 25 picks are still live.

The verifier corrected two secondary claims downward, both in the record's favour: the "Spend up"
recommendation does **not** fire (the gate needs `mdv > 10` and mdv collapses to 0), and the
distortion on the next live player after six picks measured `maxBid $4` vs `$2` true — a 2× error,
not the 1.37× the finding computed, with a non-uniform sign across the pool.

**Root cause.** One `Math.min` against a constant named `DEFAULT_` used as a maximum. In a league
with pick trading the number of picks a team owns is unbounded above.

**Required repair.** Delete both `Math.min(..., DEFAULT_INITIAL_SLOTS)` clamps in `buildTeam()`;
keep the constant strictly as the pre-fetch fallback its docstring describes. **The repair must
also delete a test assertion**: `frontend/__tests__/draft-logic.test.js:1291` is titled
"…CAPPED AT DEFAULT_INITIAL_SLOTS" and pins the wrong behaviour (`W10-F002` verification). The
repo carries two contradictory declarations of intent — docstring and test — and only one can
survive.

**Dependencies.** `W10-F001` (clamp every emitted bid by the user's remaining budget) must land
**after** this, or the affordability clamp is built on the wrong slot count. `W10-F003` (a real
constrained optimizer, size L) depends on both plus a per-player expected clearing price that is
not a league-wide constant.

**Size.** **S** for the P0 (two `Math.min` deletions plus a test). **M** for `W10-F001`, **L** for
`W10-F003`.

**Acceptance test.** `node evidence/W10/probe-slot-cap.mjs` returns `initialSlots 31` for Russini
Panini and `totalInitialSlots 72`; the rendered header reads `Pick 0 of 72`; `MDV` reads `$22`;
and no emitted bid exceeds the user's remaining budget.

---

### P0-5 · R5 — FAAB blends raw dollars across three budget regimes

**Closes:** `W11-F001` (P0), `W11-F003`, `W11-F004`, `W11-F005`, `W11-F006`, `W11-F007` (P1),
plus 7 P2 and 9 P3 FAAB findings (2 verified-working: `W11-F019`, `W11-F020`) — 22 findings.

**Problem.** `src/api/faab_analytics.py::_walk_waivers` (`:143-172`) flattens **every** season's
transactions into one bid list with no budget normalization, while `_league_budget` (`:102-121`)
returns only the current season's budget. The live snapshot covers 2026 (`waiver_budget` 100),
2025 (200) and 2024 (**1000**).

**User impact.** `positionBids['RB'].avg` is **$43.00** — a mean over bids denominated in three
different currencies — with a `max` of **$340**, physically impossible in a $100 league.
Independent per-season normalization returns **$8.58**, the finding's expected value to the cent.
`src/trade/faab_recommender.py` blends that anchor 50/50 into every RB bid
(`_LEAGUE_CALIBRATION_BLEND = 0.5`, fires whenever `count >= 3`, which is true for all 8
positions). A user on `/waivers` is told to bid $22–$32 of a $100 budget on replacement-level
running backs, and the contaminated calibration is presented to them **as evidence** — the factor
renders as `+$12` and `warnings` is empty.

The verifier corrected the scope upward twice: it is not RB-only (WR anchor 20.84 vs 4.40 true;
QB 37.74 vs 10.11), and blast radius is 930 of 1,092 contract rows — every row in a position with
≥3 historical bids — not the 283 the finding recorded. `leagueAvgWinningBid` ($19.55) and
`leagueMedianWinningBid` ($5.00 vs $2.00 normalized) are contaminated by the same mixing and feed
`_env_scale_factor`.

**Root cause.** `_league_budget()` is scalar and current-season-only; `_walk_waivers()` is
multi-season. The two are combined without a per-season divisor.

**Required repair.** Carry each bid's season `waiver_budget` through `_walk_waivers`, express
every bid as a share of its own season's budget, and re-multiply by the current budget before it
reaches `positionBids`, `leagueAvgWinningBid`, `leagueMedianWinningBid`, `teamAggression` and
`tierBids`.

**Dependencies.** This alone drops RB recommendations from ~$32 to ~$15 and unpriced-RB
recommendations from $22 to $4 — but `W11-F002` (unpriced players recommended $22–$25 as "strong
free-agent targets"; 125 of 283 free agents) survives at a lower number and must be fixed with it.
`W11-F004`'s non-monotonicity (8,362 of 39,903 free-agent pairs invert, worst case a $21 swing in
favour of the *lower*-valued player) is caused by the additive 0.5 blend on a position constant
and is only partly relieved by correcting the constant — the blend must become a multiplier.

**Size.** **M** for the P0. The full FAAB cluster is **L** (`W11-F003` alone is L: the bid formula
is pool-relative and structurally confined to 5–30 % of budget, so no player anywhere justifies an
all-in bid).

**Acceptance test.** `positionBids` reports RB ≈ $8.58 on a $100 budget and no `max` exceeds the
current league budget; `/api/public/league/faabAnalytics` and `/api/waiver/faab-recommend` agree;
and a monotonicity sweep over the free-agent pool returns 0 inversions.

---

## P1 — 86 findings across 24 root causes

The five P0 root causes above already carry **14** of the P1 findings (R1 2, R2 4, R4 3, R5 5;
R3 carries none). Those are scheduled with their root cause and are not repeated here. The
remaining **72** P1 findings sit in 20 root causes, presented below in 19 entries — R25 and R26
share one entry because their repair is the same pass.

---

### P1-1 · R6 — Percentile denominators and curve scopes disagree

**Closes:** `W30-F008`, `W02-F001`, `W02-F002`, `W02-F003` (P1); `W02-F004`, `W02-F005`,
`W02-F006`, `W02-F009`, `W03-F007` (P2); 10 P3 including 4 verified-working — 19 findings.

**Problem.** Two independent scale errors sit under every displayed value.
- `FIT_TOP_N = 400` and `_PERCENTILE_REFERENCE_N = 500` are unrelated constants with no assertion
  tying them together. The fit maps rank *i* to *p = i/399*; serving maps rank to
  *p = (rank−1)/499*. Under the champion OFFENSE constants (c=0.11, s=1.11) the same rank serves
  **13.2 % high at rank 50, 18.5 % at 100, 25.4 % at 400** (`W30-F008`, upheld).
- IDP-only sources are ladder-translated into **combined-pool** coordinates, divided by the
  combined-pool 500, then routed by `scope` to the IDP master fit on an IDP-only slice. At
  percentile 0.0661 the IDP master pays 5627 where the value-direct anchor pays 6444; the four IDP
  rank-signal sources contribute a median 0.461–0.485 of `idpTradeCalc`'s contribution at the same
  effective rank (`W02-F001`).

**User impact.** Three sources that rank Aidan Hutchinson their #1 IDP are shown, in the
`/rankings` value-chain panel, as valuing him 13 % *below* the one source that ranks him 34th. A
user reads real disagreement where there is a units error. Downstream, the Hampel filter ejects
the designated IDP market anchor on 29.4 % of Hampel-eligible IDP rows and in **52 of 52 cases for
being HIGH** (`W02-F002`), and the corridor clamp rewrites 43.3 % of ranked IDP rows to exactly
`idpTradeCalc × 0.85` or `× 1.15` with the per-bucket P90 machinery inert — the 0.15 cap binds on
**100 %** of clamps (`W02-F003`).

**Root cause.** No single place owns the coordinate system. Fit denominator, serve denominator,
ladder translation and curve routing were each chosen locally.

**Required repair.** Assert `FIT_TOP_N == _PERCENTILE_REFERENCE_N` and pick one. Key
`_curve_for_source` on whether the effective rank was ladder-translated
(`sharedMarketTranslated` / `needs_rookie_translation`) rather than on `scope`.

**Warning from verification.** `W02-F001` was **rescoped**, and the verifier found the finding's
own prescribed repair insufficient: the GLOBAL counterfactual returns per-source medians of 0.92,
0.92, 1.29 and 1.32 — a *wider* spread than the offense control band — and there is a second,
compounding defect: `_percentile_pairs` renormalises the IDP slice so the best IDP = 9999, but the
best IDP's anchor value on the live board is 6444, so the IDP master is fit in units **1.552× the
scale its output is consumed in**. The combined-pool injection is currently deflating an
over-scaled curve back toward the anchor. **Two defects are compounding; the naive re-route moves
affected IDP rows up a median 8.9 % (p90 42 %) with no validation.** Do not ship the one-line
version. Also: the finding's `playersAffected: 398` counts all DL/LB/DB rows; only **281** carry
an IDP rank-signal vote.

**Dependencies.** Must land before R2 if the market gap moves to value space, and before any
re-measurement of R21's holdout criterion — `W30-F008` establishes that the holdout RMSE gating
promotion (787.84) is not a measurement of the served board's error.

**Size.** **L.** `W30-F008` alone is L; `W02-F001` is M but must be re-derived, not applied.

**Acceptance test.** A test that imports both constants and asserts they agree. A per-source
contribution ratio at identical effective rank of ≈1.0 for IDP rank-signal sources against
`idpTradeCalc`, measured with the renormalisation defect fixed — not the GLOBAL re-route alone.

---

### P1-2 · R7 — One global top-N gate over a cross-class value scale

**Closes:** `W09-F001`, `W09-F004`, `W27-F002`, `W09-F002`, `W27-F003` (P1); `W09-F008`,
`W09-F009`, `W09-F012`, `W27-F004`, `W27-F012`, `W27-F007` (P2); 4 P3 including 2
verified-working — 15 findings.

**Problem.** `build_asset_pool_from_contract` cuts the top 150 over **one** population on a value
scale where offense peaks at 9999, IDP near 6400 and the best DB at 3159. `src/trade/finder.py`
identified this exact failure and fixed it with a per-market cut; `suggestions.py` never got the
fix and documented the global cut as safe.

**User impact.** The top-150 pool is WR 41, QB 28, RB 26, PICK 23, TE 18, DL 7, LB 7, **DB 0**.
The first DB in the 812-row pool is Caleb Downs at board rank 167. Consequences:
- **Zero suggestions for 8 of 12 live teams** (Ed, Ty, Collin, Roy, Joey, Kich, jstuedle, Blaine),
  with no diagnosis in the payload; `rosterMatched` is 3–21 of the 44–58 players actually rostered
  (jstuedle 3/44), so the engine analyses 5–36 % of the roster it was handed (`W09-F001`, authored
  P0 → verified **P1**).
- `/trade` renders a red "Should target DB" badge to **all 12 managers** while every team already
  rosters 5–9 DBs — 167–300 % of the starters needed (`W27-F002`, authored P0 → verified **P1**).
- `/angle` can never return an IDP player in a counter-package: `include_idp` defaults False and
  the page never sends the flag, in a league that starts 9 IDP (`W27-F003`).
- Every trade the arbitrage finder returns is a 1-for-2; 1-for-1 candidates rank 2,159th and
  2-for-1 never qualifies, because `board_gain_norm` normalises against the give side only
  (`W09-F002`).

**Root cause.** A quality gate defined over a scale that is not comparable across asset classes,
plus a per-market fix that was applied in one engine and not the other two.

**Required repair.** Apply the top-N cut per position family or per asset class in
`_apply_board_top_n_filter`, mirroring `finder.py`'s `market_groups`; stamp per-family counts in
metadata. Make `rosterAnalysis.starterCounts` count the whole roster, not pool members, or
suppress `needPositions` for any family with zero pool coverage. Derive `include_idp` from the
league's `roster_positions` rather than a constant. Normalize `board_delta` against the larger of
the two sides.

**Dependencies.** None on data. Interacts with R8 (picks must be in the pool at all) and R6 (the
cross-class scale itself). The gate fix is independent of and prior to the scale fix — a
per-family cut is correct regardless of what the scale does.

**Size.** **M.**

**Acceptance test.** The 150-asset pool contains a non-zero count for every position family the
league starts; no team returns `totalSuggestions: 0` without an explicit
`coverage insufficient` warning naming `rosterMatched`/`rosterProvided`; the finder's returned
package shapes include 1-for-1 and 2-for-1.

---

### P1-3 · R8 — Draft picks are name-keyed second-class assets

**Closes:** `W08-F005`, `W09-F003`, `W13-F002`, `W20-F004`, `W20-F005`, `W05-F006`, `W08-F004`
(P1); `W06-F008`, `W08-F006`, `W13-F004` (P2); `W00-F008` (P3) — 11 findings.

**Problem.** Picks have no structured identity on the live path. Season, round and slot exist only
as substrings of a display name, re-parsed by at least nine call sites (`W06-F008`). Every
consumer then invents its own join.

**User impact.**
- 53 of 216 league picks collapse onto a duplicate display name in the trade calculator, and the
  duplicate guard then makes them **untradeable** (`W08-F005`).
- Zero picks appear in any of the 480 trades the finder returned, for any of the 12 teams —
  `_resolve_roster` (`finder.py:621`) reads only `t['players']`, and the picks live in the sibling
  keys `t['picks']` / `t['pickDetails']` (`W09-F003`). Player-plus-pick and pick-for-player are
  the two most common dynasty trade shapes and neither is proposable.
- Current-year picks cannot be found in the trade calculator's only search box — a hardcoded
  `/^2026\b/` regex at four call sites rather than the contract's `currentDraftYear` (`W08-F004`).
- `frontend/lib/portfolio-insights.js` prices every current-year pick at **zero** — 15,626 per
  team, 187,512 league-wide, **39 % of all pick capital** — because it is the one pick join in the
  tree that ignores the contract's own `pickAliases`; `resolvePickRow` is already exported from a
  module it imports (`W20-F005`).
- `PortfolioSummary` renders a Total Value of 171,495 beside three legend numbers summing to
  314,562, because the server excludes picks and the client includes them, both deliberately and
  documented (`W20-F004`).
- BDVM strategy capitals and its double-positive trade scan exclude every pick, omitting 8–52 % of
  rebuilder capital and flipping 2 of 12 direction labels (`W13-F002`).
- Only 2 of 21 sources cast any vote on any pick; all 72 slot picks are single-source, and a fresh
  KTC pick value sits unread in `canonicalSiteValues` under the demoted non-voting `ktc` key
  (`W05-F006`).

**Root cause.** Assets are keyed by display **name** throughout the trade builder and the
portfolio path, and picks have no unique name. The contract publishes `pickAliases` for exactly
this and only some consumers read it.

**Required repair.** Give trade assets a stable id — `playerId` for players,
`${season}-${round}-${original_roster_id}` for picks — and key trade sides on it. Route every pick
join through `resolvePickRow(name, lookup, pickAliases)`. Extend `_resolve_roster` to concatenate
`t['players']` with `t['picks']`. Stamp `pickAnchors` under `ktcSfTep` as well as `ktc`. Pick one
asset scope for the portfolio total and make server and client agree.

**Dependencies.** `W20-F005` is a one-line import swap and can ship immediately. The stable-id
change is prior to everything else in this cluster. Pricing a from-team pick *differently* needs a
projected-standings input the platform does not have — the identity fix is independent of and
prior to that.

**Size.** **M** overall; **XS** for `W20-F005`, **S** for `W08-F004` and `W09-F003`.

**Acceptance test.** Two picks with the same display label and different original owners can both
be added to a trade; a finder run for each of the 12 teams returns at least one package containing
a pick; `portfolio-insights` and `/api/terminal` report the same total for the same team.

---

### P1-4 · R9 — Unpriced is coerced into a confident number

**Closes:** `W07-F003`, `W07-F004`, `W19-F003`, `W20-F010`, `W09-F005`, `W25-F003` (P1);
`W09-F016` (P2); 3 P3 including 1 verified-working — 10 findings.

**Problem.** The codebase has no shared representation for "we could not price this". Absence is
written as `0`, as an invented ordinal, or as a flat band.

**User impact.**
- 222 rows on the live board display a client-invented ordinal in the `#` column
  (`dynasty-data.js:1402` treats "backend left this unranked" and "legacy payload with no stamps"
  as one case), and the board then **fabricates a tier, a positional rank, a confidence badge and
  an actionable BUY/SELL verdict** for players it declines to price (`W07-F003`, `W07-F004`).
  CLAUDE.md attributes these rows to the 800-rank limit; the board never reaches 740, and every
  one of them is unpriced (`W25-F003`).
- Public trade letter grades silently drop **224 of 1,708 traded asset slots (13.1 %)** — including
  20 first-round-pick slots — and still emit a confident "Robbery"/"Fleeced" badge (`W19-F003`).
- `/api/gameplan` reports roster market / consensus / leagueAdjusted / pickValue as **0.0 for all
  12 teams** while the same payload reports `marketPriceCoverage 627 of 666 priced` (`W20-F010`).
- Monte Carlo uncertainty is a hard-coded flat ±15 % on zero live rows — `valueBand` is never
  stamped by any producer, so the documented input does not exist and the degradation path became
  the only path (`W09-F005`, rescoped under verification, severity held at P1, status *Mocked or
  hard-coded*).

**Root cause.** `0` and `None` are used interchangeably, and every display field keys off a value
that has been filled in rather than left absent.

**Required repair.** Establish the posture the codebase already ships in two places
(`src/trade/finder.py`'s `metadata.assetsUnpricedByBoard`, and `src/api/gameplan.py`'s
`oddsSource='owner_not_in_simulation'`) as the platform rule: valuation callables return `None` for
unpriced and `0.0` only for genuinely worthless; unpriced counts are stamped per side/per payload;
`r.rank = null` for unpriced non-pick rows so the `#` column renders its existing `-`; verdicts
gate on `rankDerivedValue` being non-null.

**Dependencies.** This is the enabling change for R3 step 3, R10, R11 and R19's honest degradation.
It should land early precisely because so much later work needs somewhere to put "unknown".

**Size.** **M** as a cross-cutting convention; each individual site is XS–S.

**Acceptance test.** No page renders a tier, positional rank, confidence badge or directional verb
on a row whose `rankDerivedValue` is null; every grade/score computed over a partially unpriced set
carries an `unpricedAssetCount` and is suppressed or badged partial when non-zero.

---

### P1-5 · R10 — Preseason and zero-evidence states are not gated

**Closes:** `W19-F004`, `W30-F002`, `W30-F001`, `W30-F003`, `W12-F007`, `W12-F005`, `W12-F006`,
`W12-F001`, `W12-F003` (P1); 9 P2; 3 P3 including 1 verified-working — 21 findings.

**Problem.** Two related failures: engines publish certainty from zero evidence, and directional
labels are never gated on the evidence behind them.

**User impact.**
- Eight 2026 awards are manufactured from a season with **zero scored games**: "Points King:
  Jason, 0.0 PF", "Regular-Season Crown: Jason, 0-0", "League MVP: Justin Jefferson, 0.0 VORP"
  (`W19-F004`).
- Both playoff-odds engines publish 100 %/0 % certainty with zero games played and 14 weeks
  remaining, and the convergence check passes on it (`W30-F002`).
- Two playoff-odds engines serve the same tab and disagree on the league's structure — 7 playoff
  spots vs 6, 12 teams vs 8, opposite verdicts for two managers (`W30-F001`). Two power-ranking
  engines rank the same league on the same tab — 10 teams vs 12, mean rank shift 2.8, one manager
  moves from last to third (`W30-F003`).
- **253 of the 356 directional verbs on `/rankings` sit on rows the same page badges low or no
  confidence**, and 102 rest on a "consensus" of two sources or fewer (`W12-F007`).
- Clicking a `/rankings` row opens a popup whose verdict contradicts the Edge column on that same
  row — 83 rows, including Brock Bowers (#2), Bijan Robinson (#3), Drake Maye (#5), Jahmyr Gibbs
  (#6), Trey McBride (#8), Lamar Jackson (#11) — because `marketAction` requires a 10-rank gap and
  `getPlayerEdge` requires 3, in two files with no shared constant (`W12-F001`, authored P0 →
  verified **P1**).
- No central Buy/Sell Tracker exists: **16 directional emitters, 14 reachable, 5 competing
  thresholds on the same quantity** (`>0`, `>=3`, `>=10`, `sourceRankSpread>=20 AND rank<=250`,
  and `>=10` on a different source set), none importing another. Both consolidation attempts are
  unreachable — one flag-off, one caller-less (`W12-F003`, rescoped under verification, severity
  held at P1, size XL).
- The 12-hour signal-alert cooldown is keyed on the rule **tag**, so it never engages when the
  reason changes — which is exactly what changes when a signal flips (`W12-F005`); and three
  independent email detectors can alert on the same player, the same day, to the same address,
  with three cooldown namespaces and no cross-check (`W12-F006`).

**Root cause.** No engine has a "not enough evidence" output state, and every surface that wants a
verb wrote its own threshold instead of consuming one.

**Required repair.** Refuse to publish odds when `weeksPlayed == 0`. Gate every season-scoped award
on `weeksScored > 0`. Move `MIN_EDGE_RANK_GAP` into `frontend/lib/thresholds.js` and have both
emitters read one constant. Give `marketAction` / `getPlayerEdge` a confidence argument and render
an explicit "thin evidence" state. Promote the retail-vs-consensus family to a single
backend-stamped verb computed once in `_compute_market_gap` and demote the other emitters to
explicitly labelled secondary lenses. Split the alert cooldown key from the dismissal key and
introduce one per-(user, league, sweep) digest.

**Dependencies.** The single-verb consolidation depends on R2 — there is no point making one
definition authoritative while that definition measures TE basis. The preseason guard is shared
with R3.

**Size.** **S** for `W12-F001` and the preseason guards individually; **XL** for the tracker
consolidation (`W12-F003`).

**Acceptance test.** A test asserting `marketAction(row).label` and `getPlayerEdge(row).signal`
never disagree on a real contract. With zero scored weeks, `/league` publishes no odds, no awards
and no power ranking, and says why. No row carries a verb while badged low/no confidence.

---

### P1-6 · R11 — Team direction, strength and power computed many ways

**Closes:** `W20-F006`, `W20-F007`, `W20-F008`, `W20-F003`, `W20-F001` (P1); 10 P2; 1 P3
verified-working — 16 findings.

**Problem.** Four independent team-direction classifiers ship simultaneously, three are reachable
by a user, none references the others, and they disagree on **9 of 12 teams** (`W20-F006`).
"Contender" is computed six different ways across six surfaces from four unrelated input families
(`W30-F016`). Team total value is computed three ways, and the two simple sums differ by pick
capital — **22.5 % of a portfolio** on the live snapshot (`W30-F017`).

**User impact.** `/rosters` shows two contradictory rankings of the same 12 teams on one screen —
Jason is #1 in the power table and #5 "Mid-Tier" in the tier cards 400 px below (`W20-F007`).
`/phases` classifies **zero** teams as "Rebuild" on live data, so its headline trade-partner
feature renders nothing and the page never says why (`W20-F008`). Terminal "roster strength" is the
raw sum of `rankDerivedValue` — no lineup solve, no starter/depth weighting, no positional deficit,
picks excluded entirely — while `frontend/lib/starter-slots.js::fillLineup` already performs the
solve on the same data (`W20-F003`). And `GET /api/gameplan` plus all 4,385 lines of
`src/roster_intel/` have **zero** frontend consumers (`W20-F001`).

**Root cause.** Each surface grew its own model. No shared definition module was ever nominated.

**Required repair.** Nominate one classifier (`window.py` is the best of the four per `W20-F006`)
and make the other three read it or be deleted. Either rename Terminal's number to "portfolio
value" or add the lineup solve. Decide `/api/gameplan`'s fate — build the surface or mark the
module set explicitly internal-only (see *Deprecate rather than repair*).

**Dependencies.** R9 (so "not classifiable" is expressible), R8 (so pick capital is in the sums),
R3 (so ROS strength is a real input). Choosing a winner before the inputs are trustworthy picks
the winner on noise.

**Size.** **L.**

**Acceptance test.** One classifier module; a grep proving no second direction ladder exists; every
surface stamps which engine produced its number; `/rosters` renders one ordering or labels both
with their formula.

---

### P1-7 · R28 — Trade value concepts collide under one field name

**Closes:** `W29-F001`, `W29-F002`, `W09-F006`, `W08-F002`, `W08-F003`, `W08-F007` (P1); 7 P2;
7 P3 including 4 verified-working — 20 findings.

**Problem.** `/api/trade/suggestions` serializes two different value concepts under one field
name. The offense-only board is a legitimate second concept (an IDP-disabled re-run) but it is
written into the field the board value owns, so the response cannot say which is which.

**User impact.** Travis Hunter shows **5,637** on `/trade` and **4,401** on `/rankings`
(`W29-F001`). `valuationMode: leagueAdjusted` is stamped on responses where **41 % of asset legs
are still priced on the unadjusted market board** (`W29-F002`, rescoped under verification,
severity held at P1), and the lens is a silent no-op on every all-offense trade in `/api/trade/simulate` and
`/api/trade/finder` because those engines read `offenseOnlyRankDerivedValue`, which
`overlay.adjusted_rows` never scales (`W09-F006`, upheld). Separately, adding a positive-value
asset to your side can **lower** your side's total and flip the verdict against you — the fairness
gap is non-monotonic in 1.1–1.9 % of trades (`W08-F003`); the Value Adjustment tooltip says the
bonus goes to "the side with fewer pieces" while 46.7 % of fired VAs go to a side with equal or
more pieces (`W08-F002`); and one dropdown click into "Raw" mode turns a FAIR trade into UNFAIR
and flips which side wins, because raw composites are normalised within each source's own board
(`W08-F007`).

**Root cause.** `tests/api/test_valuation_mode_threading.py` asserts that handlers *stamp* the
mode, not that the served numbers moved. The invariant "every engine reads exactly one value" is
false and nothing enforced it.

**Required repair.** Either drop the offense-only branch in `_serialize_player` or emit it as a
distinct key with a per-suggestion `valueBasis` stamp. Scale `offenseOnlyRankDerivedValue` in
`overlay.adjusted_rows`. Stop folding the VA into `adjusted` and render it as KTC does, or clamp
so adding an asset can never reduce a side's adjusted total. Gate or remove Raw mode in the
calculator.

**Dependencies.** R9 for the unpriced posture; R6 for cross-class comparability.

**Size.** **M.**

**Acceptance test.** Add an assertion to the threading test that at least one served value differs
between `market` and `leagueAdjusted` for a roster with known non-unit factors. Assert
monotonicity: adding any positive-value asset to a side never decreases that side's adjusted total.
Assert one player renders one number across `/trade` and `/rankings`.

---

### P1-8 · R12 — Auth, rate-limit and public-surface boundaries

**Closes:** `W22-F001`, `W22-F002`, `W22-F003`, `W00-F001` (P1); `W22-F004`, `W22-F005`,
`W22-F007`, `W26-F008`, `W01-F010` (P2); 4 P3 — 13 findings.

**Problem and impact.**
- `_sanitize_next_path` uses a four-prefix denylist and does not reject a backslash.
  `/login?next=/\evil.com` survives verbatim; Next resolves it with the WHATWG parser, which maps
  `\` to `/`, and **the browser was driven end to end in Chromium to a top-level navigation to
  `http://evil.com/` immediately after a successful login** (`W22-F001`, size XS). That is a
  working credential-phishing amplifier on the real domain.
- The rate limiter keys on the first entry of a client-supplied `X-Forwarded-For` with no
  trusted-proxy check. nginx uses `$proxy_add_x_forwarded_for`, which **appends**, so the first
  entry is attacker-controlled. Measured on a second backend without the bypass: the real client IP
  was driven to a hard 429 and 20 consecutive requests from the same socket with rotating
  `X-Forwarded-For` all returned 200 (`W22-F002`, upheld).
- Login has no throttle of its own, no lockout, no backoff: **200 wrong-password attempts landed at
  223 req/s with zero 429** (`W22-F003`).
- `/api/draft-capital` returns 200 with a 15,989-byte board of per-pick dollar values to an
  anonymous caller in 13,188 ms, while 47 of 66 probed GET routes correctly 401 (`W00-F001`).

**Root cause.** A denylist where an allowlist is required; a hop-by-hop header trusted
unconditionally; and one route that never got the auth dependency its peers have.

**Required repair.** Parse-and-compare the redirect target (`urlsplit`, reject unless scheme and
netloc are empty and the value starts with `/`, after normalising backslashes). Prefer
`X-Real-IP` — nginx sets it from `$remote_addr` and **overwrites**, so it is not client-controlled
— and fall back to `request.client.host`. Add a per-username failure counter with backoff and
lockout, keyed independently of IP. Apply the standard auth gate to `/api/draft-capital` and bound
the Sleeper team-name lookup.

**Dependencies.** None on anything else in this roadmap. nginx already sets `X-Real-IP` in both
`location /api/` and `location /`, so no deploy change is needed (`W22-F002`). `W22-F003`'s
IP-side half is worthless until `W22-F002` lands.

**Size.** **XS** (`W22-F001`), **S** (`W22-F002`, `W00-F001`), **M** (`W22-F003`).

**Acceptance test.** `/login?next=/\evil.com`, `/\/evil.com`, `/%5Cevil.com` and `/\t/evil.com` are
all rejected. Rotating `X-Forwarded-For` does not lift a 429 on a backend without
`RATE_LIMIT_BYPASS_IPS`. N consecutive failed logins for one username produce a 429 and an alert.
`/api/draft-capital` 401s anonymously.

---

### P1-9 · R13 — Source ingestion failures are invisible

**Closes:** `W05-F001`, `W05-F003`, `W05-F004` (P1); 17 P2; 9 P3 including 3 verified-working —
29 findings, the second-largest cluster.

**Problem.** The board blends 21 sources. Nothing that watches it can see 21.
- `/tools/source-health` lists **4 of 21** and renders IDPTradeCalc as 0 rows from a case-mismatched
  lookup (`W05-F001`, `W23-F007`).
- `/api/status.source_health` reports `total_sources: 2` (`W05-F002`, `W23-F008`) — a 19-source
  outage would not move it.
- The schema probe covers **4 of 22** sources, so a vendor header rename drops a source from the
  board with an **empty** `sourceParseErrors` (`W05-F003`).
- **9 of 21 sources have no row-count floor**: deleting `ktcSfTep` — the retail anchor, 501 rows —
  from the whole board leaves `contractHealth` "healthy" with zero errors (`W05-F004`).
- A partial scrape the promotion guard **refuses to publish** is recorded as a success, with the
  same event name and the same `last_success_at` (`W23-F002`, authored P1 → verified **P2**), and
  the "fewer than half the sites returned" guard degenerates to "block only on total loss" because
  `sites` carries 2 entries (`W23-F003`, authored P1 → **P2**).
- `data_age` on `/api/metrics` and `/api/health` measures time since the **process loaded the
  file**, not since the data was scraped (`W23-F006`, authored P1 → **P2**).

**Root cause.** Monitoring was built per incident, against the scraper's 4-item internal
vocabulary, rather than against the registry that defines the board.

**Required repair.** Drive every health surface from `served_source_coverage` + `health.sources`
(both registry-keyed and already in the payload) through one normalising helper. Make the schema
probe universal — assert one name-alias column and one value-or-rank-alias column per source, emit
`schema_mismatch` otherwise, and `source_empty:{key}` on a clean parse to zero rows. Add row-count
floors at ~80 % of measured counts for the nine unfloored keys, plus a registry-completeness test
that fails when a new source has no floor. Separate "scrape ran" from "scrape published".

**Dependencies.** None. This is the observability layer that makes every other repair verifiable in
production, which is why it is early in the sequence despite being P1 rather than P0.

**Size.** **M.**

**Acceptance test.** Delete any one source CSV and confirm `contractHealth` reports an error naming
it; rename a header and confirm `schema_mismatch`; confirm `/tools/source-health` and
`/api/status.source_health` both enumerate all 21 registry keys.

---

### P1-10 · R14 — Identity resolution is name-based end to end

**Closes:** `W06-F001`, `W06-F003` (P1); 8 P2; 6 P3 including 2 verified-working — 16 findings.

**Problem.** The merge key is a canonical **name** (`Dynasty Scraper.py:4655`), and
`CANONICAL_NAME_ALIASES` has entries for Kenneth→Kenny and Chig→Chigoziem but none for
Matt↔Matthew or Jam↔Jamarion. Two real players occupy two board rows each — a resolved row and an
unresolved ghost — stranding vendor votes on the ghost (`W06-F001`). Both identity-duplicate
detectors on the contract are **structurally unable to fire** and `scripts/audit_identity.py`
renders a permanently empty section (`W06-F002`). `unified_mapper.resolve_player` merges **11
demonstrably different NFL players** at its default threshold on today's corpus (`W06-F006`).
`config/identity/id_overrides.json` cannot influence the board at all, and where it is read the
override loses to the directory it exists to override (`W06-F004`).

`/api/player/{sleeper_id}/realized` returns `unmapped_player` for **every** player: `server.py`
reads `sleeper.players` / `sleeper.playerDict`; the producer emits `sleeper.playerIds` and
`sleeper.idToPlayer`. No writer has ever produced the key the reader asks for, and a rename alone
is not enough — neither surviving key carries a `gsis_id` (`W06-F003`, upheld, size XS).

**Root cause.** Name is the join key, and the ID-based paths that exist are either unread or
outranked.

**Required repair.** Deduplicate `playersArray` on `sleeperId` after enrichment. Add a near-name
split detector (same surname + similarity ≥ 0.85 + exactly one side lacking a `playerId`) that
raises a real flag instead of the hardcoded `nearNameMismatchCount: 0`. Resolve the GSIS id from
`idToPlayer[sid]` plus the nflverse name index, or fetch the Sleeper directory for the mapper.
Alias-table additions treat symptoms, not the class.

**Dependencies.** R8 shares the "stable id, not display name" principle and should be designed with
it.

**Size.** **M.**

**Acceptance test.** No two `playersArray` rows share a `sleeperId`; the duplicate detector fires on
a seeded split; `/api/player/{id}/realized` returns real points for a known player.

---

### P1-11 · R15 — The exact-scoring engine is duplicated and lossy

**Closes:** `W13-F001`, `W18-F003`, `W13-F003` (P1); 3 P2; 13 P3 of which **9 are
verified-working** — 19 findings.

**Problem.** The repo contains a scoring-key-agnostic dot-product engine
(`src/league_intel/scorer.py`) that is **provably exact** — ADR-006's "pure dot product, no
stacking rules" claim was independently reproduced against 1,339 host-scored player-weeks with max
|delta| 0.005 (`W18-F010`) — and a second, allow-list engine
(`src/nfl_data/realized_points.py`) keyed on nflverse column names that **disagrees with the
league host on 36 % of player-weeks** (`W18-F003`). It never reads the six reception-distance
rules and maps `pass_int` / `pass_sack` / `fum_lost` to nflverse columns that no longer exist.
BDVM's "exact league scoring" drops the same six reception yardage-band rules, understating WR
fundamentals **19.7 %** and TE **22.0 %** on real 2025 data (`W13-F001`).

Downstream, the BDVM signal layer saturates at **81.5 % STRONG_SELL** because `calibrate()` anchors
only the board maximum while the signal thresholds are absolute point values (`W13-F003`, size L).

**Root cause.** Two scoring engines, one of which silently degrades in two directions: a live
scoring rule with no entry, and an entry whose column no longer exists.

**Required repair.** Repoint the allow-list engine's stale columns via the existing candidate-tuple
mechanism, add `rec_0_4..rec_40p` from `src/nfl_data/reception_depth.py` or report them as
uncovered rather than silently zero, and emit the set of non-zero scoring keys the scorer did not
consume into the payload meta so coverage is visible.
`src/nfl_data/scoring_coverage.py` already enumerates the gap. Calibrate BDVM on a rank-matched
quantile map, or make `signal_thresholds` percentile-based within the board.

**Dependencies.** None on data. `W13-F003` depends on `W13-F001` — the reception-band omission
pushes pass-catcher fundamentals down and contributes to the negative skew that produces the
saturation.

**Size.** **M** for the scoring engine, **L** for the BDVM calibration.

**Acceptance test.** `realized_points` agrees with the league host on ≥99 % of player-weeks over the
1,339-row fixture. The BDVM signal distribution over a real board is not >50 % one label.

**What is already right here, and should not be touched:** 9 of this cluster's 13 P3 records are
verified-working, including BDVM engine parity against the frozen Appendix-C fixture (13
archetypes × 3 currencies at ±1.0, `W13-F007`), structural market isolation (`W13-F008`), the
aging/survival split (`W13-F009`), and the byte-exact `dynasty_main` league config — 141/141
scoring keys, 58/58 roster slots, 51/51 settings against the live Sleeper host (`W18-F009`).

---

### P1-12 · R16 — League registry identity is hand-typed

**Closes:** `W18-F001`, `W18-F002` (P1); `W18-F005`, `W18-F011`, `W30-F006` (P2); 3 P3 —
8 findings.

**Problem.** `scoringProfile` is a hand-typed string in `config/leagues/registry.json` with no
derivation from, and no check against, the league's actual `scoring_settings`. `dynasty_main` and
`dynasty_new` carry the same string while their host scoring differs on **35 of 48 shared keys**,
so `/api/data` serves one league's rankings to the other (`W18-F001`, upheld). The cross-league
Sleeper overlay then stamps `sleeperDataReady: true` on a **chimeric** block —
`dynasty_new`'s real teams welded to `dynasty_main`'s `scoringSettings`, `rosterPositions` and
`num_teams` — which un-gates every downstream consumer (`W18-F002`, rescoped). The registry's
`dynasty_new` entry is wrong against its own live host on every roster field it models
(`W18-F011`), and three call sites in trade suggestions still read the hardcoded `dynasty_main`
starter demand (`W30-F006`).

**Root cause.** An identity claim expressed as a label rather than as a fact.
`src/league_comparison/sleeper_scoring.py::_scoring_hash` already computes a content hash of a
scoring dict; the registry does not use it.

**Required repair.** Derive the profile identity from a content hash of the live
`scoring_settings`, or add a startup/CI check that every pair of leagues sharing a
`scoringProfile` has byte-identical scoring. Until then `dynasty_new` must get its own profile. On
the `sleeper_matches=False` branch, drop `scoringSettings`/`rosterPositions`/`leagueSettings`
rather than carrying the wrong league's forward, and keep `sleeperDataReady: false`.

**Dependencies.** `W18-F002` is downstream of `W18-F001` — with a correct profile the overlay path
would 503 before it is reached. Requires one read-only GET per league to `api.sleeper.app`, which
`config.py::fetch_live_league` already does.

**Size.** **M.**

**Acceptance test.** A CI check that fails when two registry leagues share a `scoringProfile` and
their host scoring hashes differ. No payload carries a `sleeper` block whose `scoringSettings`
came from a different league than its `teams`.

---

### P1-13 · R17 — The public-league identity filter erases franchises

**Closes:** `W19-F001`, `W19-F002`, `W28-F001` (P1); 7 P2; 8 P3 including 4 verified-working —
18 findings.

**Problem.** `identity._RETIRED_OWNER_IDS` strips two owners from the `ManagerRegistry`, which is
the `roster_id → owner_id` map every public section resolves through. Filtering identity and
filtering game data were conflated, so **34 of 170 scored 2024 roster-weeks (20 %) never enter the
aggregates**.

**User impact.** Running the repo's own `records.build_section` with the list emptied changes **5
of 10 record categories, 3 of them at rank #1**. A visitor is told the all-time lowest single-week
score is 177.25 (it is 164.79), that the fewest points in a win is 241.23 (it is 236.61), and that
the 2nd-longest win streak is held by Brent alone (SheriffB is tied). The history payload
self-contradicts on the same page: 2024 carries `numTeams: 10` and exactly **8** standings rows,
rendered with no caveat (`W19-F002`, size XS). This is a public, anonymous surface — it is a
historical rewrite people will cite.

Separately, the 12-team / 14-week schedule generator and its NFL-aware optimizer **do not exist
anywhere in the repository** — not a route, not a script, not a config, not a doc (`W28-F001`,
size L, status *Missing*). The audit archived a feasibility proof
(`evidence/W28/schedule_feasibility_proof.py`): the constraint set is exactly determined and
provably satisfiable, so this is a bounded build, not research.

**Root cause.** Display filtering applied at the identity layer.

**Required repair.** Keep retired owners in `roster_to_owner` so historical rows resolve, and filter
them only at the display surfaces that need it. Or stamp `excludedOwnerCount` /
`historicalCoverageIncomplete` on every section that drops rows and render it. Assert
`numTeams == len(standings)` at build time.

**Dependencies.** `W19-F002` is downstream of `W19-F001`. The schedule generator depends on
`config/leagues/registry.json` and treats the nflverse slate as optional (it degrades to `[]`
offline).

**Size.** **M** for the identity fix, **L** for the schedule generator.

**Acceptance test.** All 10 of the 2024 franchises appear in every all-time aggregate; the three
misattributed records return their true holders and values; `numTeams == len(standings)` for every
season.

**What is already right here:** the public trade grader reproduces the canonical linear-ratio +
KTC-value-adjustment formula exactly (`W19-F009`); the week-level roster-ownership join the
all-time claims require does exist and is used (`W19-F010`); all 21 `/league` tabs and all 10
dynamic deep-link routes render real, non-fabricated content in a real browser (`W19-F015`); and
Team Assignment reproduces to the point on an independent recomputation for all 12 managers
(`W28-F002`).

---

### P1-14 · R18 — News is joined and applied wrongly

**Closes:** `W21-F001`, `W21-F003` (P1); 7 P2; 2 P3 including 1 verified-working — 11 findings.

**Problem.** `/api/terminal` filters news by the **fantasy team's name** against **player** mention
names — the service parameter is called `team_names` and means "the players on my fantasy team",
and the caller read it as "the name of my fantasy team". Every authenticated roster view gets zero
news items and all 57 signals collapse to HOLD (`W21-F003`, size XS). Behind it,
`src/api/injury_impact.py` is a direct **news-to-value multiplier** with no structured claim, no
corroboration and no confidence: a live headline about a **contract extension** multiplies Bijan
Robinson's dynasty value by 0.9616 (`W21-F001`).

**Root cause.** An untyped string parameter whose domain nothing checks, sitting in front of a
lookup-table model that converts a two-regex headline classification straight into a percentage on
`rankDerivedValue`.

**Required repair.** Pass the resolved roster's player names (already computed as `roster_set` by
the same builder). **Then** either delete `injuryAdjustedValue` and let news drive labels only, or
route it the way BDVM already routes news — typed event, confidence, source reliability,
corroboration, feeding a module input rather than the final value.

**Dependencies.** This ordering is load-bearing and is stated in the findings: `W21-F003` currently
makes `W21-F001` **unreachable in production**. Fixing the join without first fixing the multiplier
turns a dormant defect into a live one. Fix `W21-F001` first.

**Size.** **XS** for the join, **M** for the multiplier.

**Acceptance test.** An authenticated terminal view returns non-zero news items for a roster with
known news. No news item can change a player's value without a typed event and a corroboration
count. `/api/terminal` signals are not 665-of-665 HOLD.

**Already right:** the BDVM speculation clamp is real — every news-derived event on the live feed
emits `sigma_mult` only, and every value is ≥ 1.0 (`W21-F002`).

---

### P1-15 · R19 — Payload shape and cold-path cost

**Closes:** `W26-F001`, `W26-F003`, `W26-F004`, `W00-F002` (P1); 6 P2; 2 P3 — 12 findings.

**Problem and impact.**
- `/api/data` is **11,953,535 bytes** raw / 1,176,182 gzip. Measured per view: `compact`
  **7,363,760**, `array` **6,514,536**, `app` **5,818,304**. The "compact" mobile view is therefore
  **849,224 bytes (+13.04 %) larger** than the view the desktop asks for, and only 38.4 % smaller
  than full — not the ~90 % the comments claim. Mechanism, byte-accounted: `array` drops the legacy
  `players` dict and ships `playersArray` only (6,132,969 b); `compact` prunes 14 audit fields per
  row (55→41 fields, 6,132,969 → 3,659,280 b) and then **also** ships the legacy dict
  (3,336,826 b) — the same 1,092 rows encoded twice. The per-row pruning works; shipping both
  encodings is the defect (`W26-F001`, upheld). Phones are deliberately routed to the heavier
  payload.
- `/draft` downloads the full 11.95 MB contract to read a **46.8 KB** list of 12 team names, from
  three separate call sites, two with `cache: "no-store"` (`W26-F003`, rescoped).
- `GET /api/bdvm/roster` takes **48 seconds to return 310 bytes** because two nflverse enrichment
  fetches run before a snapshot-existence check the caller already has the information to perform
  (`W26-F004` size XS, `W00-F002`). The repair is three lines.
- `AppShell` fetches the multi-megabyte contract on **every** private page including a 404 page
  (`W26-F002`, authored P1 → verified **P2**).

**Root cause.** No narrow endpoint exists for the small things pages actually want, and one
existence check sits on the wrong side of two expensive fetches.

**Required repair.** Delete the legacy `players` dict from the compact payload (which alone takes
it to ~4.03 MB, 38 % below array). Move the snapshot check before the enrichment fetches. Serve
`sleeper.teams` from a narrow route and memoise the three `/draft` call sites on
`selectedLeagueKey`. Drop `cache: "no-store"` so the existing ETag/304 works.

**Dependencies.** None. `W26-F004` can ship today and is the single largest latency win in the
audit.

**Size.** **XS** (`W26-F004`), **S** (`W26-F001`, `W26-F003`), **M** overall.

**Acceptance test.** `?view=compact` is smaller than `?view=array`; `/api/bdvm/roster` returns its
no-snapshot payload in under 1 s; `/draft` issues one contract-scale fetch per load, not three.

---

### P1-16 · R20 — CI gates do not gate

**Closes:** `W24-F001`, `W24-F002`, `W24-F004` (P1); `W24-F003`, `W24-F005`, `W24-F006`,
`W24-F007` (P2); 4 P3 — 11 findings.

**Problem.** The suites are green — 6,278 passed / 40 skipped / 0 failed (`evidence/pytest-full.txt`)
and 1,754 frontend tests / 0 failed (`evidence/vitest.txt`) — and a meaningful fraction of them
cannot fail on the things they were written to catch.
- The skip census undercounts skip sites **6×** (27 declared, 166 actual) because it greps only
  `pytest.skip(` against a majority-`unittest.TestCase` suite (`W24-F001`).
- `tests/roster_intel/test_real_rosters.py` — 22 tests written specifically to catch "a constant
  masquerading as a score" — executes in **neither** CI tier, because the fixture it needs is
  gitignored (`W24-F002`).
- `e2e.yml`'s `SKIP_VISUAL_REGRESSION=1` skips **all 13 tests in both visual specs**, including the
  structural assertions the workflow's own comment claims still run — `test.skip(condition, …)` in
  a describe body is a group-level modifier (`W24-F004`).
- **286 tests run only in a `continue-on-error` step**, at least 46 of which open no files under
  `exports/`, `CSVs/` or `data/` — pure logic exempted from the gate (`W24-F003`, authored P1 →
  verified **P2**).
- `percentile_to_value` — the conversion behind every displayed value — has **zero absolute numeric
  assertions** across 6,326 tests (`W24-F007`).
- 104 python tests and 40 frontend assertions verify behaviour by **grepping source text**, so they
  pass on a comment, a dead branch, or unreachable code (`W24-F010`).

**Root cause.** Gates added per incident, never audited as a set.

**Required repair.** Fix the census regex and add a `--collect-only` floor assertion to
`pr-validation.yml` so a drop in executed-test count fails the build. Track the roster fixture or
make it fail rather than skip. Drop `SKIP_VISUAL_REGRESSION` (`--ignore-snapshots` already
suppresses pixel comparison). Move pure-logic tests out of `continue-on-error`.

**Dependencies.** None — but every acceptance test in this roadmap is worth less until this lands,
because the mechanism that would keep a repair repaired is the thing that is broken.

**Size.** **M.**

**Acceptance test.** Executed-test count is asserted with a floor; every test in the advisory tier
that opens no data file runs in the blocking tier; `percentile_to_value` has pinned numeric
expectations.

---

### P1-17 · R22 — Confidence is one unvalidated agreement bucket

**Closes:** `W03-F004` (P1); `W03-F005`, `W00-F007`, `W03-F015` (P2); 4 P3 including 2
verified-working — 8 findings.

**Problem.** `confidenceBucket` **rises when sources disappear**: dropping one real source raises
the published label on 237 of 679 rows (34.9 %), and "high" is more common at 3 sources (11.1 %)
than at 4 (2.3 %) (`W03-F004`). The only coverage term is a binary `n>=2` gate and the agreement
statistic is computed over present sources only; `softFallbackCount` and `sourceAudit.reason`,
which do know about absent coverage, are never consulted. It measures agreement about **rank
order**, not about the value it is rendered beside — 21 of 89 "high" rows have per-source value
dispersion above the board median (`W03-F005`). Confidence reads High on two-source pick rows and
Medium on fourteen-source player rows (`W00-F007`).

**Required repair.** Make coverage a first-class term — cap the bucket when
`matchedSources/expectedSources` is low, or publish coverage as a second badge. At minimum, stop
claiming "how many sources matched" in the tooltip while the formula ignores it.

**Dependencies.** R10 consumes this: gating direction on confidence is only meaningful once
confidence means something.

**Size.** **M.**

**Acceptance test.** Removing a source never raises any row's published confidence label.

---

### P1-18 · R23 — Sharp cohort evidence is thin and unlabelled

**Closes:** `W15-F009` (P1); 8 P2; 9 P3 including 2 verified-working — 18 findings.

**Problem.** Sharp Roster Percentage publishes no per-player manager concentration, so **one
manager's five teams render as an 83 % sharp roster percentage** with nothing on the row or the
page saying it is one human (`W15-F009`). `rosterQuality` is 22 % of the Sharp Score and is
structurally 0.0 for every manager because `platform_records` never populates any of its four
inputs (`W15-F002`). `multiLeagueConsistency` — the anti-luck term — counts **season rows** as
independent leagues while the user-facing string says "6 independent leagues" (`W15-F004`), and
championship success is counted twice (`W15-F005`).

**Required repair.** Add `uniqueManagers` / `eligibleManagers` per row via
`cohort.canonical_manager_ids` — `market.py` already does this per asset and `_transparency` does
it at board level. Populate or remove `rosterQuality`. Count distinct leagues, not season rows.

**Dependencies.** The whole surface is **Blocked by data** in this container (see below); the code
defects are provable statically and the numbers are not.

**Size.** **M.**

**Acceptance test.** A player rostered by one manager's five teams shows `uniqueManagers: 1` and a
sample warning.

**Already right:** `cohort_members` is genuinely the single membership definition and the five
qualification gates that can fire were each proven firing (`W15-F015`); both imperatively
registered sharp routes are present in the live app (`W15-F014`).

---

### P1-19 · R25 / R26 — Bridge coverage and documentation drift

**Closes (R25):** `W09-F007` (P1); 8 P2; 7 P3 including 2 verified-working — 16 findings.
**Closes (R26):** `W25-F010` (P1, *Implemented and verified*); 7 P2; 5 P3 — 13 findings.

**Problem.** The Next bridge route for `/api/trade/suggestions` is the only one of four trade/angle
bridges that drops the session cookie, so the suggestions feed 401s from the browser
(`W09-F007`, size XS). More broadly, bridges cover **36 of 99** backend operations and
`next.config.mjs` declares no rewrites, so `npm run dev` serves a product where 40 client-called
routes 404 (`W01-F001`) — production is unaffected because nginx routes `/api/`, but no developer
can exercise those paths locally.

On documentation: `docs/ARCHITECTURE.md` tells you to fetch `/api/data?view=delta`, a parameter
that route silently ignores (`W25-F007`); CLAUDE.md's three payload-size figures are each ~3× low
and the test that supposedly pins them runs on a fixture **71× smaller** than production
(`W25-F002`); ADR-001..015 exist in two `DECISIONS.md` files with unrelated subjects and 36 of 44
ADR citations in `src/` do not say which file (`W25-F006`); CLAUDE.md names Selenium as the
production scraper's stack twice and no Selenium exists anywhere in the repo (`W25-F008`); and 58
of 144 markdown documents are superseded, stale or self-declared untrustworthy, with only two of
the 22 in `docs/status/` saying so (`W25-F011`).

**Required repair.** Add `Cookie: request.headers.get('cookie') || ''` to `suggestions/route.js`
and one test asserting every `frontend/app/api/**/route.js` that POSTs to `BACKEND_API_URL`
forwards the cookie. Then a documentation pass tied to the repairs above — every number CLAUDE.md
states should be re-measured against the live payload as part of the change that makes it true,
not as a separate cleanup.

**Dependencies.** Documentation must come **last within each repair**, not last overall. Correcting
the docs before the code produces a second wrong document.

**Size.** **XS** (`W09-F007`), **M** (documentation).

**Acceptance test.** A test that fails when any bridge route omits the cookie header. Every numeric
claim in CLAUDE.md is reproducible from a live payload or is removed.

---

## P2 — 180 findings

**156 of the 180 are the tail of the P0 and P1 root causes above** and ship with them: R13 17,
R11 10, R10 9, R3 8, R4 8, R14 8, R25 8, R5 7, R17 7, R18 7, R26 7, R28 7, R7 6, R19 6, R6 5,
R12 5, R1 4, R20 4, R8 3, R15 3, R16 3, R22 3, R2 2, R9 1, R23 8. Scheduling them as separate
tickets would be double-counting.

Four root causes are P2-topped and are genuinely new work.

---

### P2-1 · R21 — No model provenance and no historical board

**Closes:** `W04-F002`, `W04-F003`, `W04-F004`, `W04-F005`, `W04-F006`, `W04-F007`, `W04-F009`,
`W04-F010`, `W04-F011`, `W04-F012`, `W03-F012`, `W23-F017` (P2); 3 P3 including 2 verified-working
— 15 findings.

**Problem.** Derived values carry no model version, param-set id or as-of stamp: `/api/data` serves
1,092 values with nothing recording which champion produced them (`W04-F011`). No historical record
of the *served* board exists — archived exports carry the raw scraper composite only, with no
`rankDerivedValue`, no `canonicalConsensusRank`, no `confidenceBucket`, no `sourceRanks` — so every
"historical" backtest reconstructs a board by calling `build_api_data_contract` against **today's**
CSVs (`W04-F009`, size XL). Consequently **no recorded holdout criterion is reproducible**
(`W04-F006`). Six of the eight Hill constants a promotion ships have no out-of-sample score at all;
the 2026-07-29 promotion shipped a −34.6 % IDP curve change on that basis (`W04-F003`). One holdout
board silently lost 24 % of its rows in a day and the gate scored it anyway — that shrinkage
accounts for 99.3 % of the criterion movement (`W04-F007`). And there is no human review layer
anywhere: nothing in the UI can approve, suppress, annotate, re-run, diff or roll back a single
suspicious output (`W23-F017`, size XL).

Note the verified position: four of these were authored P1 and verified **P2** (`W04-F002`,
`W04-F003`, `W04-F005`, `W04-F009`), and a fifth was authored P1 and verified **P3**
(`W04-F008`). None of this cluster was ever P0.

**Required repair.** Write `playersArray` (or at minimum `rankDerivedValue`,
`canonicalConsensusRank`, `confidenceBucket`, `sourceRanks`) into every export; archive all 21
`site_raw` CSVs per snapshot; give `build_api_data_contract` an optional `site_raw` root so a
replay is possible. Stamp `modelVersion` + `paramSetId` + `asOf` on every derived value — BDVM
already does exactly this and is the template.

**Dependencies.** R6 first: `W30-F008` establishes that the holdout criterion is not measuring the
served board's error, so recording more of an uncalibrated criterion buys nothing.

**Size.** **XL.**

**Acceptance test.** Any archived snapshot replays to a board bit-identical to what was served that
day. Every value on `/api/data` names the champion that produced it.

---

### P2-2 · R27 — Accessibility and mobile ergonomics

**Closes:** `W26-F012`, `W26-F013`, `W26-F014`, `W26-F015`, `W26-F017` (P2); `W26-F016` (P3) —
6 findings.

**Problem.** `/draft` has **102 unlabelled form inputs** and `/settings` has 4, including two range
sliders that change the board (`W26-F014`). At 390 px, **873 of 900 interactive targets on
`/rankings` are under 44 px** and type as small as 9.0 px ships on three pages (`W26-F017`); the
trade calculator's sticky verdict bar is clipped by a floating action button and `/draft`'s teams
panel refuses to stack (`W26-F015`). `/rosters` position bars fail WCAG contrast at **2.19:1 in 53
places**, with colour the only encoding for narrow segments (`W26-F012`). The 1–9,999 value scale
is disclosed **only** through hover tooltips — 1,933 `title` attributes on `/rankings` and no
visible text (`W26-F013`). 8 of the first 22 keyboard tab stops on `/draft` have no visible focus
indicator (`W26-F016`).

**Required repair.** Labels on every input; a 44 px minimum target and a 12 px type floor at mobile
breakpoints; a non-colour encoding on every bar segment; the value scale stated in visible text
once per board; a visible focus ring.

**Dependencies.** None technically — but see the sequencing note: this is display work and it comes
after the numbers those displays present are trustworthy. Coverage caveat from `EVIDENCE_LOG.md`:
mobile measurement is **Chromium-only**; webkit is not installed, so iOS behaviour is untested.

**Size.** **M.**

**Acceptance test.** Zero unlabelled inputs; no interactive target under 44 px at 390 px; all text
contrast ≥ 4.5:1; every focusable element has a visible indicator.

---

### P2-3 · R29 — Insider Trading surfaces its own limits inconsistently

**Closes:** `W16-F003`, `W16-F004`, `W16-F005`, `W16-F007` (P2); 11 P3 including 4
verified-working — 15 findings.

**Problem.** The board counts trades made **inside the user's own league** while the page states
the trades happened in their *other* Sleeper leagues (`W16-F005`). The 503 no-data path renders an
honest banner **and a fabricated negative in the same view** — "No tracked activity yet" beside
"No buy/sell events in the rolling window" (`W16-F003`). `ledger.coverage()` is served only to
Sharp Tracker, so the board offers a 90-day lens over a ledger whose real window is shorter and
never says so (`W16-F004`). Waiver/FAAB activity is fully modelled, ingested and served, and
`GET /api/intel/waiver-interest` and `GET /api/intel/member/{ownerId}` have **zero** frontend
consumers (`W16-F007`). CLAUDE.md documents **none** of `src/intel/` — a 6,200-line subsystem with
seven routes, a page, a daily workflow and two migration scripts (`W16-F014`).

**Required repair.** Correct the scope claim on the page. Serve `coverage()` to the board and render
the real window. Suppress the fabricated negative on the no-data path. Wire or retire the two
orphan routes.

**Dependencies.** Numeric verification is **Blocked by data** here — `data/intel/ledger.sqlite3`
exists with a full 19-table schema and **zero rows** (`W16-F012`). Every defect above is a code
property provable statically.

**Size.** **M.**

**Acceptance test.** The page's scope claim matches the query's actual scope; the no-data view
contains exactly one statement about the absence.

**Already right:** the ledger's counting rules are correct — multi-team trades, refetches, failed
transactions, window overlap and waiver-vs-trade separation all behave as documented
(`W16-F002`); Sharp Tracker and Insider Trading are genuinely separate products with no silent
cohort reuse (`W16-F001`).

---

### P2-4 · R30 — Consensus Edge is honest but half-wired

**Closes:** `W14-F001`, `W14-F002`, `W14-F003` (P2); 7 P3 including 4 verified-working —
10 findings.

**Problem.** Sharp Flow can never score a single row: the ledger keys movements by Sleeper player
id and the board looks them up by `displayName` (`W14-F001`, authored P1 → verified **P2**). Even
if it joined, it consults **no sharp cohort at all** — it would count every manager in every
crawled league as a qualified sharp (`W14-F002`). 28 of the board's 73 buy-side rows are labelled
Buy directly above their own text saying the fair value is **below** the market (`W14-F003`).

**Required repair.** Join on player id. Resolve the manager pool through `src/sharp/cohort.py`
(the platform's single cohort definition per `CLAUDE.md`). Reconcile the label with the fair-value
statement it sits above.

**Dependencies.** **The flag is OFF and the code is consistent with the committed "do not ship yet"
verdict** (`W14-F007`) — nothing user-facing consumes this board. That makes it the lowest-urgency
cluster in the audit and the correct place to defer.

**Size.** **M.**

**Acceptance test.** `sharpFlow` is non-null for at least one row on a populated ledger; no row is
labelled Buy above text saying fair value is below market.

**Already right:** the leave-one-out fair value is genuinely anchor-free — zero anchor votes
survive and the served `fairValue` reproduces a freshly built LOO board (`W14-F004`); every served
number reproduces exactly from the payload and the board refuses on thin evidence rather than
fabricating (`W14-F005`).

---

## P3 — 156 findings

**56 of the 156 are verified-working records, not work.** They exist because the audit was
required to publish positive verification as well as defects — the blend is exactly reproducible
and deterministic across two in-process runs and an independent reimplementation on 800/800 rows
(`W02-F012`); KTC Value Adjustment Python↔JS parity is exact over a 139-trade fixture (`W08-F010`);
the ROS isolation cardinal rule holds in both directions at runtime (`W17-F003`); the best-ball
lineup optimizer is exact, not greedy-correct-by-accident, over 360 randomized brute-force trials
including non-laminar slot sets (`W17-F006`); all 21 registered sources have a live fetcher, a
fresh CSV and real votes on the served board (`W05-F010`). **Do not schedule these. Do not
regress them.**

Of the remaining 100, 95 are the P3 tails of root causes already scheduled, and 5 form the only
P3-topped root cause.

### P3-1 · R31 — Unreachable modules, routes and scripts

**Closes:** `W30-F011`, `W30-F013`, `W30-F014`, `W30-F015`, `W30-F022` — 5 findings.

See *Deprecate rather than repair* below. This cluster is a deletion decision, not a repair.

### The P3 tail worth knowing about

A handful of P3s are one-line corrections with a visible symptom and should be swept up whenever
their file is open, not scheduled:

- `W02-F010` — `derived = int(norm_val)` truncates where every neighbouring stamp rounds,
  publishing a value 1 point below the blend on **280 rows** (XS).
- `W07-F008` — under the league-adjusted lens the board breaks its own documented 0–9,999 ceiling;
  Josh Allen renders **10,171** (XS).
- `W10-F017` — the `/draft` overpay warning renders a doubled dollar sign, `$$175` (XS).
- `W10-F015` — `DEFAULT_ROOKIES` sums to $1,211 against a comment claiming $1,200, pulling the
  inflation singularity 11 dollars inside the draft (XS).
- `W06-F007` — `resolve_many` rebuilds the entire Sleeper directory index once per input row,
  **203×** its own documented cost (XS).
- `W29-F005` — the "Seller cash-out" tag compares a 0–9,999 board value against a 0–100 ROS index
  and is unreachable for all 1,092 rows (XS).
- `W27-F006` — `src/ros/` normalizes no position strings, so 6 IDP rows are bucketed as S/DT/DE and
  receive fabricated positional ranks (XS).

---

# 18. Recommended Implementation Sequence

The ordering principle, stated once: **do not repair a display before the number underneath it is
trustworthy, and do not repair a number before the codebase can say "unknown".** Every phase below
exists because the next one is not measurable without it.

---

## Phase A — the four one-file P0 diffs (plus two XS items that depend on nothing)

| item | root cause | size | closes |
|---|---|---|---|
| `useSettings.js:35` → `null`, drop the migration, fix Reset | R1 | S | 3 P0 |
| ROS season sort key at 4 call sites + preseason guard | R3 | XS | 1 P0 |
| `or 0.0` → `None` in `trade_deadline.py:78` + "not simulated" | R3 | S | 2 P0 |
| delete both `Math.min` clamps in `draft-logic.js:1427` (+ its test) | R4 | S | 1 P0 |
| `_sanitize_next_path` parse-and-compare | R12 | XS | open redirect |
| snapshot check before nflverse fetches in `bdvm_api.py:177` | R19 | XS | 48 s → <1 s |

**Why first.** Every one is a bounded, single-file change where the correct answer already exists
elsewhere in the tree — the ADR-015 curve is loaded and never entered; `luck.py:193` passes
`s.season` correctly; `src/api/gameplan.py:807` already returns
`oddsSource='owner_not_in_simulation'`; `slotsByTeamFromPicks()` already returns the true 31/7/6
counts. Nothing depends on any of them and they unblock measurement of everything else: while two
boards exist, no later measurement can say which board it measured.

**Ship as separate commits.** The TEP diff changes 786 rows and needs its own bisect point.

---

## Phase B — make "unknown" representable

R9 in full, plus R3's preseason guard generalised (R10's zero-evidence half) and R22's coverage
term.

**Why second.** A large fraction of every later repair terminates in "…and render 'not measured'".
Right now there is nowhere to put that. `or 0.0`, `rankDerivedValue = 0`, `computedConsensusRank`,
`HOLD`, `unpriced → dropped` and the flat ±15 % band are six spellings of the same missing concept.
Until one convention exists — `None` for unpriced, a stamped count of what was dropped, and a UI
state for it — R3, R10, R11, R19 and R28 each have to invent their own, and the audit's core
finding (that this codebase converts absence into confidence) recurs.

Two sites already do it right and are the template: `src/trade/finder.py`'s
`metadata.assetsUnpricedByBoard` and `src/api/gameplan.py`'s `oddsSource`.

---

## Phase C — the value scale

R6 in full, then R2, then R5's normalization.

**Why third, and why not earlier.** These are the numbers under every board, but they cannot be
fixed *first*, because with two boards live (Phase A) a change of ±13–25 % is unattributable.
And they cannot be deferred, because R2, R7, R11, R21 and R28 all reason about magnitudes that
Phase C is about to change.

**Do not ship the one-line version of `W02-F001`.** The verifier established that the prescribed
GLOBAL re-route returns per-source medians of 0.92/0.92/1.29/1.32 — a *wider* spread than the
control band — and that a second defect compounds it: the IDP master is fit in units **1.552×**
the scale its output is consumed in, so correct-coordinate routing would be wrong by +55 % at the
top. Fix both, or neither, and re-measure `W02-F002` and `W02-F003` afterwards rather than fixing
them independently (their own `dependencies` fields say so).

`W30-F008` — assert `FIT_TOP_N == _PERCENTILE_REFERENCE_N` — is the cheapest item in this phase and
should lead it, because until it lands the holdout RMSE is not a measurement of the served board.

---

## Phase D — asset classes: picks and IDP become first-class

R8, then R7.

**Why after C.** R7's repair is a per-family cut over a value scale; deciding the families before
the scale settles means re-tuning immediately. R8's repair is an identity change and is
scale-independent — `W20-F005` (one import swap, 39 % of pick capital) and `W08-F004` (four
hardcoded `/^2026\b/` literals) can be pulled forward into Phase A if capacity allows.

**Why before E.** Four team-direction classifiers cannot be reconciled while picks are worth zero
in two of the four inputs and DBs are structurally absent from a third.

---

## Phase E — one definition per product noun

R11, R28, then R10's tracker consolidation (`W12-F003`).

**Why here.** Choosing among four direction classifiers, three roster-value sums, two playoff-odds
engines, two power-ranking engines and 16 directional emitters is a decision about *correctness*,
and it is only a real decision once the inputs they disagree about are trustworthy. Made earlier,
it is a coin flip dressed as architecture.

Order within the phase: value-concept collisions (R28) before label consolidation (R10), because a
single authoritative verb computed over two colliding value concepts is a single authoritative
wrong answer.

---

## Phase F — boundaries, observability and the gate

R12 remainder, R13, R20, R16, R14.

**Why not earlier.** R12's XS open redirect is in Phase A because it is unrelated to everything and
actively dangerous; the rest (login throttle, XFF key, admin allowlist) is real work that blocks no
other repair. R13 and R20 are placed here rather than last for one reason: **they are what make
Phases A–E stick.** A repair verified once by an audit and then unguarded by CI is a repair with a
half-life. If capacity allows only one reordering of this document, pull `W24-F001` +
`W24-F003` (the collect-only floor and the `continue-on-error` tier) forward to Phase A.

R16 (registry identity) and R14 (name-based joins) sit here because both are correctness work whose
symptoms are currently masked — `dynasty_new` is not the primary league, and the split-row players
are two rows out of 1,092. Real, provable, not urgent.

---

## Phase G — subsystem correctness

R15 (scoring engine + BDVM calibration), R17 (public-league identity), R18 (news), R5 remainder
(FAAB formula), R23 (sharp), R29 (Insider Trading).

**Why here.** Each is a self-contained subsystem whose defects do not propagate into the core value
spine. R17's public records rewrite is the one item in this phase with a claim to being earlier —
it is an anonymous, citable, public falsehood about league history — and it is size M with no
dependencies, so promote it if there is any parallel capacity.

**Ordering constraint inside R18, stated in the findings:** fix `W21-F001` (the news→value
multiplier) **before** `W21-F003` (the news join). The join defect currently makes the multiplier
unreachable in production; fixing the join first turns a dormant defect into a live one.

---

## Phase H — provenance and replay

R21.

**Why after C and F.** Recording history of an uncalibrated board records uncalibrated history.
`W30-F008` must land first or the holdout criterion being archived is not measuring the served
board, and `W04-F009`'s export-format change should be made once, against the final field set, not
twice.

---

## Phase I — display, payload, documentation, accessibility

R19 remainder, R25, R26, R27.

**Why last, explicitly.** This is where the roadmap is most likely to be reordered by pressure, and
it should not be. Polishing a display before the number underneath it is trustworthy produces a
well-labelled wrong answer, which is strictly worse than an obviously wrong one — that is the
mechanism behind the audit's single worst finding, `/settings` rendering "**Default 1.15x**" on
the exact value that silently disables the measured curve. Documentation belongs at the end of
*each individual repair*, not at the end of the roadmap: correcting CLAUDE.md's payload figures
before R19 lands produces a second wrong document.

Two exceptions already pulled forward: `W26-F004` (48-second endpoint, XS) is in Phase A because it
is pure latency with no correctness coupling, and `W09-F007` (bridge cookie, XS) should ship
whenever someone next touches that directory.

---

## Phase J — new builds

`W28-F001` (schedule generator, L — constraint set proved satisfiable in
`evidence/W28/schedule_feasibility_proof.py`), `W10-F003` (draft optimizer, L),
`W11-F013` (season-aware FAAB, XL), `W19-F007` (Money and Constitution public surfaces, L),
`W23-F017` (human review layer, XL), `W12-F003` if not already absorbed into Phase E.

**Why last.** Every one of these is a feature that does not exist. Building new surfaces on top of
a value spine that is still being corrected means building twice.

---

## The cheap wins, stated plainly

This deserves to be the first thing anyone reads.

**Two small diffs close four P0s.**

- `frontend/components/useSettings.js:35` — one literal, plus deleting the `readSettings()`
  migration at `:182-190` and fixing the Reset button. **Size S.** Closes `W03-F001`, `W07-F001`,
  `W08-F001` — three of the nine surviving P0s. All three survived adversarial verification:
  `W08-F001` upheld, `W03-F001` and `W07-F001` rescoped with the severity held at P0 and the blast
  radius corrected **upward** (pagesAffected 1→10 and 5→~30 respectively).
- `src/ros/playoff_sim.py:464,546,562` and `src/ros/power_v2.py:325` —
  `key=luck._season_sort_key` → `key=lambda s: luck._season_sort_key(s.season)`. **Size XS.**
  Closes `W17-F001`.

**Two more small diffs close the remaining three cheap P0s.**

- `src/ros/trade_deadline.py:78` — `or 0.0` → `None`, plus a "not simulated" render. **Size S.**
  Closes `W17-F002` and `W20-F002`.
- `frontend/lib/draft-logic.js:1427-1431` — delete two `Math.min` calls and the test assertion that
  pins them. **Size S.** Closes `W10-F002`.

Four diffs, none larger than S, close **seven of the nine P0s**. The two that remain — the FAAB
budget mixing (`W11-F001`, M) and the rank-space market gap (`W12-F002`, M) — are formula changes,
not one-liners.

**Three further XS items with outsized effect:**

| item | effect |
|---|---|
| `bdvm_api.py:177` snapshot check before the fetches (`W26-F004`) | 48 s → <1 s on `/api/bdvm/roster` |
| `_sanitize_next_path` allowlist (`W22-F001`) | closes a working post-login open redirect on the real domain |
| `portfolio-insights.js` → `resolvePickRow` (`W20-F005`) | restores 187,512 of pick value, 39 % of all pick capital |

---

## Deprecate rather than repair

Nine items should be **deleted or explicitly marked internal**, not fixed. Each is currently
indistinguishable from live product, which is the actual cost.

| what | evidence | recommendation |
|---|---|---|
| `src/api/chat.py` — documented private endpoint, never registered; `/api/chat` 404s on the running server | `W30-F011` | delete |
| `src/api/auction_power.py` — declares itself the source of truth for effective auction power, zero production callers; the file calling itself its "JS mirror" is the only live implementation | `W10-F014`, `W30-F013` | delete, or delete the docstring claim |
| `src/canonical/calibration.py` — 5 of 7 functions dead, including the whole legacy pick curve and `calibrate_canonical_values` | `W30-F015` | delete the dead five |
| `src/news/unified_signal_engine.py` — calls itself "the single entry point for every BUY/SELL/HOLD decision emitted to users" and has **zero importers** | `W12-F012`, `W30-F012` | delete, or make it true in Phase E — do not leave it claiming authority it does not have |
| The raw-ingest scaffold (`/api/scaffold/raw`, `/status`, `/identity`) — serves a **2026-04-20** artifact stamped with a 2026-08-03 mtime; `/api/scaffold/identity` serves a 106-day-old report whose master players carry zero Sleeper IDs and whose pick table is empty | `W05-F007`, `W06-F010` | remove the routes; `/api/scaffold/status` is additionally in the unauthenticated allowlist and returns absolute server filesystem paths (`W01-F010`) |
| 16 backend routes with no caller outside tests, including six `/api/scaffold/*` and `POST /api/test-alert` which nothing references at all | `W01-F003` | remove |
| `/design` — a dev-only design-system gallery shipped in the production build and reachable from no navigation | `W01-F005` | exclude from the production build |
| `tests/fixtures/golden/baseline.json` — a 722 KB committed "golden baseline" no test and no workflow reads | `W24-F009` | delete |
| Five "kick sharp in prod" workflows — none scheduled, four self-triggering on their own file path; plus two byte-identical FFPC timer templates in two directories with two installers on the same 05:20 schedule | `W15-F012`, `W23-F013` | delete four, keep one of each |

**Two that look like deprecation candidates and are not.**

- `GET /api/gameplan` + `src/roster_intel/` — 4,385 lines, zero frontend consumers (`W20-F001`,
  `W01-F002`). But its 22 dedicated tests were written specifically to catch "a constant
  masquerading as a score" and execute in neither CI tier (`W24-F002`), so nobody knows whether it
  works. Decide *after* fixing `W24-F002`: build the surface, or mark it internal-only. Do not
  delete an unmeasured subsystem.
- The partner-fit / acceptance model (`W09-F015`) — the finding describes it as "rigorous and
  honest about its own unidentifiability" and unreachable from any page. That is a wiring gap, not
  dead weight.

**Scope note.** `W30-F022` reports 30 of 300 `src` modules unreachable from `server.py`,
`scripts/` or the scraper, and 27 more script-only. Treat that as a survey to work through, not a
single ticket, and be careful: `src/adapters/base.py` is imported by tests only *by design* — it is
the frozen interface definition (per `CLAUDE.md`), while `scraper_bridge_adapter.py`, which
`CLAUDE.md`'s adapter table claims is live in `server.py`, has no production caller
(`W30-F014`). One is documentation drift; the other is real.

---

## Blocked by data — not schedulable until an input exists

Eleven findings carry status *Blocked by data*. They split into two kinds, and the distinction
decides whether anything can be done.

### Blocked by container state — verify on a production host, do not schedule a repair

`EVIDENCE_LOG.md` records these as pre-declared harness conditions. In each case the code degrades
**honestly** — an explicit status string, never a fabricated number — and the audit says so.

| finding | absent input | note |
|---|---|---|
| `W13-F005` | `data/bdvm/projections/` | all four BDVM routes answer 200 with `status=no_projection_snapshot`; every UI surface degrades correctly. CLAUDE.md's "726 priced / 222 unpriced" is a production observation, not a property of a checkout |
| `W15-F001` | sharp ledger rows | ledger exists, every sharp-bearing table has 0 rows; all five routes and both pages say so explicitly |
| `W16-F012` | intel ledger rows | `ledger.sqlite3` exists with all 19 tables; only `meta` has rows |
| `W14-F010` | Consensus Edge snapshot store | `snapshotStore.exists: false`; the flag is off and nothing consumes the board |
| `W11-F014` | `contract.ktcCrowd` | producer is a scraper path the audit must not run |
| `W11-F015` | `data/intel/snapshot_dynasty_main.json` | response carries an explicit note and `staleInputs: ['intel']` |
| `W03-F011` | `data/rank_history.jsonl` | written only on fresh-scrape promotion, which the harness suppressed |

**What to do:** re-run the specific probes on production, not repairs. `W14-F010` names its own
check: `snapshotStore.lastDate` on `/api/consensus-edge/health`.

### Blocked by data, but carrying a real code defect that is *not* blocked

Three of the eleven contain a defect provable without the data, and those are schedulable now:

- `W12-F011` / `W20-F014` — HOLD is overloaded. With `rank_history.jsonl` absent, 665 of 665
  rostered players return HOLD with the reason **"Stable — no movement, volatility, or news
  triggers"** — an assertion of stability presented as a positive finding when nothing was
  measured. The mislabel is a code property; it will misfire on any production gap in the log too.
  Emit a distinct `no_history` verdict. **Size S. Schedule in Phase B.**
- `W19-F014` — the Previews/Recaps tabs render a single **eight-month-old** article pair (2025
  Week 17, the only two files that exist) under present-tense copy with no staleness threshold.
  The missing articles are blocked (the weekly-narratives workflow has never had an API key); the
  missing date stamp and empty state are not. **Size S.**
- `W10-F012` — rookie pick values are point estimates everywhere on the live path. Populating
  `data/bdvm/projections/` activates the existing pick-EV panel; whether the `/draft` **market**
  board should carry its own distribution is an independent product decision that no data unblocks.

### Blocked by an input that does not exist anywhere

`W04-F009` is not container state: **no historical record of the served board has ever been
written**. Archived exports carry the raw scraper composite only. This is why every backtest and
every promotion criterion in R21 is unreproducible, and it is why R21 is XL rather than M. Nothing
unblocks it except starting to record — which is the phase H work item.

---

## What works

Stated plainly, because a repair roadmap that lists only defects misrepresents the system.

- **The frontend shell is clean.** Measured through the production topology: 41/41 pages return
  200 authenticated, 38 render an `<h1>`, median DOM-ready **83 ms**, max 695 ms. Of 55 console
  errors the only non-artifact ones are correct behaviours — a 403 on `/admin` for a non-admin
  test user and a 503 on `/consensus-edge` for a flag that is deliberately off (`W00-F009`).
- **The test suites pass.** 6,278 python tests / 40 skipped / 0 failed / 496 subtests
  (`evidence/pytest-full.txt`); 104 frontend files / 1,754 tests / 0 failed
  (`evidence/vitest.txt`). R20 is about what they *cover*, not whether they run.
- **The blend is deterministic and exactly reproducible.** An independent reimplementation matches
  `_blendedValueUncapped` on 800/800 rows, and two in-process runs agree (`W02-F012`). The
  single-source haircut, TE basis conversion, pick tethering and board coherence are all verified
  exact on the live board (`W02-F013`). Missing data abstains rather than defaulting — the only
  fabricated values on the board are the 12 synthetic 2029 picks, and their provenance is disclosed
  (`W02-F014`).
- **All 21 registered sources are live end to end** — a fetcher, a fresh CSV (staleness 1.66–1.86 h)
  and real votes on the served board, traced key by key (`W05-F010`).
- **The delta view is faithful.** 0 mismatches over 1,092 rows × 43 `_DELTA_PLAYER_FIELDS`
  (`W03-F002`). The merge machinery is sound; R1 is about what the frontend *asks* for.
- **The exact-scoring engine is provably exact** where it is used: ADR-006's dot product reproduced
  against 1,339 host-scored player-weeks at max |delta| 0.005 (`W18-F010`), and `dynasty_main`'s
  config is byte-exact against the live Sleeper host — 141/141 scoring keys, 58/58 roster slots,
  51/51 settings (`W18-F009`).
- **The trade calculator's core math is right.** A→B / B→A verdict symmetry is exact over 20 real
  and 40,000 random trades (`W08-F009`); KTC Value Adjustment Python↔JS parity is 0 differences
  over a 139-trade fixture with identical RMS 26.59 against KTC's captured displays (`W08-F010`);
  duplicate-asset protection holds on every path including bulk import (`W08-F013`).
- **The ROS cardinal rule holds.** No ROS value reaches `rankDerivedValue`, the trade calculator or
  the rankings board — verified in both directions at runtime (`W17-F003`). The best-ball lineup
  optimizer is exact, not greedy-correct-by-accident, over 360 randomized brute-force trials
  including non-laminar slot sets (`W17-F006`).
- **BDVM's structural guarantees are real.** Reference parity against the frozen Appendix-C fixture
  passes (13 archetypes × 3 currencies at ±1.0), market isolation is structural, and the
  aging/survival split is correctly wired (`W13-F007`, `W13-F008`, `W13-F009`).
- **The Hill promotion gate cannot ship constants.** The refit workflow structurally cannot promote,
  the live curve is bit-exact to the registry champion, and the audit trail is current — a v3
  challenger was scored and recorded 2026-08-04 (`W04-F016`, `W04-F015`). The finding that claimed
  the gate's benchmark was circular was **overturned** on verification (`W04-F001`, published with
  `published: false` and the argument that killed it).
- **The arbitrage finder is no longer offense-only.** The per-market IDP gate is live and working;
  the prior audit's claim does not reproduce at HEAD (`W09-F014`, `W27-F010`).
- **The public league renders real content.** All 21 `/league` tabs and all 10 dynamic deep-link
  routes render non-fabricated content in a real browser, and every not-found path is honest
  (`W19-F015`); the public trade grader reproduces the canonical formula exactly (`W19-F009`).
- **Degradation is usually honest.** Every *Blocked by data* surface above returns an explicit
  status string rather than a number. The failures this audit reports are overwhelmingly failures
  of *fabrication in the presence of data* — a wrong number confidently rendered — not failures to
  handle absence.

---

## One caution about severities

Adversarial verification changed 22 severities and **every single change was downward**: 5× P0→P1,
2× P0→P2, 14× P1→P2, 2× P1→P3, plus one finding overturned entirely. The audit draws the obvious
conclusion in `EVIDENCE_LOG.md` — unverified severities in this codebase, including those of its
predecessors, run hot.

Only 45 of 431 findings were adversarially verified. The 386 unverified findings should be read as
proposals whose severity has not been attacked. Where this roadmap schedules a large piece of work
on unverified P1s — R11's four classifiers, R13's 29 monitoring findings, R21's XL provenance build
— the first task in that phase should be to re-derive the measurement, not to start the repair.
Nine of the nine P0s in Phase A and Phase C **were** verified; that is why they lead.
