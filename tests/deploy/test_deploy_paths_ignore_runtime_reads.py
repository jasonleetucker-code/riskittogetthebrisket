"""``deploy.yml``'s ``paths-ignore`` never hides a file production reads.

D-3 (``docs/ops/BACKEND_MEMORY_POLICY_2026-10-21.md`` §6.1) lets a push that
changes only prose or tests skip the deploy, and with it a backend restart.
That is safe only while nothing on the production box reads those files: a
docs file the server reads, left out of a deploy, would keep serving the old
copy until some unrelated push deployed.

The box runs ``server.py`` (importing ``src/`` and, lazily, a few ``scripts/``
fetchers) plus the systemd timers and ``deploy/deploy.sh`` (which run
``scripts/*.py`` from the same checkout).  This test reads that code, collects
every repository path it names under ``docs/`` or ``tests/``, and requires each
one to still START a deploy under the real ``paths-ignore`` list -- the same
GitHub rule ``scripts/deploy_trigger_audit.py`` replays.  Measured when D-3
landed: the server reads ``docs/valuation/evidence/**``,
``docs/measurements/**``, ``docs/sources/SIGNALS_FANTASY_INTEGRATION.md`` (the
model-lab API) and ``docs/owner/*.json`` (trade-advisor permission records), so
none of those is ignored.

A path that is only CITED (published as a reference string, never opened) is
listed in ``CITATION_ONLY`` with the reason; a stale entry fails too, so the
list cannot outlive the code it excuses.
"""

from __future__ import annotations

import ast
from functools import lru_cache
from pathlib import Path
import re

import pytest

from scripts import deploy_trigger_audit as audit

REPO = Path(__file__).resolve().parents[2]
IGNORE = audit.load_paths_ignore(REPO / ".github" / "workflows" / "deploy.yml")

#: The steward is an operator CLI (``python -m src.steward``): nothing the box
#: runs imports it (pinned below), and it reads the planning documents by
#: design.  Excluded from the runtime scan for that reason only.
CLI_ONLY_PACKAGES = ("src/steward/",)

#: (file, path) pairs that are documentation citations inside payload text or
#: reason strings -- never opened.  Each is under an IGNORED path on purpose.
CITATION_ONLY: dict[tuple[str, str], str] = {
    ("src/consensus_edge/api.py", "docs/consensus-edge/METHODOLOGY.md"): (
        "listed in the /api/consensus-edge methodology envelope as a reference"
    ),
    ("src/consensus_edge/api.py", "docs/consensus-edge/DECISIONS.md"): (
        "listed in the /api/consensus-edge methodology envelope as a reference"
    ),
    (
        "src/model_registry/training_manifest.py",
        "docs/valuation/HILL_SOURCE_ALIGNMENT_AUDIT_2026-09-24.md",
    ): "interpolated into NOT_HILL_BOARDS reason strings",
}

#: Directories whose ONLY reader accepts a fixed set of suffixes, so the probe
#: uses those suffixes rather than a generic file.  Each reader restriction is
#: pinned by its own test below.
DIRECTORY_SUFFIXES: dict[tuple[str, str], tuple[str, ...]] = {
    # _resolve_record_path refuses anything but ``.json`` inside docs/owner,
    # which is why ``docs/owner/*.md`` (the owner's decision prose) may be ignored.
    ("src/trade/public_advisor_permission.py", "docs/owner"): (".json",),
}

_PATH_CONSTANT = re.compile(r"^(docs|tests)/[^\s]*$")
_SCRIPT_REF = re.compile(r"scripts[/.]([A-Za-z0-9_]+)")


