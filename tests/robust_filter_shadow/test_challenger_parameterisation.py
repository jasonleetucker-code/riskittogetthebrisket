"""The filter shadow ledger is parameterised by challenger (joint | rank_space).

Pins: the joint default is unchanged (flags, version, seed, ledger directory,
CLI pins); the rank-space variants pin both joint flags OFF and differ only in
``rank_space_hampel_challenger``; the rank-space reproduction check re-runs the
rank-space filter; the seed reaches the bootstrap; record/adversarial refuse
the rank-space challenger; and the F1 diagnostics count what they claim.
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

import pytest

from src.api.joint_robust_filter import CHALLENGER_VERSION
from src.robust_filter_shadow import f1_diagnostics as F
from src.robust_filter_shadow import ledger as L
from src.robust_filter_shadow import outcomes as O
from src.robust_filter_shadow import record as R

REPO = Path(__file__).resolve().parents[2]


def _load_cli():
    spec = importlib.util.spec_from_file_location(
        "joint_filter_shadow_cli", REPO / "scripts" / "joint_filter_shadow.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# ── variants ────────────────────────────────────────────────────────────


def test_joint_default_variants_are_unchanged():
    inc, ch = R.variant_specs()
    assert inc == {"flags": [(R.CHALLENGER_FLAG, False), (R.SPARSE_FLAG, False)]}
    assert ch == {"flags": [(R.CHALLENGER_FLAG, True), (R.SPARSE_FLAG, False)]}
    assert R.variant_specs("x/y") == R.variant_specs("x/y", R.CHALLENGER_JOINT)
    assert R.variant_flags() == {
        "incumbent": {R.CHALLENGER_FLAG: False, R.SPARSE_FLAG: False},
        "challenger": {R.CHALLENGER_FLAG: True, R.SPARSE_FLAG: False},
    }
    assert R.challenger_spec()["version"] == CHALLENGER_VERSION
    assert R.challenger_spec()["bootstrapSeed"] == O.BOOTSTRAP_SEED == 1571


def test_rank_space_variants_pin_both_joint_flags_off_and_differ_only_in_its_flag():
    inc, ch = R.variant_specs(Path("/tree"), R.CHALLENGER_RANK_SPACE)
    assert inc["csv_root"] == ch["csv_root"] == Path("/tree")
    inc_flags, ch_flags = dict(inc["flags"]), dict(ch["flags"])
    assert inc_flags == {
        R.CHALLENGER_FLAG: False,
        R.SPARSE_FLAG: False,
        R.RANK_SPACE_FLAG: False,
    }
    assert ch_flags == {**inc_flags, R.RANK_SPACE_FLAG: True}
    spec = R.challenger_spec(R.CHALLENGER_RANK_SPACE)
    assert spec["version"] == "rank-space-hampel-v1"
    assert spec["bootstrapSeed"] == 17
    assert spec["preregistration"].endswith("rank-space-hampel-2026-10-17/PREREGISTRATION.md")
    assert (REPO / spec["preregistration"]).is_file()


def test_rank_space_flag_is_a_declared_default_off_flag():
    from src.api import feature_flags

    assert feature_flags._DEFAULTS[R.RANK_SPACE_FLAG] is False


def test_unknown_challenger_is_refused():
    with pytest.raises(KeyError):
        R.variant_specs(None, "nope")


def test_build_pair_threads_the_challenger(monkeypatch):
    from src.api import value_replay as vr

    seen = []
    monkeypatch.setattr(vr, "build", lambda raw, spec: seen.append(spec) or {"playersArray": []})
    R.build_pair({}, None, R.CHALLENGER_RANK_SPACE)
    assert [dict(s["flags"])[R.RANK_SPACE_FLAG] for s in seen] == [False, True]
    seen.clear()
    R.build_pair({})
    assert all(R.RANK_SPACE_FLAG not in dict(s["flags"]) for s in seen)


def test_assemble_record_stamps_each_challengers_version_and_keys_them_apart():
    common = dict(
        mode=R.MODE_REPLAY,
        board={"payloadSha256": "a" * 64},
        pins={"codeRevision": "c"},
        comparison={},
        recorded_at="t",
    )
    joint = R.assemble_record(**common)
    rank = R.assemble_record(**common, challenger=R.CHALLENGER_RANK_SPACE)
    assert joint["pins"]["challengerVersion"] == CHALLENGER_VERSION
    assert rank["pins"]["challengerVersion"] == "rank-space-hampel-v1"
    assert joint["key"] != rank["key"]


def test_separate_ledger_directory_per_challenger():
    assert L.challenger_dir() == L.DEFAULT_DIR
    assert L.challenger_dir(R.CHALLENGER_RANK_SPACE) != L.DEFAULT_DIR
    assert set(L.CHALLENGER_DIRS) == set(R.CHALLENGERS)


# ── reproduction check uses the rank-space filter ───────────────────────


def _meta(v):
    return {"valueContribution": v, "appliedWeight": 1.0}


def _row(name, obs, dropped, cls="offense", value=9000, rank=1):
    return {
        "displayName": name,
        "assetClass": cls,
        "position": "WR",
        "sourceRankMeta": {s: _meta(v) for s, v in obs.items()},
        "droppedSources": list(dropped),
        "rankDerivedValue": value,
        "canonicalConsensusRank": rank,
    }


def test_rank_space_reproduction_reruns_the_rank_space_filter():
    from src.api import data_contract as dc

    # Top of the board: rank sources compressed near the ceiling, one market vote far below.
    obs = {
        "dlfSf": 9300,
        "fantasyProsSf": 9250,
        "fantasyCalc": 9320,
        "dynastyDaddySf": 9280,
        "ktcCrowdSfTep": 7900,
    }
    curve = R.rank_space_curve({"assetClass": "offense"})
    _k, rank_drop = dc._hampel_filter_rank_space(sorted(obs.items()), curve=curve)
    _k, inc_drop = dc._hampel_filter_per_player(sorted(obs.items()))
    inc = {"playersArray": [_row("Top", obs, inc_drop)]}
    ch = {"playersArray": [_row("Top", obs, rank_drop, value=9100)]}
    rec = R.shadow_record(inc, ch, challenger_kind=R.CHALLENGER_RANK_SPACE)
    (entry,) = rec["rows"]  # listed because the published value moved
    assert entry["reproduced"] == {"incumbent": True, "challenger": True}
    assert set(entry["challengerStats"]) == {"centre", "scale", "threshold"}
    assert entry["challengerStats"]["centre"] > 0  # percentile units, not values
    # A stamped rank-space decision that the joint check would not reproduce is
    # still reproduced under the rank-space check -- the check follows the kind.
    wrong = {"playersArray": [_row("Top", obs, ["fantasyCalc"], value=9100)]}
    rec = R.shadow_record(inc, wrong, challenger_kind=R.CHALLENGER_RANK_SPACE)
    assert rec["counts"]["reproducedChallenger"] == 0


def test_rank_space_curve_follows_the_pipeline_selection():
    from src.canonical import player_valuation as pv

    assert R.rank_space_curve({"assetClass": "idp"}) == (
        pv.IDP_HILL_PERCENTILE_C,
        pv.IDP_HILL_PERCENTILE_S,
    )
    assert R.rank_space_curve({"assetClass": "offense"}) == (
        pv.HILL_PERCENTILE_C,
        pv.HILL_PERCENTILE_S,
    )


# ── the seed reaches the bootstrap ──────────────────────────────────────


def test_seed_reaches_the_bootstrap_and_the_default_is_unchanged():
    assert O.EvaluationConfig().seed == O.BOOTSTRAP_SEED
    assert O.EvaluationConfig(seed=17).seed == 17
    units = [
        O.ObservationOutcome(
            day=None,
            block=i % 6,
            side="K" if i % 2 else "X",
            name="n",
            source="s",
            asset_class="offense",
            m=(i % 7) / 7.0,
            r=None,
            delisted=False,
        )
        for i in range(60)
    ]
    result = {"observations": units, "rows": [], "census": {}}
    default = O.summarize_horizon(result)
    assert default == O.summarize_horizon(result, seed=O.BOOTSTRAP_SEED)
    assert default["delta"] != O.summarize_horizon(result, seed=17)["delta"]


# ── CLI ─────────────────────────────────────────────────────────────────


def test_cli_refuses_record_and_adversarial_for_rank_space(tmp_path):
    cli = _load_cli()
    for command in ("record", "adversarial"):
        assert cli.main(["--challenger", "rank_space", "--dir", str(tmp_path), command]) == 1
    assert not any(tmp_path.iterdir())


def test_cli_joint_pins_are_unchanged_and_rank_space_pins_its_flags(monkeypatch):
    cli = _load_cli()
    joint = cli._base_pins()
    assert joint["variants"] == {
        "incumbent": {R.CHALLENGER_FLAG: False, R.SPARSE_FLAG: False},
        "challenger": {R.CHALLENGER_FLAG: True, R.SPARSE_FLAG: False},
    }
    rank = cli._base_pins(R.CHALLENGER_RANK_SPACE)
    assert rank["variants"]["challenger"][R.RANK_SPACE_FLAG] is True
    assert rank["variants"]["incumbent"][R.RANK_SPACE_FLAG] is False


def test_cli_default_dir_follows_the_challenger(monkeypatch):
    cli = _load_cli()
    seen = {}
    monkeypatch.setattr(cli, "cmd_summary", lambda args: seen.setdefault("dir", args.dir) and 0)
    cli.main(["--challenger", "rank_space", "summary"])
    assert seen["dir"] == L.challenger_dir(R.CHALLENGER_RANK_SPACE)
    seen.clear()
    cli.main(["summary"])
    assert seen["dir"] == L.DEFAULT_DIR


def test_cli_evaluate_uses_the_challengers_seed_and_preregistration(monkeypatch, tmp_path):
    cli = _load_cli()
    seeds = []
    monkeypatch.setattr(cli, "load_boards", lambda base, mode: [object()])
    monkeypatch.setattr(
        O,
        "evaluate",
        lambda boards, cfg=None: seeds.append((cfg or O.EvaluationConfig()).seed) or {},
    )
    out = tmp_path / "e.json"
    args = argparse.Namespace(
        dir=tmp_path,
        mode=R.MODE_REPLAY,
        out=out,
        sensitivities=True,
        challenger=R.CHALLENGER_RANK_SPACE,
        no_learning_receipts=True,
    )
    monkeypatch.setattr(cli, "load_boards", lambda base, mode: [_FakeBoard()])
    assert cli.cmd_evaluate(args) == 0
    assert set(seeds) == {17} and len(seeds) == 7
    import json

    written = json.loads(out.read_text())
    assert written["bootstrapSeed"] == 17
    assert written["preregistration"].endswith("rank-space-hampel-2026-10-17/PREREGISTRATION.md")


class _FakeBoard:
    record = {"pins": {"codeRevision": "c"}, "board": {"completeness": "complete"}}


# ── F1 diagnostics ──────────────────────────────────────────────────────


def _fam(source):
    return {
        "dlfSf": "dlf",
        "fantasyCalc": "fc",
        "ktcCrowdSfTep": "ktcCrowd",
        "ktcTradesSfTep": "ktcTrades",
        "idpTradeCalc": "idptc",
    }.get(source, source)


def test_f1_rows_and_aggregate_count_what_they_claim():
    obs = {"dlfSf": 9300, "fantasyCalc": 9250, "ktcCrowdSfTep": 7900, "ktcTradesSfTep": 8000}
    inc = {
        "playersArray": [
            {
                **_row("A", obs, ["ktcCrowdSfTep", "ktcTradesSfTep"], value=9200, rank=3),
                "ktcMarket": {"normalizedValue": 8000},
            },
            {**_row("B", obs, [], value=4000, rank=150), "ktcMarket": {"normalizedValue": 5000}},
            {**_row("P", obs, [], cls="pick", value=3000, rank=20)},
        ]
    }
    ch = {
        "playersArray": [
            {**_row("A", obs, [], value=9000, rank=3), "ktcMarket": {"normalizedValue": 8000}},
            {
                **_row("B", obs, ["idpTradeCalc"], value=4000, rank=150),
                "ktcMarket": {"normalizedValue": 5000},
            },
            {**_row("P", obs, [], cls="pick", value=3000, rank=20)},
        ]
    }
    table = F.f1_rows(inc, ch)
    assert set(table) == {"A", "B", "P"}
    agg = F.aggregate([table], family_of=_fam)
    d1 = agg["D1_market_rejection_share"]
    assert d1["1-24"]["champion"] == {"voting": 2, "rejected": 2, "share": 1.0}
    assert d1["1-24"]["challenger"] == {"voting": 2, "rejected": 0, "share": 0.0}
    d2 = agg["D2_rows_with_market_rejected"]["1-24"]
    assert d2 == {"rows": 1, "champion": 1, "challenger": 0}  # the pick is not a filter row
    d4 = agg["D4_family_wiped"]["rowsByBand"]["all"]
    assert d4["champion"] == 1 and d4["challenger"] == 0
    d5 = agg["D5_model_vs_ktc_market_median"]
    assert d5["1-24"]["champion"] == pytest.approx(9200 / 8000 - 1, abs=1e-4)
    assert d5["1-24"]["challenger"] == pytest.approx(9000 / 8000 - 1, abs=1e-4)
    d3 = agg["D3_value_movement"]["offense"]
    assert d3["rows"] == 2 and d3["rowsMoved"] == 1


def test_wiped_families_needs_every_member_dropped():
    fam = {"a1": "A", "a2": "A", "b": "B"}.get
    assert F.wiped_families(["a1", "a2", "b"], ["a1"], fam) == []
    assert F.wiped_families(["a1", "a2", "b"], ["a1", "a2"], fam) == ["A"]


def test_market_sources_are_the_pipelines_value_direct_voters():
    from src.api import data_contract as dc

    assert set(F.MARKET_SOURCES) == set(dc._VALUE_BASED_SOURCES)


def test_band_edges():
    assert F.band_of(24) == "1-24" and F.band_of(25) == "25-50"
    assert F.band_of(800) == "401-800" and F.band_of(801) is None and F.band_of(None) is None
