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


def test_resolved_podcasts_carry_evidence_and_never_claim_rights():
    data = _load()
    for e in data["podcasts"]:
        if e["accessState"] == "unverified":
            continue
        assert e["verification"]["evidence"], e["seedId"]
        if e["accessState"] == "available_public":
            assert e["feed"]["rssFeedUrl"].startswith("https://") or e["feed"][
                "rssFeedUrl"
            ].startswith("http://")
        # A public feed is not a licence to transcribe or retain.
        assert e["license"]["assessed"] is False and e["license"]["permittedUses"] == []


def test_correlated_network_feeds_share_one_independence_group():
    data = _load()
    groups = {e["seedId"]: e["independenceGroup"] for e in data["podcasts"]}
    assert len({groups[s] for s in ("C-005", "C-006", "C-007", "C-008")}) == 1


def test_resolved_websites_never_claim_an_authorised_path_we_do_not_hold():
    """A paid site we do not subscribe to is permission_required, and a public
    site whose terms were never reviewed is manual-import only — openness of
    the site is not authorisation for us to acquire from it automatically."""
    data = _load()
    by_seed = {e["seedId"]: e for e in data["websites"]}
    for e in data["websites"]:
        assert e["accessState"] not in ("available_public", "available_authorized_paid"), e[
            "seedId"
        ]
        assert e["license"]["assessed"] is False and e["license"]["permittedUses"] == []
        if e.get("accessModel") == "paid":
            assert e["accessState"] == "permission_required", e["seedId"]
    # numberFire now redirects into FanDuel Research: one source, not two.
    assert by_seed["A-031"]["aliasOf"] == by_seed["A-030"]["id"]
    # Shared DATA collapses independence; shared ownership alone does not.
    assert by_seed["A-019"]["independenceGroup"] == by_seed["A-025"]["independenceGroup"]
    assert by_seed["A-053"]["independenceGroup"] == by_seed["A-054"]["independenceGroup"]
    assert by_seed["A-001"]["corporateParent"] == by_seed["A-013"]["corporateParent"]
    assert by_seed["A-001"]["independenceGroup"] != by_seed["A-013"]["independenceGroup"]
    assert by_seed["A-046"]["accessState"] == "out_of_scope"
