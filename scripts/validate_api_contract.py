from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate /api/data contract against latest payload."
    )
    parser.add_argument("--repo", default=".", help="Repository root (default: current directory)")
    parser.add_argument(
        "--lane",
        choices=("full", "structural"),
        default="full",
        help=(
            "Which failures are fatal. 'full' (default, deploy gate): any contract error, "
            "including external source-health conditions such as a timed-out KTC scrape. "
            "'structural' (pull-request gate): only errors that are statements about THIS "
            "repository's code given whatever payload arrived — schema, rank invariants, the "
            "1..9999 scale, blend integrity, the pick-completeness census. Source-health "
            "conditions are still printed, loudly, and still fail the 'full' lane."
        ),
    )
    args = parser.parse_args()
    args.repo = Path(args.repo).resolve()
    return args


def _load_latest_payload(repo_root: Path) -> tuple[dict, Path]:
    candidates: list[Path] = []
    # ``exports/latest`` FIRST and by name, because it is the only payload
    # the repository actually tracks.  Until 2026-08-16 this function looked
    # only in ``repo/data`` and the repo root — both of which are gitignored
    # for this artifact — so every CI invocation printed "No sample data;
    # skipping" and the gate had never once run.  A gate that cannot find its
    # input reads exactly like a gate that passed.
    for folder in (repo_root / "exports" / "latest", repo_root / "data", repo_root):
        if not folder.exists():
            continue
        candidates.extend(sorted(folder.glob("dynasty_data_*.json")))
    if not candidates:
        raise FileNotFoundError(
            "No dynasty_data_YYYY-MM-DD.json files found in exports/latest, repo/data "
            "or repo root."
        )
    latest = sorted(candidates, key=lambda p: p.stat().st_mtime, reverse=True)[0]
    with latest.open("r", encoding="utf-8") as f:
        payload = json.load(f)
    return payload, latest


def main() -> int:
    args = _parse_args()
    repo_root = args.repo
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

    source_health = list(report.get("sourceHealthErrors") or [])
    structural = list(report.get("structuralErrors") or [])

    print(f"[contract] source={source_file}")
    print(f"[contract] lane={args.lane}")
    print(
        f"[contract] ok={report.get('ok')} errors={report.get('errorCount')} "
        f"warnings={report.get('warningCount')} players={report.get('playerCount')}"
    )
    print(f"[contract] structuralErrors={len(structural)} sourceHealthErrors={len(source_health)}")
    if report.get("warnings"):
        for msg in report["warnings"][:8]:
            print(f"[contract][warn] {msg}")

    # Source-health conditions are ALWAYS printed as GitHub warnings, in
    # both lanes.  The structural lane declines to *fail* on them; it never
    # declines to say them.  Losing the signal was never the goal.
    for msg in source_health[:20]:
        print(f"::warning title=Source health::{msg}")
        print(f"[contract][source-health] {msg}")
    for msg in structural[:20]:
        print(f"[contract][error] {msg}")

    fatal = structural if args.lane == "structural" else (structural + source_health)
    if fatal:
        print(f"[contract] validation output: {out_path}")
        return 1

    if source_health:
        print(
            "[contract] structural lane PASSED; "
            f"{len(source_health)} source-health condition(s) remain open (see warnings)."
        )
    print(f"[contract] validation output: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
