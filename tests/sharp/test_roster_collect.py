"""The sharp roster collection pass — attribution, slots, exclusions.

Every Sleeper call is faked. These tests are about what the collector
DOES with a payload, not about Sleeper being reachable.
"""

from __future__ import annotations

import json

import pytest

from src.intel import platform_ledger
from src.platforms.base import NormalizedLeague, NormalizedManager, NormalizedMembership
from src.sharp import roster_collect as rc
from src.sharp import roster_store as rs

NOW = 1_800_000_000_000


def league_payload(**overrides):
    base = {
        "league_id": "L1",
        "season": "2026",
        "status": "in_season",
        "total_rosters": 12,
        "previous_league_id": "L0",  # makes it >= 2 seasons old
        "settings": {"type": 2},  # dynasty
        "roster_positions": ["QB", "RB", "WR", "TE", "FLEX", "SUPER_FLEX", "K", "BN"],
        "scoring_settings": {"rec": 1.0},
    }
    base.update(overrides)
    return base


def roster_payload(roster_id="1", owner="u1", players=("4046", "6794"), **overrides):
    base = {
        "roster_id": roster_id,
        "owner_id": owner,
        "players": list(players),
        "settings": {"wins": 8, "losses": 2, "ties": 0},
    }
    base.update(overrides)
    return base


@pytest.fixture
def ledger(tmp_path):
    return tmp_path / "ledger.sqlite3"


def seed_sleeper_membership(ledger, manager_key="sleeper:u1", league_key="sleeper:L1"):
    conn = platform_ledger.ensure_platform_schema(ledger)
    try:
        platform_ledger.upsert_manager(
            NormalizedManager.build("sleeper", manager_key.split(":", 1)[1]), conn=conn
        )
        platform_ledger.upsert_league(
            NormalizedLeague.build("sleeper", league_key.split(":", 1)[1]), conn=conn
        )
        platform_ledger.upsert_membership(
            NormalizedMembership(
                platform="sleeper",
                league_key=league_key,
                manager_key=manager_key,
                roster_id="1",
            ),
            conn=conn,
        )
        conn.commit()
    finally:
        conn.close()


def fake_http(league=None, rosters=None, calls=None):
    """Fake Sleeper. Pass ``calls`` to capture the URLs requested.

    ``/players/nfl`` is answered explicitly: the collector fetches the
    directory once per run to give rostered players a display name, and
    letting that fall through to the league payload would quietly feed a
    league dict into the asset catalog.
    """
    league = league if league is not None else league_payload()
    rosters = rosters if rosters is not None else [roster_payload()]

    def _get(url):
        if calls is not None:
            calls.append(url)
        if url.endswith("/players/nfl"):
            return {"4046": {"full_name": "Justin Jefferson", "position": "WR", "team": "MIN"}}
        if url.endswith("/rosters"):
            return rosters
        return league

    return _get


