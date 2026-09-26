"""2026 Waiver King eligibility override — the rule itself (owner directive 2026-09-26).

Joel (owner 712035316776669184) and Blaine (owner 1303549304882892800) may
not WIN Waiver King in the 2026 season of the dynasty league
(1312006700437352448).  The rule is season-scoped, not date-scoped: it binds
2026 forever and nothing else.  Award-level behaviour (winner fall-through,
metric preservation, standings labels, other awards unaffected) is pinned in
``test_awards_standings.py``.
"""

from __future__ import annotations

import json

import pytest

from src.public_league import award_eligibility as ae

JOEL = "712035316776669184"
BLAINE = "1303549304882892800"
LEAGUE_2026 = "1312006700437352448"
OTHERS = [
    "468418790212759552",  # Jason
    "1002085133723299840",  # Brent
    "831633191830933504",  # Collin
    "711452264774041600",  # Ed
    "609821340567941120",  # Eric
    "1012114412049731584",  # Joey
    "1208452010173538304",  # Kich
    "714912789268865024",  # MaKayla
    "472206636534984704",  # Roy
    "473973924808355840",  # Ty
]


def _rule(owner, *, season="2026", league=LEAGUE_2026, award="waiver_king"):
    return ae.ineligibility(season=season, league_id=league, award=award, owner_id=owner)


@pytest.mark.parametrize("owner", [JOEL, BLAINE])
def test_2026_joel_and_blaine_are_ineligible_for_waiver_king(owner):
    hit = _rule(owner)
    assert hit is not None
    assert hit.reason == ae.OWNER_SEASON_OVERRIDE
    assert hit.label == "Ineligible for 2026 award"
    assert hit.override_id == "2026-waiver-king-joel-blaine"


@pytest.mark.parametrize("owner", OTHERS)
def test_2026_every_other_manager_is_eligible(owner):
    assert _rule(owner) is None


@pytest.mark.parametrize("owner", [JOEL, BLAINE])
def test_2027_starts_with_no_rule(owner):
    # A new season is a new label AND a new Sleeper league id; either alone
    # already frees them.
    assert _rule(owner, season="2027") is None
    assert _rule(owner, season="2027", league="1400000000000000000") is None


@pytest.mark.parametrize("owner", [JOEL, BLAINE])
def test_other_seasons_and_leagues_are_untouched(owner):
    assert _rule(owner, season="2025") is None
    assert _rule(owner, league="1320092771247222784") is None  # dynasty_new


@pytest.mark.parametrize(
    "award",
    [
        "manager_of_the_year",
        "trader_of_the_year",
        "league_mvp",
        "off_mvp",
        "def_mvp",
        "off_roy",
        "def_roy",
        "top_qb",
        "weekly_hammer",
        "bad_beat",
        "top_offense",
        "top_defense",
        "points_king",
        "regular_season_crown",
        "champion",
    ],
)
@pytest.mark.parametrize("owner", [JOEL, BLAINE])
def test_only_waiver_king_is_affected(owner, award):
    assert _rule(owner, award=award) is None


def test_the_rule_is_not_a_date_check(monkeypatch):
    """Viewing 2026 from 2028 still applies the 2026 rule: nothing reads a clock."""
    import datetime as _dt

    class _Future(_dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2028, 6, 1, tzinfo=tz)

        @classmethod
        def utcnow(cls):
            return cls(2028, 6, 1)

    monkeypatch.setattr(_dt, "datetime", _Future)
    assert _rule(JOEL) is not None
    assert _rule(BLAINE) is not None
    source = open(ae.__file__, encoding="utf-8").read()
    assert "datetime" not in source and "date.today" not in source


def test_season_rules_lists_exactly_one_award_for_2026():
    assert ae.season_rules(season="2026", league_id=LEAGUE_2026) == {
        "waiver_king": frozenset({JOEL, BLAINE})
    }
    assert ae.season_rules(season="2027", league_id=LEAGUE_2026) == {}


def test_the_rule_carries_its_provenance():
    raw = json.loads(ae._CONFIG_PATH.read_text(encoding="utf-8"))
    (rule,) = raw["overrides"]
    assert rule["type"] == "owner_season_eligibility_override"
    assert rule["season"] == "2026" and rule["award"] == "waiver_king"
    assert {o["ownerId"] for o in rule["owners"]} == {JOEL, BLAINE}
    assert rule["decidedBy"] and rule["decidedAt"] and rule["reason"]


@pytest.mark.parametrize(
    "bad",
    [
        {},
        {"overrides": [{"id": "x"}]},
        {
            "overrides": [
                {
                    "id": "x",
                    "season": "2026",
                    "leagueId": "1",
                    "award": "waiver_king",
                    "type": "owner_season_eligibility_override",
                    "publicLabel": "L",
                    "ineligibleOwnerIds": [],
                }
            ]
        },
        {
            "overrides": [
                {
                    "id": "x",
                    "season": "2026",
                    "leagueId": "1",
                    "award": "waiver_king",
                    "type": "something_else",
                    "publicLabel": "L",
                    "ineligibleOwnerIds": ["1"],
                }
            ]
        },
    ],
)
def test_a_malformed_rule_fails_loudly_rather_than_matching_nobody(bad):
    with pytest.raises(ValueError):
        ae._parse(bad)
