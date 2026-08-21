"""Tests for the Trade Package Generator.

The properties that matter, all directive constraints:

* generation is **staged** — later stages expand only what earlier
  stages proved was worth expanding, and structural rejections are
  never expanded;
* the result is a **Pareto frontier**, not a blended score;
* the four rejection rules are real branches with explainable reasons;
* package valuation goes through WS-E's single-market path, and
  suppression keys on **boundary proximity**, not on the presence of a
  conversion;
* nothing ever claims a manager will accept.
"""

from __future__ import annotations

import pytest

from src.league_intel.cross_market import MARKET_IDPTC, MARKET_KTC
from src.roster_intel.packages import (
    CORNERSTONE_PREMIUM_PCT,
    NEAR_MISS_PCT,
    PACKAGES_MODEL_VERSION,
    PackageCandidate,
    RejectionReason,
    TradeAsset,
    describe_limitations,
    generate_packages,
    label_frontier,
    pareto_frontier,
)
from src.roster_intel.partner import RosterSignal
from src.ros.lineup import RosterPlayer

SLOTS = ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX"]


def _player(pid: str, pos: str, value: float) -> RosterPlayer:
    return RosterPlayer(player_id=pid, canonical_name=pid.upper(), position=pos, ros_value=value)


def _asset(pid: str, pos: str, ktc: float, ros: float | None = None) -> TradeAsset:
    return TradeAsset.from_player(
        _player(pid, pos, ros if ros is not None else ktc / 100.0),
        {MARKET_KTC: ktc, MARKET_IDPTC: ktc},
    )


def _idp_asset(pid: str, pos: str, idptc: float) -> TradeAsset:
    """IDP assets are priced ONLY on idpTradeCalc — the situation that
    forces the single-market rule."""
    return TradeAsset.from_player(_player(pid, pos, idptc / 100.0), {MARKET_IDPTC: idptc})


def _our_pool() -> list[RosterPlayer]:
    return [
        _player("qb1", "QB", 100.0),
        _player("rb1", "RB", 90.0),
        _player("rb2", "RB", 80.0),
        _player("wr1", "WR", 95.0),
        _player("wr2", "WR", 85.0),
        _player("te1", "TE", 20.0),
        _player("bench1", "WR", 40.0),
    ]


def _ours() -> list[TradeAsset]:
    return [_asset("rb2", "RB", 5000.0, 80.0), _asset("bench1", "WR", 2000.0, 40.0)]


def _theirs() -> list[TradeAsset]:
    return [
        _asset("their_te", "TE", 5000.0, 85.0),
        _asset("their_wr", "WR", 2200.0, 50.0),
        _asset("their_stud", "RB", 9500.0, 99.0),
    ]


# ══ Staged generation ═══════════════════════════════════════════════


