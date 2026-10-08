"""C9-HIST-02 / W19-F017 -- league history is the WHOLE chain, and says so.

``PUBLIC_MAX_SEASONS`` used to default to 3, so "all-time" records were a
rolling 3-season window: correct only while the league was 3 seasons old,
and the 2027 rollover would have silently dropped 2024.  The walk now
follows ``previous_league_id`` to the league's first season under a
25-season SAFETY cap, and reports how it ended (complete / truncated /
unverified) so a partial history can never pass for a complete one.
"""

from __future__ import annotations

import copy
import unittest
from unittest import mock

from src.public_league import build_public_contract, build_public_snapshot, sleeper_client
from src.public_league import snapshot_store
from tests.public_league import fixtures as fx

YEARS = ["2026", "2025", "2024", "2023", "2022"]


def _five_season_stubs() -> tuple[dict, dict]:
    """The fixture league, cloned into a five-season chain L2026 -> L2022."""
    base = fx.build_stub_client()
    src_for = {"2026": "L2025", "2025": "L2024", "2024": "L2025", "2023": "L2024", "2022": "L2025"}
    leagues = {}
    for i, year in enumerate(YEARS):
        lg = copy.deepcopy(fx.LEAGUE_2025 if src_for[year] == "L2025" else fx.LEAGUE_2024)
        lg["league_id"] = f"L{year}"
        lg["season"] = year
        lg["previous_league_id"] = f"L{YEARS[i + 1]}" if i + 1 < len(YEARS) else "0"
        leagues[f"L{year}"] = lg

    def per_league(name):
        fn = base[name]
        return lambda lid, *a: fn(src_for.get(str(lid)[1:], lid), *a)

    stubs = {
        name: per_league(name)
        for name in base
        if name.startswith("fetch_")
        and name
        not in {"fetch_league", "fetch_draft_picks", "fetch_draft_detail", "fetch_nfl_players"}
    }
    stubs["fetch_league"] = lambda lid: copy.deepcopy(leagues.get(lid))
    stubs["fetch_draft_picks"] = base["fetch_draft_picks"]
    stubs["fetch_draft_detail"] = base["fetch_draft_detail"]
    stubs["fetch_nfl_players"] = base["fetch_nfl_players"]
    return stubs, leagues


class _Patched(unittest.TestCase):
    def setUp(self) -> None:
        self.stubs, self.leagues = _five_season_stubs()
        self.fetched: list[str] = []
        real_fetch_league = self.stubs["fetch_league"]

        def counting_fetch_league(lid):
            self.fetched.append(lid)
            return real_fetch_league(lid)

        self.stubs["fetch_league"] = counting_fetch_league
        patches = [mock.patch.object(sleeper_client, n, f) for n, f in self.stubs.items()]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)


class ChainWalkTests(_Patched):
    def test_default_cap_is_a_safety_cap_not_a_window(self) -> None:
        self.assertGreaterEqual(sleeper_client.DEFAULT_PUBLIC_MAX_SEASONS, 25)

    def test_a_five_season_chain_keeps_all_five(self) -> None:
        chain, cov = sleeper_client.walk_league_chain_status("L2026")
        self.assertEqual([lg["season"] for lg in chain], YEARS)
        self.assertEqual(cov["state"], sleeper_client.CHAIN_COMPLETE)
        self.assertEqual(cov["seasonsWalked"], 5)

    def test_the_terminator_is_not_fetched(self) -> None:
        sleeper_client.walk_league_chain_status("L2026")
        self.assertNotIn("0", self.fetched)

    def test_hitting_the_cap_is_reported_as_truncated(self) -> None:
        with self.assertLogs(sleeper_client.log, level="WARNING") as logs:
            chain, cov = sleeper_client.walk_league_chain_status("L2026", max_seasons=3)
        self.assertEqual(len(chain), 3)
        self.assertEqual(cov["state"], sleeper_client.CHAIN_TRUNCATED)
        self.assertIn("TRUNCATED", "\n".join(logs.output))

    def test_a_chain_exactly_at_the_cap_is_complete(self) -> None:
        chain, cov = sleeper_client.walk_league_chain_status("L2026", max_seasons=5)
        self.assertEqual((len(chain), cov["state"]), (5, sleeper_client.CHAIN_COMPLETE))

    def test_an_unreadable_link_is_unverified_not_complete(self) -> None:
        self.leagues.pop("L2023")
        chain, cov = sleeper_client.walk_league_chain_status("L2026")
        self.assertEqual([lg["season"] for lg in chain], ["2026", "2025", "2024"])
        self.assertEqual(cov["state"], sleeper_client.CHAIN_UNVERIFIED)

    def test_a_loop_is_unverified(self) -> None:
        self.leagues["L2024"]["previous_league_id"] = "L2026"
        chain, cov = sleeper_client.walk_league_chain_status("L2026")
        self.assertEqual(len(chain), 3)
        self.assertEqual(cov["state"], sleeper_client.CHAIN_UNVERIFIED)

    def test_legacy_walk_returns_the_same_chain(self) -> None:
        self.assertEqual(len(sleeper_client.walk_league_chain("L2026")), 5)


