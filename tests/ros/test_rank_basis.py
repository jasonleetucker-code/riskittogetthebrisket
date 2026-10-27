"""One ROS source key, one rank basis — and a guard that reports when not.

Regression for the 2026-09-16 DraftSharks defect (automated refresh
``907dfee4d``).  The vendor's superflex ROS board stopped listing IDP
players; the adapter unioned the vendor's IDP-only board in under the same
``draftSharksRosSf`` key, so every IDP DraftSharks vote silently moved from
"rank among all positions" onto "rank among IDPs" (top LB 47/250 -> 1/440,
score 30.3 -> 100.0).  Before that date the same union split the IDP group
across the two bases inside one key.

The fixtures below reproduce both historical shapes in miniature:

* PRE  (``907dfee4d~1``): superflex board carries offense AND some IDPs;
  the idp board carries IDPs, overlapping it partially.
* POST (``907dfee4d``): superflex board carries no IDPs; the idp board
  carries all of them.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from unittest import mock

import pytest

from src.ros import rank_basis, scrape
from src.ros.aggregate import RankedRow, SourceSnapshot, aggregate
from src.ros.sources import draftsharks_ros as ds
from src.ros.sources import draftsharks_ros_idp, get_ros_source

_HEADER = ["canonicalName", "sourceName", "position", "team", "rank", "total_ranked", "projection"]

PRE_SF = [
    ("Josh Allen", "QB", 1),
    ("Bijan Robinson", "RB", 2),
    ("Ja'Marr Chase", "WR", 3),
    ("Carson Schwesinger", "LB", 4),
    ("Aidan Hutchinson", "DL", 5),
    ("Brock Bowers", "TE", 6),
]
PRE_IDP = [
    ("Carson Schwesinger", "LB", 1),
    ("Jack Campbell", "LB", 2),
    ("Aidan Hutchinson", "DE", 3),
    ("Kyle Hamilton", "S", 4),
]
POST_SF = [r for r in PRE_SF if r[1] not in ("LB", "DL")]
POST_IDP = PRE_IDP


def _write(path: Path, rows: list[tuple[str, str, int]]) -> None:
    with path.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(_HEADER)
        for name, pos, rank in rows:
            w.writerow(["", name, pos, "", rank, len(rows), ""])


@pytest.fixture()
def boards(tmp_path: Path):
    def _set(sf, idp, *, dyn_sf=None, dyn_idp=None):
        paths = {}
        for label, rows in (("sf", sf), ("idp", idp)):
            p = tmp_path / f"{label}.csv"
            _write(p, rows)
            paths[label] = p
        missing = tmp_path / "missing.csv"
        patches = [
            mock.patch.object(ds, "DS_ROS_SF_CSV", paths["sf"]),
            mock.patch.object(ds, "DS_ROS_IDP_CSV", paths["idp"]),
            mock.patch.object(ds, "DS_DYNASTY_SF_CSV", dyn_sf or missing),
            mock.patch.object(ds, "DS_DYNASTY_IDP_CSV", dyn_idp or missing),
        ]
        for p in patches:
            p.start()
        return patches

    started: list = []

    def _go(*a, **kw):
        started.extend(_set(*a, **kw))

    yield _go
    for p in started:
        p.stop()


def _both(boards_fixture, sf, idp):
    boards_fixture(sf, idp)
    return (
        ds.scrape({"key": "draftSharksRosSf"}),
        draftsharks_ros_idp.scrape({"key": "draftSharksRosIdp"}),
    )


# ── 1. one key, one rank basis, in both historical shapes ─────────────────


@pytest.mark.parametrize("shape", ["pre", "post"])
def test_each_key_publishes_exactly_one_rank_basis(boards, shape):
    sf, idp = (PRE_SF, PRE_IDP) if shape == "pre" else (POST_SF, POST_IDP)
    sf_res, idp_res = _both(boards, sf, idp)
    for res in (sf_res, idp_res):
        report = rank_basis.rank_basis_report(res.rows)
        assert report["mixedRankBasis"] is False, (res.source_key, report)
        assert report["basisDeclared"] is True
        assert report["groupsSplitAcrossBases"] == []
    assert {r["rankBasis"] for r in sf_res.rows} == {ds.BASIS_ROS_SF}
    assert {r["rankBasis"] for r in idp_res.rows} == {ds.BASIS_ROS_IDP}


def test_post_shape_idp_votes_under_the_idp_key_on_their_own_board(boards):
    sf_res, idp_res = _both(boards, POST_SF, POST_IDP)
    assert not any(r["position"] in ("LB", "DE", "DL", "S") for r in sf_res.rows)
    got = {r["sourceName"]: (r["rank"], r["total_ranked"]) for r in idp_res.rows}
    # Native rank and the board's own total — nothing renumbered or translated.
    assert got == {
        "Carson Schwesinger": (1, 4),
        "Jack Campbell": (2, 4),
        "Aidan Hutchinson": (3, 4),
        "Kyle Hamilton": (4, 4),
    }
    assert idp_res.diagnostics["withheld"][rank_basis.RANK_BASIS_MISMATCH] == 0


def test_pre_shape_superflex_board_keeps_its_idps_and_idp_key_withholds_them(boards):
    sf_res, idp_res = _both(boards, PRE_SF, PRE_IDP)
    sf_names = {r["sourceName"] for r in sf_res.rows}
    assert {"Carson Schwesinger", "Aidan Hutchinson"} <= sf_names
    idp_names = {r["sourceName"] for r in idp_res.rows}
    assert idp_names == {"Jack Campbell", "Kyle Hamilton"}
    assert idp_res.diagnostics["withheld"][rank_basis.RANK_BASIS_MISMATCH] == 2


def test_offense_rows_on_the_idp_page_never_vote_a_second_time(boards):
    """The idp URL has been served as a full 1QB board before."""
    full_board = [("Josh Allen", "QB", 1), ("Jack Campbell", "LB", 2), ("Bijan Robinson", "RB", 3)]
    _sf, idp_res = _both(boards, POST_SF, full_board)
    assert [r["sourceName"] for r in idp_res.rows] == ["Jack Campbell"]
    # Rank and total stay on the page's own population.
    assert (idp_res.rows[0]["rank"], idp_res.rows[0]["total_ranked"]) == (2, 3)
    assert idp_res.diagnostics["withheld"]["not_idp_group"] == 2


def test_cross_group_name_collision_is_withheld_not_folded_into_the_other_player(boards):
    """Measured on the 2026-10-27 boards: WR Justin Jefferson (SF 24/250) and
    an LB Justin Jefferson (idp 456/486).  The aggregate keys by canonical
    name, so emitting the LB would fold his vote into the WR's row."""
    sf = POST_SF + [("Justin Jefferson", "WR", 7)]
    idp = POST_IDP + [("Justin Jefferson", "LB", 5)]
    _sf, idp_res = _both(boards, sf, idp)
    assert "Justin Jefferson" not in {r["sourceName"] for r in idp_res.rows}
    assert idp_res.diagnostics["withheld"][ds.NAME_COLLISION_WITH_SUPERFLEX] == 1
    assert idp_res.diagnostics["withheld"][rank_basis.RANK_BASIS_MISMATCH] == 0