class TestStagedGeneration:
    def test_stage_one_runs_and_is_reported(self):
        res = generate_packages(_our_pool(), SLOTS, our_assets=_ours(), their_assets=_theirs())
        s1 = res["stages"][0]
        assert s1["stage"] == 1
        assert s1["evaluated"] == len(_ours()) * len(_theirs())

    def test_accepted_packages_are_never_expanded(self):
        """A package that already works dominates any expansion of
        itself, so expanding it can only produce dominated output."""
        from src.roster_intel.packages import _is_near_miss

        good = PackageCandidate(send=(), receive=(), stage=1, accepted=True)
        assert _is_near_miss(good, 5.0) is False

    @pytest.mark.parametrize(
        "reason",
        [
            RejectionReason.ILLEGAL_ROSTER,
            RejectionReason.WORSENS_CRITICAL_NEED,
            RejectionReason.UNVALUABLE,
        ],
    )
    def test_structural_rejections_are_never_expanded(self, reason):
        """Adding filler does not make an illegal trade legal, or make a
        partner stop needing the position you are stripping. Expanding
        these burns the budget the staging exists to protect."""
        from src.roster_intel.packages import _is_near_miss

        cand = PackageCandidate(send=(), receive=(), stage=1, accepted=False, rejection=reason)
        assert _is_near_miss(cand, 5.0) is False

    def test_near_miss_window_is_bounded(self):
        """A package 200% off is not fixable by adding a bench piece.
        Without this bound stage 2 expands everything and 'staged'
        becomes brute force with extra steps."""
        from src.league_intel.cross_market import PackageComparison, PackageValuation
        from src.league_intel.cross_market import NormalizationStrategy as NS
        from src.roster_intel.packages import _is_near_miss

        def _cand(gain: float) -> PackageCandidate:
            pv = PackageValuation(strategy=NS.SINGLE_MARKET, market=MARKET_KTC, total=1.0)
            return PackageCandidate(
                send=(),
                receive=(),
                stage=1,
                accepted=False,
                rejection=RejectionReason.CORNERSTONE_WITHOUT_PREMIUM,
                comparison=PackageComparison(
                    counter=pv, offer=pv, market_gain_pct=gain, gate_pct=5.0
                ),
            )

        assert _is_near_miss(_cand(5.0 + NEAR_MISS_PCT - 1), 5.0) is True
        assert _is_near_miss(_cand(5.0 + NEAR_MISS_PCT + 1), 5.0) is False
        assert _is_near_miss(_cand(200.0), 5.0) is False

    def test_search_budget_truncates_loudly(self):
        """A partial frontier presented as complete is worse than no
        frontier."""
        res = generate_packages(
            _our_pool(),
            SLOTS,
            our_assets=_ours(),
            their_assets=_theirs(),
            max_candidates_per_stage=2,
        )
        assert res["truncated"] is True
        assert any("not exhaustive" in n for n in res["notes"])

    def test_stage_report_is_complete(self):
        res = generate_packages(_our_pool(), SLOTS, our_assets=_ours(), their_assets=_theirs())
        assert [s["stage"] for s in res["stages"]] == [1, 2, 3]


# ══ Pareto frontier ═════════════════════════════════════════════════


