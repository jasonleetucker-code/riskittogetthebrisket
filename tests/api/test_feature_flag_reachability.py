"""A feature flag that reports True for capability that cannot execute.

T4-6.  Measured 2026-07-27 by walking imports transitively from
``server.py``: of 13 registered flags, **7 could not affect a request**,
and four of those defaulted True while their registry comments asserted
live behaviour —

    espn_injury_feed          "Safe to activate."
    depth_chart_validation    "Requires injury feed ON to cross-check."
    value_confidence_intervals "Frontend ValueBandBadge renders when
                               field is present"
    positional_tiers          "Frontend TierDivider renders when tierId
                               set"

Each sentence is the kind that reads as verified.  None was.
``ValueBandBadge`` is exported from the ui barrel and mounted on no
page; ``TierDivider`` renders only on /draft off a locally computed
``p.tier`` while the backend never stamps ``tierId``; and both injury
modules are stranded behind imports nobody makes.

WHY THE OBVIOUS TEST WOULD NOT HAVE CAUGHT IT
──────────────────────────────────────────────
"Assert every flag has an ``is_enabled`` call site" passes for
``espn_injury_feed``: it HAS one, inside a module nothing imports.
Existence-of-a-call-site is a proxy for reachability the same way a
substring is a proxy for identity — §6.15's recurring shape, and the
reason this test computes the import graph instead of grepping.

The measurement lives here; the classification lives in
``feature_flags._GATE_STATUS`` as data.  A comment cannot be checked
against reality, so the claim was moved somewhere that can be.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from src.api import feature_flags

REPO_ROOT = Path(__file__).resolve().parents[2]
SERVER = REPO_ROOT / "server.py"


def _module_path(dotted: str) -> Path | None:
    direct = REPO_ROOT / (dotted.replace(".", "/") + ".py")
    if direct.exists():
        return direct
    package = REPO_ROOT / dotted.replace(".", "/") / "__init__.py"
    return package if package.exists() else None


def _dotted_of(path: Path) -> str:
    """The dotted module name for a repo file, for resolving ``from .`` ."""
    parts = list(path.resolve().relative_to(REPO_ROOT).parts)
    if parts[-1] == "__init__.py":
        parts = parts[:-1]
    else:
        parts[-1] = parts[-1][: -len(".py")]
    return ".".join(parts)


def _src_imports(path: Path) -> set[str]:
    """Every ``src.*`` name imported by ``path``, absolute OR relative.

    ``from src.a import b`` yields both ``src.a`` and ``src.a.b`` — the
    second may be a module or just a symbol, and ``_module_path``
    discards the ones that are not files.  Over-collecting here is safe;
    under-collecting would mark a live module unreachable and produce a
    false accusation.

    RELATIVE IMPORTS ADDED 2026-08-18 (#802), and the sentence above is
    why it is a fix rather than a refinement: this walker followed only
    absolute ``src.*`` names, so ``from . import historical_stats`` was
    invisible and **42 modules measured unreachable while being imported
    on every request**.  ``src.league_comparison.sleeper_stats`` is one of
    them — reached from server.py via ``service`` → ``historical_stats``,
    all three hops relative — so a flag gated there measured UNREACHABLE
    and the table would have recorded the false accusation its own
    docstring warns about.

    Verified contained: re-measuring every registered flag with relative
    imports resolved changes exactly one verdict, the new flag's.  No
    existing classification moves, which is what makes this a repair to
    the instrument rather than a re-baseline of its readings.
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):  # pragma: no cover
        return set()

    # The package a bare ``from . import x`` resolves against.  A package
    # __init__ IS its package; a module inside one resolves to its parent.
    dotted = "" if path == SERVER else _dotted_of(path)
    if dotted and (REPO_ROOT / dotted.replace(".", "/") / "__init__.py").exists():
        package = dotted
    else:
        package = dotted.rsplit(".", 1)[0] if "." in dotted else dotted

    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(a.name for a in node.names if a.name.startswith("src"))
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.module.startswith("src"):
                found.add(node.module)
                found.update(f"{node.module}.{a.name}" for a in node.names)
            elif node.level and package:
                base = package
                for _ in range(node.level - 1):
                    base = base.rsplit(".", 1)[0] if "." in base else base
                target = f"{base}.{node.module}" if node.module else base
                if target.startswith("src"):
                    found.add(target)
                    found.update(f"{target}.{a.name}" for a in node.names)
    return found


