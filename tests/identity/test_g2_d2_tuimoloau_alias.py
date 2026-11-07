"""G2-D2 — one vendor name, one player, every source.

Draft Sharks IDP and IDP Trade Calculator both publish the identical string
"JT Tuimoloau".  The board row is Sleeper's "Jaylahn Tuimoloau" (DL, IND,
Sleeper id 12594, the only Tuimoloau in the pool).  The scraper attached the
IDPTC value through its (initial, last) rung, but the contract's CSV join
(``CONTRACT_CSV_JOIN_V1``) is exact-key only, so the Draft Sharks vote never
reached the row: one provider, ``structurally_single_source``, value 273 on
the 2026-10-27 board instead of 1,328 with both providers.

The repair is one deterministic entry in the existing alias owner,
``CANONICAL_NAME_ALIASES`` — no new matching rung, no logic outside
``src/identity`` + ``name_clean``.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from src.api.data_contract import _canonical_match_key
from src.identity.resolution import match_row_to_source_entry
from src.utils.name_clean import canonical_position_group, resolve_canonical_name

REPO = Path(__file__).resolve().parents[2]


def test_vendor_and_sleeper_spellings_share_one_key():
    assert resolve_canonical_name("JT Tuimoloau") == resolve_canonical_name("Jaylahn Tuimoloau")
    assert resolve_canonical_name("J.T. Tuimoloau") == "jaylahn tuimoloau"
    # the join key the contract uses is the same function
    assert _canonical_match_key("JT Tuimoloau") == _canonical_match_key("Jaylahn Tuimoloau")


def test_contract_join_attaches_the_vendor_row():
    """The served CSV-join decision, fed the way ``_enrich_from_source_csvs`` feeds it."""
    vendor_key = f"{_canonical_match_key('JT Tuimoloau')}::{canonical_position_group('DL')}"
    per_source = {vendor_key: {"value": 286.0, "originalRank": 286}}
    decision = match_row_to_source_entry(
        row_player_id="12594",
        row_name="Jaylahn Tuimoloau",
        row_position="DL",
        per_source=per_source,
        sid_index={},
        row_groups_by_key={},
        canonical_match_key=_canonical_match_key,
        position_group=canonical_position_group,
    )
    assert decision.entry_key == vendor_key
    assert decision.via == "name_group"


def test_alias_does_not_reach_other_players():
    assert resolve_canonical_name("Jaylahn Tuimoloau") == "jaylahn tuimoloau"
    assert resolve_canonical_name("JT Woods") == "jt woods"
    assert resolve_canonical_name("TJ Tuimoloau") == "tj tuimoloau"


@pytest.mark.parametrize("csv_name", ["draftSharksIdp.csv", "idpTradeCalc.csv"])
def test_every_tracked_spelling_resolves_to_the_board_key(csv_name):
    """Any Tuimoloau a tracked IDP board publishes lands on the one board key."""
    path = REPO / "CSVs" / "site_raw" / csv_name
    if not path.is_file():
        pytest.skip(f"{csv_name} not present")
    with path.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        col = "Player" if "Player" in (reader.fieldnames or []) else "name"
        names = [r[col] for r in reader if "tuimoloau" in (r.get(col) or "").lower()]
    if not names:
        pytest.skip(f"{csv_name} lists no Tuimoloau this refresh")
    assert {resolve_canonical_name(n) for n in names} == {"jaylahn tuimoloau"}
