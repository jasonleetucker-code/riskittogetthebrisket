"""Format fingerprint, per-axis comparability, and the owner's acceptance cases."""

from __future__ import annotations

import pytest

from src.trade import market_trade_format as F
from tests.trade.market_trade_fixtures import (
    TARGET_POSITIONS,
    TARGET_SCORING,
    ktc_settings,
    sleeper_league,
)

TARGET = F.format_from_sleeper_league(sleeper_league("TGT"))


def fmt(**kw):
    return F.format_from_sleeper_league(sleeper_league("SRC", **kw))


def positions(offense, idp, bench=37):
    return offense + idp + ["BN"] * bench


OFFENSE = ["QB", "RB", "RB", "WR", "WR", "WR", "TE", "TE", "FLEX", "FLEX", "SUPER_FLEX", "K"]
#: A minimal inspectable transaction: two sides, every asset resolved.
SIDES_1_FOR_1 = [
    [{"kind": "player", "canonicalId": "player:1", "position": "WR"}],
    [{"kind": "player", "canonicalId": "player:2", "position": "RB"}],
]
IDP_333 = ["DL"] * 3 + ["LB"] * 3 + ["DB"] * 3


def test_exact_12_team_sf_2te_matching_idp_is_native():
    d = F.disposition(fmt(), TARGET)
    assert d["disposition"] == F.NATIVE_COMPARABLE
    assert d["strongestUnsupportedAxis"] is None
    assert d["formatAuthority"]["matchedCount"] == len(F.AXES)


def test_1qb_without_validated_translation_is_unsupported_and_names_qb():
    one_qb = [p if p != "SUPER_FLEX" else "FLEX" for p in TARGET_POSITIONS]
    d = F.disposition(fmt(roster_positions=one_qb), TARGET)
    assert d["disposition"] == F.TARGET_UNSUPPORTED
    assert d["strongestUnsupportedAxis"] == "qbDemand"
    assert d["comparability"]["qbDemand"]["source"] == {"QB": [1, 1]}


def test_validated_transformable_path_with_a_stub_translator_test_only():
    one_qb = [p if p != "SUPER_FLEX" else "FLEX" for p in TARGET_POSITIONS]
    src = fmt(roster_positions=one_qb)
    reg = F.TranslatorRegistry()
    evidence = {
        "trainTradeIds": ["utrade:a"],
        "testTradeIds": ["utrade:b"],
        "split": "by_league",
        "baselines": list(F.REQUIRED_BASELINES),
        "metrics": {"maeRelative": 0.1},
        "beatsAllBaselines": True,
    }
    reg.register(
        F.Translator(
            version="stub-v0",
            applies=lambda s, t: s.superflex is False and t.superflex is True,
            transform=lambda o, s, t: {
                "adjustments": [{"asset": "x", "factor": 1.0}],
                "transformed": o.get("sides"),
                "uncertainty": 0.5,
            },
            adjustment_scope="per_asset_structural",
            validated=True,
            validation_evidence=evidence,
        )
    )
    obs = {"underlyingTradeId": "utrade:c", "sides": SIDES_1_FOR_1}
    d = F.disposition(src, TARGET, observation=obs, registry=reg)
    assert d["disposition"] == F.VALIDATED_TRANSFORMABLE
    assert d["targetPriceAuthority"] == 1
    # A hard integrity failure blocks the translator too (empty topology).
    bad = F.disposition(src, TARGET, observation={**obs, "sides": []}, registry=reg)
    assert bad["disposition"] == F.TARGET_UNSUPPORTED
    assert bad["dispositionReasons"] == ["invalid_topology:empty"]
    tr = d["translation"]
    assert tr["transformationVersion"] == "stub-v0"
    assert tr["originalObservationId"] == "utrade:c"
    assert tr["sourceFingerprint"] != tr["targetFingerprint"]
    assert tr["validationEvidence"]["testTradeIds"] == ["utrade:b"]


def test_production_registry_has_no_validated_translator():
    assert len(F.DEFAULT_REGISTRY) == 0


def test_a_global_format_multiplier_is_refused():
    with pytest.raises(F.TranslatorRefused, match="global"):
        F.TranslatorRegistry().register(
            F.Translator("x", lambda s, t: True, lambda o, s, t: {}, adjustment_scope="global")
        )


@pytest.mark.parametrize(
    "evidence,problem",
    [
        (None, "no_evidence"),
        (
            {
                "trainTradeIds": ["a"],
                "testTradeIds": ["a"],
                "split": "x",
                "baselines": list(F.REQUIRED_BASELINES),
                "metrics": {},
                "beatsAllBaselines": True,
            },
            "train_test_overlap",
        ),
        (
            {
                "trainTradeIds": ["a"],
                "testTradeIds": ["b"],
                "split": "x",
                "baselines": ["no_adjustment"],
                "metrics": {},
                "beatsAllBaselines": True,
            },
            "baseline_missing:exclusion",
        ),
        (
            {
                "trainTradeIds": ["a"],
                "testTradeIds": ["b"],
                "split": "x",
                "baselines": list(F.REQUIRED_BASELINES),
                "metrics": {},
                "beatsAllBaselines": False,
            },
            "does_not_beat_baselines",
        ),
    ],
)
def test_validated_requires_held_out_evidence(evidence, problem):
    assert problem in F.check_validation_evidence(evidence)
    with pytest.raises(F.TranslatorRefused):
        F.TranslatorRegistry().register(
            F.Translator(
                "x", lambda s, t: True, lambda o, s, t: {}, "per_asset_structural", True, evidence
            )
        )


