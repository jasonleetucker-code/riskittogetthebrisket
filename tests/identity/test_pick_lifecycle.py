"""The draft-class lifecycle rule (#1414) — one predicate, three states.

Every fixture here is Sleeper-shaped, and the "real" ones are the live
2026-09-24 observations the thresholds were measured on (see the owner
module's docstring): ``dynasty_main`` carries TWO 2026 draft objects, one of
them ``complete`` with zero picks, and its real rookie draft is 70/84
rostered.
"""

from __future__ import annotations

import inspect
import re

from src.identity import pick_lifecycle as lc
from src.identity.pick_lifecycle import (
    LIFECYCLE_ACTIVE,
    LIFECYCLE_RETIRED,
    LIFECYCLE_UNKNOWN,
    ClassLifecycle,
    DraftObservation,
    LeagueDraftEvidence,
    board_class_lifecycle,
    draft_class_lifecycle,
    evidence_from_sleeper,
    first_active_class,
    is_retired,
    league_class_lifecycles,
    retired_seasons,
)
from src.identity.picks import (
    LeaguePickIdentity,
    parse_board_pick_name,
    parse_league_pick_id,
    parse_pick_label,
)


def _picks(n: int, *, rookies: int | None = None, prefix: str = "p") -> list[dict]:
    rookies = n if rookies is None else rookies
    return [
        {
            "player_id": f"{prefix}{i}",
            "metadata": {"years_exp": "0" if i < rookies else "4"},
        }
        for i in range(n)
    ]


def _draft(draft_id: str, season: int, status: str, player_type: int | None = 1) -> dict:
    settings = {} if player_type is None else {"player_type": player_type}
    return {"draft_id": draft_id, "season": str(season), "status": status, "settings": settings}


def _evidence(drafts, picks_by_id, rostered, league="dynasty_main") -> LeagueDraftEvidence:
    return evidence_from_sleeper(
        league_key=league,
        sleeper_league_id="100",
        drafts=drafts,
        picks_by_draft_id=picks_by_id,
        rostered_player_ids=rostered,
        observed_at="2026-09-24T00:00:00+00:00",
        draft_lists_observed=["100"],
    )


def _live_2026_main() -> LeagueDraftEvidence:
    """dynasty_main as observed 2026-09-24: an empty completed draft object
    beside the real 84-pick rookie auction, 70 of whose picks are rostered."""
    picks = _picks(84)
    rostered = [p["player_id"] for p in picks[:70]] + ["veteran-1", "veteran-2"]
    return _evidence(
        [_draft("empty", 2026, "complete"), _draft("rookie", 2026, "complete")],
        {"empty": [], "rookie": picks},
        rostered,
    )


# ── The per-league predicate ──────────────────────────────────────────


def test_completed_and_rostered_class_is_retired():
    got = draft_class_lifecycle(2026, _live_2026_main())
    assert got.status == LIFECYCLE_RETIRED
    assert "rookies_rostered:70/84" in got.reasons
    # The empty completed draft object consumed nothing and blocks nothing.
    assert "empty_complete_draft_ignored:empty" in got.reasons
    assert is_retired(got)


def test_a_later_class_with_no_draft_is_not_retired():
    got = draft_class_lifecycle(2027, _live_2026_main())
    assert got.status == LIFECYCLE_UNKNOWN
    assert not is_retired(got)


def test_missing_evidence_is_unknown_and_never_retires():
    got = draft_class_lifecycle(2026, None)
    assert got.status == LIFECYCLE_UNKNOWN
    assert got.reasons == ("no_draft_evidence",)
    assert not is_retired(got)
    assert not is_retired(None)


def test_live_and_unstarted_drafts_keep_the_class_active():
    picks = _picks(12)
    for status, reason in (
        ("drafting", "draft_in_progress:d2"),
        ("paused", "draft_in_progress:d2"),
        ("pre_draft", "draft_not_started:d2"),
    ):
        ev = _evidence(
            [_draft("d1", 2026, "complete"), _draft("d2", 2026, status)],
            {"d1": picks},
            [p["player_id"] for p in picks],
        )
        got = draft_class_lifecycle(2026, ev)
        assert got.status == LIFECYCLE_ACTIVE, status
        assert reason in got.reasons


