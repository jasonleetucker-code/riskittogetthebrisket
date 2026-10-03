"""Wave A — draft-capital correctness (owner directive 2026-10-03).

Three independent defects, each pinned RED-first against the pre-fix code:

1. **Draft year.** League-scoped surfaces used five different rules for
   "this league's upcoming draft" (Sleeper ``league.season`` + 1 on any
   complete draft; calendar year stepped past retired classes; calendar-year
   horizons of 3 and of 4 classes; ``season + 1, + 2``).  There is now ONE
   league-scoped resolver, ``pick_lifecycle.league_draft_years``, and every
   league-scoped surface agrees with it.  The BOARD's year (scoring-profile
   scope) is a separately named concept and is not touched.
2. **Double count.** The workbook payload's ``teamTotals`` cover one season
   but did not say which, so /trade re-added that season's owned picks.
   Both draft-capital payloads now state ``coveredPickYears``, stamp a stable
   team key and the canonical ``assetId`` on each pick row.
3. **Not-owned picks.** A team could be debited for a pick it does not hold
   (and the simulator removed a DIFFERENT owned pick by board row).  The
   simulator now resolves owned picks by canonical id through one ownership
   lookup (``src/identity/picks.py::lookup_league_pick_owner``) and reports a
   pick the team does not hold.

Generic picks stay repeatable hypothetical quantities (owner decision
2026-10-03, #1619) — they are priced, never debited from real inventory.
"""

from __future__ import annotations

import ast
import datetime
import functools
import re
import types
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from src.api import draft_class_evidence as dce
from src.api import terminal, trade_simulator
from src.identity import picks as pick_identity
from src.identity.pick_lifecycle import evidence_from_sleeper

REPO = Path(__file__).resolve().parents[2]
_SCRAPER = REPO / "Dynasty Scraper.py"
LEAGUE_ID = "WAVEA_LEAGUE"
YEAR = datetime.datetime.now(datetime.timezone.utc).year


def _retired_evidence(season: int, rostered: list[str], league_id: str = LEAGUE_ID):
    """A completed rookie draft of ``season`` whose picks are all rostered."""
    picks = [{"player_id": pid, "metadata": {"years_exp": "0"}} for pid in rostered]
    return evidence_from_sleeper(
        league_key=None,
        sleeper_league_id=league_id,
        drafts=[
            {
                "draft_id": f"d{season}",
                "season": str(season),
                "status": "complete",
                "settings": {"player_type": 1},
            }
        ],
        picks_by_draft_id={f"d{season}": picks},
        rostered_player_ids=rostered,
        observed_at="2026-10-03T00:00:00+00:00",
    )


# ── Defect 1: one league-scoped draft year ───────────────────────────────


def test_resolver_steps_past_this_leagues_retired_class_and_keeps_the_horizon():
    from src.identity.pick_lifecycle import league_draft_years, league_class_lifecycles

    ev = _retired_evidence(YEAR, ["P1", "P2"])
    years = league_draft_years(YEAR, league_class_lifecycles(range(YEAR, YEAR + 4), ev))
    assert years.upcoming_draft_year == YEAR + 1
    assert years.owned_pick_seasons == (YEAR + 1, YEAR + 2, YEAR + 3)
    assert years.retired_seasons == (YEAR,)


def test_resolver_with_no_evidence_retires_nothing():
    from src.identity.pick_lifecycle import league_draft_years

    years = league_draft_years(YEAR, None)
    assert years.upcoming_draft_year == YEAR
    assert years.owned_pick_seasons == (YEAR, YEAR + 1, YEAR + 2, YEAR + 3)


def test_anchor_is_a_floor_of_calendar_and_league_season_never_zero():
    from src.identity.pick_lifecycle import league_draft_anchor_year

    assert league_draft_anchor_year(None, calendar_year=2026) == 2026
    assert league_draft_anchor_year("2027", calendar_year=2026) == 2027
    assert league_draft_anchor_year("2025", calendar_year=2026) == 2026
    assert league_draft_anchor_year("garbage", calendar_year=2026) == 2026


