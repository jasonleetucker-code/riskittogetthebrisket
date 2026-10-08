"""Recent real trades touching the calculator's assets — C3-CALC-01 / TC-07 + TC-10.

A DISPLAY projection of the canonical underlying-trade ledger
(``market_trade_report.read_canonical_ledger`` — the one reader of the file the
daily ``dynasty-market-trade-ledger`` build writes).  It answers one question:
"which recorded real dynasty trades moved one of the assets on my calculator,
and what format were they made in?"  It shows FACTS — the assets on each side,
the date, the source, the format tags and the ledger's own format disposition —
and nothing else.

WHAT IT DELIBERATELY DOES NOT DO
────────────────────────────────
* **No valuation, no grade, no market price.**  Nothing here reads a canonical
  value or computes one from a trade (spec §2 rule 6: "one transaction never
  becomes canonical valuation truth"; comps/market-price methodology is TC-09 /
  C4-MTL-03, not authorized here).  Pinned by
  ``tests/trade/test_market_trade_reference.py``.
* **No identity matching of its own.**  The ledger's assets were resolved by the
  canonical owners at build time (``market_trade_normalize`` →
  ``src.identity.resolution`` / ``src.identity.picks``).  The calculator's side
  arrives as Sleeper player ids, board pick-row names and owned league-pick ids,
  parsed here ONLY through ``src.identity.picks`` grammar.  A player is matched
  by canonical id equality, never by name; an unresolved ledger asset can never
  match anything.
* **No format inference.**  Every tag is read from the ledger's own
  ``marketFormat`` / full format record; ``None`` stays ``None`` (TC-10:
  "unknown format fields remain unknown").  Never the target league's format.

PICK MATCHING — two named grades
────────────────────────────────
``exact``  — the same canonical market reference (same slot, same tier, or
             both generic), or the very same owned league pick.
``round``  — same year + round where at least one side does not state a tier
             or slot (a Sleeper traded-pick record is generic by construction;
             KTC's "Mid" is filed generic — see ``market_trade_normalize``).
             Two DIFFERENT refinements (Early vs Late, a slot vs a tier) never
             match: that would be inventing an equivalence.

PRIVACY — which rows may be shown
─────────────────────────────────
* ``ktc_trade_database`` — KTC's own public trade database, ingested under the
  owner-recorded KTC permission (spec §19.2): shown.
* ``own_league_sleeper`` — shown ONLY for the requested league.  A trade any of
  whose own-league observations belongs to another registry league is withheld
  (fail closed: membership is read from the observation ids, not only the
  representative's ``leagueKey``).
* ``sleeper_sharp_discovery`` — shown, anonymized.  This follows the Sharp
  tracker's existing posture: per-transaction Sharp movements are already
  served to signed-in users by ``/api/sharp/market/audit``; this route is behind
  the same private API gate.  Like the committed census (aggregate only) it
  carries no league id, transaction id, manager id or underlying-trade id —
  the row key is a one-way hash.
* Any other / unknown source family: withheld.

Missing is never zero: no ledger on the host is ``None`` from the reader and an
``unavailable`` answer here, never an empty list presented as "no trades".
"""

from __future__ import annotations

import hashlib
import threading
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from src.identity.picks import (
    MarketPickRef,
    parse_board_pick_name,
    parse_league_pick_id,
    parse_market_pick_id,
)
from src.trade import market_trade_format as mtf
from src.trade import market_trade_report as report

SOURCE_KTC = "ktc_trade_database"
SOURCE_SHARP = "sleeper_sharp_discovery"
SOURCE_OWN = "own_league_sleeper"
_VISIBLE_FAMILIES = frozenset({SOURCE_KTC, SOURCE_SHARP, SOURCE_OWN})

#: How far back "recent" reaches.  A display/memory bound, not methodology:
#: trades are only listed, never weighted, and the window is stamped on every
#: response so the reader can see it.
RECENT_LOOKBACK_DAYS = 365
DEFAULT_LIMIT = 20
MAX_LIMIT = 50
#: Guard against an unbounded query string.
MAX_QUERY_ASSETS = 40

MATCH_EXACT = "exact"
MATCH_ROUND = "round"

#: ``formatTiming`` — a coarse reading of the ledger owner's own
#: ``format_timing_cap`` + ``formatEvidence``; the raw evidence travels too.
TIMING_EXACT = "exact"
TIMING_POST_TRADE = "post_trade"
TIMING_UNCONFIRMED = "unconfirmed"
TIMING_CHANGED = "changed_after_trade"
TIMING_UNKNOWN = "unknown"

