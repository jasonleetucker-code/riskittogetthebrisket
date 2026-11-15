"""Private multi-team War Room fixtures for WITHHELD asset values — REAL
``/api/trade/analyze-multi`` bodies for Lane B's component tests (finding F2).

Lane A's engine gives a traded asset the evidence gates withhold an explicit
``valueState`` (``quarantined`` / ``stale``) with ``value: null`` rather than
``priced`` (``analyze_service._value_entry``).  The War Room must render those
legs, and every team whose package carries one, as WITHHELD — so the fixtures
are the engine's own output, never hand-written.

This module ADDS scenarios beside Lane A's ``multi_team_ui_payloads`` without
editing it: each scenario runs through that module's ``build`` (the exact
production assembly plus the route's per-request stamps), on the LABELLED
synthetic league with one traded row carrying the pipeline's own stamp:

* ``quarantined: true`` (the row-level quarantine verdict), or
* ``confidenceAxes.freshness: "low"`` (the confidence owner's freshness axis).

Nothing is priced, adjusted or decided here.  Regenerate with::

    python -m tests.trade.multi_team_withheld_payloads
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest import mock

from tests.trade import multi_team_support as mts
from tests.trade import multi_team_ui_payloads as gen

#: Same serialisation as Lane A's fixtures (sorted keys, one-space indent).
serialize = gen.serialize

OUT_DIR = (
    Path(__file__).resolve().parents[2]
    / "frontend"
    / "__tests__"
    / "fixtures"
    / "trade-multi-withheld"
)

#: The 3-team cycle every scenario routes: A -> B -> C -> A.  ``p:201``
#: ("B Seven") is the withheld asset, so teams B (sends it) and C (receives
#: it) carry it and team A does not.
LEGS = [
    {"id": "p:101", "from": 1, "to": 2},
    {"id": "p:201", "from": 2, "to": 3},
    {"id": "p:301", "from": 3, "to": 1},
]
WITHHELD_PLAYER_ID = "201"


def _contract_with(stamp: dict) -> dict:
    contract = mts.synthetic_league()
    for row in contract["playersArray"]:
        if row.get("playerId") == WITHHELD_PLAYER_ID:
            row.update(stamp)
            break
    else:  # pragma: no cover - the synthetic league always carries it
        raise AssertionError(f"synthetic league has no player {WITHHELD_PLAYER_ID}")
    return contract


def _scenario_three_team_quarantined_asset():
    snap = mts.synthetic_snapshot(_contract_with({"quarantined": True}))
    return (
        snap,
        [1, 2, 3],
        LEGS,
        "asset_only",
        "synthetic",
        (
            "A 3-team cycle carrying a player the pipeline QUARANTINED: the leg is "
            "valueState 'quarantined' with value null, and the two teams it touches are "
            "withheld (UNABLE), never priced and never 0."
        ),
    )


def _scenario_three_team_stale_asset():
    snap = mts.synthetic_snapshot(_contract_with({"confidenceAxes": {"freshness": "low"}}))
    return (
        snap,
        [1, 2, 3],
        LEGS,
        "asset_only",
        "synthetic",
        (
            "A 3-team cycle carrying a player whose value the confidence owner reads as "
            "STALE (freshness low): the leg is valueState 'stale' with value null, and the "
            "two teams it touches are withheld (UNABLE), never priced and never 0."
        ),
    )


SCENARIOS = {
    "three-team-quarantined-asset": _scenario_three_team_quarantined_asset,
    "three-team-stale-asset": _scenario_three_team_stale_asset,
}


def build(name: str) -> dict:
    with mock.patch.dict(gen.SCENARIOS, {name: SCENARIOS[name]}):
        payload = gen.build(name)
    payload["_fixture"]["generator"] = "tests/trade/multi_team_withheld_payloads.py"
    return payload


def fixture_path(name: str) -> Path:
    return OUT_DIR / f"{name}.json"


def main(argv: list[str] | None = None) -> int:
    names = (argv if argv else None) or list(SCENARIOS)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for name in names:
        fixture_path(name).write_text(serialize(build(name)), encoding="utf-8")
        print(f"wrote {fixture_path(name)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
