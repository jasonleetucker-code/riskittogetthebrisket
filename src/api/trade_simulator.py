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
from src.identity.picks import (
    PICK_OWNER_ABSENT,
    PICK_OWNER_OWNED,
    PICK_OWNERSHIP_UNAVAILABLE,
    league_pick_owner_index,
    lookup_league_pick_owner,
    team_pick_ownership_unavailable_reason,
)


_IDP_BASE_POSITIONS = frozenset({"DL", "LB", "DB"})


def _paired_picks(
    labels: list[Any] | None, ids: list[Any] | None
) -> tuple[list[str], list[str | None]]:
    """Drop empty labels, keeping each label's parallel asset id (or ``None``)."""
    ids = list(ids or [])
    out_labels: list[str] = []
    out_ids: list[str | None] = []
    for i, label in enumerate(labels or []):
        if not label:
            continue
        aid = ids[i] if i < len(ids) else None
        aid = str(aid).strip() if isinstance(aid, (str, int)) and str(aid).strip() else None
        out_labels.append(str(label))
        out_ids.append(aid)
    return out_labels, out_ids


def _coerce_rid(team: Any) -> int | None:
    if not isinstance(team, dict):
        return None
    for key in ("roster_id", "rosterId"):
        try:
            return int(team.get(key))
        except (TypeError, ValueError):
            continue
    return None


def _roster_pick_entries(team: Any) -> list[tuple[str, str | None]]:
    """``[(label, assetId|None)]`` for the picks ``team`` holds.

    ``pickDetails`` (with ids) when published as a list, else the plain
    ``picks`` labels.  The two are the same multiset of labels.
    """
    if not isinstance(team, dict):
        return []
    details = team.get("pickDetails")
    if isinstance(details, list) and details:
        out: list[tuple[str, str | None]] = []
        for d in details:
            if not isinstance(d, dict) or not d.get("label"):
                continue
            aid = str(d.get("assetId") or "").strip() or None
            out.append((str(d["label"]), aid))
        return out
    return [(str(p), None) for p in (team.get("picks") or []) if p]


def _attach_ids(assets: list[dict[str, Any]], pairs: list[tuple[str, str | None]]) -> None:
    """Stamp each proven id onto the resolved asset of the same label (in order)."""
    pending: dict[str, list[str]] = {}
    for label, aid in pairs:
        if aid:
            pending.setdefault(str(label), []).append(aid)
    for asset in assets:
        queue = pending.get(str(asset.get("sourceLabel")))
        if queue:
            asset["assetId"] = queue.pop(0)


