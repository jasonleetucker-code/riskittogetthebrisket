"""Market Trade Ledger — source observations -> ONE normalized shape.

Every acquisition lane (spec §19.1-19.3) is mapped here into the same
observation shape, with every asset resolved through the canonical identity
owners — players via ``src.identity.resolution.resolve_canonical_v2``, picks
via ``src.identity.picks`` — so the grouping and evaluation layers never see
a vendor id or a free-text label.

Lanes today:

* ``ktc_trade_database`` — the append-only archive written by
  ``src.sources.ktc_trades`` (``market_trade_archive``);
* ``sleeper_sharp_discovery`` — trades already in the intel ledger
  (``src/intel/ledger.py``, filled by ``scripts/crawl_sharp_transactions.py``
  over the Sharp discovery graph).  Read READ-ONLY through a ``mode=ro``
  connection: opening it through ``ledger.connect`` would run its schema
  migration, and a report has no business migrating a production store;
* ``own_league_sleeper`` — our own registered leagues' trades, through the
  existing C4-MTL-01 owner ``market_trade_ledger.market_trades`` (the one
  module authorized to read the acquisition store).

No lane launches a crawl.  Each reports ``available`` / ``unavailable`` with a
reason, so "we have no Sleeper evidence on this box" and "Sleeper evidence
says there were no trades" never read the same.

IDENTITY RULES, ALL FAIL CLOSED
───────────────────────────────
* **Unresolved stays unresolved, with its reason.**  A KTC id whose name the
  canonical V2 ladder cannot place (no candidate, ambiguous homonym) is an
  ``unresolved`` asset carrying the resolver's reason and candidate ids — never
  the best fuzzy guess.  V2 is the right ladder here precisely because an
  explicit refusal is acceptable for evidence (CLAUDE.md, Player identity).
* **Picks keep their REAL grade.**  ``2026 Pick 1.02`` is a slot,
  ``2027 Early 1st`` a tier, ``2028 Round 5`` generic.  KTC's ``Mid`` tier is
  the one exception, and it is a DOWNGRADE, not an invention: KTC's own client
  rewrites every RDP ``" Mid "`` label to ``" Round "`` before display
  (``genericizePickName`` in ``site.min.js``) because Mid is the default it
  assigns when the host never said which tier.  So a KTC Mid pick is filed at
  the GENERIC grade with ``gradeNote: ktc_mid_is_vendor_default``; the raw
  label is preserved.  Nothing is ever refined upward to a slot.
* **Cross-source matching compares picks at the generic grade**
  (``mpick:<year>:r<N>``) — Sleeper's traded-pick record has no tier or slot,
  so it is the only grade both lanes can state.
* A startup-draft pick (``Startup Pick 26.01``) is not a rookie market pick
  reference; it is kept as an asset with ``canonicalId: None`` and a reason.
* FAAB money inside a trade is an asset of kind ``faab`` with its amount.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from src.identity.picks import (
    MarketPickRef,
    parse_intel_pick_asset_id,
    parse_league_pick_id,
    parse_pick_label,
)
from src.identity.resolution import (
    RESOLVED,
    Resolution,
    SleeperDirectoryIndex,
    build_sleeper_index,
    resolve_canonical_v2,
)
from src.sources.ktc_identity import KtcIdentityMap, identity_from_rows
from src.trade import market_trade_archive as archive
from src.trade import market_trade_format as mtf

SOURCE_KTC = "ktc_trade_database"
SOURCE_SLEEPER_DISCOVERY = "sleeper_sharp_discovery"
SOURCE_OWN_LEAGUE = "own_league_sleeper"

#: Provenance labels from spec §19.7.  A trade seen through several lanes
#: carries all of them while contributing ONE to volume.
PROVENANCE_BY_SOURCE = {
    SOURCE_KTC: "KTC_MARKET",
    SOURCE_SLEEPER_DISCOVERY: "SHARP_DISCOVERY",
    SOURCE_OWN_LEAGUE: "OWN_LEAGUE",
}

KIND_PLAYER = "player"
KIND_PICK = "pick"
KIND_FAAB = "faab"
KIND_UNRESOLVED = "unresolved"


# ── Identity context ──────────────────────────────────────────────────────


@dataclass
class IdentityContext:
    """One Sleeper directory index + per-build resolution caches.

    ``index`` is ``None`` when no directory is on disk; every player then
    resolves to ``unresolved`` / ``identity_directory_unavailable`` rather
    than being guessed.
    """

    index: SleeperDirectoryIndex | None
    directory_source: str | None = None
    _ktc_cache: dict[tuple[str, str], Resolution] = field(default_factory=dict)
    _sid_cache: dict[str, Resolution] = field(default_factory=dict)

    @classmethod
    def from_directory(
        cls, directory: Mapping[str, Any] | None, *, source: str | None = None
    ) -> "IdentityContext":
        if not directory:
            return cls(index=None, directory_source=None)
        return cls(index=build_sleeper_index(directory), directory_source=source)

    @classmethod
    def load_default(cls) -> "IdentityContext":
        """The app's cached Sleeper ``/players/nfl`` dump — never fetched here."""
        try:
            from src.consensus_edge.identity_join import load_player_directory  # noqa: PLC0415

            directory = load_player_directory()
        except Exception:  # noqa: BLE001 — absence is a state
            directory = None
        return cls.from_directory(
            directory, source="public_league.nfl_players" if directory else None
        )

    def resolve_name(self, name: str, position: str | None) -> Resolution | None:
        if self.index is None:
            return None
        key = (name, position or "")
        if key not in self._ktc_cache:
            self._ktc_cache[key] = resolve_canonical_v2(self.index, name=name, position=position)
        return self._ktc_cache[key]

    def true_position(self, sleeper_id: str) -> str | None:
        if self.index is None:
            return None
        cand = self.index.by_sleeper_id.get(str(sleeper_id))
        return (cand.position or None) if cand is not None else None

    def resolve_sleeper_id(self, sleeper_id: str) -> Resolution | None:
        if self.index is None:
            return None
        if sleeper_id not in self._sid_cache:
            self._sid_cache[sleeper_id] = resolve_canonical_v2(self.index, sleeper_id=sleeper_id)
        return self._sid_cache[sleeper_id]


