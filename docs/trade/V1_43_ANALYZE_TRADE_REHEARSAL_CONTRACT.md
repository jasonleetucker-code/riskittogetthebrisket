# Analyze Trade V1 (`V1-43` / `C7-DESK-01` / #792) — REHEARSAL CONTRACT

> **STATUS: REHEARSAL. NOT AUTHORIZED FOR IMPLEMENTATION.**
> No production code in this document has been written, and none may be
> written until `#914`, `#922` and `#913` are finalized on `main`. This is the
> *shape* the unit takes, published now so the shape can be reviewed before
> anyone writes it — and so the dependencies it needs can be seen to be
> missing.
>
> Binding owner records, in precedence order:
> `docs/MASTER_PRODUCT_PLAN.md` §2 → `docs/OWNER_PRODUCT_BACKLOG_SPEC.md` §1.3
> → `docs/trade/TRADE_CONTEXT_AND_TOPOLOGY_SUPERSESSION_2026-08-14.md` §3/§4 →
> `docs/OWNER_REQUESTED_TODO.md` decisions 24–27 →
> `docs/VERSION_1_COMPLETION_CONTRACT.md` §3.3.

---

## 0. What this unit is, in one sentence

**One decision owner** that turns a *specific* proposed trade into
`MAKE / LEAN MAKE / TOO CLOSE / LEAN PASS / PASS`, with confidence, the
strongest reasons for and against, and the material uncertainty — synthesizing
**unique information**, never re-counting one underlying market because it is
visible on three panels.

It computes **no** value, **no** lineup, **no** cut ladder, **no** Team
Strength and **no** playoff probability. Every number it reasons over is read
from a canonical owner. That is not a stylistic preference: it is the only
reason a "no double counting" claim can be checked, because a dimension that
computed its own inputs could not be shown to be independent of another.

---

## 1. Exact request contract

`POST /api/trade/analyze`

A **new route**, not a widening of `/api/trade/simulate`. `simulate` answers
*"what does this do to my roster"* and must keep answering it with no verdict
attached; `analyze` answers *"should I do it"*. Merging them would put a
recommendation inside the response every roster surface already consumes, and
recommendation ≠ description is the same boundary
`RosterSimulation.isVerdict: false` and `lineupDisplacement.isValueDelta:
false` already draw.

```jsonc
{
  // ── WHO ──────────────────────────────────────────────────────────
  // Optional. Falls through _resolve_league_for_request: explicit →
  // the user's activeLeagueKey → registry default. Unknown → 400
  // unknown_league; inactive → 400 inactive_league; no contract for it
  // → 503 data_not_ready. Same table as every league-scoped endpoint.
  "leagueKey": "dynasty_main",

  // Required when teamContext is on. The team the verdict is FOR.
  // Unresolvable → 400 unknown_team. Never another team's numbers.
  "teamId": "owner-1",

  // ── WHAT ─────────────────────────────────────────────────────────
  // Exactly the four arrays /api/trade/simulate already accepts, in
  // the same vocabulary, so a user can press ANALYZE on a trade the
  // calculator already holds without re-resolving anything.
  "playersIn":  ["Justin Jefferson"],
  "playersOut": ["Chris Olave", "Rome Odunze"],
  "picksIn":    ["2027 Early 1st"],
  "picksOut":   [],

  // ── HOW ──────────────────────────────────────────────────────────
  // #842. ABSENT MEANS ON. See §6 — this is the one field whose
  // default is load-bearing, and `null` is NOT accepted.
  "teamContext": true
}
```

Three request rules that are not negotiable:

* **`teamContext` absent ⇒ `true`.** Not "unset", not "server decides".
* **`teamContext: null` is a 400** (`invalid_team_context`). A client that
  cannot say which mode it wants must not be given a verdict, because the two
  modes legitimately disagree and an unlabelled answer is unattributable.
