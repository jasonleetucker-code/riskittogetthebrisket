"""Outlier-integrity-v2 Layers A + B (``src/api/source_integrity.py``).

Preregistration ``docs/sources/OUTLIER_INTEGRITY_V2_PREREGISTRATION.md`` (Stage 1:
implementation behind default-OFF flags, unit and property tests on SYNTHETIC
rows only — no held-out, independent or regression board is read here).

Covers B0 (format), B1 (rookie ladder fail-closed), B2 (payload provenance), B3
(segment integrity), B4 (continuity holds), the reason vocabulary, the history
lane, the flags, and the pipeline wiring end to end on a synthetic payload built
through the production entry point (``build_api_data_contract``).
"""

from __future__ import annotations

import contextlib
import io
import json
import math
import os
import tempfile
from pathlib import Path

import pytest

from src.api import data_contract as dc
from src.api import feature_flags
from src.api import source_integrity as si
from src.history import source_rank as lane

V2_FLAGS = (
    "outlier_integrity_v2",
    "identity_evidence_v2",
    "payload_provenance_guard",
    "rookie_ladder_fail_closed",
    "source_rank_history_record",
    "integrity_holds_as_withheld",
)
ALL_ON = (
    "outlier_integrity_v2",
    "identity_evidence_v2",
    "payload_provenance_guard",
    "rookie_ladder_fail_closed",
)


@contextlib.contextmanager
def _flags(*names: str, off: tuple[str, ...] = ()):
    env = {f"RISKIT_FEATURE_{n.upper()}": "1" for n in names}
    env.update({f"RISKIT_FEATURE_{n.upper()}": "0" for n in off})
    prior = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    feature_flags.reload()
    try:
        yield
    finally:
        for k, v in prior.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        feature_flags.reload()


# ── flags ──────────────────────────────────────────────────────────────


def test_every_v2_flag_ships_off_and_is_a_live_gate():
    for name in V2_FLAGS:
        assert feature_flags._DEFAULTS[name] is False, name
        assert feature_flags.gate_status(name) == feature_flags.LIVE, name


def test_sub_flags_need_the_master():
    with _flags(
        "identity_evidence_v2",
        "payload_provenance_guard",
        "rookie_ladder_fail_closed",
        "integrity_holds_as_withheld",
    ):
        assert not si.v2_active()
        assert not si.identity_layer_active()
        assert not si.provenance_guard_active()
        assert not si.rookie_fail_closed_active()
        assert not si.holds_as_withheld_active()
    with _flags(*ALL_ON):
        assert si.v2_active() and si.identity_layer_active()
        assert si.provenance_guard_active() and si.rookie_fail_closed_active()


def test_v2_and_v1_are_mutually_exclusive():
    with _flags("outlier_integrity_v2", "outlier_disagreement_policy"):
        with pytest.raises(si.ChallengerConflictError):
            si.v2_active()


# ── reason vocabulary ──────────────────────────────────────────────────


def test_every_emitted_reason_maps_to_one_directive_category():
    from src.identity import resolution as r

    codes = [
        si.REASON_VOTING,
        si.REASON_NAME_ONLY,
        si.REASON_SEGMENT_BREAK_UNPROVEN,
        si.REASON_FORMAT_SCHEMA,
        si.REASON_FORMAT_NON_NUMERIC,
        si.REASON_FORMAT_RANK_VALUE,
        si.REASON_UNTRANSLATED,
        si.REASON_DEPENDENCY,
        si.REASON_PROVENANCE,
        si.REASON_HELD_DISCONTINUITY,
        si.scale_error_reason("x", "idp", "LB"),
        si.scale_error_reason("x", "idp"),
        si.direction_error_reason("x", "offense", "WR"),
        r.ID_REASON_SLEEPER_ID,
        r.ID_REASON_VENDOR_ID,
        r.ID_REASON_JOIN_INCONSISTENT,
        r.ID_REASON_POSITION_GROUP,
        r.ID_REASON_ROOKIE_CLASS,
        r.ID_REASON_AGE,
        r.ID_REASON_AMBIGUOUS_IN_SOURCE,
        r.ID_REASON_HOMONYM,
        r.ID_REASON_LOW_EVIDENCE_RUNG,
        r.ID_REASON_TEAM_ONLY_MISMATCH,
    ]
    for code in codes:
        assert si.reason_category(code) is not None, code
    # A legitimate dissent / unproven segment break is never an invalid category.
    for code in (si.REASON_SEGMENT_BREAK_UNPROVEN, "kept_dissent"):
        assert si.reason_category(code) == si.CATEGORY_DISSENT
    # Held identity is "held pending confirmation", never "invalid identity".
    assert si.reason_category(r.ID_REASON_TEAM_ONLY_MISMATCH) == si.CATEGORY_HELD


def test_primary_reason_precedence_identity_format_normalization_freshness_held():
    from src.identity import resolution as r

    codes = [
        si.REASON_HELD_DISCONTINUITY,
        "freshness_or_health_zero_weight",
        si.REASON_UNTRANSLATED,
        si.REASON_PROVENANCE,
        r.ID_REASON_POSITION_GROUP,
    ]
    primary, others = si.primary_reason(codes)
    assert primary == r.ID_REASON_POSITION_GROUP
    assert others[0] == si.REASON_PROVENANCE
    assert si.primary_reason([si.REASON_HELD_DISCONTINUITY, si.REASON_UNTRANSLATED])[0] == (
        si.REASON_UNTRANSLATED
    )


# ── B0 ─────────────────────────────────────────────────────────────────


