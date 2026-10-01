"""Joint robust-filter shadow ledger (Batch 3 Unit F).

Pins: the ledger is append-only and idempotent per board identity; the
incumbent shadow build IS the default board (flag off changes nothing);
disagreement extraction is correct on a synthetic board; the leave-family-out
target cannot see the disputed family; the outcome arithmetic matches the
preregistration; constructed adversarial rows exercise BOTH safeguards; and the
box timer is wired with a write scope that exists at start.
"""

from __future__ import annotations

import json
import math
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.robust_filter_shadow import adversarial as A
from src.robust_filter_shadow import ledger as L
from src.robust_filter_shadow import outcomes as O
from src.robust_filter_shadow import record as R

REPO = Path(__file__).resolve().parents[2]
SYSTEMD = REPO / "deploy" / "systemd"


# ── synthetic boards ────────────────────────────────────────────────────


def _meta(value: float, weight: float = 1.0, **extra) -> dict:
    return {"valueContribution": value, "appliedWeight": weight, **extra}


def _row(name, metas, *, dropped=(), reasons=None, value=5000, rank=1, cls="offense"):
    row = {
        "displayName": name,
        "assetClass": cls,
        "position": "WR",
        "sourceRankMeta": metas,
        "droppedSources": list(dropped),
        "rankDerivedValue": value,
        "canonicalConsensusRank": rank,
    }
    if reasons:
        row["jointFilterReasons"] = reasons
    return row


# Real registry keys so families resolve: dlf, fantasyPros, fantasyCalc,
# dynastyDaddySf, ktcCrowd (ktcCrowdSfTep + fantasyNavigatorSf).
FIVE = {
    "dlfSf": 5000,
    "fantasyProsSf": 5100,
    "fantasyCalc": 4900,
    "dynastyDaddySf": 5050,
    "ktcCrowdSfTep": 9000,
}


def _synthetic_pair():
    metas = {s: _meta(v) for s, v in FIVE.items()}
    inc = {
        "playersArray": [
            # incumbent drops ktcCrowd, challenger keeps it (K)
            _row("Alpha", metas, dropped=["ktcCrowdSfTep"], value=5000, rank=1),
            # both drop the same observation (agreed outlier, not a disagreement row)
            _row("Bravo", metas, dropped=["ktcCrowdSfTep"], value=4000, rank=2),
            # nobody drops anything
            _row("Charlie", metas, value=3000, rank=3),
            # a pick never enters the filter
            _row("2027 Early 1st", metas, value=2500, rank=4, cls="pick"),
        ]
    }
    ch = {
        "playersArray": [
            _row(
                "Alpha",
                metas,
                dropped=["fantasyCalc"],
                reasons={"fantasyCalc": "outlier", "ktcCrowdSfTep": "dominant_evidence_kept"},
                value=5600,
                rank=1,
            ),
            _row("Bravo", metas, dropped=["ktcCrowdSfTep"], value=4000, rank=2),
            _row("Charlie", metas, value=3000, rank=3),
            _row("2027 Early 1st", metas, value=2500, rank=4, cls="pick"),
        ]
    }
    return inc, ch


def test_disagreement_extraction_on_a_synthetic_board():
    inc, ch = _synthetic_pair()
    rec = R.shadow_record(inc, ch)
    counts = rec["counts"]
    assert counts["rows"] == 4
    assert counts["filterRows"] == 3  # the pick is not a filter row
    assert counts["rowsDisagree"] == 1
    assert counts["obsIncumbentOnlyDrop"] == 1
    assert counts["obsChallengerOnlyDrop"] == 1
    assert counts["rowsValueChanged"] == 1
    assert rec["safeguardsFired"] == {"dominant_evidence_kept": 1, "kept_to_avoid_single_family": 0}
    assert [r["name"] for r in rec["rows"]] == ["Alpha"]
    obs = {o["source"]: o for o in rec["rows"][0]["obs"]}
    assert (obs["ktcCrowdSfTep"]["incumbent"], obs["ktcCrowdSfTep"]["challenger"]) == (
        "drop",
        "keep",
    )
    assert (obs["fantasyCalc"]["incumbent"], obs["fantasyCalc"]["challenger"]) == ("keep", "drop")
    assert obs["ktcCrowdSfTep"]["family"] == "ktcCrowd"
    assert rec["agreedDrops"] == [["Bravo", "ktcCrowdSfTep", "offense"]]
    alpha = rec["rows"][0]
    assert (alpha["valueIncumbent"], alpha["valueChallenger"]) == (5000, 5600)


