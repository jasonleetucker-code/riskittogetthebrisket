"""League Intelligence Engine — canonical league config + exact scoring.

Foundation modules (LI-1/LI-2):

* :mod:`src.league_intel.config` — versioned canonical league config
  loaded from the provenance snapshot in ``config/league_intel/``,
  plus a polite live-refresh path that reports drift without mutating
  the stored snapshot.
* :mod:`src.league_intel.scorer` — deterministic exact scorer over
  Sleeper stat keys (ADR-005), golden-validated against Sleeper's own
  awarded ``players_points``.

See ``docs/league-intelligence/`` for the master plan, ADRs, and the
empirical scoring-validation report.
"""
