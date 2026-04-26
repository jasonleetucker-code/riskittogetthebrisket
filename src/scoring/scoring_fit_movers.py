"""Compute scoring-fit movers — players whose ``idpScoringFitDelta``
moved most since a prior snapshot.

The daily snapshot capture (``scripts/capture_idp_fit_snapshot.py``)
writes ``data/idp_fit_snapshots/{YYYY-MM-DD}.json`` once per UTC day.
This module diffs the latest live contract against the most recent
snapshot to surface "lens noticed something changed" moments:

* A player whose delta jumped +2400 since last week — possibly a
  recent breakout the consensus market hasn't priced in yet.
* A player whose delta cratered — late-season decline the lens
  caught before the consensus did.

Output feeds the existing movers widget on /league.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

_LOGGER = logging.getLogger(__name__)


def _snapshot_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "data" / "idp_fit_snapshots"


def find_latest_snapshot(*, before: str | None = None) -> dict[str, Any] | None:
    """Return the most recent snapshot, optionally filtering to those
    captured before a given ``YYYY-MM-DD`` cutoff.

    Returns ``None`` when the directory is empty or the read fails.
    Used by ``compute_movers`` to find the comparison baseline.
    """
    snap_dir = _snapshot_dir()
    if not snap_dir.exists():
        return None
    files = sorted(snap_dir.glob("*.json"))
    if before:
        files = [f for f in files if f.stem < before]
    if not files:
        return None
    try:
        return json.loads(files[-1].read_text())
    except Exception as exc:  # noqa: BLE001
        _LOGGER.warning("scoring_fit_movers=read_failed file=%s err=%r", files[-1], exc)
        return None


def compute_movers(
    contract: dict[str, Any],
    *,
    snapshot: dict[str, Any] | None = None,
    min_change: float = 750.0,
    top_n: int = 10,
) -> dict[str, Any]:
    """Return top movers in ``idpScoringFitDelta`` since ``snapshot``.

    Each mover entry: ``{name, position, prior_delta, current_delta,
    change, consensus, tier, confidence, synthetic}``.

    Sorted by ``abs(change)`` descending — the largest jumps in
    either direction surface first.

    ``min_change`` filters out trivial movement (the lens recomputes
    every refresh; small wobbles are noise).  Default 750 = roughly
    half the BUY/SELL signal threshold.

    Returns ``{has_baseline: bool, baseline_date: str | None,
    risers: [...], fallers: [...]}``.
    """
    if snapshot is None:
        snapshot = find_latest_snapshot()
    if not isinstance(snapshot, dict):
        return {"has_baseline": False, "baseline_date": None, "risers": [], "fallers": []}

    # Index the snapshot by name (snapshot file uses ``name`` not
    # ``displayName``).  Skip entries without a usable delta.
    prior_by_name: dict[str, float] = {}
    for p in snapshot.get("players") or []:
        nm = str(p.get("name") or "").strip()
        d = p.get("delta")
        if nm and isinstance(d, (int, float)):
            prior_by_name[nm] = float(d)

    if not prior_by_name:
        return {"has_baseline": False, "baseline_date": None, "risers": [], "fallers": []}

    # Walk the live contract's IDP rows, compare to the snapshot.
    risers: list[dict[str, Any]] = []
    fallers: list[dict[str, Any]] = []
    arr = contract.get("playersArray") or []
    for row in arr:
        if not isinstance(row, dict):
            continue
        pos = str(row.get("position") or "").upper()
        if pos not in {"DL", "DT", "DE", "EDGE", "NT", "LB", "ILB", "OLB",
                       "MLB", "DB", "CB", "S", "FS", "SS"}:
            continue
        cur = row.get("idpScoringFitDelta")
        if not isinstance(cur, (int, float)):
            continue
        name = str(row.get("displayName") or row.get("canonicalName") or "").strip()
        prior = prior_by_name.get(name)
        if prior is None:
            continue  # not in baseline — no comparison possible
        change = float(cur) - prior
        if abs(change) < min_change:
            continue
        entry = {
            "name": name,
            "position": pos,
            "prior_delta": round(prior, 1),
            "current_delta": round(float(cur), 1),
            "change": round(change, 1),
            "consensus": int(row.get("rankDerivedValue") or 0),
            "tier": row.get("idpScoringFitTier"),
            "confidence": row.get("idpScoringFitConfidence"),
            "synthetic": bool(row.get("idpScoringFitSynthetic")),
        }
        if change > 0:
            risers.append(entry)
        else:
            fallers.append(entry)

    risers.sort(key=lambda e: -e["change"])
    fallers.sort(key=lambda e: e["change"])

    captured_at = snapshot.get("captured_at")
    baseline_date = None
    if isinstance(captured_at, str):
        try:
            baseline_date = datetime.fromisoformat(
                captured_at.replace("Z", "+00:00")
            ).strftime("%Y-%m-%d")
        except ValueError:
            baseline_date = captured_at[:10] if len(captured_at) >= 10 else None

    return {
        "has_baseline": True,
        "baseline_date": baseline_date,
        "risers": risers[:top_n],
        "fallers": fallers[:top_n],
    }
