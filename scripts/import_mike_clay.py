#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


def _bootstrap_path(repo: Path) -> None:
    if str(repo) not in sys.path:
        sys.path.insert(0, str(repo))


def _latest_pdf(import_dir: Path) -> Path | None:
    files = sorted(import_dir.glob("*.pdf"), reverse=True)
    return files[0] if files else None


def main() -> int:
    parser = argparse.ArgumentParser(description="Import Mike Clay NFL Projection Guide PDF")
    parser.add_argument("--repo", default=".", help="Repo root")
    parser.add_argument(
        "--pdf",
        default="",
        help="Path to Mike Clay PDF. Defaults to latest data/imports/mike_clay/*.pdf",
    )
    parser.add_argument("--guide-year", type=int, default=None, help="Optional guide year override")
    parser.add_argument("--data-dir", default="", help="Optional data directory override")
    parser.add_argument("--output-dir", default="", help="Optional output directory override")
    parser.add_argument(
        "--manual-overrides",
        default="",
        help="Optional CSV override file with canonical player mappings",
    )
    parser.add_argument(
        "--dynasty-data",
        default="",
        help="Optional dynasty_data_*.json file for canonical player universe",
    )
    parser.add_argument("--no-csv", action="store_true", help="Skip CSV artifact generation")
    args = parser.parse_args()

    repo = Path(args.repo).resolve()
    _bootstrap_path(repo)
    from src.offseason.mike_clay import run_mike_clay_import

    pdf_path = Path(args.pdf).resolve() if args.pdf else None
    if pdf_path is None:
        default_import_dir = repo / "data" / "imports" / "mike_clay"
        pdf_path = _latest_pdf(default_import_dir)
    if pdf_path is None or not pdf_path.exists():
        print("[mike-clay] no PDF found. Use --pdf or place PDF in data/imports/mike_clay/")
        return 1

    result = run_mike_clay_import(
        pdf_path=pdf_path,
        data_dir=Path(args.data_dir).resolve() if args.data_dir else None,
        output_dir=Path(args.output_dir).resolve() if args.output_dir else None,
        guide_year_hint=args.guide_year,
        manual_match_overrides_path=Path(args.manual_overrides).resolve() if args.manual_overrides else None,
        dynasty_data_path=Path(args.dynasty_data).resolve() if args.dynasty_data else None,
        write_csv=not args.no_csv,
    )

    print(
        "[mike-clay] "
        f"status={result.get('status')} "
        f"guide_year={result.get('guide_year')} "
        f"players={result.get('counts', {}).get('normalized_players')} "
        f"unresolved={result.get('counts', {}).get('unmatched_count')} "
        f"low_conf={result.get('counts', {}).get('low_confidence_count')} "
        f"ready={result.get('ready_for_formula_integration')}"
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
