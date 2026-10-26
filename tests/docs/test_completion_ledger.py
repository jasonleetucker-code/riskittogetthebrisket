"""The Calculator completion dashboard is generated, valid and current.

Owner directive 2026-10-07: every live Calculator requirement resolves to exactly
one ledger row with exactly one disposition, over the repository's existing
canonical ids, and completion is requirement-weighted. These tests make that a
deterministic gate instead of prose: a manifest row without a ledger row, an
unknown disposition, an owner/external row without a structured blocker, or a
hand-edited/stale dashboard all fail.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "completion_ledger.py"


def _module():
    spec = importlib.util.spec_from_file_location("completion_ledger", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_ledger_is_valid_and_dashboard_is_current():
    mod = _module()
    assert mod.main(["--check"]) == 0, "run: python scripts/completion_ledger.py"


def test_every_manifest_row_has_exactly_one_ledger_row():
    mod = _module()
    ledger, _md, errors = mod.build()
    assert not [e for e in errors if "manifest row" in e]
    manifest = mod.manifest_ids(
        (REPO / "docs" / "C_SERIES_SCOPE_MANIFEST.md").read_text(encoding="utf-8")
    )
    assert len(manifest) >= 160, "precondition: the manifest parser found the manifest rows"
    ids = [r["id"] for r in ledger["rows"]]
    assert len(ids) == len(set(ids)), "one requirement, one row"


def test_disagreeing_audits_resolve_conservatively_and_visibly(tmp_path):
    mod = _module()
    fam = tmp_path / "families"
    fam.mkdir()
    base = {
        "aliases": [],
        "sourceDoc": "x",
        "productFamily": "Trade",
        "capability": "c",
        "userVisibleOutcome": "u",
        "backendOwner": None,
        "frontendOwner": None,
        "dependsOn": [],
        "reality": "r",
        "prOrBranch": None,
        "evidence": "e",
        "blocker": None,
        "weight": 2,
    }
    (fam / "a.json").write_text(
        json.dumps(
            {
                "family": "a",
                "rows": [
                    {
                        **base,
                        "id": "C3-X-01",
                        "disposition": "COMPLETE_AND_PROVEN",
                        "nextAction": None,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (fam / "b.json").write_text(
        json.dumps(
            {
                "family": "b",
                "rows": [
                    {
                        **base,
                        "id": "ALIAS-9",
                        "aliases": ["C3-X-01"],
                        "disposition": "PARTIAL",
                        "nextAction": "finish",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    manifest = tmp_path / "m.md"
    manifest.write_text("# 4. The manifest\n| `C3-X-01` | c |\n# 5. Counts\n", encoding="utf-8")
    ledger, _md, errors = mod.build(fam, manifest)
    assert errors == []
    [row] = ledger["rows"]
    assert row["id"] == "C3-X-01"  # the manifest id is primary
    assert row["disposition"] == "PARTIAL"  # never the more optimistic claim
    assert "audits disagreed" in row["dispositionConflict"]
    assert "ALIAS-9" in row["aliases"]


def test_owner_rows_need_a_structured_blocker(tmp_path):
    mod = _module()
    fam = tmp_path / "families"
    fam.mkdir()
    (fam / "a.json").write_text(
        json.dumps(
            {
                "family": "a",
                "rows": [
                    {
                        "id": "Z-1",
                        "aliases": [],
                        "sourceDoc": "x",
                        "productFamily": "Trade",
                        "capability": "c",
                        "disposition": "OWNER_ACTION_REQUIRED",
                        "userVisibleOutcome": "u",
                        "backendOwner": None,
                        "frontendOwner": None,
                        "dependsOn": [],
                        "reality": "r",
                        "prOrBranch": None,
                        "evidence": "e",
                        "nextAction": "ask",
                        "blocker": None,
                        "weight": 1,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    manifest = tmp_path / "m.md"
    manifest.write_text("# 4. The manifest\n# 5. Counts\n", encoding="utf-8")
    _ledger, _md, errors = mod.build(fam, manifest)
    assert any("structured blocker" in e for e in errors)


def test_owner_paused_rows_are_outside_the_denominator_and_explained(tmp_path):
    """Owner closeout 2026-10-18: a paused requirement is neither complete nor
    rejected. It leaves the weighted denominator, is reported on its own line,
    and must still name its resume condition."""
    mod = _module()
    fam = tmp_path / "families"
    fam.mkdir()
    base = {
        "aliases": [],
        "sourceDoc": "x",
        "productFamily": "Trade",
        "capability": "c",
        "userVisibleOutcome": "u",
        "backendOwner": None,
        "frontendOwner": None,
        "dependsOn": [],
        "reality": "r",
        "prOrBranch": None,
        "evidence": "e",
        "blocker": None,
        "weight": 2,
    }
    rows = [
        {**base, "id": "T-1", "disposition": "COMPLETE_AND_PROVEN", "nextAction": None},
        {**base, "id": "T-2", "disposition": "PARTIAL", "nextAction": "finish"},
        {**base, "id": "T-3", "disposition": "OWNER_PAUSED", "nextAction": "resume on directive"},
    ]
    (fam / "a.json").write_text(json.dumps({"family": "a", "rows": rows}), encoding="utf-8")
    manifest = tmp_path / "m.md"
    manifest.write_text("# 4. The manifest\n# 5. Counts\n", encoding="utf-8")
    ledger, md, errors = mod.build(fam, manifest)
    assert errors == []
    summary = ledger["summary"]
    assert summary["weightedBuckets"]["ownerPaused"] == 2
    assert summary["weightedCompletionPct"] == 50.0  # 2 complete of 4 in-denominator weight
    assert "OWNER PAUSED" in md

    rows[2] = {**rows[2], "nextAction": None}
    (fam / "a.json").write_text(json.dumps({"family": "a", "rows": rows}), encoding="utf-8")
    _ledger, _md, errors = mod.build(fam, manifest)
    assert any("T-3" in e and "neither nextAction nor blocker" in e for e in errors)
