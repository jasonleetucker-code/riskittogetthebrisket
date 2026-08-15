# Owner Feature Addendum — Trade Context Mode + Generated-Trade Topology

> **RECONCILIATION AMENDMENT — 2026-08-14.** Promoted to `main` verbatim from its planning branch by the
> post-B master reconciliation (`docs/POST_B_RECONCILIATION_2026-08-14.md`). No content was changed. This is **newer owner intent than the
> reconciliation's original census** — it landed on the planning PRs mid-reconciliation and was folded in
> under the newest-instruction-wins rule. Phase placement and completion evidence are in
> `docs/C_SERIES_SCOPE_MANIFEST.md`.


**Owner decision date:** 2026-08-14  
**Tracking:** #841, #842, #792, #840  
**Status:** BINDING LATER OWNER ADDENDUM FOR C-SERIES ZERO-LOSS REPLAN

## Superseding decisions

1. The old generated-trade `no draft picks` rule is withdrawn under #841.
2. The old exact-equal-player-count rule is withdrawn.
3. Generated Trade Finder / Best Trade to Send Each Team packages may have at most a **one-player difference** between sides:
   `abs(players_A - players_B) <= 1`.
4. Picks do not count as players for that topology constraint.
5. Trade evaluation/generation gets one shared **Use Team Context** control under #842. Default is **ON**.

## Allowed player topologies

Allowed: 1v1, 2v1, 1v2, 3v2, 2v3, and larger topologies only when the player-count difference remains <=1.

Disallowed: 3v1, 1v3, 4v2, 2v4, or any package whose player counts differ by 2+.

Picks may accompany either side without changing the player-count difference calculation.

## Use Team Context — ON by default

When ON, Trade Finder and Analyze Trade consume the full validated team-aware stack: actual rosters/ownership, Team Strength/Weakness, #839 Meaningful Roster Core, #838 Age-Value/Young Core, #840 Competitive Posture, playoff/bye/championship counterfactuals, season timing, pick ownership/forecast, positional needs and roster fit.

Trade Finder uses both teams' context and can direct draft picks based on legitimate differences in competitive posture.

## Use Team Context — OFF / Asset-Only

When OFF, the verdict/ranking must not consume team-specific roster fit, Strength/Weakness, team Age-Value changes, playoff/title odds, competitive posture, own-pick strategic effects, season-window strategy, or opponent posture.

Asset-Only may still consume canonical league-format-aware asset value, package/VA math, external-market evidence, intrinsic player age, pick value, uncertainty, liquidity/comps, confidence/provenance, and explicit hard user constraints.

League-specific TEP/Superflex/IDP/scoring treatment remains part of canonical asset value. OFF removes **team-specific context**, not league-format valuation.

## Analyze Trade requirement

#792 uses the same toggle:
- ON = full context-aware MAKE / LEAN MAKE / TOO CLOSE / LEAN PASS / PASS synthesis.
- OFF = clearly labeled **Asset-Only Analysis** using only non-team-context evidence.

Never silently switch ON to OFF because team context is missing; mark affected dimensions unavailable/degraded.

## C-series reconciliation

The post-B C Scope Manifest must treat these as newer-owner supersessions, not as additive alternatives. It must remove/override stale planning statements that say:
- generated offers are players-only;
- draft picks are prohibited;
- player counts must be exactly equal;
- team context is always mandatory with no user control.

The canonical end state is one shared generator/analyzer architecture with a default-ON team-context mode and an explicit asset-only mode, plus the <=1 player-count topology rule.