def _box_scripts() -> list[Path]:
    """``scripts/*.py`` the box executes: systemd units, deploy scripts, and the
    fetchers ``server.py`` imports lazily."""
    names: set[str] = set()
    for pattern in ("deploy/*.sh", "deploy/**/*.sh", "deploy/systemd/*.template"):
        for path in REPO.glob(pattern):
            names.update(_SCRIPT_REF.findall(path.read_text(encoding="utf-8")))
    server = (REPO / "server.py").read_text(encoding="utf-8")
    names.update(re.findall(r"from scripts import ([A-Za-z0-9_]+)", server))
    return sorted(p for n in names if (p := REPO / "scripts" / f"{n}.py").is_file())


def _runtime_files() -> list[Path]:
    files = [REPO / "server.py", REPO / "Dynasty Scraper.py"]
    files += [
        p
        for p in sorted((REPO / "src").rglob("*.py"))
        if not p.relative_to(REPO).as_posix().startswith(CLI_ONLY_PACKAGES)
    ]
    return files + _box_scripts()


def _docstring_ids(tree: ast.AST) -> set[int]:
    return {
        id(node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
    }


@lru_cache(maxsize=None)
def _parsed() -> tuple[tuple[str, ast.AST], ...]:
    out = []
    for path in _runtime_files():
        rel = path.relative_to(REPO).as_posix()
        out.append((rel, ast.parse(path.read_text(encoding="utf-8"), filename=rel)))
    return tuple(out)


@lru_cache(maxsize=None)
def _named_paths() -> tuple[tuple[str, int, str], ...]:
    found = []
    for rel, tree in _parsed():
        skip = _docstring_ids(tree)
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
                continue
            if id(node) in skip:
                continue
            if _PATH_CONSTANT.match(node.value):
                found.append((rel, node.lineno, node.value.rstrip("/")))
    return tuple(found)


def _bare_segment_joins() -> list[str]:
    """``something / "docs"`` -- a join this scan cannot resolve to a path."""
    hits = []
    for rel, tree in _parsed():
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.BinOp)
                and isinstance(node.op, ast.Div)
                and isinstance(node.right, ast.Constant)
                and node.right.value in ("docs", "tests")
            ):
                hits.append(f"{rel}:{node.lineno}")
    return hits


def _probes(rel: str, named: str) -> list[str]:
    """A named file, or representative files inside a named directory."""
    if Path(named).suffix:
        return [named]
    suffixes = DIRECTORY_SUFFIXES.get((rel, named))
    if suffixes is not None:
        return [f"{named}/probe{suffix}" for suffix in suffixes]
    return [f"{named}/probe.json", f"{named}/PREREGISTRATION.md"]


def test_the_scan_sees_the_known_runtime_reads():
    # Guards the scan itself: if it stopped finding these, the property below
    # would pass vacuously.
    named = {p for _, _, p in _named_paths()}
    for expected in (
        "docs/owner",
        "docs/measurements",
        "docs/sources/SIGNALS_FANTASY_INTEGRATION.md",
        "docs/valuation/evidence/sparse-evidence-2026-10-01",
    ):
        assert expected in named, expected


def test_no_path_production_reads_is_ignored_by_the_deploy_trigger():
    offenders = []
    for rel, line, named in _named_paths():
        if (rel, named) in CITATION_ONLY:
            continue
        for probe in _probes(rel, named):
            if not audit.push_starts_deploy([probe], IGNORE):
                offenders.append(
                    f"{rel}:{line} names {named!r}; a push of {probe!r} would not deploy"
                )
    assert not offenders, (
        "deploy.yml paths-ignore hides a path the production box reads; remove it from "
        "paths-ignore (or, if it is only cited, add it to CITATION_ONLY with the reason):\n"
        + "\n".join(offenders)
    )


def test_no_unresolvable_docs_or_tests_join_in_runtime_code():
    assert not _bare_segment_joins(), (
        "runtime code joins a bare 'docs'/'tests' segment; this scan cannot tell which "
        "files it reads -- name the path as one constant"
    )


def test_citation_only_entries_are_still_present():
    named = {(rel, p) for rel, _, p in _named_paths()}
    stale = [key for key in CITATION_ONLY if key not in named]
    assert not stale, f"CITATION_ONLY entries no longer in the code: {stale}"


