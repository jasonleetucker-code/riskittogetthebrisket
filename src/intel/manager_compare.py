"""Manager Intelligence Batch E — manager comparisons.

Two views, both built from blocks other batches already compute — no new
valuation and no new math beyond a percentile over an existing column:

* :func:`build_manager_comparison` — two managers side by side.  For each,
  the SAME payloads the single-manager surfaces serve: the Batch A portfolio
  ``summary``, the B3 ``tendencies`` and ``draftCapital.totals`` and B2
  ``analytics`` from the activity payload read with ``window="season"``, and
  the Batch E career ``totals`` + ``archetypes``.  Each block is passed
  through verbatim (the tests pin that a compared block equals the one the
  single-manager route returns).  The career archetypes are evaluated over
  the very profile and activity payloads shown beside them, so nothing is
  read twice.

* :func:`build_league_percentile` — how one manager compares to the rest of
  ONE league, over the Batch C scouting rows
  (``manager_league.cached_league_scouting``): roster value, activity and
  picks.  The percentile is declared (``PERCENTILE_DEFINITION``); a manager
  without a value for a metric gets ``None`` + the reason (never a rank of
  last), and a metric is ranked only over the rows that have it.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

from src.intel import manager_activity as ma
from src.intel import manager_career as mc
from src.intel import manager_league as ml
from src.intel import manager_portfolio as mp
from src.public_league import sleeper_client

Provider = Callable[..., dict[str, Any]]
Fetch = Callable[..., tuple[str, Any]]

PERCENTILE_DEFINITION = (
    "share of the OTHER teams with a known value that this team is above, counting a "
    "tie as half: (below + 0.5 x tied) / (teams with a value - 1); higher = more"
)

#: ``(key, label, path into a Batch C row, reason when a value is missing)``.
LEAGUE_METRICS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("rosterValue", "Roster value (canonical board)", ("roster", "pricedValue")),
    ("pickValue", "Draft pick value", ("draftCapital", "pricedValue")),
    ("picksHeld", "Draft picks held", ("draftCapital", "counts", "held")),
    ("trades", "Completed trades", ("activity", "trades")),
    ("events", "Transactions (all kinds)", ("activity", "events")),
    ("playersAdded", "Players added", ("activity", "playersAdded")),
)

_OK = (mp.STATUS_OK, mp.STATUS_PARTIAL)


def _dig(row: dict[str, Any], path: tuple[str, ...]) -> Any:
    cur: Any = row
    for key in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur if isinstance(cur, (int, float)) and not isinstance(cur, bool) else None


def percentile(value: float | None, others: list[float]) -> float | None:
    """See :data:`PERCENTILE_DEFINITION`.  ``others`` excludes this team and
    holds only known values; ``None`` when there is nothing to compare."""
    if value is None or not others:
        return None
    below = sum(1 for o in others if o < value)
    tied = sum(1 for o in others if o == value)
    return round((below + 0.5 * tied) / len(others), 4)


def _side_blocks(
    username: str,
    *,
    contract: dict[str, Any] | None,
    scope: str,
    profile_provider: Provider,
    activity_provider: Provider,
    career_provider: Provider,
) -> dict[str, Any]:
    profile = profile_provider(username, contract=contract, scope=scope)
    if profile.get("status") not in _OK:
        return {"status": profile.get("status"), "query": username}
    activity = activity_provider(username, contract=contract, window="season", scope=scope)
    career = career_provider(
        username,
        contract=contract,
        scope=scope,
        profile_payload=profile,
        activity_payload=activity,
    )
    act_ok = activity.get("status") in _OK
    career_ok = career.get("status") in _OK
    dc = (activity.get("draftCapital") or {}) if act_ok else {}
    statuses = [profile.get("status"), activity.get("status"), career.get("status")]
    return {
        "status": mp.STATUS_OK if all(s == mp.STATUS_OK for s in statuses) else mp.STATUS_PARTIAL,
        "query": username,
        "manager": profile.get("manager"),
        "sources": {
            "profile": profile.get("status"),
            "activity": activity.get("status"),
            "career": career.get("status"),
        },
        "season": profile.get("season"),
        "leagueCount": profile.get("leaguesInScope"),
        "leagueIds": [lg.get("leagueId") for lg in profile.get("leagues") or []],
        "portfolio": profile.get("summary"),
        "tendencies": activity.get("tendencies") if act_ok else None,
        "analytics": activity.get("analytics") if act_ok else None,
        "draftCapital": dc.get("totals") if dc.get("available") else None,
        "draftCapitalReason": None if dc.get("available") else dc.get("reason") or "unavailable",
        "career": career.get("totals") if career_ok else None,
        "archetypes": career.get("archetypes") if career_ok else None,
    }


def build_manager_comparison(
    a: str,
    b: str,
    *,
    contract: dict[str, Any] | None,
    scope: str = mp.SCOPE_DYNASTY,
    profile_provider: Provider = mp.cached_manager_profile,
    activity_provider: Provider = ma.cached_manager_activity,
    career_provider: Provider = mc.cached_manager_career,
    now: Callable[[], float] = time.time,
) -> dict[str, Any]:
    """Two managers side by side.  ``status`` is ``ok`` / ``partial`` (a
    block of either side not fully read) or the first failing side's status
    (``not_found`` / ``rate_limited`` / ``upstream_unavailable``) with
    ``failedSide``."""
    if scope not in mp.SCOPES:
        scope = mp.SCOPE_DYNASTY
    kwargs = {
        "contract": contract,
        "scope": scope,
        "profile_provider": profile_provider,
        "activity_provider": activity_provider,
        "career_provider": career_provider,
    }
    with ThreadPoolExecutor(max_workers=2) as pool:
        fa = pool.submit(_side_blocks, a, **kwargs)
        fb = pool.submit(_side_blocks, b, **kwargs)
        side_a, side_b = fa.result(), fb.result()
    for name, side in (("a", side_a), ("b", side_b)):
        if side.get("status") not in _OK:
            return {
                "status": side.get("status") or mp.STATUS_UPSTREAM_UNAVAILABLE,
                "failedSide": name,
                "query": {"a": a, "b": b},
            }
    ids_a = set(side_a.get("leagueIds") or [])
    shared = [lid for lid in side_b.get("leagueIds") or [] if lid in ids_a]
    same = (side_a.get("manager") or {}).get("userId") == (side_b.get("manager") or {}).get(
        "userId"
    )
    return {
        "status": mp.STATUS_OK
        if side_a["status"] == side_b["status"] == mp.STATUS_OK
        else mp.STATUS_PARTIAL,
        "query": {"a": a, "b": b},
        "scope": scope,
        "a": side_a,
        "b": side_b,
        "sameManager": same,
        "sharedLeagueIds": shared,
        "basis": (
            "Each column is the same block the single-manager views show — portfolio summary, "
            "season tendencies and draft capital, career totals and archetypes — side by side. "
            "Nothing is re-computed for the comparison."
        ),
        "fetchedAt": int(now() * 1000),
    }


def build_league_percentile(
    username: str,
    league_id: str,
    *,
    contract: dict[str, Any] | None,
    window: str = ma.DEFAULT_WINDOW,
    fetch_user: Fetch = sleeper_client.fetch_user_classified,
    league_provider: Provider = ml.cached_league_scouting,
    now: Callable[[], float] = time.time,
) -> dict[str, Any]:
    """Where ``username``'s team sits in one league, over the Batch C rows.

    The team is matched by its CURRENT owner's Sleeper user id (Batch C rows
    publish only that); a manager who is only a co-owner, or not in the
    league, gets ``managerInLeague: False`` and no percentiles."""
    kind, user = fetch_user(username)
    if kind != sleeper_client.FETCH_OK:
        return {
            "status": {
                sleeper_client.FETCH_NOT_FOUND: mp.STATUS_NOT_FOUND,
                sleeper_client.FETCH_RATE_LIMITED: mp.STATUS_RATE_LIMITED,
            }.get(kind, mp.STATUS_UPSTREAM_UNAVAILABLE),
            "failedSide": "a",
            "query": {"a": username, "leagueId": league_id},
        }
    user_id = str(user["user_id"])
    scouting = league_provider(league_id, contract=contract, window=window)
    if scouting.get("status") not in _OK:
        return {
            "status": scouting.get("status") or mp.STATUS_UPSTREAM_UNAVAILABLE,
            "failedSide": "league",
            "query": {"a": username, "leagueId": league_id},
        }
    rows = scouting.get("managers") or []
    mine = next((r for r in rows if r.get("ownerUserId") == user_id), None)
    metrics = []
    for key, label, path in LEAGUE_METRICS:
        known = {r["rosterId"]: _dig(r, path) for r in rows}
        known = {rid: v for rid, v in known.items() if v is not None}
        value = _dig(mine, path) if mine is not None else None
        others = [v for rid, v in known.items() if mine is None or rid != mine["rosterId"]]
        reason = None
        if mine is None:
            reason = "manager_not_in_league"
        elif value is None:
            if path[0] == "roster":
                reason = (mine.get("roster") or {}).get("valueNote") or "unpriced"
            elif path[0] == "draftCapital":
                cap = mine.get("draftCapital") or {}
                if cap.get("reason"):
                    reason = cap["reason"]  # e.g. an earlier season: picks not read
                elif cap.get("counts") is None:
                    reason = cap.get("pickOwnershipReason") or "pick_ownership_unavailable"
                else:
                    # Ownership observed; the picks held carry no board value.
                    reason = next(iter(cap.get("unpricedReasons") or {}), None) or "unpriced"
            else:
                reason = "unavailable"
        metrics.append(
            {
                "key": key,
                "label": label,
                "value": value,
                "leagueMedian": _median(list(known.values())),
                "teamsWithValue": len(known),
                "percentile": percentile(value, others),
                "reason": reason,
            }
        )
    return {
        "status": scouting.get("status"),
        "query": {"a": username, "leagueId": league_id},
        "manager": {
            "userId": user_id,
            "username": user.get("username") or None,
            "displayName": user.get("display_name") or user.get("username") or None,
        },
        "managerInLeague": mine is not None,
        "notInLeagueReason": None if mine is not None else "not_a_current_owner",
        "league": scouting.get("league"),
        "season": scouting.get("season"),
        "window": scouting.get("window"),
        "windowApplied": scouting.get("windowApplied"),
        "teamCount": len(rows),
        "team": None
        if mine is None
        else {
            "rosterId": mine["rosterId"],
            "displayName": mine.get("displayName"),
            "teamName": mine.get("teamName"),
            "record": mine.get("record"),
            "valueRank": mine.get("valueRank"),
        },
        "metrics": metrics,
        "percentileDefinition": PERCENTILE_DEFINITION,
        "coverage": scouting.get("coverage"),
        "fetchedAt": int(now() * 1000),
    }


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    v = sorted(values)
    mid = len(v) // 2
    return v[mid] if len(v) % 2 else (v[mid - 1] + v[mid]) / 2


__all__ = [
    "LEAGUE_METRICS",
    "PERCENTILE_DEFINITION",
    "build_league_percentile",
    "build_manager_comparison",
    "percentile",
]