def test_excluded_observations_are_not_votes():
    metas = {"dlfSf": _meta(5000), "fantasyCalc": _meta(4000, 0.0, excludedReason="x")}
    assert R.voting_observations({"sourceRankMeta": metas}) == {"dlfSf": 5000.0}


def test_precap_weight_prefers_the_pre_family_weight():
    assert R.precap_weight({"appliedWeight": 0.5, "preFamilyWeight": 0.8}) == 0.8
    assert R.precap_weight({"appliedWeight": 0.5}) == 0.5


def test_challenger_weights_cap_correlated_members():
    obs = {"ktcCrowdSfTep": 5000.0, "fantasyNavigatorSf": 5100.0, "dlfSf": 4900.0}
    meta = {s: {"appliedWeight": 1.0} for s in obs}
    pre, capped = R.challenger_weights(obs, meta)
    assert pre == {s: 1.0 for s in obs}
    assert capped["ktcCrowdSfTep"] + capped["fantasyNavigatorSf"] == pytest.approx(1.0)
    assert capped["dlfSf"] == 1.0


# ── ledger: append-only, idempotent per board identity ──────────────────


def _record(payload_sha="a" * 64, code="c" * 40):
    return R.assemble_record(
        mode=R.MODE_REPLAY,
        board={"payloadSha256": payload_sha, "scrapeTimestamp": "2026-09-30T13:04:04"},
        pins={"codeRevision": code, "pipelineFingerprint": "f" * 64},
        comparison={"counts": {}, "rows": []},
        recorded_at="2026-10-01T00:00:00Z",
    )


def test_ledger_appends_once_per_board_identity(tmp_path):
    path = tmp_path / "ledger.jsonl"
    first = _record()
    assert L.append_record(path, first) is True
    before = path.read_bytes()
    # Same identity, different recording time: a no-op, nothing rewritten.
    again = {**_record(), "recordedAt": "2026-10-02T00:00:00Z"}
    assert again["key"] == first["key"]
    assert L.append_record(path, again) is False
    assert path.read_bytes() == before
    # A different board appends AFTER the existing bytes, which stay intact.
    other = _record(payload_sha="b" * 64)
    assert L.append_record(path, other) is True
    assert path.read_bytes().startswith(before)
    assert [r["key"] for r in L.iter_records(path)] == [first["key"], other["key"]]


def test_ledger_key_changes_with_code_revision(tmp_path):
    assert _record(code="1" * 40)["key"] != _record(code="2" * 40)["key"]


def test_a_torn_last_line_is_skipped_and_never_rewritten(tmp_path):
    path = tmp_path / "ledger.jsonl"
    L.append_record(path, _record())
    with path.open("a", encoding="utf-8") as fh:
        fh.write('{"key": "torn"')  # crash mid-append
    torn = path.read_bytes()
    assert L.append_record(path, _record(payload_sha="d" * 64)) is True
    assert path.read_bytes().startswith(torn)
    assert len(list(L.iter_records(path))) == 2


def test_panels_are_write_once(tmp_path):
    panel = {"rows": {"Alpha": {"c": "offense", "o": {"dlfSf": 5000}}}}
    p1, written = L.write_panel(tmp_path, "a" * 64, "f" * 64, panel)
    assert written
    p2, written_again = L.write_panel(tmp_path, "a" * 64, "f" * 64, panel)
    assert (p2, written_again) == (p1, False)
    assert L.read_panel(p1) == panel
    with pytest.raises(L.PanelConflict):
        L.write_panel(tmp_path, "a" * 64, "f" * 64, {"rows": {}})


# ── the incumbent shadow build IS the served board ──────────────────────


def test_flag_off_shadow_build_is_the_default_board():
    from src.api import feature_flags
    from src.api import value_replay as vr
    from tests.archive_fixtures import newest_complete_raw_payload

    raw, name = newest_complete_raw_payload()
    if raw is None:
        pytest.skip("no complete archived scrape")
    assert feature_flags.snapshot().get(R.CHALLENGER_FLAG) is False
    assert feature_flags.snapshot().get(R.SPARSE_FLAG) is False
    default = vr.build(raw)
    incumbent, challenger = R.build_pair(raw)
    assert vr.board_hash(incumbent) == vr.board_hash(default), name
    # Votes are pre-filter, so the panel is the same from either build.
    assert R.observation_panel(incumbent) == R.observation_panel(challenger)