def _reachable_from_server() -> set[str]:
    """Transitive closure of ``src.*`` modules imported from server.py."""
    seen: set[str] = set()
    stack = [SERVER]
    while stack:
        for dotted in _src_imports(stack.pop()):
            if dotted in seen:
                continue
            path = _module_path(dotted)
            if path is None:
                continue
            seen.add(dotted)
            stack.append(path)
    return seen


def _gate_sites() -> dict[str, set[str]]:
    """``{flag: {repo-relative file with an is_enabled call}}``.

    Only literal-argument calls are collected.  That blind spot is
    checked by :func:`test_no_flag_is_read_through_a_variable` below
    rather than assumed away — an indirect read would make every
    NO_GATE verdict here wrong.
    """
    roots = [SERVER, *(REPO_ROOT / d for d in ("src", "scripts"))]
    files: list[Path] = []
    for root in roots:
        if root.is_file():
            files.append(root)
        elif root.is_dir():
            files.extend(p for p in root.rglob("*.py") if "__pycache__" not in p.parts)

    sites: dict[str, set[str]] = {}
    for path in files:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):  # pragma: no cover
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
            if name != "is_enabled" or not node.args:
                continue
            arg = node.args[0]
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                sites.setdefault(arg.value, set()).add(str(path.relative_to(REPO_ROOT)))
    return sites


def _measure(flag: str, reachable: set[str], sites: dict[str, set[str]]) -> str:
    files = sites.get(flag, set())
    if not files:
        return feature_flags.NO_GATE
    statuses = set()
    for rel in files:
        if rel == "server.py":
            statuses.add(feature_flags.LIVE)
        elif rel.startswith("scripts/"):
            statuses.add(feature_flags.SCRIPT_ONLY)
        elif rel[:-3].replace("/", ".") in reachable:
            statuses.add(feature_flags.LIVE)
        else:
            statuses.add(feature_flags.UNREACHABLE)
    # A flag gated in several places is as live as its most live gate.
    for best in (feature_flags.LIVE, feature_flags.SCRIPT_ONLY, feature_flags.UNREACHABLE):
        if best in statuses:
            return best
    return feature_flags.NO_GATE  # pragma: no cover


# ── The measurement is non-vacuous ───────────────────────────────────


def test_the_import_walk_actually_finds_the_graph():
    """Guard on the guard.

    Every verdict below is a function of this set.  If ``_src_imports``
    silently returned nothing — a parse failure, a moved server.py —
    every flag would read UNREACHABLE and this file would produce a
    spectacular, entirely false bug report.
    """
    reachable = _reachable_from_server()
    assert len(reachable) > 50, f"only {len(reachable)} modules reachable; the walk is broken"
    assert "src.api.data_contract" in reachable
    assert "src.api.feature_flags" in reachable


def test_the_gate_scan_actually_finds_call_sites():
    """Same, for the other half: a scan finding nothing would mark
    every flag NO_GATE."""
    sites = _gate_sites()
    assert len(sites) >= 5, f"only {len(sites)} flags have gates; the scan is broken"
    assert "nfl_data_ingest" in sites


def test_no_flag_is_read_through_a_variable():
    """The scan reads literal arguments only.

    ``is_enabled(some_name)`` would be invisible to it, and every
    NO_GATE verdict would then be unsound.  Production has no such call
    today; this fails if one appears, rather than letting the scan
    quietly go blind.
    """
    # The registry's own ``snapshot`` / ``effective_flags`` call
    # ``is_enabled(name)`` in a comprehension over ``_DEFAULTS``.  Those
    # are reporting helpers that read every flag by construction, not
    # gates on any capability, so they are excluded by identity rather
    # than by pattern — excluding "comprehensions" generally would let a
    # real indirect gate through.
    registry = REPO_ROOT / "src" / "api" / "feature_flags.py"

    offenders: list[str] = []
    for root in (SERVER, REPO_ROOT / "src"):
        files = [root] if root.is_file() else list(root.rglob("*.py"))
        for path in files:
            if "__pycache__" in path.parts or path == registry:
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except (SyntaxError, UnicodeDecodeError):  # pragma: no cover
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                name = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
                if name != "is_enabled" or not node.args:
                    continue
                if not isinstance(node.args[0], ast.Constant):
                    offenders.append(f"{path.relative_to(REPO_ROOT)}:{node.lineno}")
    assert not offenders, (
        f"is_enabled called with a non-literal at {offenders}. The reachability "
        "scan in this module cannot see those, so its NO_GATE verdicts would be "
        "unsound. Use a literal, or teach _gate_sites about the indirection."
    )


