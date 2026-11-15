"""The pinned board stays pinned, private and deterministic -- and stays used.

Five production deploy freezes in three weeks (#2172, #2199 and the three
before) had one cause: a blocking test whose result depended on the latest
data refresh.  ``tests.archive_fixtures.newest_complete_*`` hand out the
NEWEST complete archive, and a build with ``csv_root=None`` reads TODAY's
``CSVs/site_raw`` and ``data/scrape_state`` beside it.  The pinned board
(``tests/fixtures/pinned_board/board.zip``, built by
``tests/pinned_board_build.py``) freezes one complete board's full inputs.

These tests keep that true:

* the fixture is intact, complete and in the phase the slotted-class tests
  need, and carries no real manager, team, league or draft identifier (the
  repository is public);
* a pinned build is deterministic (same contract hash twice), independent of
  the wall clock apart from its ``generatedAt`` stamps, and HERMETIC (opens
  nothing under the live ``CSVs`` / ``data`` / ``exports`` trees);
* no hard-gate test reaches for the newest-archive helpers again, and no
  module that pins its whole run to the board carries a ``livedata`` test.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from tests import archive_fixtures as af
from tests import pinned_board_build as pb

REPO = Path(__file__).resolve().parents[1]
TESTS = REPO / "tests"

_NEWEST_HELPERS = {"newest_complete_raw_payload", "newest_complete_contract"}

#: Hard-gate modules that may still call a newest-archive helper outside a
#: ``livedata`` scope, each with the reason it must.  Empty by design: a test
#: about the latest refresh is ``livedata`` (its own marker exempts it here),
#: and every other board test uses the pinned helpers.  Adding an entry is a
#: reviewed decision -- the entry is the reason a deploy can freeze on data.
_NEWEST_HELPER_ALLOWLIST: dict[str, str] = {}


def _contract_digest(contract: dict) -> str:
    return hashlib.sha256(
        json.dumps(contract, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


# ── The fixture ────────────────────────────────────────────────────────────


def test_fixture_is_intact_complete_and_slotted():
    manifest = af.pinned_board_manifest()
    assert manifest["schemaVersion"] == pb.SCHEMA_VERSION
    assert re.fullmatch(r"[0-9a-f]{40}", manifest["sourceCommit"])
    root = af.pinned_board_root()  # verifies every sha256 and the file set
    csvs = sorted(p.name for p in (root / "CSVs" / "site_raw").glob("*.csv"))
    assert len(csvs) == manifest["csvCount"] >= 25, csvs
    states = list((root / "data" / "scrape_state").iterdir())
    assert len(states) == manifest["stateFileCount"] > 0
    payload, label = af.pinned_board_payload()
    assert label == f"pinned:{manifest['archive']}"
    assert payload["scrapeTimestamp"] == manifest["asOf"]
    assert af.pinned_board_as_of() == datetime.fromisoformat(manifest["asOf"])
    assert not af._degraded_critical_sources(payload), "the pinned board must be complete"
    # The slotted-class tests (rookie tether, confidence naming) assert this
    # rather than skip, so a re-pin outside the phase fails loudly here too.
    assert af.has_published_slot_class(payload)
    teams = payload["sleeper"]["teams"]
    assert len(teams) >= 4, "the multi-team tests need >= 4 rosters"
    assert any(t.get("pickDetails") for t in teams), "no team owns a pick on the pinned board"


def test_fixture_bytes_are_reproducible_from_their_own_manifest(tmp_path):
    """The zip is deterministic: rewriting its own entries reproduces the same
    entries in the same order with the same timestamps and CRCs, so a refresh
    diff is only ever a content change.  (Compared per entry, not as raw zip
    bytes: deflate output may differ between zlib builds.)"""
    with zipfile.ZipFile(af.PINNED_BOARD_ZIP) as zf:
        manifest = json.loads(zf.read("manifest.json"))
        files = {n: zf.read(n) for n in zf.namelist() if n != "manifest.json"}
    for name, data in files.items():
        assert hashlib.sha256(data).hexdigest() == manifest["files"][name], name
    assert set(files) == set(manifest["files"])
    out = tmp_path / "board.zip"
    pb.write_zip(files, manifest, out)

    def entries(path: Path) -> list[tuple]:
        with zipfile.ZipFile(path) as zf:
            return [(i.filename, i.date_time, i.CRC, i.file_size) for i in zf.infolist()]

    assert entries(out) == entries(af.PINNED_BOARD_ZIP)


def test_fixture_carries_no_real_identifier():
    """Every manager, team, league and draft identifier is a labelled
    synthetic stand-in; no email address anywhere in the fixture."""
    payload, _ = af.pinned_board_payload()
    sleeper = payload["sleeper"]
    synthetic_id = re.compile(
        rf"^(?:{pb.SYNTHETIC_LEAGUE_ID}|{pb.SYNTHETIC_ID_PREFIX}[1-4]\d{{4}})$"
    )
    synthetic_name = re.compile(r"^(?:Manager \d{2}|Team \d{2}|Former Manager \d{2})$")
    assert sleeper["leagueId"] == pb.SYNTHETIC_LEAGUE_ID
    assert sleeper.get("leagueName") in (None, pb.SYNTHETIC_LEAGUE_NAME)
    for team in sleeper["teams"]:
        rid = int(team["roster_id"])
        assert team["name"] == pb.manager_name(rid)
        assert team.get("sleeperTeamName") in (None, pb.team_name(rid))
        assert synthetic_id.match(str(team["ownerId"])), team["ownerId"]
        for detail in team.get("pickDetails") or []:
            if detail.get("fromTeam"):
                assert synthetic_name.match(detail["fromTeam"]), detail["fromTeam"]
    for trade in sleeper.get("trades") or []:
        assert synthetic_id.match(str(trade.get("leagueId"))), trade.get("leagueId")
        for side in trade.get("sides") or []:
            assert synthetic_name.match(str(side.get("team"))), side.get("team")
            assert synthetic_id.match(str(side.get("ownerId"))), side.get("ownerId")
    evidence = sleeper.get("draftClassEvidence") or {}
    for value in [evidence.get("sleeperLeagueId"), *(evidence.get("draftListsObserved") or [])]:
        assert value is None or synthetic_id.match(str(value)), value
    for draft in evidence.get("drafts") or []:
        assert synthetic_id.match(str(draft["draftId"])), draft["draftId"]
    with zipfile.ZipFile(af.PINNED_BOARD_ZIP) as zf:
        text = "\n".join(zf.read(n).decode("utf-8", "replace") for n in zf.namelist())
    labels = set(re.findall(r"\(from ([^)]*)\)", text))
    assert labels and all(synthetic_name.match(x) for x in labels), sorted(labels)[:10]
    assert not re.findall(r"[\w.+-]+@[\w-]+\.[a-z]{2,}", text)


# ── The build ──────────────────────────────────────────────────────────────


def test_pinned_build_is_deterministic():
    assert _contract_digest(af.build_pinned_contract()) == _contract_digest(
        af.build_pinned_contract()
    )


def test_pinned_build_reads_no_wall_clock_but_its_stamps():
    """Built under two different frozen clocks, the contracts differ in their
    ``generatedAt`` stamps only.  This is what lets the module-wide
    ``pinned_board_inputs`` fixture leave the clock running: if the build ever
    starts reading the wall clock for a value, this fails."""
    payload, _ = af.pinned_board_payload()
    from src.api.data_contract import build_api_data_contract

    built = []
    for at in (af.pinned_board_as_of(), datetime(2027, 6, 1, 12, tzinfo=timezone.utc)):
        with af.pinned_build_environment(freeze_clock=False) as root, af.frozen_build_clock(at):
            built.append(build_api_data_contract(json.loads(json.dumps(payload)), csv_root=root))
    for contract in built:
        contract.pop("generatedAt", None)
        (contract.get("dataFreshness") or {}).pop("generatedAt", None)
    assert _contract_digest(built[0]) == _contract_digest(built[1])


def test_frozen_clock_restores_every_binding():
    import datetime as dtmod

    from src.api import data_contract as dc

    real = dtmod.datetime
    with af.frozen_build_clock(datetime(2030, 1, 2, tzinfo=timezone.utc)):
        assert dc.datetime.now(timezone.utc).year == 2030
        assert isinstance(real(2020, 1, 1), dc.datetime)  # a real instance still type-checks
    assert dtmod.datetime is real and dc.datetime is real
    assert dtmod.date is af._REAL_DATE


_HERMETIC_PROBE = """
import os, sys
from pathlib import Path
repo = Path(sys.argv[1]).resolve()
live = tuple(os.path.normcase(str(repo / d)) + os.sep for d in ("CSVs", "data", "exports"))
seen, on = [], [False]
def hook(event, args):
    if on[0] and event in ("open", "os.listdir", "os.scandir", "sqlite3.connect") and args:
        try:
            p = os.path.normcase(os.path.abspath(os.fsdecode(args[0])))
        except Exception:
            return
        if p.startswith(live):
            seen.append(p)