# ── leave-family-out targets ────────────────────────────────────────────


def _fam(source: str) -> str:
    return {"a1": "A", "a2": "A", "b": "B", "c": "C", "d": "D"}.get(source, source)


def test_leave_family_out_target_cannot_see_the_excluded_family():
    obs = {"a1": 9000.0, "a2": 8000.0, "b": 3000.0, "c": 3100.0, "d": 3200.0}
    base = O.leave_family_out(obs, {"A"}, _fam)
    moved = O.leave_family_out({**obs, "a1": 1.0, "a2": 50.0}, {"A"}, _fam)
    assert base == moved == pytest.approx(math.log(3100.0))


def test_leave_family_out_counts_each_family_once():
    # Family A has three agreeing members; it is ONE vote, not three.
    obs = {"a1": 9000.0, "a2": 9000.0, "x_a3": 9000.0, "b": 3000.0, "c": 3000.0}
    fam = lambda s: "A" if s.startswith(("a", "x_a")) else s  # noqa: E731
    assert O.leave_family_out(obs, set(), fam) == pytest.approx(math.log(3000.0))


def test_leave_family_out_needs_two_families():
    assert O.leave_family_out({"a1": 1.0, "b": 2.0}, {"A"}, _fam) is None


# ── outcome arithmetic (preregistration §4) ─────────────────────────────


def _board(day: date, record: dict, rows: dict) -> O.Board:
    at = datetime(day.year, day.month, day.day, 12, tzinfo=timezone.utc)
    rec = {"board": {"completeness": "complete"}, "pins": {"pipelineFingerprint": "f"}, **record}
    return O.Board(record=rec, panel={"rows": rows}, at=at)


def test_lead_share_retreat_share_and_delisting():
    d0 = date(2026, 9, 1)
    origin_votes = {"a1": 6000, "b": 3000, "c": 3000, "d": 3000}
    rows0 = {"P": {"c": "offense", "o": origin_votes}, "Q": {"c": "offense", "o": origin_votes}}
    record = {
        "rows": [
            {
                "name": "P",
                "filterRow": True,
                "assetClass": "offense",
                "valueIncumbent": 3000,
                "valueChallenger": 4000,
                "obs": [{"source": "a1", "incumbent": "drop", "challenger": "keep"}],
            },
            {
                "name": "Q",
                "filterRow": True,
                "assetClass": "offense",
                "valueIncumbent": 3000,
                "valueChallenger": 4000,
                "obs": [{"source": "a1", "incumbent": "keep", "challenger": "drop"}],
            },
        ]
    }
    # P: the independent consensus moves all the way to 6000 -> m = 1 (LED).
    # Q: the consensus stays, and a1 itself retreats to 3000 -> m = 0, r = 1
    #    (ABANDONED).
    rows7 = {
        "P": {"c": "offense", "o": {"a1": 6000, "b": 6000, "c": 6000, "d": 6000}},
        "Q": {"c": "offense", "o": {"a1": 3000, "b": 3000, "c": 3000, "d": 3000}},
    }
    by_day = {
        d0: _board(d0, record, rows0),
        d0 + timedelta(days=7): _board(d0 + timedelta(days=7), {}, rows7),
    }
    out = O.outcomes_at_horizon(by_day, 7, _fam, first_day=d0)
    by_name = {u.name: u for u in out["observations"]}
    assert by_name["P"].side == O.SIDE_RESCUED and by_name["P"].m == pytest.approx(1.0)
    assert by_name["P"].outcome_class == "LED"
    assert by_name["Q"].side == O.SIDE_REJECTED and by_name["Q"].m == pytest.approx(0.0)
    assert by_name["Q"].r == pytest.approx(1.0) and by_name["Q"].outcome_class == "ABANDONED"
    # G1: P's challenger value (4000) is closer to the later consensus (6000);
    # Q's (4000) is further from its later consensus (3000).
    g1 = {u.name: u.g1 for u in out["rows"]}
    assert g1["P"] < 0 < g1["Q"]
    # Delisted: the source no longer lists the player -> no retreat share, never 0.
    rows7_delisted = {
        "P": {"c": "offense", "o": {"b": 6000, "c": 6000, "d": 6000}},
        "Q": rows7["Q"],
    }
    by_day[d0 + timedelta(days=7)] = _board(d0 + timedelta(days=7), {}, rows7_delisted)
    out = O.outcomes_at_horizon(by_day, 7, _fam, first_day=d0)
    p = next(u for u in out["observations"] if u.name == "P")
    assert p.delisted and p.r is None


