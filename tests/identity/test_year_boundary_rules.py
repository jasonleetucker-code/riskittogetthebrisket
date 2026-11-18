"""2026 -> 2027 year-boundary rules, pinned at the three boundary instants.

Every expectation below is DERIVED from the written rules (CLAUDE.md "Draft
years and owned-pick ownership", "Pick identity", the BDVM in-season section
and the owner's 2026-10-19 horizon decision) — never from "what the code
returned the day this was written" — and no date here is "today": the instants
are fixed, so the test cannot expire.

The three instants, all UTC (the repo's clock convention; no year logic reads
local time):

* ``2026-12-31T23:30Z`` — last half hour of 2026.
* ``2027-01-01T00:30Z`` — first half hour of 2027.
* ``2027-01-02T12:00Z`` — the first ordinary 2027 day.

Plus ``2027-01-01T03:00Z`` — already 2027 in UTC, still 2026-12-31 in
``America/Los_Angeles``.  The rules are UTC-defined, so UTC is the answer for
every viewer; this pins that no surface silently follows the viewer's zone.

Rules the expectations come from:

* BOARD draft year = the rookie draft the vendors price as current.  Its
  date-derived fallback rolls ``year + 1`` only at the configured
  ``(rolloverMonth, rolloverDay)`` (May 15) — NOT at New Year — so it must be
  continuous across Jan 1.
* BOARD pick horizon END = latest PROVEN-completed class + 3 (floored at
  ``anchor - 1``); a calendar flip alone must not add a season (owner
  2026-10-19: 2030 arrives only when the 2027 draft is proven complete).
* LEAGUE anchor = ``max(calendar year, Sleeper league.season)``; the owned
  window spans ``OWNED_PICK_HORIZON_CLASSES`` (4) classes from it, minus
  classes proven retired; ``upcoming`` = first non-retired class >= anchor.
* NFL season (BDVM actuals): Sept-Dec -> year, Jan -> year - 1, Feb-Aug ->
  None; the projection season agrees wherever the former answers.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from src.api import data_contract
from src.api import draft_class_evidence as dce
from src.bdvm import actuals
from src.identity import pick_lifecycle as lc
from src.identity.pick_lifecycle import (
    HORIZON_BASIS_ANCHOR_FLOOR,
    HORIZON_BASIS_PROVEN,
    LIFECYCLE_RETIRED,
    ClassLifecycle,
    board_pick_horizon,
    league_draft_anchor_year,
    league_draft_years,
)

INSTANTS = {
    "2026-12-31T23:30Z": datetime(2026, 12, 31, 23, 30, tzinfo=timezone.utc),
    "2027-01-01T00:30Z": datetime(2027, 1, 1, 0, 30, tzinfo=timezone.utc),
    "2027-01-02T12:00Z": datetime(2027, 1, 2, 12, 0, tzinfo=timezone.utc),
    "2027-01-01T03:00Z (LA still 2026-12-31)": datetime(2027, 1, 1, 3, 0, tzinfo=timezone.utc),
}
UTC_YEAR = {k: v.year for k, v in INSTANTS.items()}
IDS = list(INSTANTS)


def _retired(*seasons: int) -> dict[int, ClassLifecycle]:
    return {s: ClassLifecycle(s, LIFECYCLE_RETIRED, ("test",)) for s in seasons}


def _clock_at(instant: datetime):
    """A ``datetime`` class whose ``now()`` answers ``instant`` (injected seam)."""

    class _At(datetime):
        @classmethod
        def now(cls, tz=None):  # type: ignore[override]
            return instant.astimezone(tz) if tz is not None else instant.replace(tzinfo=None)

    return _At


# ── BOARD scope ────────────────────────────────────────────────────────────


@pytest.fixture
def no_override_no_observation(monkeypatch):
    """Step 3 of ``current_rookie_draft_year`` on its own: no config override,
    no data-observed year (those two are clock-independent by design)."""
    cfg = dict(data_contract._load_pick_year_discount())
    cfg["currentDraftYear"] = None
    monkeypatch.setattr(data_contract, "_load_pick_year_discount", lambda: cfg)
    monkeypatch.setattr(data_contract, "_OBSERVED_CURRENT_DRAFT_YEAR", None)
    return cfg


@pytest.mark.parametrize("label", IDS)
def test_board_draft_year_does_not_step_at_new_year(label, no_override_no_observation):
    """Derivation: the fallback rolls ``year + 1`` only on/after the configured
    rollover (May 15), so on every instant between New Year's Eve and Jan 2 the
    upcoming rookie draft is the NEW calendar year (2027), identical to what it
    was on 2026-12-31 (already rolled in May 2026 -> 2027)."""
    day = INSTANTS[label].date()
    assert data_contract.rookie_draft_year_on(day) == 2027
    assert data_contract.current_rookie_draft_year(today=day) == 2027


def test_board_draft_year_steps_exactly_at_the_configured_rollover(no_override_no_observation):
    """Derivation: the only step in a year is at ``(rolloverMonth, rolloverDay)``."""
    rm = int(no_override_no_observation.get("rolloverMonth") or 5)
    rd = int(no_override_no_observation.get("rolloverDay") or 15)
    before = date(2027, rm, rd).fromordinal(date(2027, rm, rd).toordinal() - 1)
    assert data_contract.rookie_draft_year_on(before) == 2027
    assert data_contract.rookie_draft_year_on(date(2027, rm, rd)) == 2028
    # and it is flat from the rollover through the next New Year
    assert data_contract.rookie_draft_year_on(date(2027, 12, 31)) == 2028
    assert data_contract.rookie_draft_year_on(date(2028, 1, 1)) == 2028


@pytest.mark.parametrize("label", IDS)
def test_board_horizon_end_is_not_moved_by_the_calendar(label):
    """Derivation: end = latest completed class + 3.  With the 2026 class proven
    retired (the live fact today) and the 2027 class not, the end is 2029 on
    every instant — the calendar flip adds no 2030 (owner 2026-10-19)."""
    anchor = 2027  # the vendors' current class is 2027 across the whole window
    h = board_pick_horizon(anchor, _retired(2026))
    assert (h.latest_completed_class, h.end_year, h.basis) == (2026, 2029, HORIZON_BASIS_PROVEN)
    # Unproven completion fails closed onto the floor: anchor - 1 -> same 2029.
    unproven = board_pick_horizon(anchor, {})
    assert (unproven.latest_completed_class, unproven.end_year) == (2026, 2029)
    assert unproven.basis == HORIZON_BASIS_ANCHOR_FLOOR
    # 2030 arrives only when the 2027 draft is PROVEN complete.
    assert board_pick_horizon(anchor, _retired(2026, 2027)).end_year == 2030


# ── NFL season (BDVM in-season) ────────────────────────────────────────────


@pytest.mark.parametrize("label", IDS)
def test_nfl_season_is_2026_through_the_boundary(label):
    """Derivation: week 18 spills into early January, so Jan 1-2 2027 are still
    the 2026 season (Jan -> year - 1); Dec 31 2026 -> 2026 (Sept-Dec -> year).
    The projection season agrees by construction."""
    day = INSTANTS[label].date()
    assert actuals.current_nfl_season(day) == 2026
    assert actuals.nfl_projection_season(day) == 2026


def test_nfl_season_window_closes_in_february_and_reopens_in_september():
    assert actuals.current_nfl_season(date(2027, 1, 31)) == 2026
    assert actuals.current_nfl_season(date(2027, 2, 1)) is None
    assert actuals.current_nfl_season(date(2027, 8, 31)) is None
    assert actuals.current_nfl_season(date(2027, 9, 1)) == 2027
    # Projection season keeps answering outside the window: Feb-Aug -> upcoming year.
    assert actuals.nfl_projection_season(date(2027, 2, 1)) == 2027


def test_nfl_season_default_reads_the_utc_clock(monkeypatch):
    """No arg -> the UTC date.  At 2027-01-01T03:00Z it is Jan 1 in UTC (still
    Dec 31 in Los Angeles); the season is 2026 either way, and the module must
    not follow the viewer's zone."""
    monkeypatch.setattr(
        actuals, "datetime", _clock_at(INSTANTS["2027-01-01T03:00Z (LA still 2026-12-31)"])
    )
    assert actuals.current_nfl_season() == 2026


