"""Schedule Intelligence, Milestone A — ``src/public_league/schedule_impact.py``.

The expectation is checked against an INDEPENDENT oracle: every labelled
single-round-robin calendar of a small league is enumerated, each team's
actual head-to-head credits are counted in each calendar, and the mean is
compared with the module's analytic equal-opponent expectation.  The oracle
never calls the module's formula.

Lab fixture (owner prompt, 2026-09-29): an 8-team, 7-week single round robin
has 6,240 unordered round partitions x 7! labelled week orders =
31,449,600 complete calendars.  The partition count is verified here by
enumeration; the 31.4M calendars are NOT enumerated in CI (the 6-team league,
720 calendars, is the exhaustive oracle).
"""

from __future__ import annotations

import itertools
import math
import random
import unittest
from fractions import Fraction

from src.public_league import schedule_impact as si
from src.public_league.identity import build_manager_registry
from src.public_league.snapshot import PublicLeagueSnapshot, SeasonSnapshot

# ── Independent oracle ───────────────────────────────────────────────────


def _perfect_matchings(vertices: tuple[int, ...]) -> list[frozenset]:
    if not vertices:
        return [frozenset()]
    first, rest = vertices[0], vertices[1:]
    out = []
    for i, partner in enumerate(rest):
        remaining = rest[:i] + rest[i + 1 :]
        for m in _perfect_matchings(remaining):
            out.append(m | {frozenset((first, partner))})
    return out


def _one_factorizations(n: int) -> list[list[frozenset]]:
    """Unordered sets of n-1 disjoint perfect matchings covering K_n.

    Canonical form: round k is the matching that pairs vertex 0 with k+1,
    so each unordered factorization is produced exactly once."""
    matchings = _perfect_matchings(tuple(range(n)))
    by_partner: dict[int, list[frozenset]] = {p: [] for p in range(1, n)}
    for m in matchings:
        for e in m:
            if 0 in e:
                (p,) = tuple(e - {0})
                by_partner[p].append(m)
    out = []

    def rec(p: int, used: frozenset, chosen: list):
        if p == n:
            out.append(list(chosen))
            return
        for m in by_partner[p]:
            if used.isdisjoint(m):
                rec(p + 1, used | m, chosen + [m])

    rec(1, frozenset(), [])
    return out


def _labelled_calendars(n: int):
    for fact in _one_factorizations(n):
        for order in itertools.permutations(fact):
            yield order


def _credit(a: Fraction, b: Fraction) -> Fraction:
    return Fraction(1) if a > b else (Fraction(0) if a < b else Fraction(1, 2))


def _oracle_expected(n: int, scores: list[list[Fraction]]) -> list[Fraction]:
    """Mean actual H2H credits per team over every labelled calendar."""
    totals = [Fraction(0)] * n
    count = 0
    for cal in _labelled_calendars(n):
        count += 1
        for w, matching in enumerate(cal):
            for e in matching:
                a, b = tuple(e)
                totals[a] += _credit(scores[w][a], scores[w][b])
                totals[b] += _credit(scores[w][b], scores[w][a])
    return [t / count for t in totals]


def _week_inputs(n: int, scores: list[list[float]], calendar) -> list[si.WeekInput]:
    out = []
    for w, matching in enumerate(calendar):
        out.append(
            si.WeekInput(
                week=w + 1,
                scores={f"T{i}": float(scores[w][i]) for i in range(n)},
                pairs=[tuple(sorted(f"T{i}" for i in e)) for e in matching],
            )
        )
    return out


# ── Oracle agreement ─────────────────────────────────────────────────────


