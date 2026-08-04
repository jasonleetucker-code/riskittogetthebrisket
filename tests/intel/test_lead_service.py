"""Lead assembly: league scoping, home-league exclusion, and mode
symmetry."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.intel import ledger, lead_service, roster_shape, service, store
from src.roster_intel.partner import RosterSignal

DAY_MS = 24 * 3600 * 1000


def _now() -> int:
    return int(datetime.now(timezone.utc).timestamp() * 1000)


def event(tx_id, owner, asset, action, ts, league="OTHER", tx_type="trade"):
    return {
        "eventId": f"{tx_id}:{owner}:{action}:{asset}",
        "txId": tx_id,
        "leagueId": league,
        "ownerId": owner,
        "assetId": asset,
        "assetType": "player",
        "action": action,
        "txType": tx_type,
        "ts": ts,
        "week": 1,
        "faabBid": None,
    }


def snapshot(members, league_key="default"):
    state = store.default_state(season="2026")
    state["generatedAt"] = datetime.now(timezone.utc).isoformat()
    state["members"] = {m: {"leagues": ["HOME"], "truncated": False} for m in members}
    state["memberNames"] = {m: f"Mgr {m}" for m in members}
    state["leagues"] = {"HOME": {"name": "Home", "season": "2026", "holdings": {}}}
    store.save_state(state, league_key)
    service.invalidate_cache()


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_DIR", tmp_path / "intel")
    ledger.reset_setup_cache()
    service.invalidate_cache()
    yield
    ledger.reset_setup_cache()
    service.invalidate_cache()


class TestHomeLeagueExclusion:
    def test_trades_in_the_home_league_do_not_count_as_interest(self, env):
        """ "Bought this player ELSEWHERE" must not count a trade made in
        the very league we are looking at — otherwise every current
        owner reads as an enthusiastic buyer of their own player."""
        now = _now()
        snapshot(["them"])
        ledger.ingest_events([event("t1", "them", "P1", "add", now - DAY_MS, league="HOME")])
        payload = lead_service.build_leads(
            league_key="default", asset_id="P1", home_league_ids=["HOME"]
        )
        assert payload["leadsWithObservedInterest"] == 0

    def test_trades_elsewhere_do_count(self, env):
        now = _now()
        snapshot(["them"])
        ledger.ingest_events([event("t1", "them", "P1", "add", now - DAY_MS, league="OTHER")])
        payload = lead_service.build_leads(
            league_key="default", asset_id="P1", home_league_ids=["HOME"]
        )
        assert payload["leadsWithObservedInterest"] == 1
        assert payload["leads"][0]["interest"]["buys"] == 1


class TestModeSymmetry:
    def test_sell_mode_surfaces_buyers(self, env):
        now = _now()
        snapshot(["buyer", "seller"])
        ledger.ingest_events(
            [
                event("t1", "buyer", "P1", "add", now - DAY_MS),
                event("t2", "seller", "P1", "drop", now - DAY_MS),
            ]
        )
        payload = lead_service.build_leads(league_key="default", asset_id="P1", direction="buy")
        assert payload["mode"] == "sell"
        top = payload["leads"][0]
        assert top["ownerId"] == "buyer"

    def test_buy_mode_surfaces_sellers(self, env):
        now = _now()
        snapshot(["buyer", "seller"])
        ledger.ingest_events(
            [
                event("t1", "buyer", "P1", "add", now - DAY_MS),
                event("t2", "seller", "P1", "drop", now - DAY_MS),
            ]
        )
        payload = lead_service.build_leads(league_key="default", asset_id="P1", direction="sell")
        assert payload["mode"] == "buy"
        assert payload["leads"][0]["ownerId"] == "seller"


class TestScoping:
    def test_only_this_leagues_pool_appears(self, env):
        now = _now()
        snapshot(["mine"])
        ledger.ingest_events(
            [
                event("t1", "mine", "P1", "add", now - DAY_MS),
                event("t2", "stranger", "P1", "add", now - DAY_MS),
            ]
        )
        payload = lead_service.build_leads(league_key="default", asset_id="P1")
        assert [x["ownerId"] for x in payload["leads"]] == ["mine"]

    def test_excluded_owner_is_dropped(self, env):
        """In sell mode the caller owns the asset and is not a lead for
        their own player."""
        snapshot(["me", "them"])
        payload = lead_service.build_leads(
            league_key="default", asset_id="P1", exclude_owner_ids=["me"]
        )
        assert "me" not in [x["ownerId"] for x in payload["leads"]]

    def test_empty_pool_yields_no_leads(self, env):
        snapshot([])
        payload = lead_service.build_leads(league_key="default", asset_id="P1")
        assert payload["leads"] == []
        assert payload["poolSize"] == 0


class TestPayloadHonesty:
    def test_limitations_ride_along_with_every_payload(self, env):
        snapshot(["them"])
        payload = lead_service.build_leads(league_key="default", asset_id="P1")
        assert payload["limitations"]["isNotAProbability"] is True

    def test_window_is_stamped(self, env):
        snapshot(["them"])
        payload = lead_service.build_leads(league_key="default", asset_id="P1")
        assert payload["window"] == lead_service.LEAD_WINDOW

    def test_managers_with_no_interest_still_appear_ranked_below(self, env):
        """Absence of observed interest is not evidence of disinterest —
        they stay on the list, just lower."""
        now = _now()
        snapshot(["hot", "cold"])
        ledger.ingest_events([event("t1", "hot", "P1", "add", now - DAY_MS)])
        payload = lead_service.build_leads(league_key="default", asset_id="P1")
        ids = [x["ownerId"] for x in payload["leads"]]
        assert ids == ["hot", "cold"]


class TestRosterShape:
    def _teams(self):
        return [
            {"ownerId": "a", "playerIds": ["qb1", "wr1", "wr2"]},
            {"ownerId": "b", "playerIds": ["wr3"]},
        ]

    def _positions(self):
        return {"qb1": "QB", "wr1": "WR", "wr2": "WR", "wr3": "WR"}

    def test_deficit_reflects_unmet_starter_requirements(self):
        sig = roster_shape.team_signals(
            self._teams(), self._positions(), {"starters": {"QB": 1, "WR": 3}}
        )
        assert sig["a"].deficit.get("WR") == pytest.approx(1.0)
        assert "QB" not in sig["a"].deficit
        assert sig["b"].deficit.get("QB") == pytest.approx(1.0)

    def test_flex_is_spread_across_eligible_positions(self):
        sig = roster_shape.team_signals(
            [{"ownerId": "a", "playerIds": []}],
            {},
            {"starters": {"FLEX": 3}},
        )
        # FLEX spreads over RB/WR/TE — 1.0 each, not 3.0 to one.
        assert sig == {} or all(v <= 1.01 for v in sig["a"].deficit.values())

    def test_missing_settings_yields_empty_rather_than_guessing(self):
        assert roster_shape.team_signals(self._teams(), self._positions(), None) == {}

    def test_owner_of_player_finds_the_holder(self):
        assert roster_shape.owner_of_player(self._teams(), "wr3") == "b"
        assert roster_shape.owner_of_player(self._teams(), "nobody") is None

    def test_matchable_values_collects_per_owner(self):
        vals = roster_shape.matchable_values(self._teams(), {"wr1": 100.0, "wr3": 50.0})
        assert vals["a"] == [100.0]
        assert vals["b"] == [50.0]

    def test_value_floor_excludes_roster_clog(self):
        """Deep bench is not depth — counting it makes every roster look
        like it has a surplus."""
        sig = roster_shape.team_signals(
            self._teams(),
            self._positions(),
            {"starters": {"WR": 1}},
            value_by_player={"wr1": 900.0, "wr2": 1.0},
            starter_value_floor=100.0,
        )
        # Only wr1 clears the floor, so 1 startable WR against 1 needed.
        assert not sig["a"].surplus.get("WR")


class TestPartnerFitIntegration:
    def test_roster_signals_activate_the_partner_term(self, env):
        snapshot(["them"])
        sig = {"them": RosterSignal(owner_id="them", deficit={"WR": 5.0}, contend_probability=0.8)}
        ours = RosterSignal(owner_id="me", surplus={"WR": 5.0}, contend_probability=0.2)
        payload = lead_service.build_leads(
            league_key="default",
            asset_id="P1",
            position="WR",
            roster_signals=sig,
            our_roster=ours,
        )
        lead = payload["leads"][0]
        assert lead["partnerFitScore"] is not None
        assert lead["components"]["positionalNeed"] > 0

    def test_absent_roster_signals_degrade_rather_than_fail(self, env):
        snapshot(["them"])
        payload = lead_service.build_leads(league_key="default", asset_id="P1")
        assert payload["leads"][0]["partnerFitScore"] is None
