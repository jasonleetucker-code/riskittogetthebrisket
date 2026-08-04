# Insider Trading — lead scoring

*Which league-mate should I call about this player, and why?*

This is the **league-scoped** product. Its cohort is exactly "the other managers in the
selected league" — no skill filter is applied or implied. The global, skill-filtered
product is Sharp Tracker (`docs/intel/SHARP_SCORE.md`), and the two never share a cohort,
a route, or a service.

---

## 1. The two modes

Both modes read the **same** cross-league observations from opposite sides. One ledger
query serves either, which is why a mode switch is a re-score and not a re-crawl.

| Mode | The question | Scores their… | Current owner |
|---|---|---|---|
| **Sell** (`mode="sell"`) | "I want to move X — who wants him?" | **buying** of X elsewhere | excluded (you are not a lead for your own player) |
| **Buy** (`mode="buy"`) | "I want X — who has him and what do they want?" | **selling** of X elsewhere | included and flagged `ownsAsset` |

The API takes the *product* mode; `lead_service.build_leads` takes the *observation*
direction. They are deliberately inverted at exactly one place
(`server.py::_build_intel_leads`), so the mapping is stated once:

```
sell mode  →  direction="buy"   (score how much they BUY him)
buy  mode  →  direction="sell"  (score how much they SELL him)
```

## 2. The score

`src/intel/leads.py`. Additive on a 0–1 scale, displayed ×100.

| Term | Weight | Source |
|---|---|---|
| Demonstrated interest | 0.34 | ledger — trades for/against this asset in their OTHER leagues |
| Trade-partner fit | 0.26 | `roster_intel.partner.assess_partner` |
| Positional need | 0.18 | `roster_shape.team_signals` deficit (or surplus, in buy mode) |
| Value match | 0.12 | do they hold anything near this asset's value |
| Activity | 0.10 | completed trades vs the league mean |
| Contradiction penalty | −0.20 max | they have moved him **both** ways |
| Thin-evidence penalty | −0.12 max | one observation in one league |

Deliberately **not** log-odds. `partner.py` uses odds accumulation because it is
estimating something probability-shaped; a lead score is a *ranking*, and borrowing the
odds machinery would imply a calibration that does not exist.

**Recency** is a 45-day half-life on the last observation, not a window cut — a lead does
not blink out overnight, and an acquisition 300 days ago still registers faintly.

**Breadth beats repetition.** Two acquisitions in two different leagues outrank two in
one league: repeated exposure to the same league's price is weaker evidence of appetite
than paying for him twice against different markets.

**Both counts always render.** A manager with 2 buys and 1 sell shows `2 / 1 opp`, never
`+1`. That is the same rule the board follows, for the same reason — a net figure hides
whether the evidence is one-sided or contradictory.

## 3. Why this composes `roster_intel.partner` rather than extending it

`assess_partner` already models positional need, competitive window, market fairness and
activity as a bounded log-odds accumulation with calibrated confidence. Adding a
"demonstrated interest" term *inside* it was rejected for three reasons:

1. **Different questions.** `partner.py` scores a trade *shape*; a lead score answers a
   *manager* question about one specific player. Revealed preference for one player is
   evidence for the second and mostly noise for the first.
2. **Blast radius.** Five surfaces consume `assess_partner` (gameplan, trade suggestions,
   angle, the roster engine, the terminal). Injecting a term into its logit budget moves
   every one of their numbers.
3. **It is pinned as a closed set.** `contributions` is asserted by exact set equality and
   a separate test independently reimplements the assembly over the `MAX_*_LOGIT`
   constants. Those tests exist to stop a term being bolted on casually.

So partner fit enters as **one bounded input among several**. Its own module already
pre-declared this hook, in `partner.describe_limitations()`: *"Cross-league decision data
from `src/intel/` if it ever captures offers rather than only completed trades."*

**Normalisation trap.** `partner.py`'s fit score cannot reach 100 by construction.
Normalising against a nominal 100 would silently halve this term, so it is divided by
`partner_model.FIT_SCORE_REACHABLE_MAX` and pinned by
`tests/intel/test_leads.py::TestPartnerFitNormalisation`.

## 4. What is observable and what is not

**Demonstrated interest is the one genuinely new evidence type here, and unlike
acceptance it IS observable**: a manager who traded *for* this player in another league
revealed a preference, in public, with real assets.

Everything else is inference, and inherits `partner.py`'s epistemic rule verbatim: **a
lead score ranks who to approach first; it is never a prediction that anyone accepts.**
Sleeper does not record declined offers at all, so an acceptance rate is unobservable —
not merely unmeasured. `describe_limitations()` says so in the payload,
`tests/intel/test_leads.py::TestEpistemics` asserts no `probability`-shaped key can appear
anywhere in it, and the UI renders the limitations block rather than hiding it behind a
tooltip.

**Absence of observed interest is not evidence of disinterest.** Managers with no
observations stay on the ranked list, below those with signal, rather than being filtered
out — filtering would present our crawl coverage as a fact about the manager.

## 5. Home-league exclusion

`home_league_ids` drops the league being asked about. Without it, "has my league-mate
bought this player *elsewhere*" would count the trade made in *this* league, and every
current owner would read as an enthusiastic buyer of their own player. Pinned by
`tests/intel/test_lead_service.py::TestHomeLeagueExclusion`.

## 6. Degradation

Every input below the ledger is optional, because a missing contract is the normal state
of a fresh process:

| Missing | Effect |
|---|---|
| loaded contract | no rosters/positions/values → fit, need and value terms abstain (`partnerFitScore: null`) |
| league starter settings | `roster_shape.team_signals` returns `{}` rather than guessing a lineup |
| roster snapshot for one manager | that manager's fit term abstains; the others are unaffected |
| `assess_partner` raising | logged, that lead scores without the fit term |
| snapshot for the league | 503 `data_not_ready` — the one hard failure, because there is no pool to rank |

A blank fit renders as an em dash, never `0.0`, so "not computed" and "computed as bad"
cannot read the same.

## 7. Surfaces

- `POST /api/intel/leads` — `{assetId | playerId | name, mode, leagueKey}`. The body is
  parsed **before** the league resolver so a body `leagueKey` reaches it (the POST
  convention used by the other league-scoped endpoints).
- `frontend/components/InsiderLeads.jsx` — mode toggle, ranked table, per-component
  breakdown on expand, limitations footer. Pure renderer.
- `/league/insider-trading` — the board's drill-down gains an **Evidence / Trade leads**
  tab split (observation vs inference, kept visibly separate), plus a name lookup so leads
  are reachable for a player who has not moved and therefore has no board row.

## 8. Tests

| File | Covers |
|---|---|
| `tests/intel/test_leads.py` | the scorer: term behaviour, penalties, ranking, epistemics |
| `tests/intel/test_lead_service.py` | assembly: home-league exclusion, mode symmetry, league scoping, roster shape |
| `tests/intel/test_endpoints.py::TestLeads` | HTTP: auth, 400/503, mode stamping, waiver-is-not-interest, missing-contract degradation |
| `frontend/__tests__/components/insider-leads.test.jsx` | UI: mode flip, both-sides rendering, limitations, no probability language |
