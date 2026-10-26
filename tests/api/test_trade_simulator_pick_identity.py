"""Owned picks are priced by IDENTITY through one resolver (Brisket Trade
Advisor B0-a), and every ``pickDetails`` entry carries the canonical
``boardRowName`` (B0-g).

The defect: one owned pick had up to three values depending on which label
grammar named it — the scraper's baked "2028 Mid 1st" (the legacy "unknown
slot -> Mid" display fabrication) priced the Mid tier row, the overlay's
"2028 1st" priced the generic grade, and the overlay's current-year "2027 1st"
resolved to NOTHING (a War Room trade containing it was NOT ENOUGH EVIDENCE).
Now a pick that carries its canonical ``assetId`` is priced by
``market_resolution`` + ``resolve_pick_value`` (unknown slot = GENERIC grade),
whatever its label says, and labels without an id go through the same
resolver instead of the simulator's private ladder.
"""

from __future__ import annotations

import pytest

from src.api import trade_simulator as ts
from src.api.pick_value_resolution import (
    pick_rows_by_name,
    resolve_owned_pick_value,
    stamp_owned_pick_rows,
)
from src.api.terminal import _build_row_index, _players_array
from src.identity.picks import format_pick_label_overlay, parse_league_pick_id

# ── synthetic board (no archive dependency) ───────────────────────────────

CDY = 2027  # the active draft year these synthetic rows are laid out for


def _pick(name, value, **extra):
    return {
        "displayName": name,
        "canonicalName": name,
        "assetClass": "pick",
        "pos": "PICK",
        "position": "PICK",
        "rankDerivedValue": value,
        **extra,
    }


def _board():
    rows = [
        # Current year: slot rows; the Mid tier row is alias-suppressed.
        _pick("2027 Pick 1.02", 5200),
        _pick("2027 Pick 1.06", 4700),
        _pick("2027 Pick 1.10", 4300),
        _pick(
            "2027 Mid 1st",
            None,
            pickGenericSuppressed=True,
            pickAliasFor="2027 Pick 1.06",
        ),
        # Future year: tier rows + the generic-grade row.
        _pick("2028 Early 1st", 5100),
        _pick("2028 Mid 1st", 4635),
        _pick("2028 Late 1st", 4300),
        _pick("2028 Round 1", 4747),
    ]
    teams = [
        {
            "name": "A",
            "roster_id": 1,
            "ownerId": "o1",
            "players": [],
            "pickDetails": [
                {
                    "season": 2028,
                    "round": 1,
                    "fromRosterId": 1,
                    "ownerRosterId": 1,
                    "slot": None,
                    "label": "2028 Mid 1st (own)",
                    "assetId": "pick:dynasty_main:2028:r1:o1",
                },
                {
                    "season": 2027,
                    "round": 1,
                    "fromRosterId": 1,
                    "ownerRosterId": 1,
                    "slot": None,
                    "label": "2027 Mid 1st (own)",
                    "assetId": "pick:dynasty_main:2027:r1:o1",
                },
            ],
            "pickOwnershipState": "observed",
        },
        {
            "name": "B",
            "roster_id": 2,
            "ownerId": "o2",
            "players": [],
            "pickDetails": [
                {
                    "season": 2028,
                    "round": 1,
                    "fromRosterId": 2,
                    "ownerRosterId": 2,
                    "slot": 3,  # a known slot (future year -> its tier)
                    "label": "2028 Early 1st (own)",
                    "assetId": "pick:dynasty_main:2028:r1:o2",
                }
            ],
            "pickOwnershipState": "observed",
        },
    ]
    return {"playersArray": rows, "sleeper": {"teams": teams}}


@pytest.fixture
def clock(monkeypatch):
    monkeypatch.setattr("src.api.data_contract.current_rookie_draft_year", lambda *a, **k: CDY)


def _resolve(contract, label, asset_id=None):
    idx = _build_row_index(_players_array(contract))
    return ts._resolve_asset(
        label, row_index=idx, asset_id=asset_id, pick_slots=ts.owned_pick_slots(contract)
    )


@pytest.mark.usefixtures("clock")
def test_an_owned_future_pick_prices_at_the_generic_grade_whatever_its_label():
    c = _board()
    aid = "pick:dynasty_main:2028:r1:o1"
    for label in ("2028 Mid 1st (own)", "2028 1st", "2028 Late 1st", "anything at all"):
        hit = _resolve(c, label, aid)
        assert hit["name"] == "2028 Round 1", label
        assert hit["value"] == 4747
    # Without the id, the label's own stated grade still decides.
    assert _resolve(c, "2028 Mid 1st")["name"] == "2028 Mid 1st"
    assert _resolve(c, "2028 1st")["name"] == "2028 Round 1"


@pytest.mark.usefixtures("clock")
def test_a_known_slot_is_state_from_the_contract_not_the_label():
    c = _board()
    hit = _resolve(c, "2028 Mid 1st", "pick:dynasty_main:2028:r1:o2")
    assert hit["name"] == "2028 Early 1st"  # slot 3 -> early (tier_from_slot)


