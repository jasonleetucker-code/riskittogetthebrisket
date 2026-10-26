"""resolve_items: identity owners + board join, fail closed."""

from __future__ import annotations

from src.trade.market_trade_normalize import IdentityContext
from src.trade.screenshot_import.parse import parse_line
from src.trade.screenshot_import.resolve import resolve_items


def _one(text, identity_ctx, board):
    item = parse_line(text)
    assert item is not None, text
    (res,) = resolve_items([item], identity_ctx=identity_ctx, contract=board)
    return res


def test_exact_player_resolves_to_board_row(identity_ctx, board):
    res = _one("Patrick Mahomes QB KC", identity_ctx, board)
    assert (res.status, res.board_name, res.sleeper_id) == (
        "resolved",
        "Patrick Mahomes",
        "4046",
    )


def test_suffix_names_join_through_sleeper_id(identity_ctx, board):
    res = _one("Marvin Harrison Jr.", identity_ctx, board)
    assert res.status == "resolved" and res.board_name == "Marvin Harrison Jr."


def test_idp_players_resolve_in_the_idp_group(identity_ctx, board):
    assert _one("Quay Walker LB", identity_ctx, board).board_name == "Quay Walker"
    assert _one("Jordan Davis DE PHI", identity_ctx, board).board_name == "Jordan Davis"
    assert _one("Josh Hines-Allen DL", identity_ctx, board).board_name == "Josh Hines-Allen"


def test_position_hint_separates_homonyms(identity_ctx, board):
    # Josh Allen the QB (rostered) vs a retired guard — the QB hint narrows.
    res = _one("Josh Allen QB", identity_ctx, board)
    assert res.status == "resolved" and res.sleeper_id == "4984"


def test_similar_names_need_confirmation_and_never_auto_select(identity_ctx, board):
    # Two rostered IDP Byron Youngs (LAR LB, PHI DL), both on the board.
    res = _one("Byron Young", identity_ctx, board)
    assert res.status == "needs_confirmation"
    assert res.board_name is None and res.sleeper_id is None
    assert {c["sleeperId"] for c in res.candidates} == {"10917", "10925"}
    assert all(set(c) == {"sleeperId", "boardName", "position", "team"} for c in res.candidates)


def test_ocr_surname_typo_is_unresolved_with_a_suggestion(identity_ctx, board):
    res = _one("Patrick Mahomse", identity_ctx, board)
    assert res.status == "unresolved" and res.reason == "no_match"
    assert res.board_name is None and res.sleeper_id is None
    assert res.suggestions and res.suggestions[0]["boardName"] == "Patrick Mahomes"


def test_resolved_but_not_on_board_keeps_the_id_and_says_why(identity_ctx, board):
    res = _one("Tevin Coleman", identity_ctx, board)  # in the directory, not on the board
    assert res.status == "unresolved" and res.reason == "not_on_board"
    assert res.sleeper_id == "2378" and res.board_name is None


def test_exact_board_fallback_for_rows_without_player_id(identity_ctx, board):
    board["playersArray"].append(
        {"displayName": "Zeke Unlisted", "canonicalName": "Zeke Unlisted", "position": "WR"}
    )
    res = _one("Zeke Unlisted", identity_ctx, board)
    assert res.status == "resolved" and res.board_name == "Zeke Unlisted"
    assert res.sleeper_id is None


def test_directory_unavailable_is_explicit(board):
    res = _one("Patrick Mahomes", IdentityContext(index=None), board)
    assert res.status == "unresolved" and res.reason == "identity_directory_unavailable"


def test_board_unavailable_is_explicit(identity_ctx):
    res = _one("Patrick Mahomes", identity_ctx, None)
    assert res.status == "unresolved" and res.reason == "board_unavailable"


def test_generic_specific_and_tier_picks(identity_ctx, board):
    assert _one("2027 1st", identity_ctx, board).board_name == "2027 Round 1"
    assert _one("2027 Early 1st", identity_ctx, board).board_name == "2027 Early 1st"
    assert _one("2026 1.05", identity_ctx, board).board_name == "2026 Pick 1.05"


def test_slot_pick_the_board_does_not_carry_is_never_downgraded_silently(identity_ctx, board):
    res = _one("2028 1.05", identity_ctx, board)
    assert res.status == "unresolved" and res.reason == "not_on_board"
    assert res.board_name is None
    assert [s["boardName"] for s in res.suggestions] == ["2028 Round 1"]


def test_retired_pick_class(identity_ctx, board):
    res = _one("2025 1st", identity_ctx, board)
    assert res.status == "unresolved" and res.reason == "retired_pick_class"
    board["pickClassLifecycle"]["retiredYears"] = []
    assert (
        _one("2025 1st", identity_ctx, board).reason == "retired_pick_class"
    )  # < currentDraftYear


def test_team_named_pick_resolves_generic_with_owner_note(identity_ctx, board):
    res = _one("2027 Team A 1st", identity_ctx, board)
    assert res.status == "resolved" and res.board_name == "2027 Round 1"
    assert res.reason == "pick_owner_not_established"


def test_pick_without_year_is_unresolved(identity_ctx, board):
    res = _one("Early 1st", identity_ctx, board)
    assert res.status == "unresolved" and res.reason == "pick_year_missing"


def test_no_value_field_is_ever_read(identity_ctx, board):
    # Values on the board must not influence which candidate is offered.
    for row in board["playersArray"]:
        row["rankDerivedValue"] = 9999 if row.get("playerId") == "10925" else 1
    res = _one("Byron Young", identity_ctx, board)
    assert res.status == "needs_confirmation"


def test_a_bare_pick_on_a_slot_priced_class_asks_which_slot():
    """ "2027 1st" once 2027 is priced by slot: read correctly, never guessed."""
    from src.identity.picks import parse_pick_label
    from src.trade.screenshot_import.parse import ParsedItem
    from src.trade.screenshot_import.resolve import (
        BoardIndex,
        REASON_PICK_SLOT_UNKNOWN,
        _resolve_pick,
    )

    contract = {
        "currentDraftYear": 2027,
        "playersArray": [
            {"displayName": "2027 Early 1st", "assetClass": "pick"},
            {"displayName": "2027 Mid 1st", "assetClass": "pick"},
        ],
    }
    item = ParsedItem(
        kind="pick", raw="2027 1st", market_ref=parse_pick_label("2027 1st").market_ref
    )
    out = _resolve_pick(item, BoardIndex(contract))
    assert out.status == "unresolved" and out.board_name is None
    assert out.reason == REASON_PICK_SLOT_UNKNOWN
    assert [s["boardName"] for s in out.suggestions] == ["2027 Early 1st", "2027 Mid 1st"]
