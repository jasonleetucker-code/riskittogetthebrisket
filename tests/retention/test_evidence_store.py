"""C1-RET-04 / C1-RET-05 — the append-only evidence store.

These pin the properties that make the store *retention* rather than
just another cache: an observation cannot be destroyed by a later one,
a re-run cannot duplicate or truncate, and — the property owner review
had to correct — an unobserved period reads as unobserved rather than as
a straight line between two matching endpoints.
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

JAN01 = "2026-01-01T00:00:00+00:00"
JAN02 = "2026-01-02T00:00:00+00:00"
JAN03 = "2026-01-03T00:00:00+00:00"
JAN15 = "2026-01-15T00:00:00+00:00"
FEB01 = "2026-02-01T00:00:00+00:00"
MAR01 = "2026-03-01T00:00:00+00:00"


def _observe(db, league, card, when, **kw):
    return evidence_store.observe_scoring_card(league, card, observed_at=when, path=db, **kw)


# ── THE review finding: continuity may not be invented ───────────────


def test_a_same_card_observation_gap_is_not_exact(db):
    """The defect owner review caught, pinned as a regression test.

    A matching hash across an unobserved month is not evidence that the
    card held continuously.  The true history could have been A -> B -> A,
    or collection could simply have been dead.  The earlier interval
    design extended one window across this gap and answered Jan 15 with
    ``fidelity: exact``.

        UNOBSERVED MUST REMAIN UNOBSERVED.
    """
    _observe(db, "111", CARD_A, JAN01)
    # ... one month with NO observations at all ...
    _observe(db, "111", CARD_A, FEB01)

    answer = evidence_store.scoring_card_at("111", JAN15, path=db)
    assert answer is None, "a gap must not be answerable at the strict default"

    widened = evidence_store.scoring_card_at(
        "111", JAN15, accept=evidence_store.ACCEPT_ANY, path=db
    )
    assert widened["fidelity"] != evidence_store.FIDELITY_EXACT
    assert widened["fidelity"] == evidence_store.FIDELITY_RECONSTRUCTED
    # And the size of what was NOT observed is stated, not hidden.
    assert widened["bracketGapHours"] == pytest.approx(744.0)
    assert widened["bracketStartsAt"] == JAN01
    assert widened["bracketEndsAt"] == FEB01


def test_a_disagreeing_bracket_is_not_reconstructed(db):
    """Jan 1 A + Feb 1 B: the card on Jan 15 is genuinely indeterminate.

    We know it was A or B and we cannot say which, so the answer is the
    last thing actually seen, labelled as such — never a reconstruction.
    """
    _observe(db, "111", CARD_A, JAN01)
    _observe(db, "111", CARD_B, FEB01)

    assert evidence_store.scoring_card_at("111", JAN15, path=db) is None
    assert (
        evidence_store.scoring_card_at(
            "111", JAN15, accept=evidence_store.ACCEPT_BRACKETED, path=db
        )
        is None
    )

    widened = evidence_store.scoring_card_at(
        "111", JAN15, accept=evidence_store.ACCEPT_ANY, path=db
    )
    assert widened["fidelity"] == evidence_store.FIDELITY_NEAREST_PRIOR
    assert widened["scoringSettings"] == CARD_A
    assert widened["coverageGapStartsAt"] == JAN01
    assert widened["coverageGapEndsAt"] == FEB01


def test_exact_means_an_observation_at_that_instant(db):
    """Not "the endpoints matched", which is what review rejected."""
    _observe(db, "111", CARD_A, JAN01)
    _observe(db, "111", CARD_A, JAN02)

    at_obs = evidence_store.scoring_card_at("111", JAN01, path=db)
    assert at_obs["fidelity"] == evidence_store.FIDELITY_EXACT
    assert at_obs["scoringSettings"] == CARD_A

    # One second later there is no observation, so even between two
    # adjacent same-card observations the strict default declines.
    between = evidence_store.scoring_card_at("111", "2026-01-01T00:00:01+00:00", path=db)
    assert between is None


def test_the_strict_default_never_widens_on_its_own(db):
    """Every non-exact answer requires the caller to have asked for it."""
    _observe(db, "111", CARD_A, JAN01)
    _observe(db, "111", CARD_A, FEB01)

    assert evidence_store.scoring_card_at("111", JAN15, path=db) is None
    assert (
        evidence_store.scoring_card_at("111", JAN15, accept=evidence_store.ACCEPT_EXACT, path=db)
        is None
    )


def test_no_accept_setting_backfills_an_unobserved_earlier_date(db):
    """A later observation says nothing about a date before it, however
    recent and however matching."""
    _observe(db, "111", CARD_A, "2026-06-01T00:00:00+00:00")

    for accept in (
        evidence_store.ACCEPT_EXACT,
        evidence_store.ACCEPT_BRACKETED,
        evidence_store.ACCEPT_ANY,
    ):
        assert evidence_store.scoring_card_at("111", JAN01, accept=accept, path=db) is None


def test_there_is_no_gap_threshold_constant(db):
    """A "gaps under N hours bridge" rule would be a magic number
    standing in for a cadence guarantee this platform does not have.

    A 36-second gap and a one-month gap take the SAME code path and get
    the same fidelity label; only the reported ``bracketGapHours``
    differs, and the caller applies its own standard.
    """
    _observe(db, "111", CARD_A, JAN01)
    _observe(db, "111", CARD_A, "2026-01-01T00:00:36+00:00")
    tight = evidence_store.scoring_card_at(
        "111", "2026-01-01T00:00:18+00:00", accept=evidence_store.ACCEPT_ANY, path=db
    )

    assert tight["fidelity"] == evidence_store.FIDELITY_RECONSTRUCTED
    assert tight["bracketGapHours"] == pytest.approx(0.01)
    # Same fidelity as the month-wide bracket above — only the reported
    # gap distinguishes them, which is the caller's call to make.
    assert tight["fidelity"] == evidence_store.FIDELITY_RECONSTRUCTED


# ── storage is observations, append-only and idempotent ──────────────


def test_every_observation_is_recorded(db):
    """No merging at write time: the write path cannot know what
    happened while it was not looking."""
    _observe(db, "111", CARD_A, JAN01)
    _observe(db, "111", CARD_A, JAN02)
    result = _observe(db, "111", CARD_A, JAN03)

    assert result["action"] == "recorded"
    assert result["observationCount"] == 3
    assert len(evidence_store.scoring_card_observations("111", path=db)) == 3


def test_replaying_the_same_instant_is_a_no_op(db):
    _observe(db, "111", CARD_A, JAN01)
    result = _observe(db, "111", CARD_A, JAN01)

    assert result["action"] == "duplicate"
    assert len(evidence_store.scoring_card_observations("111", path=db)) == 1


def test_identical_cards_are_stored_once_but_observed_many_times(db):
    """The smallest representation that preserves the evidence:
    deduplicate identical CONTENT under its own hash, never the
    observations that decide fidelity."""
    for when in (JAN01, JAN02, JAN03):
        _observe(db, "111", CARD_A, when)

    conn = evidence_store.connect(db)
    try:
        payloads = conn.execute("SELECT COUNT(*) FROM scoring_card_payloads").fetchone()[0]
        observations = conn.execute("SELECT COUNT(*) FROM scoring_card_observations").fetchone()[0]
    finally:
        conn.close()
    assert payloads == 1
    assert observations == 3


def test_key_order_and_numeric_form_are_not_a_change(db):
    """1 and 1.0 are the same scoring rule; so is a reordered dict."""
    _observe(db, "111", {"rec": 1, "pass_td": 4}, JAN01)
    _observe(db, "111", {"pass_td": 4.0, "rec": 1.0}, JAN02)

    hashes = {o["cardHash"] for o in evidence_store.scoring_card_observations("111", path=db)}
    assert len(hashes) == 1


def test_the_overwritten_card_is_still_readable(db):
    """THE point of the row: the card the live path destroys survives."""
    _observe(db, "111", CARD_A, JAN01)
    _observe(db, "111", CARD_B, FEB01)

    old = evidence_store.scoring_card_at("111", JAN01, path=db)
    assert old["fidelity"] == evidence_store.FIDELITY_EXACT
    assert old["scoringSettings"] == CARD_A


def test_empty_card_is_not_recorded_as_an_observation(db):
    """A failed fetch must not read back as "this league scores nothing"."""
    _observe(db, "111", CARD_A, JAN01)
    result = _observe(db, "111", {}, JAN02)

    assert result["action"] == "skipped"
    assert len(evidence_store.scoring_card_observations("111", path=db)) == 1


def test_leagues_are_isolated(db):
    _observe(db, "111", CARD_A, JAN01)
    _observe(db, "222", CARD_B, JAN01)

    assert len(evidence_store.scoring_card_observations("111", path=db)) == 1
    assert evidence_store.scoring_card_at("222", JAN01, path=db)["scoringSettings"] == CARD_B


def test_out_of_order_recording_is_ordered_on_read(db):
    """Observations arrive however the collector runs; the evidence is
    ordered by when it was OBSERVED, not by when it was written."""
    _observe(db, "111", CARD_A, FEB01)
    _observe(db, "111", CARD_A, JAN01)

    stamps = [o["observedAt"] for o in evidence_store.scoring_card_observations("111", path=db)]
    assert stamps == [JAN01, FEB01]


def test_whole_card_is_stored_not_just_indexed_fields(db):
    """A question asked later about a key nobody extracted today is
    answerable only if the payload survived."""
    card = dict(CARD_A)
    card["some_future_key_nobody_reads_yet"] = 3.25
    _observe(db, "111", card, JAN01)

    stored = evidence_store.scoring_card_at("111", JAN01, path=db)
    assert stored["scoringSettings"]["some_future_key_nobody_reads_yet"] == 3.25


def test_stored_payload_is_valid_json(db):
    _observe(db, "111", CARD_A, JAN01)
    conn = evidence_store.connect(db)
    try:
        raw = conn.execute("SELECT scoring_json FROM scoring_card_payloads").fetchone()[0]
    finally:
        conn.close()
    assert json.loads(raw) == CARD_A


# ── derived windows ──────────────────────────────────────────────────


def test_a_b_a_remains_three_windows(db):
    """Merging the second A into the first would assert continuity
    across a period the card demonstrably differed."""
    _observe(db, "111", CARD_A, JAN01)
    _observe(db, "111", CARD_B, FEB01)
    _observe(db, "111", CARD_A, MAR01)

    windows = evidence_store.scoring_card_windows("111", path=db)
    assert len(windows) == 3
    assert [w["firstObservedAt"] for w in windows] == [JAN01, FEB01, MAR01]


def test_a_window_reports_its_widest_unobserved_span(db):
    """So a window of two observations a month apart reads as exactly
    that, and never as a month of coverage."""
    _observe(db, "111", CARD_A, JAN01)
    _observe(db, "111", CARD_A, FEB01)

    window = evidence_store.scoring_card_windows("111", path=db)[0]
    assert window["observationCount"] == 2
    assert window["maxGapHours"] == pytest.approx(744.0)


def test_a_single_observation_window_has_no_gap(db):
    _observe(db, "111", CARD_A, JAN01)
    window = evidence_store.scoring_card_windows("111", path=db)[0]

    assert window["observationCount"] == 1
    assert window["maxGapHours"] is None, "one observation spans nothing"


def test_windows_are_derived_never_stored(db):
    """Structural: there is no interval table to drift from the evidence."""
    _observe(db, "111", CARD_A, JAN01)
    conn = evidence_store.connect(db)
    try:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    finally:
        conn.close()
    assert "scoring_card_history" not in tables
    assert {"scoring_card_observations", "scoring_card_payloads"} <= tables


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

    _observe(db, "111", CARD_A, JAN01)
    cov = evidence_store.coverage(path=db)
    assert cov["present"] is True
    assert cov["scoringCards"]["observations"] == 1
    assert cov["scoringCards"]["distinctCards"] == 1
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