class TestSleeper:
    def test_a_cohort_members_roster_is_collected(self, ledger):
        seed_sleeper_membership(ledger)
        result = rc.collect_sleeper_rosters(
            manager_keys=["sleeper:u1"],
            http_get=fake_http(),
            ledger_path=ledger,
            sleep_fn=lambda _s: None,
            now_ms=NOW,
        )
        assert result.leagues_examined == 1
        assert result.rosters_recorded == 1
        assert result.eligible_rosters == 1
        stored = rs.load_rosters(path=ledger)
        assert stored[0]["managerKey"] == "sleeper:u1"
        assert {a["canonicalAssetId"] for a in stored[0]["assets"]} == {"4046", "6794"}

    def test_non_cohort_rosters_in_the_same_league_are_ignored(self, ledger):
        seed_sleeper_membership(ledger)
        rc.collect_sleeper_rosters(
            manager_keys=["sleeper:u1"],
            http_get=fake_http(
                rosters=[
                    roster_payload(roster_id="1", owner="u1"),
                    roster_payload(roster_id="2", owner="stranger"),
                    roster_payload(roster_id="3", owner="also-not-sharp"),
                ]
            ),
            ledger_path=ledger,
            sleep_fn=lambda _s: None,
            now_ms=NOW,
        )
        stored = rs.load_rosters(path=ledger)
        assert len(stored) == 1
        assert stored[0]["sourceRosterId"] == "1"

    def test_two_sharps_in_one_league_yield_two_rosters_from_one_fetch(self, ledger):
        seed_sleeper_membership(ledger, "sleeper:u1")
        seed_sleeper_membership(ledger, "sleeper:u2")
        calls = []
        result = rc.collect_sleeper_rosters(
            manager_keys=["sleeper:u1", "sleeper:u2"],
            http_get=fake_http(
                rosters=[
                    roster_payload(roster_id="1", owner="u1"),
                    roster_payload(roster_id="2", owner="u2"),
                ],
                calls=calls,
            ),
            ledger_path=ledger,
            sleep_fn=lambda _s: None,
            now_ms=NOW,
        )
        # The cost is per LEAGUE, not per member: two calls for the one
        # league both sharps play in, however many of them are in it.
        assert len([u for u in calls if "/league/" in u]) == 2
        assert result.rosters_recorded == 2

    def test_the_player_directory_is_fetched_once_per_run_not_per_league(self, ledger):
        for i in range(1, 4):
            seed_sleeper_membership(ledger, "sleeper:u1", f"sleeper:L{i}")
        calls = []
        rc.collect_sleeper_rosters(
            manager_keys=["sleeper:u1"],
            http_get=fake_http(calls=calls),
            ledger_path=ledger,
            sleep_fn=lambda _s: None,
            now_ms=NOW,
        )
        assert len([u for u in calls if u.endswith("/players/nfl")]) == 1

    def test_a_rostered_player_outside_our_board_still_gets_a_name(self, ledger):
        """A correct percentage next to a bare Sleeper id reads as broken.

        Our board only names players inside its ranked pool, so a real
        rostered player outside it (a deep veteran, say) rendered as
        e.g. "827". The crawl hydrates ``canonical_assets`` from
        Sleeper's directory so the board can name him.
        """
        from src.sharp import roster_percentage as rp

        seed_sleeper_membership(ledger)
        rc.collect_sleeper_rosters(
            manager_keys=["sleeper:u1"],
            http_get=fake_http(rosters=[roster_payload(players=("4046",))]),
            ledger_path=ledger,
            sleep_fn=lambda _s: None,
            now_ms=NOW,
        )
        catalog = rp._catalog_metadata(ledger)
        assert catalog.get("4046", {}).get("displayName") == "Justin Jefferson"
        # And with no contract at all, the board uses it rather than the id.
        assert rp._fallback_metadata("4046", catalog)["displayName"] == "Justin Jefferson"

    def test_a_directory_failure_never_costs_a_roster(self, ledger):
        seed_sleeper_membership(ledger)

        def flaky(url):
            if url.endswith("/players/nfl"):
                raise RuntimeError("sleeper directory down")
            return fake_http()(url)

        result = rc.collect_sleeper_rosters(
            manager_keys=["sleeper:u1"],
            http_get=flaky,
            ledger_path=ledger,
            sleep_fn=lambda _s: None,
            now_ms=NOW,
        )
        assert result.eligible_rosters == 1
        assert "player_directory_unavailable" in result.errors

    def test_a_cohort_co_owner_is_credited_when_the_primary_is_not_sharp(self, ledger):
        seed_sleeper_membership(ledger, "sleeper:u1")
        rc.collect_sleeper_rosters(
            manager_keys=["sleeper:u1"],
            http_get=fake_http(
                rosters=[roster_payload(owner="stranger", co_owners=["u1"])],
            ),
            ledger_path=ledger,
            sleep_fn=lambda _s: None,
            now_ms=NOW,
        )
        stored = rs.load_rosters(path=ledger)
        assert len(stored) == 1
        assert stored[0]["managerKey"] == "sleeper:u1"

    def test_taxi_and_reserve_are_labelled_not_added_twice(self, ledger):
        """Sleeper's ``players`` is the whole roster.

        Taxi and reserve ids appear in ``players`` too, so reading the
        three arrays as separate populations would count a taxi player
        twice. They are read only to label.
        """
        seed_sleeper_membership(ledger)
        rc.collect_sleeper_rosters(
            manager_keys=["sleeper:u1"],
            http_get=fake_http(
                rosters=[
                    roster_payload(
                        players=("4046", "6794", "5849"),
                        taxi=["6794"],
                        reserve=["5849"],
                    )
                ]
            ),
            ledger_path=ledger,
            sleep_fn=lambda _s: None,
            now_ms=NOW,
        )
        stored = rs.load_rosters(path=ledger)[0]
        assert stored["assetCount"] == 3
        assert {a["canonicalAssetId"]: a["slot"] for a in stored["assets"]} == {
            "4046": "active",
            "6794": "taxi",
            "5849": "reserve",
        }

    @pytest.mark.parametrize(
        "league_overrides,expected",
        [
            ({"settings": {"type": 0}}, rc.REASON_INCOMPATIBLE_FORMAT),  # redraft
            ({"settings": {"type": 1}}, rc.REASON_INCOMPATIBLE_FORMAT),  # keeper
            (
                {"settings": {"type": 2, "best_ball": 1}},
                rc.REASON_INCOMPATIBLE_FORMAT,
            ),
            ({"previous_league_id": ""}, rc.REASON_LEAGUE_NOT_SHARP_ELIGIBLE),  # too new
            ({"settings": {}}, rc.REASON_LEAGUE_NOT_SHARP_ELIGIBLE),  # unknown type
            ({"status": "abandoned"}, rc.REASON_ABANDONED_LEAGUE),
        ],
    )
    def test_ineligible_leagues_are_recorded_with_a_reason(
        self, ledger, league_overrides, expected
    ):
        seed_sleeper_membership(ledger)
        result = rc.collect_sleeper_rosters(
            manager_keys=["sleeper:u1"],
            http_get=fake_http(league=league_payload(**league_overrides)),
            ledger_path=ledger,
            sleep_fn=lambda _s: None,
            now_ms=NOW,
        )
        assert result.eligible_rosters == 0
        assert expected in result.exclusion_reasons
        # Recorded, never discarded — the audit trail is the point.
        stored = rs.load_rosters(path=ledger)
        assert len(stored) == 1
        assert expected in stored[0]["exclusionReasons"]

    def test_an_empty_roster_is_flagged_incomplete(self, ledger):
        seed_sleeper_membership(ledger)
        result = rc.collect_sleeper_rosters(
            manager_keys=["sleeper:u1"],
            http_get=fake_http(rosters=[roster_payload(players=())]),
            ledger_path=ledger,
            sleep_fn=lambda _s: None,
            now_ms=NOW,
        )
        assert rc.REASON_INCOMPLETE_ROSTER in result.exclusion_reasons

    def test_the_budget_bounds_the_crawl(self, ledger):
        for i in range(1, 6):
            seed_sleeper_membership(ledger, "sleeper:u1", f"sleeper:L{i}")
        result = rc.collect_sleeper_rosters(
            manager_keys=["sleeper:u1"],
            http_get=fake_http(),
            budget=4,
            ledger_path=ledger,
            sleep_fn=lambda _s: None,
            now_ms=NOW,
        )
        assert result.calls_used <= 4
        assert result.budget_exhausted is True

    def test_prior_seasons_of_one_league_chain_are_superseded(self, ledger):
        """One dynasty league is ONE roster, however many seasons of it
        we have observed.

        Sleeper mints a new league_id each season and links back through
        ``previous_league_id``. Counting each id would inflate numerator
        and denominator together, and unevenly — the longest-running
        leagues are exactly the ones most likely to be sharp-eligible.
        """
        seed_sleeper_membership(ledger, "sleeper:u1", "sleeper:L2026")
        seed_sleeper_membership(ledger, "sleeper:u1", "sleeper:L2025")
        seed_sleeper_membership(ledger, "sleeper:u1", "sleeper:L2024")

        chain = {
            "L2026": league_payload(league_id="L2026", season="2026", previous_league_id="L2025"),
            "L2025": league_payload(league_id="L2025", season="2025", previous_league_id="L2024"),
            "L2024": league_payload(league_id="L2024", season="2024", previous_league_id="L2023"),
        }

        def http(url):
            league_id = url.split("/league/")[1].split("/")[0]
            if url.endswith("/rosters"):
                return [roster_payload()]
            return chain[league_id]

        result = rc.collect_sleeper_rosters(
            manager_keys=["sleeper:u1"],
            http_get=http,
            ledger_path=ledger,
            sleep_fn=lambda _s: None,
            now_ms=NOW,
        )
        assert result.rosters_recorded == 3
        assert result.eligible_rosters == 1
        assert result.exclusion_reasons[rc.REASON_SUPERSEDED_SEASON] == 2

        eligible = [r for r in rs.load_rosters(path=ledger) if r["isEligible"]]
        assert len(eligible) == 1
        assert eligible[0]["leagueKey"] == "sleeper:L2026"

    def test_a_predecessor_outside_this_run_is_not_superseded(self, ledger):
        """We cannot supersede a league we never collected.

        L1's chain points at a 2025 instance we did not fetch. Dropping
        L1 on that basis would remove a live league from the board.
        """
        seed_sleeper_membership(ledger, "sleeper:u1", "sleeper:L1")
        result = rc.collect_sleeper_rosters(
            manager_keys=["sleeper:u1"],
            http_get=fake_http(league=league_payload(previous_league_id="never-fetched")),
            ledger_path=ledger,
            sleep_fn=lambda _s: None,
            now_ms=NOW,
        )
        assert result.eligible_rosters == 1
        assert rc.REASON_SUPERSEDED_SEASON not in result.exclusion_reasons

    def test_a_budgeted_run_rotates_instead_of_re_collecting_one_prefix(self, ledger):
        """A capped run must ADVANCE, not restart at the same leagues.

        Ordering by league id meant a budget-limited pass re-collected
        the same alphabetical prefix every run, so leagues after the
        cutoff were never collected at all — a permanently invisible
        tail that the board would not have shown as missing.
        """
        for i in range(1, 7):
            seed_sleeper_membership(ledger, "sleeper:u1", f"sleeper:L{i}")

        collected_per_run = []
        for run in range(3):
            rc.collect_sleeper_rosters(
                manager_keys=["sleeper:u1"],
                http_get=fake_http(),
                budget=4,  # two leagues per run
                ledger_path=ledger,
                sleep_fn=lambda _s: None,
                now_ms=NOW + run * 86_400_000,
            )
            collected_per_run.append({r["leagueKey"] for r in rs.load_rosters(path=ledger)})

        # Each run reaches leagues the previous ones had not.
        assert len(collected_per_run[0]) == 2
        assert len(collected_per_run[1]) == 4
        assert len(collected_per_run[2]) == 6

    def test_budget_exhaustion_reports_how_much_is_left(self, ledger):
        for i in range(1, 7):
            seed_sleeper_membership(ledger, "sleeper:u1", f"sleeper:L{i}")
        result = rc.collect_sleeper_rosters(
            manager_keys=["sleeper:u1"],
            http_get=fake_http(),
            budget=4,
            ledger_path=ledger,
            sleep_fn=lambda _s: None,
            now_ms=NOW,
        )
        assert result.budget_exhausted is True
        assert result.leagues_remaining == 4
        assert result.to_dict()["leaguesRemaining"] == 4

    def test_recollection_is_idempotent(self, ledger):
        seed_sleeper_membership(ledger)
        http = fake_http()
        for _ in range(3):
            rc.collect_sleeper_rosters(
                manager_keys=["sleeper:u1"],
                http_get=http,
                ledger_path=ledger,
                sleep_fn=lambda _s: None,
                now_ms=NOW,
            )
        assert rs.coverage(path=ledger)["rosters"] == 1


