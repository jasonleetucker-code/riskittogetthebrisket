#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
import sys


def _bootstrap_path(repo: Path) -> None:
    if str(repo) not in sys.path:
        sys.path.insert(0, str(repo))


def _latest(path: Path, pattern: str) -> Path | None:
    files = sorted(path.glob(pattern), reverse=True)
    return files[0] if files else None


def main() -> int:
    parser = argparse.ArgumentParser(description="Phase-1 reporting scaffold")
    parser.add_argument("--repo", default=".", help="Repo root")
    args = parser.parse_args()

    repo = Path(args.repo).resolve()
    _bootstrap_path(repo)

    from src.utils import load_json

    raw_file = _latest(repo / "data" / "raw_sources", "raw_source_snapshot_*.json")
    canon_file = _latest(repo / "data" / "canonical", "canonical_snapshot_*.json")
    league_file = _latest(repo / "data" / "league", "league_snapshot_*.json")

    raw = load_json(raw_file, default={}) if raw_file else {}
    canon = load_json(canon_file, default={}) if canon_file else {}
    league = load_json(league_file, default={}) if league_file else {}

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = repo / "data" / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"ops_report_{stamp}.md"

    lines = [
        "# Canonical Pipeline Ops Report",
        "",
        f"- Generated (UTC): {datetime.now(timezone.utc).isoformat()}",
        f"- Raw snapshot: {raw_file.name if raw_file else 'missing'}",
        f"- Canonical snapshot: {canon_file.name if canon_file else 'missing'}",
        f"- League snapshot: {league_file.name if league_file else 'missing'}",
        "",
        "## Counts",
        f"- Raw sources: {len(raw.get('snapshots', [])) if isinstance(raw, dict) else 0}",
        f"- Canonical assets: {canon.get('asset_count', 0) if isinstance(canon, dict) else 0}",
        f"- League assets: {league.get('asset_count', 0) if isinstance(league, dict) else 0}",
    ]
    out_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[reporting] wrote {out_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

