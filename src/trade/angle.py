"""Angle finder — player-specific trade-target arbitrage.

Given a user-owned player (or package of players), find players or
player-packages on other teams where the trade leans in the user's
favour under their own league's calibrated rankings but looks
fair-or-worse to the counterparty on the market index their position
indexes. Lets the user pitch trades that their leaguemates will
accept (the market they consult says "even") while actually gaining
value in their league-specific calibrated board.

Market anchor is per-position:
  * Offense (QB/RB/WR/TE), picks, everything else → KTC
  * IDP (DL/LB/DB) → IDP Trade Calculator

IDP leaguemates evaluate IDP trades on IDPTC, not KTC. A trade
between two DLs that looks 5% over-market on KTC is irrelevant — the
counterparty looks at IDPTC. So each player's "market value" is
drawn from the source their position indexes.

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

_IDP_POSITIONS: frozenset[str] = frozenset(
    {"DL", "DE", "DT", "EDGE", "NT", "LB", "ILB", "OLB", "MLB", "DB", "CB", "S", "SS", "FS"}
)


def _market_source_for(position: str | None) -> str:
    """Return the canonicalSiteValues key the counterparty would
    consult for this position. IDP positions compare on IDPTC;
    everything else (offense, picks, kickers, etc.) compares on KTC.
    """
    pos = str(position or "").strip().upper()
    if pos in _IDP_POSITIONS:
        return "idpTradeCalc"
    return "ktc"


def _value_pair(row: dict[str, Any]) -> tuple[float, float, str] | None:
    """Return (my_value, market_value, market_source_key) for a row.

    ``market_source_key`` is the canonicalSiteValues key used —
    ``"idpTradeCalc"`` for IDP rows, ``"ktc"`` otherwise. Returns
    ``None`` when either value is missing or non-positive.
    """
    my_val = row.get("rankDerivedValue")
    sites = row.get("canonicalSiteValues") or {}
    source = _market_source_for(row.get("position"))
    market_val = sites.get(source) if isinstance(sites, dict) else None
    try:
        my_num = float(my_val) if my_val is not None else 0.0
        market_num = float(market_val) if market_val is not None else 0.0
    except (TypeError, ValueError):
        return None
    if my_num <= 0 or market_num <= 0:
        return None
    return my_num, market_num, source


def find_angles(
    players_array: list[dict[str, Any]],
    selected_player_name: str,
    selected_team_owner_id: str,
    sleeper_teams: list[dict[str, Any]],
    *,
    min_my_gain_pct: float = 5.0,
    max_market_gain_pct: float = 5.0,
    limit: int = 50,
) -> dict[str, Any]:
    """Find trade-target candidates that lean in the user's favour.

    Each player's "market value" is drawn from the source that indexes
    their position — IDP Trade Calculator for DL/LB/DB, KTC for
    everyone else. The counterparty looks at the same market their
    player is listed in, so the threshold check matches their
    perspective.

    Parameters
    ----------
    players_array
        Canonical player rows (from build_api_data_contract's
        ``playersArray``). Each row must carry ``canonicalName``,
        ``rankDerivedValue`` (the calibrated my-league value), and
        a market value at ``canonicalSiteValues.idpTradeCalc`` for
        IDP or ``canonicalSiteValues.ktc`` for offense.
    max_market_gain_pct
        Maximum market value gain on the target side for the trade
        to still look "plausible" to the counterparty. Default 5%.
    limit
        Cap on returned candidates (sorted by arbitrage score desc).

    Returns
    -------
    dict
        ``{selected: {...}, candidates: [{...}, ...], warnings: [...]}``
        Market value is in ``market_value``; market source (``ktc``
        vs ``idpTradeCalc``) is in ``market_source``.
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
        sel_source = _market_source_for(selected_row.get("position"))
        return {
            "selected": {
                "name": selected_player_name,
                "my_value": selected_row.get("rankDerivedValue"),
                "market_value": None,
                "market_source": sel_source,
            },
            "candidates": [],
            "warnings": [
                f"{selected_player_name!r} is missing a my-league or {sel_source} value "
                "— Angle needs both to compute the arbitrage."
            ],
        }
    my_val_selected, market_val_selected, selected_market_source = pair

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
        my_val_target, market_val_target, target_market_source = target_pair

        my_gain = my_val_target - my_val_selected
        market_gain = market_val_target - market_val_selected
        my_gain_pct = 100.0 * my_gain / my_val_selected
        market_gain_pct = 100.0 * market_gain / market_val_selected

        if my_gain_pct < min_my_gain_pct:
            continue
        if market_gain_pct > max_market_gain_pct:
            continue

        candidates.append(
            {
                "name": target_name,
                "position": str(target_row.get("position") or ""),
                "team": owner_team.get("name") if owner_team else "(free agent)",
                "owner_id": str(owner_team.get("ownerId") or "") if owner_team else "",
                "my_value": int(my_val_target),
                "market_value": int(market_val_target),
                "market_source": target_market_source,
                "my_gain": int(round(my_gain)),
                "market_gain": int(round(market_gain)),
                "my_gain_pct": round(my_gain_pct, 2),
                "market_gain_pct": round(market_gain_pct, 2),
                "arb_score": round(my_gain_pct - market_gain_pct, 2),
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
            "market_value": int(market_val_selected),
            "market_source": selected_market_source,
        },
        "candidates": candidates,
        "thresholds": {
            "min_my_gain_pct": min_my_gain_pct,
            "max_market_gain_pct": max_market_gain_pct,
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
    max_market_gain_pct: float = 5.0,
    limit: int = 50,
    candidate_pool_per_team: int = 25,
    per_team_limit: int = 4,
    positions: list[str] | None = None,
    min_player_my_value: float = 0.0,
    target_team_owner_ids: list[str] | None = None,
    seed_player_names: list[str] | None = None,
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
        ``{team, size, players, my_total, market_total, my_gain_pct,
        market_gain_pct, arb_score}``. Sorted by ``arb_score`` desc.
        Market value is per-position: IDPTC for DL/LB/DB, KTC for
        offense/picks/other. Individual player rows carry
        ``market_value`` and ``market_source`` so the UI can label
        correctly.

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
            f"my-value or market value: {', '.join(missing[:5])}"
            + (" …" if len(missing) > 5 else "")
        )
    if not offer_rows:
        return {
            "offer": {"players": [], "size": 0, "my_total": 0, "market_total": 0},
            "candidates": [],
            "warnings": warnings or ["No valid offer-side players."],
        }

    offer_my_total = sum(
        _value_pair(r)[0] for r in offer_rows  # type: ignore[index]
    )
    offer_market_total = sum(
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
            my_v, market_v, market_source = pair
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
                    "market_value": market_v,
                    "market_source": market_source,
                }
            )
        pool.sort(key=lambda p: -p["my_value"])
        pool = pool[:candidate_pool_per_team]
        teams_pool.append((team, pool))

    # Pre-compute numeric thresholds in absolute-value terms so the
    # inner loop uses only arithmetic, no division.
    min_my_total = offer_my_total * (1.0 + min_my_gain_pct / 100.0)
    max_market_total = offer_market_total * (1.0 + max_market_gain_pct / 100.0)

    # Normalise target-team + seed inputs for constructed-package mode.
    target_ids: set[str] = {
        str(t).strip() for t in (target_team_owner_ids or []) if str(t).strip()
    }
    seed_names_requested = [
        str(n).strip() for n in (seed_player_names or []) if str(n).strip()
    ]

    candidates: list[dict[str, Any]] = []
    seed_names_set: set[str] = set()

    def _row_to_pool_entry(row: dict[str, Any]) -> dict[str, Any] | None:
        pair = _value_pair(row)
        if pair is None:
            return None
        my_v, market_v, market_source = pair
        return {
            "name": str(row.get("canonicalName") or row.get("displayName") or ""),
            "position": str(row.get("position") or ""),
            "my_value": my_v,
            "market_value": market_v,
            "market_source": market_source,
        }

    def _make_candidate(
        combo: tuple[dict[str, Any], ...],
        team_label: str,
        owner_id_label: str,
    ) -> dict[str, Any] | None:
        my_sum = sum(p["my_value"] for p in combo)
        if my_sum < min_my_total:
            return None
        market_sum = sum(p["market_value"] for p in combo)
        if market_sum > max_market_total:
            return None
        my_gain_pct = 100.0 * (my_sum - offer_my_total) / offer_my_total
        market_gain_pct = 100.0 * (market_sum - offer_market_total) / offer_market_total
        return {
            "team": team_label,
            "owner_id": owner_id_label,
            "size": len(combo),
            "players": [
                {
                    "name": p["name"],
                    "position": p["position"],
                    "my_value": int(p["my_value"]),
                    "market_value": int(p["market_value"]),
                    "market_source": p["market_source"],
                }
                for p in combo
            ],
            "my_total": int(round(my_sum)),
            "market_total": int(round(market_sum)),
            "my_gain_pct": round(my_gain_pct, 2),
            "market_gain_pct": round(market_gain_pct, 2),
            "arb_score": round(my_gain_pct - market_gain_pct, 2),
        }

    if target_ids:
        # ── Constructed-package mode ─────────────────────────────
        # User picked 1 or 2 specific opposing teams. Pool is the
        # union of those teams' candidates; all seed players are
        # required in every result (seeds bypass position/value
        # filters because the user explicitly asked for them).
        target_teams: list[dict[str, Any]] = []
        combined_pool_by_name: dict[str, dict[str, Any]] = {}
        owner_by_pool_name: dict[str, str] = {}
        # Seed ownership lookup: covers *all* players on target teams
        # (not just ones that survived the filter cuts into ``pool``),
        # so seed resolution is O(1) per seed instead of scanning every
        # target team's roster for each requested seed name.
        owner_by_all_player: dict[str, str] = {}
        target_team_names: list[str] = []
        target_team_owners: list[str] = []
        for team, pool in teams_pool:
            owner = str(team.get("ownerId") or "")
            if owner not in target_ids:
                continue
            target_teams.append(team)
            target_team_names.append(str(team.get("name") or ""))
            target_team_owners.append(owner)
            for entry in pool:
                combined_pool_by_name[entry["name"]] = entry
                owner_by_pool_name[entry["name"]] = owner
            for pname in team.get("players") or []:
                owner_by_all_player.setdefault(str(pname), owner)

        # Resolve seeds. Seeds must be owned by one of the target
        # teams and bypass the filter pool — they're mandatory.
        seed_entries: list[dict[str, Any]] = []
        missing_seeds: list[str] = []
        wrong_team_seeds: list[str] = []
        for sname in seed_names_requested:
            row = by_name.get(sname)
            if not row:
                missing_seeds.append(sname)
                continue
            # O(1) ownership lookup against the precomputed roster map.
            owner_of_seed = owner_by_all_player.get(sname)
            if owner_of_seed is None:
                wrong_team_seeds.append(sname)
                continue
            entry = _row_to_pool_entry(row)
            if entry is None:
                missing_seeds.append(sname)
                continue
            seed_entries.append(entry)
            # Ensure seeds are present in the combined pool so they
            # can participate in filter-respecting combo selection
            # (but seeds themselves bypass the filter cuts above).
            combined_pool_by_name.setdefault(entry["name"], entry)
            owner_by_pool_name.setdefault(entry["name"], owner_of_seed)
        if missing_seeds:
            warnings.append(
                f"Dropped {len(missing_seeds)} seed player(s) with missing data: "
                f"{', '.join(missing_seeds[:5])}"
                + (" …" if len(missing_seeds) > 5 else "")
            )
        if wrong_team_seeds:
            warnings.append(
                f"Ignored {len(wrong_team_seeds)} seed player(s) not on any selected "
                f"target team: {', '.join(wrong_team_seeds[:5])}"
                + (" …" if len(wrong_team_seeds) > 5 else "")
            )

        seed_names_set = {e["name"] for e in seed_entries}
        non_seed_pool = [
            e for e in combined_pool_by_name.values() if e["name"] not in seed_names_set
        ]
        # Sort non-seed pool by my_value for deterministic order.
        non_seed_pool.sort(key=lambda p: -p["my_value"])

        team_label = " + ".join(target_team_names) or "(selected teams)"
        owner_label = "+".join(target_team_owners) or ",".join(sorted(target_ids))

        for size in target_sizes:
            if size < len(seed_entries):
                continue  # can't fit all required seeds
            free_slots = size - len(seed_entries)
            if free_slots == 0:
                combo = tuple(seed_entries)
                cand = _make_candidate(combo, team_label, owner_label)
                if cand is not None:
                    candidates.append(cand)
                continue
            if len(non_seed_pool) < free_slots:
                continue
            for fillers in combinations(non_seed_pool, free_slots):
                combo = tuple(seed_entries) + fillers
                cand = _make_candidate(combo, team_label, owner_label)
                if cand is not None:
                    candidates.append(cand)
    else:
        # ── Default mode: one team per candidate package ──
        # This is the existing behaviour — each opposing team
        # contributes its own packages independently.
        for team, pool in teams_pool:
            for size in target_sizes:
                if len(pool) < size:
                    continue
                for combo in combinations(pool, size):
                    cand = _make_candidate(
                        combo,
                        str(team.get("name") or ""),
                        str(team.get("ownerId") or ""),
                    )
                    if cand is not None:
                        candidates.append(cand)

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
                "market_value": int(pair[1]) if pair else 0,
                "market_source": pair[2] if pair else _market_source_for(r.get("position")),
            }
        )

    return {
        "offer": {
            "team": my_team_name,
            "size": offer_size,
            "players": offer_players,
            "my_total": int(round(offer_my_total)),
            "market_total": int(round(offer_market_total)),
        },
        "candidates": candidates,
        "thresholds": {
            "min_my_gain_pct": min_my_gain_pct,
            "max_market_gain_pct": max_market_gain_pct,
            "limit": limit,
            "candidate_pool_per_team": candidate_pool_per_team,
            "per_team_limit": per_team_limit,
            "target_sizes": target_sizes,
            "positions": sorted(position_filter) if position_filter else [],
            "min_player_my_value": int(min_my_value_floor),
            "target_team_owner_ids": sorted(target_ids) if target_ids else [],
            "seed_player_names": sorted(seed_names_set) if target_ids else [],
        },
        "warnings": warnings,
    }
