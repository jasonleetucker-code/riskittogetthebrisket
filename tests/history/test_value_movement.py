"""IC-7 / UI-contract §10: two-generation value-movement attribution.

``src/history/movement.py`` reads the temporal ledger and reports the
CONTRIBUTING EVIDENCE between two board generations.  What must never blur:

* a source absent at one generation is ``appeared`` / ``disappeared`` with
  ``delta: None`` — absent is never a 0 delta, and a nearest-prior carry is
  never presence;
* no comparator is an explicit status + reason, never a zero change;
* a request before the permanent history floor answers
  ``before_history_boundary``;
* an observation after the requested date is never selected;
* the answer is labelled non-additive, and the quantities the ledger does not
  store (weights, freshness, vote state, flags) are named as unobserved;
* the comparator is the SAME board ``rankChange`` diffs against.

All ledgers are synthetic, written through the store's own write path.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.history import asof, movement, store

ASSET = "player:4034"
OTHER = "player:9999"


def _obs(
    asset_key: str,
    date: str,
    *,
    lane: str = store.LANE_CANONICAL,
    source_key: str = "",
    value: float | None = None,
    rank: int | None = None,
    tier: int | None = None,
    confidence: str | None = None,
    pipeline_version: str | None = "2026-03-10.v2+aaaa1111",
    observed_at: str | None = None,
) -> dict:
    canonical = lane == store.LANE_CANONICAL
    return {
        "asset_key": asset_key,
        "asset_class": "offense",
        "lane": lane,
        "source_key": source_key,
        "observed_date": date,
        "observed_at": observed_at or f"{date}T11:00:00+00:00",
        "observed_at_zone": "utc",
        "value": value,
        "rank": rank,
        "tier": tier,
        "confidence": confidence,
        "display_name": "Test Player",
        "position": "RB",
        "player_id": asset_key.split(":", 1)[1],
        "scope": None,
        "pipeline_version": pipeline_version if canonical else None,
        "origin": "live:server",
    }


def _src(asset_key: str, date: str, source_key: str, value: float) -> dict:
    return _obs(asset_key, date, lane=store.LANE_SOURCE, source_key=source_key, value=value)


@pytest.fixture()
def ledger(tmp_path: Path) -> Path:
    store._reset_setup_cache_for_tests()
    return tmp_path / "temporal_ledger.sqlite"


def _write(path: Path, rows: list[dict]) -> None:
    result = store.write_observations(rows, path=path)
    assert not result["rejected"], result["rejected"]
    assert not result["contentConflicts"]


def _two_generation_ledger(path: Path) -> None:
    _write(
        path,
        [
            _obs(ASSET, "2026-09-01", value=6000, rank=40, tier=3, confidence="medium"),
            _obs(ASSET, "2026-09-02", value=6400, rank=31, tier=2, confidence="high"),
            # moved
            _src(ASSET, "2026-09-01", "ktcCrowdSfTep", 6100),
            _src(ASSET, "2026-09-02", "ktcCrowdSfTep", 6500),
            # unchanged
            _src(ASSET, "2026-09-01", "ktcTradesSfTep", 5900),
            _src(ASSET, "2026-09-02", "ktcTradesSfTep", 5900),
            # disappeared
            _src(ASSET, "2026-09-01", "idpTradeCalc", 6200),
            # appeared
            _src(ASSET, "2026-09-02", "ktcCrowdTradesSfTep", 6300),
            # an unrelated asset on the same boards
            _obs(OTHER, "2026-09-01", value=100, rank=700),
            _obs(OTHER, "2026-09-02", value=110, rank=690),
        ],
    )


def _by_source(result: dict) -> dict:
    return {s["source"]: s for s in result["sources"]}


def test_two_generations_report_canonical_change_and_per_source_evidence(ledger):
    _two_generation_ledger(ledger)
    got = movement.value_movement(ASSET, as_of="2026-09-02", path=ledger)

    assert got["status"] == movement.STATUS_OK
    assert got["current"]["observedDate"] == "2026-09-02"
    assert got["current"]["fidelity"] == asof.FIDELITY_EXACT
    assert got["previous"]["observedDate"] == "2026-09-01"
    assert got["comparatorBoardDate"] == "2026-09-01"
    assert got["change"]["value"] == 400
    # rankChange convention: positive = moved up the board.
    assert got["change"]["rank"] == 9
    assert got["change"]["tierChanged"] is True
    assert got["change"]["confidenceChanged"] is True

    src = _by_source(got)
    assert src["ktcCrowdSfTep"]["status"] == movement.SOURCE_MOVED
    assert src["ktcCrowdSfTep"]["delta"] == 400
    assert src["ktcTradesSfTep"]["status"] == movement.SOURCE_UNCHANGED
    assert src["ktcTradesSfTep"]["delta"] == 0
    assert "signalsSf" in got["sourcesNotObservedAtEitherGeneration"]
    assert "signalsSf" not in src


def test_absent_source_is_appeared_or_disappeared_never_a_zero_delta(ledger):
    _two_generation_ledger(ledger)
    src = _by_source(movement.value_movement(ASSET, as_of="2026-09-02", path=ledger))

    gone = src["idpTradeCalc"]
    assert gone["status"] == movement.SOURCE_DISAPPEARED
    assert gone["delta"] is None
    assert gone["current"]["present"] is False
    assert gone["current"]["value"] is None
    # The prior value is context ("last seen"), not a value at this generation.
    assert gone["current"]["lastObservedDate"] == "2026-09-01"

    new = src["ktcCrowdTradesSfTep"]
    assert new["status"] == movement.SOURCE_APPEARED
    assert new["delta"] is None
    assert new["previous"]["present"] is False
    assert new["previous"]["value"] is None


def test_answer_is_labelled_non_additive_and_names_unobserved_quantities(ledger):
    _two_generation_ledger(ledger)
    got = movement.value_movement(ASSET, as_of="2026-09-02", path=ledger)

    assert got["additive"] is False
    assert got["evidenceNotCause"] is True
    assert "do not sum" in got["nonAdditiveNote"]
    unobserved = {u["quantity"] for u in got["unobserved"]}
    assert {
        "sourceWeights",
        "sourceFreshness",
        "voteState",
        "anomalyFlags",
        "rankSignalSourceValues",
    } <= unobserved
    # Nothing in the answer claims a weight or freshness for either generation.
    for s in got["sources"]:
        assert "weight" not in s and "freshness" not in s
        # No decomposition: nothing publishes a share of the value change.
        assert not any("share" in k.lower() for k in s)


def test_single_generation_has_no_comparator_rather_than_a_zero_change(ledger):
    _write(ledger, [_obs(ASSET, "2026-09-02", value=6400, rank=31)])
    got = movement.value_movement(ASSET, as_of="2026-09-02", path=ledger)

    assert got["status"] == movement.STATUS_NO_COMPARATOR
    assert got["missingReason"] == movement.REASON_NO_PRIOR_BOARD
    assert got["change"] is None
    assert got["previous"] is None
    assert got["sources"] == []
    assert got["current"]["value"] == 6400


def test_asset_new_to_the_board_has_no_comparator_with_the_ledger_reason(ledger):
    _write(
        ledger,
        [
            _obs(OTHER, "2026-09-01", value=100, rank=700),
            _obs(ASSET, "2026-09-02", value=6400, rank=31),
        ],
    )
    got = movement.value_movement(ASSET, as_of="2026-09-02", path=ledger)
    assert got["status"] == movement.STATUS_NO_COMPARATOR
    assert got["comparatorBoardDate"] == "2026-09-01"
    assert got["missingReason"] == asof.REASON_NO_PRIOR
    assert got["change"] is None


def test_request_before_the_history_floor_answers_the_boundary(ledger):
    _two_generation_ledger(ledger)
    got = movement.value_movement(ASSET, as_of="2026-07-01", path=ledger)
    assert got["status"] == movement.STATUS_NO_CURRENT
    assert got["missingReason"] == asof.REASON_BEFORE_BOUNDARY
    assert got["historyFloor"] == store.HISTORY_FLOOR
    assert got["current"] is None and got["change"] is None


def test_never_selects_an_observation_after_the_requested_date(ledger):
    _two_generation_ledger(ledger)
    _write(ledger, [_obs(ASSET, "2026-09-03", value=9999, rank=1)])
    got = movement.value_movement(ASSET, as_of="2026-09-02", path=ledger)
    assert got["current"]["observedDate"] == "2026-09-02"
    assert got["current"]["value"] == 6400
    assert got["change"]["value"] == 400


def test_comparator_is_the_same_board_rank_change_diffs_against(ledger):
    _two_generation_ledger(ledger)
    _write(ledger, [_obs(OTHER, "2026-09-03", value=120, rank=680)])
    # The asset is absent from the 09-03 board; its latest generation is 09-02.
    got = movement.value_movement(ASSET, as_of="2026-09-03", path=ledger)
    assert got["current"]["observedDate"] == "2026-09-02"
    assert got["current"]["fidelity"] == asof.FIDELITY_NEAREST_PRIOR
    assert asof.previous_board_date(before_date="2026-09-02", path=ledger) == "2026-09-01"
    assert got["comparatorBoardDate"] == "2026-09-01"
    # previous_board_ranks (rankChange's comparator) uses the shared rule.
    prev_ranks = asof.previous_board_ranks(before_date="2026-09-03", path=ledger)
    assert prev_ranks[ASSET] == ("2026-09-02", 31)


def test_asset_absent_from_comparator_board_carries_nearest_prior_fidelity(ledger):
    _write(
        ledger,
        [
            _obs(ASSET, "2026-09-01", value=6000, rank=40),
            _obs(OTHER, "2026-09-02", value=110, rank=690),
            _obs(ASSET, "2026-09-03", value=6600, rank=25),
        ],
    )
    got = movement.value_movement(ASSET, as_of="2026-09-03", path=ledger)
    assert got["status"] == movement.STATUS_OK
    assert got["comparatorBoardDate"] == "2026-09-02"
    assert got["previous"]["observedDate"] == "2026-09-01"
    assert got["previous"]["fidelity"] == asof.FIDELITY_NEAREST_PRIOR
    assert got["change"]["value"] == 600


def test_pipeline_version_change_is_methodology_evidence_and_unknown_is_not_unchanged(ledger):
    _write(
        ledger,
        [
            _obs(ASSET, "2026-09-01", value=6000, rank=40, pipeline_version="v2+aaaa1111"),
            _obs(ASSET, "2026-09-02", value=6400, rank=31, pipeline_version="v2+bbbb2222"),
            _obs(OTHER, "2026-09-01", value=100, rank=700, pipeline_version=None),
            _obs(OTHER, "2026-09-02", value=110, rank=690, pipeline_version="v2+bbbb2222"),
        ],
    )
    got = movement.value_movement(ASSET, as_of="2026-09-02", path=ledger)
    assert got["methodology"]["pipelineVersionChanged"] is True
    assert got["methodology"]["previousPipelineVersion"] == "v2+aaaa1111"

    other = movement.value_movement(OTHER, as_of="2026-09-02", path=ledger)
    assert other["methodology"]["pipelineVersionChanged"] is None


def test_missing_ledger_is_unavailable_and_is_not_created_by_the_read(ledger):
    assert not ledger.exists()
    got = movement.value_movement(ASSET, as_of="2026-09-02", path=ledger)
    assert got["status"] == movement.STATUS_NO_CURRENT
    assert got["missingReason"] == asof.REASON_NO_PRIOR
    assert not ledger.exists()
    assert asof.previous_board_date(before_date="2026-09-02", path=ledger) is None


# ── Generation identity: several scrapes share a date (review D2 / F1 / F3) ──


def _two_scrapes_one_date_ledger(path: Path) -> None:
    """The reviewer's repro: production records every 2h scrape, so two
    generations on 09-02; ktcCrowd answered at 08:00 and FAILED at 22:00."""
    d1_20 = "2026-09-01T20:00:00+00:00"
    d2_08 = "2026-09-02T08:00:00+00:00"
    d2_22 = "2026-09-02T22:00:00+00:00"
    _write(
        path,
        [
            _obs(ASSET, "2026-09-01", value=6000, rank=40, observed_at=d1_20),
            {**_src(ASSET, "2026-09-01", "ktcCrowdSfTep", 6100), "observed_at": d1_20},
            _obs(ASSET, "2026-09-02", value=6050, rank=39, observed_at=d2_08),
            {**_src(ASSET, "2026-09-02", "ktcCrowdSfTep", 6150), "observed_at": d2_08},
            _obs(ASSET, "2026-09-02", value=5200, rank=60, observed_at=d2_22),
            # no ktcCrowd row at 22:00 — the source failed that scrape
        ],
    )


def test_source_must_come_from_the_canonical_ends_own_scrape(ledger):
    """REGRESSION (review D2): the 08:00 ktcCrowd row is not evidence about
    the 22:00 generation.  On the first head this reported ktcCrowd present
    at 6150 (+50); it must be ``disappeared``."""
    _two_scrapes_one_date_ledger(ledger)
    got = movement.value_movement(ASSET, as_of="2026-09-02", path=ledger)

    assert got["current"]["value"] == 5200
    assert got["current"]["observedAt"] == "2026-09-02T22:00:00+00:00"
    assert got["change"]["value"] == -800
    crowd = _by_source(got)["ktcCrowdSfTep"]
    assert crowd["status"] == movement.SOURCE_DISAPPEARED
    assert crowd["delta"] is None
    assert crowd["current"]["present"] is False
    assert crowd["current"]["lastObservedAt"] == "2026-09-02T08:00:00+00:00"
    assert crowd["previous"]["generationMatch"] == asof.GENERATION_MATCH_INSTANT


def test_served_instant_pins_never_future_within_the_day(ledger):
    """Review F3: a board served at 08:00 cannot be explained with the 22:00
    scrape recorded later the same day."""
    _two_scrapes_one_date_ledger(ledger)
    got = movement.value_movement(
        ASSET, as_of="2026-09-02", served_instant="2026-09-02T08:00:00+00:00", path=ledger
    )
    assert got["currentSelection"] == movement.SELECTION_SERVED_GENERATION
    assert got["current"]["value"] == 6050
    assert got["currentIsServedGeneration"] is True
    assert got["currentIsServedGenerationBasis"] == asof.GENERATION_MATCH_INSTANT
    crowd = _by_source(got)["ktcCrowdSfTep"]
    assert crowd["status"] == movement.SOURCE_MOVED
    assert crowd["delta"] == 50


def test_ledger_behind_the_served_scrape_is_detected_on_the_instant(ledger):
    """Review F2: same date, but the served scrape (23:30) was never recorded —
    the date matches, the generation does not."""
    _two_scrapes_one_date_ledger(ledger)
    got = movement.value_movement(
        ASSET, as_of="2026-09-02", served_instant="2026-09-02T23:30:00+00:00", path=ledger
    )
    assert got["currentSelection"] == movement.SELECTION_KNOWN_BEFORE_INSTANT
    assert got["current"]["observedAt"] == "2026-09-02T22:00:00+00:00"
    assert got["currentIsServedGeneration"] is False
    assert got["currentIsServedGenerationBasis"] == asof.GENERATION_MATCH_INSTANT
    # A served instant that IS recorded matches.
    same = movement.value_movement(
        ASSET, as_of="2026-09-02", served_instant="2026-09-02T22:00:00+00:00", path=ledger
    )
    assert same["currentIsServedGeneration"] is True


def test_instant_less_legacy_source_rows_match_by_date_and_say_so(ledger):
    _write(
        ledger,
        [
            _obs(ASSET, "2026-09-01", value=6000, rank=40),
            {**_src(ASSET, "2026-09-01", "ktcCrowdSfTep", 6100), "observed_at": None},
            _obs(ASSET, "2026-09-02", value=6400, rank=31),
            _src(ASSET, "2026-09-02", "ktcCrowdSfTep", 6500),
        ],
    )
    crowd = _by_source(movement.value_movement(ASSET, as_of="2026-09-02", path=ledger))[
        "ktcCrowdSfTep"
    ]
    assert crowd["previous"]["present"] is True
    assert crowd["previous"]["generationMatch"] == asof.GENERATION_MATCH_DATE
    assert crowd["current"]["generationMatch"] == asof.GENERATION_MATCH_INSTANT
    assert crowd["delta"] == 400


def test_rank_change_alignment_is_stated(ledger):
    """Review F1: the movement diffs the same boards as rankChange only when
    the asset is on both; otherwise the payload says why it diverges."""
    _two_generation_ledger(ledger)
    ok = movement.value_movement(ASSET, as_of="2026-09-02", path=ledger)
    assert ok["rankChangeAlignment"] == {
        "sameBoardsAsRankChange": True,
        "rankChangeComparatorDate": "2026-09-01",
        "reasons": [],
    }

    _write(
        ledger,
        [
            _obs(OTHER, "2026-09-03", value=120, rank=680),
            _obs(ASSET, "2026-09-04", value=6600, rank=25),
            _obs(OTHER, "2026-09-04", value=130, rank=670),
        ],
    )
    gap = movement.value_movement(ASSET, as_of="2026-09-04", path=ledger)
    assert gap["comparatorBoardDate"] == "2026-09-03"
    assert gap["previous"]["observedDate"] == "2026-09-02"
    align = gap["rankChangeAlignment"]
    assert align["sameBoardsAsRankChange"] is False
    assert movement.ALIGN_ABSENT_FROM_COMPARATOR_BOARD in align["reasons"]

    behind = movement.value_movement(ASSET, as_of="2026-09-05", path=ledger)
    assert movement.ALIGN_LEDGER_BEHIND_SERVED_BOARD in (behind["rankChangeAlignment"]["reasons"])
    assert behind["rankChangeAlignment"]["sameBoardsAsRankChange"] is False


def test_board_dated_after_its_utc_instant_is_found_not_reported_behind(ledger):
    """REGRESSION (re-review follow-up 1, Repro H): ``observed_date`` is the
    producer's board date (box-local, ~2h ahead of UTC), so a board dated
    09-03 can carry the instant 09-02T23:00Z.  An instant-bounded search
    looks at dates <= 09-02 and answered the 22:00 generation as "ledger
    behind"; the ledger HAS the served board and must select it."""
    d2_22 = "2026-09-02T22:00:00+00:00"
    d3_board = "2026-09-02T23:00:00+00:00"
    _write(
        ledger,
        [
            _obs(ASSET, "2026-09-02", value=6000, rank=40, observed_at=d2_22),
            {**_src(ASSET, "2026-09-02", "ktcCrowdSfTep", 6100), "observed_at": d2_22},
            _obs(ASSET, "2026-09-03", value=6400, rank=31, observed_at=d3_board),
            {**_src(ASSET, "2026-09-03", "ktcCrowdSfTep", 6450), "observed_at": d3_board},
        ],
    )
    got = movement.value_movement(ASSET, as_of="2026-09-03", served_instant=d3_board, path=ledger)
    assert got["currentSelection"] == movement.SELECTION_SERVED_GENERATION
    assert got["current"]["observedDate"] == "2026-09-03"
    assert got["current"]["value"] == 6400
    assert got["currentIsServedGeneration"] is True
    assert got["rankChangeAlignment"]["reasons"] == []
    assert got["rankChangeAlignment"]["sameBoardsAsRankChange"] is True
    assert got["previous"]["observedDate"] == "2026-09-02"
    assert got["change"]["value"] == 400
    assert _by_source(got)["ktcCrowdSfTep"]["delta"] == 350


