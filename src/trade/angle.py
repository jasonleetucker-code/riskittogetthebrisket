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
from typing import Any, Iterable, Sequence

_IDP_POSITIONS: frozenset[str] = frozenset(
    {"DL", "DE", "DT", "EDGE", "NT", "LB", "ILB", "OLB", "MLB", "DB", "CB", "S", "SS", "FS"}
)

# KTC-style Value Adjustment (V2) — ports the frontend formula in
# ``frontend/lib/trade-logic.js`` (``_vaFromSortedSides``) so the Angle
# engine stops treating a package of 4 filler players as equivalent to
# Trade-fairness math is now delegated to ``src.trade.ktc_va``, the
# Python port of KTC's actual algorithm (PR #335 ported it to JS;
# this replaced the V2 regression-fit constants below in 2026-04-27).
# The legacy V2 ``_VA_*`` coefficients (calibrated against 13 trades)
# disagreed materially with what KTC.com displays, leading to Angle
# Finder grading trades differently than the trade calculator.
#
# Arbitrage math was previously pure sum-of-raw-totals, which is wrong
# for uneven sizes: 3 stars for 4 scrubs can look fair on market and a
# big win on my-value in raw terms, yet no leaguemate would accept it.
# VA injects the consolidation premium on the SMALLER side — so the
# side receiving more studs sees its effective total climb, and the
# thresholds get evaluated on the adjusted numbers.
from src.trade.ktc_va import (
    adjusted_pair_totals as _adjusted_pair_totals,  # noqa: F401
    ktc_adjust_package,
)


def _value_adjustment(small: Sequence[float], large: Sequence[float]) -> float:
    """KTC's VA from the perspective of ``small`` as team1.

    Returns the VA magnitude when KTC awards it to the ``small`` side
    (``small`` is team1 → side==1), else 0.0.  Thin compat shim around
    :func:`ktc_adjust_package` so existing callers (tests, importers)
    keep working with the legacy float-return signature.

    The legacy V2 implementation lived inline here; it was replaced
    with KTC's actual algorithm via :mod:`src.trade.ktc_va` so the
    Angle Finder grades trades the same way the trade calculator
    displays them (PR follow-up to #335).
    """
    small_sorted = sorted((float(v) for v in small), reverse=True)
    large_sorted = sorted((float(v) for v in large), reverse=True)
    if not small_sorted or not large_sorted:
        return 0.0
    result = ktc_adjust_package(small_sorted, large_sorted)
    if not result.displayed or result.value <= 0 or result.side != 1:
        return 0.0
    return float(result.value)


def _is_idp_position(position: Any) -> bool:
    return str(position or "").strip().upper() in _IDP_POSITIONS


