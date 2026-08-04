# The FAAB recommendation model

This is the standalone reference for how Risk It To Get The Brisket prices a
waiver claim. It covers the engine (`src/trade/faab_engine.py`), every
parameter in `config/trade/faab.json`, the historical fit
(`src/trade/faab_history.py`), and the backtest against this league's real
bid history (`scripts/faab_backtest.py`).

Every number below was measured on **2026-08-04** against
`exports/latest/dynasty_data_2026-08-04.json` and
`data/faab/bid_history_dynasty_main.json`. Anything I could not verify is
labelled as such rather than estimated.

## Authoritative code paths

| Concern | Module |
|---|---|
| The model — every dollar figure | `src/trade/faab_engine.py::recommend` |
| Every tunable | `config/trade/faab.json` |
| Endpoint ↔ engine translation | `src/trade/faab_recommender.py::recommend_faab` |
| Historical bid fetch + fit | `src/trade/faab_history.py`, `scripts/fetch_faab_history.py` |
| OLD-vs-NEW replay | `scripts/faab_backtest.py` |
| Back-compat shim (no math of its own) | `src/trade/waiver.py::_compute_faab_bid` |
| Endpoints | `POST /api/waiver/faab-recommend`, `POST /api/waiver/suggestions` |
| UI | `frontend/components/waivers/FaabRecommendation.jsx` (display only) |

There is **one** formula, in the engine. The frontend does no bid math; the
shim in `waiver.py` delegates; the backtest holds a frozen copy of the OLD
formula on purpose (see §9).

---

## 1. What problem this solves

The pre-engine formula, verbatim from `src/trade/waiver.py::_compute_faab_bid`
at `HEAD`:

```python
top_v = max(candidate_value, top_value_in_pool or 0)
share = candidate_value / top_v if top_v > 0 else 1.0
aggressive_pct = 0.05 + 0.25 * share
aggressive = max(1, round(league_budget * aggressive_pct))
reasonable = max(1, round(aggressive * 0.70))
lowball    = max(1, round(aggressive * 0.35))
```

It has **no absolute value scale anywhere in it**. `share` is measured against
the best player currently on the wire, so the best available player always
scores `share == 1.0` and always prices at 30% / 21% / 10% of the budget —
whether he grades 9999 or 900. Three consequences, all confirmed on the real
2026-08-04 board:

* **Everything on the wire cost roughly the same.** All 40 surfaced waiver
  candidates priced between **$14 and $21 of a $100 budget**. The best
  available was Marlin Klein (TE, canonical value 1908) at $21; the worst
  surfaced was Will Levis (QB, 1132) at $14. Reproduced exactly:
  Klein `share = 1.0000 → $30 / $21 / $10`, Levis
  `share = 1132/1908 = 0.5933 → $20 / $14 / $7`.
* **A barren wire made claims *more* expensive.** `top_value_in_pool` is the
  denominator, so a weaker field raises every candidate's share.
* **"Objective" worth shrank as the manager spent.** `find_waiver_targets`
  passed the user's **remaining balance** as `league_budget`
  (`league_budget=user_faab_remaining`), so the same player was worth less to
  a manager who had already spent. And `max` was documented in the old
  recommender as `"max": int, # ceiling = team's faabRemaining` — the balance,
  not a value ceiling. The model could not express "this player is worth more
  than you can pay."

Against the league's actual behaviour, a flat 21% is not slightly hot, it is
off the end of the distribution. Across 695 real completed adds in
`dynasty_main` over 2024–2026, the **median winning bid is $0** and the
**p90 is 6% of budget**. The old system's standing recommendation sat above
the 99th percentile of anything this league has ever paid.

---

## 2. The two questions, and why they must stay separate

The engine answers two questions and never merges them:

| | `objectiveCeiling` | `recommendedBid` |
|---|---|---|
| Question | What is this player *worth*? | What should *this team* bid? |
| Denominator | The league's **original** full-season budget | same |
| Depends on | The player's canonical value and the league **format** | The ceiling, this team's balance, roster and drop side, the week, and the expected clearing price |
| Same for every team? | Yes | No |
| Moves when a manager spends? | **No** | Yes |

Keeping them separate is what makes the model correctable. Every old factor
(trending adds, league bid temperature, contention) adjusted the *bid* while
being described as adjusting *value*; because there was only one number, a
demand signal and a worth signal were indistinguishable once applied.

It is also what produces the model's most counter-intuitive and most important
output: **"worth $100, bid $36"**. Bidding the ceiling captures zero surplus by
construction, so the expected-surplus optimum is always strictly below it. A
system that reports only one number cannot say that.

---

## 3. The model, stage by stage

### Notation

| Symbol | Meaning |
|---|---|
| `V` | The add player's canonical board value, `rankDerivedValue`, on the 0–9999 scale |
| `V_drop` | Same, for the player being dropped (0 if none) |
| `B` | The league's **original** season FAAB budget (not any balance) |
| `R` | The requesting team's **remaining** balance |
| `V_allin` | Stage-A anchor: the value at which the whole budget is rational |
| `V_repl` | Stage-A anchor: what the wire gives away for free |
| `W` | Band width, `V_allin − V_repl` (floored at `minBandWidth`) |
| `s` | Normalised surplus, `max(0, V − V_repl) / W` |
| `c` | Displayed objective ceiling, in budget units (0…1) |
| `c_raw` | Uncapped ceiling, in budget units (can exceed 1) |
| `θ` | Season option-value factor (0…1) |
| `n` | Positional-need multiplier |
| `p_i` | P(rival *i* contests this claim at all) |
| `σ` | Lognormal dispersion of a contesting rival's bid |
| `b` | A candidate bid, in dollars |

### Stage A — anchors (`resolve_anchors`)

Two reference values, both derived from the **league format** and the live
board. Neither hard-codes a player or a threshold.

```
slots    = teamCount × startersPerTeam          # K slots excluded by the caller
V_allin  = board value at rank (slots × allinSlotMultiple)
V_fmt    = board value at rank (slots × replacementSlotMultiple)
V_live   = the (replacementLivePoolRank)-th best UNROSTERED value, if known
V_repl   = w·V_live + (1−w)·V_fmt               # w = replacementLivePoolWeight
```

`board values` is every priced row on the canonical board minus
`excludedPositions` (`PICK`, `K`, `DEF`). Past the end of the board
`_value_at_rank` extrapolates toward zero rather than clamping to the last
row — clamping would set a deep league's replacement anchor to its worst
ranked player and collapse the band.

Guardrail: if `V_allin − V_repl < minBandWidth`, `V_repl` is pushed **down**
to `V_allin − minBandWidth` and `bandWidened` is stamped. It widens downward
because `V_allin` is the well-anchored end.

Measured on the 2026-08-04 board (812 priced rows, 712 after excluding
`PICK`/`K`/`DEF`, max 9993, median 1792 across all priced rows):

| League | teams × starters | slots | `V_allin` | `V_fmt` (2× slots) | `V_live` (12th FA) | `V_repl` | band `W` |
|---|---|---|---|---|---|---|---|
| `dynasty_main` | 12 × 20 | 240 | **2341** | 1383 (rank 480) | 1668 (Joe Royer, TE) | **1525.5** | 815.5 |
| `dynasty_new` | 10 × 10 | 100 | **3901** | 2643 (rank 200) | not measured¹ | 2643 | 1258 |