# Scraper harness: lift ``fetch_sleeper_rosters`` without executing the
# module (importing it runs minutes of real work).


@functools.lru_cache(maxsize=1)
def _scraper_fetch_source() -> ast.Module:
    tree = ast.parse(_SCRAPER.read_text(encoding="utf-8"))
    wanted = {"fetch_sleeper_rosters", "_env_int"}
    chunks = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in wanted]
    assert {n.name for n in chunks} == wanted
    return ast.Module(body=chunks, type_ignores=[])


class _Resp:
    def __init__(self, status: int, body: Any = None):
        self.status_code = status
        self._body = body

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code != 200:
            raise RuntimeError(f"HTTP {self.status_code}")


def _sleeper_routes(rostered: list[str]) -> dict[str, _Resp]:
    picks = [{"player_id": pid, "metadata": {"years_exp": "0"}} for pid in rostered]
    return {
        "/players/nfl": _Resp(
            200,
            {pid: {"full_name": f"Player {pid}", "position": "WR"} for pid in rostered},
        ),
        f"/league/{LEAGUE_ID}/rosters": _Resp(
            200,
            [
                {"roster_id": 1, "owner_id": "oA", "players": rostered[:1]},
                {"roster_id": 2, "owner_id": "oB", "players": rostered[1:]},
            ],
        ),
        f"/league/{LEAGUE_ID}/users": _Resp(
            200,
            [
                {"user_id": "oA", "display_name": "Team A"},
                {"user_id": "oB", "display_name": "Team B"},
            ],
        ),
        f"/league/{LEAGUE_ID}/drafts": _Resp(
            200,
            [
                {
                    "draft_id": f"d{YEAR}",
                    "season": str(YEAR),
                    "status": "complete",
                    "settings": {"player_type": 1},
                }
            ],
        ),
        f"/draft/d{YEAR}/picks": _Resp(200, picks),
        f"/draft/d{YEAR}": _Resp(200, {}),
        f"/league/{LEAGUE_ID}/traded_picks": _Resp(200, []),
        f"/league/{LEAGUE_ID}": _Resp(
            200,
            {
                "name": "T",
                "season": str(YEAR),
                "settings": {"num_teams": 2, "draft_rounds": 2},
                "scoring_settings": {"rec": 1.0},
                "roster_positions": ["QB", "WR"],
            },
        ),
    }


def _scraper_owned_seasons(rostered: list[str]) -> set[int]:
    from src.identity.name_primitives import clean_name
    from src.utils.name_clean import resolve_idp_position
    from src.utils.owner_names import owner_label

    routes = _sleeper_routes(rostered)

    def get(url: str, timeout: Any = None):
        for suffix in sorted(routes, key=len, reverse=True):
            if url.endswith(suffix):
                return routes[suffix]
        return _Resp(404, None)

    ns: dict[str, Any] = {
        "re": re,
        "datetime": datetime,
        "os": __import__("os"),
        "requests": types.SimpleNamespace(get=get),
        "clean_name": clean_name,
        "_owner_label": owner_label,
        "_resolve_idp_position": resolve_idp_position,
        "_pick_identity": pick_identity,
        "DEBUG": False,
    }
    exec(compile(_scraper_fetch_source(), "<scraper-slice>", "exec"), ns)
    _names, roster_data = ns["fetch_sleeper_rosters"](LEAGUE_ID)
    return {int(d["season"]) for t in roster_data["teams"] for d in t["pickDetails"]}


def _overlay_owned_seasons(evidence) -> set[int]:
    from src.api import sleeper_overlay

    with patch.object(dce, "read_snapshot", lambda lid: evidence if lid == LEAGUE_ID else None):
        own = sleeper_overlay._build_pick_ownership(LEAGUE_ID, [1, 2], getter=lambda url: [])
    return {int(p["season"]) for plist in own.values() for p in plist}


