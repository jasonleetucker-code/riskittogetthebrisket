"""RED-first as-of query tests for src.analyst.query (C6-ANA-01).

Mutation-verified (see docs/analyst/LEDGER_STORAGE.md for the log): the
future-leak tests were confirmed RED against a naive
``said_at``-only filter and against a ``datetime.min`` fallback before
being left in this passing state.
"""

from __future__ import annotations

import datetime as dt

import pytest

from src.analyst import claim as C
from src.analyst.stance import SourceLabel, Stance
from src.analyst.store import LedgerEntry, write_claims
from src.analyst.query import claims_as_of, independent_claims_as_of

NOW = dt.datetime(2026, 8, 1, 12, 0, tzinfo=dt.timezone.utc)


def _source(analyst="analyst:mattie", content="ep:101", platform="podcast"):
    return C.SourceRef(analyst_id=analyst, content_id=content, platform=platform)


def _claim(**kw):
    # discovered_at defaults to said_at ("discovered immediately") so
    # tests not specifically about the discovery-lag leak aren't tripped
    # up by the recorded_at fallback (real wall-clock time, which is far
    # after this fixture's NOW) — leak-focused tests override it
    # explicitly. Computed AFTER merging kwargs so it tracks whatever
    # said_at the caller passed, not a fixed constant.
    base = dict(
        source=_source(),
        asset_key="player:4034",
        stance=Stance.BUY,
        source_label=SourceLabel.BUY,
        take_type=C.TakeType.BUY_SELL_VALUE,
        said_at=NOW,
        provenance=C.Provenance.TRANSCRIPT_PARAPHRASE,
        game_type=C.GameType.DYNASTY,
    )
    base.update(kw)
    base.setdefault("discovered_at", base["said_at"])
    return C.AnalystClaim(**base)


class TestNeverFutureLeak:
    def test_a_claim_discovered_after_the_query_instant_does_not_appear(self, tmp_path):
        path = tmp_path / "q.sqlite"
        claim = _claim(
            said_at=NOW,
            discovered_at=NOW + dt.timedelta(days=9),  # discovered LATE
        )
        write_claims([LedgerEntry(claim=claim)], path=path)

        # Query instant is BEFORE discovery but AFTER said_at.
        result = claims_as_of("player:4034", NOW + dt.timedelta(days=3), path=path)
        assert result == []

    def test_the_same_claim_appears_once_discovery_has_passed(self, tmp_path):
        path = tmp_path / "q.sqlite"
        claim = _claim(said_at=NOW, discovered_at=NOW + dt.timedelta(days=9))
        write_claims([LedgerEntry(claim=claim)], path=path)

        result = claims_as_of("player:4034", NOW + dt.timedelta(days=10), path=path)
        assert len(result) == 1

    def test_no_discovered_at_falls_back_to_ledger_recorded_at_never_leaks(self, tmp_path):
        path = tmp_path / "q.sqlite"
        claim = _claim(said_at=NOW, discovered_at=None)
        # write_claims stamps recorded_at = "now" (real wall-clock, which
        # is far after NOW=2026-08-01 in this fixture) — the ledger
        # itself did not exist yet on 2026-08-01, so a claim ingested
        # today must not be visible when queried as-of that historical
        # date, even though discovered_at was never populated.
        write_claims([LedgerEntry(claim=claim)], path=path)

        result = claims_as_of("player:4034", NOW, path=path)
        assert result == [], (
            "a claim with no discovered_at leaked backward to said_at — "
            "the recorded_at fallback did not fire"
        )

    def test_said_at_alone_is_not_sufficient_a_future_discovery_still_blocks(self, tmp_path):
        """Guards against a regression to a said_at-only filter — a claim
        whose said_at is comfortably in the past but whose discovered_at
        is in the future relative to the query must still be excluded."""
        path = tmp_path / "q.sqlite"
        claim = _claim(
            said_at=NOW - dt.timedelta(days=100),
            discovered_at=NOW + dt.timedelta(days=1),
        )
        write_claims([LedgerEntry(claim=claim)], path=path)
        result = claims_as_of("player:4034", NOW, path=path)
        assert result == []

    def test_naive_instant_is_refused(self, tmp_path):
        path = tmp_path / "q.sqlite"
        with pytest.raises(ValueError, match="timezone-aware"):
            claims_as_of("player:4034", dt.datetime(2026, 8, 1), path=path)


