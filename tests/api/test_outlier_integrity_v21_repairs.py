"""Outlier integrity V2.1: the registered repairs (Stage 1, synthetic only).

Preregistration ``docs/sources/OUTLIER_INTEGRITY_V21_PREREGISTRATION.md``
(committed at ``180d2463d2`` before any V2.1 code).  Stage 1 tests read
SYNTHETIC rows and synthetic payloads only: no DEV, R, SPENT or held-out board
is read here.  Each test names the repair (§3.2) or persistence rule (§3.4) and
the §9 correctness property it pins.

Every repair sits behind ``outlier_integrity_v21`` (default OFF, effective only
under the ``outlier_integrity_v2`` master).  With it OFF every V2 rule is
unchanged; the V2 suites (``test_source_integrity.py``,
``test_outlier_integrity_v2_layer_c.py``) still pass as they were.
"""

from __future__ import annotations

import itertools
import json
import math
import random
from pathlib import Path

import pytest

from src.api import feature_flags
from src.api import outlier_policy as op
from src.api import source_integrity as si
from src.identity import resolution as r
from src.sources import voting_status as vs
from tests.api.test_source_integrity import (
    ALL_ON,
    META,
    _build,
    _csvs,
    _flags,
    _rows,
    _values,
)

V21_ON = (*ALL_ON, "outlier_integrity_v21")
REPO = Path(__file__).resolve().parents[2]


# ── flags and the repair set ───────────────────────────────────────────


def test_v21_flag_ships_off_is_live_and_needs_the_master():
    assert feature_flags._DEFAULTS["outlier_integrity_v21"] is False
    assert feature_flags.gate_status("outlier_integrity_v21") == feature_flags.LIVE
    with _flags("outlier_integrity_v21"):
        assert not si.v21_active()  # master off: nothing
    with _flags(*ALL_ON):
        assert not si.v21_active()
        assert si.repairs_for_build() == si.Repairs()
    with _flags(*V21_ON):
        assert si.v21_active()
        assert si.repairs_for_build() == si.Repairs.all_on()


def test_repairs_override_reverts_one_repair_for_the_sensitivity():
    with _flags(*V21_ON), si.repairs_override(si.Repairs.all_on().without("R6")):
        got = si.repairs_for_build()
    assert not got.on("R6") and got.on("R1") and got.on("P")
    assert si.Repairs.all_on().to_stamp() == list(si.REPAIR_IDS)


def test_v21_thresholds_fix_tau_age_at_one_year():
    t = si.load_v21_thresholds()
    assert t.tau_age == r.V21_TAU_AGE == 1.0
    if not si.V21_THRESHOLDS_PATH.exists():
        assert t.status == "v2_frozen_provisional_for_v21"


# ── R7: one per-observation vocabulary, owned by voting_status ─────────


def test_reason_table_is_voting_status_owned_never_a_fork():
    assert si.REASON_CATEGORY is vs.OBSERVATION_REASON_CATEGORY
    for code in vs.OBSERVATION_REASON_CATEGORY:
        assert si.reason_category(code) == vs.observation_reason_category(code)


def test_every_v21_reason_maps_and_no_voting_reason_reads_invalid():
    voting = [
        si.REASON_TEAM_UNCONFIRMED,
        si.REASON_FORMAT_MINOR,
        si.REASON_SEGMENT_TOO_SMALL,
        si.REASON_RELEASED_BY_CAP,
        si.REASON_PERSISTENT_GROSS_DISSENT,
        si.REASON_NAME_ONLY,
        si.REASON_KEPT_DISSENT,
        si.REASON_VOTING,
    ]
    for code in voting:
        cat = si.reason_category(code)
        assert cat in (si.CATEGORY_VOTING, si.CATEGORY_DISSENT), code
        assert cat not in vs.INVALID_OBSERVATION_CATEGORIES
    assert si.reason_category(r.ID_REASON_POSITION_FAMILY) == si.CATEGORY_IDENTITY
    assert set(vs.OBSERVATION_CATEGORIES) == set(vs.OBSERVATION_REASON_CATEGORY.values()) | {
        vs.OBS_CATEGORY_MISSING
    }


def test_frontend_label_map_carries_every_v21_code():
    js = (REPO / "frontend" / "lib" / "source-voting-status.js").read_text()
    for code, cat in vs.OBSERVATION_REASON_CATEGORY.items():
        assert f'{code}: "{cat}"' in js, code


# ── R1: B0 tolerance (§9 property 21) ──────────────────────────────────


def _board(n=400, *, top=9999.0, step=None):
    step = step or (top - 100.0) / n
    return [(i + 1, round(top - i * step), f"p{i:04d}") for i in range(n)]