def test_scraper_and_overlay_publish_the_same_owned_pick_horizon():
    """RED before Wave A: scraper {Y+1, Y+2, Y+3}, overlay {Y+1, Y+2}."""
    rostered = ["P1", "P2", "P3"]
    scraper = _scraper_owned_seasons(rostered)
    overlay = _overlay_owned_seasons(_retired_evidence(YEAR, rostered))
    assert scraper == {YEAR + 1, YEAR + 2, YEAR + 3}
    assert overlay == scraper


def test_every_league_scoped_surface_agrees_on_the_upcoming_draft():
    """A league whose current draft is complete and rostered while the BOARD
    still prices that class (the production state measured 2026-10-03)."""
    rostered = ["P1", "P2", "P3"]
    ev = _retired_evidence(YEAR, rostered)
    resolver = dce.league_draft_years_for(LEAGUE_ID, league_season=str(YEAR), evidence=ev)
    assert resolver.upcoming_draft_year == YEAR + 1

    # Overlay inventory starts at the upcoming draft.
    assert min(_overlay_owned_seasons(ev)) == resolver.upcoming_draft_year
    # Scraper inventory starts at the upcoming draft.
    assert min(_scraper_owned_seasons(rostered)) == resolver.upcoming_draft_year
    # Fallback route's year is the resolver's (snapshot evidence).
    with patch.object(dce, "read_snapshot", lambda lid: ev):
        assert dce.league_draft_years_for(LEAGUE_ID).upcoming_draft_year == YEAR + 1


def test_fallback_route_reads_the_canonical_resolver_not_a_local_rule():
    src = (REPO / "server.py").read_text(encoding="utf-8")
    body = src[
        src.index("def get_draft_capital(") : src.index('@app.get("/api/draft/roster-context")')
    ]
    assert "league_draft_years_for(" in body
    assert "active_seasons_for_league(" not in body
    assert "range(_dc_calendar_season" not in body


def test_workbook_path_no_longer_bumps_on_any_complete_draft():
    """The workbook path's local "complete draft → +1" is gone; the canonical
    resolver decides."""
    src = (REPO / "server.py").read_text(encoding="utf-8")
    body = src[src.index("def _fetch_draft_capital(") : src.index('@app.get("/api/draft-capital")')]
    assert "current_draft_complete" not in body
    assert "league_draft_years_for(" in body


def test_public_league_inventory_uses_the_resolver_horizon():
    from src.public_league import draft as pl_draft
    from src.public_league.snapshot import PublicLeagueSnapshot, SeasonSnapshot

    rostered = ["P1", "P2", "P3"]
    season = SeasonSnapshot(
        season=str(YEAR),
        league_id=LEAGUE_ID,
        league={"settings": {"draft_rounds": 2}},
        users=[],
        rosters=[{"roster_id": 1, "owner_id": "oA", "players": rostered}],
        matchups_by_week={},
        transactions_by_week={},
        drafts=[
            {
                "draft_id": f"d{YEAR}",
                "season": str(YEAR),
                "status": "complete",
                "settings": {"player_type": 1},
            }
        ],
        draft_picks_by_draft={
            f"d{YEAR}": [{"player_id": p, "metadata": {"years_exp": "0"}} for p in rostered]
        },
        traded_picks=[],
        winners_bracket=[],
        losers_bracket=[],
    )
    snap = PublicLeagueSnapshot(root_league_id=LEAGUE_ID, generated_at="x", seasons=[season])
    assert pl_draft._owned_pick_seasons(snap) == [str(YEAR + 1), str(YEAR + 2), str(YEAR + 3)]


# ── Defect 2: draft-capital payloads say what they cover ─────────────────