¹ `dynasty_new` has no roster snapshot in this working copy, so its live-pool
term could not be computed; its row is the format-only anchor the engine falls
back to. On the live server the `/waivers` path always supplies the unrostered
pool.

The K slot is excluded from `startersPerTeam` by the caller
(`server.py`) because kickers are not priced on the board — counting their
slots would push the all-in anchor one slot per team deeper for no
corresponding player supply. `dynasty_main` therefore uses 20, not 21.

### Stage B — surplus (`surplus_over_replacement`)

```
addSurplus  = max(0, V      − V_repl)
dropSurplus = max(0, V_drop − V_repl) × dropSurplusWeight
netSurplus  = max(0, addSurplus − dropSurplus)
```

Both sides are measured the same way, so a below-replacement drop is free and
nothing is counted twice. With an open roster spot `dropSurplus = 0`
(`openRosterSpotCost`).

### Stage C — the ceiling curve (`objective_ceiling`)

```
s   = max(0, V − V_repl) / W
c   = smootherstep( min(1, s^toeExponent) )                    # displayed, capped at 1
c_raw = c                                    if s ≤ 1
      = min(rawCeilingCap, 1 + (s−1)·aboveAllinSlope)   if s > 1

smootherstep(x) = 6x⁵ − 15x⁴ + 10x³
objectiveDollars = c × B
```

`smootherstep` has zero first derivative at both `x=0` and `x=1`, so nothing
jumps at either threshold. It was chosen over a logistic because it reaches
**exactly** 0 and **exactly** 1 at finite inputs — "replacement level costs
nothing" and "this player is worth the whole budget" are both exactly true
rather than nearly true.

`c` is capped at 1.0 because a bid cannot exceed the budget; `c_raw` keeps
climbing so Stage E can still separate a 2400 player from a 9999 player. Both
are computed with **no reference to any team's balance**.

### Stage D — the team layer (`team_ceiling`)

```
netValue        = V_repl + netSurplus
(c_net, c_net_raw) = objective_ceiling(netValue)
θ               = season_option_value(league, team)
n               = positionalNeed[team.needLevel]

teamCeiling$    = min(R, c_net     × n × θ × B)
teamRawCeiling$ =        c_net_raw × n × θ × B          # deliberately NOT capped at R
```

The raw team ceiling is **not** capped at the balance. It is the numerator of
the expected-surplus objective; capping it would make surplus exactly zero at
`b = R`, so the optimiser could never recommend going all-in on a player who
is genuinely worth more than the budget. The **bid** is capped by the balance;
the **value** is not.

`season_option_value` (in budget-expiry terms — a dollar kept can win a later
claim):

```
lastWaiverWeek = max(1, playoffWeekStart − 1)
progress       = 1.0                            if week ≥ lastWaiverWeek
               = (week−1) / (lastWaiverWeek−1)   otherwise
θ  = (optionValueEarly + (optionValueLate − optionValueEarly) · progress^optionValueExponent)
     × competitiveStatus[status]

θ  = offseasonOptionValue                        when not in season
θ  = eliminatedOptionValue                       when status == "eliminated"
```

With carryover leagues, `_apply_carryover` pulls `θ` back toward
`optionValueEarly` by `carryoverRetention`, because unspent budget is then not
worthless.

`classify_need` (added alongside the engine) derives `team.needLevel` from
**startable depth**: how many players at the position grade above `V_repl`,
against how many the lineup must start (direct slots plus a per-position share
of every flex that accepts the position).

```
required  = directSlots + Σ_flex (flexSlots / |eligible(flex)|)
startable = |{ rostered at position : value > V_repl }|
spare     = startable − required
             spare < 0                       → starterHole
             spare < needSpareThreshold       → need
             spare ≥ surplusSpareThreshold    → surplus
             otherwise                        → neutral
```

This deliberately does **not** use `src.trade.suggestions.analyze_roster`.
That helper answers "is this position a trade surplus"; on this platform's
real 58-man best-ball rosters it is measured to return `surplus` for 68 of 84
team/position pairs and `need` exactly once, so the factor collapses to a
near-constant and cannot discriminate. It is still the fallback when roster
values or lineup slots are unavailable.

### Stage E — the market layer (`rival_bid_cdf`, `optimal_bid`)

Rival bids are a **zero-inflated lognormal**. For each rival *i* with a visible
balance:

```
demand   = min(1, c_raw / demandSaturationBudgets)                # 0…1, team-independent
p_i      = clamp( engagementBaseRate
                  + (engagementMaxRate − engagementBaseRate)·demand^engagementExponent
                  × rivalNeedEngagementMultiplier[need_i] , 0, 1)
           ( = 0 when rival i has no balance left )

share    = rivalBaseSharePct/100
           + (rivalMaxSharePct/100 − rivalBaseSharePct/100)·demand^rivalShareExponent
median_i = min( rival_i.faabRemaining,
                max(0.25, B · share · rivalDisciplineFactor · aggression_i) )

P(rival i ≤ b) = (1 − p_i) + p_i · Φ( (ln b − ln median_i) / σ )   for b > 0
P(win at b)    = Π_i P(rival i ≤ b)
```

Three rules inside that are load-bearing:

* `demand` reads the **objective raw** ceiling, not the team ceiling and not
  the raw surplus ratio. Team-independent by construction, so rival behaviour
  never becomes a function of our roster or budget. Raw rather than displayed,
  because the displayed ceiling saturates at 1.0 for everyone above the all-in
  line and would model a marginal starter as drawing exactly as much
  competition as a top-5 dynasty asset.
* A rival's expected bid is a share of the **original budget** driven by
  league-wide demand — *not* a share of our own ceiling. What the market
  **pays** and what a player is **worth** are separate quantities; tying rival
  behaviour to our ceiling would either import the league's overpayment into
  our own recommendation, or pretend rivals are as disciplined as we are.
* A rival with `faabRemaining is None` is **excluded** entirely. An
  unverifiable rival who might be broke must never raise the user's bid. A bid
  exactly equal to a rival's balance is a **tie** (`tieBreakWinProbability`),
  not a certain win — treating it as certain is what makes an all-in bid look
  risk-free when it is not.

The bid itself:

```
recommended = the CHEAPEST b on the grid with
              P(win|b)·(teamRawCeiling$ − b)  ≥  (1 − minEdge) · max_b [ … ]
              then × riskPosture[posture], clamped to [0, hardCap]
hardCap     = min(R, floor(max(teamRawCeiling$, teamCeiling$)))
```

`conservative` and `aggressive` read the **same** win-probability curve at
different targets (`conservativeWinTarget`, `aggressiveWinTarget`), scaled into
the achievable range (`target × max P(win)`), so all four numbers stay mutually
consistent instead of being independent multiples of each other. Reading the
targets absolutely would return `hardCap` for every one of them on a contested
elite player and collapse the ladder to a single number.

`clearing` — the expected market price — is scanned over the **full budget**,
independent of our balance or ceiling. A broke team still needs to be told what
the player will go for; reporting $0 because our balance is $0 would read as
"nobody wants him".

---

## 4. Every parameter, and why it is what it is