def test_b0_rank_value_order_agreement_is_exact_and_tie_tolerant():
    assert si.rank_value_discordant_rows([(1, 100), (2, 90), (3, 80)]) == 0
    assert si.rank_value_discordant_rows([(1, 100), (2, 100), (3, 80)]) == 0  # value tie
    assert si.rank_value_discordant_rows([(1, 100), (1, 90), (2, 80)]) == 0  # rank tie
    assert si.rank_value_discordant_rows([(1, 100), (2, 90), (3, 95)]) == 1
    # Non-positive / missing values are never read (DLF / Yahoo blanks).
    assert si.rank_value_discordant_rows([(1, 100), (2, 0), (3, None)]) == 0


def test_b0_findings():
    bad = {"rows": 3, "nonNumericValueRows": 0, "rankValuePairs": [(1, 1), (2, 5)]}
    (f,) = si.format_findings("someSource", bad)
    assert f.hard and f.reason == si.REASON_FORMAT_RANK_VALUE
    assert si.format_findings("fantasyProsIdp", bad) == []  # per-page rank by design
    nn = {"rows": 5, "nonNumericValueRows": 2, "rankValuePairs": []}
    (g,) = si.format_findings("someSource", nn)
    assert not g.hard and g.reason == si.REASON_FORMAT_NON_NUMERIC


# ── B2 ─────────────────────────────────────────────────────────────────


def _pairs(groups: dict[str, float], n: int = 20, base: float = 3000.0):
    out, idx = [], 0
    for g, factor in groups.items():
        for i in range(n):
            csv = base - 10 * i
            out.append(si.ProvenancePair(idx, g, csv * factor, csv))
            idx += 1
    return out


def test_b2_healthy_board_has_exactly_zero_log_ratio_and_no_proof():
    res = si.provenance_check(_pairs({"QB": 1.0, "WR": 1.0}), epsilon=0.01)
    assert not res.board_proof and not res.row_proofs
    assert all(s["medianLogRatio"] == 0.0 for s in res.group_stats.values())


def test_b2_a_format_switch_in_two_groups_is_a_board_proof():
    res = si.provenance_check(_pairs({"QB": 0.7, "PICK": 0.8, "WR": 1.0}), epsilon=0.05)
    assert res.board_proof
    assert set(res.proven_groups) == {"QB", "PICK"}


def test_b2_one_group_alone_is_not_a_board_proof():
    res = si.provenance_check(_pairs({"QB": 0.7, "WR": 1.0}), epsilon=0.05)
    assert not res.board_proof


def test_b2_thin_groups_and_low_values_cannot_prove_a_board():
    res = si.provenance_check(_pairs({"QB": 0.7, "PICK": 0.7}, n=10), epsilon=0.05)
    assert not res.board_proof
    low = si.provenance_check(_pairs({"QB": 0.7, "PICK": 0.7}, base=90.0), epsilon=0.05)
    assert not low.board_proof


def test_b2_a_single_wrong_row_capture_is_a_row_proof():
    pairs = _pairs({"WR": 1.0})
    pairs.append(si.ProvenancePair(999, "WR", 800.0, 7500.0))  # the surname capture
    res = si.provenance_check(pairs, epsilon=0.05)
    assert not res.board_proof
    assert res.row_proofs == frozenset({999})


def test_b2_capture_stamp_with_toggle_off_is_a_board_proof():
    assert si.provenance_check([], epsilon=0.05, format_toggle_off=True).board_proof


# ── B3 ─────────────────────────────────────────────────────────────────

PROVIDERS = {"a": "pa", "b": "pb", "c": "pc", "x": "px"}


def _seg_rows(n=30, *, x_fn=None, pos="WR", asset_class="offense"):
    rows = {}
    for i in range(n):
        u = 2.5 + 0.1 * i
        votes = {"a": u, "b": u + 0.01, "c": u - 0.01}
        votes["x"] = x_fn(i, u) if x_fn else u
        rows[i] = (asset_class, pos, votes)
    return rows


def _screen(rows, history=None, proof=(), **thr):
    return si.segment_screen(
        rows,
        provider_of=PROVIDERS.get,
        thresholds=si.IntegrityThresholds(**thr),
        history=history,
        proof_sources=proof,
    )


def test_b3_healthy_board_flags_nothing():
    res = _screen(_seg_rows())
    assert not res.quarantines and not res.advisories


def test_b3_reversed_segment_is_a_direction_error_without_history():
    res = _screen(_seg_rows(x_fn=lambda i, u: 2.5 + 0.1 * (29 - i)))
    assert res.quarantines == {
        ("x", "offense", "WR"): si.direction_error_reason("x", "offense", "WR")
    }


def test_b3_direction_needs_n_min_rows():
    res = _screen(_seg_rows(n=12, x_fn=lambda i, u: 2.5 + 0.1 * (11 - i)))
    assert not res.quarantines


def _hist(medians: dict[str, float]) -> si.IntegrityHistory:
    return si.IntegrityHistory(boards=3, segments={k: (v, v, v) for k, v in medians.items()})


def test_b3_gross_scale_shift_against_own_history_is_hard():
    rows = _seg_rows(x_fn=lambda i, u: u + 1.6)  # ~5x in implied rank
    res = _screen(rows, history=_hist({"x|offense|WR": 0.0}))
    assert ("x", "offense", "WR") in res.quarantines
    assert res.quarantines[("x", "offense", "WR")].startswith(
        "normalization_scale_error@x/offense/WR"
    )


def test_b3_sub_gross_shift_is_kept_with_advisory_unless_same_build_proof():
    rows = _seg_rows(x_fn=lambda i, u: u + 0.4)
    hist = _hist({"x|offense|WR": 0.0})
    kept = _screen(rows, history=hist)
    assert not kept.quarantines
    assert kept.advisories == {("x", "offense", "WR"): si.REASON_SEGMENT_BREAK_UNPROVEN}
    proven = _screen(rows, history=hist, proof=("x",))
    assert ("x", "offense", "WR") in proven.quarantines


