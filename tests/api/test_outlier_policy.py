"""outlier-corroborated-v1 (preregistered challenger; default OFF).

docs/valuation/evidence/outlier-disagreement-2026-10-19/PREREGISTRATION.md.

Unit level: the policy keeps valid disagreement (the owner's example: three sites
near 5,000 and Draft Sharks at 3,000 keeps Draft Sharks), and rejects only a
gross, uncorroborated vote or a mis-scaled board, under the preregistered guards.
Pipeline level (newest complete archived scrape, no network): the flag ships OFF
and OFF never calls the policy; ON changes only the drop decision and leaves
every vote alone.
"""

from __future__ import annotations

import json
import math

import pytest

from src.api import data_contract as dc
from src.api import feature_flags
from src.api import outlier_policy as op

FLAG = "outlier_disagreement_policy"
OFFENSE = op.scope_curve("offense")
IDP = op.scope_curve("idp")


def fam(key: str) -> str:
    """Test families: the prefix before ``_`` (``dlf_a`` and ``dlf_b`` share one)."""
    return key.split("_")[0]


def assess(pairs, **kw):
    kw.setdefault("curve", OFFENSE)
    kw.setdefault("family_of", fam)
    return op.assess_row(pairs, **kw)


def test_flag_ships_off_and_constants_are_the_preregistered_ones():
    assert feature_flags._DEFAULTS[FLAG] is False
    assert op.constants() == {
        "version": "outlier-corroborated-v1",
        "rankOffset": 10.0,
        "referenceN": 500.0,
        "grossRankFactor": 4.0,
        "corroborationFactor": 2.0,
        "valueFloor": 1000.0,
        "minOtherFamilies": 2,
        "dominantShare": 0.5,
        "boardMinRows": 20,
        "boardShiftFactor": 1.5,
        "boardSpreadFactor": 2.0,
    }
    # The value floor is the incumbent's constant, not a new number.
    assert op.VALUE_FLOOR == dc._HAMPEL_MIN_THRESHOLD


def test_hill_inverse_is_the_pipelines():
    for v in (9999.0, 9000.0, 5000.0, 1234.5, 3.0):
        for c, s in (OFFENSE, IDP):
            assert op.hill_inverse(v, c, s) == dc._hill_inverse(v, c, s)


def test_owner_example_three_sites_near_5000_keep_draft_sharks_at_3000():
    pairs = [("ktc_a", 5050.0), ("dlf_a", 4980.0), ("fp_a", 5000.0), ("ds_a", 3000.0)]
    v = assess(pairs)
    assert v.dropped == ()
    # The incumbent drops it: three near-identical votes collapse the MAD and
    # the threshold degenerates to the 1,000-point floor.
    assert dc._hampel_filter_per_player(pairs)[1] == ["ds_a"]


def test_measured_idp_disagreements_are_kept():
    # Aidan Hutchinson and Myles Garrett, 2026-10-19 board, DLF IDP voting.
    hutch = [("idptc_a", 6444.0), ("dlf_a", 6227.0), ("fp_a", 6227.0), ("ds_a", 3181.0)]
    garrett = [("idptc_a", 5000.0), ("dlf_a", 5100.0), ("fp_a", 4900.0), ("ds_a", 1905.0)]
    for pairs in (hutch, garrett):
        assert assess(pairs, curve=IDP).dropped == ()
        assert dc._hampel_filter_per_player(pairs)[1] == ["ds_a"]


def test_gross_uncorroborated_vote_is_dropped_with_its_reason():
    pairs = [("ktc_a", 5050.0), ("dlf_a", 4980.0), ("fp_a", 5000.0), ("ds_a", 250.0)]
    v = assess(pairs)
    assert v.dropped == ("ds_a",)
    assert v.kept == ("ktc_a", "dlf_a", "fp_a")
    assert v.reasons == {"ds_a": op.REASON_GROSS}
    d = v.details["ds_a"]
    assert d["distance"] > math.log(4) and d["nearestFamily"] > math.log(2)


def _row_with(level: float, bad: float):
    return [("a_x", level), ("b_x", level * 1.03), ("c_x", level * 0.97), ("d_x", bad)]


def test_vote_times_twenty_and_twentieth_are_caught_at_every_depth():
    for level in (300.0, 1200.0, 3000.0, 6000.0, 8500.0):
        for factor in (20.0, 0.05):
            bad = min(9999.0, max(1.0, level * factor))
            if abs(bad - level) <= op.VALUE_FLOOR:
                continue  # harmless by construction: inside the value floor
            if factor > 1 and level > 6000.0:
                continue  # the documented top-of-board blind spot (below)
            assert assess(_row_with(level, bad)).dropped == ("d_x",), (level, factor)


def test_documented_blind_spot_capped_upward_corruption_at_the_top():
    # PREREGISTRATION §7: rank ~11 pushed to the 9,999 cap is under 4x in the
    # smoothed coordinate, so it is kept; the cap bounds the harm.
    assert assess(_row_with(8500.0, 9999.0)).dropped == ()


