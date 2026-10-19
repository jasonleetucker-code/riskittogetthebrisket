"""Shadow isolation (spec tests k and l).

(k) Nothing in production imports ``src.league_valuation``: not ``server.py``,
not ``src/api/**``, not any other ``src`` package, not a script, not the
frontend. And the package itself imports only an allow-listed set of owners --
never the withdrawn league-adjusted lens, the feature flags, the server, or a
sibling batch-1 package.

(l) No league is ever resolved implicitly: pins name the league explicitly,
``dynasty_new`` is never selected by omission, and a mismatch fails closed.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from src.league_valuation import challenger
from src.league_valuation.challenger import PinError, build_board_pins, validate_pins
from tests.league_valuation._builders import PARAMS, pins

REPO = Path(__file__).resolve().parents[2]
PACKAGE = REPO / "src" / "league_valuation"

#: module -> names the package may import from it (None = any name).
ALLOWED_SRC_IMPORTS: dict[str, frozenset[str] | None] = {
    "src.canonical.player_valuation": frozenset({"DISPLAY_SCALE_MAX", "DISPLAY_SCALE_MIN"}),
    "src.history.keys": frozenset({"asset_key_for_contract_row"}),
    "src.utils.name_clean": frozenset(
        {
            "POSITION_GROUP_IDP",
            "POSITION_GROUP_OFFENSE",
            "canonical_player_key",
            "canonical_position_group",
            "normalize_position_family",
        }
    ),
    "src.league_intel.scoring_fit": frozenset(
        {"DEPTH_PROBES", "MAX_DEPTH_DRIFT", "MIN_COHORT_SIZE"}
    ),
    "src.api.data_contract": frozenset({"assert_ranking_coherence", "compact_ranks_and_tiers"}),
    "src.league_comparison.sleeper_scoring": frozenset({"scoring_fingerprint"}),
    "src.model_registry.evaluation_receipt": None,
    "src.model_registry.learning_receipt": None,
}


def _imports(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            yield node.module, {a.name for a in node.names}
        elif isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name, set()


def _py_files(root: Path):
    for path in root.rglob("*.py"):
        if "node_modules" in path.parts or ".next" in path.parts:
            continue
        yield path


def test_no_production_module_imports_league_valuation():
    roots = [REPO / "src", REPO / "scripts", REPO / "deploy"]
    offenders = []
    for root in roots:
        if not root.exists():
            continue
        for path in _py_files(root):
            if PACKAGE in path.parents:
                continue
            for module, _names in _imports(path):
                if module == "src.league_valuation" or module.startswith("src.league_valuation."):
                    offenders.append(str(path.relative_to(REPO)))
    server = REPO / "server.py"
    for module, _names in _imports(server):
        if module.startswith("src.league_valuation"):
            offenders.append("server.py")
    assert offenders == [], offenders


def test_frontend_never_references_league_valuation():
    frontend = REPO / "frontend"
    hits = []
    for ext in ("*.js", "*.jsx", "*.ts", "*.tsx", "*.mjs"):
        for path in frontend.rglob(ext):
            if "node_modules" in path.parts or ".next" in path.parts:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            if "league_valuation" in text or "leagueFairValue" in text or "fairValueBoard" in text:
                hits.append(str(path.relative_to(REPO)))
    assert hits == [], hits


def test_package_imports_only_allow_listed_owners():
    for path in PACKAGE.glob("*.py"):
        for module, names in _imports(path):
            if not module.startswith("src."):
                continue
            if module.startswith("src.league_valuation"):
                continue
            assert module in ALLOWED_SRC_IMPORTS, f"{path.name} imports {module}"
            allowed = ALLOWED_SRC_IMPORTS[module]
            if allowed is not None:
                assert names <= allowed, f"{path.name} imports {names - allowed} from {module}"


def _code_strings(path: Path):
    """String literals that are code, not docstrings."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docstrings = {
        id(node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
    }
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in docstrings
        ):
            yield node.value


