"""Mid-season roster hand-off: Blaine (ughb) -> schoeppeya, dynasty_main roster 12.

The automated refresh of 2026-10-20 21:59 UTC (commit 343d47a634) committed
``data/sleeper_last_good.json`` with roster 12 owned by a new Sleeper user,
``schoeppeya`` (user_id 1393410658032177152).  The roster had been held by
**Blaine** (``ughb``, user_id 1303549304882892800) through savedAt
2026-10-19T23:56Z (Sleeper ``leg`` 6, ``last_scored_leg`` 5 — week 6 still
being played) and was ownerless ("Team 12") from 2026-10-20T05:20Z, after
week 6 was scored.  The league is best ball, so nothing is managed once week
6 locks: the first week Blaine did not hold the roster is **week 7**.  That
cutover week is derived from committed evidence and is PENDING OWNER
CONFIRMATION (``docs/OWNER_REQUESTED_TODO.md``); the new manager's real first
name is unknown, so he is named by his Sleeper display name, exactly what the
site already showed.

Mirrors ``test_roster_handoff.py`` (roster 11, Joel -> John) against the
COMMITTED config — no monkeypatched hand-off — so the record itself is what
these tests pin:

* names resolve by user id: Blaine stays "Blaine", the new manager is
  "schoeppeya" (no invented name);
* weeks 1-6 belong to Blaine, week 7 on to schoeppeya, an event with no week
  to the current owner, and the draft (week 0) to Blaine;
* Blaine keeps an identity for his weeks and leaves current directories;
* the new manager inherits neither Blaine's favourite team nor his award
  eligibility ruling, which stays keyed to Blaine's user id;
* roster 11's hand-off is untouched.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from src.acquisition.events import events_from_draft_picks, events_from_transaction
from src.api import faab_analytics
from src.api.team_assignment import _resolve_favorite_key
from src.public_league import award_eligibility, luck, metrics, ownership, playoff_odds
from src.public_league.identity import build_manager_registry
from src.public_league.snapshot import SeasonSnapshot
from src.trade.faab_engine import current_nfl_week
from src.utils import owner_names

REPO = Path(__file__).resolve().parents[2]
LEAGUE = "1312006700437352448"
BLAINE = "1303549304882892800"
NEW = "1393410658032177152"
JOEL = "712035316776669184"
JOHN = "735693375101108224"
JASON = "468418790212759552"
ROSTER = 12
EFFECTIVE_WEEK = 7


def _record() -> dict:
    raw = json.loads(
        (REPO / "config/leagues/roster_ownership_changes.json").read_text(encoding="utf-8")
    )
    rows = [c for c in raw["changes"] if c["leagueId"] == LEAGUE and c["rosterId"] == ROSTER]
    assert len(rows) == 1
    return rows[0]


def _season() -> dict:
    return {
        "league": {"league_id": LEAGUE, "season": "2026"},
        "users": [
            {"user_id": NEW, "display_name": "schoeppeya", "metadata": {}},
            {"user_id": JOHN, "display_name": "jnesselhauf", "metadata": {}},
            {"user_id": JASON, "display_name": "JasonLeeTucker", "metadata": {}},
        ],
        "rosters": [
            {"roster_id": ROSTER, "owner_id": NEW},
            {"roster_id": 11, "owner_id": JOHN},
            {"roster_id": 1, "owner_id": JASON},
        ],
    }


# ── the committed record ───────────────────────────────────────────────


def test_the_roster_12_record_is_keyed_by_user_id_and_marked_pending():
    rec = _record()
    assert rec["season"] == "2026" and rec["leagueKey"] == "dynasty_main"
    assert (rec["fromOwnerId"], rec["fromUsername"]) == (BLAINE, "ughb")
    assert (rec["toOwnerId"], rec["toUsername"]) == (NEW, "schoeppeya")
    assert rec["effectiveWeek"] == EFFECTIVE_WEEK
    # Derived, not owner-confirmed (unlike roster 11): the record says so.
    assert "PENDING OWNER CONFIRMATION" in rec["source"]
    assert ownership.changes_for(LEAGUE, ROSTER)[0]["effectiveWeek"] == EFFECTIVE_WEEK


def test_the_league_week_clock_puts_the_takeover_before_week_7():
    """The new owner was first observed on 2026-10-20 and the roster was last
    seen under Blaine on 2026-10-19; both fall in week 6 on the league's own
    clock, and week 7 is the first week that opened after the takeover."""
    assert current_nfl_week(date(2026, 10, 19)) == (6, True)
    assert current_nfl_week(date(2026, 10, 20)) == (6, True)
    assert current_nfl_week(date(2026, 10, 22)) == (EFFECTIVE_WEEK, True)


# ── names ──────────────────────────────────────────────────────────────


def test_names_resolve_by_user_id_and_no_name_is_invented():
    assert owner_names.owner_name_for_user_id(BLAINE) == "Blaine"
    assert owner_names.owner_name_for_user_id(NEW) == "schoeppeya"
    assert owner_names.owner_label({"user_id": NEW, "display_name": "renamed"}) == "schoeppeya"
    assert owner_names.owner_label({"user_id": BLAINE, "display_name": "ughb"}) == "Blaine"
    # Two different people, never one name.
    assert owner_names.owner_name_for_user_id(NEW) != owner_names.owner_name_for_user_id(BLAINE)


def test_the_new_manager_does_not_inherit_blaines_favorite_team():
    cfg = json.loads((REPO / "config/team_assignment.json").read_text(encoding="utf-8"))
    favorites = cfg["favorites"]
    aliases = {k: v for k, v in cfg["displayNameAliases"].items() if not k.startswith("_")}
    assert _resolve_favorite_key("schoeppeya", favorites, aliases) is None
    assert _resolve_favorite_key("Blaine", favorites, aliases) == "blaine"
    assert _resolve_favorite_key("ughb", favorites, aliases) == "blaine"


def test_blaines_award_ruling_stays_keyed_to_his_user_id_and_is_not_inherited():
    """Updating the second assertion IS an owner decision (the owner extended
    the roster-11 ruling to John explicitly; nothing has done so for roster 12)."""

    def rule(owner):
        return award_eligibility.ineligibility(
            season="2026", league_id=LEAGUE, award="waiver_king", owner_id=owner
        )

    assert rule(BLAINE) is not None
    assert rule(NEW) is None


# ── week attribution ───────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("week", "expected"),
    [(0, BLAINE), (1, BLAINE), (6, BLAINE), (7, NEW), (8, NEW), (None, NEW)],
)
def test_owner_at_splits_the_season_at_week_seven(week, expected):
    assert ownership.owner_at(LEAGUE, ROSTER, NEW, week) == expected


@pytest.mark.parametrize(("week", "expected"), [(5, JOEL), (6, JOHN), (7, JOHN)])
def test_roster_11_is_untouched(week, expected):
    assert ownership.owner_at(LEAGUE, 11, JOHN, week) == expected


def test_resolve_owner_and_transaction_legs():
    registry = build_manager_registry([_season()])
    assert metrics.resolve_owner(registry, LEAGUE, ROSTER) == NEW
    assert metrics.resolve_owner(registry, LEAGUE, ROSTER, 6) == BLAINE
    assert metrics.resolve_owner(registry, LEAGUE, ROSTER, metrics.tx_week({"leg": 2})) == BLAINE
    assert metrics.resolve_owner(registry, LEAGUE, ROSTER, metrics.tx_week({"leg": 7})) == NEW


# ── identity ───────────────────────────────────────────────────────────


def test_blaine_keeps_an_identity_but_leaves_the_current_directory():
    registry = build_manager_registry([_season()])
    blaine = registry.by_owner_id[BLAINE]
    assert blaine.display_name == "Blaine" and blaine.is_retired
    assert [(a.season, a.roster_id) for a in blaine.aliases] == [("2026", ROSTER)]
    new = registry.by_owner_id[NEW]
    assert new.display_name == "schoeppeya" and new.current_roster_id == ROSTER
    current = [m.owner_id for m in registry.ordered_managers()]
    assert NEW in current and JOHN in current
    assert BLAINE not in current and JOEL not in current


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


@pytest.mark.parametrize(("leg", "expected"), [(6, BLAINE), (7, NEW)])
def test_acquisition_events_attribute_by_week(leg, expected):
    events = events_from_transaction(
        _waiver(leg),
        league_key="dynasty_main",
        sleeper_league_id=LEAGUE,
        season="2026",
        owner_by_roster={ROSTER: NEW},
    )
    assert events and all(e.after_owner_user_id == expected for e in events)


def test_draft_picks_belong_to_the_outgoing_owner():
    events = events_from_draft_picks(
        [{"roster_id": ROSTER, "player_id": "1234", "round": 1, "pick_no": 5, "draft_slot": 5}],
        draft_id="d2026",
        league_key="dynasty_main",
        sleeper_league_id=LEAGUE,
        season="2026",
        owner_by_roster={ROSTER: NEW},
    )
    assert events and all(e.after_owner_user_id == BLAINE for e in events)


def test_faab_analytics_attributes_by_week():
    class _Season:
        league_id = LEAGUE
        rosters = [{"roster_id": ROSTER, "owner_id": NEW}]

    assert faab_analytics._owner_for_roster(_Season, ROSTER, 6) == BLAINE
    assert faab_analytics._owner_for_roster(_Season, ROSTER, 7) == NEW
    assert faab_analytics._owner_for_roster(_Season, ROSTER) == NEW


# ── manager history splits; the team forecast follows the roster ───────


def _scored_season(weeks: int) -> SeasonSnapshot:
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
        users=[u for u in base["users"] if u["user_id"] in (NEW, JASON)],
        rosters=[r for r in base["rosters"] if r["owner_id"] in (NEW, JASON)],
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
    season = _scored_season(7)
    registry = build_manager_registry([_season()])

    by_week = luck._season_weekly_scores(season, registry)
    assert {o for o, _ in by_week[6]} == {BLAINE, JASON}
    assert {o for o, _ in by_week[7]} == {NEW, JASON}

    per_owner, _pool = playoff_odds._season_weekly_scores(season, registry)
    assert set(per_owner) == {NEW, JASON}
    assert per_owner[NEW] == [100.0 + wk for wk in range(1, 8)]
