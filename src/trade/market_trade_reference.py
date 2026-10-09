"""Recent real trades touching the calculator's assets — C3-CALC-01 / TC-07 + TC-10.

A DISPLAY projection of the canonical underlying-trade ledger
(``market_trade_report.open_canonical_ledger`` / ``read_ledger_trades`` — the
readers of the file the daily ``dynasty-market-trade-ledger`` build writes).
It answers one question: "which recorded real dynasty trades moved one of the
assets on my calculator, and what format were they made in?"  It shows FACTS —
the assets on each side, the date, the source, the format tags and the
ledger's own format disposition — and nothing else.

WHAT IT DELIBERATELY DOES NOT DO
────────────────────────────────
* **No valuation, no grade, no market price.**  Nothing here reads a canonical
  value or computes one from a trade (spec §2 rule 6; comps / market-price
  methodology is TC-09 / C4-MTL-03, not authorized here).
* **No identity matching of its own.**  The ledger's assets were resolved by
  the canonical owners at build time.  The calculator's side arrives as
  Sleeper player ids, board pick-row names and owned league-pick ids, parsed
  here ONLY through ``src.identity.picks`` grammar.  A player is matched by
  canonical id equality, never by name; an unresolved ledger asset can never
  match anything.
* **No format inference.**  Every tag is read from the ledger's own format
  record; ``None`` stays ``None`` (TC-10).  Never the target league's format.

PICK MATCHING — two named grades
────────────────────────────────
``exact``  — both sides state the SAME tier or the SAME slot, or it is the
             very same owned league pick.
``round``  — same year + round where at least one side states no tier or slot
             (two generic picks included: "a 2027 1st" and "a 2027 1st" are
             not provably the same pick).  Two DIFFERENT refinements (Early vs
             Late, a slot vs a tier) never match.

WHICH ROWS MAY BE SHOWN — fail closed at every step
───────────────────────────────────────────────────
1. Source family must be one of the three known lanes.
2. GAME TYPE: only rows whose ledger format says ``dynastyState == dynasty``.
   Unverified game type is not dynasty (CLAUDE.md, source-domain boundaries).
3. ``own_league_sleeper`` — only for the requested league.  Membership is read
   from the observation ids, not only the representative's ``leagueKey``.
4. Any OTHER row whose host league is a registry league or one of its
   ``previous_league_id`` chain seasons is withheld: a registry league's trade
   that reached the ledger through another lane must not appear in another
   league's view.  When the chain cannot be resolved, every row that could be
   a Sleeper league (a Sharp row, a KTC row hosted on Sleeper or on an unknown
   host with a league id) is withheld.
5. ``sleeper_sharp_discovery`` rows (with no KTC observation of the same
   trade) are shown only when a manager on the trade is a member of THE Sharp
   cohort (``src.sharp.cohort.cohort_members`` — the one owner).  That is the
   population ``/api/sharp/market/audit`` already shows signed-in users; a
   non-cohort manager's trade in a discovered league is not.
6. ``ktc_trade_database`` — KTC's own public trade database (spec §19.2).

Output carries no league id, transaction id, manager id, observation id or
underlying-trade id.  The row ``id`` is an HMAC of the underlying-trade id
under a PER-PROCESS random key: stable for React keys within one server
process, unjoinable against any other endpoint, and different after restart.

Missing is never zero: no ledger on the host is an ``unavailable`` answer,
never an empty list presented as "no trades".
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

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

#: How far back "recent" reaches.  A display bound, not methodology: trades
#: are only listed, never weighted; the window is stamped on every response.
RECENT_LOOKBACK_DAYS = 365
DEFAULT_LIMIT = 20
MAX_LIMIT = 50
#: Guard against an unbounded query string.
MAX_QUERY_ASSETS = 40
#: Rows examined per request (newest first).  A very common asset (a 2027 1st)
#: touches most of the ledger; the answer only needs the newest few visible.
MAX_SCAN = 2000

MATCH_EXACT = "exact"
MATCH_ROUND = "round"

#: ``formatTiming`` — a coarse reading of the ledger owner's own
#: ``format_timing_cap`` + ``formatEvidence``; the raw evidence travels too.
TIMING_EXACT = "exact"
TIMING_POST_TRADE = "post_trade"
TIMING_UNCONFIRMED = "unconfirmed"
TIMING_CHANGED = "changed_after_trade"
TIMING_UNKNOWN = "unknown"

#: Withheld-row reasons (counted, never listed).
WITHHELD_UNKNOWN_FAMILY = "unknown_source_family"
WITHHELD_GAME_TYPE = "game_type_not_verified_dynasty"
WITHHELD_OTHER_LEAGUE = "own_league_other_league"
WITHHELD_REGISTRY_LEAGUE = "registry_league_via_other_lane"
WITHHELD_CHAIN_UNRESOLVED = "registry_league_chain_unresolved"
WITHHELD_NO_COHORT_MANAGER = "sharp_trade_without_cohort_manager"
WITHHELD_COHORT_UNVERIFIABLE = "sharp_cohort_unverifiable"

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

#: Per-process HMAC key for row ids (see module docstring).
_ROW_ID_KEY = secrets.token_bytes(32)


def _row_id(underlying_trade_id: Any) -> str:
    return hmac.new(
        _ROW_ID_KEY, str(underlying_trade_id).encode("utf-8"), hashlib.sha256
    ).hexdigest()[:16]


# ── Privacy context (registry chain + Sharp cohort), resolved lazily ─────


@dataclass
class PrivacyContext:
    """Everything the visibility rules need beyond the row itself.

    ``registry_league_ids`` — every registry league's Sleeper id plus every
    season-league in its ``previous_league_id`` chain; ``chain_resolved`` is
    False when the chain store could not prove the chain for every registry
    league.  ``sharp_trade_has_cohort_manager(league_id, tx_id)`` answers
    True / False, or ``None`` when it cannot be determined.
    """

    registry_league_ids: frozenset[str]
    chain_resolved: bool
    sharp_trade_has_cohort_manager: Callable[[str, str], bool | None]
    close: Callable[[], None] = field(default=lambda: None)


def _registry_chain() -> tuple[frozenset[str], bool]:
    from src.api import league_registry  # noqa: PLC0415
    from src.trade import own_league_format_capture as olfc  # noqa: PLC0415

    ids: set[str] = set()
    keys: set[str] = set()
    for cfg in league_registry.all_leagues():
        keys.add(cfg.key)
        if cfg.sleeper_league_id:
            ids.add(str(cfg.sleeper_league_id))
    try:
        index = olfc.load_index()
    except Exception:  # noqa: BLE001 — unreadable chain is unresolved, never empty
        return frozenset(ids), False
    seasons = index.seasons or {}
    for key in keys:
        ids.update(str(v) for v in (seasons.get(key) or {}).values())
    resolved = bool(keys) and all(seasons.get(k) for k in keys)
    return frozenset(ids), resolved


def default_privacy_context() -> PrivacyContext:
    ids, resolved = _registry_chain()
    state: dict[str, Any] = {"cohort": None, "cohort_loaded": False, "conn": None}

    def _cohort() -> frozenset[str] | None:
        if not state["cohort_loaded"]:
            state["cohort_loaded"] = True
            try:
                from src.sharp.cohort import cohort_members  # noqa: PLC0415

                members, _ = cohort_members(qualification="all")
                state["cohort"] = frozenset(m.manager_key for m in members)
            except Exception:  # noqa: BLE001 — unverifiable, withheld
                state["cohort"] = None
        return state["cohort"]

    def _conn() -> sqlite3.Connection | None:
        if state["conn"] is None:
            try:
                from src.intel import ledger as intel_ledger  # noqa: PLC0415

                p = Path(intel_ledger.default_path())
                if not p.exists():
                    return None
                state["conn"] = sqlite3.connect(f"file:{p.as_posix()}?mode=ro", uri=True)
            except Exception:  # noqa: BLE001
                return None
        return state["conn"]

    def has_cohort_manager(league_id: str, tx_id: str) -> bool | None:
        cohort = _cohort()
        conn = _conn()
        if cohort is None or conn is None:
            return None
        try:
            rows = conn.execute(
                "SELECT DISTINCT user_id, counterparty_user_id FROM asset_movements "
                "WHERE tx_id = ? AND league_id = ?",
                (tx_id, league_id),
            ).fetchall()
        except sqlite3.DatabaseError:
            return None
        if not rows:
            return None
        users = {f"sleeper:{u}" for row in rows for u in row if u}
        return bool(users & cohort)

    def close() -> None:
        if state["conn"] is not None:
            state["conn"].close()

    return PrivacyContext(
        registry_league_ids=ids,
        chain_resolved=resolved,
        sharp_trade_has_cohort_manager=has_cohort_manager,
        close=close,
    )


# ── Query: the calculator's assets, through the identity owners ──────────


class _Query:
    def __init__(self) -> None:
        self.players: set[str] = set()
        #: generic key -> refined (tier / slot) canonical ids asked for
        self.pick_refined: dict[str, set[str]] = {}
        #: generic keys asked for WITHOUT a refinement (a generic row, or an
        #: owned pick whose slot is not resolved here)
        self.pick_unrefined: set[str] = set()
        self.owned_ids: set[str] = set()
        self.unresolved: list[dict[str, Any]] = []
        self.accepted: dict[str, list[str]] = {"players": [], "picks": [], "pickAssetIds": []}

    def keys(self) -> set[str]:
        return self.players | set(self.pick_refined) | self.pick_unrefined

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
        else:
            q.pick_refined.setdefault(gid, set()).add(ref.canonical_id)
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
    trade_ref = parse_market_pick_id(cid)
    trade_refined = trade_ref is not None and trade_ref.grade != "generic"
    asked_refined = q.pick_refined.get(gid, set())
    if trade_refined and cid in asked_refined:
        return MATCH_EXACT
    if gid in q.pick_unrefined:
        return MATCH_ROUND
    if not trade_refined and asked_refined:
        return MATCH_ROUND
    return None


# ── Visibility ────────────────────────────────────────────────────────────


def _member_parts(rec: Mapping[str, Any], family: str) -> list[list[str]]:
    out = []
    for m in rec.get("members") or []:
        m = str(m)
        if m.startswith(f"{family}:"):
            out.append(m.split(":")[1:])
    return out


def visibility(
    rec: Mapping[str, Any], league_key: str, ctx: PrivacyContext
) -> tuple[bool, str | None, bool]:
    """``(visible, withheld_reason, is_this_leagues_own_trade)`` — see the
    module docstring for the rules, applied in order, failing closed."""
    families = {str(f) for f in rec.get("sourceFamilies") or []}
    if not families or not families <= _VISIBLE_FAMILIES:
        return False, WITHHELD_UNKNOWN_FAMILY, False
    general = (rec.get("marketFormat") or {}).get("general") or {}
    if general.get("dynastyState") != mtf.DYNASTY:
        return False, WITHHELD_GAME_TYPE, False
    if SOURCE_OWN in families:
        keys = {parts[0] for parts in _member_parts(rec, SOURCE_OWN) if parts}
        if not keys and rec.get("leagueKey"):
            keys = {str(rec["leagueKey"])}
        if keys != {league_key}:
            return False, WITHHELD_OTHER_LEAGUE, False
        return True, None, True
    sharp_pairs = [p for p in _member_parts(rec, SOURCE_SHARP) if len(p) >= 2]
    host_ids = {str(p[0]) for p in sharp_pairs}
    if rec.get("hostLeagueId"):
        host_ids.add(str(rec["hostLeagueId"]))
    if host_ids & ctx.registry_league_ids:
        return False, WITHHELD_REGISTRY_LEAGUE, False
    if not ctx.chain_resolved:
        could_be_sleeper = bool(sharp_pairs) or (
            rec.get("hostLeagueId") and rec.get("host") in ("sleeper", "unknown", None)
        )
        if could_be_sleeper:
            return False, WITHHELD_CHAIN_UNRESOLVED, False
    if SOURCE_KTC not in families:
        verdicts = [ctx.sharp_trade_has_cohort_manager(p[0], p[1]) for p in sharp_pairs]
        if any(v is True for v in verdicts):
            return True, None, False
        if not verdicts or any(v is None for v in verdicts):
            return False, WITHHELD_COHORT_UNVERIFIABLE, False
        return False, WITHHELD_NO_COHORT_MANAGER, False
    return True, None, False


# ── Projection ────────────────────────────────────────────────────────────


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


def format_tags(rec: Mapping[str, Any], full_format: Mapping[str, Any] | None) -> dict[str, Any]:
    """TC-10 tags, read verbatim from the ledger's format record.  ``None`` =
    unknown.  KTC's vendor TEP level / PPR code are passed through as the
    vendor's own settings — there is no measured crosswalk to a scoring card,
    so they are never translated into one."""
    mf = rec.get("marketFormat") or {}
    general = mf.get("general") or {}
    offense = mf.get("offense") or {}
    te = mf.get("te") or {}
    idp = mf.get("idp") or {}
    vendor = mf.get("vendor") or {}
    source = mf.get("source")
    scoring = full_format.get("scoring") if isinstance(full_format, Mapping) else None
    is_ktc = source == mtf.SOURCE_KTC
    # The normalized card drops explicit zeros ("absent == 0 removed"), so on a
    # KNOWN card an absent ``rec`` key is 0 PPR.  No card -> unknown.
    ppr = None
    if isinstance(scoring, Mapping):
        ppr = float(scoring["rec"]) if "rec" in scoring else 0.0
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


def format_timing(rec: Mapping[str, Any]) -> dict[str, Any]:
    """The ledger owner's timing verdict, plus a coarse label for display."""
    cap = mtf.format_timing_cap(rec)
    ev = rec.get("formatEvidence")
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


