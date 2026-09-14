# Owner Feature Addendum — 2026-09-13 — Live Rookie Auction: Dynamic Perfect Draft, Bid Tracking, Roster-Aware Budget Optimization, Price Sensitivity

**Status:** BINDING FUTURE SPECIFICATION — PLANNED. This is a backlog/specification document. **No
implementation, deployment, bid submission, auction-setting change, or roster transaction is
authorized by this file.** Only `docs/EXECUTION_PLAN.md` authorizes implementation, and it has not
been amended by this addendum.
**Canonical manifest row:** `C7-DRAFT-03` (`docs/C_SERIES_SCOPE_MANIFEST.md`), execution unit
`C7-U12` (`docs/C_SERIES_EXECUTION_MAP.md`).
**Extends:** `docs/perfect-draft.md` (mechanical reference) and ADR-009/010/011 in
`docs/roster-trade-intelligence/DECISIONS.md`. This addendum does not replace any of that —
everything already accepted there (no per-team slot limit, `k` a free variable, surplus/ECC over
replacement, cardinality-decomposed knapsack, client-side solve + server-side roster context)
carries forward unchanged and is the substrate this epic builds on.
**Registered per** `docs/PLANNING_DOCUMENT_STATUS.md` §7 rule 6, in the same change, under §3.

---

## 0. How to read this document

Three explicit categories are used throughout, because the owner's directive requires distinguishing
them and repeatedly conflating them is exactly what has produced defective specs elsewhere in this
repository's history:

- **CONFIRMED** — a rule the owner has stated as a requirement. Binding on any future implementation
  of this epic.
- **PROPOSED** — an implementation approach this document recommends to satisfy a CONFIRMED
  requirement. Not itself binding; a future implementer may choose a different mechanism as long as
  the CONFIRMED requirement is still met.
- **UNRESOLVED** — a rule or parameter genuinely not yet decided. Recorded here so it is not lost or
  silently invented. A future implementer must either get an owner decision or make the smallest
  possible provisional assumption and label it exactly that way (matching this repo's PRIOR /
  MEASURED / MECHANICAL taxonomy from `docs/MATH_MODEL_CALIBRATION_POLICY_2026-08-15.md`).

Every numeric example in this document (prices, player names, bid amounts) is a **synthetic
illustration** unless explicitly marked as a measured/live figure from the existing codebase. It is
never a claim about a real auction result, a real player's current valuation, or a prediction.

---

## 1. Owner intent (CONFIRMED)

Perfect Draft must continuously answer:

> "Given my current roster, remaining auction money, confirmed purchases, active bids, available
> rookies, and acquisition-price assumptions, what combination of players should I try to acquire,
> what should I pay, and which players would I eventually drop to maximize my overall roster
> improvement?"

**This is explicitly NOT:**
- a static auction-value sheet;
- a best-player-available ranking;
- a value-per-dollar sort;
- a recommendation to acquire exactly six rookies;
- a collection of individual maximum bids that ignore one another.

