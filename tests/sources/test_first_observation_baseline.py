"""D1 (2026-10-07 audit): FETCHED RECENTLY is not CONTENT FRESH.

The first time a board is observed, ``dataset_state.observe`` stamps every
data clock with the OBSERVATION (fetch) time, because that is the only time
it has — and marks the subset ``firstObservationIsBaseline``.  The observation
time is therefore only an UPPER bound on when the content was published, so
the age measured from it is a LOWER bound on the content's real age:

* it can prove a board is at least so stale (the decay it implies is real
  evidence and is kept — no blend weight changes);
* it can NEVER prove a board is fresh.  A baseline that would read
  ``ON_SCHEDULE`` is ``UNMEASURED`` instead (which carries the same neutral
  weight, 1.0 — so the published blend is untouched);
* it never publishes a fetch time as ``sourceDataAsOf``.

Once the source publishes a genuine broad change after the baseline, the
normal clock applies again; a vendor-stated publication time
(``EXPLICIT_UPSTREAM_TIMESTAMP``) is a real clock and is not a baseline.
"""

from __future__ import annotations

import dataclasses
from datetime import datetime, timedelta, timezone

import pytest

from src.sources import freshness as fr
from src.sources.dataset_integrity import parse_board
from src.sources.dataset_state import observe

T0 = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)
CFG = fr.load_config()


def _board(bump: int = 0) -> str:
    return "name,value\n" + "".join(f"P{i},{1000 + i + bump}\n" for i in range(60))


def _first_seen(source_key: str = "dlfSf", at: datetime = T0) -> dict:
    return observe(None, source_key=source_key, board=parse_board(_board()), observed_at=at)


class TestFirstObservationIsNotProvenFresh:
    def test_board_first_seen_two_hours_ago_is_unmeasured_not_on_schedule(self):
        state = _first_seen()
        sw = fr.assess_source("dlfSf", state, as_of=T0 + timedelta(hours=2), cfg=CFG)
        sub = sw.subsets["players"]
        assert sub.state == fr.STATE_UNMEASURED
        assert sub.state != fr.STATE_ON_SCHEDULE

    def test_fetch_time_is_never_published_as_source_data_as_of(self):
        state = _first_seen()
        d = fr.assess_source("dlfSf", state, as_of=T0 + timedelta(hours=2), cfg=CFG).to_dict()
        players = d["subsets"]["players"]
        assert players["sourceDataAsOf"] is None
        assert players["clockIsObservationBaseline"] is True
        assert players["ageIsLowerBound"] is True
        assert players["observationBaselineAt"] == "2026-10-07T12:00:00Z"
        # The baseline is not presented as a dataset change either.
        assert players["lastBroadDatasetChangeAt"] is None
        assert players["lastAnyMeaningfulChangeAt"] is None

    def test_neutral_weight_is_unchanged(self):
        """UNMEASURED carries the same neutral factor ON_SCHEDULE did (1.0):
        relabelling changes no blend weight."""
        state = _first_seen()
        sw = fr.assess_source("dlfSf", state, as_of=T0 + timedelta(hours=2), cfg=CFG)
        assert sw.subsets["players"].freshness == 1.0
        assert sw.factor_for_row(is_pick=False, row_key="p1") == (1.0, pytest.approx(2.0))
        unmeasured = fr.assess_source("dlfSf", None, as_of=T0, cfg=CFG)
        assert unmeasured.factor_for_row(is_pick=False, row_key="p1")[0] == 1.0

    def test_lower_bound_still_proves_staleness_and_keeps_its_decay(self):
        """Content first seen 20 days ago is AT LEAST 20 days old: the decay
        that lower bound implies is evidence, kept exactly as before."""
        state = _first_seen(at=T0 - timedelta(days=20))
        sub = fr.assess_source("dlfSf", state, as_of=T0, cfg=CFG).subsets["players"]
        assert sub.age_hours == pytest.approx(480.0)
        expected = fr.freshness_from_ratio(480.0 / sub.expected_hours, CFG.curve)
        assert sub.freshness == pytest.approx(expected if expected >= CFG.quarantine_below else 0)
        assert sub.freshness < 0.95
        assert sub.state not in (fr.STATE_ON_SCHEDULE, fr.STATE_UNMEASURED)
        assert sub.to_dict()["sourceDataAsOf"] is None

    def test_a_genuine_broad_change_ends_the_baseline(self):
        state = _first_seen()
        changed_at = T0 + timedelta(hours=6)
        state = observe(
            state, source_key="dlfSf", board=parse_board(_board(bump=7)), observed_at=changed_at
        )
        sub = fr.assess_source("dlfSf", state, as_of=changed_at + timedelta(hours=2), cfg=CFG)
        players = sub.subsets["players"]
        assert players.state == fr.STATE_ON_SCHEDULE
        d = players.to_dict()
        assert d["sourceDataAsOf"] == "2026-10-07T18:00:00Z"
        assert d["clockIsObservationBaseline"] is False

    def test_replaying_a_board_from_before_the_first_change_is_a_baseline_again(self):
        state = _first_seen()
        state = observe(
            state,
            source_key="dlfSf",
            board=parse_board(_board(bump=7)),
            observed_at=T0 + timedelta(days=3),
        )
        past = fr.assess_source("dlfSf", state, as_of=T0 + timedelta(hours=2), cfg=CFG)
        players = past.subsets["players"]
        assert players.state == fr.STATE_UNMEASURED
        assert players.to_dict()["sourceDataAsOf"] is None

    def test_vendor_stated_publication_time_is_a_real_clock(self):
        cfg = dataclasses.replace(
            CFG,
            sources={
                **CFG.sources,
                "idpShowCombined": fr.SourceCadence(168, 72, 336, style=fr.STYLE_EXPLICIT),
            },
        )
        state = _first_seen("idpShowCombined")
        state["upstream"] = {"publishedAt": "2026-10-07T09:00:00Z"}
        sub = fr.assess_source("idpShowCombined", state, as_of=T0 + timedelta(hours=2), cfg=cfg)
        players = sub.subsets["players"]
        assert players.clock == "upstreamPublishedAt"
        assert players.state == fr.STATE_ON_SCHEDULE
        assert players.to_dict()["sourceDataAsOf"] == "2026-10-07T09:00:00Z"