def test_offense_only_league_never_becomes_idp_evidence():
    off = fmt(
        roster_positions=positions(OFFENSE, [], 46),
        scoring={k: v for k, v in TARGET_SCORING.items() if not k.startswith("idp_")},
    )
    assert off.idp_enabled is False and not off.idp_slot_tokens
    assert off.to_dict()["idp"]["starters"] == 0
    d = F.disposition(off, TARGET)
    assert d["disposition"] == F.TARGET_UNSUPPORTED
    assert d["comparability"]["idpEnabled"]["state"] == F.DIFFERENT


def test_three_generic_idp_cannot_price_a_333_market():
    generic = fmt(roster_positions=positions(OFFENSE, ["IDP_FLEX"] * 3, 43))
    axes = F.compare_formats(generic, TARGET)
    assert axes["idpStarterDepth"]["state"] == F.DIFFERENT  # 3 vs 9
    assert axes["idpPositionalStructure"]["state"] == F.DIFFERENT
    assert F.disposition(generic, TARGET)["disposition"] == F.TARGET_UNSUPPORTED


def test_matching_333_with_similar_scoring_is_more_comparable_than_generic():
    similar = dict(TARGET_SCORING, idp_tkl_solo=1.4)  # close, not identical
    matching = F.format_authority(F.compare_formats(fmt(scoring=similar), TARGET))
    generic = F.format_authority(
        F.compare_formats(
            fmt(roster_positions=positions(OFFENSE, ["IDP_FLEX"] * 3, 43), scoring=similar), TARGET
        )
    )
    assert matching["matchedCount"] > generic["matchedCount"]
    assert "idpPositionalStructure" in matching["matchedAxes"]
    # …and still not NATIVE: no tolerance is validated, so 1.4 != 1.33.
    assert "idpScoring" in matching["differentAxes"]


def test_tackle_heavy_vs_coverage_heavy_is_not_exact_despite_nine_idp():
    tackle = dict(TARGET_SCORING, idp_tkl_solo=2.0, idp_tkl_ast=1.0, idp_pass_def=1.0)
    coverage = dict(TARGET_SCORING, idp_tkl_solo=0.75, idp_tkl_ast=0.25, idp_pass_def=6.0)
    a, b = fmt(scoring=tackle), fmt(scoring=coverage)
    axes = F.compare_formats(a, b)
    assert axes["idpStarterDepth"]["state"] == F.MATCH  # both start 9
    assert axes["idpScoring"]["state"] == F.DIFFERENT
    assert axes["idpScoring"]["detail"]["differingKeys"] == 3
    assert F.disposition(a, b)["disposition"] == F.TARGET_UNSUPPORTED


def test_1te_vs_2te_demand_is_recognized():
    one_te = list(TARGET_POSITIONS)
    one_te[one_te.index("TE")] = "WR"
    axes = F.compare_formats(fmt(roster_positions=one_te), TARGET)
    assert axes["teRosterDemand"]["state"] == F.DIFFERENT
    assert axes["teRosterDemand"]["source"] == {"TE": [1, 4]}
    assert axes["teRosterDemand"]["target"] == {"TE": [2, 5]}


def test_unknown_scoring_card_is_unknown_not_comparable():
    lg = sleeper_league("SRC")
    lg["scoring_settings"] = None
    src = F.format_from_sleeper_league(lg)
    axes = F.compare_formats(src, TARGET)
    for name in ("teScoring", "offenseScoring", "idpScoring"):
        assert axes[name]["state"] == F.UNKNOWN
    assert F.disposition(src, TARGET)["disposition"] == F.TARGET_UNSUPPORTED


def test_missing_metadata_is_unknown_never_a_default():
    blank = F.format_from_sleeper_league({"league_id": "x"})
    assert blank.teams is None and blank.demand is None and blank.idp_enabled is None
    assert blank.dynasty_state is None
    axes = F.compare_formats(blank, TARGET)
    assert all(
        axes[n]["state"] == F.UNKNOWN
        for n in ("teamCount", "qbDemand", "idpEnabled", "dynastyState")
    )


def test_ktc_limits_reduce_to_the_same_demand_as_equivalent_sleeper_slots():
    k = F.format_from_ktc_settings(
        ktc_settings(
            lineup=[
                {"limit": "1-2", "name": "QB"},
                {"limit": "2-5", "name": "RB"},
                {"limit": "3-6", "name": "WR"},
                {"limit": "2-5", "name": "TE"},
            ]
        )
    )
    axes = F.compare_formats(k, TARGET)
    for name in ("qbDemand", "teRosterDemand"):
        assert axes[name]["state"] == F.MATCH
    # but KTC publishes no card, so it can never be native
    assert axes["offenseScoring"]["state"] == F.UNKNOWN
    assert k.vendor["tepLevel"] == 1


