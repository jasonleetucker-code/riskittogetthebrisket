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
* ``sleeper_scoring`` — fetches ``scoring_settings`` for arbitrary
  Sleeper league IDs (bypasses the registry — this tool deliberately
  decouples from multi-league routing).
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

Why this is decoupled from the league registry
----------------------------------------------
The two leagues being compared are NOT the user's active league
(rosters, draft capital, etc).  They're two *scoring profiles*
to compare for calibration purposes only.  Pushing them through
``src.api.league_registry`` would force them to be added to
``config/leagues/registry.json`` even though this feature never
needs rosters, teams, or any other registry-bound data.

The endpoint returns league IDs only in its response metadata block;
the request body never carries them — IDs come from
``config/league_comparison.json`` server-side.
"""