def _format_match(rec: Mapping[str, Any], league_key: str) -> dict[str, Any]:
    target = rec.get("targetLeague")
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
        "disposition": rec.get("disposition"),
        "targetPriceAuthority": rec.get("targetPriceAuthority"),
        "broadContextKind": rec.get("broadContextKind"),
        "strongestUnsupportedAxis": rec.get("strongestUnsupportedAxis"),
        "dispositionReasons": rec.get("dispositionReasons"),
    }


def project_trade(
    rec: Mapping[str, Any],
    full_format: Mapping[str, Any] | None,
    q: _Query,
    league_key: str,
    names: Mapping[str, Mapping[str, Any]],
    *,
    own_this_league: bool,
) -> dict[str, Any]:
    sides = [
        [_project_asset(a, q, names, own_this_league=own_this_league) for a in side]
        for side in rec.get("sides") or []
    ]
    matches = [a["match"] for side in sides for a in side if a["match"]]
    rep = str(rec.get("representativeObservationId") or "")
    return {
        "id": _row_id(rec.get("underlyingTradeId")),
        "occurredDate": rec.get("occurredDate"),
        "occurredAtMs": rec.get("occurredAtMs"),
        "teamCount": rec.get("teamCount"),
        # KTC states two packages but not who received which; Sleeper lanes
        # state what each roster RECEIVED.
        "sidesSemantics": (
            "packages_orientation_unstated"
            if rep.startswith(f"{SOURCE_KTC}:")
            else "received_per_roster"
        ),
        "sides": sides,
        "matchedAssets": len(matches),
        "exactMatches": sum(1 for m in matches if m == MATCH_EXACT),
        "sourceFamilies": sorted(str(f) for f in rec.get("sourceFamilies") or []),
        "provenance": list(rec.get("provenance") or []),
        "ownLeagueTrade": own_this_league,
        "dedupeState": rec.get("dedupeState"),
        "observationCount": rec.get("observationCount"),
        "possibleOverlap": bool(rec.get("possibleOverlapWith")),
        "formatTags": format_tags(rec, full_format),
        **format_timing(rec),
        "formatMatch": _format_match(rec, league_key),
        "caveats": [str(c) for c in rec.get("caveats") or []],
    }