def test_r1_a_one_point_rounding_inversion_never_quarantines():
    board = _board()
    # Brock Wright: rank 352 at 1318 against rank 351 at 1317.
    board[350] = (351, 1317, "a")
    board[351] = (352, 1318, "b")
    tol = si.rank_value_tolerance(board)
    assert tol.discordant_pairs == 0 and not tol.whole_source
    v2 = si.format_findings("ktcCrowdSfTep", _census(board))
    v21 = si.format_findings("ktcCrowdSfTep", _census(board), tolerant=True)
    assert [f.hard for f in v2] == [True]  # V2's registered rule, unchanged
    assert v21 == []


def _census(board):
    return {
        "rows": len(board),
        "nonNumericValueRows": 0,
        "rankValuePairs": [(rk, v) for rk, v, _k in board],
        "rankValueKeys": [k for _rk, _v, k in board],
    }


def test_r1_ties_are_never_discordant():
    # A shared rank carrying two values (the KTC Crowd duplicated-rank case)
    # and equal values at different ranks are never discordant.
    board = [(1, 9500, "a"), (2, 9000, "b"), (2, 8900, "c"), (3, 8000, "d"), (4, 8000, "e")]
    assert si.rank_value_tolerance(board).discordant_pairs == 0


def test_r1_a_minor_discordance_is_an_advisory_that_still_votes():
    board = _board()
    board[100] = (101, board[99][1] + 500, "lifted")  # one real inversion
    (finding,) = si.format_findings("x", _census(board), tolerant=True)
    assert finding.reason == si.REASON_FORMAT_MINOR and not finding.hard
    assert finding.evidence["discordantKeys"] == ["lifted"]
    assert si.reason_category(finding.reason) == si.CATEGORY_VOTING


def test_r1_whole_source_needs_five_percent_and_ten_pairs():
    board = _board(400)
    for i in range(1, 400, 40):  # 10 inversions = 2.5% of 399 pairs: advisory
        board[i] = (board[i][0], board[i - 1][1] + 300, board[i][2])
    assert not si.rank_value_tolerance(board).whole_source
    board = _board(100)
    for i in range(1, 100, 8):  # 13 inversions >= 5% and >= 10: whole source
        board[i] = (board[i][0], board[i - 1][1] + 300, board[i][2])
    tol = si.rank_value_tolerance(board)
    assert tol.discordant_pairs >= 10 and tol.whole_source


def test_r1_property_jittered_healthy_boards_never_and_reversed_boards_always_fire():
    rng = random.Random(20261021)
    for _ in range(200):
        n = rng.randint(20, 600)
        top = rng.uniform(3000, 9999)
        board = [
            (i + 1, round(top * (1 - i / (n + 5))) + rng.choice((-1, 0, 1)), None) for i in range(n)
        ]
        assert not si.rank_value_tolerance(board).whole_source
        rev = [(rk, v, k) for (rk, _v0, k), (_r, v, _k) in zip(board, reversed(board))]
        assert si.rank_value_tolerance(rev).whole_source


def test_r1_rank_rescaling_keeps_order_so_b0_cannot_catch_it():
    board = _board()
    for factor in (2, 5):
        assert not si.rank_value_tolerance([(rk * factor, v, k) for rk, v, k in board]).whole_source
    assert not si.rank_value_tolerance([(rk, v * 0.01, k) for rk, v, k in board]).whole_source


# ── R2 / R3: small segments abstain (§9 property 22) ───────────────────


def _thr(**kw):
    base = {"n_min": 20, "rho_min": 0.0, "tau_gross": math.log(4.0)}
    base.update(kw)
    return si.IntegrityThresholds(**base)


def test_r2_b3a_abstains_below_twenty_rows_with_an_advisory():
    kw = dict(source="idpTradeCalc", asset_class="offense", median=-0.375, baseline=0.0)
    assert si.class_rule(rows=2, tau_board=0.015, **kw)[0] is not None  # V2: fires on 2 rows
    hard, adv, ab = si.class_rule(rows=2, tau_board=0.015, v21=True, **kw)
    assert hard is None and adv == si.REASON_SEGMENT_TOO_SMALL and ab == "segment_too_small"
    hard, _adv, _ab = si.class_rule(rows=20, tau_board=0.015, v21=True, **kw)
    assert hard == si.scale_error_reason("idpTradeCalc", "offense")


def test_r3_n_min_guards_every_b3b_test_including_proof_escalation():
    kw = dict(source="s", asset_class="idp", pos="DB", rho=0.9, thresholds=_thr())
    gross = dict(median=2.0, baseline=0.0)
    shift = dict(median=0.3, baseline=0.0)
    assert si.segment_rule(rows=5, proof=(), **gross, **kw)[0] is not None  # V2
    assert si.segment_rule(rows=5, proof={"s"}, **shift, **kw)[0] is not None  # V2
    for m in (gross, shift):
        hard, adv, ab = si.segment_rule(rows=5, proof={"s"}, v21=True, **m, **kw)
        assert (hard, adv, ab) == (None, None, "below_n_min")
    assert si.segment_rule(rows=20, proof=(), v21=True, **gross, **kw)[0] is not None
    assert si.segment_rule(rows=20, proof={"s"}, v21=True, **shift, **kw)[0] is not None


