"""Manager Intelligence Batch E — career record and archetypes.

Fixture-based (no network): a fake Sleeper universe of chained season
leagues is served through injected classified fetchers.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.intel import manager_activity as ma
from src.intel import manager_career as mc
from src.public_league import ownership, sleeper_client

OK = sleeper_client.FETCH_OK
USER = "u1"


def _roster(rid: int, owner: str | None, *, wins=0, losses=0, ties=0, fpts=0, co=None) -> dict:
    return {
        "roster_id": rid,
        "owner_id": owner,
        "co_owners": co,
        "players": [],
        "settings": {"wins": wins, "losses": losses, "ties": ties, "fpts": fpts, "fpts_decimal": 0},
    }


def _league(lid: str, season: str, prev: str, *, status="complete", type_=2, teams=4) -> dict:
    return {
        "league_id": lid,
        "name": f"League {lid}",
        "season": season,
        "status": status,
        "previous_league_id": prev,
        "total_rosters": teams,
        "settings": {"type": type_},
        "roster_positions": ["QB", "RB", "SUPER_FLEX", "BN"],
    }


#: A bracket in which roster 1 beats 2 in the final, 3 and 4 lose round 1.
BRACKET = [
    {"m": 1, "r": 1, "t1": 1, "t2": 4, "w": 1, "l": 4},
    {"m": 2, "r": 1, "t1": 2, "t2": 3, "w": 2, "l": 3},
    {"m": 3, "r": 2, "p": 1, "t1": 1, "t2": 2, "w": 1, "l": 2, "t1_from": {"w": 1}},
]


class Universe:
    """League objects, rosters and brackets by league id, plus call logs."""

    def __init__(self) -> None:
        self.leagues: dict[str, dict] = {}
        self.rosters: dict[str, list] = {}
        self.brackets: dict[str, Any] = {}
        self.fail: dict[tuple[str, str], str] = {}
        self.calls: list[tuple[str, str]] = []
        self.current: list[dict] = []

    def _get(self, kind: str, lid: str, store: dict) -> tuple[str, Any]:
        self.calls.append((kind, lid))
        if (kind, lid) in self.fail:
            return self.fail[(kind, lid)], None
        if lid not in store:
            return sleeper_client.FETCH_NOT_FOUND, None
        return OK, store[lid]

    def kwargs(self, **over: Any) -> dict[str, Any]:
        kw = {
            "fetch_user": lambda name: (
                (OK, {"user_id": USER, "username": name, "display_name": "Manager One"})
                if name != "ghost"
                else (sleeper_client.FETCH_NOT_FOUND, None)
            ),
            "fetch_leagues": lambda uid, season: (OK, self.current),
            "fetch_league": lambda lid: self._get("league", lid, self.leagues),
            "fetch_rosters": lambda lid: self._get("rosters", lid, self.rosters),
            "fetch_bracket": lambda lid: self._get("bracket", lid, self.brackets),
            "fetch_state": lambda: {"season": "2026", "league_season": "2026"},
            "include_archetypes": False,
            "now": lambda: 1_790_000_000.0,
        }
        kw.update(over)
        return kw


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    ma.reset_caches()
    mc.reset_cache()
    monkeypatch.setattr(ownership, "all_changes", lambda: [])
    yield
    ma.reset_caches()
    mc.reset_cache()


def _chain_universe() -> Universe:
    """2026 (in season) → 2025 → 2024 → 2023, with roster ids and ownership
    changing every season (Sleeper mints new ids per season)."""
    u = Universe()
    u.leagues = {
        "L26": _league("L26", "2026", "L25", status="in_season"),
        "L25": _league("L25", "2025", "L24"),
        "L24": _league("L24", "2024", "L23"),
        "L23": _league("L23", "2023", "0"),
    }
    u.current = [u.leagues["L26"]]
    u.rosters = {
        "L26": [_roster(1, "x"), _roster(3, USER, wins=4, losses=1, fpts=500)]
        + [_roster(2, "y"), _roster(4, "z")],
        # 2025: the manager is roster 1 — champion.
        "L25": [
            _roster(1, USER, wins=10, losses=4, fpts=1500),
            _roster(2, "x", wins=9, losses=5, fpts=1400),
            _roster(3, "y", wins=5, losses=9, fpts=1100),
            _roster(4, "z", wins=4, losses=10, fpts=1000),
        ],
        # 2024: the manager held no roster — absent, not a loss.
        "L24": [
            _roster(1, "x", wins=9, losses=5, fpts=1300),
            _roster(2, "y", wins=8, losses=6, fpts=1200),
            _roster(3, "z", wins=7, losses=7, fpts=1100),
            _roster(4, "w", wins=4, losses=10, fpts=1000),
        ],
        # 2023: the manager CO-owns roster 3 — missed the playoffs.
        "L23": [
            _roster(1, "x", wins=9, losses=5, fpts=1300),
            _roster(2, "y", wins=8, losses=6, fpts=1200),
            _roster(3, "z", wins=7, losses=7, fpts=1000, co=[USER]),
            _roster(4, "w", wins=4, losses=10, fpts=900),
        ],
    }
    # 2023: a two-team bracket that roster 3 did not make.
    u.brackets = {
        "L25": BRACKET,
        "L24": BRACKET,
        "L23": [{"m": 1, "r": 1, "p": 1, "t1": 1, "t2": 2, "w": 2, "l": 1}],
    }
    return u


def test_chain_walk_follows_id_changes_and_attributes_by_user_id():
    u = _chain_universe()
    out = mc.build_manager_career("someone", **u.kwargs())
    assert out["status"] == "ok"
    seasons = {s["season"]: s for s in out["seasons"]}
    assert set(seasons) == {"2026", "2025", "2023"}
    assert seasons["2025"]["rosterId"] == 1 and seasons["2025"]["finish"] == "champion"
    assert seasons["2026"]["rosterId"] == 3
    lg = out["leagues"][0]
    assert lg["chain"]["state"] == sleeper_client.CHAIN_COMPLETE
    assert lg["seasonsWalked"] == 4 and lg["notHeldSeasons"] == ["2024"]
    # The current season's league object came with the user's league list.
    assert ("league", "L26") not in u.calls
    # The in-progress season reads no bracket; the absent season none either.
    assert ("bracket", "L26") not in u.calls and ("bracket", "L24") not in u.calls


def test_season_not_held_is_absent_not_a_loss():
    u = _chain_universe()
    t = mc.build_manager_career("someone", **u.kwargs())["totals"]
    # 2025 (10-4) + 2023 (7-7); 2024 contributes nothing; 2026 is in progress.
    assert t["record"] == {
        "wins": 17,
        "losses": 11,
        "ties": 0,
        "games": 28,
        "winPct": round(17 / 28, 4),
        "seasonsCovered": 2,
    }
    assert t["seasons"] == 3 and t["countedSeasons"] == 2
    assert t["excluded"] == {"season_in_progress": 1}
    assert t["titles"] == {"count": 1, "seasonsCovered": 2}
    assert t["playoffAppearances"] == {"count": 1, "seasonsCovered": 2, "rate": 0.5}


def test_co_owner_season_is_held():
    u = _chain_universe()
    seasons = {s["season"]: s for s in mc.build_manager_career("x", **u.kwargs())["seasons"]}
    assert seasons["2023"]["coOwned"] is True
    assert seasons["2023"]["held"] == "full"
    assert seasons["2023"]["finish"] == "missed"
    assert seasons["2023"]["countsTowardTotals"] is True


def test_points_for_share_and_index():
    u = _chain_universe()
    out = mc.build_manager_career("x", **u.kwargs())
    s25 = next(s for s in out["seasons"] if s["season"] == "2025")
    assert s25["pointsForShare"] == round(1500 / 5000, 4)
    idx = out["totals"]["pointsForIndex"]
    assert idx["seasonsCovered"] == 2
    assert idx["mean"] == round((0.3 * 4 + round(1000 / 4400, 4) * 4) / 2, 3)


@pytest.mark.parametrize("kind", [sleeper_client.FETCH_ERROR, sleeper_client.FETCH_RATE_LIMITED])
def test_unreadable_bracket_is_unknown_finish_never_missed(kind):
    u = _chain_universe()
    u.fail[("bracket", "L25")] = kind
    out = mc.build_manager_career("x", **u.kwargs())
    s25 = next(s for s in out["seasons"] if s["season"] == "2025")
    assert s25["finish"] == "unknown"
    assert s25["finishReason"] in ("bracket_unavailable", "bracket_rate_limited")
    assert s25["coverageState"] == "partial"
    assert out["status"] == "partial"
    t = out["totals"]
    # Still a counted season (its record is real) but its finish covers nothing.
    assert t["titles"] == {"count": 0, "seasonsCovered": 1}
    assert t["unknownFinishes"] == 1
    assert t["record"]["seasonsCovered"] == 2


def test_missing_bracket_body_is_unknown():
    u = _chain_universe()
    del u.brackets["L25"]  # Sleeper answers null → not_found
    s25 = next(
        s for s in mc.build_manager_career("x", **u.kwargs())["seasons"] if s["season"] == "2025"
    )
    assert s25["finish"] == "unknown"


def test_playoff_finish_helper():
    assert mc.playoff_finish(BRACKET, 1) == ("champion", None, True)
    assert mc.playoff_finish(BRACKET, 2) == ("runner_up", None, True)
    assert mc.playoff_finish(BRACKET, 3) == ("playoff", None, True)
    assert mc.playoff_finish(BRACKET, 9) == ("missed", None, True)
    assert mc.playoff_finish(None, 1)[0] == "unknown"
    assert mc.playoff_finish([], 1)[0] == "unknown"
    undecided = [dict(m) for m in BRACKET]
    undecided[2]["w"] = None
    undecided[2]["l"] = None
    finish, reason, decided = mc.playoff_finish(undecided, 1)
    assert (finish, reason, decided) == ("playoff", "championship_undecided", False)


def test_undecided_championship_does_not_cover_titles():
    u = _chain_universe()
    b = [dict(m) for m in BRACKET]
    b[2]["w"] = b[2]["l"] = None
    u.brackets["L25"] = b
    t = mc.build_manager_career("x", **u.kwargs())["totals"]
    assert t["titles"] == {"count": 0, "seasonsCovered": 1}
    assert t["playoffAppearances"]["count"] == 1


def test_recorded_handoff_joined_mid_season_is_shown_but_not_totalled(monkeypatch):
    u = _chain_universe()
    monkeypatch.setattr(
        ownership,
        "all_changes",
        lambda: [
            {
                "leagueId": "L25",
                "rosterId": 1,
                "season": "2025",
                "effectiveWeek": 6,
                "fromOwnerId": "old",
                "toOwnerId": USER,
            }
        ],
    )
    out = mc.build_manager_career("x", **u.kwargs())
    s25 = next(s for s in out["seasons"] if s["season"] == "2025")
    assert s25["held"] == "from_week" and s25["heldFromWeek"] == 6
    assert s25["countsTowardTotals"] is False
    assert s25["excludedReason"] == "partial_season_handoff"
    assert out["totals"]["excluded"]["partial_season_handoff"] == 1
    assert out["totals"]["titles"]["count"] == 0


def test_recorded_handoff_left_mid_season_is_theirs_until_that_week(monkeypatch):
    u = _chain_universe()
    monkeypatch.setattr(
        ownership,
        "all_changes",
        lambda: [
            {
                "leagueId": "L24",
                "rosterId": 2,
                "season": "2024",
                "effectiveWeek": 9,
                "fromOwnerId": USER,
                "toOwnerId": "y",
            }
        ],
    )
    out = mc.build_manager_career("x", **u.kwargs())
    s24 = next(s for s in out["seasons"] if s["season"] == "2024")
    assert s24["held"] == "until_week" and s24["heldUntilWeek"] == 9
    assert s24["finish"] is None and s24["finishReason"] == "left_before_season_end"
    assert s24["countsTowardTotals"] is False
    assert ("bracket", "L24") not in u.calls
    assert out["leagues"][0]["notHeldSeasons"] == []


def test_rate_limited_predecessor_marks_chain_unverified():
    u = _chain_universe()
    u.fail[("league", "L24")] = sleeper_client.FETCH_RATE_LIMITED
    out = mc.build_manager_career("x", **u.kwargs())
    chain = out["leagues"][0]["chain"]
    assert chain["state"] == sleeper_client.CHAIN_UNVERIFIED
    assert chain["reason"] == "predecessor_rate_limited"
    assert out["status"] == "partial"
    assert out["coverage"]["chainsIncomplete"] == ["L26"]


def test_budget_exhaustion_is_flagged():
    u = _chain_universe()
    out = mc.build_manager_career("x", **u.kwargs(call_budget=3))
    assert out["coverage"]["budgetExhausted"] is True
    assert out["status"] == "partial"
    assert out["coverage"]["callsSpent"] == 3


def test_season_bound_truncates_and_reports():
    u = _chain_universe()
    out = mc.build_manager_career("x", **u.kwargs(max_seasons=2))
    assert out["leagues"][0]["chain"]["state"] == sleeper_client.CHAIN_TRUNCATED
    assert out["coverage"]["chainsTruncated"] == ["L26"]
    assert {s["season"] for s in out["seasons"]} == {"2026", "2025"}


def test_non_dynasty_predecessor_stops_the_chain():
    u = _chain_universe()
    u.leagues["L24"]["settings"]["type"] = 0
    lg = mc.build_manager_career("x", **u.kwargs())["leagues"][0]
    assert lg["chain"]["state"] == sleeper_client.CHAIN_NON_DYNASTY
    assert lg["seasonsWalked"] == 2


def test_unread_rosters_is_unknown_not_absent():
    u = _chain_universe()
    u.fail[("rosters", "L25")] = sleeper_client.FETCH_ERROR
    out = mc.build_manager_career("x", **u.kwargs())
    s25 = next(s for s in out["seasons"] if s["season"] == "2025")
    assert s25["held"] is None and s25["coverageState"] == "unavailable"
    assert out["leagues"][0]["notHeldSeasons"] == ["2024"]
    assert out["status"] == "partial"
    assert out["totals"]["seasons"] == 2  # an unread season is not a season held


def test_not_found_user():
    u = _chain_universe()
    assert mc.build_manager_career("ghost", **u.kwargs())["status"] == "not_found"


def test_cached_career_memoises_ok_only():
    u = _chain_universe()
    first = mc.cached_manager_career("x", **u.kwargs())
    n = len(u.calls)
    second = mc.cached_manager_career("X", **u.kwargs())
    assert first["cached"] is False and second["cached"] is True
    assert len(u.calls) == n


# ── archetypes ──────────────────────────────────────────────────────────


def _activity(**over: Any) -> dict[str, Any]:
    payload = {
        "status": "ok",
        "tendencies": {
            "tradeCount": 6,
            "pieces": {"counts": {"consolidation": 3, "depth": 1, "even": 2}},
        },
        "acquisitions": [{"method": "WAIVER", "player": {"isRookie": i < 3}} for i in range(10)]
        + [{"method": "DRAFT", "player": {"isRookie": True}} for _ in range(5)],
        "analytics": {"byMethod": {"WAIVER": 10, "DRAFT": 5}},
        "coverage": {"leagues": [{"rosterHeld": True}, {"rosterHeld": True}]},
        "draftCapital": {
            "available": True,
            "totals": {
                "picksHeld": 12,
                "acquiredHeld": 6,
                "ownTradedAway": 2,
                "leaguesObserved": 2,
                "leaguesUnavailable": 0,
            },
        },
    }
    payload.update(over)
    return payload


def _profile(age_mean=25.0, age_n=40) -> dict[str, Any]:
    return {"status": "ok", "summary": {"ageMean": age_mean, "ageKnownPlayers": age_n}}


def _by_key(out: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {i["key"]: i for i in out["items"]}


def test_archetype_thresholds_at_and_below():
    out = mc.evaluate_archetypes(profile=_profile(), activity=_activity(), career=None)
    items = _by_key(out)
    # 3 of 6 trades consolidated = exactly the 0.50 prior → suggested.
    assert items["consolidator"]["state"] == "suggested"
    assert items["consolidator"]["evidence"] == {"matching": 3, "trades": 6, "share": 0.5}
    assert items["depth_builder"]["state"] == "not_suggested"
    # 3 rookies of 10 non-draft adds = 0.30 → suggested; draft picks excluded.
    assert items["rookie_focused"]["evidence"]["nonDraftAcquisitions"] == 10
    assert items["rookie_focused"]["state"] == "suggested"
    # own picks = (12 - 6) + 2 = 8; ratio 1.5 → hoarder at the threshold.
    assert items["pick_hoarder"]["evidence"]["ownPicks"] == 8
    assert items["pick_hoarder"]["state"] == "suggested"
    assert items["pick_seller"]["state"] == "not_suggested"
    # 6 trades / 2 leagues = 3.0 → active; 10 adds / 2 = 5 < 8 → not waiver-active.
    assert items["active_trader"]["state"] == "suggested"
    assert items["waiver_active"]["state"] == "not_suggested"
    assert items["rebuilding"]["state"] == "not_suggested"  # 25.0 > 24.5
    assert items["win_now"]["state"] == "not_suggested"
    # No career supplied → the career archetype is unavailable, not "no".
    assert items["playoff_regular"]["state"] == "unavailable"
    assert set(out["suggested"]) == {
        "consolidator",
        "rookie_focused",
        "pick_hoarder",
        "active_trader",
    }


def test_archetype_insufficient_sample_refuses():
    act = _activity(
        tendencies={"tradeCount": 4, "pieces": {"counts": {"consolidation": 4}}},
        coverage={"leagues": [{"rosterHeld": False}]},
    )
    items = _by_key(mc.evaluate_archetypes(profile=_profile(age_n=10), activity=act, career=None))
    assert items["consolidator"]["state"] == "insufficient_sample"
    assert "Insufficient sample" in items["consolidator"]["statement"]
    assert items["active_trader"]["state"] == "insufficient_sample"  # no held league
    assert items["rebuilding"]["state"] == "insufficient_sample"  # 10 ages < 25


def test_archetype_unavailable_sources_and_partial_flag():
    items = _by_key(mc.evaluate_archetypes(profile=None, activity=None, career=None))
    assert all(i["state"] == "unavailable" for i in items.values())
    partial = _by_key(
        mc.evaluate_archetypes(
            profile=_profile(), activity=_activity(status="partial"), career=None
        )
    )
    assert partial["consolidator"]["evidenceComplete"] is False
    no_dc = _by_key(
        mc.evaluate_archetypes(
            profile=_profile(),
            activity=_activity(draftCapital={"available": False, "reason": "earlier_season"}),
            career=None,
        )
    )
    assert no_dc["pick_hoarder"]["state"] == "unavailable"
    assert no_dc["win_now"]["state"] == "unavailable"


def test_win_now_and_rebuilding_rules():
    old_few = _activity()
    old_few["draftCapital"]["totals"].update(picksHeld=6, acquiredHeld=0, ownTradedAway=6)
    items = _by_key(mc.evaluate_archetypes(profile=_profile(27.0), activity=old_few, career=None))
    assert items["win_now"]["state"] == "suggested"
    assert items["pick_seller"]["state"] == "suggested"  # 6 / 12 = 0.5
    young = _by_key(
        mc.evaluate_archetypes(profile=_profile(24.0), activity=_activity(), career=None)
    )
    assert young["rebuilding"]["state"] == "suggested"
    assert young["win_now"]["state"] == "not_suggested"


def test_playoff_regular_from_career_and_none_suggested_is_allowed():
    career = {"playoffAppearances": {"count": 3, "seasonsCovered": 5, "rate": 0.6}}
    items = _by_key(mc.evaluate_archetypes(profile=None, activity=None, career=career))
    assert items["playoff_regular"]["state"] == "suggested"
    few = {"playoffAppearances": {"count": 3, "seasonsCovered": 3, "rate": 1.0}}
    out = mc.evaluate_archetypes(profile=None, activity=None, career=few)
    assert _by_key(out)["playoff_regular"]["state"] == "insufficient_sample"
    assert out["suggested"] == []


def test_archetypes_declare_priors_and_use_evidence_wording():
    out = mc.evaluate_archetypes(profile=_profile(), activity=_activity(), career=None)
    for item in out["items"]:
        assert item["threshold"]["basis"] == "PRIOR"
        assert item["minSample"]["basis"] == "PRIOR"
        if item["state"] == "suggested":
            assert item["statement"].startswith("Evidence suggests")
        for word in ("cheat", "collud", "always", "never", "is a "):
            assert word not in item["statement"].lower()


def test_career_attaches_archetypes_from_providers():
    u = _chain_universe()
    seen: dict[str, Any] = {}

    def profile_provider(username, **kw):
        seen["profile"] = kw
        return _profile()

    def activity_provider(username, **kw):
        seen["activity"] = kw
        return _activity()

    out = mc.build_manager_career(
        "x",
        **u.kwargs(
            include_archetypes=True,
            profile_provider=profile_provider,
            activity_provider=activity_provider,
        ),
    )
    assert seen["activity"]["window"] == "season"
    assert out["archetypes"]["sources"] == {"activity": "ok", "profile": "ok", "career": True}
    assert "consolidator" in out["archetypes"]["suggested"]


def test_provider_exception_makes_archetypes_unavailable_not_500():
    u = _chain_universe()

    def boom(*_a, **_k):
        raise RuntimeError("x")

    out = mc.build_manager_career(
        "x", **u.kwargs(include_archetypes=True, profile_provider=boom, activity_provider=boom)
    )
    items = _by_key(out["archetypes"])
    assert items["consolidator"]["state"] == "unavailable"
    assert out["status"] == "ok"


def test_career_payload_names_no_other_manager():
    """Privacy: the career is the searched manager's own seasons; other
    rosters' owner ids never appear (only league-wide points totals are read)."""
    import json

    u = _chain_universe()
    blob = json.dumps(mc.build_manager_career("someone", **u.kwargs()))
    for other in ('"x"', '"y"', '"z"', '"w"'):
        assert other not in blob
