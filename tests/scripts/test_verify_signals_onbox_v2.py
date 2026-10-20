"""The hardened on-box Signals verifier (preregistration signals-idp-v2-2026-10-19).

Runs only on the production host for real (workflow
``signals-onbox-verification.yml``).  These tests drive every v2 mode end to
end on a SYNTHETIC box — the synthetic Signals fixture of
``tests/api/test_signals_active_source.py`` plus synthetic release JSONs — so
the frozen tree, the per-variant subprocess builds, the D1 quarantine, the
fail-closed flag reads, the verdicts and the privacy layer are exercised
without any private data.  Every value here is synthetic.
"""

from __future__ import annotations

import gzip
import hashlib
import importlib.util
import json
import os
import re
import stat
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tests" / "api"))

import test_signals_active_source as fixture  # noqa: E402

EVIDENCE = REPO / "docs" / "valuation" / "evidence" / "signals-idp-v2-2026-10-19"
WORKFLOW = REPO / ".github" / "workflows" / "signals-onbox-verification.yml"


def _load_script():
    spec = importlib.util.spec_from_file_location(
        "verify_signals_onbox_v2_under_test", REPO / "scripts" / "verify_signals_onbox.py"
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


MOD = _load_script()
PIN = MOD.GATES["d1"]["idpReleasePin"]


# ── a synthetic box ───────────────────────────────────────────────────────


def _synthetic_release(sha_prefix: str, as_of: str, *, shift: int = 0) -> tuple[dict, bytes]:
    """A synthetic IDP release in the collector's shape, plus its raw blob
    (``data.composite`` strictly monotone with ``value``)."""
    from src.sources import signals as S

    _off, idp = fixture._signals_observations()
    if shift:
        # Swap neighbouring values WITHIN each family so ranks change.
        idp = [dict(o) for o in idp]
        by_family: dict[str, list[dict]] = {}
        for o in idp:
            if o.get("nativeValue"):
                by_family.setdefault(o["position"], []).append(o)
        for group in by_family.values():
            for i in range(0, len(group) - 1, shift):
                a, b = group[i], group[i + 1]
                a["nativeValue"], b["nativeValue"] = b["nativeValue"], a["nativeValue"]
    rows, _excluded = S.build_board_rows(idp, S.VALUE_DATASETS["idp"])
    raw_items = [
        {
            "sleeperPlayerId": o["sleeperId"],
            "value": o["nativeValue"],
            "family": o["position"],
            "data": json.dumps({"composite": (o["nativeValue"] or 0) / 100.0}),
        }
        for o in idp
        if o.get("nativeValue")
    ]
    raw_blob = json.dumps([{"items": raw_items}], sort_keys=True).encode("utf-8")
    raw_sha = hashlib.sha256(raw_blob).hexdigest()
    release = {
        "contentSha256": sha_prefix + "0" * (64 - len(sha_prefix)),
        "asOf": as_of,
        "rawSha256": raw_sha,
        "observations": idp,
        "boardRows": rows,
    }
    return release, raw_blob


def _write_release(root: Path, release: dict, raw_blob: bytes, *, latest: bool = False) -> None:
    base = root / "data" / "sources" / "signals" / "values" / "idp"
    (base / "releases").mkdir(parents=True, exist_ok=True)
    (base / "raw").mkdir(parents=True, exist_ok=True)
    (base / "releases" / f"{release['contentSha256']}.json").write_text(
        json.dumps(release), encoding="utf-8"
    )
    (base / "raw" / f"{release['rawSha256']}.json.gz").write_bytes(gzip.compress(raw_blob))
    if latest:
        (base / "latest.json").write_text(json.dumps(release), encoding="utf-8")


def _make_box(root: Path, *, with_pin: bool = True) -> Path:
    fixture._write_store(root)
    (root / "data" / "dynasty_data_2026-10-03.json").write_text(
        json.dumps(fixture._raw_payload()), encoding="utf-8"
    )
    if with_pin:
        rel, raw = _synthetic_release(PIN, "2026-10-14T00:00:00Z")
        _write_release(root, rel, raw)
    nxt, raw2 = _synthetic_release("abcdef123456", "2026-10-21T00:00:00Z", shift=2)
    _write_release(root, nxt, raw2, latest=True)
    return root


def _status_from_defaults() -> dict:
    from src.api import feature_flags

    saved = {k: v for k, v in os.environ.items() if k.startswith("RISKIT_FEATURE_")}
    for k in saved:
        os.environ.pop(k)
    try:
        feature_flags.reload()
        snap = feature_flags.snapshot()
    finally:
        os.environ.update(saved)
        feature_flags.reload()
    return {"featureFlags": {k: {"enabled": v, "gateStatus": "live"} for k, v in snap.items()}}


def _run_mode(box: Path, mode: str, monkeypatch, *extra: str) -> tuple[int, dict, str]:
    """Run ``main()`` in ``mode`` against the synthetic box; returns the exit
    code, the parsed public stdout and whatever reached stderr."""
    import contextlib
    import io

    monkeypatch.setattr(MOD, "fetch_status", lambda *a, **k: _status_from_defaults())
    monkeypatch.setattr(
        MOD,
        "deploy_fingerprint",
        lambda app_dir: {"head": "a" * 40, "tree": "b" * 40, "config": "c", "receipt": None},
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["verify", "--app-dir", str(box), "--code-dir", str(REPO), "--mode", mode, *extra],
    )
    monkeypatch.chdir(REPO)
    monkeypatch.setattr(sys, "path", list(sys.path))
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = MOD.main()
    return rc, json.loads(out.getvalue()), err.getvalue()


def _fixture_names() -> list[str]:
    return [fixture._off(i) for i in range(fixture.N_OFF)] + [
        fixture._idp(i) for i in range(fixture.N_IDP)
    ]


def _assert_public_clean(text: str) -> None:
    lowered = text.lower()
    for name in _fixture_names():
        assert name.lower() not in lowered, "a synthetic player name reached the public output"
    assert not re.search(r'"(max|min)[A-Za-z0-9_]*"\s*:', text), "a max/min key is public"
    for key in ("wouldContribute", "valueContribution", "familyRank", "sourceShadowMeta"):
        assert f'"{key}"' not in text, key


# ── records: the embedded gates are the committed, frozen gates ───────────


def test_the_embedded_gates_are_the_committed_file():
    committed = json.loads((EVIDENCE / "gates.json").read_text(encoding="utf-8"))
    assert MOD.GATES == committed


def test_the_frozen_files_match_their_recorded_hashes():
    lines = (EVIDENCE / "FROZEN_SHA256SUMS").read_text(encoding="utf-8").split("\n")
    recorded = dict(reversed(line.split("  ", 1)) for line in lines if line.strip())
    assert set(recorded) == {"PREREGISTRATION.md", "gates.json"}
    for name, digest in recorded.items():
        assert hashlib.sha256((EVIDENCE / name).read_bytes()).hexdigest() == digest, name


def test_candidate_a_stays_failed_and_f_is_the_only_promotable_candidate():
    cands = MOD.GATES["candidates"]
    assert cands["A"]["status"] == "FAILED_ROUND_1" and cands["A"]["promotable"] is False
    assert cands["F"]["promotable"] is True
    assert set(MOD.GATES["d1"]["forbiddenCandidates"]) == {"F", "H", "G"}
    by_id = {c["id"]: c for c in MOD.GATES["empirical"]}
    # The October 17 thresholds, unchanged.
    assert by_id["G4"]["threshold"] == 0.05
    assert by_id["G5"]["threshold"] == 3.0
    assert by_id["G6-median"]["threshold"] == 0.02
    assert by_id["G6-p90"]["threshold"] == 0.08
    assert by_id["G6b"]["threshold"] == 0.05


# ── privacy layer ─────────────────────────────────────────────────────────


def test_the_sanitiser_drops_max_min_and_small_cells():
    out = MOD.sanitize_public(
        {
            "a": {"n": 5, "median": 0.123456, "p90": 0.9, "max": 3},
            "b": {"n": 40, "median": 0.123456, "p90": 0.98765},
            "maxCombinedPostCap": 1.0,
            "minimum": 2,
            "count": 7,
        }
    )
    assert out["a"] == {"n": 5, "median": None, "p90": None, "suppressed": "n<20"}
    assert out["b"] == {"n": 40, "median": 0.12, "p90": 0.99}
    assert "maxCombinedPostCap" not in out
    assert out["minimum"] == 2 and out["count"] == 7


def test_the_public_projection_is_an_explicit_allowlist():
    report = {
        "mode": "gate",
        "private": {"manifest": {"x": "y"}},
        "inputs": {"fileCount": 3, "payloadPath": "/secret/path"},
        "variants": {"served": {"status": "built", "rows": [1, 2]}},
        "families": {"DL": {"votes": 3}},
    }
    out = MOD.project_allowlist(report, MOD.GATES["privacy"]["publicAllow"])
    assert out == {
        "mode": "gate",
        "inputs": {"fileCount": 3},
        "variants": {"served": {"status": "built"}},
        "families": {"DL": {"votes": 3}},
    }


def test_the_name_blocklist_is_case_insensitive_and_word_bounded():
    names = ["Synthetic Idp 001"]
    with pytest.raises(ValueError) as err:
        MOD.assert_public_safe_v2({"x": "about synthetic IDP 001 today"}, names)
    assert "Synthetic" not in str(err.value), "the error must not carry the name"
    MOD.assert_public_safe_v2({"x": "Synthetic Idp 0012"}, names)
    with pytest.raises(ValueError):
        MOD.assert_public_safe_v2({"wouldContribute": 1}, [])


def test_a_name_bearing_exception_never_reaches_stdout_or_stderr(tmp_path, monkeypatch, capsys):
    box = tmp_path / "box"
    box.mkdir()

    def boom(*_a, **_k):
        raise ValueError("Synthetic Idp 001 carries 4321")

    monkeypatch.setattr(MOD, "v2_main", boom)
    monkeypatch.setattr(sys, "argv", ["verify", "--app-dir", str(box), "--mode", "gate"])
    monkeypatch.chdir(REPO)
    monkeypatch.setattr(sys, "path", list(sys.path))
    assert MOD.main() == 2
    captured = capsys.readouterr()
    assert json.loads(captured.out) == {"error": "ValueError"}
    assert captured.err == ""
    logs = list((box / "data" / "sources" / "signals" / "reports").glob("verify-stderr-*.log"))
    assert len(logs) == 1
    assert stat.S_IMODE(os.stat(logs[0]).st_mode) == 0o600
    assert "Synthetic Idp 001" in logs[0].read_text(encoding="utf-8")


def test_served_flags_fail_closed():
    for bad in ({}, {"featureFlags": {}}, {"featureFlags": {"x": {"enabled": "yes"}}}):
        with pytest.raises(RuntimeError):
            MOD.served_flags(bad)
    assert MOD.served_flags({"featureFlags": {"a": {"enabled": True}, "b": False}}) == {
        "a": True,
        "b": False,
    }


def test_an_unreachable_status_endpoint_stops_the_run(tmp_path, monkeypatch, capsys):
    box = _make_box(tmp_path / "box")

    def unreachable(*_a, **_k):
        raise OSError("connection refused")

    monkeypatch.setattr(MOD, "fetch_status", unreachable)
    monkeypatch.setattr(
        MOD, "deploy_fingerprint", lambda app_dir: {"head": "a", "tree": "b", "config": "c"}
    )
    monkeypatch.setattr(
        sys, "argv", ["verify", "--app-dir", str(box), "--code-dir", str(REPO), "--mode", "gate"]
    )
    monkeypatch.chdir(REPO)
    monkeypatch.setattr(sys, "path", list(sys.path))
    assert MOD.main() == 2
    assert json.loads(capsys.readouterr().out) == {"error": "OSError"}


def test_any_deploy_change_voids_the_run():
    base = {"head": "a", "tree": "t", "config": "c", "receipt": "r"}
    assert MOD.compare_fingerprints(base, dict(base))["intervened"] is False
    for field in ("head", "tree", "config", "receipt"):
        moved = {**base, field: "changed"}
        assert MOD.compare_fingerprints(base, moved)["intervened"] is True, field
    assert MOD.compare_fingerprints({**base, "head": None}, base)["intervened"] is True


@pytest.mark.parametrize(
    "argv,reason",
    [
        (["--mode", "diagnose", "--collect"], "collect_is_legacy_only"),
        (["--mode", "gate", "--payload-ref", "f9d1994e59"], "invalid_payload_ref"),
        (["--mode", "diagnose", "--payload-ref", "main;rm -rf /"], "invalid_payload_ref"),
        (["--mode", "gate", "--release-role", "R2"], "r2_needs_r1_release"),
        (["--mode", "gate", "--r1-release", "xyz"], "invalid_r1_release"),
    ],
)
def test_invalid_inputs_are_refused_before_anything_runs(argv, reason, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["verify", "--app-dir", str(REPO), *argv])
    assert MOD.main() == 2
    assert json.loads(capsys.readouterr().out) == {"error": "refused", "reason": reason}


def test_stale_freeze_trees_are_swept(tmp_path):
    old, new = tmp_path / "freeze-old", tmp_path / "freeze-new"
    old.mkdir()
    new.mkdir()
    os.utime(old, (1_000_000, 1_000_000))
    assert MOD.sweep_freezes(tmp_path, now=1_000_000 + 25 * 3600) == 1
    assert not old.exists() and new.exists()


# ── statistics ────────────────────────────────────────────────────────────


def test_newly_priced_rows_count_as_a_full_move():
    base = {"a": {"v": 1000}, "b": {"v": 1000}, "c": {"v": None}}
    var = {"a": {"v": 1010}, "b": {"v": 1000}, "c": {"v": 500}}
    mv = MOD.movement_v2(base, var, ["a", "b", "c"])
    assert mv["newlyPriced"] == 1 and mv["rowsConsidered"] == 3 and mv["rowsMoved"] == 2
    assert mv["relValueBothPriced"]["n"] == 2
    assert sorted([0.0, 0.01, 1.0])[1] == mv["relValue"]["median"]


def test_the_corrected_panel_needs_two_voting_sources():
    row = {
        "meta": {
            "x": {"valueContribution": 1000, "appliedWeight": 1.0},
            "y": {"valueContribution": 900, "appliedWeight": 0.0},
            "z": {"valueContribution": 800, "appliedWeight": 1.0, "hampelDropped": True},
        }
    }
    assert MOD.signed_bias([(1100.0, row)], [], corrected=True)["n"] == 0
    script = MOD.signed_bias([(1100.0, row)], [], corrected=False)
    assert script["n"] == 1 and script["median"] == pytest.approx(round(150 / 950, 4))


def test_judge_and_reproduction_tolerances():
    assert MOD.judge("le", 0.05, 0.05) == "PASS"
    assert MOD.judge("abs_le", -0.06, 0.05) == "FAIL"
    assert MOD.judge("le", None, 0.05) == "INSUFFICIENT"
    assert MOD.judge("insufficient_below", 0, 30) == "INSUFFICIENT"
    assert MOD.judge("report", None, None) == "REPORTED"
    rep = MOD.reproduction_verdicts(
        {
            "idpRowsMoving": 343,
            "idpRelMovementMedian": 0.0230,
            "idpRelMovementP90": 0.33,
            "signalsOutlierDropRate": 0.04,
            "lbSignedBias": -0.0700,
            "dbSignedBias": None,
            "offensePlayerRowsMoved": 0,
            "scorableIdpTrades": 0,
        }
    )
    assert rep["idpRowsMoving"]["verdict"] == "REPRODUCED"
    assert rep["idpRelMovementMedian"]["verdict"] == "REPRODUCED"  # within 1.0 point
    assert rep["idpRelMovementP90"]["verdict"] == "REPRODUCED"  # within 10% relative
    assert rep["lbSignedBias"]["verdict"] == "REPRODUCED"
    assert rep["dbSignedBias"]["verdict"] == "INSUFFICIENT"
    assert rep["offensePlayerRowsMoved"]["verdict"] == "NOT_REPRODUCED"


def test_g5_judges_every_familys_top200_share_in_an_isolated_build():
    board = {"top200ShareDeltaPp": {"DL": 0.5, "LB": -3.5, "DB": 0.0}}
    value = MOD._metric_for("top200ShareDeltaPp", {}, board, "DL", {})
    assert value == -3.5 and MOD.judge("abs_le", value, 3.0) == "FAIL"


def test_d1_never_isolates_the_candidate_f_coordinate(diagnose_run):
    _box, _rc, public, _err = diagnose_run
    cells = [
        cell
        for fam in ("DL", "LB", "DB")
        for cell in ((public["coordinates"].get(fam) or {}).get("decomposition") or {}).values()
    ]
    assert cells, "the decomposition ran"
    for cell in cells:
        assert "coverage" not in cell and "ordering" not in cell, "H(c_M) is F's vote"


def _compact(name, pos, v, meta, shadow=None, csv=None):
    return {"n": name, "pos": pos, "v": v, "meta": meta, "shadow": shadow or {}, "csv": csv or {}}


def test_permutation_controls_reuse_the_builds_own_votes():
    rows = []
    for i in range(30):
        vote = 5000 - 100 * i
        rows.append(
            _compact(
                f"Synthetic Idp {i:03d}",
                "LB",
                vote,
                {
                    "signalsIdpLb": {
                        "valueContribution": vote,
                        "effectiveRank": 10 + i,
                        "appliedWeight": 1.0,
                    },
                    "a": {"valueContribution": vote, "appliedWeight": 1.0},
                    "b": {"valueContribution": vote, "appliedWeight": 1.0},
                },
            )
        )
    nc = MOD.permutation_controls({"rows": rows}, "LB", draws=50, seed=7)
    assert nc == MOD.permutation_controls({"rows": rows}, "LB", draws=50, seed=7)
    assert nc["NC2"]["n"] == 50 and nc["NC3"]["n"] == 30
    # The identity assignment reproduces the build exactly (zero bias against
    # a panel equal to the vote).  Reversal keeps the signed median near zero
    # on a symmetric ladder: signed medians are nearly blind to ORDER, which
    # is exactly why the controls exist.
    identity = MOD.signed_bias(
        [(r["v"], r) for r in rows], MOD.FAMILY_KEYS.values(), corrected=True
    )
    assert identity == {"n": 30, "median": 0.0}
    assert abs(nc["NC3"]["median"]) < 0.05


def test_information_is_insufficient_without_reference_depth():
    served = {"rows": [_compact("Synthetic Idp 001", "DL", 100, {})]}
    out = MOD.information_diagnostic(served, None, None, None)
    assert {fam: rep["verdict"] for fam, rep in out.items()} == {
        "DL": "INSUFFICIENT",
        "LB": "INSUFFICIENT",
        "DB": "INSUFFICIENT",
    }


# ── end to end on the synthetic box ───────────────────────────────────────


@pytest.fixture(scope="module")
def diagnose_run(tmp_path_factory):
    box = _make_box(tmp_path_factory.mktemp("d1box"))
    mp = pytest.MonkeyPatch()
    try:
        rc, public, err = _run_mode(box, "diagnose", mp)
    finally:
        mp.undo()
    return box, rc, public, err


def test_d1_builds_its_matrix_and_never_candidate_f(diagnose_run):
    box, rc, public, _err = diagnose_run
    assert rc == 0, public
    assert public["mode"] == "diagnose"
    assert public["inputs"]["idpReleaseFound"] is True
    assert public["inputs"]["flagsSource"] == "local /api/status featureFlags"
    variants = public["variants"]
    for name in ("served", "noSignals", "A_all", "A_DL", "A_LB", "A_DB", "N0"):
        assert variants[name]["status"] == "built", name
    assert variants["A_all"]["voteStateAsIntended"] is True
    assert not any(name.startswith(("F_", "H", "G_")) for name in variants)
    private = json.loads((box / public["privateReport"]).read_text(encoding="utf-8"))
    assert stat.S_IMODE(os.stat(box / public["privateReport"]).st_mode) == 0o600
    flags = private["private"]["flags"]
    assert flags.get("signals_idp_shared_market") is False, "served board is the champion"
    # The pinned board was rendered from the release JSON into the frozen tree.
    assert any(k.endswith("signalsIdpDl.csv") for k in private["private"]["manifest"])


def test_d1_reports_reproduction_premises_and_decomposition(diagnose_run):
    _box, _rc, public, _err = diagnose_run
    allowed = set(MOD.GATES["reproduction"]["verdicts"]) | {"INSUFFICIENT"}
    assert set(public["reproduction"]) == {f["id"] for f in MOD.GATES["reproduction"]["figures"]}
    assert all(cell["verdict"] in allowed for cell in public["reproduction"].values())
    assert set(public["premises"]) == {"P1", "P2", "P3"}
    assert public["premises"]["P3"]["verdict"] == "PASS"  # IDP Show votes nowhere here
    coords = public["coordinates"]
    assert set(coords["bridgeReconstructionExact"]) == {"DL", "LB", "DB"}
    for fam in ("DL", "LB", "DB"):
        assert public["families"][fam]["identity"]["sidMatched"] > 0
        assert public["families"][fam]["identity"]["familyMismatched"] == 0
        assert "A_all" in public["families"][fam]["variants"]
    for fam in ("DL", "LB", "DB"):
        verdicts = public["verdicts"][fam]
        assert verdicts["promotable"] is False, "Candidate A is never promotable"
        assert set(verdicts) >= {"engineering", "empirical"}
        assert verdicts["engineering"]["G2"]["verdict"] == "PASS"
        assert verdicts["engineering"]["INT-EXTRAP"]["verdict"] == "PASS"


def test_d1_public_output_is_aggregates_only(diagnose_run):
    _box, _rc, public, err = diagnose_run
    text = json.dumps(public)
    _assert_public_clean(text)
    assert err == ""


def test_d1_refuses_without_its_pinned_release(tmp_path, monkeypatch):
    box = _make_box(tmp_path / "box", with_pin=False)
    rc, public, _err = _run_mode(box, "diagnose", monkeypatch)
    assert rc == 0
    assert public["verdicts"] == {"state": "VOID", "reason": "d1_release_pin_absent"}
    assert "variants" not in public


def test_the_d1_quarantine_is_enforced_in_code(tmp_path, monkeypatch):
    calls = []

    def fake_run_variant(name, **kw):
        calls.append((name, kw.get("toggles") or {}))
        return {
            "status": "built",
            "rows": [],
            "voteStates": {},
            "bridgeContributors": ["idpTradeCalc"],
        }

    monkeypatch.setattr(MOD, "run_variant", fake_run_variant)
    monkeypatch.setattr(MOD, "derive_tree", lambda base, dst, boards: dst)
    MOD.run_matrix("diagnose", freeze=tmp_path, code_dir=REPO, payload_path="x", flags={})
    forbidden = {MOD.XWALK_FLAG, *MOD.FAMILY_FLAGS.values()}
    assert calls and all(not (forbidden & {k for k, v in t.items() if v}) for _n, t in calls)
    # A diagnose build that tried to switch on Candidate F refuses outright.
    monkeypatch.setattr(MOD, "ACTIVE_FLAG", MOD.XWALK_FLAG)
    with pytest.raises(RuntimeError, match="d1_quarantine_violation"):
        MOD.run_matrix("diagnose", freeze=tmp_path, code_dir=REPO, payload_path="x", flags={})
    monkeypatch.undo()
    # So does one that would inherit it from the served flags.
    monkeypatch.setattr(MOD, "run_variant", fake_run_variant)
    with pytest.raises(RuntimeError, match="d1_quarantine_violation"):
        MOD.run_matrix(
            "diagnose",
            freeze=tmp_path,
            code_dir=REPO,
            payload_path="x",
            flags={MOD.XWALK_FLAG: True},
        )


def test_gate_refuses_every_f_build_until_its_flags_are_registered(tmp_path, monkeypatch):
    from src.api import feature_flags

    registered = set(feature_flags.registered_flags())
    if {MOD.XWALK_FLAG, *MOD.FAMILY_FLAGS.values()} <= registered:
        pytest.skip("the per-family flags are registered: the refusal path is unreachable")
    box = _make_box(tmp_path / "box")
    rc, public, err = _run_mode(box, "gate", monkeypatch)
    assert rc == 0
    for fam in ("DL", "LB", "DB"):
        assert public["variants"][f"F_{fam}"]["status"] == "refused"
        assert public["variants"][f"F_{fam}"]["refusedFlag"] in {
            MOD.XWALK_FLAG,
            *MOD.FAMILY_FLAGS.values(),
        }
        assert public["verdicts"][fam]["state"] == "VOID"
    assert public["variants"]["served"]["status"] == "built"
    assert public["release"]["role"] == "R1"
    assert public["release"]["qualifies"] is None  # no git anchor on a synthetic box
    _assert_public_clean(json.dumps(public))
    assert err == ""


def test_native_offline_reads_releases_only(tmp_path, monkeypatch):
    box = _make_box(tmp_path / "box")
    rc, public, _err = _run_mode(box, "native-offline", monkeypatch)
    assert rc == 0
    tier = public["nativeOffline"]
    assert tier["releases"] == 2
    assert tier["valueMonotoneInComposite"]["monotoneShareAbove95pct"] is True
    assert set(tier["rawPositionCounts"]) == {"DE", "LB", "CB"}
    assert tier["latestVsPreviousRankChange"]["changed"] > 0
    assert "variants" not in public
    _assert_public_clean(json.dumps(public))


# ── the workflow ──────────────────────────────────────────────────────────


def test_the_workflow_exposes_the_modes_and_guards_the_box():
    text = WORKFLOW.read_text(encoding="utf-8")
    for mode in MOD.MODES:
        assert f"- {mode}" in text, mode
    assert "actions: read" in text
    assert "Refuse while a production deploy is running or queued" in text
    assert "deploy.yml" in text
    # Remote stderr never reaches the public log: the verifier writes its own
    # failures to a 0600 file in its private store (private_stderr) and the
    # workflow discards anything else, without naming that store's path.
    assert "umask 077" in text and "2>/dev/null" in text
    assert callable(getattr(MOD, "private_stderr", None))
    assert "data/sources" not in text
    # Inputs reach the shell through env, validated, never interpolated.
    assert "${{ inputs.payload_ref }}" not in text.split("env:", 1)[0]
    assert re.search(r"\[0-9a-f\]\{7,40\}", text)


def test_the_matrix_splits_across_dispatches(tmp_path, monkeypatch):
    def fake_run_variant(name, **kw):
        return {"status": "built", "rows": [], "voteStates": {}, "bridgeContributors": []}

    monkeypatch.setattr(MOD, "run_variant", fake_run_variant)
    monkeypatch.setattr(MOD, "derive_tree", lambda base, dst, boards: dst)
    common = {"freeze": tmp_path, "code_dir": REPO, "payload_path": "x", "flags": {}}
    full, _ = MOD.run_matrix("diagnose", **common)
    core, _ = MOD.run_matrix("diagnose", part="core", **common)
    extra, _ = MOD.run_matrix("diagnose", part="extra", **common)
    assert set(full) == set(core) == set(extra)
    built = {
        p: {n for n, b in m.items() if b["status"] == "built"}
        for p, m in (("c", core), ("e", extra))
    }
    assert built["c"] & built["e"] == {"served"}
    assert built["c"] | built["e"] == set(full)
    assert "A_all" in built["c"] and "A_all_noRef" in built["e"]


def test_builds_stop_starting_when_the_time_budget_is_spent(tmp_path, monkeypatch):
    import time

    monkeypatch.setattr(MOD, "_DEADLINE", time.monotonic() - 1)
    out = MOD.run_variant(
        "served", freeze=tmp_path, code_dir=REPO, csv_root=tmp_path, payload_path="x", flags={}
    )
    assert out == {"status": "refused", "reason": "time_budget_exhausted"}


def test_the_gate_analysis_runs_on_built_candidate_builds(diagnose_run):
    """The F builds cannot be produced until the implementation unit lands,
    so the gate ANALYSIS is driven here with D1's synthetic compact builds
    standing in for them (same shapes).  Verdict plumbing, controls, the
    information diagnostic and the privacy layer are what is under test,
    not any number."""
    box, _rc, public, _err = diagnose_run
    work = box / public["privateReport"]
    freeze = json.loads(work.read_text(encoding="utf-8"))["private"]["freeze"]
    rows = {p.name.split(".")[0]: p for p in (Path(freeze) / "work").glob("*.rows.json")}

    def load(name):
        b = json.loads(rows[name].read_text(encoding="utf-8"))
        b["status"] = "built"
        return b

    builds = {
        "served": load("served"),
        "F_DL": load("A_DL"),
        "F_LB": load("A_LB"),
        "F_DB": load("A_DB"),
        "F_all": load("A_all"),
        "N0F": load("N0"),
        "served_noRef": load("served_noRef"),
        "F_all_noRef": load("A_all_noRef"),
        "N0F_noRef": load("N0_noRef"),
    }
    active = {k: "active" for k in MOD.FAMILY_KEYS.values()}
    intended = {
        "served": None,
        "F_DL": {"signalsIdpDl": "active"},
        "F_LB": {"signalsIdpLb": "active"},
        "F_DB": {"signalsIdpDb": "active"},
        "F_all": active,
        "N0F": active,
        "served_noRef": None,
        "F_all_noRef": active,
        "N0F_noRef": active,
    }
    rep = MOD.analyse("gate", box, builds, intended)
    for fam in ("DL", "LB", "DB"):
        v = rep["verdicts"][fam]
        assert v["candidate"] == MOD.CANDIDATE_F_ID and v["promotable"] is True
        assert {"engineering", "empirical"} <= set(v)
        allowed = set(MOD.GATES["verdictValues"])
        for section in ("engineering", "empirical"):
            assert all(
                e.get("verdict") in allowed or set(e) == {"suppressed"} for e in v[section].values()
            )
        if "watchListCounts" not in v:
            assert v["empirical"]["G3"] == {"suppressed": "watch entries below the public floor"}
            assert rep["privateWatchVerdicts"][fam]["verdict"] in allowed
        nc = rep["negativeControls"][fam]
        assert {"NC2", "NC3", "NC4", "g6bCorrectedPanelVoid"} <= set(nc)
        if nc["g6bCorrectedPanelVoid"]:
            assert v["empirical"]["G6b"]["verdict"] == "VOID"
    assert "reproduction" not in rep and "premises" not in rep, "D1-only blocks"
    public_rep = MOD.sanitize_public(
        MOD.project_allowlist(rep, MOD.GATES["privacy"]["publicAllow"])
    )
    MOD.assert_public_safe_v2(public_rep, _fixture_names())


def test_a_payload_ref_materialises_the_public_inputs_from_git(tmp_path):
    """D1's reproduction tree: public CSVs, scrape state and the raw payload
    come from the commit; private boards come from the box (git never holds
    them), with the IDP boards rendered from the pinned release."""
    import subprocess

    from src.api.data_contract import _SOURCE_CSV_PATHS

    box = _make_box(tmp_path / "box")
    public_rel = next(
        str(c["path"]) if isinstance(c, dict) else str(c)
        for c in _SOURCE_CSV_PATHS.values()
        if not (isinstance(c, dict) and c.get("private_marker"))
    )
    (box / public_rel).parent.mkdir(parents=True, exist_ok=True)
    (box / public_rel).write_text("name,rank\nSynthetic Off 000,1\n", encoding="utf-8")
    (box / "exports" / "latest").mkdir(parents=True)
    (box / "exports" / "latest" / "dynasty_data_2026-10-17.json").write_text(
        json.dumps(fixture._raw_payload()), encoding="utf-8"
    )
    (box / "data" / "scrape_state").mkdir(parents=True)
    (box / "data" / "scrape_state" / "dlfIdp_last_success").write_text("1", encoding="utf-8")
    git = ["git", "-C", str(box), "-c", "user.email=t@example.invalid", "-c", "user.name=t"]
    subprocess.run([*git, "init", "-q"], check=True)
    subprocess.run([*git, "add", public_rel, "exports", "data/scrape_state"], check=True)
    subprocess.run([*git, "commit", "-q", "-m", "synthetic"], check=True)
    ref = subprocess.run(
        [*git, "rev-parse", "--short=10", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()
    # The working copy moves on; the ref tree must not.
    (box / public_rel).write_text("name,rank\nchanged,1\n", encoding="utf-8")
    freeze = tmp_path / "freeze"
    info = MOD.build_freeze(box, freeze, payload_ref=ref, idp_pin=PIN, offense_pin=None)
    assert info["treeKind"] == "ref"
    assert info["payloadName"] == "dynasty_data_2026-10-17.json"
    assert info["idpReleaseFound"] is True
    tree = freeze / "tree"
    assert "Synthetic Off 000" in (tree / public_rel).read_text(encoding="utf-8")
    assert (tree / "data" / "scrape_state" / "dlfIdp_last_success").is_file()
    assert (tree / "data" / "sources" / "signals" / "board" / "signalsIdpDl.csv").is_file()
    assert set(info["manifest"]) >= {public_rel, "data/scrape_state/dlfIdp_last_success"}
    with pytest.raises(RuntimeError, match="payload_ref_unavailable"):
        MOD.build_freeze(
            box, tmp_path / "f2", payload_ref="deadbeef00", idp_pin=None, offense_pin=None
        )
