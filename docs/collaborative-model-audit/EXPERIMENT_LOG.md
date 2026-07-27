# Experiment log

Includes the experiments that failed or changed the plan. A log with only successes
is a summary, not a log.

---

## EXP-1 — Does the projection branch in `aggregate.py` do anything?

**Method:** two identical `RankedRow`s differing only in `projection_value`; compare
`rosValue`. Then mutate the branch to actually consume the projection and re-run.

**Result:** identical output. Under mutation, all three behavioural assertions fail.

**Conclusion:** the branch was dead; the tests that pin it are not vacuous. The value
travels from `sources/draftsharks_ros.py` through `scrape.py:414-423` and is discarded.

---

## EXP-2 — Is the nflverse weekly-stats fetch working?

**Method:** probe the URL template in `nflverse_direct.py:59` for each season.

| URL | status |
|---|---|
| `player_stats/player_stats_2023.csv` | 200 |
| `player_stats/player_stats_2024.csv` | 200 |
| `player_stats/player_stats_2025.csv` | **404** |
| `stats_player/stats_player_week_2025.csv` | 200 |
| `player_stats/player_stats_def_2025.csv` | **404** |
| `stats_player/stats_player_def_week_2025.csv` | 404 |

**Conclusion:** nflverse renamed the release asset; the 2025 file now carries `def_*`
columns unified into the offensive file (header inspected to confirm). `_fetch_csv`
swallows the 404 and returns `[]`.

**Severity revised down** after finding `historical_stats.py:70-110` implements a
documented Sleeper fallback for exactly this case. The system degrades to a lesser
source rather than failing — but silently.

---

## EXP-3 — Reachable range of `tradePartnerFitScore`

**Method one (closed form):** assume every logit cap saturates and confidence hits
`MAX_CONFIDENCE_WITHOUT_DECISION_DATA = 0.45`. → **6.7 – 47.0**.

**Method two (exhaustive sweep):** product over need, window, fairness, history and
every reachable evidence tier. → **7.24 – 43.12**.

**They disagree, and method one is wrong.** The 0.45 cap never binds: the best tier
reachable without decision data is `HISTORY_INFORMED` at 0.40. Method one assumed the
declared cap was the operative one.

**Conclusion:** 7.24 – 43.12. The constants in `partner.py` are now *derived* from the
caps rather than declared, and the test cross-checks that derivation against a brute
sweep, so the two methods can never drift apart again.

**Carried forward:** a declared ceiling and an operative ceiling are different things.
The module had both and only documented one.

---

## EXP-4 — KTC TE++ uplift: which functional form?

**Method:** 73 TEs appearing on both `ktc.csv` and `ktcSfTep.csv`. Four candidate forms.

| form | statistic | verdict |
|---|---|---|
| additive `tepp − base = c` | CV 0.304 | rejected — delta falls 1133 → 516 across the board |
| multiplicative `tepp/base = c` | CV 0.134 | rejected — ratio rises 1.209 → 2.053 |
| log-linear on ratio | R² 0.82 | **rejected — predicts ratio 0.938 at the top** |
| power `1 + a·v^−k` | R² 0.941 | **adopted** |

The log-linear form fits acceptably and is nonsense: a TE premium that *lowers* a tight
end's value. Constraining the form to be ≥ 1 by construction cost R² and bought
correctness.

**Residual analysis** (the reason for the floor):

| TE band | observed mean | fitted mean | signed error |
|---|---|---|---|
| 1–12 | 1.2270 | 1.2053 | −0.022 |
| 13–48 | 1.265–1.343 | 1.283–1.366 | +0.017 to +0.023 |
| 49–60 | 1.4555 | 1.4635 | +0.008 |
| 61–72 | 1.7015 | 1.6367 | −0.065 |
| 73 | 2.0531 | 1.8641 | −0.189 |

Good through TE60; degrades only in the deepest ~13, where single noisy observations
dominate — and it **under**-states the premium there rather than overstating it. At the
single most valuable TE the fit reads 1.146 against an observed 1.209, hence the floor
at the observed minimum.

**Headline:** the live `_TE_BLANKET_NON_NATIVE_MULTIPLIER = 1.15` sits *below the entire
observed range*. It under-corrects for every tight end.

---

## EXP-5 — What is the league's actual TE demand?

**RETRACTED AND REDONE.** The first version of this experiment measured the wrong thing.

### First attempt (wrong)

**Method:** read every TE-touching scoring key and compare against WR/RB equivalents.

```
bonus_rec_te 0.0   bonus_rec_wr 0.0   bonus_rec_rb 0.0
bonus_fd_te  1.0   bonus_fd_wr  1.0   bonus_fd_rb  1.0
```