def _market_source_for(position: str | None) -> str:
    """Return the canonicalSiteValues key the counterparty would
    consult for this position. IDP positions compare on IDPTC;
    everything else (offense, picks, kickers, etc.) compares on KTC.

    Note: ``ktc`` was retired from the blend 2026-04-28, but the
    CSV still loads into canonicalSiteValues — it remains the
    canonical retail-market signal a trade counterparty would see
    on keeptradecut.com (the public site shows the standard SF
    view by default), so the angle finder still compares against
    it.
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
    include_idp: bool = False,
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
    include_idp
        When ``False`` (default) IDP positions (DL/LB/DB and their
        sub-positions) are filtered OUT of the candidate pool entirely.
        Most managers don't value IDP the way KTC/our-board scores
        them, so the default keeps counter-packages offense+picks
        only. Set ``True`` (or explicitly include an IDP player in
        the offer / seeds) to allow IDP candidates. Offer-side and
        user-selected seeds are never filtered — the user's explicit
        choices always win.

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
            # Per-player filters: position allow-list, my-value floor,
            # and the IDP gate. IDP players get filtered out of the
            # candidate pool by default because most leaguemates don't
            # gravitate toward them — setting include_idp=True (or an
            # IDP position in ``positions``) re-admits them.
            row_pos = str(row.get("position") or "").strip().upper()
            if position_filter is not None and row_pos not in position_filter:
                continue
            if not include_idp and row_pos in _IDP_POSITIONS:
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

    # Offer-side value lists (sorted descending) used by the VA path
    # below. We keep raw totals available for display/back-compat.
    offer_my_values = sorted(
        (float(_value_pair(r)[0]) for r in offer_rows), reverse=True,  # type: ignore[index]
    )
    offer_market_values = sorted(
        (float(_value_pair(r)[1]) for r in offer_rows), reverse=True,  # type: ignore[index]
    )

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
        # Apply KTC-style Value Adjustment so consolidation packages
        # (e.g. 3 studs vs 4 filler pieces whose raws happen to match)
        # don't slip through the thresholds on pure sum-of-raws.
        counter_my_values = [p["my_value"] for p in combo]
        counter_market_values = [p["market_value"] for p in combo]
        (
            counter_my_adj,
            offer_my_adj,
            counter_my_va,
            offer_my_va,
        ) = _adjusted_pair_totals(counter_my_values, offer_my_values)
        (
            counter_market_adj,
            offer_market_adj,
            counter_market_va,
            offer_market_va,
        ) = _adjusted_pair_totals(counter_market_values, offer_market_values)

        if offer_my_adj <= 0 or offer_market_adj <= 0:
            return None
        my_gain_pct = 100.0 * (counter_my_adj - offer_my_adj) / offer_my_adj
        market_gain_pct = (
            100.0 * (counter_market_adj - offer_market_adj) / offer_market_adj
        )
        if my_gain_pct < min_my_gain_pct:
            return None
        if market_gain_pct > max_market_gain_pct:
            return None

        my_sum = sum(counter_my_values)
        market_sum = sum(counter_market_values)
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
            "my_total_adjusted": int(round(counter_my_adj)),
            "market_total_adjusted": int(round(counter_market_adj)),
            "my_value_adjustment": int(round(counter_my_va)),
            "market_value_adjustment": int(round(counter_market_va)),
            "offer_my_total_adjusted": int(round(offer_my_adj)),
            "offer_market_total_adjusted": int(round(offer_market_adj)),
            "offer_my_value_adjustment": int(round(offer_my_va)),
            "offer_market_value_adjustment": int(round(offer_market_va)),
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
            "include_idp": bool(include_idp),
        },
        "warnings": warnings,
    }


def find_acquisition_packages(
    players_array: list[dict[str, Any]],
    desired_player_names: list[str],
    selected_team_owner_id: str,
    sleeper_teams: list[dict[str, Any]],
    *,
    min_my_gain_pct: float = 5.0,
    max_market_gain_pct: float = 5.0,
    limit: int = 50,
    candidate_pool: int = 25,
    positions: list[str] | None = None,
    min_player_my_value: float = 0.0,
    include_idp: bool = False,
) -> dict[str, Any]:
    """Find offer-side packages from the user's roster that acquire a
    fixed set of desired players from other teams.

    Inverse of :func:`find_angle_packages`. The user picks players on
    opposing rosters they want to acquire; this enumerates combinations
    of their own roster (size within ±1 of the desired count) and
    keeps those that (a) leave the user ahead on my-value by at least
    ``min_my_gain_pct`` and (b) look fair-or-better to the counterparty
    on the market the counterparty consults (IDPTC for IDP, KTC
    otherwise), gap ≤ ``max_market_gain_pct``.

    Parameters
    ----------
    desired_player_names
        Canonical names of players the user wants to acquire. They
        must each be owned by a team OTHER than ``selected_team_owner_id``.
        Any missing or user-owned names are dropped with a warning.
    candidate_pool
        Top-N players (by ``rankDerivedValue``) from the user's own
        roster to enumerate combinations from. Caps combinatorial
        explosion.

    Returns
    -------
    dict
        ``{acquire: {...}, candidates: [{...}], thresholds, warnings}``
        where each candidate is an offer-side package from the user's
        roster satisfying the arbitrage constraints vs the fixed
        desired package. Sorted by ``arb_score`` desc.
    """
    warnings: list[str] = []

    by_name: dict[str, dict[str, Any]] = {}
    for row in players_array:
        name = str(row.get("canonicalName") or row.get("displayName") or "")
        if name and name not in by_name:
            by_name[name] = row

    # Locate the user's team and build a reverse index so we can
    # validate desired players are on opposing rosters.
    my_team: dict[str, Any] | None = None
    owner_by_player: dict[str, str] = {}
    for team in sleeper_teams:
        owner = str(team.get("ownerId") or "")
        if owner == selected_team_owner_id:
            my_team = team
        for pname in team.get("players") or []:
            owner_by_player[str(pname)] = owner

    if my_team is None:
        return {
            "acquire": {
                "players": [],
                "size": 0,
                "my_total": 0,
                "market_total": 0,
                "targets": [],
            },
            "candidates": [],
            "warnings": [f"Owner {selected_team_owner_id!r} not found in sleeper rosters."],
        }

    # Resolve desired players. Drop unknowns, self-owned, and rows
    # missing values — each with a warning.
    desired_rows: list[dict[str, Any]] = []
    desired_owners: dict[str, str] = {}
    missing: list[str] = []
    own_roster: list[str] = []
    for name in desired_player_names:
        name = str(name).strip()
        if not name:
            continue
        row = by_name.get(name)
        if not row:
            missing.append(name)
            continue
        owner_of = owner_by_player.get(name)
        if owner_of == selected_team_owner_id:
            own_roster.append(name)
            continue
        pair = _value_pair(row)
        if pair is None:
            missing.append(name)
            continue
        desired_rows.append(row)
        desired_owners[name] = owner_of or ""
    if missing:
        warnings.append(
            f"Dropped {len(missing)} desired player(s) with missing data: "
            f"{', '.join(missing[:5])}"
            + (" …" if len(missing) > 5 else "")
        )
    if own_roster:
        warnings.append(
            f"Dropped {len(own_roster)} player(s) already on your roster: "
            f"{', '.join(own_roster[:5])}"
            + (" …" if len(own_roster) > 5 else "")
        )
    if not desired_rows:
        return {
            "acquire": {
                "players": [],
                "size": 0,
                "my_total": 0,
                "market_total": 0,
                "targets": [],
            },
            "candidates": [],
            "warnings": warnings or ["No valid desired-acquisition players."],
        }

    desired_my_total = sum(_value_pair(r)[0] for r in desired_rows)  # type: ignore[index]
    desired_market_total = sum(_value_pair(r)[1] for r in desired_rows)  # type: ignore[index]
    desired_size = len(desired_rows)

    target_sizes = sorted({max(1, desired_size - 1), desired_size, desired_size + 1})

    position_filter: set[str] | None = None
    if positions:
        position_filter = {str(p).strip().upper() for p in positions if str(p).strip()}
        if not position_filter:
            position_filter = None
    min_my_value_floor = max(0.0, float(min_player_my_value or 0.0))

    # Build offer-side pool from the user's own roster.
    desired_name_set = {str(r.get("canonicalName") or "") for r in desired_rows}
    pool: list[dict[str, Any]] = []
    for pname in my_team.get("players") or []:
        pname = str(pname)
        if pname in desired_name_set:
            continue  # not on user's roster anyway, but guard
        row = by_name.get(pname)
        if not row:
            continue
        pair = _value_pair(row)
        if pair is None:
            continue
        my_v, market_v, market_source = pair
        row_pos = str(row.get("position") or "").strip().upper()
        if position_filter is not None and row_pos not in position_filter:
            continue
        # IDP gate — see docstring on find_angle_packages. Fixed side
        # (desired players) is never filtered; this only restricts the
        # offer-side pool built from the user's own roster.
        if not include_idp and row_pos in _IDP_POSITIONS:
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
    pool = pool[: max(1, int(candidate_pool))]

    # Desired-side value lists (sorted descending) for the VA path.
    desired_my_values = sorted(
        (float(_value_pair(r)[0]) for r in desired_rows), reverse=True,  # type: ignore[index]
    )
    desired_market_values = sorted(
        (float(_value_pair(r)[1]) for r in desired_rows), reverse=True,  # type: ignore[index]
    )

    def _make_candidate(combo: tuple[dict[str, Any], ...]) -> dict[str, Any] | None:
        # Arbitrage math: user receives ``desired_*``, gives up
        # ``offer_*``. Apply KTC-style VA so consolidation (e.g. giving
        # 4 filler to land 3 studs) isn't treated as a fair swap just
        # because raw totals line up — the consolidated side carries a
        # premium on both my-value and market-value.
        offer_my_values = [p["my_value"] for p in combo]
        offer_market_values = [p["market_value"] for p in combo]
        (
            desired_my_adj,
            offer_my_adj,
            desired_my_va,
            offer_my_va,
        ) = _adjusted_pair_totals(desired_my_values, offer_my_values)
        (
            desired_market_adj,
            offer_market_adj,
            desired_market_va,
            offer_market_va,
        ) = _adjusted_pair_totals(desired_market_values, offer_market_values)

        if offer_my_adj <= 0 or offer_market_adj <= 0:
            return None
        my_gain_pct = 100.0 * (desired_my_adj - offer_my_adj) / offer_my_adj
        market_gain_pct = (
            100.0 * (desired_market_adj - offer_market_adj) / offer_market_adj
        )
        if my_gain_pct < min_my_gain_pct:
            return None
        if market_gain_pct > max_market_gain_pct:
            return None

        offer_my_sum = sum(offer_my_values)
        offer_market_sum = sum(offer_market_values)
        return {
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
            "my_total": int(round(offer_my_sum)),
            "market_total": int(round(offer_market_sum)),
            "my_total_adjusted": int(round(offer_my_adj)),
            "market_total_adjusted": int(round(offer_market_adj)),
            "my_value_adjustment": int(round(offer_my_va)),
            "market_value_adjustment": int(round(offer_market_va)),
            "acquire_my_total_adjusted": int(round(desired_my_adj)),
            "acquire_market_total_adjusted": int(round(desired_market_adj)),
            "acquire_my_value_adjustment": int(round(desired_my_va)),
            "acquire_market_value_adjustment": int(round(desired_market_va)),
            "my_gain_pct": round(my_gain_pct, 2),
            "market_gain_pct": round(market_gain_pct, 2),
            "arb_score": round(my_gain_pct - market_gain_pct, 2),
        }

    candidates: list[dict[str, Any]] = []
    for size in target_sizes:
        if len(pool) < size:
            continue
        for combo in combinations(pool, size):
            cand = _make_candidate(combo)
            if cand is not None:
                candidates.append(cand)

    candidates.sort(key=lambda c: c["arb_score"], reverse=True)
    candidates = candidates[: max(1, int(limit))]

    desired_players = []
    for r in desired_rows:
        pair = _value_pair(r)
        dname = str(r.get("canonicalName") or "")
        desired_players.append(
            {
                "name": dname,
                "position": str(r.get("position") or ""),
                "my_value": int(pair[0]) if pair else 0,
                "market_value": int(pair[1]) if pair else 0,
                "market_source": pair[2] if pair else _market_source_for(r.get("position")),
                "owner_id": desired_owners.get(dname, ""),
            }
        )

    # Deduplicated list of target teams the desired players come from.
    targets: list[dict[str, Any]] = []
    seen_owners: set[str] = set()
    for team in sleeper_teams:
        owner = str(team.get("ownerId") or "")
        if owner in desired_owners.values() and owner not in seen_owners:
            targets.append({"team": str(team.get("name") or ""), "owner_id": owner})
            seen_owners.add(owner)

    return {
        "acquire": {
            "team": my_team.get("name"),
            "size": desired_size,
            "players": desired_players,
            "my_total": int(round(desired_my_total)),
            "market_total": int(round(desired_market_total)),
            "targets": targets,
        },
        "candidates": candidates,
        "thresholds": {
            "min_my_gain_pct": min_my_gain_pct,
            "max_market_gain_pct": max_market_gain_pct,
            "limit": limit,
            "candidate_pool": candidate_pool,
            "target_sizes": target_sizes,
            "positions": sorted(position_filter) if position_filter else [],
            "min_player_my_value": int(min_my_value_floor),
            "include_idp": bool(include_idp),
        },
        "warnings": warnings,
    }
