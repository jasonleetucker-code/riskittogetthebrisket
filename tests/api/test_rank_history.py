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
from src.canonical.player_valuation import rank_to_value_for_scope


def _contract_with(
    rank_by_name: dict[str, int],
    asset_class: str = "offense",
    *,
    value_by_name: dict[str, int] | None = None,
) -> dict:
    rows = []
    for name, rank in rank_by_name.items():
        row = {
            "canonicalName": name,
            "canonicalConsensusRank": rank,
            "assetClass": asset_class,
        }
        if value_by_name is not None and name in value_by_name:
            row["rankDerivedValue"] = value_by_name[name]
        rows.append(row)
    return {"playersArray": rows}


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
        self.assertEqual(
            ranks,
            {
                _key("James Williams", "offense"): 78,
                _key("James Williams", "idp"): 215,
            },
        )

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
        c = {
            "playersArray": [
                {"displayName": "Nickname", "canonicalConsensusRank": 9, "assetClass": "offense"}
            ]
        }
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
            self.assertEqual(entries[0]["ranks"], {_key("A"): 1, _key("B"): 2})

    def test_idempotent_per_date(self) -> None:
        # Re-running the same date overwrites — the file has exactly
        # one entry for that date after a re-run with different ranks.
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "rank_history.jsonl"
            rank_history.append_snapshot(_contract_with({"A": 1}), date="2026-04-20", path=path)
            rank_history.append_snapshot(_contract_with({"A": 5}), date="2026-04-20", path=path)
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
            self.assertEqual(len(series[_key("A")]), 3)
            ranks = [p["rank"] for p in series[_key("A")]]
            self.assertEqual(ranks, [3, 2, 1])
            dates = [p["date"] for p in series[_key("A")]]
            self.assertEqual(dates, ["2026-04-18", "2026-04-19", "2026-04-20"])
            # Each point carries a ``val`` — derived from rank when no
            # ``rankDerivedValue`` was stamped on the snapshot rows.
            self.assertTrue(all("val" in p and p["val"] > 0 for p in series[_key("A")]))
            # Rank 1 should map to the curve's top (close to 9999).
            top = series[_key("A")][-1]
            self.assertEqual(top["rank"], 1)
            self.assertGreater(top["val"], 9500)
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

    def test_stamps_canonical_value_when_rank_derived_value_present(self) -> None:
        # New schema: snapshot rows that carry ``rankDerivedValue``
        # write a ``values`` block alongside ``ranks``.  Reading back
        # surfaces the stamped value verbatim — no Hill-curve re-
        # derivation, so the trade-retro grade lines up with the live
        # ``/api/data`` value scale.
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "rank_history.jsonl"
            rank_history.append_snapshot(
                _contract_with(
                    {"Stud": 1},
                    value_by_name={"Stud": 9712},
                ),
                date="2026-04-20",
                path=path,
            )
            entries = [json.loads(line) for line in path.read_text().splitlines()]
            self.assertEqual(entries[0]["values"], {_key("Stud"): 9712})
            series = rank_history.load_history(days=30, path=path)
            self.assertEqual(series[_key("Stud")][-1]["val"], 9712)

    def test_back_fills_value_for_legacy_entries_without_values_block(self) -> None:
        # Older log entries (written before the schema bump) only have
        # ``ranks``.  Reading must back-fill ``val`` from the rank
        # using the asset-class-aware Hill curve so consumers always
        # see the same shape.
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "rank_history.jsonl"
            with path.open("w") as f:
                f.write(
                    json.dumps(
                        {
                            "date": "2026-01-01",
                            "ranks": {
                                _key("Off Rookie", "offense"): 50,
                                _key("Idp Rookie", "idp"): 50,
                            },
                        }
                    )
                    + "\n"
                )
            series = rank_history.load_history(days=30, path=path)
            off_val = series[_key("Off Rookie", "offense")][-1]["val"]
            idp_val = series[_key("Idp Rookie", "idp")][-1]["val"]
            self.assertGreater(off_val, 0)
            self.assertGreater(idp_val, 0)
            # The claim under test is that the asset class GATES which
            # curve fills the gap — so each value must equal what the
            # scope-aware curve produces, and the two must differ.
            #
            # This used to assert ``idp_val > off_val``, on the rationale
            # that "the IDP curve decays slower at rank 50".  That was
            # true of the pre-2026-07-30 constants (IDP 69.50/0.945 vs
            # offense 48.44/1.149) and is no longer: re-fitting both
            # against our own board gave 64.6/0.900 and 65.4/0.910, which
            # cross over.  The direction was never the property worth
            # pinning — ``canonicalConsensusRank`` is a single global
            # ordinal, so the two scopes lie on one relation and any
            # ordering between them at a given rank is a coincidence of
            # the fit.  See docs/legacy-rank-curve-backtest.md.
            self.assertEqual(off_val, rank_to_value_for_scope(50, "offense"))
            self.assertEqual(idp_val, rank_to_value_for_scope(50, "idp"))
            self.assertNotEqual(off_val, idp_val)

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
                    {
                        "canonicalName": "Ja'Marr Chase",
                        "canonicalConsensusRank": 1,
                        "assetClass": "offense",
                    },
                    {
                        "canonicalName": "Nobody",
                        "canonicalConsensusRank": 500,
                        "assetClass": "offense",
                    },
                ]
            }
            stamped = rank_history.stamp_contract_with_history(contract, path=path)
            self.assertEqual(stamped, 1)
            row = contract["playersArray"][0]
            self.assertIn("rankHistory", row)
            self.assertEqual(len(row["rankHistory"]), 2)
            # Row with no history should NOT be stamped.
            self.assertNotIn("rankHistory", contract["playersArray"][1])

    def test_infers_asset_class_for_legacy_rows_without_field(self) -> None:
        # Regression for Codex PR #217 round 3: legacy ``players``
        # dict rows don't carry ``assetClass`` but do carry ``position``.
        # Without position-based inference, every legacy row hashed to
        # ``::unknown`` and missed snapshot keys written as
        # ``::offense`` / ``::idp``.
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "rank_history.jsonl"
            rank_history.append_snapshot(
                _contract_with({"Josh Allen": 1}, asset_class="offense"),
                date="2026-04-19",
                path=path,
            )
            rank_history.append_snapshot(
                _contract_with({"Josh Allen": 1}, asset_class="offense"),
                date="2026-04-20",
                path=path,
            )
            contract = {
                "players": {
                    "Josh Allen": {"position": "QB"},
                    "Micah Parsons": {"position": "DL"},
                }
            }
            stamped = rank_history.stamp_contract_with_history(contract, path=path)
            self.assertEqual(stamped, 1)
            self.assertIn("rankHistory", contract["players"]["Josh Allen"])
            self.assertEqual(len(contract["players"]["Josh Allen"]["rankHistory"]), 2)

    def test_infer_asset_class_position_to_class(self) -> None:
        infer = rank_history._infer_asset_class
        self.assertEqual(infer({"position": "QB"}), "offense")
        self.assertEqual(infer({"position": "RB"}), "offense")
        self.assertEqual(infer({"position": "WR"}), "offense")
        self.assertEqual(infer({"position": "TE"}), "offense")
        self.assertEqual(infer({"position": "DL"}), "idp")
        self.assertEqual(infer({"position": "LB"}), "idp")
        self.assertEqual(infer({"position": "DB"}), "idp")
        self.assertEqual(infer({"position": "EDGE"}), "idp")
        self.assertEqual(infer({"position": "PICK"}), "pick")
        self.assertEqual(infer({"position": "K"}), "unknown")
        # Explicit assetClass wins over inferred.
        self.assertEqual(infer({"position": "DL", "assetClass": "offense"}), "offense")

    def test_infers_pick_from_name_when_no_position_or_asset(self) -> None:
        # Regression for Codex PR #217 round 4: runtime generic-pick
        # rows carry neither ``assetClass`` NOR ``position``, so the
        # only signal is the canonical display name.  Without the
        # name-pattern fallback these would hash to ``::unknown`` and
        # miss snapshot keys written as ``::pick``.
        infer = rank_history._infer_asset_class
        # Early/Mid/Late slot style (most common).
        self.assertEqual(infer({"canonicalName": "2026 Early 1st"}), "pick")
        self.assertEqual(infer({"canonicalName": "2027 Mid 2nd"}), "pick")
        self.assertEqual(infer({"canonicalName": "2028 Late 3rd"}), "pick")
        # Numbered picks ("2026 Pick 1.04").
        self.assertEqual(infer({"canonicalName": "2026 Pick 1.04"}), "pick")
        # Round labels ("2027 Round 2", "2027 R2").
        self.assertEqual(infer({"canonicalName": "2027 Round 2"}), "pick")
        self.assertEqual(infer({"canonicalName": "2027 R2"}), "pick")
        # displayName also works.
        self.assertEqual(infer({"displayName": "2026 Early 1st"}), "pick")
        # Non-pick names still hash to unknown.
        self.assertEqual(infer({"canonicalName": "Josh Allen"}), "unknown")
        # Explicit assetClass/position still win.
        self.assertEqual(
            infer({"canonicalName": "2026 Early 1st", "position": "QB"}),
            "offense",
        )

    def test_stamps_legacy_pick_rows_via_name_pattern(self) -> None:
        # End-to-end: a legacy ``players`` dict row with no assetClass
        # and no position still gets stamped if the name is pick-shaped.
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "rank_history.jsonl"
            rank_history.append_snapshot(
                _contract_with({"2026 Early 1st": 45}, asset_class="pick"),
                date="2026-04-19",
                path=path,
            )
            rank_history.append_snapshot(
                _contract_with({"2026 Early 1st": 40}, asset_class="pick"),
                date="2026-04-20",
                path=path,
            )
            contract = {
                "players": {
                    "2026 Early 1st": {},  # No assetClass, no position.
                }
            }
            stamped = rank_history.stamp_contract_with_history(contract, path=path)
            self.assertEqual(stamped, 1)
            self.assertEqual(len(contract["players"]["2026 Early 1st"]["rankHistory"]), 2)

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
            self.assertEqual(len(contract["players"]["Test Player"]["rankHistory"]), 2)
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
                    {
                        "canonicalName": "Dual Player",
                        "canonicalConsensusRank": 7,
                        "assetClass": "offense",
                    },
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
                        {
                            "canonicalName": "Clone",
                            "canonicalConsensusRank": 10,
                            "assetClass": "offense",
                        },
                        {
                            "canonicalName": "Clone",
                            "canonicalConsensusRank": 200,
                            "assetClass": "idp",
                        },
                    ],
                },
                date="2026-04-19",
                path=path,
            )
            # Stamp two contract rows that differ only by asset class.
            contract = {
                "playersArray": [
                    {
                        "canonicalName": "Clone",
                        "canonicalConsensusRank": 10,
                        "assetClass": "offense",
                    },
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

    def test_legacy_dict_borrows_asset_class_from_players_array(self) -> None:
        # Regression for the 2026-04-22 production audit: the runtime
        # ``/api/data?view=app`` legacy ``players`` dict ships without
        # ``assetClass`` or ``position`` on offense/IDP rows, so the
        # pre-fix stamp only landed on picks (which matched via the
        # name-pattern fallback).  Borrowing ``assetClass`` from the
        # playersArray mirror makes regular players stamp too.
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "rank_history.jsonl"
            rank_history.append_snapshot(
                {
                    "playersArray": [
                        {
                            "canonicalName": "Bare Legacy",
                            "canonicalConsensusRank": 42,
                            "assetClass": "offense",
                        },
                    ],
                },
                date="2026-04-22",
                path=path,
            )
            contract = {
                "playersArray": [
                    {
                        "canonicalName": "Bare Legacy",
                        "canonicalConsensusRank": 42,
                        "assetClass": "offense",
                        "displayName": "Bare Legacy",
                    },
                ],
                "players": {
                    # Mimic the production shape: no assetClass, no position.
                    "Bare Legacy": {"ktcSfTep": 4200, "_composite": 4200},
                },
            }
            rank_history.stamp_contract_with_history(contract, path=path)
            self.assertIn("rankHistory", contract["players"]["Bare Legacy"])
            self.assertEqual(contract["players"]["Bare Legacy"]["rankHistory"][-1]["rank"], 42)


class Coverage(unittest.TestCase):
    """Is the log still being written?

    This log is the only record of what the board said on a past date,
    and its append is best-effort inside a ``try`` that fires only on a
    fresh scrape.  A stall costs one warning line and then silence —
    nobody finds out until a study needs the history, a year later.
    """

    def _write(self, directory: str, dates: list[str], *, with_values: bool = True) -> Path:
        path = Path(directory) / "rank_history.jsonl"
        with path.open("w", encoding="utf-8") as fh:
            for d in dates:
                entry: dict = {"date": d, "ranks": {"A::offense": 1}}
                if with_values:
                    entry["values"] = {"A::offense": 9000}
                fh.write(json.dumps(entry) + "\n")
        return path

    def test_an_absent_log_says_so_rather_than_looking_empty(self):
        """THE CASE THIS EXISTS FOR.  "The log is missing" and "the log
        ran but recorded nothing" must not read the same: the first
        means the append has never worked."""
        with TemporaryDirectory() as tmp:
            out = rank_history.coverage(path=Path(tmp) / "nope.jsonl")
        self.assertFalse(out["exists"])
        self.assertEqual(out["snapshots"], 0)
        self.assertIn("reason", out)

    def test_a_present_but_undated_log_is_distinguished_from_an_absent_one(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "rank_history.jsonl"
            path.write_text('{"ranks": {"A::offense": 1}}\n', encoding="utf-8")
            out = rank_history.coverage(path=path)
        self.assertTrue(out["exists"])
        self.assertEqual(out["snapshots"], 0)
        self.assertIn("reason", out)

    def test_it_reports_the_span_and_the_shape(self):
        with TemporaryDirectory() as tmp:
            path = self._write(tmp, ["2026-01-01", "2026-01-02", "2026-01-03"])
            out = rank_history.coverage(path=path)
        self.assertEqual(out["snapshots"], 3)
        self.assertEqual(out["firstDate"], "2026-01-01")
        self.assertEqual(out["lastDate"], "2026-01-03")
        self.assertEqual(out["spanDays"], 3)
        self.assertEqual(out["missingDays"], 0)
        self.assertEqual(out["snapshotsWithValues"], 3)
        self.assertEqual(out["retentionCap"], rank_history.MAX_SNAPSHOTS)

    def test_gaps_inside_the_span_are_counted(self):
        """A snapshot COUNT reveals nothing on its own — 400 entries
        could be 400 consecutive days or a block that stopped growing in
        March.  Gaps against the calendar are what expose a stall."""
        with TemporaryDirectory() as tmp:
            path = self._write(tmp, ["2026-01-01", "2026-01-10"])
            out = rank_history.coverage(path=path)
        self.assertEqual(out["snapshots"], 2)
        self.assertEqual(out["spanDays"], 10)
        self.assertEqual(out["missingDays"], 8)

    def test_only_staleness_catches_a_log_that_stopped_growing(self):
        """Span, gap count and snapshot count are all PERFECT on a log
        whose newest entry is years old.  ``staleDays`` is the only
        field that catches the live-stall case."""
        with TemporaryDirectory() as tmp:
            path = self._write(tmp, ["2020-01-01", "2020-01-02", "2020-01-03"])
            out = rank_history.coverage(path=path)
        self.assertEqual(out["missingDays"], 0, "the gap check alone calls this healthy")
        self.assertGreater(out["staleDays"], 365)

    def test_duplicate_dates_count_once(self):
        """The writer is idempotent per UTC date; the reader must agree,
        or a same-day rewrite would look like extra coverage."""
        with TemporaryDirectory() as tmp:
            path = self._write(tmp, ["2026-01-01", "2026-01-01", "2026-01-02"])
            out = rank_history.coverage(path=path)
        self.assertEqual(out["snapshots"], 2)

    def test_a_values_less_log_is_reported_as_such(self):
        """Legacy entries carry ranks but no values.  A future backtest
        needs values, so "we have 400 snapshots" must not conceal "none
        of them are usable for it"."""
        with TemporaryDirectory() as tmp:
            path = self._write(tmp, ["2026-01-01"], with_values=False)
            out = rank_history.coverage(path=path)
        self.assertEqual(out["snapshots"], 1)
        self.assertEqual(out["snapshotsWithValues"], 0)

    def test_it_never_raises_on_a_corrupt_log(self):
        """A diagnostic that can take down the thing it reports on is
        worse than no diagnostic."""
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "rank_history.jsonl"
            path.write_text('{"date": "2026-01-01"}\nnot json at all\n', encoding="utf-8")
            out = rank_history.coverage(path=path)
        self.assertTrue(out["exists"])
        self.assertEqual(out["snapshots"], 1)
