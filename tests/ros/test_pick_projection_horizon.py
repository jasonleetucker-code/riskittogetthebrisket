"""A ``confidence`` field must vary with the horizon it speaks about.

History: the v1 projector derived confidence from Team Strength gaps
**today** and stamped it onto every future class, so ``2029 1.01`` carried
the same "high" as next season's pick (measured on the live 12-team snapshot:
2027, 2028 and 2029 all ``{high: 2, medium: 6, low: 4}``).

v2 (2026-10-04) reads the season simulation under the canonical draft-order
rule, which forecasts only the class drafted after the simulated season.  A
later class therefore gets NO slot and no confidence at all — stricter than
any cap.  The horizon ceiling still applies to the class that IS forecast,
for the case where it lies more than one season past ``current_season``.

The ceilings are a stated assumption, not a fitted curve; these tests assert
the cap is *applied*, never that its values are *correct*.
"""

from __future__ import annotations

from src.ros.pick_projection import _cap_confidence, build_pick_projections

# Team 1 is locked into slot 1 (high); teams 2-4 are a scrum.
DISTS = {
    1: [1.0, 0.0, 0.0, 0.0],
    2: [0.0, 0.4, 0.3, 0.3],
    3: [0.0, 0.3, 0.4, 0.3],
    4: [0.0, 0.3, 0.3, 0.4],
}


def _sim(season: int = 2026) -> dict:
    return {
        "season": season,
        "draftOrderRule": "reverse_record_lower_pf",
        # Final standings: the forecast carries full weight, so the cap is
        # what is being observed.
        "regularSeasonProgress": {"weeksFinal": 14, "weeksTotal": 14},
        "playoffOdds": [
            {"ownerId": f"o{rid}", "draftSlotDistribution": d} for rid, d in DISTS.items()
        ],
    }


def _teams(seasons):
    return [
        {
            "roster_id": rid,
            "ownerId": f"o{rid}",
            "name": f"Team {rid}",
            "pickDetails": [
                {
                    "season": str(s),
                    "round": 1,
                    "original_roster_id": rid,
                    "owner_roster_id": rid,
                    "label": f"{s} 1st",
                }
                for s in seasons
            ],
        }
        for rid in DISTS
    ]


def _by_season(payload):
    out = {}
    for p in payload["picks"]:
        out.setdefault(p["season"], []).append(p)
    return out


def test_the_fixture_produces_more_than_one_confidence_level():
    """Non-vacuity: a cap is only observable if something reads ``high``."""
    payload = build_pick_projections(_teams([2027]), _sim())
    levels = {p["slotConfidence"] for p in payload["picks"]}
    assert "high" in levels and len(levels) > 1, levels


def test_only_the_simulated_class_is_forecast():
    payload = build_pick_projections(_teams([2027, 2028, 2029]), _sim())
    by_season = _by_season(payload)
    assert "high" in {p["confidence"] for p in by_season[2027]}
    for season in (2028, 2029):
        assert {p["confidence"] for p in by_season[season]} == {None}
        assert {p["projectedSlot"] for p in by_season[season]} == {None}


def test_the_cap_binds_when_the_forecast_class_is_two_seasons_out():
    """Simulated 2026 → forecast class 2027; read from 2025 it is 2 out."""
    payload = build_pick_projections(_teams([2027]), _sim(), current_season=2025)
    top = next(p for p in payload["picks"] if p["originalRosterId"] == 1)
    assert top["seasonsOut"] == 2
    assert top["slotConfidence"] == "high" and top["confidence"] == "medium"


def test_seasons_out_is_stamped():
    payload = build_pick_projections(_teams([2027, 2029]), _sim())
    by_season = _by_season(payload)
    assert all(p["seasonsOut"] == 1 for p in by_season[2027])
    assert all(p["seasonsOut"] == 3 for p in by_season[2029])


def test_the_cap_never_raises_a_confidence():
    assert _cap_confidence("low", 1) == "low"
    assert _cap_confidence("medium", 1) == "medium"
    assert _cap_confidence("high", 1) == "high"
    assert _cap_confidence("low", 2) == "low"
    assert _cap_confidence("high", 2) == "medium"


def test_the_ceiling_keeps_applying_past_the_last_table_key():
    for horizon in (3, 4, 7, 25):
        assert _cap_confidence("high", horizon) == "low", f"horizon {horizon} escaped"


def test_an_unrecognised_label_is_not_promoted():
    assert _cap_confidence("extremely-high", 3) == "low"
    assert _cap_confidence("", 2) == "medium"


def test_the_current_season_is_still_excluded_entirely():
    payload = build_pick_projections(_teams([2025, 2026]), _sim())
    assert payload["picks"] == []
