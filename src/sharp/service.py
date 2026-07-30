"""Sharp Tracker cohort status and board assembly.

Reads the SHARED transaction ledger (``src.intel.ledger``) but keeps a
completely separate cohort and question from Insider Trading — see
``src/sharp/__init__.py`` for the split.

Stage boundary: the discovery graph that populates the cohort
(outward traversal from every observed league) lands in a later stage.
Until it runs, :func:`cohort_status` reports the real, honest coverage
numbers and a ``cohort_building`` status.  It never fabricates a
cohort, and it never falls back to the league-mate pool — doing so
would silently re-merge the two products, which is the exact defect
this work exists to undo.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from src.intel import ledger
from src.sharp import discovery, records
from src.sharp import score as sharp_score

log = logging.getLogger(__name__)

STATUS_OK = "ok"
STATUS_BUILDING = "cohort_building"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_manager_records() -> list[sharp_score.ManagerRecord]:
    """Manager records for scoring, from the season-records crawl.

    Built ONLY from completed, sharp-eligible seasons — see
    ``records.build_manager_records``.  It deliberately does not
    synthesise records from transaction rows: the eligibility gates need
    completed-season history (W/L, playoff results, championships) that
    transactions do not contain, and scoring on partial inputs would
    qualify people on the wrong evidence.

    Empty until the records crawl has run, which is the honest
    ``cohort_building`` state rather than a fabricated cohort.
    """
    try:
        return records.build_manager_records()
    except Exception:  # noqa: BLE001 — status must not 500
        log.exception("sharp: manager records unavailable")
        return []


def _records_coverage() -> dict[str, Any]:
    try:
        return records.records_coverage()
    except Exception:  # noqa: BLE001
        log.exception("sharp: records coverage failed")
        return {}


def cohort_status() -> dict[str, Any]:
    """What we observe, what we can evaluate, and what qualifies.

    The four tiers are always reported separately, so "we have not
    built the cohort yet" can never be confused with "no managers
    qualified".
    """
    try:
        coverage = ledger.coverage()
    except Exception:  # noqa: BLE001 — status must not 500
        log.exception("sharp: ledger coverage failed")
        coverage = {}

    # Graph stats are the honest "observable" tier: every manager the
    # discovery spiderweb has reached, which is strictly larger than the
    # set with transactions in the ledger.
    try:
        graph = discovery.graph_stats()
    except Exception:  # noqa: BLE001 — status must not 500
        log.exception("sharp: graph stats failed")
        graph = {}

    manager_records = load_manager_records()
    scored = sharp_score.score_managers(manager_records) if manager_records else []
    tiers = (
        sharp_score.cohort_tiers(scored)
        if scored
        else {
            "observableManagers": graph.get("observedUsers", coverage.get("managerCount", 0)),
            "evaluableManagers": 0,
            "qualifiedManagers": 0,
            "uncertainManagers": 0,
        }
    )
    if scored:
        # OBSERVABLE means every manager the discovery graph has reached
        # — not merely those we have records for.  cohort_tiers can only
        # count what it was handed, so it reports the scoreable subset
        # and would understate the population by ~4x.  The gap between
        # observable and scoreable IS the coverage story, so it is
        # reported rather than flattened.
        observable = graph.get("observedUsers") or 0
        scoreable = tiers["observableManagers"]
        tiers["observableManagers"] = max(observable, scoreable)
        tiers["managersWithRecords"] = scoreable
        total = tiers["observableManagers"]
        tiers["qualifiedShareOfObservable"] = (
            round(tiers["qualifiedManagers"] / total, 4) if total else None
        )

    status = STATUS_OK if tiers.get("qualifiedManagers", 0) > 0 else STATUS_BUILDING
    return {
        "status": status,
        "methodologyVersion": sharp_score.methodology_version(),
        "generatedAt": _utc_now_iso(),
        "cohort": {
            **tiers,
            "observedLeagues": graph.get("observedLeagues", coverage.get("leagueCount", 0)),
            # Signal-eligible is reported separately from observed:
            # redraft and best-ball leagues are traversed for the
            # managers they introduce but never counted in the dynasty
            # signal, so the two numbers legitimately differ.
            "signalEligibleLeagues": graph.get("signalEligibleLeagues", 0),
            "discoveryOnlyLeagues": graph.get("discoveryOnlyLeagues", 0),
            "observedTransactions": coverage.get("transactionCount", 0),
        },
        "graph": graph,
        "records": _records_coverage(),
        "coverage": coverage,
        "note": (
            "Sleeper publishes no global directory of users or leagues, so this "
            "cohort can only grow outward from leagues we already observe. These "
            "counts describe our observable subset, never all of Sleeper."
        ),
    }
