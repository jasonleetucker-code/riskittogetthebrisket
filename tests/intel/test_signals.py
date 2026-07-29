"""Signal metrics: volume never optional, windows never summed.

The class :class:`TestNoWindowSumming` is the regression barrier for
the defect that motivated this work — the retired ``trendScore``
(``3*net48h + 2*net7d + 1*net30d``) counted one fresh movement six
times and used the result as the board's sort key.
"""

from __future__ import annotations

import pytest

from src.intel import signals

DAY_MS = 24 * 3600 * 1000
NOW = 1_800_000_000_000


def win(buys=0, sells=0, managers=1, leagues=1, span=None):
    volume = buys + sells
    return {
        "buys": buys,
        "sells": sells,
        "net": buys - sells,
        "volume": volume,
        "buyRate": (buys / volume) if volume else None,
        "uniqueBuyers": managers if buys else 0,
        "uniqueSellers": managers if sells else 0,
        "uniqueManagers": managers,
        "uniqueLeagues": leagues,
        "tradeCount": volume,
        "movementCount": volume,
        "_spanMs": span,
    }


class TestNoWindowSumming:
    def test_trend_score_is_gone(self):
        """The retired formula must not come back under any name."""
        assert not hasattr(signals, "trend_score")
        assert not hasattr(signals, "trendScore")

    def test_asset_signal_exposes_no_total_field(self):
        sig = signals.AssetSignal(asset_id="P1", asset_type="player")
        sig.windows = {"7d": win(buys=1), "30d": win(buys=1)}
        payload = sig.to_dict()
        assert "total" not in payload
        assert "trendScore" not in payload
        # Each window stands alone.
        assert payload["windows"]["7d"]["buys"] == 1
        assert payload["windows"]["30d"]["buys"] == 1

    def test_one_event_in_three_windows_is_never_aggregated_to_three(self):
        """The 15-day movement: present in 30d, 90d and all — one
        movement, reported three times, summed nowhere."""
        per_window = {
            "7d": [],
            "30d": [{"assetId": "P1", "assetType": "player", **win(buys=1)}],
            "90d": [{"assetId": "P1", "assetType": "player", **win(buys=1)}],
            "all": [{"assetId": "P1", "assetType": "player", **win(buys=1)}],
        }
        built = signals.build_asset_signals(
            per_window,
            now_ms=NOW,
            primary_window="30d",
            windows=["7d", "30d", "90d", "all"],
        )
        assert len(built) == 1
        w = built[0].to_dict()["windows"]
        assert w["7d"]["buys"] == 0
        assert w["30d"]["buys"] == 1
        assert w["90d"]["buys"] == 1
        assert w["all"]["buys"] == 1
        assert sum(x["buys"] for x in w.values()) == 3, (
            "the sum exists arithmetically — the point is that nothing in "
            "the product ever computes it"
        )

    def test_velocity_is_a_ratio_not_a_sum(self):
        """A subset window over its superset cancels shared events, so
        velocity cannot inflate with overlap."""
        short = win(buys=2, span=2 * DAY_MS)
        long = win(buys=4, span=30 * DAY_MS)
        v = signals.velocity(short, long)
        # 2/2d = 1/day vs 4/30d = 0.133/day -> ~7.5x
        assert v == pytest.approx(7.5, rel=0.01)

    def test_velocity_of_a_steady_rate_is_one(self):
        """The overlap-cancellation property, stated directly: when the
        short window's rate equals the long window's rate, velocity is
        exactly 1 no matter how many events the two windows SHARE.  A
        sum-based metric could not have this property."""
        short = win(buys=3, span=3 * DAY_MS)  # 1/day
        long = win(buys=30, span=30 * DAY_MS)  # 1/day
        assert signals.velocity(short, long) == pytest.approx(1.0)

    def test_velocity_declines_to_none_on_thin_baseline(self):
        assert signals.velocity(win(buys=1, span=2 * DAY_MS), win(buys=2, span=30 * DAY_MS)) is None

    def test_missing_window_renders_explicit_zero_not_a_gap(self):
        per_window = {
            "48h": [],
            "30d": [{"assetId": "P1", "assetType": "player", **win(buys=3, managers=3)}],
        }
        built = signals.build_asset_signals(
            per_window, now_ms=NOW, primary_window="30d", windows=["48h", "30d"]
        )
        w = built[0].to_dict()["windows"]
        assert w["48h"]["buys"] == 0 and w["48h"]["volume"] == 0


