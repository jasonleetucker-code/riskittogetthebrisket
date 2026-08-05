"""The league-adjusted lens reaches the engines, or says it did not.

The gap this closes
───────────────────
``/api/valuation/league-adjusted`` publishes *factors* for the client to
multiply onto the board it already holds. That works for ``/rankings``.
It did nothing for the engines — trade suggestions, the arbitrage
finder, angles, waivers, the terminal, the simulator — because those run
server-side off ``latest_contract_data`` and never saw the overlay.

So switching the board changed ``/rankings`` and nothing else: adjusted
rankings, market-priced trade advice, and no field on any response
saying which was which. The user-visible symptom was two boards in one
session with no way to tell them apart.

What is pinned here, in the order it can break
──────────────────────────────────────────────
1. **The label cannot be silently omitted.** A static scan requires
   every handler that applies the lens to also stamp the mode it
   actually served. Wiring the lens without the label reintroduces
   exactly the confusion this change removes, and it is a one-line
   omission in a new endpoint a year from now.
2. **The mode served is not the mode requested.** Degradation is the
   normal case, not the error case — no roster snapshot, an incoherent
   adjusted board, a broken overlay. Each must serve the market board
   *and name the reason*.
3. **The shared global is never mutated.** ``latest_contract_data`` is
   read by every other in-flight request. One in-place multiply would
   reprice the market board for everybody, permanently, until the next
   scrape.
"""

from __future__ import annotations

import ast
import copy
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import server
from src.api import gameplan
from src.league_intel import overlay as _overlay
from src.league_intel import publish as _publish
from tests.api.test_gameplan_endpoint import league  # noqa: F401 — pytest fixture
from tests.api.test_league_adjusted_endpoint import _install_contract
from tests.api.test_league_adjusted_endpoint import _players_array as _endpoint_rows

_SERVER_PY = Path(__file__).resolve().parents[2] / "server.py"


# ── 1. The label cannot be silently omitted ─────────────────────────────


def _handlers_calling(tree: ast.Module, name: str) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for inner in ast.walk(node):
            if isinstance(inner, ast.Call):
                fn = inner.func
                if isinstance(fn, ast.Name) and fn.id == name:
                    found.add(node.name)
    return found


def test_every_handler_that_applies_the_lens_also_stamps_what_it_served():
    """THE GUARD.

    A handler that adjusts its board but forgets the stamp returns
    league-adjusted numbers under no label at all — indistinguishable
    from market numbers to the client, which is the failure this whole
    change exists to remove. The scan is over the AST rather than the
    text so a mention in a comment or docstring cannot satisfy it.
    """
    tree = ast.parse(_SERVER_PY.read_text(encoding="utf-8"))
    applies = _handlers_calling(tree, "_valuation_scoped_contract")
    stamps = _handlers_calling(tree, "_stamp_valuation_mode")

    # Non-vacuity: if the scan finds nothing it would pass trivially.
    assert len(applies) >= 8, f"only {len(applies)} handlers apply the lens; the scan is broken"

    missing = sorted(applies - stamps - {"_valuation_scoped_contract"})
    assert not missing, f"these handlers apply the lens without saying so: {missing}"


def test_the_scan_would_catch_a_handler_that_forgot():
    """The guard above is only worth anything if it can fail."""
    tree = ast.parse(
        "async def h():\n"
        "    c, m, n = await _valuation_scoped_contract(request, body, cfg)\n"
        "    return c\n"
    )
    assert _handlers_calling(tree, "_valuation_scoped_contract") == {"h"}
    assert _handlers_calling(tree, "_stamp_valuation_mode") == set()


# ── the key lockstep ────────────────────────────────────────────────────


