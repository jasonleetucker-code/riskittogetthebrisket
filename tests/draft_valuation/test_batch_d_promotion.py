"""Batch D — automated class readiness and policy-driven promotion (owner decision 12).

Mocked time throughout: every evaluation is given an explicit ``now``, every
record goes to a ``tmp_path`` store, and the real spine / frozen fallback are
read-only inputs.  Nothing here writes a tracked file (the runtime-data guard
watches the real Batch D stores).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.draft.rookie_auction import promotion as P
from src.draft.rookie_auction import published
from src.draft.rookie_auction.class_snapshot import (
    SnapshotRecordError,
    build_class_candidate,
    load_class_snapshot,
)
from src.draft.rookie_auction.ledger import LedgerRefusal, pre_draft_cutoff_from_sleeper
from src.draft.rookie_auction.snapshots import CONFIG_DIR, load_frozen_rookie_inputs
from src.identity.pick_lifecycle import evidence_from_sleeper

UTC = timezone.utc
T0 = datetime(2027, 5, 1, 0, 0, tzinfo=UTC)  # the preregistered 2027 window opening
STEP = timedelta(hours=6)  # the coarsest cadence that never resets the window (> 6 h does)
POLICY_SRC = CONFIG_DIR / "promotion_policy.json"
LEAGUE = "dynasty_main"
FROZEN_VALUES = sorted((float(v) for v in load_frozen_rookie_inputs().values), reverse=True)


def _evidence(status: str = "pre_draft", *, complete: bool = False):
    drafts = [
        {"draft_id": "d27", "season": "2027", "status": status, "settings": {"player_type": 1}}
    ]
    picks = {}
    rostered = []
    if complete:
        picks = {
            "d27": [{"player_id": f"r{i:03d}", "metadata": {"years_exp": 0}} for i in range(72)]
        }
        rostered = [f"r{i:03d}" for i in range(72)]
    return evidence_from_sleeper(
        league_key=LEAGUE,
        sleeper_league_id="L27",
        drafts=drafts,
        picks_by_draft_id=picks,
        rostered_player_ids=rostered,
        observed_at="2027-06-01T00:00:00+00:00",
        draft_lists_observed=["L27"],
    )


def _rows(values=None, *, ids=None, confidence="high", quarantined=False, overrides=None):
    values = list(values or FROZEN_VALUES)
    ids = list(ids or [f"r{i:03d}" for i in range(len(values))])
    rows = []
    for i, (pid, v) in enumerate(zip(ids, values)):
        row = {
            "playerId": pid,
            "canonicalName": f"Rookie {pid}",
            "position": "WR",
            "assetClass": "offense",
            "yearsExp": 0,
            "rankDerivedValue": v,
            "confidenceBucket": confidence,
            "quarantined": quarantined,
        }
        row.update((overrides or {}).get(i, {}))
        rows.append(row)
    return rows


def _contract(at, rows=None, *, ok=True, age_hours=1.0, health=True):
    c = {"playersArray": rows if rows is not None else _rows()}
    c["scrapeTimestamp"] = (at - timedelta(hours=age_hours)).isoformat()
    if health:
        c["contractHealth"] = {"ok": ok, "status": "ok" if ok else "invalid"}
    return c


class Harness:
    def __init__(self, tmp_path: Path, mode: str = P.MODE_DRY_RUN):
        self.store = tmp_path / "store"
        self.proot = tmp_path / "promotion"
        self.policy = tmp_path / "promotion_policy.json"
        tmp_path.mkdir(parents=True, exist_ok=True)
        pol = json.loads(POLICY_SRC.read_text("utf-8"))
        pol["promotionMode"] = mode  # outside the thresholds checksum by design
        self.policy.write_text(json.dumps(pol), "utf-8")

    def run(self, at, contract="default", *, evidence="default", **kw):
        if contract == "default":
            contract = _contract(at)
        return P.run_class_evaluation(
            league_key=LEAGUE,
            draft_year=2027,
            contract=contract,
            now=at,
            observed_nfl_season=2027,
            evidence=_evidence() if evidence == "default" else evidence,
            policy_path=self.policy,
            store_root=self.store,
            promotion_root=self.proot,
            **kw,
        )

    def series(self, start, end, contract_for=None, **kw):
        out, at = [], start
        while at <= end:
            out.append(self.run(at, contract_for(at) if contract_for else "default", **kw))
            at += STEP
        return out

    def transitions(self):
        d = self.store / "promotion_transitions" / LEAGUE / "2027"
        return sorted(d.glob("*.json")) if d.is_dir() else []

    def generation(self):
        return published.generation_state(LEAGUE, 2027, root=self.proot)

    def resolved(self, **kw):
        return published.resolve_published_allocation(
            LEAGUE,
            2027,
            store_dirs=[published.REPO_STORE],
            promotion_root=self.proot,
            persist=False,
            **kw,
        )


def _gate(outcome, name):
    return next(g for g in outcome.evaluation.gates if g.name == name)


# --- the policy -------------------------------------------------------------------


def test_policy_is_the_owner_approved_preregistration():
    pol = P.load_promotion_policy()
    assert pol.status == "OWNER_APPROVED_2026-10-18"
    assert pol.mode == P.MODE_DRY_RUN  # ships dry-run (decision 12 item 6)
    assert pol.nfl_draft_complete_on[2027].isoformat() == "2027-05-01"
    assert (pol.contract_max_age_hours, pol.confidence_top_picks) == (6, 24)
    assert pol.confidence_allowed == {"medium", "high"}
    assert (pol.stability_window_hours, pol.stability_max_gap_hours) == (24, 6)
    assert (pol.stability_pick_band_dollars, pol.stability_total_abs_change_dollars) == (3, 30)
    assert pol.review_slot_abs_dollars == 15 and str(pol.review_slot_relative) == "1/2"
    assert pol.review_first_round_picks == 12 and str(pol.review_first_round_relative) == "1/4"
    assert pol.promotable_hold_hours == 48 and pol.includes_first_switch
    doc = Path(__file__).resolve().parents[2] / "docs/draft/BATCH_D_PREREGISTRATION_2026-10-18.md"
    assert pol.thresholds_checksum in doc.read_text("utf-8")


def test_contract_age_reuses_the_repo_staleness_budget():
    from src.api.league_registry import SCORING_SNAPSHOT_MAX_AGE_HOURS

    assert P.load_promotion_policy().contract_max_age_hours == SCORING_SNAPSHOT_MAX_AGE_HOURS


def test_edited_threshold_is_refused(tmp_path):
    pol = json.loads(POLICY_SRC.read_text("utf-8"))
    pol["thresholds"]["stability"]["pickBandDollars"] = 4
    p = tmp_path / "p.json"
    p.write_text(json.dumps(pol), "utf-8")
    with pytest.raises(P.PolicyError, match="checksum"):
        P.load_promotion_policy(p)


def test_age_budget_drift_is_refused_even_when_rechecksummed(tmp_path):
    pol = json.loads(POLICY_SRC.read_text("utf-8"))
    pol["thresholds"]["sourceFreshness"]["contractMaxAgeHours"] = 7
    pol["thresholdsChecksum"]["value"] = P._sha_json(pol["thresholds"])
    p = tmp_path / "p.json"
    p.write_text(json.dumps(pol), "utf-8")
    with pytest.raises(P.PolicyError, match="staleness budget"):
        P.load_promotion_policy(p)


def test_unknown_mode_is_refused(tmp_path):
    pol = json.loads(POLICY_SRC.read_text("utf-8"))
    pol["promotionMode"] = "yes"
    p = tmp_path / "p.json"
    p.write_text(json.dumps(pol), "utf-8")
    with pytest.raises(P.PolicyError, match="promotionMode"):
        P.load_promotion_policy(p)


# --- time jump: fallback -> eligible 2027 ------------------------------------------


def test_time_jump_fallback_then_eligible(tmp_path):
    h = Harness(tmp_path)
    before = h.run(T0 - timedelta(minutes=1))
    assert before.evaluation.state == "FALLBACK_VERIFIED"
    assert "class_window_closed" in _gate(before, "class_window_open").detail
    assert before.evaluation_path is None  # nothing about a candidate is recorded
    assert before.evaluation.candidate_snapshot_sha256 is None  # no candidate built
    assert all(
        _gate(before, n).outcome == "NOT_EVALUATED"
        for n in ("source_freshness", "stability_vs_prior_generation")
    )
    at_open = h.run(T0)
    assert _gate(at_open, "class_window_open").outcome == "PASS"
    assert at_open.evaluation.state == "CANDIDATE_READY"
    assert _gate(at_open, "source_freshness").outcome == "PASS"
    assert _gate(at_open, "stability_vs_prior_generation").outcome == "FAIL"
    assert at_open.evaluation_path is not None and at_open.evaluation_path.exists()


def test_unconfigured_year_stays_fallback_with_reason(tmp_path):
    h = Harness(tmp_path)
    out = P.run_class_evaluation(
        league_key=LEAGUE,
        draft_year=2028,
        contract=_contract(T0),
        now=T0 + timedelta(days=400),
        observed_nfl_season=2028,
        evidence=None,
        policy_path=h.policy,
        store_root=h.store,
        promotion_root=h.proot,
    )
    assert out.evaluation.state == "FALLBACK_VERIFIED"
    assert "nfl_draft_completion_date_not_configured:2028" in _gate(out, "class_window_open").detail


def test_other_league_is_not_configured(tmp_path):
    h = Harness(tmp_path)
    out = P.run_class_evaluation(
        league_key="dynasty_new",
        draft_year=2027,
        contract=_contract(T0),
        now=T0,
        observed_nfl_season=2027,
        evidence=None,
        policy_path=h.policy,
        store_root=h.store,
        promotion_root=h.proot,
    )
    assert out.evaluation.state == "LEAGUE_NOT_CONFIGURED"


# --- each gate failing ------------------------------------------------------------


@pytest.mark.parametrize(
    "contract_kw, rows_kw, expect",
    [
        ({"ok": False}, {}, "contract_health_not_ok"),
        ({"health": False}, {}, "contract_health_unknown"),
        ({"age_hours": 6.5}, {}, "contract_stale"),
        ({"age_hours": -1}, {}, "contract_as_of_in_future"),
        ({}, {"quarantined": True}, "quarantined_or_unknown"),
        ({}, {"quarantined": None}, "quarantined_or_unknown"),
        ({}, {"confidence": "low"}, "confidence:"),
        ({}, {"confidence": None}, "confidence:"),
    ],
)
def test_source_freshness_failures(tmp_path, contract_kw, rows_kw, expect):
    h = Harness(tmp_path)
    out = h.run(T0, _contract(T0, _rows(**rows_kw), **contract_kw))
    gate = _gate(out, "source_freshness")
    assert gate.outcome == "FAIL" and expect in gate.detail
    assert out.evaluation.state == "CANDIDATE_READY"
    assert not out.evaluation.freshness_pass


def test_confidence_rule_covers_only_the_top_24(tmp_path):
    h = Harness(tmp_path)
    low_after_24 = _rows(overrides={i: {"confidenceBucket": "low"} for i in range(24, 72)})
    assert _gate(h.run(T0, _contract(T0, low_after_24)), "source_freshness").outcome == "PASS"
    low_at_24 = _rows(overrides={23: {"confidenceBucket": "low"}})
    assert (
        _gate(h.run(T0 + STEP, _contract(T0 + STEP, low_at_24)), "source_freshness").outcome
        == "FAIL"
    )


def test_contract_age_exactly_at_budget_passes(tmp_path):
    h = Harness(tmp_path)
    assert _gate(h.run(T0, _contract(T0, age_hours=6)), "source_freshness").outcome == "PASS"


def test_incomplete_candidate_and_missing_contract(tmp_path):
    h = Harness(tmp_path)
    short = h.run(T0, _contract(T0, _rows(FROZEN_VALUES[:71])))
    assert short.evaluation.state == "CANDIDATE_INCOMPLETE"
    missing = h.run(T0 + STEP, None, contract_error="build failed")
    assert missing.evaluation.state == "ERROR_CONTRACT_UNAVAILABLE"
    assert missing.evaluation_path is not None  # the failure is recorded (it breaks the window)


# --- the stability window ----------------------------------------------------------


def test_stability_passes_after_24_hours(tmp_path):
    h = Harness(tmp_path)
    runs = h.series(T0, T0 + timedelta(hours=24))
    assert [r.evaluation.state for r in runs[:-1]] == ["CANDIDATE_READY"] * 4
    assert runs[-1].evaluation.state == "PROMOTABLE"
    assert runs[-1].evaluation.stability["windowEvaluations"] == 5


def test_gap_over_six_hours_resets_the_window(tmp_path):
    h = Harness(tmp_path)
    h.series(T0, T0 + timedelta(hours=12))
    resumed = T0 + timedelta(hours=19)  # 7 h gap
    out = h.run(resumed)
    assert "reset the window" in _gate(out, "stability_vs_prior_generation").detail
    h.series(resumed + STEP, resumed + timedelta(hours=18))
    assert h.run(resumed + timedelta(hours=18, minutes=1)).evaluation.state == "CANDIDATE_READY"
    assert h.run(resumed + timedelta(hours=24)).evaluation.state == "PROMOTABLE"


def test_pick_band_breach_fails_stability(tmp_path):
    h = Harness(tmp_path)
    bumped = list(FROZEN_VALUES)
    bumped[0] = FROZEN_VALUES[0] * 1.6
    base_d = h.run(T0).evaluation.candidate_whole_dollars
    out_b = h.run(T0 + STEP, _contract(T0 + STEP, _rows(bumped)))
    assert abs(out_b.evaluation.candidate_whole_dollars[0] - base_d[0]) > 3  # precondition
    h.series(T0 + 2 * STEP, T0 + timedelta(hours=24))
    out = h.run(T0 + timedelta(hours=24, minutes=1))
    gate = _gate(out, "stability_vs_prior_generation")
    assert gate.outcome == "FAIL" and "+/-$3" in gate.detail


def test_identity_change_resets_stability(tmp_path):
    h = Harness(tmp_path)
    h.series(T0, T0 + timedelta(hours=12))
    ids = [f"r{i:03d}" for i in range(72)]
    ids[71] = "newcomer"
    swapped = lambda at: _contract(at, _rows(ids=ids))  # noqa: E731
    out = h.run(T0 + timedelta(hours=18), swapped(T0 + timedelta(hours=18)))
    assert "identity set changed" in _gate(out, "stability_vs_prior_generation").detail
    out = h.run(T0 + timedelta(hours=24), swapped(T0 + timedelta(hours=24)))
    assert out.evaluation.state == "CANDIDATE_READY"


def test_failed_freshness_breaks_the_run(tmp_path):
    h = Harness(tmp_path)
    h.series(T0, T0 + timedelta(hours=12))
    h.run(T0 + timedelta(hours=18), _contract(T0 + timedelta(hours=18), ok=False))
    out = h.run(T0 + timedelta(hours=24))
    assert "not ready and fresh" in _gate(out, "stability_vs_prior_generation").detail


def test_total_change_limit():
    pol = P.load_promotion_policy()
    base = tuple([20] * 60)  # length is irrelevant to the arithmetic
    pts = []
    for k in range(5):
        d = list(base)
        for j in range(k * 8):  # each step moves 8 more picks by $1 (within +/-$3)
            d[j] += 1 if j < 31 else 0
        pts.append(P._Point(T0 + k * STEP, True, "ids", tuple(d), "CANDIDATE_READY"))
    gate, info = P.stability_gate(pts[:-1], pts[-1], pol)
    assert info["totalAbsChange"] == 31 and gate.outcome == "FAIL"
    assert "total absolute change 31" in gate.detail


# --- the review band --------------------------------------------------------------


def test_review_band_slot_and_first_round():
    pol = P.load_promotion_policy()
    fb = [100] * 12 + [10] * 60
    ok = list(fb)
    ok[0] = 140  # within 50% of 100
    ok[20] = 24  # within $15 of 10
    assert P.review_band_gate(ok, fb, pol)[0].outcome == "PASS"
    slot = list(fb)
    slot[20] = 26  # > max(15, 5)
    assert P.review_band_gate(slot, fb, pol)[0].outcome == "FAIL"
    first = list(fb)
    for i in range(12):
        first[i] = 126  # each within 50%, total +26% > 25%
    gate, info = P.review_band_gate(first, fb, pol)
    assert gate.outcome == "FAIL" and info["firstRound"]["breach"]


def test_review_band_holds_promotion_and_alerts_once(tmp_path):
    h = Harness(tmp_path, mode=P.MODE_LIVE)
    skewed = list(FROZEN_VALUES)
    skewed[0] = FROZEN_VALUES[0] * 25
    runs = h.series(T0, T0 + timedelta(hours=96), lambda at: _contract(at, _rows(skewed)))
    assert runs[-1].evaluation.state == "VALIDATED_NEEDS_REVIEW"
    assert h.generation().active_checksum is None  # held: nothing switched
    review_alerts = [r for r in runs if r.alerts and "VALIDATED_NEEDS_REVIEW" in r.alerts[0]]
    assert len(review_alerts) == 1


# --- automatic promotion, dry run, rollback ----------------------------------------


def test_live_promotion_after_48_hours_promotable(tmp_path):
    h = Harness(tmp_path, mode=P.MODE_LIVE)
    fallback = h.resolved()
    runs = h.series(T0, T0 + timedelta(hours=66))
    assert all(r.evaluation.serving_state == "FALLBACK" for r in runs)
    held = runs[-1].evaluation.promotion
    assert held["decision"] == "hold" and any("of_48h" in x for x in held["holds"])
    out = h.run(T0 + timedelta(hours=72))
    assert out.evaluation.promotion["decision"] == "promoted"
    assert out.evaluation.state == out.evaluation.serving_state == "ACTIVE"
    gen = h.generation()
    assert gen.last_sequence == 1 and gen.active_checksum
    served = h.resolved()
    assert served.allocation_state == "current"
    assert list(served.final_whole_dollars) == list(out.evaluation.candidate_whole_dollars)
    assert sum(served.final_whole_dollars) == 1200
    assert any(n.startswith("promoted_generation:") for n in served.notes)
    assert served.receipt["provenance"]["source"] == "canonical_class_snapshot"
    assert fallback.notes == () or not any("promoted" in n for n in fallback.notes)
    # the generation's inputs are stored, create-only and verifiable
    snap = load_class_snapshot(json.loads(out.snapshot_path.read_text("utf-8")))
    assert snap.snapshot_sha256 == out.evaluation.candidate_snapshot_sha256
    # the 48 h clock restarts after a promotion
    drift = list(FROZEN_VALUES)
    drift[5] = FROZEN_VALUES[5] + 1.0
    nxt = h.run(T0 + timedelta(hours=78), _contract(T0 + timedelta(hours=78), _rows(drift)))
    assert nxt.evaluation.promotion["decision"] in ("hold", "already_active")
    assert h.generation().last_sequence == 1


def test_dry_run_never_switches(tmp_path):
    h = Harness(tmp_path, mode=P.MODE_DRY_RUN)
    runs = h.series(T0, T0 + timedelta(hours=96))
    assert runs[-1].evaluation.promotion["decision"] == "would_promote"
    assert all(r.evaluation.serving_state == "FALLBACK" for r in runs)
    assert not (h.proot / "promotion_pointers").exists()
    assert not (h.proot / "promoted_allocations").exists()
    assert h.generation().active_checksum is None
    would = [r for r in runs if r.alerts and "DRY RUN" in r.alerts[0]]
    assert len(would) == 1 and would[0].snapshot_path is not None
    assert "promoted_generation" not in " ".join(h.resolved().notes)


def test_no_persist_never_switches_even_live(tmp_path):
    h = Harness(tmp_path, mode=P.MODE_LIVE)
    h.series(T0, T0 + timedelta(hours=66))
    out = h.run(T0 + timedelta(hours=72), persist=False)
    assert out.evaluation.promotion["decision"] == "would_promote"
    assert h.generation().active_checksum is None


def test_rollback_restores_previous_generation_and_holds(tmp_path):
    h = Harness(tmp_path, mode=P.MODE_LIVE)
    h.series(T0, T0 + timedelta(hours=72))
    assert h.generation().active_checksum
    fallback_dollars = published.resolve_published_allocation(
        LEAGUE, 2027, store_dirs=[published.REPO_STORE], persist=False
    ).final_whole_dollars
    at = T0 + timedelta(hours=73)
    pointer, alerts = P.operator_rollback(
        LEAGUE, 2027, now=at, reason="test", store_root=h.store, promotion_root=h.proot
    )
    assert pointer["action"] == "rollback" and pointer["activeRecordChecksum"] is None
    assert len(alerts) == 1 and "ROLLED_BACK" in alerts[0]
    served = h.resolved()
    assert served.final_whole_dollars == fallback_dollars
    assert not any("promoted_generation:" in n for n in served.notes)
    # the next evaluations are held and do not re-alert
    later = h.series(T0 + timedelta(hours=78), T0 + timedelta(hours=150))
    assert all(r.evaluation.state == "ROLLED_BACK" for r in later)
    assert all("rolled_back:resume required" in r.evaluation.promotion["holds"] for r in later)
    assert not any(r.alerts for r in later)
    assert h.generation().active_checksum is None
    # nothing to roll back any more
    with pytest.raises(published.GenerationError):
        P.operator_rollback(
            LEAGUE, 2027, now=at, reason="again", store_root=h.store, promotion_root=h.proot
        )
    # resume restarts the 48 h clock
    P.operator_resume(
        LEAGUE,
        2027,
        now=T0 + timedelta(hours=151),
        reason="ok",
        store_root=h.store,
        promotion_root=h.proot,
    )
    nxt = h.run(T0 + timedelta(hours=156))
    assert nxt.evaluation.promotion["decision"] == "hold"
    assert h.generation().active_checksum is None


def test_rollback_to_an_earlier_promoted_generation(tmp_path):
    h = Harness(tmp_path, mode=P.MODE_LIVE)
    h.series(T0, T0 + timedelta(hours=72))
    first = h.generation().active_checksum
    drift = list(FROZEN_VALUES)
    drift[0] = FROZEN_VALUES[0] * 1.03  # moves pick 1 by +$3: inside the stability band
    h.series(
        T0 + timedelta(hours=78), T0 + timedelta(hours=126), lambda at: _contract(at, _rows(drift))
    )
    second = h.generation().active_checksum
    assert second and second != first
    P.operator_rollback(
        LEAGUE,
        2027,
        now=T0 + timedelta(hours=127),
        reason="t",
        store_root=h.store,
        promotion_root=h.proot,
    )
    assert h.generation().active_checksum == first
    assert h.resolved().record_checksum == first


# --- alerts, failures ---------------------------------------------------------------


def test_one_alert_per_transition_never_repeated(tmp_path):
    h = Harness(tmp_path)
    pre = [h.run(T0 - timedelta(days=d)) for d in (5, 4, 3, 2, 1)]
    assert sum(len(r.alerts) for r in pre) == 1 and len(h.transitions()) == 1
    runs = h.series(T0, T0 + timedelta(hours=96))
    states = [r.evaluation.transition_key() for r in runs]
    changes = sum(1 for a, b in zip(states, states[1:]) if a != b) + 1  # +1 entering the window
    assert sum(len(r.alerts) for r in runs) == changes
    assert len(h.transitions()) == 1 + changes


def test_every_failure_keeps_the_previous_generation(tmp_path, monkeypatch):
    h = Harness(tmp_path, mode=P.MODE_LIVE)
    h.series(T0, T0 + timedelta(hours=72))
    active = h.generation().active_checksum
    assert active
    at = T0 + timedelta(hours=78)
    assert h.run(at, None, contract_error="boom").evaluation.state == "ERROR_CONTRACT_UNAVAILABLE"
    assert h.run(at + STEP, _contract(at + STEP, ok=False)).evaluation.serving_state == "ACTIVE"
    bad = Harness(tmp_path)  # same stores, broken policy
    bad.store, bad.proot = h.store, h.proot
    bad.policy.write_text("{}", "utf-8")
    assert bad.run(at + 2 * STEP).evaluation.state == "ERROR_POLICY_INVALID"
    assert h.generation().active_checksum == active
    assert h.resolved().record_checksum == active


def test_publish_failure_keeps_the_fallback(tmp_path, monkeypatch):
    h = Harness(tmp_path, mode=P.MODE_LIVE)
    h.series(T0, T0 + timedelta(hours=66))

    def boom(*a, **k):
        raise published.GenerationError("disk full")

    monkeypatch.setattr(published, "publish_promoted_generation", boom)
    out = h.run(T0 + timedelta(hours=72))
    assert out.evaluation.state == "ERROR_PUBLISH_FAILED"
    assert out.evaluation.serving_state == "FALLBACK"
    assert h.generation().active_checksum is None


def test_draft_in_progress_holds_promotion(tmp_path):
    h = Harness(tmp_path, mode=P.MODE_LIVE)
    runs = h.series(T0, T0 + timedelta(hours=96), evidence=_evidence("drafting"))
    assert runs[-1].evaluation.promotion["decision"] == "hold"
    assert any("draft_started_or_unknown" in x for x in runs[-1].evaluation.promotion["holds"])
    assert h.generation().active_checksum is None
    unobserved = Harness(tmp_path / "u", mode=P.MODE_LIVE)
    runs = unobserved.series(T0, T0 + timedelta(hours=96), evidence=None)
    assert any("draft_status_unobserved" in x for x in runs[-1].evaluation.promotion["holds"])


def test_edited_records_are_refused(tmp_path):
    h = Harness(tmp_path, mode=P.MODE_LIVE)
    h.series(T0, T0 + timedelta(hours=72))
    ptr = h.proot / "promotion_pointers" / LEAGUE / "2027" / "000001.json"
    data = json.loads(ptr.read_text("utf-8"))
    data["reason"] = "edited"
    ptr.chmod(0o644)
    ptr.write_text(json.dumps(data), "utf-8")
    served = h.resolved()
    assert any(n.startswith("promotion_pointer_unreadable") for n in served.notes)
    assert served.allocation_state == "current"  # the verified default, never zero
    out = h.run(T0 + timedelta(hours=78))
    assert out.evaluation.state == "ERROR_STORE_INVALID"


def test_edited_evaluation_log_is_an_error_not_a_pass(tmp_path):
    h = Harness(tmp_path)
    first = h.run(T0)
    rec = json.loads(first.evaluation_path.read_text("utf-8"))
    rec["freshnessPass"] = False
    first.evaluation_path.write_text(json.dumps(rec), "utf-8")
    assert h.run(T0 + STEP).evaluation.state == "ERROR_STORE_INVALID"


# --- served values ------------------------------------------------------------------


def test_no_pointer_resolution_is_unchanged(tmp_path):
    empty = tmp_path / "empty"
    a = published.resolve_published_allocation(
        LEAGUE, 2027, store_dirs=[published.REPO_STORE], persist=False
    ).to_dict()
    b = published.resolve_published_allocation(
        LEAGUE, 2027, store_dirs=[published.REPO_STORE], promotion_root=empty, persist=False
    ).to_dict()
    assert a == b and a["allocationState"] == "current" and a["totalDollars"] == 1200


def test_default_resolution_reads_the_redirected_promotion_root(tmp_path):
    # Under the suite, PROMOTION_ROOT is a fresh empty directory, never the real store.
    assert published.PROMOTION_ROOT != CONFIG_DIR
    assert not (published.PROMOTION_ROOT / "promotion_pointers").exists()


# --- class snapshot records -----------------------------------------------------------


def test_class_snapshot_round_trip_and_edit_refusal():
    snap = build_class_candidate(
        _contract(T0),
        target_draft_year=2027,
        league_key=LEAGUE,
        observed_nfl_season=2027,
        as_of=T0.isoformat(),
    )
    d = snap.to_dict()
    assert load_class_snapshot(d).snapshot_sha256 == snap.snapshot_sha256
    d["entries"][0]["value"] = "1"
    with pytest.raises(SnapshotRecordError):
        load_class_snapshot(d)


# --- the ledger's pre-draft cutoff (decision 12 item 8) -------------------------------


def test_cutoff_comes_from_sleeper_start_time():
    ev = _evidence("complete", complete=True)
    calls = []

    def fetch(url):
        calls.append(url)
        return {"draft_id": "d27", "start_time": 1780000000000}

    cutoff = pre_draft_cutoff_from_sleeper(ev, 2027, fetch=fetch)
    assert calls == ["https://api.sleeper.app/v1/draft/d27"]
    assert cutoff == datetime.fromtimestamp(1780000000, tz=UTC).isoformat()


@pytest.mark.parametrize(
    "payload", [{}, {"start_time": None}, {"start_time": 0}, None, {"start_time": True}]
)
def test_unknown_start_time_refuses(payload):
    with pytest.raises(LedgerRefusal) as exc:
        pre_draft_cutoff_from_sleeper(
            _evidence("complete", complete=True), 2027, fetch=lambda u: payload
        )
    assert exc.value.reason == "pre_draft_cutoff_unknown"


def test_cutoff_refuses_an_incomplete_class():
    with pytest.raises(LedgerRefusal) as exc:
        pre_draft_cutoff_from_sleeper(
            _evidence("drafting"), 2027, fetch=lambda u: {"start_time": 1}
        )
    assert exc.value.reason == "class_not_verified_complete"


def test_finalize_step_dry_run_writes_nothing(tmp_path):
    cfg = tmp_path / "cfg"
    import shutil

    shutil.copytree(CONFIG_DIR / "historical_curves", cfg / "historical_curves")
    shutil.copytree(CONFIG_DIR / "frozen_inputs", cfg / "frozen_inputs")
    out = P.finalize_completed_class_step(
        league_key=LEAGUE,
        draft_class=2027,
        evidence=_evidence("complete", complete=True),
        live=False,
        store_root=tmp_path / "store",
        config_dir=cfg,
        promotion_root=tmp_path / "promo",
        fetch=lambda u: {"start_time": 1780000000000},
    )
    assert out["status"] == "would_finalize"
    assert out["inputs"]["mode"] == "frozen_fallback"  # no generation was serving
    assert not (cfg / "historical_curves" / LEAGUE / "2027.json").exists()
    assert (
        P.finalize_completed_class_step(
            league_key=LEAGUE,
            draft_class=2027,
            evidence=_evidence("drafting"),
            live=True,
            store_root=tmp_path / "store",
            config_dir=cfg,
            promotion_root=tmp_path / "promo",
        )["status"]
        == "not_complete"
    )


# --- the diagnostic -------------------------------------------------------------------


def test_diagnostic_reports_state_gates_and_window(tmp_path):
    h = Harness(tmp_path)
    h.series(T0, T0 + timedelta(hours=24))
    d = P.diagnose(
        LEAGUE,
        2027,
        now=T0 + timedelta(hours=25),
        policy_path=h.policy,
        store_root=h.store,
        promotion_root=h.proot,
    )
    assert d["latest"]["state"] == "PROMOTABLE"
    assert d["window"]["windowEvaluations"] == 5
    assert d["classWindow"]["outcome"] == "PASS"
    assert d["transitions"] and d["generation"]["activeRecordChecksum"] is None
