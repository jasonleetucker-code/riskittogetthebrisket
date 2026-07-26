"""Crawler behavior: dedupe, caps, budget resumability, co-owners,
failed-member isolation.  All against FakeSleeper — no network."""

from __future__ import annotations

from src.intel import crawler
from tests.intel.conftest import (
    DAY_MS,
    NOW_MS,
    FakeSleeper,
    fill_traded_picks,
    leagues_url,
    make_league,
    make_roster,
    make_trade_tx,
    make_waiver_tx,
    rosters_url,
    state_url,
    traded_url,
    tx_url,
    users_url,
)

SEASON = "2026"


def _base_responses() -> dict:
    return {state_url(): {"week": 1, "season_type": "off", "league_season": SEASON}}


def _crawl(members, responses, prev_state=None, budget=900, fill_traded=True):
    if fill_traded:
        fill_traded_picks(responses)
    fake = FakeSleeper(responses)
    result = crawler.crawl(
        members,
        SEASON,
        prev_state,
        budget=budget,
        sleep_s=0,
        http_get=fake,
        now_ms=NOW_MS,
    )
    return result, fake


class TestLeagueDiscovery:
    def test_league_dedupe_across_members(self):
        shared = make_league("L1", "Shared League")
        responses = _base_responses()
        responses[leagues_url("A", SEASON)] = [shared, make_league("L2")]
        responses[leagues_url("B", SEASON)] = [shared]
        responses[rosters_url("L1")] = [make_roster(1, "A"), make_roster(2, "B")]
        responses[rosters_url("L2")] = [make_roster(1, "A")]
        responses[tx_url("L1", 1)] = []
        responses[tx_url("L2", 1)] = []

        result, fake = _crawl(["A", "B"], responses)

        assert set(result.state["leagues"].keys()) == {"L1", "L2"}
        assert result.state["leagues"]["L1"]["memberOwnerIds"] == ["A", "B"]
        # The shared league is fetched exactly once despite two members.
        assert fake.count(rosters_url("L1")) == 1
        assert fake.count(tx_url("L1", 1)) == 1
        # League metadata came free with the leagues-list call.
        assert result.state["leagues"]["L1"]["name"] == "Shared League"
        assert result.state["leagues"]["L1"]["totalRosters"] == 12

    def test_per_member_cap_sets_truncated_flag(self):
        many = [make_league(f"L{i}") for i in range(30)]
        responses = _base_responses()
        responses[leagues_url("A", SEASON)] = many
        for i in range(30):
            responses[rosters_url(f"L{i}")] = [make_roster(1, "A")]
            responses[tx_url(f"L{i}", 1)] = []

        result, _fake = _crawl(["A"], responses)

        entry = result.state["members"]["A"]
        assert len(entry["leagues"]) == crawler.PER_MEMBER_LEAGUE_CAP == 25
        assert entry["truncated"] is True
        assert len(result.state["leagues"]) == 25

    def test_under_cap_not_truncated(self):
        responses = _base_responses()
        responses[leagues_url("A", SEASON)] = [make_league("L1")]
        responses[rosters_url("L1")] = [make_roster(1, "A")]
        responses[tx_url("L1", 1)] = []

        result, _fake = _crawl(["A"], responses)
        assert result.state["members"]["A"]["truncated"] is False