# ── Asset constructors ────────────────────────────────────────────────────


def _resolution_dict(res: Resolution | None, *, unavailable_reason: str | None = None) -> dict:
    if res is None:
        return {
            "status": "unresolved",
            "method": "none",
            "reason": unavailable_reason or "identity_directory_unavailable",
        }
    out = {"status": res.status, "method": res.method, "policy": res.policy}
    if res.status == RESOLVED:
        out["confidence"] = res.confidence
    else:
        out["reason"] = res.reason
        if res.candidate_ids:
            out["candidateIds"] = list(res.candidate_ids)
    return out


def _player_asset(
    res: Resolution | None,
    *,
    vendor_ref: str | None,
    label: str | None,
    ctx: "IdentityContext | None" = None,
) -> dict:
    if res is not None and res.status == RESOLVED and res.sleeper_id:
        cid = f"player:{res.sleeper_id}"
        return {
            "kind": KIND_PLAYER,
            "canonicalId": cid,
            "matchKey": cid,
            "position": res.position,
            # The directory's own position (DE / CB / S ...), so IDP evidence
            # keeps its true position rather than only the family.
            "truePosition": ctx.true_position(res.sleeper_id) if ctx is not None else None,
            "vendorRef": vendor_ref,
            "label": label,
            "resolution": _resolution_dict(res),
        }
    return {
        "kind": KIND_UNRESOLVED,
        "canonicalId": None,
        "matchKey": f"unresolved:{vendor_ref or label}",
        "vendorRef": vendor_ref,
        "label": label,
        "resolution": _resolution_dict(res),
    }


def _pick_asset(
    ref: MarketPickRef | None,
    *,
    vendor_ref: str | None,
    label: str | None,
    vendor_grade: str | None,
    grade_note: str | None = None,
    reason: str | None = None,
) -> dict:
    if ref is None:
        return {
            "kind": KIND_PICK,
            "canonicalId": None,
            "matchKey": f"unresolvedpick:{label or vendor_ref}",
            "vendorRef": vendor_ref,
            "label": label,
            "pick": None,
            "resolution": {"status": "unresolved", "method": "pick_label", "reason": reason},
        }
    generic = MarketPickRef(year=ref.year, round_num=ref.round_num)
    return {
        "kind": KIND_PICK,
        "canonicalId": ref.canonical_id,
        # Cross-source comparisons use the generic grade: it is the only
        # grade a Sleeper traded-pick record can state.
        "matchKey": generic.canonical_id,
        "vendorRef": vendor_ref,
        "label": label,
        "pick": {
            "year": ref.year,
            "round": ref.round_num,
            "grade": ref.grade,
            "vendorGrade": vendor_grade,
            "gradeNote": grade_note,
        },
        "resolution": {"status": "resolved", "method": "pick_label"},
    }


