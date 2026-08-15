"""C1-RET-04 / C1-RET-05 — the append-only evidence store.

These pin the properties that make the store *retention* rather than
just another cache: an observation cannot be destroyed by a later one,
a re-run cannot duplicate or truncate, and an unobserved period reads as
unobserved rather than as the nearest value.
"""

from __future__ import annotations

import json
import re

import pytest

from src.retention import evidence_store


@pytest.fixture
def db(tmp_path):
    evidence_store._reset_setup_cache_for_tests()
    path = tmp_path / "retention" / "evidence.sqlite"
    yield path
    evidence_store._reset_setup_cache_for_tests()


CARD_A = {"rec": 1.0, "pass_td": 4, "bonus_rec_te": 0.5}
CARD_B = {"rec": 0.08, "pass_td": 6, "bonus_rec_te": 0.0}


# ── C1-RET-04: scoring card history ──────────────────────────────────


def test_first_observation_opens_an_interval(db):
    result = evidence_store.observe_scoring_card(
        "111", CARD_A, observed_at="2026-01-01T00:00:00+00:00", path=db
    )
    assert result["action"] == "opened"
    assert result["observationCount"] == 1

    rows = evidence_store.scoring_card_history("111", path=db)
    assert len(rows) == 1
    assert rows[0]["firstObservedAt"] == "2026-01-01T00:00:00+00:00"
    assert rows[0]["lastObservedAt"] == "2026-01-01T00:00:00+00:00"


def test_unchanged_card_extends_rather_than_duplicating(db):
    evidence_store.observe_scoring_card(
        "111", CARD_A, observed_at="2026-01-01T00:00:00+00:00", path=db
    )
    evidence_store.observe_scoring_card(
        "111", CARD_A, observed_at="2026-01-02T00:00:00+00:00", path=db
    )
    result = evidence_store.observe_scoring_card(
        "111", CARD_A, observed_at="2026-01-03T00:00:00+00:00", path=db
    )

    assert result["action"] == "extended"
    assert result["observationCount"] == 3
    rows = evidence_store.scoring_card_history("111", path=db)
    assert len(rows) == 1, "an unchanged card must not mint a row per observation"
    assert rows[0]["lastObservedAt"] == "2026-01-03T00:00:00+00:00"


def test_key_order_and_numeric_form_are_not_a_change(db):
    """1 and 1.0 are the same scoring rule; so is a reordered dict.

    Same normalisation ``scoring_fingerprint`` applies for the same
    reason — without it every re-serialisation would read as a settings
    change and the history would be noise.
    """
    evidence_store.observe_scoring_card(
        "111", {"rec": 1, "pass_td": 4}, observed_at="2026-01-01T00:00:00+00:00", path=db
    )
    result = evidence_store.observe_scoring_card(
        "111", {"pass_td": 4.0, "rec": 1.0}, observed_at="2026-01-02T00:00:00+00:00", path=db
    )
    assert result["action"] == "extended"
    assert len(evidence_store.scoring_card_history("111", path=db)) == 1


def test_a_changed_card_opens_a_new_interval_and_preserves_the_old(db):
    evidence_store.observe_scoring_card(
        "111", CARD_A, observed_at="2026-01-01T00:00:00+00:00", path=db
    )
    evidence_store.observe_scoring_card(
        "111", CARD_B, observed_at="2026-02-01T00:00:00+00:00", path=db
    )

    rows = evidence_store.scoring_card_history("111", path=db)
    assert len(rows) == 2
    # THE point of the row: the old card still exists after the
    # overwrite that destroyed it in data/leagues/scoring_*.json.
    assert rows[0]["cardHash"] != rows[1]["cardHash"]

    old = evidence_store.scoring_card_at("111", "2026-01-01T00:00:00+00:00", path=db)
    assert old is not None
    assert old["fidelity"] == "exact"
    assert old["scoringSettings"] == CARD_A


def test_a_gap_between_observations_is_not_answered_exactly(db):
    """Two observations a month apart under different cards prove a
    change happened between them — not what was in force on Jan 15."""
    evidence_store.observe_scoring_card(
        "111", CARD_A, observed_at="2026-01-01T00:00:00+00:00", path=db
    )
    evidence_store.observe_scoring_card(
        "111", CARD_B, observed_at="2026-02-01T00:00:00+00:00", path=db
    )

    assert evidence_store.scoring_card_at("111", "2026-01-15T00:00:00+00:00", path=db) is None

    downgraded = evidence_store.scoring_card_at(
        "111", "2026-01-15T00:00:00+00:00", allow_nearest_prior=True, path=db
    )
    assert downgraded["fidelity"] == "nearest_prior"
    assert downgraded["scoringSettings"] == CARD_A
    # The uncertainty is bounded and stated, not implied.
    assert downgraded["coverageGapStartsAt"] == "2026-01-01T00:00:00+00:00"
    assert downgraded["coverageGapEndsAt"] == "2026-02-01T00:00:00+00:00"


