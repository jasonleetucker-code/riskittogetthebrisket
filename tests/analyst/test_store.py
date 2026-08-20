"""Persistence tests for src.analyst.store (C6-ANA-01).

Follows the fixture style of tests/analyst/test_claim.py.  Every test
uses its own tmp_path SQLite file — no shared/global ledger state.
"""

from __future__ import annotations

import datetime as dt

import pytest

from src.analyst import claim as C
from src.analyst.stance import SourceLabel, Stance
from src.analyst.store import (
    ExtractionConfidence,
    LedgerEntry,
    all_claims,
    claim_content_hash,
    claim_identity_key,
    claims_for_asset,
    write_claims,
)

NOW = dt.datetime(2026, 8, 18, 12, 0, tzinfo=dt.timezone.utc)


def _source(analyst="analyst:mattie", content="ep:101", platform="podcast"):
    return C.SourceRef(analyst_id=analyst, content_id=content, platform=platform)


def _claim(**kw):
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
    return C.AnalystClaim(**base)


def _entry(**kw) -> LedgerEntry:
    claim_kwargs = {k: v for k, v in kw.items() if k not in ("extraction_confidence", "parser_version")}
    envelope_kwargs = {k: v for k, v in kw.items() if k in ("extraction_confidence", "parser_version")}
    return LedgerEntry(claim=_claim(**claim_kwargs), **envelope_kwargs)


class TestIdentityRoundTrip:
    def test_write_then_read_reproduces_the_claim_exactly(self, tmp_path):
        path = tmp_path / "ledger.sqlite"
        entry = _entry()
        write_claims([entry], path=path)
        fetched = claims_for_asset("player:4034", path=path)
        assert len(fetched) == 1
        assert fetched[0].claim == entry.claim

    def test_default_extraction_confidence_is_unknown_never_a_number(self, tmp_path):
        path = tmp_path / "ledger.sqlite"
        write_claims([_entry()], path=path)
        fetched = claims_for_asset("player:4034", path=path)
        assert fetched[0].extraction_confidence is ExtractionConfidence.UNKNOWN

    def test_recorded_at_is_stamped_by_the_store_not_the_caller(self, tmp_path):
        path = tmp_path / "ledger.sqlite"
        # LedgerEntry constructed with no recorded_at — the store must
        # stamp one on write; a caller cannot pre-set it via write_claims.
        entry = LedgerEntry(claim=_claim(), recorded_at=None)
        write_claims([entry], path=path)
        fetched = claims_for_asset("player:4034", path=path)
        assert fetched[0].recorded_at is not None


class TestDuplicateVsConflict:
    def test_same_claim_ingested_twice_is_unchanged_not_two_rows(self, tmp_path):
        path = tmp_path / "ledger.sqlite"
        entry = _entry()
        write_claims([entry], path=path)
        result = write_claims([entry], path=path)
        assert result == {"inserted": 0, "unchanged": 1, "conflicts": [], "offered": 1}
        assert len(claims_for_asset("player:4034", path=path)) == 1

    def test_reingesting_with_a_different_stance_is_a_conflict_never_applied(self, tmp_path):
        path = tmp_path / "ledger.sqlite"
        original = _entry(stance=Stance.BUY, source_label=SourceLabel.BUY)
        write_claims([original], path=path)

        # Same utterance (same analyst/content/platform/asset/said_at) —
        # different stance, e.g. a re-run of a fixed extractor.
        reparsed = _entry(stance=Stance.SELL, source_label=SourceLabel.SELL)
        result = write_claims([reparsed], path=path)

        assert result["inserted"] == 0
        assert result["unchanged"] == 0
        assert len(result["conflicts"]) == 1
        # The stored (original) reading survives untouched.
        fetched = claims_for_asset("player:4034", path=path)
        assert len(fetched) == 1
        assert fetched[0].claim.stance is Stance.BUY

    def test_a_later_parser_run_may_refresh_confidence_on_an_unchanged_claim(self, tmp_path):
        path = tmp_path / "ledger.sqlite"
        write_claims(
            [_entry(extraction_confidence=ExtractionConfidence.LOW, parser_version="v1")],
            path=path,
        )
        write_claims(
            [_entry(extraction_confidence=ExtractionConfidence.HIGH, parser_version="v2")],
            path=path,
        )
        fetched = claims_for_asset("player:4034", path=path)
        assert len(fetched) == 1
        assert fetched[0].extraction_confidence is ExtractionConfidence.HIGH
        assert fetched[0].parser_version == "v2"
        # The claim's own facts are untouched by the envelope refresh.
        assert fetched[0].claim.stance is Stance.BUY

    def test_different_asset_is_a_different_row_not_a_conflict(self, tmp_path):
        path = tmp_path / "ledger.sqlite"
        write_claims([_entry(asset_key="player:1")], path=path)
        write_claims([_entry(asset_key="player:2")], path=path)
        assert len(all_claims(path=path)) == 2


class TestConstructionInvariantsAreInheritedNotReimplemented:
    """AnalystClaim/SourceRef already refuse these at construction time —
    these tests PIN that inheritance rather than re-implementing the
    checks in the store."""

    def test_missing_publication_time_is_refused_by_the_dataclass(self):
        with pytest.raises(TypeError):
            C.AnalystClaim(
                source=_source(),
                asset_key="player:1",
                stance=Stance.BUY,
                source_label=SourceLabel.BUY,
                take_type=C.TakeType.BUY_SELL_VALUE,
                provenance=C.Provenance.MODEL_INFERENCE,
                # said_at omitted entirely — required positional field
            )

    def test_unknown_blank_analyst_is_refused_by_source_ref(self):
        with pytest.raises(ValueError, match="analyst_id"):
            C.SourceRef(analyst_id="", content_id="ep:1", platform="podcast")


class TestSupersession:
    def test_a_superseding_claim_is_stored_and_readable(self, tmp_path):
        path = tmp_path / "ledger.sqlite"
        original = _entry(source=_source(content="ep:1"))
        write_claims([original], path=path)

        correction = _entry(
            source=_source(content="ep:2"),
            said_at=NOW + dt.timedelta(days=1),
            stance=Stance.SELL,
            source_label=SourceLabel.SELL,
            supersedes="ep:1",
        )
        write_claims([correction], path=path)

        fetched = claims_for_asset("player:4034", path=path)
        assert len(fetched) == 2
        superseding = [e for e in fetched if e.claim.supersedes == "ep:1"]
        assert len(superseding) == 1
        assert superseding[0].claim.stance is Stance.SELL


class TestHashSplit:
    def test_identity_key_ignores_stance(self):
        buy = _claim(stance=Stance.BUY, source_label=SourceLabel.BUY)
        sell = _claim(stance=Stance.SELL, source_label=SourceLabel.SELL)
        assert claim_identity_key(buy) == claim_identity_key(sell)
        assert claim_content_hash(buy) != claim_content_hash(sell)

    def test_identity_key_differs_across_analysts(self):
        a = _claim(source=_source(analyst="analyst:a"))
        b = _claim(source=_source(analyst="analyst:b"))
        assert claim_identity_key(a) != claim_identity_key(b)

    def test_identity_key_differs_across_said_at(self):
        a = _claim(said_at=NOW)
        b = _claim(said_at=NOW + dt.timedelta(hours=1))
        assert claim_identity_key(a) != claim_identity_key(b)