@pytest.mark.usefixtures("clock")
def test_the_current_year_generic_label_now_resolves():
    """'2027 1st' (overlay grammar, current draft year) used to be None."""
    c = _board()
    hit = _resolve(c, "2027 1st")
    assert hit is not None and hit["name"] == "2027 Pick 1.06" and hit["value"] == 4700
    # Same answer by identity, and the baked tier label still follows its alias.
    assert _resolve(c, "x", "pick:dynasty_main:2027:r1:o1")["name"] == "2027 Pick 1.06"
    assert _resolve(c, "2027 Mid 1st")["name"] == "2027 Pick 1.06"


@pytest.mark.usefixtures("clock")
def test_unresolvable_stays_unresolved_never_zero():
    c = _board()
    assert _resolve(c, "certainly not a pick") is None
    assert _resolve(c, "2031 1st") is None  # no row for that class
    assert _resolve(c, "2031 1st", "pick:dynasty_main:2031:r1:o1") is None


@pytest.mark.usefixtures("clock")
def test_an_unpriced_identity_row_stays_unpriced_whatever_the_label_names():
    """LANE-E-DEFECT-I9-PICKLABEL / I13-PICKSTATE.  The board HOLDS the row the
    pick's identity resolves to (``2028 Round 1``) but has not priced it.  A
    label that names ANOTHER, priced grade must not price the pick: it is
    UNPRICED - resolved to its own row with no positive value - never off-board,
    never the other grade's number, never 0 presented as a price."""
    c = _board()
    for row in c["playersArray"]:
        if row["canonicalName"] == "2028 Round 1":
            row["rankDerivedValue"] = None
            row["pickValueProvenance"] = {"state": "unavailable"}
    aid = "pick:dynasty_main:2028:r1:o1"
    for label in ("2028 Mid 1st (own)", "2028 Early 1st", "2028 1st", "anything at all"):
        hit = _resolve(c, label, aid)
        assert hit is not None, label  # on the board: not an off-board name
        assert hit["name"] == "2028 Round 1", label
        assert not hit["value"], label  # no positive canonical value: unpriced
    # No identity: the label still prices (unchanged), so the fix is not a blanket refusal.
    assert _resolve(c, "2028 Mid 1st")["value"] == 4635
    # The server-side stamp agrees: no board row is named for an unpriced pick.
    stamped = stamp_owned_pick_rows(c["sleeper"]["teams"], pick_rows_by_name(c), CDY)
    own = next(d for d in stamped[0]["pickDetails"] if d["assetId"] == aid)
    assert own["boardRowName"] is None


@pytest.mark.usefixtures("clock")
def test_identity_with_no_board_row_at_all_keeps_the_label_fallback():
    """The documented exception: when the board publishes NO row for the
    identity's grade (here the 2028 generic row is absent, tiers only), the
    label's own stated grade still decides - the pre-identity behaviour."""
    c = _board()
    c["playersArray"] = [r for r in c["playersArray"] if r["canonicalName"] != "2028 Round 1"]
    hit = _resolve(c, "2028 Mid 1st (own)", "pick:dynasty_main:2028:r1:o1")
    assert hit is not None and hit["name"] == "2028 Mid 1st" and hit["value"] == 4635


@pytest.mark.usefixtures("clock")
def test_a_non_canonical_id_falls_back_to_the_label():
    c = _board()
    assert _resolve(c, "2028 Mid 1st", "pick:2028:1")["name"] == "2028 Mid 1st"


@pytest.mark.usefixtures("clock")
def test_simulate_trade_debits_and_prices_the_same_pick_by_identity():
    c = _board()
    team = c["sleeper"]["teams"][0]
    for label in ("2028 Mid 1st (own)", "2028 1st"):
        sim = ts.simulate_trade(
            c,
            resolved_team=team,
            picks_out=[label],
            pick_asset_ids_out=["pick:dynasty_main:2028:r1:o1"],
        )
        assert [(a["name"], a["value"]) for a in sim["sending"]] == [("2028 Round 1", 4747)]
        assert sim["sending"][0]["assetId"] == "pick:dynasty_main:2028:r1:o1"
        # The before-roster prices the same pick the same way, so the debit
        # equals the sent value exactly.
        assert sim["delta"]["totalValue"] == -4747
        assert sim["unresolvedOut"] == []


@pytest.mark.usefixtures("clock")
def test_board_row_name_stamp_matches_the_simulator_and_is_additive():
    c = _board()
    teams = c["sleeper"]["teams"]
    before = [dict(d) for d in teams[0]["pickDetails"]]
    stamped = stamp_owned_pick_rows(teams, pick_rows_by_name(c), CDY)
    assert teams[0]["pickDetails"] == before, "the input must never be mutated"
    for team in stamped:
        for d in team["pickDetails"]:
            hit = _resolve(c, d["label"], d["assetId"])
            assert d["boardRowName"] == hit["name"]
            assert {k: v for k, v in d.items() if k != "boardRowName"} == next(
                x for t in teams for x in t["pickDetails"] if x["assetId"] == d["assetId"]
            )
    # A pick the board cannot price gets None, never a guessed row.
    lonely = [{"pickDetails": [{"assetId": "pick:dynasty_main:2031:r1:o1", "slot": None}]}]
    assert (
        stamp_owned_pick_rows(lonely, pick_rows_by_name(c), CDY)[0]["pickDetails"][0][
            "boardRowName"
        ]
        is None
    )