def market_ref_from_vendor_label(
    label: str, *, mid_is_vendor_default: bool
) -> tuple[MarketPickRef | None, str | None, str | None, str | None]:
    """``(ref, vendor_grade, grade_note, reason)`` for one pick label.

    Grade is never refined: a slot label stays a slot, a tier stays a tier,
    a round stays generic.  ``mid_is_vendor_default`` downgrades a ``Mid``
    tier to generic (see module docstring).  ``ref`` is ``None`` with a
    reason when the label is not a rookie market reference.
    """
    text = (label or "").strip()
    if text.lower().startswith("startup"):
        return None, None, None, "startup_pick_not_a_market_ref"
    parsed = parse_pick_label(text)
    if parsed is None:
        return None, None, None, "unparseable_pick_label"
    try:
        ref = parsed.market_ref
    except ValueError:
        return None, None, None, "pick_outside_market_grammar"
    vendor_grade = ref.grade
    if ref.tier == "mid" and mid_is_vendor_default:
        return (
            MarketPickRef(year=ref.year, round_num=ref.round_num),
            vendor_grade,
            "ktc_mid_is_vendor_default",
            None,
        )
    return ref, vendor_grade, None, None


# ── KTC lane ──────────────────────────────────────────────────────────────


def _ktc_side(
    refs: Iterable[Any], identity: KtcIdentityMap, ctx: IdentityContext
) -> list[dict[str, Any]]:
    side: list[dict[str, Any]] = []
    for raw in refs:
        asset = identity.classify(raw)
        vendor_ref = asset.raw
        if asset.kind == "faab_amount":
            amount_txt = (asset.name or "").replace("$", "").strip()
            try:
                amount: float | None = float(amount_txt)
            except ValueError:
                amount = None
            side.append(
                {
                    "kind": KIND_FAAB,
                    "canonicalId": None,
                    "matchKey": f"faab:{amount}",
                    "vendorRef": vendor_ref,
                    "label": asset.name,
                    "faabAmount": amount,
                    "resolution": {"status": "resolved", "method": "faab_literal"},
                }
            )
        elif asset.kind == "pick":
            ref, vgrade, note, reason = market_ref_from_vendor_label(
                asset.name or "", mid_is_vendor_default=True
            )
            side.append(
                _pick_asset(
                    ref,
                    vendor_ref=vendor_ref,
                    label=asset.name,
                    vendor_grade=vgrade,
                    grade_note=note,
                    reason=reason,
                )
            )
        elif asset.kind == "player":
            position = identity.position_for(asset.player_id) if asset.player_id else None
            res = ctx.resolve_name(asset.name or "", position)
            side.append(_player_asset(res, vendor_ref=vendor_ref, label=asset.name, ctx=ctx))
        else:
            side.append(
                {
                    "kind": KIND_UNRESOLVED,
                    "canonicalId": None,
                    "matchKey": f"unresolved:ktc:{vendor_ref}",
                    "vendorRef": vendor_ref,
                    "label": None,
                    "resolution": {
                        "status": "unresolved",
                        "method": "ktc_identity",
                        "reason": asset.reason,
                    },
                }
            )
    return side


def normalize_ktc_row(
    raw: Mapping[str, Any],
    identity: KtcIdentityMap,
    ctx: IdentityContext,
) -> dict[str, Any]:
    """One archived KTC revision -> one normalized observation."""
    from src.sources.ktc_trades import host_platform, observed_date  # noqa: PLC0415

    payload = raw["payload"]
    settings = payload.get("settings") or {}
    host = host_platform(settings)
    league_id = str(settings.get("id") or "").strip() or None
    t1 = payload.get("teamOne") or {}
    t2 = payload.get("teamTwo") or {}
    vft_side: int | None = None
    if t1.get("isVftFavored") is True and t2.get("isVftFavored") is not True:
        vft_side = 0
    elif t2.get("isVftFavored") is True and t1.get("isVftFavored") is not True:
        vft_side = 1
    used = payload.get("isUsedInVft")
    return {
        "observationId": f"{SOURCE_KTC}:{raw['sourceNativeId']}#{raw['payloadSha256'][:12]}",
        "sourceFamily": SOURCE_KTC,
        "sourceNativeId": str(raw["sourceNativeId"]),
        "payloadSha256": raw["payloadSha256"],
        "revision": raw.get("revision"),
        "revisionCount": raw.get("revisionCount"),
        "firstFetchedAt": raw.get("firstFetchedAt"),
        "host": host,
        "hostLeagueId": league_id,
        # KTC publishes no host transaction id — the reason a KTC/Sleeper
        # overlap can be PROBABLE but never CONFIRMED (spec §19.5 level 2).
        "hostTxId": None,
        "occurredDate": observed_date(payload),
        "occurredAtMs": None,
        "timeFidelity": "day",
        "_format": mtf.format_from_ktc_settings(settings),
        "formatSource": "ktc_vendor_settings",
        "sides": [
            _ktc_side(t1.get("playerIds") or [], identity, ctx),
            _ktc_side(t2.get("playerIds") or [], identity, ctx),
        ],
        "teamCount": 2,
        # Which team RECEIVED which package is not stated by the feed, and is
        # not needed: for a two-team trade the partition into two packages is
        # identical either way.
        "sideSemantics": "package_partition_orientation_unstated",
        "vendorFlags": {
            "isUsedInVft": used if isinstance(used, bool) else None,
            "vftFavoredSide": vft_side,
        },
        "provenance": [PROVENANCE_BY_SOURCE[SOURCE_KTC]],
        "caveats": [],
    }


