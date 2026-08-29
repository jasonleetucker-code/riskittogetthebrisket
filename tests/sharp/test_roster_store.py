"""The roster store's deduplication guarantees are STRUCTURAL.

Every assertion here is really about a primary key. If one of these
fails, the fix is the schema, not a filter in the caller — the whole
point of the design is that no caller can forget to deduplicate.
"""

from __future__ import annotations

import pytest

from src.sharp import roster_store as rs

NOW = 1_800_000_000_000


def observation(**overrides):
    base = dict(
        platform="sleeper",
        league_key="sleeper:L1",
        manager_key="sleeper:u1",
        source_roster_id="1",
        assets=[rs.RosterAsset("4046"), rs.RosterAsset("6794")],
        observed_ms=NOW,
    )
    base.update(overrides)
    return rs.RosterObservation(**base)


@pytest.fixture
def ledger(tmp_path):
    return tmp_path / "ledger.sqlite3"


def test_same_roster_collected_twice_is_one_denominator_slot(ledger):
    rs.record_rosters([observation(), observation()], path=ledger)
    rows = rs.load_rosters(path=ledger)
    assert len(rows) == 1
    assert rs.coverage(path=ledger)["rosters"] == 1


def test_duplicate_player_rows_within_one_roster_count_once(ledger):
    rs.record_rosters(
        [
            observation(
                assets=[
                    rs.RosterAsset("4046"),
                    rs.RosterAsset("4046"),
                    rs.RosterAsset("4046"),
                ]
            )
        ],
        path=ledger,
    )
    row = rs.load_rosters(path=ledger)[0]
    assert row["assetCount"] == 1
    assert [a["canonicalAssetId"] for a in row["assets"]] == ["4046"]


def test_one_manager_with_several_leagues_contributes_several_rosters(ledger):
    rs.record_rosters(
        [
            observation(league_key="sleeper:L1"),
            observation(league_key="sleeper:L2"),
            observation(league_key="sleeper:L3"),
        ],
        path=ledger,
    )
    rows = rs.load_rosters(path=ledger)
    assert len(rows) == 3
    assert {r["managerKey"] for r in rows} == {"sleeper:u1"}


def test_two_sharps_on_different_rosters_in_one_league_are_two_rosters(ledger):
    rs.record_rosters(
        [
            observation(manager_key="sleeper:u1", source_roster_id="1"),
            observation(manager_key="sleeper:u2", source_roster_id="2"),
        ],
        path=ledger,
    )
    assert len(rs.load_rosters(path=ledger)) == 2


def test_taxi_and_reserve_slots_are_labelled_not_dropped(ledger):
    rs.record_rosters(
        [
            observation(
                assets=[
                    rs.RosterAsset("4046", slot=rs.SLOT_ACTIVE),
                    rs.RosterAsset("6794", slot=rs.SLOT_TAXI),
                    rs.RosterAsset("5849", slot=rs.SLOT_RESERVE),
                ]
            )
        ],
        path=ledger,
    )
    row = rs.load_rosters(path=ledger)[0]
    assert row["assetCount"] == 3
    assert {a["canonicalAssetId"]: a["slot"] for a in row["assets"]} == {
        "4046": rs.SLOT_ACTIVE,
        "6794": rs.SLOT_TAXI,
        "5849": rs.SLOT_RESERVE,
    }


def test_more_specific_slot_wins_when_a_player_appears_twice(ledger):
    rs.record_rosters(
        [
            observation(
                assets=[
                    rs.RosterAsset("4046", slot=rs.SLOT_ACTIVE),
                    rs.RosterAsset("4046", slot=rs.SLOT_TAXI),
                ]
            )
        ],
        path=ledger,
    )
    row = rs.load_rosters(path=ledger)[0]
    assert row["assets"] == [{"canonicalAssetId": "4046", "assetType": "player", "slot": "taxi"}]


def test_recollection_replaces_holdings_rather_than_accumulating(ledger):
    rs.record_rosters([observation(assets=[rs.RosterAsset("4046")])], path=ledger)
    rs.record_rosters(
        [observation(assets=[rs.RosterAsset("6794")], observed_ms=NOW + 1000)], path=ledger
    )
    row = rs.load_rosters(path=ledger)[0]
    assert [a["canonicalAssetId"] for a in row["assets"]] == ["6794"]