class TestParetoFrontier:
    def _c(self, ve, ri, ap, si, key="x") -> PackageCandidate:
        return PackageCandidate(
            send=(_asset(key, "RB", 1.0),),
            receive=(_asset(key + "r", "WR", 1.0),),
            stage=1,
            accepted=True,
            value_efficiency=ve,
            roster_improvement=ri,
            acceptance_plausibility=ap,
            simplicity=si,
        )

    def test_dominated_package_is_excluded(self):
        best = self._c(10, 10, 0.5, 0.5, "a")
        worse = self._c(5, 5, 0.4, 0.5, "b")
        front = pareto_frontier([best, worse])
        assert len(front) == 1
        assert front[0].value_efficiency == 10

    def test_tradeoffs_both_survive(self):
        """The whole point: two packages that each win on a different
        axis are both real options, and no blend can say which is
        right."""
        value_play = self._c(20, 1, 0.2, 0.5, "a")
        upgrade_play = self._c(2, 40, 0.2, 0.5, "b")
        front = pareto_frontier([value_play, upgrade_play])
        assert len(front) == 2

    def test_identical_packages_both_survive(self):
        """Ties are not domination — otherwise iteration order would
        silently decide which of two equivalent packages you see."""
        a = self._c(5, 5, 0.3, 0.5, "a")
        b = self._c(5, 5, 0.3, 0.5, "b")
        assert len(pareto_frontier([a, b])) == 2

    def test_rejected_packages_never_reach_the_frontier(self):
        good = self._c(10, 10, 0.5, 0.5, "a")
        bad = PackageCandidate(send=(), receive=(), stage=1, accepted=False, value_efficiency=999)
        assert pareto_frontier([good, bad]) == [good]

    def test_value_and_acceptance_are_structurally_anti_correlated(self):
        """A property worth stating rather than discovering.

        ``value_efficiency`` is OUR market gain; acceptance rises as the
        partner gains. For a 1-for-1 the two move in opposite directions
        by construction, so almost every simple package is Pareto-
        optimal and frontiers are wide. That is the frontier telling the
        truth — there really is no dominant answer — but a caller
        expecting a short list should know why it is long.
        """
        res = generate_packages(
            _our_pool(),
            SLOTS,
            our_assets=[_asset("rb2", "RB", 5000.0, 80.0)],
            their_assets=[
                _asset("cheap", "TE", 4000.0, 70.0),
                _asset("fair", "TE", 5000.0, 70.0),
                _asset("rich", "TE", 6000.0, 70.0),
            ],
            their_full_roster=[_asset("untouchable", "RB", 9900.0)],
            gate_pct=100.0,
        )
        front = res["frontier"]
        assert len(front) >= 2
        by_value = sorted(front, key=lambda p: p["valueEfficiency"])
        assert by_value[0]["acceptancePlausibility"] > by_value[-1]["acceptancePlausibility"]

    def test_frontier_is_labelled_by_axis_not_ranked(self):
        front = pareto_frontier([self._c(20, 1, 0.2, 0.5, "a"), self._c(2, 40, 0.9, 0.5, "b")])
        labelled = label_frontier(front)
        assert set(labelled["bestBy"]) == {
            "valueEfficiency",
            "rosterImprovement",
            "acceptancePlausibility",
            "simplicity",
        }
        assert "preference" in labelled["note"]

    def test_simpler_package_wins_the_simplicity_axis(self):
        simple = PackageCandidate(
            send=(_asset("a", "RB", 1.0),),
            receive=(_asset("b", "WR", 1.0),),
            stage=1,
            accepted=True,
            simplicity=0.5,
        )
        complex_ = PackageCandidate(
            send=(_asset("a", "RB", 1.0), _asset("c", "WR", 1.0)),
            receive=(_asset("b", "WR", 1.0), _asset("d", "TE", 1.0)),
            stage=2,
            accepted=True,
            simplicity=0.25,
        )
        assert simple.simplicity > complex_.simplicity

    def test_domination_is_reported_as_a_rejection(self):
        """A package beaten on every axis is dropped from the frontier
        but still returned, labelled — a silent omission would leave a
        caller unable to explain why a plausible trade vanished."""
        res = generate_packages(
            _our_pool(),
            SLOTS,
            our_assets=[_asset("rb2", "RB", 5000.0, 80.0)],
            # IDENTICAL market value, so value efficiency and acceptance
            # plausibility tie; the only axis that moves is lineup fit.
            their_assets=[
                _asset("fits_us", "TE", 5000.0, 85.0),
                _asset("fits_worse", "TE", 5000.0, 60.0),
            ],
            their_full_roster=[
                _asset("untouchable", "RB", 9900.0),
                _asset("fits_us", "TE", 5000.0, 85.0),
                _asset("fits_worse", "TE", 5000.0, 60.0),
            ],
            gate_pct=100.0,
        )
        reasons = {r["rejection"] for r in res["rejected"]}
        assert RejectionReason.DOMINATED.value in reasons
        dom = next(r for r in res["rejected"] if r["rejection"] == "dominated")
        assert "at least as good" in dom["rejectionDetail"]


# ══ Rejection rules ═════════════════════════════════════════════════


