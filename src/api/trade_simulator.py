"""Trade simulator — what-if delta for a proposed trade.

Given the signed-in user's team and a proposed swap
(``playersIn[]`` / ``playersOut[]`` / ``picksIn[]`` / ``picksOut[]``),
return the delta on the usual terminal aggregates:

* ``totalValue`` before / after / delta
* ``tiers`` (elite / high / mid / depth counts) before / after
* ``byPosition`` (per-position value share) before / after
* Per-asset resolution so the caller can render "you gave X value,
  received Y value" breakdowns in the UI

Design: pure function over the live contract — no side effects, no
persistence.  Anyone can simulate anything, the live ``/api/data``
contract doesn't change.

Uses the same helpers as ``terminal.py`` (``_row_value``,
``_tier_bucket``, ``_normalize_pos``) so the simulator's numbers
exactly match what the terminal panel shows — a user can't end up
staring at a $13 delta in the header and a $147 delta in the
simulator for the same swap.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from src.api.terminal import (
    _build_row_index,
    _normalize_pos,
    _players_array,
    _row_rank,
    _row_value,
    _tier_bucket,
    POS_GROUPS,
)




def _resolve_asset(
    name: str,
    *,
    row_index: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    """Resolve a single display name to a summary dict for the
    simulator output.  Matches ``terminal.py``'s rowValue semantics.

    One canonical value per asset.  This used to take an
    ``offense_only`` flag and substitute a second, IDP-disabled board
    whenever the trade being evaluated contained no defender — so the
    same player was worth two different numbers in one league on one
    day, and the substitution reached the manager's entire untraded
    roster as well as the legs being traded.  See W29-F001 and
    ``tests/api/test_one_canonical_value_per_asset.py``.
    """
    if not name:
        return None
    key = str(name).strip().lower()
    row = row_index.get(key)
    if not row:
        # C1-U6: roster/trade pick labels arrive in overlay grammars
        # ("2027 1st", "2026 1.03 (own)") that are not board row names —
        # measured silently dropping every roster pick from the
        # before/after aggregates (no counter, no trace).  Route the
        # miss through the canonical identity owner: parse the label
        # (never a guess — an unparseable string stays unresolved),
        # resolve to the market reference for today's clock, and retry
        # the index at the ref's board row name.  The board now carries
        # a value for every valid grade — tier rows, generic-grade rows,
        # and slot rows — so a parsed pick label resolves instead of
        # vanishing.
        from src.identity.picks import market_resolution, parse_pick_label

        parsed = parse_pick_label(str(name))
        if parsed is None:
            return None
        from src.api.data_contract import current_rookie_draft_year

        # The label's OWN grade first: a parsed tier ("2027 Mid 1st
        # (from X)") PROVES the tier, and the vendor-priced tier row
        # outranks any derivation — falling straight to
        # market_resolution here would discard the proven refinement
        # and price the pick at the generic-grade PRIOR EV
        # (final-review hardening).  market_resolution then handles
        # what the label alone cannot: mapping a known slot onto the
        # right grade for the clock (slot rows exist only for the
        # active draft year).
        row = None
        own_name = parsed.market_ref.board_row_name()
        if own_name:
            row = row_index.get(own_name.strip().lower())
        if not row:
            res = market_resolution(
                year=parsed.year,
                round_num=parsed.round_num,
                slot=parsed.slot,
                current_draft_year=current_rookie_draft_year(),
            )
            board_name = res.ref.board_row_name()
            if not board_name:
                return None
            row = row_index.get(board_name.strip().lower())
        if not row:
            return None
    # A pick row the pipeline deliberately left valueless (an
    # alias-suppressed current-year tier) must not price at 0 —
    # zero-as-missing is the exact defect class C1-PICK-01 forbids.
    # Follow the alias to the centre slot; if no positive value exists
    # anywhere, stay unresolved (honest) rather than counting 0.
    if row.get("assetClass") == "pick" and _row_value(row) <= 0:
        alias = str(row.get("pickAliasFor") or "").strip().lower()
        alias_row = row_index.get(alias) if alias else None
        if alias_row is not None and _row_value(alias_row) > 0:
            row = alias_row
        else:
            return None
    value = int(_row_value(row))
    pos = _normalize_pos(row.get("pos") or row.get("position"))
    age = row.get("age")
    # ``pos`` collapses DL/LB/DB to "IDP" for terminal aggregation;
    # ``basePos`` preserves the distinction so team_impact can apply
    # per-position starter rules (DL/LB/DB are separate slots in
    # rosterSettings.starters).
    from src.utils.name_clean import normalize_position

    base_pos = normalize_position(row.get("pos") or row.get("position"))
    return {
        "name": row.get("displayName") or row.get("canonicalName") or name,
        # The label the CALLER used, kept alongside the board row name.
        # Two roster picks can share a board row ("2027 Mid 1st") while
        # being different assets ("(own)" vs "(from Team X)"), so the
        # after-state removal below needs the distinction the board row
        # deliberately does not carry.
        "sourceLabel": str(name),
        "pos": pos,
        "basePos": base_pos or pos,
        "value": value,
        "rank": _row_rank(row),
        "tier": _tier_bucket(value),
        "age": int(age) if isinstance(age, (int, float)) and age else None,
        "assetClass": row.get("assetClass") or ("pick" if pos == "PICK" else "player"),
    }


def _aggregate(assets: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute totalValue / tiers / byPosition for a roster list of
    resolved asset dicts.  Matches the shape ``_compute_portfolio_insights``
    emits so the simulator UI can reuse the same renderers.
    """
    total = 0
    tiers = {"elite": 0, "high": 0, "mid": 0, "depth": 0}
    by_position: dict[str, dict[str, int]] = {g: {"count": 0, "value": 0} for g in POS_GROUPS}
    for a in assets:
        v = int(a.get("value") or 0)
        total += v
        tiers[_tier_bucket(v)] += 1
        bucket = a.get("pos") if a.get("pos") in POS_GROUPS else None
        if bucket:
            by_position[bucket]["count"] += 1
            by_position[bucket]["value"] += v
    return {
        "totalValue": total,
        "tiers": tiers,
        "byPosition": by_position,
    }