class TestLeagueFormat:
    def test_format_axes_come_from_the_league_payload(self):
        fmt = rc.league_format(
            league_payload(
                roster_positions=["QB", "RB", "WR", "TE", "SUPER_FLEX", "LB", "DB", "K", "BN"],
                scoring_settings={"rec": 1.0, "bonus_rec_te": 0.5},
            )
        )
        assert fmt["superflex"] is True
        assert fmt["tePremium"] is True
        assert fmt["idp"] is True
        assert fmt["kicker"] is True
        assert fmt["teamDefense"] is False

    def test_one_qb_non_tep_offense_only_is_detected(self):
        fmt = rc.league_format(
            league_payload(
                roster_positions=["QB", "RB", "WR", "TE", "FLEX", "BN"],
                scoring_settings={"rec": 1.0},
            )
        )
        assert fmt["superflex"] is False
        assert fmt["tePremium"] is False
        assert fmt["idp"] is False

    def test_an_unreadable_payload_yields_unknown_not_false(self):
        """Unknown must never be silently rendered as "no"."""
        fmt = rc.league_format({"league_id": "L1"})
        assert fmt["superflex"] is None
        assert fmt["idp"] is None
        assert fmt["tePremium"] is None


class TestContention:
    def test_a_winning_record_reads_as_contending(self):
        assert rc._contention({"settings": {"wins": 8, "losses": 2}}) == "contending"

    def test_a_losing_record_reads_as_rebuilding(self):
        assert rc._contention({"settings": {"wins": 2, "losses": 8}}) == "rebuilding"

    def test_preseason_is_unknown_rather_than_a_default_bucket(self):
        assert rc._contention({"settings": {"wins": 0, "losses": 0}}) == "unknown"
        assert rc._contention({}) == "unknown"