class TestRejectionRules:
    def test_illegal_roster_is_rejected(self):
        res = generate_packages(
            _our_pool(),
            SLOTS,
            our_assets=_ours(),
            their_assets=_theirs(),
            roster_limit=len(_our_pool()) - 1,
        )
        rejects = [r for r in res["rejected"] if r["rejection"] == "illegalRoster"]
        assert rejects
        assert "roster would hold" in rejects[0]["rejectionDetail"]

    def test_same_asset_on_both_sides_is_illegal(self):
        from src.roster_intel.packages import _check_legality

        a = _asset("dup", "RB", 1000.0)
        ok, detail = _check_legality([a], [a], 10, 10, None)
        assert ok is False
        assert "both sides" in detail

    def test_worsening_a_critical_need_is_rejected(self):
        """Taking a partner's only scarce position without sending one
        back is not an offer."""
        their_signal = RosterSignal(owner_id="them", deficit={"TE": 100.0}, surplus={"RB": 50.0})
        res = generate_packages(
            _our_pool(),
            SLOTS,
            our_assets=[_asset("rb2", "RB", 5000.0, 80.0)],
            their_assets=[_asset("their_te", "TE", 5000.0, 85.0)],
            their_signal=their_signal,
        )
        rejects = [r for r in res["rejected"] if r["rejection"] == "worsensCriticalNeed"]
        assert rejects
        assert "TE" in rejects[0]["rejectionDetail"]

    def test_compensating_at_the_same_position_is_allowed(self):
        their_signal = RosterSignal(owner_id="them", deficit={"TE": 100.0})
        res = generate_packages(
            _our_pool(),
            SLOTS,
            our_assets=[_asset("my_te", "TE", 5200.0, 82.0)],
            their_assets=[_asset("their_te", "TE", 5000.0, 85.0)],
            their_signal=their_signal,
        )
        assert not [r for r in res["rejected"] if r["rejection"] == "worsensCriticalNeed"]

    def test_rule_cannot_fire_without_partner_signal_and_says_so(self):
        res = generate_packages(_our_pool(), SLOTS, our_assets=_ours(), their_assets=_theirs())
        assert any("critical-need rejection" in n for n in res["notes"])

    def test_cornerstone_at_market_price_is_rejected(self):
        """A cornerstone moves for a clear overpay or not at all."""
        res = generate_packages(
            _our_pool(),
            SLOTS,
            our_assets=[_asset("rb2", "RB", 9500.0, 80.0)],
            their_assets=[_asset("their_stud", "RB", 9500.0, 99.0)],
        )
        rejects = [r for r in res["rejected"] if r["rejection"] == "cornerstoneWithoutPremium"]
        assert rejects
        assert "clear overpay" in rejects[0]["rejectionDetail"]

    def test_cornerstone_with_a_real_premium_is_allowed(self):
        res = generate_packages(
            _our_pool(),
            SLOTS,
            our_assets=[_asset("rb2", "RB", 13000.0, 80.0)],
            their_assets=[_asset("their_stud", "RB", 9500.0, 99.0)],
            gate_pct=100.0,
        )
        assert not [r for r in res["rejected"] if r["rejection"] == "cornerstoneWithoutPremium"]

    def test_premium_is_measured_in_their_favour(self):
        """Sign check. market_gain_pct is OUR gain, so a real overpay to
        them is negative. Getting this backwards would demand a premium
        in the wrong direction and reject every serious offer."""
        from src.league_intel.cross_market import (
            NormalizationStrategy as NS,
        )
        from src.league_intel.cross_market import (
            PackageComparison,
            PackageValuation,
        )
        from src.roster_intel.packages import _check_cornerstone

        pv = PackageValuation(strategy=NS.SINGLE_MARKET, market=MARKET_KTC, total=1.0)
        stone = frozenset({"s"})
        recv = [_asset("s", "RB", 9000.0)]

        overpay = PackageComparison(
            counter=pv, offer=pv, market_gain_pct=-(CORNERSTONE_PREMIUM_PCT + 5), gate_pct=5.0
        )
        lowball = PackageComparison(counter=pv, offer=pv, market_gain_pct=+20.0, gate_pct=5.0)
        assert _check_cornerstone(recv, stone, overpay)[0] is True
        assert _check_cornerstone(recv, stone, lowball)[0] is False

    def test_cornerstone_requires_elite_value_not_merely_top_rank(self):
        """Regression. With a short candidate pool a pure top-N rule
        makes every asset a cornerstone — a 2,200 bench receiver beside
        a 9,500 stud — and the premium rule then refuses nearly every
        package that could be built."""
        from src.roster_intel.packages import _identify_cornerstones

        stones = _identify_cornerstones(
            [
                _asset("stud", "RB", 9500.0),
                _asset("mid", "TE", 5000.0),
                _asset("bench", "WR", 2200.0),
            ]
        )
        assert stones == {"stud"}

    def test_cornerstones_come_from_the_full_roster_not_the_wanted_list(self):
        """Regression. Deriving cornerstones from the players we ASKED
        about means that if we ask only about their two best, both look
        elite relative to that list and the premium rule refuses
        everything buildable."""
        wanted = [_asset("mid_te", "TE", 5000.0, 85.0)]
        full = [
            _asset("untouchable", "RB", 9900.0),
            _asset("mid_te", "TE", 5000.0, 85.0),
        ]
        narrow = generate_packages(
            _our_pool(),
            SLOTS,
            our_assets=[_asset("rb2", "RB", 5000.0, 80.0)],
            their_assets=wanted,
            gate_pct=100.0,
        )
        informed = generate_packages(
            _our_pool(),
            SLOTS,
            our_assets=[_asset("rb2", "RB", 5000.0, 80.0)],
            their_assets=wanted,
            their_full_roster=full,
            gate_pct=100.0,
        )
        narrow_blocked = [
            r for r in narrow["rejected"] if r["rejection"] == "cornerstoneWithoutPremium"
        ]
        informed_blocked = [
            r for r in informed["rejected"] if r["rejection"] == "cornerstoneWithoutPremium"
        ]
        assert narrow_blocked and not informed_blocked
        assert any("full roster" in n for n in narrow["notes"])
        assert not any("full roster" in n for n in informed["notes"])

    def test_cornerstone_set_is_capped_by_rank_too(self):
        from src.roster_intel.packages import _identify_cornerstones

        stones = _identify_cornerstones([_asset(f"p{i}", "RB", 9000.0 + i) for i in range(6)])
        assert len(stones) == 3

    def test_package_worse_than_no_trade_is_rejected(self):
        """The simplest package of all is no package, and it is always
        available. A trade that loses market value AND lineup points is
        dominated by declining to trade."""
        res = generate_packages(
            _our_pool(),
            SLOTS,
            our_assets=[_asset("rb2", "RB", 5000.0, 80.0)],
            their_assets=[_asset("junk", "WR", 2200.0, 10.0)],
            their_full_roster=[_asset("untouchable", "RB", 9900.0)],
            gate_pct=100.0,
        )
        rejects = [r for r in res["rejected"] if r["rejection"] == "dominatedByNoTrade"]
        assert rejects
        assert "declining to trade is strictly better" in rejects[0]["rejectionDetail"]

    def test_high_acceptance_cannot_rescue_a_bad_trade(self):
        """Plausibility measures how the PARTNER receives the offer.
        Being easy to give away is not a reason to give something away —
        without this rule the most lopsided giveaway lands on the
        frontier as 'most plausible to land'."""
        res = generate_packages(
            _our_pool(),
            SLOTS,
            our_assets=[_asset("rb2", "RB", 5000.0, 80.0)],
            their_assets=[_asset("junk", "WR", 2200.0, 10.0)],
            their_full_roster=[_asset("untouchable", "RB", 9900.0)],
            gate_pct=100.0,
        )
        assert res["frontier"] == []

    def test_a_trade_that_gains_on_one_axis_survives(self):
        """The rule must reject only packages worse on BOTH axes — a
        value-losing trade that materially improves the lineup is a
        legitimate win-now move, not a mistake."""
        res = generate_packages(
            _our_pool(),
            SLOTS,
            # A bench piece, so we surrender no starter.
            our_assets=[_asset("bench1", "WR", 6000.0, 40.0)],
            # Costs market value, but a real lineup upgrade at our hole.
            their_assets=[_asset("good_te", "TE", 4000.0, 90.0)],
            their_full_roster=[_asset("untouchable", "RB", 9900.0)],
            gate_pct=100.0,
        )
        assert not [r for r in res["rejected"] if r["rejection"] == "dominatedByNoTrade"]
        assert res["frontier"]

    def test_every_rejection_carries_a_detail(self):
        res = generate_packages(
            _our_pool(),
            SLOTS,
            our_assets=_ours(),
            their_assets=_theirs(),
            roster_limit=3,
        )
        for r in res["rejected"]:
            assert r["rejection"] != "none"
            assert r["rejectionDetail"]


