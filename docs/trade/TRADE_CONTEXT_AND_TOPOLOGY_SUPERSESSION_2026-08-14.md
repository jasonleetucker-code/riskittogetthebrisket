# Trade Finder / Analyze Trade — Team Context Mode + Player-Count Topology Supersession

**Owner decision:** 2026-08-14  
**Tracking:** #841, #842, #792, #840  
**Status:** APPROVED PRODUCT REQUIREMENT; SUPERSEDES OLDER CONTRADICTORY TRADE-GENERATION RULES

## 1. Player-count topology

The older exact-equal-player-count requirement is withdrawn.

For generated Trade Finder / Best Trade to Send Each Team packages:

`abs(players_side_a - players_side_b) <= 1`

Allowed examples:
- 1-for-1
- 2-for-1 / 1-for-2
- 3-for-2 / 2-for-3

Disallowed examples:
- 3-for-1 / 1-for-3
- 4-for-2 / 2-for-4
- any package where the number of **players** differs by more than one

Draft picks do not count as players for this topology rule. A package like `2 players + 1 pick for 1 player` is topology-valid; `3 players for 1 player + 1 pick` is not.

This rule broadens the search space; it does not require uneven packages. Prefer whichever qualifying topology is strongest and most mutually defensible.

## 2. Draft picks remain allowed

The prior no-picks rule remains withdrawn under #841. Picks may appear on either side when they improve the package under the active analysis mode. They are not filler and must use canonical identity/value, real ownership, and honest external-market coverage.

## 3. Shared `Use Team Context` control

Trade evaluation and generation use one shared mode contract from #842.

Default: **ON**.

### ON — Team Context

Use real selected-team/opponent context where available and valid:
- roster ownership;
- Team Strength / Team Weakness;
- #839 Meaningful Roster Core;
- #838 Age-Value / Young Core;
- #840 PUSH / HOLD / RETOOL / REBUILD posture;
- playoff / bye / championship probability and post-trade counterfactuals;
- season timing / trade deadline;
- current/future pick ownership, value and Pick Forecast;
- positional need, surplus, depth, promotion/displacement;
- approved user/team constraints.

Trade Finder must optimize mutual benefit for both teams. Posture-aware pick direction is active in this mode.

### OFF — Asset-Only

Evaluate/generate without team-specific roster or competitive context influencing the verdict/ranking.

May still use:
- canonical league-format-aware player/pick value;
- package / Value Adjustment math;
- external-market corroboration/disagreement;
- asset-level uncertainty;
- player age as an intrinsic descriptor;
- pick year/round/slot/value;
- real trade comps / liquidity where valid;
- source confidence/coverage;
- hard user constraints.

Must not use in the verdict/ranking:
- selected-team roster fit or positional needs;
- Team Strength / Weakness changes;
- #838 team Age-Value / Young Core changes;
- playoff / bye / championship odds;
- #840 competitive posture;
- own-pick strategic/tanking effects;
- season-window strategy;
- opponent posture.

OFF does **not** mean standard-format values. The selected league's TEP/Superflex/IDP/scoring/roster configuration may still affect canonical asset valuation. It removes team-specific context only.

## 4. Analyze Trade

#792 must expose the same mode:
- ON = complete team-aware MAKE / LEAN MAKE / TOO CLOSE / LEAN PASS / PASS decision;
- OFF = clearly labeled **Asset-Only Analysis** using only asset/package/market/uncertainty evidence.

If team-context panels are visible while OFF, they must be marked `not included in this verdict`.

Never silently fall back from ON to OFF because team context is missing. Missing team-context dimensions must degrade explicitly.

## 5. Trade Finder / Best Trade to Send Each Team

#841 consumes this mode:
- ON = posture-aware mutual-benefit generation, including picks based on team objectives;
- OFF = asset/package/market-based generation without contender/rebuilder or roster-fit reasoning.

The player-count-difference rule applies in both modes.

## 6. Validation

Required fixtures:
- 1v1, 2v1, 1v2, 3v2, 2v3 accepted when otherwise qualifying;
- 3v1 and 1v3 rejected even when picks are present;
- picks do not affect the player-count topology calculation;
- same trade can legitimately differ ON vs OFF only because team-context dimensions are included/excluded;
- OFF verdict/generation cannot consume #840, playoff odds, Team Strength/Weakness, or team-level age/value outputs;
- ON with missing context degrades honestly rather than switching modes;
- desktop/mobile parity and reproducible share-link state when mode affects verdict.

## 7. Reconciliation rule

Newest owner instruction wins. Any older planning language requiring `players only`, `no draft picks`, or `same number of players each direction` must be treated as superseded. Any trade-analysis document that assumes team context is mandatory with no user control must be reconciled to #842.