def _diff(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    """Pretty-print the aggregate delta for the UI."""
    delta = {
        "totalValue": int(after["totalValue"]) - int(before["totalValue"]),
        "tiers": {
            k: int(after["tiers"].get(k, 0)) - int(before["tiers"].get(k, 0))
            for k in ("elite", "high", "mid", "depth")
        },
        "byPosition": {
            g: {
                "count": int(after["byPosition"][g]["count"])
                - int(before["byPosition"][g]["count"]),
                "value": int(after["byPosition"][g]["value"])
                - int(before["byPosition"][g]["value"]),
            }
            for g in POS_GROUPS
        },
    }
    return delta


def simulate_trade(
    contract: dict[str, Any],
    *,
    resolved_team: dict[str, Any] | None,
    players_in: list[str] | None = None,
    players_out: list[str] | None = None,
    picks_in: list[str] | None = None,
    picks_out: list[str] | None = None,
    roster_settings: dict[str, Any] | None = None,
    league_key: str | None = None,
) -> dict[str, Any]:
    """Build the simulator payload for a single hypothetical trade.

    Returns::

        {
          "team":          {ownerId, name, rosterId},
          "before":        {totalValue, tiers, byPosition},
          "after":         {totalValue, tiers, byPosition},
          "delta":         {totalValue, tiers, byPosition},
          "receiving":     [{name, pos, value, rank, tier}],  # resolved
          "sending":       [{name, pos, value, rank, tier}],
          "unresolvedIn":  [str, ...],   # names we couldn't match
          "unresolvedOut": [str, ...],
          "equity":        int,          # net value to team (positive = good)
          "rosterCapacity":{...},         # see src/trade/roster_capacity
          "finalLegalRoster":{...},       # C3-CAP-01 step 5-6: cleanup applied,
                                          #   roster intelligence rerun on the
                                          #   roster that actually results
        }

    Never mutates the contract or persists.  Pure function over the
    passed inputs; call repeatedly for different what-ifs.

    ``picks_in`` / ``picks_out`` are treated identically to players —
    the contract's ``players`` dict carries pick rows by their
    canonical display name ("2026 early 1st", etc.) and they resolve
    the same way through ``row_index``.
    """
    players_in = [p for p in (players_in or []) if p]
    players_out = [p for p in (players_out or []) if p]
    picks_in = [p for p in (picks_in or []) if p]
    picks_out = [p for p in (picks_out or []) if p]

    rows = _players_array(contract)
    row_index = _build_row_index(rows)

    team_block = None
    current_players: list[str] = []
    if resolved_team and isinstance(resolved_team, dict):
        team_block = {
            "ownerId": str(resolved_team.get("ownerId") or ""),
            "name": str(resolved_team.get("name") or ""),
            "rosterId": resolved_team.get("roster_id"),
        }
        current_players = [str(p) for p in (resolved_team.get("players") or [])]

    # Every asset resolves at its canonical board value, whatever else is
    # in the trade.  The composition of the question being asked does not
    # change what the assets are worth (W29-F001).

    def _resolve_many(names: list[str]) -> tuple[list[dict[str, Any]], list[str]]:
        resolved: list[dict[str, Any]] = []
        missing: list[str] = []
        for n in names:
            hit = _resolve_asset(n, row_index=row_index)
            if hit is None:
                missing.append(n)
            else:
                resolved.append(hit)
        return resolved, missing

    # BEFORE state: the team's current roster + picks, resolved.
    before_assets: list[dict[str, Any]] = []
    for name in current_players:
        hit = _resolve_asset(name, row_index=row_index)
        if hit is not None:
            before_assets.append(hit)
    current_picks = (
        [str(p) for p in (resolved_team.get("picks") or [])]
        if resolved_team and isinstance(resolved_team, dict)
        else []
    )
    for pick in current_picks:
        hit = _resolve_asset(pick, row_index=row_index)
        if hit is not None:
            before_assets.append(hit)

    # Receiving / sending sides of the trade.
    receiving, unresolved_in = _resolve_many([*players_in, *picks_in])
    sending, unresolved_out = _resolve_many([*players_out, *picks_out])

    # AFTER state: drop the sent, add the received.
    #
    # Removal is by MULTIPLICITY, not by set membership (repaired
    # 2026-08-16, C1-U6 follow-up 10).  The old code built a set of
    # lowercased names and dropped every roster asset whose name was in
    # it, so a manager holding two picks that share a board row — a
    # 2027 1st of their own and a 2027 1st acquired from another team —
    # lost BOTH from the after-state by trading ONE.  The board row is
    # deliberately one row for both (that is what a tier grade means);
    # the roster holds two assets.  Collapsing distinct assets by
    # display name is the defect class C1-U3 exists to prevent, and it
    # only became visible once roster picks resolved at all.
    #
    # Exact caller labels first (they distinguish "(own)" from
    # "(from X)"), then board identity for anything unmatched — each
    # consuming one occurrence, never all of them.
    def _label_key(asset: dict[str, Any]) -> str:
        return str(asset.get("sourceLabel") or asset.get("name") or "").strip().lower()

    def _board_key(asset: dict[str, Any]) -> str:
        return str(asset.get("name") or "").strip().lower()

    sent_by_label = Counter(_label_key(a) for a in sending)
    consumed_label: Counter[str] = Counter()
    kept: list[dict[str, Any]] = []
    for asset in before_assets:
        key = _label_key(asset)
        if consumed_label[key] < sent_by_label.get(key, 0):
            consumed_label[key] += 1
            continue
        kept.append(asset)

    unmatched = []
    for asset in sending:
        key = _label_key(asset)
        if consumed_label[key] > 0:
            consumed_label[key] -= 1
        else:
            unmatched.append(asset)

    sent_by_board = Counter(_board_key(a) for a in unmatched)
    consumed_board: Counter[str] = Counter()
    after_assets: list[dict[str, Any]] = []
    for asset in kept:
        key = _board_key(asset)
        if consumed_board[key] < sent_by_board.get(key, 0):
            consumed_board[key] += 1
            continue
        after_assets.append(asset)
    after_assets.extend(receiving)

    before = _aggregate(before_assets)
    after = _aggregate(after_assets)
    delta = _diff(before, after)

    equity = sum(a["value"] for a in receiving) - sum(a["value"] for a in sending)

    response: dict[str, Any] = {
        "team": team_block,
        "before": before,
        "after": after,
        "delta": delta,
        "receiving": receiving,
        "sending": sending,
        "unresolvedIn": unresolved_in,
        "unresolvedOut": unresolved_out,
        "equity": int(equity),
    }

    # Roster-shape-aware fit verdict.  Only computed when we have both
    # a resolved team and league roster settings — free-analysis mode
    # (no team selected) and contracts without league context skip
    # this block entirely.
    if resolved_team and roster_settings:
        from src.trade import team_impact

        impact = team_impact.compute(
            before_assets=before_assets,
            after_assets=after_assets,
            receiving=receiving,
            sending=sending,
            equity=int(equity),
            roster_settings=roster_settings,
        )
        if impact is not None:
            response["teamImpact"] = impact

    # Roster capacity: does the roster still fit, and if not, who goes?
    #
    # REPORTED, never enforced.  ``roster_intel.packages._check_legality``
    # REFUSES an over-cap package, which is right for a generator choosing what
    # to propose and wrong here — this endpoint answers a question the user
    # typed in, and "your trade is illegal so here is nothing" is a worse
    # answer than "your trade is legal once you release these two, worth
    # 3,021".  Both consume the same counting rule.
    #
    # PLAYERS only.  Draft picks do not occupy Sleeper roster spots: measured
    # on the live board, ``rosterSize`` is 58, the largest roster holds exactly
    # 58 players, and those same teams hold 10-23 picks besides.  So
    # ``picks_in`` / ``picks_out`` are deliberately not passed.
    if resolved_team:
        try:
            from src.trade.roster_capacity import (  # noqa: PLC0415
                assess_roster_capacity,
                build_capacity_context,
                simulate_final_legal_roster,
            )
            from src.ros.lineup import configured_slot_eligibility  # noqa: PLC0415

            capacity_context = build_capacity_context(
                contract,
                league_key,
                resolved_team,
                roster_settings=roster_settings,
            )
            capacity = assess_roster_capacity(
                capacity_context,
                incoming_players=players_in,
                outgoing_players=players_out,
            )
            response["rosterCapacity"] = capacity.to_dict()

            # C3-CAP-01's last two steps: apply the optimal cleanup, then rerun
            # roster intelligence on the roster that actually results.  The
            # capacity block above says WHO must go; it cannot say what the
            # lineup looks like once they have, because roster effects are
            # set-dependent.  Opt-in and single-trade only — 9 ms measured on a
            # 58-man roster, which is cheap here and is not cheap multiplied by
            # a generator's candidate list.
            response["finalLegalRoster"] = simulate_final_legal_roster(
                capacity_context,
                capacity,
                incoming_players=players_in,
                outgoing_players=players_out,
                slot_eligibility=configured_slot_eligibility(roster_settings) or None,
            )
        except Exception as exc:  # noqa: BLE001
            # Degrade, never fail: the value delta above is the primary
            # answer and must not be taken down by an optional capacity
            # read.  Absent and zero must not read the same, so the reason
            # is published rather than the block silently vanishing.
            response["rosterCapacity"] = {
                "unavailable": f"{type(exc).__name__}",
                "notes": ["roster capacity could not be computed for this trade"],
            }
            response["finalLegalRoster"] = {
                "available": False,
                "unavailableReason": f"{type(exc).__name__}",
                "notes": ["the final legal post-trade roster could not be solved"],
            }

    return response
