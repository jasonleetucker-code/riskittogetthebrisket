"""Family-capped source voting (owner directive 2026-09-24).

Every member of a correlation family votes with its own effective weight;
the family's TOTAL is capped at one provider's authority.  Replaces the
"family head wins" selection, which stays reachable behind the
``source_family_cap`` rollback flag.
"""

from __future__ import annotations

import pytest

from src.api import data_contract as dc
from src.api.confidence import FamilyEvidence


def _cap(weights: dict[str, float], monkeypatch, groups: dict[str, str]):
    monkeypatch.setattr(dc, "correlation_group_for", lambda k: groups.get(k, k))
    return dc.cap_family_weights(weights)


GROUPS = {"dlfValue": "dlf", "dlfRank": "dlf", "other": "other"}


def test_both_fresh_members_vote_and_split_one_providers_authority(monkeypatch):
    adjusted, factor = _cap({"dlfValue": 1.0, "dlfRank": 1.0}, monkeypatch, GROUPS)
    assert adjusted == pytest.approx({"dlfValue": 0.5, "dlfRank": 0.5})
    assert factor == pytest.approx({"dlfValue": 0.5, "dlfRank": 0.5})


def test_fresher_member_keeps_the_larger_share(monkeypatch):
    adjusted, _ = _cap({"dlfValue": 1.0, "dlfRank": 0.25}, monkeypatch, GROUPS)
    assert adjusted["dlfValue"] == pytest.approx(0.8)
    assert adjusted["dlfRank"] == pytest.approx(0.2)
    assert sum(adjusted.values()) == pytest.approx(1.0)


def test_a_stale_family_is_never_scaled_back_up(monkeypatch):
    adjusted, factor = _cap({"dlfValue": 0.2, "dlfRank": 0.1}, monkeypatch, GROUPS)
    assert adjusted == pytest.approx({"dlfValue": 0.2, "dlfRank": 0.1})
    assert set(factor.values()) == {1.0}


def test_a_missing_member_does_not_remove_its_sibling(monkeypatch):
    adjusted, _ = _cap({"dlfRank": 0.7}, monkeypatch, GROUPS)
    assert adjusted == pytest.approx({"dlfRank": 0.7})


def test_other_families_are_untouched(monkeypatch):
    adjusted, _ = _cap({"dlfValue": 1.0, "dlfRank": 1.0, "other": 1.0}, monkeypatch, GROUPS)
    assert adjusted["other"] == pytest.approx(1.0)
    # Two DLF datasets can never outvote one independent provider.
    assert adjusted["dlfValue"] + adjusted["dlfRank"] == pytest.approx(adjusted["other"])


def test_the_real_ktc_families_stay_separate_voters():
    # Owner decision (2026-09-23): Crowd and Trades are two independent
    # voters; Fantasy Navigator sits inside the Crowd family, so it can never
    # become a hidden third full KTC vote.
    adjusted, _ = dc.cap_family_weights(
        {"ktcCrowdSfTep": 1.0, "ktcTradesSfTep": 1.0, "fantasyNavigatorSf": 1.0}
    )
    assert adjusted["ktcTradesSfTep"] == pytest.approx(1.0)
    assert adjusted["ktcCrowdSfTep"] + adjusted["fantasyNavigatorSf"] == pytest.approx(1.0)


def test_confidence_still_sees_one_evidence_per_family(monkeypatch):
    monkeypatch.setattr(dc, "correlation_group_for", lambda k: {"a1": "fam", "a2": "fam"}.get(k, k))
    evidence = dc._family_evidence_for_row(
        row={"position": "WR"},
        effective_source_ranks={"a1": 1, "a2": 2, "b": 3},
        effective_source_meta={
            "a1": {"appliedWeight": 0.2, "valueContribution": 5000},
            "a2": {"appliedWeight": 0.8, "valueContribution": 5200},
            "b": {"appliedWeight": 1.0, "valueContribution": 5100},
        },
        src_by_key={},
        family_by_key={"a1": "fam", "a2": "fam", "b": "b"},
        fresh_by_source={"a1": True, "a2": True, "b": True},
    )
    by_family = {ev.family: ev for ev in evidence}
    assert sorted(by_family) == ["b", "fam"]
    # The representative is the member that carried the most weight, with its
    # own published contribution, not an average of the family.
    assert by_family["fam"].source_key == "a2"
    assert by_family["fam"].value_contribution == 5200
    assert all(isinstance(ev, FamilyEvidence) for ev in evidence)


def test_a_user_weight_override_raises_its_familys_ceiling(monkeypatch):
    # Owner rule: a user override replaces the BASE weight.  A cap fixed at
    # 1.0 would silently undo a 2.0 override; the ceiling follows the base.
    adjusted, factor = _cap_with_base({"dlfValue": 2.0}, {"dlfValue": 2.0}, monkeypatch, GROUPS)
    assert adjusted == pytest.approx({"dlfValue": 2.0})
    both, _ = _cap_with_base(
        {"dlfValue": 2.0, "dlfRank": 1.0}, {"dlfValue": 2.0, "dlfRank": 1.0}, monkeypatch, GROUPS
    )
    assert sum(both.values()) == pytest.approx(2.0)
    assert both["dlfValue"] / both["dlfRank"] == pytest.approx(2.0)


def test_default_base_weights_keep_the_one_provider_cap(monkeypatch):
    adjusted, _ = _cap_with_base(
        {"dlfValue": 1.0, "dlfRank": 1.0}, {"dlfValue": 1.0, "dlfRank": 1.0}, monkeypatch, GROUPS
    )
    assert adjusted == pytest.approx({"dlfValue": 0.5, "dlfRank": 0.5})


def _cap_with_base(weights, base, monkeypatch, groups):
    monkeypatch.setattr(dc, "correlation_group_for", lambda k: groups.get(k, k))
    return dc.cap_family_weights(weights, base=base)
