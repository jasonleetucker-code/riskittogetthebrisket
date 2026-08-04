"""Consensus Edge — one explainable buy/sell signal.

The platform accumulated six overlapping answers to "is this player a
buy?" — the Sharps market signal, the ``/edge`` retail-vs-consensus rank
gap, BDVM's market alpha, the frontend ``signal-engine.js`` rule
hierarchy, ``roster_intel.targets``, and a never-wired
``news.unified_signal_engine``.  They measure different things, disagree,
and none has ever been validated against an outcome.  "Buy" means a
different thing on each screen.

This package is the single answer.  It does NOT add a seventh opinion to
the pile: it consumes the existing engines as components, scores them on
one scale, and — crucially — says out loud when they disagree or when the
evidence is too thin to support a call at all.

Isolation contract (same posture as ``src/bdvm``):

* Nothing here writes ``rankDerivedValue``, mutates
  ``latest_contract_data``, or changes an existing route's output.
* Everything is reachable only behind the ``consensus_edge`` feature
  flag, which defaults **OFF**.
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
