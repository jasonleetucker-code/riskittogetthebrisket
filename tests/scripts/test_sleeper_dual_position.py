"""Dynasty Scraper Sleeper-side dual-position resolution.

Sleeper exposes ``fantasy_positions`` as a list of eligible slots;
``position`` is just the primary. Edge rushers who also carry LB
eligibility (Parsons, Burns, Crosby) come through Sleeper as
``position="LB"`` with ``fantasy_positions=["DL","LB"]``. We want
those rows collapsed to DL in the position_map so they don't
compete in the off-ball LB bucket downstream.

Single-position rows and pure-offense rows must pass through
unchanged.
"""
from __future__ import annotations

from src.utils.name_clean import resolve_idp_position


def _resolve(raw_pos: str, fantasy_positions: list[str] | None) -> str:
    """Replicate the Dynasty Scraper sleeper-ingest block.

    We don't import Dynasty Scraper.py directly (it has a top-level
    ``import playwright`` that's not available in the CI image), so
    this helper mirrors the same condition the scraper applies.
    """
    fp_list = fantasy_positions if isinstance(fantasy_positions, list) else None
    pos = raw_pos
    if fp_list and len(fp_list) >= 2:
        resolved_family = resolve_idp_position(fp_list)
        if resolved_family in {"DL", "DB", "LB"}:
            pos = resolved_family
    return pos


def test_dl_plus_lb_collapses_to_dl():
    # Parsons case: Sleeper primary = "LB", fantasy_positions =
    # ["DL","LB"]. Must resolve to DL so he gets bucketed with
    # pass-rushers, not off-ball LBs.
    assert _resolve("LB", ["DL", "LB"]) == "DL"


def test_db_plus_lb_collapses_to_db():
    # Box safety case: LB + S eligibility should fall on DB, not LB,
    # because DB outranks LB in the shared priority ladder.
    assert _resolve("LB", ["LB", "S"]) == "DB"


def test_exclusive_lb_stays_lb():
    # Pure off-ball LB — no DL/DB co-eligibility — stays LB.
    assert _resolve("LB", ["LB"]) == "LB"


def test_single_position_passes_through():
    # Single-entry fantasy_positions list: we do NOT call
    # resolve_idp_position (it would collapse "CB" → "DB" and
    # discard the fine-grained token). Row stays as the raw position.
    assert _resolve("CB", ["CB"]) == "CB"
    assert _resolve("DE", ["DE"]) == "DE"


def test_offense_dual_position_passes_through():
    # Offense flex eligibility (e.g. "RB,WR,FLEX") must not be
    # collapsed to an IDP family just because the list has 2+
    # entries. ``resolve_idp_position`` returns "" for non-IDP
    # rosters and the row stays as the primary.
    assert _resolve("RB", ["RB", "FLEX"]) == "RB"
    assert _resolve("WR", ["WR", "TE"]) == "WR"


def test_missing_fantasy_positions_passes_through():
    # Older Sleeper snapshots may not supply fantasy_positions at
    # all. Behaviour falls back to the raw primary position.
    assert _resolve("LB", None) == "LB"
    assert _resolve("QB", None) == "QB"