sys.addaudithook(hook)
sys.path.insert(0, str(repo))
from tests import archive_fixtures as af
af.pinned_board_root()
on[0] = True
contract = af.build_pinned_contract()
# The module-wide path: NO csv_root, so every default must resolve through
# data_contract._default_input_root to the pinned tree.
from src.api.data_contract import build_api_data_contract
with af.pinned_build_environment(freeze_clock=False):
    default_built = build_api_data_contract(af.pinned_board_payload()[0])
on[0] = False
assert contract.get("playersArray"), "empty build"
for c in (contract, default_built):
    c.pop("generatedAt", None)
    (c.get("dataFreshness") or {}).pop("generatedAt", None)
assert contract == default_built, "a csv_root=None build under the env differs from the pinned build"
print("LIVE_READS=" + repr(sorted(set(seen))))
"""


def test_pinned_build_is_hermetic():
    """A pinned build opens NOTHING under the live ``CSVs`` / ``data`` /
    ``exports`` trees -- measured with an ``open`` audit hook in a fresh
    interpreter, so this process's caches cannot hide a read.  Both paths:
    ``build_pinned_contract`` (explicit ``csv_root``) and a ``csv_root=None``
    build under ``pinned_build_environment`` (the ``pinned_board_inputs``
    module fixture), which must reach the same contract -- that is what proves
    every default in ``data_contract`` resolves through
    ``_default_input_root``."""
    env = dict(os.environ)
    env.update(
        LEAGUE_REGISTRY_PATH="/nonexistent/path/for/tests.json",
        ALLOW_DEFAULT_LOGIN_DEV="1",
        UPTIME_CHECK_ENABLED="0",
    )
    env.pop("SLEEPER_LEAGUE_ID", None)
    env.pop("RISKIT_TEST_SHARD", None)
    out = subprocess.run(
        [sys.executable, "-c", _HERMETIC_PROBE, str(REPO)],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert out.returncode == 0, out.stderr[-2000:]
    line = next(x for x in out.stdout.splitlines() if x.startswith("LIVE_READS="))
    assert line == "LIVE_READS=[]", line


def test_a_test_cannot_quietly_rewrite_the_shared_tree():
    root = af.pinned_board_root()
    target = next((root / "CSVs" / "site_raw").glob("*.csv"))
    original = target.read_bytes()
    try:
        target.write_bytes(original + b"\n")
        with pytest.raises(AssertionError, match="no longer matches its manifest"):
            af.pinned_board_root()
    finally:
        target.write_bytes(original)
    af.pinned_board_root()


# ── The guard ──────────────────────────────────────────────────────────────


def _is_livedata_mark(node: ast.expr) -> bool:
    text = ast.unparse(node)
    return text.endswith("mark.livedata") or text.endswith("mark.livedata()")


def _livedata_modules() -> set[str]:
    from tests.conftest import _LIVEDATA_MODULES

    return set(_LIVEDATA_MODULES)


def _helper_aliases(tree: ast.Module) -> set[str]:
    """Every local name a newest-archive helper is bound to by an import
    (``from tests.archive_fixtures import newest_complete_contract as ncc``
    binds ``ncc``).  The unaliased name is always watched too."""
    aliases = set(_NEWEST_HELPERS)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for item in node.names:
                if item.name in _NEWEST_HELPERS and item.asname:
                    aliases.add(item.asname)
    return aliases


def _newest_helper_uses_outside_livedata(path: Path) -> list[int]:
    """Lines where ``path`` references a newest-archive helper from a scope
    that is not ``@pytest.mark.livedata`` (imports are not uses).  Sees a
    plain name, an attribute (``af.newest_complete_contract``), an import
    alias, and ``getattr(module, "newest_complete_contract")``."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = _helper_aliases(tree)
    module_live = any(
        isinstance(n, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "pytestmark" for t in n.targets)
        and "livedata" in ast.unparse(n.value)
        for n in tree.body
    )
    hits: list[int] = []

    def visit(node: ast.AST, live: bool) -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            live = live or any(_is_livedata_mark(d) for d in node.decorator_list)
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            return
        name = (
            node.id
            if isinstance(node, ast.Name)
            else node.attr
            if isinstance(node, ast.Attribute)
            else node.value
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
            else None
        )
        if name in names and not live:
            hits.append(node.lineno)
        for child in ast.iter_child_nodes(node):
            visit(child, live)

    visit(tree, module_live)
    return hits


