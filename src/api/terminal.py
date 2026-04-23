"""Terminal aggregation endpoint — one call for the landing page.

Moves to the server:

* Team aggregates — total value, 7d/30d deltas, tier distribution
* Market movers — roster / league / top150 scoped rank-change lists
* Window trends + MAD volatility per player
* Signal evaluation — the rule-driven Buy/Sell/Hold classifier
* Portfolio insights — best asset / biggest risk / trade chip / buy-low
* Roster-aware historical value (reconstructs past rosters from trades)
* News scoping — per-team relevance tagging

Design goals:

* One authoritative rank→value curve (``rank_to_value`` in the
  canonical pipeline).  The frontend's hand-maintained Hill
  constants duplicated this; we no longer want the frontend doing
  any value math at all — it just renders stamped numbers.
* No surprise per-team work: passing ``resolved_team=None`` still
  returns market movers and signals-less context, so the landing
  page renders something coherent for users who haven't picked a
  team yet.
* Stable shape: every consumer reads ``payload['teamAggregates']``,
  ``payload['movers']``, etc. — keys never disappear when a sub-
  section has no data (``None`` or ``[]`` instead).

The payload is cheap to build (<50ms on a warm cache) but we stamp
``generatedAt`` so the frontend can display age relative to the last
scrape.
"""
from __future__ import annotations

import statistics
from datetime import datetime, timezone
from typing import Any, Callable, Iterable

from src.canonical.player_valuation import rank_to_value as _rank_to_value
from src.api import rank_history as _rank_history


# ── CONSTANTS ───────────────────────────────────────────────────────────

# Tier cutoffs match the terminal header + portfolio summary visual
# story.  Keep in sync with the frontend's `tierBucket` helper.
TIER_CUTOFFS = (
    ("elite", 8500),
    ("high", 6500),
    ("mid", 3000),
    ("depth", 0),
)

# Value-adjacent helpers — identical semantics to the old frontend
# module, re-implemented here so there is one authority.
POS_GROUPS = ("QB", "RB", "WR", "TE", "K", "DEF", "IDP", "PICK")

IDP_POSITIONS = frozenset({
    "DL", "DE", "DT", "EDGE", "NT", "LB", "OLB", "ILB", "MLB",
    "DB", "CB", "S", "FS", "SS", "IDP",
})


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _normalize_pos(pos: Any) -> str:
    p = str(pos or "").upper()
    if p in {"DB", "LB", "DL", "DE", "DT", "CB", "S", "EDGE", "NT",
             "OLB", "ILB", "MLB", "FS", "SS"}:
        return "IDP"
    if p == "PK":
        return "K"
    return p or "?"


def _tier_bucket(value: float | int) -> str:
    v = float(value or 0)
    for label, cutoff in TIER_CUTOFFS:
        if v >= cutoff:
            return label
    return "depth"


# ── ROW LOOKUP ──────────────────────────────────────────────────────────


def _row_name(row: dict[str, Any]) -> str:
    return str(row.get("displayName") or row.get("canonicalName") or row.get("name") or "")


def _row_value(row: dict[str, Any]) -> float:
    # Prefer the server-stamped ``rankDerivedValue`` (part of the
    # canonical contract).  Fall back to ``values.full`` or rank-
    # derived Hill if neither is present, so we never render 0 for
    # a ranked player with a stamped rank.
    v = row.get("rankDerivedValue")
    if isinstance(v, (int, float)) and v > 0:
        return float(v)
    values = row.get("values") or {}
    if isinstance(values, dict):
        vf = values.get("full")
        if isinstance(vf, (int, float)) and vf > 0:
            return float(vf)
    rank = row.get("canonicalConsensusRank")
    if isinstance(rank, (int, float)) and rank > 0:
        return float(_rank_to_value(float(rank)))
    return 0.0


def _row_rank(row: dict[str, Any]) -> int | None:
    r = row.get("canonicalConsensusRank")
    if isinstance(r, (int, float)) and r > 0:
        return int(r)
    return None


def _row_rank_change(row: dict[str, Any]) -> int | None:
    c = row.get("rankChange")
    if isinstance(c, (int, float)):
        return int(c)
    return None


def _players_array(contract: dict[str, Any]) -> list[dict[str, Any]]:
    arr = contract.get("playersArray")
    if isinstance(arr, list):
        return [r for r in arr if isinstance(r, dict)]
    players = contract.get("players") or {}
    if isinstance(players, dict):
        out: list[dict[str, Any]] = []
        for name, row in players.items():
            if isinstance(row, dict):
                row = {"displayName": name, **row}
                out.append(row)
        return out
    return []


