"""An owner-attested baseline week, and the one restatement it authorizes.

THE SITUATION
-------------
Movement on the weekly share card is ``previousOfficialRank - currentRank``, so
Week 1 is only meaningful once Week 0 exists.  Publication of the 2026 preseason
ranking was missed: the automated publisher refuses ``week < 1`` by design, and
the spec forbids back-dating today's ROS strength into an older week, so the
ranking itself is not recomputable.  What IS recoverable is the ORDER the site
actually displayed, from the owner's screenshot of the published card.

These tests pin the two properties that keep that honest:

1. an attested week records an order and NOTHING else — no Power score, no
   components, and a ``rankSource`` that says where it came from;
2. publishing it may fill in a movement its successor could not know, and may
   not change anything else about that successor, ever.
"""

from __future__ import annotations

import json

import pytest

from src.ros import power_snapshots
from tests.ros.test_power_snapshots import _section

ATTESTATION = {"source": "owner screenshot", "attestedBy": "site owner"}


def _attested_rows(order: list[str]) -> list[dict]:
    return [
        {"ownerId": oid, "displayName": oid.upper(), "teamName": f"Team {oid}", "rank": i + 1}
        for i, oid in enumerate(order)
    ]


def _publish_week_one(ranks: dict[str, int]) -> None:
    power_snapshots.record_snapshot(
        league_key="main",
        section=_section(week=1, ranks=ranks),
        scoring_fingerprint="abc",
        finalized_at="2026-09-15T00:00:00+00:00",
    )


@pytest.fixture(autouse=True)
def _isolated_store(tmp_path, monkeypatch):
    monkeypatch.setattr(power_snapshots, "ROS_DATA_DIR", tmp_path)


def test_an_attested_week_carries_an_order_and_no_power_score():
    path, created = power_snapshots.record_attested_snapshot(
        league_key="main",
        season="2026",
        week=0,
        rows=_attested_rows(["a", "b", "c"]),
        attestation=ATTESTATION,
        methodology_version="canonical-power-2026.09-v1",
    )
    assert created
    payload = json.loads(path.read_text())

    assert payload["rankSource"] == power_snapshots.RANK_SOURCE_ATTESTED
    assert payload["preseason"] is True
    assert payload["attestation"] == ATTESTATION
    # We did not recompute this week, so we cannot claim to know the scoring
    # configuration behind it.  Unknown, not a fingerprint copied from a
    # neighbouring week.
    assert payload["scoringConfigFingerprint"] is None

    for row in payload["ranking"]:
        assert row["powerScore"] is None, "an attested row must never carry a score"
        assert all(value is None for value in row["components"].values())
        assert row["componentRanks"] == {}
        # Week 0 has no predecessor; that is a real "no baseline", not a flat.
        assert row["priorRank"] is None
        assert row["rankDelta"] is None

    assert [row["rank"] for row in payload["ranking"]] == [1, 2, 3]


def test_an_engine_week_is_stamped_as_engine_and_a_missing_stamp_reads_as_engine():
    _publish_week_one({"a": 1, "b": 2})
    published = power_snapshots.load_snapshot("main", "2026", 1)
    assert published["rankSource"] == power_snapshots.RANK_SOURCE_ENGINE

    # Snapshots published before the field existed carry no key at all, and the
    # only publisher then was the engine.
    legacy = {k: v for k, v in published.items() if k != "rankSource"}
    assert power_snapshots.rank_source(legacy) == power_snapshots.RANK_SOURCE_ENGINE


def test_a_hand_transcribed_rank_sequence_must_be_complete():
    # Exactly the two errors a hand transcription makes: a skipped position...
    with pytest.raises(ValueError, match="complete 1..3 sequence"):
        power_snapshots.record_attested_snapshot(
            league_key="main",
            season="2026",
            week=0,
            rows=[
                {"ownerId": "a", "rank": 1},
                {"ownerId": "b", "rank": 2},
                {"ownerId": "c", "rank": 4},
            ],
            attestation=ATTESTATION,
        )
    # ...and a duplicated one.
    with pytest.raises(ValueError, match="complete 1..3 sequence"):
        power_snapshots.record_attested_snapshot(
            league_key="main",
            season="2026",
            week=0,
            rows=[
                {"ownerId": "a", "rank": 1},
                {"ownerId": "b", "rank": 2},
                {"ownerId": "c", "rank": 2},
            ],
            attestation=ATTESTATION,
        )


def test_an_attested_week_must_say_where_it_came_from():
    with pytest.raises(ValueError, match="where its ranking came from"):
        power_snapshots.record_attested_snapshot(
            league_key="main",
            season="2026",
            week=0,
            rows=_attested_rows(["a", "b"]),
            attestation={},
        )


def test_an_attested_week_cannot_overwrite_a_publication():
    _publish_week_one({"a": 1, "b": 2})
    path, created = power_snapshots.record_attested_snapshot(
        league_key="main",
        season="2026",
        week=1,
        rows=_attested_rows(["b", "a"]),
        attestation=ATTESTATION,
    )
    assert created is False
    # The engine's week survives untouched.
    assert json.loads(path.read_text())["ranking"][0]["ownerId"] == "a"