def _classify_owned_picks(
    *,
    picks_out: list[str],
    ids_out: list[str | None],
    picks_in: list[str],
    ids_in: list[str | None],
    teams: list[Any],
    owner_index: tuple[dict[str, list[int]], bool],
    team_rid: int | None,
) -> dict[str, Any]:
    """Split the trade's picks by what the canonical ownership lookup proves.

    ``sendOut`` / ``receiveIn`` are ``(label, assetId|None)`` pairs that take
    part in the trade; an id is kept only when ownership was PROVEN (so the
    after-state removes exactly that pick).  Everything refused is reported,
    never silently dropped.
    """
    names = {
        _coerce_rid(t): str(t.get("name") or "")
        for t in teams
        if isinstance(t, dict) and _coerce_rid(t) is not None
    }

    def _owner_fields(own) -> dict[str, Any]:
        rid = own.owner_roster_id
        return {"actualOwnerRosterId": rid, "actualOwnerName": names.get(rid) if rid else None}

    send_out: list[tuple[str, str | None]] = []
    receive_in: list[tuple[str, str | None]] = []
    not_owned: list[dict[str, Any]] = []
    already_owned: list[dict[str, Any]] = []
    repeated: list[dict[str, Any]] = []
    unverified: list[dict[str, Any]] = []

    seen_out: set[str] = set()
    for label, aid in zip(picks_out, ids_out):
        if not aid:
            send_out.append((label, None))
            continue
        if aid in seen_out:
            repeated.append({"assetId": aid, "label": label, "direction": "out"})
            continue
        seen_out.add(aid)
        own = lookup_league_pick_owner(teams, aid, index=owner_index)
        if own.state == PICK_OWNER_OWNED and team_rid is not None:
            if own.owner_roster_id == team_rid:
                send_out.append((label, aid))
            else:
                not_owned.append(
                    {"assetId": aid, "label": label, "reason": "held_by_another_team"}
                    | _owner_fields(own)
                )
        elif own.state == PICK_OWNER_ABSENT:
            not_owned.append(
                {"assetId": aid, "label": label, "reason": own.reason} | _owner_fields(own)
            )
        else:
            # Unprovable (inventory unpublished, conflicting records, or no
            # team to attribute to): never "owned by the sender".  It stays
            # in the trade as typed and can debit only an exact roster label.
            unverified.append(
                {"assetId": aid, "label": label, "direction": "out", "reason": own.reason}
            )
            send_out.append((label, None))

    proven_sent = {aid for _label, aid in send_out if aid}
    seen_in: set[str] = set()
    incoming_holders: list[dict[str, Any]] = []
    for label, aid in zip(picks_in, ids_in):
        if not aid:
            receive_in.append((label, None))
            continue
        if aid in seen_in:
            repeated.append({"assetId": aid, "label": label, "direction": "in"})
            continue
        seen_in.add(aid)
        own = lookup_league_pick_owner(teams, aid, index=owner_index)
        # The request names no counterparty, so who SENDS this pick cannot be
        # checked.  Its current holder is still reported when known, marked
        # unverified, so a received pick nobody on the other side holds is
        # visible rather than silent.  Semantics are unchanged.
        incoming_holders.append(
            {
                "assetId": aid,
                "label": label,
                "ownershipState": own.state,
                "holderRosterId": own.owner_roster_id,
                "holderName": names.get(own.owner_roster_id) if own.owner_roster_id else None,
                "counterpartyVerified": False,
                "note": "the request names no counterparty; this is the pick's current holder",
            }
        )
        if (
            own.state == PICK_OWNER_OWNED
            and team_rid is not None
            and own.owner_roster_id == team_rid
            and aid not in proven_sent
        ):
            already_owned.append({"assetId": aid, "label": label} | _owner_fields(own))
            continue
        if own.state != PICK_OWNER_OWNED:
            unverified.append(
                {"assetId": aid, "label": label, "direction": "in", "reason": own.reason}
            )
        receive_in.append((label, aid if own.state == PICK_OWNER_OWNED else None))

    return {
        "sendOut": send_out,
        "receiveIn": receive_in,
        "notOwnedBySender": not_owned,
        "alreadyOwnedByReceiver": already_owned,
        "repeatedOwnedPick": repeated,
        "unverified": unverified,
        "incomingPickHolders": incoming_holders,
    }


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
            if not row and res.basis == "exact_slot":
                # An UNSLOTTED current class (C1-U6-D2): no vendor published
                # its slots, so the board carries its tiers, not slot rows.
                # The slot's own tier is a deterministic mapping, not a guess
                # — the same ``tier_from_slot`` rule a future year gets.
                from src.identity.picks import MarketPickRef, slot_tier

                tier_name = MarketPickRef(
                    year=parsed.year,
                    round_num=parsed.round_num,
                    tier=slot_tier(int(parsed.slot)),
                ).board_row_name()
                if tier_name:
                    row = row_index.get(tier_name.strip().lower())
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
        # Canonical stamps, READ never computed: identity for the UI's player
        # link, and the confidence owner's evidence-quality verdict for the
        # Analyze Trade evidence lens (``src/api/confidence.py``).
        "playerId": str(row.get("playerId")) if row.get("playerId") else None,
        "confidenceBucket": row.get("confidenceBucket"),
        "hasSourceDisagreement": row.get("hasSourceDisagreement"),
        # KTC Market BENCHMARK (``src.sources.ktc_market``), READ never
        # computed: Analyze Trade's market-corroboration section compares it
        # with the canonical direction and never counts it as a vote.  None
        # when KTC publishes no price (IDP, deep rows) — missing, not 0.
        "ktcMarketValue": _ktc_market_value(row),
        "marketGapDirection": row.get("marketGapDirection"),
    }