def _build_row_index(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    idx: dict[str, dict[str, Any]] = {}
    for r in rows:
        key = _row_name(r).strip().lower()
        if key:
            idx[key] = r
    return idx


# ── TEAM RESOLUTION ─────────────────────────────────────────────────────


def resolve_team(
    contract: dict[str, Any],
    *,
    owner_id: str | None = None,
    name: str | None = None,
) -> dict[str, Any] | None:
    """Pick a team from ``contract.sleeper.teams`` by ownerId (preferred)
    or name (fallback for legacy localStorage-keyed selections).

    Returns ``None`` if nothing matches — callers render the "pick
    your team" state and still get a populated league/top150 payload.
    """
    sleeper = contract.get("sleeper") or {}
    teams = sleeper.get("teams") or []
    if not isinstance(teams, list):
        return None
    if owner_id:
        oid = str(owner_id).strip()
        for t in teams:
            if not isinstance(t, dict):
                continue
            if str(t.get("ownerId") or "").strip() == oid:
                return t
    if name:
        needle = str(name).strip().lower()
        for t in teams:
            if not isinstance(t, dict):
                continue
            if str(t.get("name") or "").strip().lower() == needle:
                return t
    return None


# ── HISTORY + TRENDS ────────────────────────────────────────────────────


def _normalize_points(raw: Iterable[Any] | None) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    points: list[dict[str, Any]] = []
    for p in raw:
        if not isinstance(p, dict):
            continue
        try:
            rank = int(p.get("rank"))
        except (TypeError, ValueError):
            continue
        if rank <= 0:
            continue
        date = p.get("date")
        if not isinstance(date, str):
            continue
        try:
            t = int(datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() * 1000)
        except ValueError:
            continue
        points.append({"date": date, "t": t, "rank": rank})
    points.sort(key=lambda p: p["t"])
    return points


def _window_trend(points: list[dict[str, Any]], window_days: int) -> int | None:
    if not points:
        return None
    latest = points[-1]
    cutoff = latest["t"] - int(window_days) * 86_400_000
    baseline = None
    for p in points:
        if p["t"] >= cutoff:
            baseline = p
            break
    if baseline is None or baseline is latest:
        return None if baseline is None else 0
    return int(baseline["rank"]) - int(latest["rank"])


def _volatility(points: list[dict[str, Any]], window_days: int = 30) -> dict[str, Any] | None:
    if len(points) < 3:
        return None
    latest = points[-1]
    cutoff = latest["t"] - int(window_days) * 86_400_000
    window = [p for p in points if p["t"] >= cutoff]
    if len(window) < 3:
        return None
    deltas = [abs(window[i]["rank"] - window[i - 1]["rank"]) for i in range(1, len(window))]
    med = statistics.median(deltas)
    devs = [abs(d - med) for d in deltas]
    mad = statistics.median(devs)
    if mad <= 1:
        label = "low"
    elif mad <= 4:
        label = "med"
    else:
        label = "high"
    return {"mad": round(float(mad), 2), "label": label}


def _history_lookup(history: dict[str, Any] | None) -> Callable[[str], list[dict[str, Any]]]:
    """Build a case-insensitive rank-history lookup, tolerant of
    the ``"name::assetClass"`` composite keys written by the history
    log.
    """
    if not isinstance(history, dict):
        return lambda _name: []
    lower: dict[str, list[Any]] = {}
    lower_base: dict[str, list[Any]] = {}
    for key, series in history.items():
        if not isinstance(key, str):
            continue
        low = key.lower()
        lower[low] = series if isinstance(series, list) else []
        base = low.split("::", 1)[0] if "::" in low else low
        lower_base.setdefault(base, series if isinstance(series, list) else [])

    def _lookup(name: str) -> list[dict[str, Any]]:
        if not name:
            return []
        needle = str(name).strip().lower()
        if not needle:
            return []
        hit = lower.get(needle) or lower_base.get(needle)
        return hit if isinstance(hit, list) else []

    return _lookup


# ── ROSTER RECONSTRUCTION (historical) ──────────────────────────────────


def _reconstruct_roster_at(
    contract: dict[str, Any],
    *,
    owner_id: str,
    current_players: list[str],
    cutoff_ms: int,
) -> tuple[list[str], dict[str, Any]]:
    """Reverse-apply completed trades back to ``cutoff_ms``.

    Returns ``(roster_list, coverage_report)``.  The coverage report
    has the shape::

        {
          "rosterAware":   bool,   # True iff ≥1 trade for this owner
                                   # actually moved the roster
          "tradesSeen":    int,    # total trades in window, any owner
          "tradesApplied": int,    # trades that touched this owner
          "reason":        str,    # one of "no_owner" / "no_trades" /
                                   # "no_trades_for_owner" / "applied"
        }

    ``rosterAware: True`` ONLY when a trade actually un-did some of
    the current roster.  The prior version set it True even when the
    trades list was empty, which was a lie — a static-roster delta
    dressed up as history-aware.  Now the frontend can render "delta
    (static)" vs "delta (roster-aware)" honestly.

    Uses ``sleeper.trades[]`` (already present in the live contract,
    see ``Dynasty Scraper.py::roster_data["trades"]``).  Each trade
    carries ``sides[].{ownerId, got, gave}`` — applying each trade
    AFTER ``cutoff_ms`` in reverse means:

        * remove from roster items this owner GOT in that trade
        * add back items this owner GAVE away in that trade

    Cross-universe collisions (same name, different assetClass) are
    accepted as-is: the live contract's display-name index already
    collapses them, so a reconstruction using display names inherits
    the same collapse.
    """
    coverage: dict[str, Any] = {
        "rosterAware": False,
        "tradesSeen": 0,
        "tradesApplied": 0,
        "reason": "applied",
    }
    if not owner_id:
        coverage["reason"] = "no_owner"
        return list(current_players or []), coverage
    sleeper = contract.get("sleeper") or {}
    trades = sleeper.get("trades") or []
    if not isinstance(trades, list) or not trades:
        coverage["reason"] = "no_trades"
        return list(current_players or []), coverage

    roster = set(current_players or [])
    seen = 0
    applied = 0
    # Reverse-order iteration through completed trades, applying the
    # inverse: UNDO each trade for this owner back until we cross the
    # cutoff.  ``trades`` is already sorted newest-first in the
    # scraper output; trades[].timestamp is in ms.
    for tx in trades:
        if not isinstance(tx, dict):
            continue
        try:
            ts = int(tx.get("timestamp") or 0)
        except (TypeError, ValueError):
            continue
        if ts <= cutoff_ms:
            # This trade (and everything older) is OLDER than the
            # requested cutoff — we've already walked past the cutoff.
            break
        seen += 1
        sides = tx.get("sides") or []
        if not isinstance(sides, list):
            continue
        touched_this_owner = False
        for side in sides:
            if not isinstance(side, dict):
                continue
            if str(side.get("ownerId") or "").strip() != owner_id:
                continue
            got = side.get("got") or []
            gave = side.get("gave") or []
            if isinstance(got, list):
                for item in got:
                    roster.discard(str(item))
                    touched_this_owner = touched_this_owner or bool(item)
            if isinstance(gave, list):
                for item in gave:
                    roster.add(str(item))
                    touched_this_owner = touched_this_owner or bool(item)
        if touched_this_owner:
            applied += 1

    coverage["tradesSeen"] = seen
    coverage["tradesApplied"] = applied
    coverage["rosterAware"] = applied > 0
    if seen == 0:
        coverage["reason"] = "no_trades"
    elif applied == 0:
        coverage["reason"] = "no_trades_for_owner"
    return sorted(roster), coverage


_MIN_COVERAGE_FOR_RELIABLE_SUM: float = 0.60


def _sum_roster_value_at_date(
    roster_names: list[str],
    *,
    history_by_name: Callable[[str], list[dict[str, Any]]],
    date: str,
    row_index: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Sum Hill-curve values of ``roster_names`` at the closest
    snapshot date ≤ ``date``.

    Returns a dict::

        {
          "value":            int | None,  # sum; None when unreliable
          "resolved":         int,         # players with ≥1 matching snapshot
          "expected":         int,         # len(roster_names)
          "coverageFraction": float,       # resolved / expected
          "reliable":         bool,        # coverageFraction ≥ 0.60
        }

    The prior version returned a bare ``int | None``, which hid the
    distinction between "no data at all" and "60%+ coverage, we
    chose not to emit because the remaining players would have
    biased the sum".  Exposing the coverage lets the frontend render
    an explicit "insufficient history (32% coverage)" hint instead
    of a silent "—".
    """
    expected = len(roster_names or [])
    result: dict[str, Any] = {
        "value": None,
        "resolved": 0,
        "expected": expected,
        "coverageFraction": 0.0,
        "reliable": False,
    }
    if expected == 0:
        return result

    target = date
    resolved = 0
    total = 0
    for name in roster_names:
        points = history_by_name(name) or []
        if not points:
            continue
        chosen = None
        for p in sorted(points, key=lambda x: x.get("date") or ""):
            d = p.get("date")
            r = p.get("rank")
            if not isinstance(d, str) or not isinstance(r, (int, float)):
                continue
            if d <= target:
                chosen = r
            else:
                break
        if chosen is None:
            continue
        total += int(_rank_to_value(float(chosen)))
        resolved += 1

    coverage = resolved / max(1, expected)
    result["resolved"] = resolved
    result["coverageFraction"] = round(coverage, 3)
    result["reliable"] = coverage >= _MIN_COVERAGE_FOR_RELIABLE_SUM
    # Low-coverage guard: under-covered sum is biased against missing
    # players.  Leave ``value`` None so the UI surfaces the hint.
    if result["reliable"]:
        result["value"] = total
    return result


# ── MOVERS ──────────────────────────────────────────────────────────────


def _compute_movers(
    rows: list[dict[str, Any]],
    *,
    scope: str,
    roster_set: set[str],
    league_set: set[str],
    limit: int = 20,
) -> list[dict[str, Any]]:
    if scope == "roster":
        pool = [r for r in rows if _row_name(r).lower() in roster_set]
    elif scope == "league":
        pool = [r for r in rows if _row_name(r).lower() in league_set]
    else:
        pool = [r for r in rows if isinstance(r.get("canonicalConsensusRank"), (int, float))
                and 0 < (r.get("canonicalConsensusRank") or 0) <= 150]
    moved: list[dict[str, Any]] = []
    for r in pool:
        c = _row_rank_change(r)
        if c is None or c == 0:
            continue
        moved.append({
            "name": _row_name(r),
            "pos": _normalize_pos(r.get("pos") or r.get("position")),
            "value": int(_row_value(r)),
            "rank": _row_rank(r),
            "change": c,
            "onRoster": _row_name(r).lower() in roster_set,
        })
    moved.sort(key=lambda m: (abs(m["change"]), m["value"]), reverse=True)
    return moved[:limit]


# ── SIGNAL EVALUATION (server-side rule engine) ─────────────────────────


# Rule order + priority mirrors ``frontend/lib/signal-engine.js``; the
# frontend engine is kept as a fallback but the authoritative output
# comes from this pass.  Each rule: (priority, signal, tag, test, reason).
def _build_signal_context(
    row: dict[str, Any],
    *,
    points: list[dict[str, Any]],
    news_for_player: list[dict[str, Any]],
) -> dict[str, Any]:
    trend7 = _window_trend(points, 7)
    trend30 = _window_trend(points, 30)
    volatility = _volatility(points, 30)
    alert_count = 0
    neg_count = 0
    pos_count = 0
    for it in news_for_player:
        if it.get("severity") == "alert":
            alert_count += 1
        for p in it.get("players") or []:
            impact = p.get("impact") if isinstance(p, dict) else None
            if impact == "negative":
                neg_count += 1
            elif impact == "positive":
                pos_count += 1
    rank_change = _row_rank_change(row)
    confidence = row.get("confidence")
    try:
        confidence = float(confidence) if confidence is not None else None
    except (TypeError, ValueError):
        confidence = None
    # Sleeper ID is a stable identifier across renames — every row
    # in the contract carries either ``sleeperId`` (modern) or
    # ``_sleeperId`` (legacy dict).  We surface both on the signal
    # context so the frontend can maintain a rename-resistant
    # dismissal alias map.
    sleeper_id = (
        row.get("sleeperId")
        or row.get("_sleeperId")
        or (row.get("raw") or {}).get("_sleeperId")
        or ""
    )
    return {
        "name": _row_name(row),
        "sleeperId": str(sleeper_id) if sleeper_id else "",
        "pos": _normalize_pos(row.get("pos") or row.get("position")),
        "value": int(_row_value(row)),
        "rank": _row_rank(row),
        "rankChange": rank_change,
        "confidence": confidence,
        "trend7": trend7,
        "trend30": trend30,
        "volatility": volatility,
        "alertCount": alert_count,
        "negativeImpactCount": neg_count,
        "positiveImpactCount": pos_count,
        "newsCount": len(news_for_player),
    }


def _fmt_delta(v: int | float | None) -> str:
    if v is None:
        return "—"
    if v == 0:
        return "·"
    return f"+{int(v)}" if v > 0 else f"{int(v)}"


def _evaluate_signal(ctx: dict[str, Any]) -> dict[str, Any]:
    fired: list[dict[str, Any]] = []
    trend7 = ctx.get("trend7")
    trend30 = ctx.get("trend30")
    vol_label = (ctx.get("volatility") or {}).get("label")
    mad = (ctx.get("volatility") or {}).get("mad")
    value = ctx.get("value") or 0
    rank_change = ctx.get("rankChange")
    conf = ctx.get("confidence")
    alert = ctx.get("alertCount") or 0
    neg = ctx.get("negativeImpactCount") or 0
    pos = ctx.get("positiveImpactCount") or 0

    def add(priority: int, signal: str, tag: str, reason: str) -> None:
        fired.append({
            "priority": priority,
            "signal": signal,
            "tag": tag,
            "reason": reason,
        })

    if alert > 0 and neg > 0 and (trend7 is not None and trend7 <= -3):
        add(100, "RISK", "alert_with_drop",
            f"Alert-severity news alongside a 7d drop of {_fmt_delta(trend7)}.")
    if vol_label == "high" and (trend7 is not None and trend7 <= -5):
        add(95, "RISK", "high_vol_drop",
            f"High volatility (MAD {float(mad or 0):.1f}) with a steep 7d drop of {_fmt_delta(trend7)}.")
    if (trend7 is not None and trend7 <= -3) and (trend30 is not None and trend30 <= 0):
        add(80, "SELL", "sustained_downtrend",
            f"7d trend {_fmt_delta(trend7)} continues a 30d trend of {_fmt_delta(trend30)}.")
    if neg > 0 and vol_label == "high":
        add(78, "SELL", "neg_news_high_vol",
            f"Negative news with high volatility (MAD {float(mad or 0):.1f}).")
    if alert > 0:
        add(65, "MONITOR", "alert_present",
            f"{alert} alert-severity headline{'' if alert == 1 else 's'} — watch for follow-up.")
    if vol_label == "high":
        add(62, "MONITOR", "high_vol",
            f"High volatility (MAD {float(mad or 0):.1f}).")
    if conf is not None and conf < 0.35 and (
        vol_label == "med" or (trend7 is not None and abs(trend7) >= 2)
    ):
        add(60, "MONITOR", "low_conf_unstable",
            f"Low market confidence ({conf * 100:.0f}%) plus recent movement.")
    if value >= 7000 and (trend30 is not None and trend30 >= 0) and vol_label in ("low", "med"):
        add(50, "STRONG_HOLD", "elite_stable",
            f"Elite value ({int(value):,}) with a non-negative 30d trend and non-high volatility.")
    if (trend7 is not None and trend7 >= 3) and vol_label != "high":
        add(40, "BUY", "uptrend_controlled",
            f"7d trend of {_fmt_delta(trend7)} and volatility {vol_label or '—'}.")
    if pos > 0 and (rank_change is not None and rank_change > 0):
        add(38, "BUY", "pos_news_rising",
            f"Positive news with rank rising {_fmt_delta(rank_change)} on the last scrape.")

    fired.sort(key=lambda r: -r["priority"])
    if not fired:
        return {
            "signal": "HOLD",
            "reason": "Stable — no movement, volatility, or news triggers.",
            "tag": "default_hold",
            "fired": [],
        }
    primary = fired[0]
    return {
        "signal": primary["signal"],
        "reason": primary["reason"],
        "tag": primary["tag"],
        "fired": fired,
    }


def _signal_key(name: str, tag: str) -> str:
    """Stable dismissal key: ``name::tag``.

    Re-using the same key across reloads means dismissal lifecycle
    follows the SIGNAL REASON, not just the player — if a player's
    signal flips from SELL/sustained_downtrend to RISK/alert_with_drop,
    they re-surface even if the first was dismissed.

    Note: a player rename at the display-name layer would produce a
    different ``name::tag`` key from the old one, so a dismissal
    stored under the old name would silently fail to match.  The
    terminal payload therefore emits an ``aliasSignalKey`` field
    alongside the primary ``signalKey`` — keyed by Sleeper ID
    instead of display name — and the frontend/user_kv alias map
    lets it resolve dismissals across renames.  See
    ``_signal_alias_key`` below.
    """
    return f"{str(name).strip()}::{str(tag).strip()}"


def _signal_alias_key(sleeper_id: str, tag: str) -> str:
    """Rename-resistant dismissal key: ``sid:<id>::tag``.

    Emitted alongside the display-name ``signalKey`` so the user_kv
    alias map can resolve a dismissal when a player's display name
    changes between scrapes.  When ``sleeper_id`` is empty the alias
    collapses to an empty string — the UI treats that as "only the
    display-name key is available" and behaves identically to the
    pre-alias path.
    """
    sid = str(sleeper_id or "").strip()
    if not sid:
        return ""
    return f"sid:{sid}::{str(tag).strip()}"


# ── PORTFOLIO INSIGHTS ──────────────────────────────────────────────────


def _compute_portfolio_insights(
    resolved_team: dict[str, Any],
    roster_rows: list[dict[str, Any]],
    *,
    row_history: Callable[[str], list[dict[str, Any]]],
    rows: list[dict[str, Any]],
    roster_set: set[str],
) -> dict[str, Any]:
    rosterValues: list[dict[str, Any]] = []
    for row in roster_rows:
        pos = _normalize_pos(row.get("pos") or row.get("position"))
        value = int(_row_value(row))
        points = _normalize_points(row_history(_row_name(row)))
        vol = _volatility(points, 30)
        rosterValues.append({
            "name": _row_name(row),
            "pos": pos,
            "value": value,
            "rank": _row_rank(row),
            "rankChange": _row_rank_change(row),
            "age": row.get("age"),
            "isRookie": bool(row.get("rookie")),
            "trend7": _window_trend(points, 7),
            "trend30": _window_trend(points, 30),
            "volatility": vol,
            "volLabel": (vol or {}).get("label") or "unknown",
        })
    totalValue = sum(p["value"] for p in rosterValues) or 0

    # Best asset
    best = max(rosterValues, key=lambda p: p["value"], default=None)
    bestAsset = None
    if best:
        stable_hint = ""
        if best["trend30"] is not None and best["trend30"] >= 0:
            stable_hint = " with a stable 30d trend"
        bestAsset = {
            "player": best,
            "reason": f"Highest-valued asset at {int(best['value']):,}{stable_hint}.",
            "metric": "value",
        }

    # Biggest risk
    risk = None
    tier1 = [p for p in rosterValues if p["volLabel"] == "high" and (p["trend7"] or 0) < 0]
    if tier1:
        t = max(tier1, key=lambda p: p["value"])
        risk = {
            "player": t,
            "reason": f"High volatility (MAD {float((t['volatility'] or {}).get('mad') or 0):.1f}) and 7d trend of {_fmt_delta(t['trend7'])}.",
            "metric": "vol_plus_drop",
        }
    if not risk:
        tier2 = [p for p in rosterValues if p["volLabel"] == "high"]
        if tier2:
            t = max(tier2, key=lambda p: p["value"])
            risk = {
                "player": t,
                "reason": f"High volatility on an asset worth {int(t['value']):,}.",
                "metric": "vol_alone",
            }
    if not risk:
        tier3 = sorted(
            [p for p in rosterValues if (p["trend7"] or 0) <= -3],
            key=lambda p: p["trend7"] or 0,
        )
        if tier3:
            t = tier3[0]
            risk = {
                "player": t,
                "reason": f"Steep 7d decline of {_fmt_delta(t['trend7'])} ranks.",
                "metric": "steep_decline",
            }

    # Trade chip: mid-tier rising
    chips = [p for p in rosterValues
             if 3000 <= p["value"] <= 7500
             and (p["trend7"] or 0) >= 3
             and p["volLabel"] != "high"]
    chip = max(chips, key=lambda p: p["trend7"] or 0) if chips else None
    tradeChip = None
    if chip:
        tradeChip = {
            "player": chip,
            "reason": f"Rising {_fmt_delta(chip['trend7'])} ranks over 7d — sell-into-demand candidate.",
            "metric": "rising_mid_tier",
        }

    # Buy-low (league-wide, excluding roster)
    buyLow = None
    best_cand = None
    best_score = None
    for r in rows:
        name = _row_name(r).lower()
        if name in roster_set:
            continue
        rank = _row_rank(r)
        if not rank or rank > 150:
            continue
        val = _row_value(r)
        if val < 3000:
            continue
        rc = _row_rank_change(r)
        if rc is None or rc > -3:
            continue
        score = -rc
        if best_score is None or score > best_score:
            best_score = score
            best_cand = r
    if best_cand:
        buyLow = {
            "player": {
                "name": _row_name(best_cand),
                "pos": _normalize_pos(best_cand.get("pos") or best_cand.get("position")),
                "value": int(_row_value(best_cand)),
                "rank": _row_rank(best_cand),
            },
            "reason": f"Dropped {abs(int(_row_rank_change(best_cand) or 0))} ranks on the last scrape but still inside the top {_row_rank(best_cand)}.",
            "metric": "short_drop_long_steady",
        }

    # ── Sub-section breakdowns ────────────────────────────────────
    # Match the client-side ``computePortfolio`` output so the
    # PortfolioSummary + ScoutingIntel components can render off
    # server-provided data without re-deriving anything locally.

    def _age_bucket(age: Any, is_rookie: bool) -> str:
        if is_rookie:
            return "rookie"
        try:
            a = float(age) if age is not None else None
        except (TypeError, ValueError):
            a = None
        if a is None or a <= 0:
            return "unknown"
        if a <= 22:
            return "rookie"
        if a <= 24:
            return "young"
        if a <= 28:
            return "prime"
        return "vet"

    position_groups = ("QB", "RB", "WR", "TE", "K", "DEF", "IDP", "PICK")
    by_position: dict[str, dict[str, Any]] = {
        g: {"count": 0, "value": 0, "pct": 0.0} for g in position_groups
    }
    for p in rosterValues:
        bucket = p["pos"] if p["pos"] in position_groups else None
        if bucket:
            by_position[bucket]["count"] += 1
            by_position[bucket]["value"] += p["value"]
    # Picks aren't part of ``rosterValues`` (picks handled separately
    # in the contract), so ``PICK`` stays zero unless the caller pre-
    # injects them — matching the client-side shape.
    if totalValue:
        for g in position_groups:
            by_position[g]["pct"] = round(by_position[g]["value"] / totalValue * 100, 1)

    by_age: dict[str, dict[str, Any]] = {
        "rookie":  {"count": 0, "value": 0, "pct": 0.0},
        "young":   {"count": 0, "value": 0, "pct": 0.0},
        "prime":   {"count": 0, "value": 0, "pct": 0.0},
        "vet":     {"count": 0, "value": 0, "pct": 0.0},
        "unknown": {"count": 0, "value": 0, "pct": 0.0},
    }
    ages: list[float] = []
    for p in rosterValues:
        bucket = _age_bucket(p.get("age"), p.get("isRookie", False))
        by_age[bucket]["count"] += 1
        by_age[bucket]["value"] += p["value"]
        try:
            a = float(p.get("age")) if p.get("age") is not None else None
        except (TypeError, ValueError):
            a = None
        if a is not None and a > 0:
            ages.append(a)
    if totalValue:
        for k in by_age:
            by_age[k]["pct"] = round(by_age[k]["value"] / totalValue * 100, 1)
    ages.sort()
    median_age = None
    if ages:
        mid = len(ages) // 2
        median_age = (
            ages[mid]
            if len(ages) % 2 == 1
            else round((ages[mid - 1] + ages[mid]) / 2.0, 1)
        )

    vol_exposure: dict[str, dict[str, Any]] = {
        "low":     {"count": 0, "value": 0, "pct": 0.0},
        "med":     {"count": 0, "value": 0, "pct": 0.0},
        "high":    {"count": 0, "value": 0, "pct": 0.0},
        "unknown": {"count": 0, "value": 0, "pct": 0.0},
    }
    for p in rosterValues:
        lbl = p.get("volLabel") or "unknown"
        if lbl not in vol_exposure:
            lbl = "unknown"
        vol_exposure[lbl]["count"] += 1
        vol_exposure[lbl]["value"] += p["value"]
    if totalValue:
        for k in vol_exposure:
            vol_exposure[k]["pct"] = round(vol_exposure[k]["value"] / totalValue * 100, 1)

    # Rising / falling / high-vol counters — for the roster-chip row.
    rising = sum(1 for p in rosterValues if (p["trend7"] or 0) >= 3)
    falling = sum(1 for p in rosterValues if (p["trend7"] or 0) <= -3)
    high_vol = vol_exposure["high"]["count"]

    return {
        "totalValue": totalValue,
        "rosterValues": rosterValues,
        "bestAsset": bestAsset,
        "biggestRisk": risk,
        "tradeChip": tradeChip,
        "buyLow": buyLow,
        # Sub-section breakdowns now computed server-side so
        # PortfolioSummary / ScoutingIntel can render without
        # recomputing locally.
        "byPosition": by_position,
        "byAge": by_age,
        "volExposure": vol_exposure,
        "medianAge": median_age,
        "counters": {
            "rising": rising,
            "falling": falling,
            "highVol": high_vol,
        },
    }


# ── NEWS GATHERING ──────────────────────────────────────────────────────


def gather_news_items(
    news_service_factory: Callable[[], Any],
    live_names: list[str] | None,
    team_name: str | None,
) -> list[dict[str, Any]]:
    """Pull raw news items through the existing NewsService aggregator.

    Failure is non-fatal — the terminal payload still renders without
    news.  Service lookup is lazy so tests can pass a factory that
    returns a stub.
    """
    try:
        svc = news_service_factory()
        aggregated = svc.aggregate(
            player_names=live_names or [],
            team_names=[team_name] if team_name else None,
        )
    except Exception:
        return []
    items = aggregated.to_dict().get("items") or []
    return items if isinstance(items, list) else []


# ── MAIN BUILDER ────────────────────────────────────────────────────────


def build_terminal_payload(
    contract: dict[str, Any],
    *,
    resolved_team: dict[str, Any] | None,
    window_days: int = 30,
    news_items: list[dict[str, Any]] | None = None,
    user_state: dict[str, Any] | None = None,
    history_window_days: int | None = None,
    public_mode: bool = False,
) -> dict[str, Any]:
    """Assemble the full landing-page payload.

    The payload is a single object with the top-level keys:

    * ``generatedAt``       — ISO 8601 UTC stamp
    * ``contract``          — {version, source, generatedAt} pass-through
    * ``team``              — {ownerId, name} resolved selection (or null)
    * ``availableTeams``    — [{ownerId, name, playerCount}] for picker
    * ``windowDays``        — the clamped window echoed back
    * ``teamAggregates``    — {totalValue, delta7d, delta30d, delta90d,
                               delta180d, tiers, starterCount, benchCount}
    * ``movers``            — {roster, league, top150} scoped mover lists
    * ``trendWindows``      — [7, 30, 90, 180] supported windows
    * ``signals``           — [{name, pos, signal, reason, tag, fired,
                                 dismissedUntil, signalKey, ...}] sorted
    * ``portfolio``         — full portfolio insights block
    * ``news``              — {items, source} filtered/tagged
    * ``watchlist``         — [{name, ...}] using user_kv watchlist
    * ``meta``              — {rosterCoverage, unresolved, ...}
    """
    window_days = max(7, min(180, int(window_days or 30)))
    history_window_days = max(window_days, int(history_window_days or 180))

    rows = _players_array(contract)
    row_index = _build_row_index(rows)

    # Rank history for the requested window.  A 180-day pull is cheap
    # (it's just JSONL on disk, a few hundred KB) and lets the same
    # payload service the 7d / 30d / 90d / 180d trend windows without
    # a second read.
    history = _rank_history.load_history(days=history_window_days)
    history_for = _history_lookup(history)

    sleeper = contract.get("sleeper") or {}
    teams = sleeper.get("teams") or []
    availableTeams = []
    for t in teams if isinstance(teams, list) else []:
        if not isinstance(t, dict):
            continue
        availableTeams.append({
            "ownerId": str(t.get("ownerId") or ""),
            "name": str(t.get("name") or ""),
            "playerCount": len(t.get("players") or []) if isinstance(t.get("players"), list) else 0,
        })

    team_block = None
    roster_set: set[str] = set()
    league_set: set[str] = set()
    for t in teams if isinstance(teams, list) else []:
        if not isinstance(t, dict):
            continue
        for p in t.get("players") or []:
            league_set.add(str(p).lower())

    # Prepare news scoped for this view.
    news_items = news_items if isinstance(news_items, list) else []
    news_by_player: dict[str, list[dict[str, Any]]] = {}
    for it in news_items:
        for p in it.get("players") or []:
            key = str((p or {}).get("name") or "").lower()
            if not key:
                continue
            news_by_player.setdefault(key, []).append(it)

    # Defaults we populate further below.
    teamAggregates = {
        "totalValue": None,
        "delta7d": None,
        "delta30d": None,
        "delta90d": None,
        "delta180d": None,
        "rosterAware": True,
        "tiers": None,
        "rosterCount": 0,
        "coverage": None,
    }
    portfolio_block: dict[str, Any] | None = None
    signals_list: list[dict[str, Any]] = []
    watchlist_block: list[dict[str, Any]] = []
    roster_rows: list[dict[str, Any]] = []

    # Dismissals applied to signals.
    active_dismissals: dict[str, int] = {}
    if isinstance(user_state, dict):
        ds = user_state.get("dismissedSignals")
        if isinstance(ds, dict):
            for k, v in ds.items():
                try:
                    active_dismissals[str(k)] = int(v)
                except (TypeError, ValueError):
                    continue

    if resolved_team and isinstance(resolved_team, dict):
        owner_id = str(resolved_team.get("ownerId") or "").strip()
        team_block = {
            "ownerId": owner_id,
            "name": str(resolved_team.get("name") or ""),
            "rosterId": resolved_team.get("roster_id"),
        }
        current_players = [str(p) for p in (resolved_team.get("players") or [])]
        roster_set = {p.lower() for p in current_players}
        roster_rows = [row_index[n.lower()] for n in current_players if n.lower() in row_index]

        # Current totalValue / tiers.
        tiers = {"elite": 0, "high": 0, "mid": 0, "depth": 0}
        total = 0
        resolved = 0
        for r in roster_rows:
            v = int(_row_value(r))
            if v <= 0:
                continue
            total += v
            tiers[_tier_bucket(v)] += 1
            resolved += 1
        coverage = resolved / max(1, len(current_players))
        teamAggregates["totalValue"] = total if resolved else None
        teamAggregates["tiers"] = tiers if resolved else None
        teamAggregates["rosterCount"] = len(current_players)
        teamAggregates["coverage"] = round(coverage, 3)

        # Roster-aware deltas for 7 / 30 / 90 / 180.
        #
        # Each delta carries both the numeric value and a coverage
        # block so the UI can distinguish:
        #   * value=int, rosterAware=True    — clean window, backed
        #     by trades
        #   * value=int, rosterAware=False   — clean window but no
        #     trades fell inside it (static-roster delta)
        #   * value=None, reason="low_history_coverage" — the past
        #     snapshot had fewer than 60% of the roster with
        #     matching rank history; UI renders "—"
        #
        # ``delta*d`` is ``int | None`` for backwards compat with
        # the pre-coverage consumers; the full block is exposed on
        # ``delta*dDetail``.
        latest_date = _latest_snapshot_date(history)
        teamAggregates["rosterAware"] = False
        if latest_date and total > 0:
            any_roster_aware = False

            def _delta(days: int) -> dict[str, Any]:
                past_date = _back_iso_date(latest_date, days)
                past_ms = _iso_date_to_ms(past_date)
                past_roster, roster_coverage = _reconstruct_roster_at(
                    contract,
                    owner_id=owner_id,
                    current_players=current_players,
                    cutoff_ms=past_ms,
                )
                past_total = _sum_roster_value_at_date(
                    past_roster,
                    history_by_name=history_for,
                    date=past_date,
                    row_index=row_index,
                )
                value = past_total["value"]
                return {
                    "value": (total - value) if value is not None else None,
                    "coverageFraction": past_total["coverageFraction"],
                    "resolved": past_total["resolved"],
                    "expected": past_total["expected"],
                    "reliable": past_total["reliable"],
                    "rosterAware": roster_coverage["rosterAware"],
                    "tradesSeen": roster_coverage["tradesSeen"],
                    "tradesApplied": roster_coverage["tradesApplied"],
                    "reason": roster_coverage["reason"] if value is not None
                              else "low_history_coverage",
                    "pastDate": past_date,
                }

            for days in (7, 30, 90, 180):
                detail = _delta(days)
                teamAggregates[f"delta{days}d"] = detail["value"]
                teamAggregates[f"delta{days}dDetail"] = detail
                if detail["rosterAware"]:
                    any_roster_aware = True
            teamAggregates["rosterAware"] = any_roster_aware

        # Signals for each roster player.
        for r in roster_rows:
            points = _normalize_points(history_for(_row_name(r)))
            player_news = news_by_player.get(_row_name(r).lower(), [])
            ctx = _build_signal_context(r, points=points, news_for_player=player_news)
            verdict = _evaluate_signal(ctx)
            tag = verdict.get("tag") or "unknown"
            skey = _signal_key(ctx["name"], tag)
            alias_key = _signal_alias_key(ctx.get("sleeperId", ""), tag)
            # Resolve dismissal via either the display-name key or
            # the Sleeper-ID alias key — whichever matches wins.  A
            # legacy dismissal stored under the old display-name key
            # keeps applying even after a rename, because the alias
            # key still matches by sleeperId.
            dismissed_until = active_dismissals.get(skey)
            if dismissed_until is None and alias_key:
                dismissed_until = active_dismissals.get(alias_key)
            entry = {
                **ctx,
                "signal": verdict["signal"],
                "reason": verdict["reason"],
                "tag": verdict["tag"],
                "fired": verdict["fired"],
                "signalKey": skey,
                "aliasSignalKey": alias_key,
                "dismissedUntil": dismissed_until,
                "dismissed": bool(dismissed_until),
            }
            signals_list.append(entry)
        # Sort like the frontend: RISK/SELL/MONITOR first, HOLD last,
        # value desc within bucket, then dismissed items to the tail.
        priority = {"RISK": 0, "SELL": 1, "MONITOR": 2, "STRONG_HOLD": 3, "BUY": 4, "HOLD": 5}
        signals_list.sort(key=lambda s: (
            1 if s["dismissed"] else 0,
            priority.get(s["signal"], 99),
            -(s.get("value") or 0),
        ))

        # Portfolio insights (always computed for the signed-in team).
        portfolio_block = _compute_portfolio_insights(
            resolved_team,
            roster_rows,
            row_history=history_for,
            rows=rows,
            roster_set=roster_set,
        )

    # Watchlist is user-wide, not team-specific.
    watch_names: list[str] = []
    if isinstance(user_state, dict):
        wl = user_state.get("watchlist")
        if isinstance(wl, list):
            for n in wl:
                if isinstance(n, str) and n.strip():
                    watch_names.append(n.strip())
    for name in watch_names:
        row = row_index.get(name.lower())
        if not row:
            continue
        points = _normalize_points(history_for(name))
        watchlist_block.append({
            "name": _row_name(row),
            "pos": _normalize_pos(row.get("pos") or row.get("position")),
            "value": int(_row_value(row)),
            "rank": _row_rank(row),
            "rankChange": _row_rank_change(row),
            "trend7": _window_trend(points, 7),
            "trend30": _window_trend(points, 30),
            "trend90": _window_trend(points, 90),
            "trend180": _window_trend(points, 180),
            "volatility": _volatility(points, 30),
            "onRoster": _row_name(row).lower() in roster_set,
        })

    # Movers: always include all three scopes.  ``roster`` is empty if
    # the user hasn't picked a team yet.
    movers = {
        "roster": _compute_movers(rows, scope="roster", roster_set=roster_set,
                                  league_set=league_set, limit=20),
        "league": _compute_movers(rows, scope="league", roster_set=roster_set,
                                  league_set=league_set, limit=30),
        "top150": _compute_movers(rows, scope="top150", roster_set=roster_set,
                                  league_set=league_set, limit=30),
    }

    # News is pre-scored for the picked team.
    news_block = {
        "items": _score_news(news_items, roster_set=roster_set, league_set=league_set),
        "count": len(news_items),
    }

    payload = {
        "generatedAt": _utc_now_iso(),
        "contract": {
            "version": contract.get("contractVersion") or contract.get("version"),
            "date": contract.get("date"),
            "generatedAt": contract.get("generatedAt"),
            "playerCount": contract.get("playerCount"),
        },
        "team": team_block,
        "availableTeams": availableTeams,
        "windowDays": window_days,
        "trendWindows": [7, 30, 90, 180],
        "teamAggregates": teamAggregates,
        "movers": movers,
        "signals": signals_list,
        "portfolio": portfolio_block,
        "news": news_block,
        "watchlist": watchlist_block,
        "meta": {
            "historyWindowDays": history_window_days,
            "historyPlayerCount": len(history) if isinstance(history, dict) else 0,
            "publicMode": bool(public_mode),
        },
    }
    if public_mode:
        # Strip everything that requires an authenticated identity:
        #   * no team — public visitors don't have a selection
        #   * no signals / portfolio / watchlist — those are all
        #     private per-roster
        #   * no roster movers — the league ownership is private too
        #   * keep: league + top150 movers, news (scoped by public
        #     relevance), availableTeams (identity-free metadata),
        #     trendWindows, contract meta
        # The frontend treats this as "public terminal" and falls
        # back to a condensed layout without the roster rails.
        payload["team"] = None
        payload["signals"] = []
        payload["portfolio"] = None
        payload["watchlist"] = []
        payload["teamAggregates"] = {
            "totalValue": None,
            "delta7d": None, "delta30d": None, "delta90d": None, "delta180d": None,
            "rosterAware": False,
            "tiers": None,
            "rosterCount": 0,
            "coverage": None,
        }
        payload["movers"]["roster"] = []
        # News coverage in public mode is "top-150 only" — roster
        # scoping needed an authenticated roster set.
        payload["news"]["items"] = [
            n for n in payload["news"]["items"] if (n.get("relevance") or 0) < 100
        ]
    return payload


def _latest_snapshot_date(history: dict[str, Any]) -> str | None:
    if not isinstance(history, dict) or not history:
        return None
    latest = None
    for series in history.values():
        if not isinstance(series, list):
            continue
        for p in series:
            d = p.get("date") if isinstance(p, dict) else None
            if isinstance(d, str) and (latest is None or d > latest):
                latest = d
    return latest


def _back_iso_date(latest_date: str, days: int) -> str:
    try:
        dt = datetime.strptime(latest_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return latest_date
    from datetime import timedelta
    return (dt - timedelta(days=int(days))).strftime("%Y-%m-%d")


def _iso_date_to_ms(date: str) -> int:
    try:
        dt = datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return 0
    return int(dt.timestamp() * 1000)


def _score_news(
    items: list[dict[str, Any]],
    *,
    roster_set: set[str],
    league_set: set[str],
) -> list[dict[str, Any]]:
    scored = []
    for it in items[:30]:
        relevance = 10  # general
        matched_scope = "general"
        players = it.get("players") or []
        for p in players:
            n = str((p or {}).get("name") or "").lower()
            if not n:
                continue
            if n in roster_set and relevance < 100:
                relevance = 100
                matched_scope = "roster"
            elif n in league_set and relevance < 50:
                relevance = 50
                matched_scope = "league"
        scored.append({
            "id": it.get("id"),
            "ts": it.get("ts"),
            "provider": it.get("provider"),
            "providerLabel": it.get("providerLabel"),
            "severity": it.get("severity"),
            "kind": it.get("kind"),
            "headline": it.get("headline"),
            "body": it.get("body"),
            "players": players,
            "url": it.get("url"),
            "relevance": relevance,
            "scope": matched_scope,
        })
    scored.sort(key=lambda n: (-(n.get("relevance") or 0), -_ts_ms(n.get("ts"))))
    return scored


def _ts_ms(iso: Any) -> int:
    if not isinstance(iso, str):
        return 0
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return int(dt.timestamp() * 1000)
    except ValueError:
        return 0
