"""As-of read contract of the analyst claim ledger (C6-ANA-01).

Never future (both bases, both granularities), missing != empty,
time-aware corrections, and delegation of thesis/retraction semantics to
the claim owner.
"""

from __future__ import annotations

from datetime import date, datetime

import pytest

from src.analyst.asof import (
    REASON_NO_COVERAGE,
    REASON_NO_LEDGER,
    STATUS_CLAIMS,
    STATUS_EMPTY,
    STATUS_UNAVAILABLE,
    Basis,
    claims_as_of,
    parse_as_of,
    stance_as_of,
)
from src.analyst.claim import GameType
from src.analyst.stance import SourceLabel, Stance
from src.analyst.store import LedgerError, TimePrecision, all_claims, correct_claim, ingest
from src.history.asof import FIDELITY_EXACT, FIDELITY_NEAREST_PRIOR, FIDELITY_UNAVAILABLE
from tests.analyst._ledger_fixtures import OTHER_PLAYER, PLAYER, at, content, entry

BOTH = (Basis.SAID, Basis.KNOWN)


@pytest.fixture
def db(tmp_path):
    return tmp_path / "analyst_ledger.sqlite"


# ── basis is a required choice ──────────────────────────────────────────


def test_basis_has_no_default(db):
    with pytest.raises(TypeError):
        claims_as_of(PLAYER, at(0), path=db)  # type: ignore[call-arg]


def test_naive_as_of_is_refused():
    with pytest.raises(LedgerError):
        parse_as_of(datetime(2026, 9, 1, 12, 0))
    assert parse_as_of("2026-09-01").granularity == "day"
    assert parse_as_of("2026-09-01T12:00:00Z").granularity == "instant"


# ── never future ────────────────────────────────────────────────────────


@pytest.mark.parametrize("basis", BOTH)
def test_a_claim_said_after_t_is_never_selected(db, basis):
    ingest(content(published=at(0)), [entry(said=at(0))], path=db, recorded_at=at(0, 1))
    ingest(
        content("ep-2", published=at(2)),
        [entry(content_id="ep-2", said=at(2), label=SourceLabel.SELL)],
        path=db,
        recorded_at=at(2, 1),
    )
    for bound in (at(1), date(2026, 9, 2)):
        got = claims_as_of(PLAYER, bound, basis=basis, path=db)
        assert [s.claim.stance for s in got.claims] == [Stance.BUY]


def test_said_at_bounds_independently_of_publication(db):
    # A live stream: the content went live at 12:00, the take came at 15:00.
    ingest(content(published=at(0)), [entry(said=at(0, 3))], path=db, recorded_at=at(0, 4))
    assert claims_as_of(PLAYER, at(0, 1), basis=Basis.SAID, path=db).claims == ()
    assert len(claims_as_of(PLAYER, at(0, 3), basis=Basis.SAID, path=db).claims) == 1


def test_known_basis_excludes_what_the_ledger_had_not_recorded(db):
    # Said and published at day 0, but only ingested on day 3 (a backfill).
    ingest(content(published=at(0)), [entry(said=at(0))], path=db, recorded_at=at(3))
    said = claims_as_of(PLAYER, at(1), basis=Basis.SAID, path=db)
    known = claims_as_of(PLAYER, at(1), basis=Basis.KNOWN, path=db)
    assert said.status == STATUS_CLAIMS and len(said.claims) == 1
    assert known.status == STATUS_UNAVAILABLE
    assert known.missing_reason == REASON_NO_COVERAGE
    assert claims_as_of(PLAYER, at(3), basis=Basis.KNOWN, path=db).status == STATUS_CLAIMS


@pytest.mark.parametrize("basis", BOTH)
def test_a_claim_is_not_public_before_its_content_is_published(db, basis):
    # Recorded on day 0 (a podcast taping), released day 2.
    ingest(content(published=at(2)), [entry(said=at(0))], path=db, recorded_at=at(2, 1))
    assert claims_as_of(PLAYER, at(1), basis=Basis.SAID, path=db).claims == ()
    assert len(claims_as_of(PLAYER, at(3), basis=basis, path=db).claims) == 1


