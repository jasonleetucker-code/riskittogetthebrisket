"""Lane E: the public advisor result is a REDUCTION of the private engine's
per-team entries, at engine level (spec ``docs/trade/NTEAM_TRADE_ENGINE_SPEC.md``
§2.10 I11, §4.3 reduction rules, §2.6 / I14 worked example).

TEST-ONLY.  Sibling of ``test_multi_team_surface_parity.py``, which compares the
routes over HTTP; this module needs no client.  It folds in the cases of PR #1930
that the HTTP suite does not state:

1. **The spec's I14 one-to-many example, publicly.**  A +610 ``slight``, B -1000
   ``unfair``, C +500 ``unfair``: under ``fairness_bands_v2`` only ``fair`` counts
   as a fair trade (OD-F1), so every team and the overall are NOT FAIR, publicly
   and privately alike, and the overall carries the N >= 3 note.  The engine half
   of I14 is pinned in ``test_multi_team_properties`` / ``test_multi_team_parity_fixture``;
   what was not pinned is the public result for that exact trade.
2. **``public_advisor.evaluate`` IS ``reduce_fairness`` over the private entries.**
   On every Lane E board scenario, at 2, 3 and 4 teams, in both private modes:
   the public ``FairnessResult`` equals ``reduce_fairness`` applied to the
   private engine's own team entries -- with no fail-closed downgrade between
   them -- per-team result / reason code / overall follow the private fairness,
   and the result does not depend on the perspective the ledger was validated
   from.  (The HTTP tests compare the route's per-field answers; they never run
   the reduction itself over the private entries.)

Already pinned elsewhere -- NOT repeated here: roster-limit and Team Context
reader invariance of the public body (``test_multi_team_surface_parity`` /
``test_public_advisor_privacy_multi::test_m1_*``), and engine-level public ==
private result on the real archive (``test_public_advisor_archive_parity``).
"""

from __future__ import annotations

import types

from src.trade import analyze_service as svc
from src.trade import public_advisor as pa
from src.trade import trade_ledger as tl
from tests.parity import surface_harness as H
from tests.trade import multi_team_support as mts
from tests.trade import test_multi_team_properties as P
from tests.trade.test_multi_team_properties import _pinned  # noqa: F401 -- autouse pins

TEAM_COUNTS = (2, 3, 4)
#: Private engine state -> public result (spec §4.3 reduction rules).
PUBLIC_RESULT = {"FAIR": "FAIR", "NOT_FAIR": "NOT_FAIR", "UNABLE": "UNABLE_TO_DETERMINE"}


def _public_ledger(snap, teams, legs, perspective: int):
    return pa.validate(
        snap,
        perspective=perspective,
        teams=list(teams),
        legs=[(x["id"], x["from"], x["to"]) for x in legs],
        policy=pa.public_policy(max_teams=4, max_legs=128),
    )


def _reduction_of(out: dict, pub_ledger) -> pa.FairnessResult:
    """The public reduction applied to the PRIVATE engine's own team entries."""
    inputs = [pa.team_fairness_input(out["teams"][rid]) for rid in sorted(out["teams"])]
    return pa.reduce_fairness(
        inputs, overall_state=pa.public_overall_state(inputs), legs=pub_ledger.legs
    )


def _assert_public_follows_private(where, public: pa.FairnessResult, out: dict, mode: str) -> None:
    for row in public.teams:
        fairness = out["teams"][row.roster_id]["fairness"]
        assert row.result == PUBLIC_RESULT[fairness["state"]], (where, mode, row.roster_id)
        assert row.reason_code == fairness["reasonCode"], (where, mode, row.roster_id)
    overall = out["summary"]["fairnessOverall"]
    assert public.overall.result == PUBLIC_RESULT[overall["state"]], (where, mode)
    assert public.overall.reason_code == overall["reasonCode"], (where, mode)


# ══ 1. The spec's I14 example, publicly ════════════════════════════════════


