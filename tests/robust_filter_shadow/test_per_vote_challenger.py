"""The per-vote rank-space challenger is a THIRD registered challenger of the
filter shadow ledger (docs/valuation/evidence/rank-space-hampel-per-vote-
2026-10-17/PREREGISTRATION.md).

Pins: its variants pin the joint flags and the ORIGINAL rank-space flag OFF and
differ only in the per-vote flag; its version, seed (2027) and preregistration;
its own ledger directory; the reproduction check re-runs the per-vote filter
from the row's stamps; the segment reports classify offense non-TE / TE / IDP
without guessing; the original two challengers are byte-identical.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

from src.api import data_contract as dc
from src.robust_filter_shadow import f1_diagnostics as F
from src.robust_filter_shadow import ledger as L
from src.robust_filter_shadow import outcomes as O
from src.robust_filter_shadow import record as R

REPO = Path(__file__).resolve().parents[2]


def _load_cli():
    spec = importlib.util.spec_from_file_location(
        "joint_filter_shadow_cli_pv", REPO / "scripts" / "joint_filter_shadow.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_per_vote_variants_pin_every_other_challenger_off():
    inc, ch = R.variant_specs(Path("/tree"), R.CHALLENGER_PER_VOTE)
    inc_flags, ch_flags = dict(inc["flags"]), dict(ch["flags"])
    assert inc_flags == {
        R.CHALLENGER_FLAG: False,
        R.SPARSE_FLAG: False,
        R.RANK_SPACE_FLAG: False,
        R.PER_VOTE_FLAG: False,
    }
    assert ch_flags == {**inc_flags, R.PER_VOTE_FLAG: True}
    spec = R.challenger_spec(R.CHALLENGER_PER_VOTE)
    assert spec["version"] == "rank-space-hampel-per-vote-v1"
    assert spec["bootstrapSeed"] == 2027
    assert spec["preregistration"].endswith(
        "rank-space-hampel-per-vote-2026-10-17/PREREGISTRATION.md"
    )
    assert (REPO / spec["preregistration"]).is_file()


def test_original_challengers_are_unchanged():
    assert R.challenger_spec(R.CHALLENGER_RANK_SPACE)["version"] == "rank-space-hampel-v1"
    assert R.challenger_spec(R.CHALLENGER_RANK_SPACE)["bootstrapSeed"] == 17
    assert dict(R.challenger_spec(R.CHALLENGER_RANK_SPACE)["challenger"]) == {
        R.CHALLENGER_FLAG: False,
        R.SPARSE_FLAG: False,
        R.RANK_SPACE_FLAG: True,
    }
    assert R.challenger_spec(R.CHALLENGER_JOINT)["bootstrapSeed"] == 1571


def test_own_ledger_directory_and_record_key():
    dirs = {L.challenger_dir(c) for c in R.CHALLENGERS}
    assert len(dirs) == len(R.CHALLENGERS)
    common = dict(
        mode=R.MODE_REPLAY,
        board={"payloadSha256": "a" * 64},
        pins={"codeRevision": "c"},
        comparison={},
        recorded_at="t",
    )
    keys = {R.assemble_record(**common, challenger=c)["key"] for c in R.CHALLENGERS}
    assert len(keys) == 3


def test_flag_is_declared_default_off():
    from src.api import feature_flags

    assert feature_flags._DEFAULTS[R.PER_VOTE_FLAG] is False


def _row(name, obs, dropped, *, pools, te=None, value=9000, rank=1, position="WR"):
    meta = {}
    for s, v in obs.items():
        m = {"valueContribution": v, "appliedWeight": 1.0, "rankCoordinatePool": pools[s]}
        if te and s in te:
            m.update(te[s])
        meta[s] = m
    return {
        "displayName": name,
        "assetClass": "offense",
        "position": position,
        "sourceRankMeta": meta,
        "droppedSources": list(dropped),
        "rankDerivedValue": value,
        "canonicalConsensusRank": rank,
    }


def test_forward_maps_are_rebuilt_from_stamps():
    row = _row(
        "T",
        {"dlfSf": 8000, "draftSharks": 7900, "idpTradeCalc": 7800, "fantasyCalc": 8100},
        [],
        pools={
            "dlfSf": "offense",
            "draftSharks": "shared_market",
            "idpTradeCalc": "shared_market",
            "fantasyCalc": "offense",
        },
        te={
            "dlfSf": {"tepBoostApplied": True, "tepBasisFrom": "base", "tepBasisTo": "tepp"},
            "idpTradeCalc": {"tepNativeCorrectionApplied": True, "tepNativeCorrection": 1.1},
        },
        position="TE",
    )
    maps = R.per_vote_forward_maps(row)
    from src.canonical.rank_coordinates import curve_for_pool

    assert maps["dlfSf"] == (*curve_for_pool("offense"), dc.PER_VOTE_TE_BASIS, ("base", "tepp"))
    assert maps["draftSharks"] == (*curve_for_pool("shared_market"), None, None)
    assert maps["idpTradeCalc"] == (*curve_for_pool("shared_market"), dc.PER_VOTE_TE_FLAT, 1.1)


def test_reproduction_reruns_the_per_vote_filter():
    obs = {"dlfSf": 9300, "fantasyProsSf": 9250, "fantasyCalc": 9320, "dynastyDaddySf": 9280}
    obs["ktcCrowdSfTep"] = 7000
    pools = {s: "offense" for s in obs}
    probe = _row("Top", obs, [], pools=pools)
    maps = R.per_vote_forward_maps(probe)
    _k, pv_drop = dc._hampel_filter_rank_space_per_vote(sorted(obs.items()), forward_maps=maps)
    _k, inc_drop = dc._hampel_filter_per_player(sorted(obs.items()))
    inc = {"playersArray": [_row("Top", obs, inc_drop, pools=pools)]}
    ch = {"playersArray": [_row("Top", obs, pv_drop, pools=pools, value=9100)]}
    rec = R.shadow_record(inc, ch, challenger_kind=R.CHALLENGER_PER_VOTE)
    (entry,) = rec["rows"]
    assert entry["reproduced"]["challenger"] is True
    assert set(entry["challengerStats"]) == {"centre", "scale", "perVote", "dropped"}
    assert set(entry["challengerStats"]["perVote"]) == set(obs)


def test_segments_classify_without_guessing():
    assert O.segment_of("idp", "LB") == O.SEGMENT_IDP
    assert O.segment_of("offense", "TE") == O.SEGMENT_TE
    assert O.segment_of("offense", "WR") == O.SEGMENT_OFFENSE_NON_TE
    assert O.segment_of("offense", None) is None
    assert O.segment_of("pick", None) is None
    assert O.EvaluationConfig().segment is None


def test_agreed_drops_take_their_position_from_the_record():
    record = {
        "rows": [],
        "agreedDrops": [["A", "dlfSf", "offense"], ["B", "dlfSf", "offense"]],
        "positions": {"A": "TE"},
    }
    sides = list(O._sides(record))
    assert sides == [
        ("R", "A", "dlfSf", "offense", "TE"),
        ("R", "B", "dlfSf", "offense", None),
    ]


class _FakeBoard:
    record = {"pins": {"codeRevision": "c"}, "board": {"completeness": "complete"}}


def test_cli_evaluate_reports_segments_with_the_per_vote_seed(monkeypatch, tmp_path):
    cli = _load_cli()
    seen = []
    monkeypatch.setattr(cli, "load_boards", lambda base, mode: [_FakeBoard()])
    monkeypatch.setattr(
        O,
        "evaluate",
        lambda boards, cfg=None: seen.append(cfg or O.EvaluationConfig()) or {},
    )
    out = tmp_path / "e.json"
    args = argparse.Namespace(
        dir=tmp_path,
        mode=R.MODE_REPLAY,
        out=out,
        sensitivities=True,
        challenger=R.CHALLENGER_PER_VOTE,
        no_learning_receipts=True,
    )
    assert cli.cmd_evaluate(args) == 0
    assert {c.seed for c in seen} == {2027}
    assert [c.segment for c in seen if c.segment] == list(O.SEGMENTS)
    written = json.loads(out.read_text(encoding="utf-8"))
    assert set(written["segments"]) == set(O.SEGMENTS)
    assert written["challengerVersion"] == "rank-space-hampel-per-vote-v1"


def test_cli_refuses_record_and_adversarial(tmp_path):
    cli = _load_cli()
    for command in ("record", "adversarial"):
        assert (
            cli.main(["--challenger", "rank_space_per_vote", "--dir", str(tmp_path), command]) == 1
        )


def test_player_level_reports():
    table = {
        "Star": [
            "offense",
            3,
            3,
            9000.0,
            9300.0,
            8100.0,
            True,
            ["dlfSf", "ktcCrowdSfTep"],
            [],
            ["ktcCrowdSfTep"],
        ],
        "Deep": ["offense", 300, 290, 1000.0, 1500.0, None, True, ["dlfSf"], [], []],
        "Pick": ["pick", 40, 40, 3000.0, 6000.0, None, False, [], [], []],
    }
    moves = F.largest_value_moves([("b", table, {"Star": "WR"})], top=5)
    assert [m["name"] for m in moves] == ["Deep", "Star"]  # picks excluded
    rej = F.top24_market_rejections(table)
    assert rej == [
        {
            "name": "Star",
            "rankIncumbent": 3,
            "source": "ktcCrowdSfTep",
            "champion": "keep",
            "challenger": "drop",
        }
    ]
    census = F.coordinate_census_total(
        [
            {
                "byFamily": {
                    "OFFENSE": {"votes": 4, "droppedIncumbent": 1, "droppedChallenger": 2}
                },
                "rows": {"filterRows": 2, "mixedCurveRows": 1},
            }
        ]
    )
    assert census["byFamily"]["OFFENSE"]["shareDroppedChallenger"] == 0.5
    assert census["rows"]["shareMixedCurve"] == 0.5
