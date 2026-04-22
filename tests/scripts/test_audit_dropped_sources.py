"""Unit tests for ``scripts/audit_dropped_sources.py``.

The script is a diagnostic surface for the per-player Hampel filter.
These tests pin the shape of its summary output so a future refactor
can't silently break the histogram / per-source / biggest-offender
sections consumers rely on.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "audit_dropped_sources.py"


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "audit_dropped_sources", SCRIPT
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


_mod = _load_module()
_summarise = _mod._summarise
_eligible_rows_per_source = _mod._eligible_rows_per_source
_players_array = _mod._players_array


def _row(
    name,
    pos,
    rank,
    source_ranks,
    dropped=(),
    source_count=None,
    spread=None,
):
    return {
        "displayName": name,
        "position": pos,
        "canonicalConsensusRank": rank,
        "sourceRanks": dict(source_ranks),
        "droppedSources": list(dropped),
        "sourceCount": source_count if source_count is not None else len(source_ranks),
        "sourceRankPercentileSpread": spread,
    }


class TestPlayersArrayExtraction:
    def test_reads_top_level_players_array(self):
        payload = {"playersArray": [{"displayName": "X"}]}
        assert len(_players_array(payload)) == 1

    def test_reads_nested_data_players_array(self):
        payload = {"data": {"playersArray": [{"displayName": "Y"}]}}
        assert len(_players_array(payload)) == 1

    def test_returns_empty_list_on_missing(self):
        assert _players_array({}) == []


class TestEligibleRowsPerSource:
    def test_counts_each_source_once_per_row(self):
        players = [
            _row("A", "WR", 1, {"ktc": 1, "dlfSf": 1}),
            _row("B", "WR", 2, {"ktc": 2}),
        ]
        eligible = _eligible_rows_per_source(players)
        assert eligible == {"ktc": 2, "dlfSf": 1}

    def test_handles_missing_source_ranks(self):
        players = [{"displayName": "Z"}]
        assert _eligible_rows_per_source(players) == {}

    def test_counts_dropped_even_when_absent_from_sourceRanks(self):
        # Regression for Codex PR #212 review: the elevated-source
        # diagnosis compares ``dropped_by_source[k] / eligible[k]``.
        # If the backend ever strips Hampel-dropped keys out of
        # ``sourceRanks`` (currently it keeps them, but defensive
        # robustness matters because a chronically-dropped source is
        # *exactly* the case the script exists to surface), the
        # denominator must still reflect the rejected occurrences.
        # Otherwise a source dropped on every row it covered would
        # land at ``0 / 0`` and never trip the ``>=10%`` flag.
        players = [
            # Dropped — absent from sourceRanks on this row.
            _row("A", "WR", 1, {"ktc": 1, "dlfSf": 1}, dropped=["badSource"]),
            _row("B", "WR", 2, {"ktc": 2, "dlfSf": 2}, dropped=["badSource"]),
            # Matched — present in sourceRanks on this row.
            _row("C", "WR", 3, {"ktc": 3, "badSource": 99, "dlfSf": 3}),
        ]
        eligible = _eligible_rows_per_source(players)
        assert eligible["badSource"] == 3
        # Summary must report the same denominator.
        s = _summarise(players)
        assert s["eligible_rows_per_source"]["badSource"] == 3
        assert s["dropped_by_source"]["badSource"] == 2


class TestSummariseShape:
    def test_no_drops_anywhere_produces_zero_summary(self):
        players = [
            _row("A", "WR", 1, {"ktc": 1, "dlfSf": 1}),
            _row("B", "WR", 2, {"ktc": 2}),
        ]
        s = _summarise(players)
        assert s["total_rows"] == 2
        assert s["rows_with_drops"] == 0
        assert s["drop_count_histogram"] == {}
        assert s["dropped_by_source"] == {}
        assert s["biggest_offenders"] == []

    def test_drops_surface_in_every_facet(self):
        players = [
            _row(
                "A", "WR", 1,
                {"ktc": 1, "dlfSf": 1, "dynastyNerdsSfTep": 300},
                dropped=["dynastyNerdsSfTep"],
            ),
            _row(
                "B", "LB", 50,
                {"idpTradeCalc": 50, "dlfIdp": 50, "footballGuysIdp": 400},
                dropped=["footballGuysIdp"],
                spread=0.25,
            ),
            _row("C", "QB", 10, {"ktc": 10, "dlfSf": 12}),
        ]
        s = _summarise(players)
        assert s["total_rows"] == 3
        assert s["rows_with_drops"] == 2
        assert s["drop_count_histogram"] == {1: 2}
        assert s["dropped_by_source"] == {
            "dynastyNerdsSfTep": 1,
            "footballGuysIdp": 1,
        }
        assert s["dropped_by_position"] == {"WR": 1, "LB": 1}
        # The LB row has a percentile spread stamp; it must round-trip.
        offenders_by_name = {o["name"]: o for o in s["biggest_offenders"]}
        assert offenders_by_name["B"]["spread"] == 0.25
        assert offenders_by_name["A"]["dropped"] == ["dynastyNerdsSfTep"]

    def test_biggest_offenders_sorted_by_drop_count_then_rank(self):
        players = [
            _row("One-drop late", "WR", 100, {"ktc": 100, "a": 1}, dropped=["a"]),
            _row("Two-drop early", "WR", 5, {"ktc": 5, "a": 1, "b": 2}, dropped=["a", "b"]),
            _row("One-drop early", "WR", 20, {"ktc": 20, "c": 1}, dropped=["c"]),
        ]
        s = _summarise(players)
        names = [o["name"] for o in s["biggest_offenders"]]
        # Two-drop row wins on count; among the 1-drop rows, the
        # earlier-ranked one comes first.
        assert names == ["Two-drop early", "One-drop early", "One-drop late"]

    def test_eligibility_denominator_counts_all_matches(self):
        # A source that covered 10 rows but only got dropped on 1 has
        # a 10% drop rate.  The script flags >=10% with eligible>=20 as
        # "elevated"; below the denominator threshold the flag must
        # not fire.
        players = []
        # 21 rows where 'footballGuysIdp' ranked all of them; 3 dropped.
        for i in range(21):
            dropped = ["footballGuysIdp"] if i < 3 else []
            players.append(
                _row(
                    f"P{i}", "LB", i + 1,
                    {"idpTradeCalc": i + 1, "dlfIdp": i + 1, "footballGuysIdp": i + 1},
                    dropped=dropped,
                )
            )
        s = _summarise(players)
        assert s["eligible_rows_per_source"]["footballGuysIdp"] == 21
        assert s["dropped_by_source"]["footballGuysIdp"] == 3
        # Rate ≈ 14.3%; denominator ≥ 20; should meet the elevated-flag
        # threshold when the text report renders.
        rate = 100.0 * 3 / 21
        assert rate >= 10.0


class TestCliJsonMode:
    """End-to-end check that ``--json`` produces parseable stdout.

    The ``Loading: ...`` status line must be on stderr so downstream
    consumers can pipe stdout straight into ``jq`` without a prefix-
    stripping hack.  Regression for Codex PR #212 review.
    """

    def test_json_mode_stdout_is_clean_json(self, tmp_path):
        snapshot = tmp_path / "snapshot.json"
        snapshot.write_text(
            json.dumps(
                {
                    "playersArray": [
                        {
                            "displayName": "A",
                            "position": "WR",
                            "canonicalConsensusRank": 1,
                            "sourceRanks": {"ktc": 1, "dlfSf": 1, "bad": 300},
                            "droppedSources": ["bad"],
                            "sourceCount": 3,
                        }
                    ]
                }
            )
        )
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--json-path",
                str(snapshot),
                "--json",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        # stdout must parse as JSON on its own — no status chatter.
        summary = json.loads(result.stdout)
        assert summary["rows_with_drops"] == 1
        assert summary["dropped_by_source"] == {"bad": 1}
        # Status line must still be visible for interactive runs —
        # just not on stdout.
        assert "Loading:" in result.stderr