def test_fallback_payload_stamps_coverage_upcoming_year_team_keys_and_asset_ids(monkeypatch):
    from src.api import draft_capital_fallback as dcf
    from src.identity.pick_lifecycle import league_draft_years

    rosters = [
        {"roster_id": 1, "owner_id": "oA"},
        {"roster_id": 2, "owner_id": "oB"},
    ]
    users = [
        {"user_id": "oA", "display_name": "Alpha"},
        {"user_id": "oB", "display_name": "Bravo"},
    ]

    def fake_fetch(url):
        if url.endswith("/rosters"):
            return rosters
        if url.endswith("/users"):
            return users
        if url.endswith("/traded_picks"):
            return [{"season": str(YEAR + 1), "round": 1, "roster_id": 2, "owner_id": 1}]
        return None

    monkeypatch.setattr(dcf, "_fetch_json", fake_fetch)
    monkeypatch.setattr(
        "src.api.league_registry.league_key_for_sleeper_id", lambda lid: "wave_a_league"
    )
    contract = {
        "playersArray": [
            {"displayName": f"{YEAR + 1} Pick 1.0{s}", "rankDerivedValue": 1000 * s} for s in (1, 2)
        ]
    }
    years = league_draft_years(YEAR, None)
    out = dcf.build_sleeper_derived(
        LEAGUE_ID,
        contract,
        current_season=YEAR + 1,
        draft_rounds=1,
        league_draft_years=years,
    )
    assert out["upcomingDraftYear"] == YEAR + 1
    assert out["leagueDraftYears"]["scope"] == "league"
    assert out["coveredPickYears"] == [YEAR + 1]
    keyed = {r["team"]: (r["rosterId"], r["ownerId"]) for r in out["teamTotals"]}
    assert keyed == {"Alpha": (1, "oA"), "Bravo": (2, "oB")}
    ids = [p["assetId"] for p in out["picks"]]
    assert all(ids) and len(set(ids)) == len(ids)
    traded = next(p for p in out["picks"] if p["season"] == YEAR + 1 and p["originRosterId"] == 2)
    assert traded["currentOwnerRosterId"] == 1
    assert traded["assetId"] == f"pick:wave_a_league:{YEAR + 1}:r1:o2"


def _workbook_stub(url_map):
    import io
    import json as _json

    meta = url_map["__LEAGUE_META__"]

    def fake_urlopen(url, *args, **kwargs):
        target = url.full_url if hasattr(url, "full_url") else str(url)
        tail = target.split("/v1/league/", 1)[-1] if "/v1/league/" in target else ""
        if "/v1/league/" in target and "/" not in tail:
            return io.BytesIO(_json.dumps(meta).encode())
        for key, payload in url_map.items():
            if key != "__LEAGUE_META__" and key in target:
                return io.BytesIO(_json.dumps(payload).encode())
        raise OSError(f"unexpected urlopen({target})")

    return fake_urlopen


def _workbook_run(evidence):
    import server

    _, workbook_picks, slot_to_original, _, _, _ = server._parse_draft_data()
    if not workbook_picks or not slot_to_original:
        pytest.skip("Draft Data workbook unavailable")
    rosters, users, slot_to_roster = [], [], {}
    for slot, first in slot_to_original.items():
        rid = int(slot)
        rosters.append({"roster_id": rid, "owner_id": f"u{rid}", "players": []})
        users.append({"user_id": f"u{rid}", "display_name": f"Team-{first}", "metadata": {}})
        slot_to_roster[str(slot)] = rid
    url_map = {
        "/rosters": rosters,
        "/users": users,
        "/drafts": [
            {
                "draft_id": "D1",
                "season": str(YEAR),
                "status": "complete",
                "settings": {"player_type": 1},
            }
        ],
        "/traded_picks": [],
        "/draft/D1": {"slot_to_roster_id": slot_to_roster},
        "__LEAGUE_META__": {"season": str(YEAR)},
    }
    with (
        patch.object(server.urllib.request, "urlopen", _workbook_stub(url_map)),
        patch.object(server, "_sleeper_league_id_for_draft", return_value=LEAGUE_ID),
        patch.object(dce, "read_snapshot", lambda lid: evidence),
    ):
        return server._fetch_draft_capital(apply_sleeper_trades=True)


def test_workbook_payload_states_its_season_coverage_and_team_keys():
    """RED before Wave A: no ``coveredPickYears``, no ``upcomingDraftYear``,
    no ``rosterId`` — /trade fell back to the BOARD year and re-added every
    owned pick of the workbook's season."""
    out = _workbook_run(_retired_evidence(YEAR, ["P1"]))
    assert "error" not in out
    assert out["season"] == YEAR + 1
    assert out["upcomingDraftYear"] == YEAR + 1
    assert out["coveredPickYears"] == [YEAR + 1]
    assert all(r.get("rosterId") is not None for r in out["teamTotals"])
    assert {p["season"] for p in out["picks"]} == {YEAR + 1}


