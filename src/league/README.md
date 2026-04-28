# `src/league` — intentionally empty

This directory used to host the **League Adjustment Model (LAM)** —
a per-league scarcity / replacement-level overlay that shifted a
player's value based on positional supply across the user's specific
roster.

LAM was retired in 2026 because the upstream sources we now blend
(KTC, IDPTradeCalc, DLF, FantasyPros, DraftSharks, FootballGuys, etc.)
already price the market for the operator's superflex / TE-premium /
IDP-on configuration via their own scoring profiles, and the per-
league delta LAM produced was small and noisy.

The single source of truth for league-aware behavior now lives in:

- `src/api/league_registry.py` — the active league inventory
  (`config/leagues/registry.json`), scoring-profile resolution, and
  the `LeagueConfig` dataclass.
- `src/api/data_contract.py` — every league-scoped stamp on the
  contract response (`meta.leagueKey`, `meta.scoringProfile`,
  `sleeper.*`, etc.).
- `src/api/sleeper_overlay.py` — the per-league roster + trade overlay.

If you find yourself reaching for "league-side adjustments to player
values" again, **stop and revisit the rankings vs. league context split
documented in `CLAUDE.md`** before adding code here:

> Scoring profile controls rankings. League key controls context.

The empty `__init__.py` is kept so `import src.league` doesn't break
historical references. There is no replacement module — LAM-style
adjustments are expected to come from upstream source weights or the
TE-premium multiplier in the unified rankings blend, not from a
separate per-league post-pass.

— Audit pass 2026-04-28