_EVIDENCE_KEYS = (
    "timing",
    "exactAtTradeTime",
    "confirmationAfterTrade",
    "capturedAt",
    "confirmedAt",
    "basis",
    "reason",
    "seasonCompleteAtCapture",
)


# ── Cache over the persisted ledger ───────────────────────────────────────

_cache_lock = threading.Lock()
_cache: dict[str, Any] = {"key": None, "value": None}


def _reset_cache_for_tests() -> None:
    with _cache_lock:
        _cache["key"] = None
        _cache["value"] = None


def _load(root: Path | None, since: str) -> tuple[dict[str, Any], list[dict[str, Any]]] | None:
    """The ledger rows since ``since``, compacted and indexed; cached on the
    file's identity so the daily atomic rebuild invalidates it."""
    path = report.ledger_file_path(root)
    try:
        st = path.stat()
    except OSError:
        return None
    key = (str(path), st.st_mtime_ns, st.st_size, since)
    with _cache_lock:
        if _cache["key"] == key:
            return _cache["value"]
        read = report.read_canonical_ledger(root=root, since_date=since)
        if read is None:
            value = None
        else:
            meta, rows = read
            value = (meta, [_compact(rec, full) for rec, full in rows])
        _cache["key"] = key
        _cache["value"] = value
        return value


def _compact(rec: Mapping[str, Any], full_format: Mapping[str, Any] | None) -> dict[str, Any]:
    """Keep only what the projection reads; drops observation ids, host ids,
    relations and vendor grading flags so they cannot leak by accident."""
    scoring = (full_format or {}).get("scoring") if isinstance(full_format, Mapping) else None
    members = [str(m) for m in (rec.get("members") or [])]
    own_keys = sorted(
        {
            m.split(":", 2)[1]
            for m in members
            if m.startswith(f"{SOURCE_OWN}:") and m.count(":") >= 2
        }
    )
    rep = str(rec.get("representativeObservationId") or "")
    return {
        "opaqueId": hashlib.sha256(str(rec.get("underlyingTradeId")).encode("utf-8")).hexdigest()[
            :16
        ],
        "sourceFamilies": sorted(str(f) for f in (rec.get("sourceFamilies") or [])),
        "provenance": list(rec.get("provenance") or []),
        "ownLeagueKeys": own_keys,
        "leagueKey": rec.get("leagueKey"),
        "representativeFamily": rep.split(":", 1)[0] if rep else None,
        "dedupeState": rec.get("dedupeState"),
        "observationCount": rec.get("observationCount"),
        "possibleOverlap": bool(rec.get("possibleOverlapWith")),
        "occurredDate": rec.get("occurredDate"),
        "occurredAtMs": rec.get("occurredAtMs"),
        "teamCount": rec.get("teamCount"),
        "sides": rec.get("sides") or [],
        "marketFormat": rec.get("marketFormat"),
        "scoring": dict(scoring) if isinstance(scoring, Mapping) else None,
        "formatSource": rec.get("formatSource"),
        "formatEvidence": rec.get("formatEvidence"),
        "targetLeague": rec.get("targetLeague"),
        "disposition": rec.get("disposition"),
        "targetPriceAuthority": rec.get("targetPriceAuthority"),
        "broadContextKind": rec.get("broadContextKind"),
        "strongestUnsupportedAxis": rec.get("strongestUnsupportedAxis"),
        "dispositionReasons": rec.get("dispositionReasons"),
        "caveats": [str(c) for c in (rec.get("caveats") or [])],
    }


# ── Query: the calculator's assets, through the identity owners ──────────


class _Query:
    def __init__(self) -> None:
        self.players: set[str] = set()
        #: generic key -> set of exact market canonical ids asked for
        self.pick_exact: dict[str, set[str]] = {}
        #: generic keys at which the query itself is unrefined (generic row or
        #: an owned pick whose slot we do not resolve here)
        self.pick_unrefined: set[str] = set()
        self.owned_ids: set[str] = set()
        self.unresolved: list[dict[str, Any]] = []
        self.accepted: dict[str, list[str]] = {"players": [], "picks": [], "pickAssetIds": []}

    def keys(self) -> set[str]:
        return self.players | set(self.pick_exact) | self.pick_unrefined

    def empty(self) -> bool:
        return not self.keys()


def _generic_id(ref: MarketPickRef) -> str:
    return MarketPickRef(year=ref.year, round_num=ref.round_num).canonical_id


