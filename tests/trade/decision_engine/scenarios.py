"""Named two-sided scenarios behind the committed camelCase fixtures.

Each team's layers are built from THAT team's own perspective (its own
package direction, lineup delta and strategy); nothing on one side is derived
from the other.
"""

from __future__ import annotations

from src.trade.decision_engine.contracts import TeamLayers
from src.trade.decision_engine.providers import stub_providers
from tests.trade.decision_engine.builders import asset_layer, layers, lineup_layer, unavailable


def both_gain() -> tuple[TeamLayers, TeamLayers]:
    # A contender pays a slight premium for a large lineup gain; a rebuilder
    # takes the value and accepts a modest lineup loss.
    a = layers(
        "team-a",
        strategy="WIN_NOW",
        asset=asset_layer([5000.0], [4700.0]),
        lineup=lineup_layer(4.0, se=0.15),
    )
    b = layers(
        "team-b",
        strategy="LONG_TERM",
        source="posture",
        posture_label="REBUILD",
        asset=asset_layer([4700.0], [5000.0]),
        lineup=lineup_layer(-2.0, se=0.15),
    )
    return a, b


def both_lose() -> tuple[TeamLayers, TeamLayers]:
    a = layers(
        "team-a",
        strategy="BALANCED",
        asset=asset_layer([5000.0], [4400.0]),
        lineup=lineup_layer(-0.2, se=0.1),
    )
    b = layers(
        "team-b",
        strategy="BALANCED",
        asset=asset_layer([4400.0], [5000.0]),
        lineup=lineup_layer(-4.0, se=0.1),
    )
    return a, b


def insufficient() -> tuple[TeamLayers, TeamLayers]:
    a = layers(
        "team-a",
        strategy="WIN_NOW",
        asset=asset_layer([5000.0], [4700.0]),
        lineup=lineup_layer(2.0, coverage="partial"),
    )
    b = layers(
        "team-b",
        strategy="LONG_TERM",
        asset=asset_layer([4700.0], [5000.0], gates=("unpriced_assets",)),
        lineup=lineup_layer(-1.0),
    )
    return a, b


def va_overlap() -> tuple[TeamLayers, TeamLayers]:
    # Team A consolidates two pieces into one: the geometric VA credits A, and
    # A's lineup also improves (aligned -> overlap guard).  Team B's lineup
    # improves from depth while the VA points the other way (the structural
    # consolidation premium label, not evidence against B).
    a = layers(
        "team-a",
        strategy="WIN_NOW",
        asset=asset_layer([3000.0, 2600.0], [5000.0]),
        lineup=lineup_layer(2.5, se=0.1),
    )
    b = layers(
        "team-b",
        strategy="BALANCED",
        asset=asset_layer([5000.0], [3000.0, 2600.0]),
        lineup=lineup_layer(1.5, se=0.1),
    )
    return a, b


def all_stub() -> tuple[TeamLayers, TeamLayers]:
    """Every provider is a batch-1 stub and no analyze packet exists."""
    prov = stub_providers()
    deltas = prov.bestball.two_sided_lineup_deltas(["team-a", "team-b"])
    titles = prov.competitive.championship_delta(["team-a", "team-b"], deltas)
    out = []
    for tid in ("team-a", "team-b"):
        out.append(
            TeamLayers(
                team_id=tid,
                strategy=None,
                strategy_source="none",
                posture_label=None,
                posture_probabilities=None,
                asset=unavailable("analyze_packet_not_supplied"),
                lineup=deltas[tid],
                title=titles[tid],
                horizon=prov.bestball.team_horizon(tid),
                roster_known=None,
                roster_limit_known=None,
                freshness={},
            )
        )
    return out[0], out[1]


SCENARIOS = {
    "both_gain": both_gain,
    "both_lose": both_lose,
    "insufficient": insufficient,
    "va_overlap": va_overlap,
    "all_stub": all_stub,
}
