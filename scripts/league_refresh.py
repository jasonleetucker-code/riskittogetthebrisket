#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
import sys

# Ensure repo root is on sys.path for shared imports
_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))


def _bootstrap_path(repo: Path) -> None:
    if str(repo) not in sys.path:
        sys.path.insert(0, str(repo))


from scripts._shared import _latest


def main() -> int:
    parser = argparse.ArgumentParser(description="Phase-1 league refresh scaffold")
    parser.add_argument("--repo", default=".", help="Repo root")
    args = parser.parse_args()

    print("[league_refresh] WARNING: This is a scaffold. "
          "Output contains only pass-through canonical counts.")

    repo = Path(args.repo).resolve()
    _bootstrap_path(repo)

    from src.utils import load_json, save_json

    canonical_dir = repo / "data" / "canonical"
    canonical_file = _latest(canonical_dir, "canonical_snapshot_*.json")
    if canonical_file is None:
        print("[league_refresh] No canonical snapshot found. Run canonical_build first.")
        return 0

    league_cfg_path = repo / "config" / "leagues" / "default_superflex_idp.template.json"
    league_cfg = load_json(league_cfg_path, default={}) or {}
    canonical = load_json(canonical_file, default={}) or {}

    now = datetime.now(timezone.utc)
    run_id = now.strftime("%Y%m%dT%H%M%SZ")
    out_dir = repo / "data" / "league"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"league_snapshot_{run_id}.json"

    payload = {
        "run_id": run_id,
        "created_at": now.isoformat(),
        "input_canonical_snapshot": canonical_file.name,
        "league_profile": league_cfg.get("league_name", "unknown"),
        "note": "Scaffold output only. Full league adjustment math remains in legacy pipeline for now.",
        "asset_count": canonical.get("asset_count", 0),
    }
    save_json(out_file, payload)
    print(f"[league_refresh] wrote {out_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