def test_b3_constant_opinion_offset_with_matching_history_is_not_a_break():
    """A consistently contrarian source: its offset is its own baseline."""
    rows = _seg_rows(x_fn=lambda i, u: u + 0.9)
    res = _screen(
        rows,
        history=_hist({"x|offense|WR": 0.9, "x|offense|*": 0.9}),
        tau_board={"x|offense": 0.05},
    )
    assert not res.quarantines and not res.advisories


def test_b3a_class_conservation_needs_history_and_tau_board():
    rows = _seg_rows(x_fn=lambda i, u: u + 0.5)
    no_tau = _screen(rows, history=_hist({"x|offense|*": 0.0}))
    assert ("x", "offense", None) not in no_tau.quarantines
    assert no_tau.stats["x|offense|*"]["abstained"] == "tau_board_unavailable"
    fired = _screen(rows, history=_hist({"x|offense|*": 0.0}), tau_board={"x|offense": 0.02})
    assert ("x", "offense", None) in fired.quarantines


def test_b3_is_order_free():
    rows = _seg_rows(x_fn=lambda i, u: 2.5 + 0.1 * (29 - i))
    shuffled = {k: rows[k] for k in sorted(rows, reverse=True)}
    a, b = _screen(rows), _screen(shuffled)
    assert a.quarantines == b.quarantines and a.medians == b.medians


def test_b3_identical_synthetic_values_never_narrow_anything():
    """Two rank boards translated onto one identical coordinate are not a
    corroborated cluster for B3: equality changes no statistic of the third."""
    rows = _seg_rows()
    dup = {k: (c, p, {**v, "b": v["a"]}) for k, (c, p, v) in rows.items()}
    assert _screen(rows).quarantines == _screen(dup).quarantines == {}


# ── B4 ─────────────────────────────────────────────────────────────────


def _thr_c(tau=0.3):
    return si.IntegrityThresholds(tau_c={"x": {b: tau for _e, b in si.B4_BANDS}})


def _b4(row_votes, history, *, hash_="h1", as_of="2026-08-20T00:00:00+00:00", thr=None):
    return si.continuity_decision(
        source="x",
        player_key="player:1",
        row_votes=row_votes,
        provider_of=PROVIDERS.get,
        history=history,
        thresholds=thr or _thr_c(),
        source_hash=hash_,
        as_of=as_of,
    )


def _obs_hist(**obs) -> si.IntegrityHistory:
    return si.IntegrityHistory(
        boards=3, observations={f"{k}|player:1": tuple(v) for k, v in obs.items()}
    )


def test_b4_abstains_without_history_or_tau_c():
    votes = {"x": 5.0, "a": 3.0, "b": 3.0}
    assert _b4(votes, None).action == si.B4_ABSTAIN
    assert _b4(votes, _obs_hist(x=[3.0] * 3), thr=si.IntegrityThresholds()).action == si.B4_ABSTAIN
    assert _b4(votes, _obs_hist(a=[3.0] * 3)).action == si.B4_ABSTAIN  # no own prior


def test_b4_holds_a_jump_away_from_everyone_with_no_comovement():
    hist = _obs_hist(x=[3.0, 3.0, 3.0], a=[3.0] * 3, b=[3.0] * 3)
    d = _b4({"x": 5.0, "a": 3.0, "b": 3.0}, hist)
    assert d.held


def test_b4_never_holds_a_move_toward_consensus():
    hist = _obs_hist(x=[5.0] * 3, a=[3.0] * 3, b=[3.0] * 3)
    assert _b4({"x": 3.1, "a": 3.0, "b": 3.0}, hist).action == si.B4_ACCEPT


def test_b4_corroboration_or_comovement_releases_real_news():
    hist = _obs_hist(x=[3.0] * 3, a=[3.0] * 3, b=[3.0] * 3)
    # another provider already within ln 1.25
    assert _b4({"x": 5.0, "a": 4.9, "b": 3.0}, hist).action == si.B4_ACCEPT
    # another provider co-moved the same way by at least half as much
    assert _b4({"x": 5.0, "a": 4.0, "b": 3.0}, hist).action == si.B4_ACCEPT


def test_b4_pending_hold_release_rules():
    base = dict(
        observations={"x|player:1": (3.0,) * 3, "a|player:1": (3.0,) * 3, "b|player:1": (3.0,) * 3},
        boards=3,
    )
    pending = si.PendingHold(
        u=5.0, first_held_at="2026-08-20T00:00:00+00:00", fetches=0, last_hash="h1"
    )
    hist = si.IntegrityHistory(**base, pending={"x|player:1": pending})
    votes = {"x": 5.0, "a": 3.0, "b": 3.0}
    # same content: still held
    assert _b4(votes, hist, hash_="h1", as_of="2026-08-20T02:00:00+00:00").held
    # next content-distinct fetch reproduces the value: released
    assert _b4(votes, hist, hash_="h2", as_of="2026-08-20T04:00:00+00:00").action == si.B4_RELEASE
    # 48 h cap: released with an alert
    d = _b4(votes, hist, hash_="h1", as_of="2026-08-22T01:00:00+00:00")
    assert d.action == si.B4_RELEASE and d.alert == si.ALERT_HOLD_CAP
    # fetch cap: a second content-distinct fetch still suspicious -> released, alert
    p2 = si.PendingHold(u=5.0, first_held_at="2026-08-20T00:00:00+00:00", fetches=1, last_hash="h2")
    h2 = si.IntegrityHistory(**base, pending={"x|player:1": p2})
    d2 = _b4({"x": 5.9, "a": 3.0, "b": 3.0}, h2, hash_="h3", as_of="2026-08-20T06:00:00+00:00")
    assert d2.action == si.B4_RELEASE and d2.alert == si.ALERT_HOLD_CAP


# ── history lane ───────────────────────────────────────────────────────