def test_exact_served_match_never_selects_a_later_scrape(ledger):
    """The exact match is the served instant only: a later scrape on the same
    board date is never chosen, and a served instant the ledger lacks falls
    back to instant-strict selection (nothing after it)."""
    _write(
        ledger,
        [
            _obs(ASSET, "2026-09-02", value=6000, rank=40, observed_at="2026-09-02T08:00:00+00:00"),
            _obs(ASSET, "2026-09-02", value=9000, rank=2, observed_at="2026-09-02T22:00:00+00:00"),
        ],
    )
    got = movement.value_movement(
        ASSET, as_of="2026-09-02", served_instant="2026-09-02T09:00:00+00:00", path=ledger
    )
    assert got["currentSelection"] == movement.SELECTION_KNOWN_BEFORE_INSTANT
    assert got["current"]["value"] == 6000


def test_date_match_refused_when_the_generation_stamped_its_source_rows(ledger):
    """Re-review follow-up 2: the 09-02 11:00 scrape recorded ktcTrades with
    its instant, so an instant-less ktcCrowd row that day is not that
    scrape's evidence — ktcCrowd is absent from it, not date-matched."""
    _write(
        ledger,
        [
            _obs(ASSET, "2026-09-01", value=6000, rank=40),
            _src(ASSET, "2026-09-01", "ktcCrowdSfTep", 6100),
            _src(ASSET, "2026-09-01", "ktcTradesSfTep", 5900),
            _obs(ASSET, "2026-09-02", value=6400, rank=31),
            _src(ASSET, "2026-09-02", "ktcTradesSfTep", 6000),
            {**_src(ASSET, "2026-09-02", "ktcCrowdSfTep", 6600), "observed_at": None},
        ],
    )
    src = _by_source(movement.value_movement(ASSET, as_of="2026-09-02", path=ledger))
    assert src["ktcCrowdSfTep"]["status"] == movement.SOURCE_DISAPPEARED
    assert src["ktcCrowdSfTep"]["current"]["present"] is False
    assert src["ktcTradesSfTep"]["status"] == movement.SOURCE_MOVED
