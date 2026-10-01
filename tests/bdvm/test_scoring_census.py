"""BDVM scoring census: vocabulary probes, classification, signed impact.

No network: synthetic cards and synthetic weekly rows only.  The census is
reporting-only — the last block pins that it changes no projected point.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from src.bdvm.scoring import score_stat_line_per_game_detailed
from src.bdvm.scoring_census import (
    census_for_card,
    clay_vocabularies,
    idpshow_vocabulary,
    manual_csv_vocabulary,
    measure_realized,
    source_supply,
)
from src.bdvm.service import _weight_sign

REPO_ROOT = Path(__file__).resolve().parents[2]

CARD = {
    "rec": 1.0,
    "rec_yd": 0.1,
    "fum_lost": -2.0,
    "rec_40p": 2.0,
    "pass_int_td": -2.0,
    "bonus_fd_wr": 1.0,
    "bonus_rec_wr": 0.5,
    "idp_tkl_solo": 1.0,
    "idp_tkl_loss": 4.0,
    "pts_allow_0": 10.0,
    "xpm": 1.0,
    "zero_rated": 0.0,
}


def _by_key(rows):
    return {e["key"]: e for e in rows}


# --------------------------------------------------------------------------
# Vocabularies are derived from the adapters' own parsers
# --------------------------------------------------------------------------


def test_clay_vocabulary_is_probed_from_the_parser():
    off, idp = clay_vocabularies()
    assert {"receptions", "receiving_yards", "completions", "attempts", "carries"} <= off
    assert "fumbles_lost" not in off and "fumbles_lost_total" not in off
    assert idp == {"def_tackles_solo", "def_tackle_assists", "def_sacks", "def_interceptions"}


def test_idpshow_vocabulary_never_emits_combined_tackles():
    vocab = idpshow_vocabulary()
    assert {"def_tackles_for_loss", "def_pass_defended", "def_qb_hits"} <= vocab
    # realized_points reads ``def_tackles`` as the pre-2025 gamebook SOLO total.
    assert "def_tackles" not in vocab


def test_manual_csv_cannot_carry_play_by_play_rules():
    vocab = manual_csv_vocabulary()
    assert source_supply("fum_lost", vocab, ["RB"]) == "direct"
    assert source_supply("rec_40p", vocab, ["WR"]) == "none"


def test_first_downs_are_reported_as_imputed_not_direct():
    off, _ = clay_vocabularies()
    assert source_supply("bonus_fd_wr", off, ["WR"]) == "imputed"


# --------------------------------------------------------------------------
# Classification
# --------------------------------------------------------------------------


def test_classification_per_rule():
    rows = _by_key(census_for_card(CARD))
    assert "zero_rated" not in rows  # zero-rated rules cost nothing
    assert rows["rec"]["classification"] == "SUPPORTED"
    assert rows["bonus_rec_wr"]["classification"] == "SUPPORTED"
    # Supplied only through the first-down-rate imputation: its own class,
    # never folded into SUPPORTED.
    assert rows["bonus_fd_wr"]["classification"] == "SUPPORTED_IMPUTED"
    assert rows["bonus_fd_wr"]["imputed"] == ["clayOffense"]
    assert rows["fum_lost"]["classification"] == "UNSUPPORTED_VOCABULARY"
    assert rows["fum_lost"]["capability"]["manualCsv"] == "direct"
    assert rows["rec_40p"]["classification"] == "UNSUPPORTED_VOCABULARY"
    assert rows["idp_tkl_loss"]["classification"] == "ABSENT_FIELD"
    assert rows["idp_tkl_loss"]["missingFrom"] == ["clayIdp"]
    assert rows["idp_tkl_solo"]["classification"] == "SUPPORTED"
    assert rows["pts_allow_0"]["classification"] == "NOT_APPLICABLE"
    assert rows["xpm"]["classification"] == "NOT_APPLICABLE"
    assert rows["xpm"]["reason"] == "kicker rule"


def test_weight_sign_travels_and_penalties_are_flagged():
    rows = _by_key(census_for_card(CARD))
    assert rows["fum_lost"]["weightSign"] == "-"
    assert rows["pass_int_td"]["weightSign"] == "-"
    assert rows["rec"]["weightSign"] == "+"


def test_only_play_by_play_rules_are_reported_by_unscored_keys():
    """Vocabulary gaps such as fum_lost score a SILENT zero today — the census
    is the surface that names them."""
    rows = _by_key(census_for_card(CARD))
    assert rows["rec_40p"]["reportedInUnscoredKeys"] is True
    assert rows["pass_int_td"]["reportedInUnscoredKeys"] is True
    assert rows["fum_lost"]["reportedInUnscoredKeys"] is False


def test_engine_gap_is_a_mapping_error():
    rows = _by_key(census_for_card({"bonus_invented_rule": 1.0}))
    assert rows["bonus_invented_rule"]["classification"] == "MAPPING_ERROR"


@pytest.mark.parametrize("key", ["pass_fd", "rush_fd", "rec_fd"])
def test_play_type_first_downs_are_a_vocabulary_gap_never_a_mapping_fix(key):
    """The realized engine reads no column for play-type first downs (probe
    GAP), but for the PROJECTION lane the question is the source: no source
    publishes first downs by play type, and deriving them from aggregate
    yards would fabricate a stat.  So: UNSUPPORTED_VOCABULARY, and the remedy
    says never to derive them."""
    row = _by_key(census_for_card({key: 0.5}))[key]
    assert row["engine"] == "gap"
    assert row["classification"] == "UNSUPPORTED_VOCABULARY"
    assert set(row["sources"].values()) == {"none"}
    assert "never derive" in row["remedy"]
    assert "aggregate" in row["remedy"]


def test_imputed_rule_has_its_own_at_risk_basis_and_ranks_by_magnitude():
    rows = [
        {
            "season": 2025,
            "week": 1,
            "season_type": "REG",
            "player_id": "w1",
            "position": "WR",
            "receptions": 5,
            "receiving_yards": 80,
            "receiving_first_downs": 4,
            "receiving_tds": 1,
        },
    ]
    card = {"rec": 1.0, "bonus_fd_wr": 1.0}
    m = measure_realized(rows, card, card)
    by = _by_key(census_for_card(card, realized=m))
    fd = by["bonus_fd_wr"]
    assert fd["classification"] == "SUPPORTED_IMPUTED"
    assert fd["realized"]["atRiskBasis"].startswith("estimated")
    assert fd["priority"] == pytest.approx(abs(fd["realized"]["points"])) and fd["priority"] > 0
    assert "imputed" in fd["remedy"]
    assert by["rec"]["priority"] == 0.0  # directly supplied: nothing at risk


def test_play_type_first_downs_are_measured_the_host_way():
    """Realized measurement only: nflverse first downs MINUS that play type's
    TDs (Sleeper excludes scoring plays).  A missing TD column makes the stat
    unmeasurable, never "zero TDs"."""
    rows = [
        {
            "season": 2025,
            "week": 1,
            "season_type": "REG",
            "player_id": "r1",
            "position": "RB",
            "rushing_first_downs": 5,
            "rushing_tds": 2,
        },
        {
            "season": 2025,
            "week": 2,
            "season_type": "REG",
            "player_id": "r1",
            "position": "RB",
            "rushing_first_downs": 3,
        },
    ]
    m = measure_realized(rows, {"rush_fd": 0.5}, ["rush_fd"])
    assert m["keys"]["rush_fd"]["stat"] == 3.0
    assert m["keys"]["rush_fd"]["points"] == 1.5


def test_missing_rate_and_missing_columns_are_never_zero():
    rows = [
        {
            "season": 2025,
            "week": 1,
            "season_type": "REG",
            "player_id": "d1",
            "position": "LB",
            "def_tackles_solo": 3,
        }
    ]
    m = measure_realized(
        rows, {"idp_tkl_solo": 1.0, "rec": None, "x": "bad"}, ["idp_tkl_solo", "rec", "x"]
    )
    assert m["unmeasuredKeys"] == ["rec", "x"]
    assert "rec" not in m["keys"]
    # The engine-finding columns are absent from this row: counted as missing,
    # not summed as zeros.
    assert m["columnTotals"] == {}
    assert m["columnRowsMissing"]["fumble_recovery_opp"] == 1
    # Non-numeric / absent card values are not census rules at all.
    assert census_for_card({"rec": None, "x": "bad"}) == []


def test_idp_rules_do_not_apply_to_a_league_that_starts_no_defenders():
    rows = _by_key(census_for_card(CARD, idp_enabled=False))
    assert rows["idp_tkl_loss"]["classification"] == "NOT_APPLICABLE"
    assert rows["rec"]["classification"] == "SUPPORTED"


def test_declared_baseline_mapping_finding_is_attached():
    rows = _by_key(census_for_card({"idp_fum_rec": 3.0}))
    finding = rows["idp_fum_rec"]["baselineMappingError"]
    assert finding["engineColumn"] == "fumble_recovery_own"
    assert finding["hostMatchingColumn"] == "fumble_recovery_opp"


# --------------------------------------------------------------------------
# Realized measurement: signed points, players, shares, priority
# --------------------------------------------------------------------------

ROWS = [
    {
        "season": 2025,
        "week": 1,
        "season_type": "REG",
        "player_id": "w1",
        "position": "WR",
        "receptions": 5,
        "receiving_yards": 80,
        "fumbles_lost_total": 1,
        "pbp_derived": {"rec_40p": 1},
    },
    {
        "season": 2025,
        "week": 2,
        "season_type": "REG",
        "player_id": "w1",
        "position": "WR",
        "receptions": 3,
        "receiving_yards": 30,
        "pbp_derived": {},
    },
    {
        "season": 2025,
        "week": 1,
        "season_type": "REG",
        "player_id": "r1",
        "position": "RB",
        "receptions": 2,
        "receiving_yards": 10,
        "fumbles_lost_total": 2,
        "pbp_derived": {},
    },
    {
        "season": 2025,
        "week": 1,
        "season_type": "REG",
        "player_id": "l1",
        "position": "LB",
        "def_tackles_solo": 6,
        "def_tackles_for_loss": 2,
        "fumble_recovery_opp": 1,
        "fumble_recovery_own": 0,
    },
    {
        "season": 2025,
        "week": 1,
        "season_type": "POST",
        "player_id": "w1",
        "position": "WR",
        "receptions": 99,
    },
    {
        "season": 2025,
        "week": 1,
        "season_type": "REG",
        "player_id": "k1",
        "position": "K",
        "pat_made": 4,
    },
]


def test_measure_realized_is_signed_and_counts_players():
    card = {**CARD, "idp_fum_rec": 3.0}
    m = measure_realized(ROWS, card, [k for k, v in card.items() if v])
    assert m["pbpAttached"] is True
    assert m["keys"]["fum_lost"] == {
        "players": 2,
        "playersByFamily": {"RB": 1, "WR": 1},
        "stat": 3.0,
        "points": -6.0,
        "byFamily": {"RB": -4.0, "WR": -2.0},
    }
    assert m["keys"]["rec_40p"]["points"] == 2.0
    assert m["keys"]["rec"]["stat"] == 10.0  # POST row excluded
    # A defender's recovery of the OFFENSE's fumble is measured off _opp.
    assert m["keys"]["idp_fum_rec"]["points"] == 3.0
    assert "K" not in m["families"]  # kickers are not priced


def test_census_priority_ranks_by_signed_magnitude_not_key_count():
    m = measure_realized(ROWS, CARD, [k for k, v in CARD.items() if v])
    rows = census_for_card(CARD, realized=m)
    ranked = [e["key"] for e in rows if e["priority"] > 0]
    # |fum_lost| = 6 points outranks rec_40p's 2, despite the smaller |weight|.
    assert ranked.index("fum_lost") < ranked.index("rec_40p")
    fum = _by_key(rows)["fum_lost"]["realized"]
    assert fum["points"] == -6.0
    assert fum["shareOfAffectedFamilyPoints"] < 0
    assert fum["atRiskBasis"].startswith("full")
    assert _by_key(rows)["idp_tkl_loss"]["realized"]["atRiskBasis"].startswith("upper_bound")
    assert all(e["priority"] == 0.0 for e in rows if e["classification"] == "SUPPORTED")


# --------------------------------------------------------------------------
# Reporting only: supported totals are unchanged; wording is sign-aware
# --------------------------------------------------------------------------


def test_unscored_penalty_is_reported_and_supported_total_is_unchanged():
    line = {"passing_yards": 250.0, "passing_tds": 2.0, "interceptions": 1.0}
    base = {"pass_yd": 0.04, "pass_td": 4.0, "pass_int": -2.0}
    plain, plain_unscored = score_stat_line_per_game_detailed(line, base, position="QB")
    with_pen, unscored = score_stat_line_per_game_detailed(
        line, {**base, "pass_int_td": -2.0}, position="QB"
    )
    assert plain == pytest.approx(16.0)
    assert with_pen == pytest.approx(plain)  # the supported total does not move
    assert plain_unscored == ()
    assert unscored == ("pass_int_td",)  # ...and the omitted PENALTY travels


@pytest.mark.parametrize(
    "card,key,expected",
    [
        ({"pass_int_td": -2.0}, "pass_int_td", "-"),
        ({"rec_40p": 2.0}, "rec_40p", "+"),
        ({"rec_40p": 0.0}, "rec_40p", None),
        ({}, "rec_40p", None),
        ({"rec_40p": "x"}, "rec_40p", None),
    ],
)
def test_service_weight_sign(card, key, expected):
    assert _weight_sign(card, key) == expected


_PARTIAL_TOTAL_SURFACES = (
    "src/bdvm/scoring.py",
    "src/bdvm/projections.py",
    "src/bdvm/service.py",
    "src/bdvm/baseline.py",
    "src/bdvm/actuals.py",
    "src/bdvm/scoring_census.py",
    "src/nfl_data/realized_points.py",
    "src/league_comparison/scoring_engine.py",
)


@pytest.mark.parametrize("rel", _PARTIAL_TOTAL_SURFACES)
def test_no_lower_bound_wording_survives_on_partial_total_surfaces(rel):
    """Unscored rules can be penalties (``pass_int_td``), so a partial total is
    never described as a lower bound — every remaining mention must be the
    negation ("not a lower bound")."""
    text = " ".join((REPO_ROOT / rel).read_text(encoding="utf-8").lower().split())
    start = 0
    while (i := text.find("lower bound", start)) != -1:
        assert "not" in text[max(0, i - 8) : i], (rel, text[max(0, i - 80) : i + 20])
        start = i + 1


# --------------------------------------------------------------------------
# The script: pinned, LOCAL, writes JSON + markdown, no network
# --------------------------------------------------------------------------


def _load_script():
    spec = importlib.util.spec_from_file_location(
        "bdvm_scoring_census", REPO_ROOT / "scripts" / "bdvm_scoring_census.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_script_writes_pinned_local_census(tmp_path):
    leagues = tmp_path / "leagues"
    leagues.mkdir()
    (leagues / "scoring_1312006700437352448.json").write_text(
        json.dumps(
            {
                "scoringSettings": CARD,
                "fetchedAt": "2026-09-26T00:00:00+00:00",
                "scoringFingerprint": "sf1:test",
                "season": "2026",
            }
        ),
        encoding="utf-8",
    )
    weekly = tmp_path / "weekly.json"
    weekly.write_text(json.dumps(ROWS), encoding="utf-8")
    out = tmp_path / "out"
    rc = _load_script().main(
        ["--out-dir", str(out), "--leagues-dir", str(leagues), "--weekly-json", str(weekly)]
    )
    assert rc == 0
    doc = json.loads((out / "census.json").read_text(encoding="utf-8"))
    assert doc["scope"] == "LOCAL"
    assert doc["code"]["sha"]
    assert len(doc["realizedInput"]["sha256"]) == 64
    [league] = doc["leagues"]  # the other registry league has no card here
    assert league["leagueKey"] == "dynasty_main"
    assert league["card"]["fingerprint"] == "sf1:test"
    md = (out / "census.md").read_text(encoding="utf-8")
    assert "LOCAL" in md and "`fum_lost`" in md and "not a lower bound" in md


def test_script_without_history_is_vocabulary_only(tmp_path):
    leagues = tmp_path / "leagues"
    leagues.mkdir()
    (leagues / "scoring_1312006700437352448.json").write_text(
        json.dumps({"scoringSettings": CARD}), encoding="utf-8"
    )
    out = tmp_path / "out"
    assert _load_script().main(["--out-dir", str(out), "--leagues-dir", str(leagues)]) == 0
    doc = json.loads((out / "census.json").read_text(encoding="utf-8"))
    assert doc["realizedInput"]["status"].startswith("unavailable")
    assert all("realized" not in e for e in doc["leagues"][0]["rules"])


def test_script_fails_without_any_card(tmp_path):
    assert (
        _load_script().main(["--out-dir", str(tmp_path / "o"), "--leagues-dir", str(tmp_path)]) == 1
    )
