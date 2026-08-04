"""Read-time aggregation over crawled intel events.

Events are the raw add/drop rows the crawler extracted from Sleeper
transactions (see ``crawler.py`` for the shape).  Nothing here is
persisted — summaries are computed at read time so window edges are
always relative to "now" and a snapshot never goes stale between
crawls.

Semantics:
    * A trade produces PAIRED add+drop events per side (each roster's
      incoming assets are adds, outgoing are drops).
    * Waiver / free-agent moves produce single-sided events.
    * ``buys`` counts adds, ``sells`` counts drops, ``net = buys −
      sells`` per rolling window.
    * ``leagueCount`` is the number of DISTINCT leagues where the
      asset is currently held by a pool member or was traded by one.
    * ``signalStrength`` / ``confidence`` / ``velocity`` are the
      ranking numbers, all computed by ``signals.py`` — see below.

──────────────────────────────────────────────────────────────────────
Why there is no ``trendScore`` here any more
──────────────────────────────────────────────────────────────────────
This module used to publish ``trendScore = 3·net48h + 2·net7d +
1·net30d`` and ``service.py`` sorted the board by it.  The windows
below are NESTED, so a movement an hour old is inside all three terms
and contributed 3+2+1 = 6 to a number the UI presented as a signal
strength.  One event, six counted — it ranked one fresh buy above five
sustained ones.  See the deprecation notice at the top of
``signals.py`` and ``docs/intel/METRICS.md``.

The replacements never add two windows together:

    * ``signalStrength`` — ``signals.signal_strength`` over the
      PRIMARY window alone, so each movement enters the ranking
      exactly once.  Direction is normalized (``net / volume``) and
      re-weighted by sample-size confidence and manager breadth, which
      is what stops 1 buy / 0 sells from reading like 40 buys / 10.
    * ``velocity`` — a RATIO of the short window's rate to the primary
      window's rate.  Arithmetically incapable of double-counting: the
      shared movements sit in both numerator and denominator and
      cancel.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from src.intel import signals

# Window durations come from ONE registry — ``signals.WINDOWS_MS`` —
# so a span can never drift between the two modules.  This module
# reports a SUBSET of that registry on purpose: summaries are computed
# from the snapshot's event log, which ``store.save_state`` prunes at
# ``EVENT_RETENTION_DAYS`` (45), so a 90d window read off a snapshot
# would answer with 45 days of data under a 90-day label.  Naming the
# subset explicitly means a window renamed in the registry fails at
# import here rather than silently diverging.
SUMMARY_WINDOWS: tuple[str, ...] = ("48h", "7d", "14d", "30d")
WINDOWS_MS: dict[str, int] = {name: signals.WINDOWS_MS[name] for name in SUMMARY_WINDOWS}

# The single window every headline number is computed over — the
# board's primary lens, shared with the ledger-backed surfaces.
PRIMARY_WINDOW = signals.INSIDER_DEFAULT_WINDOW
# Numerator of the velocity ratio; the primary window is the baseline.
VELOCITY_SHORT_WINDOW = "48h"

# Fail at import, not at read time: the shared registry could gain a
# window this module deliberately does not compute (90d today), and if
# the primary lens ever pointed at one, every summary would KeyError on
# a live request instead of here.
if PRIMARY_WINDOW not in WINDOWS_MS or VELOCITY_SHORT_WINDOW not in WINDOWS_MS:
    raise RuntimeError(
        f"intel.aggregate reports {SUMMARY_WINDOWS}, which must contain both the "
        f"primary window ({PRIMARY_WINDOW!r}) and the velocity numerator "
        f"({VELOCITY_SHORT_WINDOW!r})"
    )


def _now_ms(now: datetime | int | float | None) -> int:
    if now is None:
        return int(datetime.now(timezone.utc).timestamp() * 1000)
    if isinstance(now, datetime):
        return int(now.timestamp() * 1000)
    return int(now)


def _empty_windows() -> dict[str, dict[str, int]]:
    return {key: {"buys": 0, "sells": 0, "net": 0} for key in WINDOWS_MS}


def _valid_events(events: list[dict[str, Any]] | None, now: int) -> list[dict[str, Any]]:
    out = []
    for e in events or []:
        if not isinstance(e, dict):
            continue
        ts = e.get("ts")
        if not isinstance(ts, (int, float)) or ts <= 0 or ts > now:
            continue
        if e.get("action") not in ("add", "drop"):
            continue
        if not e.get("assetId"):
            continue
        out.append(e)
    return out


def holdings_from_state(state: dict[str, Any]) -> dict[str, dict[str, list[str]]]:
    """Extract ``{leagueId: {ownerId: [assetId, ...]}}`` from a crawl
    state's leagues block."""
    out: dict[str, dict[str, list[str]]] = {}
    for lid, league in (state.get("leagues") or {}).items():
        if not isinstance(league, dict):
            continue
        holdings = league.get("holdings")
        if isinstance(holdings, dict) and holdings:
            out[str(lid)] = {
                str(oid): [str(a) for a in assets or []]
                for oid, assets in holdings.items()
                if isinstance(assets, list)
            }
    return out


