"""Hard tripwire for Hill canonicality.

The old test pinned July's literal constants, which meant every legitimate
promotion required a human to remember to rewrite the guard.  Autopilot
changes the invariant: the numbers may move, but ONLY through the model
registry.  The hard contract is therefore registry champion == committed
source == imported runtime constants.
"""

from __future__ import annotations

from src.canonical.player_valuation import (
    HILL_GLOBAL_PERCENTILE_C,
    HILL_GLOBAL_PERCENTILE_S,
    HILL_PERCENTILE_C,
    HILL_PERCENTILE_S,
    HILL_ROOKIE_PERCENTILE_C,
    HILL_ROOKIE_PERCENTILE_S,
    IDP_HILL_PERCENTILE_C,
    IDP_HILL_PERCENTILE_S,
    percentile_to_value,
)
from src.model_registry.hill_masters import load_or_seed_registry, read_committed_constants


def _imported() -> dict[str, float]:
    return {
        "HILL_GLOBAL_PERCENTILE_C": HILL_GLOBAL_PERCENTILE_C,
        "HILL_GLOBAL_PERCENTILE_S": HILL_GLOBAL_PERCENTILE_S,
        "HILL_PERCENTILE_C": HILL_PERCENTILE_C,
        "HILL_PERCENTILE_S": HILL_PERCENTILE_S,
        "IDP_HILL_PERCENTILE_C": IDP_HILL_PERCENTILE_C,
        "IDP_HILL_PERCENTILE_S": IDP_HILL_PERCENTILE_S,
        "HILL_ROOKIE_PERCENTILE_C": HILL_ROOKIE_PERCENTILE_C,
        "HILL_ROOKIE_PERCENTILE_S": HILL_ROOKIE_PERCENTILE_S,
    }


def test_committed_constants_are_exactly_the_registry_champion():
    reg = load_or_seed_registry()
    assert read_committed_constants() == reg.champion.params


def test_imported_runtime_constants_equal_the_committed_source():
    assert _imported() == read_committed_constants()


def test_offense_curve_is_bounded_and_monotone_over_the_served_domain():
    from src.api.data_contract import _PERCENTILE_REFERENCE_N
    from src.canonical.player_valuation import rank_to_percentile

    values = [
        percentile_to_value(rank_to_percentile(rank, reference_n=_PERCENTILE_REFERENCE_N))
        for rank in range(1, 905)
    ]
    assert values[0] == 9999
    assert all(1 <= v <= 9999 for v in values)
    assert all(a >= b for a, b in zip(values, values[1:], strict=False))


def test_champion_has_a_reproducible_parameter_identity():
    reg = load_or_seed_registry()
    champ = reg.champion
    assert champ.version >= 1
    assert set(champ.params) == set(read_committed_constants())
    assert champ.producer