class TestFFPC:
    def seed(self, ledger, roster_assets, *, confidence=0.7, manager="ffpc:league:F1:team:7"):
        conn = platform_ledger.ensure_platform_schema(ledger)
        try:
            conn.execute(
                """
                INSERT INTO platform_managers
                  (manager_key, platform, source_manager_id, source_identity_type,
                   identity_scope, identity_confidence, first_seen_ms, last_seen_ms,
                   metadata_json)
                VALUES (?, 'ffpc', ?, 'league_scoped_team', 'league', ?, ?, ?, '{}')
                """,
                (manager, manager.split(":", 1)[1], confidence, NOW, NOW),
            )
            platform_ledger.upsert_league(
                NormalizedLeague.build("ffpc", "F1", season="2026", sharp_eligible=True), conn=conn
            )
            platform_ledger.upsert_membership(
                NormalizedMembership(
                    platform="ffpc",
                    league_key="ffpc:F1",
                    manager_key=manager,
                    source_team_id="7",
                    roster_id="7",
                    team_name="North Stars",
                    metadata={"rosterAssets": roster_assets},
                ),
                conn=conn,
            )
            conn.commit()
        finally:
            conn.close()

    def test_already_crawled_roster_assets_are_lifted_without_network_calls(self, ledger):
        self.seed(
            ledger,
            [
                {"canonicalAssetId": "4046", "displayName": "Justin Jefferson"},
                {"canonicalAssetId": "6794", "displayName": "Bijan Robinson"},
            ],
        )
        result = rc.collect_ffpc_rosters(
            manager_keys=["ffpc:league:F1:team:7"], ledger_path=ledger, now_ms=NOW
        )
        assert result.calls_used == 0
        assert result.rosters_recorded == 1
        assert result.eligible_rosters == 1
        stored = rs.load_rosters(path=ledger)[0]
        assert stored["platform"] == "ffpc"
        assert {a["canonicalAssetId"] for a in stored["assets"]} == {"4046", "6794"}

    def test_unmapped_players_are_counted_never_guessed(self, ledger):
        self.seed(
            ledger,
            [
                {"canonicalAssetId": "4046", "displayName": "Justin Jefferson"},
                {"canonicalAssetId": None, "displayName": "Someone Unmatched"},
            ],
        )
        result = rc.collect_ffpc_rosters(
            manager_keys=["ffpc:league:F1:team:7"], ledger_path=ledger, now_ms=NOW
        )
        assert result.unmapped_assets == 1
        stored = rs.load_rosters(path=ledger)[0]
        assert [a["canonicalAssetId"] for a in stored["assets"]] == ["4046"]

    def test_a_name_only_identity_is_excluded_as_uncertain(self, ledger):
        """FFPC name-only identities sit at 0.25 confidence.

        Attributing a roster to a manager matched on a display-name hash
        is exactly the "uncertain identity matching" case the audit
        requires be excluded rather than counted.
        """
        self.seed(
            ledger,
            [{"canonicalAssetId": "4046"}],
            confidence=0.25,
            manager="ffpc:league:F1:name:abc123",
        )
        result = rc.collect_ffpc_rosters(
            manager_keys=["ffpc:league:F1:name:abc123"], ledger_path=ledger, now_ms=NOW
        )
        assert result.eligible_rosters == 0
        assert rc.REASON_UNCERTAIN_IDENTITY in result.exclusion_reasons

    def test_memberships_without_roster_contents_are_skipped(self, ledger):
        conn = platform_ledger.ensure_platform_schema(ledger)
        try:
            conn.execute(
                """
                INSERT INTO platform_managers
                  (manager_key, platform, source_manager_id, source_identity_type,
                   identity_scope, identity_confidence, first_seen_ms, last_seen_ms,
                   metadata_json)
                VALUES ('ffpc:x', 'ffpc', 'x', 'global_verified', 'platform', 1.0, ?, ?, '{}')
                """,
                (NOW, NOW),
            )
            platform_ledger.upsert_membership(
                NormalizedMembership(
                    platform="ffpc",
                    league_key="ffpc:F1",
                    manager_key="ffpc:x",
                    roster_id="1",
                    metadata={"sourceUrl": "https://example.invalid"},
                ),
                conn=conn,
            )
            conn.commit()
        finally:
            conn.close()
        result = rc.collect_ffpc_rosters(manager_keys=["ffpc:x"], ledger_path=ledger, now_ms=NOW)
        assert result.rosters_recorded == 0


