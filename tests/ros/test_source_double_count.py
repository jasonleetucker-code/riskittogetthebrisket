"""One vendor, one vote.

Two guards, at two layers, for the same defect: from 2026-07-27 until
2026-07-30 the DraftSharks ROS adapter concatenated two of the vendor's
OWN boards under one source key.  The two files covered an identical
978-player universe (zero names unique to either side) but ranked them
for different formats, so every player was counted twice — DraftSharks
took 67.4% of the blend against an intended 50.8%, ``sourceCount`` read
2 where one vendor had spoken once, and ``confidence`` was inflated on
939 of 1084 players.

Layer 1 (``src/ros/sources/draftsharks_ros.py``) is the specific fix:
union name-first instead of concatenating.
Layer 2 (``src/ros/aggregate.py``) is the durable one: the aggregator
adds a source's weight once per ROW, so it now refuses a repeat
regardless of which adapter emits it.

Both are tested here because either alone leaves the hole open — the
adapter fix does nothing for the next adapter, and the aggregate guard
does nothing about the adapter shipping rows nobody wanted.
"""

from __future__ import annotations

import csv
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from src.ros.aggregate import RankedRow, SourceSnapshot, aggregate


_LEAGUE = {
    "is_superflex": True,
    "is_2qb": False,
    "is_te_premium": True,
    "idp_enabled": True,
}
_NOW = datetime(2026, 7, 30, 12, 0, 0, tzinfo=timezone.utc)
_FRESH = "2026-07-30T11:00:00+00:00"

_ROS_HEADER = [
    "canonicalName",
    "sourceName",
    "position",
    "team",
    "rank",
    "total_ranked",
    "projection",
]


def _write_ros_csv(path: Path, rows: list[tuple[str, str, int]], total: int) -> None:
    with path.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(_ROS_HEADER)
        for name, pos, rank in rows:
            w.writerow(["", name, pos, "FA", rank, total, ""])


def _snapshot(key: str, rows: list[RankedRow], *, player_count: int) -> SourceSnapshot:
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
        scraped_at=_FRESH,
        player_count=player_count,
        has_valid_cache=True,
        rows=rows,
    )


class TestAdapterUnion(unittest.TestCase):
    """``draftsharks_ros.scrape`` must emit each player at most once."""

    def _scrape_with(self, sf, idp, *, sf_total=None, idp_total=None):
        from src.ros.sources import draftsharks_ros as mod

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            sf_csv = root / "sf.csv"
            idp_csv = root / "idp.csv"
            _write_ros_csv(sf_csv, sf, sf_total if sf_total is not None else len(sf))
            _write_ros_csv(idp_csv, idp, idp_total if idp_total is not None else len(idp))
            with (
                mock.patch.object(mod, "DS_ROS_SF_CSV", sf_csv),
                mock.patch.object(mod, "DS_ROS_IDP_CSV", idp_csv),
            ):
                return mod.scrape({"key": "draftSharksRosSf"})

    def test_fully_overlapping_boards_collapse_to_one_row_per_player(self):
        """The live shape: same universe, different format, both full."""
        sf = [("Josh Allen", "QB", 1), ("Jahmyr Gibbs", "RB", 2), ("Ja'Marr Chase", "WR", 3)]
        # The /ros-rankings/idp page verbatim — same three players, 1QB order.
        idp = [("Jahmyr Gibbs", "RB", 1), ("Ja'Marr Chase", "WR", 2), ("Josh Allen", "QB", 3)]

        result = self._scrape_with(sf, idp)

        self.assertEqual(result.status, "ok")
        names = [r["sourceName"] for r in result.rows]
        self.assertEqual(len(names), len(set(names)), f"duplicate players emitted: {names}")
        self.assertEqual(len(result.rows), 3)
        # The SF board wins outright — it is the board this source key
        # claims to be (is_superflex=True, +10% format-match bonus).
        by_name = {r["sourceName"]: r["rank"] for r in result.rows}
        self.assertEqual(by_name["Josh Allen"], 1)
        self.assertEqual(by_name["Jahmyr Gibbs"], 2)

    def test_idp_only_players_absent_from_sf_are_merged(self):
        """The documented forward-compat case still works."""
        sf = [("Josh Allen", "QB", 1), ("Jahmyr Gibbs", "RB", 2)]
        idp = [("Micah Parsons", "LB", 1), ("Josh Allen", "QB", 2)]

        result = self._scrape_with(sf, idp)

        by_name = {r["sourceName"]: r["rank"] for r in result.rows}
        self.assertIn("Micah Parsons", by_name, "genuinely new coverage was dropped")
        self.assertEqual(by_name["Josh Allen"], 1, "SF board should win the collision")
        self.assertEqual(len(result.rows), 3)

    def test_empty_sf_board_does_not_promote_the_1qb_board(self):
        """An outage must not serve a 1QB board under a superflex key.

        The source is registered ``is_superflex: True`` and paid a 1.10
        format-match bonus for it.  With the SF page down, substituting
        the idp page would pay that bonus for a format mismatch — so the
        adapter falls through to the dynasty proxies instead, which are
        genuinely superflex.
        """
        from src.ros.sources import draftsharks_ros as mod

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            sf_csv = root / "sf.csv"
            idp_csv = root / "idp.csv"
            _write_ros_csv(sf_csv, [], 0)
            _write_ros_csv(idp_csv, [("Jahmyr Gibbs", "RB", 1)], 1)
            missing = root / "nope.csv"
            with (
                mock.patch.object(mod, "DS_ROS_SF_CSV", sf_csv),
                mock.patch.object(mod, "DS_ROS_IDP_CSV", idp_csv),
                mock.patch.object(mod, "DS_DYNASTY_SF_CSV", missing),
                mock.patch.object(mod, "DS_DYNASTY_IDP_CSV", missing),
            ):
                result = mod.scrape({"key": "draftSharksRosSf"})

        # No dynasty proxies available either, so this legitimately fails
        # rather than quietly shipping the wrong-format board.
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.rows, [])


