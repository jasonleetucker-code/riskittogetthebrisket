"""Outlier-integrity-v2 DLF restoration readiness: structural invariants.

Directive 2026-10-20 §9 / prereg §15: DLF IDP (``dlfIdp``) and DLF Rookie IDP
(``dlfRookieIdp``) -- and D4's DLF Values (``dlfValuesSfTep``) -- may only ever
vote through the ONE established ``dlf`` provider family, sharing its cap, and
must never count as a second DLF opinion anywhere (blend weight, independence
count, Layer C corroboration). The full-board evidence is
``docs/sources/outlier_integrity_v2/dlf_readiness/``; these tests pin the
synthetic, board-independent half so a registry or lineage edit cannot quietly
give DLF a second family vote.

Read-only: no flag default, weight, cap or hold is touched here (the holds are
pinned by ``test_dlf_idp_hold_locked.py`` / ``test_dlf_values_hold_locked.py``).
"""

from __future__ import annotations

import math

import pytest

from src.api import data_contract as dc
from src.api import outlier_policy as op

DLF_BOARDS = ("dlfSf", "dlfRookieSf", "dlfIdp", "dlfRookieIdp", "dlfValuesSfTep")


def _registry(key: str) -> dict:
    return next(s for s in dc._RANKING_SOURCES if s.get("key") == key)


@pytest.mark.parametrize("key", DLF_BOARDS)
def test_every_dlf_board_is_one_family_and_one_provider(key: str) -> None:
    assert dc.correlation_group_for(key) == "dlf"
    assert dc._integrity_provider_of(key) == dc._integrity_provider_of("dlfSf")


def test_family_cap_gives_dlf_one_providers_authority() -> None:
    weights = {k: 1.0 for k in DLF_BOARDS} | {"idpTradeCalc": 1.0, "draftSharksIdp": 1.0}
    capped, factor = dc.cap_family_weights(weights)
    assert sum(capped[k] for k in DLF_BOARDS) == pytest.approx(1.0)
    # members keep proportional shares; nobody outside the family is touched
    assert {round(factor[k], 6) for k in DLF_BOARDS} == {0.2}
    assert capped["idpTradeCalc"] == 1.0 and capped["draftSharksIdp"] == 1.0


def test_family_cap_never_scales_a_stale_dlf_family_back_up() -> None:
    capped, _ = dc.cap_family_weights({"dlfIdp": 0.2, "dlfRookieIdp": 0.1})
    assert capped == {"dlfIdp": pytest.approx(0.2), "dlfRookieIdp": pytest.approx(0.1)}


def test_dlf_idp_boards_are_translated_not_raw() -> None:
    idp = _registry("dlfIdp")
    rookie = _registry("dlfRookieIdp")
    assert idp["scope"] == rookie["scope"] == dc.SOURCE_SCOPE_OVERALL_IDP
    assert idp.get("needs_shared_market_translation") is True
    assert rookie.get("needs_rookie_translation") is True
    pair = [p for p in dc.ROOKIE_LADDER_PAIRS if p[0] == "dlfRookieIdp"]
    assert len(pair) == 1 and pair[0][1] == "idpTradeCalc"
    assert pair[0][2] == {"DL", "LB", "DB"}


def _layer_c(pairs: list[tuple[str, float]]) -> op.LayerCVerdict:
    weights = dc.cap_family_weights({k: 1.0 for k, _v in pairs})[0]
    return op.assess_row_layer_c(
        pairs,
        curve=op.scope_curve("idp"),
        provider_of=dc._integrity_provider_of,
        family_of=dc.correlation_group_for,
        weights=weights,
        tau_c_big=math.log(4),  # the most catching registered grid point
    )


def test_two_dlf_boards_cannot_form_a_corroborated_reference() -> None:
    # Draft Sharks sits far from everyone; the only agreeing pair is DLF IDP +
    # DLF Rookie IDP -- one provider, so no reference exists and the dissent stays.
    v = _layer_c(
        [
            ("draftSharksIdp", 9000),
            ("dlfIdp", 1000),
            ("dlfRookieIdp", 1000),
            ("fantasyProsIdp", 300),
        ]
    )
    assert v.dropped == ()
    assert v.kept_because.get("draftSharksIdp") == op.C_KEPT_NO_REFERENCE
    # control: the same agreement from two DIFFERENT providers is a reference
    ctrl = _layer_c(
        [
            ("draftSharksIdp", 9000),
            ("dlfIdp", 1000),
            ("idpTradeCalc", 1000),
            ("fantasyProsIdp", 300),
        ]
    )
    assert ctrl.dropped == ("draftSharksIdp",)
    assert ctrl.details["draftSharksIdp"]["reference"] == ["dlfIdp", "idpTradeCalc"]


def test_a_second_dlf_board_does_not_corroborate_a_dlf_tail() -> None:
    # Both DLF boards agree with each other and with nobody else: DLF's own
    # second board is not "another provider", so both are still a tail.
    v = _layer_c(
        [
            ("draftSharksIdp", 1000),
            ("idpTradeCalc", 1000),
            ("fantasyProsIdp", 1050),
            ("dlfIdp", 9000),
            ("dlfRookieIdp", 9000),
        ]
    )
    assert set(v.dropped) == {"dlfIdp", "dlfRookieIdp"}
    assert v.details["dlfIdp"]["familyShare"] == pytest.approx(0.25)
