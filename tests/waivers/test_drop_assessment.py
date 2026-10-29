"""Dynasty asset protection (safe-to-drop assessment) — ``src/waivers/drop_assessment.py``.

One test per classification rule, plus the four properties a consumer (the
streaming solver) relies on: the config refuses rather than defaulting, an
unpriced player is never churn, a user lock is absolute, and the answer is
deterministic.  The archive-board test checks invariants on a real board, not
counts.
"""

from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.history import store
from src.trade.constraints import UNRESOLVED, resolve_constraints
from src.waivers import drop_assessment as da
from src.waivers.drop_assessment import (
    CLASS_CHURN,
    CLASS_CONDITIONAL,
    CLASS_PROTECTED,
    DropAssessmentConfigError,
    TeamNotInLeague,
    assess_team_drops,
    load_protection_config,
)

NOW = datetime(2026, 10, 29, 12, 0, tzinfo=timezone.utc)
REPO = Path(__file__).resolve().parents[2]


def _row(pid, name, pos, value, *, conf="high", age=27, yx=4, **extra):
    row = {
        "playerId": pid,
        "canonicalName": name,
        "displayName": name,
        "legacyRef": name,
        "position": pos,
        "rankDerivedValue": value,
        "confidenceBucket": conf,
        "retainedAuthority": 0.8,
        "assetClass": "idp" if pos in {"DL", "LB", "DB"} else "offense",
        "age": age,
        "yearsExp": yx,
        "team": "AAA",
    }
    row.update(extra)
    return row


_ALPHA = [
    "Star QB",
    "Vet WR",
    "Band WR",
    "Mid WR",
    "Young DL",
    "Bust DL",
    "Ghost Body",
    "Null Value",
    "Quarantined WR",
    "Kicker",
]


def _contract():
    return {
        "meta": {"leagueKey": "pd_main"},
        "playersArray": [
            _row("101", "Star QB", "QB", 8000),
            _row("102", "Vet WR", "WR", 1100, age=31, yx=9),
            _row("103", "Band WR", "WR", 1300, conf="low", age=29, yx=6),
            _row("109", "Mid WR", "WR", 1900),
            _row("104", "Young DL", "DL", 900, conf="low", age=22, yx=1),
            _row("105", "Bust DL", "DL", 500, conf="low", age=23, yx=1),
            _row("106", "Null Value", "WR", None, conf="none"),
            _row(
                "107",
                "Quarantined WR",
                "WR",
                1000,
                quarantined=True,
                anomalyFlags=["blend_integrity_violation"],
            ),
            _row("108", "Kicker", "K", 1500),
            _row("201", "Other QB", "QB", 6000),
            _row("301", "Free WR", "WR", 1200),
            _row("302", "Free QB", "QB", 3000),
            _row("303", "Free DL", "DL", 2000),
        ],
        "sleeper": {
            "rosterPositions": ["QB", "WR", "DL", "BN", "BN", "BN"],
            "teams": [
                {
                    "name": "Alpha",
                    "ownerId": "owner-a",
                    "roster_id": 1,
                    "players": list(_ALPHA),
                    "playerIds": [],
                },
                {
                    "name": "Beta",
                    "ownerId": "owner-b",
                    "roster_id": 2,
                    "players": ["Other QB"],
                    "playerIds": [],
                },
            ],
        },
    }


def _snapshot(as_of="2026-10-27"):
    return {
        "asOf": as_of,
        "sleeperIndex": {"104": "G104", "105": "G105", "102": "G102"},
        "players": {
            "G104": {
                "gsisId": "G104",
                "snaps": {"games": 6, "pct": 55.0, "recentPct": 65.0, "trend": 10.0},
            },
            "G105": {
                "gsisId": "G105",
                "snaps": {"games": 6, "pct": 5.0, "recentPct": 5.0, "trend": 0.0},
            },
            "G102": {
                "gsisId": "G102",
                "snaps": {"games": 7, "pct": 88.0, "recentPct": 90.0, "trend": 2.0},
            },
        },
    }