def test_the_factor_key_matches_the_one_the_overlay_publishes_under():
    """Two functions, one key. A divergence here would not raise — the
    overlay would simply apply to nobody, and every engine would serve
    the market board under a ``leagueAdjusted`` label."""
    for row in (
        {"displayName": "Ja'Marr Chase", "canonicalName": "chase"},
        {"canonicalName": "Only Canonical"},
        {"displayName": "  padded  "},
        {},
    ):
        assert _overlay.row_factor_key(row) == _publish._row_key(row)


# ── the overlay module ──────────────────────────────────────────────────


def _rows():
    return [
        {
            "displayName": "A",
            "position": "WR",
            "rankDerivedValue": 5000,
            "canonicalConsensusRank": 1,
        },
        {
            "displayName": "B",
            "position": "RB",
            "rankDerivedValue": 4000,
            "canonicalConsensusRank": 2,
        },
        {
            "displayName": "C",
            "position": "TE",
            "rankDerivedValue": 3000,
            "canonicalConsensusRank": 3,
        },
    ]


def test_factors_are_applied_multiplicatively_and_the_board_is_re_ranked():
    rows = _rows()
    out = _overlay.adjusted_rows(rows, {"C": 2.0})
    assert out is not None
    by_name = {r["displayName"]: r for r in out}
    assert by_name["C"]["rankDerivedValue"] == 6000
    assert by_name["A"]["rankDerivedValue"] == 5000
    # C overtook A, so the ranks must have moved with the values.
    assert by_name["C"]["canonicalConsensusRank"] < by_name["A"]["canonicalConsensusRank"]


def test_the_callers_rows_are_never_mutated():
    """``latest_contract_data`` is a shared module global. One in-place
    multiply would reprice the market board for every other request."""
    rows = _rows()
    before = copy.deepcopy(rows)
    _overlay.adjusted_rows(rows, {"A": 1.5, "B": 0.5})
    assert rows == before


def test_nothing_to_apply_and_applied_nothing_are_the_same_answer():
    """Both mean "serve the market board", so both must return None —
    a caller that could tell them apart would grow a branch for a
    distinction with no consequence."""
    assert _overlay.adjusted_rows(_rows(), None) is None
    assert _overlay.adjusted_rows(_rows(), {}) is None
    assert _overlay.adjusted_rows([], {"A": 1.5}) is None
    assert _overlay.adjusted_rows(_rows(), {"Nobody On This Board": 1.5}) is None
    assert _overlay.adjusted_contract(None, {"A": 1.5}) is None
    assert _overlay.adjusted_contract({"playersArray": _rows()}, {}) is None


def test_an_unpriced_row_is_left_alone_rather_than_zeroed():
    rows = _rows() + [{"displayName": "D", "position": "WR", "rankDerivedValue": None}]
    out = _overlay.adjusted_rows(rows, {"A": 1.2, "D": 1.2})
    assert {r["displayName"]: r["rankDerivedValue"] for r in out}["D"] is None


def test_the_adjusted_board_keeps_every_row_the_market_board_had():
    """THE REGRESSION THIS CAUGHT.

    ``compact_ranks_and_tiers`` RETURNS only the rows it ranked — it
    drops unranked rows and clears (and drops) current-year slot picks,
    which are proxies for the corresponding rookies and must not consume
    a rank slot. Returning that subset as "the board" measured 740 of
    1093 rows on the live contract: 240 unpriced players and 113 picks,
    every 2026 pick among them. Under the adjusted lens the trade
    calculator would simply not have had any 2026 picks in it.

    Row COUNT is the invariant, not row content: the lens reprices a
    board, it does not curate one.
    """
    rows = _rows() + [
        {"displayName": "Unranked Guy", "position": "WR", "rankDerivedValue": 100},
        {
            "displayName": "2026 Pick 1.06",
            "canonicalName": "2026 Pick 1.06",
            "position": "PICK",
            "assetClass": "pick",
            "rankDerivedValue": 4200,
            "canonicalConsensusRank": 4,
        },
    ]
    from src.api.data_contract import current_rookie_draft_year

    rows[-1]["canonicalName"] = f"{current_rookie_draft_year()} Pick 1.06"
    rows[-1]["displayName"] = rows[-1]["canonicalName"]

    out = _overlay.adjusted_rows(rows, {"A": 1.2})
    assert out is not None
    assert len(out) == len(rows)
    names = {r["displayName"] for r in out}
    assert rows[-1]["displayName"] in names, "the anchor slot pick vanished from the board"
    assert "Unranked Guy" in names, "an unranked row vanished from the board"