class TestAggregateOneVotePerSource(unittest.TestCase):
    """The durable guard: no adapter can double a source's weight."""

    def test_duplicate_rows_from_one_source_do_not_double_its_weight(self):
        dup = _snapshot(
            "vendorA",
            [
                RankedRow(canonical_name="josh allen", position="QB", rank=1, total_ranked=10),
                RankedRow(canonical_name="josh allen", position="QB", rank=9, total_ranked=10),
            ],
            player_count=10,
        )
        single = _snapshot(
            "vendorA",
            [RankedRow(canonical_name="josh allen", position="QB", rank=1, total_ranked=10)],
            player_count=10,
        )

        with_dup = aggregate([dup], league=_LEAGUE, now_iso=_NOW.isoformat())
        without = aggregate([single], league=_LEAGUE, now_iso=_NOW.isoformat())

        self.assertEqual(len(with_dup), 1)
        # The second row would have dragged the blend toward rank 9.
        self.assertAlmostEqual(with_dup[0]["rosValue"], without[0]["rosValue"], places=6)
        self.assertEqual(len(with_dup[0]["contributors"]), 1)

    def test_source_count_counts_distinct_sources_not_rows(self):
        """``sourceCount`` is shown as 'N sources' and breaks join ties."""
        two_boards_one_vendor = _snapshot(
            "vendorA",
            [
                RankedRow(canonical_name="josh allen", position="QB", rank=1, total_ranked=10),
                RankedRow(canonical_name="josh allen", position="QB", rank=4, total_ranked=10),
            ],
            player_count=10,
        )
        other = _snapshot(
            "vendorB",
            [RankedRow(canonical_name="josh allen", position="QB", rank=2, total_ranked=10)],
            player_count=10,
        )

        out = aggregate([two_boards_one_vendor, other], league=_LEAGUE, now_iso=_NOW.isoformat())

        self.assertEqual(len(out), 1)
        self.assertEqual(
            out[0]["sourceCount"],
            2,
            "two vendors spoke; one of them twice — that is still two sources",
        )

    def test_a_zero_scoring_row_does_not_shut_out_a_scoring_duplicate(self):
        """Dedup happens after scoring, so a dead row can't claim the slot."""
        snap = _snapshot(
            "vendorA",
            [
                # rank 0 -> rank_to_score returns <= 0 and the row is dropped.
                RankedRow(canonical_name="josh allen", position="QB", rank=0, total_ranked=10),
                RankedRow(canonical_name="josh allen", position="QB", rank=1, total_ranked=10),
            ],
            player_count=10,
        )

        out = aggregate([snap], league=_LEAGUE, now_iso=_NOW.isoformat())

        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["sourceMinRank"], 1)


if __name__ == "__main__":
    unittest.main()
