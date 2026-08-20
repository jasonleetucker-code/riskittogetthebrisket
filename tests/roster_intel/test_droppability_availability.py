"""What "available" means on the waiver side of droppability (F8).

Integration's non-blocking finding 2.  The cut ladder measures a
release against what you could sign instead, so the waiver level is
load-bearing — and the two surfaces disagreed about who is signable.
``/api/draft/roster-context`` passes ``auction_rookie_keys(contract)``
(144 keys live); the roster chain defaulted to ``()``.

Measured on the live board with scarcity inert on both sides:

    WR  2036.0 -> 1519.0   (-25.4%)
    DL  1900.0 -> 1746.0   ( -8.1%)
    TE  1929.0 -> 1792.0   ( -7.1%)

The direction matters.  Counting the auction's own rookies as free
agents RAISES the replacement bar, which makes every cut look CHEAPER —
the exact defect ``src/draft/rookie_pool.py`` exists to prevent, arriving
by a different door.

Two separate "not available" states are pinned here, because collapsing
them is the failure the brief names:

* a player who is **not signable** must not set the waiver level;
* a rostered player the board **cannot price** must not read as free to
  release.
"""

from __future__ import annotations

from src.roster_intel.droppability import team_droppability

_SLOTS = ["QB", "WR"]


def _contract(*, rookie_values=(), fa_value=100.0):
    rows = [
        {"playerId": "id_QB1", "canonicalName": "QB1", "displayName": "QB1",
         "position": "QB", "rankDerivedValue": 900.0},
        {"playerId": "id_WR1", "canonicalName": "WR1", "displayName": "WR1",
         "position": "WR", "rankDerivedValue": 800.0},
        {"playerId": "id_SPARE", "canonicalName": "SPARE", "displayName": "SPARE",
         "position": "WR", "rankDerivedValue": 500.0},
        {"playerId": "id_FA", "canonicalName": "FA_WR", "displayName": "FA_WR",
         "position": "WR", "rankDerivedValue": fa_value},
    ]  # fmt: skip
    for i, value in enumerate(rookie_values):
        rows.append(
            {
                "playerId": f"id_ROOK{i}",
                "canonicalName": f"ROOK{i}",
                "displayName": f"ROOK{i}",
                "position": "WR",
                "rankDerivedValue": value,
                "rookie": True,
            }
        )
    return {
        "meta": {"leagueKey": "k"},
        "playersArray": rows,
        "sleeper": {
            "rosterPositions": list(_SLOTS) + ["BN", "BN"],
            "positions": {"QB1": "QB", "WR1": "WR", "SPARE": "WR"},
            "teams": [{"ownerId": "o1", "name": "T", "players": ["QB1", "WR1", "SPARE"]}],
        },
    }


# ══ An unsignable player must not set the waiver level ═════════════


def test_an_explicitly_unavailable_player_never_sets_the_waiver_level():
    contract = _contract()
    with_him = team_droppability(contract, owner_id="o1", unavailable_keys=())
    without = team_droppability(contract, owner_id="o1", unavailable_keys=["FA_WR"])
    assert with_him["waiverValues"]["WR"] == 100.0
    assert "WR" not in without["waiverValues"]


def test_excluding_the_unsignable_makes_cuts_dearer_never_cheaper():
    """The conservative direction, and the one that matters: a lower
    waiver level means a bigger gap between a rostered player and his
    replacement, so releasing him costs MORE. A default that inflates
    the waiver level is a default that under-prices every cut."""
    contract = _contract(fa_value=400.0)
    inflated = team_droppability(contract, owner_id="o1", unavailable_keys=())
    honest = team_droppability(contract, owner_id="o1", unavailable_keys=["FA_WR"])
    by_id_inflated = {r["playerId"]: r["effectiveCutCost"] for r in inflated["cutLadder"]["rungs"]}
    by_id_honest = {r["playerId"]: r["effectiveCutCost"] for r in honest["cutLadder"]["rungs"]}
    for pid, cost in by_id_inflated.items():
        assert by_id_honest.get(pid, cost) >= cost, pid


def test_the_waiver_population_is_stamped_so_exclusions_are_visible():
    """ "Not available" has to be legible. A silently smaller free-agent
    pool and a genuinely empty wire look identical in the numbers."""
    out = team_droppability(_contract(), owner_id="o1", unavailable_keys=["FA_WR"])
    pop = out["waiverPopulation"]
    assert pop["excludedKeys"] == 1
    assert pop["source"] == "caller"
    assert pop["freeAgents"] >= 0


def test_the_default_resolves_the_auction_rather_than_assuming_nothing_is_unavailable():
    """RED before the fix. ``unavailable_keys=()`` was the default, which
    is the claim "every unrostered player is signable" — and during a
    rookie auction that is false for every lot in it."""
    out = team_droppability(_contract(rookie_values=(700.0,)), owner_id="o1")
    assert out["waiverPopulation"]["source"] == "contract_auction_rookies"


def test_an_explicit_empty_tuple_still_means_nothing_is_unavailable():
    """Missing and explicitly-empty must stay distinguishable: ``None``
    asks the contract, ``()`` asserts there is nothing to exclude."""
    out = team_droppability(_contract(), owner_id="o1", unavailable_keys=())
    assert out["waiverPopulation"]["source"] == "caller"
    assert out["waiverPopulation"]["excludedKeys"] == 0


# ══ An unpriced ROSTERED player is not a free cut ══════════════════


def test_a_rostered_player_the_board_cannot_price_is_not_freely_droppable():
    """The other "not available". He is stamped ``assumedWaiver`` and
    surfaced for verification rather than presented as costless — the
    board's tail is "the noisiest number in the league", so a join miss
    on a real asset must not read as a free cut."""
    contract = _contract()
    contract["sleeper"]["teams"][0]["players"].append("GHOST")
    contract["sleeper"]["positions"]["GHOST"] = "WR"
    out = team_droppability(contract, owner_id="o1")
    ghost = next((r for r in out["cutLadder"]["rungs"] if r["name"] == "GHOST"), None)
    assert ghost is not None
    assert ghost["valueBasis"] == "assumedWaiver"
    assert "GHOST" in out["unmatchedRosterPlayers"]
    assert any("verify before releasing" in n for n in out["notes"])