**Conclusion drawn:** TE premium is exactly 1.000, so TE values should be translated
*down* off the TE++ basis.

**Why it was wrong:** it measured the scoring *mechanism* and called it the *demand*.

### Redone

**Method:** read `roster_positions` from the league snapshot.

```
['QB','RB','RB','WR','WR','WR','TE','TE','FLEX','FLEX','SUPER_FLEX', ...]
                                    ^^^^^^^^^^
counts: {'QB':1,'RB':2,'WR':3,'TE':2,'FLEX':2,'SUPER_FLEX':1, ...}
flexEligible: [RB, WR, TE]   sflexEligible: [QB, RB, WR, TE]
```

**Conclusion:** **two mandatory TE starters**, plus TE eligibility in both FLEX and
SUPER_FLEX. Twelve teams must field twenty-four tight ends every week. That is large
structural demand, entirely independent of scoring — and it is the class of league KTC's
TE-premium boards exist for.

**Target basis: TE++**, which is what the live blend already assumes. So the direction of
the live adjustment was right; only its magnitude (a flat 1.15 against a measured
1.209–2.053) is wrong, and correcting it moves TE values **UP**.

**Carried forward:** a scoring key is one way demand shows up, not the definition of it.
Any "does this league value position X" question must read roster structure first.

### Double-count check

With the target basis established as TE++, the risk is applying an uplift to something
already on that basis. Verified:

| case | result |
|---|---|
| `ktcSfTep` (already `tepp`) → `tepp` | no-op, value unchanged |
| convert twice with the same pair | second call sees `from == to`, no compounding |
| `base 8169 → tepp → base` | returns 8169 (round-trip exact) |
| `base 8169 → tepp` | 9878 — matches Brock Bowers' real KTC pair |
| `base → teppp` | raises; no fitted curve, refuses to interpolate |

The blend site was already safe — its `if/elif` is mutually exclusive and KTC is exempt.
The risk was introduced by *this audit*: the first API returned a `multiplier` field a
caller would naturally stack on top. Replaced with a target *basis*, which cannot be
multiplied into anything.

## EXP-6 — F-6 threshold re-derivation: percentile or scale?

**Method one (percentile equivalence on the full pools):** absurd. `MIN_MARKET_VALUE`
500 → 1097 (ratio 2.19), `JUNK_THRESHOLD` 400 → 1060 (2.65). The composite prices 1077
assets and the board 812, so percentile matching conflates the scale change with a
population change.

**Method two (percentile on the paired population, n=803):** degenerate at the low end.
`MIN_ASSET_VALUE` = 800 sits at the 99.25th percentile and `JUNK_THRESHOLD` = 400 at the
100th, so both map to ~900 — collapsing two gates that exist to do different jobs.

**Method three (scale by measured k):** median board/composite ratio over the paired
population is **0.875** (p10 0.775, p90 1.056). Stable, and it preserves which assets a
gate admits.

**Adopted method three.** It also agrees with PR #567's own finding that porting the
constants unchanged "silently tightens every absolute gate" by ~14% (1/0.875 = 1.143).

**Independent reproduction of PR #567** fell out of this: 803 paired assets (they said
803), k = 0.875 (0.880), 189 orphans clearing the old gate (194). One day of drift.

---

## EXP-7 — What does the F-6 migration actually change?

**Method:** `scripts/audit/finder_migration_snapshot.py` over all 12 teams, same payload
before and after, contract built from the raw payload both times so the input is held
constant.

| | before | after |
|---|---|---|
| total trades | 436 | 435 |
| median `boardDelta` | 1047 | 1030 |
| median `arbitrageScore` | 21.65 | 21.28 |
| top-1 changed | — | **0 of 12 teams** |
| top-5 slots identical | — | 45 of 60 |

**This contradicts F-6's own prediction** that it "moves every number the endpoint
emits". The levels move; the ordering barely does.

**Why, structurally:** the dominant score term is `board_delta / give_model` — a ratio.
A near-uniform rescale (ρ = 0.9626) cancels. And the pool is capped at 150 per market,
where the two boards agree best; the disagreement lives in the tail, which never enters.

**Conclusion:** a coherence fix, not a behaviour change. Worth stating plainly in both
directions — the small diff does not mean the migration was unnecessary. Before it, "our
board says X" referred to a board no user could see.

---

## Not run, and why

* **rosValue vs actual weekly points** (finding A's key experiment). Blocked twice:
  the projection path is a dead branch, and nflverse 2025 404s (EXP-2). Needs finding Q
  resolved first.
* **Pairwise source correlation** (finding P). The CSVs are on disk and this is
  runnable; deferred because the follow-on change moves a user-visible confidence field
  on every player and deserves its own pass.
* **Removal-cost surplus** (finding E). Needs the same before/after harness F-6 got.
