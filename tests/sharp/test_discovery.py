"""Discovery graph: outward BFS, and the seed-vs-signal separation.

The central case is :class:`TestDiscoveryIsNotSignalEligibility` — the
shipped seed (The Megalabowl) is a REDRAFT league, so a filter that
gated discovery on dynasty-eligibility would discard it and the graph
would never start.
"""

from __future__ import annotations

import json

import pytest

from src.intel import ledger
from src.sharp import discovery

BASE = discovery.SLEEPER_BASE


class FakeSleeper:
    """url → payload map with a call log.  No network anywhere."""

    def __init__(self, responses=None):
        self.responses = dict(responses or {})
        self.calls: list[str] = []

    def __call__(self, url):
        self.calls.append(url)
        return self.responses.get(url)


def league(league_id, type_=2, best_ball=0, rosters=12, name=None, season="2026"):
    return {
        "league_id": league_id,
        "name": name or f"League {league_id}",
        "season": season,
        "total_rosters": rosters,
        "settings": {"type": type_, "best_ball": best_ball},
    }


def user(uid, username=None):
    return {"user_id": uid, "username": username or f"u{uid}", "display_name": f"U{uid}"}


@pytest.fixture()
def db_path(tmp_path, monkeypatch):
    from src.intel import store

    monkeypatch.setattr(store, "DATA_DIR", tmp_path / "intel")
    ledger.reset_setup_cache()
    yield tmp_path / "intel" / ledger.LEDGER_FILENAME
    ledger.reset_setup_cache()


def seeds(seed_leagues=None, seed_users=None, **traversal):
    trav = {
        "maxGenerations": 4,
        "seasons": ["2026"],
        "perUserLeagueCap": 40,
        "maxLeagueRosters": 32,
        "minLeagueRosters": 6,
        "callBudgetPerRun": 500,
        "sleepSecondsBetweenCalls": 0,
    }
    trav.update(traversal)
    return {
        "seedLeagues": [{"leagueId": lid} for lid in (seed_leagues or [])],
        "seedUsers": [{"userId": uid} for uid in (seed_users or [])],
        "traversal": trav,
        "limits": {"maxUsersPerRun": 20000, "maxLeaguesPerRun": 5000},
    }


class TestDiscoveryIsNotSignalEligibility:
    """A redraft seed must still introduce us to its managers."""

    def test_redraft_seed_league_is_traversed_for_members(self, db_path):
        http = FakeSleeper(
            {
                # The shipped seed shape: redraft (type 0).
                f"{BASE}/league/MEGA/users": [user("u1"), user("u2")],
                f"{BASE}/user/u1/leagues/nfl/2026": [league("D1", type_=2)],
                f"{BASE}/user/u2/leagues/nfl/2026": [league("D2", type_=2)],
                f"{BASE}/league/D1/users": [user("u3")],
                f"{BASE}/league/D2/users": [user("u4")],
                f"{BASE}/user/u3/leagues/nfl/2026": [],
                f"{BASE}/user/u4/leagues/nfl/2026": [],
            }
        )
        res = discovery.discover(
            http_get=http, seeds=seeds(seed_leagues=["MEGA"]), ledger_path=db_path
        )
        assert res.users_discovered == 4, "a redraft seed must still yield its managers"
        assert f"{BASE}/league/MEGA/users" in http.calls

    def test_redraft_league_is_recorded_but_not_signal_eligible(self, db_path):
        http = FakeSleeper(
            {
                f"{BASE}/user/u1/leagues/nfl/2026": [
                    league("REDRAFT", type_=0),
                    league("DYN", type_=2),
                ],
                f"{BASE}/league/REDRAFT/users": [],
                f"{BASE}/league/DYN/users": [],
            }
        )
        discovery.discover(http_get=http, seeds=seeds(seed_users=["u1"]), ledger_path=db_path)
        eligible = discovery.signal_eligible_league_ids(ledger_path=db_path)
        assert "DYN" in eligible
        assert "REDRAFT" not in eligible, "redraft trades must never feed the dynasty board"

        # …but it IS stored, because it earned its place by introducing managers.
        conn = ledger.connect(db_path)
        try:
            ids = {r["league_id"] for r in conn.execute("SELECT league_id FROM leagues").fetchall()}
        finally:
            conn.close()
        assert {"DYN", "REDRAFT"} <= ids

    def test_best_ball_is_discovery_only(self, db_path):
        http = FakeSleeper(
            {
                f"{BASE}/user/u1/leagues/nfl/2026": [league("BB", type_=2, best_ball=1)],
                f"{BASE}/league/BB/users": [user("u2")],
                f"{BASE}/user/u2/leagues/nfl/2026": [],
            }
        )
        res = discovery.discover(http_get=http, seeds=seeds(seed_users=["u1"]), ledger_path=db_path)
        assert discovery.signal_eligible_league_ids(ledger_path=db_path) == []
        assert res.discovery_only_leagues == 1
        assert res.excluded_from_signal == {"best_ball": 1}

    def test_exclusions_are_reported_never_silent(self, db_path):
        http = FakeSleeper(
            {
                f"{BASE}/user/u1/leagues/nfl/2026": [
                    league("R1", type_=0),
                    league("R2", type_=0),
                    league("D1", type_=2),
                ],
                f"{BASE}/league/R1/users": [],
                f"{BASE}/league/R2/users": [],
                f"{BASE}/league/D1/users": [],
            }
        )
        res = discovery.discover(http_get=http, seeds=seeds(seed_users=["u1"]), ledger_path=db_path)
        assert res.excluded_from_signal == {"redraft": 2}
        assert res.signal_eligible_leagues == 1


