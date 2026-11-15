"""The withheld-value War Room fixtures ARE the engine's output (finding F2).

``frontend/__tests__/fixtures/trade-multi-withheld/*`` feed Lane B's
component tests.  This regenerates each scenario through the production
engine (``tests/trade/multi_team_withheld_payloads.py``) and requires the
committed file to equal it, plus the invariants the UI relies on: the
withheld leg carries ``valueState`` quarantined / stale with ``value: null``
(never a number, never 0) and every team it touches is UNABLE.  Regenerate
with::

    python -m tests.trade.multi_team_withheld_payloads
"""

from __future__ import annotations

import json

import pytest

from tests.trade import multi_team_withheld_payloads as gen

EXPECTED_STATE = {
    "three-team-quarantined-asset": "quarantined",
    "three-team-stale-asset": "stale",
}


def _load(name: str) -> dict:
    path = gen.fixture_path(name)
    assert path.exists(), f"missing {path}; run python -m tests.trade.multi_team_withheld_payloads"
    return json.loads(path.read_text(encoding="utf-8"))


def test_every_scenario_names_its_withheld_state():
    assert set(gen.SCENARIOS) == set(EXPECTED_STATE)


@pytest.mark.parametrize("name", sorted(gen.SCENARIOS))
def test_committed_fixture_is_the_engines_output(name):
    # The synthetic league is fully pinned, so the whole body must match.
    assert _load(name) == json.loads(gen.serialize(gen.build(name))), (
        f"{name}.json drifted from the engine; regenerate with "
        "python -m tests.trade.multi_team_withheld_payloads"
    )


@pytest.mark.parametrize("name", sorted(gen.SCENARIOS))
def test_withheld_leg_is_never_priced_and_its_teams_are_unable(name):
    body = _load(name)
    state = EXPECTED_STATE[name]
    asset_id = f"p:{gen.WITHHELD_PLAYER_ID}"
    touched = set()
    for t in body["teams"]:
        for row in (*t["gives"], *t["receives"]):
            if row["assetId"] == asset_id:
                assert row["valueState"] == state
                assert row["value"] is None  # missing is never zero
                touched.add(t["rosterId"])
            else:
                assert row["valueState"] == "priced"
    assert touched == {2, 3}
    for t in body["teams"]:
        if t["rosterId"] in touched:
            assert t["fairness"]["state"] == "UNABLE"
            assert t["fairness"]["reasonCode"] == "evaluation_unavailable"
            assert t["category"] == "UNAVAILABLE"
        else:
            assert t["fairness"]["state"] != "UNABLE"
