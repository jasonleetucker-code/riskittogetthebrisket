#!/usr/bin/env python3
"""Publish an owner-attested Power Rankings baseline week, then restate its successor.

    python scripts/publish_power_week_zero.py --league-key dynasty_main \
        --input config/power/attested/dynasty_main_2026_week_00.json --dry-run

Exit codes: 0 ok · 1 error · 2 nothing to do.

WHY THIS EXISTS
───────────────
Movement on the weekly share card is ``previousOfficialRank - currentRank``, so
Week 1 needs Week 0 to exist.  The automated publisher in ``src/ros/scrape.py``
refuses ``week < 1`` by design and only ever finalizes the immediately completed
host week, so a preseason ranking that was never published cannot be published
later by the pipeline — and the spec forbids back-dating today's ROS strength
into an older week, which is what recomputing it would do.

What IS recoverable is the order the site actually displayed, from the owner's
screenshot of the published card.  This script records exactly that: ranks and
names, no Power score, stamped ``rankSource: owner_attested_published_card`` so
no reader can mistake it for something the engine produced.

Owner ids are resolved from an ALREADY PUBLISHED snapshot of the same league and
season, never from a fuzzy name match against the live league — a rename since
the screenshot must fail loudly rather than silently attach a rank to the wrong
manager.

Publishing the baseline changes what Week 1 knows about itself, so the second
step restates Week 1's movement from the two frozen files.  That is the only
edit ``restate_movement`` permits: a ``None`` becoming a number.  It refuses to
rewrite an arrow that was already published.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.ros import power_snapshots  # noqa: E402


def _resolve_owner_ids(
    rows: list[dict[str, Any]],
    reference: dict[str, Any],
) -> list[dict[str, Any]]:
    """Attach ownerIds by exact display name against a published snapshot."""
    by_name: dict[str, list[str]] = {}
    for row in reference.get("ranking") or []:
        name = str(row.get("displayName") or "").strip()
        owner_id = str(row.get("ownerId") or "")
        if name and owner_id:
            by_name.setdefault(name, []).append(owner_id)

    resolved: list[dict[str, Any]] = []
    problems: list[str] = []
    for row in rows:
        name = str(row.get("displayName") or "").strip()
        matches = by_name.get(name) or []
        if len(matches) != 1:
            problems.append(
                f"  rank {row.get('rank')}: {name!r} matched {len(matches)} owners in the reference week"
            )
            continue
        resolved.append({**row, "ownerId": matches[0]})
    if problems:
        raise SystemExit(
            "cannot resolve every attested name to exactly one owner:\n" + "\n".join(problems)
        )
    return resolved


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--league-key", required=True, help="registry league key, e.g. dynasty_main")
    ap.add_argument("--input", required=True, type=Path, help="attested ranking JSON")
    ap.add_argument(
        "--reference-week",
        type=int,
        default=1,
        help="published week used to resolve display names to owner ids, and restated afterwards",
    )
    ap.add_argument("--dry-run", action="store_true", help="report, write nothing")
    args = ap.parse_args()

    try:
        doc = json.loads(args.input.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: cannot read {args.input}: {exc}", file=sys.stderr)
        return 1

    season = str(doc.get("season") or "")
    week = doc.get("week")
    rows = doc.get("rows") or []
    if not season or not isinstance(week, int) or not rows:
        print(
            "ERROR: input needs season, an integer week and a non-empty rows list", file=sys.stderr
        )
        return 1
    if str(doc.get("leagueKey") or args.league_key) != args.league_key:
        print(
            f"ERROR: input is for league {doc.get('leagueKey')!r}, not {args.league_key!r}",
            file=sys.stderr,
        )
        return 1

    reference = power_snapshots.load_snapshot(args.league_key, season, args.reference_week)
    if reference is None:
        print(
            f"ERROR: no published week {args.reference_week} for {args.league_key} {season} "
            "to resolve owner ids against",
            file=sys.stderr,
        )
        return 1

    resolved = _resolve_owner_ids(rows, reference)
    target = power_snapshots.snapshot_path(args.league_key, season, week)
    if target.exists():
        print(f"nothing to do: {target} already published")
        return 2

    if args.dry_run:
        print(f"DRY RUN — would publish {target}")
    else:
        path, created = power_snapshots.record_attested_snapshot(
            league_key=args.league_key,
            season=season,
            week=week,
            rows=resolved,
            attestation=doc.get("attestation") or {},
            methodology_version=doc.get("methodologyVersion"),
        )
        if not created:
            print(f"nothing to do: {path} already published")
            return 2
        print(f"published {path}")

    # Movement the reference week could not know when it was published.
    previous_rank = {str(r["ownerId"]): int(r["rank"]) for r in resolved}
    print(f"\nweek {args.reference_week} movement against week {week}:")
    for row in reference.get("ranking") or []:
        owner_id = str(row.get("ownerId") or "")
        prior = previous_rank.get(owner_id)
        rank = row.get("rank")
        delta = prior - int(rank) if prior is not None and rank is not None else None
        mark = "—" if not delta else ("+" if delta > 0 else "") + str(delta)
        print(f"  {rank:>2}  {str(row.get('displayName')):<10} {prior} -> {rank}  {mark}")

    if args.dry_run:
        print(f"\nDRY RUN — would restate week {args.reference_week}")
        return 0

    path, restated = power_snapshots.restate_movement(
        league_key=args.league_key,
        season=season,
        week=args.reference_week,
        reason=f"owner_authorized_week_{week:02d}_backfill",
    )
    print(f"\n{'restated' if restated else 'already consistent'}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