@pytest.mark.usefixtures("clock")
def test_resolver_is_none_only_for_a_non_canonical_id():
    rows = pick_rows_by_name(_board())
    assert (
        resolve_owned_pick_value("nope", slot=None, rows_by_name=rows, current_draft_year=CDY)
        is None
    )
    pv = resolve_owned_pick_value(
        "pick:dynasty_main:2028:r1:o1", slot=None, rows_by_name=rows, current_draft_year=CDY
    )
    assert pv.value == 4747 and pv.basis_row_name == "2028 Round 1"


# ── archive board: the census the PR body reports ─────────────────────────


@pytest.fixture(scope="module")
def archive_contract():
    from tests.archive_fixtures import newest_complete_raw_payload

    raw, _name = newest_complete_raw_payload()
    if raw is None:
        pytest.skip("no complete archived scrape")
    from src.api.data_contract import build_api_data_contract

    return build_api_data_contract(raw)


def test_archive_every_owned_pick_has_one_value_across_label_grammars(archive_contract):
    c = archive_contract
    idx = _build_row_index(_players_array(c))
    slots = ts.owned_pick_slots(c)
    teams = c["sleeper"]["teams"]
    checked = 0
    for team in teams:
        for d in team.get("pickDetails") or []:
            aid = d.get("assetId")
            if not aid:
                continue
            labels = [
                d["label"],
                d.get("baseLabel"),
                format_pick_label_overlay(d["season"], d["round"], d.get("slot")),
            ]
            rows = {
                (h["name"], h["value"]) if h else None
                for h in (
                    ts._resolve_asset(lab, row_index=idx, asset_id=aid, pick_slots=slots)
                    for lab in labels
                    if lab
                )
            }
            assert len(rows) == 1, (aid, labels, rows)
            (only,) = rows
            assert only is not None, f"{aid} unpriced"
            assert only[0] == d.get("boardRowName"), (aid, only, d.get("boardRowName"))
            ident = parse_league_pick_id(aid)
            if d.get("slot") is None and ident.season > int(c["currentDraftYear"]):
                # Unknown future slot = the GENERIC grade, never "assume Mid".
                assert only[0] == f"{ident.season} Round {ident.round_num}", (aid, only)
            checked += 1
    assert checked > 0


def test_archive_overlay_labels_never_resolve_to_nothing(archive_contract):
    c = archive_contract
    idx = _build_row_index(_players_array(c))
    for team in c["sleeper"]["teams"]:
        for d in team.get("pickDetails") or []:
            label = format_pick_label_overlay(d["season"], d["round"], d.get("slot"))
            assert ts._resolve_asset(label, row_index=idx) is not None, label


@pytest.mark.usefixtures("clock")
def test_server_overlay_stamp_copies_and_never_mutates_the_cached_overlay():
    import server

    c = _board()
    overlay_teams = [
        {**t, "pickDetails": [dict(d) for d in t["pickDetails"]]} for t in c["sleeper"]["teams"]
    ]
    snapshot = repr(overlay_teams)
    out = server._overlay_pick_board_rows(overlay_teams, c)
    assert repr(overlay_teams) == snapshot
    names = {d["assetId"]: d["boardRowName"] for t in out for d in t["pickDetails"]}
    assert names["pick:dynasty_main:2028:r1:o1"] == "2028 Round 1"
    assert names["pick:dynasty_main:2028:r1:o2"] == "2028 Early 1st"
    # Degrade, never fail: no contract -> teams unchanged.
    assert server._overlay_pick_board_rows(overlay_teams, None) is overlay_teams


@pytest.mark.usefixtures("clock")
def test_identity_with_no_priced_row_falls_back_to_the_label_grade():
    """An unslotted current class whose board carries tiers only: identity
    (generic grade -> centre-slot convention) finds no row, so the label's
    own stated grade prices it — never unresolved when the board can answer."""
    c = _board()
    c["playersArray"] = [
        r for r in c["playersArray"] if not r["canonicalName"].startswith("2027 Pick")
    ]
    c["playersArray"].append(_pick("2027 Late 1st", 4000))
    c["playersArray"] = [r for r in c["playersArray"] if r["canonicalName"] != "2027 Mid 1st"]
    hit = _resolve(c, "2027 Late 1st (from X)", "pick:dynasty_main:2027:r1:o1")
    assert hit is not None and hit["name"] == "2027 Late 1st" and hit["value"] == 4000
    assert _resolve(c, "garbage", "pick:dynasty_main:2027:r1:o1") is None