def _ledger_summary(conn: sqlite3.Connection, since: str) -> dict[str, Any]:
    meta = report.read_ledger_meta(conn)
    count, newest = conn.execute(
        "SELECT COUNT(*), MAX(occurred_date) FROM underlying_trades "
        "WHERE occurred_date IS NOT NULL AND occurred_date >= ?",
        (since,),
    ).fetchone()
    return {
        "builtAt": meta.get("builtAt"),
        "targetLeague": meta.get("targetLeague"),
        "tradesInWindow": count,
        "newestTradeDate": newest,
    }


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
    privacy: Callable[[], PrivacyContext] | None = None,
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
    conn = report.open_canonical_ledger(root)
    if conn is None:
        return {
            **base,
            "state": "unavailable",
            "reason": "trade_ledger_not_built",
            "ledger": None,
            "trades": [],
            "truncated": False,
            "withheld": None,
        }
    ctx: PrivacyContext | None = None
    try:
        ledger = _ledger_summary(conn, since)
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
        ctx = (privacy or default_privacy_context)()
        names = names or {}
        withheld: dict[str, int] = {}
        out: list[dict[str, Any]] = []
        scanned = 0
        scan_capped = False
        for rec, full_format in report.read_ledger_trades(
            conn, asset_keys=sorted(q.keys()), since_date=since
        ):
            if scanned >= MAX_SCAN:
                scan_capped = True
                break
            scanned += 1
            visible, reason, own = visibility(rec, league_key, ctx)
            if not visible:
                withheld[reason or "withheld"] = withheld.get(reason or "withheld", 0) + 1
                continue
            projected = project_trade(rec, full_format, q, league_key, names, own_this_league=own)
            if not projected["matchedAssets"]:
                continue
            out.append(projected)
            if len(out) > limit:
                break
    finally:
        conn.close()
        if ctx is not None:
            ctx.close()
    return {
        **base,
        "state": "ok",
        "reason": None,
        "ledger": ledger,
        "trades": out[:limit],
        "truncated": len(out) > limit,
        "scanned": scanned,
        "scanCapped": scan_capped,
        "withheld": withheld,
    }
