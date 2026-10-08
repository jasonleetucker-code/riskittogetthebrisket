"""Model Lab (AL-0b / IC-5): a read-only, private view over the existing owners.

Pins, per plan §33 and the IC-5 intake row:

* the contract shape — every family carries the same fields, every observed
  champion the same champion fields, every challenger row the same row fields and a
  lab state from the fixed vocabulary;
* rejected challengers are LISTED, never dropped (plan §30);
* missing evidence is an explicit state block, never ``0`` / ``None`` / ``[]``;
* drift with no monitor is ``unmeasured`` (never "none");
* every family with at least one receipt appears, even without a wired owner;
* private + admin-only (401 anonymous, 403 non-admin, 401 when unwired);
* read-only — GET routes only, no write call in either module, and building the Lab
  leaves the repository's model evidence byte-identical and creates no file.
"""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from src.model_registry import model_lab as ml
from src.model_registry import model_lab_api

REPO = Path(__file__).resolve().parents[2]
STATE_BLOCK_STATES = {"unobserved", "not_applicable", "unmeasured"}


# ── helpers ──────────────────────────────────────────────────────────────────


def _families(payload):
    return {f["family"]: f for f in payload["families"]}


def _assert_family_shape(block):
    assert tuple(block) == ml.FAMILY_FIELDS, block.get("family")
    for key in ml.FAMILY_FIELDS:
        # A family field is never a bare null: observed data or a state block.
        assert block[key] is not None, (block["family"], key)
    champ = block["champion"]
    if not ml.is_state_block(champ):
        assert tuple(champ) == ml.CHAMPION_FIELDS, block["family"]
        for key in ml.CHAMPION_FIELDS:
            assert champ[key] is not None, (block["family"], key)
    if isinstance(block["challengers"], list):
        for row in block["challengers"]:
            assert tuple(row) == ml.CHALLENGER_FIELDS
            assert row["state"] in ml.LAB_STATES
            assert row["reason"], (block["family"], row["version"])
        assert set(block["challengerStates"]) == set(ml.LAB_STATES)
        assert sum(block["challengerStates"].values()) == len(block["challengers"])
    drift = block["drift"]
    assert drift["state"] == "unmeasured" and drift["reason"]