_DRAFT_ROWS = [
    {
        "gsis_id": "G105",
        "display_name": "Bust DL",
        "position": "DE",
        "draft_pick": 20,
        "draft_year": 2025,
        "rookie_season": 2025,
    },
    {
        "gsis_id": "G104",
        "display_name": "Young DL",
        "position": "DE",
        "draft_pick": 180,
        "draft_year": 2025,
        "rookie_season": 2025,
    },
]


@pytest.fixture(autouse=True)
def _registry(tmp_path, monkeypatch):
    from src.api import league_registry

    path = tmp_path / "registry.json"
    path.write_text(
        json.dumps(
            {
                "defaultLeagueKey": "pd_main",
                "leagues": [
                    {
                        "key": "pd_main",
                        "displayName": "PD Main",
                        "sleeperLeagueId": "L-PD-MAIN",
                        "scoringProfile": "prof_a",
                        "active": True,
                        "rosterSettings": {
                            "teamCount": 2,
                            "rosterSize": 10,
                            "taxiSize": 0,
                            "starters": {"QB": 1, "WR": 1, "DL": 1},
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("LEAGUE_REGISTRY_PATH", str(path))
    league_registry.reload_registry()
    yield
    league_registry.reload_registry()


def _assess(contract=None, tmp_path=None, **kw):
    kw.setdefault("player_context_snapshot", _snapshot())
    kw.setdefault("draft_rows", _DRAFT_ROWS)
    kw.setdefault("history_path", Path("/nonexistent/ledger.sqlite"))
    kw.setdefault("unavailable_keys", ())
    return assess_team_drops(
        contract or _contract(), league_key="pd_main", owner_id="owner-a", now=NOW, **kw
    )


def _by_name(result):
    return {a.name: a for a in result.assessments}


# ══ Config: refuse, never default ═══════════════════════════════════


def _cfg_doc():
    return json.loads(
        (REPO / "config" / "waivers" / "streaming_protection.json").read_text(encoding="utf-8")
    )


def _write_cfg(tmp_path, doc):
    path = tmp_path / "cfg.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


def test_the_committed_config_loads_and_every_entry_is_a_prior():
    cfg = load_protection_config()
    assert cfg.version == "streaming_protection_v1"
    assert len(cfg.sha256) == 64
    for name, entry in _cfg_doc()["parameters"].items():
        assert entry["class"] == "PRIOR", name
        assert entry["rationale"].strip(), name


def test_missing_config_refuses(tmp_path):
    with pytest.raises(DropAssessmentConfigError):
        load_protection_config(tmp_path / "absent.json")
    with pytest.raises(DropAssessmentConfigError):
        _assess(config_path=tmp_path / "absent.json")


def test_malformed_config_refuses(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(DropAssessmentConfigError):
        load_protection_config(path)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d["parameters"].pop("protectGapMin"),
        lambda d: d["parameters"]["protectGapMin"].update({"class": "FIT"}),
        lambda d: d["parameters"]["protectGapMin"].update({"rationale": ""}),
        lambda d: d["parameters"]["protectGapMin"].update({"value": "0.4"}),
        lambda d: d["parameters"]["clearlyBelowGapMax"].update({"value": 0.1}),
        lambda d: d["parameters"]["churnGapMaxByConfidence"].update({"value": {"high": 0.9}}),
        lambda d: d["parameters"]["protectingFlags"].update({"value": ["made_up_flag"]}),
        lambda d: d["parameters"]["churnBlockingFlags"].update({"value": ["young_rising_usage"]}),
        lambda d: d.pop("version"),
        lambda d: d.pop("parameters"),
    ],
)
def test_a_missing_or_malformed_entry_refuses(tmp_path, mutate):
    doc = _cfg_doc()
    mutate(doc)
    with pytest.raises(DropAssessmentConfigError):
        load_protection_config(_write_cfg(tmp_path, doc))


# ══ One test per rule ═══════════════════════════════════════════════


def test_a_meaningful_dynasty_asset_is_protected():
    a = _by_name(_assess())
    assert a["Star QB"].drop_class == CLASS_PROTECTED
    assert a["Star QB"].reasons[0].code == "meaningful_dynasty_asset"
    # Mid WR: (1900 - 1200) / 1550 = 0.45 >= 0.40.
    assert a["Mid WR"].drop_class == CLASS_PROTECTED


def test_a_low_value_veteran_at_replacement_is_churn():
    vet = _by_name(_assess())["Vet WR"]
    assert vet.drop_class == CLASS_CHURN
    assert vet.reasons[0].code == "replaceable_by_free_agent"
    assert vet.replacement_value == 1200.0
    assert vet.value_above_replacement == -100.0
    assert vet.dynasty_cost == 0.0
    assert vet.development_flags == ()


def test_a_weekly_starter_is_not_churn():
    vet = _by_name(_assess(weekly_starter_ids={"102"}))["Vet WR"]
    assert vet.drop_class == CLASS_CONDITIONAL
    assert vet.reasons[0].code == "weekly_starter"
    assert vet.roster_role == "weekly_starter"
    bench = _by_name(_assess(weekly_starter_ids={"101"}))["Vet WR"]
    assert bench.roster_role == "bench" and bench.drop_class == CLASS_CHURN


def test_low_confidence_must_be_at_or_below_replacement():
    # Band WR: low confidence, (1300 - 1200) / 1250 = +0.08 — inside the 0.15
    # band but above the low-confidence margin of 0.0.
    band = _by_name(_assess())["Band WR"]
    assert band.drop_class == CLASS_CONDITIONAL
    assert band.reasons[0].code == "above_replacement_band"
    assert band.dynasty_cost == 100.0


def test_a_confidence_bucket_outside_the_map_is_never_churn():
    c = _contract()
    for r in c["playersArray"]:
        if r["displayName"] == "Vet WR":
            r["confidenceBucket"] = "none"
    vet = _by_name(_assess(c))["Vet WR"]
    assert vet.drop_class == CLASS_CONDITIONAL
    assert vet.reasons[0].code == "confidence_not_churn_eligible"


def test_young_rising_usage_protects_a_defender_below_replacement():
    young = _by_name(_assess())["Young DL"]
    assert "young_rising_usage" in young.development_flags
    assert young.drop_class == CLASS_PROTECTED
    assert young.reasons[0].code == "development_upside"
    assert young.inputs["snapUsage"]["state"] == "available"


def test_draft_capital_flag_is_overridden_when_clearly_below_with_observed_no_usage():
    bust = _by_name(_assess())["Bust DL"]
    assert "high_draft_capital_recent" in bust.development_flags
    assert bust.inputs["draftCapital"]["identityJoin"] == "gsis"
    assert bust.inputs["draftCapital"]["value"] == 20
    assert bust.drop_class == CLASS_CONDITIONAL
    assert bust.reasons[0].code == "development_flag_overridden_no_usage"


def test_draft_capital_without_observed_usage_still_protects():
    snap = _snapshot()
    del snap["players"]["G105"]["snaps"]
    bust = _by_name(_assess(player_context_snapshot=snap))["Bust DL"]
    # Absent usage is unknown, never zero — so it cannot prove "no usage".
    assert bust.inputs["snapUsage"]["state"] == "unavailable"
    assert bust.drop_class == CLASS_PROTECTED


def test_young_player_with_unknown_usage_is_never_churn():
    c = _contract()
    for r in c["playersArray"]:
        if r["displayName"] == "Vet WR":
            r["age"] = 22  # young; no snap record in a snapshot without him
    snap = _snapshot()
    del snap["sleeperIndex"]["102"]
    vet = _by_name(_assess(c, player_context_snapshot=snap))["Vet WR"]
    assert "young_usage_unknown" in vet.development_flags
    assert vet.drop_class == CLASS_CONDITIONAL
    assert vet.reasons[0].code == "churn_blocked_by_signal"


def test_a_stale_usage_snapshot_is_not_used():
    res = _assess(player_context_snapshot=_snapshot(as_of="2026-09-01"))
    young = _by_name(res)["Young DL"]
    assert young.inputs["snapUsage"]["state"] == "stale"
    assert "young_rising_usage" not in young.development_flags
    assert "young_usage_unknown" in young.development_flags
    assert young.drop_class != CLASS_CHURN
    assert res.summary["usageSnapshot"]["state"] == "stale"


def test_a_name_keyed_draft_record_for_another_position_is_refused():
    rows = [dict(_DRAFT_ROWS[0], gsis_id="OTHER", position="QB")]
    bust = _by_name(_assess(draft_rows=rows))["Bust DL"]
    assert bust.inputs["draftCapital"]["state"] == "unavailable"
    assert bust.inputs["draftCapital"]["reason"].startswith("identity_unconfirmed")
    assert "recent_draft_capital_unknown" in bust.development_flags


def test_a_rising_value_blocks_churn_but_never_protects(tmp_path):
    store._reset_setup_cache_for_tests()
    ledger = tmp_path / "ledger.sqlite"
    store.write_observations(
        [
            {
                "asset_key": "player:102",
                "asset_class": "offense",
                "lane": store.LANE_CANONICAL,
                "source_key": "",
                "observed_date": "2026-09-29",
                "value": 800,
                "origin": "test",
            }
        ],
        path=ledger,
    )
    vet = _by_name(_assess(history_path=ledger))["Vet WR"]
    assert vet.inputs["valueTrend30d"]["state"] == "available"
    assert vet.inputs["valueTrend30d"]["value"] == pytest.approx(0.375)
    assert "value_trending_up" in vet.development_flags
    assert vet.drop_class == CLASS_CONDITIONAL
    assert vet.reasons[0].code == "churn_blocked_by_signal"
    # A future observation is never read.
    assert vet.inputs["valueTrend60d"]["state"] == "unavailable"


def test_replacement_unknown_charges_full_board_value():
    kicker = _by_name(_assess())["Kicker"]
    assert kicker.replacement_value is None
    assert kicker.value_above_replacement is None
    assert kicker.dynasty_cost == 1500.0
    assert kicker.drop_class == CLASS_CONDITIONAL
    assert kicker.reasons[0].code == "replacement_level_unavailable"


def test_a_quarantined_value_is_protected():
    q = _by_name(_assess())["Quarantined WR"]
    assert q.drop_class == CLASS_PROTECTED
    assert q.reasons[0].code == "value_quarantined_never_auto_drop"


# ══ Invariants the solver relies on ═════════════════════════════════


def test_unpriced_is_never_churn_even_under_the_most_permissive_config(tmp_path):
    doc = _cfg_doc()
    doc["parameters"]["churnGapMaxByConfidence"]["value"] = {
        "high": 0.39,
        "medium": 0.39,
        "low": 0.39,
        "none": 0.39,
    }
    doc["parameters"]["churnBlockingFlags"]["value"] = []
    res = _assess(config_path=_write_cfg(tmp_path, doc))
    a = _by_name(res)
    for name in ("Ghost Body", "Null Value"):
        assert a[name].drop_class == CLASS_PROTECTED, name
        assert a[name].reasons[0].code == "unpriced_never_auto_drop"
        assert a[name].dynasty_value is None and a[name].dynasty_cost is None
    assert res.summary["unpriced"] == 2


def test_a_user_lock_is_absolute():
    cons = resolve_constraints(contract=_contract(), persistent={"untouchables": ["Vet WR"]})
    vet = _by_name(_assess(constraints=cons))["Vet WR"]
    assert vet.drop_class == CLASS_PROTECTED
    assert vet.reasons[0].code == "user_lock"
    assert vet.locks[0]["reason"] == "protected_individual"
    # The value and its cost are still reported; protection is not valuation.
    assert vet.dynasty_value == 1100.0


def test_unresolved_constraints_protect_everyone():
    res = _assess(constraints=UNRESOLVED)
    assert all(a.drop_class == CLASS_PROTECTED for a in res.assessments)
    assert res.summary["locksState"] == "unresolved"


def test_dynasty_cost_is_value_above_replacement_floored_at_zero():
    for a in _assess().assessments:
        if a.dynasty_value is None:
            assert a.dynasty_cost is None
        elif a.value_above_replacement is None:
            assert a.dynasty_cost == a.dynasty_value
        else:
            assert a.value_above_replacement == a.dynasty_value - a.replacement_value
            assert a.dynasty_cost == max(0.0, a.value_above_replacement)


def test_the_answer_is_deterministic():
    first = _assess().to_dict()
    second = _assess(copy.deepcopy(_contract())).to_dict()
    assert first == second
    ids = [a["playerId"] for a in first["assessments"]]
    assert ids == sorted(ids)


def test_the_public_shape_is_camel_case():
    out = _assess().to_dict()
    assert {
        "contractVersion",
        "leagueKey",
        "team",
        "asOf",
        "configVersion",
        "configHash",
        "replacementValues",
        "summary",
        "assessments",
    } <= set(out)
    a = out["assessments"][0]
    assert set(a) == {
        "playerId",
        "name",
        "position",
        "dropClass",
        "dynastyValue",
        "replacementValue",
        "valueAboveReplacement",
        "dynastyCost",
        "valueScale",
        "confidence",
        "reasons",
        "inputs",
        "locks",
        "developmentFlags",
        "rosterRole",
        "recoveryRisk",
    }
    assert a["recoveryRisk"]["state"] == "unmeasured"
    assert out["summary"]["counts"].keys() == {"protected", "conditional", "churn"}


def test_unknown_team_and_league_mismatch_refuse():
    with pytest.raises(TeamNotInLeague):
        assess_team_drops(_contract(), league_key="pd_main", owner_id="nobody", now=NOW)
    with pytest.raises(ValueError, match="league_mismatch"):
        assess_team_drops(_contract(), league_key="other", owner_id="owner-a", now=NOW)


def test_missing_inputs_are_stated_never_zero():
    res = _assess(player_context_snapshot=None, draft_rows=None)
    young = _by_name(res)["Young DL"]
    assert young.inputs["snapUsage"]["state"] == "unavailable"
    assert young.inputs["draftCapital"]["state"] == "unavailable"
    assert young.inputs["valueTrend30d"]["reason"] == "temporal_ledger_absent"
    assert young.inputs["weeklyRole"]["state"] == "not_supplied"
    assert young.inputs["injury"]["state"] == "not_supplied"
    assert young.drop_class != CLASS_CHURN


# ══ Archive board — invariants, not counts ══════════════════════════


def test_invariants_hold_on_the_archived_board(tmp_path):
    from tests.archive_fixtures import newest_complete_contract

    contract, name = newest_complete_contract()
    if contract is None:
        pytest.skip("no complete archived board")
    teams = (contract.get("sleeper") or {}).get("teams") or []
    if not teams:
        pytest.skip(f"{name} carries no rosters")
    cfg = load_protection_config()
    league_key = str((contract.get("meta") or {}).get("leagueKey") or "dynasty_main")
    for team in teams:
        owner = str(team.get("ownerId") or "")
        if not owner:
            continue
        first = next((p for p in team.get("players") or []), None)
        cons = resolve_constraints(contract=contract, persistent={"untouchables": [first]})
        res = assess_team_drops(
            contract,
            league_key=league_key,
            owner_id=owner,
            constraints=cons,
            now=NOW,
            player_context_snapshot=None,
            draft_rows=None,
            history_path=tmp_path / "absent.sqlite",
        )
        assert sum(res.summary["counts"].values()) == len(res.assessments)
        for a in res.assessments:
            assert a.drop_class in (CLASS_PROTECTED, CLASS_CONDITIONAL, CLASS_CHURN)
            assert a.reasons, a.name
            if a.dynasty_value is None:
                assert a.drop_class == CLASS_PROTECTED, a.name
            if a.drop_class == CLASS_CHURN:
                assert a.confidence in cfg.churn_gap_max_by_confidence
                assert a.replacement_value is not None
                assert a.dynasty_value is not None
                gap = da._gap(a.dynasty_value, a.replacement_value)
                assert gap <= cfg.churn_gap_max_by_confidence[a.confidence] + 1e-9
                assert not a.locks
            if first and a.name == first:
                assert a.drop_class == CLASS_PROTECTED and a.locks