def test_the_re_ranked_board_stays_dense_and_contiguous():
    rows = _rows()
    out = _overlay.adjusted_rows(rows, {"C": 3.0, "B": 0.4})
    ranks = sorted(
        r["canonicalConsensusRank"] for r in out if isinstance(r.get("canonicalConsensusRank"), int)
    )
    assert ranks == list(range(1, len(ranks) + 1))


def test_the_contract_copy_shares_untouched_blocks_by_reference():
    """What makes this cheap enough to do per request: only
    ``playersArray`` is rebuilt."""
    sleeper = {"teams": [{"name": "T"}]}
    contract = {"playersArray": _rows(), "sleeper": sleeper, "sources": {"ktc": 1}}
    out = _overlay.adjusted_contract(contract, {"A": 1.2})
    assert out is not None
    assert out["sleeper"] is sleeper
    assert out["playersArray"] is not contract["playersArray"]
    assert contract["playersArray"][0]["rankDerivedValue"] == 5000


# ── 2. The mode served is not the mode requested ────────────────────────


def _post(client, path, body):
    return client.post(path, json=body)


def test_market_is_what_you_get_when_you_do_not_ask(league, monkeypatch):  # noqa: F811
    with TestClient(server.app, raise_server_exceptions=True) as c:
        _install_contract(monkeypatch)
        res = c.get("/api/terminal")
    assert res.status_code == 200, res.text
    assert res.json()["valuationMode"] == "market"


def test_an_unrecognised_mode_degrades_to_market_rather_than_erroring(
    league,  # noqa: F811
    monkeypatch,
):
    """A typo must land on the board the server always has. Erroring
    would take down a working engine over a spelling mistake; honouring
    it would serve a lens nobody named."""
    with TestClient(server.app, raise_server_exceptions=True) as c:
        _install_contract(monkeypatch)
        res = c.get("/api/terminal?valuationMode=leagueadjusted")
    assert res.status_code == 200, res.text
    assert res.json()["valuationMode"] == "market"


def test_asking_for_the_lens_gets_the_lens(league, monkeypatch):  # noqa: F811
    """Non-vacuity for everything below: the adjusted path must actually
    engage on this fixture, or the degradation tests prove nothing."""
    with TestClient(server.app, raise_server_exceptions=True) as c:
        _install_contract(monkeypatch)
        res = c.get("/api/terminal?valuationMode=leagueAdjusted")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["valuationMode"] == "leagueAdjusted", body.get("valuationNote")
    assert "valuationNote" not in body


def test_the_engines_see_different_numbers_under_the_two_lenses(
    league,  # noqa: F811
    monkeypatch,
):
    """The point of the whole change. Same request, two lenses, and the
    values the engine reads must actually differ — otherwise every stamp
    above is decoration on an identical board."""
    # The client is entered for the app lifespan the league fixture
    # needs, not to issue a request — the comparison is on the board
    # itself, which is what every engine reads.
    with TestClient(server.app, raise_server_exceptions=True):
        stub = _install_contract(monkeypatch)
        overlay = gameplan.get_league_adjusted_values("main", "prof_a", stub)
    factors = overlay["factors"]
    assert factors, "fixture produced no factors; the comparison would be vacuous"

    adjusted = _overlay.adjusted_contract(stub, factors)
    assert adjusted is not None
    market_values = {r["displayName"]: r["rankDerivedValue"] for r in stub["playersArray"]}
    lens_values = {r["displayName"]: r["rankDerivedValue"] for r in adjusted["playersArray"]}
    assert market_values != lens_values


