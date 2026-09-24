"""C1-U6-D2 — a class with no published slots is priced as tiers, never tethered.

Live defect (2026-09-24T07:57Z scrape): after the 2026 rookie draft the vendors
dropped the 2026 class and priced 2027 as Early/Mid/Late TIERS.  The scraper
still minted 72 ``2027 Pick R.SS`` rows valued from the ``years_exp == 0`` pool
(the 2026 class, already in the NFL) and the pick map spread the vendor tiers
into slots (``derived_slot_from_tier``).  The board then called 2027 the active
slot class, tethered ``2027 Pick 1.01`` to Jeremiyah Love (7677 vs KTC 8376),
and alias-suppressed the vendor-priced 2027 tiers to ``None``.

The evidence that a class's draft order is known is a vendor PUBLISHING its
slots (``pickAnchorsProvenance == published_slot``).  Without it the class
prices exactly like a future year.

Deterministic: synthetic inputs, plus two pinned, tracked archives straddling
the rollover (skipped if retention ever prunes them).  Never the live board.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from src.api import data_contract as dc
from src.api.pick_value_resolution import resolve_pick_value
from src.identity.picks import MarketPickRef

_ARCHIVE = Path(__file__).resolve().parents[2] / "exports" / "archive"
_PRE_ROLLOVER = "dynasty_export_20260924_005628.zip"  # 2026 slots published (IDPTC)
_POST_ROLLOVER = "dynasty_export_20260924_075735.zip"  # 2027 slots only derived


def _archive_raw(name: str) -> dict:
    path = _ARCHIVE / name
    if not path.exists():
        pytest.skip(f"pinned archive {name} not present")
    with zipfile.ZipFile(path) as zf:
        member = next(
            n for n in zf.namelist() if n.startswith("dynasty_data_") and n.endswith(".json")
        )
        return json.loads(zf.read(member))


def _picks(contract: dict) -> dict[str, dict]:
    return {
        str(r["canonicalName"]): r
        for r in contract["playersArray"]
        if r.get("assetClass") == "pick"
    }


def _prov_class(row: dict) -> str | None:
    prov = row.get("pickValueProvenance")
    return prov.get("class") if isinstance(prov, dict) else None


# ── the evidence rule ────────────────────────────────────────────────


def test_only_published_slots_count_as_slot_evidence():
    prov = {
        "ktc": {
            "2027 1.01": "derived_slot_from_tier",
            "2026 1.01": "model_injected_composite",
            "2027 Early 1st": "published_tier",
        },
        "idpTradeCalc": {"2026 1.02": "published_slot"},
    }
    assert dc.published_slot_years(prov) == {2026}
    assert dc.published_slot_years({"ktc": {"2027 1.01": "derived_slot_from_tier"}}) == set()


def test_unknown_provenance_is_not_no_evidence():
    """A payload that predates ``pickAnchorsProvenance`` keeps its rows."""
    assert dc.published_slot_years(None) is None
    players = {"2027 Pick 1.01": {}, "2027 Early 1st": {}}
    assert dc._drop_unpublished_slot_pick_rows(players, None) == []
    assert set(players) == {"2027 Pick 1.01", "2027 Early 1st"}


def test_unpublished_slot_rows_are_dropped_and_tiers_kept():
    players = {
        "2027 Pick 1.01": {},
        "2027 Pick 6.12": {},
        "2027 Early 1st": {},
        "2028 Mid 1st": {},
        "Josh Allen": {},
    }
    prov = {"ktc": {"2027 1.01": "derived_slot_from_tier", "2027 Early 1st": "published_tier"}}
    dropped = dc._drop_unpublished_slot_pick_rows(players, prov)
    assert sorted(dropped) == ["2027 Pick 1.01", "2027 Pick 6.12"]
    assert set(players) == {"2027 Early 1st", "2028 Mid 1st", "Josh Allen"}


def test_pick_floor_follows_the_boards_phase():
    slotted = [{"assetClass": "pick", "canonicalName": "2026 Pick 1.01"}]
    tiers_only = [{"assetClass": "pick", "canonicalName": "2027 Early 1st"}]
    assert dc._pick_count_floor_for_board(slotted) == dc._PICK_COUNT_FLOOR
    # (horizon 3 + current) x 6 rounds x (3 tiers + generic) = 96 → 80% = 77
    assert dc._pick_count_floor_for_board(tiers_only) == 77


# ── end to end on the rollover itself ───────────────────────────────


@pytest.fixture(scope="module")
def post_rollover() -> dict:
    return dc.build_api_data_contract(_archive_raw(_POST_ROLLOVER))


def test_no_slot_rows_for_a_class_nobody_published(post_rollover):
    picks = _picks(post_rollover)
    assert not [n for n in picks if n.startswith("2027 Pick ")]


def test_nothing_is_tethered_to_the_class_just_drafted(post_rollover):
    tethered = [
        n for n, r in _picks(post_rollover).items() if _prov_class(r) == "rookie_pool_tether"
    ]
    assert tethered == []


def test_the_current_class_prices_from_its_vendor_tiers(post_rollover):
    picks = _picks(post_rollover)
    for tier in ("Early", "Mid", "Late"):
        row = picks[f"2027 {tier} 1st"]
        assert not row.get("pickGenericSuppressed")
        assert (row.get("rankDerivedValue") or 0) > 0
        assert _prov_class(row) == "direct_market_blend"
    assert post_rollover.get("pickAliases") in ({}, None)


def test_the_current_class_is_complete_like_a_future_year(post_rollover):
    """Rounds 5-6 by round-step and a generic-grade row per round — never
    ``unavailable``, never 0."""
    picks = _picks(post_rollover)
    for rnd, suffix in ((1, "1st"), (5, "5th"), (6, "6th")):
        generic = picks[f"2027 Round {rnd}"]
        assert _prov_class(generic) == "derived_uniform_tier_ev"
        assert (generic.get("rankDerivedValue") or 0) > 0
        for tier in ("Early", "Mid", "Late"):
            row = picks[f"2027 {tier} {suffix}"]
            assert (row.get("rankDerivedValue") or 0) > 0, row["canonicalName"]
            assert _prov_class(row) != "unavailable"


def test_the_contract_validates_clean(post_rollover):
    report = dc.validate_api_data_contract(post_rollover)
    assert not report.get("structuralErrors")
    assert not [
        e for e in report.get("sourceHealthErrors") or [] if e.startswith("pick_count_below_floor")
    ]


def test_a_known_slot_resolves_to_its_own_tier(post_rollover):
    """Consumers holding a slot for an unslotted class get that slot's tier,
    labelled — the deterministic slot→tier map, not a fabricated slot."""
    res = resolve_pick_value(post_rollover, MarketPickRef(year=2027, round_num=1, slot=3))
    assert res.basis == "tier_of_unslotted_class"
    assert res.value == _picks(post_rollover)["2027 Early 1st"]["rankDerivedValue"]
    generic = resolve_pick_value(post_rollover, MarketPickRef(year=2027, round_num=2))
    assert generic.value == _picks(post_rollover)["2027 Round 2"]["rankDerivedValue"]


# ── and the slotted phase is untouched ──────────────────────────────


def test_a_published_slot_class_still_tethers():
    contract = dc.build_api_data_contract(_archive_raw(_PRE_ROLLOVER))
    picks = _picks(contract)
    slots = [n for n in picks if n.startswith("2026 Pick ")]
    assert len(slots) == 72
    assert _prov_class(picks["2026 Pick 1.01"]) == "rookie_pool_tether"
    assert picks["2026 Early 1st"].get("pickGenericSuppressed")
