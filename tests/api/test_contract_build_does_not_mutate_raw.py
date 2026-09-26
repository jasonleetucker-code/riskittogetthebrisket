"""The contract builders must never mutate the raw payload they are handed.

``build_api_data_contract`` shallow-copies the top of ``raw_payload`` for
speed, which left ``base["sleeper"]`` ALIASED to the caller's dict.  Two
later writes then landed on the caller's object:

* a missing ``sleeper.positions`` was created in place (``{}``);
* ``stamp_optimal_lineups`` replaced ``sleeper.teams`` with its stamped
  copies, so the raw generation grew ``optimalLineup`` on every team.

The raw payload is the accepted scrape generation (``server.latest_data``)
and is re-read by every later build and by the rankings-override path, so a
build that edits it makes the next build's input depend on the previous
build's output.

Harvested from #1346 (donor commit 47b90cd41), adapted to call the
builders directly instead of the excluded prepared-serving generation.
"""

from __future__ import annotations

import copy
import hashlib
import json

import pytest

from src.api.data_contract import build_api_data_contract, build_rankings_delta_payload
from tests.api.test_source_overrides import _fixture_raw_payload


def _raw_hash(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def _raw_with_teams(*, positions_present: bool) -> dict:
    raw = _fixture_raw_payload()
    sleeper = raw.setdefault("sleeper", {})
    sleeper["teams"] = [
        {"ownerId": "fixture-owner", "players": ["Josh Allen", "Unknown Fixture Player"]}
    ]
    sleeper["rosterPositions"] = ["QB"]
    if positions_present:
        sleeper.setdefault("positions", {"Josh Allen": "QB"})
    else:
        sleeper.pop("positions", None)
    return raw


def _build_full(raw: dict) -> dict:
    return build_api_data_contract(raw, tep_multiplier=1.15)


def _build_full_with_override(raw: dict) -> dict:
    return build_api_data_contract(
        raw, tep_multiplier=1.15, source_overrides={"dlfSf": {"include": False}}
    )


def _build_delta(raw: dict) -> dict:
    return build_rankings_delta_payload(
        raw, tep_multiplier=1.15, source_overrides={"dlfSf": {"include": False}}
    )


@pytest.mark.parametrize(
    "builder",
    [_build_full, _build_full_with_override, _build_delta],
    ids=["full", "full_override", "delta_override"],
)
@pytest.mark.parametrize("positions_present", [True, False])
def test_builders_leave_raw_payload_byte_identical(builder, positions_present):
    raw = _raw_with_teams(positions_present=positions_present)
    before = copy.deepcopy(raw)
    before_hash = _raw_hash(raw)

    result = builder(raw)
    assert result  # the build ran

    mutations = {
        "serialized_hash": _raw_hash(raw) != before_hash,
        "teams": raw["sleeper"].get("teams") != before["sleeper"].get("teams"),
        "positions": ("positions" in raw["sleeper"]) != ("positions" in before["sleeper"])
        or raw["sleeper"].get("positions") != before["sleeper"].get("positions"),
    }
    assert not any(mutations.values()), mutations
    assert raw == before


def test_full_build_still_stamps_its_own_output():
    """Non-mutation must not come at the cost of the stamped output."""
    raw = _raw_with_teams(positions_present=True)
    result = build_api_data_contract(raw, tep_multiplier=1.15)
    teams = result["sleeper"]["teams"]
    assert "optimalLineup" in teams[0]
    assert "optimalLineup" not in raw["sleeper"]["teams"][0]
    assert result["sleeper"] is not raw["sleeper"]


def test_missing_positions_is_stamped_on_output_only():
    raw = _raw_with_teams(positions_present=False)
    result = build_api_data_contract(raw, tep_multiplier=1.15)
    assert isinstance(result["sleeper"]["positions"], dict)
    assert "positions" not in raw["sleeper"]


@pytest.mark.parametrize("sleeper_state", ["missing", "null", "invalid"])
def test_missing_sleeper_block_compatibility(sleeper_state):
    raw = _fixture_raw_payload()
    if sleeper_state == "missing":
        raw.pop("sleeper", None)
    else:
        raw["sleeper"] = None if sleeper_state == "null" else []
    before = copy.deepcopy(raw)
    result = build_api_data_contract(raw, tep_multiplier=1.15)
    assert result["playersArray"]
    assert result["sleeper"]["positions"] == {}
    assert raw == before