def ktc_observations(
    *, archive_path: Path | None = None, ctx: IdentityContext
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Latest revision per KTC trade id, normalized.  ``(rows, laneStatus)``."""
    raws = archive.read_observations(SOURCE_KTC, path=archive_path)
    if not raws:
        exists = (Path(archive_path) if archive_path else archive.default_path()).exists()
        return [], {
            "available": False,
            "reason": "archive_empty" if exists else "archive_missing",
        }
    latest: dict[str, dict[str, Any]] = {}
    for r in raws:
        latest[r["sourceNativeId"]] = r  # ordered oldest-first, so last wins
    identity_cache: dict[str | None, KtcIdentityMap] = {}
    out: list[dict[str, Any]] = []
    for r in latest.values():
        sha = r.get("identitySha256") or archive.identity_snapshot_sha_at(
            SOURCE_KTC, r.get("firstFetchedAt"), path=archive_path
        )
        if sha not in identity_cache:
            rows = archive.read_identity_snapshot(sha, path=archive_path) if sha else None
            identity_cache[sha] = identity_from_rows(rows or [], source="archived_snapshot")
        out.append(normalize_ktc_row(r, identity_cache[sha], ctx))
    # A row without a revision count is not counted as revised (unknown is
    # not "revised"), and no number is fabricated for it.
    revised = sum(
        1
        for r in latest.values()
        if isinstance(r.get("revisionCount"), int) and r["revisionCount"] > 1
    )
    return out, {
        "available": True,
        "rawRevisions": len(raws),
        "distinctTrades": len(latest),
        "tradesWithRevisions": revised,
    }


# ── Sleeper discovery lane (intel ledger, read-only) ─────────────────────


def _sleeper_asset(asset_id: str, asset_type: str, ctx: IdentityContext) -> dict[str, Any]:
    if asset_type == "pick":
        parsed = parse_intel_pick_asset_id(asset_id)
        if parsed is None:
            return _pick_asset(
                None,
                vendor_ref=asset_id,
                label=asset_id,
                vendor_grade=None,
                reason="unparseable_intel_pick_id",
            )
        season, rnd = parsed
        try:
            ref: MarketPickRef | None = MarketPickRef(year=season, round_num=rnd)
            reason = None
        except ValueError:
            ref, reason = None, "pick_outside_market_grammar"
        return _pick_asset(
            ref, vendor_ref=asset_id, label=asset_id, vendor_grade="generic", reason=reason
        )
    res = ctx.resolve_sleeper_id(str(asset_id))
    return _player_asset(res, vendor_ref=str(asset_id), label=None, ctx=ctx)


def _ms_to_date(ms: int | None) -> str | None:
    if ms is None:
        return None
    return datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc).date().isoformat()


def _sides_from_movements(
    moves: list[dict[str, Any]], to_asset
) -> tuple[list[list[dict[str, Any]]], list[str]]:
    """Per-roster RECEIVED lists from add/drop movements, plus caveats.

    An asset dropped with no matching add was RELEASED inside the trade (not
    exchanged) and is left out of the sides; an add with no matching drop means
    the sending roster was outside the recorded pool, so the record is partial.
    """
    received: dict[str, list[dict[str, Any]]] = {}
    sent_count: dict[str, int] = {}
    add_count: dict[str, int] = {}
    rosters: set[str] = set()
    for m in moves:
        rid = str(m.get("roster_id") or "?")
        rosters.add(rid)
        if m["action"] == "add":
            received.setdefault(rid, []).append(to_asset(m))
            add_count[m["asset_id"]] = add_count.get(m["asset_id"], 0) + 1
        elif m["action"] == "drop":
            sent_count[m["asset_id"]] = sent_count.get(m["asset_id"], 0) + 1
    caveats: list[str] = []
    released = sum(max(0, n - add_count.get(a, 0)) for a, n in sent_count.items())
    unsent = sum(max(0, n - sent_count.get(a, 0)) for a, n in add_count.items())
    if released:
        caveats.append(f"released_in_trade:{released}")
    if unsent:
        caveats.append(f"partial_record_adds_without_sender:{unsent}")
    sides = [received.get(rid, []) for rid in sorted(rosters)]
    return sides, caveats


#: ``formatSource`` labels for a Sharp-discovery trade.  The census counts
#: these; it does not interpret them.
FORMAT_SOURCE_CAPTURE_FULL = "sleeper_league_capture_full"
FORMAT_SOURCE_CAPTURE_POST_TRADE = "sleeper_league_capture_post_trade"
FORMAT_SOURCE_PARTIAL = "discovery_row_partial"
#: A KTC row upgraded to a host capture in force at its trade date.
FORMAT_SOURCE_KTC_HOST_UPGRADE = "host_capture_via_discovery"


def _sleeper_league_format(
    league_row: Mapping[str, Any],
    settings: Any,
    *,
    captures: list[Mapping[str, Any]] | None = None,
    trade_ms: int | None = None,
) -> tuple[mtf.TradeMarketFormat, str, dict[str, Any]]:
    """``(format, formatSource, formatEvidence)`` for one Sharp-discovery trade.

    The format is the host league's DATED capture in force at the trade's
    timestamp (``league_format_capture.capture_in_force``): the nearest prior
    capture is ``sleeper_league_capture_full``; when only a later capture of the
    same season exists it is used but labelled
    ``sleeper_league_capture_post_trade`` and never presented as exact-at-time.
    With no capture, only the facts the discovery row itself carries (type,
    best-ball, roster count) are known and everything else is UNKNOWN — never
    inferred from the discovering user.
    """
    from src.sharp import league_format_capture as lfc  # noqa: PLC0415

    settings = settings if isinstance(settings, dict) else {}
    season = str(league_row.get("season")) if league_row.get("season") else None
    candidates = list(captures or [])
    legacy = lfc.legacy_settings_capture(str(league_row.get("league_id") or ""), settings)
    if legacy is not None:
        candidates.append(legacy)
    cap, timing = lfc.capture_in_force(candidates, trade_ms, season=season)
    if cap is not None:
        label = (
            FORMAT_SOURCE_CAPTURE_FULL
            if timing == lfc.TIMING_AT_OR_BEFORE
            else FORMAT_SOURCE_CAPTURE_POST_TRADE
        )
        return (
            mtf.format_from_sleeper_league(cap["payload"], captured_at=cap.get("capturedAt")),
            label,
            lfc.evidence_dict(cap, timing),
        )
    teams = league_row.get("total_rosters")
    partial = {
        "total_rosters": teams if isinstance(teams, int) else None,
        "season": league_row.get("season"),
        "settings": {"type": settings.get("type"), "best_ball": settings.get("bestBall")},
    }
    return (
        mtf.format_from_sleeper_league(partial),
        FORMAT_SOURCE_PARTIAL,
        lfc.evidence_dict(None, None),
    )


def load_format_captures(ledger_path: Path | None) -> tuple[dict[str, list[dict]], str]:
    """The dated league-format capture index, read through a ``mode=ro``
    connection (never migrating), plus a state label for lane status."""
    from src.sharp import league_format_capture as lfc  # noqa: PLC0415

    if ledger_path is None:
        try:
            from src.intel import ledger as intel_ledger  # noqa: PLC0415

            ledger_path = intel_ledger.default_path()
        except Exception:  # noqa: BLE001
            return {}, "ledger_path_unresolvable"
    p = Path(ledger_path)
    if not p.exists():
        return {}, "intel_ledger_missing"
    try:
        conn = sqlite3.connect(f"file:{p.as_posix()}?mode=ro", uri=True)
        try:
            index = lfc.load_capture_index(conn)
        finally:
            conn.close()
    except sqlite3.DatabaseError as exc:
        return {}, f"capture_table_unreadable:{exc}"
    return index, ("available" if index else "no_captures")


def sleeper_discovery_observations(
    *,
    ledger_path: Path | None = None,
    ctx: IdentityContext,
    captures: Mapping[str, list[dict[str, Any]]] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if ledger_path is None:
        try:
            from src.intel import ledger as intel_ledger  # noqa: PLC0415

            ledger_path = intel_ledger.default_path()
        except Exception as exc:  # noqa: BLE001
            return [], {"available": False, "reason": f"ledger_path_unresolvable:{exc}"}
    p = Path(ledger_path)
    if not p.exists():
        return [], {"available": False, "reason": "intel_ledger_missing"}
    try:
        conn = sqlite3.connect(f"file:{p.as_posix()}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            moves = [
                dict(r)
                for r in conn.execute(
                    "SELECT m.movement_id, m.tx_id, m.league_id, m.asset_id, m.asset_type, "
                    "m.action, m.roster_id, m.ts, t.created_ms, t.status "
                    "FROM asset_movements m LEFT JOIN transactions t ON t.tx_id = m.tx_id "
                    "WHERE m.tx_type = 'trade' ORDER BY m.league_id, m.tx_id, m.movement_id"
                ).fetchall()
            ]
            leagues = {
                str(r["league_id"]): dict(r)
                for r in conn.execute(
                    "SELECT league_id, season, total_rosters, settings_json FROM leagues"
                ).fetchall()
            }
            member_counts = {
                str(r[0]): int(r[1])
                for r in conn.execute(
                    "SELECT league_id, COUNT(*) FROM league_memberships GROUP BY league_id"
                ).fetchall()
            }
        finally:
            conn.close()
    except sqlite3.DatabaseError as exc:
        return [], {"available": False, "reason": f"intel_ledger_unreadable:{exc}"}
    capture_state = "provided"
    if captures is None:
        captures, capture_state = load_format_captures(p)

    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for m in moves:
        grouped.setdefault((str(m["league_id"]), str(m["tx_id"])), []).append(m)

    out: list[dict[str, Any]] = []
    format_sources: dict[str, int] = {}
    for (league_id, tx_id), group in grouped.items():
        lg = leagues.get(league_id) or {}
        try:
            settings = json.loads(lg.get("settings_json") or "{}")
        except (TypeError, ValueError):
            settings = {}
        created = group[0].get("created_ms")
        if created is None:
            created = group[0].get("ts")
        sides, caveats = _sides_from_movements(
            group, lambda m: _sleeper_asset(m["asset_id"], m["asset_type"], ctx)
        )
        caveats.append("sleeper_trade_faab_component_not_recorded")
        fmt, fmt_source, fmt_evidence = _sleeper_league_format(
            {**lg, "league_id": league_id},
            settings,
            captures=captures.get(league_id),
            trade_ms=int(created) if created is not None else None,
        )
        format_sources[fmt_source] = format_sources.get(fmt_source, 0) + 1
        out.append(
            {
                "observationId": f"{SOURCE_SLEEPER_DISCOVERY}:{league_id}:{tx_id}",
                "sourceFamily": SOURCE_SLEEPER_DISCOVERY,
                "sourceNativeId": tx_id,
                "payloadSha256": None,
                "revision": 1,
                "revisionCount": 1,
                "firstFetchedAt": None,
                "host": "sleeper",
                "hostLeagueId": league_id,
                "hostTxId": tx_id,
                "occurredDate": _ms_to_date(created),
                "occurredAtMs": int(created) if created is not None else None,
                "timeFidelity": "exact" if created is not None else "undated",
                "_format": fmt,
                "formatSource": fmt_source,
                "formatEvidence": fmt_evidence,
                "sampleProvenance": {
                    "lane": "sharp_discovery_graph",
                    "discovery": settings.get("discovery") if isinstance(settings, dict) else None,
                    "recordedMemberCount": member_counts.get(league_id),
                    "leagueSeason": lg.get("season"),
                },
                "sides": sides,
                "teamCount": len(sides),
                "sideSemantics": "received_per_roster",
                "vendorFlags": {},
                "provenance": [PROVENANCE_BY_SOURCE[SOURCE_SLEEPER_DISCOVERY]],
                "caveats": caveats,
            }
        )
    return out, {
        "available": True,
        "trades": len(out),
        "leagues": len({k[0] for k in grouped}),
        "formatCaptures": {
            "state": capture_state,
            "leaguesWithCapture": len(captures),
            "tradesByFormatSource": dict(sorted(format_sources.items())),
        },
    }


# ── Own-league lane (C4-MTL-01) ──────────────────────────────────────────


def _own_asset(asset_id: str, asset_kind: str, ctx: IdentityContext) -> dict[str, Any]:
    if asset_kind == "pick":
        lp = parse_league_pick_id(asset_id)
        if lp is None:
            return _pick_asset(
                None,
                vendor_ref=asset_id,
                label=asset_id,
                vendor_grade=None,
                reason="unparseable_league_pick_id",
            )
        return _pick_asset(
            MarketPickRef(year=lp.season, round_num=lp.round_num),
            vendor_ref=asset_id,
            label=asset_id,
            vendor_grade="generic",
            grade_note="league_pick_slot_not_carried",
        )
    sid = asset_id.split(":", 1)[1] if asset_id.startswith("player:") else asset_id
    return _player_asset(ctx.resolve_sleeper_id(sid), vendor_ref=asset_id, label=None, ctx=ctx)


def own_league_observations(
    *,
    league_keys: Iterable[str] | None = None,
    acquisition_path: Path | None = None,
    ctx: IdentityContext,
    allow_stale_scoring: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    from src.trade.market_trade_ledger import market_trades  # noqa: PLC0415

    if league_keys is None:
        try:
            from src.api.league_registry import active_leagues  # noqa: PLC0415

            league_keys = [lg.key for lg in active_leagues()]
        except Exception as exc:  # noqa: BLE001
            return [], {"available": False, "reason": f"registry_unreadable:{exc}"}
    if acquisition_path is None:
        from src.retention.evidence_store import RETENTION_DIR  # noqa: PLC0415

        if not (Path(RETENTION_DIR) / "acquisition.sqlite").exists():
            return [], {"available": False, "reason": "acquisition_store_missing"}
    out: list[dict[str, Any]] = []
    league_keys = list(league_keys)
    for key in league_keys:
        reg_fmt = mtf.format_from_registry(key, allow_stale_scoring=allow_stale_scoring)
        try:
            rows = market_trades(key, path=acquisition_path)
        except Exception as exc:  # noqa: BLE001
            return out, {"available": False, "reason": f"acquisition_unreadable:{exc}"}
        for t in rows:
            tx = str(t["sourceRef"]).removeprefix("tx:")
            sides = [
                [_own_asset(a["assetId"], a["assetKind"], ctx) for a in team["received"]]
                for _, team in sorted(t["teams"].items())
            ]
            out.append(
                {
                    "observationId": f"{SOURCE_OWN_LEAGUE}:{key}:{tx}",
                    "sourceFamily": SOURCE_OWN_LEAGUE,
                    "sourceNativeId": tx,
                    "payloadSha256": None,
                    "revision": 1,
                    "revisionCount": 1,
                    "firstFetchedAt": None,
                    "host": "sleeper",
                    "hostLeagueId": t.get("sleeperLeagueId"),
                    "hostTxId": tx,
                    "leagueKey": key,
                    "occurredDate": _ms_to_date(t.get("occurredAtMs")),
                    "occurredAtMs": t.get("occurredAtMs"),
                    "timeFidelity": "exact" if t.get("occurredAtMs") is not None else "undated",
                    "_format": reg_fmt,
                    "formatSource": "registry_and_scoring_card",
                    "sides": sides,
                    "teamCount": t.get("teamCount", len(sides)),
                    "sideSemantics": "received_per_roster",
                    "vendorFlags": {},
                    "provenance": [PROVENANCE_BY_SOURCE[SOURCE_OWN_LEAGUE]],
                    "caveats": ["sleeper_trade_faab_component_not_recorded"],
                }
            )
    return out, {"available": True, "trades": len(out), "leagues": list(league_keys)}


# ── All lanes ─────────────────────────────────────────────────────────────


def build_observations(
    *,
    archive_path: Path | None = None,
    intel_ledger_path: Path | None = None,
    acquisition_path: Path | None = None,
    league_keys: Iterable[str] | None = None,
    ctx: IdentityContext | None = None,
    lanes: Iterable[str] = (SOURCE_KTC, SOURCE_SLEEPER_DISCOVERY, SOURCE_OWN_LEAGUE),
    allow_stale_scoring: bool = False,
) -> dict[str, Any]:
    ctx = ctx if ctx is not None else IdentityContext.load_default()
    wanted = set(lanes)
    observations: list[dict[str, Any]] = []
    status: dict[str, Any] = {}
    if SOURCE_KTC in wanted:
        rows, st = ktc_observations(archive_path=archive_path, ctx=ctx)
        observations += rows
        status[SOURCE_KTC] = st
    captures: dict[str, list[dict[str, Any]]] = {}
    if SOURCE_SLEEPER_DISCOVERY in wanted or SOURCE_KTC in wanted:
        captures, _capture_state = load_format_captures(intel_ledger_path)
    if SOURCE_SLEEPER_DISCOVERY in wanted:
        rows, st = sleeper_discovery_observations(
            ledger_path=intel_ledger_path, ctx=ctx, captures=captures
        )
        observations += rows
        status[SOURCE_SLEEPER_DISCOVERY] = st
    if SOURCE_OWN_LEAGUE in wanted:
        rows, st = own_league_observations(
            league_keys=league_keys,
            acquisition_path=acquisition_path,
            ctx=ctx,
            allow_stale_scoring=allow_stale_scoring,
        )
        observations += rows
        status[SOURCE_OWN_LEAGUE] = st
    attach_host_formats(observations, captures=captures)
    for obs in observations:
        obs["marketFormat"] = obs["_format"].to_dict()
    return {
        "observations": observations,
        "lanes": status,
        "identityDirectory": ctx.directory_source,
    }


def _ktc_conservative_trade_ms(occurred_date: Any) -> int | None:
    """The EARLIEST instant a KTC day-dated trade can have happened.

    KTC dates are day granularity in an unstated timezone (the grouping layer
    allows one day either side), so a capture counts as in force for a KTC
    trade only if it precedes 00:00 UTC of the day BEFORE the stated date.
    """
    if not occurred_date:
        return None
    try:
        day = datetime.fromisoformat(str(occurred_date)[:10]).replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    return int((day - timedelta(days=1)).timestamp() * 1000)


def attach_host_formats(
    observations: list[dict[str, Any]],
    *,
    captures: Mapping[str, list[Mapping[str, Any]]] | None = None,
) -> int:
    """Give a vendor observation its HOST-captured format when one exists.

    A KTC row names its Sleeper league id; if the Sharp crawls captured that
    league's real roster slots and scoring card, those host facts are a
    stronger statement of format than the vendor's summary.  The Sharp lane's
    timing rule applies: a capture in force at the (conservative) trade date
    upgrades the row as ``host_capture_via_discovery``; a capture only from
    AFTER the trade upgrades it as ``sleeper_league_capture_post_trade``, never
    as exact-at-time.  The vendor format is kept beside it (``vendorFormat``).
    Returns how many were upgraded.

    ``captures`` is the dated capture index (``load_format_captures``); without
    one, the legacy capture snapshots the Sharp observations in this batch were
    built from are used.
    """
    from src.sharp import league_format_capture as lfc  # noqa: PLC0415

    index: dict[str, list[Mapping[str, Any]]] = {}
    if captures:
        index = {str(k): list(v) for k, v in captures.items()}
    else:
        for obs in observations:
            ev = obs.get("formatEvidence") or {}
            if obs["sourceFamily"] != SOURCE_SLEEPER_DISCOVERY or not ev.get("timing"):
                continue
            captured_ms = _parse_iso_ms(ev.get("capturedAt"))
            if captured_ms is None:
                continue
            index.setdefault(str(obs["hostLeagueId"]), []).append(
                {**ev, "capturedMs": captured_ms, "_format": obs["_format"]}
            )
    upgraded = 0
    for obs in observations:
        if obs["sourceFamily"] != SOURCE_KTC or not obs.get("hostLeagueId"):
            continue
        if obs.get("host") != "sleeper":
            continue
        cap, timing = lfc.capture_in_force(
            index.get(str(obs["hostLeagueId"])),
            _ktc_conservative_trade_ms(obs.get("occurredDate")),
        )
        if cap is None:
            continue
        if "_format" in cap:
            fmt = cap["_format"]
            evidence = {k: v for k, v in cap.items() if k not in ("_format", "capturedMs")}
            evidence["timing"] = timing
            evidence["exactAtTradeTime"] = timing == lfc.TIMING_AT_OR_BEFORE
        else:
            fmt = mtf.format_from_sleeper_league(cap["payload"], captured_at=cap.get("capturedAt"))
            evidence = lfc.evidence_dict(cap, timing)
        obs["vendorFormat"] = obs["_format"].to_dict()
        obs["_format"] = fmt
        obs["formatSource"] = (
            FORMAT_SOURCE_KTC_HOST_UPGRADE
            if timing == lfc.TIMING_AT_OR_BEFORE
            else FORMAT_SOURCE_CAPTURE_POST_TRADE
        )
        obs["formatEvidence"] = evidence
        upgraded += 1
    return upgraded


def _parse_iso_ms(value: Any) -> int | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def identity_summary(observations: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Resolution rate by source family and asset kind — counts only."""
    by_source: dict[str, dict[str, Any]] = {}
    for obs in observations:
        s = by_source.setdefault(
            obs["sourceFamily"],
            {"assets": 0, "resolved": 0, "byKind": {}, "byMethod": {}, "unresolvedReasons": {}},
        )
        for side in obs["sides"]:
            for a in side:
                s["assets"] += 1
                s["byKind"][a["kind"]] = s["byKind"].get(a["kind"], 0) + 1
                method = (a.get("resolution") or {}).get("method") or "none"
                s["byMethod"][method] = s["byMethod"].get(method, 0) + 1
                if a.get("canonicalId") or a["kind"] == KIND_FAAB:
                    s["resolved"] += 1
                else:
                    reason = (a.get("resolution") or {}).get("reason") or "unknown"
                    s["unresolvedReasons"][reason] = s["unresolvedReasons"].get(reason, 0) + 1
    for s in by_source.values():
        s["resolutionRate"] = round(s["resolved"] / s["assets"], 4) if s["assets"] else None
    return by_source
