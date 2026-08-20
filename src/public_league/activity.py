"""Section: Trade Activity Center.

Public-safe trade feed + rollups.  No private valuation columns.
Computes:
    * trades by season
    * trades by manager
    * most active trader
    * most frequent trade partner pair
    * biggest blockbuster by total assets moved (players + picks)
    * trade timeline by week
    * position mix moved in trades
    * picks moved count / players moved count

Blockbuster tiebreaks (prompt spec):
    1. Most total moved assets
    2. Most distinct starters / notable players moved (approx: count
       of moved assets whose Sleeper position is in the offensive
       core of {QB, RB, WR, TE})
    3. Combined end-of-season internal values — server-side only,
       NEVER exposed on the public payload.  We use it as a silent
       deterministic tiebreaker and drop the raw number from the
       response.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
from typing import Any, Callable, Iterable

from src.api.public_activity_valuation import trade_instant_from_created_at

from . import metrics, trade_grading
from .snapshot import PublicLeagueSnapshot, SeasonSnapshot


OFFENSIVE_CORE = {"QB", "RB", "WR", "TE"}
# Any position we consider "notable" enough for the tiebreak.
NOTABLE_POSITIONS = OFFENSIVE_CORE | {"DL", "LB", "DB", "EDGE"}

# ── Trade grading ────────────────────────────────────────────────────────
# The math lives in ``trade_grading.py``, which is the Python half of a
# two-language pair with ``frontend/lib/league-analysis.js``: the private
# ``/trades`` page and this public timeline grade a trade with ONE
# formula — per-side linear net plus the KTC value adjustment, over the
# larger effective side total — pinned by
# ``tests/fixtures/trade_grade_parity_cases.json``.
#
# What this file used to do, and why it was wrong (audit 2026-08-04,
# finding C3): it summed ``max(value, 1) ** 1.65`` over each side's
# RECEIVED assets and compared side totals, then fed the result to the
# same 3/8/15/25/40 band table the frontend uses on a LINEAR ratio.
# Raising to 1.65 inflates a gap — a 10% linear edge is a ~16% alpha
# edge — so the same trade rendered "Good win (A-)" on /trades and
# "Clear win (B+)" here, under a comment claiming the two "land in the
# same bucket".  They did not, and the band table can only be shared by
# implementations that feed it the same quantity.
#
# The grade is computed server-side from a caller-supplied valuation
# callable; only the resulting ``{grade, color, label}`` object is
# emitted on the public payload — the raw values and per-side totals
# NEVER leave the backend.


# A resolver takes an asset and the trade's own instant (``None`` when the
# trade's timestamp could not be parsed) and answers its historical value
# at-or-before that instant, or ``None`` when the ledger has no admissible
# observation.  ``None`` must never be silently treated as 0 — see
# ``_unavailable_grade``.
_Resolver = Callable[[dict[str, Any], "datetime | None"], "float | None"]

# A factory sees every ``(asset, instant)`` pair the whole feed will ever
# need up front (so it can batch through ``asof.batch_known_before`` once)
# and returns the resolver above.
_ResolverFactory = Callable[[Iterable[tuple[dict[str, Any], "datetime | None"]]], _Resolver]


def _unavailable_grade(reason: str, missing: list[dict[str, Any]]) -> dict[str, Any]:
    """The honest "could not grade this side" sentinel.

    Never a partial total computed by silently excluding the assets that
    failed to resolve — a present-but-wrong grade is worse than an
    explicit absence, which is the whole point of V1-97 / C3-REPLAY-01.
    """
    return {
        "grade": None,
        "color": None,
        "label": "Insufficient historical evidence",
        "available": False,
        "reason": reason,
        "missingAssets": missing,
    }


def _resolve_side(
    assets: Any,
    resolve: _Resolver,
    instant: datetime,
) -> tuple[list[float], list[dict[str, Any]]]:
    """Resolve one side's asset list at ``instant``.

    Returns ``(values, missing)``.  ``missing`` names every asset that
    could not be resolved — never silently dropped from the total, which
    would turn "we don't know" into a smaller-but-present number.  A
    resolver that raises is tolerated the same way a hostile valuation
    always was here: the asset is counted missing, not allowed to poison
    the whole side.
    """
    values: list[float] = []
    missing: list[dict[str, Any]] = []
    for asset in assets or []:
        try:
            val = resolve(asset, instant)
        except (TypeError, ValueError):
            val = None
        if val is None:
            missing.append(
                {
                    "kind": asset.get("kind") if isinstance(asset, dict) else None,
                    "name": (
                        (asset.get("playerName") or asset.get("label"))
                        if isinstance(asset, dict)
                        else None
                    ),
                }
            )
            continue
        values.append(val)
    return values, missing


def _apply_trade_grades(
    feed: list[dict[str, Any]],
    resolve: _Resolver,
) -> None:
    """Attach a ``grade`` block to each side of every trade in ``feed``.

    Mutates the trade dicts in place.  Each side is graded on its OWN
    got-minus-gave net, which is what makes 3+ team trades come out
    right — their sent and received pools do not pair up, so ranking
    sides against each other's received totals mislabels whoever
    happened to receive fewest pieces.  The per-side totals are
    discarded after grading; the public payload surfaces only the
    grade letter, label, and color.

    Values are resolved AS OF the trade's own instant
    (``trade["createdAt"]``), never against today's board — that is the
    hindsight leak V1-97 / C3-REPLAY-01 closes.  A trade whose instant
    cannot be parsed, or a side with any asset the ledger cannot resolve
    at that instant, gets ``_unavailable_grade`` instead of a grade
    computed from a partial or substituted total.  One side's missing
    evidence does not poison another side's grade — each is independent.
    """
    for trade in feed:
        sides = trade.get("sides") or []
        if len(sides) < 2:
            continue
        instant = trade_instant_from_created_at(trade.get("createdAt"))
        if instant is None:
            for side in sides:
                side["grade"] = _unavailable_grade("invalid_trade_instant", [])
            continue
        for side in sides:
            got_values, got_missing = _resolve_side(side.get("receivedAssets"), resolve, instant)
            gave_values, gave_missing = _resolve_side(side.get("sentAssets"), resolve, instant)
            missing = got_missing + gave_missing
            if missing:
                side["grade"] = _unavailable_grade("no_historical_evidence", missing)
                continue
            (result,) = trade_grading.grade_trade_sides([(got_values, gave_values)])
            side["grade"] = result["grade"]


def _pick_asset(pick: dict[str, Any], snapshot: PublicLeagueSnapshot) -> dict[str, Any]:
    season = pick.get("season")
    round_ = pick.get("round")
    try:
        season_int = int(season)
    except (TypeError, ValueError):
        season_int = None
    try:
        round_int = int(round_)
    except (TypeError, ValueError):
        round_int = None
    return {
        "kind": "pick",
        "season": str(season) if season is not None else "",
        "round": round_int,
        "fromRosterId": pick.get("roster_id"),
        "label": (
            f"{season_int} R{round_int}" if season_int and round_int else f"{season} R{round_}"
        ),
    }


def _player_asset(player_id: str, snapshot: PublicLeagueSnapshot) -> dict[str, Any]:
    return {
        "kind": "player",
        "playerId": str(player_id),
        "playerName": snapshot.player_display(player_id),
        "position": snapshot.player_position(player_id),
    }


def _normalize_trade(
    snapshot: PublicLeagueSnapshot, season: SeasonSnapshot, tx: dict[str, Any]
) -> dict[str, Any] | None:
    roster_ids = []
    for rid in tx.get("roster_ids") or []:
        try:
            roster_ids.append(int(rid))
        except (TypeError, ValueError):
            continue
    if len(roster_ids) < 2:
        return None

    adds_map = tx.get("adds") or {}
    drops_map = tx.get("drops") or {}
    # Sleeper's pick shape names both ends of the move: ``owner_id``
    # receives it, ``previous_owner_id`` gave it up (``roster_id`` is
    # the ORIGINAL slot owner and is not who sent it in this trade).
    # Grading needs both halves — a side's net is what it got minus
    # what it sent, and a pick-for-pick swap is invisible otherwise.
    picks_by_owner: dict[int, list[dict[str, Any]]] = defaultdict(list)
    picks_by_sender: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for pk in tx.get("draft_picks") or []:
        try:
            owner_rid = int(pk.get("owner_id"))
        except (TypeError, ValueError):
            owner_rid = None
        if owner_rid is not None:
            picks_by_owner[owner_rid].append(pk)
        try:
            sender_rid = int(pk.get("previous_owner_id"))
        except (TypeError, ValueError):
            continue
        picks_by_sender[sender_rid].append(pk)

    sides = []
    total_assets = 0
    total_notable = 0
    for rid in roster_ids:
        owner_id = metrics.resolve_owner(snapshot.managers, season.league_id, rid)
        received_player_ids = [pid for pid, r in adds_map.items() if int(r) == rid]
        sent_player_ids = [pid for pid, r in drops_map.items() if int(r) == rid]
        received_picks = picks_by_owner.get(rid, [])
        sent_picks = picks_by_sender.get(rid, [])
        received_assets = [_player_asset(pid, snapshot) for pid in received_player_ids] + [
            _pick_asset(p, snapshot) for p in received_picks
        ]
        sent_assets = [_player_asset(pid, snapshot) for pid in sent_player_ids] + [
            _pick_asset(p, snapshot) for p in sent_picks
        ]
        if not received_assets and not sent_assets:
            continue
        side_note_count = sum(1 for a in received_assets if a.get("position") in NOTABLE_POSITIONS)
        total_assets += len(received_assets)
        total_notable += side_note_count
        sides.append(
            {
                "rosterId": rid,
                "ownerId": owner_id,
                "displayName": metrics.display_name_for(snapshot, owner_id) if owner_id else "",
                "teamName": metrics.team_name(snapshot, season.league_id, rid)
                if owner_id
                else f"Team {rid}",
                "receivedAssets": received_assets,
                # Outgoing counterpart of ``receivedAssets`` — same
                # asset shape, both players and picks.  ``sentPlayerIds``
                # stays for existing consumers.
                "sentAssets": sent_assets,
                "sentPlayerIds": list(sent_player_ids),
                "receivedPlayerCount": len(received_player_ids),
                "receivedPickCount": len(received_picks),
                "notableAssetCount": side_note_count,
            }
        )

    if not sides:
        return None

    return {
        "transactionId": str(tx.get("transaction_id") or ""),
        "season": season.season,
        "leagueId": season.league_id,
        "week": tx.get("leg") or tx.get("_leg"),
        "createdAt": tx.get("created") or tx.get("status_updated"),
        "sides": sides,
        "totalAssets": total_assets,
        "notableAssetCount": total_notable,
    }


def _position_mix(feed: list[dict[str, Any]]) -> dict[str, int]:
    counter: Counter = Counter()
    for trade in feed:
        for side in trade["sides"]:
            for asset in side["receivedAssets"]:
                if asset["kind"] != "player":
                    continue
                pos = asset.get("position") or "UNK"
                counter[pos] += 1
    return dict(counter)


def _by_manager_counts(feed: list[dict[str, Any]]) -> list[dict[str, Any]]:
    trade_counts: Counter = Counter()
    for t in feed:
        seen_owners = {side["ownerId"] for side in t["sides"] if side.get("ownerId")}
        for owner in seen_owners:
            trade_counts[owner] += 1
    rows = [{"ownerId": owner, "trades": n} for owner, n in trade_counts.items()]
    rows.sort(key=lambda r: -r["trades"])
    return rows


def _partner_pairs(feed: list[dict[str, Any]]) -> list[dict[str, Any]]:
    pair_counts: Counter = Counter()
    for t in feed:
        owners = sorted({side["ownerId"] for side in t["sides"] if side.get("ownerId")})
        if len(owners) < 2:
            continue
        for i in range(len(owners)):
            for j in range(i + 1, len(owners)):
                pair_counts[(owners[i], owners[j])] += 1
    rows = [{"ownerIds": list(pair), "trades": n} for pair, n in pair_counts.items()]
    rows.sort(key=lambda r: -r["trades"])
    return rows


def _server_side_tiebreak_score(trade: dict[str, Any]) -> float:
    """Internal tiebreak — NEVER exposed on the public payload.

    Approximates "combined end-of-season internal values" using a
    simple proxy: sum of notable-asset counts per side times the
    count of received picks (earlier rounds carry more weight).
    The raw number is intentionally opaque.
    """
    score = 0.0
    for side in trade["sides"]:
        score += side["notableAssetCount"] * 1.5
        for asset in side["receivedAssets"]:
            if asset["kind"] == "pick":
                r = asset.get("round") or 5
                score += max(0.0, 5.0 - r)
    return score


def _biggest_blockbusters(feed: list[dict[str, Any]], n: int = 5) -> list[dict[str, Any]]:
    ordered = sorted(
        feed,
        key=lambda t: (
            -t["totalAssets"],
            -t["notableAssetCount"],
            -_server_side_tiebreak_score(t),
        ),
    )
    top = []
    for t in ordered[:n]:
        # Strip internal tiebreaker output — it was only used for
        # ordering, never returned.
        row = {k: v for k, v in t.items() if k != "_tiebreak"}
        top.append(row)
    return top


def _timeline_by_week(feed: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, int], int] = defaultdict(int)
    for t in feed:
        wk = t.get("week") or 0
        grouped[(t["season"], int(wk))] += 1
    rows = [{"season": season, "week": week, "trades": n} for (season, week), n in grouped.items()]
    rows.sort(key=lambda r: (r["season"], r["week"]))
    return rows


def build_section(
    snapshot: PublicLeagueSnapshot,
    limit: int = 200,
    *,
    valuation_factory: _ResolverFactory | None = None,
) -> dict[str, Any]:
    """Build the public activity section.

    ``valuation_factory`` is an optional callable that, given every
    ``(asset, instant)`` pair the feed will need resolved, returns a
    ``(asset, instant) -> value | None`` resolver — the shape
    ``src.api.public_activity_valuation.build_asof_valuation`` produces.
    When provided, per-side grade badges are attached to every trade in
    the returned feed, each graded AS OF that trade's own timestamp
    (never today's board — V1-97 / C3-REPLAY-01) — mirroring the private
    ``/trades`` page letter grades.  The raw values themselves are never
    written to the output; only the derived ``{grade, color, label}``
    object leaves the backend.  When ``valuation_factory`` is ``None``,
    the feed has no grade fields (keeps older contract consumers
    unchanged when the private valuation pipeline is offline).
    """
    feed: list[dict[str, Any]] = []
    per_season_counts: list[dict[str, Any]] = []
    picks_moved = 0
    players_moved = 0

    for season in snapshot.seasons:
        season_trades = 0
        for tx in season.trades():
            normalized = _normalize_trade(snapshot, season, tx)
            if normalized:
                feed.append(normalized)
                season_trades += 1
                for side in normalized["sides"]:
                    picks_moved += side["receivedPickCount"]
                    players_moved += side["receivedPlayerCount"]
        per_season_counts.append(
            {
                "season": season.season,
                "leagueId": season.league_id,
                "tradeCount": season_trades,
            }
        )

    feed.sort(key=lambda t: -int(t.get("createdAt") or 0))
    if valuation_factory is not None:
        requests: list[tuple[dict[str, Any], datetime | None]] = []
        for trade in feed:
            instant = trade_instant_from_created_at(trade.get("createdAt"))
            for side in trade.get("sides") or []:
                for asset in side.get("receivedAssets") or []:
                    requests.append((asset, instant))
                for asset in side.get("sentAssets") or []:
                    requests.append((asset, instant))
        resolve = valuation_factory(requests)
        _apply_trade_grades(feed, resolve)
    by_manager = _by_manager_counts(feed)
    partner_pairs = _partner_pairs(feed)
    blockbusters = _biggest_blockbusters(feed)
    timeline = _timeline_by_week(feed)
    position_mix = _position_mix(feed)

    most_active = by_manager[0] if by_manager else None
    if most_active:
        most_active = {
            **most_active,
            "displayName": metrics.display_name_for(snapshot, most_active["ownerId"]),
        }
    partner_display = None
    if partner_pairs:
        top_pair = partner_pairs[0]
        partner_display = {
            "ownerIds": top_pair["ownerIds"],
            "trades": top_pair["trades"],
            "displayNames": [
                metrics.display_name_for(snapshot, oid) for oid in top_pair["ownerIds"]
            ],
        }

    return {
        "feed": feed[:limit],
        "totalCount": len(feed),
        "perSeasonCounts": per_season_counts,
        "byManager": by_manager,
        "partnerPairs": partner_pairs,
        "mostActiveTrader": most_active,
        "mostFrequentPartnerPair": partner_display,
        "biggestBlockbusters": blockbusters,
        "timelineByWeek": timeline,
        "positionMixMoved": position_mix,
        "picksMovedCount": picks_moved,
        "playersMovedCount": players_moved,
    }
