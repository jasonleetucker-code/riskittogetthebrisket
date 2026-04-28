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
    luck,
    matchup_preview,
    overview,
    playoff_odds,
    power,
    records,
    rivalries,
    streaks,
    superlatives,
    weekly,
    weekly_recap,
)
from .snapshot import PublicLeagueSnapshot

PUBLIC_CONTRACT_VERSION = "public-league/2026-04-18.v1"


# Sections exposed by the public contract.  Each entry maps the public
# contract key to its section builder.  The order is the order each
# endpoint walks when assembling the aggregate payload.
#
# ``overview`` is special — it's composed from the already-built
# sections, so we don't place it in the straight builder dict.  The
# assemble function below runs overview last.
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
    "luck": luck.build_section,
    "streaks": streaks.build_section,
    "power": power.build_section,
    "matchupPreview": matchup_preview.build_section,
    "weeklyRecap": weekly_recap.build_section,
}

# Sections that are expensive enough to warrant lazy-loading — they are
# *not* included in aggregate ``build_public_contract()`` responses but
# remain addressable through ``/api/public/league/<section>`` so the
# specific tab that needs them can fetch on-demand.  ``playoffOdds``
# runs a 10,000-sim Monte Carlo; including it in the aggregate path
# would impose that cost on every landing-page load.
#
# ``rosTeamStrength`` reads a cached file written by the ROS engine's
# scheduled scrape — cheap to assemble but kept lazy so the existing
# /league landing-page payload stays unchanged in shape (the ROS
# layer is opt-in until it's been validated against real rosters).
from src.ros import api as _ros_api  # noqa: E402

_LAZY_SECTION_BUILDERS: dict[str, Callable[[PublicLeagueSnapshot], dict[str, Any]]] = {
    "playoffOdds": playoff_odds.build_section,
    "rosTeamStrength": _ros_api.build_section,
}

# Derived overview is a first-class section key the UI can fetch just
# like any other, but it composes over the other builders instead of
# walking the snapshot directly.
OVERVIEW_SECTION = "overview"

PUBLIC_SECTION_KEYS: tuple[str, ...] = (
    (OVERVIEW_SECTION,)
    + tuple(_SECTION_BUILDERS.keys())
    + tuple(_LAZY_SECTION_BUILDERS.keys())
)

# Subset of ``PUBLIC_SECTION_KEYS`` that have matching CSV exporters
# in ``src/public_league/csv_export.py::export_section``.  The CSV
# route handler gates on THIS tuple, not ``PUBLIC_SECTION_KEYS``,
# because lazy-only sections (playoffOdds) don't have CSV exporters
# — advertising them through the CSV allowlist would pass the route
# check and then raise KeyError inside ``export_section``, returning
# 503 for a section the API appears to advertise as valid.  Per
# Codex PR #215 round 4.
PUBLIC_CSV_EXPORTABLE_KEYS: tuple[str, ...] = (
    (OVERVIEW_SECTION,) + tuple(_SECTION_BUILDERS.keys())
)


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


def _build_overview(snapshot: PublicLeagueSnapshot, sections: dict[str, Any]) -> dict[str, Any]:
    return overview.build_section(
        snapshot,
        history_section=sections.get("history") or {},
        rivalries_section=sections.get("rivalries") or {},
        records_section=sections.get("records") or {},
        awards_section=sections.get("awards") or {},
        activity_section=sections.get("activity") or {},
        draft_section=sections.get("draft") or {},
        weekly_section=sections.get("weekly") or {},
        luck_section=sections.get("luck") or {},
        streaks_section=sections.get("streaks") or {},
        power_section=sections.get("power") or {},
        matchup_preview_section=sections.get("matchupPreview") or {},
        weekly_recap_section=sections.get("weeklyRecap") or {},
    )


def _build_activity_section(
    snapshot: PublicLeagueSnapshot,
    activity_valuation: Callable[[dict[str, Any]], float] | None,
) -> dict[str, Any]:
    if activity_valuation is None:
        return activity.build_section(snapshot)
    return activity.build_section(snapshot, valuation=activity_valuation)


def build_section_payload(
    snapshot: PublicLeagueSnapshot,
    section: str,
    *,
    activity_valuation: Callable[[dict[str, Any]], float] | None = None,
) -> dict[str, Any]:
    """Build a single public-section payload, wrapped in the standard header.

    ``activity_valuation`` (optional) enables server-side trade-grade
    computation on the activity feed.  When supplied it must be a
    callable that takes a received-asset dict and returns a numeric
    value; only the derived grade letter/label is emitted — raw
    values never leave the backend.

    Raises ``KeyError`` if ``section`` is unknown.
    """
    if section == OVERVIEW_SECTION:
        sections: dict[str, Any] = {}
        for key, builder in _SECTION_BUILDERS.items():
            if key == "activity":
                sections[key] = _build_activity_section(snapshot, activity_valuation)
            else:
                sections[key] = builder(snapshot)
        section_body = _build_overview(snapshot, sections)
    elif section == "activity":
        section_body = _build_activity_section(snapshot, activity_valuation)
    elif section in _SECTION_BUILDERS:
        section_body = _SECTION_BUILDERS[section](snapshot)
    elif section in _LAZY_SECTION_BUILDERS:
        # Lazy section builders (e.g. playoffOdds) run on-demand via
        # ``/api/public/league/<section>`` but are deliberately excluded
        # from the aggregate overview walk above to avoid imposing their
        # compute cost on every public-contract request.
        section_body = _LAZY_SECTION_BUILDERS[section](snapshot)
    else:
        raise KeyError(f"Unknown public-league section: {section!r}")
    header = _league_header(snapshot)
    payload = {
        "contractVersion": PUBLIC_CONTRACT_VERSION,
        "league": header,
        "section": section,
        "data": section_body,
    }
    assert_public_payload_safe(payload)
    return payload


def build_public_contract(
    snapshot: PublicLeagueSnapshot,
    *,
    activity_valuation: Callable[[dict[str, Any]], float] | None = None,
) -> dict[str, Any]:
    """Assemble the full public contract: every section + header.

    See ``build_section_payload`` for the ``activity_valuation`` arg.
    """
    header = _league_header(snapshot)
    sections: dict[str, Any] = {}
    for key, builder in _SECTION_BUILDERS.items():
        if key == "activity":
            sections[key] = _build_activity_section(snapshot, activity_valuation)
        else:
            sections[key] = builder(snapshot)
    sections[OVERVIEW_SECTION] = _build_overview(snapshot, sections)
    payload = {
        "contractVersion": PUBLIC_CONTRACT_VERSION,
        "league": header,
        "sections": sections,
        "sectionKeys": list(PUBLIC_SECTION_KEYS),
    }
    assert_public_payload_safe(payload)
    return payload
