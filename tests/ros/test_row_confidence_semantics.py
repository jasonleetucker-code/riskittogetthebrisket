"""ROS row confidence and projection: zero, missing and 1.0 are three statements.

Research reconciliation 2026-09-25 (confidence-semantics row): the ROS path
coerced a per-row ``confidence`` of ``0`` to ``1.0`` in three places
(``scrape._build_snapshot``, the resolver multiplication in ``run_all``,
and ``aggregate()``), and ``_build_snapshot`` turned a numeric ``0``
projection into ``None``.  MISSING IS NEVER ZERO cuts both ways: a real
zero may not be read as missing, nor as full confidence.

The semantics these tests pin are the EXISTING owner's, not new ones:

* ``confidence`` is a per-row MULTIPLIER on the source's weight
  (``RankedRow``, default ``1.0``; ``run_all``: "an adapter can express
  low-signal-row confidence").  An adapter that states none has expressed
  no per-row reduction, so absent / ``None`` / a blank CSV cell is the
  multiplicative identity, exactly the dataclass default.
* ``0`` is a statement: this row carries no weight.  A row whose weight is
  zero is treated the way ``aggregate()`` already treats a zero-weight
  SOURCE (``if weight <= 0: continue``) and a zero-SCORE row: it casts no
  vote, is not a contributor, and does not claim the per-source dedup slot.
* ``projection_value`` of ``0`` is a projection of zero points; blank is
  missing.  (It is carried, not consumed — see
  ``test_projection_value_is_not_consumed.py`` — so this pins identity, not
  a value change.)

Each test uses OPPOSING observations so a coercion changes the answer.
"""

from __future__ import annotations

import csv
from pathlib import Path
from unittest import mock

import pytest

from src.ros import scrape
from src.ros.aggregate import RankedRow, SourceSnapshot, aggregate
from src.ros.mapping import MappedPlayer
from src.ros.parse import rank_to_score

LEAGUE = {"is_superflex": True, "is_2qb": False, "is_te_premium": True, "idp_enabled": True}
FRESH = "2026-09-25T11:00:00+00:00"
TOTAL = 50


def _snap(key: str, rows: list[RankedRow]) -> SourceSnapshot:
    return SourceSnapshot(
        source_key=key,
        base_weight=1.0,
        is_ros=True,
        is_dynasty=False,
        is_te_premium=False,
        is_superflex=True,
        is_2qb=False,
        is_idp=False,
        status="ok",
        scraped_at=FRESH,
        player_count=TOTAL,
        has_valid_cache=True,
        rows=rows,
    )


def _row(name: str, rank: int, confidence) -> RankedRow:
    return RankedRow(
        canonical_name=name, position="WR", rank=rank, total_ranked=TOTAL, confidence=confidence
    )


def _player_x(confidence_a) -> dict:
    """Source A loves X (rank 1); source B hates X (rank 50).  Only A's row
    confidence varies, so the answer moves exactly when A's vote does."""
    snaps = [
        _snap("a", [_row("X", 1, confidence_a), _row("Y", 50, 1.0)]),
        _snap("b", [_row("X", 50, 1.0), _row("Y", 1, 1.0)]),
    ]
    out = aggregate(snaps, league=LEAGUE)
    return next(p for p in out if p["canonicalName"] == "X")


# ── aggregate(): the consumer ──────────────────────────────────────────────


def test_zero_confidence_is_not_full_confidence():
    zero, one = _player_x(0.0), _player_x(1.0)
    # With A's row at zero weight, X is priced by B alone (rank 50 of 50).
    assert zero["rosValue"] == pytest.approx(round(rank_to_score(50, TOTAL), 2))
    assert zero["rosValue"] != one["rosValue"]
    assert zero["rosValue"] < one["rosValue"]


def test_a_zero_confidence_row_is_not_a_contributor_or_a_source():
    zero = _player_x(0.0)
    assert [c["sourceKey"] for c in zero["contributors"]] == ["b"]
    assert zero["sourceCount"] == 1
    assert _player_x(1.0)["sourceCount"] == 2


def test_missing_confidence_is_the_documented_identity_not_zero():
    missing, one = _player_x(None), _player_x(1.0)
    assert missing["rosValue"] == one["rosValue"]
    assert missing["sourceCount"] == 2
    # ...and it is NOT the zero answer: missing never collapses into 0.
    assert missing["rosValue"] != _player_x(0.0)["rosValue"]


def test_partial_confidence_scales_the_vote():
    half, one, zero = _player_x(0.5), _player_x(1.0), _player_x(0.0)
    assert zero["rosValue"] < half["rosValue"] < one["rosValue"]
    a = next(c for c in half["contributors"] if c["sourceKey"] == "a")
    b = next(c for c in half["contributors"] if c["sourceKey"] == "b")
    assert a["weight"] == pytest.approx(b["weight"] * 0.5, rel=1e-3)


def test_a_zero_confidence_row_does_not_claim_the_dedup_slot():
    """A vendor listing X twice, the first at zero confidence: the zero row
    casts no vote, so the scoreable duplicate behind it keeps the slot (the
    same rule as a zero-SCORE row)."""
    snaps = [_snap("a", [_row("X", 1, 0.0), _row("X", 10, 1.0)])]
    x = aggregate(snaps, league=LEAGUE)[0]
    assert x["sourceMinRank"] == 10
    assert x["rosValue"] == pytest.approx(round(rank_to_score(10, TOTAL), 2))