class TestSpiderwebExpansion:
    def test_traverses_multiple_generations(self, db_path):
        """league -> members -> their leagues -> those members."""
        http = FakeSleeper(
            {
                f"{BASE}/league/L0/users": [user("u1")],
                f"{BASE}/user/u1/leagues/nfl/2026": [league("L1")],
                f"{BASE}/league/L1/users": [user("u2")],
                f"{BASE}/user/u2/leagues/nfl/2026": [league("L2")],
                f"{BASE}/league/L2/users": [user("u3")],
                f"{BASE}/user/u3/leagues/nfl/2026": [],
            }
        )
        res = discovery.discover(
            http_get=http, seeds=seeds(seed_leagues=["L0"]), ledger_path=db_path
        )
        assert res.users_discovered == 3
        assert res.leagues_discovered == 3

    def test_boundary_generation_users_are_known_even_though_unexpanded(self, db_path):
        """A manager found at the generation edge is fully recorded and
        scoreable — we just have not walked THEIR leagues yet.  Counting
        only expanded users would undercount the cohort."""
        http = FakeSleeper(
            {
                f"{BASE}/league/L0/users": [user("u1")],
                f"{BASE}/user/u1/leagues/nfl/2026": [league("L1")],
                f"{BASE}/league/L1/users": [user("u2")],
                f"{BASE}/user/u2/leagues/nfl/2026": [],
            }
        )
        res = discovery.discover(
            http_get=http,
            seeds=seeds(seed_leagues=["L0"], maxGenerations=2),
            ledger_path=db_path,
        )
        assert res.users_discovered == 2
        assert res.users_expanded < res.users_discovered

        # The unexpanded manager is still persisted, so the Sharp Score
        # can evaluate them without another crawl.
        conn = ledger.connect(db_path)
        try:
            ids = {
                r["user_id"] for r in conn.execute("SELECT user_id FROM sleeper_users").fetchall()
            }
        finally:
            conn.close()
        assert {"u1", "u2"} <= ids

    def test_generation_cap_stops_expansion(self, db_path):
        http = FakeSleeper(
            {
                f"{BASE}/league/L0/users": [user("u1")],
                f"{BASE}/user/u1/leagues/nfl/2026": [league("L1")],
                f"{BASE}/league/L1/users": [user("u2")],
                f"{BASE}/user/u2/leagues/nfl/2026": [league("L2")],
                f"{BASE}/league/L2/users": [user("u3")],
            }
        )
        res = discovery.discover(
            http_get=http,
            seeds=seeds(seed_leagues=["L0"], maxGenerations=1),
            ledger_path=db_path,
        )
        # The cap stops EXPANSION.  Things reached at the boundary are
        # still known (and still recorded) — they are simply not walked.
        assert res.leagues_expanded == 1
        assert res.users_expanded == 1
        assert res.leagues_discovered >= res.leagues_expanded

    def test_shared_league_counted_once_not_once_per_referrer(self, db_path):
        """A league reachable via many members is ONE league.

        Counting it per referrer inflates every league statistic — the
        same double-count class this codebase exists to have stamped
        out, and it produced the incoherent `46 discovered / 738
        eligible` on the first live run.
        """
        http = FakeSleeper(
            {
                f"{BASE}/league/L0/users": [user(f"u{i}") for i in range(5)],
                # All five managers play in the SAME dynasty league.
                **{
                    f"{BASE}/user/u{i}/leagues/nfl/2026": [league("POPULAR", type_=2)]
                    for i in range(5)
                },
                f"{BASE}/league/POPULAR/users": [],
            }
        )
        res = discovery.discover(
            http_get=http, seeds=seeds(seed_leagues=["L0"]), ledger_path=db_path
        )
        assert res.leagues_discovered == 2, "L0 + POPULAR, counted once each"
        assert res.signal_eligible_leagues == 1, "POPULAR is one league, not five"

    def test_discovered_never_undercounts_expanded(self, db_path):
        """Invariant: expanded is always a subset of discovered."""
        http = FakeSleeper(
            {
                f"{BASE}/league/L0/users": [user("u1"), user("u2")],
                f"{BASE}/user/u1/leagues/nfl/2026": [league("A"), league("B")],
                f"{BASE}/user/u2/leagues/nfl/2026": [league("B"), league("C")],
                f"{BASE}/league/A/users": [],
                f"{BASE}/league/B/users": [],
                f"{BASE}/league/C/users": [],
            }
        )
        res = discovery.discover(
            http_get=http, seeds=seeds(seed_leagues=["L0"]), ledger_path=db_path
        )
        assert res.leagues_expanded <= res.leagues_discovered
        assert res.users_expanded <= res.users_discovered

    def test_shared_league_is_visited_once(self, db_path):
        """Two managers in the same league must not cost two crawls."""
        http = FakeSleeper(
            {
                f"{BASE}/league/L0/users": [user("u1"), user("u2")],
                f"{BASE}/user/u1/leagues/nfl/2026": [league("SHARED")],
                f"{BASE}/user/u2/leagues/nfl/2026": [league("SHARED")],
                f"{BASE}/league/SHARED/users": [],
            }
        )
        discovery.discover(http_get=http, seeds=seeds(seed_leagues=["L0"]), ledger_path=db_path)
        assert http.calls.count(f"{BASE}/league/SHARED/users") == 1

    def test_degenerate_league_sizes_are_skipped(self, db_path):
        http = FakeSleeper(
            {
                f"{BASE}/user/u1/leagues/nfl/2026": [
                    league("TINY", rosters=2),
                    league("HUGE", rosters=200),
                    league("GOOD", rosters=12),
                ],
                f"{BASE}/league/GOOD/users": [],
            }
        )
        res = discovery.discover(http_get=http, seeds=seeds(seed_users=["u1"]), ledger_path=db_path)
        assert res.leagues_discovered == 1