def build_query(
    league_key: str,
    *,
    player_ids: Iterable[str] = (),
    pick_names: Iterable[str] = (),
    pick_asset_ids: Iterable[str] = (),
) -> _Query:
    q = _Query()
    for raw in list(player_ids)[:MAX_QUERY_ASSETS]:
        sid = str(raw or "").strip()
        if not sid:
            continue
        if not sid.isalnum():
            q.unresolved.append({"ref": sid, "reason": "invalid_player_id"})
            continue
        q.players.add(f"player:{sid}")
        q.accepted["players"].append(sid)
    for raw in list(pick_names)[:MAX_QUERY_ASSETS]:
        name = str(raw or "").strip()
        if not name:
            continue
        ref = parse_board_pick_name(name)
        if ref is None:
            q.unresolved.append({"ref": name, "reason": "unparseable_pick_name"})
            continue
        gid = _generic_id(ref)
        if ref.grade == "generic":
            q.pick_unrefined.add(gid)
        q.pick_exact.setdefault(gid, set()).add(ref.canonical_id)
        q.accepted["picks"].append(name)
    for raw in list(pick_asset_ids)[:MAX_QUERY_ASSETS]:
        aid = str(raw or "").strip()
        if not aid:
            continue
        lp = parse_league_pick_id(aid)
        if lp is None:
            q.unresolved.append({"ref": aid, "reason": "unparseable_league_pick_id"})
            continue
        if lp.league_key != league_key:
            q.unresolved.append({"ref": aid, "reason": "owned_pick_other_league"})
            continue
        try:
            gid = MarketPickRef(year=lp.season, round_num=lp.round_num).canonical_id
        except ValueError:
            q.unresolved.append({"ref": aid, "reason": "pick_outside_market_grammar"})
            continue
        q.owned_ids.add(lp.canonical_id)
        q.pick_unrefined.add(gid)
        q.accepted["pickAssetIds"].append(aid)
    return q


def _asset_match(asset: Mapping[str, Any], q: _Query, *, own_this_league: bool) -> str | None:
    kind = asset.get("kind")
    cid = asset.get("canonicalId")
    if kind == "player":
        return MATCH_EXACT if cid and cid in q.players else None
    if kind != "pick" or not cid:
        return None
    if own_this_league and str(asset.get("vendorRef") or "") in q.owned_ids:
        return MATCH_EXACT
    gid = asset.get("matchKey")
    if not gid:
        return None
    asked = q.pick_exact.get(gid, set())
    if cid in asked:
        return MATCH_EXACT
    trade_ref = parse_market_pick_id(cid)
    trade_unrefined = trade_ref is not None and trade_ref.grade == "generic"
    if gid in q.pick_unrefined or (trade_unrefined and asked):
        return MATCH_ROUND
    return None


# ── Projection ────────────────────────────────────────────────────────────


def _visibility(row: Mapping[str, Any], league_key: str) -> tuple[bool, str | None, bool]:
    """``(visible, withheld_reason, is_this_leagues_own_trade)``."""
    families = set(row["sourceFamilies"])
    if not families or not families <= _VISIBLE_FAMILIES:
        return False, "unknown_source_family", False
    if SOURCE_OWN in families:
        keys = set(row["ownLeagueKeys"])
        if not keys and row.get("leagueKey"):
            keys = {str(row["leagueKey"])}
        if keys != {league_key}:
            return False, "own_league_other_league", False
        return True, None, True
    return True, None, False


def _asset_label(asset: Mapping[str, Any], names: Mapping[str, Mapping[str, Any]]) -> str | None:
    kind = asset.get("kind")
    cid = asset.get("canonicalId")
    if kind == "player" and cid:
        entry = names.get(str(cid).split(":", 1)[1])
        if entry and entry.get("name"):
            return str(entry["name"])
        return asset.get("label")
    if kind == "pick":
        ref = parse_market_pick_id(cid) if cid else None
        if ref is not None:
            return ref.board_row_name() or f"{ref.year} round {ref.round_num}"
        # Unresolved pick: the vendor's text (e.g. KTC "Startup Pick 26.01"),
        # never an internal asset id.
        label = asset.get("label")
        return None if not label or str(label).startswith("pick:") else str(label)
    if kind == "faab":
        amount = asset.get("faabAmount")
        return f"${amount:g} FAAB" if isinstance(amount, (int, float)) else "FAAB"
    # Unresolved: the vendor's own text when it published one (KTC), else
    # nothing — an unresolved asset is never given a guessed name.
    return asset.get("label")