def test_idp_key_fails_closed_without_any_idp_board(boards):
    _sf, idp_res = _both(boards, POST_SF, [])
    assert idp_res.status == "failed"
    assert idp_res.rows == []


def test_idp_key_falls_back_to_the_dynasty_idp_proxy(boards, tmp_path):
    proxy = tmp_path / "dyn_idp.csv"
    with proxy.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["Player", "Fantasy Position", "Team", "Rank"])
        w.writerow(["Jack Campbell", "LB", "DET", "1"])
    boards(POST_SF, [], dyn_idp=proxy)
    res = draftsharks_ros_idp.scrape({"key": "draftSharksRosIdp"})
    assert res.status == "ok"
    assert res.diagnostics["sourceMode"] == "dynasty_proxy"
    assert {r["rankBasis"] for r in res.rows} == {ds.BASIS_DYNASTY_IDP_PROXY}


def test_registry_declares_the_idp_board_as_its_own_idp_source():
    entry = get_ros_source("draftSharksRosIdp")
    assert entry is not None
    assert entry["is_idp"] is True and entry["is_ros"] is True
    assert entry["is_superflex"] is False and entry["is_dynasty"] is False
    assert entry["scraper"] == "src.ros.sources.draftsharks_ros_idp"


# ── 2. the aggregate still sees one DraftSharks vote per player ───────────


def _snap(key: str, rows: list[dict], *, is_idp: bool, is_superflex: bool) -> SourceSnapshot:
    return SourceSnapshot(
        source_key=key,
        base_weight=1.25,
        is_ros=True,
        is_dynasty=False,
        is_te_premium=False,
        is_superflex=is_superflex,
        is_2qb=False,
        is_idp=is_idp,
        status="ok",
        scraped_at="2026-10-27T00:00:00+00:00",
        player_count=len(rows),
        has_valid_cache=True,
        rows=[
            RankedRow(
                canonical_name=r["sourceName"].lower(),
                position=r["position"],
                rank=r["rank"],
                total_ranked=r["total_ranked"],
            )
            for r in rows
        ],
    )


@pytest.mark.parametrize("shape", ["pre", "post"])
def test_one_draftsharks_vote_per_player_across_both_keys(boards, shape):
    sf, idp = (PRE_SF, PRE_IDP) if shape == "pre" else (POST_SF, POST_IDP)
    sf_res, idp_res = _both(boards, sf, idp)
    agg = aggregate(
        [
            _snap("draftSharksRosSf", sf_res.rows, is_idp=False, is_superflex=True),
            _snap("draftSharksRosIdp", idp_res.rows, is_idp=True, is_superflex=False),
        ],
        league={"is_superflex": True, "is_2qb": False, "is_te_premium": True, "idp_enabled": True},
    )
    for player in agg:
        assert player["sourceCount"] == 1, player
        assert len(player["contributors"]) == 1, player


# ── 3. the guard (pure) ───────────────────────────────────────────────────