class TestBudgetAndResumability:
    def test_budget_exhaustion_leaves_a_resumable_frontier(self, db_path):
        http = FakeSleeper(
            {
                f"{BASE}/league/L0/users": [user(f"u{i}") for i in range(10)],
                **{f"{BASE}/user/u{i}/leagues/nfl/2026": [league(f"L{i}")] for i in range(10)},
            }
        )
        res = discovery.discover(
            http_get=http,
            seeds=seeds(seed_leagues=["L0"], callBudgetPerRun=3),
            ledger_path=db_path,
        )
        assert res.calls_used <= 3
        assert res.budget_exhausted is True
        assert res.frontier_users or res.frontier_leagues

    def test_fetch_failure_is_recorded_not_raised(self, db_path):
        http = FakeSleeper({f"{BASE}/league/L0/users": None})
        res = discovery.discover(
            http_get=http, seeds=seeds(seed_leagues=["L0"]), ledger_path=db_path
        )
        assert any("league_users_fetch_failed" in e for e in res.errors)

    def test_rerun_is_idempotent_against_the_ledger(self, db_path):
        http = FakeSleeper(
            {
                f"{BASE}/league/L0/users": [user("u1"), user("u2")],
                f"{BASE}/user/u1/leagues/nfl/2026": [],
                f"{BASE}/user/u2/leagues/nfl/2026": [],
            }
        )
        for _ in range(3):
            discovery.discover(http_get=http, seeds=seeds(seed_leagues=["L0"]), ledger_path=db_path)
        conn = ledger.connect(db_path)
        try:
            assert conn.execute("SELECT COUNT(*) c FROM sleeper_users").fetchone()["c"] == 2
            assert conn.execute("SELECT COUNT(*) c FROM league_memberships").fetchone()["c"] == 2
        finally:
            conn.close()