def _project_asset(
    asset: Mapping[str, Any],
    q: _Query,
    names: Mapping[str, Mapping[str, Any]],
    *,
    own_this_league: bool,
) -> dict[str, Any]:
    kind = asset.get("kind")
    cid = asset.get("canonicalId")
    out: dict[str, Any] = {
        "kind": kind,
        "canonicalId": cid if kind in ("player", "pick") else None,
        "label": _asset_label(asset, names),
        "match": _asset_match(asset, q, own_this_league=own_this_league),
    }
    if kind == "player" and cid:
        entry = names.get(str(cid).split(":", 1)[1])
        out["position"] = (entry or {}).get("position") or asset.get("position")
        out["onBoard"] = entry is not None
    if kind == "pick":
        pick = asset.get("pick") or {}
        out["pick"] = (
            {
                "year": pick.get("year"),
                "round": pick.get("round"),
                "grade": pick.get("grade"),
                "gradeNote": pick.get("gradeNote"),
            }
            if pick
            else None
        )
    if kind == "faab":
        out["faabAmount"] = asset.get("faabAmount")
    if kind == "unresolved" or (kind == "pick" and not cid):
        out["unresolvedReason"] = (asset.get("resolution") or {}).get("reason")
    return out


def format_tags(row: Mapping[str, Any]) -> dict[str, Any]:
    """TC-10 tags, read verbatim from the ledger's format record.  ``None`` =
    unknown.  KTC's vendor TEP level / PPR code are passed through as the
    vendor's own settings — there is no measured crosswalk to a scoring card,
    so they are never translated into one."""
    mf = row.get("marketFormat") or {}
    general = mf.get("general") or {}
    offense = mf.get("offense") or {}
    te = mf.get("te") or {}
    idp = mf.get("idp") or {}
    vendor = mf.get("vendor") or {}
    source = mf.get("source")
    scoring = row.get("scoring")
    is_ktc = source == mtf.SOURCE_KTC
    # The normalized card drops explicit zeros ("absent == 0 removed"), so on a
    # KNOWN card an absent ``rec`` is 0 PPR.  No card -> unknown.
    ppr = float(scoring.get("rec", 0.0)) if isinstance(scoring, Mapping) else None
    return {
        "formatSource": source,
        "dynastyState": general.get("dynastyState"),
        "superflex": offense.get("superflex"),
        "teams": general.get("teams"),
        "starters": offense.get("totalStarters"),
        "teScoringEdge": te.get("scoringEdge"),
        "ktcTepLevel": vendor.get("tepLevel") if is_ktc else None,
        "pprPerReception": ppr,
        "ktcPprCode": vendor.get("pprCode") if is_ktc else None,
        "idp": idp.get("enabled"),
        "bestBall": general.get("bestBall"),
        "season": general.get("season"),
    }


def format_timing(row: Mapping[str, Any]) -> dict[str, Any]:
    """The ledger owner's timing verdict, plus a coarse label for display."""
    cap = mtf.format_timing_cap(row)
    ev = row.get("formatEvidence")
    ev = ev if isinstance(ev, Mapping) else None
    if cap is None and ev is not None and ev.get("exactAtTradeTime") is True:
        label = TIMING_EXACT
    elif cap == mtf.TIMING_CAP_POST_TRADE:
        label = TIMING_POST_TRADE
    elif cap == mtf.TIMING_CAP_UNCONFIRMED_AFTER_TRADE:
        label = TIMING_UNCONFIRMED
    elif cap == mtf.TIMING_CAP_CHANGED_AFTER_TRADE:
        label = TIMING_CHANGED
    else:
        label = TIMING_UNKNOWN
    return {
        "formatTiming": label,
        "formatTimingCap": cap,
        "formatEvidence": (
            {k: ev.get(k) for k in _EVIDENCE_KEYS if k in ev} if ev is not None else None
        ),
    }


def _format_match(row: Mapping[str, Any], league_key: str) -> dict[str, Any]:
    target = row.get("targetLeague")
    if target != league_key:
        return {
            "targetLeague": target,
            "appliesToThisLeague": False,
            "reason": "disposition_computed_for_other_league",
            "disposition": None,
            "targetPriceAuthority": None,
            "broadContextKind": None,
            "strongestUnsupportedAxis": None,
            "dispositionReasons": None,
        }
    return {
        "targetLeague": target,
        "appliesToThisLeague": True,
        "reason": None,
        "disposition": row.get("disposition"),
        "targetPriceAuthority": row.get("targetPriceAuthority"),
        "broadContextKind": row.get("broadContextKind"),
        "strongestUnsupportedAxis": row.get("strongestUnsupportedAxis"),
        "dispositionReasons": row.get("dispositionReasons"),
    }