def test_no_hard_gate_test_reaches_for_the_newest_archive():
    """The regression guard.  A hard-gate test that needs a real complete
    board uses ``pinned_board_contract`` / ``pinned_board_payload`` /
    ``build_pinned_contract``; one that is about the latest refresh is
    ``livedata``.  Anything else is how a data refresh freezes a deploy."""
    live_modules = _livedata_modules()
    offenders = []
    for path in sorted(TESTS.rglob("*.py")):
        rel = path.relative_to(REPO).as_posix()
        if rel in ("tests/archive_fixtures.py", "tests/test_pinned_board.py"):
            continue
        if path.name in live_modules or rel in _NEWEST_HELPER_ALLOWLIST:
            continue
        lines = _newest_helper_uses_outside_livedata(path)
        if lines:
            offenders.append(f"{rel}:{lines}")
    assert not offenders, (
        "hard-gate tests use the NEWEST-archive helpers (a function of the latest data "
        f"refresh): {offenders}. Use tests.archive_fixtures.pinned_board_* / "
        "build_pinned_contract, or mark a test that is about the latest refresh "
        "@pytest.mark.livedata."
    )


def test_the_allowlist_names_real_modules_with_reasons():
    for rel, reason in _NEWEST_HELPER_ALLOWLIST.items():
        assert (REPO / rel).is_file(), rel
        assert len(reason.strip()) > 20, f"{rel}: give the reason it must read the newest board"


def test_the_guard_sees_a_use(tmp_path):
    """Guard on the guard: the AST scan finds a plain call and ignores one
    under ``@pytest.mark.livedata``."""
    sample = tmp_path / "test_sample.py"
    sample.write_text(
        "import pytest\n"
        "from tests.archive_fixtures import newest_complete_contract\n"
        "def test_a():\n    newest_complete_contract()\n"
        "@pytest.mark.livedata\n"
        "def test_b():\n    newest_complete_contract()\n",
        encoding="utf-8",
    )
    assert _newest_helper_uses_outside_livedata(sample) == [4]


@pytest.mark.parametrize(
    "source, expected",
    [
        (
            "from tests.archive_fixtures import newest_complete_contract as ncc\n"
            "def test_a():\n    ncc()\n",
            [3],
        ),
        (
            "from tests import archive_fixtures as af\n"
            "def test_a():\n    af.newest_complete_raw_payload()\n",
            [3],
        ),
        (
            "from tests import archive_fixtures as af\n"
            'def test_a():\n    getattr(af, "newest_complete_contract")()\n',
            [3],
        ),
        (
            "import tests.archive_fixtures as af\n"
            "def test_a():\n    f = af.newest_complete_contract\n    f()\n",
            [3],
        ),
        (
            "import pytest\nfrom tests.archive_fixtures import newest_complete_contract as ncc\n"
            "@pytest.mark.livedata\ndef test_a():\n    ncc()\n"
            '    getattr(af, "newest_complete_contract")\n',
            [],
        ),
        (
            "from tests.archive_fixtures import pinned_board_contract as pbc\n"
            "def test_a():\n    pbc()\n",
            [],
        ),
    ],
    ids=["import-alias", "attribute", "getattr-string", "attribute-assigned", "livedata", "pinned"],
)
def test_the_guard_resolves_aliases(tmp_path, source, expected):
    sample = tmp_path / "test_sample.py"
    sample.write_text(source, encoding="utf-8")
    assert _newest_helper_uses_outside_livedata(sample) == expected


def _module_pins_whole_run(tree: ast.Module) -> bool:
    return any(
        isinstance(n, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "pytestmark" for t in n.targets)
        and "pinned_board_inputs" in ast.unparse(n.value)
        for n in tree.body
    )


def _carries_livedata(tree: ast.Module) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if any(_is_livedata_mark(d) for d in node.decorator_list):
                return True
        if (
            isinstance(node, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "pytestmark" for t in node.targets)
            and "livedata" in ast.unparse(node.value)
        ):
            return True
    return False


