# Owner Feature Addendum — Trade Finder Posture-Aware Draft Picks

**Owner decision date:** 2026-08-14  
**Tracking:** #841  
**Related:** #840 Competitive Posture, #792 Analyze Trade, PR #835 trade-generation planning  
**Status:** APPROVED C-SERIES SCOPE; SUPERSEDES EARLIER NO-PICKS RULE

## Superseding decision

The earlier rule that Trade Finder / Best Trade to Send Each Team generated offers must be players-only with no draft picks is withdrawn.

Draft picks are allowed when their inclusion makes the generated trade more mutually beneficial given both teams' competitive posture, current-season odds, roster construction, age/value window, and future-asset incentives.

This is a true owner-precedence change. The C-series Scope Manifest must not preserve both contradictory rules. The later 2026-08-14 posture-aware pick rule wins.

## Required behavior

- Consume #840 Competitive Posture for both teams.
- PUSH contender vs RETOOL/REBUILD opponent: explore the contender paying picks/future value for current production when the trade materially improves playoff/championship equity and improves the opponent's future value/window.
- RETOOL/REBUILD selected team vs PUSH opponent: explore sending present-oriented production and receiving picks/younger liquid value when the opponent gets a real current-season benefit.
- HOLD/similar-posture matchups: picks remain legal but must not become generic filler.
- Use canonical pick identity/value, actual ownership, Pick Forecast/projected slot where available, and real league draft-order rules.
- Never claim a team benefits from worsening its own pick outlook when it does not own that pick.
- Never recommend illegal lineup manipulation/tanking.

## Best Trade to Send Each Team

- Exactly one strongest qualifying offer per opponent remains the target.
- Picks may now be included.
- The earlier equal-count rule remains **equal player count each direction**; picks do not count as players and may be added around that equal-player package.
- Do not force picks when a player-only offer is better.
- Preserve honest no-result behavior.

## Mutual-benefit ranking

Generated offers should account for both sides' roster and strategic utility, including canonical package value, Team Strength/Weakness, #839 Meaningful Roster Core, #838 Age-Value/Young Core, playoff/championship probability changes, pick capital, #840 posture fit, external market evidence where valid, plausibility, and user protection/LOCK/EXCLUDE constraints.

Do not rank solely by calculator exploit.

## External-market guardrail

Pick-inclusive packages must not manufacture independent KTC/IDP approval using our own imputed values. Unsupported external coverage is incomplete. Before shipping, the parent feature must have an honest qualification path for pick-inclusive packages.

## Analyze Trade integration

Every generated package should be analyzable by #792 using the full before/after roster, age/value, probability, pick-capital, and strategic-posture framework.

## Zero-loss reconciliation

During the post-B C-series replan, reconcile this later owner instruction into:

- `docs/OWNER_MASTER_FEATURE_BACKLOG_2026-08-13.md` — supersede the no-picks language in the existing Best Trade row and add/map #841;
- `docs/OWNER_REQUESTED_TODO.md`;
- `docs/OWNER_REQUESTED_TODO_SPEC_INDEX.md`;
- `docs/MASTER_PRODUCT_PLAN.md`;
- `docs/OWNER_FEATURE_INVENTORY.md`;
- `docs/OWNER_PRODUCT_BACKLOG_SPEC.md`;
- `docs/trade/TRADE_GENERATION_PREFERENCES_AND_REFINEMENT_SPEC.md`;
- the final C-Series Scope Manifest / dependency DAG.

Until reconciliation is complete, this addendum + #841 are authoritative over any older `players only / no draft picks` Trade Finder statement.