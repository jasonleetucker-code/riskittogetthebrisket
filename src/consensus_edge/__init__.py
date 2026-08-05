"""Consensus Edge — one explainable buy/sell signal.

The platform accumulated six overlapping answers to "is this player a
buy?" — the Sharps market signal, the ``/edge`` retail-vs-consensus rank
gap, BDVM's market alpha, the frontend ``signal-engine.js`` rule
hierarchy, ``roster_intel.targets``, and a never-wired
``news.unified_signal_engine``.  They measure different things, disagree,
and none has ever been validated against an outcome.  "Buy" means a
different thing on each screen.

This package is the intended single answer, and it is honest about how
far that has got.  It scores its components on one scale and — crucially
— says out loud when they disagree or when the evidence is too thin to
support a call at all.

**It does not, today, consume those six engines.**  This paragraph used
to claim it did.  What it actually reads is the canonical contract
(``src.api.data_contract``), the raw intel ledger, ``src.league_intel``,
``src.nfl_data``, ``src.playerctx``, ``src.public_league`` and
``src.sharp.cohort`` — and the incumbent Sharps formula is
*reimplemented* in ``sharp_flow.legacy_signal_strength`` as a benchmark
to score against, not consumed.  None of the six has been retired
either, so for now this is a seventh opinion that is measured and
labelled, rather than the one that replaced the other six.  Saying
otherwise made a plan sound like a state.

Isolation contract (same posture as ``src/bdvm``):

* Nothing here writes ``rankDerivedValue``, mutates
  ``latest_contract_data``, or changes an existing route's output.
* Every board-serving route is reachable only behind the
  ``consensus_edge`` feature flag, which defaults **OFF**.  The one
  deliberate exception is ``GET /api/consensus-edge/methodology``, which
  answers with the flag off so a user who cannot see the board can still
  read what it does and does not claim (``api.py``, and pinned by
  ``test_methodology_is_readable_even_when_disabled``).  This said
  "everything" until 2026-08-05, which understated the surface by
  exactly one route and made an isolation contract slightly false.
* Every payload carries a model version, a parameter-set id, and the
  timestamps of the data it was computed from.  A number without
  provenance is not shippable here.

Deliberately stdlib-only: ``numpy``/``pandas``/``scipy`` are optional
extras in this repo (absent from a default ``make setup``), and a
buy/sell engine that cannot run without them would be undeployable on
exactly the boxes that serve it.
"""

from __future__ import annotations

# Bumped when a change alters the numbers a given input would produce.
# Stamped on every payload and every snapshot row so a stored result can
# always be traced to the code that made it.
MODEL_VERSION = "ce.2026-08-04.v0-shadow"

__all__ = ["MODEL_VERSION"]
