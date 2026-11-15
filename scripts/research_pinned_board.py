"""Pin a research board: the archive AND the repository tree the contract build reads.

RESEARCH HELPER (shared; one copy).  An archived raw payload does not pin the board
on its own: ``build_api_data_contract`` also reads the source CSVs, the per-source
scrape-state stamps and ``config/weights`` from a repository tree, and the
two-hourly refreshes move those.  ``--csv-rev REV`` materialises exactly those paths
from a git revision into a temporary directory and routes every contract build in
the process through it (``build_api_data_contract(csv_root=...)``), including the
forked workers of a replay, which inherit the patch.

The idea and the pinned revision come from the disclosure shadow
(``scripts/low_value_depth_disclosure_shadow.py`` on PR #1887); this module is the
reusable form so a further research script does not paste another copy.
"""

from __future__ import annotations

import contextlib
import functools
import hashlib
import io
import json
import re
import subprocess
import tarfile
import tempfile
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

#: What ``build_api_data_contract(csv_root=...)`` reads from a repository tree
#: besides the archive: the source CSVs, the per-source fetch stamps and the
#: coverage-floor configs.
CSV_TREE_PATHS = ("CSVs", "data/scrape_state", "config/weights")


def git(*args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(REPO), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def load_archive(archive: str) -> tuple[Path, str, bytes, dict]:
    """``(path, member, blob, raw)`` of a ``dynasty_export_*.zip`` (repo-relative or absolute)."""
    zpath = Path(archive)
    if not zpath.is_absolute():
        zpath = (REPO / zpath).resolve()
    with zipfile.ZipFile(zpath) as zf:
        member = next(n for n in zf.namelist() if re.match(r"dynasty_data_.*\.json$", n))
        blob = zf.read(member)
    return zpath, member, blob, json.loads(blob)


def tree_content_sha256(root: Path) -> str:
    """sha256 over (relative path, file bytes) of every file under ``CSV_TREE_PATHS``."""
    h = hashlib.sha256()
    for top in CSV_TREE_PATHS:
        base = root / top
        if not base.exists():
            continue
        for p in sorted(x for x in base.rglob("*") if x.is_file()):
            h.update(p.relative_to(root).as_posix().encode() + b"\0")
            h.update(hashlib.sha256(p.read_bytes()).digest())
    return h.hexdigest()


@contextlib.contextmanager
def csv_tree(rev: str | None):
    """Yield ``(csv_root, provenance)``.

    ``rev`` None = the working tree (``csv_root`` None: nothing is pinned);
    otherwise ``CSV_TREE_PATHS`` at that git revision, materialised into a
    temporary directory that is deleted on exit."""
    if rev is None:
        yield None, {"source": "working tree", "contentSha256": tree_content_sha256(REPO)}
        return
    full = git("rev-parse", "--verify", f"{rev}^{{commit}}")
    tar = subprocess.run(
        ["git", "-C", str(REPO), "archive", "--format=tar", full, *CSV_TREE_PATHS],
        check=True,
        capture_output=True,
    ).stdout
    with tempfile.TemporaryDirectory(prefix="research-csv-tree-") as tmp:
        with tarfile.open(fileobj=io.BytesIO(tar)) as tf:
            tf.extractall(tmp, filter="data")
        root = Path(tmp)
        yield (
            root,
            {
                "source": "git revision",
                "revisionSha": full,
                "revisionCommittedAt": git("log", "-1", "--format=%cI", full),
                "contentSha256": tree_content_sha256(root),
            },
        )


@contextlib.contextmanager
def pinned_contract_builds(csv_root: Path | None):
    """Route every ``build_api_data_contract`` call in this process through ``csv_root``.

    The module attribute is rebound for the duration, so callers that import the
    function inside their own body (the Trade Finder replay does) and forked
    worker processes see the pinned tree.  ``csv_root`` None changes nothing."""
    if csv_root is None:
        yield
        return
    from src.api import data_contract as dc  # noqa: PLC0415

    original = dc.build_api_data_contract
    dc.build_api_data_contract = functools.partial(original, csv_root=csv_root)
    try:
        yield
    finally:
        dc.build_api_data_contract = original


def built_board_sha256(rows: dict) -> str:
    """Hash of the built board (name -> canonical value) so a re-run can prove it
    built the same board from the same archive and CSV tree."""
    blob = json.dumps(sorted((n, r["value"]) for n, r in rows.items()), separators=(",", ":"))
    return hashlib.sha256(blob.encode()).hexdigest()