class TestALaneThatDidNotRunNeverReadsAsAnEmptyOne:
    """V1: the FFPC roster lane must be real or explicitly unavailable —
    never a silent zero.

    Every counter on ``CollectResult`` is 0 in two completely different
    situations: the lane ran and legitimately found nothing, and the lane
    never ran at all. Those serialise identically unless something says
    which it was, and "0 rosters, 0 errors" reads as a healthy platform
    with an empty wire.
    """

    def test_a_real_empty_pass_is_ok(self):
        """A lane that ran and found nothing is NOT unavailable — the
        distinction only works if both directions hold."""
        payload = rc.CollectResult().to_dict()
        assert payload["status"] == rc.STATUS_OK
        assert payload["unavailableReason"] == ""

    def test_ffpc_with_no_cohort_managers_is_unavailable_not_zero(self, ledger):
        result = rc.collect_ffpc_rosters(manager_keys=["sleeper:u1"], ledger_path=ledger)
        assert result.status == rc.STATUS_UNAVAILABLE
        assert result.unavailable_reason == rc.UNAVAILABLE_NO_MANAGERS
        assert result.rosters_recorded == 0

    def test_the_reason_survives_serialisation(self, ledger):
        payload = rc.collect_ffpc_rosters(manager_keys=[], ledger_path=ledger).to_dict()
        assert payload["status"] == "unavailable"
        assert payload["unavailableReason"] == "no_cohort_managers_on_platform"

    @pytest.mark.parametrize("lane", ["sleeper", "ffpc"])
    def test_a_skipped_lane_says_it_was_skipped(self, ledger, monkeypatch, lane):
        monkeypatch.setattr(rc.sharp_cohort, "cohort_members", lambda **kw: ([], {"note": "empty"}))
        summary = rc.collect_all(
            ledger_path=ledger,
            run_id="r1",
            skip_sleeper=(lane == "sleeper"),
            skip_ffpc=(lane == "ffpc"),
        )
        assert summary[lane]["status"] == rc.STATUS_UNAVAILABLE
        assert summary[lane]["unavailableReason"] == rc.UNAVAILABLE_SKIPPED

    def test_skipping_one_lane_does_not_mark_the_other_unavailable(self, ledger, monkeypatch):
        monkeypatch.setattr(rc.sharp_cohort, "cohort_members", lambda **kw: ([], {"note": "empty"}))
        summary = rc.collect_all(ledger_path=ledger, run_id="r1", skip_sleeper=True)
        assert summary["sleeper"]["status"] == rc.STATUS_UNAVAILABLE
        # FFPC genuinely ran; it reports its own reason for contributing
        # nothing rather than inheriting the skip.
        assert summary["ffpc"]["unavailableReason"] == rc.UNAVAILABLE_NO_MANAGERS

    def test_unavailable_is_distinguishable_from_ok_by_status_alone(self):
        """A consumer must not have to infer availability from the counters,
        which is what made the silent zero possible."""
        ran = rc.CollectResult(rosters_recorded=0)
        never = rc.CollectResult.unavailable(rc.UNAVAILABLE_SKIPPED)
        assert ran.to_dict()["rostersRecorded"] == never.to_dict()["rostersRecorded"] == 0
        assert ran.to_dict()["status"] != never.to_dict()["status"]


def test_collection_run_is_filed_under_its_own_pseudo_platform(ledger):
    """Must not overwrite the Buy/Sell Tracker's freshness reading."""
    rc.record_collection_run(
        {"sleeper": {"callsUsed": 4, "leaguesExamined": 2}, "ffpc": {"unmappedAssets": 1}},
        started_ms=NOW,
        finished_ms=NOW + 1000,
        ledger_path=ledger,
        run_id="test-run",
    )
    coverage = platform_ledger.platform_coverage(ledger)
    assert coverage["sleeper"]["latestIngestion"] is None
    assert coverage["ffpc"]["latestIngestion"] is None
    conn = platform_ledger.ensure_platform_schema(ledger)
    try:
        row = conn.execute(
            "SELECT platform, pages_fetched, metadata_json FROM ingestion_runs WHERE run_id=?",
            ("test-run",),
        ).fetchone()
    finally:
        conn.close()
    assert row["platform"] == "sharp_rosters"
    assert row["pages_fetched"] == 4
    assert json.loads(row["metadata_json"])["sleeper"]["leaguesExamined"] == 2