def test_another_family_corroborates_an_outlying_view():
    pairs = [
        ("ktc_a", 5000.0),
        ("dlf_a", 5100.0),
        ("fp_a", 4950.0),
        ("ds_a", 900.0),
        ("yb_a", 1000.0),
    ]
    assert assess(pairs).dropped == ()


def test_one_providers_two_boards_cannot_corroborate_each_other():
    pairs = [
        ("ktc_a", 5000.0),
        ("idptc_a", 5100.0),
        ("fp_a", 4950.0),
        ("dlf_idp", 300.0),
        ("dlf_rookie", 310.0),
    ]
    v = assess(pairs)
    assert set(v.dropped) == {"dlf_idp", "dlf_rookie"}


def test_dominant_evidence_is_never_dropped():
    pairs = [("a_x", 3000.0), ("b_x", 3100.0), ("c_x", 3200.0), ("d_x", 9900.0)]
    weights = {"a_x": 0.05, "b_x": 0.05, "c_x": 0.05, "d_x": 1.0}
    v = assess(pairs, weights=weights)
    assert v.dropped == ()
    assert v.reasons == {"d_x": op.KEPT_DOMINANT}
    assert assess(pairs).dropped == ("d_x",)


def test_value_floor_and_top_of_board_offset_keep_small_value_gaps():
    # Deep tail: a 4x+ rank gap that is under 1,000 points of value.
    deep = [("a_x", 900.0), ("b_x", 880.0), ("c_x", 910.0), ("d_x", 120.0)]
    assert assess(deep).dropped == ()
    # Top of the board: rank ~0 vs rank ~16 is not a gross disagreement.
    top = [("a_x", 9999.0), ("b_x", 9990.0), ("c_x", 9995.0), ("d_x", 8000.0)]
    assert assess(top).dropped == ()


def test_reference_needs_two_other_families():
    pairs = [("a_x", 5000.0), ("a_y", 5010.0), ("b_x", 200.0)]
    assert assess(pairs).dropped == ()


def test_missing_values_are_never_assessed_or_dropped():
    pairs = [("a_x", 5000.0), ("b_x", 5100.0), ("c_x", 4900.0), ("d_x", 0.0), ("e_x", -3.0)]
    v = assess(pairs)
    assert v.dropped == ()
    assert "d_x" not in v.details and "e_x" not in v.details


def test_survivor_and_family_guards():
    pairs = [("a_x", 5000.0), ("b_x", 5100.0), ("c_x", 4900.0)]
    v = assess(pairs, board_excluded=("a_x", "b_x"))
    assert v.dropped == ()
    assert v.reasons == {"a_x": op.KEPT_SURVIVORS, "b_x": op.KEPT_SURVIVORS}
    # Two families: excluding one would leave a single family.
    two = [("a_x", 5000.0), ("a_y", 5100.0), ("b_x", 4900.0)]
    assert assess(two, board_excluded=("b_x",)).dropped == ()


def test_board_excluded_votes_are_dropped_and_are_no_reference():
    pairs = [("a_x", 5000.0), ("b_x", 5100.0), ("c_x", 4900.0), ("d_x", 400.0), ("e_x", 450.0)]
    # d and e corroborate each other until e's board is flagged.
    assert assess(pairs).dropped == ()
    v = assess(pairs, board_excluded=("e_x",))
    assert set(v.dropped) == {"d_x", "e_x"}
    assert v.reasons == {"d_x": op.REASON_GROSS, "e_x": op.REASON_BOARD}


def test_order_invariance():
    pairs = [("ktc_a", 5050.0), ("dlf_a", 4980.0), ("fp_a", 5000.0), ("ds_a", 250.0)]
    a = assess(pairs)
    b = assess(list(reversed(pairs)))
    assert set(a.dropped) == set(b.dropped) and a.reasons == b.reasons


def _board(scale_source: str | None = None, factor: float = 1.0, reverse: bool = False):
    rows = []
    sources = ["a_x", "b_x", "c_x", "d_x"]
    levels = [9000.0 - 150.0 * i for i in range(40)]
    for i, level in enumerate(levels):
        votes = {s: level * (1.0 + 0.02 * ((i + j) % 3 - 1)) for j, s in enumerate(sources)}
        rows.append(votes)
    if scale_source is not None:
        c, s = OFFENSE
        col = [r[scale_source] for r in rows]
        if reverse:
            col = list(reversed(col))
        for r, v in zip(rows, col):
            p = op.hill_inverse(v, c, s) * factor
            r[scale_source] = 9999.0 / (1.0 + (p / c) ** s)
    return [op.BoardRow("offense", OFFENSE, r) for r in rows]


def test_board_screen_flags_scaled_and_reversed_boards_only():
    healthy = op.board_screen(_board(), fam)
    assert healthy["flagged"] == {}
    assert all(not s["flagged"] for s in healthy["stats"].values())
    for factor, reverse in ((2.0, False), (5.0, False), (0.2, False), (1.0, True)):
        screen = op.board_screen(_board("d_x", factor, reverse), fam)
        assert screen["flagged"] == {"offense": ["d_x"]}, (factor, reverse)


