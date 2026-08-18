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
| every configured category covered incl. individual ST | **OPEN** — card GAP count is 0, but 10 configured rules remain UNSCORABLE on the champion path and 6 of them are derivable today (§4a) |
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

The remaining OPEN items mostly require production data this environment does not have
(gitignored `data/`, live Sleeper API). They are the promotion PR's work, and
promotion must not proceed without them.

**Promotion is a separate, measured PR** that flips the canonical owner, migrates
the affected baselines/backtests/consumers together, deletes `_FIELD_MAP` and
`_translate_stats`, and records the migration — coordinated through Claude 5 so
the other parallel lanes receive the new baseline at a controlled integration
point.

---

## 4a. Inventory: configured rules still UNSCORABLE

"Exact league scoring" is **not yet earned**, and this table is why. Ten rules
`dynasty_main` actively pays are still unscored on the champion path.

| rule(s) | rate | verdict |
|---|---|---|
| `rec_0_4` … `rec_40p` (6) | 0.17 → 1.92 | **derivable today, in-tree** |
| `st_tkl_solo` | 1.33 | derivable from PBP; published by the host |
| `st_ff` | 4.25 | derivable from PBP; published by the host |
| `st_fum_rec` | 3.19 | derivable from PBP; published by the host |
| `pass_int_td` | −2 | derivable from PBP; published by the host |

**The six reception bands are the sharp case.**
`src/nfl_data/reception_depth.py` already streams nflverse play-by-play and
emits **these exact six key names** (`BAND_KEYS`, boundaries 0/5/10/20/30/40).
Its own docstring explains why it exists: the weekly `receiving_10/16/20/40`
columns are cumulative, misaligned with Sleeper's bands, and "nothing in that
set can reconstruct 0-4 — the 0.33x band, the single most mispriced one. So
the source has to be play-by-play."

So calling these unscorable-for-lack-of-data was **false**: the producer is in
the tree, using the right names, from a source this repo already streams. They
are 66% of the measured weekly gap (289 of 435.57 points). What is missing is
the **join** into weekly realized points — the histogram currently aggregates
per season, and `_iter_receptions` already yields `week`, so a per-week variant
plus a join is the work. That is a **separate authorized unit**: it moves
historical numbers and needs the same promotion evidence as the challenger.

`UNSCORABLE_REASONS` has been restated so no reason contradicts the tree, and
`DERIVABLE_FROM_PLAY_BY_PLAY` records the verdicts. The previous wording —
"no configured source publishes it per player-week" — was wrong about
play-by-play, which *is* a configured source
(`nflverse_direct._URL_TEMPLATES["pbp"]`).

**The long-play bonuses are not currently-configured rules.** `rush_40p`,
`pass_td_40p/50p`, `rec_td_40p/50p`, `rush_td_40p/50p`, `pass_cmp_40p` and
`idp_pass_def_3p` are **zero-rated on both live cards** — verified, not
asserted, by `test_the_long_play_bonuses_are_zero_rated_on_the_live_cards`,
which fails if a commissioner turns one on. All are deterministic from PBP
(`yards_gained`, `complete_pass`, `touchdown`, `pass_touchdown`,
`rush_touchdown`, plus the passer/rusher/receiver id columns), so if one is
ever enabled it must be built rather than declared unavailable.

**Until these are scored, or the V1 contract explicitly classifies them as an
unavoidable external limitation, this system must not be described as "exact
league scoring".** For the six bands that classification is not available: the
data is here.

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

All deterministic, over committed fixtures. No live-board counts in the hard gate.