def test_unrecognized_status_is_unknown():
    ev = _evidence([_draft("d1", 2026, "archived")], {}, [])
    got = draft_class_lifecycle(2026, ev)
    assert got.status == LIFECYCLE_UNKNOWN
    assert got.reasons == ("draft_status_unrecognized:d1=archived",)


def test_complete_but_rosters_unobserved_is_unknown():
    picks = _picks(40)
    ev = _evidence([_draft("d1", 2026, "complete")], {"d1": picks}, None)
    got = draft_class_lifecycle(2026, ev)
    assert got.status == LIFECYCLE_UNKNOWN
    assert got.reasons[0] == "rosters_unobserved"


def test_complete_but_not_consumed_onto_rosters_is_unknown():
    picks = _picks(40)
    # A mock / reset / unassigned draft: complete, but its picks never
    # reached rosters.
    ev = _evidence(
        [_draft("d1", 2026, "complete")], {"d1": picks}, [p["player_id"] for p in picks[:5]]
    )
    got = draft_class_lifecycle(2026, ev)
    assert got.status == LIFECYCLE_UNKNOWN
    assert "consumption_unproven:5/40" in got.reasons


def test_consumption_threshold_boundary():
    picks = _picks(40)
    at = _evidence(
        [_draft("d1", 2026, "complete")], {"d1": picks}, [p["player_id"] for p in picks[:20]]
    )
    below = _evidence(
        [_draft("d1", 2026, "complete")], {"d1": picks}, [p["player_id"] for p in picks[:19]]
    )
    assert lc.CONSUMPTION_MIN_ROSTERED_SHARE == 0.5
    assert draft_class_lifecycle(2026, at).status == LIFECYCLE_RETIRED
    assert draft_class_lifecycle(2026, below).status == LIFECYCLE_UNKNOWN


def test_a_completed_dispersal_draft_does_not_retire_the_rookie_class():
    # Mixed-pool draft of veterans (player_type 0, 2 of 30 rookies).
    picks = _picks(30, rookies=2)
    ev = _evidence(
        [_draft("disp", 2027, "complete", player_type=0)],
        {"disp": picks},
        [p["player_id"] for p in picks],
    )
    got = draft_class_lifecycle(2027, ev)
    assert got.status == LIFECYCLE_UNKNOWN
    assert "non_rookie_draft_ignored:disp" in got.reasons


def test_a_mixed_pool_draft_of_mostly_rookies_is_a_rookie_draft():
    # dynasty_main's 2025 draft: player_type 0, 58 of 70 picks rookies.
    picks = _picks(70, rookies=58)
    ev = _evidence(
        [_draft("d25", 2025, "complete", player_type=0)],
        {"d25": picks},
        [p["player_id"] for p in picks[:61]],
    )
    assert draft_class_lifecycle(2025, ev).status == LIFECYCLE_RETIRED


def test_a_synthetic_future_year_retires_without_a_code_change():
    year = 2031  # no literal in the owner decides anything about this year
    picks = _picks(48)
    ev = _evidence(
        [_draft("f", year, "complete")], {"f": picks}, [p["player_id"] for p in picks[:40]]
    )
    assert draft_class_lifecycle(year, ev).status == LIFECYCLE_RETIRED
    assert draft_class_lifecycle(year + 1, ev).status == LIFECYCLE_UNKNOWN


def test_the_owner_reads_no_clock_and_hardcodes_no_year():
    source = inspect.getsource(lc)
    code = "\n".join(
        line for line in source.splitlines() if not line.lstrip().startswith(("#", '"', "*"))
    )
    assert "datetime" not in code and "today" not in code and "time.time" not in code
    # No 20xx literal in executable code (docstrings cite measurements).
    body = re.sub(r'"""[\s\S]*?"""', "", source)
    assert not re.search(r"\b20\d\d\b", body)


# ── Supersession ──────────────────────────────────────────────────────


def test_a_retired_later_class_retires_an_unknown_earlier_one():
    # After a league rolls over, last season's draft leaves /drafts — the
    # earlier class is only provable through the later one.
    lcs = league_class_lifecycles([2025, 2026, 2027], _live_2026_main())
    assert lcs[2025].status == LIFECYCLE_RETIRED
    assert lcs[2025].reasons[0] == "superseded_by_retired_class:2026"
    assert lcs[2026].status == LIFECYCLE_RETIRED
    assert lcs[2027].status == LIFECYCLE_UNKNOWN
    assert retired_seasons(lcs) == {2025, 2026}