**CONFIRMED — variable plan size.** The owner's examples of five or six acquisitions are illustrative,
not a required draft size. The best result may be fewer players, more players, one expensive player
plus inexpensive players, or **no additional purchases**. Unused money is permitted when further
purchases do not improve the roster. This is already the accepted behavior of the existing optimizer
(ADR-009: "the league caps nobody's rookie count... the optimizer may return zero rookies, one, or
many, and is never required to spend the full budget") — this addendum extends that behavior into a
live-auction setting; it does not change it.

**CONFIRMED — the optimizer must evaluate complete affordable combinations and their roster
consequences**, not score acquisitions independently. This is the existing cardinality-decomposed
knapsack in `frontend/lib/perfect-draft.js` (`docs/perfect-draft.md` §5) — this epic's job is to keep
that joint evaluation correct while the auction is live, not to introduce a new objective.

### 1.1 Correction: ~12 simultaneous active auctions, not ~20 (CONFIRMED, configurable)

Plan for **approximately 12 simultaneously active player auctions** as the assumed order of
magnitude for the live board, not the earlier ~20 estimate. No prior repository document stated the
~20 figure — this is recorded here as the first written parameter, superseding only conversational
context outside the repo. Make this value **configurable** (a named constant or league-setting-derived
value, not hardcoded into the solve), matched against the actual platform's simultaneous-auction rule
before implementation.

**UNRESOLVED — exact simultaneous-auction rule.** The live rookie-auction platform's actual
nomination/concurrency limit is not yet confirmed in this repository. Whatever it is, it must be read
from the real auction rules, not assumed.

**CONFIRMED — the twelve active auctions are not the entire opportunity set.** Eligible rookies who
have not yet been nominated remain part of the plan; the system must not spend the whole budget
merely because a handful of players are currently on-screen. See §6.

**CONFIRMED — preserve the slow-auction format.** "Live" means immediately responsive to the
evolving auction state, not a redesign into a different (e.g. fast/blind) auction format. Timers, quiet
hours, and nomination rules stay exactly as the platform defines them; this epic changes what Perfect
Draft *shows and recommends*, never how the auction itself runs.

---

## 2. Preserve league and roster context (CONFIRMED)

- Use the **globally selected fantasy team** throughout. Changing the selected team must change the
  roster, budget, bids, drop candidates, and recommendations consistently. (Existing precedent:
  `docs/perfect-draft.md` §8's "cache key carries team identity... an unresolvable team is a 400,
  never a silent fallback to whichever team sorted first" — this rule extends unchanged to every new
  live-bid data structure this epic adds.)
- Read current league settings and roster data from the authoritative sources
  (`GET /api/draft/roster-context`, `src/api/league_registry.py`). Do not hardcode a stale roster, a
  fixed six open spots, or equal budgets across teams.

### 2.1 Preserve the established rookie-auction framework (CONFIRMED)

- Rookie picks convert into auction dollars; they do not reserve particular rookies for their owners.
- The existing framework uses **six rounds × twelve teams = 72 picks** and a **$1,200 league-wide
  budget pool**.
- Individual team budgets come from the picks each team owns, not an assumption that every team
  starts with $100. (`docs/perfect-draft.md` documents the $1,200 ladder and its non-invertibility;
  this addendum adds no second ladder.)
- Six nomination opportunities per team must not become a six-player acquisition requirement.
- Preserve permitted **$0 bids and $0 purchases**.
- Do not introduce a mandatory $1-per-slot reserve. (ADR-009 already deleted the slot-reservation
  model this would reintroduce — `effectiveBudgetFor` reserving $1/slot was explicitly removed and
  must not come back under a new name.)
- Unused rookie-auction money does not automatically become waiver FAAB. These are different budgets
  with different rules (`src/trade/faab_engine.py` vs. the draft's own `teamTotals[].auctionDollars`)
  and must not be merged.

**UNRESOLVED — the eligible player pool's exact size.** Check the governing specification (this
repository's rookie-pool definition, `src/draft/rookie_pool.py`) before assuming 72 picks/nominations
equals a hard cap of 72 eligible candidates. Do not equate the two without verifying against the live
pool.

**CONFIRMED — dynasty/roster context is real.** The optimizer must understand this league's actual
dynasty, best-ball, superflex, full-IDP roster and scoring context, using the canonical roster limit
and eligibility rules (`src/api/league_registry.py::league_roster_limit`,
`src/ros/lineup.py::resolve_starter_slots` — never a private eligibility table, per CLAUDE.md's
"Lineup / slot assignment — one owner").

### 2.2 Separate four distinct questions (CONFIRMED)

1. What acquisitions are **legal during the auction**.
2. What roster **size is temporarily permitted**.
3. Which **cuts are eventually needed**.
4. **When** those cuts must occur.

Do not assume an acquisition requires an immediate drop if the league permits temporary offseason
roster expansion. `docs/perfect-draft.md` §5's `openRosterSpots` and cut-ladder machinery already
separates "can I hold this roster temporarily" from "who would I eventually cut" — this epic must
preserve that separation, not collapse it under live-auction pressure.

---

## 3. Provide an obvious place to enter and track bids (CONFIRMED requirement, PROPOSED UI shape)

**CONFIRMED — a live auction board with inline controls, connected to the Perfect Draft panel.**

For each relevant player, distinguish (CONFIRMED fields; PROPOSED exact labels/layout):

| Field | Meaning |
|---|---|
| Current public auction price | What the auction engine currently shows |
| Current leading team | Who holds the lead, if known/public |
| My actual submitted bid | A real bid this team has placed, when available |
| My private proxy maximum | This team's private ceiling, if the platform supports proxy bidding |
| My hypothetical purchase price / proposed bid | A what-if scenario input — never a real bid |
| Recommended target price | Perfect Draft's current suggestion |
| Strategic maximum bid | §7's definition |
| Legal maximum bid | §7's definition, given other commitments |
| Auction status and closing information | Active / closing soon / closed, per the platform |
| Source and freshness of the information | Where this row's data came from and how stale it may be |

**CONFIRMED — three explicitly labeled, easy-to-find controls:** "My Bid", "What-if Purchase Price",
"Test a Raise". These must not be buried in an unrelated settings page.

**CONFIRMED — real and hypothetical state must never blur.** Typing a what-if number must not:
submit a real bid; mark the player as won; deduct settled spending; or overwrite the official auction
state. This is the single most safety-critical UI rule in this epic — see §12 for the consistency
requirements this implies.

**CONFIRMED — support both manual tracking and, where available, integration with the established
auction data source.** Document the source-of-truth and reconciliation rule for what happens when an
imported update conflicts with a manual entry (PROPOSED default: the platform's own confirmed state
always wins over a stale manual entry; a manual entry is provisional until confirmed or superseded).

**CONFIRMED — do not claim real-time feed or bid-submission capability for an external platform
without verifying it.** `docs/perfect-draft.md` §8 already documents one real integration point
(`useSleeperDraftSync` → `handleLivePick` → `recordPick`) for **recording completed picks** from the
Sleeper live feed — that is confirmed to exist. **UNRESOLVED — whether that or any other integration
supports live in-progress bid state (leading bid, current price before a sale) or only completed
picks.** Do not assume real-time bid-level integration exists until verified against the actual
platform capability.

---

## 4. Model auction states correctly (CONFIRMED)

At minimum, distinguish these states per player:

1. **Available / not nominated**
2. **Active auction**
3. **I am leading**
4. **I have been outbid**
5. **Confirmed won by me**
6. **Confirmed won by another team**
7. **Hypothetical scenario only**

**CONFIRMED semantics:**
- A current lead is **not** a completed purchase.
- A losing bid is **not** a cash commitment.
- A hypothetical bid is **neither** a lead nor a commitment.
- However, a leading bid **may become** a binding purchase, so the system cannot ignore it when
  recommending other bids — it must be treated as an **enforceable commitment** for budget purposes
  (see §5's `C` term).
- Maintain a safe view of "if all current leading bids win" alongside clearly labeled contingent
  scenarios where a lead is later outbid.
- **Preserve the established rule that a leader cannot withdraw a binding leading bid.** Do not
  recommend "cancelling" a leading commitment unless the actual auction platform's rules permit it.
  (This generalizes the existing ADR-009 principle that the model must describe the real platform,
  not a convenient fiction of it.)
- **Confirmed purchases must remain owned and paid for.** Reoptimization can never undo a confirmed
  purchase or refund its cost. Closed players owned by someone else leave the available pool
  permanently for this draft.

---

## 5. One shared budget across all active auctions (CONFIRMED formula, PROPOSED enforcement mechanism)

**CONFIRMED reconciliation:**

```
B = authorized auction budget
S = settled spending on confirmed purchases
C = current enforceable commitments on auctions I am leading
F = presently uncommitted cash

F = B - S - C
```

Apply this according to the actual platform's commitment rules (an auction platform's specific
proxy/increment mechanics decide exactly what counts as "enforceable" — this formula is the shape,
not a claim about one specific engine's semantics).

**CONFIRMED — replacing, not stacking, an own raised bid.** When increasing an existing leading bid,
the new commitment **replaces** the old one for that player; the two must never both count against `C`.

**CONFIRMED — what must be shown separately:**
- starting / current authorized budget (`B`);
- confirmed spending (`S`);
- leading-bid commitments (`C`);
- uncommitted cash (`F`);
- conditional remaining cash for the *displayed* draft plan (i.e. `F` minus the plan's own planned
  spend on players not yet won);
- any additional proxy-exposure risk (see below).

**CONFIRMED — shared affordability across recommendations.** Multiple recommendations must draw from
the same `F`. The system must never recommend N individually-affordable bids whose sum exceeds `F`.
Individual strategic ceilings (§7) are **conditional on current state** and must be shown as such —
explicitly warn that they may not all be simultaneously submittable.

**CONFIRMED — losing hidden proxy maximums do not lock budget.** Do not "solve" shared-affordability
by reserving every losing proxy maximum as though it were a purchase — that manufactures phantom
scarcity. **PROPOSED** — enforce shared affordability at the moment of each actual bid or automatic
proxy escalation. Where the native auction engine handles proxy bidding, this requires an **atomic
budget check** at the engine (or at the boundary this system controls) so simultaneous updates cannot
overspend the account — a race between "recompute my plan" and "the auction advances my proxy" must
never be allowed to authorize spend beyond `F`.

**CONFIRMED — a proxy maximum is not necessarily the final purchase price.** Track actual current
liability, possible escalation, and assumed settlement price as three separate quantities, never
collapsed into one number.

**CONFIRMED — a legitimate $0 bid is not the same as an unknown/missing price.** A $0 bid is a real,
valid observation; a missing price must be reported as missing (per this repository's "missing is
never zero" invariant, `CLAUDE.md` governance invariants §MISSING-NEVER-ZERO), never coerced to $0.

**Consolidates existing defect W10-F001 / inventory row 3.7 ("Draft bid respects remaining budget —
stop telling a manager with $4 left to 'win at $37'").** That defect is the legal-maximum half of this
section's budget model; fixing it under this epic's `F`/legal-maximum machinery is the correct
disposition rather than a separate patch, per the "extend or consolidate" instruction governing this
addendum. See §14.

---

## 6. The optimization objective (CONFIRMED shape, math stated precisely)

**CONFIRMED — the central objective is maximum net improvement in the final roster**, using this
site's established dynasty valuation and team-context methodology (`rankDerivedValue`, the surplus/ECC
primitives of ADR-010 — no second valuation is created by this epic).

Conceptually:

```
choose future acquisitions A and legal roster cuts D jointly to maximize

    Utility(resulting roster) - Utility(current owned roster)

subject to:
    remaining budget (F, from §5)
    binding auction commitments (C, from §5)
    player availability (auction state, §4)
    legal acquisition prices and bid increments (the platform's rules)
    unique player ownership (a player is acquired or dropped at most once)
    actual roster rules and cut deadlines (§2.2)
    explicit user locks or exclusions (§9)
    applicable positional and eligibility constraints
```

**CONFIRMED — no double counting.** Confirmed purchases already folded into the owned roster must
never have their value or cost counted a second time by the live-recommendation layer.

**CONFIRMED — explainable decomposition.** For a simple additive explanation, show acquired value
minus displaced value (`Σ surplus - R(k) - D(k)`, ADR-010's existing decomposition). Where the
existing roster-utility model includes interaction effects beyond that decomposition, use that model
consistently and explain the decomposition honestly rather than presenting a simplified number as the
whole model.

**CONFIRMED — evaluate drops as part of the combination, not as an afterthought:**
- open spots do not require a displaced player;
- the same roster player cannot be dropped twice;
- the best cuts can change when a different rookie is acquired (this is already true of the existing
  cheapest-first ladder + matroid argument in ADR-010 — the live-auction extension must not silently
  reintroduce a per-acquisition-independent cut choice);
- an apparently attractive rookie may not improve the roster after displacement cost is charged;
- an expensive rookie may still justify replacing several smaller planned purchases.

**CONFIRMED — use canonical Dropability and roster-context inputs.** Never invent a separate,
inconsistent "the six worst players" list. `src/draft/displacement.py`'s cut ladder and
`consumptionOrder` (`docs/perfect-draft.md` §5) remain the single answer to "which cut is next" —
every new live-auction consumer must go through it, per the existing "three separate places got this
wrong before it was unified" lesson recorded there.

**CONFIRMED — keep canonical player value, team-specific recommendation value, and auction price
separate.** In particular, do **not**:
- alter canonical dynasty value because one player sold cheaply in this auction;
- subtract auction dollars directly from dimensionless player-value scores (the existing
  "currency discipline" rule in `docs/perfect-draft.md` §4 — `rosValue` vs. `rankDerivedValue` vs.
  dollars are three different units and must never be mixed);
- apply duplicate positional/scarcity adjustments (surplus and ECC already apply the one canonical
  scarcity multiplier; a second one would double-count);
- charge an arbitrary extra "opportunity-cost penalty" for alternatives already accounted for by the
  optimization itself.

**CONFIRMED — opportunity cost is grounded in the best competing feasible plan**, i.e. exactly the
`bestNetWithout(i)` pivot ADR-010/§6 of `docs/perfect-draft.md` already computes — not an invented
constant or heuristic penalty.

**CONFIRMED — define the objective precisely rather than hiding undefined math behind "optimal."**
Every future implementation of this epic must state: the objective function, its units, every
constraint, the tie-breaking rule, and any approximation made (e.g. a time-limited solver returning a
best-found rather than proven-optimal plan — see §12).

---

## 7. Three distinct price concepts (CONFIRMED)

**TARGET PRICE** — a desirable acquisition price for the current plan.

**STRATEGIC MAXIMUM** — the highest price at which acquiring the player remains at least as valuable
as the best feasible alternative, under the stated model and assumptions. This **is** the existing
`planMaxBid` indifference price (`docs/perfect-draft.md` §6: `planMaxBid(i) = max{ q ∈ [price_i, B] :
Φ_i(q) ≥ bestNetWithout(i) }`), generalized to run against the *live* budget `F` and the *live* set of
still-available alternatives rather than only the pre-auction snapshot.

**LEGAL MAXIMUM** — the highest bid permitted by current budget commitments and the actual auction
platform's rules (a function of `F`, §5, and the platform's bid-increment/proxy rules).

**CONFIRMED relationships:**
- A player can be **legally affordable but strategically undesirable**.
- A player can be **strategically attractive but temporarily unaffordable** because money is tied up
  in other leading bids (`C` from §5).
- Do **not** infer a strategic ceiling by adding a fixed percentage to the target price — it must be
  derived by solving the actual alternative-plan comparison (§8), never approximated by a markup.
- Do **not** confuse a currently-displayed public price with the price at which this team could
  legally take the lead — use the platform's actual next-bid and proxy rules, whatever they are.

---

## 8. The Mendoza counterfactual — required future acceptance scenario (CONFIRMED math and framing)

> **SYNTHETIC EXAMPLE.** Fernando Mendoza is a real player already present in this repository's
> rookie/valuation fixtures and audits (e.g. `docs/master-site-audit/PROOF_CASES.md`), but the
> scenario below — a $65 recommendation and a $68 what-if — is a **synthetic illustration for
> specification purposes only**. It is not a claim about an actual auction, a real current valuation,
> or a prediction about this or any player.

**Owner scenario (CONFIRMED as a required acceptance case):** "Perfect Draft recommends Fernando
Mendoza at $65. What happens if I bid or pay $68 instead?"

**CONFIRMED — the feature must distinguish four different things**, each with different budget
implications:

| Label | Meaning | Budget effect |
|---|---|---|
| A. Testing a hypothetical $68 purchase | a what-if scenario query | none — no real commitment |
| B. Setting a private proxy maximum of $68 | a real but conditional commitment | counts toward `C` only while leading |
| C. Actually leading at $68 | a real enforceable commitment | counts toward `C` |
| D. Officially winning at $68 | a settled purchase | moves from `C` to `S` |

### 8.1 The decision-advantage function (CONFIRMED math)

For a player `p` the team is still free to pursue or pass on, define:

```
V_win(p, price)  = the best attainable final-roster utility conditional on acquiring p at
                   settlement price = "price", while reoptimizing every OTHER acquisition and
                   drop and preserving every other binding commitment

V_pass(p)        = the best attainable final-roster utility without acquiring p, under the same
                   remaining-player, price, and auction-state assumptions

Delta(p, price)  = V_win(p, price) - V_pass(p)
```

**Interpretation (CONFIRMED):**
- `Delta > 0`: the buy branch is better under the model.
- `Delta = 0`: the branches tie under the model.
- `Delta < 0`: the best alternative is better.

**CONFIRMED — the strategic ceiling is `planMaxBid` restated in this notation**: it is the largest
`price` such that `Delta(p, price) >= 0`. It must be derived by evaluating complete competing plans at
legal price increments, never by inspecting the player's isolated value alone.

### 8.2 If already leading (CONFIRMED constraint on the model, not just the UI)

**If this team is already leading a player, "pass and recover that money" may not be an available
immediate action.** The model must compare only **legally available actions** — e.g. holding the
current bid, or raising it. Any branch of the comparison that assumes the existing commitment is freed
must explicitly depend on a real triggering event: being outbid, or another permitted release under
the platform's actual rules. A `V_pass` branch that silently assumes a binding lead evaporates is
invalid and must not be presented.

### 8.3 What a correct answer to the $65→$68 example must show (CONFIRMED checklist)

1. Whether $68 is **legal** given current commitments (§5, §7).
2. Whether the **plan remains affordable** at $68.
3. Whether the **same combination remains optimal**, or a **different combination becomes optimal**.
4. **Which targets are replaced or removed**, if any.
5. **Which proposed cuts change**, if any.
6. **How much cash remains** after the change.
7. The **change in roster utility** (`Delta(Mendoza, 68) - Delta(Mendoza, 65)`, or the equivalent
   direct comparison the implementation actually computes).
8. The **best alternative** under the new state.
9. The **current strategic ceiling** and the assumptions it rests on.

**CONFIRMED — possible outcome shapes** (illustrative wording, not literal required strings):
- "Still the same best combination, with $3 less flexibility."
- "Still worth buying, but replace another target."
- "Still affordable, but passing now produces a better roster."
- "Not currently affordable because of other commitments."

**CONFIRMED — none of these outcomes may be fabricated.** Every one must come from actually solving
the corresponding scenario against the live state, never from a template filled in with the player's
name.

---

## 9. Reoptimize after every meaningful change (CONFIRMED trigger list)

The future implementation must recompute the live plan when:

- a hypothetical price is edited;
- a bid is changed or increased;
- this team becomes the leader, or is outbid;
- a player is won at a different price than expected;
- another manager acquires a target;
- a new player is nominated;
- a relevant price estimate changes;
- budget or roster data changes;
- a player is locked or excluded (§9.1);
- a potential drop is protected or allowed;
- the globally selected team is switched.

**CONFIRMED — a below-plan win must trigger a full re-solve, not a cosmetic cash update.** If a player
is won for less than planned, recompute the entire remaining draft; do not merely display extra
leftover cash while leaving stale recommendations on screen.

**CONFIRMED — a price increase must trigger a full re-solve, not a mechanical trim.** If a player
becomes more expensive, recompute the entire remaining draft; do not automatically remove only the
cheapest planned player or mechanically reduce the player count by one.

### 9.1 User locks (CONFIRMED)

A user lock/exclusion must be clearly labeled as such. **"Best under your constraints" is not
necessarily the unconstrained best plan** — the UI must never present a constrained result as if it
were the global optimum.

---

## 10. Unknown prices: distinguish evidence classes, never pretend to know the future (CONFIRMED)

For every acquisition cost, identify which of these it is:

1. a **settled purchase price**;
2. a **current binding lead**;
3. a **current public price or legal next bid**;
4. a **user-specified scenario price**;
5. a **modeled expected final price**.

**CONFIRMED — a currently-low bid is never a guaranteed final price.**

**CONFIRMED — reuse the established auction-price methodology** (`docs/perfect-draft.md` §3's
`inflation` / `tierInflation` / `expectedPrice` model, already the one live price model — this epic
introduces no second one), with transparent inputs for: remaining league buying power, remaining
eligible player value, other teams' known budgets and commitments, relevant roster demand, actual
auction results so far, and the remaining nomination pool.

**CONFIRMED — keep live inflation/budget-leverage effects inside the auction-price/recommendation
layer.** One auction result must never silently rewrite canonical player values (`rankDerivedValue`).

**CONFIRMED — document any inflation-style calculation's numerator, denominator, units, treatment of
commitments, and zero-denominator handling.** Never count committed money or committed players twice
across that calculation.

**CONFIRMED — staged rollout.** The initial deterministic version must be usable with explicit
user-supplied price assumptions and the available deterministic forecast. More advanced
scenario/probability modeling is an explicitly **later, dependent** task (Phase F, §14).

**CONFIRMED — if probability is introduced later, it requires evidence and calibration.** Do not
invent precise win probabilities, and do not assume auction outcomes are independent when rival teams
share the same competing budgets — this is the same correlation-independence discipline this
repository already applies to source signals (`CLAUDE.md` governance invariant on signal
independence) and must be applied here too.

**CONFIRMED — "optimal" always means optimal for the specified model, snapshot, constraints, and
price assumptions** — never a guarantee against unknowable future bids.

---

## 11. Live Perfect Draft plan panel and change explanation (CONFIRMED content, PROPOSED layout)

**CONFIRMED — the primary panel must show:**
- confirmed acquisitions, clearly separated from projected acquisitions;
- recommended remaining targets and their assumed prices;
- total planned spending and budget reconciliation (`B`/`S`/`C`/`F`, §5);
- expected number of acquisitions (never a fixed target count, §1);
- proposed cuts and protected players;
- net roster improvement;
- the immediate recommended action;
- the most important alternative.

**CONFIRMED — after any change, show a concise before/after explanation**, e.g. (illustrative,
synthetic):

> "Your proposed Mendoza price increased from $65 to $68. The revised plan replaces Target A with
> Target B, keeps the same cuts, and leaves $X. Buying Mendoza remains better than the best pass plan
> by Y model-value units."

**CONFIRMED — every amount and explanation must come from the actual calculation.** Any synthetic
example in documentation must be clearly labeled as such (as this document does throughout).

**CONFIRMED — actionable explanations are required** when the plan changes because of a tier drop, a
roster constraint, another active commitment, or uncertainty about a later target.

**CONFIRMED — mobile-usable, on-brand, linked to canonical profiles.** The primary experience must
stay understandable on mobile; player names link to existing player profiles (per this repository's
`#1337` canonical player-link requirement in `docs/OWNER_REQUESTED_TODO.md`); the feature follows the
site's established visual design (`docs/PREMIUM_SPORTS_INTELLIGENCE_DESIGN_NORTH_STAR.md` where the
route in question has migrated, current design otherwise).

**CONFIRMED — strict privacy.** Store private bids, proxy ceilings, scenarios, and recommendations
per authorized user/team. **Never expose private ceilings to opposing managers** through shared views,
APIs, exports, or logs. (This generalizes the existing team-identity cache-key isolation in
`docs/perfect-draft.md` §8 to every new piece of state this epic adds.)

---

## 12. Responsiveness and state-consistency requirements (PROPOSED targets, CONFIRMED invariants)

**PROPOSED, to be validated before being treated as an accepted target:**
- immediate local input feedback and budget validation, **≈100 ms or less**;
- updated primary plan within **≈1 second at p95**, on representative warm-state workloads;
- benchmark with **at least twelve simultaneous auctions** (§1.1), the full relevant candidate pool,
  and actual roster complexity.

These are proposed future acceptance targets, **not claims about current performance** — the existing
static solve measures ~140 ms at a $417 budget (`docs/perfect-draft.md` §8); the live-auction version
adds event volume and concurrency this measurement did not cover.

**CONFIRMED — do not rebuild canonical valuations, retrain models, or refetch every external source
on every keystroke.** Reuse prepared valuation snapshots and price inputs; recompute only what the
changed state actually requires. Follow the existing performance architecture
(`docs/GLOBAL_PERFORMANCE_STANDARD.md`) rather than inventing a separate pipeline.

**CONFIRMED — version every recommendation** against the auction snapshot, valuation snapshot,
selected team, and scenario inputs. This must prevent, at minimum:
- an older calculation overwriting a newer result;
- a team switch displaying the previous team's bids;
- a duplicate event charging the budget twice;
- simultaneous bid events exceeding the budget (the atomic check from §5);
- a reconnect showing a stale recommendation as current.

**CONFIRMED — honest solver-status labeling.** If an exact solve exceeds its time limit, show a valid
best-found plan with an honest solver-status label. Do not silently call an unproven result "the
perfect draft." Record solver bounds or optimality gaps where the solver method supports them. Handle
infeasible or inconsistent input states with an explanation, never a fabricated plan.

---

## 13. Future acceptance tests (record only — none implemented, none passed, by this document)

The following are recorded as **planned** acceptance tests for a future implementation. **This
addendum does not implement, run, or pass any of them.**

1. $65 and $68 both preserve the same optimal combination.
2. The additional $3 changes another acquisition or proposed cut.
3. The additional $3 makes passing better despite remaining affordable.
4. A below-plan winning price releases money and changes the remaining plan.
5. Another team wins a target and the optimizer finds the best replacement combination.
6. Several simultaneous leading bids share one budget without double-counting.
7. Raising an existing leading bid charges only the incremental commitment.
8. Being outbid releases the correct commitment; a losing proxy cap does not reserve cash.
9. Simultaneous proxy/bid updates cannot exceed the permitted budget.
10. A leading commitment cannot be canceled by the optimizer to manufacture a better plan.
11. $0 bids, $0 budgets, unknown prices, unused cash, and no-beneficial-purchase outcomes all behave
    correctly.
12. The optimal acquisition count changes according to value and roster consequences, never a fixed
    six-player target.
13. Joint add/drop optimization avoids duplicate cuts and correctly handles open spots and protected
    players.
14. Unnominated eligible players remain part of future planning; sold players are excluded.
15. Manual what-if edits never create real bids, purchases, or roster transactions.
16. Switching teams, stale events, duplicate events, reconnects, and private-data permissions are all
    handled correctly.
17. Missing valuation data is disclosed rather than silently treated as zero.
18. A small, hand-checkable candidate set matches exhaustive enumeration of all legal acquisition/drop
    combinations.
19. "Best found," "proven optimal under this model," and "infeasible" are labeled correctly and
    distinctly.
20. Raising one hypothetical purchase price cannot improve the best feasible utility when every other
    input and constraint is held fixed (a monotonicity property test).

**CONFIRMED — evidence discipline for these tests, once written:** use synthetic fixtures for
mathematical tests and clearly identify them as synthetic (matching this document's own convention).
Historical replay, when added later, must use only information that would have been available at the
time — the same no-hindsight rule as
`docs/trade/HISTORICAL_TRADE_REPLAY_AS_OF_ANALYSIS_SPEC.md`.

---

## 14. Fit into the existing combined-phase roadmap (CONFIRMED reuse list, PROPOSED phase breakdown)

### 14.1 Reusable existing components (inspected, confirmed present)

| Component | Path | Reused for |
|---|---|---|
| Canonical player valuation | `_compute_unified_rankings`, `rankDerivedValue` | all value inputs — no second valuation |
| Team/roster context | `GET /api/draft/roster-context`, `src/api/draft_optimizer_api.py` | roster state, budget, open spots |
| Dropability / whole-roster optimization | `src/draft/displacement.py`, `src/ros/lineup.py::solve_optimal_assignment` | cut ladder, legality |
| Replacement level | `C2-REPL-01` (`src/roster_intel/*` — 5 implementations flagged for consolidation in the manifest) | `waiverValue(pos)` |
| Auction settings and budget allocation | draft-capital pick-to-dollar ladder, `src/draft/rookie_pool.py` | budget provenance |
| Bid-state ingestion | `useSleeperDraftSync` → `handleLivePick` → `recordPick` (completed picks only, confirmed) | completed-purchase ingestion; live in-progress bid ingestion is new work (§3) |
| Selected-team state | existing global team-selection mechanism | every per-team view in this epic |
| Shared data snapshots / event handling | `useMemo`/`useDeferredValue` workspace pattern (`docs/perfect-draft.md` §8) | live re-solve triggers (§9) |
| Existing draft UI and player profiles | `frontend/components/draft/PerfectDraftPanel.jsx`, canonical player-profile route | UI shell, player linking |

**CONFIRMED — reuse these; do not reimplement any of them.** Preserve the different rules for rookie
auctions, waivers, and trades — their budgets and transaction semantics are not collapsed into one
model (this is the same separation §2.1 already states for rookie-auction dollars vs. FAAB).

### 14.2 Proposed phase breakdown (PROPOSED — sequencing itself is `docs/EXECUTION_PLAN.md`'s decision, not this document's)

| Phase | Scope | Depends on |
|---|---|---|
| **A** | Verified auction rules, data contracts, price provenance, bid/budget state model (§3–§5, §10) | existing roster-context API, existing price model |
| **B** | Joint roster-and-budget optimizer extended to live state; validated mathematical fixtures (§6, §13 tests 1–14, 18–20) | Phase A; existing knapsack/ECC/ladder machinery |
| **C** | Price sensitivity, strategic ceilings, what-if comparisons (§7, §8) | Phase B |
| **D** | Live auction board and Perfect Draft UI (§3, §11) | Phase A (data), Phase C (numbers to display) |
| **E** | Event consistency, privacy, performance, replay validation (§9, §12, §13 tests 15–17) | Phases A–D |
| **F** | Later uncertainty/scenario improvements (probability-calibrated price modeling, §10) | Phase A–E, and explicit evidence/calibration per §10 |

This phase breakdown organizes future dependent work; it does **not** create six new manifest rows.
One manifest row (`C7-DRAFT-03`) carries the whole epic, consistent with this repository's
capability-grain manifest convention (e.g. `C7-BEST-TRADE`); phase sequencing and PR boundaries are
authorized only through `docs/EXECUTION_PLAN.md`, when and if the owner authorizes implementation.

### 14.3 Consolidation, not a competing schedule

- Extends `docs/perfect-draft.md` (§11 there points here) rather than replacing it.
- Consolidates existing defect **W10-F001 / inventory row 3.7** ("Draft bid respects remaining
  budget") into this epic's §5/§7 legal-maximum machinery.
- Does not touch, duplicate, or override `C7-DRAFT-01` (declared-scope Perfect Draft, COMPLETE) or
  `C7-DRAFT-02` (pre-auction snapshot capture, separate and still time-critical per inventory row
  3.6 — **run before the actual 2026 rookie auction regardless of this epic's status**).
- Does not alter FAAB (`C4-FAAB-*`), waivers, or trade budgets/semantics.
- Fits into `docs/BACKLOG_REPLAN_2026-09-10.md` Phase 6 (FAAB/Waiver Platform) alongside existing
  draft/budget work, per that document's own combined-phase grouping convention — see the row added
  there in this same change.

---

## 15. Unresolved items (recorded, not invented)

| # | Item | Why unresolved |
|---|---|---|
| U1 | Exact simultaneous-auction concurrency limit of the live platform | Not yet confirmed against the real platform's rules (§1.1) |
| U2 | Whether any existing integration exposes live in-progress bid/lead state, or only completed picks | `useSleeperDraftSync` is confirmed for completed picks only; live bid-level integration is unverified (§3) |
| U3 | Exact eligible-player-pool size if it differs from 72 nominations/picks | Needs verification against `src/draft/rookie_pool.py` and the live pool, not assumed equal to the pick count (§2.1) |
| U4 | Reconciliation-conflict rule between an imported platform update and a manual entry | A default is proposed (§3) but not confirmed as an owner decision |
| U5 | Whether/when probability-calibrated price modeling (Phase F) is authorized, and its evidence bar | Explicitly deferred; requires calibration evidence per §10 before any implementation |
| U6 | Exact bid-increment and proxy-escalation rules of the live auction platform | Needed to implement the atomic budget check in §5 correctly; must be read from the platform, not assumed |

These remain open. Recording them here satisfies this addendum's own instruction to preserve
unresolved details rather than inventing answers or blocking the documentation update.
