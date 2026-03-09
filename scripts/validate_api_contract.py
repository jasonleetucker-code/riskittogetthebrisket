from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


def _repo_root_from_args() -> Path:
    parser = argparse.ArgumentParser(description="Validate /api/data contract against latest payload.")
    parser.add_argument("--repo", default=".", help="Repository root (default: current directory)")
    args = parser.parse_args()
    return Path(args.repo).resolve()


def _load_latest_payload(repo_root: Path) -> tuple[dict, Path]:
    candidates: list[Path] = []
    for folder in (repo_root / "data", repo_root):
        if not folder.exists():
            continue
        candidates.extend(sorted(folder.glob("dynasty_data_*.json")))
    if not candidates:
        raise FileNotFoundError("No dynasty_data_YYYY-MM-DD.json files found in repo/data or repo root.")
    latest = sorted(candidates, key=lambda p: p.stat().st_mtime, reverse=True)[0]
    with latest.open("r", encoding="utf-8") as f:
        payload = json.load(f)
    return payload, latest


def main() -> int:
    repo_root = _repo_root_from_args()
    sys.path.insert(0, str(repo_root))

    from src.api.data_contract import (  # noqa: WPS433 - intentional runtime import from repo root
        CONTRACT_VERSION,
        build_api_data_contract,
        validate_api_data_contract,
    )

    payload, source_file = _load_latest_payload(repo_root)
    contract_payload = build_api_data_contract(
        payload,
        data_source={
            "type": "ci_file",
            "path": str(source_file),
            "loadedAt": datetime.now(timezone.utc).isoformat(),
        },
    )
    report = validate_api_data_contract(contract_payload)

    validation_dir = repo_root / "data" / "validation"
    validation_dir.mkdir(parents=True, exist_ok=True)
    out_path = validation_dir / "api_contract_validation_latest.json"
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(
            {
                "contractVersion": CONTRACT_VERSION,
                "sourceFile": str(source_file),
                "checkedAt": datetime.now(timezone.utc).isoformat(),
                "report": report,
            },
            f,
            ensure_ascii=False,
            indent=2,
        )

    print(f"[contract] source={source_file}")
    print(
        f"[contract] ok={report.get('ok')} errors={report.get('errorCount')} "
        f"warnings={report.get('warningCount')} players={report.get('playerCount')}"
    )
    if report.get("warnings"):
        for msg in report["warnings"][:8]:
            print(f"[contract][warn] {msg}")

    if not report.get("ok"):
        for msg in report.get("errors", [])[:20]:
            print(f"[contract][error] {msg}")
        print(f"[contract] validation output: {out_path}")
        return 1

    print(f"[contract] validation output: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