def _record(as_of, obs, hashes=None, medians=None, quarantined=()):
    return {
        "schema": "oiv2-board-record/v1",
        "asOf": as_of,
        "hashes": hashes or {"x": "h-" + as_of},
        "observations": obs,
        "segmentMedians": medians or {},
        "quarantinedScopes": list(quarantined),
    }


def test_advance_keeps_three_accepted_and_tracks_pending_holds():
    h = None
    for i in range(5):
        h = si.advance(
            h,
            _record(
                f"2026-08-2{i}T00:00:00+00:00",
                {"x|p": {"u": float(i), "status": "voting", "team": "BUF"}},
                medians={"x|offense|WR": 0.1 * i},
            ),
        )
    assert h.observations["x|p"] == (2.0, 3.0, 4.0)
    assert h.teams["x|p"] == "BUF"
    assert h.segments["x|offense|WR"] == pytest.approx((0.2, 0.3, 0.4))
    h2 = si.advance(
        h,
        _record(
            "2026-08-26T00:00:00+00:00", {"x|p": {"u": 9.0, "status": "held"}}, hashes={"x": "hA"}
        ),
    )
    assert h2.pending["x|p"].fetches == 0 and h2.observations["x|p"] == (2.0, 3.0, 4.0)
    same = si.advance(
        h2,
        _record(
            "2026-08-26T02:00:00+00:00", {"x|p": {"u": 9.0, "status": "held"}}, hashes={"x": "hA"}
        ),
    )
    assert same.pending["x|p"].fetches == 0
    new = si.advance(
        same,
        _record(
            "2026-08-26T04:00:00+00:00", {"x|p": {"u": 9.1, "status": "held"}}, hashes={"x": "hB"}
        ),
    )
    assert new.pending["x|p"].fetches == 1
    done = si.advance(
        new, _record("2026-08-27T00:00:00+00:00", {"x|p": {"u": 9.1, "status": "voting"}})
    )
    assert "x|p" not in done.pending and done.observations["x|p"][-1] == 9.1


def test_quarantined_segments_never_enter_the_baseline():
    h = si.advance(
        None,
        _record(
            "2026-08-20T00:00:00+00:00",
            {},
            medians={"x|offense|WR": 1.5},
            quarantined=["x|segment:offense/WR"],
        ),
    )
    assert "x|offense|WR" not in h.segments


def test_history_json_round_trip():
    h = si.IntegrityHistory(
        as_of="2026-08-20T00:00:00+00:00",
        boards=2,
        segments={"x|idp|LB": (0.1, 0.2)},
        observations={"x|p": (3.0,)},
        teams={"x|p": "BUF"},
        pending={"x|q": si.PendingHold(4.0, "2026-08-20T00:00:00+00:00", 1, "h")},
        hashes={"x": "h"},
    )
    assert si.IntegrityHistory.from_json(json.loads(json.dumps(h.to_json()))) == h
    assert si.IntegrityHistory.from_json({"schema": "other"}) is None


def test_lane_never_serves_a_state_not_older_than_the_board(tmp_path):
    from datetime import datetime, timezone

    rec = _record("2026-08-20T00:00:00+00:00", {})
    state = si.advance(None, rec).to_json()
    assert lane.record_board(tmp_path, rec, state)["written"]
    assert lane.record_board(tmp_path, rec, state) == {
        "written": False,
        "reason": "not_newer_than_state",
    }
    t = datetime(2026, 8, 20, tzinfo=timezone.utc)
    assert lane.load_state(tmp_path, before=t) is None  # same instant: not older
    assert lane.load_state(tmp_path, before=t.replace(day=21)) is not None
    lines = (lane.lane_dir(tmp_path) / lane.RECORDS_FILE).read_text().splitlines()
    assert len(lines) == 1 and "stateSha256" in json.loads(lines[0])


# ── pipeline (synthetic payload through build_api_data_contract) ───────

OFF_POS = ("QB", "RB", "WR", "TE")
IDP_POS = ("DL", "LB", "DB")
TEAMS = ("BUF", "MIA", "NE", "NYJ", "KC", "DEN", "LV", "LAC")


def _payload(n_off=96, n_idp=48, n_rook=12):
    players: dict[str, dict] = {}
    meta = []
    market = 9000
    for i in range(max(n_off, n_idp)):
        if i < n_off:
            name, pos = f"Off Vet {i + 1:03d}", OFF_POS[i % 4]
            players[name] = {
                "position": pos,
                "team": TEAMS[i % 8],
                "age": 25,
                "_sleeperId": str(1000 + i),
                "_yearsExp": 3,
                "_canonicalSiteValues": {"idpTradeCalc": market, "ktcCrowdSfTep": market},
                "idpTradeCalc": market,
                "ktcCrowdSfTep": market,
            }
            meta.append((name, pos, market, False))
            market -= 40
        if i < n_idp:
            name, pos = f"Idp Vet {i + 1:03d}", IDP_POS[i % 3]
            players[name] = {
                "position": pos,
                "team": TEAMS[(i + 3) % 8],
                "age": 26,
                "_sleeperId": str(2000 + i),
                "_yearsExp": 4,
                "_canonicalSiteValues": {"idpTradeCalc": market},
                "idpTradeCalc": market,
            }
            meta.append((name, pos, market, False))
            market -= 30
    for i in range(n_rook):
        name, pos = f"Off Rook {i + 1:03d}", ("RB", "WR")[i % 2]
        players[name] = {
            "position": pos,
            "team": TEAMS[i % 8],
            "age": 21,
            "_sleeperId": str(3000 + i),
            "_yearsExp": 0,
            "_isRookie": True,
            "_canonicalSiteValues": {"idpTradeCalc": market, "ktcCrowdSfTep": market},
            "idpTradeCalc": market,
            "ktcCrowdSfTep": market,
        }
        meta.append((name, pos, market, True))
        market -= 20
    payload = {
        "version": "oiv2-synth",
        "date": "2026-08-20",
        "settings": {},
        "sites": {},
        "maxValues": {},
        "players": players,
    }
    return payload, meta