def test_module_wide_pinning_never_covers_a_livedata_test():
    """``pinned_board_inputs`` redirects every default build in a module to
    the pinned tree; a ``livedata`` test there would silently stop reading
    today's board.  Pinning a whole module and live data do not mix."""
    live_modules = _livedata_modules()
    users = []
    for path in sorted(TESTS.rglob("test_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        if not _module_pins_whole_run(tree):
            continue
        users.append(path)
        assert path.name not in live_modules, path
        assert not _carries_livedata(tree), f"{path} pins its whole run but carries a livedata test"
    assert users, "no module uses pinned_board_inputs; the scan is stale"


# ── The guard: a contract build reads pinned CSVs and state ────────────────

#: Hard-gate modules that build a contract WITHOUT the pinned inputs and
#: without an explicit ``csv_root``, each with the reason it must.  Empty by
#: design: ``build_api_data_contract(raw)`` with no ``csv_root`` reads TODAY's
#: ``CSVs/site_raw`` and ``data/scrape_state`` (freshness weighting, source
#: health), so a data refresh can change the result of a "fixed" build -- the
#: archive and the synthetic payload alike.  A new entry needs a measured
#: reason, e.g. "asserts a property of the live board by design" (that test is
#: ``livedata`` instead).
_UNPINNED_BUILD_ALLOWLIST: dict[str, str] = {}

#: ``"<module>::<function>"`` -> reason.  Helpers that build from TODAY's board
#: (``exports/latest``) on purpose.  Unlike a whole-module entry this exempts
#: one function (and the cached getter chain above it), and
#: ``test_live_build_helpers_are_reached_only_from_livedata`` fails if any
#: hard-gate code reaches one, so the exemption cannot leak into a blocking test.
_LIVE_BUILD_HELPERS: dict[str, str] = {
    "tests/api/test_launch_readiness.py::_load_contract": "reads exports/latest for the livedata health floors",
    "tests/api/test_launch_readiness.py::_get": "cached getter over _load_contract, livedata callers only",
    "tests/api/test_pick_refinement.py::_load_contract": "reads exports/latest for the livedata pick checks",
    "tests/api/test_pick_refinement.py::_get": "cached getter over _load_contract, livedata callers only",
    "tests/api/test_picks_end_to_end.py::_load_contract": "reads exports/latest for the livedata pick checks",
    "tests/api/test_source_monitoring.py::_get_live_contract": "reads exports/latest for the livedata source-health floors",
    "tests/api/test_source_monitoring.py::_load_latest_raw": "reads exports/latest for the livedata source-health floors",
    "tests/api/test_player_identity_regression.py::_latest_dynasty_payload": "reads exports/latest for the livedata player-presence checks",
    "tests/api/test_dynasty_nerds_integration.py::_live_dn_csv": "today's scraped CSV, read only by the livedata shape class",
    "tests/api/test_fantasypros_idp_integration.py::_live_fp_csv": "today's scraped CSV, read only by the livedata classes",
    "tests/api/test_fantasypros_idp_integration.py::_fp_csv_rows": "rows of today's scraped CSV, livedata classes only",
}


def _live_helpers_for(rel: str) -> frozenset[str]:
    prefix = rel + "::"
    return frozenset(k[len(prefix) :] for k in _LIVE_BUILD_HELPERS if k.startswith(prefix))


_BUILD_CALLS = {"build_api_data_contract", "build_rankings_delta_payload"}
_PINNING_NAMES = (
    "pinned_board_inputs",
    "pinned_build_environment",
    "build_pinned_contract",
    "pinned_board_contract",
)


def _names_a_pin(node: ast.AST) -> bool:
    """True when ``node``'s subtree references a pinning helper as CODE."""
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name) and sub.id in _PINNING_NAMES:
            return True
        if isinstance(sub, ast.Attribute) and sub.attr in _PINNING_NAMES:
            return True
    return False


def _module_really_pins(tree: ast.Module) -> bool:
    """True only for a module-level ``pytestmark`` / ``usefixtures`` naming the
    fixture (a mention in a docstring or comment does not count)."""
    for node in ast.walk(tree):
        is_marks = isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "pytestmark" for t in node.targets
        )
        is_use = (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "usefixtures"
        )
        if is_marks or is_use:
            for sub in ast.walk(node):
                if isinstance(sub, ast.Constant) and sub.value in _PINNING_NAMES:
                    return True
    return False


def _own_csv_root(call: ast.Call) -> bool:
    """An explicit, non-``None`` ``csv_root=``.  ``**kwargs`` does not count (it
    is how a helper forwards whatever the test passed, usually nothing) and
    ``csv_root=None`` is the default spelled out."""
    for kw in call.keywords:
        if kw.arg == "csv_root":
            return not (isinstance(kw.value, ast.Constant) and kw.value.value is None)
    return False