def test_r2_r3_property_small_segments_never_quarantine_whatever_the_shift():
    rng = random.Random(7)
    for _ in range(500):
        rows = rng.randint(0, 19)
        m, base = rng.uniform(-5, 5), rng.uniform(-5, 5)
        rho = rng.choice([None, rng.uniform(-1, 1)])
        assert (
            si.segment_rule(
                source="s",
                asset_class="offense",
                pos="TE",
                rows=rows,
                rho=rho,
                median=m,
                baseline=base,
                thresholds=_thr(),
                proof={"s"},
                v21=True,
            )[0]
            is None
        )
        assert (
            si.class_rule(
                source="s",
                asset_class="idp",
                rows=rows,
                median=m,
                baseline=base,
                tau_board=0.001,
                v21=True,
            )[0]
            is None
        )


def _seg_rows(n, *, shift=0.0, pos="TE"):
    out = {}
    for i in range(n):
        base = math.log(10 + 500 * (0.05 + 0.9 * i / max(1, n)))
        out[i] = (
            "offense",
            pos,
            {"a": base + shift, "b": base, "c": base + 0.01, "d": base - 0.01},
        )
    return out


def test_r3_segment_screen_v21_abstains_on_a_small_shifted_segment_with_proof():
    hist = si.IntegrityHistory(boards=3, segments={"a|offense|TE": (0.0, 0.0, 0.0)})
    kw = dict(provider_of=lambda k: k, thresholds=_thr(), history=hist, proof_sources={"a"})
    v2 = si.segment_screen(_seg_rows(6, shift=2.0), **kw)
    v21 = si.segment_screen(_seg_rows(6, shift=2.0), v21=True, **kw)
    assert ("a", "offense", "TE") in v2.quarantines
    assert not v21.quarantines
    assert v21.stats["a|offense|TE"]["abstained"] == "below_n_min"
    big = si.segment_screen(_seg_rows(30, shift=2.0), v21=True, **kw)
    assert ("a", "offense", "TE") in big.quarantines


def test_r3_selector_evaluates_the_served_rule_through_the_same_code_path():
    from src.robust_filter_shadow import oiv2_select as sel

    hist = si.IntegrityHistory(boards=3, segments={"a|offense|TE": (0.0, 0.0, 0.0)})
    for n, shift in ((6, 2.0), (30, 2.0), (30, 0.3), (6, 0.3)):
        screen = si.segment_screen(
            _seg_rows(n, shift=shift),
            provider_of=lambda k: k,
            thresholds=_thr(),
            history=hist,
            proof_sources={"a"},
            v21=True,
        )
        window = {k: list(v) for k, v in hist.segments.items()}
        got = sel._hard_findings(
            screen.stats,
            window,
            n_min=20,
            rho_min=0.0,
            tau_gross=math.log(4.0),
            tau_board={},
            proof={"a"},
            v21=True,
        )
        assert set(got) == {"|".join(x for x in k if x) for k in screen.quarantines}, (n, shift)


def test_r3_selector_reads_the_builds_served_proof_set():
    from src.robust_filter_shadow import oiv2_select as sel

    rec = {"builds": {"v2": {"sourceIntegrity": {"proofSources": ["dlfRookieSf", "ktc"]}}}}
    assert sel._proof_sources(rec, v21=True) == {"dlfRookieSf", "ktc"}
    with pytest.raises(ValueError):
        sel._proof_sources({"builds": {"v2": {"sourceIntegrity": {}}}}, v21=True)


# ── R14: B2 sign share over rows that moved ────────────────────────────


def _inj_pairs(shift_share=0.7, n=40, seed=3):
    rng = random.Random(seed)
    out = []
    i = 0
    for g, m in (("QB", 0.2), ("RB", -0.25), ("WR", 0.15)):
        for _ in range(n):
            csv = rng.uniform(800, 8000)
            d = m if rng.random() < shift_share else 0.0
            out.append(si.ProvenancePair(i, g, csv * math.exp(d), csv))
            i += 1
    return out


def test_r14_a_seventy_percent_shift_is_a_board_proof_only_under_the_v21_reading():
    pairs = _inj_pairs()
    assert not si.provenance_check(pairs, epsilon=0.01).board_proof  # V2 S16
    assert si.provenance_check(pairs, epsilon=0.01, nonzero_sign_share=True).board_proof


def test_r14_a_healthy_capture_never_proves():
    pairs = _inj_pairs(shift_share=0.0)
    res = si.provenance_check(pairs, epsilon=0.01, nonzero_sign_share=True)
    assert not res.board_proof and not res.row_proofs


# ── R4: position families (§9 property 23) ─────────────────────────────