# ── scrape._build_snapshot(): the ingestion boundary ──────────────────────


def _built(**row) -> RankedRow:
    base = {"canonicalName": "X", "position": "WR", "rank": 3, "total_ranked": TOTAL}
    result = scrape.ScrapeResult(source_key="a", status="ok", rows=[{**base, **row}])
    return scrape._build_snapshot({"key": "a", "base_weight": 1.0}, result).rows[0]


@pytest.mark.parametrize(
    ("given", "expected"),
    [(0, 0.0), (0.0, 0.0), ("0", 0.0), (0.5, 0.5), (1.0, 1.0)],
)
def test_build_snapshot_keeps_a_stated_confidence(given, expected):
    assert _built(confidence=given).confidence == expected


@pytest.mark.parametrize("given", [None, ""])
def test_build_snapshot_missing_confidence_is_the_identity(given):
    assert _built(confidence=given).confidence == 1.0
    assert _built().confidence == 1.0  # key absent entirely


@pytest.mark.parametrize(("given", "expected"), [(0, 0.0), (0.0, 0.0), ("0", 0.0), ("12.5", 12.5)])
def test_build_snapshot_keeps_a_zero_projection(given, expected):
    assert _built(projection=given).projection_value == expected


@pytest.mark.parametrize("given", [None, ""])
def test_build_snapshot_blank_projection_is_missing(given):
    assert _built(projection=given).projection_value is None


# ── run_all(): resolver × source confidence ────────────────────────────────


def _run_all_with(rows: list[dict], tmp_path: Path, resolver_confidence: float) -> RankedRow:
    captured: list[SourceSnapshot] = []

    def fake_aggregate(snaps, **_kw):
        captured.extend(snaps)
        return []

    src = {"key": "a", "base_weight": 1.0, "scraper": "unused", "is_ros": True}
    result = scrape.ScrapeResult(source_key="a", status="ok", rows=rows, started_at="t")
    with (
        mock.patch.object(scrape, "ROS_DATA_DIR", tmp_path),
        mock.patch.object(scrape, "enabled_ros_sources", return_value=[src]),
        mock.patch.object(scrape, "_invoke_adapter", return_value=result),
        mock.patch.object(
            scrape,
            "resolve_player",
            return_value=MappedPlayer(
                source_name="X", canonical_name="x", confidence=resolver_confidence, method="exact"
            ),
        ),
        mock.patch.object(scrape, "aggregate", side_effect=fake_aggregate),
        mock.patch.object(scrape, "_refresh_team_strength_snapshot", return_value={}),
        mock.patch.object(scrape, "_refresh_power_snapshots", return_value={}),
        mock.patch.object(scrape, "_refresh_sim_caches", return_value={}),
    ):
        scrape.run_all(canonical_universe={"x"})
    return captured[0].rows[0]


def _source_row(**extra) -> dict:
    return {"sourceName": "X", "canonicalName": "", "rank": 3, "total_ranked": TOTAL, **extra}


def test_resolver_multiplies_a_zero_source_confidence_to_zero(tmp_path):
    assert _run_all_with([_source_row(confidence=0.0)], tmp_path, 0.9).confidence == 0.0


def test_resolver_multiplies_a_stated_confidence(tmp_path):
    assert _run_all_with([_source_row(confidence=0.5)], tmp_path, 0.9).confidence == pytest.approx(
        0.45
    )


def test_resolver_confidence_alone_when_the_source_states_none(tmp_path):
    assert _run_all_with([_source_row()], tmp_path, 0.9).confidence == pytest.approx(0.9)


# ── CSV round trip: the persisted projection says what the live row said ───


@pytest.mark.parametrize("given", [0, 0.0, "0", 7.25, ""])
def test_projection_survives_the_csv_round_trip(given, tmp_path):
    """The live snapshot is built from the adapter's in-memory row; the next
    read comes back through ``data/ros/sources/<key>.csv`` as text.  The same
    observation must mean the same thing on both sides."""
    from src.ros.sources import draftsharks_ros

    row = {
        "canonicalName": "X",
        "sourceName": "X",
        "position": "WR",
        "team": "KC",
        "rank": 3,
        "total_ranked": 1,
        "projection": given,
    }
    live = scrape._build_snapshot(
        {"key": "a"}, scrape.ScrapeResult(source_key="a", status="ok", rows=[row])
    ).rows[0]
    with mock.patch.object(scrape, "ROS_DATA_DIR", tmp_path):
        scrape._write_csv("a", [row])
        path = scrape._csv_path("a")
    with path.open(newline="") as f:
        assert next(csv.DictReader(f))["projection"] == ("" if given == "" else str(given))
    reread = draftsharks_ros._read_ros_csv(path)
    reread[0]["canonicalName"] = "X"
    back = scrape._build_snapshot(
        {"key": "a"}, scrape.ScrapeResult(source_key="a", status="ok", rows=reread)
    ).rows[0]
    assert back.projection_value == live.projection_value
    assert live.projection_value == (None if given == "" else float(given))