class TestBudgetResumability:
    def _three_member_responses(self):
        responses = _base_responses()
        for oid, lid in (("A", "LA"), ("B", "LB"), ("C", "LC")):
            responses[leagues_url(oid, SEASON)] = [make_league(lid)]
            responses[rosters_url(lid)] = [make_roster(1, oid, players=["p1"])]
            responses[traded_url(lid)] = []
            responses[tx_url(lid, 1)] = [
                make_waiver_tx(f"t-{lid}", NOW_MS - DAY_MS, 1, add_player=f"p-{lid}")
            ]
        return responses

    def test_budget_exhaustion_mid_run_is_resumable(self):
        responses = self._three_member_responses()

        # Budget 7: state(1) + 3 member lists + rosters/traded-picks/tx
        # for the first league only → leagues LB/LC must land in the
        # cursor.
        result, _fake = _crawl(["A", "B", "C"], responses, budget=7)
        assert result.budget_exhausted is True
        assert result.completed is False
        assert result.calls_used == 7
        cursor = result.state["cursor"]
        assert cursor["pendingLeagues"] == ["LB", "LC"]
        assert result.new_event_count == 1  # only LA processed

        # Resume: run 2 with a full budget picks up the pending
        # leagues and finishes everything.
        result2, fake2 = _crawl(["A", "B", "C"], responses, prev_state=result.state)
        assert result2.budget_exhausted is False
        assert result2.state["cursor"] is None
        asset_ids = {e["assetId"] for e in result2.state["events"]}
        assert asset_ids == {"p-LA", "p-LB", "p-LC"}
        # LA's already-recorded event is not duplicated on the resume.
        assert len([e for e in result2.state["events"] if e["assetId"] == "p-LA"]) == 1

    def test_member_phase_exhaustion_round_robins(self):
        responses = self._three_member_responses()

        # Budget 2: state(1) + member A only → B and C pend.
        result, _fake = _crawl(["A", "B", "C"], responses, budget=2)
        assert result.state["cursor"]["pendingMembers"] == ["B", "C"]

        # Run 2 processes the pending members FIRST (round-robin).
        fake2 = FakeSleeper(responses)
        crawler.crawl(
            ["A", "B", "C"],
            SEASON,
            result.state,
            budget=3,
            sleep_s=0,
            http_get=fake2,
            now_ms=NOW_MS,
        )
        member_calls = [c for c in fake2.calls if "/user/" in c]
        assert member_calls == [leagues_url("B", SEASON), leagues_url("C", SEASON)]


class TestOwnerMatching:
    def test_co_owner_matching(self):
        responses = _base_responses()
        responses[leagues_url("A", SEASON)] = [make_league("L1")]
        # Roster 1's primary owner is a stranger; pool member A is a
        # co-owner.  Roster 2 is a stranger entirely.
        responses[rosters_url("L1")] = [
            make_roster(1, "stranger1", players=["p9"], co_owners=["A"]),
            make_roster(2, "stranger2", players=[]),
        ]
        responses[tx_url("L1", 1)] = [
            make_trade_tx("t1", NOW_MS - DAY_MS, adds={"p42": 1}, drops={"p42": 2})
        ]

        result, _fake = _crawl(["A"], responses)

        events = result.state["events"]
        # Only the co-owned side attributes to the pool: A adds p42;
        # stranger2's drop is not a pool event.
        assert len(events) == 1
        assert events[0]["ownerId"] == "A"
        assert events[0]["action"] == "add"
        # Holdings credit the co-owner too.
        holdings = result.state["leagues"]["L1"]["holdings"]
        assert set(holdings) == {"A"}
        assert "p9" in holdings["A"]

    def test_orphaned_rosters_skipped(self):
        responses = _base_responses()
        responses[leagues_url("A", SEASON)] = [make_league("L1")]
        responses[rosters_url("L1")] = [
            make_roster(1, None, players=["px"]),  # orphaned
            make_roster(2, "A", players=["py"]),
        ]
        responses[tx_url("L1", 1)] = [
            make_waiver_tx("t1", NOW_MS - DAY_MS, 1, add_player="p1"),  # orphan's move
            make_waiver_tx("t2", NOW_MS - DAY_MS, 2, add_player="p2"),
        ]

        result, _fake = _crawl(["A"], responses)
        assert {e["ownerId"] for e in result.state["events"]} == {"A"}
        assert {e["assetId"] for e in result.state["events"]} == {"p2"}