class SnapshotAndContractTests(_Patched):
    def test_snapshot_contract_and_archives_cover_all_five_seasons(self) -> None:
        snap = build_public_snapshot("L2026", include_nfl_players=False)
        self.assertEqual(snap.season_ids, YEARS)
        self.assertEqual(snap.history_coverage["state"], "complete")

        contract = build_public_contract(snap)
        header = contract["league"]
        self.assertEqual(header["seasonsCovered"], YEARS)
        self.assertEqual(header["historyCoverage"]["state"], "complete")

        archives = contract["sections"]["archives"]
        result_seasons = {r["season"] for r in archives["seasonResults"]}
        self.assertEqual(result_seasons, set(YEARS))

    def test_coverage_survives_the_on_disk_round_trip(self) -> None:
        snap = build_public_snapshot("L2026", max_seasons=2, include_nfl_players=False)
        back = snapshot_store.snapshot_from_dict(snapshot_store.snapshot_to_dict(snap))
        self.assertEqual(back.history_coverage, snap.history_coverage)
        self.assertEqual(back.history_coverage["state"], "truncated")

    def test_a_pre_field_snapshot_reads_as_unknown_not_complete(self) -> None:
        snap = build_public_snapshot("L2026", include_nfl_players=False)
        d = snapshot_store.snapshot_to_dict(snap)
        d.pop("historyCoverage")
        self.assertIsNone(snapshot_store.snapshot_from_dict(d).history_coverage)


class DynastyGateTests(_Patched):
    """Only DYNASTY predecessors are this league's history (Sleeper
    ``settings.type`` 2).  A redraft/keeper season before the dynasty began
    is a different game type and must not enter "all-time" records."""

    def test_a_non_dynasty_predecessor_stops_the_walk_and_says_why(self) -> None:
        self.leagues["L2023"]["settings"]["type"] = 0  # redraft
        chain, cov = sleeper_client.walk_league_chain_status("L2026")
        self.assertEqual([lg["season"] for lg in chain], ["2026", "2025", "2024"])
        self.assertEqual(cov["state"], sleeper_client.CHAIN_NON_DYNASTY)
        self.assertEqual(cov["reason"], "league_type_0")
        self.assertEqual(cov["stoppedAtLeagueId"], "L2023")

    def test_an_untyped_predecessor_fails_closed(self) -> None:
        # Unknown game type is not dynasty.
        del self.leagues["L2024"]["settings"]["type"]
        chain, cov = sleeper_client.walk_league_chain_status("L2026")
        self.assertEqual(len(chain), 2)
        self.assertEqual(cov["state"], sleeper_client.CHAIN_UNVERIFIED)
        self.assertEqual(cov["reason"], "predecessor_type_unknown")

    def test_the_current_league_is_included_whatever_its_type(self) -> None:
        self.leagues["L2026"]["settings"]["type"] = 0
        chain, cov = sleeper_client.walk_league_chain_status("L2026")
        self.assertEqual(len(chain), 5)
        self.assertEqual(cov["state"], sleeper_client.CHAIN_COMPLETE)

    def test_the_snapshot_excludes_the_non_dynasty_season(self) -> None:
        self.leagues["L2022"]["settings"]["type"] = 1  # keeper
        snap = build_public_snapshot("L2026", include_nfl_players=False)
        self.assertEqual(snap.season_ids, ["2026", "2025", "2024", "2023"])
        self.assertEqual(snap.history_coverage["state"], "non_dynasty_predecessor")