def test_r4_every_family_pair_behaves_as_registered_both_ways():
    offense = ("QB", "RB", "WR", "TE", "K")
    for a, b in itertools.permutations(offense, 2):
        assert r.v21_families_compatible(a, [b]) is False, (a, b)
        assert r.v21_families_compatible(b, [a]) is False, (b, a)
    allowed = {("DL", "LB"), ("LB", "DB"), ("RB", "FB")}
    for a, b in allowed:
        assert r.v21_families_compatible(a, [b]) is True
        assert r.v21_families_compatible(b, [a]) is True
    assert r.v21_families_compatible("DL", ["DB"]) is False
    assert r.v21_families_compatible("CB", ["DE"]) is False
    assert r.v21_families_compatible("EDGE", ["DT"]) is True
    assert r.v21_families_compatible("EDGE", ["OLB"]) is True
    assert r.v21_families_compatible("PK", ["K"]) is True
    assert r.v21_families_compatible("WR", ["DB"]) is False
    # fantasy_positions and the two-way alt widen the row's families
    assert r.v21_families_compatible("RB", ["WR"]) is False
    assert r.v21_families_compatible("RB", ["WR", "RB"]) is True
    assert r.v21_families_compatible("CB", ["WR"], ["DB"]) is True
    # no published or no row family: no evidence
    assert r.v21_families_compatible("", ["WR"]) is None
    assert r.v21_families_compatible("OL", ["WR"]) is None


def _row(**kw):
    base = dict(player_id="1", name="Jo Smith", position="WR", team="BUF", age=25)
    base.update(kw)
    return r.RowIdentityEvidence(**base)


def _assess(row, entry, **kw):
    return r.assess_identity_evidence(
        row=row,
        candidates=[entry],
        chosen=0,
        via="name_group",
        canonical_match_key=lambda s: s.lower(),
        position_group=lambda p: "OFFENSE" if p in ("QB", "RB", "WR", "TE") else "IDP",
        **kw,
    )


def test_r4_a_qb_entry_on_a_wr_row_is_contradicted_only_under_v21():
    e = r.SourceEntryEvidence(raw_name="Jo Smith", position="QB", team="BUF")
    v2 = _assess(_row(), e)
    assert v2.verdict == r.ID_VERIFIED  # V2: one OFFENSE group, teams agree
    v21 = _assess(_row(), e, v21=True)
    assert (v21.verdict, v21.reason) == (r.ID_CONTRADICTED, r.ID_REASON_POSITION_FAMILY)


# ── R5: age intervals ──────────────────────────────────────────────────


def test_r5_decimal_vendor_age_against_integer_row_age_within_a_year_votes():
    # Pete Werner 28.3 vs 27, Tuten 24.6 vs 23, Koziol 23.7 vs 22, Bigsby
    # 25.1 vs 24, Beck 24.8 vs 23 — the same players V2 refused.
    for vendor, row_age in ((28.3, 27), (24.6, 23), (23.7, 22), (25.1, 24), (24.8, 23)):
        e = r.SourceEntryEvidence(raw_name="Jo Smith", position="WR", team="BUF", age=vendor)
        assert _assess(_row(age=row_age), e, tau_age=1.0).reason == r.ID_REASON_AGE
        assert _assess(_row(age=row_age), e, v21=True).verdict == r.ID_VERIFIED


def test_r5_a_real_age_gap_above_one_year_is_still_refused():
    e = r.SourceEntryEvidence(raw_name="Jo Smith", position="WR", team="BUF", age=28.7)
    assert _assess(_row(age=24), e, v21=True).reason == r.ID_REASON_AGE
    assert r.v21_age_gap(26, 24, None) == pytest.approx(1.0)  # [26,27) vs [24,25)
    e2 = r.SourceEntryEvidence(raw_name="Jo Smith", position="WR", team="BUF", age=26)
    assert _assess(_row(age=24), e2, v21=True).verdict == r.ID_VERIFIED  # gap 1.0, not > 1


def test_r5_birth_date_gives_the_exact_age_at_publication():
    from datetime import date

    asof = date(2026, 10, 20)
    exact = r.v21_exact_age("1998-01-01", asof)
    assert exact == pytest.approx(28.80, abs=0.01)
    # A stale integer row age (27) alone would refuse a vendor 29.2 (gap 1.2);
    # the exact age at publication (28.8) shows the same player.
    e = r.SourceEntryEvidence(raw_name="Jo Smith", position="WR", team="BUF", age=29.2)
    assert _assess(_row(age=27), e, v21=True, age_as_of=asof).reason == r.ID_REASON_AGE
    row = _row(age=27, birth_date="1998-01-01")
    assert _assess(row, e, v21=True, age_as_of=asof).verdict == r.ID_VERIFIED
    far = r.SourceEntryEvidence(raw_name="Jo Smith", position="WR", team="BUF", age=30.5)
    assert _assess(row, far, v21=True, age_as_of=asof).reason == r.ID_REASON_AGE