class OracleTests(unittest.TestCase):
    def test_lab_partition_count_8_teams(self) -> None:
        # 6,240 unordered round partitions of K8 (the lab's claim).
        facts = _one_factorizations(8)
        self.assertEqual(len(facts), 6240)
        self.assertEqual(len(facts) * math.factorial(7), 31_449_600)

    def test_small_counts(self) -> None:
        self.assertEqual(len(_one_factorizations(4)), 1)
        self.assertEqual(len(_one_factorizations(6)), 6)
        self.assertEqual(sum(1 for _ in _labelled_calendars(6)), 720)

    def test_expected_credits_equal_the_exhaustive_mean_six_teams(self) -> None:
        rng = random.Random(20260929)
        for trial in range(4):
            # Integers force some exact ties; the oracle uses exact fractions.
            ints = [[rng.randint(80, 90) for _ in range(6)] for _ in range(5)]
            oracle = _oracle_expected(6, [[Fraction(x) for x in row] for row in ints])
            actual_calendar = next(itertools.islice(_labelled_calendars(6), trial * 97, None))
            got = si.compute_schedule_impact(_week_inputs(6, ints, actual_calendar))
            self.assertEqual(got["state"], si.STATE_COMPLETE)
            for i in range(6):
                self.assertAlmostEqual(
                    got["teams"][f"T{i}"]["equalOpponentExpectedH2HCredits"],
                    float(oracle[i]),
                    places=12,
                    msg=f"trial {trial} team {i}",
                )

    def test_eight_team_lab_identity_expected_is_all_play_over_seven(self) -> None:
        # Consistency check of the lab's stated identity, NOT oracle evidence:
        # with no ties this is the production formula restated.  The
        # independent oracle is the exhaustive 6-team enumeration above.
        rng = random.Random(7)
        scores = [[rng.uniform(70, 160) for _ in range(8)] for _ in range(7)]  # no ties
        cal = _one_factorizations(8)[123]
        got = si.compute_schedule_impact(_week_inputs(8, scores, cal))
        for i in range(8):
            t = got["teams"][f"T{i}"]
            self.assertAlmostEqual(
                t["equalOpponentExpectedH2HCredits"], t["allPlayWins"] / 7, places=12
            )


# ── League invariants and edge cases ─────────────────────────────────────


def _league(n=6, weeks=5, seed=1, ties=False):
    rng = random.Random(seed)
    scores = [
        [float(rng.randint(90, 95)) if ties else rng.uniform(80, 150) for _ in range(n)]
        for _ in range(weeks)
    ]
    cal = next(itertools.islice(_labelled_calendars(n), seed, None))
    return scores, cal


