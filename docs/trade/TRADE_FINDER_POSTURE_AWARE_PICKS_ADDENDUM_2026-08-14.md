# Trade Finder — Posture-Aware Draft Picks Addendum

**Owner decision date:** 2026-08-14  
**Tracking:** #841  
**Supersedes:** the earlier blanket `players only / no draft picks` rule for Trade Finder / Best Trade to Send Each Team generation  
**Depends on:** #840 Competitive Posture, #839 Meaningful Roster Core, #838 Roster Age-Value / Young Core, canonical Team Strength/Weakness, Playoff Predictor, canonical pick values / Pick Forecast

## Binding owner decision

Draft picks are valid generated-trade assets when their inclusion makes a proposed trade more mutually beneficial given **both teams' actual strategic position**.

The generator must not treat picks as generic equalizer filler. It should use them because dynasty teams can rationally value current production and future capital differently depending on championship probability, playoff probability, season timing, roster window, positional needs, age/value construction, and future-pick ownership.

## Required strategic behavior

### PUSH contender vs RETOOL / REBUILD opponent

Explore packages where the contender sends future draft capital and/or younger liquid value in exchange for current production that:

- fills a real Team Weakness;
- improves the canonical Meaningful Roster Core;
- materially improves Make Playoffs / Bye / Championship probability where supported;
- is worth the future-value cost.

The rebuilding/retooling side must receive enough future value, youth, liquidity, or pick capital for the package to improve its own window rather than merely subsidizing the contender.

### RETOOL / REBUILD selected team vs PUSH opponent

Explore packages where the selected team sends present-oriented production that the contender can genuinely use and receives:

- owned draft picks;
- younger liquid assets;
- future-value improvement;
- legitimate improvement to its own pick outlook only when it actually owns the relevant pick and league draft-order rules support that conclusion.

The contender should receive a meaningful current-season benefit, not merely a player with a recognizable name.

### HOLD / same-posture matchups

Picks remain legal but are not mandatory. Add them only when they improve the actual package or solve a real two-team objective mismatch.

## Best Trade to Send Each Team

The prior `no draft picks` constraint is withdrawn.

The feature should still return exactly one strongest qualifying offer per opponent when one exists.

The prior equal-count constraint now means **equal number of players each direction**. Picks are not players and may appear additionally on either side when the posture-aware generator finds that appropriate.

Examples:

- 1 player + 2027 1st for 1 player is allowed.
- 2 players for 2 players + 2028 2nd is allowed.
- 1 player for 2 players remains disallowed under the equal-player-count rule unless the owner later changes that separate constraint.

Do not force a pick into a player-only trade that is already the strongest mutually defensible offer.

## Pick construction rules

1. Use canonical pick identity and canonical pick value.
2. Offer only picks actually owned by the team unless the surface explicitly supports hypothetical generic picks.
3. Prefer exact known pick identity/slot when known; otherwise use the canonical future-pick representation and projected slot distribution.
4. Do not assume every first is interchangeable. Year, round, original franchise, projected slot/range, and uncertainty matter.
5. Do not use a pick merely to make raw totals line up.
6. Quantify pick-value change against what each side is giving up.
7. If the team does not own its own pick, worsening that team's outlook is not a draft-capital benefit to that team.
8. Respect the league's actual draft-order mechanics, including Max PF / record / consolation rules.
9. Never recommend illegal lineup manipulation or intentional lineup violations.

## Two-team mutual-utility objective

Generated candidates should be evaluated for both teams with a shared canonical package generator. Relevant dimensions include:

- canonical package/equity value;
- package / consolidation methodology where approved;
- Team Strength and Team Weakness before/after;
- #839 Meaningful Roster Core promotions/displacements;
- #838 age/value and Young Core before/after;
- Make Playoffs / Bye / Championship probability change;
- future draft capital and Pick Forecast change;
- #840 Competitive Posture fit for each side;
- external market corroboration/coverage where valid;
- owner protections, untouchables, LOCK and EXCLUDE constraints;
- plausibility / asset quality / liquidity.

Do not double-count descendants of the same canonical value evidence and do not rank by the largest calculator exploit.

## External calculator coverage

Pick-inclusive packages complicate the earlier external qualification rule. Preserve honesty:

- use only native external coverage as an independent vote;
- canonical imputation cannot manufacture external corroboration;
- if KTC or IDP Trade Calculator cannot natively evaluate the full pick-inclusive package, mark that source incomplete;
- before shipping, define a valid qualification path for pick-inclusive generated packages rather than silently pretending an unsupported source approved the trade.

## Analyzer integration

Every generated package should be eligible for the same canonical Analyze Trade contract (#792), including before/after roster construction, age/value, playoff/championship odds, pick capital, and Competitive Posture explanation.

A generated package is not good merely because the selected side 'wins the calculator.' The intended end state is a deal the selected manager should want **and** the opponent has a rational reason to accept based on its own situation.

## Acceptance examples

- PUSH team offers a future 1st to a REBUILD team for a veteran who materially changes championship odds: valid candidate.
- REBUILD team asks a PUSH team for picks in exchange for useful current production: valid candidate.
- PUSH team pays a 1st for a veteran who changes championship odds only trivially: should rank poorly / fail strategic-fit threshold.
- REBUILD team that does not own its own 1st is not credited with 'improving its pick' by getting worse.
- Player-only offer remains preferred when it is the best mutual trade.
- Pick is never inserted solely as cosmetic filler.

## Sequencing

This is approved C-series scope. Establish the shared canonical foundations first, then integrate posture-aware pick generation into Trade Finder / Best Trade to Send Each Team and validate the same packages through Analyze Trade.

This addendum is binding where older trade-generation records still say `no draft picks`; those older statements are superseded.