def _unpinned_builds(path: Path, live_helpers: frozenset[str] = frozenset()) -> list[int]:
    """Lines of contract builds that read TODAY's inputs: no own ``csv_root``,
    not under ``@pytest.mark.livedata``, and not pinned by the module-wide
    fixture, an enclosing ``with pinned_build_environment()``, or an enclosing
    function / class that names a pinning helper.  ``live_helpers`` are
    function names (``_LIVE_BUILD_HELPERS``) whose bodies read today's board by
    design."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    if _module_really_pins(tree):
        return []
    module_live = any(
        isinstance(n, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "pytestmark" for t in n.targets)
        and "livedata" in ast.unparse(n.value)
        for n in tree.body
    )
    hits: list[int] = []

    def visit(node: ast.AST, live: bool, pinned: bool) -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            live = live or any(_is_livedata_mark(d) for d in node.decorator_list)
            pinned = pinned or _names_a_pin(node)
            if getattr(node, "name", None) in live_helpers and not isinstance(node, ast.ClassDef):
                live = True
        if isinstance(node, (ast.With, ast.AsyncWith)) and any(
            _names_a_pin(item.context_expr) for item in node.items
        ):
            pinned = True
        if isinstance(node, ast.Call) and not live and not pinned:
            fn = node.func
            called = (
                fn.id
                if isinstance(fn, ast.Name)
                else fn.attr
                if isinstance(fn, ast.Attribute)
                else None
            )
            if called in _BUILD_CALLS and not _own_csv_root(node):
                hits.append(node.lineno)
        for child in ast.iter_child_nodes(node):
            visit(child, live, pinned)

    visit(tree, module_live, False)
    return sorted(hits)


def test_no_hard_gate_build_reads_todays_inputs():
    """A hard-gate module that builds a contract pins the build's inputs
    (``pinned_board_inputs`` / ``pinned_build_environment`` /
    ``build_pinned_contract``) or passes its own ``csv_root``; a ``livedata``
    scope is exempt.  Archive-sourced and synthetic payloads alike: the build
    reads today's scrape state either way."""
    live_modules = _livedata_modules()
    offenders = []
    for path in sorted(TESTS.rglob("*.py")):
        rel = path.relative_to(REPO).as_posix()
        if rel in (
            "tests/archive_fixtures.py",
            "tests/test_pinned_board.py",
            "tests/pinned_board_build.py",
        ):
            continue
        if path.name in live_modules or rel in _UNPINNED_BUILD_ALLOWLIST:
            continue
        lines = _unpinned_builds(path, _live_helpers_for(rel))
        if lines:
            offenders.append(f"{rel}:{lines}")
    assert not offenders, (
        "hard-gate tests build a contract with csv_root=None, which reads TODAY's "
        f"CSVs and scrape state: {offenders}. Add "
        'pytestmark = pytest.mark.usefixtures("pinned_board_inputs") (a module with '
        "livedata tests: wrap the call in pinned_build_environment(freeze_clock=False)), "
        "use build_pinned_contract, or pass your own csv_root."
    )