def test_target_is_never_earlier_than_the_horizon():
    days = [date(2026, 9, 1) + timedelta(days=i) for i in (0, 6, 9)]
    assert O.target_day(days[0], 7, days) is None  # day 6 is early; day 9 too late (h=7 allows +1)
    assert O.target_day(days[0], 7, days + [date(2026, 9, 9)]) == date(2026, 9, 9)


def test_block_bootstrap_is_deterministic():
    units = [(i % 5, float(i)) for i in range(50)]
    stat = lambda us: sum(v for _b, v in us) / len(us)  # noqa: E731
    a = O.block_bootstrap(units, stat, block_of=lambda u: u[0], resamples=200)
    b = O.block_bootstrap(units, stat, block_of=lambda u: u[0], resamples=200)
    assert a == b and a["lo"] <= a["point"] <= a["hi"]


def _summary(delta, g1, n=40, days=12, blocks=5):
    side = {"n": n}
    return {
        "sides": {O.SIDE_RESCUED: side, O.SIDE_REJECTED: side},
        "delta": {"point": sum(delta) / 2, "lo95": delta[0], "hi95": delta[1]},
        "g1": {"point": sum(g1) / 2, "lo95": g1[0], "hi95": g1[1]},
        "originDays": days,
        "blocks": blocks,
    }


def test_decision_rule_matches_the_preregistration():
    pos = {h: {"delta": {"point": 0.1}} for h in O.SECONDARY_HORIZONS}
    assert O.decide(_summary((0.05, 0.3), (-0.02, 0.004)), pos)["verdict"] == O.VERDICT_ELIGIBLE
    # Fails non-inferiority by a hair -> not eligible.
    assert O.decide(_summary((0.05, 0.3), (-0.02, 0.006)), pos)["verdict"] == O.VERDICT_INCONCLUSIVE
    assert O.decide(_summary((-0.3, -0.05), (-0.02, 0.0)), pos)["verdict"] == O.VERDICT_NOT_BETTER
    assert O.decide(_summary((-0.1, 0.2), (0.001, 0.02)), pos)["verdict"] == O.VERDICT_NOT_BETTER
    assert O.decide(_summary((-0.1, 0.2), (-0.01, 0.0)), pos)["verdict"] == O.VERDICT_INCONCLUSIVE
    assert (
        O.decide(_summary((0.05, 0.3), (-0.02, 0.0), n=29), pos)["verdict"]
        == O.VERDICT_INSUFFICIENT
    )
    assert (
        O.decide(_summary((0.05, 0.3), (-0.02, 0.0), blocks=3), pos)["verdict"]
        == O.VERDICT_INSUFFICIENT
    )


# ── adversarial rows exercise both safeguards ───────────────────────────


def _real_like_rows(levels=(3100.0, 3500.0, 4200.0)):
    """Rows shaped like ``adversarial.real_rows`` output, with real source keys."""
    sources = [
        "dlfSf",
        "fantasyProsSf",
        "fantasyCalc",
        "dynastyDaddySf",
        "pfkDynasty",
        "ktcCrowdSfTep",
        "fantasyNavigatorSf",
    ]
    rows = []
    for i, level in enumerate(levels):
        obs = {s: level * (1 + 0.01 * j) for j, s in enumerate(sources)}
        rows.append(
            {
                "name": f"Row{i}",
                "assetClass": "offense",
                "rank": i + 1,
                "obs": obs,
                "weights": {s: 1.0 for s in obs},
                "families": {s: R.dc.correlation_group_for(s) for s in obs},
            }
        )
    return rows


def test_trap_keeps_the_fresh_evidence_and_fires_the_single_family_guard():
    result = A.case_a1_trap(_real_like_rows())
    assert result["rows"] == 3 and result["expectedHeld"] == 3
    assert result["safeguardsFired"]["kept_to_avoid_single_family"] >= 3
    # The incumbent drops the fresh evidence in the trap -- the defect.
    assert result["descriptive"]["incumbentDropsFresh"] == 3
    # The fresh 4600 is protected by the weighted centre, not by a rule.
    assert {r["freshProtectedBy"] for r in result["examples"]} == {"weighted_centre"}


