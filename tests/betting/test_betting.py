"""Unit tests for the Betting feature backend.

Covers the recommendation blend, Kalshi market matching, per-user
guardrails, the SQLite bet store, and (when the crypto backend is
available) the RSA-PSS request signer.
"""

from __future__ import annotations

import pytest

from src.api import bets_store
from src.api import kalshi_client as kc
from src.betting import kalshi_mapping as kmap
from src.betting import recommendations as recs
from src.betting import settings as bset


# ── recommendation blend ────────────────────────────────────────────────
def _snapshot():
    return {
        "generated_at": "2026-05-21T18:00:00Z",
        "games": [
            {
                "game_id": "g1",
                "sport": "basketball_nba",
                "commence_time": "2026-05-21T23:30:00Z",
                "home_team": "San Antonio Spurs",
                "away_team": "New York Knicks",
                "books": [
                    {
                        "book": "draftkings",
                        "outcomes": [
                            {"team": "New York Knicks", "price": -150},
                            {"team": "San Antonio Spurs", "price": 130},
                        ],
                    },
                    {
                        "book": "fanduel",
                        "outcomes": [
                            {"team": "New York Knicks", "price": -145},
                            {"team": "San Antonio Spurs", "price": 125},
                        ],
                    },
                ],
            },
            {
                "game_id": "g2",
                "sport": "basketball_nba",
                "commence_time": "2026-05-21T23:30:00Z",
                "home_team": "Boston Celtics",
                "away_team": "Miami Heat",
                "books": [
                    {
                        "book": "draftkings",
                        "outcomes": [
                            {"team": "Boston Celtics", "price": -110},
                            {"team": "Miami Heat", "price": -110},
                        ],
                    }
                ],
            },
        ],
    }


def test_american_to_prob():
    assert recs.american_to_prob(-150) == pytest.approx(0.6, abs=0.01)
    assert recs.american_to_prob(150) == pytest.approx(0.4, abs=0.01)
    assert recs.american_to_prob("nan") is None
    assert recs.american_to_prob(0) is None


def test_build_recommendations_picks_favorite_and_sorts():
    out = recs.build_recommendations(_snapshot())
    assert len(out) == 2
    # The Knicks game is a clearer favorite → higher confidence → first.
    top = out[0]
    assert top["side_team"] == "New York Knicks"
    assert top["side_label"] == "New York Knicks ML"
    # De-vigged fair price ~ 58-60 cents.
    assert 55 <= top["fair_price_cents"] <= 62
    assert top["book_count"] == 2
    # Sorted by confidence descending.
    assert out[0]["confidence"] >= out[1]["confidence"]
    # The coinflip game produces a near-50 fair price.
    coin = next(r for r in out if r["game_id"] == "g2")
    assert 48 <= coin["fair_price_cents"] <= 52


def test_build_recommendations_min_books_filter():
    out = recs.build_recommendations(_snapshot(), min_books=2)
    # Only the 2-book game survives.
    assert [r["game_id"] for r in out] == ["g1"]


def test_build_recommendations_handles_garbage():
    assert recs.build_recommendations({}) == []
    assert recs.build_recommendations({"games": "nope"}) == []
    assert recs.build_recommendations({"games": [{"home_team": "A"}]}) == []


# ── Kalshi market matching ──────────────────────────────────────────────
def test_select_market_picks_target_team_yes_side():
    markets = [
        {
            "ticker": "KXNBAGAME-26MAY21NYKSAS-NYK",
            "title": "Will the New York Knicks beat the San Antonio Spurs?",
            "yes_sub_title": "New York Knicks",
        },
        {
            "ticker": "KXNBAGAME-26MAY21NYKSAS-SAS",
            "title": "Will the San Antonio Spurs beat the New York Knicks?",
            "yes_sub_title": "San Antonio Spurs",
        },
    ]
    m = kmap.select_market(markets, team="New York Knicks", opponent="San Antonio Spurs")
    assert m is not None
    assert m["ticker"] == "KXNBAGAME-26MAY21NYKSAS-NYK"
    assert m["side"] == "yes"


def test_select_market_no_match_returns_none():
    markets = [{"ticker": "KXNFLGAME-X", "title": "Will the Cowboys win?"}]
    assert kmap.select_market(markets, team="New York Knicks", opponent="Spurs") is None


def test_score_market_zero_when_team_absent():
    assert kmap.score_market({"title": "Spurs game"}, team="Knicks", opponent="Spurs") == 0.0


def test_series_for_sport():
    assert kmap.series_for_sport("basketball_nba") == "KXNBAGAME"
    assert kmap.series_for_sport("unknown") is None


def test_resolve_market_uses_client(monkeypatch):
    class FakeClient:
        def get_markets(self, **params):
            assert params.get("series_ticker") == "KXNBAGAME"
            return {
                "markets": [
                    {
                        "ticker": "KXNBAGAME-NYK",
                        "title": "Will the New York Knicks beat the San Antonio Spurs?",
                        "yes_sub_title": "New York Knicks",
                    }
                ]
            }

    rec = {"side_team": "New York Knicks", "game": "New York Knicks @ San Antonio Spurs", "sport": "basketball_nba"}
    m = kmap.resolve_market(FakeClient(), rec)
    assert m["ticker"] == "KXNBAGAME-NYK"


