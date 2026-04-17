"""Section: League Superlatives.

Roster-composition + activity superlatives.  Everything is derived
from public-safe inputs only — Sleeper roster lists, Sleeper player
position lookups, trade/waiver counts, draft-pick ownership.

Output per superlative is a single winner row + the full ranking for
transparency.

Supported superlatives:
    * most_qb_heavy    — highest QB count on the active roster
    * most_rb_heavy    — RB
    * most_wr_heavy    — WR
    * most_te_heavy    — TE
    * most_idp_heavy   — DL+DB+LB+EDGE+S+CB count
    * most_pick_heavy  — most weighted draft capital owned
    * most_rookie_heavy — count of players whose Sleeper ``years_exp`` == 0
    * most_balanced    — lowest standard deviation across QB/RB/WR/TE
    * most_active      — most trades + waivers in the 2-season window
    * most_future_focused — pick-heavy + rookie-heavy blended score

Tiebreaks use additional roster-composition counts, then weighted
pick score, then owner_id alpha order for determinism.  No private
rank / value is ever exposed on the output.
"""
from __future__ import annotations

import math
from typing import Any

from . import metrics
from .draft import pick_weight, _pick_ownership_map
from .snapshot import PublicLeagueSnapshot


POSITION_GROUPS = ("QB", "RB", "WR", "TE")
IDP_POSITIONS = {"DL", "DE", "DT", "LB", "DB", "CB", "S", "EDGE"}


def _roster_composition(snapshot: PublicLeagueSnapshot) -> dict[str, dict[str, Any]]:
    """Per-owner composition of the CURRENT roster.

    Keys:
        qb, rb, wr, te, idp, rookies, total, byPos, rosterSize
    """
    current = snapshot.current_season
    if current is None:
        return {}
    out: dict[str, dict[str, Any]] = {}
    for roster in current.rosters:
        try:
            rid = int(roster.get("roster_id"))
        except (TypeError, ValueError):
            continue
        owner_id = metrics.resolve_owner(snapshot.managers, current.league_id, rid)
        if not owner_id:
            continue
        counts = {pos: 0 for pos in POSITION_GROUPS}
        idp = 0
        rookies = 0
        by_pos: dict[str, int] = {}
        player_ids = roster.get("players") or []
        for pid in player_ids:
            pos = snapshot.player_position(pid)
            by_pos[pos or "UNK"] = by_pos.get(pos or "UNK", 0) + 1
            if pos in POSITION_GROUPS:
                counts[pos] += 1
            if pos in IDP_POSITIONS:
                idp += 1
            p = snapshot.nfl_players.get(str(pid)) or {}
            yx = p.get("years_exp")
            try:
                if int(yx) == 0:
                    rookies += 1
            except (TypeError, ValueError):
                pass
        out[owner_id] = {
            "rosterSize": len(player_ids),
            "qb": counts["QB"],
            "rb": counts["RB"],
            "wr": counts["WR"],
            "te": counts["TE"],
            "idp": idp,
            "rookies": rookies,
            "byPos": by_pos,
        }
    return out


def _balance_score(entry: dict[str, int]) -> float:
    """Lower = more balanced QB/RB/WR/TE mix."""
    vals = [entry["qb"], entry["rb"], entry["wr"], entry["te"]]
    mean = sum(vals) / len(vals) if vals else 0.0
    var = sum((v - mean) ** 2 for v in vals) / len(vals) if vals else 0.0
    return math.sqrt(var)


def _activity_counts(snapshot: PublicLeagueSnapshot) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    for season in snapshot.seasons:
        for tx in season.trades():
            for rid in tx.get("roster_ids") or []:
                owner_id = metrics.resolve_owner(snapshot.managers, season.league_id, rid)
                if owner_id:
                    out.setdefault(owner_id, {"trades": 0, "waivers": 0})
                    out[owner_id]["trades"] += 1
        for tx in season.waivers():
            for rid in tx.get("roster_ids") or []:
                owner_id = metrics.resolve_owner(snapshot.managers, season.league_id, rid)
                if owner_id:
                    out.setdefault(owner_id, {"trades": 0, "waivers": 0})
                    out[owner_id]["waivers"] += 1
    return out


