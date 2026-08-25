#!/usr/bin/env python3
"""Recompute the league comparison BOTH ways — asymmetric windows vs symmetric.

Reproduces the before/after table in
``docs/scoring/HOST_NATIVE_SCORING_VALIDATION.md`` §5b.

WHAT THE TWO ARMS ARE
---------------------
The repaired path scores every season of BOTH leagues under that league's
current card (``service.CARD_BASIS_COUNTERFACTUAL``) — one declared basis.

The defect it replaced resolved each league's ``previous_league_id`` chain
INDEPENDENTLY, and the two failure modes were not the same shape: an arm whose
walk returned nothing fell back to today's card with every season available,
while an arm whose walk returned something dropped the seasons it could not
resolve.  On the live configuration that is a four-season average against a
one-season average, compared as though it were one measurement.

This script models the defect by simply restricting one arm's window — which is
all the chain resolution amounted to at the output — and runs the real
``_build_league_block`` / ``_build_position_comparisons`` / similarity code on
both, so the difference is measured in the service's own arithmetic rather than
re-derived here.

It needs the weekly stat feed.  It does not need Sleeper: the two live cards are
committed at ``tests/nfl_data/fixtures/live_scoring_cards_2026-07-28.json``.

Exit codes: 0 measured, 2 inputs unavailable.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

CARDS = REPO / Path("tests/nfl_data/fixtures/live_scoring_cards_2026-07-28.json")
CONFIG = REPO / Path("config/league_comparison.json")


class _Info:
    """The subset of ``LeagueScoringInfo`` the block builder reads."""

    def __init__(self, league_id: str, scoring: dict[str, Any], name: str) -> None:
        self.league_id = league_id
        self.scoring_settings = scoring
        self.name = name
        self.season = None


def _load_rows(seasons: list[int]) -> dict[int, list[dict[str, Any]] | None]:
    from src.nfl_data.ingest import fetch_weekly_stats

    out: dict[int, list[dict[str, Any]] | None] = {}
    for season in seasons:
        try:
            rows = fetch_weekly_stats([season])
        except Exception as exc:  # noqa: BLE001 — a missing season is reported, not fatal
            print(f"  {season}: unavailable ({exc!r})", file=sys.stderr)
            out[season] = None
            continue
        reg = [r for r in rows or [] if str(r.get("season_type") or "REG").upper() == "REG"]
        print(f"  {season}: {len(reg):,} REG rows")
        out[season] = reg or None
    return out


def _run(
    svc: Any,
    my_info: _Info,
    base_info: _Info,
    seasons_map: dict[int, Any],
    sample_sizes: dict[str, int],
    *,
    baseline_window: list[int] | None,
) -> dict[str, Any]:
    """One comparison.  ``baseline_window`` restricts the baseline arm's seasons."""
    base_map = seasons_map
    if baseline_window is not None:
        base_map = {s: (rows if s in baseline_window else None) for s, rows in seasons_map.items()}

    my_block = svc._build_league_block(my_info, seasons_map, sample_sizes)
    base_block = svc._build_league_block(base_info, base_map, sample_sizes)
    positions, _my_sl, my_si, _base_sl, base_si = svc._build_position_comparisons(
        my_block, base_block
    )
    flex = svc._flex_block(my_block, base_block)
    similarity = svc._m.similarity_score(
        my_shares=my_si,
        baseline_shares=base_si,
        my_flex=flex["my"]["improvedScore"],
        baseline_flex=flex["baseline"]["improvedScore"],
    )

    def _avail(block: dict[str, Any]) -> list[str]:
        return sorted(k for k, v in block["perSeason"].items() if v.get("available"))

    return {
        "mySeasons": _avail(my_block),
        "baselineSeasons": _avail(base_block),
        "similarity": similarity.score,
        "similarityLabel": similarity.label,
        "flexDevPct": similarity.flex_dev_pct,
        "totalShareDevPp": similarity.total_share_dev_pp,
        "baselineShares": {pos: round(v, 4) for pos, v in sorted(base_si.items())},
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--defect-baseline-window",
        default="2025",
        help="comma-separated seasons the baseline arm retained under the defect "
        "(default 2025 — what the live chain walk produced)",
    )
    args = ap.parse_args(argv)

    if not CARDS.exists() or not CONFIG.exists():
        print("cards or config fixture missing", file=sys.stderr)
        return 2

    from src.api import league_registry
    from src.league_comparison import service as svc

    cfg = json.loads(CONFIG.read_text())
    cards = json.loads(CARDS.read_text())
    seasons = [int(s) for s in cfg["seasons"]]

    # "My league" is the registry's default league (W18-F005) — mirror
    # build_comparison's own resolution rather than the retired
    # cfg["my_league"] config key, so this reproduction script keeps
    # measuring the SAME arithmetic the live service actually runs.
    my_league_cfg = league_registry.get_default_league()
    if my_league_cfg is None:
        print("no default league configured in the registry", file=sys.stderr)
        return 2
    sample_sizes = {str(k): int(v) for k, v in cfg["sample_sizes"].items()}
    sample_sizes.update(svc._sample_sizes_from_roster_settings(my_league_cfg.roster_settings))

    my_info = _Info(
        my_league_cfg.sleeper_league_id,
        cards["dynasty_main"].get("scoring_settings", cards["dynasty_main"]),
        my_league_cfg.display_name,
    )
    base_info = _Info(
        str(cfg["baseline_league"]["id"]),
        cards["baseline"].get("scoring_settings", cards["baseline"]),
        cfg["baseline_league"]["label"],
    )

    print(f"seasons requested: {seasons}")
    seasons_map = _load_rows(seasons)
    total = sum(len(r or []) for r in seasons_map.values())
    if not total:
        print("no weekly rows available", file=sys.stderr)
        return 2
    print(f"weekly rows total: {total:,}\n")

    window = [int(s) for s in args.defect_baseline_window.split(",") if s.strip()]
    before = _run(svc, my_info, base_info, seasons_map, sample_sizes, baseline_window=window)
    after = _run(svc, my_info, base_info, seasons_map, sample_sizes, baseline_window=None)

    for label, res in (("BEFORE (asymmetric)", before), ("AFTER  (symmetric)", after)):
        print(f"{label}")
        print(f"   seasons  mine={res['mySeasons']}  baseline={res['baselineSeasons']}")
        print(f"   similarity           : {res['similarity']} ({res['similarityLabel']})")
        print(f"   FLEX deviation       : {res['flexDevPct']}%")
        print(f"   total share deviation: {res['totalShareDevPp']} pp")
        print(f"   baseline shares      : {res['baselineShares']}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