def test_restating_fills_in_the_movement_week_one_could_not_know():
    # Published ranking: a 1, b 2, c 3, d 4.
    _publish_week_one({"a": 1, "b": 2, "c": 3, "d": 4})
    assert all(
        row["rankDelta"] is None
        for row in power_snapshots.load_snapshot("main", "2026", 1)["ranking"]
    )

    # Attested baseline: b was 1st, a 2nd, d 3rd, c 4th.
    power_snapshots.record_attested_snapshot(
        league_key="main",
        season="2026",
        week=0,
        rows=_attested_rows(["b", "a", "d", "c"]),
        attestation=ATTESTATION,
    )
    path, restated = power_snapshots.restate_movement(
        league_key="main", season="2026", week=1, reason="owner_authorized_backfill"
    )
    assert restated

    payload = json.loads(path.read_text())
    rows = {row["ownerId"]: row for row in payload["ranking"]}
    assert (rows["a"]["priorRank"], rows["a"]["rankDelta"]) == (2, 1)
    assert (rows["b"]["priorRank"], rows["b"]["rankDelta"]) == (1, -1)
    assert (rows["c"]["priorRank"], rows["c"]["rankDelta"]) == (4, 1)
    assert (rows["d"]["priorRank"], rows["d"]["rankDelta"]) == (3, -1)

    # The baseline has no Power score, so the SCORE delta stays unknown. A rank
    # movement we can prove does not license a score movement we cannot.
    assert all(row["powerScoreDelta"] is None for row in payload["ranking"])

    # The change is recorded, not applied silently.
    assert payload["restatements"][0]["reason"] == "owner_authorized_backfill"
    assert len(payload["restatements"][0]["changed"]) == 4


def test_restating_is_idempotent():
    _publish_week_one({"a": 1, "b": 2})
    power_snapshots.record_attested_snapshot(
        league_key="main",
        season="2026",
        week=0,
        rows=_attested_rows(["b", "a"]),
        attestation=ATTESTATION,
    )
    power_snapshots.restate_movement(league_key="main", season="2026", week=1, reason="first")
    before = json.loads(power_snapshots.snapshot_path("main", "2026", 1).read_text())

    _, restated = power_snapshots.restate_movement(
        league_key="main", season="2026", week=1, reason="second"
    )
    assert restated is False
    after = json.loads(power_snapshots.snapshot_path("main", "2026", 1).read_text())
    assert after == before, "a no-op restatement must not even append an audit row"


def test_restating_refuses_to_rewrite_movement_that_was_already_published():
    # Two published engine weeks: week 2's arrows are real and final.
    _publish_week_one({"a": 1, "b": 2})
    power_snapshots.record_snapshot(
        league_key="main",
        section=_section(week=2, ranks={"a": 2, "b": 1}),
        scoring_fingerprint="abc",
        finalized_at="2026-09-22T00:00:00+00:00",
    )
    rows = {r["ownerId"]: r for r in power_snapshots.load_snapshot("main", "2026", 2)["ranking"]}
    assert rows["a"]["rankDelta"] == -1

    # Now corrupt week 1 so a recomputation would produce a DIFFERENT arrow.
    path = power_snapshots.snapshot_path("main", "2026", 1)
    payload = json.loads(path.read_text())
    for row in payload["ranking"]:
        row["rank"] = 1 if row["ownerId"] == "b" else 2
    path.write_text(json.dumps(payload))

    with pytest.raises(ValueError, match="refusing to rewrite published movement"):
        power_snapshots.restate_movement(
            league_key="main", season="2026", week=2, reason="should not be allowed"
        )


def test_restating_refuses_when_anything_but_movement_would_change():
    _publish_week_one({"a": 1, "b": 2})
    power_snapshots.record_attested_snapshot(
        league_key="main",
        season="2026",
        week=0,
        rows=_attested_rows(["b", "a"]),
        attestation=ATTESTATION,
    )
    # A row shape the restatement cannot reproduce: drop a key the writer emits.
    path = power_snapshots.snapshot_path("main", "2026", 1)
    payload = json.loads(path.read_text())
    for row in payload["ranking"]:
        row.pop("powerScoreDelta")
    path.write_text(json.dumps(payload))

    with pytest.raises(ValueError, match="row shape"):
        power_snapshots.restate_movement(
            league_key="main", season="2026", week=1, reason="shape change"
        )


def test_restating_a_week_that_was_never_published_is_an_error():
    with pytest.raises(ValueError, match="no published snapshot"):
        power_snapshots.restate_movement(
            league_key="main", season="2026", week=4, reason="nothing there"
        )


def test_season_snapshots_are_ordered_and_scoped_to_their_season():
    power_snapshots.record_attested_snapshot(
        league_key="main",
        season="2026",
        week=0,
        rows=_attested_rows(["a", "b"]),
        attestation=ATTESTATION,
    )
    _publish_week_one({"a": 1, "b": 2})
    power_snapshots.record_snapshot(
        league_key="main",
        section=_section(week=3, ranks={"a": 2, "b": 1}),
        scoring_fingerprint="abc",
        finalized_at="2026-10-06T00:00:00+00:00",
    )
    # A different season must not leak into this one's history.
    power_snapshots.record_snapshot(
        league_key="main",
        section={**_section(week=9, ranks={"a": 1, "b": 2}), "asOfSeason": "2025"},
        scoring_fingerprint="abc",
        finalized_at="2025-11-01T00:00:00+00:00",
    )

    history = power_snapshots.season_snapshots("main", "2026")
    assert [snap["week"] for snap in history] == [0, 1, 3]
    assert {snap["season"] for snap in history} == {"2026"}
    assert power_snapshots.season_snapshots("main", "2099") == []
