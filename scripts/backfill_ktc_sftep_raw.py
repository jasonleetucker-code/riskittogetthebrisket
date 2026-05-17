"""One-shot backfill: rewrite ``ktcSfTep`` entries in
``data/source_value_history.jsonl`` to use the raw scrape value from
the matching ``data/dynasty_data_<date>.json`` instead of the
Hill-curve ``valueContribution`` that was originally persisted.

Context
-------
``ktcSfTep`` is in ``_RAW_VALUE_PREFERRED_KEYS`` (see
``src/api/source_history.py``) — KTC publishes a public 0-9999 dynasty
board on keeptradecut.com, so the chart shows the raw scrape (e.g.
9594 for Brock Bowers on 2026-05-05) instead of the Hill contribution
(9999) that goes into the blend.  New snapshots from the
``_extract_player_entry`` change forward are already raw; this
script back-rewrites the existing 180-day window so the time series
doesn't show a discontinuity on the day the writer changed.

The script is idempotent: rerunning is a no-op since the second pass
sees raw values already.  ``--dry-run`` prints the diff without
writing.

Usage
-----
    python -m scripts.backfill_ktc_sftep_raw            # apply
    python -m scripts.backfill_ktc_sftep_raw --dry-run  # preview
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HISTORY_PATH = ROOT / "data" / "source_value_history.jsonl"
DATA_DIR = ROOT / "data"


def _load_export_top_level_ktc_sftep(date: str) -> dict[str, int]:
    """Return ``{playerName.lower(): raw_ktc_sftep}`` from the daily
    export for ``date``, if present.  Empty dict when the file is
    missing or has no ``ktcSfTep`` data.
    """
    export = DATA_DIR / f"dynasty_data_{date}.json"
    if not export.exists():
        return {}
    try:
        raw = json.loads(export.read_text())
    except Exception as exc:  # noqa: BLE001
        print(f"  [warn] failed to read {export}: {exc}", file=sys.stderr)
        return {}
    players = raw.get("players")
    if not isinstance(players, dict):
        return {}
    out: dict[str, int] = {}
    for name, entry in players.items():
        if not isinstance(entry, dict):
            continue
        val = entry.get("ktcSfTep")
        try:
            v = int(val) if val is not None else None
        except (TypeError, ValueError):
            v = None
        if v is not None and v > 0:
            out[str(name).strip().lower()] = v
    return out


def _norm_player_key(snap_key: str) -> str:
    """``"Brock Bowers::offense"`` → ``"brock bowers"``.  Mirror of
    ``source_history._norm_name_key`` reduced to just the name half
    for matching against export player keys.
    """
    name = snap_key.split("::")[0]
    return name.strip().lower()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="preview only")
    parser.add_argument(
        "--path",
        type=Path,
        default=HISTORY_PATH,
        help="snapshot JSONL path (default: data/source_value_history.jsonl)",
    )
    args = parser.parse_args()

    if not args.path.exists():
        print(f"snapshot file not found: {args.path}", file=sys.stderr)
        return 1

    lines = args.path.read_text().splitlines()
    rewritten: list[str] = []
    total_replaced = 0
    total_unchanged = 0
    total_no_export = 0
    total_dropped_missing = 0

    for line in lines:
        if not line.strip():
            rewritten.append(line)
            continue
        try:
            snap = json.loads(line)
        except json.JSONDecodeError as exc:
            print(f"  [warn] skipping malformed line: {exc}", file=sys.stderr)
            rewritten.append(line)
            continue

        date = str(snap.get("date") or "")
        players = snap.get("players")
        if not date or not isinstance(players, dict):
            rewritten.append(line)
            continue

        export_map = _load_export_top_level_ktc_sftep(date)
        if not export_map:
            total_no_export += 1
            # Snapshot has ktcSfTep entries but no export to source raw
            # values from — leave as-is.  Chart will show the Hill
            # contribution for these days; it'll roll off in 180 days.
            rewritten.append(line)
            continue

        snap_replaced = 0
        snap_dropped = 0
        snap_unchanged = 0
        for snap_key, entry in players.items():
            if not isinstance(entry, dict):
                continue
            sources = entry.get("sources")
            if not isinstance(sources, dict):
                continue
            current = sources.get("ktcSfTep")
            if current is None:
                continue
            name_key = _norm_player_key(snap_key)
            raw = export_map.get(name_key)
            if raw is None:
                # Player in snapshot but not in export — drop the
                # ktcSfTep entry rather than leave a stale Hill
                # contribution sitting next to today's raw values.
                sources.pop("ktcSfTep", None)
                snap_dropped += 1
                continue
            if int(current) == int(raw):
                snap_unchanged += 1
                continue
            sources["ktcSfTep"] = int(raw)
            snap_replaced += 1

        total_replaced += snap_replaced
        total_unchanged += snap_unchanged
        total_dropped_missing += snap_dropped
        rewritten.append(json.dumps(snap, separators=(",", ":")))
        print(
            f"  {date}: replaced={snap_replaced} unchanged={snap_unchanged} "
            f"dropped(no_export_match)={snap_dropped}"
        )

    print()
    print(f"Total replaced: {total_replaced}")
    print(f"Total unchanged (already raw): {total_unchanged}")
    print(f"Total dropped (no export match): {total_dropped_missing}")
    print(f"Snapshot dates with no daily export: {total_no_export}")

    if args.dry_run:
        print("[dry-run] no changes written")
        return 0

    backup = args.path.with_suffix(args.path.suffix + ".bak")
    backup.write_text(args.path.read_text())
    args.path.write_text("\n".join(rewritten) + ("\n" if rewritten else ""))
    print(f"Wrote {args.path} (backup at {backup})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