def test_workbook_season_without_proven_retirement_stays_on_the_anchor():
    """A complete draft whose rookies were never rostered is NOT retirement
    (the lifecycle owner's rule), so the workbook season is not bumped by a
    local rule either."""
    out = _workbook_run(_retired_evidence(YEAR, []))
    assert "error" not in out
    assert out["upcomingDraftYear"] == out["season"] == YEAR


# ── Defect 3: a team is never debited for a pick it does not hold ────────


PICK_VALUES = {"2027 Early 1st": 6000, "2027 Mid 1st": 5000, "2027 Late 1st": 4000}


def _owned_contract() -> dict:
    def row(name, value, pos, asset):
        return {
            "displayName": name,
            "canonicalName": name,
            "assetClass": asset,
            "position": pos,
            "pos": pos,
            "canonicalConsensusRank": 40,
            "rankChange": 0,
            "rankDerivedValue": value,
            "values": {"full": value},
        }

    def detail(label, origin):
        return {
            "season": 2027,
            "round": 1,
            "label": label,
            "assetId": f"pick:lk:2027:r1:o{origin}",
        }

    return {
        "playersArray": [
            row("Alice", 8000, "QB", "offense"),
            row("Carlo", 7000, "RB", "offense"),
            *[row(n, v, "PICK", "pick") for n, v in PICK_VALUES.items()],
        ],
        "sleeper": {
            "teams": [
                {
                    "ownerId": "o1",
                    "name": "Team Alpha",
                    "roster_id": 1,
                    "players": ["Alice"],
                    "picks": ["2027 Early 1st (own)", "2027 Late 1st (from Team Charlie)"],
                    "pickDetails": [
                        detail("2027 Early 1st (own)", 1),
                        detail("2027 Late 1st (from Team Charlie)", 3),
                    ],
                },
                {
                    "ownerId": "o2",
                    "name": "Team Bravo",
                    "roster_id": 2,
                    "players": ["Carlo"],
                    "picks": ["2027 Mid 1st (own)"],
                    "pickDetails": [detail("2027 Mid 1st (own)", 2)],
                },
                {
                    "ownerId": "o3",
                    "name": "Team Charlie",
                    "roster_id": 3,
                    "players": [],
                    "picks": [],
                    "pickDetails": [],
                },
            ],
        },
    }


def _sim(owner: str, **kw):
    contract = _owned_contract()
    team = terminal.resolve_team(contract, owner_id=owner, name=None)
    return trade_simulator.simulate_trade(contract, resolved_team=team, **kw)


def test_ownership_lookup_states():
    teams = _owned_contract()["sleeper"]["teams"]
    own = pick_identity.lookup_league_pick_owner(teams, "pick:lk:2027:r1:o2")
    assert (own.state, own.owner_roster_id) == ("owned", 2)
    absent = pick_identity.lookup_league_pick_owner(teams, "pick:lk:2027:r1:o9")
    assert absent.state == "absent"
    assert pick_identity.lookup_league_pick_owner(teams, "2027 Mid 1st").state == "absent"
    # An unpublished inventory (e.g. failed /traded_picks, #1618) is UNKNOWN,
    # never "nobody holds it" and never "the sender holds it".
    unpublished = [*teams[:2], {**teams[2], "pickDetails": None}]
    assert (
        pick_identity.lookup_league_pick_owner(unpublished, "pick:lk:2027:r1:o9").state == "unknown"
    )
    # Two teams claiming one id is UNKNOWN, never last-writer-wins.
    doubled = [
        teams[0],
        {**teams[1], "pickDetails": [*teams[1]["pickDetails"], teams[0]["pickDetails"][0]]},
    ]
    assert (
        pick_identity.lookup_league_pick_owner(doubled, "pick:lk:2027:r1:o1").reason
        == "conflicting_ownership_records"
    )