# ══ WS-E integration ════════════════════════════════════════════════


class TestCrossMarketIntegration:
    def test_idp_package_routes_to_the_idp_board(self):
        """An IDP asset forces idpTradeCalc, the only board spanning
        both universes. Exact — no conversion."""
        res = generate_packages(
            _our_pool(),
            SLOTS,
            our_assets=[_asset("rb2", "RB", 5000.0, 80.0)],
            their_assets=[_idp_asset("edge1", "DL", 5100.0)],
            gate_pct=100.0,
        )
        assert not [r for r in res["rejected"] if r["rejection"] == "unvaluable"]

    def test_asset_priced_on_neither_board_is_unvaluable(self):
        orphan = TradeAsset(
            asset_id="ghost",
            name="Ghost",
            position="WR",
            row={"displayName": "Ghost", "position": "WR", "canonicalSiteValues": {}},
            player=_player("ghost", "WR", 10.0),
        )
        res = generate_packages(
            _our_pool(),
            SLOTS,
            our_assets=[_asset("rb2", "RB", 5000.0, 80.0)],
            their_assets=[orphan],
        )
        assert [r for r in res["rejected"] if r["rejection"] == "unvaluable"]

    def test_suppression_is_boundary_proximity_not_conversion_presence(self):
        """The rule WS-E arrived at after two wrong revisions: a package
        is withheld only when its band straddles the gate. A wide band
        far from the boundary must still resolve."""
        from src.league_intel.cross_market import (
            NormalizationStrategy as NS,
        )
        from src.league_intel.cross_market import (
            PackageValuation,
            compare_packages,
        )

        wide_far = compare_packages(
            PackageValuation(
                strategy=NS.SCALAR_FALLBACK,
                market=MARKET_IDPTC,
                total=10000.0,
                uncertainty_band=800.0,
            ),
            PackageValuation(strategy=NS.SINGLE_MARKET, market=MARKET_IDPTC, total=5000.0),
            gate_pct=5.0,
        )
        assert wide_far.verdict_certain is True

        narrow_near = compare_packages(
            PackageValuation(
                strategy=NS.SCALAR_FALLBACK,
                market=MARKET_IDPTC,
                total=5200.0,
                uncertainty_band=300.0,
            ),
            PackageValuation(strategy=NS.SINGLE_MARKET, market=MARKET_IDPTC, total=5000.0),
            gate_pct=5.0,
        )
        assert narrow_near.verdict_certain is False

    def test_generator_does_not_reimplement_valuation(self):
        import inspect

        from src.roster_intel import packages

        src = inspect.getsource(packages)
        assert "value_package" in src and "compare_packages" in src
        # No hand-rolled summing of market values across a package.
        assert "sum(a.raw_market_value" not in src

    def test_does_not_depend_on_the_pre_fix_trade_engines(self):
        """finder.py was silently offense-only until recently.

        Narrowed 2026-08-20 (C3-PKG-01): the concern this test names is
        specifically about the trade VALUATION engines that carried the
        offense-only defect (finder / suggestions / angle, plus the KTC-VA
        ports they used before cross_market.py existed) — not the entire
        ``src.trade`` namespace. A blanket substring ban on ``"src.trade"``
        also blocked importing ``src.trade.constraints`` (C3-CON-01), the
        canonical LOCK/EXCLUDE owner ``finder.py`` and ``angle.py`` already
        consume — a different, later-built, cross-cutting concern with no
        connection to the offense-only valuation bug. An AST import scan
        pins the actual claim instead of a string match that could not
        distinguish "reimplements offense-only valuation" from "consumes an
        unrelated canonical owner that happens to live under the same
        package".
        """
        import ast
        from pathlib import Path

        source_path = Path(__file__).resolve().parents[2] / "src" / "roster_intel" / "packages.py"
        tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
        forbidden = {"src.trade.finder", "src.trade.suggestions", "src.trade.angle"}
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
        offenders = imported & forbidden
        assert not offenders, (
            f"roster_intel/packages.py imports the pre-fix, offense-only trade "
            f"valuation engine(s) {sorted(offenders)} — it must value packages "
            f"through src.league_intel.cross_market instead"
        )