def _pick_weight_totals(snapshot: PublicLeagueSnapshot) -> dict[str, int]:
    ownership = _pick_ownership_map(snapshot)
    return {
        owner_id: sum(pick_weight(p["round"]) for p in picks)
        for owner_id, picks in ownership.items()
    }


def _ranking(rows: list[dict[str, Any]], key_primary, key_tiebreak_1=None, key_tiebreak_2=None) -> list[dict[str, Any]]:
    def sort_key(row):
        tb1 = key_tiebreak_1(row) if key_tiebreak_1 else 0
        tb2 = key_tiebreak_2(row) if key_tiebreak_2 else 0
        return (-key_primary(row), -tb1, -tb2, row["ownerId"])

    return sorted(rows, key=sort_key)


def build_section(snapshot: PublicLeagueSnapshot) -> dict[str, Any]:
    composition = _roster_composition(snapshot)
    activity = _activity_counts(snapshot)
    weighted = _pick_weight_totals(snapshot)

    rows = []
    for owner_id, comp in composition.items():
        rows.append({
            "ownerId": owner_id,
            "displayName": metrics.display_name_for(snapshot, owner_id),
            "rosterSize": comp["rosterSize"],
            "qb": comp["qb"],
            "rb": comp["rb"],
            "wr": comp["wr"],
            "te": comp["te"],
            "idp": comp["idp"],
            "rookies": comp["rookies"],
            "trades": activity.get(owner_id, {}).get("trades", 0),
            "waivers": activity.get(owner_id, {}).get("waivers", 0),
            "weightedPickScore": weighted.get(owner_id, 0),
            "balanceScore": round(_balance_score(comp), 4),
        })

    def _winner(ranked: list[dict[str, Any]]) -> dict[str, Any] | None:
        return ranked[0] if ranked else None

    by_qb = _ranking(rows, lambda r: r["qb"], lambda r: r["rosterSize"], lambda r: r["weightedPickScore"])
    by_rb = _ranking(rows, lambda r: r["rb"], lambda r: r["rosterSize"], lambda r: r["weightedPickScore"])
    by_wr = _ranking(rows, lambda r: r["wr"], lambda r: r["rosterSize"], lambda r: r["weightedPickScore"])
    by_te = _ranking(rows, lambda r: r["te"], lambda r: r["rosterSize"], lambda r: r["weightedPickScore"])
    by_idp = _ranking(rows, lambda r: r["idp"], lambda r: r["rosterSize"], lambda r: r["weightedPickScore"])
    by_picks = _ranking(rows, lambda r: r["weightedPickScore"], lambda r: r["rosterSize"])
    by_rookies = _ranking(rows, lambda r: r["rookies"], lambda r: r["rosterSize"], lambda r: r["weightedPickScore"])
    by_active = _ranking(rows, lambda r: r["trades"] + r["waivers"], lambda r: r["trades"], lambda r: r["waivers"])
    # future-focused: pick-heavy + rookie-heavy blended
    by_future = _ranking(
        rows,
        lambda r: r["weightedPickScore"] * 2 + r["rookies"],
        lambda r: r["weightedPickScore"],
        lambda r: r["rookies"],
    )
    # Most balanced is ASCENDING balance score (lower = more balanced).
    by_balanced = sorted(rows, key=lambda r: (r["balanceScore"], r["ownerId"]))

    def _pack(winner: dict[str, Any] | None, ranking: list[dict[str, Any]]) -> dict[str, Any]:
        return {"winner": winner, "ranking": ranking}

    return {
        "seasonsCovered": [s.season for s in snapshot.seasons],
        "mostQbHeavy": _pack(_winner(by_qb), by_qb),
        "mostRbHeavy": _pack(_winner(by_rb), by_rb),
        "mostWrHeavy": _pack(_winner(by_wr), by_wr),
        "mostTeHeavy": _pack(_winner(by_te), by_te),
        "mostIdpHeavy": _pack(_winner(by_idp), by_idp),
        "mostPickHeavy": _pack(_winner(by_picks), by_picks),
        "mostRookieHeavy": _pack(_winner(by_rookies), by_rookies),
        "mostBalanced": _pack(by_balanced[0] if by_balanced else None, by_balanced),
        "mostActive": _pack(_winner(by_active), by_active),
        "mostFutureFocused": _pack(_winner(by_future), by_future),
    }
