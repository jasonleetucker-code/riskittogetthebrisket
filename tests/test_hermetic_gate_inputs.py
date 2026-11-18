"""The blocking gate must not depend on rolling checkout data.

``exports/archive`` is a rolling window: ``src/maintenance/retention.py`` keeps each
zip 14 days and then only the newest per calendar day, and the scheduled refresh
runs that pass.  Two research tests named ``dynasty_export_20261107_063955.zip``
(not the newest of its day) and would have started skipping on ~2026-11-21, pushing
the suite past its skip budget (``config/ci/test_shards.json::max_skipped``) and
turning every PR and deploy gate red at once -- the same class as the data-refresh
freezes ``tests/test_pinned_board.py`` closed for board builds.

This guard keeps the class closed.  It statically scans every blocking-gate test
module (``tests/hermetic_gate_scan.py``) and fails on a NEW

* literal naming a specific ``exports/archive/<file>.zip`` outside ``tests/fixtures``,
* ``skip`` / ``skipif`` / ``skipTest`` whose reason says the data is absent from the
  checkout (archive, absent, missing, shallow, ...).

Existing cases are inventoried in ``tests/hermetic_gate_allowlist.json``, each with
a reason, so only new ones fail.  The fix for a hit is to pin the input under
``tests/fixtures`` (see ``tests/fixtures/pinned_board`` and
``tests/fixtures/bdvm_saturation_outcome_archives``), or to mark a test that is
genuinely about the latest refresh ``@pytest.mark.livedata``.  A ``livedata`` scope
is outside the gate and never reported.
"""

from __future__ import annotations

import json

from tests import hermetic_gate_scan as scan
from tests.conftest import _LIVEDATA_MODULES

ALLOWLIST = scan.TESTS / "hermetic_gate_allowlist.json"
SELF = "tests/test_hermetic_gate_inputs.py"


def _allowlist() -> dict[str, dict]:
    return json.loads(ALLOWLIST.read_text(encoding="utf-8"))["files"]


def _current_hits() -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    for path in scan.gate_test_files(frozenset(_LIVEDATA_MODULES)):
        rel = path.relative_to(scan.REPO).as_posix()
        if rel == SELF:
            continue
        counts: dict[str, int] = {}
        for hit in scan.scan_source(path.read_text(encoding="utf-8")):
            counts[hit.kind] = counts.get(hit.kind, 0) + 1
        if counts:
            out[rel] = counts
    return out


def test_no_new_gate_test_depends_on_rolling_archive_or_skips_on_missing_data():
    allowed = _allowlist()
    offenders = []
    for rel, counts in sorted(_current_hits().items()):
        budget = allowed.get(rel, {}).get("maxHits", {})
        for kind, n in sorted(counts.items()):
            if n > budget.get(kind, 0):
                offenders.append(f"{rel}: {n} x {kind} (allowlisted: {budget.get(kind, 0)})")
    assert not offenders, (
        "blocking-gate tests depend on rolling checkout data (a retention pass or a "
        "shallow clone turns each into a skip, and past the skip budget the whole gate "
        f"goes red): {offenders}. Pin the input under tests/fixtures, mark a test about "
        "the latest refresh @pytest.mark.livedata, or -- last resort -- add a reasoned "
        "entry to tests/hermetic_gate_allowlist.json."
    )


def test_the_allowlist_has_no_stale_or_unreasoned_entry():
    hits = _current_hits()
    stale, unreasoned = [], []
    for rel, entry in _allowlist().items():
        if not (scan.REPO / rel).is_file():
            stale.append(f"{rel} (file is gone)")
        elif rel not in hits:
            stale.append(f"{rel} (no longer has any hit: delete the entry)")
        if len(str(entry.get("reason", "")).strip()) < 40:
            unreasoned.append(rel)
    assert not stale, f"stale allowlist entries: {stale}"
    assert not unreasoned, f"allowlist entries without a real reason: {unreasoned}"


# ── guard on the guard: the scanner must fire on a seeded violation ─────────


def test_scanner_flags_an_archive_zip_literal():
    src = 'ARCHIVE = "exports/archive/dynasty_export_20991231_235959.zip"\n'
    hits = scan.scan_source(src)
    assert [(h.kind, h.line) for h in hits] == [("archive-literal", 1)]


def test_scanner_flags_a_bare_export_name_whether_or_not_the_file_exists():
    """Data-independent: the verdict never depends on what is in exports/archive."""
    src = 'NAME = "dynasty_export_20991231_235959.zip"\n'
    assert [h.kind for h in scan.scan_source(src)] == ["archive-literal"]


def test_scanner_folds_string_concatenation_and_path_joins():
    for src in (
        'A = "exports/archive/" + "dynasty_export_20991231_235959.zip"\n',
        'A = REPO / "exports" / "archive" / "dynasty_export_20991231_235959.zip"\n',
        'A = Path("exports") / "archive" / "dynasty_export_20991231_235959.zip"\n',
    ):
        hits = scan.scan_source(src)
        assert [(h.kind, h.line) for h in hits] == [("archive-literal", 1)], src


def test_scanner_flags_listing_the_archive_directory():
    for src in (
        'for p in (REPO / "exports" / "archive").glob("*.zip"):\n    pass\n',
        'os.listdir(os.path.join(REPO, "exports", "archive"))\n',
    ):
        kinds = [h.kind for h in scan.scan_source(src)]
        assert kinds == ["archive-listing"], src


def test_scanner_flags_missing_data_skips_in_every_spelling():
    src = (
        "import pytest, unittest\n"
        "def test_a():\n    pytest.skip('tracked archive not in this checkout')\n"
        "@pytest.mark.skipif(not X.exists(), reason='pinned archive bundle absent')\n"
        "def test_b():\n    pass\n"
        "class T(unittest.TestCase):\n"
        "    def test_c(self):\n        self.skipTest('No complete archived board')\n"
        "def test_d():\n    pytest.skip(f'{name} is missing from the clone')\n"
    )
    assert [(h.kind, h.line) for h in scan.scan_source(src)] == [
        ("missing-data-skip", 3),
        ("missing-data-skip", 4),
        ("missing-data-skip", 9),
        ("missing-data-skip", 11),
    ]


def test_scanner_flags_the_broadened_missing_data_phrases():
    for why in ("fixture not found", "no data for this week", "file does not exist", "unavailable"):
        src = f"import pytest\ndef test_a():\n    pytest.skip({why!r})\n"
        assert [h.kind for h in scan.scan_source(src)] == ["missing-data-skip"], why


def test_scanner_ignores_livedata_scopes_docstrings_and_unrelated_skips():
    src = (
        '"""Mentions exports/archive/dynasty_export_20991231_235959.zip in prose."""\n'
        "import pytest\n"
        "@pytest.mark.livedata\n"
        "def test_live():\n    pytest.skip('archive absent')\n"
        "def test_platform():\n    pytest.skip('POSIX only')\n"
    )
    assert scan.scan_source(src) == []
    live_module = (
        "import pytest\npytestmark = pytest.mark.livedata\npytest.skip('archive absent')\n"
    )
    assert scan.scan_source(live_module) == []
