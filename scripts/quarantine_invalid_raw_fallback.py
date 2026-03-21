#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.api.raw_fallback_health import scan_raw_fallback_health


def _unique_destination(root: Path, relative_path: Path) -> Path:
    target = root / relative_path
    if not target.exists():
        return target
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return target.with_name(f"{target.stem}-{stamp}{target.suffix}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Inspect local dynasty raw fallback files and optionally quarantine invalid candidates.",
    )
    parser.add_argument(
        "--base-dir",
        default=str(Path(__file__).resolve().parents[1]),
        help="Repo root containing dynasty_data_*.json and dynasty_data.js",
    )
    parser.add_argument(
        "--data-dir",
        help="Optional data directory override (defaults to <base-dir>/data)",
    )
    parser.add_argument(
        "--quarantine-dir",
        help="Optional quarantine directory override (defaults to <data-dir>/quarantine/raw_fallback)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Move invalid fallback candidates into the quarantine directory. Dry-run by default.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the scan result as JSON.",
    )
    args = parser.parse_args()

    base_dir = Path(args.base_dir).resolve()
    data_dir = Path(args.data_dir).resolve() if args.data_dir else (base_dir / "data").resolve()
    quarantine_dir = (
        Path(args.quarantine_dir).resolve()
        if args.quarantine_dir
        else (data_dir / "quarantine" / "raw_fallback").resolve()
    )

    payload, skipped_paths = scan_raw_fallback_health(
        base_dir,
        data_dir,
        checked_at=datetime.now(timezone.utc).isoformat(),
    )

    result = {
        **payload,
        "mode": "apply" if args.apply else "dry-run",
        "quarantine_dir": str(quarantine_dir),
        "moved_files": [],
    }

    if args.apply and skipped_paths:
        for skipped_path in skipped_paths:
            try:
                relative_path = skipped_path.resolve().relative_to(base_dir.resolve())
            except Exception:
                relative_path = Path(skipped_path.name)
            destination = _unique_destination(quarantine_dir, relative_path)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(skipped_path), str(destination))
            result["moved_files"].append(
                {
                    "from": str(skipped_path),
                    "to": str(destination),
                }
            )

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=True))
        return 0

    print("# Raw Fallback Audit")
    print(f"- Status: {result['status']}")
    print(f"- Selected source: {result.get('selected_source') or 'none'}")
    print(f"- Skipped file count: {result.get('skipped_file_count')}")
    print(f"- Mode: {result['mode']}")
    if result["skipped_files"]:
        print("## Invalid candidates")
        for item in result["skipped_files"]:
            print(f"- {item.get('file')}: {item.get('reason')}")
    else:
        print("## Invalid candidates")
        print("- none")
    if result["moved_files"]:
        print("## Quarantined")
        for item in result["moved_files"]:
            print(f"- {item['from']} -> {item['to']}")
    elif args.apply:
        print("## Quarantined")
        print("- none")
    else:
        print(f"- Quarantine target: {quarantine_dir}")
        print("- Re-run with --apply to move invalid candidates there.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