# ══ C3-CON-01 constraints (LOCK/EXCLUDE, persistent protection) ═══════
#
# 2026-08-20: previously this generator was the one surface with ZERO
# constraints.py integration — no way to keep a protected or excluded
# player out of a generated package at all. Wired through the same
# partition_sendable/blocked_outgoing seam finder.py already uses.


class TestConstraintsWiring:
    def test_constraints_none_is_byte_identical_to_omitting_it(self):
        """The default must be a true no-op — not merely 'usually agrees'.

        This is the golden-fixture inertness proof for the one production
        caller (src/api/gameplan.py), which passes no constraints argument
        today: calling explicitly with ``constraints=None`` must produce
        the exact same dict as not passing the parameter at all.
        """
        with_default = generate_packages(
            _our_pool(), SLOTS, our_assets=_ours(), their_assets=_theirs()
        )
        with_explicit_none = generate_packages(
            _our_pool(), SLOTS, our_assets=_ours(), their_assets=_theirs(), constraints=None
        )
        assert with_default == with_explicit_none

    def test_a_protected_player_never_appears_on_the_outgoing_side(self):
        from src.trade.constraints import resolve_constraints

        constraints = resolve_constraints(persistent={"untouchables": ["BENCH1"]})
        res = generate_packages(
            _our_pool(),
            SLOTS,
            our_assets=_ours(),
            their_assets=_theirs(),
            constraints=constraints,
        )
        sent_ids = {a["id"] for pkg in (*res["frontier"], *res["rejected"]) for a in pkg["send"]}
        assert "bench1" not in sent_ids

    def test_a_protected_player_is_reported_blocked_with_a_reason(self):
        from src.trade.constraints import resolve_constraints

        constraints = resolve_constraints(persistent={"untouchables": ["BENCH1"]})
        res = generate_packages(
            _our_pool(),
            SLOTS,
            our_assets=_ours(),
            their_assets=_theirs(),
            constraints=constraints,
        )
        assert res["constraintsBlockedOutgoing"] == 1
        assert res["constraintsBlockedReasons"] == ["protected_individual"]

    def test_an_incoming_target_who_is_protected_on_the_other_roster_is_untouched(self):
        """Only the OUTGOING side is constrained — a protected player stays
        a valid ACQUISITION target (spec §2.2)."""
        from src.trade.constraints import resolve_constraints

        constraints = resolve_constraints(persistent={"untouchables": ["THEIR_STUD"]})
        unconstrained = generate_packages(
            _our_pool(), SLOTS, our_assets=_ours(), their_assets=_theirs()
        )
        constrained = generate_packages(
            _our_pool(),
            SLOTS,
            our_assets=_ours(),
            their_assets=_theirs(),
            constraints=constraints,
        )
        # Their protected player is still offered to us on some receive side
        # in both runs — nothing about the ACQUISITION side changed.
        received_ids_unconstrained = {
            a["id"] for pkg in unconstrained["frontier"] for a in pkg["receive"]
        }
        received_ids_constrained = {
            a["id"] for pkg in constrained["frontier"] for a in pkg["receive"]
        }
        assert received_ids_unconstrained == received_ids_constrained