def test_supersession_never_overrides_an_active_class():
    picks = _picks(12)
    ev = _evidence(
        [_draft("live", 2025, "drafting"), _draft("r", 2026, "complete")],
        {"r": picks},
        [p["player_id"] for p in picks],
    )
    lcs = league_class_lifecycles([2025, 2026], ev)
    assert lcs[2025].status == LIFECYCLE_ACTIVE
    assert lcs[2026].status == LIFECYCLE_RETIRED


# ── Board scope ───────────────────────────────────────────────────────


def _retired(s: int) -> ClassLifecycle:
    return ClassLifecycle(s, LIFECYCLE_RETIRED, ("x",))


def test_board_retires_only_when_every_served_league_does():
    assert board_class_lifecycle(2026, {"a": _retired(2026), "b": _retired(2026)}).status == (
        LIFECYCLE_RETIRED
    )


def test_one_unknown_league_keeps_the_board_class():
    got = board_class_lifecycle(2026, {"a": _retired(2026), "b": None})
    assert got.status == LIFECYCLE_UNKNOWN
    assert any(r.startswith("b:unknown:no_draft_evidence") for r in got.reasons)


def test_one_active_league_keeps_the_board_class_active():
    active = ClassLifecycle(2026, LIFECYCLE_ACTIVE, ("draft_in_progress:d",))
    unknown = ClassLifecycle(2026, LIFECYCLE_UNKNOWN, ("no_draft_evidence",))
    got = board_class_lifecycle(2026, {"a": _retired(2026), "b": active, "c": unknown})
    assert got.status == LIFECYCLE_ACTIVE


def test_no_served_league_is_unknown_not_retired():
    assert board_class_lifecycle(2026, {}).status == LIFECYCLE_UNKNOWN


# ── Evidence shape ────────────────────────────────────────────────────


def test_evidence_counts_unobserved_as_none_never_zero():
    ev = evidence_from_sleeper(
        league_key="k",
        sleeper_league_id="1",
        drafts=[_draft("a", 2026, "complete"), _draft("b", 2026, "drafting")],
        picks_by_draft_id={"a": _picks(3)},
        rostered_player_ids=None,
        observed_at=None,
    )
    by_id = {d.draft_id: d for d in ev.drafts}
    assert by_id["a"].pick_count == 3 and by_id["a"].rookie_pick_count == 3
    assert by_id["a"].rostered_pick_count is None  # rosters unobserved
    assert by_id["b"].pick_count is None  # picks not fetched


def test_evidence_round_trips_and_refuses_unknown_schema():
    ev = _live_2026_main()
    again = LeagueDraftEvidence.from_dict(ev.to_dict())
    assert again == ev
    raw = ev.to_dict()
    raw["schemaVersion"] = 99
    assert LeagueDraftEvidence.from_dict(raw) is None
    assert LeagueDraftEvidence.from_dict(None) is None
    assert DraftObservation.from_dict({"draftId": ""}) is None


# ── History is untouched ──────────────────────────────────────────────


def test_retired_pick_identities_still_resolve():
    """Retirement is a present-tense verdict; identity has no notion of it."""
    ref = parse_board_pick_name("2026 Pick 1.03")
    assert ref is not None and ref.year == 2026 and ref.slot == 3
    tier = parse_board_pick_name("2026 Early 1st")
    assert tier is not None and tier.tier == "early"
    ident = LeaguePickIdentity("dynasty_main", 2026, 1, 7)
    assert parse_league_pick_id(ident.canonical_id) == ident
    # A stored trade label from before retirement.
    label = parse_pick_label("2026 1.02 (from Blaine)")
    assert label is not None and label.year == 2026 and label.slot == 2


def test_first_active_class_steps_past_retired_classes():
    assert first_active_class(2026, []) == 2026
    assert first_active_class(2026, [2026]) == 2027
    assert first_active_class(2026, [2026, 2027]) == 2028
    assert first_active_class(2026, [2025, 2028]) == 2026  # only a contiguous run moves it