def _walk_state_blocks(obj, path="$"):
    """Every dict carrying a ``state`` from the vocabulary must carry a reason."""
    if isinstance(obj, dict):
        if obj.get("state") in STATE_BLOCK_STATES:
            assert str(obj.get("reason") or "").strip(), f"state block without reason at {path}"
        for k, v in obj.items():
            _walk_state_blocks(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            _walk_state_blocks(v, f"{path}[{i}]")


def _write(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(obj, str):
        path.write_text(obj, encoding="utf-8")
    else:
        path.write_text(json.dumps(obj), encoding="utf-8")


def _tree_digest(root: Path) -> dict[str, str]:
    return {
        p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def _holdout(criterion, measured="2026-10-01T00:00:00+00:00"):
    return {
        "criterion": criterion,
        "criterionName": "mean_per_source_rmse",
        "criterionUnits": "points",
        "perSource": {"A": criterion, "B": criterion, "C": criterion},
        "perSourceRows": {"A": 400, "B": 400, "C": 400},
        "measuredAt": measured,
        "holdoutSources": ["A", "B", "C"],
        "trainingSources": ["T"],
    }


def _version(n, status, **extra):
    base = {
        "modelId": "hill_scope_masters",
        "version": n,
        "params": {"HILL_PERCENTILE_C": 0.1},
        "fittedAt": f"2026-09-{n:02d}T00:00:00+00:00",
        "producer": "test",
        "status": status,
        "trainingInputs": {"KTC": "sha256:x"},
        "holdout": _holdout(500.0 + n),
        "notes": [],
        "promotedAt": None,
        "retiredAt": None,
        "appliedAt": None,
        "scopeValidation": {},
    }
    base.update(extra)
    return base


REPRODUCIBLE = {"reproducible": True, "trainingCutoff": "2026-09-30T00:00:00+00:00"}


@pytest.fixture
def hill_root(tmp_path):
    """A synthetic Hill registry exercising every lab state."""
    versions = [
        _version(
            1,
            "retired",
            fittedAt="unknown",
            promotedAt="2026-07-01T00:00:00+00:00",
            retiredAt="2026-07-29T00:00:00+00:00",
            notes=["seeded"],
        ),
        _version(2, "champion", promotedAt="2026-07-29T00:00:00+00:00", notes=["promoted: win"]),
        _version(3, "rejected", notes=["rejected: improvement +22.4 does not clear the margin"]),
        _version(4, "challenger"),  # no trainingRun -> legacy substrate
        _version(5, "challenger", holdout=None),  # no holdout -> unqualified
        _version(6, "challenger", trainingRun=REPRODUCIBLE),  # excluded: stale
        _version(7, "challenger", trainingRun=REPRODUCIBLE),  # competed
        _version(8, "challenger", trainingRun=REPRODUCIBLE),  # winner
    ]
    _write(
        tmp_path / ml.HILL_REGISTRY_REL,
        {"modelId": "hill_scope_masters", "championVersion": 2, "versions": versions},
    )
    run = {
        "evaluatedAt": "2026-10-07T17:46:13+00:00",
        "outcome": "HOLD",
        "ready": False,
        "reason": "blocked by: parameter_stability",
        "winnerVersion": 8,
        "championVersion": 2,
        "championCriterion": 900.0,
        "championPerSource": {"A": 900.0},
        "currentRows": {"A": 400},
        "gates": {"winner": True, "parameter_stability": False},
        "independentValidation": {"reason": "no_independent_validation_target"},
        "holdoutIndependence": {"reason": "no_independent_holdout", "lineageDependence": {}},
        "safePromotionScope": ["OFFENSE"],
        "tournament": [{"version": 7}, {"version": 8}],
        "excludedFromTournament": {
            "duplicates": {},
            "legacySubstrateCount": 1,
            "otherExclusions": {"6": "stale_code_or_manifest"},
        },
        "rowHealthDetail": {"A": {"pass": True}},
    }
    older = dict(run, evaluatedAt="2026-10-01T00:00:00+00:00", outcome="OLD")
    _write(
        tmp_path / ml.HILL_AUTOPILOT_RUNS_REL,
        json.dumps(run) + "\nnot json\n" + json.dumps(older) + "\n",
    )
    return tmp_path


# ── the contract on the committed evidence ───────────────────────────────────


@pytest.fixture(scope="module")
def live_payload():
    return ml.build_model_lab()


def test_every_family_has_the_contract_shape(live_payload):
    fams = _families(live_payload)
    for family_id, _ in ml.FAMILY_BUILDERS:
        assert family_id in fams
        _assert_family_shape(fams[family_id])
    assert live_payload["builderErrors"] == {}
    _walk_state_blocks(live_payload)
    json.dumps(live_payload)  # serializable as served


def test_hill_lists_every_registry_version_and_keeps_rejected(live_payload):
    registry = json.loads((REPO / ml.HILL_REGISTRY_REL).read_text(encoding="utf-8"))
    hill = _families(live_payload)[ml.HILL_FAMILY]
    by_version = {row["version"]: row for row in hill["challengers"]}
    assert set(by_version) == {v["version"] for v in registry["versions"]}
    rejected = [v for v in registry["versions"] if v["status"] == "rejected"]
    assert rejected, "the committed registry carries rejected challengers"
    for v in rejected:
        row = by_version[v["version"]]
        assert row["state"] == ml.LAB_REJECTED
        assert row["nativeStatus"] == "rejected"
        assert row["reason"] == v["notes"][-1]
    champions = [r for r in hill["challengers"] if r["state"] == ml.LAB_CHAMPION]
    assert [r["version"] for r in champions] == [registry["championVersion"]]
    assert hill["champion"]["version"] == registry["championVersion"]


def test_hill_production_state_compares_served_constants(live_payload):
    hill = _families(live_payload)[ml.HILL_FAMILY]
    assert isinstance(hill["productionState"]["liveConstantsMatchChampion"], bool)
    assert hill["promotionAuthority"]["independentTargetRequired"] is True


def test_rejected_evaluator_candidates_are_listed(live_payload):
    fams = _families(live_payload)
    sq = fams[ml.SQ_FAMILY]
    assert {r["state"] for r in sq["challengers"]} >= {ml.LAB_CHAMPION}
    sq_candidates = [r for r in sq["challengers"] if r["state"] != ml.LAB_CHAMPION]
    assert sq_candidates, "the committed #1589 evaluation lists its candidates"
    for row in sq_candidates:
        if row["nativeStatus"] == "DOES_NOT_MEET_PREREGISTERED_GATE":
            assert row["state"] == ml.LAB_REJECTED
    sparse = fams[ml.SPARSE_FAMILY]
    assert any(r["state"] == ml.LAB_REJECTED for r in sparse["challengers"])


# ── missing is never zero ────────────────────────────────────────────────────


def test_empty_root_reports_unobserved_not_zero(tmp_path):
    payload = ml.build_model_lab(tmp_path)
    assert payload["builderErrors"] == {}
    fams = _families(payload)
    for family_id, _ in ml.FAMILY_BUILDERS:
        _assert_family_shape(fams[family_id])
    _walk_state_blocks(payload)
    hill = fams[ml.HILL_FAMILY]
    assert hill["champion"]["state"] == "unobserved"
    assert hill["lastEvaluation"]["state"] == "unobserved"
    assert hill["gate"]["state"] == "unobserved"
    assert hill["rollback"]["state"] == "unobserved"
    assert hill["challengers"] == []
    sparse = fams[ml.SPARSE_FAMILY]
    assert sparse["champion"]["sampleSize"]["boardRows"]["state"] == "unobserved"
    assert sparse["productionState"]["shadowLedger"]["state"] == "unobserved"
    sq = fams[ml.SQ_FAMILY]
    assert sq["champion"]["metrics"]["state"] == "unobserved"
    assert sq["lastEvaluation"]["state"] == "unobserved"


def test_receipt_store_absent_is_unobserved_not_zero(tmp_path):
    payload = ml.build_model_lab(
        tmp_path, receipt_store_path=tmp_path / "data/learning/none.sqlite"
    )
    assert payload["receiptStore"]["state"] == "unobserved"
    for block in payload["families"]:
        assert block["receipts"]["state"] == "unobserved"


def test_hill_states_follow_the_recorded_autopilot_verdict(hill_root):
    hill = ml.build_hill_family(hill_root, {"state": "unobserved", "reason": "x"})
    _assert_family_shape(hill)
    rows = {r["version"]: r for r in hill["challengers"]}
    assert rows[1]["state"] == ml.LAB_RETIRED
    assert rows[1]["createdAt"]["state"] == "unobserved"  # "unknown" is not a time
    assert "'unknown'" in rows[1]["createdAt"]["reason"]
    assert rows[2]["state"] == ml.LAB_CHAMPION
    assert rows[3]["state"] == ml.LAB_REJECTED
    assert rows[3]["reason"].startswith("rejected: improvement")
    assert rows[4]["state"] == ml.LAB_INSUFFICIENT
    assert rows[4]["reason"].startswith("legacy_substrate")
    assert rows[5]["state"] == ml.LAB_INSUFFICIENT
    assert rows[6]["state"] == ml.LAB_HELD and "stale_code_or_manifest" in rows[6]["reason"]
    assert rows[7]["state"] == ml.LAB_HELD and "competed" in rows[7]["reason"]
    assert rows[8]["state"] == ml.LAB_HELD and "winner" in rows[8]["reason"]
    # Latest run by evaluatedAt, not file order; the malformed line is reported.
    assert hill["gate"]["result"] == "HOLD"
    assert hill["dataQuality"]["autopilotLog"] == "1 malformed line(s) skipped"
    assert hill["rollback"]["version"] == 1
    assert hill["champion"]["dataThrough"]["state"] == "unobserved"
    assert hill["champion"]["metrics"]["latestPairedRescore"]["point"] == 900.0
    assert hill["challengerStates"] == {
        "CHAMPION": 1,
        "SHADOW": 0,
        "HELD": 3,
        "REJECTED": 1,
        "INSUFFICIENT_EVIDENCE": 2,
        "RETIRED": 1,
    }


def test_family_with_receipts_but_no_owner_still_appears(tmp_path, monkeypatch):
    from src.model_registry import receipt_store
    from src.model_registry.learning_receipt import Unobserved, build_receipt

    monkeypatch.setattr(receipt_store, "EXTRA_ALLOWED_ROOTS", (tmp_path.resolve(),))
    store = tmp_path / "receipts.sqlite"
    receipts = [
        build_receipt(
            kind="OBSERVATION",
            producer="test_producer",
            native_id=f"n{i}",
            model_family=family,
            model_version_id=None,
            slots={"inputs": Unobserved("test")},
        )
        for i, family in enumerate(["hill_scope_masters", "hill_scope_masters", "future_family"])
    ]
    receipt_store.append_receipts(receipts, path=store)
    before = hashlib.sha256(store.read_bytes()).hexdigest()
    payload = ml.build_model_lab(tmp_path, receipt_store_path=store)
    # Reading the store (``iter_receipts``, mode=ro) leaves the database byte-identical.
    # SQLite may materialise its WAL-mode side files on a read-only open; any WAL it
    # leaves is empty -- no content was written.
    assert hashlib.sha256(store.read_bytes()).hexdigest() == before
    wal = store.with_name(store.name + "-wal")
    assert not wal.exists() or wal.stat().st_size == 0
    fams = _families(payload)
    assert payload["receiptStore"]["state"] == "observed"
    assert fams[ml.HILL_FAMILY]["receipts"]["byKind"] == {"OBSERVATION": 2}
    assert fams[ml.SQ_FAMILY]["receipts"] == {
        "state": "observed",
        "total": 0,
        "byKind": {},
        "latestCutoff": None,
    }
    assert "future_family" in fams
    _assert_family_shape(fams["future_family"])
    assert fams["future_family"]["receipts"]["total"] == 1


# ── read-only ────────────────────────────────────────────────────────────────

EVIDENCE_PATHS = (
    "config/model_registry",
    "config/bdvm",
    "config/consensus_edge",
    "docs/valuation/evidence",
    "docs/measurements",
    "src/canonical/player_valuation.py",
)


def _digest_paths(paths):
    out = {}
    for rel in paths:
        p = REPO / rel
        files = [p] if p.is_file() else sorted(x for x in p.rglob("*") if x.is_file())
        for f in files:
            out[f.relative_to(REPO).as_posix()] = hashlib.sha256(f.read_bytes()).hexdigest()
    return out


def test_building_the_lab_changes_nothing(hill_root):
    before_repo = _digest_paths(EVIDENCE_PATHS)
    learning_existed = (REPO / "data" / "learning").exists()
    before_tmp = _tree_digest(hill_root)
    ml.clear_memo()
    ml.build_model_lab()
    ml.build_model_lab(hill_root)
    ml.cached_model_lab()
    assert _digest_paths(EVIDENCE_PATHS) == before_repo
    assert (REPO / "data" / "learning").exists() == learning_existed
    assert _tree_digest(hill_root) == before_tmp
    ml.clear_memo()


WRITE_ATTRS = {
    "write_text",
    "write_bytes",
    "unlink",
    "rmtree",
    "rename",
    "touch",
    "mkdir",
    "save",
    "promote",
    "reject",
    "rollback",
    "mark_applied",
    "append_receipts",
    "record_correction",
    "write_committed_constants",
    "append_record",
    "connect",
}


@pytest.mark.parametrize(
    "module", ["src/model_registry/model_lab.py", "src/model_registry/model_lab_api.py"]
)
def test_modules_name_no_write_call(module):
    tree = ast.parse((REPO / module).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", None)
            assert name not in WRITE_ATTRS, f"{module}:{node.lineno} calls {name}"
            if name == "open":
                for arg in [*node.args[1:], *[k.value for k in node.keywords if k.arg == "mode"]]:
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        assert not set(arg.value) & set("wax+"), f"{module}:{node.lineno}"
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                assert alias.name not in WRITE_ATTRS, f"{module} imports {alias.name}"


def test_router_has_get_routes_only():
    methods = {m for r in model_lab_api.router.routes for m in getattr(r, "methods", set())}
    assert methods == {"GET"}


# ── memo ─────────────────────────────────────────────────────────────────────


def test_memo_reuses_within_ttl_and_rebuilds_after(monkeypatch):
    ml.clear_memo()
    calls = []

    def fake_build():
        calls.append(1)
        return {"n": len(calls)}

    monkeypatch.setattr(ml, "build_model_lab", fake_build)
    now = [100.0]
    first = ml.cached_model_lab(ttl=60, clock=lambda: now[0])
    now[0] = 159.0
    assert ml.cached_model_lab(ttl=60, clock=lambda: now[0]) is first
    now[0] = 161.0
    assert ml.cached_model_lab(ttl=60, clock=lambda: now[0]) == {"n": 2}
    ml.clear_memo()


# ── private + admin-only ─────────────────────────────────────────────────────


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(
        ml, "cached_model_lab", lambda: {"schema": "x", "families": [{"family": "fam"}]}
    )
    app = FastAPI()
    app.include_router(model_lab_api.router)
    yield TestClient(app)
    model_lab_api.configure_authorizer(None)


def test_unwired_router_refuses(client):
    model_lab_api.configure_authorizer(None)
    res = client.get("/api/model-lab")
    assert res.status_code == 401
    assert res.headers["cache-control"] == "no-store"


def test_anonymous_and_non_admin_are_refused(client):
    model_lab_api.configure_authorizer(
        lambda request: JSONResponse(status_code=401, content={"error": "auth_required"})
    )
    assert client.get("/api/model-lab").status_code == 401
    assert client.get("/api/model-lab/fam").status_code == 401
    model_lab_api.configure_authorizer(
        lambda request: JSONResponse(status_code=403, content={"error": "admin_required"})
    )
    res = client.get("/api/model-lab")
    assert res.status_code == 403
    assert res.headers["cache-control"] == "no-store"


def test_authorizer_fault_never_grants(client):
    def boom(request):
        raise RuntimeError("session store down")

    model_lab_api.configure_authorizer(boom)
    assert client.get("/api/model-lab").status_code == 401


def test_admin_reads_the_lab_and_one_family(client):
    model_lab_api.configure_authorizer(lambda request: {"username": "admin"})
    res = client.get("/api/model-lab")
    assert res.status_code == 200
    assert res.headers["cache-control"] == "no-store"
    assert res.json()["families"] == [{"family": "fam"}]
    one = client.get("/api/model-lab/fam")
    assert one.status_code == 200 and one.json()["family"] == {"family": "fam"}
    missing = client.get("/api/model-lab/nope")
    assert missing.status_code == 404 and missing.json()["families"] == ["fam"]
    assert client.post("/api/model-lab").status_code == 405


def test_server_wires_the_admin_authorizer():
    import server

    # app.openapi(), not app.routes: the route list's shape differs across the
    # FastAPI versions used locally and in CI.
    paths = server.app.openapi()["paths"]
    for path in ("/api/model-lab", "/api/model-lab/{family}"):
        assert set(paths[path]) == {"get"}
    assert not server._is_public_api_path("/api/model-lab")
    assert not server._is_public_api_path("/api/model-lab/hill_scope_masters")
    src = (REPO / "server.py").read_text(encoding="utf-8")
    assert (
        "_model_lab_api.configure_authorizer(lambda request: _require_admin_session(request))"
        in src
    )


def test_consensus_edge_reports_the_newest_validation_per_horizon(live_payload):
    horizons = set()
    for path in (REPO / "docs/measurements").glob("consensus-edge-board-validation-*.json"):
        horizons.add(json.loads(path.read_text(encoding="utf-8")).get("horizonDays"))
    ce = _families(live_payload)[ml.CE_FAMILY]
    (model,) = ce["challengers"]
    names = {m["name"] for m in model["metrics"]}
    assert names == {f"medianExcessTop20[{h}d]" for h in horizons}


# ── one verdict vocabulary: the Lab consumes AL-0's tables ───────────────────


def test_lab_states_cover_exactly_the_al0_verdicts():
    from src.model_registry.evaluation_receipt import VERDICTS

    assert set(ml.VERDICT_TO_LAB_STATE) == set(VERDICTS)
    assert set(ml.VERDICT_TO_LAB_STATE.values()) <= set(ml.LAB_STATES)


@pytest.mark.parametrize(
    "table_path",
    [
        ("src.model_registry.learning_adapters", "SQ_DISPOSITION_TO_VERDICT"),
        ("src.model_registry.producer_receipts", "ROBUST_VERDICT_TO_VERDICT"),
    ],
)
def test_evaluator_states_derive_from_the_producers_al0_table(table_path):
    import importlib

    module, name = table_path
    table = getattr(importlib.import_module(module), name)
    for native, verdict in table.items():
        state, al0 = ml._state_from_native(native, table)
        assert al0 == verdict
        assert state == ml.VERDICT_TO_LAB_STATE[verdict]
    state, al0 = ml._state_from_native("SOMETHING_NEW", table)
    assert state == ml.LAB_INSUFFICIENT and al0["state"] == "unobserved"
    assert "SOMETHING_NEW" in al0["reason"]


def test_lab_tables_speak_only_al0_verdicts():
    from src.model_registry.evaluation_receipt import VERDICTS

    for table in (ml.SPARSE_VERDICT_TO_VERDICT, ml.CE_DECISION_TO_VERDICT):
        assert set(table.values()) <= set(VERDICTS)


def test_rollback_identity_is_the_owners_selection(hill_root):
    from src.model_registry.versioning import ModelRegistry

    registry = ModelRegistry.load("hill_scope_masters", hill_root / "config/model_registry")
    named = ml.build_hill_family(hill_root, {"state": "unobserved", "reason": "x"})["rollback"]
    assert named["version"] == registry.rollback_target().version
    # ...and it is exactly what rollback() would reinstate (in memory only).
    assert registry.rollback(reason="test").version == named["version"]


def test_flags_are_read_through_the_registry_reporting_helper(monkeypatch):
    from src.api import feature_flags

    def refuse(name):  # a variable read would be invisible to the reachability scan
        raise AssertionError(f"is_enabled({name!r}) read through a variable")

    real = feature_flags.effective_flags()
    monkeypatch.setattr(feature_flags, "effective_flags", lambda: real)
    monkeypatch.setattr(feature_flags, "is_enabled", refuse)
    row = ml._flag_state("consensus_edge")
    assert row["enabled"] is real["consensus_edge"]["enabled"]
    assert row["gateStatus"] == real["consensus_edge"]["gateStatus"]


def test_receipt_counts_is_a_grouped_read(tmp_path, monkeypatch):
    from src.model_registry import receipt_store
    from src.model_registry.learning_receipt import Unobserved, build_receipt

    monkeypatch.setattr(receipt_store, "EXTRA_ALLOWED_ROOTS", (tmp_path.resolve(),))
    store = tmp_path / "r.sqlite"
    assert receipt_store.receipt_counts(store) is None  # absent, not zero
    receipt_store.append_receipts(
        [
            build_receipt(
                kind=kind,
                producer="p",
                native_id=f"n{i}",
                model_family="fam",
                model_version_id=None,
                slots={"inputs": Unobserved("test")},
            )
            for i, kind in enumerate(["OBSERVATION", "OBSERVATION", "FEATURES"])
        ],
        path=store,
    )
    counts = receipt_store.receipt_counts(store)
    assert counts["corrections"] == 0
    assert {(g["modelFamily"], g["kind"], g["count"]) for g in counts["groups"]} == {
        ("fam", "FEATURES", 1),
        ("fam", "OBSERVATION", 2),
    }
