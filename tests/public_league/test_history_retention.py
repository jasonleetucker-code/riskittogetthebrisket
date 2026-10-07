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


if __name__ == "__main__":
    unittest.main()
