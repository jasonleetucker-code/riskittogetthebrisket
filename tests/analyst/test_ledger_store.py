"""Write-path contract of the analyst claim ledger (C6-ANA-01).

Idempotency, conflict surfacing, explicit corrections, identity keying
through the canonical owners, and fail-closed validation.
"""

from __future__ import annotations

import sqlite3
from datetime import timedelta

import pytest

from src.analyst.stance import SourceLabel, Stance
from src.analyst.store import (
    REASON_INVALID_ASSET_KEY,
    REASON_UNRESOLVED_IDENTITY,
    ContentRecord,
    ExtractionConfidence,
    LedgerEntry,
    LedgerError,
    all_claims,
    asset_key_for_board_pick_name,
    asset_key_for_market_pick,
    asset_key_for_resolution,
    correct_claim,
    coverage,
    ingest,
    is_ledger_asset_key,
    utc_now,
)
from src.analyst.claim import AssetSide
from src.identity.picks import MarketPickRef
from src.identity.resolution import RESOLVED, UNRESOLVED, Resolution
from tests.analyst._ledger_fixtures import PICK, PLAYER, at, content, entry


@pytest.fixture
def db(tmp_path):
    return tmp_path / "analyst_ledger.sqlite"


def _count(db, table: str) -> int:
    conn = sqlite3.connect(str(db))
    try:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    finally:
        conn.close()


# ── idempotency ─────────────────────────────────────────────────────────


def test_identical_reingest_is_a_counted_noop(db):
    first = ingest(content(), [entry()], path=db, recorded_at=at(1))
    assert (first.content_status, first.written, first.duplicates) == ("written", 1, 0)

    again = ingest(content(), [entry()], path=db, recorded_at=at(2))
    assert (again.content_status, again.written, again.duplicates) == ("duplicate", 0, 1)
    assert again.conflicts == () and again.rejected == ()
    assert _count(db, "claims") == 1
    assert _count(db, "content") == 1


def test_recorded_at_is_not_content(db):
    # A rerun at a different wall-clock time is still the same fact.
    ingest(content(observed=None), [entry()], path=db, recorded_at=at(1))
    again = ingest(content(observed=None), [entry()], path=db, recorded_at=at(3))
    assert again.content_status == "duplicate"
    assert again.duplicates == 1


def test_content_with_no_claims_is_recorded(db):
    res = ingest(content(), [], path=db, recorded_at=at(1))
    assert res.content_status == "written"
    assert _count(db, "content") == 1 and _count(db, "claims") == 0


# ── conflicts surfaced, never applied ───────────────────────────────────


def test_conflicting_claim_is_surfaced_and_not_applied(db):
    ingest(content(), [entry(label=SourceLabel.BUY)], path=db, recorded_at=at(1))
    res = ingest(content(), [entry(label=SourceLabel.SELL)], path=db, recorded_at=at(2))

    assert res.written == 0 and res.duplicates == 0
    assert len(res.conflicts) == 1
    conflict = res.conflicts[0]
    assert conflict["kind"] == "claim"
    assert conflict["storedHash"] != conflict["incomingHash"]

    stored = all_claims(path=db)
    assert len(stored) == 1
    assert stored[0].claim.stance is Stance.BUY  # the original reading stands


def test_envelope_difference_is_a_conflict_not_a_silent_update(db):
    ingest(content(), [entry(parser_version="v1")], path=db, recorded_at=at(1))
    res = ingest(content(), [entry(parser_version="v2")], path=db, recorded_at=at(2))
    assert len(res.conflicts) == 1
    assert all_claims(path=db)[0].parser_version == "v1"


def test_content_conflict_rejects_its_claims(db):
    ingest(content(show_id="show-a"), [], path=db, recorded_at=at(1))
    res = ingest(content(show_id="show-b"), [entry()], path=db, recorded_at=at(2))
    assert res.content_status == "conflict"
    assert res.conflicts[0]["kind"] == "content"
    assert [r["reason"] for r in res.rejected] == ["content_conflict"]
    assert _count(db, "claims") == 0


# ── explicit corrections ────────────────────────────────────────────────


def test_correction_is_a_new_row_and_the_original_is_retained(db):
    ingest(content(), [entry(label=SourceLabel.BUY)], path=db, recorded_at=at(1))
    original = all_claims(path=db)[0]

    new_id = correct_claim(
        original.ledger_id,
        entry(label=SourceLabel.SELL),
        "extractor misread sarcasm",
        path=db,
        recorded_at=at(2),
    )
    rows = {s.ledger_id: s for s in all_claims(path=db)}
    assert set(rows) == {original.ledger_id, new_id}
    assert rows[original.ledger_id].claim.stance is Stance.BUY  # untouched
    assert rows[new_id].claim.stance is Stance.SELL
    assert rows[new_id].revision == 1
    assert _count(db, "corrections") == 1


def test_correction_requires_a_reason_and_cannot_repeat(db):
    ingest(content(), [entry()], path=db, recorded_at=at(1))
    sid = all_claims(path=db)[0].ledger_id
    with pytest.raises(LedgerError, match="reason"):
        correct_claim(sid, entry(label=SourceLabel.SELL), "  ", path=db, recorded_at=at(2))
    correct_claim(sid, entry(label=SourceLabel.SELL), "fix", path=db, recorded_at=at(2))
    with pytest.raises(LedgerError, match="already superseded"):
        correct_claim(sid, entry(label=SourceLabel.HOLD), "again", path=db, recorded_at=at(3))


def test_correction_of_missing_claim_or_unrecorded_content_is_refused(db):
    ingest(content(), [entry()], path=db, recorded_at=at(1))
    with pytest.raises(LedgerError, match="missing claim"):
        correct_claim(999, entry(), "x", path=db, recorded_at=at(2))
    sid = all_claims(path=db)[0].ledger_id
    with pytest.raises(LedgerError, match="never recorded"):
        correct_claim(sid, entry(content_id="ep-unknown"), "x", path=db, recorded_at=at(2))


