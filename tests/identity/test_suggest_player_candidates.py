"""``suggest_player_candidates`` — suggestions only, never a resolution."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.identity import resolution as R

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "identity_directory_subset.json"


@pytest.fixture(scope="module")
def index():
    return R.build_sleeper_index(json.loads(FIXTURE.read_text(encoding="utf-8"))["players"])


def test_ocr_surname_typo_is_refused_by_v2_but_suggested(index):
    res = R.resolve_canonical_v2(index, name="Patrick Mahomse", position="QB")
    assert res.status == R.UNRESOLVED and res.reason == R.REASON_NO_CANDIDATE
    got = R.suggest_player_candidates(index, "Patrick Mahomse", position="QB")
    assert [s.sleeper_id for s in got][:1] == ["4046"]
    assert got[0].display_name == "Patrick Mahomes"
    assert 0.80 <= got[0].score < 1.0


def test_suggestions_carry_no_status(index):
    got = R.suggest_player_candidates(index, "Bijan Robinsen")
    assert got and isinstance(got[0], R.PlayerSuggestion)
    assert not hasattr(got[0], "status")
    assert not isinstance(got[0], R.Resolution)


def test_position_group_filter(index):
    # "Josh Allen" homonyms: QB BUF and a retired guard; the IDP Josh
    # Hines-Allen is not a near-name at 0.80.
    offense = R.suggest_player_candidates(index, "Josh Alen", position="QB", limit=5)
    assert offense and all(s.position in {"QB", "G"} for s in offense)
    idp = R.suggest_player_candidates(index, "Byron Yong", position="LB", limit=5)
    assert {s.sleeper_id for s in idp} == {"10917", "10925"}
    none_off = R.suggest_player_candidates(index, "Byron Yong", position="WR")
    assert none_off == []


def test_below_threshold_and_degenerate_inputs(index):
    assert R.suggest_player_candidates(index, "Completely Different Person") == []
    assert R.suggest_player_candidates(index, "") == []
    assert R.suggest_player_candidates(index, None) == []
    assert R.suggest_player_candidates(index, "2027 Early 1st") == []
    assert R.suggest_player_candidates(index, "Patrick Mahomse", limit=0) == []


def test_limit_and_deterministic_order(index):
    a = R.suggest_player_candidates(index, "Kyle Wiliams", limit=2)
    b = R.suggest_player_candidates(index, "Kyle Wiliams", limit=2)
    assert a == b and len(a) == 2
    # Rostered candidates rank ahead of retired homonyms at equal score.
    assert a[0].team == "NE"