def test_excluded_rosters_are_kept_with_their_reasons(ledger):
    rs.record_rosters(
        [observation(exclusion_reasons=["stale_roster_data", "orphaned_roster_no_owner"])],
        path=ledger,
    )
    row = rs.load_rosters(path=ledger)[0]
    assert row["isEligible"] is False
    assert row["exclusionReasons"] == ["orphaned_roster_no_owner", "stale_roster_data"]
    assert rs.exclusion_reason_counts(path=ledger) == {
        "orphaned_roster_no_owner": 1,
        "stale_roster_data": 1,
    }


class TestHistory:
    def test_spans_answer_holdings_at_a_past_instant(self, ledger):
        rs.record_rosters(
            [observation(assets=[rs.RosterAsset("4046"), rs.RosterAsset("6794")])], path=ledger
        )
        rs.record_rosters(
            [
                observation(
                    assets=[rs.RosterAsset("4046"), rs.RosterAsset("5849")],
                    observed_ms=NOW + 86_400_000,
                )
            ],
            path=ledger,
        )
        keys = ["sleeper:L1#1"]
        assert rs.holdings_as_of(NOW, roster_keys=keys, path=ledger) == {
            "sleeper:L1#1": {"4046", "6794"}
        }
        assert rs.holdings_as_of(NOW + 86_400_000, roster_keys=keys, path=ledger) == {
            "sleeper:L1#1": {"4046", "5849"}
        }

    def test_a_roster_not_yet_observed_is_absent_not_empty(self, ledger):
        """The distinction a trend depends on.

        Present-and-empty would read as "this roster owned nobody",
        turning every later discovery into a fake ownership gain.
        """
        rs.record_rosters([observation()], path=ledger)
        assert rs.holdings_as_of(NOW - 1, roster_keys=["sleeper:L1#1"], path=ledger) == {}

    def test_an_open_span_covers_instants_after_the_last_observation(self, ledger):
        rs.record_rosters([observation()], path=ledger)
        later = rs.holdings_as_of(NOW + 999_999, roster_keys=["sleeper:L1#1"], path=ledger)
        assert later == {"sleeper:L1#1": {"4046", "6794"}}

    def test_a_holding_persists_until_the_observation_that_contradicts_it(self, ledger):
        """The gap between two observations is HELD, not unheld.

        Rosters are observed periodically. A roster seen on day 0 and
        again on day 40 was never confirmed on day 10 — but the player
        was rostered then, because nothing had said otherwise yet.
        Answering this against the last CONFIRMING observation instead
        of the CONTRADICTING one zeroes every drop that happened between
        two crawls, which surfaces as a 30-day trend of exactly 0.0 no
        matter how much moved.
        """
        day = 86_400_000
        rs.record_rosters(
            [observation(assets=[rs.RosterAsset("4046")], observed_ms=NOW)], path=ledger
        )
        rs.record_rosters([observation(assets=[], observed_ms=NOW + 40 * day)], path=ledger)

        keys = ["sleeper:L1#1"]
        # Ten days in, the drop has not been observed yet.
        assert rs.holdings_as_of(NOW + 10 * day, roster_keys=keys, path=ledger) == {
            "sleeper:L1#1": {"4046"}
        }
        # At the observation that found him gone, he is gone.
        assert rs.holdings_as_of(NOW + 40 * day, roster_keys=keys, path=ledger) == {
            "sleeper:L1#1": set()
        }


