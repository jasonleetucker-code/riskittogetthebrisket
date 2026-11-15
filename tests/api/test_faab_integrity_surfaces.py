"""CW-10 / AMATH-S27 — FAAB integrity across the surfaces that show a bid.

* W10-F001 / W11-F005 at the route: the bid desk's figure is capped by the team's
  balance while the objective block does not move with it.
* W11-F007: the payload's legacy keys are the engine's numbers, and the client
  holds no bid arithmetic (it exports none -- ``CLAUDE.md`` FAAB section).
* AMATH-S27 at the route: a broken ``config/trade/faab.json`` is a named 503, never
  a bid computed from substituted defaults.

All Sleeper / analytics / intel inputs are stubbed by the shared ``faab_env``
fixture -- no network.
"""

from __future__ import annotations

import json
import pathlib
import re

import pytest
from fastapi.testclient import TestClient

import server
from src.trade import faab_engine as FE
from tests.api.test_faab_recommend_endpoint import (  # noqa: F401  (fixture re-export)
    _post,
    faab_env,
)

ROOT = pathlib.Path(__file__).resolve().parents[2]


def _with_balance(balance: int):
    def mutate(contract):
        for team in contract["sleeper"]["teams"]:
            if team["ownerId"] == "me":
                team["faabRemaining"] = balance

    return mutate


@pytest.mark.usefixtures("faab_env")
class TestDeskRoute:
    def _ask(self, monkeypatch, balance: int, add: str = "Hot Pickup") -> dict:
        with TestClient(server.app, raise_server_exceptions=True) as client:
            res = _post(
                client,
                monkeypatch,
                {"addPlayerName": add, "teamOwnerId": "me"},
                mutate=_with_balance(balance),
            )
        assert res.status_code == 200, res.text
        return res.json()

    @pytest.mark.parametrize("balance", [0, 1, 3, 80])
    def test_the_figure_never_exceeds_the_teams_balance(self, monkeypatch, balance):
        payload = self._ask(monkeypatch, balance)
        bids = payload["bids"]
        assert 0 <= bids["conservative"] <= bids["recommended"] <= bids["aggressive"]
        assert bids["aggressive"] <= bids["maxRational"] <= balance
        assert payload["standard"] == bids["recommended"] <= balance
        assert payload["max"] == bids["maxRational"]

    def test_worth_does_not_move_with_the_balance(self, monkeypatch):
        reference = self._ask(monkeypatch, 80)["objective"]
        for balance in (0, 1, 7, 500):
            assert self._ask(monkeypatch, balance)["objective"] == reference

    def test_the_same_player_gets_the_same_worth_whatever_else_is_asked_first(self, monkeypatch):
        first = self._ask(monkeypatch, 80)
        self._ask(monkeypatch, 80, add="Backup Wr")
        again = self._ask(monkeypatch, 80)
        assert again["bids"] == first["bids"]
        assert again["objective"] == first["objective"]


@pytest.mark.usefixtures("faab_env")
class TestBrokenConfigIsARefusalAtTheRoute:
    @pytest.fixture()
    def broken_config(self, tmp_path, monkeypatch):
        shipped = json.loads((ROOT / "config" / "trade" / "faab.json").read_text(encoding="utf-8"))
        del shipped["market"]["rivalSigma"]
        path = tmp_path / "faab.json"
        path.write_text(json.dumps(shipped), encoding="utf-8")
        monkeypatch.setattr(FE, "_CONFIG_PATH", path)
        monkeypatch.setattr(FE, "_CONFIG_CACHE", None)

    def test_the_bid_desk_refuses_with_a_named_error(self, monkeypatch, broken_config):
        with TestClient(server.app, raise_server_exceptions=True) as client:
            res = _post(client, monkeypatch, {"addPlayerName": "Hot Pickup", "teamOwnerId": "me"})
        assert res.status_code == 503
        body = res.json()
        assert body["error"] == "faab_config_invalid"
        assert "market.rivalSigma" in body["message"]
        assert "standard" not in body  # no figure is quoted at all

    def test_the_suggestions_list_refuses_too(self, monkeypatch, broken_config):
        monkeypatch.setattr(server, "latest_contract_data", {"playersArray": [{"x": 1}]})
        with TestClient(server.app, raise_server_exceptions=True) as client:
            res = client.post("/api/waiver/suggestions", json={"teamOwnerId": "me"})
        assert res.status_code == 503
        assert res.json()["error"] == "faab_config_invalid"

    def test_a_valid_config_is_not_refused(self, monkeypatch):
        FE.load_faab_config(refresh=True)
        with TestClient(server.app, raise_server_exceptions=True) as client:
            res = _post(client, monkeypatch, {"addPlayerName": "Hot Pickup", "teamOwnerId": "me"})
        assert res.status_code == 200


class TestTheClientHoldsNoBidArithmetic:
    """W11-F005 / W11-F007's mechanism was a client port (``computeFaabHint``) with
    its own denominator.  It is gone; these source guards fail if one returns."""

    FRONTEND_FILES = [
        "frontend/lib/waiver-faab.js",
        "frontend/lib/waiver-logic.js",
        "frontend/components/waivers/WaiverBidFigure.jsx",
        "frontend/components/waivers/FaabRecommendation.jsx",
        "frontend/app/waivers/page.jsx",
    ]

    def _sources(self):
        for rel in self.FRONTEND_FILES:
            path = ROOT / rel
            assert path.exists(), rel
            yield rel, path.read_text(encoding="utf-8")

    def test_no_client_bid_formula_is_defined_or_exported(self):
        pattern = re.compile(
            r"(function|const|let|var|export\s+(function|const))\s+computeFaabHint\b"
        )
        for rel, src in self._sources():
            assert not pattern.search(src), rel

    def test_the_filtered_list_maximum_is_not_a_denominator_anywhere(self):
        for rel, src in self._sources():
            assert "topAddValue" not in src, rel

    def test_the_figure_renderer_uses_the_backend_number_verbatim(self):
        src = (ROOT / "frontend/components/waivers/WaiverBidFigure.jsx").read_text(encoding="utf-8")
        # Unit formatting only: no multiplication, scale, cap or floor on a bid.
        code = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
        code = re.sub(r"//[^\n]*", "", code)
        for needle in ("Math.min", "Math.max", "* 0.", "0.7 *", "budget", "remaining"):
            assert needle not in code, needle
