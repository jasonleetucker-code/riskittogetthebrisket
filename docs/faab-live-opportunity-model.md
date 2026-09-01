# Live Waiver Opportunity — design and calibration record

Status: **APPROVED SCOPE, IN IMPLEMENTATION.** Extends, does not replace,
`docs/faab-model.md` (the FAAB engine reference) and
`docs/FAAB_MARKET_SIGNAL_NORMALIZATION_2026-08-14.md` (owner spec, issue
#830). Those two remain binding for the objective-ceiling/recommended-bid
separation, the market model, and crowd comparability — none of that changes
here. This document covers only the new Live Waiver Opportunity layer and the
two pre-existing defects fixed alongside it.

## 1. Root cause, with real numbers

Reproduced live against the real 2026-09-01 board
(`exports/archive/dynasty_export_20260901_120444.zip`, built through the
actual `src.api.data_contract.build_api_data_contract` pipeline — not hand
math) before any code changed:

**Cyrus Allen** (rookie WR, board value 2282, confidence `low`, 3 sources):

| Path | Result |
|---|---|
| `/api/waiver/suggestions` (`waiver.py::_compute_faab_bid`) | **aggressive $85 / reasonable $60 / lowball $30** |
| `/api/waiver/faab-recommend`, no rival balance data | **recommended $0** (objective ceiling $85, but nobody's contest is modeled) |
| `/api/waiver/faab-recommend`, 11 rivals at full $100 balance, neutral need (the *most* contested plausible scenario) | **recommended $19** |

The owner's complaint ("approximately $40") sits between these two numbers,
consistent with whatever mix of real (partial) rival balances the live page
had at the moment they looked. **Root cause confirmed**: `/suggestions` used
a fixed-multiplier shim (`reasonable = 0.70 × ceiling×budget`) with **no
market/rival model at all**, while `/faab-recommend`'s full engine
appropriately damps the same player toward $0–$19 once contested demand is
actually modeled. Two different formulas, same player, same moment — a 3–4x+
divergence with no way for the owner to know which number to trust.

**A second, larger finding from the same run**, not previously known: on the
real board, every other named September-1 benchmark player *except* Cyrus
Allen prices at **exactly $0 under both current formulas** —

| Player | Board value | Position | Current `/suggestions` (agg/reas/low) | Current `/faab-recommend`, 11 full-balance rivals |
|---|---|---|---|---|
| George Holani | 1464 | RB | 0 / 0 / 0 | $0 |
| Jacob Saylors | 74 | RB | 0 / 0 / 0 | $0 |
| Kamren Kinchens | 1593 | DB | 0 / 0 / 0 | $0 |
| Seth McGowan | 1607 | RB | 0 / 0 / 0 | $0 |
| Barion Brown | 1438 | WR | 0 / 0 / 0 | $0 |
| Derrick Moore | 1955 | DL | 3 / 2 / 1 | $0 |
| Jonas Sanker | 1998 | DB | 7 / 5 / 2 | $0 |
| Justice Hill | 1379 | RB | 0 / 0 / 0 | $0 |
| Malik Benson | 1411 | WR | 0 / 0 / 0 | $0 |
| Dohnte Meyers | 711 | WR | 0 / 0 / 0 | $0 |
| Jer'Zhan Newton | 1816 | DL | 0 / 0 / 0 | $0 |
| Carson Wentz | **not on the canonical board at all** | — | — | — |
| Aaron Donald | **not on the canonical board at all** | — | — | — |

The league-wide replacement anchor on this board is `V_repl = 1607` (12 teams
× 20 starters × 2.0 replacement multiple). Every one of these players sits at
or below it — the canonical dynasty consensus, which is thinly sourced for
deep rookies and moves on a scrape/refit cadence, has not yet recognized any
of them as rosterable, even though the owner's own human review (informed by
live roster cuts, depth-chart clarity, and Sleeper's own suggested-bid
ranges) says otherwise for most of them. Aaron Donald (a just-returned veteran
with essentially no active dynasty market yet) and Carson Wentz have **zero**
canonical coverage — not a low value, an absent one.

**This is the same problem stated twice, in opposite directions**: Cyrus
Allen is one player where the *market/contention* layer failed to discipline
a high raw ceiling; the other eleven are where the *value* layer has nothing
current enough to price a real opportunity at all. Fixing the engine
unification (§3) addresses the first. The Live Waiver Opportunity layer (§2)
addresses the second — and it is the larger, more consequential gap: eleven
of thirteen benchmark players are wrong in the underpricing direction on the
real board, not just the one overpriced outlier the complaint named.

## 2. The Live Waiver Opportunity layer

New, FAAB-scoped concept — never a second canonical player-value owner (same
posture BDVM already establishes: "never touches `rankDerivedValue`...
additive by construction"). Owned by `src/trade/faab_opportunity.py`.

```
opportunity_value(player) = dynasty_value
                             + retention(dynasty_value) × short_term_surplus
```

- **`dynasty_value`** — unchanged `rankDerivedValue`. Represents "does this
  player stay worth something once the immediate situation passes."
- **`short_term_surplus`** — sum of independently-weighted sub-scores, each
  bounded and each inspectable (feeds the UI's factor rows):
  - **role sub-score** — from `src/playerctx/` (live, weekly snap
    share/trend/depth rank) — the single genuinely-live role signal already
    in production.
  - **event sub-score** — from the (extended) BDVM structured event ledger,
    `data/bdvm/events/<season>.json`, read-only. An auto-classified news
    event stays capped below the speculation-confidence threshold (0.45,
    unchanged from `news_events.py`) and can widen uncertainty but never move
    this sub-score's mean by itself — the same non-negotiable rule that
    module already enforces. Only measured role/depth-chart/injury evidence,
    never raw prose, is allowed to move the mean.
  - **market-heat sub-score** — Sleeper trending velocity, **used only in
    the engine's Stage E market layer (§3.2), never here.** Kept out of
    `short_term_surplus` by construction: worth and demand are different
    axes and this file only ever answers the worth question.
- **`retention(dynasty_value)`** — monotonic 0→1 curve. Config category **D
  (explicitly provisional)**: starts flat at `1.0` (fully additive) until
  outcome data exists to fit a real shape. Its presence, not its initial
  value, is what keeps a discontinuity from being possible: `short_term_surplus`
  is bounded independently of `dynasty_value`, so a 1-point change in the
  dynasty board can never produce a large jump in `opportunity_value`.

### What does NOT change

Stage A anchors (`resolve_anchors`) stay computed off the stable canonical
board exactly as today. Rival need-classification (`classify_need`) stays on
canonical value. Both represent "where does the league-wide bar sit" and
"how deep is an existing roster", which must not whipsaw on every news cycle.
Only the single per-claim `add_value` that feeds `objective_ceiling`/
`team_ceiling` for the specific player under evaluation is affected.

### Shadow-first rollout

Feature flag `waiver_live_opportunity` (new, `src/api/feature_flags.py`,
default shadow-only). Both the canonical-only value and the opportunity value
are computed and fed through `faab_engine.recommend()` independently; only
the canonical-only result is shown live. Both are logged to
`data/faab/shadow_comparisons_<leagueKey>.json`. Promotion to the live
response is a separate, explicit, human-reviewed step — never automatic, per
CLAUDE.md's champion/challenger invariant.

## 3. The two independent defect fixes (ship regardless of §2)

### 3.1 Unify `/api/waiver/suggestions` with the full engine

`waiver.py::_compute_faab_bid` stops using the fixed 0.70/0.35-of-ceiling
shim and calls `faab_engine.recommend()` (the same path `/faab-recommend`
uses) whenever league/team/rival context is available, via
`faab_recommender.build_rivals` (reused, not reimplemented). Falls back to a
clearly-labeled ceiling-only estimate — stamped as such, never presented as
the market-aware number — only when no league context exists at all (e.g. a
bare unauthenticated call).

### 3.2 Wire Sleeper trending into `demand_signal`, bounded

Trending count (plus new drop/velocity data, §4) enters
`_rival_engagement`'s `p_i` / `rival_bid_cdf`'s `share` term only — never
`objective_ceiling`. A new `trendingEngagementLift` config constant (same
shape as the existing `crowdEngagementLift`) bounds its contribution so a
single viral add-count spike can raise expected competition but never
dominate it.

### 3.3 `faab_analytics.py`'s zero-bid gate — investigated, not a live defect

The audit initially flagged this module as still gating its league-wide
avg/median on `bid > 0`, per `docs/faab-model.md` §9.2's own text. Reading
the file at HEAD disproved this: `all_bids.append(bid)` already runs
unconditionally, with an explicit in-code comment documenting why zero bids
are kept. Only `docs/faab-model.md` was stale (corrected there). A
`zeroBidShare` field was added to `faab_analytics.py`'s output for parity
with `faab_history.py`'s existing field of the same name, so the "league FAAB
context" panel and the engine's own market priors can never silently disagree
about what fraction of the league's real bids were $0.

## 4. Data sources, cadence, and category

| Source | Module | Cadence | Config category |
|---|---|---|---|
| Canonical dynasty board | existing pipeline | scrape cadence (~2h) | unchanged |
| Snap share / trend / depth rank | `src/playerctx/` | weekly (systemd) | reused as-is |
| BDVM structured events | `src/bdvm/news_events.py` | daily (systemd, existing) | reused, ontology extended |
| Sleeper trending adds+drops, with history | `src/adapters/sleeper_trending.py` + new history script | in-process 15-min TTL, new disk snapshots for velocity | new |
| Anchors (`V_allin`/`V_repl`) | `faab_engine.resolve_anchors` | per request, off live board | unchanged |
| Rival balances | live Sleeper overlay | per request | unchanged |

**Ontology extension, scoped after inspection rather than added wholesale.**
`DEPTH_CHART_PROMOTION`'s existing regex already matches "named the starter" /
"promoted to" / "elevated to the starting/first [team]" — a candidate
`PROMOTED_TO_STARTER` type would have duplicated it for no behavioral gain,
since `faab_opportunity.py` reads the ontology's `mu_pct` regardless of which
type fired. `PRACTICE_SQUAD_ELEVATION`/`SIGNED_OFF_WAIVERS` are roster-
*transaction* facts, not narrative facts, and belong on a Sleeper-transaction
event source that does not exist yet — registered nowhere, a genuine
follow-up rather than fabricated here. The one real gap: nothing covered
"committee backfield / timeshare / unclear role" language, which asserts
*less certainty*, not a directional change — added as `ROLE_UNCERTAIN`
(`role_uncertainty_delta` + `sigma_mult` only, deliberately no `mu_pct`) plus
a keyword rule placed last in `news_events.py`'s priority order so it can
never shadow an existing rule. 336 pre-existing BDVM tests pass unchanged.

Config parameter provenance (directive category labels):
- **A (directly derived)**: anchors, starter-slot counts — already so, unchanged.
- **B (empirically fitted)**: existing `market.*` rival model constants —
  already fitted from real bid history, unchanged.
- **C (documented reasoning, in config for calibration)**:
  `trendingEngagementLift`, role/event sub-score weights — reasoned bounds
  stated in `config/trade/faab.json`'s `opportunity` section comments,
  explicitly flagged for recalibration once the shadow log accumulates cases.
- **D (explicitly provisional)**: `retention()`'s shape (flat 1.0 initially).

## 5. Backtesting — scoped honestly

The temporal ledger's floor is 2026-07-14, and none of playerctx, depth-chart,
injury-feed, or trending-history snapshots have historical retention today —
the raw evidence to reconstruct "what was the depth chart on 2026-06-15" does
not exist and is not fabricated. `scripts/faab_backtest.py`'s
CURRENT-vs-CHALLENGER comparison therefore covers the objective-ceiling and
market-model machinery (§3, which has real historical bid data) fully, but
the opportunity layer specifically is validated going forward via the shadow
log, not a retroactive backtest. The September 1 board comparison above is a
**structural explanation case**, not statistical backtest evidence, and is
reported as such.

## 5a. Activation / calibration plan (added 2026-09-01 follow-up)

The owner's requirement was a *live* daily waiver engine — role/injury/
opportunity evidence actually moving production FAAB numbers. As shipped,
this layer is shadow-only: it is computed (when `waiver_live_opportunity` is
enabled) and logged for comparison, but never read by the live recommendation.
That is not yet the finished feature; it is the champion/challenger scaffold
the finished feature has to be validated through. Per CLAUDE.md's own
invariant ("evaluation is not activation, nothing self-promotes"), promotion
is a staged, criteria-gated, human-reviewed process, not a flag flip on
completion of the code:

- **Stage 0 (current state).** `waiver_live_opportunity` defaults off in
  production. Nothing changes for a live user.
- **Stage 1 — turn on shadow logging in production.** Flip the flag on (via
  the per-process env-var override this codebase already uses for
  script-only/shadow features, matching the `bdvm_engine` precedent) and
  restart. This requires deploy access this development session does not
  have (see the follow-up report's production-verification section) — it is
  a named action item for whoever operates the deploy, not something claimed
  done here.
- **Stage 2 — accumulation window.** No review is meaningful on a thin
  sample. Minimum bar before Stage 3 runs: **N ≥ 200** logged rows in
  `data/faab/shadow_comparisons_<leagueKey>.json`, spanning **at least one**
  real injury or depth-chart-promotion event class (not only
  `hasEvidence: false` rows) and **at least 2 weeks** of in-season play, so
  the sample isn't dominated by the no-evidence case this layer degrades to.
- **Stage 3 — analysis.** Extend `scripts/faab_backtest.py`'s existing
  CHALLENGER column to join the shadow log against realized outcomes once
  they exist: `faab_history.py`'s recorded bids (did teams actually pay more
  for opportunity-flagged players?) and, where obtainable, the player's
  realized weekly production after the claim (did a promoted backup's role
  actually hold?). Report: how often `opportunity_value` moved the
  recommended bid, the size of the move, and whether the direction agreed
  with what happened — not a single pass/fail number, since a role bet can
  be well-calibrated and still wrong on any individual case.
- **Stage 4 — human review.** Same posture as Hill-curve promotion
  (`scripts/model_registry.py promote` + `apply`): a person reads the Stage 3
  report and explicitly decides promote / partially promote (e.g., cap
  `retention()` below 1.0, or gate promotion to specific event types with
  strong Stage 3 evidence) / hold. No automatic promotion path exists or
  should be built.
- **Stage 5 — promotion mechanism, if approved.** Change is localized to the
  `add_value` assignment at each call site (`server.py`'s
  `/api/waiver/faab-recommend` handler, and `find_waiver_targets`'s
  market-aware branch after the 2026-09-01 follow-up fix) — read
  `opportunity_value(...)["value"]` instead of raw `rankDerivedValue` when a
  promoted-live state is set, keeping the champion/challenger boundary at
  exactly one line per call site, matching the BDVM/Hill-curve precedent
  already in this codebase. This is deliberately not a new flag *state*
  invented for the occasion — reuse whatever mechanism `scripts/model_registry.py`
  already established for exactly this "challenger evaluated, human
  approved, promote" sequence rather than inventing a second one.

None of Stages 1-5 are executed by the 2026-09-01 follow-up work — that work
fixed the `/waivers` frontend bug (see the FAAB redesign report addendum,
`docs/faab-redesign-2026-09-01-report.md`) and left the shadow layer's status
otherwise unchanged. This section exists so "when does this become live" has
a concrete, falsifiable answer instead of an open-ended "later."

## 6. See also

- `docs/faab-model.md` — the engine reference (unchanged, still binding).
- `docs/FAAB_MARKET_SIGNAL_NORMALIZATION_2026-08-14.md` — owner spec for the
  market/crowd layer (unchanged, still binding).
- `docs/OWNER_FEATURE_INVENTORY.md` row 3.1 — updated to point here.