# ── The claims ───────────────────────────────────────────────────────


@pytest.mark.parametrize("flag", feature_flags.registered_flags())
def test_declared_gate_status_matches_the_import_graph(flag):
    """``_GATE_STATUS`` is re-derived, not trusted.

    This is the whole point of moving the classification out of comments
    and into data: prose describing a gate cannot be checked, and four
    such comments were wrong at once.
    """
    measured = _measure(flag, _reachable_from_server(), _gate_sites())
    declared = feature_flags.gate_status(flag)
    assert declared == measured, (
        f"{flag} is declared {declared} but measures {measured}. "
        f"Gate sites: {sorted(_gate_sites().get(flag, [])) or 'none'}. "
        "Update _GATE_STATUS, or wire the module if the gate should be live."
    )


@pytest.mark.parametrize("flag", feature_flags.registered_flags())
def test_only_a_live_flag_may_default_on(flag):
    """A flag that cannot affect a request must not advertise itself
    as on.

    This is the assertion that would have caught all four at once, and
    it is the reason ``/api/status``'s flag block was misleading: it
    reports ``enabled`` with no way to tell that seven of the trues
    changed nothing.
    """
    if feature_flags._DEFAULTS[flag]:
        assert feature_flags.gate_status(flag) == feature_flags.LIVE, (
            f"{flag} defaults True but its gate is "
            f"{feature_flags.gate_status(flag)} — it cannot change a response. "
            "Either wire it or default it False."
        )


def test_every_registered_flag_is_classified():
    """Adding a flag without classifying it fails here rather than
    silently defaulting to a status nobody checked."""
    missing = set(feature_flags.registered_flags()) - set(feature_flags._GATE_STATUS)
    extra = set(feature_flags._GATE_STATUS) - set(feature_flags.registered_flags())
    assert not missing, f"unclassified flags: {sorted(missing)}"
    assert not extra, f"_GATE_STATUS names unregistered flags: {sorted(extra)}"


def test_gate_status_rejects_an_unknown_flag():
    with pytest.raises(KeyError):
        feature_flags.gate_status("no_such_flag")


# ── The reporting surface ────────────────────────────────────────────


def test_effective_flags_reports_both_halves():
    """ "Is it on?" is the misleading question on its own.  Seven flags
    answer it True-or-False identically regardless of whether they do
    anything."""
    effective = feature_flags.effective_flags()
    assert set(effective) == set(feature_flags.registered_flags())
    for name, row in effective.items():
        assert row["enabled"] is feature_flags.is_enabled(name)
        assert row["gateStatus"] == feature_flags.gate_status(name)
    # Non-vacuity: the split must actually distinguish something, or
    # this surface is decoration too.
    statuses = {row["gateStatus"] for row in effective.values()}
    assert len(statuses) > 1, "every flag has the same gate status; the field says nothing"


def test_the_walker_follows_relative_imports():
    """Non-vacuity for the relative-import resolution (#802).

    ``src.league_comparison.sleeper_stats`` is reached from server.py only
    through relative imports (``service`` → ``historical_stats`` →
    ``sleeper_stats``).  An absolute-only walker measured it, and 41 other
    live modules, as unreachable — the "false accusation" ``_src_imports``
    exists to avoid.
    """
    reachable = _reachable_from_server()
    for module in (
        "src.league_comparison.historical_stats",
        "src.league_comparison.sleeper_stats",
        "src.news.service",
    ):
        assert module in reachable, f"{module} is imported on every request but measured unreachable"


def test_relative_resolution_did_not_reclassify_an_existing_flag():
    """A repair to the instrument must not silently re-baseline its readings.

    Every flag's declared status is re-derived above; this states the
    stronger property that the walker change moved exactly one verdict —
    the flag it was made for — rather than quietly promoting a stranded
    gate to LIVE.
    """
    reachable = _reachable_from_server()
    sites = _gate_sites()
    for flag in feature_flags.registered_flags():
        if flag == "host_native_scoring":
            continue
        assert _measure(flag, reachable, sites) == feature_flags.gate_status(flag), flag