def project_trade(
    row: Mapping[str, Any],
    q: _Query,
    league_key: str,
    names: Mapping[str, Mapping[str, Any]],
    *,
    own_this_league: bool,
) -> dict[str, Any]:
    sides = [
        [_project_asset(a, q, names, own_this_league=own_this_league) for a in side]
        for side in row["sides"]
    ]
    matches = [a["match"] for side in sides for a in side if a["match"]]
    return {
        "id": row["opaqueId"],
        "occurredDate": row["occurredDate"],
        "occurredAtMs": row["occurredAtMs"],
        "teamCount": row["teamCount"],
        # KTC states two packages but not who received which; Sleeper lanes
        # state what each roster RECEIVED.
        "sidesSemantics": (
            "packages_orientation_unstated"
            if row["representativeFamily"] == SOURCE_KTC
            else "received_per_roster"
        ),
        "sides": sides,
        "matchedAssets": len(matches),
        "exactMatches": sum(1 for m in matches if m == MATCH_EXACT),
        "sourceFamilies": row["sourceFamilies"],
        "provenance": row["provenance"],
        "ownLeagueTrade": own_this_league,
        "dedupeState": row["dedupeState"],
        "observationCount": row["observationCount"],
        "possibleOverlap": row["possibleOverlap"],
        "formatTags": format_tags(row),
        **format_timing(row),
        "formatMatch": _format_match(row, league_key),
        "caveats": row["caveats"],
    }


def _sort_key(t: Mapping[str, Any]) -> tuple:
    return (str(t.get("occurredDate") or ""), int(t.get("occurredAtMs") or 0), t["id"])


def reference_trades(
    league_key: str,
    *,
    player_ids: Sequence[str] = (),
    pick_names: Sequence[str] = (),
    pick_asset_ids: Sequence[str] = (),
    limit: int = DEFAULT_LIMIT,
    names: Mapping[str, Mapping[str, Any]] | None = None,
    today: date | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    """The response body for the route.  ``state`` is ``ok`` /
    ``no_assets`` / ``unavailable`` — the last never reads as "no trades"."""
    limit = max(1, min(int(limit), MAX_LIMIT))
    q = build_query(
        league_key,
        player_ids=player_ids,
        pick_names=pick_names,
        pick_asset_ids=pick_asset_ids,
    )
    since = ((today or date.today()) - timedelta(days=RECENT_LOOKBACK_DAYS)).isoformat()
    base: dict[str, Any] = {
        "leagueKey": league_key,
        "lookbackDays": RECENT_LOOKBACK_DAYS,
        "since": since,
        "query": {**q.accepted, "unresolved": q.unresolved},
        "samplingBiases": list(report.KNOWN_SAMPLING_BIASES),
    }
    loaded = _load(root, since)
    if loaded is None:
        return {
            **base,
            "state": "unavailable",
            "reason": "trade_ledger_not_built",
            "ledger": None,
            "trades": [],
            "truncated": False,
            "withheld": None,
        }
    meta, rows = loaded
    ledger = {
        "builtAt": meta.get("builtAt"),
        "targetLeague": meta.get("targetLeague"),
        "tradesInWindow": len(rows),
        "newestTradeDate": max(
            (r["occurredDate"] for r in rows if r["occurredDate"]), default=None
        ),
    }
    if q.empty():
        return {
            **base,
            "state": "no_assets",
            "reason": None,
            "ledger": ledger,
            "trades": [],
            "truncated": False,
            "withheld": None,
        }
    names = names or {}
    keys = q.keys()
    withheld: dict[str, int] = {}
    out: list[dict[str, Any]] = []
    for row in rows:
        touched = False
        for side in row["sides"]:
            for a in side:
                if a.get("canonicalId") in q.players or a.get("matchKey") in keys:
                    touched = True
                    break
            if touched:
                break
        if not touched:
            continue
        visible, reason, own = _visibility(row, league_key)
        if not visible:
            withheld[reason or "withheld"] = withheld.get(reason or "withheld", 0) + 1
            continue
        projected = project_trade(row, q, league_key, names, own_this_league=own)
        if projected["matchedAssets"]:
            out.append(projected)
    out.sort(key=_sort_key, reverse=True)
    return {
        **base,
        "state": "ok",
        "reason": None,
        "ledger": ledger,
        "trades": out[:limit],
        "matchingTrades": len(out),
        "truncated": len(out) > limit,
        "withheld": withheld,
    }
