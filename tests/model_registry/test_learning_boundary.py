"""AL-0 A7: facts and rules do not learn (plan §18).

The learning substrate may READ deterministic owners. It may not write a
canonical value field (``CANONICAL_VALUE_FIELDS``), league config, an identity
mapping, a timestamp owner or a contract stamp, and running it must leave the
served board untouched. Proved three ways:

1. **imports** — an allow-list: every ``src`` import of a learning module is named
   here, with the exact names it may take. A new import fails until reviewed;
2. **writes** — no learning module writes a file except the receipt store, which
   writes only its own SQLite file;
3. **runtime** — running every adapter over the committed evidence and storing
   the receipts leaves the served board, the Hill constants, the league registry,
   identity config and the model registry byte-identical, and no receipt carries
   a canonical value or contract field.
"""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path

from src.league_intel.overlay import CANONICAL_VALUE_FIELDS

REPO = Path(__file__).resolve().parents[2]

LEARNING_MODULES = (
    "src/model_registry/learning_receipt.py",
    "src/model_registry/evaluation_receipt.py",
    "src/model_registry/feature_dictionary.py",
    "src/model_registry/receipt_store.py",
    "src/model_registry/learning_adapters.py",
    "src/model_registry/producer_receipts.py",
    "src/model_registry/game_day_calibration.py",
    "src/model_registry/projection_scorecard.py",
)

#: module -> names it may import (None = the module is learning-internal).
ALLOWED_SRC_IMPORTS: dict[str, frozenset[str] | None] = {
    "src.history.asof": frozenset(
        {
            "FIDELITY_EXACT",
            "FIDELITY_NEAREST_PRIOR",
            "FIDELITY_PARTIAL",
            "FIDELITY_RECONSTRUCTED",
            "FIDELITY_UNAVAILABLE",
        }
    ),
    "src.history.store": frozenset({"has_time_component"}),
    "src.model_registry.training_run": frozenset({"pins_hash"}),
    "src.source_quality.panel": frozenset({"day_end"}),
    # AL-4a / AL-3b scorecards READ the projection, realized-points and metric
    # owners; they write nothing (rule 2 below still applies to them).
    "src.bdvm.backtest": frozenset({"brier"}),
    "src.bdvm.projections": frozenset({"ProjectionRecord"}),
    "src.dfs.metrics": frozenset({"SMALL_SAMPLE", "point_forecast"}),
    "src.nfl_data.realized_points": frozenset({"compute_weekly_points", "host_stat_line"}),
    "src.ros.projection_ensemble": frozenset(
        {"_DEFAULT_ROS_FULL_SEASON_SOURCES", "combine_ensemble"}
    ),
    "src.ros.projection_observations": frozenset(
        {"ProjectionObservationError", "rescore_projection_record"}
    ),
    "src.ros.sleeper_weekly_projections": frozenset(
        {"WeeklyProjectionError", "build_weekly_observations", "lock_baseline_at_kickoff"}
    ),
    "src.model_registry.learning_receipt": None,
    "src.model_registry.evaluation_receipt": None,
    "src.model_registry.feature_dictionary": None,
    "src.model_registry.receipt_store": None,
    "src.model_registry.learning_adapters": None,
    "src.model_registry.producer_receipts": None,
    "src.model_registry.game_day_calibration": None,
    "src.model_registry.projection_scorecard": None,
}

#: Contract stamps, league config and identity-mapping fields a learning module
#: must never name as a key it writes.
FORBIDDEN_FIELD_LITERALS = frozenset(
    {
        *CANONICAL_VALUE_FIELDS,
        "canonicalConsensusRank",
        "canonicalTier",
        "confidenceBucket",
        "scoringSettings",
        "rosterPositions",
        "leagueSettings",
        "sleeperDataReady",
        "contractVersion",
        "playerIds",
        "idToPlayer",
        "sleeperId",
    }
)

WRITE_ATTRS = frozenset(
    {"write_text", "write_bytes", "unlink", "rmtree", "rename", "touch", "mkdir"}
)


def _trees():
    for rel in LEARNING_MODULES:
        yield rel, ast.parse((REPO / rel).read_text(encoding="utf-8"))