def test_a_missing_roster_snapshot_serves_market_and_names_the_reason(
    league,  # noqa: F811
    monkeypatch,
):
    """Refusing outright would take down working engines to protect an
    optional lens. Serving market *silently* is the failure this change
    exists to remove. So: market board, explicit note."""

    def _boom(*args, **kwargs):
        raise gameplan.GameplanUnavailable("no_rosters", "no roster snapshot on disk")

    monkeypatch.setattr(gameplan, "get_league_adjusted_values", _boom)
    with TestClient(server.app, raise_server_exceptions=True) as c:
        _install_contract(monkeypatch)
        res = c.get("/api/terminal?valuationMode=leagueAdjusted")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["valuationMode"] == "market"
    assert body["valuationNote"] == "league_adjusted_unavailable: no_rosters"
    assert any("league_adjusted_unavailable" in w for w in body.get("warnings") or [])


def test_an_overlay_that_blows_up_still_serves_a_board(league, monkeypatch):  # noqa: F811
    def _boom(*args, **kwargs):
        raise RuntimeError("something unforeseen")

    monkeypatch.setattr(gameplan, "get_league_adjusted_values", _boom)
    with TestClient(server.app, raise_server_exceptions=True) as c:
        _install_contract(monkeypatch)
        res = c.get("/api/terminal?valuationMode=leagueAdjusted")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["valuationMode"] == "market"
    assert body["valuationNote"] == "league_adjusted_unavailable: overlay_error"


def test_an_overlay_that_moves_nobody_reports_market(league, monkeypatch):  # noqa: F811
    """ "Adjusted" and "adjusted by exactly nothing" are the same board.
    Claiming the lens for a board identical to market would make the
    stamp meaningless."""
    monkeypatch.setattr(gameplan, "get_league_adjusted_values", lambda *a, **k: {"factors": {}})
    with TestClient(server.app, raise_server_exceptions=True) as c:
        _install_contract(monkeypatch)
        res = c.get("/api/terminal?valuationMode=leagueAdjusted")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["valuationMode"] == "market"
    assert body["valuationNote"] == "league_adjusted_unavailable: no_op"


# ── 3. The shared global is never mutated ───────────────────────────────


def test_serving_the_lens_leaves_the_loaded_contract_untouched(league, monkeypatch):  # noqa: F811
    with TestClient(server.app, raise_server_exceptions=True) as c:
        stub = _install_contract(monkeypatch)
        before = copy.deepcopy(stub)
        res = c.get("/api/terminal?valuationMode=leagueAdjusted")
        assert res.status_code == 200, res.text
        assert res.json()["valuationMode"] == "leagueAdjusted"
        assert server.latest_contract_data == before


# ── the request parser ──────────────────────────────────────────────────


class _FakeRequest:
    def __init__(self, params=None):
        self.query_params = params or {}


@pytest.mark.parametrize(
    "body,params,expected",
    [
        (None, {}, "market"),
        ({}, {}, "market"),
        ({"valuation_mode": "leagueAdjusted"}, {}, "leagueAdjusted"),
        ({"valuationMode": "leagueAdjusted"}, {}, "leagueAdjusted"),
        (None, {"valuationMode": "leagueAdjusted"}, "leagueAdjusted"),
        ({"valuation_mode": "market"}, {"valuationMode": "leagueAdjusted"}, "market"),
        ({"valuation_mode": "LEAGUEADJUSTED"}, {}, "market"),
        ({"valuation_mode": None}, {"valuationMode": "leagueAdjusted"}, "leagueAdjusted"),
    ],
)
def test_the_mode_parser(body, params, expected):
    assert server._requested_valuation_mode(_FakeRequest(params), body) == expected


def test_the_stamp_records_market_explicitly_rather_than_by_omission():
    """ "This is the market board" and "this field is missing" must not
    read the same to a client deciding what label to show."""
    result: dict = {}
    server._stamp_valuation_mode(result, "market", None)
    assert result == {"valuationMode": "market"}


