"""Master-site-audit W12-F003 regression (CW-40 P1 re-adjudication, 2026-11-06) -- PARTIAL.

August claim: no central Buy/Sell tracker; 16 emitters; five cutoffs on one quantity;
the two candidate arbiters were one flag-off and one caller-less.

What is closed and pinned here (offline, source-shape only):

* the caller-less arbiter ``src/news/unified_signal_engine.py`` is gone and nothing
  imports it;
* ``src/signals/reconciler.py`` (C6-SIG-01) exists, is pure, and is served by
  ``GET /api/signals/reconciled``.

What stays open (documented, not pinned as a defect): the reconciler is dedup + lineage
only by owner design -- there is still no single Buy/Sell verdict or tracker page, the
``consensus_edge`` flag is still default OFF (ADR-023; pinned below so a flip is a
deliberate edit), and ``docs/EXECUTION_PLAN.md`` keeps "central Buy/Sell reconciliation
post-V1".  The threshold half (five cutoffs -> two) is pinned in
``frontend/__tests__/audit-w12-f003-regression.test.js``.
"""

from __future__ import annotations

import re
from pathlib import Path

from src.api import feature_flags

REPO = Path(__file__).resolve().parents[2]


def _read(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


def test_the_caller_less_arbiter_is_deleted_and_nothing_imports_it():
    assert not (REPO / "src/news/unified_signal_engine.py").exists()
    pat = re.compile(r"^\s*(from|import)\s+[\w.]*unified_signal_engine", re.M)
    offenders = []
    for root in ("src", "scripts"):
        for p in (REPO / root).rglob("*.py"):
            if pat.search(p.read_text(encoding="utf-8")):
                offenders.append(str(p.relative_to(REPO)))
    assert offenders == []
    assert not pat.search(_read("server.py"))


def test_reconciler_exists_and_is_routed():
    assert "RECONCILER_VERSION" in _read("src/signals/reconciler.py")
    assert '@app.get("/api/signals/reconciled")' in _read("server.py")


def test_consensus_edge_flag_is_still_default_off():
    # Documents the residual half of the finding; flips only by a deliberate owner edit.
    assert feature_flags._DEFAULTS["consensus_edge"] is False