def test_correction_can_move_a_misresolved_asset(db):
    ingest(content(), [entry(asset_key=PLAYER)], path=db, recorded_at=at(1))
    sid = all_claims(path=db)[0].ledger_id
    new_id = correct_claim(
        sid, entry(asset_key="player:9999"), "wrong player resolved", path=db, recorded_at=at(2)
    )
    moved = {s.ledger_id: s for s in all_claims(path=db)}[new_id]
    assert moved.claim.asset_key == "player:9999"
    assert moved.revision == 0  # first row at its own coordinates


# ── identity keying through the canonical owners ────────────────────────


def test_asset_keys_come_from_identity_owners():
    resolved = Resolution(status=RESOLVED, policy="p", method="m", sleeper_id="4984")
    unresolved = Resolution(status=UNRESOLVED, policy="p", method="m", reason="ambiguous")
    assert asset_key_for_resolution(resolved) == "player:4984"
    assert asset_key_for_resolution(unresolved) is None
    assert asset_key_for_market_pick(MarketPickRef(year=2027, round_num=1)) == "mpick:2027:r1"
    assert asset_key_for_board_pick_name("2027 Early 1st") == "mpick:2027:r1:tearly"
    assert asset_key_for_board_pick_name("Josh Allen") is None
    assert is_ledger_asset_key("player:4984") and is_ledger_asset_key(PICK)
    assert not is_ledger_asset_key("name:josh allen::OFFENSE")
    assert not is_ledger_asset_key("Josh Allen")


def test_name_grade_and_raw_names_are_refused(db):
    res = ingest(
        content(),
        [entry(asset_key="name:josh allen::OFFENSE"), entry(asset_key="Josh Allen")],
        path=db,
        recorded_at=at(1),
    )
    assert [r["reason"] for r in res.rejected] == [
        REASON_UNRESOLVED_IDENTITY,
        REASON_INVALID_ASSET_KEY,
    ]
    assert _count(db, "claims") == 0


def test_pick_and_player_keys_do_not_cross_asset_sides(db):
    res = ingest(
        content(),
        [
            entry(asset_key=PICK, asset_side=AssetSide.OFFENSE),
            entry(asset_key=PLAYER, asset_side=AssetSide.PICK, said=at(0, 1)),
            entry(asset_key=PICK, asset_side=AssetSide.PICK, said=at(0, 2)),
        ],
        path=db,
        recorded_at=at(1),
    )
    assert [r["reason"] for r in res.rejected] == ["asset_side_mismatch", "asset_side_mismatch"]
    assert res.written == 1


# ── provenance and time validation ──────────────────────────────────────


def test_claim_must_belong_to_its_content(db):
    res = ingest(
        content(analysts=("alice",)),
        [entry(analyst="bob"), entry(content_id="ep-2")],
        path=db,
        recorded_at=at(1),
    )
    assert [r["reason"] for r in res.rejected] == ["analyst_not_in_content", "content_mismatch"]


def test_naive_instants_are_refused(db):
    naive = at(0).replace(tzinfo=None)
    res = ingest(content(), [entry(said=naive)], path=db, recorded_at=at(1))
    assert res.rejected[0]["reason"].startswith("invalid_time")
    bad = ingest(content("ep-2", published=naive), [], path=db, recorded_at=at(1))
    assert bad.content_status == "rejected"


def test_discovery_cannot_precede_saying_or_follow_the_write(db):
    res = ingest(
        content(),
        [
            entry(said=at(0, 2), discovered=at(0, 1)),
            entry(said=at(0, 3), discovered=at(2)),
        ],
        path=db,
        recorded_at=at(1),
    )
    assert [r["reason"] for r in res.rejected] == [
        "discovered_before_said",
        "discovered_after_recorded",
    ]


def test_content_observed_before_published_is_refused(db):
    res = ingest(content(published=at(1), observed=at(0)), [], path=db, recorded_at=at(2))
    assert res.content_status == "rejected"


def test_recorded_at_may_not_be_in_the_future(db):
    with pytest.raises(LedgerError, match="future"):
        ingest(content(), [], path=db, recorded_at=utc_now() + timedelta(hours=1))


def test_envelope_round_trips(db):
    e = LedgerEntry(
        claim=entry().claim,
        origin="extract:podcast",
        parser_version="v7",
        extraction_confidence=ExtractionConfidence.HIGH,
    )
    ingest(content(), [e], path=db, recorded_at=at(1))
    stored = all_claims(path=db)[0]
    assert stored.origin == "extract:podcast"
    assert stored.parser_version == "v7"
    assert stored.extraction_confidence is ExtractionConfidence.HIGH
    assert stored.claim == e.claim
    assert stored.to_dict()["ledgerId"] == stored.ledger_id


def test_content_record_requires_attribution():
    with pytest.raises(LedgerError):
        ContentRecord(
            platform="podcast", content_id="x", analyst_ids=(), published_at=at(0), origin="o"
        )
    with pytest.raises(LedgerError):
        ContentRecord(
            platform="podcast", content_id="x", analyst_ids=("a",), published_at=at(0), origin=""
        )


# ── reads never create the ledger ───────────────────────────────────────


def test_diagnostics_do_not_create_the_file(db):
    assert coverage(path=db)["exists"] is False
    assert all_claims(path=db) == []
    assert not db.exists()
    ingest(content(), [entry()], path=db, recorded_at=at(1))
    cov = coverage(path=db)
    assert (cov["content"], cov["claims"], cov["analysts"]) == (1, 1, 1)
