#!/usr/bin/env python3
"""Diff two BDVM projection snapshots (``projections_<date>[_<label>].json``,
written by ``scripts/bdvm_build_baseline.py``).

Built for the V1-49 controlled-activation workflow's "BDVM rerun against
challenger output" measurement
(``docs/scoring/HOST_NATIVE_SCORING_VALIDATION.md`` §4 item 1): a
pre-activation snapshot (``--label v149_pre``) is compared against a
post-activation snapshot (``--label v149_post``) of the same season, and
this tool reports exactly what moved.

This is a COMPARISON tool only — it never recomputes fantasy points or
any scoring value. It diffs the already-published, already-scored scalar
fields each record carries (``games``, ``fpg``, ``fpts``, ``projHigh``,
``projLow``) plus provenance flags (``isProxy``, ``statBasis``,
``scoringNative``). Recomputing a value here would duplicate the
canonical scoring engine and risk drifting from it; reporting the raw
delta between two already-canonical numbers does not.

Records are matched by ``(playerKey, season, source)`` — the same
identity a snapshot file already keys its rows on.

Exit codes: 0 success (a report was produced, regardless of whether any
differences were found — this tool never judges pass/fail), 2 usage/IO
error (missing file, malformed JSON).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

_COMPARABLE_NUMERIC_FIELDS = ("games", "fpg", "fpts", "projHigh", "projLow")
_PROVENANCE_FIELDS = ("isProxy", "statBasis", "scoringNative")


class SnapshotDiffError(Exception):
    """Raised on invalid input; callers should exit 2."""


def load_snapshot_payload(path: Path) -> dict:
    if not path.is_file():
        raise SnapshotDiffError(f"snapshot not found: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SnapshotDiffError(f"malformed snapshot JSON at {path}: {exc}") from exc
    if "records" not in payload:
        raise SnapshotDiffError(f"snapshot at {path} has no 'records' key")
    return payload


def _record_key(record: dict) -> tuple[str, int, str]:
    return (record["playerKey"], int(record["season"]), record["source"])


def _summarize(key: tuple[str, int, str], record: dict) -> dict:
    return {
        "playerKey": key[0],
        "season": key[1],
        "source": key[2],
        "fpg": record.get("fpg"),
        "fpts": record.get("fpts"),
        "isProxy": record.get("isProxy"),
    }


def _numeric_delta(before_value: Any, after_value: Any) -> float | None:
    if isinstance(before_value, (int, float)) and isinstance(after_value, (int, float)):
        return after_value - before_value
    return None


def _max_abs_field_delta(changed_entry: dict) -> float:
    magnitudes = [
        abs(d["delta"]) for d in changed_entry["fieldDeltas"].values() if d.get("delta") is not None
    ]
    return max(magnitudes) if magnitudes else 0.0


def diff_records(before: list[dict], after: list[dict]) -> dict:
    """Compare two lists of raw snapshot records (as loaded from JSON).

    Returns a dict with full added/removed/changed lists (unsorted
    counts are exact; ``changed`` is sorted by the largest absolute
    numeric-field delta first) plus summary counts.
    """
    before_by_key = {_record_key(r): r for r in before}
    after_by_key = {_record_key(r): r for r in after}
    all_keys = set(before_by_key) | set(after_by_key)

    added: list[dict] = []
    removed: list[dict] = []
    changed: list[dict] = []
    unchanged_count = 0

    for key in sorted(all_keys):
        before_rec = before_by_key.get(key)
        after_rec = after_by_key.get(key)
        if before_rec is None:
            added.append(_summarize(key, after_rec))
            continue
        if after_rec is None:
            removed.append(_summarize(key, before_rec))
            continue

        field_deltas: dict[str, dict] = {}
        for field in _COMPARABLE_NUMERIC_FIELDS:
            before_value, after_value = before_rec.get(field), after_rec.get(field)
            if before_value != after_value:
                field_deltas[field] = {
                    "before": before_value,
                    "after": after_value,
                    "delta": _numeric_delta(before_value, after_value),
                }

        provenance_deltas: dict[str, dict] = {}
        for field in _PROVENANCE_FIELDS:
            before_value, after_value = before_rec.get(field), after_rec.get(field)
            if before_value != after_value:
                provenance_deltas[field] = {"before": before_value, "after": after_value}

        if field_deltas or provenance_deltas:
            changed.append(
                {
                    "playerKey": key[0],
                    "season": key[1],
                    "source": key[2],
                    "fieldDeltas": field_deltas,
                    "provenanceDeltas": provenance_deltas,
                }
            )
        else:
            unchanged_count += 1

    changed.sort(key=_max_abs_field_delta, reverse=True)

    return {
        "beforeRecordCount": len(before),
        "afterRecordCount": len(after),
        "addedCount": len(added),
        "removedCount": len(removed),
        "changedCount": len(changed),
        "unchangedCount": unchanged_count,
        "added": added,
        "removed": removed,
        "changed": changed,
    }


def diff_snapshots(before_path: Path, after_path: Path, *, top_n: int | None = None) -> dict:
    before_payload = load_snapshot_payload(before_path)
    after_payload = load_snapshot_payload(after_path)
    report = diff_records(before_payload["records"], after_payload["records"])
    report["beforePath"] = str(before_path)
    report["afterPath"] = str(after_path)
    report["beforeSeason"] = before_payload.get("season")
    report["afterSeason"] = after_payload.get("season")
    report["beforeAsOf"] = before_payload.get("asOf")
    report["afterAsOf"] = after_payload.get("asOf")
    if top_n is not None:
        report["added"] = report["added"][:top_n]
        report["removed"] = report["removed"][:top_n]
        report["changed"] = report["changed"][:top_n]
        report["truncatedToTopN"] = top_n
    return report


def _cmd_diff(args: argparse.Namespace) -> int:
    report = diff_snapshots(Path(args.before), Path(args.after), top_n=args.top_n)
    print(json.dumps(report, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before", required=True, help="pre-activation snapshot path")
    parser.add_argument("--after", required=True, help="post-activation snapshot path")
    parser.add_argument(
        "--top-n",
        type=int,
        default=25,
        help="cap added/removed/changed lists to the top N entries (default 25); "
        "pass 0 to disable truncation",
    )
    parser.set_defaults(func=_cmd_diff)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.top_n is not None and args.top_n <= 0:
        args.top_n = None
    try:
        return args.func(args)
    except SnapshotDiffError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
