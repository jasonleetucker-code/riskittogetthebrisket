"""Cross-league crowd bids — the second market signal.

KTC's public waiver database publishes real claims from other people's
dynasty leagues.  It is a much wider read on what a waiver claim costs
than our own league's history, and it is used for exactly one thing:
pricing the MARKET.  The invariant these tests exist to protect is
that it can never price the PLAYER.

Measured 2026-08-04 for context: the feed served 200 rows spanning
five days across 83 leagues, 98 of them comparable to ``dynasty_main``.
The wider superflex+TEP market's median claim is 0.30% of budget with
a p90 of 8.5% — which brackets this league's own 0% / 6%, i.e. the two
markets agree.
"""

from __future__ import annotations

import pytest

from src.trade import faab_engine as FE
from src.trade import faab_comparability as FC
from src.trade.faab_history import (
    CROWD_RETENTION_DAYS,
    build_crowd_market,
    crowd_bid_index,
    crowd_evidence_for,
    crowd_refusal_reason,
    merge_crowd_rows,
)


BOARD = [9999 - i * 12 for i in range(700)]
NOW = "2026-08-04T12:00:00+00:00"


def _league(**kw):
    base = dict(original_budget=100, team_count=12, starters_per_team=20, current_week=1)
    base.update(kw)
    return FE.LeagueContext(**base)


def _anchors():
    return FE.resolve_anchors(BOARD, _league())


def _rivals(n=11, remaining=100):
    return [FE.RivalTeam(owner_id=f"r{i}", faab_remaining=remaining) for i in range(n)]


def _row(rid, name, pct, date="2026-08-01T00:00:00", league="L1"):
    return {
        "id": rid,
        "date": date,
        "added": name,
        "dropped": None,
        "bidPct": pct,
        "settings": {"leagueId": league},
    }


def _rec(value, crowd=None, **kw):
    return FE.recommend(
        FE.PlayerInput(name="Target", value=value),
        _league(),
        FE.TeamContext(faab_remaining=100, **kw),
        anchors=_anchors(),
        rivals=_rivals(),
        crowd=crowd,
    )


# ── Accumulation ─────────────────────────────────────────────────────


class TestAccumulation:
    def test_rows_accumulate_across_fetches(self):
        """The feed is a ~5-day rolling window, so a single fetch is a
        snapshot.  A season's sample only exists if runs merge."""
        first = merge_crowd_rows(None, [_row(1, "A", 5.0), _row(2, "B", 1.0)], now_iso=NOW)
        second = merge_crowd_rows(first, [_row(3, "C", 2.0)], now_iso=NOW)
        assert len(second["rows"]) == 3
        assert second["addedLastRun"] == 1

    def test_refetching_the_same_window_does_not_multiply_rows(self):
        """The feed re-serves the same recent claims every scrape; at a
        2-hourly cadence that would be ~60x duplication without the id
        dedup."""
        rows = [_row(1, "A", 5.0), _row(2, "B", 1.0)]
        payload = merge_crowd_rows(None, rows, now_iso=NOW)
        for _ in range(5):
            payload = merge_crowd_rows(payload, rows, now_iso=NOW)
        assert len(payload["rows"]) == 2
        assert payload["addedLastRun"] == 0

    def test_existing_rows_win_over_refetched_ones(self):
        first = merge_crowd_rows(None, [_row(1, "A", 5.0)], now_iso=NOW)
        second = merge_crowd_rows(first, [_row(1, "A", 99.0)], now_iso=NOW)
        assert second["rows"][0]["bidPct"] == 5.0

    def test_stale_rows_are_pruned(self):
        """Bidding drifts across a season; an unbounded file would let
        an old market outvote the current one."""
        payload = merge_crowd_rows(
            None,
            [_row(1, "Old", 5.0, date="2020-01-01T00:00:00"), _row(2, "New", 5.0)],
            now_iso=NOW,
        )
        assert [r["added"] for r in payload["rows"]] == ["New"]

    def test_retention_window_is_configurable_and_sane(self):
        assert 30 <= CROWD_RETENTION_DAYS <= 365

    def test_rows_without_an_id_are_skipped(self):
        payload = merge_crowd_rows(None, [{"added": "A", "bidPct": 5.0}], now_iso=NOW)
        assert payload["rows"] == []