def test_r5_cold_start_property_integer_vs_decimal_within_a_year_never_refuses():
    rng = random.Random(11)
    for _ in range(500):
        a = rng.randint(20, 38)
        vendor = round(a + rng.uniform(0.0, 1.999), 1)
        e = r.SourceEntryEvidence(raw_name="Jo Smith", position="WR", team="BUF", age=vendor)
        assert _assess(_row(age=a), e, v21=True).reason != r.ID_REASON_AGE


# ── R8 / R10: team at cold start (§9 property 20) ──────────────────────


def test_r8_team_only_mismatch_without_history_votes_stamped():
    e = r.SourceEntryEvidence(raw_name="Jo Smith", position="WR", team="MIA")
    assert _assess(_row(), e).reason == r.ID_REASON_TEAM_ONLY_MISMATCH  # V2 holds it
    got = _assess(_row(), e, v21=True)
    assert (got.verdict, got.reason) == (r.ID_TEAM_UNCONFIRMED, r.ID_REASON_TEAM_UNCONFIRMED)
    assert not got.refused


def test_r8_continuity_and_previous_team_vote_as_team_lag():
    e = r.SourceEntryEvidence(raw_name="Jo Smith", position="WR", team="MIA")
    lag = _assess(_row(), e, v21=True, prior_source_team="MIA")
    assert lag.verdict == r.ID_VERIFIED and "team_lag" in lag.evidence
    prev = _assess(_row(), e, v21=True, row_previous_teams=("MIA",))
    assert prev.verdict == r.ID_VERIFIED


def test_r8_a_vendor_that_moved_away_from_the_current_team_is_unresolved():
    e = r.SourceEntryEvidence(raw_name="Jo Smith", position="WR", team="MIA")
    got = _assess(_row(), e, v21=True, prior_source_team="BUF", row_previous_teams=("NE",))
    assert (got.verdict, got.reason) == (r.ID_UNRESOLVED, r.ID_REASON_TEAM_ONLY_MISMATCH)


def test_r10_team_continuity_reads_the_a4_chosen_entry():
    # Two entries of one source on the key; A4 picks the WR (family match),
    # not the join's choice (index 0, the LB).  The vendor's own history
    # carries the WR entry's team: continuity, so it votes.
    cands = [
        r.SourceEntryEvidence(raw_name="Jo Smith", position="LB", team="BUF", value=9000),
        r.SourceEntryEvidence(raw_name="Jo Smith", position="WR", team="MIA", value=5000),
    ]
    got = r.assess_identity_evidence(
        row=_row(),
        candidates=cands,
        chosen=0,
        via="name_group",
        canonical_match_key=lambda s: s.lower(),
        position_group=lambda p: "OFFENSE" if p in ("QB", "RB", "WR", "TE") else "IDP",
        v21=True,
        prior_source_team="MIA",
    )
    assert got.selected == 1 and got.verdict == r.ID_VERIFIED


# ── P-1..P-4: persistence and B4 release (§9 property 18) ──────────────


def _rec(as_of, obs, hashes, rules=si.PERSISTENCE_RULES_V21):
    out = {
        "schema": "oiv2-board-record/v1",
        "asOf": as_of,
        "hashes": hashes,
        "observations": obs,
        "segmentMedians": {},
        "quarantinedScopes": [],
    }
    if rules:
        out["persistenceRules"] = rules
    return out


def test_p1_rereading_one_dataset_adds_one_observation_not_many():
    h = None
    for i in range(6):  # six rebuilds of ONE vendor dataset
        h = si.advance(
            h,
            _rec(
                f"2026-10-21T0{i}:00:00+00:00",
                {"src|player:1": {"u": 5.0, "status": "voting", "team": None}},
                {"src": "SAME"},
            ),
        )
    assert h.observations["src|player:1"] == (5.0,)
    assert not si.persistence_confirmed(h, si.IntegrityThresholds(), "src", "player:1", 5.0)
    # V2 semantics (no rules stamp) counted every re-read
    h2 = None
    for i in range(3):
        h2 = si.advance(
            h2,
            _rec(
                f"2026-10-21T0{i}:00:00+00:00",
                {"src|player:1": {"u": 5.0, "status": "voting", "team": None}},
                {"src": "SAME"},
                rules=None,
            ),
        )
    assert len(h2.observations["src|player:1"]) == 3


def test_p1_content_distinct_datasets_do_accumulate():
    h = None
    for i in range(3):
        h = si.advance(
            h,
            _rec(
                f"2026-10-2{i + 1}T00:00:00+00:00",
                {"src|player:1": {"u": 5.0, "status": si.STATUS_REJECTED_TAIL, "team": None}},
                {"src": f"H{i}"},
            ),
        )
    assert h.observations["src|player:1"] == (5.0, 5.0, 5.0)  # P-4: C drops accrue
    assert si.persistence_confirmed(h, si.IntegrityThresholds(), "src", "player:1", 5.0)


