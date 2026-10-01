"""Source vocabulary → per-player scoring coverage (Batch 3 Unit J1, req. 2).

A projected total is only as complete as the stats its SOURCE publishes.
Before this, ``unscoredKeys`` reported the play-by-play-only rules and
nothing else, so:

* a Clay-scored QB omitted ``fum_lost`` — a PENALTY — in silence, overstating
  his partial total;
* a Clay-only defender omitted PD / TFL / QB hits (~40% of IDP points on
  dynasty_main's card, census 2026-10-01) in silence;
* an fpg-only reconstructed-baseline proxy looked fully scoreable, because a
  record with no stat line reported no unscored keys at all.

The declaration lives in ``src.bdvm.source_vocabulary``; these tests pin that
it reaches ``ConsensusProjection.unscored_keys`` and the service payload.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from src.bdvm import service as bdvm_service
from src.bdvm.params import load_param_set
from src.bdvm.projections import (
    ProjectionRecord,
    RealizedSeason,
    blend_consensus,
    build_reconstructed_baseline,
    load_snapshot,
    write_snapshot,
)
from src.bdvm.source_vocabulary import (
    capability_for,
    declared_capabilities,
    record_coverage,
)
from tests.bdvm.pool_depth import depth_records
from tests.bdvm.test_service import PROJECTIONS, build_contract

PARAMS = load_param_set("params_v1")

CARD = {
    "pass_yd": 0.04,
    "pass_td": 4.0,
    "pass_int": -2.0,
    "rush_yd": 0.1,
    "rec": 1.0,
    "rec_yd": 0.1,
    "fum_lost": -2.0,
    "idp_tkl_solo": 1.5,
    "idp_tkl_ast": 0.75,
    "idp_sack": 4.0,
    "idp_int": 6.0,
    "idp_pass_def": 5.3,
    "idp_tkl_loss": 4.24,
    "idp_qb_hit": 2.12,
    "idp_fum_rec": 3.19,
    "rec_40p": 2.0,
}


def _clay_qb(key="clay qb"):
    return ProjectionRecord(
        source="clayProjections",
        player_key=key,
        position="QB",
        season=2026,
        as_of="2026-07-20",
        games=17.0,
        stat_line={
            "attempts": 560.0,
            "completions": 370.0,
            "passing_yards": 4100.0,
            "passing_tds": 28.0,
            "interceptions": 11.0,
            "carries": 60.0,
            "rushing_yards": 300.0,
            "rushing_tds": 3.0,
        },
    )


def _clay_lb(key="some lb"):
    return ProjectionRecord(
        source="clayProjections",
        player_key=key,
        position="LB",
        season=2026,
        as_of="2026-07-20",
        games=17.0,
        stat_line={
            "def_tackles_solo": 70.0,
            "def_tackle_assists": 40.0,
            "def_sacks": 2.0,
            "def_interceptions": 1.0,
        },
    )


def _idpshow_lb(key="some lb", **extra):
    line = {
        "def_tackles_solo": 72.0,
        "def_tackle_assists": 41.0,
        "def_sacks": 2.5,
        "def_interceptions": 1.0,
        "def_pass_defended": 5.0,
        "def_tackles_for_loss": 7.0,
        "def_qb_hits": 6.0,
        "fumble_recovery_opp": 1.0,
        **extra,
    }
    return ProjectionRecord(
        source="idpShowProjections",
        player_key=key,
        position="LB",
        season=2026,
        as_of="2026-07-20",
        games=17.0,
        stat_line=line,
    )


def _card_fp(card=None):
    from src.league_comparison.sleeper_scoring import scoring_fingerprint

    return scoring_fingerprint(dict(card if card is not None else CARD))


def _proxy(key="proxy wr", declared=None, card_fp="__card__"):
    return ProjectionRecord(
        source="reconstructedBaseline",
        player_key=key,
        position="WR",
        season=2026,
        as_of="2026-07-20",
        games=16.0,
        fpg=11.0,
        scoring_native=True,
        is_proxy=True,
        declared_unscored=declared,
        declared_card_fingerprint=_card_fp() if card_fp == "__card__" else card_fp,
    )


def _blend(recs, card=CARD):
    return blend_consensus(recs, scoring_settings=card, snapshot_as_of="2026-07-27", params=PARAMS)


# --------------------------------------------------------------------------
# The declaration itself
# --------------------------------------------------------------------------


def test_every_live_projection_source_is_declared():
    caps = declared_capabilities()
    for source in (
        "clayProjections",
        "idpShowProjections",
        "reconstructedBaseline",
        "rookieDraftSlotPrior",
    ):
        assert source in caps, source
    clay = caps["clayProjections"]
    assert "receptions" in clay.vocabulary_by_family["WR"]
    assert "fumbles_lost" not in clay.vocabulary_by_family["WR"]
    assert "def_pass_defended" not in clay.vocabulary_by_family["LB"]
    assert "def_pass_defended" in caps["idpShowProjections"].vocabulary_by_family["LB"]
    assert caps["reconstructedBaseline"].vocabulary_by_family is None
    assert capability_for("someManualCsv").basis == "undeclared"


# --------------------------------------------------------------------------
# Stat-line sources: what the line cannot carry is unscored
# --------------------------------------------------------------------------


def test_clay_qb_reports_the_silent_fumble_penalty():
    blended = _blend([_clay_qb()])
    assert "fum_lost" in blended.unscored_keys
    assert blended.coverage_status == "partial"
    # A rule the line supplies is not reported, nor is a defender rule.
    assert "pass_yd" not in blended.unscored_keys
    assert not any(k.startswith("idp_") for k in blended.unscored_keys)


def test_clay_only_defender_reports_pd_tfl_and_qb_hits():
    blended = _blend([_clay_lb()])
    for key in ("idp_pass_def", "idp_tkl_loss", "idp_qb_hit", "idp_fum_rec"):
        assert key in blended.unscored_keys, key
    for key in ("idp_tkl_solo", "idp_sack", "idp_int"):
        assert key not in blended.unscored_keys, key
    # Offense rules are not a defensive feed's responsibility.
    assert "rec" not in blended.unscored_keys
    assert "fum_lost" not in blended.unscored_keys


def test_full_idp_show_capture_scores_what_clay_cannot():
    cov = record_coverage(_idpshow_lb(), CARD)
    assert cov.status == "complete", cov
    assert cov.unscored_keys == ()


def test_idp_show_capture_missing_a_column_says_so_for_its_players():
    rec = _idpshow_lb()
    line = dict(rec.stat_line)
    line.pop("def_pass_defended")
    partial = ProjectionRecord(**{**rec.__dict__, "stat_line": line})
    assert record_coverage(partial, CARD).unscored_keys == ("idp_pass_def",)


def test_consensus_keeps_per_source_coverage():
    blended = _blend([_clay_lb(), _idpshow_lb()])
    by_source = {c.source: c for c in blended.source_coverage}
    assert by_source["idpShowProjections"].status == "complete"
    assert "idp_pass_def" in by_source["clayProjections"].unscored_keys
    # The union still names what the Clay half of the blend omits.
    assert "idp_pass_def" in blended.unscored_keys


# --------------------------------------------------------------------------
# fpg-only records: never fully scoreable by default
# --------------------------------------------------------------------------


def test_undeclared_fpg_only_proxy_is_unverifiable_not_complete():
    blended = _blend([_proxy()])
    assert blended.coverage_status == "unverifiable"
    assert record_coverage(_proxy(), CARD).reason == "proxy_coverage_not_recorded"


def test_source_scored_points_are_unverifiable():
    rec = ProjectionRecord(
        source="idpShowProjections",
        player_key="big three",
        position="LB",
        season=2026,
        as_of="2026-07-20",
        games=17.0,
        fpts=150.0,
    )
    cov = record_coverage(rec, CARD)
    assert cov.status == "unverifiable"
    assert cov.reason == "source_scored_points"


def test_reconstructed_baseline_declares_its_realized_unscored_rules():
    history = {
        "proxy wr": (
            "WR",
            [
                RealizedSeason(season=2025, ppg=12.0, games=16.0, unscored=(("rec_40p", 2.0),)),
                RealizedSeason(season=2024, ppg=10.0, games=15.0),
            ],
        )
    }
    (record,) = build_reconstructed_baseline(
        history,
        season=2026,
        as_of="2026-07-20",
        positional_means={"WR": 8.0},
        card_fingerprint=_card_fp(),
    )
    assert record.declared_unscored == ("rec_40p",)
    blended = _blend([record])
    assert blended.unscored_keys == ("rec_40p",)
    assert blended.coverage_status == "partial"


def test_proxy_built_with_everything_scored_is_complete():
    blended = _blend([_proxy(declared=())])
    assert blended.coverage_status == "complete"
    assert blended.unscored_keys == ()


def test_declaration_survives_the_snapshot_and_legacy_snapshots_stay_unknown():
    with tempfile.TemporaryDirectory() as td:
        path = write_snapshot(
            [_proxy(declared=("rec_40p",)), _proxy(key="legacy", declared=None)],
            season=2026,
            as_of="2026-07-20",
            base_dir=Path(td),
        )
        _as_of, recs = load_snapshot(path)
    by_key = {r.player_key: r for r in recs}
    assert by_key["proxy wr"].declared_unscored == ("rec_40p",)
    assert by_key["legacy"].declared_unscored is None


# --------------------------------------------------------------------------
# Service payload
# --------------------------------------------------------------------------


def test_service_publishes_per_player_coverage_and_sign():
    contract = build_contract()
    contract["sleeper"]["scoringSettings"] = {
        **contract["sleeper"]["scoringSettings"],
        "fum_lost": -2.0,
    }
    clay = _clay_qb(key="alpha qb")
    payload = bdvm_service.run_valuation(
        contract,
        league_key="dynasty_main",
        params=PARAMS,
        projection_records=list(PROJECTIONS) + [clay] + depth_records(),
        snapshot_as_of="2026-07-27",
        season=2026,
    )
    alpha = next(p for p in payload["players"] if p["name"] == "Alpha Qb")
    proj = alpha["projection"]
    assert "fum_lost" in proj["unscoredKeys"]
    assert proj["scoringCoverage"]["status"] == "unverifiable"  # srcA/srcB are fpg-only
    by_source = {c["source"]: c for c in proj["scoringCoverage"]["bySource"]}
    assert by_source["clayProjections"]["status"] == "partial"
    assert "fum_lost" in by_source["clayProjections"]["unscoredKeys"]
    meta = payload["meta"]["scoringCoverage"]
    assert meta["weightSign"]["fum_lost"] == "-"
    assert meta["playersByStatus"]["unverifiable"] >= 1
    assert "clayProjections" in meta["sourceCapabilities"]
    assert "positive or negative" in meta["note"]


# --------------------------------------------------------------------------
# Review of #1585
# --------------------------------------------------------------------------


def test_a_proxy_built_under_another_card_or_no_card_is_unverifiable():
    other = {**CARD, "rec": 0.5}
    built_elsewhere = record_coverage(_proxy(declared=(), card_fp=_card_fp(other)), CARD)
    assert built_elsewhere.status == "unverifiable"
    assert built_elsewhere.reason == "proxy_built_under_different_card"
    unrecorded = record_coverage(_proxy(declared=(), card_fp=None), CARD)
    assert unrecorded.status == "unverifiable"
    assert unrecorded.reason == "proxy_card_not_recorded"
    same = record_coverage(_proxy(declared=(), card_fp=_card_fp()), CARD)
    assert same.status == "complete"


def test_clay_published_zeros_are_not_omissions():
    wr = ProjectionRecord(
        source="clayProjections",
        player_key="clay wr",
        position="WR",
        season=2026,
        as_of="2026-07-20",
        games=17.0,
        stat_line={"targets": 120.0, "receptions": 80.0, "receiving_yards": 1000.0},
    )
    wr_cov = record_coverage(wr, CARD)
    for key in ("pass_yd", "pass_td", "pass_int"):
        assert key not in wr_cov.unscored_keys, key
    cb = ProjectionRecord(
        source="clayProjections",
        player_key="clay cb",
        position="CB",
        season=2026,
        as_of="2026-07-20",
        games=17.0,
        stat_line={"def_tackles_solo": 50.0, "def_tackle_assists": 10.0},
    )
    cb_cov = record_coverage(cb, CARD)
    assert "idp_sack" not in cb_cov.unscored_keys
    assert "idp_int" not in cb_cov.unscored_keys
    # What Clay genuinely does not publish is still reported.
    assert "idp_pass_def" in cb_cov.unscored_keys
    assert "fum_lost" in wr_cov.unscored_keys


def test_a_per_capture_source_keeps_absence_as_omission():
    lb = ProjectionRecord(
        source="idpShowProjections",
        player_key="idp lb",
        position="LB",
        season=2026,
        as_of="2026-07-20",
        games=17.0,
        stat_line={"def_tackles_solo": 70.0, "def_tackle_assists": 30.0},
    )
    cov = record_coverage(lb, CARD)
    assert "idp_sack" in cov.unscored_keys
