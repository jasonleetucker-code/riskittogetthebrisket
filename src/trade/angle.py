"""Angle finder — player-specific trade-target arbitrage.

Given a user-owned player, find players on other teams where the trade
leans in the user's favour under their own league's rankings but looks
fair-or-worse to the counterparty on KTC. Lets the user pitch trades
that their leaguemates will accept ("KTC says it's even") while
actually gaining value in their league-specific calibrated board.

The user_value vs market_value comparison is the same mechanic the
Finder arbitrage engine surfaces board-wide; Angle narrows it to a
specific pivot player so a single trade proposal is easy to generate.
"""
from __future__ import annotations

from typing import Any


def _value_pair(row: dict[str, Any]) -> tuple[float, float] | None:
    """Return (my_value, ktc_value) for a row, or None if incomplete."""
    my_val = row.get("rankDerivedValue")
    sites = row.get("canonicalSiteValues") or {}
    ktc_val = sites.get("ktc") if isinstance(sites, dict) else None
    try:
        my_num = float(my_val) if my_val is not None else 0.0
        ktc_num = float(ktc_val) if ktc_val is not None else 0.0
    except (TypeError, ValueError):
        return None
    if my_num <= 0 or ktc_num <= 0:
        return None
    return my_num, ktc_num


def find_angles(
    players_array: list[dict[str, Any]],
    selected_player_name: str,
    selected_team_owner_id: str,
    sleeper_teams: list[dict[str, Any]],
    *,
    min_my_gain_pct: float = 5.0,
    max_ktc_gain_pct: float = 5.0,
    limit: int = 50,
) -> dict[str, Any]:
    """Find trade-target candidates that lean in the user's favour.

    Parameters
    ----------
    players_array
        Canonical player rows (from build_api_data_contract's
        ``playersArray``). Each row must carry ``canonicalName``,
        ``rankDerivedValue`` (the calibrated my-league value), and
        ``canonicalSiteValues.ktc`` (the market anchor).
    selected_player_name
        Canonical name of the player on the user's team to pivot on.
    selected_team_owner_id
        Sleeper ``ownerId`` identifying the user's roster. Used to
        filter out same-team targets so Angle never suggests trading
        with yourself.
    sleeper_teams
        List of team entries from ``sleeper.teams`` — each team has
        ``name``, ``ownerId``, and ``players`` (canonical names).
    min_my_gain_pct
        Minimum my-league value gain for a target to qualify (as a
        percentage of the selected player's my-league value). Default
        5% — the trade has to visibly move the needle.
    max_ktc_gain_pct
        Maximum market (KTC) value gain on the target side for the
        trade to still look "plausible" to the counterparty. Default
        5% — anything beyond that and the counterparty would reject
        purely on KTC grounds.
    limit
        Cap on returned candidates (sorted by arbitrage score desc).

    Returns
    -------
    dict
        ``{selected: {...}, candidates: [{...}, ...], warnings: [...]}``
    """
    warnings: list[str] = []

    by_name: dict[str, dict[str, Any]] = {}
    for row in players_array:
        name = str(row.get("canonicalName") or row.get("displayName") or "")
        if name and name not in by_name:
            by_name[name] = row

    selected_row = by_name.get(selected_player_name)
    if not selected_row:
        return {
            "selected": None,
            "candidates": [],
            "warnings": [f"Player {selected_player_name!r} not found in the current board."],
        }

    pair = _value_pair(selected_row)
    if pair is None:
        return {
            "selected": {
                "name": selected_player_name,
                "my_value": selected_row.get("rankDerivedValue"),
                "ktc_value": None,
            },
            "candidates": [],
            "warnings": [
                f"{selected_player_name!r} is missing a my-league or KTC value "
                "— Angle needs both to compute the arbitrage."
            ],
        }
    my_val_selected, ktc_val_selected = pair

    # Build reverse index: canonical name -> owner's team dict.
    owner_by_player: dict[str, dict[str, Any]] = {}
    my_team_name: str | None = None
    for team in sleeper_teams:
        owner = str(team.get("ownerId") or "")
        if owner == selected_team_owner_id:
            my_team_name = team.get("name")
        for p in team.get("players") or []:
            owner_by_player[str(p)] = team

    if my_team_name is None:
        warnings.append(
            f"Owner {selected_team_owner_id!r} not found in sleeper roster list; "
            "results will include all other teams."
        )

    candidates: list[dict[str, Any]] = []
    for target_name, target_row in by_name.items():
        if target_name == selected_player_name:
            continue
        owner_team = owner_by_player.get(target_name)
        # Skip same-team targets (trading with yourself is nonsense).
        if (
            owner_team is not None
            and str(owner_team.get("ownerId") or "") == selected_team_owner_id
        ):
            continue
        target_pair = _value_pair(target_row)
        if target_pair is None:
            continue
        my_val_target, ktc_val_target = target_pair

        my_gain = my_val_target - my_val_selected
        ktc_gain = ktc_val_target - ktc_val_selected
        my_gain_pct = 100.0 * my_gain / my_val_selected
        ktc_gain_pct = 100.0 * ktc_gain / ktc_val_selected

        if my_gain_pct < min_my_gain_pct:
            continue
        if ktc_gain_pct > max_ktc_gain_pct:
            continue

        candidates.append(
            {
                "name": target_name,
                "position": str(target_row.get("position") or ""),
                "team": owner_team.get("name") if owner_team else "(free agent)",
                "owner_id": str(owner_team.get("ownerId") or "") if owner_team else "",
                "my_value": int(my_val_target),
                "ktc_value": int(ktc_val_target),
                "my_gain": int(round(my_gain)),
                "ktc_gain": int(round(ktc_gain)),
                "my_gain_pct": round(my_gain_pct, 2),
                "ktc_gain_pct": round(ktc_gain_pct, 2),
                "arb_score": round(my_gain_pct - ktc_gain_pct, 2),
            }
        )

    candidates.sort(key=lambda c: c["arb_score"], reverse=True)
    candidates = candidates[: max(1, int(limit))]

    return {
        "selected": {
            "name": selected_player_name,
            "position": str(selected_row.get("position") or ""),
            "team": my_team_name,
            "my_value": int(my_val_selected),
            "ktc_value": int(ktc_val_selected),
        },
        "candidates": candidates,
        "thresholds": {
            "min_my_gain_pct": min_my_gain_pct,
            "max_ktc_gain_pct": max_ktc_gain_pct,
            "limit": limit,
        },
        "warnings": warnings,
    }
