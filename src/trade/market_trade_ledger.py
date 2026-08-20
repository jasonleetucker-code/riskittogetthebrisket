"""The Market Trade Ledger — C4-MTL-01, own-league lane.

WHAT THIS IS, AND WHAT IT DELIBERATELY IS NOT YET
───────────────────────────────────────────────────
``docs/MARKET_TRADE_LEDGER_ACTIONABILITY_SPEC.md`` describes a ledger of
recent REAL dynasty trades across the wider market, format-aware, used as
evidence for comps, liquidity and package construction. The broad
cross-league population that spec ultimately wants comes from external
sources (KTC's trade database, or an equivalent), and that lane is
``C4-MTL-02`` — explicitly gated on a captured third-party permission
grant (``F-EXT-01``) that does not exist in this repository yet. This
module does not attempt that.

What it DOES build, and what is dependency-ready today, is the same
normalized-ledger SHAPE the spec calls for, seeded from the one source
already fully within reach and already licensed by construction: our own
leagues' own completed trades, as recorded in the canonical acquisition
ledger (``src.acquisition``, C1-ACQ-01 / C1-U8). Every field the spec's
§3 schema asks for that a Sleeper-sourced trade can actually answer is
populated; nothing is fabricated to fill the rest. When ``C4-MTL-02``
lands, its rows join this same shape rather than inventing a second one.

WHY THIS DOES NOT RE-VALUE THE ASSETS
───────────────────────────────────────
Per §3, "raw real trades must not directly overwrite canonical dynasty
value merely because they occurred." This module is a NORMALIZER, not a
valuation engine — it names which assets moved, when, and under what
league format, and stops there. It never computes, blends, or votes a
canonical value from the trade; that decision belongs entirely to
``src.api.data_contract`` (unchanged by this module) and, later, to a
deliberately-scoped comps engine (``C4-MTL-03``).

DEDUP, TRUTHFULLY SCOPED
─────────────────────────
The spec asks for "cross-source dedup with unresolved-stays-unresolved."
With exactly one source lane (our own Sleeper-derived acquisition
ledger), the acquisition store's own primary key
(``league_key, source_ref, asset_id``) already makes re-ingestion
idempotent, so there is nothing to dedup YET — a single source cannot
collide with itself. Cross-source dedup is a real, unsolved problem only
once a second source lane exists (``C4-MTL-02``), and is deliberately
NOT claimed here rather than half-built against a source that isn't
there to test against.

WHY THIS IS A DELIBERATE, NAMED EXCEPTION TO "NOTHING READS ACQUISITION"
──────────────────────────────────────────────────────────────────────
See ``src/trade/waiver_ledger.py`` for the same rationale, restated
here because this module makes the identical claim: it is a pure
historical PROJECTION, never reaching ``rankDerivedValue`` or any
canonical value, so it does not create the circularity
``tests/acquisition/test_board_inertness.py`` guards against. That test
names this file as an authorized exception alongside the waiver ledger.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.acquisition.store import read_events
from src.trade.faab_comparability import TargetFormat

TRADE = "TRADE"
TRADE_AWAY = "TRADE_AWAY"
_TRADE_EVENT_TYPES = (TRADE, TRADE_AWAY)

def _asset_ref(ev: dict[str, Any]) -> dict[str, Any]:
    return {"assetId": ev["asset_id"], "assetKind": ev["asset_kind"]}


def _format_metadata(league_key: str) -> dict[str, Any]:
    """Structured format metadata for the league, via the one existing
    canonical format reader (``TargetFormat``) rather than a second
    scoring-card parser invented for this ledger."""
    fmt = TargetFormat.from_registry(league_key)
    return {
        "teams": fmt.teams,
        "superflex": fmt.superflex,
        "tep": fmt.tep,
        "tepLevel": fmt.tep_level,
        "is2Te": fmt.is_2te,
        "idp": fmt.idp,
    }


def market_trades(league_key: str, *, path: Path | None = None) -> list[dict[str, Any]]:
    """One row per completed trade, oldest first, with both sides intact.

    A trade can involve more than two teams. Rather than force every trade
    into an A/B pair (which loses the third team's assets or fabricates a
    two-party fiction), each row carries ``teams``: a mapping of
    participating roster id -> what that team received and what it sent.
    That is exactly the shape ``src.acquisition.events`` already recorded
    per asset movement — this module only groups it by transaction and
    inverts it into a per-team view.
    """
    events = read_events(league_key, path=path)
    groups: dict[str, list[dict[str, Any]]] = {}
    for ev in events:
        if ev["event_type"] not in _TRADE_EVENT_TYPES:
            continue
        groups.setdefault(ev["source_ref"], []).append(ev)

    format_meta = _format_metadata(league_key)

    trades: list[dict[str, Any]] = []
    for source_ref, group in groups.items():
        teams: dict[int, dict[str, list[dict[str, Any]]]] = {}

        def _side(rid: Any) -> dict[str, list[dict[str, Any]]]:
            if rid is None:
                return {}
            return teams.setdefault(int(rid), {"received": [], "sent": []})

        for e in group:
            asset = _asset_ref(e)
            recv = _side(e["after_owner_rid"])
            if recv:
                recv["received"].append(asset)
            sent = _side(e["before_owner_rid"])
            if sent:
                sent["sent"].append(asset)

        primary = group[0]
        trades.append(
            {
                "leagueKey": league_key,
                "sourceRef": source_ref,
                "season": primary["season"],
                "week": primary["week"],
                "occurredAtMs": primary["occurred_at_ms"],
                "timeFidelity": primary["time_fidelity"],
                "assetCount": len(group),
                "teamCount": len(teams),
                "teams": {str(rid): sides for rid, sides in sorted(teams.items())},
                "format": format_meta,
                "sourceFamily": "own_league_sleeper",
                "dynastyVerified": True,
            }
        )

    trades.sort(
        key=lambda t: (
            t["occurredAtMs"] is not None,
            t["occurredAtMs"] or 0,
            t["sourceRef"],
        )
    )
    return trades


def market_ledger_summary(league_key: str, *, path: Path | None = None) -> dict[str, Any]:
    """Counts and stamps only — never per-trade contents.

    Mirrors ``src.acquisition.store.coverage`` and
    ``src.trade.waiver_ledger.waiver_ledger_summary``'s posture.
    """
    trades = market_trades(league_key, path=path)
    dated_ms = [t["occurredAtMs"] for t in trades if t["occurredAtMs"] is not None]
    multi_team = [t for t in trades if t["teamCount"] > 2]

    return {
        "leagueKey": league_key,
        "totalTrades": len(trades),
        "twoTeamTrades": len(trades) - len(multi_team),
        "multiTeamTrades": len(multi_team),
        "undatedTrades": len(trades) - len(dated_ms),
        "oldestOccurredAtMs": min(dated_ms) if dated_ms else None,
        "newestOccurredAtMs": max(dated_ms) if dated_ms else None,
        "sourceFamilies": ["own_league_sleeper"],
    }
