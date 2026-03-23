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
    parser = argparse.ArgumentParser(description="Phase-1 reporting scaffold")
    parser.add_argument("--repo", default=".", help="Repo root")
    args = parser.parse_args()

    repo = Path(args.repo).resolve()
    _bootstrap_path(repo)

    from src.utils import load_json

    raw_file = _latest(repo / "data" / "raw_sources", "raw_source_snapshot_*.json")
    ingest_validation_file = _latest(repo / "data" / "validation", "ingest_validation_*.json")
    identity_file = _latest(repo / "data" / "identity", "identity_resolution_*.json")
    if identity_file is None:
        identity_file = _latest(repo / "data" / "identity", "identity_report_*.json")
    canonical_validation_file = _latest(repo / "data" / "validation", "canonical_validation_*.json")
    canon_file = _latest(repo / "data" / "canonical", "canonical_snapshot_*.json")
    league_file = _latest(repo / "data" / "league", "league_snapshot_*.json")

    raw = load_json(raw_file, default={}) if raw_file else {}
    ingest_validation = load_json(ingest_validation_file, default={}) if ingest_validation_file else {}
    identity = load_json(identity_file, default={}) if identity_file else {}
    canonical_validation = load_json(canonical_validation_file, default={}) if canonical_validation_file else {}
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
        f"- Ingest validation: {ingest_validation_file.name if ingest_validation_file else 'missing'}",
        f"- Identity report: {identity_file.name if identity_file else 'missing'}",
        f"- Canonical snapshot: {canon_file.name if canon_file else 'missing'}",
        f"- Canonical validation: {canonical_validation_file.name if canonical_validation_file else 'missing'}",
        f"- League snapshot: {league_file.name if league_file else 'missing'}",
        "",
        "## Counts",
        f"- Raw sources: {len(raw.get('snapshots', [])) if isinstance(raw, dict) else 0}",
        f"- Ingest status: {ingest_validation.get('status', 'missing') if isinstance(ingest_validation, dict) else 'missing'}",
        f"- Identity unresolved: {identity.get('unresolved_count', 0) if isinstance(identity, dict) else 0}",
        f"- Identity low confidence: {identity.get('low_confidence_count', 0) if isinstance(identity, dict) else 0}",
        f"- Duplicate aliases: {identity.get('duplicate_alias_count', 0) if isinstance(identity, dict) else 0}",
        f"- Canonical assets: {canon.get('asset_count', 0) if isinstance(canon, dict) else 0}",
        f"- Suspicious jumps: {canonical_validation.get('suspicious_jump_count', 0) if isinstance(canonical_validation, dict) else 0}",
        f"- Rookie universe warnings: {canonical_validation.get('rookie_universe_warning_count', 0) if isinstance(canonical_validation, dict) else 0}",
        f"- League assets: {league.get('asset_count', 0) if isinstance(league, dict) else 0}",
    ]
    out_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[reporting] wrote {out_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
