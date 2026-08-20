#!/usr/bin/env python3
"""Measure the SAF scoring defect at TWO levels, because they are different numbers.

Reproduces the figures in ``docs/scoring/HOST_NATIVE_SCORING_VALIDATION.md`` §2a.

Why two levels
--------------
``SAF`` was in neither ``POSITION_ALIASES`` nor ``realized_points._IDP_POSITIONS``,
so the canonical engine skipped the whole IDP block for safeties.  That is a real
defect in the canonical owner and it is large.

But both production consumers already normalized ``SAF`` before calling the
engine — ``league_comparison.scoring_engine._canonical_position`` to ``DB`` and
``bdvm.context.TRUE_POSITION_MAP`` to ``S`` — each with its own private table.
So the *consumer-reachable* delta from repairing ``SAF`` is zero, and quoting the
engine-level number as if a user saw it would overstate the impact.

Two arms, therefore:

* ``engine``   — hand the engine the raw ``SAF`` spelling, no normalization.
                 This is the defect's magnitude in the owner.
* ``consumer`` — run the full ``league_comparison`` season-scoring path.
                 This is what anything downstream could actually see move.

Run it against two trees (a ``git worktree`` at ``origin/main`` and this one) to
get the before/after; ``--root`` selects which tree's ``src/`` is imported.

Exit codes: 0 measured, 2 inputs unavailable.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any, Iterable

#: Fallback import root.  ``--root`` takes precedence — it is inserted at
#: position 0 later, which is the whole point of this script (it imports a
#: DIFFERENT tree's ``src/`` to measure the before side).
REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.append(str(REPO))

CARD_FIXTURE = Path("tests/nfl_data/fixtures/live_scoring_cards_2026-07-28.json")


def _load_card(root: Path, league_key: str) -> dict[str, Any]:
    raw = json.loads((root / CARD_FIXTURE).read_text())[league_key]
    return raw.get("scoring_settings", raw)


def _reg_rows(path: Path) -> list[dict[str, Any]]:
    with path.open(newline="") as fh:
        return [
            row
            for row in csv.DictReader(fh)
            if str(row.get("season_type") or "REG").upper() == "REG"
        ]


def _points(result: Any) -> float:
    """The engine's per-week result names this field differently across versions."""
    for attr in ("fantasy_points", "points"):
        if hasattr(result, attr):
            return float(getattr(result, attr))
    raise AttributeError("weekly result carries no points field")


def measure_engine(
    rows: Iterable[dict[str, Any]], card: dict[str, Any], *, position: str | None
) -> tuple[int, float]:
    """Total points for the SAF rows, optionally overriding the position first.

    ``position=None`` is the honest reproduction of what the engine was handed:
    the source's own spelling, unnormalized.
    """
    from src.nfl_data import realized_points as rp

    total = 0.0
    count = 0
    for row in rows:
        if str(row.get("position") or "").upper() != "SAF":
            continue
        count += 1
        scored = dict(row)
        if position:
            scored["position"] = position
        total += _points(rp.compute_weekly_points(scored, card))
    return count, total


def measure_consumer(
    rows: list[dict[str, Any]], card: dict[str, Any], season: int
) -> dict[str, Any]:
    """The league-comparison path — no PBP supplement, so both trees are comparable."""
    from src.league_comparison.scoring_engine import compute_player_season_scores

    scores = compute_player_season_scores(rows, card, season=season)
    by_player = {s.player_id: round(float(s.total_points), 6) for s in scores}
    by_position: dict[str, float] = {}
    for s in scores:
        by_position[s.position] = round(by_position.get(s.position, 0.0) + float(s.total_points), 6)
    return {
        "total": round(sum(by_player.values()), 6),
        "players": by_player,
        "byPosition": by_position,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=".", help="tree whose src/ is imported (default: cwd)")
    ap.add_argument("--weekly-csv", required=True, help="nflverse stats_player_week_<season>.csv")
    ap.add_argument("--season", type=int, default=2025)
    ap.add_argument("--league-key", default="dynasty_main")
    ap.add_argument("--out", help="write the consumer arm's per-player totals here (JSON)")
    args = ap.parse_args(argv)

    root = Path(args.root).resolve()
    sys.path.insert(0, str(root))

    csv_path = Path(args.weekly_csv)
    if not csv_path.exists():
        print(f"weekly CSV not found: {csv_path}", file=sys.stderr)
        return 2
    if not (root / CARD_FIXTURE).exists():
        print(f"card fixture not found under {root}", file=sys.stderr)
        return 2

    rows = _reg_rows(csv_path)
    card = _load_card(root, args.league_key)

    print(f"tree={root}  season={args.season} REG  rows={len(rows):,}")

    print("\n-- engine arm: what the canonical engine does with the raw spelling --")
    n, raw = measure_engine(rows, card, position=None)
    _, as_s = measure_engine(rows, card, position="S")
    _, as_db = measure_engine(rows, card, position="DB")
    print(f"   SAF player-weeks                        : {n:,}")
    print(f"   raw 'SAF' verbatim                      : {raw:>12,.2f}")
    print(f"   normalized -> 'S'   (bdvm.context)      : {as_s:>12,.2f}")
    print(f"   normalized -> 'DB'  (league_comparison) : {as_db:>12,.2f}")

    print("\n-- consumer arm: the full league-comparison season path --")
    consumer = measure_consumer(rows, card, args.season)
    print(f"   players scored : {len(consumer['players']):,}")
    print(f"   total points   : {consumer['total']:>12,.2f}")
    if args.out:
        Path(args.out).write_text(json.dumps(consumer, indent=1, sort_keys=True))
        print(f"   wrote {args.out} — diff it against the other tree's run")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
