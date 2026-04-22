"""Unit tests for ``src/api/rank_history.py``.

Covers:
* Snapshot extraction from full / data-wrapped contracts
* JSONL append + idempotency by date
* Retention cap (MAX_SNAPSHOTS)
* Corrupt-line tolerance on read
* stamp_contract_with_history mutation
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from src.api import rank_history


def _contract_with(rank_by_name: dict[str, int], asset_class: str = "offense") -> dict:
    return {
        "playersArray": [
            {
                "canonicalName": name,
                "canonicalConsensusRank": rank,
                "assetClass": asset_class,
            }
            for name, rank in rank_by_name.items()
        ]
    }


def _key(name: str, asset_class: str = "offense") -> str:
    """Shorthand for the composite ``{name}::{assetClass}`` key."""
    return f"{name}::{asset_class}"


class ExtractRanks(unittest.TestCase):
    def test_reads_top_level_players_array(self) -> None:
        c = _contract_with({"A": 1, "B": 2})
        self.assertEqual(
            rank_history._extract_ranks(c),
            {_key("A"): 1, _key("B"): 2},
        )

    def test_reads_nested_data_players_array(self) -> None:
        c = {"data": _contract_with({"X": 5})}
        self.assertEqual(rank_history._extract_ranks(c), {_key("X"): 5})

    def test_distinguishes_cross_universe_collisions(self) -> None:
        # Regression for Codex PR #217 round 2: two humans named the
        # same thing on different asset classes must produce two
        # distinct series, not overwrite each other.
        c = {
            "playersArray": [
                {
                    "canonicalName": "James Williams",
                    "canonicalConsensusRank": 78,
                    "assetClass": "offense",
                },
                {
                    "canonicalName": "James Williams",
                    "canonicalConsensusRank": 215,
                    "assetClass": "idp",
                },
            ]
        }
        ranks = rank_history._extract_ranks(c)
        self.assertEqual(ranks, {
            _key("James Williams", "offense"): 78,
            _key("James Williams", "idp"): 215,
        })

    def test_skips_unranked_rows(self) -> None:
        c = {
            "playersArray": [
                {"canonicalName": "A", "canonicalConsensusRank": 1, "assetClass": "offense"},
                {"canonicalName": "B", "canonicalConsensusRank": None, "assetClass": "offense"},
                {"canonicalName": "C", "assetClass": "offense"},
                {"canonicalName": "D", "canonicalConsensusRank": 0, "assetClass": "offense"},
                {"canonicalName": "E", "canonicalConsensusRank": -3, "assetClass": "offense"},
            ]
        }
        self.assertEqual(rank_history._extract_ranks(c), {_key("A"): 1})

    def test_falls_back_to_displayName(self) -> None:
        c = {"playersArray": [{"displayName": "Nickname", "canonicalConsensusRank": 9, "assetClass": "offense"}]}
        self.assertEqual(rank_history._extract_ranks(c), {_key("Nickname"): 9})

    def test_missing_asset_class_gets_unknown(self) -> None:
        # Legacy rows without assetClass fall through to a consistent
        # fallback key so the snapshot write doesn't silently drop
        # them.  Less granular than properly-stamped rows but better
        # than nothing.
        c = {"playersArray": [{"canonicalName": "Legacy", "canonicalConsensusRank": 10}]}
        self.assertEqual(rank_history._extract_ranks(c), {"Legacy::unknown": 10})

    def test_missing_players_array_returns_empty(self) -> None:
        self.assertEqual(rank_history._extract_ranks({}), {})


class AppendSnapshot(unittest.TestCase):
    def test_appends_single_snapshot(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "rank_history.jsonl"
            ok = rank_history.append_snapshot(
                _contract_with({"A": 1, "B": 2}), date="2026-04-20", path=path
            )
            self.assertTrue(ok)
            entries = [json.loads(line) for line in path.read_text().splitlines()]
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0]["date"], "2026-04-20")
            self.assertEqual(
                entries[0]["ranks"], {_key("A"): 1, _key("B"): 2}
            )

    def test_idempotent_per_date(self) -> None:
        # Re-running the same date overwrites — the file has exactly
        # one entry for that date after a re-run with different ranks.
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "rank_history.jsonl"
            rank_history.append_snapshot(
                _contract_with({"A": 1}), date="2026-04-20", path=path
            )
            rank_history.append_snapshot(
                _contract_with({"A": 5}), date="2026-04-20", path=path
            )
            entries = [json.loads(line) for line in path.read_text().splitlines()]
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0]["ranks"], {_key("A"): 5})

    def test_retention_cap(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "rank_history.jsonl"
            for i in range(10):
                rank_history.append_snapshot(
                    _contract_with({"P": i + 1}),
                    date=f"2026-01-{i+1:02d}",
                    path=path,
                    max_snapshots=5,
                )
            entries = [json.loads(line) for line in path.read_text().splitlines()]
            self.assertEqual(len(entries), 5)
            # Newest 5 retained, oldest dropped.
            dates = [e["date"] for e in entries]
            self.assertEqual(dates, sorted(dates))
            self.assertEqual(dates[0], "2026-01-06")
            self.assertEqual(dates[-1], "2026-01-10")

    def test_empty_contract_returns_false(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "rank_history.jsonl"
            ok = rank_history.append_snapshot({}, date="2026-04-20", path=path)
            self.assertFalse(ok)
            self.assertFalse(path.exists())


class LoadHistory(unittest.TestCase):
    def test_flips_entries_into_per_player_series(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "rank_history.jsonl"
            rank_history.append_snapshot(
                _contract_with({"A": 3, "B": 1}), date="2026-04-18", path=path
            )
            rank_history.append_snapshot(
                _contract_with({"A": 2, "B": 1}), date="2026-04-19", path=path
            )
            rank_history.append_snapshot(
                _contract_with({"A": 1, "B": 4}), date="2026-04-20", path=path
            )
            series = rank_history.load_history(days=30, path=path)
            self.assertIn(_key("A"), series)
            self.assertEqual(
                series[_key("A")],
                [
                    {"date": "2026-04-18", "rank": 3},
                    {"date": "2026-04-19", "rank": 2},
                    {"date": "2026-04-20", "rank": 1},
                ],
            )
            self.assertEqual(series[_key("B")][-1]["rank"], 4)

    def test_days_window_truncates_oldest(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "rank_history.jsonl"
            for i in range(5):
                rank_history.append_snapshot(
                    _contract_with({"A": i + 1}),
                    date=f"2026-03-{i+1:02d}",
                    path=path,
                )
            series = rank_history.load_history(days=2, path=path)
            self.assertEqual(len(series[_key("A")]), 2)
            self.assertEqual(series[_key("A")][0]["date"], "2026-03-04")

    def test_corrupt_line_is_skipped(self) -> None:
        # A half-written final line must not break the reader.  We
        # simulate by writing one good line + one bad manually.
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "rank_history.jsonl"
            with path.open("w") as f:
                f.write(json.dumps({"date": "2026-04-01", "ranks": {_key("A"): 1}}) + "\n")
                f.write("{not valid json\n")
                f.write(json.dumps({"date": "2026-04-02", "ranks": {_key("A"): 2}}) + "\n")
            series = rank_history.load_history(days=30, path=path)
            self.assertEqual(len(series[_key("A")]), 2)


class StampContract(unittest.TestCase):
    def test_mutates_rows_with_matching_history(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "rank_history.jsonl"
            rank_history.append_snapshot(
                _contract_with({"Ja'Marr Chase": 2}),
                date="2026-04-19",
                path=path,
            )
            rank_history.append_snapshot(
                _contract_with({"Ja'Marr Chase": 1}),
                date="2026-04-20",
                path=path,
            )
            contract = {
                "playersArray": [
                    {"canonicalName": "Ja'Marr Chase", "canonicalConsensusRank": 1, "assetClass": "offense"},
                    {"canonicalName": "Nobody", "canonicalConsensusRank": 500, "assetClass": "offense"},
                ]
            }
            stamped = rank_history.stamp_contract_with_history(contract, path=path)
            self.assertEqual(stamped, 1)
            row = contract["playersArray"][0]
            self.assertIn("rankHistory", row)
            self.assertEqual(len(row["rankHistory"]), 2)
            # Row with no history should NOT be stamped.
            self.assertNotIn("rankHistory", contract["playersArray"][1])

    def test_stamps_legacy_players_dict_for_runtime_view(self) -> None:
        # Regression for Codex PR #217 round 2: the runtime view
        # strips ``playersArray`` and the frontend falls back to the
        # legacy ``players`` dict — stamping must happen there too
        # or sparklines never activate on the default /rankings path.
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "rank_history.jsonl"
            rank_history.append_snapshot(
                _contract_with({"Test Player": 5}),
                date="2026-04-19",
                path=path,
            )
            rank_history.append_snapshot(
                _contract_with({"Test Player": 3}),
                date="2026-04-20",
                path=path,
            )
            contract = {
                "players": {
                    "Test Player": {"assetClass": "offense"},
                    "Nobody": {"assetClass": "offense"},
                }
            }
            stamped = rank_history.stamp_contract_with_history(contract, path=path)
            self.assertEqual(stamped, 1)
            self.assertIn("rankHistory", contract["players"]["Test Player"])
            self.assertEqual(
                len(contract["players"]["Test Player"]["rankHistory"]), 2
            )
            self.assertNotIn("rankHistory", contract["players"]["Nobody"])

    def test_stamps_both_playersArray_and_legacy_dict(self) -> None:
        # When the contract carries both shapes, both must be stamped
        # so the full-view and runtime-view frontends agree.
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "rank_history.jsonl"
            rank_history.append_snapshot(
                _contract_with({"Dual Player": 7}),
                date="2026-04-19",
                path=path,
            )
            contract = {
                "playersArray": [
                    {"canonicalName": "Dual Player", "canonicalConsensusRank": 7, "assetClass": "offense"},
                ],
                "players": {
                    "Dual Player": {"assetClass": "offense"},
                },
            }
            rank_history.stamp_contract_with_history(contract, path=path)
            self.assertIn("rankHistory", contract["playersArray"][0])
            self.assertIn("rankHistory", contract["players"]["Dual Player"])

    def test_cross_universe_series_stay_isolated(self) -> None:
        # Regression for Codex PR #217 round 2 (P2): two same-named
        # players on different asset classes get distinct series.
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "rank_history.jsonl"
            rank_history.append_snapshot(
                {
                    "playersArray": [
                        {"canonicalName": "Clone", "canonicalConsensusRank": 10, "assetClass": "offense"},
                        {"canonicalName": "Clone", "canonicalConsensusRank": 200, "assetClass": "idp"},
                    ],
                },
                date="2026-04-19",
                path=path,
            )
            # Stamp two contract rows that differ only by asset class.
            contract = {
                "playersArray": [
                    {"canonicalName": "Clone", "canonicalConsensusRank": 10, "assetClass": "offense"},
                    {"canonicalName": "Clone", "canonicalConsensusRank": 200, "assetClass": "idp"},
                ]
            }
            rank_history.stamp_contract_with_history(contract, path=path)
            off_hist = contract["playersArray"][0]["rankHistory"]
            idp_hist = contract["playersArray"][1]["rankHistory"]
            # Different ranks at the same date — proves series didn't
            # collide in the log.
            self.assertEqual(off_hist[-1]["rank"], 10)
            self.assertEqual(idp_hist[-1]["rank"], 200)

    def test_empty_log_is_noop(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "rank_history.jsonl"
            contract = _contract_with({"A": 1})
            stamped = rank_history.stamp_contract_with_history(contract, path=path)
            self.assertEqual(stamped, 0)
            self.assertNotIn("rankHistory", contract["playersArray"][0])