def _labelled_posture(contract, league_key, team, *, build_if_missing):
    return {
        "available": True,
        "label": "PUSH",
        "evidence": "measured",
        "probabilities": {"PUSH": 0.7, "HOLD": 0.2, "RETOOL": 0.05, "REBUILD": 0.05},
        "confidence": "medium",
        "paramsVersion": "posture_v1_prior",
        "notes": ["SYNTHETIC_FIXTURE_POSTURE (LABELLED)"],
    }


def test_i14_one_to_many_example_is_not_fair_for_every_team_publicly_and_privately():
    snap = mts.synthetic_snapshot()
    teams = [1, 2, 3]
    legs = [
        {"id": "p:101", "from": 1, "to": 2},
        {"id": "p:102", "from": 1, "to": 3},
        {"id": "p:201", "from": 2, "to": 1},
        {"id": "p:301", "from": 3, "to": 1},
    ]
    ledger = tl.validate_ledger(snap, teams=teams, legs=legs, policy=tl.private_policy())
    pub_ledger = _public_ledger(snap, teams, legs, teams[0])
    public = pa.evaluate(snap, pub_ledger)
    outs = {
        mode: svc.analyze_trade_n(
            snap,
            ledger,
            mode=mode,
            counterfactuals=False,
            posture_resolver=_labelled_posture,
        )
        for mode in ("team_context", "asset_only")
    }
    for mode, out in outs.items():
        levels = {rid: out["teams"][rid]["fairness"]["level"] for rid in teams}
        assert levels == {1: "slight", 2: "unfair", 3: "unfair"}, mode
        assert _reduction_of(out, pub_ledger) == public, mode
        _assert_public_follows_private("I14", public, out, mode)
    assert [(r.roster_id, r.result) for r in public.teams] == [
        (1, "NOT_FAIR"),
        (2, "NOT_FAIR"),
        (3, "NOT_FAIR"),
    ]
    assert public.overall.result == "NOT_FAIR"
    assert public.overall.note == pa.MULTI_TEAM_NOTE  # N >= 3 note


# ══ 2. evaluate() is reduce_fairness() over the private entries ════════════


def test_public_result_is_the_reduction_of_the_private_engine_entries_on_every_board():
    seen: set[str] = set()
    checked = refused = 0
    for scenario in H.SCENARIOS:
        contract, snap = P._board(scenario)
        # ``corpus`` reads only ``scenario`` / ``snap`` / ``contract``: the same
        # seeded send-and-receive ledgers and near-even package cycles the HTTP
        # parity tests use (the cycles are what reach FAIR).
        board = types.SimpleNamespace(scenario=scenario, snap=snap, contract=contract)
        for n in TEAM_COUNTS:
            for teams, legs in H.corpus(board, n, random_count=2, near_even=2, tag="reduction"):
                where = (scenario, n, teams, legs)
                try:
                    ledger = P._validate(snap, teams, legs)
                except tl.LedgerError as exc:
                    # A generator artefact, not a product answer: on the
                    # multi-holder board a near-even cycle can put one player
                    # who sits on two rosters into two packages, which the
                    # ledger owner refuses (``duplicate_asset``) under every
                    # policy.  Nothing else may be refused.
                    assert (scenario, exc.reason) == ("multi_holder", "duplicate_asset"), where
                    refused += 1
                    continue
                pub_ledger = _public_ledger(snap, teams, legs, teams[0])
                public = pa.evaluate(snap, pub_ledger)
                for mode in ("team_context", "asset_only"):
                    out = P._run(snap, ledger, mode)
                    # No fail-closed downgrade between the two products.
                    assert _reduction_of(out, pub_ledger) == public, (where, mode)
                    _assert_public_follows_private(where, public, out, mode)
                # Perspective selects the default view only: the reduction is the
                # same from every team.
                for perspective in teams:
                    again = pa.evaluate(snap, _public_ledger(snap, teams, legs, perspective))
                    assert again == public, (where, perspective)
                seen |= {t.result for t in public.teams} | {public.overall.result}
                checked += 1
    assert checked >= len(H.SCENARIOS) * len(TEAM_COUNTS) * 2
    assert refused <= checked // 10, (refused, checked)
    # The generators reach every public result, so the equalities are not
    # vacuous on one result class.
    assert seen == {"FAIR", "NOT_FAIR", "UNABLE_TO_DETERMINE"}, seen