# ── LEAGUE scope ───────────────────────────────────────────────────────────


@pytest.mark.parametrize("label", IDS)
def test_league_anchor_follows_the_utc_calendar_year(label):
    """Derivation: anchor = max(calendar year, league season).  A league whose
    Sleeper ``season`` is still 2026 (renewed in spring) anchors at 2027 from
    the first UTC second of 2027 — including 03:00Z, when Los Angeles is still
    on Dec 31."""
    year = UTC_YEAR[label]
    assert league_draft_anchor_year("2026", calendar_year=year) == year
    # an UNKNOWN league season is absent from the max, never 0
    assert league_draft_anchor_year(None, calendar_year=year) == year
    # a league already on the next season is never dragged back by the calendar
    assert league_draft_anchor_year("2027", calendar_year=2026) == 2027


@pytest.mark.parametrize("label", IDS)
def test_league_years_for_reads_the_injected_clock(label, monkeypatch):
    """``league_draft_years_for`` with no ``calendar_year`` reads the UTC clock.
    No evidence retires nothing, so upcoming == anchor and the window is the
    four classes from the anchor."""
    monkeypatch.setattr(dce, "datetime", _clock_at(INSTANTS[label]))
    got = dce.league_draft_years_for(None, league_season="2026", evidence=None)
    year = UTC_YEAR[label]
    assert got.anchor_year == year
    assert got.upcoming_draft_year == year
    assert got.owned_pick_seasons == tuple(range(year, year + lc.OWNED_PICK_HORIZON_CLASSES))


