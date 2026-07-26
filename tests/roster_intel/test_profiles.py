"""Tests for ``src/roster_intel/profiles.py``.

Mechanism-disconnection focus (ORCHESTRATION §2b): the profile's
strength fields must stay lineup-derived, and surplus/need must stay
lineup-derived rather than count-derived.  Each test below is built so
it fails if someone reconnects a headcount or a summed value.
"""

from __future__ import annotations

import pytest

from src.league_intel.replacement import PositionReplacement, ReplacementLevel
from src.roster_intel.marginal import to_roster_players
from src.roster_intel.profiles import (
    TIER_ORDER,
    build_position_profiles,
    classify_tier,
    elite_threshold,
)


def _p(pid, pos, value, **kw):
    return {
        "playerId": pid,
        "canonicalName": pid,
        "position": pos,
        "rosValue": value,
        "fantasyPositions": kw.pop("fpos", ()),
        **kw,
    }


def _rep(pos, elite, starter, roster):
    def lvl(tier, v):
        return ReplacementLevel(
            position=pos,
            tier=tier,
            value=v,
            threshold_rank=None,
            band_low=None,
            band_high=None,
            sample_size=50,
        )

    return PositionReplacement(
        position=pos,
        starters_per_team=2.0,
        rostered_count=50,
        priced_count=50,
        levels={
            "bestBallStarter": lvl("bestBallStarter", elite),
            "starter": lvl("starter", starter),
            "roster": lvl("roster", roster),
        },
    )


SLOTS = ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "SUPER_FLEX"]


# ── Tiering ────────────────────────────────────────────────────────


class TestClassifyTier:
    def test_tiers_against_league_levels_not_roster_relative(self):
        """A weak room must report ZERO elites. Roster-relative tiering
        would crown every team's best player and is how 'everyone looks
        the same' metrics are born."""
        # NOTE: `_rep`'s first argument populates `bestBallStarter`,
        # which is the startable FLOOR and sits BELOW `starter` in real
        # measured data.  This fixture originally passed 70.0 there and
        # called it "elite", asserting an ordering replacement.py cannot
        # produce — that inverted fixture is precisely why the unreachable
        # `starter` tier survived review.  The floor is now given a
        # realistic value and the elite cut is passed explicitly.
        rep = _rep("RB", elite=30.0, starter=45.0, roster=20.0)
        assert classify_tier(80.0, rep, elite=70.0) == "elite"
        assert classify_tier(50.0, rep, elite=70.0) == "starter"
        assert classify_tier(25.0, rep, elite=70.0) == "depth"
        assert classify_tier(5.0, rep, elite=70.0) == "developmental"

    def test_unknown_levels_never_promote(self):
        assert classify_tier(999.0, None) == "developmental"

    def test_zero_value_is_developmental(self):
        assert classify_tier(0.0, _rep("RB", 70.0, 45.0, 20.0)) == "developmental"


# ── Strength stays lineup-derived ──────────────────────────────────


class TestStrengthIsLineupDerived:
    def test_hoarded_qbs_do_not_inflate_strength(self):
        """MECHANISM TEST. Five QBs vs two: marginal and entry rate must
        expose the hoard. A summed-value or count field would not."""
        base = [
            _p("rb1", "RB", 60),
            _p("rb2", "RB", 55),
            _p("wr1", "WR", 58),
            _p("wr2", "WR", 52),
            _p("te1", "TE", 40),
        ]
        two = build_position_profiles(
            to_roster_players(base + [_p("qb1", "QB", 90), _p("qb2", "QB", 88)]), SLOTS
        ).positions["QB"]
        # The five-QB set must share the SAME top two as the two-QB set,
        # otherwise the comparison measures different players rather
        # than the hoarding effect.
        five = build_position_profiles(
            to_roster_players(
                base
                + [
                    _p("qb1", "QB", 90),
                    _p("qb2", "QB", 88),
                    _p("qb3", "QB", 86),
                    _p("qb4", "QB", 84),
                    _p("qb5", "QB", 82),
                ]
            ),
            SLOTS,
        ).positions["QB"]

        assert five.marginal_points == pytest.approx(two.marginal_points, abs=1e-6)
        assert five.rostered > two.rostered
        assert five.entry_rate < two.entry_rate

    def test_a_position_with_no_slot_has_zero_strength(self):
        prof = build_position_profiles(
            to_roster_players([_p("qb1", "QB", 90), _p("k1", "K", 999), _p("rb1", "RB", 50)]),
            SLOTS,  # no K slot
        )
        assert prof.positions["K"].marginal_points == 0.0
        assert prof.positions["K"].entered_lineup == 0