def test_package_never_touches_the_withdrawn_lens_or_serving_seams():
    forbidden_modules = (
        "src.league_intel.overlay",
        "src.league_intel.adjustment",
        "src.league_intel.publish",
        "src.api.feature_flags",
        "src.api.gameplan",
        "src.bdvm.market",
        "src.bestball",
        "src.evidence_lineage",
        "src.trade",
        "server",
    )
    for path in PACKAGE.glob("*.py"):
        for module, names in _imports(path):
            assert not any(
                module == f or module.startswith(f + ".") for f in forbidden_modules
            ), f"{path.name} imports {module}"
            assert "_valuation_scoped_contract" not in names
        for literal in _code_strings(path):
            # No league is named in code: nothing can default to one.
            assert "dynasty_new" not in literal and "dynasty_main" not in literal, path.name
            assert "experimentalLeagueAdjusted" not in literal, path.name


def test_league_key_is_required_and_never_defaulted():
    sig = inspect.signature(build_board_pins)
    assert sig.parameters["league_key"].default is inspect.Parameter.empty
    assert sig.parameters["league_key"].kind is inspect.Parameter.KEYWORD_ONLY
    bad = pins()
    bad.pop("leagueKey")
    with pytest.raises(PinError):
        validate_pins(bad, PARAMS)
    with pytest.raises(PinError):
        validate_pins(dict(pins(), leagueKey=""), PARAMS)


def _contract(league_key="dynasty_main"):
    return {
        "contractVersion": "2026-03-10.v2",
        "generatedAt": "2026-10-19T10:00:00Z",
        "meta": {"leagueKey": league_key},
        "sleeper": {"scoringSettings": {"rec": 0.08, "pass_td": 6.0, "bonus_rec_te": 0.0}},
    }


def _bdvm(league_key="dynasty_main"):
    return {
        "status": "ok",
        "meta": {
            "leagueKey": league_key,
            "modelVersion": "bdvm-1.0.0",
            "paramSetId": "params_v1:abc",
            "projectionSnapshot": {"asOf": "2026-10-14T06:10:00+00:00"},
        },
    }


def test_build_board_pins_reads_every_pin_from_its_artifact():
    out = build_board_pins(
        _contract(),
        _bdvm(),
        league_key="dynasty_main",
        format_fingerprint="tmf1:00ff",
        params=PARAMS,
    )
    assert out["leagueKey"] == "dynasty_main"
    assert out["scoringFingerprint"].startswith("sf1:")
    assert out["challengerParamSetId"] == PARAMS["paramSetId"]


@pytest.mark.parametrize(
    "contract,bdvm,league_key,fmt",
    [
        (_contract("dynasty_new"), _bdvm(), "dynasty_main", "tmf1:00ff"),
        (_contract(), _bdvm("dynasty_new"), "dynasty_main", "tmf1:00ff"),
        (_contract(), _bdvm(), "", "tmf1:00ff"),
        (_contract(), _bdvm(), "dynasty_main", None),
        ({**_contract(), "sleeper": {}}, _bdvm(), "dynasty_main", "tmf1:00ff"),
        (
            {
                **_contract(),
                "meta": {"leagueKey": "dynasty_main", "scoringFingerprint": "sf1:wrong"},
            },
            _bdvm(),
            "dynasty_main",
            "tmf1:00ff",
        ),
    ],
)
def test_unprovable_or_mismatched_pins_fail_closed(contract, bdvm, league_key, fmt):
    with pytest.raises(PinError):
        build_board_pins(
            contract, bdvm, league_key=league_key, format_fingerprint=fmt, params=PARAMS
        )


def test_pins_travel_on_every_value():
    from tests.league_valuation._builders import board, run, shuffled_payload

    rows = board()
    fb = run(rows, shuffled_payload(rows))
    assert all(dict(v.pins) == dict(fb.pins) for v in fb.values.values())
    assert set(challenger.REQUIRED_PIN_KEYS) <= set(fb.pins)
