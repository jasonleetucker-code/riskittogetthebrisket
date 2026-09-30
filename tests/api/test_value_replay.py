"""Pinned value replay (``src/api/value_replay.py``) and two characterized findings.

Invariants only -- no assertion depends on which sources answered the last scrape
(the hard-gate rule in the runbook): the replay must reproduce every published
offense value from its own stamped stages, counterfactuals must be single-change
rebuilds that restore the module afterwards, and the diagnostics must never
report a partial answer as a number.

Also pins two findings from the 2026-09-30 replay (docs/valuation/VALUATION_
ADVANCEMENT_MAP_2026-09-30.md) as CHARACTERIZATION, not endorsement:

* the per-player outlier filter is weight-blind -- weak observations can remove a
  strong one (lead V2-3: mechanism VERIFIED, latent on the measured board);
* the single-source haircut counts families after that filter, so a weight-aware
  replacement is not a drop-in fix (it would turn 4600 into ~1380 in the fixture).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.api import data_contract as dc
from src.api import value_replay as vr
from tests.archive_fixtures import newest_complete_raw_payload


@pytest.fixture(scope="module")
def raw_payload(tmp_path_factory):
    payload, name = newest_complete_raw_payload()
    if payload is None:
        pytest.skip("no complete archived scrape")
    path = tmp_path_factory.mktemp("replay") / f"{name}.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


@pytest.fixture(scope="module")
def baseline(raw_payload):
    return vr.build(json.loads(raw_payload.read_text(encoding="utf-8")))


def test_every_ranked_offense_value_is_reproduced_from_its_own_stamps(baseline):
    checked = 0
    for row in baseline["playersArray"]:
        if row.get("assetClass") == "offense" and row.get("canonicalConsensusRank"):
            check = vr.blend_check(row)
            assert check["status"] in {"reproduced", "no_voters"}, (row["displayName"], check)
            checked += check["status"] == "reproduced"
    assert checked > 0


def test_non_offense_rows_decline_rather_than_report_a_misleading_number(baseline):
    for row in baseline["playersArray"]:
        if row.get("assetClass") in {"idp", "pick"}:
            assert vr.blend_check(row)["status"] == "not_applicable"
            break


def test_identical_builds_show_no_board_difference(raw_payload, baseline):
    again = vr.build(json.loads(raw_payload.read_text(encoding="utf-8")))
    diff = vr.board_diff(baseline, again)
    assert diff["rowsChanged"] == 0 and diff["top200MembershipChanges"] == 0


def test_leaving_a_source_out_removes_only_that_source(raw_payload, baseline):
    keys = {k for r in baseline["playersArray"] for k in (r.get("sourceRankMeta") or {})}
    target = sorted(keys)[0]
    other = vr.build(json.loads(raw_payload.read_text(encoding="utf-8")), {"disable": [target]})
    for row in other["playersArray"]:
        assert target not in (row.get("sourceRankMeta") or {})
    assert vr.board_diff(baseline, other)["rowsChanged"] > 0


def test_diagnostic_patches_are_restored_after_each_build(raw_payload):
    before = (dc._hampel_filter_per_player, dc._VALUE_BASED_SOURCES)
    specs = vr.counterfactual_specs({}, [])
    raw = json.loads(raw_payload.read_text(encoding="utf-8"))
    vr.build(raw, specs["hampel_off"])
    vr.build(raw, specs["native_values_as_ranks"])
    assert (dc._hampel_filter_per_player, dc._VALUE_BASED_SOURCES) == before


def test_hampel_off_counterfactual_leaves_no_outlier_drops(raw_payload):
    raw = json.loads(raw_payload.read_text(encoding="utf-8"))
    other = vr.build(raw, vr.counterfactual_specs({}, [])["hampel_off"])
    assert not any(r.get("droppedSources") for r in other["playersArray"])


def test_pins_hash_every_input_the_build_reads(raw_payload):
    pinned = vr.pins(raw_payload)
    assert len(pinned["payload"]["sha256"]) == 64
    assert pinned["sourceCsvs"] and all(len(h) == 64 for h in pinned["sourceCsvs"].values())
    assert pinned["freshnessState"]
    assert set(pinned["flags"]) >= {"source_freshness_weighting", "source_family_cap"}


def test_family_counterfactuals_exist_only_for_multi_member_families():
    families = {"a": "f1", "b": "f1", "c": "f2"}
    specs = vr.counterfactual_specs(families, ["a", "b", "c"])
    assert specs["leave_out_family:f1"]["disable"] == ["a", "b"]
    assert "leave_out_family:f2" not in specs


# --- Characterization: lead V2-3 (weight-blind outlier filter) --------------------


def test_outlier_filter_ignores_weights_so_weak_evidence_can_remove_strong():
    # Three stale observations at weight 0.03 each and one fresh one at 1.0. The
    # filter sees only values: the fresh 4600 is removed although it carries ~92%
    # of the evidence weight. Mechanism verified; latent on the 2026-09-30 board
    # (no drop removed an observation outweighing the survivors).
    pairs = [("stale_a", 3000.0), ("stale_b", 3100.0), ("stale_c", 3200.0), ("fresh", 4600.0)]
    kept, dropped = dc._hampel_filter_per_player(pairs)
    assert dropped == ["fresh"]
    blended, _ = dc.weighted_count_aware_mean_median_blend(
        [v for _k, v in kept], [0.03, 0.03, 0.03]
    )
    assert round(blended) == 3100


def test_a_naive_weighted_filter_is_not_a_drop_in_fix():
    # Were the three weak observations dropped instead, one family would remain and
    # the single-source haircut (counted after the filter) would keep 30% -- a
    # worse answer than today's. Any correction must address both stages together.
    assert dc._SINGLE_SOURCE_VALUE_RETENTION == pytest.approx(0.30)
    assert round(4600 * dc._SINGLE_SOURCE_VALUE_RETENTION) == 1380


def test_replay_reports_an_absent_asset_as_absent(raw_payload):
    result = vr.replay(raw_payload, ["No Such Player Xyz"], counterfactuals=[])
    assert result["assets"]["No Such Player Xyz"]["baseline"] is None
    assert Path(result["pins"]["payload"]["path"]).name.endswith(".json")
