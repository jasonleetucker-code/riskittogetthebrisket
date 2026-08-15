# Analyze Trade + Competitive Posture Addendum

> **RECONCILIATION AMENDMENT — 2026-08-14.** Promoted to `main` verbatim from its planning branch by the
> post-B master reconciliation (`docs/POST_B_RECONCILIATION_2026-08-14.md`). No content was changed. This is **newer owner intent than the
> reconciliation's original census** — it landed on the planning PRs mid-reconciliation and was folded in
> under the newest-instruction-wins rule. Phase placement and completion evidence are in
> `docs/C_SERIES_SCOPE_MANIFEST.md`.


**Owner decision date:** 2026-08-14  
**Tracking:** #792, #838, #839, #840  
**Status:** BINDING C-SERIES SCOPE INPUT; DEPENDENCY-GATED

## Owner intent

The Trade Calculator must not stop at asset arithmetic. Relevant roster-construction and season-context data should be visible while building/reviewing a trade, and the deliberate **Analyze Trade** action must actually **factor that evidence into** the final MAKE / LEAN MAKE / TOO CLOSE / LEAN PASS / PASS recommendation.

The final analyzer must answer not only “who wins the values?” but also:

- What does this do to the selected team's meaningful roster by position?
- Does it fix or create roster weaknesses?
- Does meaningful roster value improve or decline?
- Does the valuable core get younger or older overall and by position?
- How does Young Core / roster window change?
- How do Make Playoffs %, Earn Bye %, and Win Championship % change?
- How does owned future draft capital change?
- If the selected team owns its own future pick, does legitimate roster construction materially change its projected pick slot/value under the league's actual draft-order rules?
- Given the current week/deadline and the team's real competitive outlook, should the manager be pushing, holding, retooling, or rebuilding?
- Does this particular trade fit that strategy strongly enough to accept it?

## Canonical before/after trade state

For every proposed trade, build a true pre-trade and post-trade roster state and rerun downstream canonical consumers. Do not approximate roster impact by summing incoming minus outgoing values.

Where the corresponding canonical subsystem is available/trustworthy, the analyzer must compare:

1. canonical incoming/outgoing asset and package equity;
2. Team Strength overall and position groups;
3. Team Weakness / Need Priority;
4. #839 Meaningful Roster Core membership, promotions and displacements;
5. meaningful positional value at QB/RB/WR/TE/DL-EDGE/LB/DB;
6. #838 value-weighted core age;
7. #838 Young Core Index and position-group age/value ranks;
8. current-season projected production / best-ball fit through canonical projection owners;
9. Make Playoffs %;
10. Earn Bye % where applicable;
11. Win Championship %;
12. owned pick capital / canonical pick value;
13. projected own-pick slot/value when the user owns that pick and the league's real draft-order methodology permits a defensible counterfactual;
14. external market corroboration/disagreement;
15. uncertainty/confidence;
16. #840 Competitive Posture and strategic fit.

The UI may show additional related context such as NFL-team exposure/concentration, but descriptive portfolio context does not become an automatic veto unless separately owner-approved.

## Competitive Posture

Create one reusable team-level strategic owner, tracked in #840, with outputs:

- **PUSH** — prioritize meaningful current-season championship equity;
- **HOLD** — preserve optionality because current/future incentives are close or uncertain;
- **RETOOL** — move some present-oriented value toward younger/liquid/future assets while preserving a credible core;
- **REBUILD** — prioritize future dynasty value and draft capital over marginal current-season production.

Posture must not be a single arbitrary threshold. It must interpret canonical inputs including:

- Make Playoffs / Bye / Championship probabilities;
- actual week, games remaining, deadline proximity and postseason state;
- Team Strength / Weakness;
- #839 Meaningful Roster Core;
- #838 age/value window and Young Core;
- position-specific age/value/strength;
- injuries/availability/current-season outlook where trustworthy;
- owned draft capital and Pick Forecast;
- whether the team owns its own pick;
- actual league draft-order rules;
- confidence/uncertainty.

The same probability should mean different things at different times. A 25% playoff chance before Week 1 is not the same strategic state as 25% in deadline week.

## Marginal probability and utility, not labels alone

Analyze Trade must care about the **change caused by the trade**.

Examples:

- A PUSH team paying a first for a veteran is not automatically good. If championship odds move only 12.0% → 12.8%, the current-season gain may be too small for the future-value cost.
- A RETOOL team losing some current-season scoring is not automatically good. The younger/pick package still has to justify the dynasty-value and probability sacrifice.
- A REBUILD team can still accept an older player if the value/liquidity is clearly favorable.
- A HOLD team can become PUSH if a proposed trade produces a large enough title-equity jump at an acceptable price.

Posture changes the utility of outcomes; it is not a hard veto.

## Pick-position strategy guardrails

The analyzer may consider whether a team should trade present production for picks / future value, but must model this correctly:

- Never treat losing as beneficial unless it improves the value of a pick the selected manager actually owns.
- If the manager traded away its own pick, worsening its own record/Max PF is not a draft-capital benefit.
- Other teams' picks follow those teams' projected outcomes, not the selected team's.
- Derive actual non-playoff draft-order methodology where possible (Max PF, record, consolation bracket, etc.).
- If Max PF determines order, benching a player does not reduce Max PF; legitimate roster changes may.
- Never encourage illegal lineup manipulation or violation of league anti-tanking rules.
- Quantify expected pick-value improvement versus dynasty value surrendered; do not sacrifice substantial value for a trivial pick-slot move.

## Required decision explanation

The user should get a compact recommendation plus expandable evidence. Example:

> **LEAN MAKE — Medium confidence**  
> **Team direction:** RETOOL  
> **For:** WR core gets 1.4 years younger; Young Core rises 61 → 72; projected own first improves from roughly 1.08 to 1.05; canonical future value improves.  
> **Against:** playoff odds fall 42% → 34%; championship odds fall 5.6% → 3.9%; RB becomes a bottom-three league weakness.  
> **Why MAKE:** at Week 9, current title equity is low enough that the future-value/window gain outweighs the lost 2026 equity.

Or:

> **PASS — High confidence**  
> **Team direction:** PUSH  
> The veteran upgrade fixes RB2 but improves championship odds only 14% → 15.1% while costing a projected early first and making the meaningful RB core materially older. The title-equity gain is too small for the future-value cost.

## Evidence lineage / double-counting rule

Do not simply average visible cards.

Canonical player value, vendor sources contributing to value, Monte Carlo centered on those values, Team Strength weighted by those values, and Young Core weighted by those values are related evidence lineages. Analyze Trade must distinguish:

- base asset equity;
- genuinely incremental roster marginal impact;
- current-season probability impact;
- strategic/future-window context;
- independent market corroboration;
- uncertainty.

Age does not become a second player-value adjustment. Competitive Posture does not become another independent vote when it is derived from playoff odds / Team Strength / age-value; it is a strategic interpretation layer whose components remain visible.

## Canonical dependency rules

Analyze Trade must consume, not recreate:

- canonical player/pick/package value;
- Team Strength / Team Weakness;
- #839 Meaningful Roster Core;
- #838 Roster Age-Value / Young Core;
- canonical Playoff Predictor / season simulation;
- canonical Pick Forecast / pick values;
- #840 Competitive Posture;
- canonical market/Second Opinions lineage;
- revalidated uncertainty model.

The ordinary Trade Calculator should expose the most useful before/after information inline. The deliberate **Analyze Trade** action owns the full synthesis and recommendation. CE-05 Trade Desk later consumes the same decision contract; it must not create a second analyzer.

## Validation

Before this can be trusted, test at minimum:

- strong contender paying a future first for a large title-odds jump;
- strong contender paying the same price for a tiny title-odds jump;
- bubble team near the deadline;
- rebuilder that owns its own first;
- rebuilder that traded away its own first;
- Max-PF draft order versus record-based order;
- young low-probability roster adding an older producer;
- old high-probability roster acquiring younger value;
- trade that wins raw value but creates a severe positional hole;
- trade that loses small raw value but materially improves title odds;
- trade that improves Young Core without materially improving total core value;
- current week/deadline changes causing a rational posture transition.

Use archived no-lookahead snapshots for historical validation wherever possible. Preserve unavailable/partial evidence honestly; missing inputs never become zero or fake certainty.

## C-series sequencing

This is required C-series scope. Establish the canonical dependencies first, especially Team Strength/Weakness, Playoff Predictor, Pick Forecast, #839, #838, and #840. Then integrate them into #792 and the Trade Calculator / Trade Desk surfaces. The C-series zero-loss manifest must not consider Analyze Trade complete if it only grades raw value while ignoring these approved roster/window/probability dimensions.