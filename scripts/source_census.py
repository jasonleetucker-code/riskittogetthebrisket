#!/usr/bin/env python3
"""Source trust census (Batch 3 Unit A) — CLI over ``src/sources/source_census.py``.

Builds the canonical contract from a pinned raw payload through the live
pipeline (``build_api_data_contract``), gathers the dataset-state, fetch-stamp,
CSV, git-history, export-archive and temporal-ledger evidence, and writes the
census as JSON plus a concise Markdown table.  Read-only toward every
canonical owner; changes nothing that decides a value.

Usage::

    python scripts/source_census.py                          # newest exports/latest payload
    python scripts/source_census.py --payload exports/latest/dynasty_data_2026-09-30.json \\
        --out-json docs/sources/census/CENSUS_2026-10-01.json \\
        --out-md docs/sources/census/CENSUS_2026-10-01.md
    python scripts/source_census.py --from-archive           # newest COMPLETE archived scrape

Exit codes: 0 census built and internally consistent; 1 census built but it
found an integrity problem (an UNCLASSIFIED source, a source with no lineage
entry, a lineage-registry error, or an effective-authority mismatch against the
pipeline's own summary); 2 no payload / build failure.
"""

from __future__ import annotations

import argparse
import glob
import hashlib
import json
import sys
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


def _latest_payload() -> Path | None:
    paths = sorted(glob.glob(str(REPO / "exports" / "latest" / "dynasty_data_*.json")))
    return Path(paths[-1]) if paths else None


def _archive_payload(tmp: Path) -> Path | None:
    from tests.archive_fixtures import newest_complete_raw_payload

    payload, name = newest_complete_raw_payload()
    if payload is None:
        return None
    out = tmp / f"{Path(str(name)).stem}.json"
    out.write_text(json.dumps(payload), encoding="utf-8")
    return out


def _signals_inputs(as_of: datetime) -> tuple[list[dict], dict]:
    from src.sources import signals
    from src.sources.dataset_state import load_state
    from src.sources.freshness import assess_source

    root = REPO / "data" / "sources" / "signals"
    store = signals.SignalsStore(root)
    boards, weightings = [], {}
    for spec in signals.BOARDS.values():
        bdir = root / spec.key
        state = load_state(bdir / "dataset_state.json")
        fstate = store.fetch_state(spec.key) if bdir.is_dir() else {}
        latest = store.latest(spec.key) if bdir.is_dir() else None
        success = [
            t
            for t in ((latest or {}).get("fetchedAt"), fstate.get("lastVerifiedUnchangedAt"))
            if isinstance(t, str) and t
        ]
        boards.append(
            {
                "sourceKey": spec.source_key,
                "displayName": f"Signals Fantasy {spec.key} (public board)",
                "positions": list(spec.positions),
                "metadata": signals.dataset_metadata(spec),
                "fetchState": {"lastSuccessAt": max(success)} if success else None,
                "fetchReason": (
                    f"no Signals store at {bdir.relative_to(REPO).as_posix()} on this host "
                    "(box-local, gitignored)"
                    if not bdir.is_dir()
                    else "no successful release fetch recorded"
                ),
            }
        )
        weightings[spec.source_key] = (
            assess_source(spec.source_key, state, as_of=as_of).to_dict() if state else None
        )
    return boards, weightings


