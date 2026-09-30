"""The owner's DFS source catalog is preserved, and no seed claims access it has not earned."""

from __future__ import annotations

import json
from pathlib import Path

REGISTRY = Path(__file__).resolve().parents[2] / "config" / "dfs" / "source_seeds.json"


def _load():
    return json.loads(REGISTRY.read_text(encoding="utf-8"))


def test_every_supplied_seed_is_preserved_with_a_stable_id():
    data = _load()
    assert (len(data["websites"]), len(data["sportsbooks"]), len(data["podcasts"])) == (74, 6, 29)
    seed_ids = [e["seedId"] for k in ("websites", "sportsbooks", "podcasts") for e in data[k]]
    ids = [e["id"] for k in ("websites", "sportsbooks", "podcasts") for e in data[k]]
    assert len(set(seed_ids)) == len(seed_ids) == 109
    assert len(set(ids)) == len(ids)
    names = {e["suppliedName"] for e in data["podcasts"]}
    assert (
        "RotoGrinders Daily Fantasy 6 Pack / Beer’s Six Pack" in names
    )  # verbatim, curly apostrophe kept


def test_no_seed_claims_verified_access_without_evidence():
    data = _load()
    for k in ("websites", "sportsbooks", "podcasts"):
        for e in data[k]:
            assert e["accessState"] in data["accessStates"]
            assert e["sourceCategory"] in data["sourceCategories"]
            if e["accessState"] != "unverified":
                assert e["verification"]["evidence"], e["suppliedName"]
            if e["connector"]["state"] != "none":
                assert e["connector"]["lastSuccess"], e["suppliedName"]
            if e["aliasOf"] is not None:
                assert e["aliasOf"] in {
                    x["id"] for kk in ("websites", "sportsbooks", "podcasts") for x in data[kk]
                }
