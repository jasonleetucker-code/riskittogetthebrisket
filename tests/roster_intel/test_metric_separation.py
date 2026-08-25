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
separation *where this lane owns the code* (sections 1-4), plus a direct
read of the two frontend files the audit's F-1/F-3 findings named
(section 5) — not because this lane owns those files, but because a
census claim that another lane's file stays retired is worth this
lane's OWN evidence rather than a trusted document, per the repo's
"do not assume features work" rule.  It still cannot prove separation on
`src/ros/` and `src/public_league/` — those are a different lane's
production code and a different V1 row (V1-51/V1-52); the audit records
that boundary rather than crossing it.
"""

from __future__ import annotations

import ast
import re
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


# ---------------------------------------------------------------------------
# 5. The UI half, read directly — not trusted from a document.
#
# The audit (``V1_35_METRIC_SEPARATION_AUDIT.md`` F-1/F-3, handoffs H-1/
# H-2) found two live decision-69 violations on `/rosters` and `/phases`
# and records both as retired by a later, Claude-6-owned change:
# `scoreTeamTiers` (a weighted starterValue/depthValue/pickValue blend,
# tercile-cut into contender/mid-tier/rebuilder) deleted from
# `frontend/lib/league-analysis.js`, and `frontend/lib/team-phase.js`'s
# raw top-25-`rankDerivedValue` + raw-age derivation redirected onto
# `strengthTotal` / `valueWeightedCoreAge`.  Both are ALSO guarded by
# `frontend/__tests__/no-frontend-team-strength-methodology.test.js`, a
# JS/vitest file this lane does not own.
#
# Trusting that guard's existence from its docstring would be exactly
# the failure mode CLAUDE.md's non-negotiable rules warn against ("do
# not assume features work — trace the live execution path").  So this
# lane's OWN suite reads the two real production files directly and
# proves the same absence with its own regexes, mirrored from the JS
# guard's patterns rather than re-derived, so a future edit to one guard
# is a visible prompt to check the other rather than a silent drift.
# ---------------------------------------------------------------------------

#: Mirrors the JS guard's ``COMPOSITE``: a numeric coefficient applied to
#: a *-Value/-Score term, the shape of the retired ``scoreTeamTiers``.
_UI_COMPOSITE = re.compile(
    r"\b0?\.\d+\s*\*\s*\w*(?:[Vv]alue|[Ss]core)\w*|\w*(?:[Vv]alue|[Ss]core)\w*\s*\*\s*0?\.\d+"
)

#: Mirrors the JS guard's ``TIER_CUT``: the contender/rebuilder tier cut.
_UI_TIER_CUT = re.compile(r"""["'`](?:contender|rebuilder|mid-?tier)["'`]""", re.IGNORECASE)

#: Mirrors the JS guard's ``RAW_ROW_DERIVATION``: the retired team-phase.js
#: shape — a raw top-25 value sum plus a raw per-player age lookup.
_UI_RAW_ROW_DERIVATION = re.compile(r"\brankDerivedValue\b|useDynastyData\s*\(|sleeper\??\.teams\b")

#: `/rosters` — where the weighted-composite / tier-cut collapse lived.
_UI_COMPOSITE_FILES = ("frontend/lib/league-analysis.js", "frontend/app/rosters/page.jsx")

#: `/phases` — where the raw-row Team Strength duplicate lived.
_UI_RAW_ROW_FILES = ("frontend/lib/team-phase.js", "frontend/components/TeamPhasePanel.jsx")


def _strip_js_comments(src: str) -> str:
    """Blank comments so prose ABOUT the retired shapes cannot trip the
    scan — mirrors the JS guard's own ``stripComments``, including its
    equal-length-blank approach so any future offender's line number is
    still correct."""
    src = re.sub(r"/\*.*?\*/", lambda m: re.sub(r"[^\n]", " ", m.group(0)), src, flags=re.S)
    return re.sub(r"^\s*//.*$", "", src, flags=re.M)


def _ui_offenders(rel_paths: tuple[str, ...], pattern: re.Pattern[str]) -> list[str]:
    offenders = []
    for rel in rel_paths:
        text = (REPO / rel).read_text(encoding="utf-8")
        clean = _strip_js_comments(text)
        for i, line in enumerate(clean.splitlines(), start=1):
            if pattern.search(line):
                offenders.append(f"{rel}:{i}  {line.strip()}")
    return offenders


def test_the_ui_scan_reads_real_files_not_nothing():
    """Non-vacuity: the scoped files exist and are non-empty, so an
    absent-file typo cannot make every scan below pass by finding
    nothing to search."""
    for rel in _UI_COMPOSITE_FILES + _UI_RAW_ROW_FILES:
        path = REPO / rel
        assert path.is_file(), f"{rel} not found — the UI scope is stale"
        assert path.stat().st_size > 0


def test_rosters_surface_has_no_weighted_composite_team_score():
    """`/rosters` — decision 69's F-1 violation (`scoreTeamTiers`) stays
    retired, read directly from the real production file."""
    offenders = _ui_offenders(_UI_COMPOSITE_FILES, _UI_COMPOSITE)
    assert not offenders, (
        "a weighted blend of value/score terms is a Team Strength "
        "methodology living in the browser (decision 69, F-1). Read "
        f"strength.total from GET /api/roster/intelligence instead:\n{offenders}"
    )


def test_rosters_surface_has_no_tier_classification():
    """`/rosters` publishes no client-side contender/rebuilder cut — the
    classification half of the same F-1 violation."""
    offenders = _ui_offenders(_UI_COMPOSITE_FILES, _UI_TIER_CUT)
    assert not offenders, (
        "tiering teams client-side is a backend classification (decision 69, "
        f"F-1). Use strength.leagueRank / leaguePercentile instead:\n{offenders}"
    )


def test_phases_surface_reads_canonical_strength_not_raw_rows():
    """`/phases` — decision 69's F-3 violation (a raw top-25 value sum
    plus a raw per-player age lookup) stays retired."""
    offenders = _ui_offenders(_UI_RAW_ROW_FILES, _UI_RAW_ROW_DERIVATION)
    assert not offenders, (
        "a raw player-row value/age derivation is a second Team Strength "
        "engine (decision 69, F-3). Read strengthTotal / valueWeightedCoreAge "
        f"from GET /api/roster/intelligence instead:\n{offenders}"
    )


def test_the_ui_composite_scan_would_catch_the_retired_formula():
    """Mutation proof: the exact retired `scoreTeamTiers` line, verbatim
    from the audit, must trip the detector — a scan that cannot be made
    to fail is decoration."""
    line = (
        "const score = starterValue * 0.7 + depthValue * 0.2 + "
        "(pickValue > 0 ? -pickValue * 0.1 : 0);"
    )
    assert _UI_COMPOSITE.search(line), "the detector missed the exact retired formula shape"
    assert _UI_TIER_CUT.search('tier: i < top ? "contender" : "rebuilder"')


def test_the_ui_raw_row_scan_would_catch_the_retired_derivation():
    """Mutation proof for the raw-row detector, against the exact retired
    `team-phase.js` lines named in the audit (F-3)."""
    assert _UI_RAW_ROW_DERIVATION.search("value: Number(r.rankDerivedValue || 0),")
    assert _UI_RAW_ROW_DERIVATION.search("const { rows, rawData } = useDynastyData();")
    assert _UI_RAW_ROW_DERIVATION.search("const teams = rawData?.sleeper?.teams || [];")
    # Negative control: the canonical materializer's own field names,
    # including a MEDIAN of ages, must not trip it.
    assert not _UI_RAW_ROW_DERIVATION.search("totalValue: t.strengthTotal,")
    assert not _UI_RAW_ROW_DERIVATION.search("medianAge: t.valueWeightedCoreAge,")


# ---------------------------------------------------------------------------
# 6. Positive control: on a representative real board, distinct metrics
#    genuinely diverge — the separation is not vacuous because there was
#    never anything to conflate.
# ---------------------------------------------------------------------------


def test_metrics_genuinely_diverge_on_a_representative_real_board():
    """decision 69 only matters if the seven quantities actually take
    DIFFERENT values on a real team — if they always agreed, "do not
    collapse them" would be a distinction without a difference.

    Team Strength (`strength.leagueRank`, value on the meaningful core)
    and the Young Core Index (`agePortfolio.leagueRank`, a value-weighted
    youth percentile — not one of decision 69's seven, but the axis
    `V1-33`'s own validation proved genuinely separate from Strength on
    this same board) are the two fields this endpoint actually populates
    for every team, so this is a real measurement rather than a fixture
    contrived to differ.  Measured on the newest complete archived
    board: a team can be the single STRONGEST roster in the league by
    value while ranking near the BOTTOM on youth (or the reverse) —
    exactly the divergence decision 69 exists to keep visible rather
    than average into one number.
    """
    from tests.archive_fixtures import newest_complete_raw_payload

    raw, _archive = newest_complete_raw_payload()
    if raw is None:
        import pytest

        pytest.skip("no complete archived payload available in this environment")

    from src.api.data_contract import build_api_data_contract
    from src.api.roster_intelligence import build_league_roster_intelligence

    payload = build_league_roster_intelligence(build_api_data_contract(raw), team_count=12)
    teams = payload.get("teams") or {}
    assert len(teams) >= 8, "too few teams to call this representative"

    pairs = []
    for team in teams.values():
        strength_rank = (team.get("strength") or {}).get("leagueRank")
        yci_rank = (team.get("agePortfolio") or {}).get("leagueRank")
        if strength_rank is not None and yci_rank is not None:
            pairs.append((strength_rank, yci_rank))

    assert len(pairs) >= len(teams) - 1, "too many teams missing a rank to measure divergence"

    inversions = sum(1 for s, y in pairs if s != y)
    assert inversions >= len(pairs) // 2, (
        "Team Strength rank and Young Core Index rank should diverge for "
        f"most teams; only {inversions} of {len(pairs)} differed at all — "
        "either the board is unrepresentative or the two axes have collapsed"
    )

    # The magnitude half of the same property, stated over the POPULATION.
    #
    # This clause used to read ``min(pairs, key=...)`` then
    # ``assert strongest[0] != strongest[1]`` — the single strongest-by-value
    # team must not also rank #1 on youth. That asserted a COINCIDENCE about
    # one data point, not a fact about the two concepts: the best roster in a
    # league is perfectly entitled to also be its youngest, and on the
    # 2026-08-24 board it was, giving ``(1, 1)`` and a RED that said nothing
    # about collapse. Two distinct metrics may agree anywhere, including at
    # the top; what they may not do is agree EVERYWHERE.
    #
    # So the leader is no longer special-cased. What the docstring actually
    # claims — "a team can be the single STRONGEST roster in the league by
    # value while ranking near the BOTTOM on youth" — is a statement about
    # displacement, and it is asserted here directly: somewhere in the
    # population, a team's two ranks must sit at least half a league apart.
    # That is the same ``len(pairs) // 2`` scale the inversion bar above
    # already uses, so no new threshold is introduced; a team displaced by
    # half the league is by construction top-half on one axis and bottom-half
    # on the other.
    #
    # It is also strictly stronger than counting inversions. Inversions treat
    # a one-place shuffle and an eleven-place swing identically, so a Young
    # Core that had degenerated into "Team Strength plus noise" could show 12
    # of 12 differing and still pass. Requiring real displacement closes that.
    displacements = [abs(s - y) for s, y in pairs]
    assert max(displacements) >= len(pairs) // 2, (
        "Team Strength and Young Core Index rank every team within "
        f"{max(displacements)} places of each other (need >= {len(pairs) // 2}). "
        "No team is strong-but-old or weak-but-young, so the two axes are "
        "tracking one another rather than measuring different things."
    )