def _helper_uses_outside_livedata(path: Path, helpers: frozenset[str]) -> list[int]:
    """Lines referencing one of ``helpers`` from code that is neither
    ``@pytest.mark.livedata`` nor itself one of the helpers (the getter chain)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    module_live = any(
        isinstance(n, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "pytestmark" for t in n.targets)
        and "livedata" in ast.unparse(n.value)
        for n in tree.body
    )
    hits: list[int] = []

    def visit(node: ast.AST, live: bool) -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            live = live or any(_is_livedata_mark(d) for d in node.decorator_list)
            if node.name in helpers:
                live = True
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            return
        name = (
            node.id
            if isinstance(node, ast.Name)
            else node.attr
            if isinstance(node, ast.Attribute)
            else None
        )
        if name in helpers and not live:
            hits.append(node.lineno)
        for child in ast.iter_child_nodes(node):
            visit(child, live)

    visit(tree, module_live)
    return hits


def test_live_build_helpers_are_reached_only_from_livedata():
    by_module: dict[str, set[str]] = {}
    for key, reason in _LIVE_BUILD_HELPERS.items():
        rel, _, func = key.partition("::")
        assert (REPO / rel).is_file(), rel
        assert len(reason.strip()) > 20, f"{key}: give the reason it reads today's board"
        by_module.setdefault(rel, set()).add(func)
    offenders = []
    for rel, funcs in by_module.items():
        path = REPO / rel
        defined = {
            n.name
            for n in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
            if isinstance(n, ast.FunctionDef)
        }
        assert funcs <= defined, f"{rel}: {sorted(funcs - defined)} not defined"
        lines = _helper_uses_outside_livedata(path, frozenset(funcs))
        if lines:
            offenders.append(f"{rel}:{lines}")
    assert not offenders, (
        f"a today's-board build helper is reached from a hard-gate test: {offenders}. "
        "Mark that test @pytest.mark.livedata or use the pinned board."
    )


def test_the_live_helper_guard_sees_a_leak(tmp_path):
    sample = tmp_path / "test_sample.py"
    sample.write_text(
        "import pytest\n"
        "def _load():\n    return build_api_data_contract(raw)\n"
        "def _get():\n    return _load()\n"
        "@pytest.mark.livedata\n"
        "def test_live():\n    _get()\n"
        "def test_hard():\n    _get()\n",
        encoding="utf-8",
    )
    assert _unpinned_builds(sample) == [3]
    assert _unpinned_builds(sample, frozenset({"_load"})) == []
    assert _helper_uses_outside_livedata(sample, frozenset({"_load", "_get"})) == [10]


def test_the_unpinned_build_allowlist_names_real_modules_with_reasons():
    for rel, reason in _UNPINNED_BUILD_ALLOWLIST.items():
        assert (REPO / rel).is_file(), rel
        assert len(reason.strip()) > 20, f"{rel}: give the reason it must read today's inputs"


@pytest.mark.parametrize(
    "source, expected",
    [
        ('A = "dynasty_export_1.zip"\nbuild_api_data_contract(raw)\n', [2]),
        ('A = "dynasty_export_1.zip"\ndc.build_api_data_contract(raw)\n', [2]),
        ("build_api_data_contract(synthetic)\n", [1]),
        ("dc.build_rankings_delta_payload(raw)\n", [1]),
        ("def _b(**kw):\n    return dc.build_api_data_contract(raw, **kw)\n", [2]),
        ("build_api_data_contract(raw, csv_root=None)\n", [1]),
        ("build_api_data_contract(raw, csv_root=tmp)\n", []),
        (
            'import pytest\npytestmark = pytest.mark.usefixtures("pinned_board_inputs")\n'
            "build_api_data_contract(raw)\n",
            [],
        ),
        (
            "def test_a():\n    with pinned_build_environment():\n"
            "        build_api_data_contract(raw)\n"
            "def test_b():\n    build_api_data_contract(raw)\n",
            [5],
        ),
        (
            "def _b():\n    pinned_board_contract()\n    return build_api_data_contract(raw)\n",
            [],
        ),
        (
            "import pytest\n@pytest.mark.livedata\nclass T:\n    def test_a(self):\n"
            "        build_api_data_contract(raw)\n"
            "def test_b():\n    build_api_data_contract(raw)\n",
            [7],
        ),
        ('"""pinned_board_inputs"""\nbuild_api_data_contract(raw)\n', [2]),
    ],
    ids=[
        "archive-name",
        "attribute-call",
        "synthetic",
        "delta-payload",
        "kwargs-forwarding",
        "csv-root-none",
        "own-csv-root",
        "pinned-module",
        "with-pin-covers-only-its-block",
        "helper-names-a-pin",
        "livedata-scope-exempt",
        "docstring-is-not-a-pin",
    ],
)
def test_the_unpinned_build_guard_sees_it(tmp_path, source, expected):
    sample = tmp_path / "test_sample.py"
    sample.write_text(source, encoding="utf-8")
    assert _unpinned_builds(sample) == expected


def test_the_audit_board_fixture_carries_no_real_identifier():
    """``audit_board_20261106.zip`` (the cw40 module's board, pseudonymized by
    ``pinned_board_build.pseudonymize_payload``) holds only synthetic ids/names."""
    with zipfile.ZipFile(TESTS / "fixtures" / "audit_board_20261106.zip") as zf:
        payload = json.loads(zf.read("payload.json"))
    sleeper = payload["sleeper"]
    assert sleeper["leagueId"] == pb.SYNTHETIC_LEAGUE_ID
    for team in sleeper["teams"]:
        assert team["name"] == pb.manager_name(int(team["roster_id"]))
        assert str(team["ownerId"]).startswith(pb.SYNTHETIC_ID_PREFIX)
    assert not re.findall(r"[\w.+-]+@[\w-]+\.[a-z]{2,}", json.dumps(payload))


# ── The guard: no hard-gate test reads today's refresh-written inputs by PATH ─
#
# The guards above see helper calls and contract builds.  Neither sees a test
# that opens ``CSVs/site_raw`` (or a script's ``CSV_DIR`` constant that
# resolves there) directly: PR 2213 -- ``test_hill_alignment_audit`` built its
# base board from the pinned tree but copied its KTC CSVs from
# ``scripts.hill_alignment_audit.CSV_DIR``, so the next KTC refresh failed
# Deploy Production with the code byte-identical.  This scan closes that gap.

#: A path component naming a refresh-written store.  ``exports`` + ``latest``
#: is matched as an adjacent pair (neither word is a store alone).
_REFRESH_TOKENS = {"site_raw", "scrape_state", "sleeper_last_good.json", "sleeper_last_good"}

#: Upper-case only: ``REPO`` / ``REPO_ROOT`` / ``_REPO`` are the module constants
#: the real checkout hangs off; a lower-case ``repo`` is a tmp git repo fixture.
_REPO_ROOT_NAME = re.compile(r"^_*(REPO|REPO_ROOT|PROJECT_ROOT|REPO_DIR|PROJECT_DIR)$")

#: Infrastructure that names these stores on purpose: the pin itself, the
#: runtime-data redirect and its watch list, the conftest, and this guard.
_LIVE_PATH_SCAN_SKIP = {
    "tests/archive_fixtures.py",
    "tests/pinned_board_build.py",
    "tests/runtime_data_isolation.py",
    "tests/conftest.py",
    "tests/test_pinned_board.py",
}

#: ``"<module>"`` -> reason.  Hard-gate modules that may still name a
#: refresh-written store by path.  Every entry must still offend (a stale
#: entry fails ``test_the_live_path_allowlist_is_exact``) and carry a reason.
_LIVE_PATH_READ_ALLOWLIST: dict[str, str] = {
    "tests/api/test_hill_alignment_audit.py": (
        "PR 2213 repoints its KTC CSV copies and DLF probe at the pinned tree; "
        "delete this entry when it merges"
    ),
    # The four below assert a property of the PUBLISHED artifacts themselves, not of
    # a value a refresh moves: they stay blocking because a regression in OUR
    # exporter / scraper / privacy redaction must stop a deploy, and a vendor refresh
    # cannot turn them red with the code byte-identical.
    "tests/api/test_export_leg_is_raw_evidence.py": (
        "asserts the committed export CSV headers / raw payload carry no canonical field"
        " name; a structural property of the export leg, independent of any value"
    ),
    "tests/api/test_tracked_artifacts_privacy.py": (
        "scans what the refresh commits for private-intelligence fields; the privacy"
        " gate must read the real tracked artifacts by definition"
    ),
    "tests/deploy/test_scheduled_refresh_playwright_runner.py": (
        "asserts a committed CSV exists for every declared browser source (is_file only,"
        " no content); a refresh rewrites these files, never removes them"
    ),
    "tests/model_registry/test_learning_boundary.py": (
        "hashes the served board and facts before and after running the substrate to prove"
        " it wrote nothing; compares the file with itself, so no refresh can change it"
    ),
}


def _string_tokens(node: ast.AST) -> list[str]:
    """Every path component spelled by a string constant under ``node``, in
    source order (so ``"exports" / "latest"`` yields adjacent tokens)."""
    consts = sorted(
        (n for n in ast.walk(node) if isinstance(n, ast.Constant) and isinstance(n.value, str)),
        key=lambda n: (n.lineno, n.col_offset),
    )
    tokens: list[str] = []
    for c in consts:
        tokens.extend(t for t in re.split(r"[\\/]+", c.value) if t)
    return tokens


def _names_refresh_store(tokens: list[str]) -> bool:
    if any(t in _REFRESH_TOKENS for t in tokens):
        return True
    return any(a == "exports" and b == "latest" for a, b in zip(tokens, tokens[1:]))


def _is_repo_anchor(node: ast.AST, modules: frozenset[str] | None = None) -> bool:
    """True when ``node`` is a repo-root name or ``__file__``.  An attribute
    (``audit.REPO_ROOT``) counts only on an IMPORTED module (``modules``; ``None``
    = any base): ``jfs = run.jfs`` / ``self.REPO`` are locals a test routinely
    monkeypatches to a tmp tree."""
    if isinstance(node, ast.Name):
        return bool(_REPO_ROOT_NAME.match(node.id)) or node.id == "__file__"
    if isinstance(node, ast.Attribute) and _REPO_ROOT_NAME.match(node.attr):
        return modules is None or ast.unparse(node.value) in modules
    return False


def _module_file(dotted: str) -> Path | None:
    base = REPO.joinpath(*dotted.split("."))
    for candidate in (base.with_suffix(".py"), base / "__init__.py"):
        if candidate.is_file():
            return candidate
    return None


_CONSTANT_CACHE: dict[str, tuple[frozenset[str], frozenset[str]]] = {}


def _refresh_constants(dotted: str) -> tuple[frozenset[str], frozenset[str]]:
    """``(names, anchored)``: module-level constants of ``dotted`` whose value
    names a refresh-written store (directly or through another such constant),
    and the subset whose value is also rooted at the repo (an absolute path --
    ``CSV_DIR = REPO_ROOT / "CSVs" / "site_raw"``).  The rest are relative
    (``DLF_VALUES_CSV_REL = "CSVs/site_raw/..."``) and only offend when joined
    to a repo root."""
    if dotted in _CONSTANT_CACHE:
        return _CONSTANT_CACHE[dotted]
    path = _module_file(dotted) if dotted.split(".")[0] in {"scripts", "src"} else None
    names: set[str] = set()
    anchored: set[str] = set()
    if path is not None:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        assigns = []
        for stmt in tree.body:
            if isinstance(stmt, ast.Assign):
                targets = [t.id for t in stmt.targets if isinstance(t, ast.Name)]
            elif isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                targets = [stmt.target.id]
            else:
                continue
            if stmt.value is not None:
                assigns.append((targets, stmt.value))
        changed = True
        while changed:
            changed = False
            for targets, value in assigns:
                refs = {n.id for n in ast.walk(value) if isinstance(n, ast.Name)}
                if not (_names_refresh_store(_string_tokens(value)) or refs & names):
                    continue
                rooted = any(_is_repo_anchor(n) for n in ast.walk(value)) or bool(refs & anchored)
                for t in targets:
                    if t not in names:
                        names.add(t)
                        changed = True
                    if rooted and t not in anchored:
                        anchored.add(t)
                        changed = True
    result = (frozenset(names), frozenset(anchored))
    _CONSTANT_CACHE[dotted] = result
    return result


def _import_bindings(tree: ast.Module) -> tuple[dict[str, str], dict[str, tuple[str, str]]]:
    """``(modules, constants)``: local name -> dotted module, and local name ->
    ``(dotted module, attribute)`` for ``from scripts.x import NAME``."""
    modules: dict[str, str] = {}
    constants: dict[str, tuple[str, str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for item in node.names:
                modules[item.asname or item.name] = item.name
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            for item in node.names:
                local = item.asname or item.name
                if _module_file(f"{node.module}.{item.name}") is not None:
                    modules[local] = f"{node.module}.{item.name}"
                else:
                    constants[local] = (node.module, item.name)
    return modules, constants


def _live_path_reads(path: Path, live_helpers: frozenset[str] = frozenset()) -> list[int]:
    """Lines where ``path`` (outside a ``livedata`` scope, and outside the
    ``_LIVE_BUILD_HELPERS`` functions that only livedata callers reach) builds a path that
    is rooted at the repo AND names a refresh-written store -- either spelled
    out (``REPO / "CSVs" / "site_raw"``) or reached through a ``scripts`` /
    ``src`` module constant (``audit.CSV_DIR``).  A path rooted at the pinned
    tree (``dc._default_input_root() / "CSVs" / "site_raw"``) or a tmp dir is
    not repo-anchored and is fine."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules, constants = _import_bindings(tree)
    imported = frozenset(modules)

    def const_ref(node: ast.AST) -> tuple[bool, bool]:
        """``(names a store, absolute)`` for a reference to a module constant."""
        if isinstance(node, ast.Name) and node.id in constants:
            mod, attr = constants[node.id]
        elif isinstance(node, ast.Attribute):
            mod = modules.get(ast.unparse(node.value))
            attr = node.attr
            if mod is None:
                return False, False
        else:
            return False, False
        names, anchored = _refresh_constants(mod)
        return attr in names, attr in anchored

    def examine(node: ast.AST) -> bool:
        stores = _names_refresh_store(_string_tokens(node))
        anchored = False
        for sub in ast.walk(node):
            ref_store, ref_abs = const_ref(sub)
            stores = stores or ref_store
            anchored = anchored or ref_abs or _is_repo_anchor(sub, imported)
        return stores and anchored

    module_live = any(
        isinstance(n, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "pytestmark" for t in n.targets)
        and "livedata" in ast.unparse(n.value)
        for n in tree.body
    )
    hits: list[int] = []

    def visit(node: ast.AST, live: bool) -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            live = live or any(_is_livedata_mark(d) for d in node.decorator_list)
            if getattr(node, "name", None) in live_helpers and not isinstance(node, ast.ClassDef):
                live = True
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            return
        if (
            isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            return  # a docstring or bare string is prose, not a read
        if isinstance(node, ast.expr) and not live and examine(node):
            hits.append(node.lineno)
            return
        for child in ast.iter_child_nodes(node):
            visit(child, live)

    visit(tree, module_live)
    return sorted(hits)


def _hard_gate_live_path_offenders() -> dict[str, list[int]]:
    live_modules = _livedata_modules()
    found: dict[str, list[int]] = {}
    for path in sorted(TESTS.rglob("*.py")):
        rel = path.relative_to(REPO).as_posix()
        if rel in _LIVE_PATH_SCAN_SKIP or path.name in live_modules:
            continue
        lines = _live_path_reads(path, _live_helpers_for(rel))
        if lines:
            found[rel] = lines
    return found


def test_no_hard_gate_test_reads_todays_inputs_by_path():
    """A hard-gate test that needs the board's CSVs, scrape state, last-good
    Sleeper snapshot or ``exports/latest`` reads them from the PINNED tree
    (``dc._default_input_root()`` under ``pinned_board_inputs``) or builds its
    own under ``tmp_path``.  A test that is about the latest refresh is
    ``livedata``.  Anything else is how a data refresh freezes a deploy."""
    offenders = {
        rel: lines
        for rel, lines in _hard_gate_live_path_offenders().items()
        if rel not in _LIVE_PATH_READ_ALLOWLIST
    }
    assert not offenders, (
        "hard-gate tests name a refresh-written store (CSVs/site_raw, data/scrape_state, "
        f"exports/latest, data/sleeper_last_good.json) rooted at the repo: {offenders}. "
        "Read it from dc._default_input_root() under the pinned_board_inputs fixture, build "
        "it under tmp_path, or mark the test @pytest.mark.livedata."
    )


def test_the_live_path_allowlist_is_exact():
    """Every entry names a real module with a reason and STILL offends: when the
    fix it waits for lands, the entry must go (the allowlist is a debt list)."""
    offenders = _hard_gate_live_path_offenders()
    for rel, reason in _LIVE_PATH_READ_ALLOWLIST.items():
        assert (REPO / rel).is_file(), rel
        assert len(reason.strip()) > 20, f"{rel}: give the reason it must name a live store"
        assert rel in offenders, f"{rel} no longer reads a live store by path: delete its entry"


def test_the_live_path_allowlist_check_fails_on_a_stale_entry(monkeypatch):
    """Guard on the stale-entry check: an entry for a module that does not
    offend makes ``test_the_live_path_allowlist_is_exact`` fail."""
    monkeypatch.setitem(
        _LIVE_PATH_READ_ALLOWLIST,
        "tests/test_livedata_policy.py",
        "a module that names no refresh-written store by path",
    )
    with pytest.raises(AssertionError, match="delete its entry"):
        test_the_live_path_allowlist_is_exact()


def _scan(tmp_path, source: str) -> list[int]:
    sample = tmp_path / "test_sample.py"
    sample.write_text(source, encoding="utf-8")
    return _live_path_reads(sample)


@pytest.mark.parametrize(
    "source, expected",
    [
        ('p = REPO / "CSVs" / "site_raw" / "ktc.csv"\n', [1]),
        ('p = REPO_ROOT / "data" / "scrape_state"\n', [1]),
        ('p = _REPO / "exports" / "latest"\n', [1]),
        ('import json\nj = json.loads((REPO / "data/sleeper_last_good.json").read_text())\n', [2]),
        ('g = glob.glob(os.path.join(REPO, "exports/latest/site_raw/*.csv"))\n', [1]),
        # a scripts constant that resolves to today's CSVs (the 2213 shape)
        ("from scripts import hill_alignment_audit as audit\nx = audit.CSV_DIR / 'k.csv'\n", [2]),
        ("from scripts.hill_alignment_audit import CSV_DIR\nx = CSV_DIR / 'k.csv'\n", [2]),
        ("import scripts.hill_alignment_audit as a\nx = a.CSV_DIR\n", [2]),
        # a relative constant only offends when joined to a repo root
        (
            "from scripts import hill_alignment_audit as audit\n"
            "x = audit.REPO_ROOT / audit.DLF_VALUES_CSV_REL\n",
            [2],
        ),
        (
            "from scripts import hill_alignment_audit as audit\n"
            "x = dc._default_input_root() / audit.DLF_VALUES_CSV_REL\n",
            [],
        ),
        # the pinned tree, a tmp tree and prose are fine
        ('p = dc._default_input_root() / "CSVs" / "site_raw" / "ktc.csv"\n', []),
        ('p = tmp_path / "CSVs" / "site_raw"\n', []),
        ('"""reads REPO / "CSVs" / "site_raw"."""\nx = 1\n', []),
        ('assert "site_raw" in text\n', []),
        # a livedata scope is exempt, the rest of the module is not
        (
            "import pytest\n@pytest.mark.livedata\ndef test_a():\n"
            '    p = REPO / "CSVs" / "site_raw"\n'
            'def test_b():\n    p = REPO / "CSVs" / "site_raw"\n',
            [6],
        ),
        (
            'import pytest\npytestmark = pytest.mark.livedata\np = REPO / "exports" / "latest"\n',
            [],
        ),
        # "exports" and "latest" are only a store as an adjacent pair
        ('p = REPO / "exports" / "archive"\nq = REPO / "latest"\n', []),
    ],
    ids=[
        "site-raw",
        "scrape-state",
        "exports-latest",
        "sleeper-last-good",
        "glob-join",
        "script-constant-attribute",
        "script-constant-import",
        "script-constant-module-alias",
        "relative-constant-with-repo-root",
        "relative-constant-with-pinned-root",
        "pinned-tree",
        "tmp-tree",
        "docstring",
        "mere-mention",
        "livedata-function-exempt",
        "livedata-module-exempt",
        "adjacent-pair-only",
    ],
)
def test_the_live_path_guard_sees_it(tmp_path, source, expected):
    assert _scan(tmp_path, source) == expected