def test_day_precision_never_answers_its_own_day_at_instant_grain(db):
    ingest(
        content(published=at(0), precision=TimePrecision.DAY),
        [entry(said=at(0), precision=TimePrecision.DAY)],
        path=db,
        recorded_at=at(1),
    )
    same_day_instant = datetime.fromisoformat("2026-09-01T23:59:00+00:00")
    assert claims_as_of(PLAYER, same_day_instant, basis=Basis.SAID, path=db).claims == ()
    assert len(claims_as_of(PLAYER, date(2026, 9, 1), basis=Basis.SAID, path=db).claims) == 1
    next_day = datetime.fromisoformat("2026-09-02T00:00:00+00:00")
    assert len(claims_as_of(PLAYER, next_day, basis=Basis.SAID, path=db).claims) == 1


# ── missing is never empty ──────────────────────────────────────────────


@pytest.mark.parametrize("basis", BOTH)
def test_no_ledger_is_unavailable_and_creates_nothing(db, basis):
    got = claims_as_of(PLAYER, at(0), basis=basis, path=db)
    assert (got.status, got.missing_reason) == (STATUS_UNAVAILABLE, REASON_NO_LEDGER)
    assert not db.exists()
    stance = stance_as_of(PLAYER, "alice", at(0), basis=basis, path=db)
    assert (stance.fidelity, stance.missing_reason) == (FIDELITY_UNAVAILABLE, REASON_NO_LEDGER)
    assert not db.exists()


@pytest.mark.parametrize("basis", BOTH)
def test_uncovered_analyst_is_unavailable_but_covered_silence_is_empty(db, basis):
    ingest(
        content(analysts=("alice",)), [entry(asset_key=OTHER_PLAYER)], path=db, recorded_at=at(0, 1)
    )

    silent = claims_as_of(PLAYER, at(1), basis=basis, analyst_id="alice", path=db)
    assert silent.status == STATUS_EMPTY
    assert silent.missing_reason is None
    assert silent.covered_content == 1

    uncovered = claims_as_of(PLAYER, at(1), basis=basis, analyst_id="bob", path=db)
    assert uncovered.status == STATUS_UNAVAILABLE
    assert uncovered.missing_reason == REASON_NO_COVERAGE

    before_any = claims_as_of(PLAYER, at(-1), basis=basis, analyst_id="alice", path=db)
    assert before_any.status == STATUS_UNAVAILABLE


def test_no_signal_is_a_claim_not_an_absence(db):
    ingest(content(), [entry(label=SourceLabel.INSUFFICIENT_SIGNAL)], path=db, recorded_at=at(0, 1))
    got = stance_as_of(PLAYER, "alice", at(1), basis=Basis.SAID, path=db)
    assert got.status == STATUS_CLAIMS
    assert got.claim is not None and got.claim.claim.stance is Stance.NO_SIGNAL


def test_source_scope_filters_by_show_and_platform(db):
    ingest(content("ep-1", show_id="show-a"), [entry()], path=db, recorded_at=at(0, 1))
    ingest(
        content("vid-1", platform="youtube", show_id="show-b"),
        [entry(content_id="vid-1", platform="youtube")],
        path=db,
        recorded_at=at(0, 1),
    )
    a = claims_as_of(PLAYER, at(1), basis=Basis.SAID, show_id="show-a", path=db)
    yt = claims_as_of(PLAYER, at(1), basis=Basis.SAID, platform="youtube", path=db)
    none = claims_as_of(PLAYER, at(1), basis=Basis.SAID, show_id="show-z", path=db)
    assert [s.claim.source.content_id for s in a.claims] == ["ep-1"]
    assert [s.claim.source.content_id for s in yt.claims] == ["vid-1"]
    assert none.status == STATUS_UNAVAILABLE


# ── corrections are time-aware ──────────────────────────────────────────


