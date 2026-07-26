"""Roster & Trade Intelligence (WS-J).

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