* **Manual Trade Calculator entry is free-form.** Persistent outgoing
  protections (`src/trade/constraints.py`, `C3-CON-01` / #929) constrain
  *generated* packages and **must not** filter, refuse or warn on a trade the
  user typed in. §2.6 of the preferences spec is explicit; this endpoint is on
  the manual side of that line.

---

## 2. Exact response contract

```jsonc
{
  "leagueKey": "dynasty_main",
  "teamId": "owner-1",
  "asOf": "2026-08-19T13:42:11+00:00",
  "contractVersion": "2026-03-10.v2",
  "boardAsOf": "…",              // which board this verdict was formed on

  // ── THE DECISION ─────────────────────────────────────────────────
  "verdict": "LEAN MAKE",        // MAKE | LEAN MAKE | TOO CLOSE | LEAN PASS | PASS
  "confidence": "medium",        // high | medium | low
  "confidenceReasons": [
    "3 of 6 dimensions are unavailable in this league",
    "two dimensions disagree in direction"
  ],

  // ── WHY ──────────────────────────────────────────────────────────
  // Concrete, quantified, and attributed to the owner that produced
  // the number. No reason may be phrased in the synthesizer's own
  // units — a reason nobody can go and check is an assertion.
  "reasonsFor": [
    {
      "dimension": "packageEquity",
      "owner": "src/trade/ktc_va.py",
      "statement": "adjusted side gap +1,204 to you on a 12,430 package",
      "magnitude": 1204.0
    }
  ],
  "reasonsAgainst": [ /* same shape */ ],

  // ── WHAT WE COULD NOT SEE ────────────────────────────────────────
  // Reported with equal weight to the reasons. A dimension that is
  // missing is NOT a dimension that said "fine".
  "uncertainty": [
    {
      "dimension": "playoffImpact",
      "state": "unavailable",
      "reason": "no_canonical_owner",
      "detail": "C5-PLAY-01 unstarted; two engines disagree and neither is canonical"
    }
  ],

  // ── THE EVIDENCE, ONE ENTRY PER DIMENSION ────────────────────────
  // Always present, always the full list, whatever the mode. A
  // dimension excluded by teamContext:false is present and says so —
  // "not included in this verdict" is the supersession doc's own
  // wording and it must be visible, not inferred from an absence.
  "dimensions": [
    {
      "id": "packageEquity",
      "label": "Package-adjusted equity",
      "correlationGroup": "canonical-board",
      "state": "ok",               // ok | unavailable | excluded_by_mode | stale
      "includedInVerdict": true,
      "direction": "for",          // for | against | neutral
      "weight": 0.34,              // share of the decision, sums to 1 over included
      "owner": "src/trade/ktc_va.py",
      "value": { /* the owner's own payload, verbatim */ }
    }
  ],

  // ── ROSTER CONSEQUENCES (§3, §4) ─────────────────────────────────
  "rosterCapacity": { /* verbatim RosterCapacity.to_dict() */ },
  "finalLegalRoster": { /* verbatim simulate_final_legal_roster() */ },

  // ── MODE ─────────────────────────────────────────────────────────
  "teamContext": {
    "requested": true,
    "effective": true,
    // NEVER true. #842: "Never silently fall back from ON to OFF."
    "degradedToAssetOnly": false,
    "missingDimensions": ["playoffImpact", "posture"]
  },

  // Same disclaimer device as the roster owners, for the opposite
  // reason: this block IS a verdict, and the ones it consumes are not.
  "isVerdict": true,
  "isExecution": false            // decision 15 / spec §8 — never executes
}
```

### 2.1 Error surface

| condition | HTTP | code |
|---|---|---|
| unknown / inactive `leagueKey` | 400 | `unknown_league` / `inactive_league` |
| contract not loaded for that league | 503 | `data_not_ready` |
| loaded contract's `leagueKey` ≠ request | 503 | `league_mismatch` |
| `teamId` unresolvable, `teamContext` on | 400 | `unknown_team` |
| `teamContext: null` | 400 | `invalid_team_context` |
| every dimension unavailable | **200** | verdict `TOO CLOSE`, confidence `low` |

The last row is deliberate. "We cannot tell you" is an answer and must be
rendered as one; a 500 or an empty body reads as a broken page and invites the
user to re-run until something comes back.

---

## 3. Roster-capacity consequences

Read **verbatim** from `src/trade/roster_capacity.py`. Analyze Trade adds no
counting rule of its own.

| capacity state | effect on the verdict |
|---|---|
| `requiresDrops: false` | no capacity term; not a reason FOR |
| `requiresDrops: true`, drops priced | a reason AGAINST, magnitude = `forcedDropReleaseCost` |
| `requiresDrops: null` (taxi bracket straddles zero) | a row in `uncertainty`, **never** a reason either way |
| `rosterLimit: null` (unknown cap) | a row in `uncertainty`; the trade is **not** treated as free |
| `ladderExhausted: true` | a reason AGAINST **and** a confidence penalty — no legal path back to roster size was modelled |
| `forcedDropsAreUpperBound: true` | the magnitude is stated as an upper bound in the reason text |

Two rules that follow from "REPORTS, never rejects":

* **An over-cap trade is never refused.** It is graded, with the release cost
  in it. `/api/trade/analyze` answers a question the user typed; refusing is
  `roster_intel.packages._check_legality`'s job on a *generator's* frontier.
* **The release cost is `forcedDropReleaseCost`, not `forcedDropValue`.**
  `effectiveCutCost` is structurally 0.0 on a full roster (every forced drop
  is at or below waiver level by construction), so a verdict weighted on it
  would price every forced release at nothing. That measurement is already
  recorded on `ForcedDrop.release_cost`; this contract just names which field
  the decision layer must read.

---

## 4. Forced-drop consequences

| drop state | effect |
|---|---|
| priced drop | counted at `releaseCost`, named in the reason |
| `value: null` (unpriced) | named, counted in `unpricedForcedDrops`, **excluded from the magnitude**, and a row in `uncertainty` |
| `acquiredInTrade: true` | named separately — "the piece you are acquiring is the piece you would have to release" is a distinct sentence and usually decisive |
| drops ordered by tied ECC (`rungOrderWasTied`) | the order is presented as arbitrary; the reason must not read as a priority |

**`unpricedForcedDrops > 0` may never be silently absorbed.** The player the
board cannot price is the one whose release is most likely to be a mistake, and
a magnitude that quietly excludes him understates the cost by exactly the
amount nobody can see. Excluding him from the number and naming him in
`uncertainty` is the only combination that is honest in both directions.

**The post-cleanup roster comes from `simulate_final_legal_roster`, not from
subtraction.** Analyze Trade never rebuilds the after-roster; §7 is why.

---

## 5. Position / age / value effects

Three separate dimensions, three separate owners, **one correlation group
between two of them**:

| dimension | owner | correlation group |
|---|---|---|
| `packageEquity` — raw canonical value, then Value Adjustment | `_compute_unified_rankings` → `src/trade/ktc_va.py` | `canonical-board` |
| `positionFit` — starter slots filled/vacated, depth, overflow | `src/trade/team_impact.py` (which consumes `src/ros/lineup.py`) | `roster-shape` |
| `rosterShape` — meaningful core, Team Strength, needs fixed/created | `src/roster_intel/` via `simulate_final_legal_roster` | `roster-shape` |
| `ageConstruction` — age-value portfolio, young-core direction | `src/roster_intel/age_portfolio.py` | `roster-shape` |
| `marketCorroboration` — external boards agreeing or not | `sources` block / Second Opinions | `external-market` |
| `uncertaintyBand` — Monte Carlo dispersion | `src/trade/monte_carlo.py` | `canonical-board` |

### 5.1 No double counting — the rule stated executably

> **A body of evidence affects the verdict once.**

Three collapses are live hazards here, and each is closed structurally rather
than by a weight the reader has to trust:

1. **`monte_carlo` is a descendant of the canonical board**, not an independent
   vote. It samples around the same values. It therefore may set the
   **confidence** and may widen the band — it may **not** contribute a
   `direction`. Same posture as BDVM's speculation lane, where
   `confidence < 0.5` lets an event widen σ and never move a mean.
2. **`marketCorroboration` must not re-count sources already inside
   `rankDerivedValue`.** Every source in `_RANKING_SOURCES` is *already* in the
   canonical value. An external board is independent evidence only to the
   extent it is **not** a blend input. In practice that leaves very little, so
   V1 states the overlap rather than claiming independence: the dimension
   carries `overlapWithCanonicalBoard: [sourceKey…]` and its weight is scaled
   by the non-overlapping share.
3. **`positionFit`, `rosterShape` and `ageConstruction` all describe the same
   post-trade roster.** They share the `roster-shape` correlation group, and a
   group's weight is allocated across its members — it is not the sum of them.
   Without this, a trade that improves one roster improves it three times.

**Weights are per correlation GROUP, then split within the group.** Included
dimensions' weights sum to 1. A dimension in `state != "ok"` has weight 0 and
the remaining groups renormalize — with the renormalization **recorded**, so
"three of six dimensions were unavailable" is visible rather than being
laundered into confident-looking full weights.

### 5.2 Age is a descriptor in BOTH modes, team age construction is not

Per the supersession doc §3: with Team Context OFF, "player age as an intrinsic
descriptor" is still allowed, while "#838 team Age-Value / Young Core changes"
are not. So `ageConstruction` splits: the per-asset age descriptor survives
into asset-only mode; the team-level portfolio delta does not.

---

## 6. Team Context toggle — default ON

`teamContext` absent ⇒ `true`. The shared contract is #842's, and this endpoint
does not get a private interpretation of it.

| dimension | ON | OFF |
|---|---|---|
| `packageEquity` | ✅ | ✅ |
| `marketCorroboration` | ✅ | ✅ |
| `uncertaintyBand` | ✅ (confidence only) | ✅ (confidence only) |
| per-asset age descriptor | ✅ | ✅ |
| `positionFit` | ✅ | ❌ `excluded_by_mode` |
| `rosterShape` | ✅ | ❌ `excluded_by_mode` |
| `ageConstruction` (team level) | ✅ | ❌ `excluded_by_mode` |
| `rosterCapacity` / forced drops | ✅ | ❌ `excluded_by_mode` |
| `playoffImpact` | (blocked — §8) | ❌ |
| `posture` | (blocked — §8) | ❌ |

Four rules:

* **OFF is not "standard format".** The league's TEP / Superflex / IDP /
  scoring configuration still shapes canonical value. OFF removes *team*
  context only.
* **`rosterCapacity` is still COMPUTED and still RETURNED with OFF** — it is a
  fact about the roster and the user asked to see the trade. It is marked
  `includedInVerdict: false`. Computing it and hiding it, or not computing it
  at all, are both worse than showing it labelled.
* **Never silently degrade ON → OFF.** If team context is missing, the
  affected dimensions go `unavailable` with a reason and the verdict is formed
  from what remains, at reduced confidence. `degradedToAssetOnly` exists only
  so a future violation is detectable; it is always `false`.
* **The mode travels with the verdict.** A share link that reproduces a verdict
  without its mode reproduces a different verdict.

---

## 7. No duplicate Roster business logic

This is the property `tests/trade/test_trade_consumes_roster.py` already
proves for `C3-CAP-01`, extended to the decision layer. Analyze Trade must add
**zero** of the following, and the existing structural guards already fail if
it does — they scan every module in `src/trade/`, so a new
`src/trade/analyze.py` is covered the day it is created:

| concept | owner Analyze Trade must call |
|---|---|
| lineup / slot assignment | `src/ros/lineup.py` |
| slot eligibility, slot demand | `src/ros/lineup.py` |
| meaningful core, Team Strength, Team Weakness | `src/roster_intel/` |
| before → apply → re-solve → after | `roster_intel.simulation.simulate_roster_change` |
| cut ladder / replacement level | `roster_intel.pool_cut_ladder` (the adapter, not the board's door) |
| roster limit, taxi bracket, forced drops | `src/trade/roster_capacity.py` |
| age-value portfolio | `roster_intel.age_portfolio` |
| canonical value | `rankDerivedValue` — read, never recomputed |
| Value Adjustment | `src/trade/ktc_va.py` |
| NFL-franchise exposure | `roster_intel.exposure` (descriptive; emits no penalty — §1.6) |

**The synthesizer's only original computation is the synthesis**: correlation
grouping, weight allocation, verdict thresholds and confidence. Everything it
reasons over is somebody else's published number, read verbatim.

Concretely, the module is expected to be small — on the order of 400 lines,
almost all of it the correlation/weight table and the reason grammar — and if
it is not, something has been reimplemented.

---

## 8. What BLOCKS this unit, stated rather than worked around

Three dimensions the owner records name as inputs have **no canonical owner
today**. V1-43 may not invent one, and may not pick a side between two
disagreeing engines.

| dimension | blocker | required behaviour until it lands |
|---|---|---|
| `playoffImpact` | `C5-PLAY-01` / `V1-51` NOT STARTED. **Two engines**: `src/public_league/playoff_odds.py` (empirical) and `src/ros/playoff_sim.py` (ROS-blended). They disagree by 7 vs 6 spots. | `state: "unavailable"`, `reason: "no_canonical_owner"` — **never** a coin-flip between them |
| `championshipImpact` | `src/ros/championship.py` extends `ros/playoff_sim` and declares its own bracket model "intentionally simple" | same |
| `posture` (PUSH / HOLD / RETOOL / REBUILD) | `C7-POST-01` ABSENT | same. `team_impact._classify_window` is a **local** window classifier and is **not** the posture owner — consuming it would mint a second one |

This is the honest reading of *"playoff/championship effects only from
canonical owners"*: **there is no canonical owner yet, so V1-43 ships with
those dimensions explicitly unavailable.** A verdict that quietly omitted them
would look more confident than the evidence supports; one that picked an engine
would be manufacturing agreement out of a disagreement nobody resolved.

Consequence to state up front: at V1, Analyze Trade's confidence is capped at
`medium` in a league where those three dimensions are unavailable, because a
third of the named evidence is missing. That is a truthful ceiling, not a
defect to tune away.

---

## 9. Acceptance — what must be proven before this ships

RED-first and mutation-proven, the same standard as `C3-CON-01` and the
integration proof:

1. `teamContext` absent produces the identical verdict to `teamContext: true`.
2. `teamContext: null` is a 400.
3. ON and OFF may differ **only** by the `excluded_by_mode` dimensions —
   proven by re-running the verdict with those dimensions zero-weighted.
4. No dimension in `state != "ok"` carries non-zero weight.
5. Included weights sum to 1, and the renormalization is recorded.
6. Two dimensions in one correlation group cannot both contribute a full
   group's weight (the no-double-count test `C7-DESK-01` names).
7. `monte_carlo` cannot change a `direction` — only confidence.
8. Every dimension is unavailable ⇒ 200 `TOO CLOSE` / `low`, not 500.
9. A forced drop with `value: null` never enters a magnitude and always enters
   `uncertainty`.
10. `requiresDrops: null` never becomes a reason in either direction.
11. `playoffImpact` / `championshipImpact` / `posture` are `unavailable` and a
    guard **fails** if any code path reads either playoff engine or
    `_classify_window` into the verdict.
12. Structural: no lineup, strength, ladder or simulation logic is defined in
    the analyze module — the existing `src/trade`-wide guards cover it.
13. A protected outgoing player is analyzable — the constraint owner is not
    consulted on this route.
14. The canonical board is byte-identical.

---

## 10. Sequencing

`V1-43` cannot start until:

* `#914` (`C2` roster chain) — **merged to `main`**
* `#922` (cut-ladder flex threading) — **merged to `main`**
* `#913` (`C3-CAP-01` + substrate) — **merged to `main`**
* `#929` (`C3-CON-01` constraint owner) — merged, so the manual-vs-generated
  boundary in §1 is real rather than aspirational

and it should follow, not precede, `V1-41` (`C3-CTX-01`, the toggle itself),
because §6 is that contract applied rather than a second copy of it.