class TestHoldingsAsOfMulti:
    """holdings_as_of_multi() answers several timestamps from one pass
    over the observation/span tables instead of one scan per timestamp
    (V1-61: the remaining source of a >60s production timeout after
    connection reuse alone proved insufficient). It must be
    byte-identical to calling holdings_as_of() once per timestamp —
    every property below is already proven of holdings_as_of() itself
    in TestHistory; this class exists to prove the batched path never
    diverges from it, not to re-derive the semantics.
    """

    def _fixture(self, ledger):
        day = 86_400_000
        # Roster 1 (league L1): held {4046, 6794} from NOW, then 6794
        # was dropped as of the observation at NOW + 40d (still holds
        # 4046, an OPEN span with no closing observation at all).
        rs.record_rosters(
            [observation(assets=[rs.RosterAsset("4046"), rs.RosterAsset("6794")], observed_ms=NOW)],
            path=ledger,
        )
        rs.record_rosters(
            [observation(assets=[rs.RosterAsset("4046")], observed_ms=NOW + 40 * day)],
            path=ledger,
        )
        # Roster 2 (league L1, a second manager/roster): not observed
        # until NOW + 10d — absent from any as_of before that.
        rs.record_rosters(
            [
                observation(
                    manager_key="sleeper:u2",
                    source_roster_id="2",
                    assets=[rs.RosterAsset("5849")],
                    observed_ms=NOW + 10 * day,
                )
            ],
            path=ledger,
        )
        # Roster "sleeper:L2#1" is deliberately never recorded at all —
        # the never-observed case.
        return day

    def test_matches_per_call_output_at_every_boundary(self, ledger):
        day = self._fixture(ledger)
        keys = ["sleeper:L1#1", "sleeper:L1#2", "sleeper:L2#1"]
        # Spans the fixture's real boundaries: before anything, exactly
        # at roster 1's first observation, between roster 2's first
        # observation and roster 1's second, exactly at roster 1's
        # second (the drop), and long after everything.
        as_ofs = [NOW - 1, NOW, NOW + 5 * day, NOW + 15 * day, NOW + 40 * day, NOW + 100 * day]

        batched = rs.holdings_as_of_multi(as_ofs, roster_keys=keys, path=ledger)
        per_call = {a: rs.holdings_as_of(a, roster_keys=keys, path=ledger) for a in as_ofs}

        assert batched == per_call
        # Concrete sanity checks so a bug in BOTH implementations at once
        # (which the equality above could not catch) still fails loudly.
        assert batched[NOW - 1] == {}  # nothing observed yet — ABSENT
        assert batched[NOW] == {"sleeper:L1#1": {"4046", "6794"}}
        assert batched[NOW + 15 * day] == {
            "sleeper:L1#1": {"4046", "6794"},
            "sleeper:L1#2": {"5849"},
        }
        assert batched[NOW + 40 * day] == {
            "sleeper:L1#1": {"4046"},
            "sleeper:L1#2": {"5849"},
        }
        # sleeper:L2#1 is absent from every timestamp — never observed.
        for a in as_ofs:
            assert "sleeper:L2#1" not in batched[a]

    def test_empty_roster_keys_returns_empty_per_timestamp(self, ledger):
        self._fixture(ledger)
        assert rs.holdings_as_of_multi([NOW, NOW + 1], roster_keys=[], path=ledger) == {
            NOW: {},
            NOW + 1: {},
        }

    def test_a_caller_supplied_connection_is_not_closed(self, ledger):
        self._fixture(ledger)
        conn = rs.ensure_roster_schema(ledger)
        try:
            rs.holdings_as_of_multi([NOW], roster_keys=["sleeper:L1#1"], conn=conn)
            # A closed connection raises on any further use.
            conn.execute("SELECT 1")
        finally:
            conn.close()


def test_schema_creation_is_idempotent_and_does_not_touch_platform_version(ledger):
    from src.intel import platform_ledger

    conn = rs.ensure_roster_schema(ledger)
    try:
        before = conn.execute(
            "SELECT value FROM meta WHERE key=?", (platform_ledger.MIGRATION_META_KEY,)
        ).fetchone()
        rs.ensure_roster_schema(conn=conn)
        rs.ensure_roster_schema(conn=conn)
        after = conn.execute(
            "SELECT value FROM meta WHERE key=?", (platform_ledger.MIGRATION_META_KEY,)
        ).fetchone()
        assert before[0] == after[0] == str(platform_ledger.PLATFORM_SCHEMA_VERSION)
    finally:
        conn.close()