class TestVolumeNeverOptional:
    def test_thin_signal_scores_far_below_broad_signal(self):
        """The brief's example: 1 buy / 0 sells must not appear
        equally strong as 40 buys / 10 sells."""
        thin = signals.signal_strength(net=1, volume=1, unique_managers=1)
        broad = signals.signal_strength(net=30, volume=50, unique_managers=12)
        assert thin > 0 and broad > 0
        assert broad > thin * 5

    def test_a_conflicted_asset_scores_near_zero_by_design(self):
        """40 buys / 39 sells is not a strong signal — it is real
        DISAGREEMENT, and a directional metric must say so.  Its
        volume and confidence stay high; only the direction collapses,
        which is why volume is reported beside strength and never
        replaced by it."""
        conflicted = signals.signal_strength(net=1, volume=79, unique_managers=12)
        assert abs(conflicted) < 2.0
        assert signals.confidence_tier(79, 12, 8) == "high", (
            "high confidence in a genuinely balanced market is correct — "
            "we are confident that opinion is split"
        )

    def test_thin_signal_is_never_labelled_confident_even_when_unanimous(self):
        """The guard against thin-but-lopsided assets is the confidence
        label, not the ordering."""
        assert signals.signal_strength(net=1, volume=1, unique_managers=1) < 10.0
        assert signals.confidence_tier(1, 1, 1) == "low"

    def test_unanimous_broad_signal_beats_unanimous_thin_signal(self):
        thin = signals.signal_strength(net=2, volume=2, unique_managers=1)
        broad = signals.signal_strength(net=20, volume=20, unique_managers=9)
        assert broad > thin * 2

    def test_sample_confidence_is_saturating(self):
        assert signals.sample_confidence(0) == 0.0
        assert signals.sample_confidence(1) < 0.2
        assert signals.sample_confidence(12) > 0.7
        assert signals.sample_confidence(1000) < 1.0

    def test_breadth_discounts_one_manager_repeating(self):
        """Six leagues, one manager, is one opinion — not six."""
        one_manager = signals.signal_strength(net=6, volume=6, unique_managers=1)
        six_managers = signals.signal_strength(net=6, volume=6, unique_managers=6)
        assert six_managers > one_manager

    def test_zero_volume_is_zero_strength(self):
        assert signals.signal_strength(net=0, volume=0, unique_managers=0) == 0.0

    def test_confidence_tier_labels(self):
        assert signals.confidence_tier(0, 0, 0) == "insufficient"
        assert signals.confidence_tier(1, 1, 1) == "low"
        assert signals.confidence_tier(6, 2, 2) == "medium"
        assert signals.confidence_tier(20, 8, 6) == "high"

    def test_single_observation_never_reads_as_high_confidence(self):
        assert signals.confidence_tier(1, 1, 1) != "high"


class TestSorting:
    def _sig(self, asset, buys, sells, managers):
        s = signals.AssetSignal(asset_id=asset, asset_type="player")
        s.windows = {"30d": win(buys=buys, sells=sells, managers=managers)}
        s.strength = signals.signal_strength(
            net=buys - sells, volume=buys + sells, unique_managers=managers
        )
        return s

    def test_net_sort_breaks_ties_on_volume(self):
        thin = self._sig("thin", 1, 0, 1)
        broad = self._sig("broad", 40, 39, 10)
        ordered = signals.sort_signals([thin, broad], sort="net", primary_window="30d")
        assert [s.asset_id for s in ordered] == [
            "broad",
            "thin",
        ], "equal net must be broken by volume, not by insertion order"

    def test_volume_sort(self):
        a = self._sig("a", 2, 0, 1)
        b = self._sig("b", 10, 8, 5)
        assert [s.asset_id for s in signals.sort_signals([a, b], sort="volume")] == ["b", "a"]

    def test_sells_sort_surfaces_negative_signals(self):
        buy = self._sig("buy", 8, 0, 4)
        sell = self._sig("sell", 0, 9, 5)
        assert signals.sort_signals([buy, sell], sort="sells")[0].asset_id == "sell"


class TestWindowBounds:
    def test_all_has_no_lower_bound(self):
        since, until = signals.window_bounds("all", NOW)
        assert since is None and until == NOW

    def test_named_windows_span_correctly(self):
        since, _ = signals.window_bounds("30d", NOW)
        assert NOW - since == 30 * DAY_MS

    def test_unknown_window_raises(self):
        with pytest.raises(ValueError):
            signals.window_bounds("13d", NOW)

    def test_insider_default_is_a_single_uncluttered_window(self):
        assert signals.INSIDER_DEFAULT_WINDOW == "30d"