# ══ Acceptance language ═════════════════════════════════════════════


class TestAcceptanceLanguage:
    def test_every_package_carries_the_acceptance_caveat(self):
        res = generate_packages(_our_pool(), SLOTS, our_assets=_ours(), their_assets=_theirs())
        for pkg in res["frontier"] + res["rejected"]:
            assert "not a calibrated acceptance probability" in pkg["acceptanceCaveat"]
            assert "will accept" in pkg["acceptanceCaveat"]

    def test_field_is_named_plausibility_not_probability(self):
        res = generate_packages(_our_pool(), SLOTS, our_assets=_ours(), their_assets=_theirs())
        for pkg in res["frontier"]:
            assert "acceptancePlausibility" in pkg
            assert "acceptanceProbability" not in pkg

    def test_confidence_travels_with_the_estimate(self):
        res = generate_packages(_our_pool(), SLOTS, our_assets=_ours(), their_assets=_theirs())
        for pkg in res["frontier"]:
            assert pkg["acceptanceConfidence"] <= 0.45


# ══ Limitations ═════════════════════════════════════════════════════


class TestLimitations:
    def test_inherits_the_acceptance_limitation(self):
        lim = describe_limitations()
        blob = " ".join(lim["cannotSupport"]).lower()
        assert "will accept" in blob
        assert "rejections are never observed" in blob

    def test_declares_search_is_not_exhaustive(self):
        lim = describe_limitations()
        assert any("exhaustive" in s.lower() for s in lim["cannotSupport"])

    def test_declares_the_frontier_must_not_be_collapsed(self):
        lim = describe_limitations()
        assert any("exchange rate" in s.lower() for s in lim["cannotSupport"])

    def test_declares_thresholds_are_assumed(self):
        lim = describe_limitations()
        assert lim["keyAssumptions"]["thresholdsAreMeasured"] is False
        assert lim["keyAssumptions"]["cornerstonePremiumPct"] == CORNERSTONE_PREMIUM_PCT

    def test_model_version_is_stamped(self):
        res = generate_packages(_our_pool(), SLOTS, our_assets=_ours(), their_assets=_theirs())
        assert res["modelVersion"] == PACKAGES_MODEL_VERSION


