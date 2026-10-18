"""The native run log for served trade decisions (TC-C decision receipts).

``POST /api/trade/analyze`` appends one line per served decision here, at serve
time, best effort -- exactly the arrangement Best Offers uses
(``src/trade/best_offers.py::record_run``).  The AL-P5 learning layer then READS
this log (``scripts/trade_decision_receipts.py``) and records one DECISION
receipt per line through ``src/model_registry/producer_receipts.py``.  There is
no second receipt system: the same receipt contract, store and recorder.

The line records what was decided and on what (headline, leaning, strategy,
missing-evidence codes, the decision's own receipt: request hash, bands,
package model, board stamp, scoring fingerprint).  It names no asset; the
learning receipt copies none of it either -- it points at the line.

The log is box-local and gitignored like the rest of ``data/``.  Writing it is
the only side effect of a served decision, and the decision never depends on
it: a failure returns ``None`` and the response is unchanged.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping

from src.trade import best_offers as _best_offers

DECISION_RUN_LOG_VERSION = "trade_decision_log_v1"
DECISION_RUN_LOG_DIR = Path(__file__).resolve().parents[2] / "data" / "trade" / "decisions"
#: Override for tests and operators (read at call time, like the other
#: box-local evidence logs).
LOG_DIR_ENV = "RISKIT_TRADE_DECISION_LOG_DIR"


def _default_dir() -> Path:
    override = os.environ.get(LOG_DIR_ENV)
    return Path(override) if override else DECISION_RUN_LOG_DIR


def record_decision(
    analysis: Mapping[str, Any],
    *,
    league_key: str | None,
    team: str | None,
    log_dir: Path | None = None,
) -> str | None:
    """Append one served decision; returns its run id, or ``None``.

    Best effort by contract: a decision never fails because its record could
    not be written.  ``recordedAt`` is stamped after the decision was built.
    """
    try:
        decision = analysis.get("decision") or {}
        receipt = decision.get("receipt") or {}
        strategy = decision.get("strategy") or {}
        now = datetime.now(timezone.utc)
        body = {
            "version": DECISION_RUN_LOG_VERSION,
            "recordedAt": now.isoformat(),
            "leagueKey": league_key,
            "team": team,
            "packetVersion": analysis.get("version"),
            "decisionVersion": decision.get("version"),
            "headline": decision.get("headline"),
            "leaning": decision.get("leaning"),
            "deciding": decision.get("deciding"),
            "confidenceLevel": (decision.get("confidence") or {}).get("level"),
            "missingEvidence": [g.get("code") for g in decision.get("missingEvidence") or []],
            "strategy": {
                "used": strategy.get("used"),
                "source": strategy.get("source"),
                "requested": strategy.get("requested"),
            },
            "teamContext": analysis.get("teamContext"),
            "receipt": dict(receipt),
        }
        line = json.dumps(body, sort_keys=True, default=str)
        run_id = hashlib.sha256(line.encode("utf-8")).hexdigest()[:20]
        body["runId"] = run_id
        target = log_dir or _default_dir()
        target.mkdir(parents=True, exist_ok=True)
        with (target / f"runs-{now:%Y-%m}.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(body, sort_keys=True, default=str) + "\n")
        return run_id
    except Exception:  # noqa: BLE001 -- never fail a decision on its record
        return None


def iter_decision_log_lines(
    log_dir: Path | None = None,
) -> Iterator[tuple[str, Mapping[str, Any] | None]]:
    """``(file name, parsed line | None)`` for every complete line -- the same
    reader (and the same torn-line rule) as the Best Offers run log."""
    yield from _best_offers.iter_run_log_lines(log_dir or _default_dir())
