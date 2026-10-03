"""Team-context layer for the trade finder (#842 ON only).

``src.trade.finder`` scores a package on canonical board value (our side) and
the counterparty's retail market (their side).  This module is what Use Team
Context = ON adds on top of that score, and nothing else:

* **#843 capacity for BOTH teams** (:func:`apply_capacity_ranking`) — a
  package is ranked on each side's FINAL LEGAL roster.  The forced-drop cost
  comes from the canonical capacity owner (``src.trade.roster_capacity``,
  ``ForcedDrop.release_cost`` = canonical value × positional scarcity) and is
  charged to the side that must cut, normalised by that side's own outgoing
  package — the SAME computation for each side (Wave B double-count rule 6).
  It REPLACES the retired ``rosterFitBonus`` (+1.0 per surplus position shed,
  +1.5 per urgent need filled), which was an unvalidated additive score; the
  urgent-need flags survive as explanation only.
* **#841 posture-directed picks** (:func:`pick_direction`,
  :func:`owned_pick_assets`) — owned draft picks enter a generated package
  only when the two teams' Competitive Postures make the pick a currency both
  want: a PUSH team may SEND its owned picks to a RETOOL / REBUILD team; a
  RETOOL / REBUILD team may RECEIVE a PUSH team's owned picks.  Never as
  filler, never a pick the sender does not hold, never in Asset-Only.

What it deliberately does not do
────────────────────────────────
* No posture-weighted score for player-only packages.  Turning "this team is
  PUSH" into a rate at which current production trades for future value is a
  methodology the owner has not approved, and the trade counterfactual for
  title odds is not wired; posture here only gates pick direction and is
  reported on every package.
* No own-pick slot credit.  The league's draft-order method is unmodelled
  (``src.roster_intel.posture`` says so on every payload), so a team is never
  credited with "improving its pick" by getting worse.
* No manufactured market approval.  A future pick whose slot is unknown is
  valued at the canonical GENERIC grade (``identity.picks.market_resolution``
  → ``api.pick_value_resolution``).  Vendors price tiers, not the generic
  grade, so its market leg is the MEAN of the vendor's own Early / Mid / Late
  prices (uniform-slot assumption, labelled ``vendorTierMean``) and the
  package's market coverage is reported ``partial`` — demoted and capped by
  the finder exactly like any other incomplete market evaluation.
"""

from __future__ import annotations

from typing import Any, Callable, Mapping, Sequence

__all__ = [
    "CAPACITY_EXAMINE_BUDGET",
    "NOT_EXAMINED_FLAG",
    "PICKS_PER_SENDER",
    "apply_capacity_ranking",
    "owned_pick_assets",
    "pick_direction",
    "posture_by_team_name",
]

#: Owned picks considered per sending team, highest canonical value first.
PICKS_PER_SENDER = 4
#: Postures that may send picks for current production / receive them.
_PICK_BUYERS = frozenset({"PUSH"})
_PICK_SELLERS = frozenset({"RETOOL", "REBUILD"})
_TRUSTED_CONFIDENCE = frozenset({"HIGH", "MEDIUM"})


def posture_by_team_name(league_postures: Mapping[str, Any] | None) -> dict[str, dict[str, Any]]:
    teams = (league_postures or {}).get("teams") if isinstance(league_postures, Mapping) else None
    out: dict[str, dict[str, Any]] = {}
    for entry in (teams or {}).values():
        if isinstance(entry, dict) and entry.get("teamName"):
            out[str(entry["teamName"])] = entry
    return out