class TestIdentity:
    def test_users_keyed_on_stable_id_through_a_rename(self, db_path):
        first = FakeSleeper(
            {
                f"{BASE}/league/L0/users": [user("u1", username="before")],
                f"{BASE}/user/u1/leagues/nfl/2026": [],
            }
        )
        discovery.discover(http_get=first, seeds=seeds(seed_leagues=["L0"]), ledger_path=db_path)
        second = FakeSleeper(
            {
                f"{BASE}/league/L0/users": [user("u1", username="after")],
                f"{BASE}/user/u1/leagues/nfl/2026": [],
            }
        )
        discovery.discover(http_get=second, seeds=seeds(seed_leagues=["L0"]), ledger_path=db_path)

        conn = ledger.connect(db_path)
        try:
            rows = conn.execute("SELECT * FROM sleeper_users").fetchall()
        finally:
            conn.close()
        assert len(rows) == 1
        assert rows[0]["current_username"] == "after"
        assert "before" in rows[0]["username_history"]


class TestShippedSeeds:
    def test_megalabowl_is_configured_as_a_discovery_seed(self):
        cfg = discovery.load_seeds()
        ids = discovery.seed_league_ids(cfg)
        assert "872952227344678912" in ids

        entry = next(e for e in cfg["seedLeagues"] if str(e["leagueId"]) == "872952227344678912")
        assert entry.get("discoveryOnly") is True, (
            "The Megalabowl is redraft (settings.type=0) — it must be traversed for "
            "managers but never counted in the dynasty signal"
        )

    def test_owner_is_a_seed_user_so_new_leagues_join_the_graph(self):
        cfg = discovery.load_seeds()
        assert any(str(e.get("userId")) == "468418790212759552" for e in cfg.get("seedUsers") or [])

    def test_sleep_is_under_sleepers_documented_rate_ceiling(self):
        trav = discovery.load_seeds()["traversal"]
        sleep_s = float(trav["sleepSecondsBetweenCalls"])
        assert sleep_s > 0
        assert (60.0 / sleep_s) < 1000, "Sleeper documents <1000 calls/min"

    def test_add_seed_leagues_appends_and_dedupes(self, tmp_path):
        path = tmp_path / "seeds.json"
        path.write_text(json.dumps({"seedLeagues": [{"leagueId": "A"}]}), encoding="utf-8")
        assert discovery.add_seed_leagues(["A", "B", "B"], path=path) == 1
        written = json.loads(path.read_text(encoding="utf-8"))
        assert [e["leagueId"] for e in written["seedLeagues"]] == ["A", "B"]