def test_imports_are_allow_listed():
    for rel, tree in _trees():
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    assert not a.name.startswith("src"), f"{rel}: plain import of {a.name}"
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("src"):
                assert (
                    node.module in ALLOWED_SRC_IMPORTS
                ), f"{rel} imports {node.module} (not allow-listed)"
                allowed = ALLOWED_SRC_IMPORTS[node.module]
                if allowed is not None:
                    names = {a.name for a in node.names}
                    assert names <= allowed, f"{rel} takes {names - allowed} from {node.module}"


def test_no_learning_module_names_a_canonical_contract_league_or_identity_field():
    for rel, tree in _trees():
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                assert node.value not in FORBIDDEN_FIELD_LITERALS, f"{rel} names {node.value!r}"


def test_only_the_receipt_store_writes_and_only_its_sqlite_file():
    for rel, tree in _trees():
        is_store = rel.endswith("receipt_store.py")
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr in WRITE_ATTRS:
                assert is_store and node.attr == "mkdir", f"{rel} calls .{node.attr}"
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "open"
            ):
                modes = [a.value for a in node.args[1:2] if isinstance(a, ast.Constant)]
                modes += [
                    k.value.value
                    for k in node.keywords
                    if k.arg == "mode" and isinstance(k.value, ast.Constant)
                ]
                assert not any(
                    set(str(m)) & set("wax+") for m in modes
                ), f"{rel} opens a file for writing"
            if isinstance(node, ast.Attribute) and node.attr == "dump":
                raise AssertionError(f"{rel} dumps to a file")
            if isinstance(node, ast.Attribute) and node.attr == "connect" and not is_store:
                raise AssertionError(f"{rel} opens a database")


def _protected() -> dict[str, str]:
    paths = [
        *sorted((REPO / "exports" / "latest").glob("dynasty_data_*.json")),
        REPO / "src" / "canonical" / "player_valuation.py",
        REPO / "config" / "model_registry" / "hill_scope_masters.json",
        REPO / "config" / "leagues" / "registry.json",
        *sorted((REPO / "config" / "identity").glob("*")),
        *sorted((REPO / "data" / "leagues").glob("scoring_*.json")),
        REPO / "data" / "temporal_ledger.sqlite",
    ]
    return {
        p.relative_to(REPO).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in paths
        if p.is_file()
    }


def _keys(obj, out: set[str]) -> set[str]:
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.add(str(k))
            _keys(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _keys(v, out)
    return out


def test_running_the_substrate_leaves_the_served_board_and_facts_untouched(tmp_path):
    from src.model_registry import learning_adapters as la
    from src.model_registry import receipt_store as rs
    from src.model_registry.feature_dictionary import load_dictionary

    before = _protected()
    assert any(k.startswith("exports/latest/") for k in before), "no served board to pin"
    d = load_dictionary()
    reg = json.loads(
        (REPO / "config/model_registry/hill_scope_masters.json").read_text(encoding="utf-8")
    )
    receipts = []
    for v in reg["versions"]:
        receipts += la.hill_receipts_from_registry_version(
            v, champion_version=reg["championVersion"]
        )
    sq = REPO / "docs/valuation/evidence/source-quality-2026-10-01"
    results = json.loads((sq / "results_2026-09-30.json").read_text(encoding="utf-8"))
    for line in (sq / "evaluations.jsonl").read_text(encoding="utf-8").splitlines():
        receipts += la.source_quality_receipts(
            json.loads(line),
            archive_key="evaluations.jsonl",
            dictionary=d,
            results=results,
            results_key="r",
        )
    store = tmp_path / "receipts.sqlite"
    rs.append_receipts(receipts, path=store)
    assert _protected() == before
    assert [p.name for p in tmp_path.iterdir() if not p.name.startswith("receipts.sqlite")] == []
    keys: set[str] = set()
    for r in rs.iter_receipts(store):
        _keys(r, keys)
    assert not (keys & FORBIDDEN_FIELD_LITERALS), keys & FORBIDDEN_FIELD_LITERALS
