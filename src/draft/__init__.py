"""Rookie-auction draft optimization ("Perfect Draft").

This package answers one question: *given a team's remaining rookie-auction
dollars, its current roster, the rookies still available and their expected
prices, which COMBINATION of rookies produces the greatest net increase in
roster value?*

Two things it deliberately is not:

* It is not a valuation system.  Every value it consumes is the canonical
  ``rankDerivedValue`` stamped by ``src/api/data_contract.py``; nothing here
  re-prices a player.
* It is not a draft-slot model.  This league places no minimum or maximum on
  how many rookies a team may draft — a team may buy as many or as few as its
  dollars allow.  The only real constraints are budget, roster capacity, and
  the value of the player who would have to be released.

Module map:

``displacement``
    Who would actually get cut, and what that costs.  Builds the Effective Cut
    Cost ladder with a real starting-lineup feasibility check.
``context``
    Assembles the per-team roster context the client optimizer runs against.

The optimizer itself (the budget knapsack) lives in
``frontend/lib/perfect-draft.js`` — see that file's header for why it runs on
the client rather than here.
"""
