"""League Comparison — positional scoring-balance calibration tool.

Compares the user's custom Sleeper league scoring against a "standard"
baseline league across multiple historical NFL seasons.  The goal is
to detect whether custom scoring rules accidentally distort positional
value relative to a normal fantasy environment.

Public entry point: :func:`src.league_comparison.service.build_comparison`
which returns a fully-built ComparisonResult dict ready to be returned
by ``GET /api/league-comparison``.

Architecture
------------
* ``sleeper_scoring`` — fetches ``scoring_settings`` for a given
  Sleeper league ID.  It has no registry awareness of its own; callers
  decide which ID to hand it (see below).
* ``historical_stats`` — wraps ``src.nfl_data.ingest`` to load weekly
  stat rows season-by-season with graceful unavailability handling.
* ``scoring_engine`` — applies a Sleeper scoring dict to weekly stat
  rows using the existing ``compute_weekly_points`` engine and rolls
  up to season totals per player.
* ``metrics`` — pure stat math: average / median / percentiles /
  blended scores (legacy + improved) / positional shares /
  similarity score / status labels.
* ``idp`` — placeholder hooks for IDP comparison (Top-96 IDP vs
  Top-96 offensive flex); inert until real IDP data is verified.
* ``service`` — orchestrator that ties everything together with a
  7-day disk cache keyed on league IDs + scoring hashes + version.

Why the baseline league stays decoupled from the league registry
------------------------------------------------------------------
The two leagues being compared are NOT symmetric.  "My league" IS the
user's active league, so its Sleeper ID is resolved through
``src.api.league_registry.get_default_league()`` (W18-F005) — the same
canonical owner every other league-scoped consumer uses.  This module
does not maintain a second, independent notion of which league is
"mine".

"Baseline league" is different: a *reference* scoring profile chosen
purely for calibration, not a league anyone actually plays in.  Pushing
it through ``src.api.league_registry`` would force it into
``config/leagues/registry.json`` even though this feature never needs
its rosters, teams, or any other registry-bound data — so it stays
config-supplied via ``config/league_comparison.json``.

The endpoint returns both league IDs only in its response metadata
block; the request body never carries them.
"""
