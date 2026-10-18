"""Signals IDP dependence (owner Decision 7): box-only, aggregate-only.

With no private board the measurement says ``not_provisioned`` and computes
nothing.  With boards present (here: synthetic copies built from a committed
IDP capture, so the expected answer is "near-identical order") it reports per
family Spearman / leave-pair-out residuals and never a player name.
"""

from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def mod():
    spec = importlib.util.spec_from_file_location(
        "idp_rehab_eval_t", REPO / "scripts" / "idp_rehab_eval.py"
    )
    m = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(m)
    return m


def _base_from_capture(path: Path) -> tuple[dict, list[dict]]:
    with path.open(encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    base = {
        "playersArray": [
            {"displayName": r["name"], "assetClass": "idp", "position": r["family"]}
            for r in rows
            if r.get("family") in ("DL", "LB", "DB")
        ]
    }
    return base, rows


def test_not_provisioned_computes_nothing(mod, tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "SIGNALS_BOARD_DIR", tmp_path / "absent")
    assert mod.signals_dependence({"playersArray": []})["state"] == "not_provisioned"


def test_provisioned_is_aggregate_only(mod, tmp_path, monkeypatch):
    capture = REPO / "CSVs" / "site_raw" / "fantasyProsIdp.csv"
    if not capture.is_file():
        pytest.skip("no committed IDP capture")
    base, rows = _base_from_capture(capture)
    board_dir = tmp_path / "board"
    board_dir.mkdir()
    for key, fam in (("signalsIdpDl", "DL"), ("signalsIdpLb", "LB"), ("signalsIdpDb", "DB")):
        fam_rows = [r for r in rows if r.get("family") == fam]
        with (board_dir / f"{key}.csv").open("w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            w.writeheader()
            for i, r in enumerate(fam_rows, start=1):
                w.writerow({**r, "originalRank": i, "effectiveRank": i})
    monkeypatch.setattr(mod, "SIGNALS_BOARD_DIR", board_dir)
    out = mod.signals_dependence(base)
    assert out["state"] == "provisioned"
    text = json.dumps(out)
    for r in rows[:50]:
        assert r["name"] not in text
    fp = [
        p
        for fam in out["families"].values()
        for p in fam.get("pairs", [])
        if p["b"] == "fantasyProsIdp"
    ]
    assert fp and all(p["spearman"] is not None and p["spearman"] > 0.95 for p in fp)