class TransientFailureRecoveryTests(_Patched):
    """A Sleeper blip mid-chain must not replace a COMPLETE history with a
    shorter one: the finished seasons come back from the last snapshot, and
    the degradation is reported."""

    def _previous(self):
        prev = build_public_snapshot("L2026", include_nfl_players=False)
        self.assertEqual(prev.history_coverage["state"], "complete")
        return prev

    def test_without_a_previous_snapshot_the_history_is_short_and_unverified(self) -> None:
        self.leagues.pop("L2023")
        snap = build_public_snapshot("L2026", include_nfl_players=False)
        self.assertEqual(snap.season_ids, ["2026", "2025", "2024"])
        self.assertEqual(snap.history_coverage["state"], "unverified")
        self.assertEqual(snap.history_coverage["reason"], "predecessor_fetch_failed")

    def test_the_last_complete_history_is_kept_and_the_degradation_named(self) -> None:
        prev = self._previous()
        self.leagues.pop("L2023")  # transient: Sleeper cannot answer for it now
        snap = build_public_snapshot("L2026", include_nfl_players=False, previous=prev)

        self.assertEqual(snap.season_ids, YEARS)
        cov = snap.history_coverage
        self.assertEqual(cov["state"], "complete")
        self.assertEqual(cov["seasonsWalked"], 3)
        rec = cov["recovered"]
        self.assertTrue(rec["degraded"])
        self.assertEqual(rec["cause"], "predecessor_fetch_failed")
        self.assertEqual(rec["seasons"], ["2023", "2022"])
        self.assertEqual(rec["fromSnapshotGeneratedAt"], prev.generated_at)
        # The recovered seasons are the previous snapshot's own objects.
        self.assertIs(snap.seasons[3], prev.seasons[3])
        # The registry covers them, so their owners still resolve.
        self.assertTrue(
            any(lid == "L2023" for (lid, _rid) in snap.managers.roster_to_owner),
        )
        header = build_public_contract(snap)["league"]
        self.assertEqual(header["seasonsCovered"], YEARS)
        self.assertTrue(header["historyCoverage"]["recovered"]["degraded"])

    def test_recovery_needs_the_previous_snapshot_to_hold_that_exact_league(self) -> None:
        prev = build_public_snapshot("L2026", max_seasons=3, include_nfl_players=False)
        self.leagues.pop("L2023")
        snap = build_public_snapshot("L2026", include_nfl_players=False, previous=prev)
        self.assertEqual(snap.season_ids, ["2026", "2025", "2024"])
        self.assertEqual(snap.history_coverage["state"], "unverified")
        self.assertNotIn("recovered", snap.history_coverage)

    def test_a_non_dynasty_stop_is_never_papered_over_from_cache(self) -> None:
        prev = self._previous()
        self.leagues["L2023"]["settings"]["type"] = 0
        snap = build_public_snapshot("L2026", include_nfl_players=False, previous=prev)
        self.assertEqual(snap.season_ids, ["2026", "2025", "2024"])
        self.assertNotIn("recovered", snap.history_coverage)


class ServerPassesThePreviousSnapshotTests(unittest.TestCase):
    def test_rebuild_hands_the_cached_snapshot_for_the_same_league(self) -> None:
        import server

        saved = dict(server._public_league_cache)
        seen = {}
        cached = object()

        def builder(league_id, max_seasons=None, **kwargs):
            seen.update(kwargs)
            raise RuntimeError("stop after capturing the call")

        try:
            server._public_league_cache.update(
                {
                    "snapshot": cached,
                    "snapshot_league_id": "SAME",
                    "fetched_at": 0.0,
                    "last_failure_at": 0.0,
                    "last_failure_error": None,
                }
            )
            with mock.patch.object(server, "build_public_snapshot", builder):
                with self.assertRaises(RuntimeError):
                    server._rebuild_public_snapshot("SAME", trigger="test")
            self.assertIs(seen.get("previous"), cached)

            seen.clear()
            server._public_league_cache.update({"last_failure_at": 0.0})
            with mock.patch.object(server, "build_public_snapshot", builder):
                with self.assertRaises(RuntimeError):
                    server._rebuild_public_snapshot("OTHER", trigger="test")
            # Another league's snapshot is never offered as this one's history.
            self.assertIsNone(seen.get("previous"))
        finally:
            server._public_league_cache.clear()
            server._public_league_cache.update(saved)


if __name__ == "__main__":
    unittest.main()
