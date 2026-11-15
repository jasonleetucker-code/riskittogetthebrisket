"""Best-ball marginal utility lane (league intelligence, Stage C).

Offline / shadow library code.  It CONSUMES the public API of the existing
owners — :mod:`src.roster_intel.best_ball_utility` (the roster-conditional
best-ball simulation), :mod:`src.ros.lineup` (the exact lineup solver),
:mod:`src.draft.context` / :mod:`src.draft.rookie_pool` (who is rostered, who is
in the auction) — and modifies none of them.  No production module imports
this package; nothing it computes is served.

Modules:

* :mod:`src.bestball.contracts` — published dataclass shapes (camelCase
  ``to_dict`` + committed fixtures).
* :mod:`src.bestball.params` — PRIOR parameters with a content-hashed
  ``paramSetId`` (``config/bestball/marginal_v1.json``).
* :mod:`src.bestball.replacement` — the realistic free-agent pool.
* :mod:`src.bestball.marginal` — marginal best-ball utility per player.
* :mod:`src.bestball.competitive` — title-probability delta, explicitly
  unavailable until the playoff simulator's basis question is decided.

Model card: ``docs/league-intelligence/bestball/MARGINAL_UTILITY_MODEL_CARD.md``.
"""