PAYLOAD, META = _payload()


def _csvs(meta) -> dict[str, str]:
    players = PAYLOAD["players"]
    off = [m for m in meta if m[1] in OFF_POS and not m[3]]
    idp = [m for m in meta if m[1] in IDP_POS]
    rook = [m for m in meta if m[3]]
    dn = ["Name,Rank,Value,SleeperId,Pos,Team"] + [
        f"{n},{r},{10000 - r * 50},{players[n]['_sleeperId']},{p},{players[n]['team']}"
        for r, (n, p, _v, _rk) in enumerate(off + rook, 1)
    ]
    fc = ["name,value,rank"] + [
        f"{n},{9000 - r * 10},{r}" for r, (n, _p, _v, _rk) in enumerate(off + rook, 1)
    ]
    dlfr = ["name,rank,value"] + [f"{n},{r}," for r, (n, _p, _v, _rk) in enumerate(rook, 1)]
    fpi = [
        "name,originalRank,effectiveRank,derivationMethod,family,normalizedValue,"
        "matchedSourceName,position,team"
    ] + [
        f"{n},{r},{r},direct,{p},0,{n},{p},{players[n]['team']}"
        for r, (n, p, _v, _rk) in enumerate(idp, 1)
    ]
    dsi = ["Rank,Team,Player,Fantasy Position,ADP,Bye,Age,3D Value +"] + [
        f"{r},{players[n]['team']},{n},{p},0,0,26,{100 - r}"
        for r, (n, p, _v, _rk) in enumerate(idp, 1)
    ]
    return {
        "dynastyNerdsSfTep.csv": "\n".join(dn) + "\n",
        "fantasyCalc.csv": "\n".join(fc) + "\n",
        "dlfRookieSf.csv": "\n".join(dlfr) + "\n",
        "fantasyProsIdp.csv": "\n".join(fpi) + "\n",
        "draftSharksIdp.csv": "\n".join(dsi) + "\n",
    }


def _build(flags=(), *, csvs=None, overrides=None, mutate=None, history="unset"):
    with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
        d = Path(tmp) / "CSVs" / "site_raw"
        d.mkdir(parents=True)
        for name, text in (csvs if csvs is not None else _csvs(META)).items():
            (d / name).write_text(text)
        payload = json.loads(json.dumps(PAYLOAD))
        if mutate:
            mutate(payload)
        with _flags(*flags), contextlib.ExitStack() as stack:
            if history != "unset":
                stack.enter_context(si.history_override(history))
            contract = dc.build_api_data_contract(
                payload, csv_root=Path(tmp), source_overrides=overrides
            )
    return contract


def _rows(contract):
    return {r["displayName"]: r for r in contract["playersArray"]}


def _values(contract):
    return {r["displayName"]: r.get("rankDerivedValue") for r in contract["playersArray"]}


@pytest.fixture(scope="module")
def clean_off():
    return _build()


@pytest.fixture(scope="module")
def clean_on():
    return _build(ALL_ON)


def test_off_never_constructs_a_build_and_stamps_nothing(clean_off, monkeypatch):
    def boom(*_a, **_k):
        raise AssertionError("source_integrity reached with the flag off")

    monkeypatch.setattr(si, "new_build", boom)
    monkeypatch.setattr(si, "rank_with_segment_screen", boom)
    contract = _build()
    assert "sourceIntegrity" not in contract
    for row in contract["playersArray"]:
        assert "sourceIntegrity" not in row and "sourceProvenance" not in row
        for meta in (row.get("sourceRankMeta") or {}).values():
            assert "integrity" not in meta
    assert _values(contract) == _values(clean_off)


def test_on_a_clean_board_changes_no_value(clean_off, clean_on):
    assert _values(clean_on) == _values(clean_off)
    stamp = clean_on["sourceIntegrity"]
    assert stamp["version"] == si.POLICY_VERSION
    assert stamp["voteExclusions"] == {} and stamp["rankingPasses"] == 1
    assert stamp["historyLane"]["state"] == "absent"
    assert stamp["thresholds"]["status"] == "frozen_stage2"
    # every vote carries its integrity block
    for row in clean_on["playersArray"]:
        for meta in (row.get("sourceRankMeta") or {}).values():
            if not meta.get("excludedReason"):
                assert meta["integrity"]["status"] == si.STATUS_VOTING


def test_layer_a_refuses_a_wrong_player_join_and_leaves_it_absent(clean_off):
    csvs = _csvs(META)
    # Dynasty Nerds publishes "Off Vet 002" as a LINEBACKER at rank 90: on the
    # offense board that is another person, and the incumbent votes it.
    lines = csvs["dynastyNerdsSfTep.csv"].splitlines()
    lines = [ln for ln in lines if not ln.startswith("Off Vet 002,")]
    lines.append("Off Vet 002,90,5500,,LB,CLE")
    csvs["dynastyNerdsSfTep.csv"] = "\n".join(lines) + "\n"
    off = _build(csvs=csvs)
    on = _build(ALL_ON, csvs=csvs)
    r_off, r_on = _rows(off)["Off Vet 002"], _rows(on)["Off Vet 002"]
    assert "dynastyNerdsSfTep" in r_off["canonicalSiteValues"]
    assert "dynastyNerdsSfTep" not in r_on["canonicalSiteValues"]  # absent, never 0
    stamp = r_on["sourceIntegrity"]["dynastyNerdsSfTep"]
    assert stamp["status"] == si.STATUS_REFUSED
    assert stamp["primaryReason"] == "identity_contradicted:position_group"
    assert stamp["category"] == si.CATEGORY_IDENTITY
    assert "dynastyNerdsSfTep" not in (r_on.get("sourceRankMeta") or {})