# ── Surplus / need are lineup-derived ──────────────────────────────


class TestSurplusAndNeed:
    def test_surplus_is_non_entering_value_not_excess_headcount(self):
        """MECHANISM TEST. Only players who do NOT enter the lineup can
        be surplus. A count-vs-required-slots rule would call the QB
        room 'surplus 3' regardless of who plays."""
        rep = {"QB": _rep("QB", elite=80.0, starter=50.0, roster=20.0)}
        prof = build_position_profiles(
            to_roster_players(
                [
                    _p("qb1", "QB", 90),
                    _p("qb2", "QB", 88),
                    _p("qb3", "QB", 86),
                    _p("qb4", "QB", 84),
                    _p("rb1", "RB", 60),
                    _p("rb2", "RB", 55),
                    _p("wr1", "WR", 58),
                    _p("wr2", "WR", 52),
                    _p("te1", "TE", 40),
                ]
            ),
            SLOTS,
            replacement=rep,
        ).positions["QB"]
        # QB + SUPER_FLEX start two; the other two are surplus.
        assert prof.entered_lineup == 2
        assert prof.tradeable_surplus == pytest.approx(86 + 84)
        assert set(prof.surplus_players) == {"qb3", "qb4"}

    def test_low_value_bench_is_not_called_tradeable(self):
        """Without the floor, every dart throw reads as an asset."""
        rep = {"WR": _rep("WR", elite=80.0, starter=50.0, roster=20.0)}
        prof = build_position_profiles(
            to_roster_players(
                [
                    _p("qb1", "QB", 90),
                    _p("wr1", "WR", 70),
                    _p("wr2", "WR", 65),
                    _p("wr3", "WR", 60),
                    _p("wr4", "WR", 3),  # deep dart throw
                    _p("rb1", "RB", 50),
                    _p("te1", "TE", 40),
                ]
            ),
            SLOTS,
            replacement=rep,
        ).positions["WR"]
        assert "wr4" not in prof.surplus_players

    def test_unfilled_dedicated_slots_raise_urgent_need(self):
        prof = build_position_profiles(
            to_roster_players([_p("qb1", "QB", 90), _p("rb1", "RB", 50)]), SLOTS
        )
        assert prof.positions["RB"].urgent_need is True
        assert any("dedicated RB slots" in r for r in prof.positions["RB"].need_reasons)

    def test_position_required_but_absent_is_reported(self):
        """A position with zero bodies must still appear — omitting it
        makes the biggest hole on the roster invisible."""
        prof = build_position_profiles(to_roster_players([_p("qb1", "QB", 90)]), SLOTS)
        assert "TE" in prof.positions
        assert prof.positions["TE"].rostered == 0
        assert prof.positions["TE"].urgent_need is True

    def test_flex_slots_are_not_attributed_to_any_position(self):
        """MECHANISM TEST. Splitting FLEX/SUPER_FLEX by assumption is
        the error that made even-split demand wrong by 40% at QB
        (LI-5). requiredSlots must count dedicated slots only."""
        prof = build_position_profiles(
            to_roster_players([_p("qb1", "QB", 90), _p("rb1", "RB", 60), _p("rb2", "RB", 55)]),
            SLOTS,
        )
        assert prof.positions["QB"].required_slots == 1  # not 2 with SUPER_FLEX
        assert prof.positions["RB"].required_slots == 2  # not 3 with FLEX


# ── Exposure is descriptive, kept separate ─────────────────────────


