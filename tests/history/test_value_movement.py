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
