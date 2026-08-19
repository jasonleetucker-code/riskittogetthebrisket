"""V1-35 — the seven quantities of decision 69 stay distinct.

Binding source, ``docs/OWNER_REQUESTED_TODO.md`` decision 69, verbatim:

    **Total Asset Value, Meaningful Roster Strength, Exact Starting
    Lineup, Depth Value, Power Ranking, Playoff Probability and
    Championship Probability stay distinct** in the model and the UI.
    They may not be collapsed into one generic team score.

V1-35's required evidence level is **EVIDENCE-L1**, so the artifact that
moves the row is a deterministic test rather than a document.  The
document (``docs/roster-intelligence/V1_35_METRIC_SEPARATION_AUDIT.md``)
records the census and the cross-lane findings; this file pins the half
that lives inside the Roster lane and can be enforced in CI.

**Scope, stated so a green run is not over-read.**  This suite proves
separation *where this lane owns the code*.  It cannot prove it on
`/rosters`, `/phases` or the `src/ros/` and `src/public_league/`
surfaces — those are other lanes' files, and the audit hands their
findings to integration rather than editing them.  A green result here
is necessary for V1-35 and not sufficient for it.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any, Iterator, Mapping

from src.roster_intel.engine import RosterIntel, analyze_roster

REPO = Path(__file__).resolve().parents[2]
ROSTER_INTEL = REPO / "src" / "roster_intel"

#: Field names that would BE the collapse: one number standing for a
#: team's overall quality.  Not a denylist of substrings — "value" and
#: "strength" are legitimate when they name a specific quantity, and
#: banning them would forbid the vocabulary decision 69 requires.  These
#: are the names that assert generality.
COLLAPSED_SCORE_FIELDS = frozenset(
    {
        "teamScore",
        "overallScore",
        "overallRating",
        "genericScore",
        "compositeScore",
        "teamRating",
        "powerScore",
        "teamQuality",
    }
)

#: The modules that PRODUCE the ROS 0-100 log-rank production index.
#: Importing one into the dynasty-value lane is the seam through which
#: the two currencies could silently merge, so the absence of that
#: import is the structural guarantee.  ``src.ros.lineup`` is
#: deliberately NOT here: it is the canonical lineup/slot owner (C2-U1),
#: it is unit-agnostic, and consuming it is required rather than
#: forbidden.
ROS_PRODUCTION_MODULES = frozenset(
    {
        "src.ros.team_strength",
        "src.ros.aggregate",
        "src.ros.power_v2",
        "src.ros.playoff_sim",
        "src.ros.championship",
        "src.ros.direction",
    }
)


def _walk(node: Any, path: str = "") -> Iterator[tuple[str, str, Any]]:
    """Every ``(path, key, value)`` in a nested payload."""
    if isinstance(node, Mapping):
        for key, value in node.items():
            yield path, str(key), value
            yield from _walk(value, f"{path}.{key}")
    elif isinstance(node, list):
        for i, value in enumerate(node):
            yield from _walk(value, f"{path}[{i}]")


def _imported_modules(source: Path) -> set[str]:
    tree = ast.parse(source.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
        elif isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
    return found


# ---------------------------------------------------------------------------
# 1. No collapsed team score anywhere in the canonical roster payload.
# ---------------------------------------------------------------------------


def test_roster_intelligence_publishes_no_generic_team_score():
    """The payload names specific quantities and never a general one.

    Non-vacuous: the assertion below also proves the walk reached a
    real payload, so "no collapsed field found" cannot mean "found
    nothing at all".
    """
    from tests.archive_fixtures import newest_complete_raw_payload

    raw, _archive = newest_complete_raw_payload()
    if raw is None:
        import pytest

        pytest.skip("no complete archived payload available in this environment")

    from src.api.data_contract import build_api_data_contract
    from src.api.roster_intelligence import build_league_roster_intelligence

    payload = build_league_roster_intelligence(build_api_data_contract(raw), team_count=12)

    keys = [(path, key) for path, key, _ in _walk(payload)]
    assert (
        len(keys) > 500
    ), f"the walk only reached {len(keys)} keys — it did not traverse the payload"

    offenders = [f"{path}.{key}" for path, key in keys if key in COLLAPSED_SCORE_FIELDS]
    assert not offenders, (
        "decision 69: these fields collapse distinct quantities into one "
        f"generic team score: {sorted(set(offenders))[:10]}"
    )


def test_team_strength_and_portfolio_total_are_separately_named():
    """ "Meaningful Roster Strength" and "Total Asset Value" are two of
    decision 69's seven, so they may not share a field.

    ``strength.total`` is the meaningful core; ``strength.fullRosterValue``
    is the whole-roster portfolio.  They are far apart by construction on
    a deep best-ball roster — a 58-man roster books bench player #40 at
    full market value — so publishing one under the other's name would
    misstate the number, not merely the label.
    """
    from src.roster_intel.core import CoreMember, MeaningfulCore
    from src.roster_intel.strength import build_team_strength

    core = MeaningfulCore(
        members=(
            CoreMember("a", "A", "QB", "QB", "starter", 900.0),
            CoreMember("b", "B", "RB", "RB", "starter", 500.0),
        )
    )
    strength = build_team_strength(core, full_roster_values=[900.0, 500.0, 40.0])
    published = strength.to_dict()

    assert published["total"] == 1400.0
    assert published["fullRosterValue"] == 1440.0
    assert (
        published["total"] != published["fullRosterValue"]
    ), "the fixture must keep them distinguishable, or this test proves nothing"


def test_absent_full_roster_is_null_not_the_core_total():
    """MISSING IS NEVER ZERO, applied to the separation itself.

    A caller that supplies no full roster gets ``None`` — never the core
    total silently standing in for the portfolio, which would collapse
    two of the seven quantities by omission rather than by design.
    """
    from src.roster_intel.core import CoreMember, MeaningfulCore
    from src.roster_intel.strength import build_team_strength

    core = MeaningfulCore(members=(CoreMember("a", "A", "QB", "QB", "starter", 900.0),))
    published = build_team_strength(core).to_dict()
    assert published["total"] == 900.0
    assert published["fullRosterValue"] is None


# ---------------------------------------------------------------------------
# 2. Lineup, strength and depth are three quantities, not one.
# ---------------------------------------------------------------------------


def test_lineup_assignment_and_value_are_published_as_different_facts():
    """ "Exact Starting Lineup" and "Meaningful Roster Strength" are
    separate entries in decision 69.

    The core publishes the ASSIGNMENT (which slot seated whom) and Team
    Strength publishes the VALUE.  Neither is derivable from the other:
    two teams can field the same slots at wildly different value, and
    the same value can be assigned to different slots.
    """
    from src.roster_intel.core import CoreMember, MeaningfulCore
    from src.roster_intel.strength import build_team_strength

    core = MeaningfulCore(
        members=(
            CoreMember("a", "A", "WR", "FLEX", "starter", 700.0),
            CoreMember("b", "B", "WR", "WR", "reserve", 300.0),
        ),
        starter_slots=("WR", "FLEX"),
    )
    core_dict = core.to_dict()
    strength_dict = build_team_strength(core).to_dict()

    assert {m["slot"] for m in core_dict["members"]} == {"FLEX", "WR"}
    assert "slot" not in strength_dict
    assert "total" not in core_dict
    # And a FLEX starter is grouped under his NATIVE position, never a
    # "FLEX" strength group (decision 72: FLEX is an assignment rule,
    # not a sortable Team Strength position).
    assert "FLEX" not in strength_dict["positionOrder"]


def test_starter_and_reserve_value_partition_the_total():
    """ "Depth Value" is its own quantity, published beside the total
    rather than folded into it."""
    from src.roster_intel.core import CoreMember, MeaningfulCore
    from src.roster_intel.strength import build_team_strength

    core = MeaningfulCore(
        members=(
            CoreMember("a", "A", "QB", "QB", "starter", 900.0),
            CoreMember("b", "B", "QB", "BENCH", "reserve", 100.0),
        )
    )
    published = build_team_strength(core).to_dict()
    assert published["starterValue"] == 900.0
    assert published["reserveValue"] == 100.0
    assert published["starterValue"] + published["reserveValue"] == published["total"]


# ---------------------------------------------------------------------------
# 3. Probability is relayed, never manufactured, and never from value.
# ---------------------------------------------------------------------------


def test_playoff_and_championship_odds_are_none_without_a_simulator():
    """ "Playoff Probability" and "Championship Probability" are the two
    quantities most at risk of being invented from roster value.

    With no simulator output the answer is ``None`` with a note — never
    a number derived from Team Strength.  Deriving one would collapse
    three of decision 69's seven into a single value-driven score while
    looking, in the payload, like three independent measurements.
    """
    result = analyze_roster("owner-1", [], ["QB"])
    assert isinstance(result, RosterIntel)
    published = result.to_dict()
    assert published["playoffOdds"] is None
    assert published["championshipOdds"] is None


def test_championship_odds_stay_none_when_the_simulator_supplies_only_playoff_odds():
    """The measured state of the live simulator: ``simulate_playoff_odds``
    stops at qualification and does not run the bracket.

    Relaying its playoff number while leaving championship ``None`` is
    the honest shape; filling the gap from the playoff figure would
    manufacture the seventh quantity out of the sixth.
    """
    result = analyze_roster(
        "owner-1",
        [],
        ["QB"],
        playoff_odds=[{"ownerId": "owner-1", "playoffOdds": 0.62}],
    )
    published = result.to_dict()
    assert published["playoffOdds"] == 0.62
    assert published["championshipOdds"] is None


# ---------------------------------------------------------------------------
# 4. The structural guard: the dynasty-value lane cannot import the
#    ROS-production lane.
# ---------------------------------------------------------------------------


def test_roster_intel_never_imports_the_ros_production_modules():
    """One import is all it would take to merge two currencies.

    ``rosValue`` is "a normalized log-rank index on 0-100 — not points,
    and not projection-aware" (``src/ros/aggregate.py``); canonical
    dynasty value is 1-9999 market value.  ``MASTER_PRODUCT_PLAN`` §4.1:
    *"Team Strength is dynasty roster strength; it is not Power Ranking,
    Playoff Odds, or ROS production."*

    This is exactly the defect the endpoint was repaired for — Team
    Strength used to sum ``rosValue`` — so the absence of the import is
    worth pinning rather than trusting.

    ``src.ros.lineup`` is permitted and expected: it is the canonical
    lineup owner and it is unit-agnostic.
    """
    modules = sorted(ROSTER_INTEL.glob("*.py")) + [REPO / "src" / "api" / "roster_intelligence.py"]
    assert len(modules) > 5, "the glob found almost nothing — the guard would pass vacuously"

    offenders: dict[str, list[str]] = {}
    for path in modules:
        bad = sorted(_imported_modules(path) & ROS_PRODUCTION_MODULES)
        if bad:
            offenders[str(path.relative_to(REPO))] = bad
    assert not offenders, (
        "the dynasty-value lane imported a ROS-production module, which is the "
        f"seam through which the two currencies merge: {offenders}"
    )


def test_the_guard_would_catch_a_real_import():
    """Mutation proof for the guard above.

    A structural test that cannot be made to fail is decoration.  This
    parses a module that DOES import one of the named producers and
    confirms the detector sees it.
    """
    ros_api = REPO / "src" / "ros" / "api.py"
    assert _imported_modules(ros_api) & ROS_PRODUCTION_MODULES, (
        "src/ros/api.py imports src.ros.team_strength; if this assertion fails "
        "the detector is broken, not the boundary"
    )


def test_the_collapsed_score_detector_would_catch_one():
    """Mutation proof for the walk above.

    ``COLLAPSED_SCORE_FIELDS`` is a small allowlist-of-offenders, so the
    failure mode is a detector that never matches anything and passes
    forever.  Inject the field the audit found live on ``/rosters``
    (``frontend/lib/league-analysis.js::scoreTeamTiers`` publishes a
    ``score``) under one of the names decision 69 forbids, and confirm
    the walk finds it.
    """
    payload = {"teams": {"o1": {"strength": {"total": 1400.0, "teamScore": 87.2}}}}
    offenders = [
        f"{path}.{key}" for path, key, _ in _walk(payload) if key in COLLAPSED_SCORE_FIELDS
    ]
    assert offenders == [".teams.o1.strength.teamScore"]
