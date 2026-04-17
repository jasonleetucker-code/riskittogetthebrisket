"""Public API contract for the /league experience.

This module assembles a PublicLeagueSnapshot into the public-safe
payload served to ``/api/public/league*`` routes, and enforces a
hard field-name blocklist that rejects any leak of private
internals.

The test suite pins this shape — adding a new field here requires
updating ``tests/public_league/test_public_contract.py`` as well.
"""
from __future__ import annotations

from typing import Any, Callable

from . import (
    activity,
    archives,
    awards,
    draft,
    franchise,
    history,
    records,
    rivalries,
    superlatives,
    weekly,
)
from .snapshot import PublicLeagueSnapshot

PUBLIC_CONTRACT_VERSION = "public-league/2026-04-17.v1"


# Sections exposed by the public contract.  Each entry maps the public
# contract key to its section builder.  The order is the order each
# endpoint walks when assembling the aggregate payload.
_SECTION_BUILDERS: dict[str, Callable[[PublicLeagueSnapshot], dict[str, Any]]] = {
    "history": history.build_section,
    "rivalries": rivalries.build_section,
    "awards": awards.build_section,
    "records": records.build_section,
    "franchise": franchise.build_section,
    "activity": activity.build_section,
    "draft": draft.build_section,
    "weekly": weekly.build_section,
    "superlatives": superlatives.build_section,
    "archives": archives.build_section,
}

PUBLIC_SECTION_KEYS: tuple[str, ...] = tuple(_SECTION_BUILDERS.keys())


# Field name blocklist.  These substrings MUST NOT appear as dict keys
# anywhere in a public payload.  The assertion runs recursively over
# the payload before it leaves the backend.
#
# This list is conservative on purpose — the point is to refuse to
# ship anything resembling private internals, even if a future edit
# accidentally imports a private helper.
_PRIVATE_FIELD_BLOCKLIST: frozenset[str] = frozenset(
    key.lower()
    for key in (
        # Private rank / value internals
        "ourValue",
        "our_value",
        "canonicalSiteValues",
        "canonical_site_values",
        "canonicalConsensusRank",
        "rankDerivedValue",
        "sourceRanks",
        "sourceRankMeta",
        "sourceAudit",
        "siteValues",
        "site_values",
        "siteWeights",
        "site_weights",
        "siteOverrides",
        "rankingsOverride",
        "rankings_override",
        "tepMultiplier",
        "tep_multiplier",

        # Private edge / trade internals
        "edge",
        "edgeSignals",
        "edge_signals",
        "edgeScore",
        "tradeFinder",
        "trade_finder",
        "tradeTargets",
        "trade_targets",
        "tradeSuggestions",
        "trade_suggestions",
        "leagueEdgeMap",
        "league_edge_map",
        "teamComparison",
        "team_comparison",
        "finderOutput",
        "finder_output",
        "marketGapDirection",
        "marketGapMagnitude",
        "confidenceBucket",
        "anomalyFlags",
        "waiverGems",
        "waiver_gems",
        "arbitrageScore",
        "arbitrage_score",

        # Scraper / pipeline internals
        "rawSources",
        "raw_sources",
        "sourceHealth",
        "source_health",
        "pickAliases",
        "pick_aliases",
    )
)


def assert_public_payload_safe(payload: Any, path: str = "$") -> None:
    """Raise ``AssertionError`` if any blocked field name appears anywhere
    in ``payload``.  Checks dict keys at every depth.
    """
    if isinstance(payload, dict):
        for key, value in payload.items():
            if not isinstance(key, str):
                continue
            if key.lower() in _PRIVATE_FIELD_BLOCKLIST:
                raise AssertionError(
                    f"Public payload contains blocked field {key!r} at {path}"
                )
            assert_public_payload_safe(value, f"{path}.{key}")
    elif isinstance(payload, (list, tuple)):
        for i, item in enumerate(payload):
            assert_public_payload_safe(item, f"{path}[{i}]")


def _league_header(snapshot: PublicLeagueSnapshot) -> dict[str, Any]:
    current = snapshot.current_season
    name = ""
    if current is not None:
        name = str(current.league.get("name") or "")
    return {
        "rootLeagueId": snapshot.root_league_id,
        "leagueName": name,
        "seasonsCovered": snapshot.season_ids,
        "leagueIds": snapshot.league_ids,
        "currentLeagueId": current.league_id if current else "",
        "generatedAt": snapshot.generated_at,
        "managers": snapshot.managers.to_public_list(),
    }


def build_section_payload(snapshot: PublicLeagueSnapshot, section: str) -> dict[str, Any]:
    """Build a single public-section payload, wrapped in the standard header.

    Raises ``KeyError`` if ``section`` is unknown.
    """
    if section not in _SECTION_BUILDERS:
        raise KeyError(f"Unknown public-league section: {section!r}")
    header = _league_header(snapshot)
    section_body = _SECTION_BUILDERS[section](snapshot)
    payload = {
        "contractVersion": PUBLIC_CONTRACT_VERSION,
        "league": header,
        "section": section,
        "data": section_body,
    }
    assert_public_payload_safe(payload)
    return payload


def build_public_contract(snapshot: PublicLeagueSnapshot) -> dict[str, Any]:
    """Assemble the full public contract: every section + header."""
    header = _league_header(snapshot)
    sections: dict[str, Any] = {}
    for key, builder in _SECTION_BUILDERS.items():
        sections[key] = builder(snapshot)
    payload = {
        "contractVersion": PUBLIC_CONTRACT_VERSION,
        "league": header,
        "sections": sections,
        "sectionKeys": list(PUBLIC_SECTION_KEYS),
    }
    assert_public_payload_safe(payload)
    return payload