def test_stale_cluster_and_dominant_broken_are_kept_by_design():
    rows = _real_like_rows()
    a2 = A.case_a2_stale_cluster(rows)
    assert a2["rows"] and a2["expectedHeld"] == a2["rows"]
    assert a2["safeguardsFired"]["kept_to_avoid_single_family"] > 0
    a4b = A.case_a4b_dominant_broken(rows)
    assert a4b["rows"] and a4b["expectedHeld"] == a4b["rows"]


def test_both_safeguard_branches_are_live_and_dominant_never_fires_at_production_k():
    probe = A.dominant_safeguard_reachability(trials=3000)
    production = probe["productionK"]["reasons"]
    diagnostic = probe["diagnosticK"]["reasons"]
    # kept_to_avoid_single_family decides real cases at the production k ...
    assert production["kept_to_avoid_single_family"] > 0
    # ... dominant_evidence_kept is reachable code (k < 1) but never fires at
    # k = 2.75: the weighted centre already protects dominant evidence.
    assert diagnostic["dominant_evidence_kept"] > 0
    assert production["dominant_evidence_kept"] == 0


def test_correlated_members_cannot_outvote_independent_families():
    rows = _real_like_rows()
    a3 = A.case_a3_correlated_family(rows)
    assert a3["rows"] and a3["expectedHeld"] == a3["rows"]


def test_low_weight_broken_scale_is_dropped():
    a4 = A.case_a4_broken_scale(_real_like_rows((600.0, 900.0, 1500.0)), 5.0)
    assert a4["rows"] and a4["expectedHeld"] == a4["rows"]


# ── CLI completeness rule == the fixture's rule ─────────────────────────


def test_cli_completeness_rule_matches_the_archive_fixture():
    import zipfile

    from scripts import joint_filter_shadow as jfs
    from tests.archive_fixtures import ARCHIVE, _degraded_critical_sources

    archives = sorted(ARCHIVE.glob("dynasty_export_*.zip"))
    if not archives:
        pytest.skip("no archive")
    for path in archives[:: max(1, len(archives) // 12)]:
        with zipfile.ZipFile(path) as zf:
            name = next(
                n for n in zf.namelist() if n.startswith("dynasty_data_") and n.endswith(".json")
            )
            payload = json.loads(zf.read(name))
        assert jfs._degraded(payload) == sorted(set(_degraded_critical_sources(payload))), path.name


# ── box timer wiring ────────────────────────────────────────────────────


def test_timer_templates_are_wired_with_an_existing_write_scope():
    service = (SYSTEMD / "dynasty-joint-filter-shadow.service.template").read_text(encoding="utf-8")
    timer = (SYSTEMD / "dynasty-joint-filter-shadow.timer.template").read_text(encoding="utf-8")
    assert re.search(r"^ReadWritePaths=__APP_DIR__/data$", service, re.M)
    assert re.search(r"^User=__APP_USER__$", service, re.M)
    assert re.search(r"^ProtectSystem=strict$", service, re.M)
    assert "scripts/joint_filter_shadow.py record --then-evaluate" in service
    assert (REPO / "scripts" / "joint_filter_shadow.py").is_file()
    oncal = [line for line in timer.splitlines() if line.startswith("OnCalendar=")]
    assert oncal and all(line.rstrip().endswith("UTC") for line in oncal)
    assert "Unit=__SERVICE_NAME__-joint-filter-shadow.service" in timer
    installer = (REPO / "deploy" / "install-systemd-service.sh").read_text(encoding="utf-8")
    assert 'install_simple_timer "joint-filter-shadow"' in installer
    readme = (SYSTEMD / "README.md").read_text(encoding="utf-8")
    assert "`dynasty-joint-filter-shadow.*`" in readme


def test_the_timer_never_runs_a_promotion_path():
    service = (SYSTEMD / "dynasty-joint-filter-shadow.service.template").read_text(encoding="utf-8")
    exec_lines = [line for line in service.splitlines() if line.startswith("ExecStart")]
    assert len(exec_lines) == 1
    assert "model_registry" not in exec_lines[0] and "promote" not in exec_lines[0]