def test_nearest_prior_never_reaches_backwards_to_a_later_card(db):
    """No flag makes today's card an answer about the past."""
    evidence_store.observe_scoring_card(
        "111", CARD_A, observed_at="2026-06-01T00:00:00+00:00", path=db
    )

    assert (
        evidence_store.scoring_card_at(
            "111", "2026-01-01T00:00:00+00:00", allow_nearest_prior=True, path=db
        )
        is None
    )


def test_reverting_to_an_earlier_card_opens_a_third_interval(db):
    """A → B → A is three windows, not two.

    Merging the second A into the first would assert the card was
    continuous across a period it demonstrably differed.
    """
    evidence_store.observe_scoring_card(
        "111", CARD_A, observed_at="2026-01-01T00:00:00+00:00", path=db
    )
    evidence_store.observe_scoring_card(
        "111", CARD_B, observed_at="2026-02-01T00:00:00+00:00", path=db
    )
    evidence_store.observe_scoring_card(
        "111", CARD_A, observed_at="2026-03-01T00:00:00+00:00", path=db
    )

    rows = evidence_store.scoring_card_history("111", path=db)
    assert len(rows) == 3
    mid = evidence_store.scoring_card_at(
        "111", "2026-02-15T00:00:00+00:00", allow_nearest_prior=True, path=db
    )
    assert mid["scoringSettings"] == CARD_B
    assert mid["coverageGapEndsAt"] == "2026-03-01T00:00:00+00:00"


def test_card_at_an_unobserved_date_is_none_not_the_nearest(db):
    """MISSING IS NEVER ZERO, and never today's value either."""
    evidence_store.observe_scoring_card(
        "111", CARD_A, observed_at="2026-06-01T00:00:00+00:00", path=db
    )

    assert evidence_store.scoring_card_at("111", "2026-01-01T00:00:00+00:00", path=db) is None
    # And after the last observation: the window is open-ended in
    # reality but only CLOSED evidence is reported.
    assert evidence_store.scoring_card_at("111", "2026-09-01T00:00:00+00:00", path=db) is None


def test_empty_card_is_not_recorded_as_a_change(db):
    """A failed fetch must not read back as "this league scores nothing"."""
    evidence_store.observe_scoring_card(
        "111", CARD_A, observed_at="2026-01-01T00:00:00+00:00", path=db
    )
    result = evidence_store.observe_scoring_card(
        "111", {}, observed_at="2026-01-02T00:00:00+00:00", path=db
    )
    assert result["action"] == "skipped"
    assert len(evidence_store.scoring_card_history("111", path=db)) == 1


def test_leagues_are_isolated(db):
    evidence_store.observe_scoring_card(
        "111", CARD_A, observed_at="2026-01-01T00:00:00+00:00", path=db
    )
    evidence_store.observe_scoring_card(
        "222", CARD_B, observed_at="2026-01-01T00:00:00+00:00", path=db
    )

    assert len(evidence_store.scoring_card_history("111", path=db)) == 1
    assert len(evidence_store.scoring_card_history("222", path=db)) == 1
    assert (
        evidence_store.scoring_card_at("222", "2026-01-01T00:00:00+00:00", path=db)[
            "scoringSettings"
        ]
        == CARD_B
    )


def test_out_of_order_replay_does_not_rewind_the_window(db):
    evidence_store.observe_scoring_card(
        "111", CARD_A, observed_at="2026-01-05T00:00:00+00:00", path=db
    )
    evidence_store.observe_scoring_card(
        "111", CARD_A, observed_at="2026-01-02T00:00:00+00:00", path=db
    )

    rows = evidence_store.scoring_card_history("111", path=db)
    assert rows[0]["lastObservedAt"] == "2026-01-05T00:00:00+00:00"


