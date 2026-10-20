"""Outlier-integrity-v2 directive §5 gates as executable, full-pipeline gates.

The harness (``src/robust_filter_shadow/oiv2_gates.py``) builds every
corrupted case end to end and states which pipeline component each gate
measures; ``scripts/oiv2_gates.py`` is the executable gate (exit 0 only when
every gate passes) and refuses held-out boards. This file pins:

* the seven bars, verbatim from the directive (a bar can never be loosened to
  make a run pass);
* the replay seam is inert in serving and byte-identical when unused;
* the harness mechanics on a synthetic board (every case judged in every
  configuration, contamination measured, a not-run gate is never a pass);
* the held-out refusal;
* the gate OUTCOME on a real board, when a result is supplied
  (``OIV2_GATE_RESULT``): every gate must pass. A failing gate fails this test;
  it is never relabelled.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import re
import tempfile
from pathlib import Path

import pytest

from src.api import data_contract as dc
from src.api import value_replay as vr
from src.robust_filter_shadow import oiv2_gates as G
from tests.api import test_source_integrity as T

REPO = Path(__file__).resolve().parents[2]


def test_gate_bars_are_the_directive_section5_bars_verbatim():
    assert {g: v.get("bar") for g, v in G.GATES.items() if "bar" in v} == {
        "AD1a": 0.90,
        "AD1b": 0.90,
        "AD1c": 0.95,
        "AD1d": 0.95,
        "AD2": 0.90,
        "AD4": 0.95,
    }
    assert G.GATES["AD3"]["boardsRequired"] == 16
    assert [G.GATES[g]["factor"] for g in ("AD1a", "AD1b", "AD1c", "AD1d")] == [
        5.0,
        0.2,
        20.0,
        0.05,
    ]
    assert G.MATERIAL == 0.10
    assert len(G.AD3_SOURCES) * len(G.AD3_KINDS) == 16


def test_seam_is_none_in_serving_and_never_assigned_outside_replay():
    assert dc._ADVERSARIAL_VOTE_TRANSFORM is None
    assign = re.compile(r"_ADVERSARIAL_VOTE_TRANSFORM\s*(:[^=]*)?=(?!=)")
    offenders = []
    for path in [*(REPO / "src").rglob("*.py"), REPO / "server.py"]:
        text = path.read_text("utf-8", errors="replace")
        for line in text.splitlines():
            if assign.search(line) and "_vote_transform = _ADVERSARIAL" not in line:
                offenders.append(f"{path.relative_to(REPO)}: {line.strip()}")
    # Exactly one assignment: the module-level ``None`` definition.
    assert offenders == [
        'src/api/data_contract.py: _ADVERSARIAL_VOTE_TRANSFORM: "Callable[[Mapping[str, Any], str, float], float] | None" = None'
    ]


def _synthetic_root(tmp: str) -> Path:
    d = Path(tmp) / "CSVs" / "site_raw"
    d.mkdir(parents=True)
    for name, text in T._csvs(T.META).items():
        (d / name).write_text(text)
    return Path(tmp)


@pytest.mark.parametrize("config", ["incumbent", "v2"])
def test_identity_transform_is_byte_identical_to_no_seam(config):
    with tempfile.TemporaryDirectory() as tmp:
        root = _synthetic_root(tmp)
        plain = G.build(T.PAYLOAD, root, config)
        ident = G.build(T.PAYLOAD, root, config, lambda _r, _s, v: v)
    assert json.dumps(plain["playersArray"], sort_keys=True, default=str) == json.dumps(
        ident["playersArray"], sort_keys=True, default=str
    )


def test_harness_mechanics_on_a_synthetic_board():
    with tempfile.TemporaryDirectory() as tmp:
        root = _synthetic_root(tmp)
        clean = {c: G.build(T.PAYLOAD, root, c) for c in G.CONFIGS}
        cases = G.plan_cases(clean, seed=G.SEED, max_rows=12)
        assert {c.gate for c in cases} >= {"AD1a", "AD1b", "AD1c", "AD1d"}
        # deterministic planning
        assert cases == G.plan_cases(clean, seed=G.SEED, max_rows=12)
        for batch in G.batch_cases(cases):
            assert len({c.row for c in batch}) == len(batch)
            assert len({c.segment for c in batch}) == len(batch)
        results, census = G.run_cases(T.PAYLOAD, root, clean, cases)
    assert len(results) == len(cases)
    for r in results:
        assert set(r.harm) == set(G.CONFIGS)
        assert r.excluded["none"] is None
    for c in G.CONFIGS:
        assert census[c]["maxUncorruptedRowLogMove"] == 0.0
    summary = G.summarize_cases(results)
    verdicts = G.gate_verdicts(summary)
    assert verdicts["AD3"] is None  # not run is never a pass
    for gate in ("AD1a", "AD1b", "AD1c", "AD1d"):
        entry = summary[gate]
        assert entry["cases"] == sum(1 for r in results if r.case.gate == gate)
        assert entry["v2Passes"] == (
            entry["v2"]["passRate"] is not None and entry["v2"]["passRate"] >= entry["bar"]
        )


def test_a_case_counts_as_passed_only_when_excluded_or_harmless():
    case = G.Case("AD1c", "x", "s", 1000.0, 9999.0, ("s", "offense", "QB"), "3")
    r = G.CaseResult(case, harm={"none": 0.5, "incumbent": 0.5, "v2": 0.5}, excluded={"v2": None})
    assert r.material and not r.passed("v2")
    r.excluded["v2"] = "extreme_uncorroborated_tail"
    assert r.passed("v2")
    r2 = G.CaseResult(case, harm={"none": 0.05, "v2": 0.05}, excluded={})
    assert not r2.material


def test_ad3_harness_flags_a_reversed_board_and_reports_the_rest():
    with tempfile.TemporaryDirectory() as tmp:
        root = _synthetic_root(tmp)
        with contextlib.redirect_stdout(io.StringIO()):
            clean_none = G.build(T.PAYLOAD, root, "none")
            ov = G.ad3_overrides(clean_none, "fantasyCalc", "offense", "reversed")
            contract = G.build(T.PAYLOAD, root, "v2", G.transform_for(ov))
    assert ov
    assert G.ad3_flagged(contract, "fantasyCalc", "offense")


@pytest.mark.parametrize(
    "manifest", ["V_HELDOUT.json", "I_INDEPENDENT.json", "R_REGRESSION_PIN.json"]
)
def test_script_refuses_held_out_boards(manifest, tmp_path):
    from scripts import oiv2_gates as S

    data = json.loads(
        (REPO / "docs/sources/outlier_integrity_v2/manifests" / manifest).read_text("utf-8")
    )
    board = next(b["board"] for b in data["boards"] if b.get("board"))
    assert S.main(["--board", board, "--out", str(tmp_path / "x.json")]) == 2
    assert not (tmp_path / "x.json").exists()


def test_script_refuses_a_board_in_no_manifest(tmp_path):
    from scripts import oiv2_gates as S

    assert S.main(["--board", "nope.zip", "--out", str(tmp_path / "x.json")]) == 2


RESULT = os.environ.get("OIV2_GATE_RESULT")


@pytest.mark.skipif(not RESULT, reason="set OIV2_GATE_RESULT to a scripts/oiv2_gates.py output")
@pytest.mark.parametrize("gate", list(G.GATES))
def test_directive_section5_gate_passes_on_the_full_pipeline(gate):
    result = json.loads(Path(RESULT).read_text("utf-8"))
    assert result["schema"] == G.SCHEMA
    assert result["gates"][gate] is True, json.dumps(
        {k: v for k, v in result["summary"].get(gate, {}).items() if k != "cases"}, default=str
    )[:2000]


def test_value_replay_patch_helper_restores_the_seam():
    with vr._patched("_ADVERSARIAL_VOTE_TRANSFORM", lambda _r, _s, v: v):
        assert dc._ADVERSARIAL_VOTE_TRANSFORM is not None
    assert dc._ADVERSARIAL_VOTE_TRANSFORM is None
