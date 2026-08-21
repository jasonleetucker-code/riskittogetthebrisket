"""V1-41 / C3-CTX-01 — "Use Team Context" toggle, defaults ON.

Census before this unit: no trade surface consumed any canonical
team-context signal (Team Strength/Weakness/etc.) anywhere on `main` —
`src/trade/finder.py` and `src/trade/suggestions.py` both generated and
ranked trades off asset value alone. The finder's existing "light
roster-fit adjustment" block was the closest thing to team-context
awareness, but its "fills a need" arm used a raw position COUNT
(`<= ROSTER_WEAK_THRESHOLD`), never the canonical Team Weakness owner
(`src.roster_intel.weakness.build_team_weakness`, C2-WEAK-01).

The fix makes that arm consult the canonical owner (via
`build_league_roster_intelligence`) and gates the WHOLE roster-fit block
— both the "sheds surplus" and "fills a need" arms — behind
`use_team_context`, which defaults to ``True`` (ON). OFF suppresses the
block entirely: no bonus, no `roster_fit` / `addresses_urgent_need:*`
flags, no team-specific signal in the response at all.
"""

from __future__ import annotations

from src.trade.finder import find_trades

_SLOTS = ["QB", "RB", "RB", "WR", "WR", "WR", "TE", "FLEX"]


def _player(name: str, position: str, value: int, *, team: str = "KC"):
    return {
        "position": position,
        "team": team,
        "_finalAdjusted": value,
        "_sites": 4,
        "_canonicalSiteValues": {"ktcSfTep": value},
    }


def _row(name: str, position: str, value: int, *, player_id: str | None = None):
    return {
        "playerId": player_id or f"id_{name}",
        "canonicalName": name,
        "displayName": name,
        "legacyRef": name,
        "position": position,
        "rankDerivedValue": value,
    }


def _fixture():
    """Four teams. "Me" has ZERO TE on the roster against a 1-TE starter
    demand — a deterministic "unfilled" rung, which `_reduce` maps to
    `level == "critical"` regardless of rank thresholds. "Me" also
    carries 4 RB (>= ROSTER_SURPLUS_THRESHOLD) so the surplus arm has
    something to fire on independently. "Rival" owns a real TE that
    "Me" can target.
    """
    players: dict[str, dict] = {}
    rows: list[dict] = []
    teams: list[dict] = []

    def add(owner: str, name: str, pos: str, value: int, names: list[str]):
        players[name] = _player(name, pos, value)
        rows.append(_row(name, pos, value))
        names.append(name)

    # "Me": QB1, RB1-4 (surplus), WR1-3 — deliberately NO TE.
    me_names: list[str] = []
    add("me", "Me QB1", "QB", 6000, me_names)
    for i in range(4):
        add("me", f"Me RB{i}", "RB", 5000 - i * 100, me_names)
    for i in range(3):
        add("me", f"Me WR{i}", "WR", 4500 - i * 100, me_names)
    teams.append({"ownerId": "me", "name": "Me", "players": me_names})

    # "Rival": a full, unremarkable roster, including a real TE we can
    # target — priced well above the finder's asset-pool floor.
    rival_names: list[str] = []
    add("rival", "Rival QB1", "QB", 5800, rival_names)
    for i in range(2):
        add("rival", f"Rival RB{i}", "RB", 4800 - i * 100, rival_names)
    for i in range(2):
        add("rival", f"Rival WR{i}", "WR", 4200 - i * 100, rival_names)
    add("rival", "Rival TE1", "TE", 3800, rival_names)
    teams.append({"ownerId": "rival", "name": "Rival", "players": rival_names})

    # Two filler teams so `build_league_roster_intelligence`'s league-wide
    # rank population isn't degenerate at n=2.
    for ti in range(2, 4):
        owner = f"filler{ti}"
        names: list[str] = []
        add(owner, f"{owner} QB1", "QB", 5000, names)
        for i in range(2):
            add(owner, f"{owner} RB{i}", "RB", 4000 - i * 100, names)
        for i in range(2):
            add(owner, f"{owner} WR{i}", "WR", 3800 - i * 100, names)
        add(owner, f"{owner} TE1", "TE", 3000, names)
        teams.append({"ownerId": owner, "name": owner, "players": names})

    contract = {
        "meta": {"leagueKey": "test_league"},
        "playersArray": rows,
        "sleeper": {
            "rosterPositions": list(_SLOTS) + ["BN", "BN"],
            "teams": teams,
        },
    }
    return players, contract, teams


