"""Angle finder — player-specific trade-target arbitrage.

Given a user-owned player (or package of players), find players or
player-packages on other teams where the trade leans in the user's
favour under their own league's rankings but looks fair-or-worse to
the counterparty on KTC. Lets the user pitch trades that their
leaguemates will accept ("KTC says it's even") while actually gaining
value in their league-specific calibrated board.

``find_angles`` handles the single-player pivot. ``find_angle_packages``
extends to multi-player offers: give it a list of your players and it
returns multi-player counter-packages whose size is within ±1 of your
offer (e.g. offering 4 players → returns 3-, 4-, and 5-player
counter-offers). Same arbitrage math; combinations are evaluated per
opposing team with the candidate pool clamped to each team's top-N
players by your calibrated value so the search stays fast.
"""
from __future__ import annotations

from itertools import combinations
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


def find_angle_packages(
    players_array: list[dict[str, Any]],
    selected_player_names: list[str],
    selected_team_owner_id: str,
    sleeper_teams: list[dict[str, Any]],
    *,
    min_my_gain_pct: float = 5.0,
    max_ktc_gain_pct: float = 5.0,
    limit: int = 50,
    candidate_pool_per_team: int = 25,
    per_team_limit: int = 4,
    positions: list[str] | None = None,
    min_player_my_value: float = 0.0,
) -> dict[str, Any]:
    """Find multi-player counter-packages for a user-built offer.

    Parameters
    ----------
    selected_player_names
        List of canonical player names on the user's roster that
        constitute the OFFER side of the trade.
    selected_team_owner_id
        Sleeper ``ownerId`` identifying the user's team (excluded
        from candidate pool).
    candidate_pool_per_team
        Top-N players (by ``rankDerivedValue``) considered per
        opposing team when enumerating combinations. Caps the
        combinatorial explosion; 25 × size-5 ≈ 53k combos per team
        which completes comfortably inside a request.
    per_team_limit
        Max packages kept per opposing team (by arb score desc)
        before the global ``limit`` is applied. Default 4 — keeps
        one team from swamping the results with 50 variations of
        the same trade. Set to a large number to disable.
    positions
        When non-empty, restrict the candidate pool to players whose
        ``position`` matches one of these tokens (case-insensitive).
        ``None`` or empty list = any position.
    min_player_my_value
        Minimum ``rankDerivedValue`` a player must have to be
        considered in the candidate pool. Caller uses this to say
        "don't suggest filler-depth guys in my counter-package."

    Returns
    -------
    dict
        ``{offer, candidates, thresholds, warnings}`` where
        ``candidates`` is a list of package dicts, each with
        ``{team, size, players, my_total, ktc_total, my_gain_pct,
        ktc_gain_pct, arb_score}``. Sorted by ``arb_score`` desc.

    The counter-package size is constrained to ``{N-1, N, N+1}``
    where ``N`` is the offered-player count. Size ``0`` is skipped
    when ``N == 1`` (that's what :func:`find_angles` is for).
    """
    warnings: list[str] = []

    by_name: dict[str, dict[str, Any]] = {}
    for row in players_array:
        name = str(row.get("canonicalName") or row.get("displayName") or "")
        if name and name not in by_name:
            by_name[name] = row

    # Resolve offer-side rows; drop any with missing values and warn.
    offer_rows: list[dict[str, Any]] = []
    missing: list[str] = []
    for name in selected_player_names:
        row = by_name.get(name)
        if not row:
            missing.append(name)
            continue
        pair = _value_pair(row)
        if pair is None:
            missing.append(name)
            continue
        offer_rows.append(row)
    if missing:
        warnings.append(
            f"Dropped {len(missing)} player(s) from the offer that have no "
            f"my-value or KTC value: {', '.join(missing[:5])}"
            + (" …" if len(missing) > 5 else "")
        )
    if not offer_rows:
        return {
            "offer": {"players": [], "size": 0, "my_total": 0, "ktc_total": 0},
            "candidates": [],
            "warnings": warnings or ["No valid offer-side players."],
        }

    offer_my_total = sum(
        _value_pair(r)[0] for r in offer_rows  # type: ignore[index]
    )
    offer_ktc_total = sum(
        _value_pair(r)[1] for r in offer_rows  # type: ignore[index]
    )
    offer_size = len(offer_rows)

    # Target sizes: N-1, N, N+1 — never less than 1.
    target_sizes = sorted({max(1, offer_size - 1), offer_size, offer_size + 1})

    # Normalise position filter.
    position_filter: set[str] | None = None
    if positions:
        position_filter = {str(p).strip().upper() for p in positions if str(p).strip()}
        if not position_filter:
            position_filter = None
    min_my_value_floor = max(0.0, float(min_player_my_value or 0.0))

    # Build per-team candidate pool, filtered + capped.
    my_team_name: str | None = None
    teams_pool: list[tuple[dict[str, Any], list[dict[str, Any]]]] = []
    offer_name_set = {str(r.get("canonicalName") or "") for r in offer_rows}
    for team in sleeper_teams:
        owner = str(team.get("ownerId") or "")
        if owner == selected_team_owner_id:
            my_team_name = team.get("name")
            continue
        pool: list[dict[str, Any]] = []
        for pname in team.get("players") or []:
            pname = str(pname)
            if pname in offer_name_set:
                continue  # never suggest trading for your own player
            row = by_name.get(pname)
            if not row:
                continue
            pair = _value_pair(row)
            if pair is None:
                continue
            my_v, ktc_v = pair
            # Per-player filters: position allow-list and my-value floor.
            row_pos = str(row.get("position") or "").strip().upper()
            if position_filter is not None and row_pos not in position_filter:
                continue
            if my_v < min_my_value_floor:
                continue
            pool.append(
                {
                    "name": pname,
                    "position": str(row.get("position") or ""),
                    "my_value": my_v,
                    "ktc_value": ktc_v,
                }
            )
        pool.sort(key=lambda p: -p["my_value"])
        pool = pool[:candidate_pool_per_team]
        teams_pool.append((team, pool))

    # Pre-compute numeric thresholds in absolute-value terms so the
    # inner loop uses only arithmetic, no division.
    min_my_total = offer_my_total * (1.0 + min_my_gain_pct / 100.0)
    max_ktc_total = offer_ktc_total * (1.0 + max_ktc_gain_pct / 100.0)

    candidates: list[dict[str, Any]] = []
    for team, pool in teams_pool:
        for size in target_sizes:
            if len(pool) < size:
                continue
            for combo in combinations(pool, size):
                my_sum = sum(p["my_value"] for p in combo)
                if my_sum < min_my_total:
                    continue
                ktc_sum = sum(p["ktc_value"] for p in combo)
                if ktc_sum > max_ktc_total:
                    continue
                my_gain_pct = 100.0 * (my_sum - offer_my_total) / offer_my_total
                ktc_gain_pct = 100.0 * (ktc_sum - offer_ktc_total) / offer_ktc_total
                candidates.append(
                    {
                        "team": team.get("name"),
                        "owner_id": str(team.get("ownerId") or ""),
                        "size": size,
                        "players": [
                            {
                                "name": p["name"],
                                "position": p["position"],
                                "my_value": int(p["my_value"]),
                                "ktc_value": int(p["ktc_value"]),
                            }
                            for p in combo
                        ],
                        "my_total": int(round(my_sum)),
                        "ktc_total": int(round(ktc_sum)),
                        "my_gain_pct": round(my_gain_pct, 2),
                        "ktc_gain_pct": round(ktc_gain_pct, 2),
                        "arb_score": round(my_gain_pct - ktc_gain_pct, 2),
                    }
                )

    # Per-team cap first — prevents a single opposing roster from
    # swamping the results with 50 near-identical variations of the
    # same trade. Sort each team's candidates by arb_score desc, keep
    # the top ``per_team_limit``, then apply the global cap across
    # what's left.
    candidates.sort(key=lambda c: c["arb_score"], reverse=True)
    if per_team_limit and per_team_limit > 0:
        kept: list[dict[str, Any]] = []
        seen_per_team: dict[str, int] = {}
        for c in candidates:
            owner_id = c.get("owner_id") or c.get("team") or ""
            count = seen_per_team.get(owner_id, 0)
            if count >= per_team_limit:
                continue
            kept.append(c)
            seen_per_team[owner_id] = count + 1
        candidates = kept
    candidates = candidates[: max(1, int(limit))]

    offer_players = []
    for r in offer_rows:
        pair = _value_pair(r)
        offer_players.append(
            {
                "name": str(r.get("canonicalName") or ""),
                "position": str(r.get("position") or ""),
                "my_value": int(pair[0]) if pair else 0,
                "ktc_value": int(pair[1]) if pair else 0,
            }
        )

    return {
        "offer": {
            "team": my_team_name,
            "size": offer_size,
            "players": offer_players,
            "my_total": int(round(offer_my_total)),
            "ktc_total": int(round(offer_ktc_total)),
        },
        "candidates": candidates,
        "thresholds": {
            "min_my_gain_pct": min_my_gain_pct,
            "max_ktc_gain_pct": max_ktc_gain_pct,
            "limit": limit,
            "candidate_pool_per_team": candidate_pool_per_team,
            "per_team_limit": per_team_limit,
            "target_sizes": target_sizes,
            "positions": sorted(position_filter) if position_filter else [],
            "min_player_my_value": int(min_my_value_floor),
        },
        "warnings": warnings,
    }
