"""Provenance labelling for historical records.

``pipeline_version`` moved here verbatim from
``src/snapshots/board_store.py`` when the temporal ledger became the
canonical owner of history provenance (C1-U4).  It is a PURE function
of a contract — it reads no store — so housing it here lets the live
recorder label its rows without ``src/history`` importing the
board-history store, whose no-decision-path-reads charter is
structurally pinned (``tests/snapshots/test_board_store.py``).
``board_store`` now imports it from here, so there is still exactly
one implementation.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any


def pipeline_version(contract: dict[str, Any]) -> str:
    """Identify the pipeline that produced a board, for a row KEY.

    ``contractVersion`` alone is not enough.  It is the API SHAPE
    version (``2026-03-10.v2``) and it does not move when the maths
    move — a Hill-curve re-fit changes every IDP value on the board and
    leaves that string untouched.  Keying on it would file the
    pre-revaluation and post-revaluation boards for a date as the same
    claim and let the second overwrite the first, destroying the
    before/after the C6 batch exists to produce.

    So it is paired with a content hash of the constants that actually
    determine values — the routed Hill curves.  Same pattern as BDVM's
    content-hashed ``paramSetId`` over ``params_v1.json``, for the same
    reason: a version that cannot change is not a version.

    Scoped to the four known scope-curve keys ONLY (V1-21 / W04-F011):
    ``hillCurves`` also carries a ``provenance`` sub-block (which model
    version PRODUCED these constants — descriptive metadata, not a
    value-determining constant itself).  Hashing it verbatim would make
    this identity move on a purely cosmetic registry correction (e.g.
    backfilling a champion's ``appliedAt``) with no curve constant
    changing at all — exactly the "a version that cannot change is not a
    version" failure this function exists to prevent, just aimed at the
    wrong input.  Any OTHER future non-curve key added to ``hillCurves``
    is excluded the same way, defensively, not just this one.

    Degrades to ``nohash`` rather than raising.  A recording job must
    not take the process down over its own labelling.
    """
    shape = str(contract.get("contractVersion") or contract.get("version") or "unknown")
    curves = contract.get("hillCurves")
    if not isinstance(curves, dict) or not curves:
        return f"{shape}+nohash"
    curve_keys = ("global", "offense", "idp", "rookie")
    value_determining = {k: curves[k] for k in curve_keys if k in curves}
    if not value_determining:
        return f"{shape}+nohash"
    try:
        blob = json.dumps(value_determining, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError):
        return f"{shape}+nohash"
    return f"{shape}+{hashlib.sha256(blob.encode('utf-8')).hexdigest()[:8]}"