def _ktc_market_value(row: dict[str, Any]) -> float | None:
    market = row.get("ktcMarket")
    if not isinstance(market, dict):
        return None
    value = market.get("normalizedValue")
    return float(value) if isinstance(value, (int, float)) and value > 0 else None


def roster_profile_inputs(contract: dict[str, Any] | None) -> dict[str, Any]:
    """Board-derived inputs for Team Weakness and the age-value portfolio,
    keyed the way ``RosterAsset.player_id`` is (Sleeper ``playerId``, else the
    board name) so a rank or an age can never silently miss every player.

    Positional ranks order canonical values the board already published;
    nothing is computed here.  ``team_count`` is the league's own roster count
    (``sleeper.teams``) — None when unknown, which leaves weakness unmeasured
    rather than measured against an invented league size.
    """
    from src.roster_intel.age_portfolio import build_youth_curve  # noqa: PLC0415
    from src.roster_intel.weakness import build_position_ranks  # noqa: PLC0415

    rows = _players_array(contract or {})
    board: list[tuple[str, str, float | None]] = []
    ages: dict[str, float | None] = {}
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict) or row.get("assetClass") == "pick":
            continue
        position = str(row.get("position") or "").strip()
        key = str(row.get("playerId") or row.get("canonicalName") or row.get("displayName") or "")
        if not position or not key or key in seen:
            continue
        seen.add(key)
        value = row.get("rankDerivedValue")
        board.append((key, position, float(value) if isinstance(value, (int, float)) else None))
        age = row.get("age")
        if isinstance(age, (int, float)) and age > 0:
            ages[key] = float(age)
    teams = ((contract or {}).get("sleeper") or {}).get("teams") or []
    return {
        "ranks": build_position_ranks(board, population="contract_board_priced_players"),
        "team_count": len(teams) if isinstance(teams, list) and len(teams) > 1 else None,
        "ages": ages,
        "youth": build_youth_curve([(pos, ages.get(pid)) for pid, pos, _ in board]),
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


def competitive_posture_for(
    contract: Any,
    league_key: str,
    team: dict[str, Any],
    *,
    build_if_missing: bool,
) -> dict[str, Any]:
    """This team's canonical posture block, or a NAMED unavailable.

    The route calls this and hands the block to :func:`simulate_trade`.
    Analyze Trade may build the league bundle (``build_if_missing``); a plain
    simulate (every calculator edit) reads a warm one only, so it never pays
    the cold solve.
    """
    owner_id = str(team.get("ownerId") or "")
    try:
        from src.api.gameplan import GameplanUnavailable, league_competitive_postures
        from src.api.league_registry import get_scoring_profile

        postures, meta = league_competitive_postures(
            league_key,
            get_scoring_profile(league_key),
            contract,
            build_if_missing=build_if_missing,
        )
    except GameplanUnavailable as exc:
        return {"available": False, "unavailableReason": exc.reason}
    except Exception as exc:  # noqa: BLE001 — context never fails a simulation
        return {"available": False, "unavailableReason": f"error:{type(exc).__name__}"}
    posture = postures.get(owner_id)
    if posture is None:
        return {"available": False, "unavailableReason": "team_not_in_league_bundle"}
    return {
        "available": True,
        **posture.to_dict(),
        "bundleFreshness": meta.get("bundleFreshness"),
    }


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
    include_roster_utility: bool = False,
    competitive_posture: dict[str, Any] | None = None,
    pick_asset_ids_in: list[Any] | None = None,
    pick_asset_ids_out: list[Any] | None = None,
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
          "finalRosterSimulation": {...}, # optional; see src.roster_intel.simulation.
                                           # RosterSimulation.to_dict() plus cleanupApplied /
                                           # cleanupIsUpperBound. Absent (not null) whenever
                                           # rosterCapacity itself is absent/failed; an
                                           # {"available": False, ...} / {"unavailable": ...}
                                           # shape when computable-but-refused or errored.
        }

    Never mutates the contract or persists.  Pure function over the
    passed inputs; call repeatedly for different what-ifs.

    ``picks_in`` / ``picks_out`` resolve to board rows exactly like
    players.  What differs is which of them may touch the team's REAL
    inventory (Wave A, owner directive 2026-10-03):

    * ``pick_asset_ids_in`` / ``pick_asset_ids_out`` run parallel to the
      pick lists (``None`` for an entry without one).  An owned league pick
      id is resolved by the canonical ownership lookup
      (``src.identity.picks.lookup_league_pick_owner``): the team is debited
      for exactly that pick only when it holds it; a pick another team holds
      (or no team holds) is reported in ``ownedPickChecks.notOwnedBySender``
      with the actual owner and is neither debited nor counted as sent.
    * A pick with no id debits the roster only by its EXACT ownership label
      on this team's roster.  Anything else — a generic market pick such as
      ``"2027 Mid 1st"`` — is hypothetical: it is priced in ``sending``
      but never removes one of the team's real picks.  The board-row
      fallback that used to remove "some pick on that row" could remove a
      DIFFERENT owned pick, and is now applied to players only.
    * One real pick counts at most once: a repeated id is reported, not
      debited or credited twice, and a pick the team already holds is not
      credited again.
    """
    players_in = [p for p in (players_in or []) if p]
    players_out = [p for p in (players_out or []) if p]
    picks_in, pick_ids_in = _paired_picks(picks_in, pick_asset_ids_in)
    picks_out, pick_ids_out = _paired_picks(picks_out, pick_asset_ids_out)

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
    # Pick ownership UNKNOWN (failed /traded_picks, #1618): the team's
    # untraded picks cannot enter before/after, and the response SAYS so
    # rather than letting an absent pick list read as "this team owns no
    # picks".
    picks_unknown_reason = (
        team_pick_ownership_unavailable_reason(resolved_team)
        if resolved_team and isinstance(resolved_team, dict)
        else None
    )
    # Roster picks carry their canonical owned id when the producer stamped
    # one (``pickDetails[].assetId``), so a sent id removes exactly that pick.
    # ``pickDetails`` and ``picks`` are the same multiset of labels; without
    # details the plain labels are used, unidentified.
    roster_pick_entries = (
        [] if picks_unknown_reason is not None else _roster_pick_entries(resolved_team)
    )
    for label, asset_id in roster_pick_entries:
        hit = _resolve_asset(label, row_index=row_index)
        if hit is not None:
            if asset_id:
                hit["assetId"] = asset_id
            before_assets.append(hit)

    # Which picks may touch REAL inventory — see the docstring.
    teams = ((contract.get("sleeper") or {}).get("teams")) if isinstance(contract, dict) else None
    owner_index = league_pick_owner_index(teams if isinstance(teams, list) else [])
    team_rid = _coerce_rid(resolved_team)
    checks = _classify_owned_picks(
        picks_out=picks_out,
        ids_out=pick_ids_out,
        picks_in=picks_in,
        ids_in=pick_ids_in,
        teams=teams if isinstance(teams, list) else [],
        owner_index=owner_index,
        team_rid=team_rid,
    )
    sent_pick_labels = [label for label, _aid in checks["sendOut"]]
    received_pick_labels = [label for label, _aid in checks["receiveIn"]]
    if picks_unknown_reason is not None:
        # The inventory is unknown, so nothing here is "owned by the sender"
        # (the classification above already marked these ``unverified``).
        # The picks this trade sends are still counted on BOTH sides: seeded
        # into ``before`` under their exact label so the label removal below
        # takes them out of ``after``.  Without this a sent pick never leaves
        # the after-state and ``delta`` overstates the gain by its value.
        # Only the UNTRADED picks stay out of both sides.
        for label in sent_pick_labels:
            hit = _resolve_asset(label, row_index=row_index)
            if hit is not None:
                before_assets.append(hit)

    # Receiving / sending sides of the trade.
    receiving, unresolved_in = _resolve_many([*players_in, *received_pick_labels])
    sending, unresolved_out = _resolve_many([*players_out, *sent_pick_labels])
    # Re-attach the ids the classification proved this team holds, so the
    # after-state removal below takes exactly that pick.
    _attach_ids(sending, checks["sendOut"])
    _attach_ids(receiving, checks["receiveIn"])
    for entry in checks["notOwnedBySender"]:
        hit = _resolve_asset(entry["label"], row_index=row_index)
        entry["value"] = hit["value"] if hit is not None else None

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
    #
    # Wave A: an owned pick id the team holds removes exactly that pick
    # first.  Picks are then matched by exact ownership label only; the
    # board-identity fallback below is for PLAYERS — on a pick it removed
    # "some pick of that row", which could be a different owned pick
    # while equity subtracted the sent one.
    def _label_key(asset: dict[str, Any]) -> str:
        return str(asset.get("sourceLabel") or asset.get("name") or "").strip().lower()

    def _board_key(asset: dict[str, Any]) -> str:
        return str(asset.get("name") or "").strip().lower()

    sent_ids = Counter(str(a["assetId"]) for a in sending if a.get("assetId"))
    by_id: list[dict[str, Any]] = []
    for asset in before_assets:
        aid = str(asset.get("assetId") or "")
        if aid and sent_ids.get(aid, 0) > 0:
            sent_ids[aid] -= 1
            continue
        by_id.append(asset)

    by_label_sending = [a for a in sending if not a.get("assetId")]
    sent_by_label = Counter(_label_key(a) for a in by_label_sending)
    consumed_label: Counter[str] = Counter()
    kept: list[dict[str, Any]] = []
    for asset in by_id:
        key = _label_key(asset)
        if consumed_label[key] < sent_by_label.get(key, 0):
            consumed_label[key] += 1
            continue
        kept.append(asset)

    unmatched = []
    hypothetical_out: list[str] = []
    for asset in by_label_sending:
        key = _label_key(asset)
        if consumed_label[key] > 0:
            consumed_label[key] -= 1
        elif asset.get("assetClass") == "pick":
            # Generic / unheld pick label: priced as sent, never debits a
            # real pick of this team.
            hypothetical_out.append(str(asset.get("sourceLabel") or asset.get("name")))
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
        # When the board these values came from was produced, so every
        # Analyze Trade section can state its freshness.
        "boardAsOf": (contract or {}).get("scrapeTimestamp") or (contract or {}).get("date"),
        "ownedPickChecks": {
            "rule": "src/identity/picks.py::lookup_league_pick_owner",
            "notOwnedBySender": checks["notOwnedBySender"],
            "alreadyOwnedByReceiver": checks["alreadyOwnedByReceiver"],
            "repeatedOwnedPick": checks["repeatedOwnedPick"],
            "unverified": checks["unverified"],
            "incomingPickHolders": checks["incomingPickHolders"],
            "hypotheticalPicksOut": hypothetical_out,
        },
    }
    if picks_unknown_reason is not None:
        response["pickOwnership"] = {
            "state": PICK_OWNERSHIP_UNAVAILABLE,
            "reason": picks_unknown_reason,
            "note": (
                "This team's draft-pick ownership is unknown, so its untraded "
                "picks are excluded from both before and after. Picks in this "
                "trade are counted on both sides, so delta still reflects them."
            ),
        }

    # Competitive Posture (#840 / C7-POST-01): the canonical owner's answer
    # for THIS team, resolved by the caller (``competitive_posture_for``) and
    # passed in — this function stays pure over its inputs.
    posture_block = competitive_posture if isinstance(competitive_posture, dict) else None
    if resolved_team and posture_block is not None:
        response["competitivePosture"] = posture_block

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
            canonical_posture=(
                posture_block if posture_block and posture_block.get("label") else None
            ),
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
            )

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
        except Exception as exc:  # noqa: BLE001
            # Degrade, never fail: the value delta above is the primary
            # answer and must not be taken down by an optional capacity
            # read.  Absent and zero must not read the same, so the reason
            # is published rather than the block silently vanishing.
            response["rosterCapacity"] = {
                "unavailable": f"{type(exc).__name__}",
                "notes": ["roster capacity could not be computed for this trade"],
            }
            capacity = None
            capacity_context = None

        # Final legal roster: WHICH player actually goes, the re-solved
        # lineup, and the Team Strength delta — not just the forced-drop
        # COST estimate ``rosterCapacity`` above reports.
        #
        # C2-SIM-01 (``src.roster_intel.simulation.simulate_roster_change``)
        # and its C3-CAP-01 composition
        # (``roster_capacity.simulate_final_legal_roster``) already exist and
        # are independently tested (``tests/trade/test_trade_consumes_roster.py``,
        # P1-P9). This block is pure composition of those two already-owned
        # primitives at this endpoint — no new roster-impact methodology.
        #
        # A separate try/except from the block above: a failure here must
        # not erase an already-successful ``rosterCapacity`` result, and a
        # failure above must not be double-reported.
        if capacity is not None and capacity_context is not None:
            requires_drops = capacity.requires_drops
            if requires_drops is None:
                # Taxi-bracket ambiguity: the outgoing set for the cleanup
                # solve is itself uncertain, so re-solving against one
                # arbitrary guess would publish a specific lineup as though
                # it were determined. Missing is never zero: this is a
                # distinct "unknown" from a computed, empty result.
                response["finalRosterSimulation"] = {
                    "available": False,
                    "unavailableReason": "capacity_uncertain",
                    "notes": [
                        "taxi membership is unknown and the forced-drop set is "
                        "therefore a range, not a determined set — see rosterCapacity"
                    ],
                }
            else:
                try:
                    from src.trade.roster_capacity import (  # noqa: PLC0415
                        simulate_final_legal_roster,
                    )

                    # Analyze Trade only: Team Weakness and the age-value
                    # portfolio before/after on the same final legal roster
                    # (their canonical owners; ranks / ages / youth come from
                    # the board).  Plain simulate keeps its existing shape.
                    profile = roster_profile_inputs(contract) if include_roster_utility else {}
                    response["finalRosterSimulation"] = simulate_final_legal_roster(
                        capacity_context,
                        capacity,
                        incoming_players=players_in,
                        outgoing_players=players_out,
                        **profile,
                    )
                except Exception as exc:  # noqa: BLE001
                    response["finalRosterSimulation"] = {
                        "unavailable": f"{type(exc).__name__}",
                        "notes": ["the final legal roster could not be simulated for this trade"],
                    }

    # #1173 roster-conditional best-ball utility, on the SAME final legal
    # roster as ``finalRosterSimulation`` (``roster_capacity.final_legal_roster``)
    # but priced by league-scored projections, never by canonical value.
    # Opt-in: it is a Monte-Carlo pass, and only Analyze Trade asks for it.
    if include_roster_utility:
        if not resolved_team:
            response["rosterUtility"] = {
                "available": False,
                "unavailableReason": "no_team_selected",
            }
        elif capacity is None or capacity_context is None:
            response["rosterUtility"] = {
                "available": False,
                "unavailableReason": "roster_capacity_unavailable",
            }
        else:
            try:
                from src.bdvm.actuals import current_nfl_season  # noqa: PLC0415
                from src.trade.roster_capacity import (  # noqa: PLC0415
                    evaluate_final_roster_utility,
                )

                sleeper = contract.get("sleeper") if isinstance(contract, dict) else None
                response["rosterUtility"] = evaluate_final_roster_utility(
                    capacity_context,
                    capacity,
                    incoming_players=players_in,
                    outgoing_players=players_out,
                    season=current_nfl_season(),
                    scoring_settings=(sleeper or {}).get("scoringSettings") or {},
                )
            except Exception as exc:  # noqa: BLE001
                # Degrade, never fail: the package answer stands without it,
                # and "could not compute" must not read as "no impact".
                response["rosterUtility"] = {
                    "available": False,
                    "unavailableReason": f"error:{type(exc).__name__}",
                }

    return response
