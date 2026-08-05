"""Roster & Trade Intelligence (WS-J).

**STATUS: INTERNAL-ONLY. NO FRONTEND CONSUMER. NOT LIVE PRODUCT.**

4,385 lines reachable only through ``GET /api/gameplan``, which no page,
component or Next bridge route fetches (audit W20-F001).  Read
``src/api/gameplan.py``'s module docstring before treating anything here
as shipped — including why it is marked rather than deleted, and why
the ``override_state`` hook has no caller.  The marker is enforced by
``tests/api/test_gameplan_internal_only.py``.

One exception, and it is load-bearing: ``src/roster_intel/window.py``
IS live product.  It is THE team-direction definition for the whole app
(audit W20-F006) — ``frontend/lib/team-phase.js`` is a port of it,
pinned by ``tests/fixtures/competitive_window_cases.json``, and /phases
and /rosters both render it.  Changing its anchors, weights,
temperature or age bounds changes two user-facing pages.

Additive layer over the League Intelligence engine. Valuation, exact
scoring, the best-ball optimizer, replacement levels and the value
schema are consumed from ``src/league_intel/`` as-is — nothing here
re-derives them.

Two halves that meet at ``RosterProfile`` / ``CompetitiveWindow``:

* **Roster engine** — ``marginal``, ``profiles``, ``window``,
  ``roster_source``, ``engine``. Measures what a roster IS by
  re-solving the exact lineup: marginal contribution, absence
  fragility, tradeable surplus, urgent need, and the competitive
  window as a five-state distribution. ``engine.analyze_roster``
  composes them and consumes ``src/ros/playoff_sim`` rather than
  simulating a second time.
* **Trade engine** — ``partner``, ``targets``, ``packages``. Measures
  what to DO about it: which positions are worth attacking, which
  players are worth pursuing, how a counterparty is likely to receive
  an offer, and which concrete packages are worth sending. Consumes
  the roster engine's output; never re-derives it.
"""
