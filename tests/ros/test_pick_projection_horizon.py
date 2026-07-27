"""A ``confidence`` field that could not vary with the horizon.

``project_draft_order`` derives confidence from how isolated a team's
strength score is from its neighbours **today**. ``build_pick_projections``
then stamped that value verbatim onto every future pick, so a row
labelled ``2029 1.01`` — a claim about a draft three years out, built
entirely from this week's rosters — carried the same "high" as next
season's.

Measured on the live 12-team snapshot before the fix: 2027, 2028 and
2029 all returned ``{high: 2, medium: 6, low: 4}``, and one team read
``medium`` in all three. Identical, because nothing in the computation
referenced the season at all.

That is the name/predicate gap again — the field is called
``confidence`` and the predicate is "gap to neighbours now". These
tests pin the horizon ceiling, and they pin the two ways such a fix
goes wrong: capping that silently *raises* a low confidence, and a
ceiling table that quietly stops applying past its last key.

NOTE ON WHAT IS AND IS NOT ESTABLISHED HERE. The ceilings are a stated
assumption, not a fitted curve — ``data/ros/team_strength/`` holds one
snapshot per league, so there is no multi-season history to backtest
against. These tests assert the cap is *applied*, never that its values
are *correct*.
"""

from __future__ import annotations

from src.ros.pick_projection import _cap_confidence, build_pick_projections

STRENGTHS = [
    # Deliberately spread so the gap-based reading produces all three
    # labels — a fixture where everything is already "low" would let a
    # broken cap pass by doing nothing.
    {"rosterId": 1, "ownerId": "o1", "teamName": "Weakest", "teamRosStrength": 100.0},
    {"rosterId": 2, "ownerId": "o2", "teamName": "Cluster A", "teamRosStrength": 300.0},
    {"rosterId": 3, "ownerId": "o3", "teamName": "Cluster B", "teamRosStrength": 305.0},
    {"rosterId": 4, "ownerId": "o4", "teamName": "Strongest", "teamRosStrength": 600.0},
]


def _teams(seasons):
    return [
        {
            "roster_id": row["rosterId"],
            "name": row["teamName"],
            "pickDetails": [
                {
                    "season": str(s),
                    "round": 1,
                    "original_roster_id": row["rosterId"],
                    "owner_roster_id": row["rosterId"],
                    "label": f"{s} 1st",
                }
                for s in seasons
            ],
        }
        for row in STRENGTHS
    ]


def _by_season(payload):
    out = {}
    for p in payload["picks"]:
        out.setdefault(p["season"], []).append(p)
    return out


# ── The fixture has to be capable of showing the bug ─────────────────


def test_the_fixture_produces_more_than_one_confidence_level():
    """Non-vacuity, and it is the load-bearing check in this file.

    If every team read ``low`` on its own merits, a cap that did
    nothing would pass every assertion below. The uncapped
    ``slotConfidence`` is what proves the ceiling has something to bite
    on.
    """
    payload = build_pick_projections(_teams([2027]), STRENGTHS, current_season=2026)
    levels = {p["slotConfidence"] for p in payload["picks"]}
    assert len(levels) > 1, f"fixture yields only {levels}; the cap could not be observed"
    assert "high" in levels, "need at least one high, or the ceiling is untestable"


# ── The claim ────────────────────────────────────────────────────────


def test_confidence_falls_as_the_pick_moves_further_out():
    """The defect, stated directly: these three must not be equal."""
    payload = build_pick_projections(_teams([2027, 2028, 2029]), STRENGTHS, current_season=2026)
    by_season = _by_season(payload)

    near = {p["confidence"] for p in by_season[2027]}
    mid = {p["confidence"] for p in by_season[2028]}
    far = {p["confidence"] for p in by_season[2029]}

    assert "high" in near
    assert "high" not in mid, "a two-year-out pick cannot be high confidence"
    assert far == {"low"}, "a three-year-out pick is a guess, and must say so"


def test_the_uncapped_reading_is_preserved_separately():
    """``slotConfidence`` keeps the today-only answer, so a consumer can
    distinguish "tightly ranked team, distant pick" from "team in a
    scrum". Losing it would replace one missing distinction with
    another."""
    payload = build_pick_projections(_teams([2029]), STRENGTHS, current_season=2026)
    for pick in payload["picks"]:
        assert pick["confidence"] == "low"
    assert {p["slotConfidence"] for p in payload["picks"]} != {"low"}


def test_seasons_out_is_stamped():
    payload = build_pick_projections(_teams([2027, 2029]), STRENGTHS, current_season=2026)
    by_season = _by_season(payload)
    assert all(p["seasonsOut"] == 1 for p in by_season[2027])
    assert all(p["seasonsOut"] == 3 for p in by_season[2029])


# ── The two ways this fix goes wrong ─────────────────────────────────


def test_the_cap_never_raises_a_confidence():
    """A ceiling, not an assignment.

    ``min(confidence, ceiling)`` is only correct if it is ordered
    correctly; an implementation that assigned the ceiling outright
    would promote a genuinely-low team to "high" for next season, which
    is worse than the bug being fixed.
    """
    assert _cap_confidence("low", 1) == "low"
    assert _cap_confidence("medium", 1) == "medium"
    assert _cap_confidence("high", 1) == "high"
    assert _cap_confidence("low", 2) == "low"
    assert _cap_confidence("high", 2) == "medium"


def test_the_ceiling_keeps_applying_past_the_last_table_key():
    """The table lists horizons 1 and 2. A ``dict.get`` without a
    default would return None for horizon 7 and the cap would silently
    stop — the failure mode being that the furthest-out picks, the ones
    least knowable, are the ones that escape."""
    for horizon in (3, 4, 7, 25):
        assert _cap_confidence("high", horizon) == "low", f"horizon {horizon} escaped the ceiling"


def test_an_unrecognised_label_is_not_promoted():
    """If ``project_draft_order`` ever emits a new label, the cap must
    not treat the unknown as permission to keep it. Falling back to the
    ceiling is the conservative direction."""
    assert _cap_confidence("extremely-high", 3) == "low"
    assert _cap_confidence("", 2) == "medium"


def test_the_current_season_is_still_excluded_entirely():
    """This module projects only future drafts; the current season's
    order is actual standings. A horizon of 0 or less must produce no
    rows at all rather than a capped guess."""
    payload = build_pick_projections(_teams([2025, 2026]), STRENGTHS, current_season=2026)
    assert payload["picks"] == []