class TestFailedMemberIsolation:
    def test_failed_member_keeps_previous_data_and_others_proceed(self):
        # Run 1: A and B both healthy.
        responses = _base_responses()
        responses[leagues_url("A", SEASON)] = [make_league("LA")]
        responses[leagues_url("B", SEASON)] = [make_league("LB")]
        responses[rosters_url("LA")] = [make_roster(1, "A", players=["pa"])]
        responses[rosters_url("LB")] = [make_roster(1, "B", players=["pb"])]
        responses[tx_url("LA", 1)] = [make_waiver_tx("ta", NOW_MS - DAY_MS, 1, add_player="x1")]
        responses[tx_url("LB", 1)] = []
        result1, _ = _crawl(["A", "B"], responses)
        assert result1.failed_member_ids == []

        # Run 2: A's league-list call fails (missing → None); B gains
        # a new transaction.
        responses2 = _base_responses()
        responses2[leagues_url("B", SEASON)] = [make_league("LB")]
        responses2[rosters_url("LB")] = [make_roster(1, "B", players=["pb"])]
        responses2[tx_url("LB", 1)] = [make_waiver_tx("tb", NOW_MS - DAY_MS, 1, add_player="x2")]
        result2, _ = _crawl(["A", "B"], responses2, prev_state=result1.state)

        assert result2.failed_member_ids == ["A"]
        # A's previous league membership + events survive.
        assert result2.state["members"]["A"]["leagues"] == ["LA"]
        assert result2.state["members"]["A"]["lastError"]
        assert "LA" in result2.state["leagues"]
        assert any(e["assetId"] == "x1" for e in result2.state["events"])
        # B still crawled fine.
        assert any(e["assetId"] == "x2" for e in result2.state["events"])

    def test_crawl_never_raises_on_total_sleeper_outage(self):
        result, _ = _crawl(["A", "B"], {})  # every call returns None
        assert sorted(result.failed_member_ids) == ["A", "B"]
        assert result.state["events"] == []


class TestReconciliation:
    def _two_member_state(self):
        responses = _base_responses()
        responses[leagues_url("A", SEASON)] = [make_league("LA")]
        responses[leagues_url("B", SEASON)] = [make_league("LB")]
        responses[rosters_url("LA")] = [make_roster(1, "A", players=["pa"])]
        responses[rosters_url("LB")] = [make_roster(1, "B", players=["pb"])]
        responses[tx_url("LA", 1)] = [make_waiver_tx("ta", NOW_MS - DAY_MS, 1, add_player="xa")]
        responses[tx_url("LB", 1)] = [make_waiver_tx("tb", NOW_MS - DAY_MS, 1, add_player="xb")]
        result, _ = _crawl(["A", "B"], responses)
        return result.state, responses

    def test_departed_member_is_dropped_with_their_leagues_and_events(self):
        state, responses = self._two_member_state()
        assert set(state["members"]) == {"A", "B"}

        # B left the seed league → pool is now just A.
        result2, _ = _crawl(["A"], responses, prev_state=state)
        assert set(result2.state["members"]) == {"A"}
        assert set(result2.state["leagues"]) == {"LA"}
        assert {e["assetId"] for e in result2.state["events"]} == {"xa"}

    def test_league_a_member_left_is_dropped(self):
        responses = _base_responses()
        responses[leagues_url("A", SEASON)] = [make_league("L1"), make_league("L2")]
        responses[rosters_url("L1")] = [make_roster(1, "A", players=["p1"])]
        responses[rosters_url("L2")] = [make_roster(1, "A", players=["p2"])]
        responses[tx_url("L1", 1)] = [make_waiver_tx("t1", NOW_MS - DAY_MS, 1, add_player="x1")]
        responses[tx_url("L2", 1)] = [make_waiver_tx("t2", NOW_MS - DAY_MS, 1, add_player="x2")]
        result1, _ = _crawl(["A"], responses)
        assert set(result1.state["leagues"]) == {"L1", "L2"}

        # A left L2: their fresh league list only has L1.
        responses[leagues_url("A", SEASON)] = [make_league("L1")]
        result2, _ = _crawl(["A"], responses, prev_state=result1.state)
        assert set(result2.state["leagues"]) == {"L1"}
        assert {e["assetId"] for e in result2.state["events"]} == {"x1"}
        assert result2.state["leagues"]["L1"]["memberOwnerIds"] == ["A"]

    def test_failed_member_fetch_never_triggers_removal(self):
        state, responses = self._two_member_state()

        # B's league-list call fails this run — preserve-on-failure:
        # B, LB, and B's events all survive.
        del responses[leagues_url("B", SEASON)]
        result2, _ = _crawl(["A", "B"], responses, prev_state=state)
        assert result2.failed_member_ids == ["B"]
        assert set(result2.state["members"]) == {"A", "B"}
        assert set(result2.state["leagues"]) == {"LA", "LB"}
        assert {e["assetId"] for e in result2.state["events"]} == {"xa", "xb"}
        assert "pb" in result2.state["leagues"]["LB"]["holdings"]["B"]

    def test_member_owner_ids_track_current_membership(self):
        shared = make_league("L1")
        responses = _base_responses()
        responses[leagues_url("A", SEASON)] = [shared]
        responses[leagues_url("B", SEASON)] = [shared]
        responses[rosters_url("L1")] = [make_roster(1, "A"), make_roster(2, "B")]
        responses[tx_url("L1", 1)] = []
        result1, _ = _crawl(["A", "B"], responses)
        assert result1.state["leagues"]["L1"]["memberOwnerIds"] == ["A", "B"]

        # B leaves the shared league (still in the pool).
        responses[leagues_url("B", SEASON)] = []
        result2, _ = _crawl(["A", "B"], responses, prev_state=result1.state)
        assert result2.state["leagues"]["L1"]["memberOwnerIds"] == ["A"]


