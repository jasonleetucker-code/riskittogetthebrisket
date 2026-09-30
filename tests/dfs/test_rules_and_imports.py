"""DFS rule registry honesty + untrusted-file import behaviour."""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from src.dfs import rules
from src.dfs.imports import (
    ImportError_,
    apply_platform_average,
    apply_projection_csv,
    parse_draftkings_salaries,
    parse_fanduel_players,
)

FIX = Path(__file__).parent / "fixtures"
REPO = Path(__file__).resolve().parents[2]


def _dk_text() -> str:
    return (FIX / "synthetic_dk_nfl_classic_salaries.csv").read_text(encoding="utf-8")


# ── rules ─────────────────────────────────────────────────────────────


def test_every_requested_sport_and_platform_has_an_honest_capability_row():
    matrix = rules.capability_matrix()
    for sport in rules.SPORTS:
        for platform in rules.PLATFORMS:
            rows = [r for r in matrix if r["sport"] == sport and r["platform"] == platform]
            assert rows, (sport, platform)
            for r in rows:
                assert r["readiness"] in rules.READINESS
                if r["readiness"] != "money_ready":
                    assert r["reason"], r


def test_unverified_rules_can_never_read_as_money_ready():
    for rs in rules.load_rulesets().values():
        if not rs.verified or not rs.export_verified:
            assert rs.readiness == "research_only"
        if rs.verification["state"] == "unverified":
            assert rs.verification.get("blocker")


def test_a_verified_ruleset_must_cite_evidence(tmp_path):
    data = json.loads(rules.RULESETS_PATH.read_text(encoding="utf-8"))
    data["rulesets"][0]["verification"] = {"state": "verified", "evidence": []}
    p = tmp_path / "r.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(rules.RulesetError):
        rules.load_rulesets(p)


def test_export_header_must_equal_slot_order(tmp_path):
    data = json.loads(rules.RULESETS_PATH.read_text(encoding="utf-8"))
    data["rulesets"][0]["export"]["header"] = list(
        reversed(data["rulesets"][0]["export"]["header"])
    )
    p = tmp_path / "r.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(rules.RulesetError):
        rules.load_rulesets(p)


# ── imports ───────────────────────────────────────────────────────────


def test_draftkings_salary_file_parses_with_ids_as_strings_and_utc_kickoffs():
    athletes, report = parse_draftkings_salaries("﻿" + _dk_text())
    assert report.rows_used == 84 and not report.rejected
    a = athletes[0]
    assert isinstance(a.player_id, str) and a.game == "AAA@BBB" and a.opponent == "BBB"
    # 1:00 PM ET on 2026-10-04 is EDT (UTC-4).
    assert a.start_time_utc == "2026-10-04T17:00:00+00:00"
    assert a.projection is None  # nothing imported yet: missing, not zero


def test_kickoff_after_dst_ends_uses_standard_time():
    text = "Position,Name,ID,Salary,Game Info,TeamAbbrev\nQB,X,1,5000,AAA@BBB 11/08/2026 01:00PM ET,AAA\n"
    athletes, _ = parse_draftkings_salaries(text)
    assert athletes[0].start_time_utc == "2026-11-08T18:00:00+00:00"


def test_header_mismatch_fails_loud():
    with pytest.raises(ImportError_) as exc:
        parse_draftkings_salaries("Player,Cost\nA,1\n")
    assert exc.value.code == "HEADER_MISMATCH"
    assert "expected" in exc.value.detail


def test_bad_rows_are_reported_not_guessed():
    text = (
        "Position,Name,ID,Salary,Game Info,TeamAbbrev\n"
        "QB,Good,1,5000,AAA@BBB 10/04/2026 01:00PM ET,AAA\n"
        "QB,Dupe,1,5000,AAA@BBB 10/04/2026 01:00PM ET,AAA\n"
        "RB,NoSalary,2,abc,AAA@BBB 10/04/2026 01:00PM ET,AAA\n"
        'RB,Formula,"=HYPERLINK(1)",4000,AAA@BBB 10/04/2026 01:00PM ET,AAA\n'
    )
    athletes, report = parse_draftkings_salaries(text)
    assert [a.player_id for a in athletes] == ["1"]
    reasons = sorted(r["reason"] for r in report.rejected)
    assert reasons == ["duplicate_player_id", "invalid_or_missing_player_id", "invalid_salary"]


def test_oversized_file_is_refused():
    with pytest.raises(ImportError_) as exc:
        parse_draftkings_salaries("Position,Name,ID,Salary,TeamAbbrev\n" + "x" * (3 * 1024 * 1024))
    assert exc.value.code == "FILE_TOO_LARGE"