def test_owner_record_reader_accepts_json_only():
    from src.trade import public_advisor_permission as perm

    assert perm.RECORD_DIR == "docs/owner"
    assert perm._resolve_record_path("docs/owner/record.json", REPO) is not None
    assert perm._resolve_record_path("docs/owner/DECISIONS.md", REPO) is None


def test_directory_suffix_entries_are_still_present():
    named = {(rel, p) for rel, _, p in _named_paths()}
    stale = [key for key in DIRECTORY_SUFFIXES if key not in named]
    assert not stale, f"DIRECTORY_SUFFIXES entries no longer in the code: {stale}"


def test_cli_only_packages_are_not_run_on_the_box():
    server = (REPO / "server.py").read_text(encoding="utf-8")
    assert "src.steward" not in server and "src/steward" not in server
    for path in list(REPO.glob("deploy/**/*.sh")) + list(REPO.glob("deploy/**/*.template")):
        text = path.read_text(encoding="utf-8")
        assert "src.steward" not in text and "src/steward" not in text, path
    imported_from_src = [
        p.relative_to(REPO).as_posix()
        for p in (REPO / "src").rglob("*.py")
        if not p.relative_to(REPO).as_posix().startswith(CLI_ONLY_PACKAGES)
        and re.search(r"^\s*(from|import) src\.steward", p.read_text(encoding="utf-8"), re.M)
    ]
    assert not imported_from_src, imported_from_src


@pytest.mark.parametrize(
    "changed",
    [
        ["server.py"],
        ["Dynasty Scraper.py"],
        ["src/api/data_contract.py"],
        ["CSVs/site_raw/dlfSf.csv"],
        ["config/sources/freshness_v1.json"],
        ["config/model_registry/hill_scope_masters.json"],
        ["deploy/deploy.sh"],
        ["deploy/systemd/README.md"],
        ["scripts/fetch_dlf.py"],
        ["frontend/app/page.jsx"],
        ["frontend/lib/trade-logic.js"],
        ["frontend/package-lock.json"],
        [".github/workflows/deploy.yml"],
        ["requirements.lock.txt"],
        ["docs/owner/brisket_trade_advisor_permission.json"],
        ["docs/valuation/evidence/sparse-evidence-2026-10-01/results.json"],
        ["docs/valuation/evidence/joint-filter-shadow-2026-10-01/PREREGISTRATION.md"],
        ["docs/measurements/consensus-edge-backtest-2026-08-04-h14.json"],
        ["docs/sources/SIGNALS_FANTASY_INTEGRATION.md"],
        ["docs/brand-new-subtree/notes.md"],
        # a push mixing ignored prose with one runtime file still deploys
        ["docs/EXECUTION_PLAN.md", "tests/api/test_x.py", "src/api/data_contract.py"],
    ],
)
def test_runtime_changes_still_deploy(changed):
    assert audit.push_starts_deploy(changed, IGNORE)


@pytest.mark.parametrize(
    "changed",
    [
        ["tests/api/test_source_overrides.py"],
        ["tests/fixtures/u3_pre_cutover/idpTradeCalc.csv"],
        ["frontend/__tests__/trade-logic.test.js"],
        ["CLAUDE.md"],
        ["docs/EXECUTION_PLAN.md", "docs/WORK_CLAIMS.md"],
        ["docs/trade/NTEAM_TRADE_ENGINE_SPEC.md"],
        ["docs/owner/LVA_OWNER_DECISIONS_2026-10-21.md"],
        ["docs/valuation/LI5_REPLACEMENT_CONSOLIDATION_DESIGN_2026-10-21.md"],
        ["data/scrape_state/x_last_success", "exports/latest/a.json"],
    ],
)
def test_prose_and_test_only_pushes_skip_the_deploy(changed):
    assert not audit.push_starts_deploy(changed, IGNORE)