# ── Indexing ─────────────────────────────────────────────────────────


class TestCrowdIndex:
    def test_median_not_mean(self):
        rows = [_row(i, "Star", pct) for i, pct in enumerate([0.0, 0.0, 1.0, 2.0, 90.0])]
        idx = crowd_bid_index(merge_crowd_rows(None, rows, now_iso=NOW))
        assert idx["star"]["medianPct"] == 1.0
        assert idx["star"]["maxPct"] == 90.0

    def test_zero_bids_are_kept(self):
        """A $0 add is the modal outcome and the most informative thing
        the feed says.  Dropping zeros is what made the legacy
        analytics read a quiet wire as a contested one."""
        rows = [_row(i, "Quiet", 0.0) for i in range(4)] + [_row(9, "Quiet", 8.0)]
        idx = crowd_bid_index(merge_crowd_rows(None, rows, now_iso=NOW))
        assert idx["quiet"]["claims"] == 5
        assert idx["quiet"]["medianPct"] == 0.0

    def test_unresolvable_ids_are_excluded(self):
        """KTC ids outside its top-500 board surface as 'Player#1234'
        and can never join our board by name."""
        rows = [_row(1, "Player#2014", 5.0), _row(2, "Real Guy", 5.0)]
        idx = crowd_bid_index(merge_crowd_rows(None, rows, now_iso=NOW))
        assert set(idx) == {"realguy"}

    def test_distinct_leagues_are_counted(self):
        rows = [
            _row(1, "Hot", 5.0, league="L1"),
            _row(2, "Hot", 6.0, league="L2"),
            _row(3, "Hot", 7.0, league="L1"),
        ]
        idx = crowd_bid_index(merge_crowd_rows(None, rows, now_iso=NOW))
        assert idx["hot"]["claims"] == 3
        assert idx["hot"]["leagues"] == 2

    def test_share_of_claims_measures_contention(self):
        rows = [_row(i, "Hot", 5.0) for i in range(6)] + [
            _row(100 + i, f"Cold{i}", 0.0) for i in range(94)
        ]
        idx = crowd_bid_index(merge_crowd_rows(None, rows, now_iso=NOW))
        assert idx["hot"]["shareOfClaims"] == pytest.approx(0.06, abs=0.005)

    def test_a_missing_payload_indexes_to_nothing(self):
        assert crowd_bid_index(None) == {}
        assert crowd_bid_index({}) == {}


# ── The invariant: market only, never value ──────────────────────────


class TestCrowdNeverPricesThePlayer:
    CROWD = {"medianPct": 40.0, "claims": 20, "shareOfClaims": 0.2}

    def test_crowd_never_raises_the_objective_value(self):
        """The headline invariant.  A hype cycle can tell us a claim
        will be expensive; it can never tell us the player is worth
        more.  Our board owns value."""
        for value in (900, 1400, 1900, 2400, 5000):
            without = _rec(value)["objective"]["dollars"]
            with_crowd = _rec(value, crowd=self.CROWD)["objective"]["dollars"]
            assert with_crowd == without, value

    def test_crowd_never_raises_the_max_rational_bid(self):
        for value in (900, 1400, 1900, 2400, 5000):
            without = _rec(value)["bids"]["maxRational"]
            with_crowd = _rec(value, crowd=self.CROWD)["bids"]["maxRational"]
            assert with_crowd == without, value

    def test_a_below_replacement_player_stays_a_zero_bid(self):
        """Cyrus Allen, in effect: our board grades him replacement
        level while comparable leagues pay real money.  We decline."""
        rec = _rec(900, crowd=self.CROWD)
        assert rec["objective"]["dollars"] == 0
        assert rec["bids"]["recommended"] == 0

    def test_but_the_clearing_estimate_becomes_honest(self):
        """Declining is only defensible if we say what it would cost."""
        quiet = _rec(900)["bids"]["clearing"]
        contested = _rec(900, crowd=self.CROWD)["bids"]["clearing"]
        assert contested > quiet

    def test_the_disagreement_is_explained_not_hidden(self):
        rec = _rec(900, crowd=self.CROWD)
        assert "market disagrees" in rec["explanation"]
        assert "40%" in rec["explanation"]

    def test_crowd_appears_as_a_factor_row(self):
        rec = _rec(2400, crowd=self.CROWD)
        assert any(f["label"] == "Cross-league market" for f in rec["factors"])