# ── guardrails ──────────────────────────────────────────────────────────
def test_effective_settings_merges_user_over_defaults():
    eff = bset.effective_settings({"unit_usd": 10, "per_bet_max_usd": 40})
    assert eff["unit_usd"] == 10
    assert eff["per_bet_max_usd"] == 40
    # daily_cap falls back to config default
    assert eff["daily_cap_usd"] > 0
    # require_live_confirm is a safety floor the user cannot disable
    assert eff["require_live_confirm"] is True


def test_check_bet_allowed_paths():
    eff = bset.effective_settings({"unit_usd": 5, "per_bet_max_usd": 25, "daily_cap_usd": 50})
    assert bset.check_bet_allowed(stake_usd=5, settings=eff, committed_today_usd=0, is_live=False).ok
    assert bset.check_bet_allowed(stake_usd=0, settings=eff, committed_today_usd=0, is_live=False).error == "invalid_stake"
    assert (
        bset.check_bet_allowed(stake_usd=30, settings=eff, committed_today_usd=0, is_live=False).error
        == "exceeds_per_bet_max"
    )
    assert (
        bset.check_bet_allowed(stake_usd=20, settings=eff, committed_today_usd=40, is_live=False).error
        == "exceeds_daily_cap"
    )
    # Live + unconfirmed is blocked; demo is fine.
    assert (
        bset.check_bet_allowed(stake_usd=5, settings=eff, committed_today_usd=0, is_live=True).error
        == "live_confirmation_required"
    )
    eff_confirmed = bset.effective_settings(
        {"unit_usd": 5, "per_bet_max_usd": 25, "daily_cap_usd": 50, "live_confirmed": True}
    )
    assert bset.check_bet_allowed(stake_usd=5, settings=eff_confirmed, committed_today_usd=0, is_live=True).ok


def test_sanitize_settings_patch_ignores_unknown_and_floor():
    patch = bset.sanitize_settings_patch(
        {"unit_usd": 7, "require_live_confirm": False, "evil": 1, "live_confirmed": True}
    )
    assert patch["unit_usd"] == 7
    assert patch["live_confirmed"] is True
    # cannot weaken the live-confirm floor or inject arbitrary keys
    assert "require_live_confirm" not in patch
    assert "evil" not in patch


# ── bet store ───────────────────────────────────────────────────────────
def test_bets_store_roundtrip(tmp_path):
    db = tmp_path / "bets.sqlite"
    bet = bets_store.create_bet(
        "alice",
        sport="nba",
        game="NYK @ SAS",
        side_label="NYK ML",
        kalshi_ticker="KXNBAGAME-NYK",
        kalshi_side="yes",
        target_price=60,
        stake_usd=6.0,
        count=10,
        status="resting",
        kalshi_order_id="ord1",
        env="demo",
        path=db,
    )
    assert bet["status"] == "resting"
    assert bet["username"] == "alice"

    listed = bets_store.list_bets("alice", path=db)
    assert len(listed) == 1

    # open across users
    assert len(bets_store.open_bets(path=db)) == 1

    # advancing to filled removes it from the open set
    bets_store.update_bet(bet["id"], {"status": "filled", "filled_count": 10, "filled_price": 59}, path=db)
    assert len(bets_store.open_bets(path=db)) == 0
    refreshed = bets_store.get_bet(bet["id"], path=db)
    assert refreshed["status"] == "filled"
    assert refreshed["filled_price"] == 59

    # committed-today excludes rejected/canceled
    bets_store.create_bet("alice", stake_usd=4.0, status="canceled", path=db)
    assert bets_store.stake_committed_today("alice", path=db) == pytest.approx(6.0)


def test_bets_store_invalid_status(tmp_path):
    with pytest.raises(ValueError):
        bets_store.create_bet("bob", status="bogus", path=tmp_path / "b.sqlite")


# ── price helpers ───────────────────────────────────────────────────────
def test_price_helpers():
    assert kc.dollars_to_cents("0.6500") == 65
    assert kc.dollars_to_cents(0.65) == 65
    assert kc.dollars_to_cents(65) == 65
    assert kc.dollars_to_cents("garbage") is None
    assert kc.cents_to_dollars(65) == "0.6500"


# ── RSA signer (only when the native crypto backend is available) ────────
def test_rsa_signature_verifies():
    if kc.rsa is None:
        pytest.skip("cryptography backend unavailable in this environment")
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding

    private_key = kc.rsa.generate_private_key(public_exponent=65537, key_size=2048)
    client = kc.KalshiClient(key_id="kid", private_key=private_key, base_url=kc.DEMO_BASE)
    ts = "1716315000000"
    method = "GET"
    path = "/trade-api/v2/portfolio/balance"
    sig_b64 = client._sign(ts, method, path)

    import base64

    signature = base64.b64decode(sig_b64)
    message = f"{ts}{method}{path}".encode("utf-8")
    # Raises InvalidSignature if the signature doesn't verify.
    private_key.public_key().verify(
        signature,
        message,
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH),
        hashes.SHA256(),
    )