def test_layer_a_flag_off_under_the_master_is_the_incumbent_join(clean_off):
    on = _build(("outlier_integrity_v2",))
    assert _values(on) == _values(clean_off)
    assert on["sourceIntegrity"]["identity"] == {}


def test_b1_untranslated_rookie_votes_are_withheld_not_voted():
    ov = {"ktcCrowdSfTep": {"include": False}}  # the ladder's reference is gone
    off = _build(overrides=ov)
    on = _build(ALL_ON, overrides=ov)
    r_off = _rows(off)["Off Rook 001"]["sourceRankMeta"]["dlfRookieSf"]
    r_on = _rows(on)["Off Rook 001"]["sourceRankMeta"]["dlfRookieSf"]
    assert not r_off.get("excludedReason")  # incumbent: the within-class rank votes
    assert r_on["excludedReason"] == si.REASON_UNTRANSLATED
    assert r_on["integrity"]["status"] == si.STATUS_WITHHELD
    assert r_on["contributedToBlend"] is False
    assert on["sourceIntegrity"]["voteExclusions"][si.REASON_UNTRANSLATED] == 12
    # rookie_ladder_fail_closed OFF under the master: incumbent behaviour
    master_only = _build(("outlier_integrity_v2",), overrides=ov)
    assert not _rows(master_only)["Off Rook 001"]["sourceRankMeta"]["dlfRookieSf"].get(
        "excludedReason"
    )


def test_b1_translated_rookie_votes_are_untouched(clean_on):
    meta = _rows(clean_on)["Off Rook 001"]["sourceRankMeta"]["dlfRookieSf"]
    assert meta["method"].startswith("rookie_ladder_translation_")
    assert meta["integrity"]["status"] == si.STATUS_VOTING


def _idptc_csv() -> str:
    return "\n".join(["name,value"] + [f"{n},{v}" for n, _p, v, _r in META]) + "\n"


def _scale_payload_qb_rb(payload, factor=0.7):
    for pl in payload["players"].values():
        if pl["position"] in ("QB", "RB"):
            pl["idpTradeCalc"] = int(pl["idpTradeCalc"] * factor)
            pl["_canonicalSiteValues"]["idpTradeCalc"] = pl["idpTradeCalc"]


def test_b2_a_broken_payload_capture_votes_the_vendors_own_csv():
    csvs = {**_csvs(META), "idpTradeCalc.csv": _idptc_csv()}
    off = _build(csvs=csvs, mutate=_scale_payload_qb_rb)
    on = _build(ALL_ON, csvs=csvs, mutate=_scale_payload_qb_rb)
    prov = on["sourceIntegrity"]["provenance"]["idpTradeCalc"]
    assert prov["boardProof"] is True and set(prov["provenGroups"]) == {"QB", "RB"}
    r_off, r_on = _rows(off)["Off Vet 001"], _rows(on)["Off Vet 001"]  # a QB
    assert r_off["canonicalSiteValues"]["idpTradeCalc"] == 6300
    assert r_on["canonicalSiteValues"]["idpTradeCalc"] == 9000
    assert r_on["sourceProvenance"]["idpTradeCalc"]["selected"] == "csv"
    # WR rows were never inconsistent: untouched either way.
    assert "sourceProvenance" not in _rows(on)["Off Vet 003"]


def test_b2_proven_payload_without_a_csv_row_is_withheld_not_zero():
    csv_lines = _idptc_csv().splitlines()
    csv_lines = [ln for ln in csv_lines if not ln.startswith("Off Vet 001,")]
    csvs = {**_csvs(META), "idpTradeCalc.csv": "\n".join(csv_lines) + "\n"}
    on = _build(ALL_ON, csvs=csvs, mutate=_scale_payload_qb_rb)
    row = _rows(on)["Off Vet 001"]
    assert "idpTradeCalc" not in row["canonicalSiteValues"]
    assert row["sourceIntegrity"]["idpTradeCalc"]["status"] == si.STATUS_WITHHELD
    assert row["sourceIntegrity"]["idpTradeCalc"]["primaryReason"] == si.REASON_PROVENANCE


def test_b2_guard_off_under_the_master_keeps_the_payload():
    csvs = {**_csvs(META), "idpTradeCalc.csv": _idptc_csv()}
    on = _build(("outlier_integrity_v2",), csvs=csvs, mutate=_scale_payload_qb_rb)
    assert _rows(on)["Off Vet 001"]["canonicalSiteValues"]["idpTradeCalc"] == 6300


def test_b0_a_board_whose_rank_contradicts_its_value_is_quarantined_at_the_vote():
    csvs = _csvs(META)
    lines = csvs["fantasyCalc.csv"].splitlines()
    head, body = lines[0], lines[1:]
    n0, v0, r0 = body[0].split(",")
    n9, v9, r9 = body[9].split(",")
    body[0], body[9] = f"{n0},{v9},{r0}", f"{n9},{v0},{r9}"  # value order swapped vs rank
    csvs["fantasyCalc.csv"] = "\n".join([head] + body) + "\n"
    on = _build(ALL_ON, csvs=csvs)
    assert on["sourceIntegrity"]["sourceQuarantines"] == {
        "fantasyCalc": si.REASON_FORMAT_RANK_VALUE
    }
    row = _rows(on)["Off Vet 020"]
    meta = row["sourceRankMeta"]["fantasyCalc"]
    assert meta["excludedReason"] == si.REASON_FORMAT_RANK_VALUE
    assert meta["integrity"]["status"] == si.STATUS_QUARANTINED
    # quarantined, not missing: the observation is still on the row and its
    # family is still expected (coverage falls, confidence cannot rise).
    assert "fantasyCalc" in row["canonicalSiteValues"]
    assert "fantasyCalc" in row["sourceRanks"]