def test_correction_applies_retrospectively_under_said_and_from_its_instant_under_known(db):
    ingest(content(), [entry(label=SourceLabel.BUY)], path=db, recorded_at=at(0, 1))
    sid = all_claims(path=db)[0].ledger_id
    correct_claim(sid, entry(label=SourceLabel.SELL), "misread", path=db, recorded_at=at(2))

    def stances(bound, basis):
        return [s.claim.stance for s in claims_as_of(PLAYER, bound, basis=basis, path=db).claims]

    assert stances(at(1), Basis.SAID) == [Stance.SELL]  # today's best reading
    assert stances(at(1), Basis.KNOWN) == [Stance.BUY]  # what was served then
    assert stances(at(3), Basis.KNOWN) == [Stance.SELL]  # exactly one row, never both


# ── thesis / retraction semantics delegated to the claim owner ──────────


def test_syndicated_take_counts_once(db):
    ingest(content("ep-1"), [entry(thesis_id="t1", said=at(0))], path=db, recorded_at=at(0, 1))
    ingest(
        content("vid-1", platform="youtube"),
        [entry(content_id="vid-1", platform="youtube", thesis_id="t1", said=at(0, 2))],
        path=db,
        recorded_at=at(0, 3),
    )
    got = claims_as_of(PLAYER, at(1), basis=Basis.SAID, path=db)
    assert len(got.claims) == 2  # both utterances are on the record
    assert len(got.independent()) == 1  # one opinion


def test_retraction_after_t_does_not_hide_the_claim_at_t(db):
    ingest(content("ep-1"), [entry(said=at(0))], path=db, recorded_at=at(0, 1))
    ingest(
        content("ep-2", published=at(3)),
        [entry(content_id="ep-2", said=at(3), label=SourceLabel.HOLD, supersedes="ep-1")],
        path=db,
        recorded_at=at(3, 1),
    )
    early = stance_as_of(PLAYER, "alice", at(1), basis=Basis.SAID, path=db)
    late = stance_as_of(PLAYER, "alice", at(4), basis=Basis.SAID, path=db)
    assert early.claim.claim.stance is Stance.BUY
    assert late.claim.claim.stance is Stance.HOLD


def test_dynasty_gate_is_the_claim_owners(db):
    ingest(
        content(),
        [entry(game_type=GameType.UNKNOWN), entry(game_type=GameType.DYNASTY, said=at(0, 1))],
        path=db,
        recorded_at=at(0, 2),
    )
    got = claims_as_of(PLAYER, at(1), basis=Basis.SAID, path=db)
    assert all(c.is_dynasty_evidence for c in got.independent(dynasty_only=True))
    assert len(got.independent(dynasty_only=True)) == 1


# ── stance fidelity mirrors src.history.asof ────────────────────────────


def test_stance_fidelity_exact_and_nearest_prior(db):
    ingest(content(), [entry(said=at(0))], path=db, recorded_at=at(0, 1))
    exact = stance_as_of(PLAYER, "alice", date(2026, 9, 1), basis=Basis.SAID, path=db)
    prior = stance_as_of(PLAYER, "alice", date(2026, 9, 4), basis=Basis.SAID, path=db)
    assert (exact.fidelity, exact.distance_days) == (FIDELITY_EXACT, 0)
    assert (prior.fidelity, prior.distance_days) == (FIDELITY_NEAREST_PRIOR, 3)
    payload = prior.to_dict()
    assert payload["fidelity"] == FIDELITY_NEAREST_PRIOR
    assert payload["claim"]["analystId"] == "alice"


def test_latest_stance_wins_among_changed_minds(db):
    ingest(content("ep-1"), [entry(said=at(0), thesis_id="a")], path=db, recorded_at=at(0, 1))
    ingest(
        content("ep-2", published=at(2)),
        [entry(content_id="ep-2", said=at(2), thesis_id="b", label=SourceLabel.SELL)],
        path=db,
        recorded_at=at(2, 1),
    )
    got = stance_as_of(PLAYER, "alice", at(3), basis=Basis.KNOWN, path=db)
    assert got.claim.claim.stance is Stance.SELL