def test_p2_refused_held_withheld_and_quarantined_are_never_evidence():
    h = None
    for i, status in enumerate(
        (si.STATUS_REFUSED, si.STATUS_WITHHELD, si.STATUS_QUARANTINED, si.STATUS_HELD)
    ):
        h = si.advance(
            h,
            _rec(
                f"2026-10-2{i + 1}T00:00:00+00:00",
                {"src|player:1": {"u": 5.0, "status": status, "team": None}},
                {"src": f"H{i}"},
            ),
        )
    assert "src|player:1" not in h.observations


def _released_history(**kw):
    base = dict(
        boards=3,
        observations={"src|p": (2.0, 2.0)},
        released={"src|p": si.ReleasedHold(5.0, ("H1",), "2026-10-21T00:00:00+00:00", None)},
    )
    base.update(kw)
    return si.IntegrityHistory(**base)


def _cont(history, *, u=5.0, others=None, hash_="H2", as_of="2026-10-22T00:00:00+00:00", v21=True):
    votes = {"src": u, **(others or {"o1": 2.0, "o2": 2.05})}
    return si.continuity_decision(
        source="src",
        player_key="p",
        row_votes=votes,
        provider_of=lambda k: k,
        history=history,
        thresholds=si.IntegrityThresholds(),
        source_hash=hash_,
        as_of=as_of,
        v21=v21,
    )


def test_p3_a_hold_at_the_cap_votes_but_is_not_accepted():
    pend = si.IntegrityHistory(
        boards=3,
        observations={"src|p": (2.0, 2.0)},
        pending={"src|p": si.PendingHold(5.0, "2026-10-21T00:00:00+00:00", 1, "H1")},
    )
    v2 = _cont(pend, v21=False, u=5.6)
    v21 = _cont(pend, u=5.6)
    assert v2.action == si.B4_RELEASE and v2.alert == si.ALERT_HOLD_CAP
    assert v21.action == si.B4_RELEASED_BY_CAP and v21.alert == si.ALERT_HOLD_CAP
    assert not v21.held  # it votes


def test_p3_released_vote_stays_unaccepted_until_three_datasets_over_72h():
    h = _released_history()
    assert _cont(h).released_by_cap  # 2 datasets, 24 h
    h3 = _released_history(
        released={"src|p": si.ReleasedHold(5.0, ("H1", "H2"), "2026-10-21T00:00:00+00:00", None)}
    )
    assert _cont(h3, hash_="H3", as_of="2026-10-22T00:00:00+00:00").released_by_cap  # 48 h
    got = _cont(h3, hash_="H3", as_of="2026-10-24T01:00:00+00:00")
    assert got.action == si.B4_ACCEPT and got.detail["why"] == "reproduced_content_distinct"
    # same dataset re-read three times is still one dataset
    same = _released_history(
        released={"src|p": si.ReleasedHold(5.0, ("H1",), "2026-10-20T00:00:00+00:00", None)}
    )
    assert _cont(same, hash_="H1", as_of="2026-10-25T00:00:00+00:00").released_by_cap


def test_p3_cross_sectional_release_accepts():
    got = _cont(_released_history(), others={"o1": 5.1, "o2": 2.0})
    assert got.action == si.B4_ACCEPT and got.detail["why"] == "cross_sectional_release"


def test_p3_advance_never_accepts_a_released_by_cap_vote():
    h = si.advance(
        None,
        _rec(
            "2026-10-21T00:00:00+00:00",
            {"src|p": {"u": 5.0, "status": si.STATUS_RELEASED_BY_CAP, "team": None}},
            {"src": "H1"},
        ),
    )
    assert "src|p" not in h.observations and "src|p" in h.released
    h = si.advance(
        h,
        _rec(
            "2026-10-22T00:00:00+00:00",
            {"src|p": {"u": 5.0, "status": si.STATUS_RELEASED_BY_CAP, "team": None}},
            {"src": "H1"},
        ),
    )
    assert h.released["src|p"].hashes == ("H1",)  # P-1 inside P-3
    h = si.advance(
        h,
        _rec(
            "2026-10-25T00:00:00+00:00",
            {"src|p": {"u": 5.0, "status": si.STATUS_VOTING, "team": None}},
            {"src": "H9"},
        ),
    )
    assert "src|p" not in h.released and h.observations["src|p"] == (5.0,)