def test_board_screen_needs_enough_rows():
    rows = _board("d_x", 5.0)[: op.BOARD_MIN_ROWS - 1]
    screen = op.board_screen(rows, fam)
    assert screen["flagged"] == {}
    assert screen["stats"]["d_x|offense"]["screened"] is False


def test_replay_matches_assess_row_unweighted():
    pairs = [("ktc_a", 5050.0), ("dlf_a", 4980.0), ("fp_a", 5000.0), ("ds_a", 250.0)]
    replay = op.replay_dropped(curve=OFFENSE, family_of=fam)
    assert replay(pairs) == list(assess(pairs).dropped)


def test_lost_evidence_seats_use_the_replay_when_given():
    voting = [("a_x", 5000.0), ("b_x", 5100.0), ("c_x", 4900.0)]
    withheld = [("d_x", 300.0)]
    replay = op.replay_dropped(curve=OFFENSE, family_of=fam)
    # The policy would have rejected the withheld gross vote: not a lost seat.
    assert (
        dc._lost_evidence_seats(
            voting_pairs=voting,
            withheld_pairs=withheld,
            dropped_now=[],
            outlier_test_applies=True,
            replay=replay,
        )
        == []
    )
    # Default (no replay) is the incumbent's replay, unchanged.
    assert dc._lost_evidence_seats(
        voting_pairs=voting, withheld_pairs=withheld, dropped_now=[], outlier_test_applies=True
    ) == dc._lost_evidence_seats(
        voting_pairs=voting,
        withheld_pairs=withheld,
        dropped_now=[],
        outlier_test_applies=True,
        replay=None,
    )


def test_policy_yields_to_every_other_filter_challenger(monkeypatch):
    enabled = {FLAG: True, "source_family_cap": True}
    monkeypatch.setattr(feature_flags, "is_enabled", lambda name: enabled.get(name, False))
    assert dc._outlier_policy_active() is True
    for other in (
        "joint_outlier_sparse_challenger",
        "rank_space_hampel_challenger",
        "rank_space_hampel_per_vote_challenger",
        "idp_hampel_n3_challenger",
    ):
        enabled[other] = True
        assert dc._outlier_policy_active() is False, other
        del enabled[other]
    enabled[FLAG] = False
    assert dc._outlier_policy_active() is False


# ── full pipeline (archived scrape, no network) ─────────────────────────


@pytest.fixture(scope="module")
def boards():
    from src.api import value_replay as vr
    from tests.archive_fixtures import newest_complete_raw_payload

    payload, _name = newest_complete_raw_payload()
    if payload is None:
        pytest.skip("no complete archived scrape")
    pins = [("dlf_offense_only_vote", False)]
    off = vr.build(json.loads(json.dumps(payload)), {"flags": pins})
    on = vr.build(json.loads(json.dumps(payload)), {"flags": pins + [(FLAG, True)]})
    return payload, off, on


def _votes(row: dict) -> dict:
    return {
        k: m.get("valueContribution")
        for k, m in (row.get("sourceRankMeta") or {}).items()
        if isinstance(m, dict) and not m.get("excludedReason")
    }


def test_off_never_calls_the_policy(monkeypatch):
    from src.api import value_replay as vr
    from tests.archive_fixtures import newest_complete_raw_payload

    payload, _name = newest_complete_raw_payload()
    if payload is None:
        pytest.skip("no complete archived scrape")

    def boom(*_a, **_k):
        raise AssertionError("policy called with the flag off")

    monkeypatch.setattr(op, "assess_row", boom)
    monkeypatch.setattr(op, "rank_with_board_screen", boom)
    contract = vr.build(json.loads(json.dumps(payload)), {"flag": (FLAG, False)})
    assert "outlierPolicy" not in contract
    assert not any(r.get("outlierPolicyReasons") for r in contract["playersArray"])


def test_on_changes_only_the_drop_decision(boards):
    _payload, off, on = boards
    assert on["outlierPolicy"]["version"] == op.POLICY_VERSION
    assert on["outlierPolicy"]["rankingPasses"] in (1, 2)
    off_rows = {r["displayName"]: r for r in off["playersArray"]}
    on_rows = {r["displayName"]: r for r in on["playersArray"]}
    assert off_rows.keys() == on_rows.keys()
    off_drops = on_drops = 0
    for name, row in on_rows.items():
        other = off_rows[name]
        # Votes are computed before the filter: identical in both builds.
        assert _votes(row) == _votes(other), name
        if row.get("assetClass") == "pick":
            assert not row.get("droppedSources")
        for k, reason in (row.get("outlierPolicyReasons") or {}).items():
            assert reason in (
                op.REASON_GROSS,
                op.REASON_BOARD,
                op.KEPT_DOMINANT,
                op.KEPT_SURVIVORS,
            )
            if reason in (op.REASON_GROSS, op.REASON_BOARD):
                assert k in row["droppedSources"]
        off_drops += len(other.get("droppedSources") or [])
        on_drops += len(row.get("droppedSources") or [])
    # The policy keeps the valid disagreement the incumbent removes.
    assert on_drops < off_drops
