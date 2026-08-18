# Exact league scoring — repairs, and the host-native challenger

**Issue:** #802 · **Date:** 2026-08-18 · **Flag:** `host_native_scoring` (default **OFF**)

This record covers two things that arrived together because measuring the first
found the second: repairs to the champion scoring path, and a challenger
scoring source that is **off by default** pending promotion.

**Deployment status — read this before quoting anything below.** #915 is OPEN
and UNMERGED, so *nothing in this document is live*. The only already-live
work is the 2026-08-13 return-yard repair (B7 / W18-F003) described in §1,
which is on `main` because it merged earlier and independently. Everything in
§2 and §3 becomes live only after **merge → deploy → production
verification**, and production verification has **not** been done.

---

## 1. What #802 asked for, and what was already live

The issue says individual special-teams production is paid to RB/WR/TE/LB assets
this board values while being classified as an asset class the platform does not
value.

**The headline was already fixed** by B7 / W18-F003 (2026-08-13), which
reclassified the `st_` / `kr_yd` / `pr_yd` families and wired `kr_yd`, `pr_yd`
and `st_td` into the engine. Verified before anything was changed, against the
real 2025 nflverse feed and the live `dynasty_main` card:

| key | source column | rows | points (2025 REG) |
|---|---|---|---|
| `kr_yd` | `kickoff_return_yards` | 849 | 1,795.63 |
| `pr_yd` | `punt_return_yards` | 404 | 281.77 |
| `st_td` | `special_teams_tds` | 27 | 162.00 |
| **total** | | **1,280** | **2,239.40** |

Single-row proof: DeAndre Carter, 2025 wk1, 105 KR yards and 41 PR yards, scores
**4.867** with the columns present and **0.000** with them zeroed.

That work is not repeated here.

---

## 2. Repairs in this change (champion path — unflagged, NOT yet deployed)

These are unflagged, so they take effect **as soon as this PR is deployed** —
but they are not live today. #915 is unmerged.

### 2a. Safeties scored zero — 10,842.88 points

`SAF` is the spelling the 2025 unified nflverse release uses for a safety. It was
in **neither** `POSITION_ALIASES` — which CLAUDE.md names the single source of
truth for position families — nor `realized_points._IDP_POSITIONS`.

`_is_idp_position("SAF")` returned False, so the entire IDP scoring block was
skipped and every safety scored a well-formed **0.000** with no reason and no
flag.

| measure | value |
|---|---|
| affected player-weeks (2025 REG) | 1,429 |
| points never awarded | **10,842.88** |
| mean per affected player-week | 7.59 |
| worst affected | Talanoa Hufanga 222.70, Tre'von Moehrig 222.31, Nick Emmanwori 219.15 |

For scale: this is **4.8×** the entire return-yards repair above. After the fix
safeties contribute 10,846 points across 2025 REG — 8.3% of the 130,704-point
board — where they previously contributed none.

Two consumers had already found this and patched it **locally**
(`league_comparison.scoring_engine._canonical_position`, whose comment records
that it "was in neither POSITION_ALIASES nor this table", and
`bdvm.context.TRUE_POSITION_MAP`). That is why it never surfaced in their output,
and exactly why a third private copy in the scoring engine kept the bug.

**Fixed at the owner:** `SAF` added to `POSITION_ALIASES`, and `_IDP_POSITIONS`
is now *derived* from it rather than restated, so the next spelling the owner
learns is scored automatically. A position table that is not derived from the
owner is a second owner.

Position-scoped understatement is a **relative** bias, not merely a magnitude
error: crushing the DB group against DL and LB tilts every comparison between
them — the same argument `scoring_coverage`'s module header makes about partial
corrections.

### 2b. Blocked kicks were a GAP recorded as impossible — 175.56 points

`UNSCORABLE_REASONS` declared `idp_blk_kick` (5.32/event) unscorable because
"blocked kicks are not a column on the weekly defensive feed", while
`def_punt_blocks`, `def_pat_blocks` and `def_fg_blocks` were all populated on the
very feed the engine already reads.

2025 REG: 44 player-weeks of blocks, split **punt 9 / PAT 12 / FG 23**. The
field-goal blocks are more than half, which is what a first-present candidate
lookup would have dropped — hence `_IDP_SUM_KEYS`, which sums.