def test_keeper_league_is_not_dynasty():
    axes = F.compare_formats(fmt(ltype=1), TARGET)
    assert axes["dynastyState"]["state"] == F.DIFFERENT


def test_fingerprint_is_stable_and_format_sensitive():
    assert fmt().to_dict()["fingerprint"] == TARGET.to_dict()["fingerprint"]
    assert fmt(teams=10).to_dict()["fingerprint"] != TARGET.to_dict()["fingerprint"]


def test_holdout_split_never_trains_and_tests_on_the_same_trades_or_league():
    trades = [
        {
            "underlyingTradeId": "t1",
            "host": "sleeper",
            "hostLeagueId": "A",
            "occurredDate": "2026-09-01",
        },
        {
            "underlyingTradeId": "t2",
            "host": "sleeper",
            "hostLeagueId": "A",
            "occurredDate": "2026-10-01",
        },
        {
            "underlyingTradeId": "t3",
            "host": "sleeper",
            "hostLeagueId": "B",
            "occurredDate": "2026-09-01",
        },
    ]
    train, test = F.holdout_split(trades, is_test=lambda t: t["occurredDate"] >= "2026-10-01")
    assert {t["underlyingTradeId"] for t in test} == {"t1", "t2"}, "league A held out whole"
    assert {t["underlyingTradeId"] for t in train} == {"t3"}
    assert not ({t["underlyingTradeId"] for t in train} & {t["underlyingTradeId"] for t in test})


def test_capture_keeps_host_facts_only():
    cap = F.capture_sleeper_league_format(
        sleeper_league("L"), captured_at="2026-10-01T00:00:00+00:00"
    )
    assert set(cap) == {
        "capturedAt",
        "season",
        "total_rosters",
        "roster_positions",
        "scoring_settings",
        "settings",
    }
    assert (
        F.format_from_sleeper_league(cap).to_dict()["fingerprint"]
        == TARGET.to_dict()["fingerprint"]
    )


# ── Target format from the registry (review finding 6) ────────────────────


def _registry(monkeypatch, entry):
    from src.api import league_registry as reg

    cfg = reg._parse_league_entry({"key": "tgt", "sleeperLeagueId": "999", **entry})
    monkeypatch.setattr(reg, "get_league_by_key", lambda key: cfg if key == "tgt" else None)
    monkeypatch.setattr(reg, "scoring_evidence_state", lambda c: "missing")
    monkeypatch.setattr(reg, "scoring_settings_for_league", lambda c: None)
    return cfg


REG_STARTERS = {"QB": 1, "RB": 2, "WR": 3, "TE": 1, "SUPER_FLEX": 1, "DL": 2, "LB": 2, "DB": 2}


def test_registry_target_uses_the_canonical_starter_ladder(monkeypatch):
    _registry(monkeypatch, {"rosterSettings": {"starters": REG_STARTERS, "teamCount": 12}})
    reg_only = F.format_from_registry("tgt")
    assert reg_only.vendor["starterSource"] == "registry_starters"
    assert reg_only.total_starters == sum(REG_STARTERS.values())
    # Live host positions outrank the registry (same ladder as src/ros/lineup).
    live = F.format_from_registry("tgt", roster_positions=TARGET_POSITIONS)
    assert live.vendor["starterSource"] == "sleeper_roster_positions"
    assert live.to_dict()["offense"] == TARGET.to_dict()["offense"]


def test_registry_target_refuses_rather_than_inventing_a_lineup(monkeypatch):
    _registry(monkeypatch, {"rosterSettings": {"teamCount": 12}})
    f = F.format_from_registry("tgt")
    assert f.vendor["starterSource"] is None
    assert f.demand is None and f.total_starters is None and f.superflex is None


def test_registry_defaults_are_not_facts(monkeypatch):
    # Neither bestBall nor idpEnabled stated, and no lineup resolves.
    _registry(monkeypatch, {"rosterSettings": {"teamCount": 12}})
    f = F.format_from_registry("tgt")
    assert f.best_ball is None, "an unstated bestBall default is UNKNOWN, not False"
    assert f.idp_enabled is None, "an unstated idpEnabled default is UNKNOWN, not False"


def test_stated_registry_facts_are_used(monkeypatch):
    _registry(
        monkeypatch,
        {"rosterSettings": {"teamCount": 12}, "bestBall": True, "idpEnabled": True},
    )
    f = F.format_from_registry("tgt")
    assert f.best_ball is True and f.idp_enabled is True


def test_resolved_lineup_decides_idp_over_a_stated_flag(monkeypatch):
    offense_only = {"QB": 1, "RB": 2, "WR": 3, "TE": 1}
    _registry(monkeypatch, {"rosterSettings": {"starters": offense_only}, "idpEnabled": True})
    assert F.format_from_registry("tgt").idp_enabled is False
