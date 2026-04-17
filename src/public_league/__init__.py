"""Public league experience — isolated pipeline for the /league page.

This package is deliberately fork-isolated from the private canonical
valuation pipeline (``src/canonical``), the private API data contract
(``src/api/data_contract.py``), and the private trade engines
(``src/trade``).

Nothing in here may:
    * read from ``latest_data`` / ``latest_contract_data``
    * import private rank / value / edge signals
    * expose raw "our value" internals, trade finder output, league
      edge maps, private team-comparison data, or source-override state

The public contract is assembled from the Sleeper API (public
endpoints) only.  Each section module is responsible for producing a
single JSON-safe block of the public contract.  ``public_contract``
assembles them and applies a field allowlist before the payload
leaves the backend.

Section modules:
    history        — League History / Hall of Fame
    rivalries      — Rivalries
    awards         — Awards
    records        — Records
    franchise      — Franchise Pages
    activity       — Trade Activity Center
    draft          — Draft Center
    weekly         — Weekly Recap
    superlatives   — League Superlatives
    archives       — Public searchable archives / databases

Infrastructure modules:
    identity        — Owner-id-keyed manager identity + team aliases
    sleeper_client  — Thin Sleeper HTTP client with graceful fallbacks
    snapshot        — Snapshot pipeline — pulls the current + previous
                      dynasty seasons and hands a normalized shape to
                      every section module
    public_contract — Public API contract wrapper + safety allowlist
"""
from __future__ import annotations

from .public_contract import (
    PUBLIC_CONTRACT_VERSION,
    PUBLIC_SECTION_KEYS,
    build_public_contract,
    build_section_payload,
    assert_public_payload_safe,
)
from .snapshot import PublicLeagueSnapshot, build_public_snapshot

__all__ = [
    "PUBLIC_CONTRACT_VERSION",
    "PUBLIC_SECTION_KEYS",
    "PublicLeagueSnapshot",
    "assert_public_payload_safe",
    "build_public_contract",
    "build_public_snapshot",
    "build_section_payload",
]