class TestPurity:
    def test_no_io(self):
        import inspect

        from src.roster_intel import packages

        src = inspect.getsource(packages)
        for forbidden in ("import requests", "open(", "datetime.now", "os.getenv"):
            assert forbidden not in src

    def test_deterministic(self):
        a = generate_packages(_our_pool(), SLOTS, our_assets=_ours(), their_assets=_theirs())
        b = generate_packages(_our_pool(), SLOTS, our_assets=_ours(), their_assets=_theirs())
        assert a["frontier"] == b["frontier"]

    def test_inputs_not_mutated(self):
        pool = _our_pool()
        before = [(p.player_id, p.ros_value) for p in pool]
        generate_packages(pool, SLOTS, our_assets=_ours(), their_assets=_theirs())
        assert [(p.player_id, p.ros_value) for p in pool] == before


# ─────────────────────────────────────────────────────────────────────
# allow_scalar_fallback, at the GENERATOR level
#
# 928a1fa8 made the flag real in cross_market.py — it had been declared
# and never read, so a caller that opted OUT of scalar conversion
# silently got converted totals anyway.  generate_packages defaults it
# to False, so that fix changes what this module returns.
#
# tests/league_intel/test_cross_market.py covers value_package directly.
# Nothing covered the generator, and test_packages.py was 47/47 green
# both before and after the fix — a behaviour change no test observed.
# These close that gap.
# ─────────────────────────────────────────────────────────────────────


def _ktc_only_asset(pid: str, pos: str, ktc: float) -> TradeAsset:
    """Priced ONLY on ktcSfTep — the offense-side mirror of
    ``_idp_asset``.  A package holding one of each cannot be valued on
    a single market, which is the only way to reach the scalar path."""
    return TradeAsset.from_player(_player(pid, pos, ktc / 100.0), {MARKET_KTC: ktc})


class TestScalarFallbackReachesTheGenerator:
    """A package whose SIDE mixes a KTC-only and an IDPTC-only asset."""

    @staticmethod
    def _run(*, allow_scalar_fallback: bool):
        their = [
            _ktc_only_asset("wr9", "WR", 2900.0),
            TradeAsset.from_player(_player("lb9", "LB", 15.0), {MARKET_IDPTC: 1500.0}),
        ]
        # A deep partner roster so `wr9` is not read as a cornerstone —
        # otherwise the structural rule fires first and the 1-for-2 is
        # never generated.
        deep = [
            _asset("stud", "WR", 9500.0),
            _asset("stud2", "RB", 9000.0),
            _asset("stud3", "QB", 8800.0),
        ]
        return generate_packages(
            _our_pool(),
            SLOTS,
            our_assets=[_ktc_only_asset("te1", "TE", 3000.0)],
            their_assets=their,
            their_full_roster=deep + their,
            allow_scalar_fallback=allow_scalar_fallback,
        )

    def test_default_is_opt_out(self):
        """The default must be the strict one. If this flips, every
        caller silently starts trusting a converted total again."""
        import inspect

        sig = inspect.signature(generate_packages)
        assert sig.parameters["allow_scalar_fallback"].default is False

    def test_mixed_market_package_is_unvaluable_by_default(self):
        res = self._run(allow_scalar_fallback=False)
        unvaluable = [r for r in res["rejected"] if r["rejection"] == "unvaluable"]
        assert unvaluable, (
            "a package mixing a KTC-only and an IDPTC-only asset resolved "
            "without conversion — the scalar path is being taken despite "
            f"the opt-out: {res['rejected']}"
        )
        assert not res["members"]

    def test_the_same_package_resolves_when_conversion_is_opted_in(self):
        """The other half of the proof: the package is otherwise fine,
        so the rejection above is the FLAG and not some unrelated rule."""
        res = self._run(allow_scalar_fallback=True)
        assert not [r for r in res["rejected"] if r["rejection"] == "unvaluable"]
        assert res["members"], "opting in should price the package"

    def test_the_flag_changes_the_frontier(self):
        """Stated as the difference, so a future refactor that stops
        threading the flag through fails here rather than silently."""
        strict = self._run(allow_scalar_fallback=False)
        lenient = self._run(allow_scalar_fallback=True)
        assert len(strict["members"]) != len(lenient["members"]), (
            "allow_scalar_fallback made no difference to the frontier — "
            "it is no longer reaching value_package"
        )