class InvariantTests(unittest.TestCase):
    def test_league_totals_equal_games_and_impact_sums_to_zero(self) -> None:
        for seed in range(6):
            scores, cal = _league(seed=seed, ties=seed % 2 == 0)
            got = si.compute_schedule_impact(_week_inputs(6, scores, cal))
            games = 5 * 3
            actual = sum(t["actualH2HCredits"] for t in got["teams"].values())
            expected = sum(t["equalOpponentExpectedH2HCredits"] for t in got["teams"].values())
            impact = sum(t["scheduleImpact"] for t in got["teams"].values())
            self.assertAlmostEqual(actual, games, places=9)
            self.assertAlmostEqual(expected, games, places=9)
            self.assertAlmostEqual(impact, 0.0, places=9)

    def test_sign_positive_means_favorable(self) -> None:
        # T0 scores 2nd-lowest every week but always draws the lowest scorer.
        weeks = []
        for w in range(3):
            scores = {"T0": 100.0, "T1": 90.0, "T2": 150.0, "T3": 140.0}
            weeks.append(si.WeekInput(w + 1, scores, [("T0", "T1"), ("T2", "T3")]))
        got = si.compute_schedule_impact(weeks)
        t0 = got["teams"]["T0"]
        self.assertEqual(t0["actualH2HCredits"], 3.0)
        self.assertAlmostEqual(t0["equalOpponentExpectedH2HCredits"], 1.0)
        self.assertAlmostEqual(t0["scheduleImpact"], 2.0)
        self.assertGreater(t0["scheduleImpact"], 0)

    def test_scores_and_points_for_are_never_changed(self) -> None:
        scores, cal = _league(seed=3)
        got = si.compute_schedule_impact(_week_inputs(6, scores, cal))
        for row in got["weeks"]:
            i = int(row["teamKey"][1:])
            self.assertEqual(row["score"], round(scores[row["week"] - 1][i], 2))
        for i in range(6):
            self.assertAlmostEqual(
                got["teams"][f"T{i}"]["pointsFor"], sum(scores[w][i] for w in range(5)), places=9
            )

    def test_relabelling_teams_relabels_the_results(self) -> None:
        scores, cal = _league(seed=4)
        base = si.compute_schedule_impact(_week_inputs(6, scores, cal))
        perm = [3, 5, 0, 1, 4, 2]
        pscores = [[row[perm.index(i)] for i in range(6)] for row in scores]
        pcal = [frozenset(frozenset(perm[x] for x in e) for e in m) for m in cal]
        moved = si.compute_schedule_impact(_week_inputs(6, pscores, pcal))
        for i in range(6):
            a = base["teams"][f"T{i}"]
            b = moved["teams"][f"T{perm[i]}"]
            for k in ("actualH2HCredits", "equalOpponentExpectedH2HCredits", "scheduleImpact"):
                self.assertAlmostEqual(a[k], b[k], places=12)

    def test_all_tied_week(self) -> None:
        wk = si.WeekInput(1, {f"T{i}": 100.0 for i in range(4)}, [("T0", "T1"), ("T2", "T3")])
        got = si.compute_schedule_impact([wk])
        for t in got["teams"].values():
            self.assertEqual(t["h2hTies"], 1)
            self.assertEqual(t["allPlayRate"], 0.5)
            self.assertEqual(t["scheduleImpact"], 0.0)

    def test_beat_everyone_and_lost_to_everyone(self) -> None:
        wk = si.WeekInput(
            1, {"T0": 200.0, "T1": 50.0, "T2": 100.0, "T3": 110.0}, [("T0", "T1"), ("T2", "T3")]
        )
        got = si.compute_schedule_impact([wk])
        self.assertEqual(got["teams"]["T0"]["allPlayRate"], 1.0)
        self.assertEqual(got["teams"]["T0"]["scheduleImpact"], 0.0)
        self.assertEqual(got["teams"]["T1"]["allPlayRate"], 0.0)
        self.assertEqual(got["teams"]["T1"]["scheduleImpact"], 0.0)

    def test_bye_team_has_no_game_and_is_not_an_eligible_opponent(self) -> None:
        # Five teams scored; T4 was on a bye (unpaired).
        wk = si.WeekInput(
            1,
            {"T0": 100.0, "T1": 90.0, "T2": 80.0, "T3": 70.0, "T4": 999.0},
            [("T0", "T1"), ("T2", "T3")],
        )
        got = si.compute_schedule_impact([wk])
        self.assertNotIn("T4", got["teams"])
        # T0's field is T1..T3 only: T4's 999 is not a possible opponent.
        self.assertEqual(got["teams"]["T0"]["allPlayRate"], 1.0)
        total = sum(t["scheduleImpact"] for t in got["teams"].values())
        self.assertAlmostEqual(total, 0.0, places=12)

    def test_missing_score_is_partial_not_zero(self) -> None:
        wk = si.WeekInput(1, {"T0": 100.0, "T1": 90.0, "T2": 80.0}, [("T0", "T1"), ("T2", "T3")])
        got = si.compute_schedule_impact([wk])
        self.assertEqual(got["state"], si.STATE_PARTIAL)
        self.assertNotIn("T2", got["teams"])
        self.assertNotIn("T3", got["teams"])
        self.assertTrue(any("missing_score:T3" in i for i in got["issues"]))

    def test_multiple_games_in_a_week_is_unsupported(self) -> None:
        wk = si.WeekInput(1, {f"T{i}": 90.0 + i for i in range(4)}, [("T0", "T1"), ("T0", "T2")])
        got = si.compute_schedule_impact([wk])
        self.assertEqual(got["state"], si.STATE_UNSUPPORTED)
        self.assertEqual(got["teams"], {})

    def test_self_matchup_is_unsupported(self) -> None:
        wk = si.WeekInput(1, {"T0": 1.0, "T1": 2.0}, [("T0", "T0")])
        self.assertEqual(si.compute_schedule_impact([wk])["state"], si.STATE_UNSUPPORTED)

    def test_no_weeks_is_unavailable_not_zero(self) -> None:
        got = si.compute_schedule_impact([])
        self.assertEqual(got["state"], si.STATE_UNAVAILABLE)
        self.assertEqual(got["teams"], {})

    def test_opponent_difficulty(self) -> None:
        wk = si.WeekInput(
            1, {"T0": 100.0, "T1": 150.0, "T2": 80.0, "T3": 60.0}, [("T0", "T1"), ("T2", "T3")]
        )
        t0 = si.compute_schedule_impact([wk])["weeks"][0]
        self.assertEqual(t0["teamKey"], "T0")
        # T1 (the opponent faced) outscored both other possible opponents.
        self.assertEqual(t0["opponentScorePercentile"], 1.0)
        self.assertAlmostEqual(t0["pointsFacedVsField"], 150.0 - (150 + 80 + 60) / 3)


