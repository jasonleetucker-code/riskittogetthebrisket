"""The census counts what the decision brief says it counts, on a synthetic payload."""

from __future__ import annotations

import importlib.util
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "public_surface_census",
    Path(__file__).resolve().parents[2] / "scripts" / "public_surface_census.py",
)
census_mod = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(census_mod)

A = "468418790212759552"
B = "831633191830933504"


def test_counts_ids_keys_avatars_names_and_distinct():
    payload = {
        "league": {"managers": [{"ownerId": A, "displayName": "Ann", "avatar": "a" * 32}]},
        "sections": {
            "x": [{"ownerId": A, "winnerOwnerId": B, "teamName": "T"}],
            "y": {"ownerIds": [A, B], "byOwner": {A: {"wins": 1}}},
        },
        "short": "123",
        "season": "2026",
    }
    out = census_mod.census(payload)
    assert out["ids"]["ownerId"] == 2
    assert out["ids"]["winnerOwnerId"] == 1
    assert out["ids"]["ownerIds"] == 2
    assert out["idKeys"]["byOwner.{id}"] == 1
    assert out["avatars"]["avatar"] == 1
    assert out["names"]["displayName"] == 1 and out["names"]["teamName"] == 1
    assert out["distinctIds"]["distinct"] == 2
    assert "season" not in out["ids"], "a 4-digit year is not a Sleeper id"