def build_asset_summary(
    events: list[dict[str, Any]] | None,
    now: datetime | int | float | None,
    holdings: dict[str, dict[str, list[str]]] | None = None,
) -> dict[str, dict[str, Any]]:
    """Per-asset buy/sell/net counts over the rolling windows.

    Returns ``{assetId: summary}`` where summary is::

        {
            "assetId": str,
            "assetType": "player" | "pick",
            "windows": {"48h": {"buys", "sells", "net"}, "7d": ..., ...},
            "leagueCount": int,     # distinct leagues held OR traded
            "heldLeagueCount": int, # distinct leagues currently held
            "signalStrength": float,  # ranking metric, PRIMARY window only
            "confidence": str,        # high|medium|low|insufficient
            "velocity": float | None, # 48h rate ÷ primary-window rate
            "lastEventTs": int | None,
        }

    Window membership is inclusive at the edge: an event exactly
    ``window`` old still counts (``ts >= now − window``).

    The windows are overlapping VIEWS of the same movements, never
    additive buckets — nothing here (and nothing downstream) may sum
    them.  ``signalStrength`` is therefore computed from a single
    window; see the module docstring.
    """
    now_ms = _now_ms(now)
    summaries: dict[str, dict[str, Any]] = {}

    def _entry(asset_id: str, asset_type: str | None) -> dict[str, Any]:
        entry = summaries.get(asset_id)
        if entry is None:
            entry = {
                "assetId": asset_id,
                "assetType": asset_type or ("pick" if asset_id.startswith("pick:") else "player"),
                "windows": _empty_windows(),
                "_tradedLeagues": set(),
                "_heldLeagues": set(),
                # Per-window manager sets: breadth is "how many people",
                # not "how many movements", so they cannot be derived
                # from the counts afterwards.
                "_managers": {key: set() for key in WINDOWS_MS},
                "signalStrength": 0.0,
                "confidence": "insufficient",
                "velocity": None,
                "lastEventTs": None,
            }
            summaries[asset_id] = entry
        return entry

    for event in _valid_events(events, now_ms):
        asset_id = str(event["assetId"])
        entry = _entry(asset_id, event.get("assetType"))
        ts = int(event["ts"])
        age = now_ms - ts
        bucket = "buys" if event["action"] == "add" else "sells"
        owner = str(event.get("ownerId") or "")
        for key, window in WINDOWS_MS.items():
            if age <= window:
                entry["windows"][key][bucket] += 1
                if owner:
                    entry["_managers"][key].add(owner)
        lid = str(event.get("leagueId") or "")
        if lid and age <= WINDOWS_MS[PRIMARY_WINDOW]:
            entry["_tradedLeagues"].add(lid)
        if entry["lastEventTs"] is None or ts > entry["lastEventTs"]:
            entry["lastEventTs"] = ts

    for lid, by_owner in (holdings or {}).items():
        for _owner, assets in (by_owner or {}).items():
            for asset_id in assets or []:
                entry = _entry(str(asset_id), None)
                entry["_heldLeagues"].add(str(lid))

    for entry in summaries.values():
        for win in entry["windows"].values():
            win["net"] = win["buys"] - win["sells"]
        traded_leagues = entry.pop("_tradedLeagues")
        managers = entry.pop("_managers")
        entry["leagueCount"] = len(traded_leagues | entry["_heldLeagues"])
        entry["heldLeagueCount"] = len(entry.pop("_heldLeagues"))

        # Everything below reads ONE window.  Adding a second one back
        # in is the defect this module was fixed for.
        primary = entry["windows"][PRIMARY_WINDOW]
        primary_volume = primary["buys"] + primary["sells"]
        # An unattributable movement is still one actor: counting zero
        # managers would zero ``breadth_factor`` and silently erase the
        # row from the board.  The crawler never emits an event without
        # an ownerId, so this only guards legacy/hand-built payloads.
        primary_managers = len(managers[PRIMARY_WINDOW]) or (1 if primary_volume else 0)
        entry["signalStrength"] = signals.signal_strength(
            net=primary["net"],
            volume=primary_volume,
            unique_managers=primary_managers,
            # Insider Trading's cohort is "everyone in your league" —
            # no skill weighting is applied or implied (that is Sharp
            # Tracker's job), so quality stays at the neutral 1.0.
            manager_quality=1.0,
        )
        entry["confidence"] = signals.confidence_tier(
            primary_volume,
            primary_managers,
            # Leagues the asset MOVED in, not leagues it sits rostered
            # in — a widely-rostered player is not a widely-traded one.
            len(traded_leagues),
        )
        short = entry["windows"][VELOCITY_SHORT_WINDOW]
        entry["velocity"] = signals.velocity(
            {
                "volume": short["buys"] + short["sells"],
                "_spanMs": WINDOWS_MS[VELOCITY_SHORT_WINDOW],
            },
            {"volume": primary_volume, "_spanMs": WINDOWS_MS[PRIMARY_WINDOW]},
        )
    return summaries


