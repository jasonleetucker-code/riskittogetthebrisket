"""Build ``inputs.zip``: the W27-F005 TE-skew research test's pinned inputs, frozen.

WHY
───
``tests/scripts/test_w27_f005_te_skew_research.py`` ran
``scripts/research/w27_f005_te_skew.py::analyse_archive`` over a file in
``exports/archive`` (a rolling window: ``src/maintenance/retention.py`` keeps the
newest export of each day for 365 days, then deletes it) and over the repository
tree at the commit that ADDED that archive (``git archive <rev>``, which needs the
commit in the clone's history).  Either missing turned four tests into skips.

This fixture carries exactly what ``analyse_archive`` reads, so the test needs
neither the archive directory nor git history:

* ``dynasty_data_2026-11-06.json`` -- the archive's raw payload, pseudonymized with
  ``tests.pinned_board_build.pseudonymize_payload`` (the repository is public: no
  Sleeper user / league / draft id or manager name survives).  The member keeps the
  archive's member name, so ``load_archive`` reads the fixture zip as the archive.
* ``tree/`` -- the paths ``build_api_data_contract(csv_root=...)`` reads, from the
  same commit: every ``CSVs/site_raw/*.csv``, the ``data/scrape_state`` stamps the
  build reads (the pinned board's own selection rule) and ``config/weights``.
* ``manifest.json`` -- the source archive and its sha256, the payload member's
  original sha256, the tree revision, and a sha256 per file (verified on every read).

Usage (needs the source commit in history; the archive itself is read from that
commit, not from the working tree)::

    python tests/fixtures/te_skew_20261106/build_fixture.py

Deterministic: sorted members, fixed timestamps (``pinned_board_build.write_zip``).
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import subprocess
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO))

from tests.pinned_board_build import (  # noqa: E402
    _STATE_FILE_RE,
    pseudonymize_payload,
    write_zip,
)

OUT = HERE / "inputs.zip"
SCHEMA_VERSION = 1

#: The commit that added the archive: its tree is the one that built that board.
TREE_REVISION = "2550b42abf36728731320bcfd78f762b7833402e"
SOURCE_ARCHIVE = "dynasty_export_20261106_194518.zip"
SOURCE_ARCHIVE_SHA256 = "d4b196eace153ec17a2c29bff53b66568bda3264a48c09aaadac852c7ce7ced1"


def _git_bytes(rev: str, path: str) -> bytes:
    return subprocess.run(
        ["git", "-C", str(REPO), "show", f"{rev}:{path}"], check=True, capture_output=True
    ).stdout


def _git_ls(rev: str, path: str) -> list[str]:
    out = subprocess.run(
        ["git", "-C", str(REPO), "ls-tree", "-r", "--name-only", rev, "--", path],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout
    return [line for line in out.splitlines() if line.strip()]


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def collect() -> tuple[dict[str, bytes], dict]:
    archive = _git_bytes(TREE_REVISION, f"exports/archive/{SOURCE_ARCHIVE}")
    if _sha256(archive) != SOURCE_ARCHIVE_SHA256:
        raise SystemExit(f"{SOURCE_ARCHIVE} at {TREE_REVISION} does not match its recorded sha256")
    with zipfile.ZipFile(io.BytesIO(archive)) as zf:
        member = next(n for n in zf.namelist() if re.match(r"dynasty_data_.*\.json$", n))
        blob = zf.read(member)
    payload, counts = pseudonymize_payload(json.loads(blob))
    files: dict[str, bytes] = {
        member: json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    }
    tree: list[str] = [
        p
        for p in _git_ls(TREE_REVISION, "CSVs/site_raw")
        if p.endswith(".csv") and p.count("/") == 2
    ]
    tree += [
        p
        for p in _git_ls(TREE_REVISION, "data/scrape_state")
        if p.count("/") == 2 and _STATE_FILE_RE.match(p.rsplit("/", 1)[1])
    ]
    tree += [p for p in _git_ls(TREE_REVISION, "config/weights") if not p.endswith(".gitkeep")]
    for path in tree:
        files[f"tree/{path}"] = _git_bytes(TREE_REVISION, path)
    manifest = {
        "schemaVersion": SCHEMA_VERSION,
        "purpose": (
            "Pinned inputs of tests/scripts/test_w27_f005_te_skew_research.py: one archived "
            "raw payload (pseudonymized) and the contract-build tree of the commit that added "
            "it. Built by tests/fixtures/te_skew_20261106/build_fixture.py."
        ),
        "source": {
            "archive": SOURCE_ARCHIVE,
            "archiveSha256": SOURCE_ARCHIVE_SHA256,
            "payloadMember": member,
            "payloadSha256": _sha256(blob),
            "treeRevision": TREE_REVISION,
            "treePaths": [
                "CSVs/site_raw/*.csv",
                "data/scrape_state (read stamps)",
                "config/weights",
            ],
        },
        "asOf": payload.get("scrapeTimestamp"),
        "boardDate": payload.get("date"),
        "pseudonymized": counts,
        "files": {name: _sha256(data) for name, data in sorted(files.items())},
    }
    return files, manifest


def main() -> int:
    files, manifest = collect()
    write_zip(files, manifest, OUT)
    print(f"wrote {OUT.relative_to(REPO)}: {OUT.stat().st_size:,} bytes, {len(files)} files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
