"""Mid-season roster hand-off: Joel (jstuedle) -> John (jnesselhauf), roster 11.

Owner directive 2026-10-16, corrected 2026-10-17: Sleeper user ``jnesselhauf``
(user_id 735693375101108224) is **John** and took over ``dynasty_main`` roster
11 from **Joel** (``jstuedle``, user_id 712035316776669184) effective week 6.
Two different people, keyed by user id.  These tests pin:

* names resolve by user id first (a rename, or a mistyped display-name key,
  cannot bring the wrong name back);
* weeks before the hand-off belong to Joel, weeks from it to John, and an
  event with no week belongs to the current owner;
* Joel keeps an identity for his own weeks but leaves current directories;
* the committed league snapshot names every current owner.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.acquisition.events import events_from_draft_picks, events_from_transaction
from src.identity import picks
from src.api import faab_analytics, sleeper_overlay
from src.api.team_assignment import _resolve_favorite_key
from src.public_league import luck, metrics, ownership, playoff_odds, snapshot_store
from src.public_league.identity import build_manager_registry, register_handed_off_owners
from src.public_league.snapshot import SeasonSnapshot
from src.utils import owner_names

REPO = Path(__file__).resolve().parents[2]
LEAGUE = "1312006700437352448"
JOEL = "712035316776669184"
JOHN = "735693375101108224"
ROSTER = 11


def _season() -> dict:
    return {
        "league": {"league_id": LEAGUE, "season": "2026"},
        "users": [
            {
                "user_id": JOHN,
                "display_name": "jnesselhauf",
                "metadata": {"team_name": "281 BBQ smoke n fire"},
            },
            {"user_id": "468418790212759552", "display_name": "JasonLeeTucker", "metadata": {}},
        ],
        "rosters": [
            {"roster_id": ROSTER, "owner_id": JOHN},
            {"roster_id": 1, "owner_id": "468418790212759552"},
        ],
    }


# ── names ──────────────────────────────────────────────────────────────


def test_names_resolve_by_user_id_first():
    assert owner_names.owner_label({"user_id": JOHN, "display_name": "jnesselhauf"}) == "John"
    assert owner_names.owner_label({"user_id": JOEL, "display_name": "jstuedle"}) == "Joel"
    # A rename keeps the right person's name; a stranger reusing the old
    # handle does not inherit it.
    assert owner_names.owner_label({"user_id": JOHN, "display_name": "renamed123"}) == "John"
    assert owner_names.owner_label({"user_id": "999", "display_name": "jstuedle"}) == "jstuedle"


def test_the_jstudle_typo_key_is_gone():
    raw = json.loads((REPO / "config/leagues/owner_names.json").read_text(encoding="utf-8"))
    assert "jstudle" not in {k.lower() for k in raw}
    by_id = raw["_byUserId"]
    assert by_id[JOEL] == "Joel" and by_id[JOHN] == "John"
    assert all(k.isdigit() for k in by_id)


def test_every_current_owner_in_the_committed_snapshot_has_a_configured_name():
    """Catches a display-name key that no longer matches anyone (``jstudle``)."""
    teams = json.loads((REPO / "data/sleeper_last_good.json").read_text(encoding="utf-8"))[
        "rosterData"
    ]["teams"]
    configured = set(owner_names._load_mapping().values())
    unnamed = [
        (t["roster_id"], t["ownerId"], t["name"])
        for t in teams
        if not owner_names.owner_name_for_user_id(t["ownerId"]) and t["name"] not in configured
    ]
    assert unnamed == []


def test_john_does_not_inherit_joels_favorite_team():
    favorites = {"joel": {"abbr": "KC"}}
    aliases = {"jstuedle": "joel"}
    assert _resolve_favorite_key("John", favorites, aliases) is None
    assert _resolve_favorite_key("Joel", favorites, aliases) == "joel"


# ── week attribution ───────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("week", "expected"),
    [(0, JOEL), (1, JOEL), (5, JOEL), (6, JOHN), (7, JOHN), (None, JOHN)],
)
def test_owner_at_splits_the_season_at_week_six(week, expected):
    assert ownership.owner_at(LEAGUE, ROSTER, JOHN, week) == expected


def test_other_rosters_and_leagues_are_untouched():
    assert ownership.owner_at(LEAGUE, 1, "468418790212759552", 3) == "468418790212759552"
    assert ownership.owner_at("1180092661344120832", ROSTER, "someone", 3) == "someone"


def test_resolve_owner_and_transaction_legs():
    registry = build_manager_registry([_season()])
    assert metrics.resolve_owner(registry, LEAGUE, ROSTER) == JOHN
    assert metrics.resolve_owner(registry, LEAGUE, ROSTER, 4) == JOEL
    assert metrics.resolve_owner(registry, LEAGUE, ROSTER, metrics.tx_week({"leg": 3})) == JOEL
    assert metrics.resolve_owner(registry, LEAGUE, ROSTER, metrics.tx_week({"leg": 8})) == JOHN
    assert metrics.tx_week({}) is None and metrics.tx_week({"leg": 0}) is None


# ── identity ───────────────────────────────────────────────────────────


def test_joel_keeps_an_identity_but_leaves_the_current_directory():
    registry = build_manager_registry([_season()])
    joel = registry.by_owner_id[JOEL]
    assert joel.display_name == "Joel" and joel.is_retired
    assert [(a.season, a.roster_id) for a in joel.aliases] == [("2026", ROSTER)]
    john = registry.by_owner_id[JOHN]
    assert john.display_name == "John" and john.current_roster_id == ROSTER
    current = [m.owner_id for m in registry.ordered_managers()]
    assert JOHN in current and JOEL not in current


def test_registry_reload_restores_joel_once():
    registry = build_manager_registry([_season()])
    persisted = snapshot_store._registry_to_dict(registry)
    persisted["byOwnerId"].pop(JOEL)  # a snapshot saved before the hand-off was recorded
    reloaded = snapshot_store._registry_from_dict(persisted)
    assert JOEL in reloaded.by_owner_id
    register_handed_off_owners(reloaded)
    assert len(reloaded.by_owner_id[JOEL].aliases) == 1


def test_handoffs_are_skipped_for_snapshots_without_that_league():
    other = _season()
    other["league"]["league_id"] = "1180092661344120832"
    registry = build_manager_registry([other])
    assert JOEL not in registry.by_owner_id


# ── ledgers ────────────────────────────────────────────────────────────


def _waiver(leg: int) -> dict:
    return {
        "transaction_id": f"tx{leg}",
        "status": "complete",
        "type": "waiver",
        "leg": leg,
        "status_updated": 1_760_000_000_000 + leg,
        "roster_ids": [ROSTER],
        "adds": {"9999": ROSTER},
        "drops": {},
        "settings": {"waiver_bid": 3},
    }


@pytest.mark.parametrize(("leg", "expected"), [(3, JOEL), (6, JOHN)])
def test_acquisition_events_attribute_by_week(leg, expected):
    events = events_from_transaction(
        _waiver(leg),
        league_key="dynasty_main",
        sleeper_league_id=LEAGUE,
        season="2026",
        owner_by_roster={ROSTER: JOHN},
    )
    assert events and all(e.after_owner_user_id == expected for e in events)


def test_draft_picks_belong_to_the_outgoing_owner():
    events = events_from_draft_picks(
        [{"roster_id": ROSTER, "player_id": "1234", "round": 1, "pick_no": 3, "draft_slot": 3}],
        draft_id="d2026",
        league_key="dynasty_main",
        sleeper_league_id=LEAGUE,
        season="2026",
        owner_by_roster={ROSTER: JOHN},
    )
    assert events and all(e.after_owner_user_id == JOEL for e in events)


def test_faab_analytics_attributes_by_week():
    class _Season:
        league_id = LEAGUE
        rosters = [{"roster_id": ROSTER, "owner_id": JOHN}]

    assert faab_analytics._owner_for_roster(_Season, ROSTER, 2) == JOEL
    assert faab_analytics._owner_for_roster(_Season, ROSTER, 9) == JOHN
    assert faab_analytics._owner_for_roster(_Season, ROSTER) == JOHN


# ── baked contract labels ──────────────────────────────────────────────


def test_relabel_pick_origin_touches_only_a_renamed_annotation():
    renames = {"jnesselhauf": "John"}
    assert picks.relabel_pick_origin("2027 Mid 2nd (from jnesselhauf)", renames) == (
        "2027 Mid 2nd (from John)"
    )
    assert picks.relabel_pick_origin("2027 Mid 2nd (own)", renames) == "2027 Mid 2nd (own)"
    assert picks.relabel_pick_origin("2027 Mid 2nd (from Roy)", renames) == (
        "2027 Mid 2nd (from Roy)"
    )
    assert picks.relabel_pick_origin(None, renames) is None


def test_a_contract_baked_before_the_name_was_configured_is_relabelled():
    """The committed export names roster 11 by handle until the next scrape."""
    sleeper = {
        "teams": [
            {
                "ownerId": JOHN,
                "roster_id": ROSTER,
                "name": "jnesselhauf",
                "picks": ["2027 Mid 1st (own)"],
                "pickDetails": [
                    {"fromTeam": "jnesselhauf", "label": "2027 Mid 1st (own)", "fromRosterId": 11}
                ],
            },
            {
                "ownerId": "468418790212759552",
                "roster_id": 1,
                "name": "Jason",
                "picks": ["2027 Mid 2nd (from jnesselhauf)"],
                "pickDetails": [
                    {"fromTeam": "jnesselhauf", "label": "2027 Mid 2nd (from jnesselhauf)"}
                ],
            },
        ],
        "trades": [
            {
                "sides": [
                    {"team": "jnesselhauf", "got": [], "gave": ["2027 Mid 2nd (from jnesselhauf)"]}
                ]
            }
        ],
    }
    assert sleeper_overlay.relabel_sleeper_block(sleeper) == {"jnesselhauf": "John"}
    john, jason = sleeper["teams"]
    assert john["name"] == "John" and john["ownerId"] == JOHN and john["roster_id"] == ROSTER
    assert john["pickDetails"][0]["fromTeam"] == "John"
    assert jason["name"] == "Jason"
    assert jason["picks"] == ["2027 Mid 2nd (from John)"]
    assert jason["pickDetails"][0] == {"fromTeam": "John", "label": "2027 Mid 2nd (from John)"}
    side = sleeper["trades"][0]["sides"][0]
    assert side["team"] == "John" and side["gave"] == ["2027 Mid 2nd (from John)"]
    # Idempotent, and a no-op on an already-current block.
    assert sleeper_overlay.relabel_sleeper_block(sleeper) == {}


def test_relabel_never_creates_a_duplicate_team_label():
    sleeper = {
        "teams": [
            {"ownerId": JOHN, "name": "jnesselhauf"},
            {"ownerId": "999", "name": "John"},
        ]
    }
    assert sleeper_overlay.relabel_sleeper_block(sleeper) == {}
    assert sleeper["teams"][0]["name"] == "jnesselhauf"
    assert sleeper_overlay.relabel_sleeper_block(None) == {}


# ── team-level forecasts follow the roster, not the week's manager ─────


def _scored_season(weeks: int = 6) -> SeasonSnapshot:
    base = _season()
    return SeasonSnapshot(
        season="2026",
        league_id=LEAGUE,
        league={
            "league_id": LEAGUE,
            "season": "2026",
            "season_type": "regular",
            "total_rosters": 2,
            "settings": {"playoff_week_start": 15, "last_scored_leg": weeks},
        },
        users=base["users"],
        rosters=base["rosters"],
        matchups_by_week={
            wk: [
                {"matchup_id": 1, "roster_id": ROSTER, "points": 100.0 + wk},
                {"matchup_id": 1, "roster_id": 1, "points": 90.0 + wk},
            ]
            for wk in range(1, weeks + 1)
        },
        transactions_by_week={},
        drafts=[],
        draft_picks_by_draft={},
        traded_picks=[],
        winners_bracket=[],
        losers_bracket=[],
    )


def test_manager_history_splits_but_the_team_forecast_does_not():
    """dynasty_main roster 11, 2026-10-17: weekly scores split Joel/John by week
    while the record and remaining schedule key the roster to John, so the
    playoff simulator saw a scheduled team with no scores and championship odds
    stopped publishing.  A forecast is a TEAM question: scores follow the roster.
    """
    season = _scored_season()
    registry = build_manager_registry([_season()])

    by_week = luck._season_weekly_scores(season, registry)
    assert {o for o, _ in by_week[5]} == {JOEL, "468418790212759552"}
    assert {o for o, _ in by_week[6]} == {JOHN, "468418790212759552"}

    per_owner, _pool = playoff_odds._season_weekly_scores(season, registry)
    assert set(per_owner) == {JOHN, "468418790212759552"}
    assert per_owner[JOHN] == [100.0 + wk for wk in range(1, 7)]

    record, _rule = playoff_odds.regular_season_standings_to_date(season, registry)
    assert set(record) == set(per_owner)
