"""Source participation: no source can silently stop voting.

Owner directive 2026-09-24 (B22): a registered, applicable, healthy dynasty
source with a valid observation for a player must appear in that player's
model-source contributions — and when it does not vote, the row must say WHY.
This protects against the failure mode where a source is scraped and stored
for months while contributing nothing to the value.

Built from the newest COMPLETE archived scrape
(``tests/archive_fixtures.newest_complete_raw_payload``), never the live board,
so it is deterministic in the hard gate.  Each assertion is an invariant over
every row — no counts, no floors.
"""

from __future__ import annotations

from collections import Counter

import pytest

from src.api import data_contract as dc
from src.sources.ktc_market import KTC_MARKET_KEY
from tests.archive_fixtures import newest_complete_raw_payload

REGISTERED = {s["key"] for s in dc._RANKING_SOURCES}


@pytest.fixture(scope="module")
def rows() -> list[dict]:
    raw, name = newest_complete_raw_payload()
    if raw is None:
        pytest.skip("no complete archived scrape available")
    return dc.build_api_data_contract(raw)["playersArray"]


def _disposition(row: dict, key: str, meta: dict) -> str:
    """Exactly one named outcome per observation."""
    if meta.get("hampelDropped"):
        return "hampel_outlier"
    if meta.get("supersededBy"):
        return "family_superseded"
    if (
        key in set(row.get("freshnessExcludedSources") or [])
        or not float(meta.get("appliedWeight") or 0.0) > 0.0
    ):
        return "zero_effective_weight"
    return "voted"


def test_every_matched_registered_source_reaches_the_row(rows):
    """A source the matcher found for a row is carried into its ranks."""
    lost = []
    for row in rows:
        matched = set((row.get("sourceAudit") or {}).get("matchedSources") or []) & REGISTERED
        missing = matched - set(row.get("sourceRanks") or {})
        if missing:
            lost.append((row["canonicalName"], sorted(missing)))
    assert not lost, f"matched sources dropped before the blend: {lost[:10]}"


def test_every_priced_row_explains_every_source(rows):
    """``sourceRanks`` without ``sourceRankMeta`` is a price nobody can explain.

    Off-cap player rows (#1101) used to publish a value with an empty meta —
    AJ Dillon priced by seven sources, none of them visible.
    """
    unexplained = []
    for row in rows:
        if row.get("assetClass") == "pick" or not (row.get("rankDerivedValue") or 0) > 0:
            continue
        missing = set(row.get("sourceRanks") or {}) - set(row.get("sourceRankMeta") or {})
        if missing:
            unexplained.append((row["canonicalName"], sorted(missing)))
    assert not unexplained, f"priced rows with unexplained sources: {unexplained[:10]}"


def test_a_voting_observation_contributes_a_value(rows):
    """``voted`` means a contribution exists and nothing marked it non-contributing."""
    bad = []
    for row in rows:
        for key, meta in (row.get("sourceRankMeta") or {}).items():
            if _disposition(row, key, meta) != "voted":
                continue
            if meta.get("contributedToBlend") is False or meta.get("valueContribution") is None:
                bad.append((row["canonicalName"], key))
    assert not bad, f"voting observations without a contribution: {bad[:10]}"


def test_a_non_voting_observation_names_its_reason(rows):
    """Superseded rows name the family head that out-voted them."""
    bad = []
    for row in rows:
        for key, meta in (row.get("sourceRankMeta") or {}).items():
            if _disposition(row, key, meta) == "family_superseded":
                head = meta["supersededBy"]
                if dc.correlation_group_for(head) != dc.correlation_group_for(key):
                    bad.append((row["canonicalName"], key, head))
    assert not bad, f"superseded by a source outside the family: {bad[:10]}"


def test_one_vote_per_correlation_family(rows):
    """KTC Crowd + Fantasy Navigator, the four DLF boards, FantasyPros +
    Fitzmaurice, Flock + Flock rookies: each family casts at most one vote."""
    doubled = []
    for row in rows:
        voters = [
            k
            for k, m in (row.get("sourceRankMeta") or {}).items()
            if _disposition(row, k, m) == "voted"
        ]
        counts = Counter(dc.correlation_group_for(k) for k in voters)
        extra = {g: n for g, n in counts.items() if n > 1}
        if extra:
            doubled.append((row["canonicalName"], extra))
    assert not doubled, f"families voting more than once: {doubled[:10]}"


def test_dlf_rookie_board_never_votes_beside_the_regular_board(rows):
    """A rookie on both DLF boards gets ONE DLF vote — the regular board's."""
    for row in rows:
        meta = row.get("sourceRankMeta") or {}
        for regular, rookie in (("dlfSf", "dlfRookieSf"), ("dlfIdp", "dlfRookieIdp")):
            if regular in meta and rookie in meta:
                assert _disposition(row, rookie, meta[rookie]) != "voted" or (
                    _disposition(row, regular, meta[regular]) != "voted"
                ), f"{row['canonicalName']}: {regular} and {rookie} both voted"


def test_ktc_market_is_never_an_observation(rows):
    """The benchmark is published beside the model, never inside it."""
    leaked = [
        row["canonicalName"]
        for row in rows
        if KTC_MARKET_KEY in (row.get("sourceRanks") or {})
        or KTC_MARKET_KEY in (row.get("sourceRankMeta") or {})
    ]
    assert not leaked, f"KTC Market reached the blend on: {leaked[:10]}"