# ── Snapshot adapter: finalized weeks, official record, median component ──


def _snap(
    *, median: int | None, records: dict[int, tuple[int, int, int]], weeks: dict[int, list[dict]]
):
    settings = {"playoff_week_start": 15}
    if median is not None:
        settings["league_average_match"] = median
    league = {
        "league_id": "L1",
        "name": "Fixture",
        "season": "2026",
        "season_type": "regular",
        "status": "complete",
        "total_rosters": 4,
        "settings": settings,
    }
    users = [
        {"user_id": f"o{i}", "display_name": f"U{i}", "metadata": {"team_name": f"Team {i}"}}
        for i in range(1, 5)
    ]
    rosters = [
        {
            "roster_id": i,
            "owner_id": f"o{i}",
            "players": [],
            "settings": {"wins": w, "losses": lo, "ties": t}
            if (w, lo, t) != (None, None, None)
            else {},
        }
        for i, (w, lo, t) in records.items()
    ]
    season = SeasonSnapshot(
        season="2026",
        league_id="L1",
        league=league,
        users=users,
        rosters=rosters,
        matchups_by_week=weeks,
        transactions_by_week={},
        drafts=[],
        draft_picks_by_draft={},
        traded_picks=[],
        winners_bracket=[],
        losers_bracket=[],
    )
    return PublicLeagueSnapshot(
        root_league_id="L1",
        generated_at="2026-09-29T00:00:00+00:00",
        seasons=[season],
        managers=build_manager_registry([{"league": league, "users": users, "rosters": rosters}]),
    )


def _week(rows):
    return [{"roster_id": r, "matchup_id": m, "points": p} for r, m, p in rows]


class AdapterTests(unittest.TestCase):
    WEEKS = {
        1: _week([(1, 1, 120.0), (2, 1, 100.0), (3, 2, 90.0), (4, 2, 80.0)]),
        2: _week([(1, 1, 70.0), (3, 1, 130.0), (2, 2, 110.0), (4, 2, 60.0)]),
    }

    def test_median_component_derived_only_when_aligned(self) -> None:
        # o1: H2H 1-1.  With the median game: week1 120 beats median, week2 70 loses -> 2-2.
        snap = _snap(
            median=1,
            records={1: (2, 2, 0), 2: (2, 2, 0), 3: (3, 1, 0), 4: (1, 3, 0)},
            weeks=self.WEEKS,
        )
        c = si.season_contract(snap, snap.seasons[0])
        o1 = next(t for t in c["teams"] if t["ownerId"] == "o1")
        self.assertEqual((o1["h2hWins"], o1["h2hLosses"]), (1, 1))
        self.assertEqual(
            o1["medianComponent"], {"state": "complete", "wins": 1, "losses": 1, "ties": 0}
        )
        self.assertEqual(o1["officialRecord"], {"wins": 2, "losses": 2, "ties": 0})

    def test_misaligned_official_record_is_unavailable_not_invented(self) -> None:
        snap = _snap(
            median=1,
            records={1: (1, 0, 0), 2: (0, 1, 0), 3: (1, 0, 0), 4: (0, 1, 0)},
            weeks=self.WEEKS,
        )
        c = si.season_contract(snap, snap.seasons[0])
        for t in c["teams"]:
            self.assertEqual(t["medianComponent"]["state"], "unavailable")
            self.assertEqual(t["medianComponent"]["reason"], "official_record_unaligned")

    def test_unknown_median_setting_is_unavailable(self) -> None:
        snap = _snap(median=None, records={i: (1, 1, 0) for i in range(1, 5)}, weeks=self.WEEKS)
        c = si.season_contract(snap, snap.seasons[0])
        self.assertTrue(
            all(t["medianComponent"]["reason"] == "median_setting_unknown" for t in c["teams"])
        )

    def test_contract_identity_and_reproducibility(self) -> None:
        snap = _snap(median=0, records={i: (1, 1, 0) for i in range(1, 5)}, weeks=self.WEEKS)
        a = si.season_contract(snap, snap.seasons[0])
        b = si.season_contract(snap, snap.seasons[0])
        self.assertEqual(a["generationId"], b["generationId"])
        self.assertEqual(a["model"]["id"], si.MODEL_EQUAL_OPPONENT)
        self.assertEqual(a["algorithmVersion"], si.ALGORITHM_VERSION)
        self.assertEqual(a["finalizedWeeks"], [1, 2])
        self.assertEqual(a["cutoffWeek"], 2)
        c = si.season_contract(snap, snap.seasons[0], cutoff_week=1)
        self.assertEqual(c["finalizedWeeks"], [1])
        self.assertNotEqual(c["scoreHash"], a["scoreHash"])

    def test_an_unfinished_week_is_never_used(self) -> None:
        weeks = dict(self.WEEKS)
        weeks[3] = _week([(1, 1, 5.0), (2, 1, None), (3, 2, 1.0), (4, 2, None)])
        snap = _snap(median=0, records={i: (1, 1, 0) for i in range(1, 5)}, weeks=weeks)
        snap.seasons[0].league["settings"]["last_scored_leg"] = 2
        c = si.season_contract(snap, snap.seasons[0])
        self.assertNotIn(3, c["finalizedWeeks"])


