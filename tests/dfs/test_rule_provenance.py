"""DFS-MOD-15: every rule set carries its provenance, and nothing is verified without evidence."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

RULESETS = Path(__file__).resolve().parents[2] / "config" / "dfs" / "rulesets.json"


def test_every_rule_set_states_version_status_last_checked_and_evidence_or_blocker():
    data = json.loads(RULESETS.read_text(encoding="utf-8"))
    assert data["rulesets"]
    for rs in data["rulesets"]:
        v = rs["verification"]
        assert rs["version"] and rs["platform"] and rs["sport"] and rs["format"], rs["id"]
        assert v["state"] in ("verified", "unverified"), rs["id"]
        date.fromisoformat(v["checkedOn"])  # a real date, not a placeholder
        if v["state"] == "verified":
            # Never silently promoted: verification needs recorded evidence.
            assert v.get("evidence"), f"{rs['id']} claims verified with no evidence"
        else:
            assert v.get("blocker"), f"{rs['id']} is unverified without saying why"
        ev = (rs.get("export") or {}).get("verification") or {}
        assert ev.get("state") in ("verified", "unverified"), rs["id"]
        if ev.get("state") == "verified":
            assert ev.get("evidence"), f"{rs['id']} export claims verified with no evidence"


def test_no_rule_set_is_currently_verified():
    """Today's truth, pinned: the official pages refused automated access on 2026-09-30,
    so every rule set is research-only.  Flipping one to verified must come with evidence
    AND a deliberate change to this test."""
    data = json.loads(RULESETS.read_text(encoding="utf-8"))
    assert {rs["verification"]["state"] for rs in data["rulesets"]} == {"unverified"}
