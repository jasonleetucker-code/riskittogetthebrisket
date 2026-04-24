#!/usr/bin/env python3
"""Monthly refit of Cohen's-d tier thresholds (upgrade item #2).

Fits per-position thresholds from the live canonical contract.
If drift exceeds ``--tolerance`` (default 15%), exits non-zero
without writing — caller should open a PR.

Usage
-----
    python3 scripts/refit_tier_thresholds.py [--force] [--tolerance 0.15]

Inputs
------
    data/latest_contract.json  latest canonical contract export
OR  fetched from the running server at FRONTEND_URL/api/data (requires auth)

Output
------
    config/tiers/thresholds.json  updated per-position thresholds

Exit codes
----------
    0  auto-approved and written
    1  drift exceeds tolerance — caller opens a PR
    2  fatal (no contract available)
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.scoring.tiering import (
    fit_thresholds_grid_search,
    load_thresholds,
    detect_threshold_drift,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
_LOGGER = logging.getLogger(__name__)


def _load_contract_players(path: Path) -> list[dict[str, Any]]:
    """Return the playersArray (or its legacy-dict equivalent) from
    a contract JSON dump."""
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        _LOGGER.error("failed to load contract %s: %s", path, exc)
        return []
    arr = data.get("playersArray")
    if isinstance(arr, list) and arr:
        return [
            {
                "name": str(p.get("displayName") or p.get("canonicalName") or ""),
                "pos": str(p.get("position") or ""),
                "rankDerivedValue": p.get("rankDerivedValue"),
            }
            for p in arr if isinstance(p, dict)
        ]
    # Legacy dict shape — derive pos from asset stamps.
    players = data.get("players") or {}
    out = []
    for name, row in players.items():
        if not isinstance(row, dict):
            continue
        out.append({
            "name": name,
            "pos": str(row.get("position") or ""),
            "rankDerivedValue": row.get("rankDerivedValue"),
        })
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--tolerance", type=float, default=0.15)
    parser.add_argument(
        "--contract-path", type=Path,
        default=Path("data/latest_contract.json"),
    )
    parser.add_argument(
        "--thresholds-out", type=Path,
        default=Path("config/tiers/thresholds.json"),
    )
    args = parser.parse_args(argv)

    rows = _load_contract_players(args.contract_path)
    if not rows:
        _LOGGER.error(
            "no players loaded from %s — ensure contract is exported",
            args.contract_path,
        )
        return 2

    new_thresholds = fit_thresholds_grid_search(rows)
    old_thresholds = load_thresholds(args.thresholds_out)
    drift = detect_threshold_drift(
        old_thresholds, new_thresholds, tolerance_pct=args.tolerance,
    )
    _LOGGER.info(
        "fit complete: %d positions, max_drift=%.2f%%, hasDrift=%s",
        len(new_thresholds), drift["maxDriftPct"] * 100, drift["hasDrift"],
    )
    for pos, new_t in sorted(new_thresholds.items()):
        old_t = old_thresholds.get(pos, 0.0)
        pct = (new_t - old_t) / old_t * 100 if old_t else 0.0
        _LOGGER.info("  %s: %.3f → %.3f (%+.1f%%)", pos, old_t, new_t, pct)

    if drift["hasDrift"] and not args.force:
        _LOGGER.warning(
            "drift > %.1f%% — NOT writing.  Open a PR or re-run with --force.",
            args.tolerance * 100,
        )
        return 1

    args.thresholds_out.parent.mkdir(parents=True, exist_ok=True)
    body = {
        "_comment": "Refit by scripts/refit_tier_thresholds.py",
        "_refit_at": datetime.now(timezone.utc).isoformat(),
        "_max_drift_pct": drift["maxDriftPct"],
        "thresholds": new_thresholds,
    }
    tmp = args.thresholds_out.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(body, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(args.thresholds_out)
    _LOGGER.info("wrote thresholds → %s", args.thresholds_out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