def test_b3_a_reversed_segment_quarantines_and_reranks_once(clean_off):
    csvs = _csvs(META)
    lines = csvs["fantasyCalc.csv"].splitlines()
    head, body = lines[0], lines[1:]
    wr = [
        i
        for i, ln in enumerate(body)
        if ln.split(",")[0] in {m[0] for m in META if m[1] == "WR" and not m[3]}
    ]
    ranks = [body[i].split(",")[2] for i in wr]
    vals = [body[i].split(",")[1] for i in wr]
    # Reverse the WR order WITHIN the board while keeping rank/value consistent.
    for j, i in enumerate(wr):
        name = body[i].split(",")[0]
        body[i] = f"{name},{vals[len(wr) - 1 - j]},{ranks[len(wr) - 1 - j]}"
    csvs["fantasyCalc.csv"] = "\n".join([head] + body) + "\n"
    on = _build(ALL_ON, csvs=csvs)
    stamp = on["sourceIntegrity"]
    assert stamp["rankingPasses"] == 2
    assert stamp["segmentQuarantines"] == {
        "fantasyCalc/offense/WR": si.direction_error_reason("fantasyCalc", "offense", "WR")
    }
    wr_row = _rows(on)["Off Vet 003"]
    assert wr_row["sourceRankMeta"]["fantasyCalc"]["integrity"]["status"] == si.STATUS_QUARANTINED
    qb_row = _rows(on)["Off Vet 001"]
    assert qb_row["sourceRankMeta"]["fantasyCalc"]["integrity"]["status"] == si.STATUS_VOTING


def _hold_thresholds(monkeypatch, tau=0.2):
    thr = si.IntegrityThresholds(tau_c={"dynastyNerdsSfTep": {b: tau for _e, b in si.B4_BANDS}})
    monkeypatch.setattr(si, "load_thresholds", lambda path=None: thr)


def _history_from(contract) -> si.IntegrityHistory:
    rec = si.board_record(contract)
    h = None
    for i in range(3):
        h = si.advance(h, {**rec, "asOf": f"2026-08-1{i}T00:00:00+00:00"})
    return h


@pytest.mark.parametrize("d1", [False, True])
def test_b4_holds_a_discontinuous_vote_with_history_and_releases_nothing_else(
    clean_on, monkeypatch, d1
):
    _hold_thresholds(monkeypatch)
    history = _history_from(clean_on)
    csvs = _csvs(META)
    lines = csvs["dynastyNerdsSfTep.csv"].splitlines()
    # Off Vet 006 (rank 6) suddenly published at rank 95: away from its own
    # history and from every other provider, nobody co-moved.
    lines = [ln.replace("Off Vet 006,6,9700,", "Off Vet 006,95,5250,") for ln in lines]
    csvs["dynastyNerdsSfTep.csv"] = "\n".join(lines) + "\n"
    flags = ALL_ON + (("integrity_holds_as_withheld",) if d1 else ())
    on = _build(flags, csvs=csvs, history=history)
    meta = _rows(on)["Off Vet 006"]["sourceRankMeta"]["dynastyNerdsSfTep"]
    assert meta["integrity"]["status"] == si.STATUS_HELD
    assert meta["excludedReason"] == si.REASON_HELD_DISCONTINUITY
    assert si.reason_category(meta["excludedReason"]) == si.CATEGORY_HELD
    assert on["sourceIntegrity"]["historyLane"]["state"] == "override"
    held = [
        (n, k)
        for n, r in _rows(on).items()
        for k, m in (r.get("sourceRankMeta") or {}).items()
        if (m.get("integrity") or {}).get("status") == si.STATUS_HELD
    ]
    assert held == [("Off Vet 006", "dynastyNerdsSfTep")]


def test_history_lane_record_contract_and_reload(tmp_path, clean_on):
    contract = json.loads(json.dumps(clean_on))
    contract["scrapeTimestamp"] = "2026-08-20T00:00:00+00:00"
    out = lane.record_contract(contract, root=tmp_path)
    assert out["written"]
    raw = lane.load_state(tmp_path)
    h = si.IntegrityHistory.from_json(raw)
    assert h is not None and h.boards == 1
    assert any(k.startswith("dynastyNerdsSfTep|player:") for k in h.observations)


def test_missing_is_never_zero_for_any_excluded_vote():
    ov = {"ktcCrowdSfTep": {"include": False}}
    on = _build(ALL_ON, overrides=ov)
    for row in on["playersArray"]:
        for k, meta in (row.get("sourceRankMeta") or {}).items():
            integ = meta.get("integrity") or {}
            if integ.get("status") not in (None, si.STATUS_VOTING):
                assert meta.get("appliedWeight") == 0.0
                assert meta.get("contributedToBlend") is False
        assert row.get("rankDerivedValue") is None or row["rankDerivedValue"] > 0


def test_flags_off_keep_every_protected_constant_unchanged():
    """§9 property 11: the layers change no weight, family, curve or cap."""
    from src.canonical import player_valuation as pv

    before = (
        json.dumps(dc._RANKING_SOURCES, sort_keys=True, default=str),
        pv.HILL_PERCENTILE_C,
        pv.HILL_PERCENTILE_S,
        pv.IDP_HILL_PERCENTILE_C,
        pv.IDP_HILL_PERCENTILE_S,
        dc._HAMPEL_K,
        dc._HAMPEL_MIN_N,
        dc._HAMPEL_MIN_THRESHOLD,
    )
    _build(ALL_ON)
    after = (
        json.dumps(dc._RANKING_SOURCES, sort_keys=True, default=str),
        pv.HILL_PERCENTILE_C,
        pv.HILL_PERCENTILE_S,
        pv.IDP_HILL_PERCENTILE_C,
        pv.IDP_HILL_PERCENTILE_S,
        dc._HAMPEL_K,
        dc._HAMPEL_MIN_N,
        dc._HAMPEL_MIN_THRESHOLD,
    )
    assert before == after