def test_p4_persistence_confirmed_gross_dissent_votes_and_is_named():
    verdict = op.LayerCVerdict(
        kept=("a", "b", "c"),
        dropped=(),
        dissent={"a": op.KEPT_DISSENT},
        kept_because={"a": op.C_KEPT_PERSISTENT},
    )
    v2 = si.layer_c_stamp(None, "a", verdict)
    v21 = si.layer_c_stamp(None, "a", verdict, v21=True)
    assert v2["primaryReason"] == si.REASON_KEPT_DISSENT
    assert v21["status"] == si.STATUS_VOTING
    assert v21["primaryReason"] == si.REASON_PERSISTENT_GROSS_DISSENT
    assert v21["category"] == si.CATEGORY_DISSENT


def test_history_json_round_trip_carries_the_v21_state_and_v2_json_is_unchanged():
    h = si.IntegrityHistory(
        boards=2,
        observations={"s|p": (1.0,)},
        obs_hashes={"s|p": ("H",)},
        released={"s|q": si.ReleasedHold(2.0, ("H",), "a", "b")},
        row_teams={"p": ("BUF", "MIA")},
    )
    back = si.IntegrityHistory.from_json(json.loads(json.dumps(h.to_json())))
    assert back == h
    assert back.previous_row_teams("p", "MIA") == ("BUF",)
    v2_json = si.IntegrityHistory(boards=1).to_json()
    assert not {"obsHashes", "released", "rowTeams"} & set(v2_json)


# ── R13: compact stamps ────────────────────────────────────────────────


def test_r13_a_plain_vote_carries_no_block_and_advisories_still_travel():
    plain = {"sourceIntegrity": {"s": {"identity": {"verdict": "VERIFIED"}}}}
    assert si.voting_stamp(plain, "s", compact=True) is None
    assert si.voting_stamp(plain, "s")["status"] == si.STATUS_VOTING  # V2
    team = {"sourceIntegrity": {"s": {"identity": {"verdict": "TEAM_UNCONFIRMED"}}}}
    assert si.voting_stamp(team, "s", compact=True)["primaryReason"] == si.REASON_TEAM_UNCONFIRMED
    adv = {"sourceIntegrity": {"s": {"advisory": si.REASON_FORMAT_MINOR}}}
    assert si.voting_stamp(adv, "s", compact=True)["advisory"] == si.REASON_FORMAT_MINOR


# ── pipeline: R6 ordinal slots, R7 explainer, OFF identity (§9 19 / 24) ─


def _wrong_player_csvs():
    csvs = _csvs(META)
    lines = csvs["dynastyNerdsSfTep.csv"].splitlines()
    lines = [ln for ln in lines if not ln.startswith("Off Vet 002,")]
    lines.append("Off Vet 002,90,5500,,LB,CLE")
    csvs["dynastyNerdsSfTep.csv"] = "\n".join(lines) + "\n"
    return csvs


@pytest.fixture(scope="module")
def wrong_player():
    csvs = _wrong_player_csvs()
    return {
        "off": _build(csvs=csvs),
        "v2": _build(ALL_ON, csvs=csvs),
        "v21": _build(V21_ON, csvs=csvs),
    }


def test_v21_flag_off_under_the_master_is_v2_exactly(wrong_player):
    again = _build(ALL_ON, csvs=_wrong_player_csvs())
    assert _values(again) == _values(wrong_player["v2"])
    assert "repairs" not in wrong_player["v2"]["sourceIntegrity"]


def test_v21_stamps_its_repairs_and_proof_sources(wrong_player):
    stamp = wrong_player["v21"]["sourceIntegrity"]
    assert stamp["repairs"] == list(si.REPAIR_IDS)
    assert isinstance(stamp["proofSources"], list)
    assert stamp["persistenceRules"] == si.PERSISTENCE_RULES_V21
    assert stamp["sleeperDirectory"] in ("sleeper_directory", "board_rows_only")


def test_r6_a_refusal_moves_only_its_own_row(wrong_player):
    """§9 property 19: refusing one entry leaves every other entry's effective
    rank and vote value byte-identical to the incumbent's."""
    off, v21 = _rows(wrong_player["off"]), _rows(wrong_player["v21"])
    src = "dynastyNerdsSfTep"
    moved_v2 = 0
    v2 = _rows(wrong_player["v2"])
    for name, row in off.items():
        if name == "Off Vet 002" or src not in (row.get("sourceRanks") or {}):
            continue
        assert v21[name]["sourceRanks"][src] == row["sourceRanks"][src], name
        assert (
            v21[name]["sourceRankMeta"][src]["valueContribution"]
            == row["sourceRankMeta"][src]["valueContribution"]
        ), name
        if v2[name]["sourceRanks"].get(src) != row["sourceRanks"][src]:
            moved_v2 += 1
    assert moved_v2 > 0  # V2's side effect (boards F2) that R6 removes


