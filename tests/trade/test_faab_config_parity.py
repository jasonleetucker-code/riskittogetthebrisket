"""Every in-code FAAB default must equal the shipped config value.

``FaabConfig.num`` / ``FaabConfig.get`` substitute a caller-supplied
default rather than raising when a key is missing.  That is deliberate
— a corrupt or partial ``config/trade/faab.json`` should degrade to
documented behaviour instead of taking the waiver page down — but it
means those literals are a second, silent source of truth.  If they
drift from the config, the fallback path stops matching the documented
model and nothing announces it.

This test parses the engine for every ``num("section", "key", default)``
call and asserts the default matches ``faab.json``.  It is deliberately
source-scanning rather than a hand-maintained list: a hand-maintained
list is exactly the thing that goes stale.
"""

from __future__ import annotations

import ast

import pytest

from src.trade.faab_engine import FaabConfig, load_faab_config
from src.utils.config_loader import repo_root


ENGINE_PATH = repo_root() / "src" / "trade" / "faab_engine.py"
COMPARABILITY_PATH = repo_root() / "src" / "trade" / "faab_comparability.py"
CONFIG_PATH = repo_root() / "config" / "trade" / "faab.json"

#: Every module that reads ``faab.json`` through the substituting accessor.
#: A module added here is scanned; a module NOT added here can drift silently,
#: which is the whole failure mode this file exists to prevent.
SCANNED_PATHS = (ENGINE_PATH, COMPARABILITY_PATH)


def _literal(node: ast.AST):
    """Return the constant value of ``node``, or a sentinel when it is
    not a literal (e.g. a computed default we cannot compare)."""
    try:
        return ast.literal_eval(node)
    except (ValueError, TypeError, SyntaxError):
        return _NOT_LITERAL


_NOT_LITERAL = object()


def _config_defaults() -> list[tuple[str, str, object, int, str]]:
    """``(section, key, in_code_default, lineno, filename)`` for every
    ``self.num(...)`` / ``cfg.num(...)`` / ``config.num(...)`` call in a
    scanned module that passes three literal arguments."""
    found: list[tuple[str, str, object, int, str]] = []
    for path in SCANNED_PATHS:
        found.extend(_defaults_in(path))
    return found


def _defaults_in(path) -> list[tuple[str, str, object, int, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: list[tuple[str, str, object, int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute) or func.attr not in ("num", "get"):
            continue
        if len(node.args) != 3:
            continue
        section, key, default = (_literal(a) for a in node.args)
        if not isinstance(section, str) or not isinstance(key, str):
            continue
        if default is _NOT_LITERAL:
            continue
        found.append((section, key, default, node.lineno, path.name))
    return found


def test_the_scanner_actually_finds_calls():
    """Guard against the parity test silently passing because the AST
    walk stopped matching anything."""
    assert len(_config_defaults()) >= 15


@pytest.mark.parametrize(
    "section,key,default,lineno,filename",
    _config_defaults(),
    ids=lambda v: str(v) if not isinstance(v, int) else f"L{v}",
)
def test_in_code_default_matches_shipped_config(section, key, default, lineno, filename):
    raw = load_faab_config()
    block = raw.get(section)
    assert isinstance(block, dict), (
        f"{filename}:{lineno} reads section {section!r}, "
        f"which is missing from {CONFIG_PATH.name}"
    )
    assert key in block, (
        f"{filename}:{lineno} reads {section}.{key!r} with an in-code "
        f"default of {default!r}, but that key is absent from {CONFIG_PATH.name}. "
        "Either add it to the config or drop the fallback."
    )
    shipped = block[key]
    expected = pytest.approx(default) if isinstance(default, (int, float)) else default
    assert shipped == expected, (
        f"{filename}:{lineno} defaults {section}.{key} to {default!r} "
        f"but {CONFIG_PATH.name} ships {shipped!r}.  A missing config would "
        "silently change the model."
    )


def test_the_comparability_owner_is_actually_scanned():
    """The scanner must reach every module that reads the config, not just
    the engine — an unscanned reader is exactly the silent second source of
    truth this file exists to prevent."""
    assert any(row[4] == COMPARABILITY_PATH.name for row in _config_defaults())


def test_config_is_valid_json_and_versioned():
    raw = load_faab_config()
    assert raw.get("schemaVersion") == 1
    for required in (
        "anchors",
        "ceilingCurve",
        "dropCost",
        "seasonPhase",
        "positionalNeed",
        "market",
        "bidPolicy",
        "leagueRules",
        "confidence",
        "crowdComparability",
    ):
        assert isinstance(raw.get(required), dict), f"missing config section {required}"


def test_every_section_documents_itself():
    """Each block carries a ``_comment`` explaining the derivation —
    the brief's 'avoid unexplained magic numbers' requirement, enforced
    rather than trusted."""
    raw = load_faab_config()
    for name, block in raw.items():
        if not isinstance(block, dict) or name == "_comment":
            continue
        has_comment = any(k.startswith("_") and "comment" in k.lower() for k in block)
        assert has_comment, f"config section {name!r} has no _comment explaining its values"


def test_engine_contains_no_unexplained_tuning_literals():
    """The engine must not carry a numeric tunable outside a config
    default.  Scans module-level assignments for bare floats."""
    tree = ast.parse(ENGINE_PATH.read_text(encoding="utf-8"))
    offenders = []
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        value = _literal(node.value)
        if isinstance(value, float):
            names = [t.id for t in node.targets if isinstance(t, ast.Name)]
            offenders.extend(names)
    assert not offenders, (
        f"module-level float constants in {ENGINE_PATH.name}: {offenders}. "
        "Tunables belong in config/trade/faab.json."
    )


def test_config_defaults_round_trip_through_the_accessor():
    cfg = FaabConfig()
    assert cfg.num("ceilingCurve", "toeExponent", -1.0) > 0
    # A genuinely absent key falls back, and says so by returning the
    # caller's value rather than None.
    assert cfg.num("ceilingCurve", "notARealKey", 3.5) == 3.5
    assert cfg.get("anchors", "notARealKey", "fallback") == "fallback"