class TestSupersessionAsOf:
    def test_a_not_yet_visible_correction_does_not_hide_the_original(self, tmp_path):
        """A retraction said/discovered AFTER the query instant must not
        retroactively hide the original — as of that instant, we did not
        know about the retraction yet."""
        path = tmp_path / "q.sqlite"
        original = _claim(source=_source(content="ep:1"), said_at=NOW)
        correction = _claim(
            source=_source(content="ep:2"),
            said_at=NOW + dt.timedelta(days=5),
            stance=Stance.SELL,
            source_label=SourceLabel.SELL,
            supersedes="ep:1",
        )
        write_claims([LedgerEntry(claim=original), LedgerEntry(claim=correction)], path=path)

        # As of a date BEFORE the correction — original is still visible.
        early = claims_as_of("player:4034", NOW + dt.timedelta(days=1), path=path)
        assert len(early) == 1
        assert early[0].claim.stance is Stance.BUY

        # As of a date AFTER the correction — original is superseded.
        late = claims_as_of("player:4034", NOW + dt.timedelta(days=10), path=path)
        assert len(late) == 1
        assert late[0].claim.stance is Stance.SELL

    def test_include_superseded_returns_both(self, tmp_path):
        path = tmp_path / "q.sqlite"
        original = _claim(source=_source(content="ep:1"), said_at=NOW)
        correction = _claim(
            source=_source(content="ep:2"),
            said_at=NOW + dt.timedelta(days=5),
            supersedes="ep:1",
        )
        write_claims([LedgerEntry(claim=original), LedgerEntry(claim=correction)], path=path)
        result = claims_as_of(
            "player:4034", NOW + dt.timedelta(days=10), include_superseded=True, path=path
        )
        assert len(result) == 2


class TestIndependenceReuse:
    def test_repeated_takes_from_the_same_analyst_thesis_collapse(self, tmp_path):
        """Reuses claim.independent_claims() -- not re-derived here."""
        path = tmp_path / "q.sqlite"
        first = _claim(source=_source(content="ep:1"), said_at=NOW)
        again = _claim(
            source=_source(content="ep:2"),
            said_at=NOW + dt.timedelta(days=7),
        )
        write_claims([LedgerEntry(claim=first), LedgerEntry(claim=again)], path=path)

        raw = claims_as_of("player:4034", NOW + dt.timedelta(days=10), path=path)
        assert len(raw) == 2  # both stored, both individually visible

        independent = independent_claims_as_of(
            "player:4034", NOW + dt.timedelta(days=10), path=path
        )
        assert len(independent) == 1  # collapsed to one thesis vote

    def test_same_take_syndicated_across_platforms_collapses(self, tmp_path):
        """thesis_key deliberately ignores platform/content_id (§4.20) —
        this is claim.py's existing behavior, pinned here as a query-path
        integration test, not new logic."""
        path = tmp_path / "q.sqlite"
        podcast = _claim(
            source=C.SourceRef(analyst_id="analyst:mattie", content_id="ep:1", platform="podcast"),
            said_at=NOW,
        )
        youtube_cut = _claim(
            source=C.SourceRef(analyst_id="analyst:mattie", content_id="yt:1", platform="youtube"),
            said_at=NOW + dt.timedelta(hours=2),
        )
        write_claims(
            [LedgerEntry(claim=podcast), LedgerEntry(claim=youtube_cut)], path=path
        )
        independent = independent_claims_as_of(
            "player:4034", NOW + dt.timedelta(days=1), path=path
        )
        assert len(independent) == 1


class TestUnknownFieldsRoundTrip:
    def test_unknown_game_type_and_unset_horizon_are_not_coerced(self, tmp_path):
        path = tmp_path / "q.sqlite"
        claim = _claim(game_type=C.GameType.UNKNOWN, asset_side=C.AssetSide.UNKNOWN)
        write_claims([LedgerEntry(claim=claim)], path=path)
        result = claims_as_of("player:4034", NOW + dt.timedelta(days=1), path=path)
        assert result[0].claim.game_type is C.GameType.UNKNOWN
        assert result[0].claim.asset_side is C.AssetSide.UNKNOWN
        # UNKNOWN game type must never read as dynasty evidence.
        assert result[0].claim.is_dynasty_evidence is False