Now scored: **33 player-weeks, 175.56 points** (DE 12, DT 11, LB 6, CB 2, NT 1,
DL 1). The 11 remaining blocks belong to SAF (8, now scored via 2a) and to an RB,
a TE and an OT — deliberately not paid, because `idp_blk_kick` is Sleeper's IDP
rule and those players occupy no IDP slot. The team `blk_kick` rule stays
NOT_APPLICABLE.

### 2c. "Unscorable" was stated as a property of the universe

Every remaining reason read as universal impossibility — "not a column on the
weekly feed", "needs play-by-play". Each is true of **nflverse** and false of the
**league host**. Reasons now name their limiting source, `HOST_PUBLISHED` records
which categories another configured source supplies, and `describe_gaps`
distinguishes "not scored on this path, recoverable" from "no source has it".

Collapsing those two is the same silencing failure `NOT_APPLICABLE` was for
`st_`: the key vanishes from the warning surface without the limitation being
true.

---

## 3. The challenger: host-native scoring (flag OFF)

### 3a. The defect

`league_comparison.sleeper_stats._FIELD_MAP` translates Sleeper's short stat keys
**into** nflverse long column names; `realized_points.sleeper_stat_line_from_row`
then translates them **back** into Sleeper keys to score them. A category with no
nflverse column is destroyed in the middle hop even though both ends of the trip
speak the host's vocabulary.

**50 of the 85 rules `dynasty_main` pays** are published by the host and cannot
traverse `_FIELD_MAP` — every player special-teams category, the whole kicker
family, all six `rec_*` distance bands, the first-down bonuses, `pass_cmp`,
`pass_inc`, `rush_att`, `idp_pass_def` and `idp_blk_kick`.

This is the fallback path for any season nflverse has not finalised. nflverse
404s on 2026, so it becomes the live path when the 2026 season starts.

Note `kr_yd` is among the 50. The category #802 was raised about scores correctly
on the nflverse path and is **still lost** on the path that will be live in
September.

### 3b. The fix is subtraction, not addition

Sleeper's stat line **is** the canonical scoring vocabulary.
`league_intel.scorer.score_stat_line` scores it directly and is validated against
the host's own `players_points` (1,339 player-weeks, max |Δ| 0.0050). The
challenger hands the host's line to that scorer with nothing in between. No new
scoring engine was written; a translation was removed.

It is also *more* accurate than normalizing: the host publishes `pass_inc`,
`bonus_fd_qb` and the tackle split directly, so three reconstructions
(`attempts − completions`, first downs net of TDs, `_tackle_view`) are replaced by
measured values.

### 3c. Impact attribution — host wk14 2025, player entries only

| key | rate | players | pts (wk14) | share |
|---|---|---|---|---|
| `st_tkl_solo` | 1.33 | 87 | 135.66 | 31.1% |
| `rec_10_19` | 0.67 | 108 | 107.20 | 24.6% |
| `rec_5_9` | 0.42 | 123 | 73.92 | 17.0% |
| `rec_20_29` | 0.92 | 40 | 45.08 | 10.3% |
| `rec_30_39` | 1.17 | 16 | 25.74 | 5.9% |
| `rec_40p` | 1.92 | 8 | 19.20 | 4.4% |
| `rec_0_4` | 0.17 | 81 | 18.02 | 4.1% |
| `st_ff` | 4.25 | 3 | 12.75 | 2.9% |
| `pass_int_td` | −2 | 1 | −2.00 | −0.5% |
| **total** | | **467** | **435.57** | 100% |

≈ **7,405 points per 17-week regular season**, on one league's card.

`st_fum_rec` is recoverable and had no occurrence in this week — published by the
host's schema, but the event did not happen. That is not evidence against it.

**Reconciliation: 0.000000 unexplained points across all 2,086 player entries.**
Every point the challenger adds is attributable to a named rule — this is the
check that the redistribution is the intended corrections and not accidental
double counting or omission.

### 3d. Reconciliation against the league host's own scoreboard