# ── Market calibration ───────────────────────────────────────────────


class TestMarketCalibration:
    @pytest.mark.parametrize("observed", [5.0, 10.0, 20.0, 35.0])
    def test_clearing_estimate_reproduces_the_observed_winning_bid(self, observed):
        """The crowd figure is a WINNING bid — already a max over its
        league's field — so feeding it in as one rival's typical bid
        and maxing again would double-count the order statistic.  With
        the correction applied, our clearing estimate should land near
        what the crowd actually paid."""
        rec = _rec(1400, crowd={"medianPct": observed, "claims": 6, "shareOfClaims": 0.06})
        assert rec["bids"]["clearing"] == pytest.approx(observed, abs=max(2.5, observed * 0.25))

    def test_a_contested_player_raises_the_clearing_price(self):
        cold = _rec(1400, crowd={"medianPct": 1.0, "claims": 1, "shareOfClaims": 0.01})
        hot = _rec(1400, crowd={"medianPct": 25.0, "claims": 12, "shareOfClaims": 0.12})
        assert hot["bids"]["clearing"] > cold["bids"]["clearing"]

    def test_observed_contention_beats_a_modelled_lack_of_it(self):
        """Engagement is derived from OUR board, which scores a
        replacement-level player near zero demand.  Observed claims in
        comparable leagues have to override that."""
        rec = _rec(1400, crowd={"medianPct": 12.0, "claims": 10, "shareOfClaims": 0.1})
        assert rec["bids"]["clearing"] > 0

    def test_no_crowd_data_changes_nothing(self):
        for value in (1400, 2400, 5000):
            assert _rec(value, crowd=None) == _rec(value)

    def test_an_empty_crowd_entry_is_survivable(self):
        assert _rec(2400, crowd={})["bids"]["recommended"] >= 0


# ── The ledger describes itself: freshness, tiers, refusals ──────────


TARGET = FC.TargetFormat(
    teams=12, superflex=True, tep=True, is_2te=True, idp=True, original_budget=100.0
)


def _crowd_settings(**kw):
    base = dict(
        leagueId="L1",
        superflex=True,
        tepLevel=1,
        is2TE=True,
        teams=12,
        rostersPerPlayer=1,
        hasIdpSlots=False,
        originalBudget=200.0,
    )
    base.update(kw)
    return base


def _stamped(rid, name, pct, *, date="2026-08-01T00:00:00", **settings):
    return {
        "id": rid,
        "date": date,
        "added": name,
        "bidPct": pct,
        "settings": _crowd_settings(**settings),
    }