class TestExposure:
    def test_age_and_bye_are_reported_without_touching_strength(self):
        meta = {
            "rb1": {"age": 30, "byeWeek": 7},
            "rb2": {"age": 24, "byeWeek": 7},
            "rb3": {"age": 22, "byeWeek": 9},
        }
        pool = to_roster_players(
            [_p("qb1", "QB", 90), _p("rb1", "RB", 60), _p("rb2", "RB", 55), _p("rb3", "RB", 50)]
        )
        with_meta = build_position_profiles(pool, SLOTS, player_meta=meta).positions["RB"]
        without = build_position_profiles(pool, SLOTS).positions["RB"]

        assert with_meta.mean_age == pytest.approx((30 + 24 + 22) / 3)
        assert with_meta.age_over_28 == 1
        assert with_meta.bye_concentration == pytest.approx(2 / 3)
        # Strength is identical either way — exposure never blends in.
        assert with_meta.marginal_points == without.marginal_points
        assert without.mean_age is None

    def test_full_bye_stack_reads_as_total_concentration(self):
        meta = {f"rb{i}": {"byeWeek": 9} for i in (1, 2)}
        prof = build_position_profiles(
            to_roster_players([_p("rb1", "RB", 60), _p("rb2", "RB", 55)]),
            ["RB", "RB"],
            player_meta=meta,
        ).positions["RB"]
        assert prof.bye_concentration == pytest.approx(1.0)

    def test_injured_starters_are_distinguished_from_injured_bench(self):
        pool = to_roster_players(
            [
                _p("rb1", "RB", 60, injured=True),  # starts
                _p("rb2", "RB", 55),
                _p("rb3", "RB", 10, injured=True),  # benched
            ]
        )
        prof = build_position_profiles(pool, ["RB", "RB"]).positions["RB"]
        assert prof.injured_count == 2
        assert prof.injured_starters == 1


# ── Shape / variation ──────────────────────────────────────────────


class TestShape:
    def test_tier_counts_cover_every_player_exactly_once(self):
        rep = {"RB": _rep("RB", 70.0, 45.0, 20.0)}
        prof = build_position_profiles(
            to_roster_players([_p(f"rb{i}", "RB", 90 - i * 20) for i in range(4)]),
            ["RB", "RB"],
            replacement=rep,
        ).positions["RB"]
        assert sum(prof.tier_counts.values()) == prof.rostered
        assert set(prof.tier_counts) == set(TIER_ORDER)

    def test_profiles_vary_across_distinct_rosters(self):
        """A constant here would be the `_positional_coverage` defect."""
        vals = set()
        for seed in range(12):
            prof = build_position_profiles(
                to_roster_players(
                    [
                        _p("qb1", "QB", 60 + seed * 3),
                        _p("rb1", "RB", 55 - seed),
                        _p("rb2", "RB", 40 + seed * 2),
                        _p("wr1", "WR", 58 - seed * 2),
                        _p("wr2", "WR", 45),
                        _p("te1", "TE", 25 + seed * 4),
                    ]
                ),
                SLOTS,
            )
            vals.add(round(prof.positions["RB"].marginal_points, 4))
        assert len(vals) > 1

    def test_to_dict_is_json_shaped(self):
        prof = build_position_profiles(
            to_roster_players([_p("qb1", "QB", 90), _p("rb1", "RB", 50)]), SLOTS
        )
        blob = prof.to_dict()
        assert "positions" in blob and "lineupScore" in blob
        qb = blob["positions"]["QB"]
        assert set(qb) >= {"marginalPoints", "entryRate", "tierCounts", "urgentNeed"}


# ─────────────────────────────────────────────────────────────────────
# Tier ladder regression (peer-review defect, 2026-07-26)
#
# classify_tier read `bestBallStarter` as the ELITE bar.  replacement.py
# builds that level as the mean of the LOWEST marginals and `starter` as
# their MEDIAN, so bestBallStarter <= starter always — the top tier was
# pinned to the startable FLOOR.  Anything reaching `starter` had
# already returned "elite", so the `starter` tier was unreachable and
# 65-78% of every rostered player classified elite.
#
# Every test below fails against that code.  `_rep(elite=70, starter=45)`
# in the older fixtures above encodes bestBallStarter ABOVE starter,
# which real data can never produce — that inverted fixture is why the
# defect survived review, so these build levels from MEASURED data.
# ─────────────────────────────────────────────────────────────────────


def _measured_levels():
    """Replacement levels from the synthetic 12-team league."""
    import sys

    sys.path.insert(0, "tests")
    from league_intel.test_replacement import make_team

    from src.league_intel.replacement import compute_replacement_levels

    teams = [make_team(i, scale=1.0 + 0.06 * i) for i in range(12)]
    slots = ["QB", "RB", "RB", "WR", "WR", "WR", "TE", "FLEX", "SUPER_FLEX", "LB", "LB"]
    return teams, compute_replacement_levels(teams, slots)


def _league_values(teams):
    from src.league_intel.replacement import normalize_base_position

    out: dict[str, list[float]] = {}
    for t in teams:
        for p in t["players"]:
            base = normalize_base_position(p["position"])
            v = float(p.get("rosValue") or 0)
            if base and v > 0:
                out.setdefault(base, []).append(v)
    return out