def test_sending_another_teams_owned_pick_is_reported_not_debited():
    result = _sim(
        "o1",
        players_in=["Carlo"],
        picks_out=["2027 Mid 1st (own)"],
        pick_asset_ids_out=["pick:lk:2027:r1:o2"],
    )
    checks = result["ownedPickChecks"]
    assert [c["actualOwnerRosterId"] for c in checks["notOwnedBySender"]] == [2]
    assert checks["notOwnedBySender"][0]["actualOwnerName"] == "Team Bravo"
    assert result["sending"] == []
    # Alpha's own picks are untouched: before + Carlo.
    assert result["after"]["totalValue"] == result["before"]["totalValue"] + 7000
    assert result["equity"] == 7000


def test_unheld_ownership_label_never_removes_a_different_owned_pick():
    """RED before Wave A: Alpha "sends" Bravo's 2027 Early 1st by its label.
    Alpha holds no such pick, but the board-row fallback removed Alpha's OWN
    "2027 Early 1st (own)" -- a different real pick -- while equity
    subtracted the sent value."""
    result = _sim("o1", picks_out=["2027 Early 1st (from Team Bravo)"])
    assert result["after"]["totalValue"] == result["before"]["totalValue"]
    assert result["ownedPickChecks"]["hypotheticalPicksOut"] == ["2027 Early 1st (from Team Bravo)"]


def test_generic_pick_is_hypothetical_and_never_debits_real_inventory():
    """RED before Wave A: a generic "2027 Late 1st" removed Alpha's real
    "2027 Late 1st (from Team Charlie)" via the board-row fallback."""
    result = _sim("o1", picks_out=["2027 Late 1st"])
    assert [a["name"] for a in result["sending"]] == ["2027 Late 1st"]
    assert result["equity"] == -4000
    assert result["after"]["totalValue"] == result["before"]["totalValue"]
    assert result["ownedPickChecks"]["hypotheticalPicksOut"] == ["2027 Late 1st"]


def test_owned_id_removes_exactly_that_pick():
    result = _sim(
        "o1",
        picks_out=["2027 Late 1st"],
        pick_asset_ids_out=["pick:lk:2027:r1:o3"],
    )
    assert result["ownedPickChecks"]["notOwnedBySender"] == []
    assert result["sending"][0]["assetId"] == "pick:lk:2027:r1:o3"
    assert result["after"]["totalValue"] == result["before"]["totalValue"] - 4000


def test_one_real_pick_counts_at_most_once():
    result = _sim(
        "o1",
        picks_out=["2027 Late 1st", "2027 Late 1st"],
        pick_asset_ids_out=["pick:lk:2027:r1:o3", "pick:lk:2027:r1:o3"],
        picks_in=["2027 Early 1st (own)"],
        pick_asset_ids_in=["pick:lk:2027:r1:o1"],
    )
    checks = result["ownedPickChecks"]
    assert len(result["sending"]) == 1
    assert [c["direction"] for c in checks["repeatedOwnedPick"]] == ["out"]
    # Alpha already holds its own 2027 1st: not credited a second time.
    assert [c["assetId"] for c in checks["alreadyOwnedByReceiver"]] == ["pick:lk:2027:r1:o1"]
    assert result["receiving"] == []
    assert result["after"]["totalValue"] == result["before"]["totalValue"] - 4000


def test_generic_picks_stay_repeatable_quantities():
    result = _sim("o2", players_out=["Carlo"], picks_in=["2027 Mid 1st"] * 3)
    assert [a["name"] for a in result["receiving"]] == ["2027 Mid 1st"] * 3
    assert result["equity"] == 3 * 5000 - 7000


def test_analyze_names_the_not_owned_pick():
    from src.trade.analyze_trade import analyze_trade

    sim = _sim(
        "o1",
        players_in=["Carlo"],
        picks_out=["2027 Mid 1st (own)"],
        pick_asset_ids_out=["pick:lk:2027:r1:o2"],
    )
    out = analyze_trade(sim)
    text = repr(out)
    assert "Not held by this team" in text and "Team Bravo" in text