class TestLedgerFreshness:
    """A snapshot proves when it was taken, not that it is still true."""

    def _payload(self, updated_at):
        payload = merge_crowd_rows(None, [_stamped(1, "Target", 6.0)], now_iso=NOW)
        payload["updatedAt"] = updated_at
        return payload

    def test_a_recent_ledger_is_fresh_and_usable(self):
        market = build_crowd_market(self._payload(NOW), target=TARGET, now_iso=NOW)
        assert market.state == "fresh" and market.usable
        assert crowd_evidence_for(market, "Target", "WR") is not None
        assert crowd_refusal_reason(market, "WR") is None

    def test_a_stale_ledger_is_refused_not_served_as_current(self):
        market = build_crowd_market(
            self._payload("2026-07-01T00:00:00+00:00"), target=TARGET, now_iso=NOW
        )
        assert market.state == "stale" and not market.usable
        assert crowd_evidence_for(market, "Target", "WR") is None
        assert crowd_refusal_reason(market, "WR") == "crowd_ledger_stale"

    def test_stale_evidence_is_retained_and_readable_only_its_authority_expires(self):
        market = build_crowd_market(
            self._payload("2026-07-01T00:00:00+00:00"), target=TARGET, now_iso=NOW
        )
        assert market.rows_used == 1 and "target" in market.index
        assert market.age_days is not None and market.age_days > 7

    def test_unmeasurable_freshness_is_not_freshness(self):
        """No ``updatedAt`` at all must not read as recently updated."""
        payload = self._payload(NOW)
        payload.pop("updatedAt")
        market = build_crowd_market(payload, target=TARGET, now_iso=NOW)
        assert market.state == "stale" and market.age_days is None

    def test_an_absent_ledger_says_so(self):
        market = build_crowd_market(None, target=TARGET, now_iso=NOW)
        assert market.state == "missing"
        assert crowd_refusal_reason(market, "WR") == "no_crowd_ledger"

    def test_the_budget_comes_from_config_not_a_literal(self):
        from src.trade.faab_engine import FaabConfig

        policy = FC.ComparabilityPolicy.from_config(FaabConfig())
        payload = self._payload(NOW)
        assert (
            build_crowd_market(payload, target=TARGET, now_iso=NOW, policy=policy).state == "fresh"
        )


class TestLedgerClassification:
    def test_incomparable_rows_are_dropped_on_read_not_only_at_fetch(self):
        """The feed is a rolling window that must be accumulated, so the
        ledger outlives any single fetch.  Tightening the policy has to apply
        to rows already stored, or a fix would take months to take effect."""
        rows = [
            _stamped(1, "Keep", 6.0),
            _stamped(2, "MultiCopy", 0.0, rostersPerPlayer=3),
            _stamped(3, "TinyBudget", 0.0, originalBudget=1.0),
            _stamped(4, "OneQb", 9.0, superflex=False),
        ]
        market = build_crowd_market(
            merge_crowd_rows(None, rows, now_iso=NOW), target=TARGET, now_iso=NOW
        )
        assert set(market.index) == {"keep"}
        assert market.excluded_counts["multi_copy_league"] == 1
        assert market.excluded_counts["degenerate_budget"] == 1
        assert market.excluded_counts["superflex_mismatch"] == 1
        assert market.rows_total == 4 and market.rows_used == 1

    def test_tier_composition_is_reported(self):
        rows = [_stamped(1, "A", 5.0), _stamped(2, "B", 5.0, is2TE=False)]
        market = build_crowd_market(
            merge_crowd_rows(None, rows, now_iso=NOW), target=TARGET, now_iso=NOW
        )
        assert market.tier_counts == {FC.TIER_A: 1, FC.TIER_B: 1}

    def test_a_tier_changes_no_number(self):
        """Tier weights are evidence-gated by the owner spec and no outcome
        data exists to fit them, so a demoted row still votes in full."""
        a_only = build_crowd_market(
            merge_crowd_rows(None, [_stamped(1, "X", 4.0), _stamped(2, "X", 8.0)], now_iso=NOW),
            target=TARGET,
            now_iso=NOW,
        )
        mixed = build_crowd_market(
            merge_crowd_rows(
                None,
                [_stamped(1, "X", 4.0), _stamped(2, "X", 8.0, is2TE=False, teams=14)],
                now_iso=NOW,
            ),
            target=TARGET,
            now_iso=NOW,
        )
        assert a_only.index["x"]["medianPct"] == mixed.index["x"]["medianPct"]

    def test_legacy_rows_are_retained_as_unverified_not_discarded(self):
        """Rows persisted before the format evidence was captured are real
        observations collected under the older gate.  They may not pass as
        verified — but discarding them would throw away months of accumulated
        market evidence, and the retention window ages them out anyway."""
        market = build_crowd_market(
            merge_crowd_rows(None, [_row(1, "Legacy", 5.0)], now_iso=NOW),
            target=TARGET,
            now_iso=NOW,
        )
        assert market.tier_counts == {FC.TIER_UNVERIFIED: 1}
        assert "legacy" in market.index

    def test_the_dollar_equivalent_is_published_on_the_target_budget(self):
        market = build_crowd_market(
            merge_crowd_rows(None, [_stamped(1, "Target", 20.0)], now_iso=NOW),
            target=TARGET,
            now_iso=NOW,
        )
        assert market.index["target"]["medianEquivalentDollars"] == pytest.approx(20.0)

    def test_provenance_names_dynasty_as_a_source_level_claim(self):
        """``dynastyPlatformType`` is 1 on every row measured — it is the
        platform, not proof of format.  Dynasty here is asserted by the feed,
        and the payload says so rather than implying per-league verification."""
        market = build_crowd_market(
            merge_crowd_rows(None, [_stamped(1, "Target", 5.0)], now_iso=NOW),
            target=TARGET,
            now_iso=NOW,
        )
        assert market.to_dict()["dynastyProvenance"].startswith("source_level_claim")