def test_league_upcoming_class_is_continuous_when_2026_is_proven_retired():
    """Live fact today: the 2026 class is retired, the 2027 class is not.
    Derivation: ``upcoming`` = first non-retired class >= anchor.  Before the
    flip (anchor 2026) that steps past 2026 to 2027; after it (anchor 2027) it
    is 2027 directly — the upcoming draft is 2027 on BOTH sides of Jan 1, and a
    retired 2026 never reappears in the owned seasons."""
    before = league_draft_years(2026, _retired(2026))
    after = league_draft_years(2027, _retired(2026))
    assert before.upcoming_draft_year == after.upcoming_draft_year == 2027
    assert 2026 not in before.owned_pick_seasons and 2026 not in after.owned_pick_seasons
    assert before.owned_pick_seasons == (2027, 2028, 2029)
    assert before.retired_seasons == (2026,)
    assert after.retired_seasons == ()  # classes before the anchor are not reported


def test_documented_divergence_league_window_reaches_one_class_past_the_board_horizon():
    """DOCUMENTED, NOT ENDORSED — the one place the two scopes disagree at the
    boundary, pinned so changing it is a deliberate owner decision.

    League scope spans ``OWNED_PICK_HORIZON_CLASSES`` (4) classes FROM THE
    CALENDAR ANCHOR, so from 2027-01-01 (2027 draft not yet complete) it covers
    2027..2030.  Board scope ends three seasons after the latest COMPLETED draft
    (2026) = 2029, and the owner's 2026-10-19 decision says 2030 arrives only
    when the 2027 draft is proven complete.  Until then a 2030 league pick has
    no board price (it is reported ``isUnpriced``/unavailable, never 0).
    """
    league = league_draft_years(2027, _retired(2026))
    board = board_pick_horizon(2027, _retired(2026))
    assert max(league.owned_pick_seasons) == board.end_year + 1 == 2030
