"""The derived-evidence lineage registry (League Intelligence Stage E)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.evidence_lineage import registry as reg
from src.evidence_lineage.registry import LineageViolation, assert_voting_terms_valid, group_of

ROOT = Path(__file__).resolve().parents[2]


def _t(member: str, vote: bool = True) -> dict:
    return {"lineage_member": member, "counted_as_vote": vote}


def test_declared_groups_and_voting_flags():
    assert set(reg.GROUPS) == {
        "canonical_market",
        "league_scored_projection",
        "team_strategy_context",
        "manager_context",
        "market_comparables",
    }
    assert reg.GROUPS["canonical_market"].members == ("rank_derived_value", "package_va")
    assert set(reg.GROUPS["league_scored_projection"].members) == {
        "projection_snapshot",
        "bdvm_fundamental",
        "ros_ensemble",
        "bestball_lineup_delta",
        "bestball_marginal",
        "bestball_horizon",
        "playoff_presim",
        "league_fair_value",
    }
    for gid in ("team_strategy_context", "manager_context", "market_comparables"):
        assert reg.GROUPS[gid].voting is False
    posture = reg.GROUPS["team_strategy_context"]
    assert posture.members == ("posture",)
    assert set(posture.selection_dependencies) == {"league_scored_projection", "rosValue"}
    assert reg.PARTIAL_OVERLAPS == {
        frozenset({"canonical_market", "league_scored_projection"}): "current_season_production"
    }


def test_group_of_raises_on_undeclared_member():
    assert group_of("package_va") == "canonical_market"
    assert group_of("league_fair_value") == "league_scored_projection"
    with pytest.raises(KeyError):
        group_of("vibes")


def test_c_and_d2_both_voting_raises():
    with pytest.raises(LineageViolation):
        assert_voting_terms_valid([_t("bestball_lineup_delta"), _t("bestball_horizon")])


def test_rank_value_and_va_both_voting_raises():
    with pytest.raises(LineageViolation):
        assert_voting_terms_valid([_t("rank_derived_value"), _t("package_va")])


def test_a_posture_vote_raises():
    with pytest.raises(LineageViolation):
        assert_voting_terms_valid([_t("rank_derived_value"), _t("posture")])
    with pytest.raises(LineageViolation):
        assert_voting_terms_valid([_t("manager_tendency")])


def test_undeclared_member_in_terms_raises_even_when_not_voting():
    with pytest.raises(LineageViolation):
        assert_voting_terms_valid([_t("rank_derived_value"), _t("vibes", vote=False)])


def test_a_plus_c_passes_with_medium_agreement_cap():
    v = assert_voting_terms_valid(
        [
            _t("rank_derived_value"),
            _t("bestball_lineup_delta"),
            _t("bestball_horizon", vote=False),
            _t("posture", vote=False),
        ]
    )
    assert v.voting_groups == ("canonical_market", "league_scored_projection")
    assert v.partial_overlaps == ("current_season_production",)
    assert v.agreement_cap == "medium"


def test_a_alone_has_no_cap_and_camel_case_is_accepted():
    v = assert_voting_terms_valid([{"lineageMember": "rank_derived_value", "countedAsVote": True}])
    assert v.voting_groups == ("canonical_market",)
    assert v.agreement_cap is None


def test_counted_as_vote_must_be_literally_true():
    # A truthy non-bool never votes (no accidental double count from "yes").
    v = assert_voting_terms_valid(
        [_t("rank_derived_value"), {"lineage_member": "package_va", "counted_as_vote": 1}]
    )
    assert v.voting_members == ("rank_derived_value",)


def test_source_families_are_b10_ids_resolving_through_source_lineage():
    """Every referenced family is a B10 id (``correlation_group_for``) of a
    source recorded in ``config/sources/source_lineage.json`` -- referenced,
    never redefined.  Read-only."""
    from src.api import data_contract

    lineage = json.loads((ROOT / "config/sources/source_lineage.json").read_text(encoding="utf-8"))
    known = {data_contract.correlation_group_for(k) for k in lineage["sources"]}
    for g in reg.GROUPS.values():
        assert set(g.descends_from_source_families) <= known, g.id
    market = set(reg.GROUPS["canonical_market"].descends_from_source_families)
    assert {"ktcCrowd", "ktcTrades", "idpTradeCalc"} <= market
    # The non-voting KTC benchmark is not a canonical-board family.
    assert "ktcCrowdTradesSfTep" not in market


def test_registry_imports_nothing_from_src():
    import ast

    tree = ast.parse((ROOT / "src/evidence_lineage/registry.py").read_text(encoding="utf-8"))
    mods = {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    mods |= {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    assert not any(m.startswith("src") for m in mods)


def test_snapshot_is_json_serialisable():
    snap = reg.registry_snapshot()
    assert json.loads(json.dumps(snap))["registryVersion"] == reg.REGISTRY_VERSION