class TestIdpPopulationGate:
    """Measured on the live feed: no external league in it starts an
    individual defender, so its median is offense-only evidence."""

    def _market(self, *, idp_source):
        rows = [_stamped(1, "Defender", 12.0, hasIdpSlots=idp_source)]
        return build_crowd_market(
            merge_crowd_rows(None, rows, now_iso=NOW), target=TARGET, now_iso=NOW
        )

    def test_an_offense_only_population_may_not_price_a_defender(self):
        market = self._market(idp_source=False)
        assert market.prices_idp is False
        assert crowd_evidence_for(market, "Defender", "LB") is None
        assert crowd_refusal_reason(market, "LB") == "population_cannot_price_idp"

    def test_it_still_prices_offense(self):
        market = self._market(idp_source=False)
        assert crowd_evidence_for(market, "Defender", "WR") is not None

    def test_an_idp_league_in_the_population_unlocks_it(self):
        market = self._market(idp_source=True)
        assert market.prices_idp is True
        assert crowd_evidence_for(market, "Defender", "LB") is not None

    def test_an_unknown_position_is_not_treated_as_idp(self):
        market = self._market(idp_source=False)
        assert crowd_evidence_for(market, "Defender", None) is not None


class TestTheInvariantSurvivesTheRewire:
    """The headline invariant, re-asserted through the new accessor: crowd
    evidence prices the MARKET and never the PLAYER."""

    def test_evidence_from_the_ledger_cannot_move_the_objective_ceiling(self):
        market = build_crowd_market(
            merge_crowd_rows(None, [_stamped(i, "Target", 40.0) for i in range(20)], now_iso=NOW),
            target=TARGET,
            now_iso=NOW,
        )
        evidence = crowd_evidence_for(market, "Target", "WR")
        assert evidence is not None
        with_crowd = _rec(2000, crowd=evidence)
        without = _rec(2000)
        assert with_crowd["objective"] == without["objective"]
        assert with_crowd["bids"]["maxRational"] == without["bids"]["maxRational"]

    def test_a_refused_population_leaves_the_recommendation_crowd_free(self):
        market = build_crowd_market(
            merge_crowd_rows(None, [_stamped(i, "Target", 40.0) for i in range(20)], now_iso=NOW),
            target=TARGET,
            now_iso=NOW,
        )
        refused = crowd_evidence_for(market, "Target", "LB")
        assert refused is None
        assert _rec(2000, crowd=refused) == _rec(2000)