def _pins(payload_path: Path) -> dict:
    from src.api import value_replay

    full = value_replay.pins(payload_path)
    digest = hashlib.sha256(json.dumps(full, sort_keys=True, default=str).encode()).hexdigest()
    return {
        "codeRevision": full.get("codeRevision"),
        "workingTreeDirty": full.get("workingTreeDirty"),
        "payload": {
            **(full.get("payload") or {}),
            "path": str((full.get("payload") or {}).get("path")).replace("\\", "/"),
        },
        "freshnessConfig": full.get("freshnessConfig"),
        # Line endings normalized so a Windows checkout (CRLF) and Linux/CI
        # record the same hash for the same commit.
        "lineageRegistrySha256": hashlib.sha256(
            (REPO / "config" / "sources" / "source_lineage.json")
            .read_bytes()
            .replace(b"\r\n", b"\n")
        ).hexdigest(),
        "contractVersion": full.get("contractVersion"),
        "flags": full.get("flags"),
        "pinsDigest": digest,
        "pinsDigestNote": "sha256 of src.api.value_replay.pins(payload) — every source CSV, "
        "dataset-state file, fetch stamp and config file hashed",
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--payload", type=Path, default=None, help="raw scraper payload JSON")
    ap.add_argument("--from-archive", action="store_true", help="newest complete archived scrape")
    ap.add_argument("--out-json", type=Path, default=None)
    ap.add_argument("--out-md", type=Path, default=None)
    ap.add_argument("--state-dir", type=Path, default=REPO / "data" / "scrape_state")
    ap.add_argument("--ledger", type=Path, default=None, help="temporal ledger path override")
    ap.add_argument("--no-git", action="store_true", help="skip the CSV git-history channel")
    ap.add_argument("--label", default="LOCAL")
    args = ap.parse_args(argv)

    with tempfile.TemporaryDirectory() as td:
        payload_path = (
            _archive_payload(Path(td)) if args.from_archive else (args.payload or _latest_payload())
        )
        if payload_path is None or not Path(payload_path).exists():
            print("no raw payload to build a contract from", file=sys.stderr)
            return 2
        try:
            census = _build(Path(payload_path), args)
        except (OSError, ValueError, KeyError, zipfile.BadZipFile) as exc:
            print(f"census build failed: {exc}", file=sys.stderr)
            return 2

    from src.sources.source_census import census_markdown

    # Compact on purpose (artifact size); the Markdown is the human-readable view.
    text = json.dumps(census, separators=(",", ":"), default=str, ensure_ascii=False) + "\n"
    md = census_markdown(census)
    for out, body in ((args.out_json, text), (args.out_md, md)):
        if out:
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(body, encoding="utf-8")
    if not args.out_json and not args.out_md:
        sys.stdout.write(md)

    s = census["summary"]
    problems = {
        "unclassified": s["unclassified"],
        "lineageGaps": s["lineageGaps"],
        "authorityMismatches": s["authorityMismatches"],
        "lineageErrors": census.get("lineageErrors") or [],
    }
    bad = {k: v for k, v in problems.items() if v}
    if bad:
        print(f"census integrity problems: {bad}", file=sys.stderr)
        return 1
    return 0


def _build(payload_path: Path, args: argparse.Namespace) -> dict:
    from src.sources import source_census as sc

    inputs = collect_inputs(payload_path, args)
    census = sc.build_census(inputs)
    if not (inputs.ledger or {}).get("exists"):
        census["temporalLedger"] = {"exists": False, "reason": inputs.ledger_reason}
    census["lineageErrors"] = sc.validate_lineage(inputs.lineage, REPO)
    return census


def collect_inputs(payload_path: Path, args: argparse.Namespace):
    """Every census input, gathered read-only from the canonical owners."""
    from scripts.source_inventory import KNOWN_NON_VOTING_REASONS
    from src.api import data_contract as dc
    from src.history import asof as ledger_asof
    from src.history import backfill as ledger_backfill
    from src.history import record as ledger_record
    from src.sources import ktc_market
    from src.sources import source_census as sc
    from src.sources.dataset_state import load_state, state_path
    from src.sources.freshness import assess_source

    raw = json.loads(payload_path.read_text(encoding="utf-8"))
    contract = dc.build_api_data_contract(raw)
    board_as_of = (contract.get("sourceWeighting") or {}).get("asOf")
    as_of = (
        datetime.fromisoformat(str(board_as_of).replace("Z", "+00:00"))
        if board_as_of
        else datetime.now(timezone.utc)
    )

    registry = list(dc._RANKING_SOURCES)
    csv_paths = dict(dc._SOURCE_CSV_PATHS)
    on_disk = sorted(p.stem for p in (REPO / "CSVs" / "site_raw").glob("*.csv"))
    covered = set(((contract.get("sourceWeighting") or {}).get("sources") or {}).keys())
    second_opinions, so_weightings = _signals_inputs(as_of)
    candidate_keys = (
        {s["key"] for s in registry}
        | set(csv_paths)
        | set(dc._NON_VOTING_SOURCE_CSV_KEYS)
        | set(dc._RETIRED_SOURCE_CORRELATION_GROUPS)
        | set(on_disk)
        | set(KNOWN_NON_VOTING_REASONS)
    )
    extra_weightings: dict = dict(so_weightings)
    change_events: dict = {}
    for key in sorted(candidate_keys):
        state = load_state(state_path(args.state_dir, key))
        if state:
            change_events[key] = {
                sub: len((st or {}).get("changeHistory") or [])
                for sub, st in (state.get("subsets") or {}).items()
            }
        if key not in covered:
            extra_weightings[key] = (
                assess_source(key, state, as_of=as_of).to_dict() if state else None
            )
    profiles = {}
    for key in sorted(candidate_keys):
        rel = sc.csv_path_of(key, csv_paths)
        profiles[key] = sc.profile_csv(REPO / rel)
    git_history = None if args.no_git else sc.collect_git_history(REPO)
    ledger_path = args.ledger
    ledger = ledger_asof.source_lane_coverage(ledger_path)
    lineage = sc.load_lineage()
    inputs = sc.CensusInputs(
        contract=contract,
        registry=registry,
        value_based=frozenset(dc._VALUE_BASED_SOURCES),
        non_voting_declared=frozenset(dc._NON_VOTING_SOURCE_CSV_KEYS),
        retired_groups=dict(dc._RETIRED_SOURCE_CORRELATION_GROUPS),
        csv_paths=csv_paths,
        lineage=lineage,
        non_voting_reasons=dict(KNOWN_NON_VOTING_REASONS),
        on_disk_csv_stems=on_disk,
        extra_weightings=extra_weightings,
        fetch_stamps={k: sc.read_fetch_stamp(args.state_dir, k) for k in sorted(candidate_keys)},
        dataset_change_events=change_events,
        csv_profiles=profiles,
        git_history=git_history,
        git_history_reason="skipped (--no-git)" if args.no_git else "git log unavailable",
        export_archive=sc.collect_export_archive(REPO / "exports" / "archive"),
        export_archive_reason="exports/archive not present",
        ledger=ledger,
        ledger_reason=None
        if ledger.get("exists")
        else "temporal ledger (data/temporal_ledger.sqlite) is gitignored and lives on the "
        "production host; absent from this checkout (pass --ledger to read a copy)",
        ledger_eligible_keys=frozenset(ledger_record._CONTRACT_RETAIL_KEYS)
        | frozenset(ledger_backfill._RAW_RETAIL_KEYS),
        second_opinions=second_opinions,
        benchmark_key=ktc_market.KTC_MARKET_KEY,
        benchmark_derived_from=tuple(ktc_market.KTC_MARKET_DERIVED_FROM),
        pins=_pins(payload_path),
        generated_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        label=args.label,
    )
    return inputs


if __name__ == "__main__":
    raise SystemExit(main())