class TestTierLadder:
    def test_bestball_floor_is_below_starter_in_measured_data(self):
        """The premise. If this ever flips, the old code was defensible."""
        _, levels = _measured_levels()
        checked = 0
        for pos, rep in levels.items():
            bb, st = rep.value("bestBallStarter"), rep.value("starter")
            if bb is None or st is None:
                continue
            checked += 1
            assert bb <= st, f"{pos}: bestBallStarter {bb} > starter {st}"
        assert checked >= 4

    def test_thresholds_are_strictly_ordered(self):
        """Property 1 — elite > starter > depth, on measured levels."""
        teams, levels = _measured_levels()
        vals = _league_values(teams)
        checked = 0
        for pos, rep in levels.items():
            st, ro = rep.value("starter"), rep.value("roster")
            el = elite_threshold(vals.get(pos, ()))
            if None in (st, ro, el):
                continue
            checked += 1
            assert el > st > ro, f"{pos}: elite {el} starter {st} roster {ro}"
        assert checked >= 4

    def test_every_tier_is_reachable(self):
        """Property 2 — the one that actually catches the defect."""
        from collections import Counter

        from src.league_intel.replacement import normalize_base_position

        teams, levels = _measured_levels()
        vals = _league_values(teams)
        counts: Counter = Counter()
        for t in teams:
            for p in t["players"]:
                base = normalize_base_position(p["position"])
                counts[
                    classify_tier(
                        float(p.get("rosValue") or 0),
                        levels.get(base),
                        elite=elite_threshold(vals.get(base, ())),
                    )
                ] += 1
        assert counts["starter"] > 0, f"starter tier unreachable: {dict(counts)}"
        assert counts["elite"] > 0, f"elite tier unreachable: {dict(counts)}"
        total = sum(counts.values())
        assert counts["elite"] / total < 0.25, (
            f"elite is {100 * counts['elite'] / total:.0f}% of the league: {dict(counts)}"
        )

    def test_an_ordinary_starter_is_not_elite(self):
        """Property 3."""
        teams, levels = _measured_levels()
        vals = _league_values(teams)
        for pos, rep in levels.items():
            st = rep.value("starter")
            el = elite_threshold(vals.get(pos, ()))
            if st is None or el is None:
                continue
            assert classify_tier(st, rep, elite=el) == "starter"

    def test_the_best_player_at_a_position_is_elite(self):
        """Property 4."""
        teams, levels = _measured_levels()
        vals = _league_values(teams)
        checked = 0
        for pos, rep in levels.items():
            pool = vals.get(pos, [])
            if not pool or rep.value("starter") is None:
                continue
            checked += 1
            assert (
                classify_tier(max(pool), rep, elite=elite_threshold(pool)) == "elite"
            ), f"{pos}: best player not elite"
        assert checked >= 4

    def test_missing_replacement_data_degrades_never_promotes(self):
        """Property 5."""
        assert classify_tier(9999.0, None, elite=1.0) == "developmental"
        rep = _rep("RB", elite=0.0, starter=45.0, roster=20.0)
        assert classify_tier(9999.0, rep, elite=None) == "starter"

    def test_a_degenerate_threshold_cannot_make_everyone_elite(self):
        """Property 6 — a non-separating elite cut is ignored, not obeyed.

        When every team is identical the pool has no spread, so the
        top-5% value collapses onto `starter`. The old code's failure
        mode was exactly this shape.
        """
        from collections import Counter

        from src.league_intel.replacement import (
            compute_replacement_levels,
            normalize_base_position,
        )

        import sys

        sys.path.insert(0, "tests")
        from league_intel.test_replacement import make_team

        teams = [make_team(i, scale=1.0) for i in range(12)]  # identical
        slots = ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "SUPER_FLEX", "LB", "LB"]
        levels = compute_replacement_levels(teams, slots)
        vals = _league_values(teams)
        counts: Counter = Counter()
        for t in teams:
            for p in t["players"]:
                base = normalize_base_position(p["position"])
                counts[
                    classify_tier(
                        float(p.get("rosValue") or 0),
                        levels.get(base),
                        elite=elite_threshold(vals.get(base, ())),
                    )
                ] += 1
        total = sum(counts.values())
        assert counts["elite"] / total < 0.25, (
            f"degenerate pool promoted {100 * counts['elite'] / total:.0f}% to elite: "
            f"{dict(counts)}"
        )
        assert counts["starter"] > 0, f"starter unreachable: {dict(counts)}"