class TestTeamContextDefaultsOn:
    def test_omitting_use_team_context_behaves_as_on(self):
        players, contract, teams = _fixture()
        res = find_trades(
            players=players,
            my_team="Me",
            opponent_teams=["Rival"],
            sleeper_teams=teams,
            contract=contract,
        )
        assert res["metadata"]["teamContext"]["applied"] is True
        assert "TE" in res["metadata"]["teamContext"]["urgentPositions"]


class TestOnUsesTheCanonicalOwner:
    def test_a_trade_receiving_the_critical_need_position_is_flagged(self):
        players, contract, teams = _fixture()
        res = find_trades(
            players=players,
            my_team="Me",
            opponent_teams=["Rival"],
            sleeper_teams=teams,
            contract=contract,
            use_team_context=True,
        )
        te_trades = [t for t in res["trades"] if any(a["position"] == "TE" for a in t["receive"])]
        assert te_trades, "expected at least one candidate trade bringing in the TE"
        assert any("addresses_urgent_need:TE" in t.get("flags", []) for t in te_trades)
        assert any("roster_fit" in t.get("flags", []) for t in te_trades)

    def test_teamcontext_metadata_names_the_canonical_owner_result(self):
        players, contract, teams = _fixture()
        res = find_trades(
            players=players,
            my_team="Me",
            opponent_teams=["Rival"],
            sleeper_teams=teams,
            contract=contract,
            use_team_context=True,
        )
        tc = res["metadata"]["teamContext"]
        assert tc["applied"] is True
        assert tc["unavailableReason"] is None
        assert "TE" in tc["urgentPositions"]


class TestOffGenuinelySuppressesTeamContext:
    def test_off_stamps_no_bonus_and_no_flags(self):
        players, contract, teams = _fixture()
        res = find_trades(
            players=players,
            my_team="Me",
            opponent_teams=["Rival"],
            sleeper_teams=teams,
            contract=contract,
            use_team_context=False,
        )
        tc = res["metadata"]["teamContext"]
        assert tc["applied"] is False
        assert tc["unavailableReason"] == "context_off"
        assert tc["urgentPositions"] == []
        for t in res["trades"]:
            assert "roster_fit" not in t.get("flags", [])
            assert not any(f.startswith("addresses_urgent_need:") for f in t.get("flags", []))
            # ``rankingFactors["rosterFitBonus"]`` is stamped 0.0 as a
            # baseline default by the scorer itself, independent of this
            # toggle — OFF's obligation is that it never moves off that
            # default, not that the key vanishes.
            assert (t.get("rankingFactors") or {}).get("rosterFitBonus") == 0.0

    def test_on_and_off_are_genuinely_behaviorally_distinct(self):
        """Same fixture, only the toggle differs — scores must differ for
        any trade the ON run flagged as addressing the critical TE need."""
        players, contract, teams = _fixture()
        kwargs = dict(
            players=players,
            my_team="Me",
            opponent_teams=["Rival"],
            sleeper_teams=teams,
            contract=contract,
        )
        on_res = find_trades(**kwargs, use_team_context=True)
        off_res = find_trades(**kwargs, use_team_context=False)

        on_by_key = {
            (
                tuple(sorted(a["name"] for a in t["give"])),
                tuple(sorted(a["name"] for a in t["receive"])),
            ): t
            for t in on_res["trades"]
        }
        off_by_key = {
            (
                tuple(sorted(a["name"] for a in t["give"])),
                tuple(sorted(a["name"] for a in t["receive"])),
            ): t
            for t in off_res["trades"]
        }
        te_keys = [k for k in on_by_key if "Rival TE1" in k[1]]
        assert te_keys, "expected a shared TE-acquiring candidate in both runs"
        for key in te_keys:
            assert key in off_by_key, "OFF must not silently drop the same candidate"
            assert on_by_key[key]["arbitrageScore"] > off_by_key[key]["arbitrageScore"]
