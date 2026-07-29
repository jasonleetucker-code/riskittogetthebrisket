"""BDVM — the Brisket Dynasty Valuation Model (v1).

A projection-driven, format-configurable *fundamental* dynasty valuation
engine, integrated per the BDVM v1.0 research document
(``docs/research/bdvm-v1/BDVM_v1_complete.pdf``) and its master
integration prompt.  The verified reference implementation lives in
``docs/research/bdvm-v1/reference/`` and is the acceptance fixture for
this package (``tests/bdvm/test_reference_parity.py``,
``tests/bdvm/test_engine.py``).

Architectural position
----------------------
This package is a SECOND, INDEPENDENT value concept — *fundamental*
value from projections — deliberately separate from the live market
board (``src/api/data_contract.py::_compute_unified_rankings``, which
produces ``rankDerivedValue`` from market ranks/values).  It never
mutates the live contract, never writes into ``rankDerivedValue``, and
is only reachable behind the ``bdvm_engine`` feature flag
(``src/api/feature_flags.py``), **default ON since 2026-07-28** (this
line said "default OFF" until the 2026-07-29 audit; the flag has been
``True`` since the baseline snapshot builder landed).  Rollback is
``RISKIT_FEATURE_BDVM_ENGINE=0`` **plus a restart** — flag reads are
cached per process.

Core formula (per player i, strategy s)::

    DV(i,s) = sum_t u_s(t) * d_s^t * S_i(t) * E[max(0, X_i(t) - R_p(t))] * G_i(t)
              - lambda_s * 0.35 * Psi_i

Module map
----------
params        versioned parameter sets (config/bdvm/*.json, content-hashed)
league_config league scoring + lineup contract (from the live Sleeper block)
scoring       projected stat line -> FPG under exact league scoring
projections   projection snapshots, adapters, robust consensus blend
pool          positional rank->FPG curves from blended projections
replacement   flex-aware dynamic replacement (VORP + VOLS diagnostic)
curves        aging curves, effective age (mileage), role ascension
survival      discrete-time fantasy-relevance hazard model
uncertainty   sigma model (CV base, role/event/sample multipliers, drift)
surplus       option-value season surplus E[max(0, X - R)] (+ ablations)
engine        season paths, strategy values, probabilities, explanations
market        market comparison layer (runs strictly AFTER fundamentals)
picks         rookie-pick outcome distributions
trade_math    CES package math + both-sides trade verdicts
ros           rest-of-season shrinkage math (scaffolding)
service       orchestration: contract + projections -> versioned payload

Every constant is a STARTING PRIOR (config/bdvm/params_v1.json) — not
backtested truth.  See docs/research/bdvm-v1/IMPLEMENTATION_REPORT.md.
"""

from __future__ import annotations

MODEL_VERSION = "1.0.0"
