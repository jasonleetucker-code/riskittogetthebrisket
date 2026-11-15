"""AMATH-S27 — ``config/trade/faab.json`` fails closed, and nothing in it is inert.

Before this, a missing file loaded as ``{}`` and a missing key was silently
replaced by an in-code default (``FaabConfig.num``), so a corrupt config changed
bids without anything announcing it.  The load boundary now raises one named
error, ``FaabConfigError``, listing every offending ``section.key``.

Companion to ``test_faab_config_parity.py`` (in-code call-site defaults equal the
shipped values) -- that test keeps the documentation literals honest, this one
makes them unreachable.
"""

from __future__ import annotations

import ast
import copy
import json
import pathlib

import pytest

from src.trade import faab_engine as FE
from src.utils.config_loader import repo_root

ROOT = repo_root()
CONFIG_PATH = ROOT / "config" / "trade" / "faab.json"


@pytest.fixture()
def shipped() -> dict:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def _write(tmp_path: pathlib.Path, payload) -> pathlib.Path:
    path = tmp_path / "faab.json"
    path.write_text(payload if isinstance(payload, str) else json.dumps(payload), encoding="utf-8")
    return path


# ── fail closed ──────────────────────────────────────────────────────


def test_the_shipped_config_validates_and_loads():
    FE.validate_faab_config(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
    assert FE.load_faab_config(refresh=True)["schemaVersion"] == FE.CONFIG_SCHEMA_VERSION
    assert isinstance(FE.FaabConfig().raw, dict)


def test_a_missing_file_is_a_named_refusal_not_an_empty_config(tmp_path):
    with pytest.raises(FE.FaabConfigError, match="file not found"):
        FE.load_faab_config(tmp_path / "nope.json")


@pytest.mark.parametrize("text", ["{not json", "", "[1, 2]", "null", '"text"'])
def test_unparseable_or_non_object_json_is_refused(tmp_path, text):
    with pytest.raises(FE.FaabConfigError):
        FE.load_faab_config(_write(tmp_path, text))


@pytest.mark.parametrize(
    "section, key, kind", FE._REQUIRED_CONFIG, ids=[f"{s}.{k}" for s, k, _ in FE._REQUIRED_CONFIG]
)
def test_every_required_key_missing_is_refused_by_name(tmp_path, shipped, section, key, kind):
    broken = copy.deepcopy(shipped)
    del broken[section][key]
    with pytest.raises(FE.FaabConfigError, match=f"{section}\\.{key}: missing"):
        FE.load_faab_config(_write(tmp_path, broken))


def test_a_missing_section_is_refused(tmp_path, shipped):
    broken = copy.deepcopy(shipped)
    del broken["market"]
    with pytest.raises(FE.FaabConfigError, match="market: section missing"):
        FE.load_faab_config(_write(tmp_path, broken))


@pytest.mark.parametrize(
    "section, key, bad",
    [
        ("market", "rivalSigma", "1.1"),  # a string is not a number
        ("market", "rivalSigma", True),  # nor is a bool
        ("market", "rivalSigma", 0),  # sigma must be positive
        ("market", "rivalSigma", float("nan")),
        ("bidPolicy", "minEdge", 1.5),  # a share outside [0, 1]
        ("bidPolicy", "searchGridPoints", -3),
        ("market", "aggressionClamp", [2.0, 0.5]),  # inverted bounds
        ("market", "aggressionClamp", [1.0]),
        ("market", "rivalNeedEngagementMultiplier", {"neutral": 1.0}),
        ("bidPolicy", "riskPosture", {"balanced": 1.0}),
        ("bidPolicy", "defaultRiskPosture", "reckless"),
        ("leagueRules", "zeroBidAllowed", "yes"),
        ("anchors", "excludedPositions", "K"),
    ],
)
def test_mistyped_or_out_of_range_values_are_refused(tmp_path, shipped, section, key, bad):
    broken = copy.deepcopy(shipped)
    broken[section][key] = bad
    with pytest.raises(FE.FaabConfigError, match=f"{section}\\.{key}"):
        FE.load_faab_config(_write(tmp_path, broken))


def test_the_schema_version_is_a_named_invariant(tmp_path, shipped):
    broken = copy.deepcopy(shipped)
    broken["schemaVersion"] = 2
    with pytest.raises(FE.FaabConfigError, match="schemaVersion"):
        FE.load_faab_config(_write(tmp_path, broken))
    del broken["schemaVersion"]
    with pytest.raises(FE.FaabConfigError, match="schemaVersion"):
        FE.load_faab_config(_write(tmp_path, broken))


def test_every_problem_is_reported_at_once(tmp_path, shipped):
    broken = copy.deepcopy(shipped)
    del broken["market"]["rivalSigma"]
    del broken["bidPolicy"]["minEdge"]
    broken["ceilingCurve"]["toeExponent"] = "x"
    with pytest.raises(FE.FaabConfigError) as err:
        FE.load_faab_config(_write(tmp_path, broken))
    text = str(err.value)
    assert "(3)" in text
    for needle in ("market.rivalSigma", "bidPolicy.minEdge", "ceilingCurve.toeExponent"):
        assert needle in text


def test_an_explicit_partial_config_object_is_refused_too():
    with pytest.raises(FE.FaabConfigError):
        FE.FaabConfig({"market": {"rivalSigma": 1.1}})
    with pytest.raises(FE.FaabConfigError):
        FE.FaabConfig({})


def test_a_failed_reload_raises_and_never_serves_a_default(tmp_path, monkeypatch, shipped):
    good = FE.load_faab_config(refresh=True)
    broken = copy.deepcopy(shipped)
    del broken["market"]["rivalSigma"]
    monkeypatch.setattr(FE, "_CONFIG_PATH", _write(tmp_path, broken))
    with pytest.raises(FE.FaabConfigError, match="market.rivalSigma"):
        FE.load_faab_config(refresh=True)
    # The process-level cache was not replaced by anything partial.
    monkeypatch.undo()
    assert FE.load_faab_config() is good or FE.load_faab_config() == good


def test_a_valid_config_changes_nothing(tmp_path, shipped):
    """Present-and-valid is byte-for-byte the shipped model: loading it through the
    explicit-path route returns exactly the file's content."""
    assert FE.load_faab_config(_write(tmp_path, shipped)) == shipped
    assert FE.FaabConfig(shipped).raw == shipped


# ── nothing is inert, nothing read is unvalidated ───────────────────

#: Keys the engine reads with a NON-literal second argument (a status / need /
#: posture name chosen at run time), so the literal-call scan below cannot see
#: them.  Each is still a read; listing them here is what lets the inert-key test
#: be strict about everything else.
_DYNAMIC_READS = {
    ("competitiveStatus", "contender"),
    ("competitiveStatus", "bubble"),
    ("competitiveStatus", "rebuilder"),
    ("competitiveStatus", "eliminated"),
    ("positionalNeed", "starterHole"),
    ("positionalNeed", "need"),
    ("positionalNeed", "neutral"),
    ("positionalNeed", "surplus"),
    ("market", "rivalNeedEngagementMultiplier"),
    ("market", "aggressionClamp"),
    ("bidPolicy", "riskPosture"),
}


def _literal_reads(sections: set[str]) -> set[tuple[str, str]]:
    found: set[tuple[str, str]] = set()
    for path in list((ROOT / "src").rglob("*.py")) + list((ROOT / "scripts").rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in ("num", "get")
                and len(node.args) >= 2
            ):
                continue
            a, b = node.args[0], node.args[1]
            if (
                isinstance(a, ast.Constant)
                and isinstance(b, ast.Constant)
                and isinstance(a.value, str)
                and isinstance(b.value, str)
                and a.value in sections
            ):
                found.add((a.value, b.value))
    return found


def _config_leaves(shipped: dict) -> set[tuple[str, str]]:
    return {
        (section, key)
        for section, block in shipped.items()
        if isinstance(block, dict)
        for key in block
        if not key.startswith("_")
    }


def test_no_shipped_config_key_is_inert(shipped):
    reads = _literal_reads({s for s, b in shipped.items() if isinstance(b, dict)}) | _DYNAMIC_READS
    inert = sorted(f"{s}.{k}" for s, k in _config_leaves(shipped) - reads)
    assert not inert, f"config keys that nothing reads (delete or name as invariants): {inert}"


def test_every_shipped_key_is_validated_and_every_validated_key_exists(shipped):
    required = {(s, k) for s, k, _ in FE._REQUIRED_CONFIG}
    leaves = _config_leaves(shipped)
    assert leaves - required == set(), f"unvalidated config keys: {sorted(leaves - required)}"
    assert (
        required - leaves == set()
    ), f"validated keys absent from config: {sorted(required - leaves)}"


def test_every_key_the_code_reads_is_in_the_required_table(shipped):
    sections = {s for s, b in shipped.items() if isinstance(b, dict)}
    required = {(s, k) for s, k, _ in FE._REQUIRED_CONFIG}
    unvalidated = sorted(f"{s}.{k}" for s, k in _literal_reads(sections) - required)
    assert not unvalidated, f"read by code but not validated at load: {unvalidated}"


def test_underscore_keys_are_comments_or_named_invariants_only(shipped):
    """The two former "switches" that were hard-coded behaviour live on as
    ``_invariantNotAToggle_*`` -- named so nobody mistakes them for a setting."""
    for section, block in shipped.items():
        if not isinstance(block, dict):
            continue
        for key in block:
            if key.startswith("_"):
                assert (
                    key.endswith("Comment")
                    or key == "_comment"
                    or key.startswith("_invariantNotAToggle_")
                ), f"{section}.{key}"
    market = shipped["market"]
    assert "unknownBalanceAssumption" not in market
    assert "regularSeasonWeeks" not in shipped["seasonPhase"]
    assert "defaultPlayoffWeekStart" not in shipped["seasonPhase"]
    assert "applyToObjectiveValue" not in shipped["positionalNeed"]
