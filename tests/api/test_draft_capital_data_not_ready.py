"""``/api/draft-capital`` returned 200 with invented pick values.

Backlog defect #10, and it is worse than "returns 200 where 503 is
expected" suggests. The non-default-league path reads pick values
through ``draft_capital_fallback._pick_value_from_contract``, which
falls through to a HARDCODED table when the contract cannot answer::

    round 1 -> 7000.0    round 3 -> 2000.0
    round 2 -> 4000.0    round 4 -> 1200.0

So with no contract loaded the endpoint did not return an empty board —
it returned a complete one, at HTTP 200, full of numbers a caller cannot
distinguish from the Hill-curve-calibrated real ones. Plausible and
wrong is the worst combination available.

CLAUDE.md already specified the fix, and had for as long as the
endpoint has existed:

    /api/terminal, /api/trade/*, /api/angle/*, /api/draft-capital —
    503 whenever the loaded contract's leagueKey doesn't match the
    request.

The guard is scoped to the non-default path on purpose: the default
league is served from ``CSVs/Draft Data.xlsx`` and never consults the
contract, so 503-ing it on a cold contract would break the one league
that never needed the guard.
"""

from __future__ import annotations

import pytest

from src.api.draft_capital_fallback import _pick_value_from_contract


# ── The reason a 200 was dangerous ───────────────────────────────────


def test_an_absent_contract_yields_fabricated_values_not_zero():
    """This is why the missing guard mattered.

    Had the fallback returned 0 or None, an empty board would have made
    the problem visible at the UI. It returns confident round-based
    constants instead, so nothing downstream can tell.

    Pinning the behaviour rather than changing it: the flat table is a
    reasonable last resort for a *partially* populated contract. What
    was wrong was reaching it with no contract at all.
    """
    assert _pick_value_from_contract({}, 2027, 1, 1) == 7000.0
    assert _pick_value_from_contract({}, 2027, 2, 1) == 4000.0
    assert _pick_value_from_contract({}, 2027, 3, 1) == 2000.0


def test_a_populated_contract_wins_over_the_flat_table():
    """Non-vacuity for the guard: the real path must genuinely differ,
    or 503-ing on an absent contract would be protecting nothing."""
    contract = {
        "playersArray": [
            {"displayName": "2027 Pick 1.01", "rankDerivedValue": 8123.0},
        ]
    }
    assert _pick_value_from_contract(contract, 2027, 1, 1) == 8123.0


# ── The route contract ───────────────────────────────────────────────


@pytest.fixture
def client(tmp_path, monkeypatch):
    """A two-league registry, so the non-default path actually runs.

    The first draft of this file read whatever registry the environment
    happened to hold and skipped when it found no non-default league —
    which is what CI holds, so the two guards that matter never
    executed. A guard that skips is not a guard; §6.15 applies to the
    tests written against it as much as to the code.
    """
    import json

    from fastapi.testclient import TestClient

    import server
    from src.api import league_registry

    path = tmp_path / "registry.json"
    path.write_text(
        json.dumps(
            {
                "defaultLeagueKey": "dc_main",
                "leagues": [
                    {
                        "key": "dc_main",
                        "displayName": "DC Main",
                        "sleeperLeagueId": "L-DC-MAIN",
                        "scoringProfile": "prof_a",
                        "active": True,
                        "rosterSettings": {"teamCount": 12},
                    },
                    {
                        "key": "dc_side",
                        "displayName": "DC Side",
                        "sleeperLeagueId": "L-DC-SIDE",
                        "scoringProfile": "prof_a",
                        "active": True,
                        "rosterSettings": {"teamCount": 12},
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("LEAGUE_REGISTRY_PATH", str(path))
    league_registry.reload_registry()
    yield TestClient(server.app), server
    league_registry.reload_registry()


def _non_default_key(server) -> str:
    return "dc_side"


def test_a_cold_contract_503s_for_a_non_default_league(client, monkeypatch):
    """The defect, stated directly."""
    api, server = client
    key = _non_default_key(server)
    if not key:
        pytest.skip("registry has no non-default active league to exercise the fallback")

    monkeypatch.setattr(server, "latest_contract_data", None, raising=False)
    res = api.get(f"/api/draft-capital?leagueKey={key}")
    assert res.status_code == 503, res.text
    body = res.json()
    assert body["error"] == "data_not_ready"
    assert body["leagueKey"] == key


def test_a_contract_for_another_league_is_still_served(client, monkeypatch):
    """NOT 503 — and that is deliberate.

    CLAUDE.md's table lists this route among those that 503 on a league
    mismatch, and it does not. That gap is Defect D-2 in
    ``docs/python-coverage-audit.md``: an OPEN decision between
    "503 per the table" and "keep the cross-league fallback and fix the
    doc". ``tests/api/test_league_isolation_invariants.py`` pins today's
    behaviour on purpose rather than pre-empting it, and serving a
    foreign league its OWN Sleeper rosters is real functionality.

    My first draft of this guard 503'd here too and broke that test.
    Recorded so the next person does not resolve D-2 by accident
    either: it is the operator's call, and this test exists to make an
    accidental change loud.
    """
    api, server = client
    key = _non_default_key(server)

    monkeypatch.setattr(
        server,
        "latest_contract_data",
        {"meta": {"leagueKey": "some_other_league"}, "playersArray": []},
        raising=False,
    )
    res = api.get(f"/api/draft-capital?leagueKey={key}")
    assert res.status_code != 503, (
        "a league-mismatch 503 here resolves Defect D-2 unilaterally — "
        "see docs/python-coverage-audit.md"
    )


def test_the_default_league_is_not_gated_by_the_contract(client, monkeypatch):
    """Deliberately asymmetric.

    The workbook path reads ``CSVs/Draft Data.xlsx`` and never touches
    the contract, so applying the guard there would 503 the one league
    that has real data regardless of scrape state. Anything but 503 is
    the pass condition — the workbook may be absent in CI, which is a
    different failure with a different status.
    """
    api, server = client
    default = server._league_registry.get_default_league()
    if not default:
        pytest.skip("no default league configured")

    monkeypatch.setattr(server, "latest_contract_data", None, raising=False)
    res = api.get(f"/api/draft-capital?leagueKey={default.key}")
    assert res.status_code != 503, (
        "the default league is served from the workbook and must not be "
        f"gated on contract readiness (got {res.text[:200]})"
    )


def test_an_unknown_league_still_400s_ahead_of_the_new_guard(client, monkeypatch):
    """Ordering matters. Resolution errors must keep their 400; a
    readiness guard that ran first would relabel every typo as
    ``data_not_ready``."""
    api, server = client
    monkeypatch.setattr(server, "latest_contract_data", None, raising=False)
    res = api.get("/api/draft-capital?leagueKey=definitely_not_a_league")
    assert res.status_code == 400
    assert res.json()["error"] == "unknown_league"
