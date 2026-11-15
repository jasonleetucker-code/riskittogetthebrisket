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


# ── The guard: a build from a real archive reads pinned CSVs and state ─────

#: Hard-gate modules that build a contract from a real ``exports/archive``
#: payload WITHOUT the pinned inputs, each with the reason it must.  Empty by
#: design: ``build_api_data_contract(raw)`` with no ``csv_root`` reads TODAY's
#: ``CSVs/site_raw`` and ``data/scrape_state`` beside the archived payload, so
#: a data refresh changes the result of a "fixed" archive build.
_UNPINNED_ARCHIVE_BUILD_ALLOWLIST: dict[str, str] = {}

_ARCHIVE_SOURCE = re.compile(r"dynasty_export_|\bARCHIVE\b|\barchive_dir\b|exports[\"'/ ,]+archive")
_BUILD_CALLS = {"build_api_data_contract", "build_rankings_delta_payload"}
_PINNING_NAMES = (
    "pinned_board_inputs",
    "pinned_build_environment",
    "build_pinned_contract",
    "pinned_board_contract",
)


def _module_really_pins(tree: ast.Module) -> bool:
    """True only for CODE that pins: a ``pytestmark`` / ``usefixtures`` naming
    the fixture, or a reference to / call of a pinning helper.  A mention in a
    docstring or comment does not count."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in _PINNING_NAMES:
            return True
        if isinstance(node, ast.Attribute) and node.attr in _PINNING_NAMES:
            return True
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


def _unpinned_archive_builds(path: Path) -> list[int]:
    """Lines of contract builds with no ``csv_root`` in a module that reads a
    real archive and does not pin its inputs."""
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text)
    if not _ARCHIVE_SOURCE.search(text) or _module_really_pins(tree):
        return []
    hits = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        called = (
            fn.id
            if isinstance(fn, ast.Name)
            else fn.attr
            if isinstance(fn, ast.Attribute)
            else None
        )
        if called not in _BUILD_CALLS:
            continue
        if any(k.arg in ("csv_root", None) for k in node.keywords):
            continue
        hits.append(node.lineno)
    return sorted(hits)


def test_no_hard_gate_archive_build_reads_todays_inputs():
    """A hard-gate module that builds a contract from a real archive payload
    pins the build's inputs (``pinned_board_inputs`` / ``build_pinned_contract``)
    or passes its own ``csv_root``; ``livedata`` modules are exempt."""
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
        if path.name in live_modules or rel in _UNPINNED_ARCHIVE_BUILD_ALLOWLIST:
            continue
        lines = _unpinned_archive_builds(path)
        if lines:
            offenders.append(f"{rel}:{lines}")
    assert not offenders, (
        "hard-gate tests build a contract from a real archive with csv_root=None, "
        f"which reads TODAY's CSVs and scrape state: {offenders}. Add "
        'pytestmark = pytest.mark.usefixtures("pinned_board_inputs") or use '
        "build_pinned_contract."
    )


def test_the_unpinned_archive_allowlist_names_real_modules_with_reasons():
    for rel, reason in _UNPINNED_ARCHIVE_BUILD_ALLOWLIST.items():
        assert (REPO / rel).is_file(), rel
        assert len(reason.strip()) > 20, f"{rel}: give the reason it must read today's inputs"


@pytest.mark.parametrize(
    "source, expected",
    [
        ('A = "dynasty_export_1.zip"\nbuild_api_data_contract(raw)\n', [2]),
        ('A = "dynasty_export_1.zip"\ndc.build_api_data_contract(raw)\n', [2]),
        ('A = "dynasty_export_1.zip"\nbuild_api_data_contract(raw, csv_root=r)\n', []),
        (
            'import pytest\nA = "dynasty_export_1.zip"\n'
            'pytestmark = pytest.mark.usefixtures("pinned_board_inputs")\n'
            "build_api_data_contract(raw)\n",
            [],
        ),
        ("build_api_data_contract(synthetic)\n", []),
    ],
    ids=["archive-name", "attribute-call", "own-csv-root", "pinned-module", "synthetic-only"],
)
def test_the_unpinned_build_guard_sees_it(tmp_path, source, expected):
    sample = tmp_path / "test_sample.py"
    sample.write_text(source, encoding="utf-8")
    assert _unpinned_archive_builds(sample) == expected


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
