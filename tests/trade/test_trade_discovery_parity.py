"""Lockstep: the frontend discovery vocabulary mirrors the canonical owners.

``frontend/lib/trade-discovery.js`` filters the client-side research table by
Players to target.  Its position lists must equal what the Python owner
derives from ``POSITION_ALIASES`` + the lineup owner's slot eligibility, and
its option values must equal the server's — or the table and the engines would
disagree about what "Defense" means.
"""

from __future__ import annotations

import re
from pathlib import Path

from src.trade import discovery as disc
from src.utils.name_clean import POSITION_ALIASES

JS = Path(__file__).resolve().parents[2] / "frontend" / "lib" / "trade-discovery.js"


def _array(name: str) -> list[str]:
    src = JS.read_text(encoding="utf-8")
    m = re.search(rf"export const {name} = \[(.*?)\];", src, re.S)
    assert m, f"{name} not found in {JS}"
    return re.findall(r'"([^"]+)"', m.group(1))


def _values(name: str) -> list[str]:
    src = JS.read_text(encoding="utf-8")
    m = re.search(rf"export const {name} = \[(.*?)\];", src, re.S)
    assert m, f"{name} not found"
    return re.findall(r'value: "([^"]+)"', m.group(1))


def test_offense_positions_match_the_lineup_owner():
    assert set(_array("OFFENSE_POSITIONS")) == set(disc.offense_positions())


def test_defense_positions_match_every_alias_of_an_idp_family():
    expected = {
        alias
        for alias, fam in POSITION_ALIASES.items()
        if fam in disc.defense_positions() or disc.player_group(alias) == "defense"
    }
    assert set(_array("DEFENSE_POSITIONS")) == expected
    assert all(disc.player_group(p) == "defense" for p in _array("DEFENSE_POSITIONS"))


def test_option_values_match_the_server():
    assert _values("TARGET_QUALITY_OPTIONS") == list(disc.QUALITY_LEVELS)
    assert set(_values("PLAYER_SCOPE_OPTIONS")) == set(disc.SCOPES)
    assert _values("DISCOVERY_SORT_OPTIONS") == list(disc.SORTS)
    src = JS.read_text(encoding="utf-8")
    assert f'DEFAULT_TARGET_QUALITY = "{disc.DEFAULT_QUALITY}"' in src
    assert f'DEFAULT_PLAYER_SCOPE = "{disc.DEFAULT_SCOPE}"' in src
    assert f'DEFAULT_DISCOVERY_SORT = "{disc.DEFAULT_SORT}"' in src