def test_r6_r7_the_refused_vote_is_absent_from_the_blend_and_shown_in_the_explainer(
    wrong_player,
):
    row = _rows(wrong_player["v21"])["Off Vet 002"]
    src = "dynastyNerdsSfTep"
    assert src not in row["canonicalSiteValues"]  # absent, never zero
    stamp = row["sourceIntegrity"][src]
    assert stamp["status"] == si.STATUS_REFUSED
    assert stamp["primaryReason"] == r.ID_REASON_POSITION_FAMILY
    assert stamp["refusedObservation"]["value"] is not None
    meta = row["sourceRankMeta"][src]
    assert meta["contributedToBlend"] is False and meta["appliedWeight"] == 0.0
    assert meta["excludedReason"] == r.ID_REASON_POSITION_FAMILY
    assert meta["integrity"]["category"] == si.CATEGORY_IDENTITY
    assert row["sourcePresence"].get(src) is False


def test_r7_every_exclusion_reaches_the_explainer_with_one_category(wrong_player):
    """§9 property 24 on a built contract."""
    for row in wrong_player["v21"]["playersArray"]:
        metas = row.get("sourceRankMeta") or {}
        for source, stamp in (row.get("sourceIntegrity") or {}).items():
            if stamp.get("status") in (si.STATUS_REFUSED, si.STATUS_WITHHELD):
                assert source in metas, (row["displayName"], source)
        for source, meta in metas.items():
            integ = meta.get("integrity")
            if not integ:
                continue
            assert si.reason_category(integ["primaryReason"]) == integ["category"]
            if integ["status"] == si.STATUS_VOTING:
                assert integ["category"] not in vs.INVALID_OBSERVATION_CATEGORIES


def test_r13_v21_contract_is_smaller_than_v2s(wrong_player):
    def size(c):
        return len(json.dumps(c["playersArray"], sort_keys=True))

    assert size(wrong_player["v21"]) < size(wrong_player["v2"])


def test_v21_team_only_mismatch_votes_on_the_board_at_cold_start():
    csvs = _csvs(META)
    lines = csvs["dynastyNerdsSfTep.csv"].splitlines()
    head, rows = lines[0], lines[1:]
    # Off Vet 005's vendor team is stale (previous team); name + position agree.
    patched = []
    for ln in rows:
        parts = ln.split(",")
        if parts[0] == "Off Vet 005":
            parts[3] = ""  # no Sleeper id: a name join
            parts[5] = "ARI"
        patched.append(",".join(parts))
    csvs["dynastyNerdsSfTep.csv"] = "\n".join([head, *patched]) + "\n"
    v2 = _rows(_build(ALL_ON, csvs=csvs))["Off Vet 005"]
    v21 = _rows(_build(V21_ON, csvs=csvs))["Off Vet 005"]
    assert v2["sourceIntegrity"]["dynastyNerdsSfTep"]["status"] == si.STATUS_REFUSED
    assert "dynastyNerdsSfTep" in v21["canonicalSiteValues"]
    integ = v21["sourceRankMeta"]["dynastyNerdsSfTep"]["integrity"]
    assert integ["primaryReason"] == si.REASON_TEAM_UNCONFIRMED
    assert v21["sourceRankMeta"]["dynastyNerdsSfTep"].get("contributedToBlend") is not False


def test_v21_flags_off_board_is_byte_identical_to_the_incumbent():
    off = _build(csvs=_wrong_player_csvs())
    with_v21_only = _build(("outlier_integrity_v21",), csvs=_wrong_player_csvs())
    assert json.dumps(off["playersArray"], sort_keys=True) == json.dumps(
        with_v21_only["playersArray"], sort_keys=True
    )
    assert "sourceIntegrity" not in with_v21_only


# ── #1831 Option B item 6: the freshness-affected rows (L3) ────────────

FIXTURE = REPO / "tests/fixtures/outlier_integrity_v2/freshness_v2_affected_rows_2026-10-20.json"


def test_l3_freshness_fixture_defines_the_registered_cold_start_set():
    """V2.1 §7.4 L3: the Option-B fixture's incumbent exclusions are the
    registered legitimate set (27 flag-OFF + 23 flag-ON = 50 vote-instances,
    39 distinct player-source pairs).  The board-level L3 run (pinOB at D,
    freshness v2 OFF and ON) is a Stage 3 constraint; this pins its input."""
    data = json.loads(FIXTURE.read_text())
    rows = data["rows"]
    before = sum(len(x["outlierExcludedBefore"]) for x in rows)
    after = sum(len(x["outlierExcludedAfter"]) for x in rows)
    pairs = {
        (x["player"], s)
        for x in rows
        for s in x["outlierExcludedBefore"] + x["outlierExcludedAfter"]
    }
    assert (len(rows), before, after, len(pairs)) == (31, 27, 23, 39)
    wester = next(x for x in rows if x["player"] == "LaJohntay Wester")
    assert "flockFantasySf" in wester["outlierExcludedBefore"]
    unpriced = {x["player"] for x in data["summary"]["newlyUnpriced"]}
    assert {"Dee Alford", "James Pierre", "Kyle Dugger"} <= unpriced