def _posture_summary(entry: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not entry:
        return None
    return {"posture": entry.get("posture"), "confidence": entry.get("confidence")}


def pick_direction(
    mine: Mapping[str, Any] | None, theirs: Mapping[str, Any] | None
) -> tuple[str | None, str]:
    """``("send" | "receive" | None, reason)`` for owned picks in this pairing."""
    if not mine or not theirs:
        return None, "posture_unavailable"
    if mine.get("confidence") not in _TRUSTED_CONFIDENCE:
        return None, "your_posture_low_confidence"
    if theirs.get("confidence") not in _TRUSTED_CONFIDENCE:
        return None, "their_posture_low_confidence"
    m, t = mine.get("posture"), theirs.get("posture")
    if m in _PICK_BUYERS and t in _PICK_SELLERS:
        return "send", f"{m} vs {t}: your picks for their current production"
    if m in _PICK_SELLERS and t in _PICK_BUYERS:
        return "receive", f"{m} vs {t}: their picks for your current production"
    return None, f"{m} vs {t}: no strategic reason for picks to move"


def _market_from_row(
    pdata: Mapping[str, Any] | None, keys: Sequence[str]
) -> tuple[int | None, str | None]:
    if not isinstance(pdata, Mapping):
        return None, None
    csv = pdata.get("_canonicalSiteValues")
    for key in keys:
        raw = csv.get(key) if isinstance(csv, Mapping) else None
        if raw is None:
            raw = pdata.get(key)
        try:
            val = int(raw) if raw is not None else None
        except (TypeError, ValueError):
            val = None
        if val is not None and val > 0:
            return val, key
    return None, None


def owned_pick_assets(
    team: Mapping[str, Any] | None,
    contract: Mapping[str, Any] | None,
    players: Mapping[str, Any],
    *,
    asset_factory: Callable[..., Any],
    market_keys: Sequence[str],
    min_value: int,
    limit: int = PICKS_PER_SENDER,
) -> tuple[list[Any], dict[str, Any]]:
    """The team's OWNED picks as finder assets, plus a report of what was refused.

    Ownership is the league's own published inventory (``pickDetails`` — the
    Wave A owner).  An entry without a canonical ``assetId`` is not offered:
    an unidentifiable pick cannot be debited from the right roster later.
    """
    from src.api.pick_value_resolution import (  # noqa: PLC0415
        _pick_rows_by_name,
        resolve_pick_value,
    )
    from src.identity.picks import market_resolution  # noqa: PLC0415

    report: dict[str, Any] = {"considered": 0, "unidentified": 0, "unpriced": 0, "belowFloor": 0}
    details = (team or {}).get("pickDetails") if isinstance(team, Mapping) else None
    if not isinstance(details, list) or not contract:
        report["reason"] = "pick_inventory_unpublished"
        return [], report
    seasons = []
    for t in (contract.get("sleeper") or {}).get("teams") or []:
        for d in (t or {}).get("pickDetails") or []:
            try:
                seasons.append(int(d.get("season")))
            except (TypeError, ValueError, AttributeError):
                continue
    upcoming = min(seasons) if seasons else None
    rows = _pick_rows_by_name(dict(contract))
    out: list[Any] = []
    for d in details:
        if not isinstance(d, Mapping):
            continue
        report["considered"] += 1
        aid = str(d.get("assetId") or "").strip()
        try:
            year, rnd = int(d.get("season")), int(d.get("round"))
        except (TypeError, ValueError):
            report["unidentified"] += 1
            continue
        if not aid or upcoming is None:
            report["unidentified"] += 1
            continue
        slot = d.get("slot")
        res = market_resolution(
            year=year,
            round_num=rnd,
            slot=int(slot) if isinstance(slot, int) and slot > 0 else None,
            current_draft_year=upcoming,
        )
        val = resolve_pick_value(dict(contract), res.ref, rows_by_name=rows)
        if val.value is None or not val.basis_row_name:
            report["unpriced"] += 1
            continue
        if val.value < min_value:
            report["belowFloor"] += 1
            continue
        market, source = _market_from_row(players.get(val.basis_row_name), market_keys)
        estimated = False
        basis_rows = (val.provenance or {}).get("basis") if val.provenance else None
        if market is None and isinstance(basis_rows, list) and basis_rows:
            vals = [_market_from_row(players.get(str(b)), market_keys) for b in basis_rows]
            if all(v is not None for v, _ in vals):
                market = int(round(sum(v for v, _ in vals) / len(vals)))
                source = vals[0][1]
                estimated = True
        if market is None:
            # A pick no vendor prices at all is never offered: on the side
            # that GIVES it, an absent market value would understate what
            # that side sends and so INFLATE the other side's market appeal —
            # canonical imputation manufacturing market approval.
            report["noMarketPrice"] = report.get("noMarketPrice", 0) + 1
            continue
        out.append(
            asset_factory(
                name=val.basis_row_name,
                position="PICK",
                team="",
                model_value=int(val.value),
                market_value=market,
                is_pick=True,
                source_count=0,
                market_source=source,
                asset_id=aid,
                market_estimated=estimated,
                owned_label=str(d.get("label") or "") or None,
                pick_value_basis=res.basis,
            )
        )
    out.sort(key=lambda a: -a.model_value)
    return out[:limit], report


def _player_names(assets: Sequence[Any]) -> list[str]:
    return [a.name for a in assets if not getattr(a, "is_pick", False)]


def _release(cap: Any) -> tuple[float | None, str]:
    """``(release_cost, state)`` — ``None`` cost when it cannot be known."""
    if cap is None:
        return None, "unavailable"
    req = cap.requires_drops
    if req is None:
        return None, "uncertain"
    if not req:
        return 0.0, "no_cut"
    cost = cap.forced_drop_release_cost
    return (float(cost) if cost is not None else None), "cut_required"


#: Hard bound on candidates whose cut cost is measured per request (two
#: capacity reads each, cached by roster delta).  When it runs out the
#: unmeasured candidates are flagged and ordered after measured ones, and the
#: report says so.
CAPACITY_EXAMINE_BUDGET = 400

#: Flag on a package whose cut cost could not be measured within the budget.
NOT_EXAMINED_FLAG = "capacity_not_examined"


def apply_capacity_ranking(
    candidates: list[Any],
    *,
    my_context: Any,
    opponent_context_for: Callable[[str], Any],
    opponent_of: Callable[[Any], str | None],
    order: Callable[[list[Any]], list[Any]],
    window: int,
    budget: int = CAPACITY_EXAMINE_BUDGET,
) -> dict[str, Any]:
    """Re-rank on BOTH teams' final legal roster until the top is settled.

    Two halves of the canonical capacity owner:

    * ``roster_capacity.requires_cleanup`` (counts only, no lineup solve) on
      every uneven-player-count candidate: a package that fits both rosters
      costs nothing and is settled at once.
    * ``roster_capacity.assess_roster_capacity`` (the cut ladder) only for a
      package that forces a cut, and only while it could still reach the
      returned ``window`` of ``order`` — the finder's exact final ordering.  A
      charge only ever LOWERS a score, so an unmeasured package's current
      score is an upper bound: once the first ``window`` places hold only
      settled packages, nothing unmeasured can overtake them.

    Mutates each charged candidate's ``arbitrage_score`` / flags /
    ``ranking_factors``.  An unknown capacity (no cap, taxi bracket straddling
    zero) charges NOTHING and is flagged — unknown is never zero, and never a
    fabricated cost either.
    """
    from src.trade.roster_capacity import (  # noqa: PLC0415
        assess_roster_capacity,
        requires_cleanup,
    )

    report: dict[str, Any] = {
        "uneven": 0,
        "fitWithoutCut": 0,
        "examined": 0,
        "charged": 0,
        "erasedYourEdge": 0,
        "erasedTheirAppeal": 0,
        "unknown": 0,
        "window": int(window),
        "budget": int(budget),
        "settled": False,
        "notExamined": 0,
    }
    cache: dict[tuple, Any] = {}
    pending: set[int] = set()

    def _assess(ctx: Any, side: str, incoming: list[str], outgoing: list[str]) -> Any:
        key = (side, tuple(sorted(incoming)), tuple(sorted(outgoing)))
        if key not in cache:
            cache[key] = assess_roster_capacity(
                ctx, incoming_players=incoming, outgoing_players=outgoing
            )
        return cache[key]

    def _examine(tc: Any) -> None:
        give = _player_names(tc.give)
        recv = _player_names(tc.receive)
        report["examined"] += 1
        opp_name = opponent_of(tc)
        mine = theirs = None
        try:
            if my_context is not None:
                mine = _assess(my_context, "mine", recv, give)
            opp_ctx = opponent_context_for(opp_name) if opp_name else None
            if opp_ctx is not None:
                theirs = _assess(opp_ctx, f"theirs:{opp_name}", give, recv)
        except Exception:  # noqa: BLE001 — a capacity read never drops a trade
            mine = theirs = None
        my_cost, my_state = _release(mine)
        their_cost, their_state = _release(theirs)
        if my_cost is None or their_cost is None:
            report["unknown"] += 1
            tc.flags.append("capacity_unknown")
        mult = float(tc.ranking_factors.get("confidenceMultiplier") or 1.0)
        # The SAME computation per side (double-count rule 6): the side's
        # forced-release cost (canonical) over the canonical value of the
        # package that side sends.
        mine_frac = (my_cost or 0.0) / max(tc.give_model_total, 1)
        theirs_frac = (their_cost or 0.0) / max(tc.receive_model_total, 1)
        delta = -(50.0 * mine_frac + 30.0 * theirs_frac) * mult
        if tc.ktc_coverage != "full":
            delta *= 0.3
        if delta:
            report["charged"] += 1
        tc.arbitrage_score += delta
        tc.ranking_factors["capacityAdjustment"] = round(delta, 2)
        tc.ranking_factors["yourForcedReleaseCost"] = None if my_cost is None else round(my_cost, 1)
        tc.ranking_factors["theirForcedReleaseCost"] = (
            None if their_cost is None else round(their_cost, 1)
        )
        tc.ranking_factors["yourCapacityState"] = my_state
        tc.ranking_factors["theirCapacityState"] = their_state
        if my_cost and tc.board_delta - my_cost <= 0:
            report["erasedYourEdge"] += 1
            tc.flags.append("capacity_erases_your_edge")
        if their_cost and tc.opponent_ktc_appeal - theirs_frac <= 0:
            report["erasedTheirAppeal"] += 1
            tc.flags.append("capacity_erases_their_appeal")

    # Pass 1 — counts only.
    for tc in candidates:
        give = _player_names(tc.give)
        recv = _player_names(tc.receive)
        if len(give) == len(recv):
            continue
        report["uneven"] += 1
        opp_name = opponent_of(tc)
        opp_ctx = opponent_context_for(opp_name) if opp_name else None
        needs = [
            requires_cleanup(my_context, incoming_players=recv, outgoing_players=give)
            if my_context is not None
            else None,
            requires_cleanup(opp_ctx, incoming_players=give, outgoing_players=recv)
            if opp_ctx is not None
            else None,
        ]
        if any(n is True for n in needs):
            pending.add(id(tc))
        elif any(n is None for n in needs):
            report["unknown"] += 1
            tc.flags.append("capacity_unknown")
        else:
            report["fitWithoutCut"] += 1
            tc.ranking_factors["capacityAdjustment"] = 0.0
            tc.ranking_factors["yourCapacityState"] = "no_cut"
            tc.ranking_factors["theirCapacityState"] = "no_cut"

    # Pass 2 — measure cut costs until the window is settled.
    while True:
        ranked = order(candidates)
        batch: list[Any] = []
        settled_seen = 0
        for tc in ranked:
            if settled_seen >= window:
                break
            if id(tc) in pending:
                batch.append(tc)
            else:
                settled_seen += 1
        if not batch:
            report["settled"] = True
            break
        if report["examined"] >= budget:
            break
        for tc in batch:
            if report["examined"] >= budget:
                break
            pending.discard(id(tc))
            _examine(tc)
    for tc in candidates:
        if id(tc) in pending:
            tc.flags.append(NOT_EXAMINED_FLAG)
            report["notExamined"] += 1
    report["assessmentsComputed"] = len(cache)
    return report


def posture_payload(mine: Mapping[str, Any] | None, theirs: Mapping[str, Any] | None) -> dict:
    return {"you": _posture_summary(mine), "them": _posture_summary(theirs), "countedAsVote": False}