def test_the_stamp_appends_to_existing_warnings_rather_than_replacing_them():
    result = {"warnings": ["something else"]}
    server._stamp_valuation_mode(result, "market", "league_adjusted_unavailable: no_op")
    assert result["warnings"] == ["something else", "league_adjusted_unavailable: no_op"]


# ── 4. The label must be true of the NUMBERS, not just of the response ──
#
# Everything above pins that a handler STAMPS the mode it served. None of
# it pins that the served numbers moved — and for a year they did not, on
# every all-offense trade. ``overlay.adjusted_rows`` scaled
# ``rankDerivedValue`` alone while three engines read
# ``offenseOnlyRankDerivedValue``, so the lens was a measurable no-op with
# ``valuationMode: leagueAdjusted`` and ``valuationNote: null`` on the
# response (W09-F006: identical equity 4004 and identical per-player
# values under both modes; W29-F002: 21 of 51 suggestion legs still at
# the unadjusted value).


def _rows_carrying_both_boards():
    """The endpoint fixture's rows plus the second board.

    ``offenseOnlyRankDerivedValue`` is deliberately NOT equal to
    ``rankDerivedValue``: an engine reading the wrong one has to produce
    a visibly different number, or this test cannot tell the two apart.
    """
    rows = _endpoint_rows()
    for row in rows:
        row["offenseOnlyRankDerivedValue"] = int(round(row["rankDerivedValue"] * 0.92))
    return rows


def test_a_served_engine_value_actually_moves_between_the_two_lenses(
    league,  # noqa: F811
    monkeypatch,
):
    """The acceptance test for R28. An all-offense trade — the shape the
    dropped branch fired on — simulated against both boards."""
    from src.api.trade_simulator import simulate_trade

    with TestClient(server.app, raise_server_exceptions=True):
        stub = _install_contract(monkeypatch, rows=_rows_carrying_both_boards())
        overlay = gameplan.get_league_adjusted_values("main", "prof_a", stub)
    factors = overlay["factors"]
    assert factors, "fixture produced no factors; the comparison would be vacuous"
    assert any(abs(f - 1.0) > 1e-9 for f in factors.values()), "every factor is unity"

    adjusted = _overlay.adjusted_contract(stub, factors)
    assert adjusted is not None

    offense = [
        r["displayName"]
        for r in stub["playersArray"]
        if r.get("position") in ("QB", "RB", "WR", "TE") and factors.get(r["displayName"])
    ]
    assert len(offense) >= 3, "need an all-offense trade to exercise the dropped branch"
    out_name, in_a, in_b = offense[0], offense[1], offense[2]

    def _sim(contract):
        return simulate_trade(
            contract,
            resolved_team={"name": "Me", "players": [out_name]},
            players_out=[out_name],
            players_in=[in_a, in_b],
        )

    market, lens = _sim(stub), _sim(adjusted)
    served = lambda payload: {  # noqa: E731
        a["name"]: a["value"] for a in payload["sending"] + payload["receiving"]
    }
    assert served(market) != served(lens), (
        "the lens changed no served value — every valuationMode stamp above is "
        "decoration on the market board"
    )
    assert market["equity"] != lens["equity"]


def test_every_board_scale_field_is_in_the_list_the_overlay_scales():
    """The list is the contract. A new 0-9999 field added to a contract
    row and forgotten here is the same defect again, and it fails
    silently — the response still says ``leagueAdjusted``."""
    rows = _rows_carrying_both_boards()
    out = _overlay.adjusted_rows(rows, {rows[0]["displayName"]: 1.5})
    moved = out[[r["displayName"] for r in out].index(rows[0]["displayName"])]
    for field in _overlay.BOARD_SCALE_ROW_FIELDS:
        assert moved[field] == int(round(rows[0][field] * 1.5)), field