def build_member_exposure(
    events: list[dict[str, Any]] | None,
    holdings: dict[str, dict[str, list[str]]] | None,
    asset_id: str,
    now: datetime | int | float | None,
) -> list[dict[str, Any]]:
    """Which pool members hold / recently traded ``asset_id``, and in
    how many of their leagues.  Sorted by held-league count desc."""
    now_ms = _now_ms(now)
    asset_id = str(asset_id)
    per_member: dict[str, dict[str, Any]] = {}

    def _member(oid: str) -> dict[str, Any]:
        entry = per_member.get(oid)
        if entry is None:
            entry = {
                "ownerId": oid,
                "heldLeagueCount": 0,
                "buys30d": 0,
                "sells30d": 0,
                "net30d": 0,
                "lastEventTs": None,
                "_held": set(),
            }
            per_member[oid] = entry
        return entry

    for lid, by_owner in (holdings or {}).items():
        for oid, assets in (by_owner or {}).items():
            if asset_id in (assets or []):
                _member(str(oid))["_held"].add(str(lid))

    for event in _valid_events(events, now_ms):
        if str(event["assetId"]) != asset_id:
            continue
        ts = int(event["ts"])
        if now_ms - ts > WINDOWS_MS["30d"]:
            continue
        oid = str(event.get("ownerId") or "")
        if not oid:
            continue
        entry = _member(oid)
        if event["action"] == "add":
            entry["buys30d"] += 1
        else:
            entry["sells30d"] += 1
        if entry["lastEventTs"] is None or ts > entry["lastEventTs"]:
            entry["lastEventTs"] = ts

    out = []
    for entry in per_member.values():
        entry["heldLeagueCount"] = len(entry.pop("_held"))
        entry["net30d"] = entry["buys30d"] - entry["sells30d"]
        out.append(entry)
    out.sort(key=lambda m: (-m["heldLeagueCount"], -(m["buys30d"] + m["sells30d"])))
    return out


def build_member_activity(
    events: list[dict[str, Any]] | None,
    owner_id: str,
    now: datetime | int | float | None,
) -> dict[str, Any]:
    """One member's per-asset activity (their personal buy/sell log
    across every league of theirs we track)."""
    now_ms = _now_ms(now)
    owner_id = str(owner_id)
    member_events = [
        e for e in _valid_events(events, now_ms) if str(e.get("ownerId") or "") == owner_id
    ]
    assets = build_asset_summary(member_events, now_ms)
    # Same non-overlapping metric as the board, ordered by MAGNITUDE:
    # a member's most decisive moves lead, sells as well as buys.  The
    # breadth term is a constant 0.25 here (one member is one manager
    # by construction), so this ranks on conviction × volume.
    ranked = sorted(
        assets.values(),
        key=lambda a: (-abs(a["signalStrength"]), -(a["lastEventTs"] or 0)),
    )
    return {
        "ownerId": owner_id,
        "eventCount30d": sum(
            1 for e in member_events if now_ms - int(e["ts"]) <= WINDOWS_MS[PRIMARY_WINDOW]
        ),
        "assets": ranked,
    }