def test_projection_join_by_id_and_by_name_team_with_quarantine():
    athletes, _ = parse_draftkings_salaries(_dk_text())
    report = apply_projection_csv(
        athletes, (FIX / "synthetic_dk_nfl_classic_projections.csv").read_text(encoding="utf-8")
    )
    assert report["matched"] == 84 and report["athletesWithoutProjection"] == 0
    assert all(a.projection_match == "platform_id" for a in athletes)

    athletes, _ = parse_draftkings_salaries(_dk_text())
    # Two slate athletes with the same normalized name + team → ambiguous, never first-wins.
    athletes[1].name = athletes[0].name
    text = f"Name,Team,Proj\n{athletes[0].name},AAA,20\nSyn AAA RB1,AAA,11.5\nNobody,ZZZ,3\nSyn AAA WR1,AAA,\n"
    report = apply_projection_csv(athletes, text)
    assert report["ambiguous"] and report["ambiguous"][0]["reason"] == "ambiguous_identity"
    assert athletes[0].projection is None and athletes[1].projection is None
    assert report["unmatched"][0]["reason"] == "no_slate_athlete"
    assert report["invalid"][0]["reason"] == "projection_not_numeric_or_blank"
    rb1 = next(a for a in athletes if a.name == "Syn AAA RB1")
    assert rb1.projection == 11.5 and rb1.projection_match == "name_team"


def test_disagreeing_projection_rows_leave_the_athlete_unresolved():
    athletes, _ = parse_draftkings_salaries(_dk_text())
    pid = athletes[0].player_id
    report = apply_projection_csv(athletes, f"ID,Projection\n{pid},10\n{pid},12\n")
    assert report["conflicts"] and athletes[0].projection is None


def test_platform_average_is_opt_in_and_labelled():
    athletes, _ = parse_draftkings_salaries(_dk_text())
    assert all(a.projection is None for a in athletes)
    n = apply_platform_average(athletes)
    assert n == 84
    assert {a.projection_source for a in athletes} == {"platform_season_average"}


def test_fanduel_players_zero_games_played_means_no_average():
    text = (FIX / "synthetic_fd_nfl_classic_players.csv").read_text(encoding="utf-8")
    athletes, report = parse_fanduel_players(text)
    assert report.rows_used == 84
    assert athletes[0].player_id.startswith("123-")
    lines = text.splitlines()
    lines[1] = lines[1].replace(",4,", ",0,", 1)
    athletes, _ = parse_fanduel_players("\n".join(lines))
    assert athletes[0].platform_average is None


# ── domain separation ─────────────────────────────────────────────────

_FORBIDDEN = (
    "src.api.data_contract",
    "src.canonical",
    "src.consensus_edge",
    "src.trade",
    "src.bdvm",
    "src.league_intel",
    "src.model_registry",
)


def test_dfs_never_imports_dynasty_valuation_owners():
    for path in (REPO / "src" / "dfs").glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for n in names:
                assert not n.startswith(_FORBIDDEN), f"{path.name} imports {n}"


def test_supplied_id_is_authoritative_in_projection_join():
    athletes, _ = parse_draftkings_salaries(_dk_text())
    a0 = athletes[0]
    text = (
        "ID,Name,Team,Projection\n"
        f"{a0.player_id},Someone Else,{a0.team},10\n"  # id names a different player
        f"123456789,{athletes[1].name},{athletes[1].team},11\n"  # id not on slate: no name fallback
    )
    report = apply_projection_csv(athletes, text)
    assert athletes[0].projection is None and athletes[1].projection is None
    assert report["conflicts"][0]["reason"] == "id_name_mismatch"
    assert report["unmatched"][0]["reason"] == "platform_id_not_on_slate"


def test_leading_dash_ids_are_rejected_at_import():
    text = "Position,Name,ID,Salary,Game Info,TeamAbbrev\nQB,X,-A1,5000,AAA@BBB 10/04/2026 01:00PM ET,AAA\n"
    athletes, report = parse_draftkings_salaries(text)
    assert athletes == [] and report.rejected[0]["reason"] == "invalid_or_missing_player_id"


# ── owner-imported projected ownership ────────────────────────────────


def test_ownership_needs_a_stated_unit_and_missing_is_never_zero():
    from src.dfs.imports import apply_ownership_csv

    athletes, _ = parse_draftkings_salaries(_dk_text())
    with pytest.raises(ImportError_) as exc:
        apply_ownership_csv(athletes, "ID,Own%\n900001,35\n", unit="")
    assert exc.value.code == "OWNERSHIP_UNIT_REQUIRED"
    report = apply_ownership_csv(
        athletes, "ID,Own%\n900001,35%\n900002,0.5\n900003,140\n", unit="percent"
    )
    a1, a2, a3 = athletes[0], athletes[1], athletes[2]
    assert (a1.ownership, a2.ownership, a3.ownership) == (35.0, 0.5, None)
    assert report["invalid"][0]["reason"] == "ownership_out_of_range_for_unit"
    assert athletes[4].ownership is None  # not in the file: unknown, not 0%


def test_fraction_unit_is_scaled_to_percent():
    from src.dfs.imports import apply_ownership_csv

    athletes, _ = parse_draftkings_salaries(_dk_text())
    apply_ownership_csv(athletes, "ID,Ownership\n900001,0.35\n", unit="fraction")
    assert athletes[0].ownership == 35.0