The 16 golden fixtures in `tests/league_intel/fixtures/golden_player_weeks.json`
are real 2025 player-weeks with host-awarded `players_points`. Host-native
scoring reproduces **all 16 within 0.011** (the host's display precision),
covering pocket/rushing/sack-prone/pick-six QB, both RB archetypes, three
receiver archetypes, **kicker and kicker-with-miss**, and five IDP roles
(tackle LB, edge rusher, interior DL, box safety, ballhawk corner).

The champion path cannot be validated this way at all — it would have to rename
the host's line into nflverse columns and back first, which is the step that
loses the rules.

### 3e. Two defects the validation caught

Both were found by the evidence above, not by review, and both are now pinned:

1. **Double count via alias spellings.** `compute_weekly_points` already copies an
   alias *rate* onto the canonical key, so a card written as `idp_qb_hit` pays
   both spellings. An earlier `host_stat_line` also copied the *stat* onto both,
   and the rule was paid twice: the tackle-LB archetype scored **29.7956** against
   the host's **27.6**. Fixed by collapsing the line onto canonical spellings
   (a `pop`, not a copy), which makes exactly-once structural rather than
   arithmetic.

2. **Half the team entries were taken for players.** The host's dump carries
   **two** team-entry families — bare codes (`PHI`, `HOU`) and prefixed
   (`TEAM_BUF`, `TEAM_LAR`), 28 of each. A "short alphabetic id" deny-list
   cleared all 28 prefixed ones. Fixed by identifying players **positively**
   (numeric or GSIS-shaped ids); a new team spelling is now refused by default.

   This matters because `st_tkl_solo` and `kr_yd` are published under **one key
   name on both entry kinds**, meaning the team's total and the player's own. The
   split cannot be done by key family — only by entry kind.

### 3f. Player vs DST separation

Measured on the host dump: pure-DST keys (`int`, `fum_rec`, `blk_kick`,
`pts_allow`, `safe`, `def_3_and_out`, `def_st_td`, `def_kr_yd`) appear **only** on
team entries — 0 player-entry occurrences. Team entries scored as players after
the fix: **0 of 56**.

---

## 4. Promotion gate — status

Per owner direction the flag is a **temporary champion/challenger validation
gate, not a permanent second scoring system**.

| requirement | status |
|---|---|
| redistribution attributed per category, not accidental | **done** — §3c, 0.000000 unexplained |
| every configured category covered incl. individual ST | **done (2026-08-18)** — all ten remaining rules are derived by `src/nfl_data/pbp_weekly.py` and joined; the live card audits 54 scored / 0 unscorable / 0 gap with the supplement, reconciling to the host at delta 0.00 (§4a). Coverage is met; production verification of the resulting historical movement is not, and is tracked below. |
| historical player-weeks reconcile to independent totals | **done** — §3d, 16/16 vs host-awarded |
| offense and IDP stacking semantics correct | **done** — §3d IDP archetypes; §3e(1) |
| no future-week / future-stat leakage | **done** — REG-only, week 18 excluded, no future week selectable (§5) |
| historical scoring-card / as-of configuration correctness | **partly closed** — resolver landed, promotion still needs a live chain walk (§5) |
| downstream consumers identified | **done** — §6 |
| performance / caching measured | **done** — §7 |
| regression tests cover corrected categories | **done** — §8 |
| BDVM rerun against challenger output | **OPEN** — needs a prod box with snapshots |
| league-comparison rerun and measured | **OPEN** — needs live Sleeper fetch |
| historical backtests rerun | **OPEN** — needs the above |
| play-by-play artifact built and joined in production | **OPEN** — `scripts/build_pbp_weekly.py` must run on prod, and the resulting movement in BDVM baselines and league comparison must be measured, not assumed (§4a) |

The remaining OPEN items mostly require production data this environment does not have
(gitignored `data/`, live Sleeper API). They are the promotion PR's work, and
promotion must not proceed without them.

**Promotion is a separate, measured PR** that flips the canonical owner, migrates
the affected baselines/backtests/consumers together, deletes `_FIELD_MAP` and
`_translate_stats`, and records the migration — coordinated through Claude 5 so
the other parallel lanes receive the new baseline at a controlled integration
point.

---

## 4a. Inventory: the ten configured rules — CLOSED 2026-08-18

Ten rules `dynasty_main` actively pays had no column on the nflverse **weekly**
feed and scored at nothing. All ten are now derived, from play-by-play, by
`src/nfl_data/pbp_weekly.py`, and joined into realized points through
`realized_points.PBP_SUPPLEMENT_ROW_KEY`.

**Measured against the league host's own week-14 2025 dump**, player entries
only, at `dynasty_main`'s live rates:

| rule | rate | events (wk14) | points |
|---|---|---|---|
| `st_tkl_solo` | 1.33 | 102 | 135.66 |
| `rec_10_19` | 0.67 | 160 | 107.20 |
| `rec_5_9` | 0.42 | 176 | 73.92 |
| `rec_20_29` | 0.92 | 49 | 45.08 |
| `rec_30_39` | 1.17 | 22 | 25.74 |
| `rec_40p` | 1.92 | 10 | 19.20 |
| `rec_0_4` | 0.17 | 106 | 18.02 |
| `st_ff` | 4.25 | 3 | 12.75 |
| `pass_int_td` | −2 | 1 | −2.00 |
| `st_fum_rec` | 3.19 | 0 | 0.00 |
| **total** | | | **435.57** — ≈ **7,405/season** |

The producer reproduces that total **exactly** (delta +0.00), which is the
point: it is not an approximation of the host's numbers, it is the same
numbers derived independently.

### The predicates, and what each was measured against

Every one was reconciled against Sleeper's own `/v1/stats/nfl/regular/2025/{week}`
dumps for REG weeks **1, 3, 5, 8, 11, 14 and 17** before it was written down.

| key | predicate | agreement |
|---|---|---|
| `rec_0_4` … `rec_40p` | `complete_pass`, credited to `receiver_player_id`, banded on `receiving_yards` (else `yards_gained`) | **exact, 7/7 weeks**, on player count and reception count, all six bands — 42 of 42 cells |
| `st_tkl_solo` | `special_teams_play` + `solo_tackle_1/2_player_id` + `tackle_with_assist_1/2_player_id` | 758 of 759; **exact in 6 of 7 weeks** |
| `st_ff` | `special_teams_play` + `forced_fumble_player_1/2_player_id` | **exact, 7/7** (10 of 10) |
| `st_fum_rec` | `special_teams_play` + `fumble_recovery_N_player_id` **where the recovering team is not the fumbling team** | **exact, 7/7** (8 of 8) |
| `pass_int_td` | `interception` + `return_touchdown` **and the TD scored by a team other than the offense**, charged to `passer_player_id` | **exact, 7/7** (12 of 12) |

Three of those constraints are load-bearing and none was obvious:

* **A negative-yardage catch is a reception in NO band.** `reception_depth`'s
  docstring had called this "an interpretation of an undocumented boundary
  rather than a measurement" and put those catches in `rec_0_4`. It is now
  measured, and the interpretation was wrong: week 14 has 537 completed passes,
  the host reports `rec` 537.0 and bands totalling **523**, and the difference
  is exactly that week's 14 negative receptions. Aaron Rodgers carries
  `rec: 1`, `rec_yd: −9` and no `rec_0_4` key at all. Shipping the old reading
  would have paid a band the host does not pay — to two quarterbacks among
  others. `band_for_yards` now returns `None` for a loss.
* **`st_fum_rec` needs the opponent constraint.** Counting every special-teams
  recovery scores 20 events against the host's 8: falling on your own muff is
  not a takeaway.
* **`pass_int_td` needs the scoring-team constraint.** 2025 week 5: Cam Ward's
  interception was fumbled back on the return and Tennessee recovered it in the
  end zone. `return_touchdown` is 1 and it is not a pick-six. Without the
  clause a quarterback is charged −2 points he did not concede.

The one residual — a single week-3 special-teams tackle — is a per-play
charting difference between nflverse and the gamebook Sleeper reads, not a rule
difference. Scoping special teams by `play_type` instead of the flag was
measured as an alternative: it nets to 759 of 759 but is wrong in **both**
directions (+1 week 1, −1 week 3), so the flag is what ships.

### Missing is never zero — the three states

`compute_weekly_points` distinguishes them, and that is what makes this
honest rather than merely better:

| state | meaning | result |
|---|---|---|
| supplement key **absent** | play-by-play was not consulted | rules reported in `RealizedPoints.unscored`; `fantasyPointsComplete: false` |
| supplement present, `{}` | consulted; this player recorded none | real zeroes, no `unscored` |
| supplement present with counts | consulted; these are the counts | scored |

`compute_cumulative_points` takes the **union** across weeks, so one
unavailable week makes a season total a declared lower bound rather than a
complete-looking number. A rule the card rates at zero is never reported: it
cannot cost anything.

Three structural guards, each with its own test:

* the supplement is an **allow-list** of the ten keys — it cannot write `rec`,
  `pass_yd`, or `kr_yd`/`pr_yd`/`st_td` (which are on the weekly feed and are
  scored from it, so a second owner would eventually disagree with the first);
* a **host-native row refuses a supplement outright** — Sleeper publishes all
  ten itself, and silently resolving the combination would pay several twice;
* `attach_supplement` **copies** the row, because callers iterate rows they do
  not own.

### Coverage is now a property of the engine AND its inputs

`scoring_coverage`'s probe takes `pbp_supplement: bool = False`. On the live
`dynasty_main` card:

    pbp_supplement=False → 44 scored, 10 unscorable, 0 gap
    pbp_supplement=True  → 54 scored,  0 unscorable, 0 gap

It defaults to **False**, the bare nflverse path, deliberately: answering as
though an input were present when the caller does not supply it is the same
overstatement this module exists to remove. `pbp_supplement_recoverable()`
names what a given pipeline is still missing, and the remedy is a join rather
than a new source.

### Predicate evidence is committed, and it discriminates

The seven-week reconciliation above was a one-off run against a 98 MB
download. What is committed — and what runs in the hard gate — is four
weeks of it: **2025 REG weeks 1, 5, 11 and 14**, as column-pruned
play-by-play slices plus the host's own line for each.

Four weeks and not one, because **week 14 alone is vacuous for three of
the four non-band rules.** Mutation-tested: with only week 14, deleting
`st_fum_rec` outright, dropping the `tackle_with_assist` columns, and
dropping the `td_team != posteam` clause all leave the reconciliation
GREEN — week 14 has no tackle-with-assist id on any special-teams play,
all five of its special-teams fumble recoveries are own-team, and its
only returned interception is a genuine pick-six. The added weeks each
supply what week 14 cannot, and week 5 carries the Cam Ward return.

Against the committed four weeks, each mutation now turns cells RED:

| mutation | cells failing (of 40) |
|---|---|
| drop the `tackle_with_assist` columns | 3 |
| count every special-teams fumble recovery | 4 |
| drop the `td_team != posteam` clause | 1 |
| put negative-yardage catches back in `rec_0_4` | 4 |

The pruned host fixtures are themselves checked against the untouched
`docs/master-site-audit/evidence/W18/` dump, so the pruning is verifiable
rather than merely convenient.

**One residual, stated rather than smoothed over.** `st_tkl_solo` is 758
of 759 over the seven sampled weeks — a single week-3 tackle. That is a
per-play charting difference between nflverse and the gamebook Sleeper
reads, not a rule difference, and week 3 is deliberately not among the
committed fixtures because it would encode a known disagreement as an
expectation.

### Two owners of the reception fact — found, and merged

`reception_depth` (season histogram) and `pbp_weekly` (per week) both
count catches by band, and each carried its own copy of the predicate.
They **already disagreed**: one accepted `complete_pass="TRUE"` and a
leading-space `" 1"` and the other did not, so the same play was a catch
to one and nothing to the other. Both now call
`reception_depth.reception_from_play` and `reception_depth.band_for_yards`
— one owner for what a reception is, one for which band it falls in — and
`test_the_two_band_producers_agree_on_the_same_play_by_play` holds them
in lockstep per player and per band over the committed week-14 slice.

`scripts/backtest_adjusted_board.py` was a **third** owner: it bolted
band points onto season totals from the depth histogram, and carried none
of the special-teams rules or the pick-six penalty at all. That code is
deleted; it takes the canonical supplement.

### A schema bump orphans what is already on disk

`RECEPTION_DEPTH_SCHEMA_VERSION` moved `2026-07-27.v1` → `2026-08-18.v2`,
and v2 changes what a band **means**. Two independent paths would have
kept serving v1 forever:

* `scripts/refresh_reception_depth.py` skipped completed seasons on **file
  existence alone**; it now reads the version and rebuilds a stale one.
* `load_reception_depth` had **no version check at all**; it now refuses a
  file at any other schema and says so. Every consumer already handles
  `None` by serving no overlay, so this degrades rather than breaks — the
  same silent-vanish posture the /rankings gap column uses.

Refusing rather than adapting is the point: a v1 file is not a v1-shaped
v2, it is a different measurement wearing the same field names.

### A mid-week build must not fabricate zeros

nflverse republishes the **current** season's play-by-play during the
week, so a Thursday-night build contains week N and almost none of it.
Every player whose game is on Sunday would resolve to `{}` — "consulted,
recorded nothing" — which scores a fabricated zero **and** suppresses the
`unscored` flag that is the only thing that would have said the week was
not knowable. That result feeds the in-season posterior blend.

So `persist_pbp_weekly` takes `complete_through_week`; anything after it
is recorded in `partialWeeks` and reads back as **unknown**, for players
who have played that week as well as those who have not. The build script
**refuses** an in-progress season unless given that flag or
`--assume-complete`, and the scheduled unit uses
`--completed-seasons-back`, which can never select such a season.

### Downstream effect of the negative-reception correction — measured

`band_for_yards` is the single owner of what a band is, so correcting it also
moves `league_intel/reception_fit.py` (and through it the /gameplan panel and
`consensus_edge/scoring_fit.py`), which measures each receiver's per-catch
value ratio from the same histograms. Measured over the full 2025 REG
play-by-play, `dynasty_main` vs the baseline card, receivers with ≥ 20 catches
(`MIN_RECEPTIONS`):

| | |
|---|---|
| players in scope | 199 |
| players whose shape changed | 114 |
| per-catch ratio delta | mean **+0.0138**, median **+0.0092** |
| largest single move | **+0.0885** (a receiver with 6 lost-yardage catches) |

The direction is uniformly positive and is the correction working: the old
reading padded the cheapest band (0.33×) with catches the host does not band
there, which understated every affected receiver's fit. The moves sit far
inside `MAX_TILT` (0.35) and the level/tilt split is unchanged.

`RECEPTION_DEPTH_SCHEMA_VERSION` moves to `2026-08-18.v2`, and the persisted
histogram gains `unbandedReceptions` per player plus `unbandedReceptionCount`
per season — so `receptions` minus the band total is a stated quantity rather
than an unexplained shortfall, exactly as it is on the host's own line.

### Wiring, and how to build the artifact

`scripts/build_pbp_weekly.py --seasons 2021 2022 2023 2024 2025` writes
`data/nfl_data/actuals/pbp_weekly_<season>.jsonl` (gitignored like the rest of
`data/`; build it on prod, same posture as the BDVM snapshots). Three
production consumers thread a resolver:

**Threading a parameter is not wiring.** The original defect was a producer
nothing called; adding `pbp_for_season` to three signatures repeats that shape
exactly if no call site passes one. Every production call site now does:

| call site | what it computes |
|---|---|
| `bdvm/baseline.realized_ppg_history` (+ `build_baseline_records`, `fetch_and_build_baseline`) | the reconstructed baseline |
| `bdvm/actuals.weekly_points_from_rows` / `fetch_current_season_actuals` | the in-season posterior blend |
| `league_comparison/scoring_engine.compute_player_season_scores` | card-vs-card season totals |
| `league_comparison/service._per_season_metrics_for_league` | the league comparison |
| `api/gameplan.py` (both calls) | the reception-share ratio |
| `league_intel/scoring_fit.py` (both calls) | the scoring-fit measurement |
| `scripts/backtest_adjusted_board.py` | the adjusted-board backtest |
| `server.py` realized-points route | the live per-player response |

`tests/nfl_data/test_pbp_supplement_call_sites.py` is a **static AST guard**
over every call site, with a `DECLARED_EXEMPT` map so "we forgot" and "we
decided not to" stop looking the same. It is written statically on purpose: a
behavioural test is satisfied by the test supplying its own resolver, which is
what every test in `test_pbp_supplement_consumers.py` does — only reading the
call sites answers the question. Mutation-checked (removing one keyword turns
it RED).

**Where it mattered most, measured rather than assumed.** A review draft
placed the sharpest effect at `gameplan.py`'s reception-share ratio and quoted
5.66% against a true 30.43%. That number does not survive checking, and the
reason is worth recording: the share is computed under the **baseline** card,
which pays **0.0 for every reception band**, so joining the supplement moves a
pure receiver's share by exactly nothing. What it does move there is the
*denominator*, for players who also play special teams — the baseline card pays
`st_tkl_solo` 1.25 and `st_ff` 4.0. Measured over 17 weeks at 6 catches / 80
yards a week: 36.00% unchanged with no ST production, 36.00% → 32.73% at one ST
tackle a week, 36.00% → 27.69% at three.

The large effect is at **`league_intel/scoring_fit.py`**, where *both* cards are
scored and only one of them bands. Season-total my/baseline ratio, same probe:

| catch profile | without the supplement | with |
|---|---|---|
| checkdown (all short) | 0.678 | 0.800 |
| balanced | 0.678 | 0.940 |
| deep threat (all long) | 0.678 | **1.420** |

Every profile returns the **identical** 0.678 without it. The measurement's
entire discriminating power — the thing the module exists to produce — was the
part that was missing, and it does not cancel between the arms because only one
arm has anything to lose. `scoring_coverage`'s own docstring already records
that a partial correction to a relative quantity is a directional bias rather
than a smaller error; this is that, and the direction depends on the player.

`scripts/bdvm_build_baseline.py` builds a `SeasonPbpIndex` by default and
prints which seasons have no artifact; `--no-pbp-supplement` reproduces a
pre-2026-08-18 build. A season the producer never built resolves to `None` and
its ten rules stay **unavailable** — deliberately *not* skipped the way an
unresolvable scoring card is, because a partial line is still a real lower
bound while an unknown rule set makes the whole line meaningless.

**`unscored` survives the consumer boundaries.** It was landing on
`RealizedPoints` and being discarded one line later at every one of them, which
would have made the three-state design structurally unobservable.
`PlayerSeasonScore` and `RealizedSeason` now carry it; `bdvm/actuals` logs a
warning naming the rules and the command that fixes it. `fantasyPointsComplete`
is stamped **always**, including when true — "this total is complete" and "this
payload predates the check" must not read the same.

**Scheduling.** `deploy/systemd/dynasty-pbp-weekly.{service,timer}.template`,
Wednesday 08:20 UTC, an hour after the reception-depth stream so two ~98 MB
pulls do not collide. It runs `--completed-seasons-back 5 --skip-existing`, so
almost every run exits 2 having done nothing — that is treated as success,
because completed seasons do not change and a unit sitting red teaches everyone
to ignore it.

### What this does and does not entitle us to say

Every configured nonzero rule on `dynasty_main` is now scorable, and with the
artifact built and joined, scored. That closes the last of the promotion gate's
coverage precondition.

It does **not** by itself make "exact league scoring" a verified claim. These
numbers move historical realized points wherever the join is switched on, and
the change is unmerged and undeployed — production verification is still
required, and `docs/EXECUTION_PLAN.md` remains authoritative for status. The
`host_native_scoring` challenger stays **default OFF**; §4's gate is unchanged
by this work except that the coverage row is now met.

**The long-play bonuses are still not currently-configured rules.** `rush_40p`,
`pass_td_40p/50p`, `rec_td_40p/50p`, `rush_td_40p/50p`, `pass_cmp_40p` and
`idp_pass_def_3p` are **zero-rated on both live cards** — verified, not
asserted, by `test_the_long_play_bonuses_are_zero_rated_on_the_live_cards`,
which fails if a commissioner turns one on. All are deterministic from PBP
(`yards_gained`, `complete_pass`, `touchdown`, `pass_touchdown`,
`rush_touchdown`, plus the passer/rusher/receiver id columns), so if one is
ever enabled it must be built rather than declared unavailable.

## 5. Time semantics and leakage — two separate claims

These were collapsed into one gate row, which let a closed claim vouch for an
open one. They are split now.

### 5a. Future-week / future-stat leakage — CLOSED

* Week 18 stays excluded — `_REGULAR_WEEK_RANGE = range(1, 18)`, unchanged.
* Only `season_type == "REG"` rows are scored, unchanged.
* No future week is selectable; the challenger changes *which rules* score,
  never *which weeks* are visible.

### 5b. Historical scoring-card correctness — was OPEN, now largely closed

The original text of this section conceded that historical rescoring applied
**today's** card to every season, and the gate table still marked leakage
"done" beside it. Applying the wrong season's *rules* is an as-of error in
exactly the same family as reading a future *stat*: both answer a question
about 2023 with information that does not belong to 2023.

Measured, two independent consumers had it:

* `league_comparison/service.py` looped seasons and passed the single
  `league_info.scoring_settings` into every one;
* `bdvm/baseline.py::realized_ppg_history` applied one card across its whole
  multi-season window.

**Now resolved by `src/league_comparison/season_scoring.py`**, which walks the
Sleeper `previous_league_id` chain and indexes each hop by **its own `season`**
— so a chain that skips a year cannot shift every earlier card by one. Both
consumers resolve per season through it.

It **fails closed**: a season whose card cannot be resolved is reported
`unresolved` and excluded, never scored with today's card, because that
substitution *is* the defect and doing it silently is what let it survive.
`cardBasis` is stamped on every season block — `season_card` when the real card
was resolved, `current_card_unverified` when the whole chain walk failed and the
result is a labelled weaker number rather than a silent one.

One deliberate nuance: a walk that resolves **nothing** is treated as "we
learned nothing", not as "this league has no history". The walker degrades
internally rather than raising, so an empty result is indistinguishable from a
dead network, and treating it as authoritative absence would blank an entire
comparison during a transient outage.

Pinned by `tests/league_comparison/test_season_scoring.py` and
`tests/bdvm/test_baseline_season_cards.py`, including the property the audit
asked for — *changing a later season's card cannot move an earlier season's
points* — and its non-vacuity twin, *the earlier season IS moved by its own
card*, because a resolver returning nothing would satisfy the first perfectly.

**Still open for promotion:** the resolver has only ever been exercised against
synthetic chains. Walking the real `dynasty_main` chain and recording which
seasons resolve is production work, and belongs with the other three gates.

## 6. Consumers

Reached by the champion-path repairs (§2) once this PR is deployed (not today):

* `src/bdvm/actuals.py`, `src/bdvm/baseline.py` — in-season blending and the
  reconstructed baseline
* `src/league_comparison/scoring_engine.py` — `/api/league-comparison`
* `src/bdvm/scoring.py`, `src/nfl_data/scoring_coverage.py`

Reached by the challenger (§3), only when the flag is on:

* `src/league_comparison/sleeper_stats.py` → `historical_stats.load_season_rows`
  → `scoring_engine` — the fallback for any season nflverse has not finalised

Latent, and repaired defensively: `nfl_data.actuals_store` persists through
`WeeklyStatRow`, which carries no return or `special_teams_tds` fields. Nothing
scores from the persisted store today — every realized-points consumer passes raw
rows — so this was not a live defect, but the schema could not represent return
production if one ever did.

## 7. Performance

The challenger removes work rather than adding it: `host_stat_line` is one pass
over a dict with no derivations, against `sleeper_stat_line_from_row`'s table
walks plus three reconstructions. Fetch cost is unchanged — same
`/v1/stats/nfl/regular/{season}/{week}` calls behind the same 7-day disk TTL, and
the 28+28 team entries are now dropped before the player-index join rather than
after. Full suite runtime is unchanged.

## 8. Tests

* `tests/nfl_data/test_idp_position_coverage.py` — the SAF defect, the derivation
  guard, and the rule that offensive players are still not paid IDP rules
* `tests/nfl_data/test_individual_special_teams.py` — return family, blocked kicks
  summed across all three columns, IDP scoping, host-published claims checked
  against the host's own dump, player/DST separation
* `tests/nfl_data/test_host_native_scoring.py` — host-only categories, derived
  totals refused, alias collapse, team-entry census, and the 16-archetype
  reconciliation against host-awarded points
* `tests/league_comparison/test_sleeper_stats.py` — team-entry drop, flag-off
  translation preserved, flag-on host vocabulary, and an end-to-end measurement
  of what the flag changes
* `tests/nfl_data/test_pbp_weekly.py` — all ten derived keys reconciled against
  the host's own week-14 line, the negative-reception boundary settled by
  measurement, the two constraints that are the rule (`st_fum_rec` opponent,
  `pass_int_td` scoring team), a renamed column raising instead of reading as
  no plays, and the uncovered-vs-zero distinction
* `tests/nfl_data/test_pbp_supplement_join.py` — the three states of the seam,
  the allow-list, the host-native double-count refusal, union-across-weeks
  aggregation, and the coverage audit on the real card with and without the join
* `tests/nfl_data/test_pbp_supplement_consumers.py` — that each consumer
  behaves correctly given a resolver, that the default still reports the
  shortfall, and that host-native rows are never given a supplement
* `tests/nfl_data/test_pbp_supplement_call_sites.py` — the static AST guard
  that every production call site actually passes one

All deterministic, over committed fixtures. No live-board counts in the hard gate.