class OrphanRosterTests(unittest.TestCase):
    def test_an_orphan_roster_is_a_real_participant(self) -> None:
        # Roster 4 has no owner that season.  Its games are real: o3's win
        # over it must count, and it must be a possible opponent for everyone.
        weeks = {
            1: _week([(1, 1, 120.0), (2, 1, 100.0), (3, 2, 90.0), (4, 2, 80.0)]),
            2: _week([(1, 1, 70.0), (4, 1, 130.0), (2, 2, 110.0), (3, 2, 60.0)]),
        }
        snap = _snap(median=0, records={i: (1, 1, 0) for i in range(1, 5)}, weeks=weeks)
        snap.seasons[0].rosters[3]["owner_id"] = None
        snap = _snap_with_registry(snap)
        c = si.season_contract(snap, snap.seasons[0])
        self.assertEqual(len(c["teams"]), 4)
        orphan = next(t for t in c["teams"] if t["orphanRoster"])
        self.assertEqual(
            (orphan["teamKey"], orphan["ownerId"], orphan["rosterId"]), ("roster:4", None, 4)
        )
        o3 = next(t for t in c["teams"] if t["ownerId"] == "o3")
        self.assertEqual(o3["games"], 2)
        self.assertAlmostEqual(sum(t["scheduleImpact"] for t in c["teams"]), 0.0, places=12)
        self.assertAlmostEqual(sum(t["actualH2HCredits"] for t in c["teams"]), 4.0, places=12)


def _snap_with_registry(snap):
    season = snap.seasons[0]
    return PublicLeagueSnapshot(
        root_league_id=snap.root_league_id,
        generated_at=snap.generated_at,
        seasons=[season],
        managers=build_manager_registry(
            [{"league": season.league, "users": season.users, "rosters": season.rosters}]
        ),
    )