def test_whole_card_is_stored_not_just_indexed_fields(db):
    """A question asked later about a key nobody extracted today is
    answerable only if the payload survived."""
    card = dict(CARD_A)
    card["some_future_key_nobody_reads_yet"] = 3.25
    evidence_store.observe_scoring_card(
        "111", card, observed_at="2026-01-01T00:00:00+00:00", path=db
    )

    stored = evidence_store.scoring_card_at("111", "2026-01-01T00:00:00+00:00", path=db)
    assert stored["scoringSettings"]["some_future_key_nobody_reads_yet"] == 3.25


# ── C1-RET-05: trending observations ─────────────────────────────────


SNAP = {
    "fetchedAt": "2026-01-01T00:00:00+00:00",
    "lookbackHours": 24,
    "counts": {"4034": 900, "6786": 400},
}


def test_trending_snapshot_is_recorded(db):
    result = evidence_store.observe_trending_snapshot(SNAP, path=db)
    assert result["action"] == "recorded"
    assert result["inserted"] == 2

    series = evidence_store.trending_series("4034", path=db)
    assert [s["count"] for s in series] == [900]
    assert series[0]["lookbackHours"] == 24


def test_recording_the_same_snapshot_twice_is_a_no_op(db):
    """The adapter caches for 15 minutes and the scrape runs every 2h,
    so a cached snapshot WILL be offered more than once."""
    evidence_store.observe_trending_snapshot(SNAP, path=db)
    result = evidence_store.observe_trending_snapshot(SNAP, path=db)

    assert result["action"] == "duplicate"
    assert result["inserted"] == 0
    assert len(evidence_store.trending_series("4034", path=db)) == 1


def test_a_later_snapshot_extends_the_series(db):
    evidence_store.observe_trending_snapshot(SNAP, path=db)
    evidence_store.observe_trending_snapshot(
        {**SNAP, "fetchedAt": "2026-01-01T02:00:00+00:00", "counts": {"4034": 1200}},
        path=db,
    )
    series = evidence_store.trending_series("4034", path=db)
    assert [s["count"] for s in series] == [900, 1200], "oldest first"


def test_empty_or_undated_snapshots_are_skipped(db):
    assert evidence_store.observe_trending_snapshot(None, path=db)["action"] == "skipped"
    assert evidence_store.observe_trending_snapshot({}, path=db)["action"] == "skipped"
    assert (
        evidence_store.observe_trending_snapshot({"counts": {"1": 2}}, path=db)["reason"]
        == "no_fetched_at"
    )
    # Zero recorded players is the absence of a fetch, not evidence
    # that nobody was added.
    assert (
        evidence_store.observe_trending_snapshot(
            {"fetchedAt": "2026-01-01T00:00:00+00:00", "counts": {}}, path=db
        )["reason"]
        == "no_counts"
    )


# ── coverage ─────────────────────────────────────────────────────────


def test_coverage_distinguishes_absent_from_empty(db):
    assert evidence_store.coverage(path=db) == {"present": False, "path": str(db)}

    evidence_store.observe_scoring_card(
        "111", CARD_A, observed_at="2026-01-01T00:00:00+00:00", path=db
    )
    cov = evidence_store.coverage(path=db)
    assert cov["present"] is True
    assert cov["scoringCards"]["intervals"] == 1
    # The trending half is genuinely empty, and says so with a count
    # rather than by being absent from the report.
    assert cov["trending"]["observations"] == 0
    assert cov["trending"]["lastObservedAt"] is None


def test_no_insert_or_replace_in_the_write_path():
    """INSERT OR REPLACE is DELETE-then-INSERT in SQLite and silently
    nulls every unlisted column.  Structural guard, same as board_store."""
    source = (evidence_store.__file__).replace(".pyc", ".py")
    with open(source, encoding="utf-8") as fh:
        text = fh.read()
    # Match real SQL (which always names a table) rather than prose, so
    # the module can go on explaining WHY the statement is banned.  The
    # only permitted target is the schema_version meta row, which owns
    # every column in its table.
    statements = re.findall(r"INSERT OR REPLACE INTO\s+(\w+)", text)
    assert statements == ["meta"], statements


def test_stored_payload_is_valid_json(db):
    evidence_store.observe_scoring_card(
        "111", CARD_A, observed_at="2026-01-01T00:00:00+00:00", path=db
    )
    conn = evidence_store.connect(db)
    try:
        raw = conn.execute("SELECT scoring_json FROM scoring_card_history").fetchone()[0]
    finally:
        conn.close()
    assert json.loads(raw) == CARD_A
