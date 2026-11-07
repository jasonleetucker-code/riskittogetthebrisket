"""Master-site-audit W25-F003 regression (CW-40 P1 re-adjudication, 2026-11-06) -- OPEN (doc accuracy).

Claim: CLAUDE.md says the rows ``buildRows`` numbers itself are "players past the
backend's ``OVERALL_RANK_LIMIT`` (800) -- rows the backend deliberately left unranked".

Measured offline on the pinned tracked archive board
``exports/archive/dynasty_export_20261106_194518.zip`` (raw payload -> real
``build_api_data_contract``): the unranked non-pick rows are TWO populations, and only one
is "past the cap".

* ``offCapPlayerValue`` rows -- priced, value stamped, no rank: genuinely past the rank
  cap (#1101);
* null-value rows -- the board could NOT price them (``rankDerivedValue`` is None, almost
  all single-source K/DL/DB).  They are not past any cutoff; the cap is not why they are
  unranked.

Also: the cap counts pick rows, so the maximum stamped PLAYER rank is below 800.

The strict xfail pins the doc correction (the CLAUDE.md nuance paragraph must say the
unpriced population exists); it flips when CLAUDE.md is corrected.  CLAUDE.md is NOT edited
in this PR.  Exact proposed correction: see CW40_P1_UNADJUDICATED.md section W25-F003.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
ARCHIVE = REPO / "exports" / "archive" / "dynasty_export_20261106_194518.zip"
_cache: dict = {}


def _contract() -> dict:
    if "c" not in _cache:
        if not ARCHIVE.is_file():
            pytest.skip("pinned archive bundle absent")
        from src.api.data_contract import build_api_data_contract

        with zipfile.ZipFile(ARCHIVE) as zf:
            name = next(
                n for n in zf.namelist() if n.startswith("dynasty_data_") and n.endswith(".json")
            )
            raw = json.loads(zf.read(name))
        _cache["c"] = build_api_data_contract(raw)
    return _cache["c"]


def _unranked_players() -> list[dict]:
    return [
        r
        for r in _contract()["playersArray"]
        if r.get("canonicalConsensusRank") is None and r.get("assetClass") != "pick"
    ]


def test_unranked_players_are_two_populations_not_one_cap_cut():
    rows = _unranked_players()
    off_cap = [r for r in rows if r.get("offCapPlayerValue")]
    unpriced = [r for r in rows if r.get("rankDerivedValue") is None]
    assert off_cap and unpriced, "the finding's premise: both populations exist"
    # They partition the unranked players: every row is one or the other.
    assert len(off_cap) + len(unpriced) == len(rows)
    # Unpriced rows are not "past the cap": a cap cut never removes a value.
    assert all(not r.get("offCapPlayerValue") for r in unpriced)


def test_max_stamped_player_rank_is_below_the_published_limit():
    ranks = [
        r["canonicalConsensusRank"]
        for r in _contract()["playersArray"]
        if isinstance(r.get("canonicalConsensusRank"), int)
    ]
    assert max(ranks) < 800  # the cap is shared with pick rows; no player sits at 800


# W25-F003 closed 2026-11-06: CLAUDE.md now names the unpriced population.
def test_claude_md_names_the_unpriced_population():
    text = (REPO / "CLAUDE.md").read_text(encoding="utf-8")
    start = text.index("One precise nuance on ranks")
    nuance = text[start : start + 1400].lower()
    assert "unpriced" in nuance or "could not price" in nuance