class ReviewRegressionTests(unittest.TestCase):
    """Independent review of #1531 (REJECT) -- each must-fix pinned."""

    def test_a_broken_matchup_is_partial_not_a_bye(self) -> None:
        # Roster 2's partner row is missing from matchup 1 (singleton group).
        weeks = {1: _week([(1, 1, 120.0), (3, 2, 90.0), (4, 2, 80.0)])}
        weeks[1].append({"roster_id": 2, "matchup_id": 9, "points": 100.0})
        snap = _snap(median=0, records={i: (0, 0, 0) for i in range(1, 5)}, weeks=weeks)
        c = si.season_contract(snap, snap.seasons[0])
        self.assertEqual(c["state"], si.STATE_PARTIAL)
        self.assertTrue(any(i.endswith("unpaired:o1") for i in c["issues"]))
        self.assertIn("o1", c["teamsWithoutEvaluableGames"])

    def test_a_three_team_matchup_is_unsupported(self) -> None:
        weeks = {1: _week([(1, 1, 120.0), (2, 1, 100.0), (3, 1, 90.0), (4, 2, 80.0)])}
        snap = _snap(median=0, records={i: (0, 0, 0) for i in range(1, 5)}, weeks=weeks)
        c = si.season_contract(snap, snap.seasons[0])
        self.assertEqual(c["state"], si.STATE_UNSUPPORTED)
        self.assertEqual(c["teams"], [])

    def test_a_real_bye_is_recorded_per_team(self) -> None:
        weeks = {1: _week([(1, 1, 120.0), (2, 1, 100.0), (3, 2, 90.0), (4, 2, 80.0)])}
        weeks[2] = _week([(1, 1, 70.0), (3, 1, 130.0)]) + [
            {"roster_id": 2, "matchup_id": None, "points": 110.0},
            {"roster_id": 4, "matchup_id": None, "points": 60.0},
        ]
        snap = _snap(median=0, records={i: (0, 0, 0) for i in range(1, 5)}, weeks=weeks)
        c = si.season_contract(snap, snap.seasons[0])
        self.assertEqual(c["state"], si.STATE_COMPLETE)
        o2 = next(t for t in c["teams"] if t["ownerId"] == "o2")
        self.assertEqual((o2["games"], o2["byeWeeks"]), (1, [2]))

    def test_an_impossible_median_record_is_never_published(self) -> None:
        # The reviewer's probe: host records whose H2H half disagrees with the
        # scores produced a "complete" median record of -1 wins.
        snap = _snap(
            median=1,
            records={1: (1, 3, 0), 2: (2, 2, 0), 3: (3, 1, 0), 4: (2, 2, 0)},
            weeks=AdapterTests.WEEKS,
        )
        c = si.season_contract(snap, snap.seasons[0])
        for t in c["teams"]:
            m = t["medianComponent"]
            if m["state"] == "complete":
                self.assertTrue(all(m[k] >= 0 for k in ("wins", "losses", "ties")))
        o1 = next(t for t in c["teams"] if t["ownerId"] == "o1")
        self.assertEqual(o1["medianComponent"]["reason"], "official_record_inconsistent")

    def test_the_median_component_matches_the_scores_when_published(self) -> None:
        # Fully consistent host records: H2H + score-derived median.
        snap = _snap(
            median=1,
            records={1: (2, 2, 0), 2: (3, 1, 0), 3: (3, 1, 0), 4: (0, 4, 0)},
            weeks=AdapterTests.WEEKS,
        )
        c = si.season_contract(snap, snap.seasons[0])
        got = {t["ownerId"]: t["medianComponent"] for t in c["teams"]}
        self.assertEqual(got["o2"], {"state": "complete", "wins": 2, "losses": 0, "ties": 0})
        self.assertTrue(all(m["state"] == "complete" for m in got.values()))

    def test_generation_id_covers_the_official_record(self) -> None:
        a = _snap(median=0, records={i: (1, 1, 0) for i in range(1, 5)}, weeks=AdapterTests.WEEKS)
        b = _snap(median=0, records={i: (2, 0, 0) for i in range(1, 5)}, weeks=AdapterTests.WEEKS)
        ga = si.season_contract(a, a.seasons[0])["generationId"]
        gb = si.season_contract(b, b.seasons[0])["generationId"]
        self.assertNotEqual(ga, gb)

    def test_public_block_carries_no_weekly_rows(self) -> None:
        snap = _snap(
            median=0, records={i: (1, 1, 0) for i in range(1, 5)}, weeks=AdapterTests.WEEKS
        )
        block = si.build_block(snap)
        self.assertIsNone(block["bySeason"]["2026"]["weeks"])

    def test_a_schedule_failure_does_not_take_down_the_luck_section(self) -> None:
        from unittest import mock

        from src.public_league import luck

        snap = _snap(
            median=0, records={i: (1, 1, 0) for i in range(1, 5)}, weeks=AdapterTests.WEEKS
        )
        with mock.patch.object(si, "build_block", side_effect=RuntimeError("boom")):
            sec = luck.build_section(snap)
        self.assertEqual(sec["scheduleImpact"]["state"], "failed")
        self.assertTrue(sec["byOwnerSeason"])