def _rows(spec):
    return [
        {"position": pos, "total_ranked": total, **({"rankBasis": basis} if basis else {})}
        for pos, total, basis in spec
    ]


def test_guard_flags_a_source_whose_rows_mix_bases():
    """The pre-fix DraftSharks union, as the guard sees it (no declared basis)."""
    report = rank_basis.rank_basis_report(
        _rows([("QB", 250, None), ("LB", 250, None), ("LB", 440, None), ("DL", 440, None)])
    )
    assert report["mixedRankBasis"] is True
    assert report["basisDeclared"] is False
    assert report["groupsSplitAcrossBases"] == ["IDP"]
    assert rank_basis.MIXED_RANK_BASIS in report["issues"]
    assert f"{rank_basis.GROUP_SPLIT_ACROSS_BASES}:IDP" in report["issues"]


def test_guard_is_quiet_on_a_single_board():
    report = rank_basis.rank_basis_report(_rows([("QB", 300, None), ("LB", 300, None)]))
    assert report["issues"] == []
    assert report["groupCoverage"] == {"IDP": 1, "OFFENSE": 1}


def test_guard_reports_vanished_group_coverage_between_refreshes():
    before = rank_basis.rank_basis_report(_rows([("QB", 250, "b:sf"), ("LB", 250, "b:sf")]))
    after = rank_basis.diagnose(_rows([("QB", 250, "b:sf")]), before)
    assert f"{rank_basis.GROUP_COVERAGE_VANISHED}:IDP" in after["issues"]


def test_guard_reports_a_group_moving_onto_another_basis():
    """The 907dfee4d signature: coverage barely moves, the basis under it does."""
    before = rank_basis.rank_basis_report(
        _rows([("QB", 250, "b:sf"), ("LB", 250, "b:sf"), ("LB", 440, "b:idp")])
    )
    after = rank_basis.diagnose(_rows([("QB", 250, "b:sf"), ("LB", 440, "b:idp")]), before)
    assert f"{rank_basis.GROUP_RANK_BASIS_CHANGED}:IDP" in after["transitionIssues"]


def test_guard_first_run_is_a_baseline_not_a_pass_or_an_alarm():
    out = rank_basis.diagnose(_rows([("QB", 10, "b")]), None)
    assert out["baseline"] is True
    assert out["transitionIssues"] == []


def test_inferred_bases_are_not_compared_for_basis_change():
    """A board changing length changes its inferred id; that is not a basis change."""
    before = rank_basis.rank_basis_report(_rows([("QB", 250, None)]))
    after = rank_basis.diagnose(_rows([("QB", 251, None)]), before)
    assert after["transitionIssues"] == []


# ── 4. wired into the run status (index.json -> /api/ros/status) ──────────


def _run(tmp_path: Path, rows: list[dict], key: str = "demo") -> dict:
    src = {"key": key, "base_weight": 1.0, "scraper": "unused", "is_ros": True}

    def fake_adapter(src_meta):
        return scrape.ScrapeResult(
            source_key=key,
            status="ok",
            rows=[dict(r) for r in rows],
            started_at="2026-10-27T00:00:00+00:00",
            completed_at="2026-10-27T00:00:00+00:00",
            player_count=len(rows),
            diagnostics={"sourceMode": "ros", "withheld": {rank_basis.RANK_BASIS_MISMATCH: 3}},
        )

    with (
        mock.patch.object(scrape, "ROS_DATA_DIR", tmp_path),
        mock.patch.object(scrape, "enabled_ros_sources", return_value=[src]),
        mock.patch.object(scrape, "_invoke_adapter", side_effect=fake_adapter),
        mock.patch.object(scrape, "aggregate", return_value=[]),
        mock.patch.object(scrape, "_refresh_team_strength_snapshot", return_value={}),
        mock.patch.object(scrape, "_refresh_power_snapshots", return_value={}),
        mock.patch.object(scrape, "_refresh_sim_caches", return_value={}),
    ):
        scrape.run_all(canonical_universe={"alpha", "beta"})
    return json.loads((tmp_path / "runs" / "index.json").read_text())["sources"][key]


def _row(name, pos, total, basis):
    return {
        "sourceName": name,
        "canonicalName": name.lower(),
        "position": pos,
        "team": "",
        "rank": 1,
        "total_ranked": total,
        "projection": "",
        "rankBasis": basis,
    }


def test_run_status_carries_rank_basis_and_flags_the_transition(tmp_path):
    first = _run(tmp_path, [_row("Alpha", "QB", 2, "b:sf"), _row("Beta", "LB", 2, "b:sf")])
    assert first["rank_basis"]["baseline"] is True
    assert first["rank_basis"]["withheld"] == {rank_basis.RANK_BASIS_MISMATCH: 3}
    assert first["source_mode"] == "ros"

    second = _run(tmp_path, [_row("Alpha", "QB", 1, "b:sf")])
    assert f"{rank_basis.GROUP_COVERAGE_VANISHED}:IDP" in second["rank_basis"]["issues"]
    # Reporting only: the run itself is not demoted.
    assert second["status"] == "ok"