Rationale is drawn from the `_comment` blocks in `config/trade/faab.json` and
the function docstrings in the engine. Values are the shipped ones.

### `anchors`

| Key | Value | Why |
|---|---|---|
| `allinSlotMultiple` | 1.0 | The all-in line is the size of the league-wide **starting** pool: a player at that rank would start for *every* team, which is the scarcity level at which committing the whole budget is rational. Multiplying it is how you'd move that definition; 1.0 says the definition needs no fudge factor. |
| `replacementSlotMultiple` | 2.0 | Twice the starting pool is roughly "one full startable body per lineup slot in reserve" — the depth at which the next player down is genuinely re-acquirable. Measured 1383 on 2026-08-04 against a live 12th-best free agent of 1668: two independent estimates that converge, which is the argument for the anchor. |
| `replacementLivePoolRank` | 12 | Not the single best free agent — *he* is contested too, and anchoring on him would move the whole curve every time one player is claimed. The 12th is deep enough to be genuinely uncontested in a 12-team league. |
| `replacementLivePoolWeight` | 0.5 | The format line and the live pool measure the same thing from different directions and landed 285 points apart (1383 vs 1668). An even blend takes both rather than declaring one authoritative. |
| `minBandWidth` | 700 | A compressed board can push `V_repl` up against `V_allin`, making the curve near-vertical — small value differences would cause extreme bid jumps. Floors the band and stamps `bandWidened` so the UI can say so. |
| `excludedPositions` | `PICK`, `K`, `DEF` | Picks are not waiver claims; K and DEF are not priced on this board at all (712 non-`PICK` rows = 712 rows after all three exclusions, so K/DEF contribute nothing today). Including unpriced classes would distort the rank→value lookup. |
| `fallbackAllinValue` / `fallbackReplacementValue` | 2400 / 1400 | Used only when no board is available (the `waiver.py` shim's no-context path). Chosen near the measured `dynasty_main` anchors so a context-free call degrades to something plausible rather than to a pool-relative scale. |

### `ceilingCurve`

| Key | Value | Why |
|---|---|---|
| `toeExponent` | 2.2 | `> 1` lengthens the flat toe just above replacement so ordinary wire players stay near zero. 2.2 specifically because it puts the real 2026-08-04 wire top (1908) at a ~12% ceiling on the format-only anchor and the live 12th-best free agent at ~0%, while every human-anchored all-in player still saturates at 100%. (On the live blended anchor `V_repl = 1525.5` the same 1908 prices at **5.0%** — the toe is sensitive to the anchor, which is the point of §10's first limitation.) |
| `aboveAllinSlope` | 0.5 | Above the all-in line the displayed ceiling is pinned at 100%, but `c_raw` must keep rising or every saturated player draws the same bid. Half a budget per band-width is a deliberately shallow slope: the difference between "worth everything" and "worth much more than everything" is real but should not dominate. |
| `rawCeilingCap` | 6.0 | Bounds `c_raw` so the optimiser cannot be driven all-in by an unbounded number. Six budgets is far above any realistic claim and only binds at the very top of the board. |

### `dropCost`

| Key | Value | Why |
|---|---|---|
| `dropSurplusWeight` | 1.0 | The drop's cost is only the part that is **not** re-acquirable from the wire, `max(0, V_drop − V_repl)`. Expressed as surplus so it subtracts cleanly from the add's surplus with no double counting. **Note the tension:** the config comment argues for `< 1` (the dropped player retains trade/stash value you keep by *not* claiming), and ships 1.0 — i.e. the swap is currently treated as pure zero-sum. That is a knob the comment says is mis-set; changing it is a calibration decision, not a bug fix. |
| `openRosterSpotCost` | 0.0 | An open spot means no drop at all. Not a discount — an absence. |

### `seasonPhase` and `competitiveStatus`

| Key | Value | Why |
|---|---|---|
| `optionValueEarly` | 0.55 | In week 1 most of the budget's worth is in *future* claims, so only about half the ceiling is available now. |
| `optionValueLate` | 1.0 | By the final waiver period unspent budget expires worthless, so the entire ceiling is available. |
| `optionValueExponent` | 1.6 | `> 1` keeps the relaxation back-loaded: the budget stays mostly reserved through the early season and opens up as periods actually run out, rather than relaxing linearly from week 1. |
| `eliminatedOptionValue` | 1.0 | A mathematically eliminated team has no future use for FAAB. |
| `offseasonOptionValue` | 0.45 | Below `optionValueEarly`: in the offseason *every* claim is a future claim, so preserving budget is worth more than it is in week 1. |
| `carryoverRetention` | 0.5 | With carryover a dollar kept still has worth, so the late-season relaxation is damped halfway back toward the early-season factor. |
| `competitiveStatus.contender` | 1.15 | **Urgency only, never value.** Dynasty outlook and age are already inside the canonical 1–9999 number; re-weighting here would double-count them. A contender values converting budget into roster *now*. |
| `.bubble` | 1.0 | The neutral default. |
| `.rebuilder` | 0.8 | The reverse of a contender: a preserved budget is worth more than an immediate starter upgrade. |
| `.eliminated` | 0.7 | Applied to the option factor as a multiplier for a team still nominally in the season; the hard `eliminatedOptionValue = 1.0` branch takes precedence once a team is *declared* eliminated. |
| `regularSeasonWeeks` (14), `defaultPlayoffWeekStart` (15) | — | **Inert.** Neither key is read anywhere. The engine derives the last waiver period from `LeagueContext.playoff_week_start`, which `server.py` reads from live Sleeper settings. |

### `positionalNeed`

| Key | Value | Why |
|---|---|---|
| `starterHole` | 1.3 | The team cannot field a starter at the position. The largest multiplier because this is the only case where the add changes what the lineup *can* do this week. |
| `need` | 1.15 | Thin — an injury away from a hole. |
| `neutral` | 1.0 | Adequately covered. |
| `surplus` | 0.7 | Already deep; the add mostly duplicates a role. Discounted rather than zeroed, because a surplus player still has trade and injury-insurance worth. |
| `needSpareThreshold` | 1.0 | Fewer than one spare startable body above the required slot count is "thin". |
| `surplusSpareThreshold` | 3.0 | Three or more spares is genuine depth. |
| `applyToObjectiveValue` | `false` | **Inert as a switch, correct as documentation.** The engine never reads it; the separation is structural — `n` is applied in `team_ceiling`, and `objective_ceiling` has no team argument at all. Positional *scarcity* is already inside the canonical value (and inside the league-adjusted overlay when that lens is on), so this factor is deliberately about **this roster's shape**, not the position's league-wide scarcity. |

### `market`

| Key | Value | Why |
|---|---|---|
| `engagementBaseRate` | 0.05 | The floor probability that a given rival contests a replacement-level player. Anchored on the measured reality that roughly half of this league's completed adds cost $0 — most claims are simply not contested. |
| `engagementMaxRate` | 0.7 | Even an elite claim is not contested by every rival with certainty. |
| `engagementExponent` | 0.9 | Slightly `< 1`, so engagement rises quickly out of the replacement toe rather than staying flat until a player is nearly all-in. |
| `rivalBaseSharePct` | 1.5 | A contesting rival's median bid on a marginal player, as % of the original budget. The league's true median winning bid is $0 and its p90 is 6%; 1.5% is the *conditional* median given someone bids at all. |
| `rivalMaxSharePct` | 45.0 | The top of the rival share curve. Justified by the observed maxima — 61.5% of budget in `dynasty_main` (a $123 bid on a $200 budget in 2025) and 65% in `dynasty_new` — so a contested elite claim has a genuine long right tail. |
| `rivalShareExponent` | 1.3 | `> 1` keeps rival bids small across the ordinary range and lets them climb only near the top of the demand scale, matching a distribution whose median is $0 and whose tail is long. |
| `rivalDisciplineFactor` | 1.0 | Managers bid below their true maximum — the same behaviour this engine recommends. Shipped neutral: the discipline is already inside the fitted share curve, and a second multiplier on top would double-discount. |
| `rivalSigma` | 1.1 | Lognormal dispersion of a contesting rival's bid, fitted from the spread of observed nonzero bids. A large σ is what reproduces "median $0, p90 6%, max 61.5%" from one distribution. |
| `demandSaturationBudgets` | 2.5 | `c_raw` is normalised by this to produce the 0–1 demand signal. 2.5 budgets means demand saturates well above the all-in line, so the model keeps distinguishing 2400 from 9999 instead of treating every saturated player as maximally contested. |
| `rivalNeedEngagementMultiplier` | `starterHole` 1.8, `need` 1.35, `neutral` 1.0, `surplus` 0.35 | A rival's *need* changes how often they bid, not how much a player is worth. The 0.35 for `surplus` is the sharpest: a team already deep at the position usually skips the claim entirely. |
| `aggressionClamp` | `[0.5, 2.0]` | Per-manager aggression from the historical fit is bounded so one outlier season cannot make a manager look like a 5× bidder. |
| `minWinningBidsForAggression` | 3 | Below three observed adds a manager defaults to neutral with `lowSample = true`, surfaced in the UI rather than pretending to know a tendency from two claims. |
| `tieBreakWinProbability` | 0.5 | Sleeper settles equal bids by waiver priority. A coin flip is the honest model, and it is what stops "bid exactly their balance" from reading as a guaranteed win. |
| `unknownBalanceAssumption` | `"exclude"` | **Inert as a switch, correct as documentation.** The exclusion is hard-coded (`if rival.faab_remaining is None: continue`). The policy: an unverifiable rival must never raise the user's bid. |

### `bidPolicy`

| Key | Value | Why |
|---|---|---|
| `conservativeWinTarget` | 0.35 | The conservative rung is "a bid that still wins a third of the time", read off the same curve, then floored at `min(recommended, …)` so it can never exceed the recommendation. |
| `aggressiveWinTarget` | 0.85 | "Win most of the time", ceilinged at `hardCap`. |
| `minEdge` | 0.02 | The EV curve is genuinely flat for an uncontested player, and `argmax` alone would pick an arbitrary point on that plateau. Within 2% of the optimum, prefer the **cheapest** bid — this is what implements "the lowest rational bid". |
| `riskPosture` | 0.8 / 1.0 / 1.25 | Shifts the target on the curve only; the result is still clamped to `hardCap`, so a posture can never push a bid above the ceiling. |
| `searchGridPoints` | 400 | The grid is dense from $0–$40 (where almost every real claim lands) and thinned above, so a $1000-budget league stays cheap to search without losing $0–$5 resolution. |

### `leagueRules` and `confidence`

`defaultBudget` 100 / `minBid` 0 / `bidIncrement` 1 / `zeroBidAllowed` true are
fallbacks only — live Sleeper settings win. `zeroBidAllowed` matters because a
$0 claim is a legitimate, and modally the *most common*, way this league adds
players. `confidence.highThreshold` 0.85 / `mediumThreshold` 0.55 are the
weighted realised-input shares that match the pre-existing UI buckets, so the
contract did not change under the redesign.

---

## 5. Human calibration, and the format derivation of the all-in region

Two humans independently named players they would spend an entire FAAB budget
on. Their canonical values on 2026-08-04:

| Player | Site value | KTC value | KTC rank | Board rank (non-pick) | Pos | Age | Owner all-in | Peer all-in |
|---|---|---|---|---|---|---|---|---|
| Josh Jacobs | 3901 | 4072 | 107 | 100 | RB | 28 | Yes | unknown |
| Jaylen Warren | 2938 | 3299 | 165 | 166 | RB | 27 | unknown | Yes |
| De'Zhaun Stribling | 2680 | 3194 | 168 | 193 | WR | 23 | unknown | Yes |
| J.K. Dobbins | 2661 | 3043 | 180 | 196 | RB | 27 | unknown | Yes |

Board ranks re-verified against the export: 100 / 166 / 193 / 196 of 712
non-pick rows.

The obvious move — hard-code "all-in above ~2700" — would have been wrong, and
demonstrably so, because the two humans play in **different formats** and
picked different values. The threshold is not a property of the board; it is a
property of the league.

**The derivation.** `V_allin` is the board value at rank
`teamCount × starterSlotsPerTeam` — the size of the league-wide starting pool.
A player at that line starts for *every* team in the league, which is exactly
the scarcity level at which committing the whole budget is rational.

| League | teams × starters | slots | `V_allin` | Lands on |
|---|---|---|---|---|
| `dynasty_new` | 10 × 10 | 100 | **3901** | **Josh Jacobs exactly** — the value the site owner independently named |
| `dynasty_main` | 12 × 20 | 240 | **2341** | Just **below** the peer's cluster (2661 / 2680 / 2938), so all three are all-in players in that league |

One format rule reproduces both humans' judgments, without hard-coding either
of them, and it re-derives itself on every board refresh and for any league
added later. That is the single most important design decision in the model.

The **replacement** anchor got the same treatment. The format line at
`2 × slots` gives 1383; the live 12th-best unrostered player gives 1668. Two
independent estimates 285 points apart on a 9999-point scale, which is why the
engine blends them rather than picking one.

---

## 6. Value → objective FAAB

Generated by running the engine directly against the 2026-08-04 export.
`dynasty_main` uses the live blended anchors (`V_repl` 1525.5, `V_allin` 2341,
band 815.5) from the roster snapshot in `data/sleeper_last_good.json`;
`dynasty_new` uses its format-only anchors (2643 → 3901, band 1258).

### 6.1 The required breakpoints — objective ceiling

The **objective** ceiling depends on the player and the format only, so this
table is the same for every team and every week.

| Canonical value | `dynasty_main` obj $ | % of budget | raw % | `dynasty_new` obj $ | % of budget | raw % |
|---|---|---|---|---|---|---|
| 500 | $0 | 0.0% | 0% | $0 | 0.0% | 0% |
| 1000 | $0 | 0.0% | 0% | $0 | 0.0% | 0% |
| 1500 | $0 | 0.0% | 0% | $0 | 0.0% | 0% |
| 2500 | $100 | 100.0% | 110% | $0 | 0.0% | 0% |
| 3000 | $100 | 100.0% | 140% | $0 | 0.2% | 0% |
| 3500 | $100 | 100.0% | 171% | $37 | 37.0% | 37% |
| 4000 | $100 | 100.0% | 202% | $100 | 100.0% | 104% |
| 5000 | $100 | 100.0% | 263% | $100 | 100.0% | 144% |
| 6000 | $100 | 100.0% | 324% | $100 | 100.0% | 183% |
| 7500 | $100 | 100.0% | 416% | $100 | 100.0% | 243% |
| 9000 | $100 | 100.0% | 508% | $100 | 100.0% | 303% |
| 9999 | $100 | 100.0% | 570% | $100 | 100.0% | 342% |

Read this carefully: **these breakpoints straddle the entire interesting
region.** In `dynasty_main` everything below 1525.5 is worth $0 and everything
above 2341 is worth the whole budget, so the requested value grid shows only
the two flats and none of the curve. The two leagues' columns differ by a
factor of ~1.6 in where the curve sits — that is the format derivation of §5
doing its job, not an inconsistency.

### 6.2 The required breakpoints — the full ladder, `dynasty_main`

Neutral team: full $100 balance, open roster spot, neutral need, bubble status,
balanced posture, against 11 rivals each holding a full budget.

| Value | obj $ | rec (offseason) | rec (wk 8) | rec (wk 14) | clearing | maxRational (wk 8) | P(win) at rec (wk 8) |
|---|---|---|---|---|---|---|---|
| 500 | $0 | $0 | $0 | $0 | $0 | $0 | — |
| 1000 | $0 | $0 | $0 | $0 | $0 | $0 | — |
| 1500 | $0 | $0 | $0 | $0 | $0 | $0 | — |
| 2500 | $100 | $27 | $37 | $46 | $47 | $78 | 0.387 |
| 3000 | $100 | $37 | $52 | $64 | $73 | $100 | 0.333 |
| 3500 | $100 | $48 | $68 | $85 | $100 | $100 | 0.285 |
| 4000 | $100 | $60 | $85 | $98 | $100 | $100 | 0.244 |
| 5000 | $100 | $83 | $99 | $99 | $100 | $100 | 0.136 |
| 6000 | $100 | $97 | $99 | $100 | $100 | $100 | 0.136 |
| 7500 | $100 | $99 | $100 | $100 | $100 | $100 | 0.140 |
| 9000 | $100 | $99 | $100 | $100 | $100 | $100 | 0.140 |
| 9999 | $100 | $99 | $100 | $100 | $100 | $100 | 0.140 |

Note the objective column is flat at $100 from 2500 up while the recommended
bid keeps climbing from $27 to $99. That gap **is** the model: everything above
the all-in line is worth the whole budget, and what separates them is how much
you have to pay.

### 6.3 Inside the band — where the curve actually lives

`dynasty_main`, `V_repl` 1525.5 → `V_allin` 2341.

| Value | `s` | obj $ | obj % | raw % | rec (offseason) | rec (wk 8) | clearing (wk 8) |
|---|---|---|---|---|---|---|---|
| 1526 | 0.001 | $0 | 0.0% | 0% | $0 | $0 | $0 |
| 1600 | 0.091 | $0 | 0.0% | 0% | $0 | $0 | $0 |
| 1700 | 0.214 | $0 | 0.0% | 0% | $0 | $0 | $0 |
| 1800 | 0.337 | $1 | 0.7% | 1% | $0 | $0 | $0 |
| 1900 | 0.459 | $4 | 4.4% | 4% | $0 | $0 | $1 |
| 2000 | 0.582 | $17 | 16.8% | 17% | $2 | $3 | $3 |
| 2100 | 0.704 | $43 | 43.0% | 43% | $7 | $10 | $10 |
| 2200 | 0.827 | $78 | 77.8% | 78% | $17 | $23 | $26 |
| 2300 | 0.950 | $99 | 99.0% | 99% | $23 | $32 | $40 |
| 2341 | 1.000 | $100 | 100.0% | 100% | $23 | $33 | $40 |
| 2400 | 1.072 | $100 | 100.0% | 104% | $25 | $34 | $43 |

The toe is long and flat by design: a player 275 points above replacement
(1800) is worth $1, and the curve only becomes steep in the top third of the
band. This is what stops "ordinary wire player" from ever pricing like an
asset.

### 6.4 `dynasty_new` — the full ladder for comparison

10-team, 10 starters, format-only anchors, offseason, neutral full-budget team
against 9 rivals.

| Value | obj $ | obj % | rec | conservative | aggressive | maxRational | clearing |
|---|---|---|---|---|---|---|---|
| 500 | $0 | 0.0% | $0 | $0 | $0 | $0 | $0 |
| 1000 | $0 | 0.0% | $0 | $0 | $0 | $0 | $0 |
| 1500 | $0 | 0.0% | $0 | $0 | $0 | $0 | $0 |
| 2500 | $0 | 0.0% | $0 | $0 | $0 | $0 | $0 |
| 3000 | $0 | 0.2% | $0 | $0 | $0 | $0 | $0 |
| 3500 | $37 | 37.0% | $5 | $3 | $11 | $16 | $6 |
| 4000 | $100 | 100.0% | $23 | $18 | $38 | $46 | $37 |
| 5000 | $100 | 100.0% | $36 | $30 | $56 | $64 | $66 |
| 6000 | $100 | 100.0% | $50 | $45 | $73 | $82 | $100 |
| 7500 | $100 | 100.0% | $73 | $65 | $93 | $100 | $100 |
| 9000 | $100 | 100.0% | $88 | $66 | $93 | $100 | $100 |
| 9999 | $100 | 100.0% | $96 | $66 | $96 | $100 | $100 |

The same player is worth a different amount in the two leagues, because the
question "would he start for everyone" has a different answer in a 10-starter
league than in a 20-starter one.

---

## 7. Worked examples

### 7.1 Worth $100, bid far less — the mechanism

Josh Jacobs (3901), `dynasty_main`, week 8, neutral full-budget team.
`objectiveCeiling = $100` (the full budget). `teamRawCeiling = $140.30`
(need 1.0 × option factor 0.717 × raw 1.958 budgets). Demand signal 0.7826.

| Bid | P(win) | Expected surplus |
|---|---|---|
| $0 | 0.000 | 0.01 |
| $20 | 0.005 | 0.56 |
| $40 | 0.044 | 4.44 |
| $60 | 0.132 | 10.58 |
| $74 | 0.209 | 13.82 |
| $80 | 0.243 | 14.63 |
| **$90** | **0.299** | **15.06** ← optimum |
| $100 | 0.354 | 14.28 |

Bidding $100 wins *more often* than $90 and is worth *less*, because the
surplus captured shrinks faster than the win probability grows. The engine
returns **$82** here — the cheapest bid within `minEdge` of the plateau — not
$90 and not $100. The player is worth the whole budget; the correct bid is not
the whole budget.

At the very top of the board the two do converge: a 9999 player in the same
spot returns `recommended = $100` with `winProbability = 0.14`, and the
engine's own explanation says so — *"the player is worth up to the entire $100
budget, but $100 is the lowest bid that still wins often enough to be worth
it."*

### 7.2 The same player, different teams

Josh Jacobs (3901), `dynasty_main`, week 8. The objective ceiling is **$100 in
every row** — it is a property of the player and the format. Everything that
moves is Stage D and Stage E.

| Team situation | obj $ | team ceiling | rec | cons | aggr | maxRational | P(win) | θ | n |
|---|---|---|---|---|---|---|---|---|---|
| Full budget, open spot, neutral, bubble | $100 | $72 | **$82** | $59 | $91 | $100 | 0.254 | 0.717 | 1.0 |
| Starter hole at the position, contender | $100 | $100 | **$97** | $59 | $97 | $100 | 0.338 | 0.825 | 1.3 |
| Already deep there, rebuilder | $100 | $40 | **$53** | $50 | $72 | $78 | 0.097 | 0.574 | 0.7 |
| Only $18 of $100 left | $100 | $18 | **$18** | $13 | $18 | $18 | 0.003 | 0.717 | 1.0 |
| Roster full, must drop a 2600 bench piece | $100 | $72 | **$61** | $56 | $85 | $93 | 0.137 | 0.717 | 1.0 |
| Roster full, must drop a 1500 bench piece | $100 | $72 | **$82** | $59 | $91 | $100 | 0.254 | 0.717 | 1.0 |
| Aggressive posture | $100 | $72 | **$100** | $59 | $100 | $100 | 0.354 | 0.717 | 1.0 |
| Conservative posture | $100 | $72 | **$66** | $59 | $91 | $100 | 0.164 | 0.717 | 1.0 |

Three things to read off this table:

* **The drop side is asymmetric on purpose.** Dropping a 2600 player costs
  $21 of recommendation ($82 → $61); dropping a 1500 player costs **nothing**,
  because 1500 is below the 1525.5 replacement line and is re-acquirable for
  free. The old system charged for both.
* **The $18 team still gets the truth.** Its objective ceiling is $100 and its
  bid is $18 — the model says explicitly *"this player is worth more ($100)
  than this team has left ($18) — the bid is capped by the balance, not by
  value"*, and it still reports a $100 expected clearing price so the manager
  knows they are outgunned rather than being told nobody wants him.
* **Posture moves only the bid.** Every row's objective column is identical.

### 7.3 Early season, mid season, late season

Josh Jacobs (3901), `dynasty_main`, neutral full-budget team.

| Phase | θ | team ceiling | rec | cons | aggr | maxRational | clearing |
|---|---|---|---|---|---|---|---|
| Offseason | 0.450 | $45 | $58 | $54 | $81 | $88 | $100 |
| Week 1 | 0.550 | $55 | $68 | $59 | $91 | $100 | $100 |
| Week 5 | 0.618 | $62 | $74 | $59 | $91 | $100 | $100 |
| Week 8 | 0.717 | $72 | $82 | $59 | $91 | $100 | $100 |
| Week 11 | 0.846 | $85 | $92 | $59 | $91 | $100 | $100 |
| Week 14 (final waiver period) | 1.000 | $100 | $97 | $59 | $97 | $100 | $100 |
| Week 8, eliminated | 1.000 | $100 | $97 | $59 | $97 | $100 | $100 |
| Week 8, contender | 0.825 | $82 | $90 | $59 | $91 | $100 | $100 |
| Week 8, rebuilder | 0.574 | $57 | $70 | $59 | $91 | $100 | $100 |

The **clearing price does not move**. The season phase relaxes what *we* are
willing to commit; it does not claim rivals will pay more in December. If bids
rise late it will be because rival balances and demand actually changed, which
enters through Stage E.

An eliminated team in week 8 behaves exactly like every team in week 14 —
correct, since neither has any future claim to save for.

### 7.4 The real 2026-08-04 wire, old versus new

`dynasty_main`, offseason, neutral full-budget team, live anchors.

| Player | Value | NEW obj $ | NEW rec | NEW cons | NEW aggr | NEW max | NEW clearing | OLD reasonable / aggressive |
|---|---|---|---|---|---|---|---|---|
| Marlin Klein (TE) | 1908 | $5 (5.0%) | $0 | $0 | $2 | $2 | $1 | **$21 / $30** |
| Tanner Koziol (TE) | 1865 | $2 (2.4%) | $0 | $0 | $1 | $1 | $0 | **$20 / $29** |
| Joe Royer (TE) | 1668 | $0 (0.0%) | $0 | $0 | $0 | $0 | $0 | **$19 / $27** |
| Will Levis (QB) | 1132 | $0 (0.0%) | $0 | $0 | $0 | $0 | $0 | **$14 / $20** |

The engine's explanation for Levis: *"No bid. Will Levis grades at or below the
1526 free-agent baseline — comparable production is available for nothing."*
For Klein: *"A minimum or $0 claim is enough here — worth up to $5 of the
original $100."*

This is the whole point of the redesign in four rows. The best player on an
August dynasty wire is a $0–$2 claim, and the old formula priced him at $21.

---

## 8. What is deliberately NOT double-counted

The single most common failure in the old system was one signal entering the
answer through several multiplicative doors. The engine enforces the
separations structurally, not by convention.

| Signal | Enters exactly once, at | Never enters at |
|---|---|---|
| Dynasty outlook, age, positional scarcity | The canonical `rankDerivedValue` itself | Any FAAB multiplier |
| League format (teams × starters) | Stage A anchors | The bid ladder |
| The drop side | Stage B, as surplus over replacement | Stage E |
| This roster's shape at the position | Stage D, `positionalNeed` | The objective ceiling |
| Contender / rebuilder urgency | Stage D, on the **option factor** | The player's value |
| Time remaining in the season | Stage D, on the **ceiling** | The clearing price |
| Market demand (trending, crowd bids, rival need) | Stage E, on rival engagement | The objective ceiling, the team ceiling |
| A manager's personal bidding history | Stage E, as `aggression` on that rival | Anything about the player |
| The team's remaining balance | The bid's `hardCap` | The objective ceiling, and `teamRawCeiling` |

### Where every old factor went

The old `recommend_faab` started from `_compute_faab_bid` and multiplied it by
up to five independent factors, with nothing bounding their product. A trending
player at a position the league bid hot could be marked up ~3.5× off a baseline
that was already 21% of budget.

| Old factor | Old constant | Disposition |
|---|---|---|
| Value-gain modifier | `_VALUE_MOD_FLOOR 0.5` … `_VALUE_MOD_CEILING 1.8` | **Relocated.** Became Stage B: the drop side is subtracted as surplus over replacement, symmetrically with the add. |
| Sleeper trending kicker | `_TRENDING_TIER_BREAKPOINTS` (+10% / +15% / +20%) | **Demoted to evidence.** Reported as a factor row (`_demand_evidence_factors`) and reflected once in Stage E's demand term. It can raise the price you must pay; it can no longer raise what the player is worth. |
| League-historical position blend | `_LEAGUE_CALIBRATION_BLEND 0.5` | **Replaced.** Became the fitted priors in `faab_history.py`, applied per-manager as a rival aggression factor — and now built on data that *keeps* $0 bids (§9). |
| Budget-environment scale | `_ENV_SCALE_TARGET_SHARE 0.08`, `_ENV_SCALE_CLAMP (0.6, 1.6)`, `_ENV_MIN_BIDS_ANALYZED 10` | **Removed.** It was a second reading of the same league bid temperature as the position blend — the old code already carried a guard against that double-count, and the guard's existence was the tell. League temperature now enters once, through the rival share curve. |
| Replaceability gate / ceiling dropoff | `_DROPOFF_GATE 0.15`, `_CEILING_DROPOFF_CLAMP 0.5`, `_CEILING_DROPOFF_SCALE 0.5` | **Absorbed.** "Is there a comparable player available for free" is exactly what `V_repl` measures, applied to *every* claim rather than as a special-case gate. |
| Rival-contention raise | ad-hoc `standard = clearing` | **Replaced.** Became the full expected-surplus optimisation. The old version raised the bid to the clearing price whenever that was affordable, which is precisely the "bid your max" behaviour that captures zero surplus. |
| KTC crowd bid blend | `_ktc_crowd_blend` | **Demoted to evidence.** Reported, not multiplied. |
| Pacing warning | `_PACING_WARN_SHARE 0.40` | **Superseded.** The engine warns from the actual numbers (`objectiveDollars > remaining`), not from a share threshold. |
| `max` = team's `faabRemaining` | — | **Replaced** by `maxRational` = `min(remaining, floor(max(rawCeiling, displayedCeiling)))`, bounded by both the player's worth *and* the balance. |

---

## 9. Historical calibration and backtest

### 9.1 The league's real bidding behaviour

`scripts/fetch_faab_history.py` walks the Sleeper league chain backwards
through `previous_league_id` and persists every completed `waiver` /
`free_agent` add with its winning bid. Everything is normalised to **percent of
that season's original budget**, never dollars — this league ran $1,000 in
2024, $200 in 2025 and $100 in 2026.

`dynasty_main`, per season:

| Season | Budget | Adds | Median bid | p90 bid | Max bid | $0 share |
|---|---|---|---|---|---|---|
| 2026 | $100 | 90 | $1 | $5 | $52 | 42.2% |
| 2025 | $200 | 457 | $0 | $12 | $123 | 61.3% |
| 2024 | $1,000 | 148 | $0 | $100 | $340 | 50.7% |

Combined, as % of budget:

| League | Adds | Median | p75 | p90 | Max | Nonzero median | $0 share |
|---|---|---|---|---|---|---|---|
| `dynasty_main` | 695 | **0.00%** | 2.00% | 6.00% | 61.5% | 2.00% | **56.6%** |
| `dynasty_new` | 312 | **0.00%** | 6.00% | 15.00% | 65.0% | 6.00% | **50.3%** |

**The league's median winning bid is 0–1% of budget.** The old system's flat
21% sat above the 99th percentile of anything either league has ever paid.

### 9.2 The zero-bid audit finding

`src/api/faab_analytics.py` gates its league average and median on `bid > 0`
(line 220, `if bid > 0: all_bids.append(bid)`). With 42–61% of adds costing
exactly $0, that turns a true median of **0.00%** of budget into a reported
median of **2.00%**. Those excluded bids are not noise — they are the modal
outcome, and "how often does a claim go uncontested" is the single most
important number in the market model.

That inflated median fed the old recommender's league-calibration blend and its
budget-environment scaling, so the bias propagated straight into the bid.

`src/trade/faab_history.py` keeps zero bids and reports `zeroBidShare`
explicitly. Note the module docstring characterises the analytics gap as a
"200x overstatement"; that is rhetorical shorthand — a ratio against a true
median of zero is undefined. The precise statement is: **the reported league
median is 2% of budget when the true median is 0%.**

`faab_analytics.py` has **not** been changed; it still powers the historical
context panel. Anything reading `leagueMedianWinningBid` is reading a
nonzero-only median.

### 9.3 Fitting the market model

Rival bids are fitted as a zero-inflated lognormal against the **bands below
the all-in line only**. Above that line the join is look-ahead biased: every
historical claim is priced against **today's** canonical value, so a player
added for $0 in 2024 who has since broken out now grades 3900 and makes the
top bands look artificially cheap. Above the line the parameters come from
principle plus the §5 human anchors and the observed maxima (61.5% and 65% of
budget).

Re-derived at documentation time — observed distribution from the 384 claims
that join to a canonical value, model prediction from `rival_bid_cdf` at each
band's mean value against 11 full-budget rivals:

| Value band | n | observed $0 share | model $0 share | observed p90 | model p90 |
|---|---|---|---|---|---|
| < 1200 | 74 | 44.6% | 56.9% | 3.0% | 4% |
| 1200–1700 | 191 | 55.0% | 56.9% | 6.0% | 4% |
| 1700–2100 | 63 | 46.0% | 50.0% | 7.5% | 5% |
| 2100–2600 | 24 | 45.8% | 0.6% | 12.5% | 100% |
| 2600+ | 32 | 62.5% | 0.1% | 7.0% | 100% |

The three clean bands fit well on the quantity that matters most (the zero
share) and slightly under-predict the p90. The two bands above the all-in line
diverge completely — the model says a 2400 player is essentially always
contested and clears near the full budget, while history says he went for
12.5% at p90. **That divergence is the look-ahead bias, not a model error, and
it is exactly why the fit deliberately ignores those bands.** It also means
those two rows are *not* evidence the model is right up there.

The observed percentiles recorded at fit time (5.0% / 7.0% / 15.0% for the
three clean bands) differ from this re-derivation (3.0% / 6.0% / 7.5%). I could
not reconcile that offline — the fit-time figures appear to have been measured
against a different join than the 384-claim canonical-value join used here.
The zero-shares agree closely in both, and both agree on the shape.

### 9.4 Backtest: OLD versus NEW

`python scripts/faab_backtest.py --league dynasty_main`. 384 of 695 persisted
claims (55.3%) join to a canonical value today. **Read `scripts/faab_backtest.py`'s
five stated caveats before quoting any of this** — it is a structurally biased
comparison, and the script says so at the top of every run.

| Metric | Actually spent | OLD | NEW |
|---|---|---|---|
| Claims priced | 384 | 384 | 384 |
| Would have won | — | 366 (95.3%) | 239 (62.2%) |
| Total FAAB committed (budget-units) | **9.25** | **45.51** | **31.14** |
| Median overpayment when winning | — | **$20.00** | **$0.00** |
| Mean overpayment when winning | — | **$34.73** | **$57.38** |
| Average recommendation | $7.79 (avg actual) | $39.12 | $37.62 |

Edge cases, against the backtest's own anchors (`V_allin` 2168, `V_repl` 1376):

| Failure mode | Population | OLD | NEW |
|---|---|---|---|
| Low-value overbid — below replacement, bid > 5% of budget | 145 claims | **145 of 145** | **0 of 145** |
| Impactful player missed — above the all-in line, bid below the winner | 50 claims | 1 | **0** |

Per value band, average recommendation as % of budget:

| Band | n | avg actual | OLD | NEW | OLD win % | NEW win % |
|---|---|---|---|---|---|---|
| < 1200 | 74 | 1.76% | 9.33% | **0.00%** | 95.9 | 44.6 |
| 1200–1700 | 191 | 2.32% | 10.91% | **0.00%** | 93.7 | 55.0 |
| 1700–2100 | 63 | 3.03% | 13.56% | 7.55% | 98.4 | 73.0 |
| 2100–2600 | 24 | 4.54% | 14.84% | 35.40% | 91.7 | 95.8 |
| 2600+ | 32 | 1.64% | 17.69% | 55.90% | 100.0 | 100.0 |

**Honest reading of the win rate.** NEW's 62.2% is lower than OLD's 95.3%, and
that is intended, not a regression. OLD buys its win rate by committing 45.5
budget-units against the 9.25 actually spent — it wins nearly everything
because it bids roughly five times the market on every claim. All 145 of NEW's
"losses" are claims that genuinely cost money, at a median of $5; 138 of them
are players NEW priced at $0 because they grade below the replacement anchor
on today's board. NEW is declining to buy players it says are freely
replaceable, and the cost of declining all 145 was 7.56 budget-units of claims
it did not make.

**Honest reading of the overpayment.** NEW's *median* overpayment when winning
is $0 against OLD's $20 — NEW routinely pays the market price exactly. Its
*mean* is worse, $57.38 against $34.73, and that number should not be waved
away. It is dragged by 32 wins with overpayment above $100, essentially all of
them 2024 ($1,000 budget) and 2025 ($200 budget) claims on players who cleared
for $0–$13 at the time and grade 3,500–3,900 today: Edgerrin Cooper ($0 actual
vs $705 recommended), Dallas Turner ($0 vs $887), Brenton Strange ($5 vs $891).
Those are look-ahead artifacts — the model is being asked to price a breakout
that had not happened yet — but the mean is the mean, and a reader is entitled
to know NEW's tail is fatter than OLD's on the joined sample.

**The one clean signal.** Below the replacement anchor, where look-ahead bias
cuts the *other* way (a player who is bad today was probably not better then),
NEW eliminates all 145 low-value overbids and misses nothing impactful. That
band is 38% of the sample and it is the failure mode the redesign existed to
fix.

---

## 10. Limitations, and what would improve this

1. **The toe is sensitive to the replacement anchor.** Marlin Klein (1908)
   prices at 12.1% of budget on the format-only anchor (`V_repl` 1383) and
   **5.0%** on the live blended anchor (`V_repl` 1525.5). The `ceilingCurve`
   config comment cites the 12% figure, which is the format-only number; the
   live `/waivers` path serves the 5% one. Both are "correct" for their anchor
   set, but a reader comparing the config comment to the UI will see a
   discrepancy. A live pool snapshot is not always available (offline scripts,
   the `waiver.py` no-context path), so the two paths will keep diverging until
   the anchor source is stamped alongside every quoted calibration number.

2. **Above the all-in line the market model is unvalidated.** §9.3 shows the
   fit only covers the three bands below it. The parameters up there come from
   principle plus two human anchors plus the observed maxima. Nothing in the
   available data can confirm or refute them, because no historical board
   snapshot exists to join a 2024 claim to a 2024 value.

3. **No historical board snapshots.** This is the root cause of limitation 2
   and of every backtest caveat. The platform keeps no board snapshot reaching
   back to 2024. Persisting a weekly `rankDerivedValue` snapshot going forward
   is the single highest-value change available — one season of it would make
   the backtest unbiased and would let the above-all-in parameters be fitted
   rather than asserted.

4. **Sleeper never exposes losing bids.** "Would have won" is measured against
   the winning bid alone and is an optimistic upper bound: a recommendation
   that ties or beats the winner is scored a win, even though the real auction
   might have drawn a higher losing bid once our bid existed.

5. **`dynasty_new`'s anchors here are format-only.** No roster snapshot for
   that league exists in this working copy, so every `dynasty_new` number in
   §6 omits the live-pool blend. On the live server it is included.

6. **The backtest and the server disagree on `startersPerTeam`.**
   `scripts/faab_backtest.py::_league_format` sums **all** starter slots
   including K (21 for `dynasty_main`), while `server.py` excludes K (20). The
   backtest therefore ran with `V_allin = 2168` at rank 252 rather than the
   live 2341 at rank 240. The direction is conservative for the backtest (a
   lower all-in line makes NEW bid *more*, so NEW's spend figures are if
   anything overstated), but the two should agree.

7. **In-code fallback defaults diverge from the shipped config.**
   `FaabConfig.num` substitutes a default when a key is missing — it does not
   fail, despite the class docstring's "fails loudly at the boundary". Where
   the two disagree, a missing or corrupt `faab.json` silently changes
   behaviour rather than erroring:

   | Key | Config | In-code default |
   |---|---|---|
   | `market.engagementBaseRate` | 0.05 | 0.06 |
   | `market.engagementMaxRate` | 0.70 | 0.85 |
   | `market.engagementExponent` | 0.90 | 1.5 |
   | `market.rivalSigma` | 1.10 | 0.95 |
   | `market.rivalMaxSharePct` | 45.0 | **38.0** in `rival_bid_cdf`, **45.0** in `rival_expected_bids` |

   The last row is an internal inconsistency: with the config present both read
   45.0, but the contention panel and the clearing math would disagree without
   it.

8. **Four config keys are inert.** `seasonPhase.regularSeasonWeeks` and
   `seasonPhase.defaultPlayoffWeekStart` are never read (the engine uses
   `LeagueContext.playoff_week_start` from live Sleeper settings).
   `positionalNeed.applyToObjectiveValue` and `market.unknownBalanceAssumption`
   are documentation of behaviour that is structurally hard-coded — correct as
   documentation, misleading as switches.

9. **Two config comments are stale.** `market._comment` says "observed max 52%
   of budget" — that is the 2026 maximum; the all-history maximum is **61.5%**
   (`dynasty_main`) and **65%** (`dynasty_new`). It also says "45–64% of adds
   cost nothing"; the measured per-season range is **41.4%–76.9%** and the
   combined figures are 56.6% / 50.3%. The comment also describes a key named
   `medianShare` "as a share of their own ceiling", which is not what the code
   does — `rivalDisciplineFactor` multiplies a share of the **original budget**
   (the code comment in `rival_bid_cdf` explains why the decoupling is
   deliberate).

10. **`dropCost.dropSurplusWeight` ships at 1.0 while its own comment argues
    for less than 1.0.** The swap is currently treated as pure zero-sum; the
    comment's reasoning (the dropped player retains trade/stash value you keep
    by *not* claiming) is unimplemented.

11. **What data would help most, ranked.** (a) Weekly board snapshots, per
    limitation 3. (b) Per-league roster snapshots persisted alongside the bid
    history, so the backtest could reconstruct balances, drop sides and
    positional need at claim time instead of running every claim against the
    most competitive field the league could field. (c) Any source of *losing*
    bids — a league that records them, or manual entry — which would let the
    rival distribution be fitted directly instead of inferred from winners.

---

## Reproducing everything in this document

```bash
# league bid history (network; writes data/faab/bid_history_<leagueKey>.json)
python scripts/fetch_faab_history.py --league dynasty_main
python scripts/fetch_faab_history.py --summary-only

# OLD vs NEW replay
python scripts/faab_backtest.py --league dynasty_main
python scripts/faab_backtest.py --json > /tmp/faab_backtest.json

# the engine's own regression suites
python -m pytest tests/trade/test_faab_engine.py \
                 tests/trade/test_faab_calibration.py \
                 tests/trade/test_faab_recommender.py \
                 tests/trade/test_waiver.py \
                 tests/api/test_faab_recommend_endpoint.py -q
```

`tests/trade/test_faab_calibration.py` is the file that pins the §6 shape —
replacement-level players priced at $0, ordinary wire players at ≤ $1, the
mapping nonlinear and monotonic, and the top of the scale at a full ceiling.
