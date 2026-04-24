#!/usr/bin/env python3
"""Monthly refit of dynamic source weights (Phase 10 upgrade item #2).

Loads historical source ranks + realized fantasy points, computes
Spearman + top-K hit rate per source, smooths with 4-week EMA against
the prior weights file, and either writes the new weights (auto-
approved, drift <15%) or prints the proposal + exits non-zero (pending
approval) so the cron caller can open a PR instead of committing.

Usage
-----
    python3 scripts/refit_source_weights.py [--force] [--alpha 0.25] [--tolerance 0.15]

Flags
-----
    --force       Skip the approval gate — overwrite weights no matter the drift.
                  Use sparingly (mid-season source shutdown, etc.).
    --alpha       EMA smoothing factor (default 0.25 = 75% prior / 25% new).
    --tolerance   Drift threshold that triggers pending_approval (default 0.15).

Inputs (looked up by path)
---------------------------
    data/source_rank_history.jsonl   per-source rank history
    data/realized_points_history.jsonl   per-player realized totals
    config/weights/dynasty.json      prior weights (seed on first run)

Outputs
-------
    config/weights/dynamic_source_weights.json   proposed/final weights
    STDOUT                            human-readable summary

Exit codes
----------
    0  auto-approved + weights written
    1  pending approval (no write), caller should open a PR
    2  fatal error (bad inputs, etc.)
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.backtesting.correlation import SourceAccuracy, score_all_sources
from src.backtesting.dynamic_weights import (
    load_prior_weights,
    propose_weights,
    save_weights,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
_LOGGER = logging.getLogger(__name__)


def _load_source_ranks(path: Path) -> dict[str, dict[str, int]]:
    """Return ``{source: {player_id: rank}}`` from a JSONL file.

    Each JSONL line: ``{"source": "ktc", "player_id": "4017", "rank": 12}``.
    Only the most-recent rank per (source, player_id) is kept.
    """
    out: dict[str, dict[str, int]] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except Exception:  # noqa: BLE001
            continue
        src = str(row.get("source") or "")
        pid = str(row.get("player_id") or "")
        try:
            rank = int(row.get("rank"))
        except (TypeError, ValueError):
            continue
        if not src or not pid:
            continue
        out.setdefault(src, {})[pid] = rank
    return out


def _load_realized(path: Path) -> dict[str, float]:
    """Return ``{player_id: total_fantasy_points}``.

    JSONL shape: ``{"player_id": "4017", "total_points": 312.4}``.
    Multiple rows per player sum.
    """
    out: dict[str, float] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except Exception:  # noqa: BLE001
            continue
        pid = str(row.get("player_id") or "")
        try:
            pts = float(row.get("total_points") or 0)
        except (TypeError, ValueError):
            continue
        if not pid:
            continue
        out[pid] = out.get(pid, 0.0) + pts
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--alpha", type=float, default=0.25)
    parser.add_argument("--tolerance", type=float, default=0.15)
    parser.add_argument(
        "--source-ranks-path", type=Path,
        default=Path("data/source_rank_history.jsonl"),
    )
    parser.add_argument(
        "--realized-path", type=Path,
        default=Path("data/realized_points_history.jsonl"),
    )
    parser.add_argument(
        "--weights-out", type=Path,
        default=Path("config/weights/dynamic_source_weights.json"),
    )
    args = parser.parse_args(argv)

    source_ranks = _load_source_ranks(args.source_ranks_path)
    realized = _load_realized(args.realized_path)

    if not source_ranks or not realized:
        _LOGGER.error(
            "refit inputs missing: source_ranks=%d, realized=%d",
            len(source_ranks), len(realized),
        )
        return 2

    accuracies = score_all_sources(source_ranks, realized)
    _LOGGER.info("scored %d sources", len(accuracies))
    for a in accuracies:
        _LOGGER.info(
            "  %s: rho=%.3f n=%d top50_hit=%.3f",
            a.source, a.spearman_rho, a.n_players, a.top_50_hit_rate,
        )

    prior = load_prior_weights(args.weights_out)
    proposal = propose_weights(
        accuracies, prior, alpha=args.alpha, tolerance_pct=args.tolerance,
    )
    _LOGGER.info("proposal status=%s max_drift=%.2f%%",
                 proposal.status, proposal.max_drift_pct * 100)
    for src, w in sorted(proposal.weights.items()):
        _LOGGER.info("  %s: %.4f", src, w)

    if proposal.status == "pending_approval" and not args.force:
        _LOGGER.warning(
            "drift exceeds %.1f%% — NOT writing.  Open a PR or re-run with --force.",
            args.tolerance * 100,
        )
        return 1

    meta = {
        "refit_at": datetime.now(timezone.utc).isoformat(),
        "alpha": args.alpha,
        "tolerance_pct": args.tolerance,
        "status": proposal.status,
        "max_drift_pct": proposal.max_drift_pct,
        "n_sources": len(proposal.weights),
    }
    saved = save_weights(proposal.weights, path=args.weights_out, meta=meta)
    _LOGGER.info("wrote weights → %s", saved)
    return 0


if __name__ == "__main__":
    sys.exit(main())