def test_build_is_deterministic_under_v2():
    a = _build(ALL_ON)
    b = _build(ALL_ON)

    # The board and the integrity stamp; file-mtime freshness blocks of a
    # temporary tree legitimately differ between two builds.
    def strip(c):
        return json.dumps(
            {"rows": c["playersArray"], "integrity": c["sourceIntegrity"]},
            sort_keys=True,
            default=str,
        )

    assert strip(a) == strip(b)


def test_vote_coordinate_is_v1s():
    from src.api import outlier_policy as v1

    for value in (9999, 5000.0, 1234, 10):
        for cls in ("offense", "idp"):
            assert si.vote_coordinate(value, cls) == v1.rank_coordinate(value, v1.scope_curve(cls))
    assert si.vote_coordinate(0, "offense") is None
    assert si.vote_coordinate(None, "offense") is None
    assert math.isfinite(si.vote_coordinate(1, "offense"))


def test_a_valid_consistently_contrarian_source_keeps_its_votes():
    """§9 property 7: a source that disagrees (here fantasyCalc ranking the
    bottom half of the board 3x deeper, consistently) is opinion, not a fault —
    no A or B layer excludes it, with or without history."""
    csvs = _csvs(META)
    lines = csvs["fantasyCalc.csv"].splitlines()
    head, body = lines[0], lines[1:]
    out = []
    for ln in body:
        name, value, rank = ln.split(",")
        r = int(rank)
        new_r = r if r <= 50 else 50 + (r - 50) * 3
        out.append(f"{name},{9000 - new_r * 10},{new_r}")
    csvs["fantasyCalc.csv"] = "\n".join([head] + out) + "\n"
    first = _build(ALL_ON, csvs=csvs)
    assert first["sourceIntegrity"]["voteExclusions"] == {}
    history = _history_from(first)
    second = _build(ALL_ON, csvs=csvs, history=history)
    assert second["sourceIntegrity"]["voteExclusions"] == {}
    assert not [f for f in second["sourceIntegrity"]["findings"] if f["hard"]]


def test_named_residual_a_wrong_value_with_no_identity_or_format_signature_passes_a_and_b():
    """§9 property 6, asserted as the documented miss: a single wrong number
    that is well formatted, correctly attributed and has no history carries no
    A or B signature.  A and B do not fake a catch; whether it votes is Layer
    C's question."""
    csvs = _csvs(META)
    lines = csvs["fantasyCalc.csv"].splitlines()
    head, body = lines[0], lines[1:]
    # Off Vet 010 moved from rank 10 to the bottom, value kept consistent.
    body = [ln for ln in body if not ln.startswith("Off Vet 010,")] + ["Off Vet 010,1,999"]
    csvs["fantasyCalc.csv"] = "\n".join([head] + body) + "\n"
    on = _build(ALL_ON, csvs=csvs)
    meta = _rows(on)["Off Vet 010"]["sourceRankMeta"]["fantasyCalc"]
    # No A or B verdict: the observation reaches Layer C (which, since it is
    # now implemented, may set it aside as an extreme uncorroborated tail --
    # a rule category, never an identity / format / normalization fault).
    assert meta["integrity"]["status"] in (si.STATUS_VOTING, si.STATUS_REJECTED_TAIL)
    assert meta["integrity"]["category"] in (
        si.CATEGORY_VOTING,
        si.CATEGORY_DISSENT,
        si.CATEGORY_RULE,
    )


def test_decisions_do_not_depend_on_the_hash_seed():
    """§9 property 12: identical decisions across PYTHONHASHSEED values."""
    import subprocess
    import sys

    script = (
        "import json,hashlib,sys;sys.path.insert(0,'.');sys.path.insert(0,'tests/api');"
        "import test_source_integrity as t;"
        "c=t._build(t.ALL_ON, overrides={'ktcCrowdSfTep': {'include': False}});"
        "print(hashlib.sha256(json.dumps({'r':c['playersArray'],'i':c['sourceIntegrity']},"
        "sort_keys=True,default=str).encode()).hexdigest())"
    )
    root = Path(__file__).resolve().parents[2]
    digests = set()
    for seed in ("0", "1", "12345"):
        out = subprocess.run(
            [sys.executable, "-c", script],
            cwd=root,
            env={**os.environ, "PYTHONHASHSEED": seed},
            capture_output=True,
            text=True,
            check=True,
        )
        digests.add(out.stdout.strip().splitlines()[-1])
    assert len(digests) == 1


def test_a_parse_cached_while_off_is_reparsed_for_evidence_when_on(tmp_path):
    """The served (OFF) parse collects no evidence; turning V2 on in the same
    process must not silently grade joins with none."""
    d = tmp_path / "CSVs" / "site_raw"
    d.mkdir(parents=True)
    csvs = _csvs(META)
    lines = csvs["dynastyNerdsSfTep.csv"].splitlines()
    lines = [ln for ln in lines if not ln.startswith("Off Vet 002,")] + [
        "Off Vet 002,90,5500,,LB,CLE"
    ]
    csvs["dynastyNerdsSfTep.csv"] = "\n".join(lines) + "\n"
    for name, text in csvs.items():
        (d / name).write_text(text)
    with contextlib.redirect_stdout(io.StringIO()):
        dc.build_api_data_contract(json.loads(json.dumps(PAYLOAD)), csv_root=tmp_path)
        assert dc._source_csv_integrity_inputs(d / "dynastyNerdsSfTep.csv") is None
        with _flags(*ALL_ON):
            on = dc.build_api_data_contract(json.loads(json.dumps(PAYLOAD)), csv_root=tmp_path)
    stamp = _rows(on)["Off Vet 002"]["sourceIntegrity"]["dynastyNerdsSfTep"]
    assert stamp["primaryReason"] == "identity_contradicted:position_group"