class TestPickHoldings:
    def test_pick_holdings_defaults_and_traded_diffs(self):
        # Rosters 1 + 2, 2 rounds, seasons now..now+2.  One traded
        # pick moves roster 2's first-season R1 to roster 1.
        traded = [{"season": "2026", "round": 1, "roster_id": 2, "owner_id": 1}]
        out = crawler._pick_holdings(["1", "2"], traded, draft_rounds=2, now_year=2026)
        # Roster 1: own 6 defaults + acquired 2026 R1.
        assert out["1"].count("pick:2026:1") == 2
        assert "pick:2026:1" not in out["2"]
        assert "pick:2026:2" in out["2"]
        assert len(out["1"]) == 7
        assert len(out["2"]) == 5
        # Asset naming matches _events_from_tx's pick ids exactly.
        tx = make_trade_tx(
            "t1",
            NOW_MS,
            draft_picks=[
                {
                    "season": "2026",
                    "round": 1,
                    "roster_id": 2,
                    "owner_id": 1,
                    "previous_owner_id": 2,
                }
            ],
        )
        events = crawler._events_from_tx(tx, "L1", 1, {"1": "A", "2": "B"}, {"A", "B"}, set())
        assert {e["assetId"] for e in events} == {"pick:2026:1"}
        assert all(e["assetId"] in out["1"] for e in events)

    def test_draft_rounds_clamped_and_defaulted(self):
        out = crawler._pick_holdings(["1"], [], draft_rounds=0, now_year=2026)
        # Default 4 rounds × 3 years.
        assert len(out["1"]) == 12
        out6 = crawler._pick_holdings(["1"], [], draft_rounds=99, now_year=2026)
        assert len(out6["1"]) == 18  # clamped to 6 rounds

    def test_crawl_folds_pick_holdings_into_member_holdings(self):
        from datetime import datetime, timezone

        from src.intel import aggregate

        now_year = datetime.fromtimestamp(NOW_MS / 1000, tz=timezone.utc).year
        league = make_league("L1")
        league["settings"] = {"draft_rounds": 2}
        responses = _base_responses()
        responses[leagues_url("A", SEASON)] = [league]
        responses[rosters_url("L1")] = [
            make_roster(1, "A", players=["p9"]),
            make_roster(2, "stranger"),
        ]
        # The stranger traded their first-year R1 to pool member A.
        responses[traded_url("L1")] = [
            {"season": str(now_year), "round": 1, "roster_id": 2, "owner_id": 1}
        ]
        responses[tx_url("L1", 1)] = []

        result, fake = _crawl(["A"], responses)
        assert fake.count(traded_url("L1")) == 1
        holdings = result.state["leagues"]["L1"]["holdings"]
        # Only the pool member carries holdings; players + picks fold
        # into the SAME structure.
        assert set(holdings) == {"A"}
        assert "p9" in holdings["A"]
        assert holdings["A"].count(f"pick:{now_year}:1") == 2  # own + acquired
        assert f"pick:{now_year}:2" in holdings["A"]

        # Drill-down join: the pick asset now has a real held count.
        exposure = aggregate.build_member_exposure(
            result.state["events"],
            aggregate.holdings_from_state(result.state),
            f"pick:{now_year}:1",
            NOW_MS,
        )
        assert exposure[0]["ownerId"] == "A"
        assert exposure[0]["heldLeagueCount"] == 1

    def test_multiple_same_round_picks_produce_distinct_events(self):
        # One trade sends manager A TWO 2027 2nds (different original
        # roster slots).  The grouped assetId is identical, so the
        # event ids must carry the original-roster identity or the
        # dedupe collapses them and buys/sells undercount.
        tx = make_trade_tx(
            "t1",
            NOW_MS,
            draft_picks=[
                {
                    "season": "2027",
                    "round": 2,
                    "roster_id": 2,
                    "owner_id": 1,
                    "previous_owner_id": 2,
                },
                {
                    "season": "2027",
                    "round": 2,
                    "roster_id": 3,
                    "owner_id": 1,
                    "previous_owner_id": 2,
                },
            ],
        )
        events = crawler._events_from_tx(tx, "L1", 1, {"1": "A", "2": "B"}, {"A", "B"}, set())
        adds = [e for e in events if e["action"] == "add"]
        drops = [e for e in events if e["action"] == "drop"]
        assert len(adds) == 2  # both picks counted, not collapsed
        assert len(drops) == 2
        # Grouped asset id preserved for aggregation…
        assert {e["assetId"] for e in events} == {"pick:2027:2"}
        # …while the event ids stay distinct (original-roster suffix).
        assert len({e["eventId"] for e in events}) == 4

    def test_traded_picks_failure_never_fabricates_defaults(self):
        from datetime import datetime, timezone

        now_year = datetime.fromtimestamp(NOW_MS / 1000, tz=timezone.utc).year
        league = make_league("L1")
        league["settings"] = {"draft_rounds": 1}
        responses = _base_responses()
        responses[leagues_url("A", SEASON)] = [league]
        responses[rosters_url("L1")] = [
            make_roster(1, "A", players=["p9"]),
            make_roster(2, "stranger"),
        ]
        responses[tx_url("L1", 1)] = []

        # Phase 1: first-ever crawl with a FAILING traded_picks fetch
        # (url missing → None).  No pick holdings may be fabricated,
        # and the league stays in the retry cursor so pick data
        # arrives promptly.
        result1, _ = _crawl(["A"], responses, fill_traded=False)
        h1 = result1.state["leagues"]["L1"]["holdings"]
        assert not any(a.startswith("pick:") for a in h1.get("A", []))
        assert "traded_picks" in (result1.state["leagues"]["L1"]["lastError"] or "")
        assert result1.state["cursor"]["pendingLeagues"] == ["L1"]
        assert result1.completed is False

        # Phase 2: traded_picks succeeds WITH a diff (stranger's R1 →
        # A) — real ownership recorded, retry cleared.
        responses[traded_url("L1")] = [
            {"season": str(now_year), "round": 1, "roster_id": 2, "owner_id": 1}
        ]
        result2, _ = _crawl(["A"], responses, prev_state=result1.state, fill_traded=False)
        h2 = result2.state["leagues"]["L1"]["holdings"]
        assert h2["A"].count(f"pick:{now_year}:1") == 2  # own + acquired
        assert result2.state["leagues"]["L1"]["pickHoldingsAt"]
        assert result2.state["cursor"] is None

        # Phase 3: traded_picks fails again — the PRIOR (correct)
        # traded ownership is preserved, NOT reset to defaults (which
        # would show only 1 first-rounder), and no retry is needed
        # because a good pick snapshot exists.
        del responses[traded_url("L1")]
        result3, _ = _crawl(["A"], responses, prev_state=result2.state, fill_traded=False)
        h3 = result3.state["leagues"]["L1"]["holdings"]
        assert h3["A"].count(f"pick:{now_year}:1") == 2  # preserved, not defaults
        assert "traded_picks" in (result3.state["leagues"]["L1"]["lastError"] or "")
        assert result3.state["cursor"] is None
        assert result3.completed is True


class TestSeedCollection:
    def test_collect_seed_members_includes_co_owners_and_skips_orphans(self):
        responses = {
            rosters_url("SEED"): [
                make_roster(1, "A", co_owners=["A2"]),
                make_roster(2, "B"),
                make_roster(3, None),  # orphaned — skipped
            ],
            users_url("SEED"): [
                {"user_id": "A", "display_name": "Alice"},
                {"user_id": "B", "display_name": "Bob"},
                {"user_id": "Z", "display_name": "NotInLeaguePool"},
            ],
        }
        fake = FakeSleeper(responses)
        member_ids, names = crawler.collect_seed_members("SEED", http_get=fake)
        assert member_ids == ["A", "A2", "B"]
        assert names == {"A": "Alice", "B": "Bob"}
