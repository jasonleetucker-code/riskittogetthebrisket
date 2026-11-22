"""Build the archive-selection fixture for ``tests/idp_accuracy/test_backtest.py``.

``scripts/idp_accuracy/backtest.py::select_archive`` walks ``<REPO>/exports/archive``
and reads, from the last four archives stamped up to a day past the kickoff, only
each archive's internal ``scrapeTimestamp`` (its generation instant) and its
``manifest.json`` ``generatedAt``.  The test asserted the selection against the REAL
directory, a rolling window ``src/maintenance/retention.py`` prunes.

This writes, under ``exports/archive/`` beside this file, one minimal zip per archive
the test's two kickoffs inspect, carrying exactly those two values under the source
archive's own names, and ``provenance.json`` recording every source archive's sha256
and the commit that added it.  The test points the module's ``REPO`` here.

Usage (needs each source archive's adding commit in history)::

    python tests/fixtures/idp_backtest_20260909/build_fixture.py

Deterministic: sorted members, fixed timestamps, compact sorted JSON.
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
OUT_DIR = HERE / "exports" / "archive"
PROVENANCE = HERE / "provenance.json"

#: Every archive ``select_archive`` inspects for the test's two kickoffs (2026-09-10
#: 00:20Z, and the selected archive's own generation instant): the last four stamped
#: before each kickoff + 1 day.
SOURCE_ARCHIVES = (
    "dynasty_export_20260906_205400.zip",
    "dynasty_export_20260907_230241.zip",
    "dynasty_export_20260908_212819.zip",
    "dynasty_export_20260909_211525.zip",
    "dynasty_export_20260910_224947.zip",
)


def _git(*args: str) -> bytes:
    return subprocess.run(["git", "-C", str(REPO), *args], check=True, capture_output=True).stdout


def _adding_commit(name: str) -> str:
    out = _git("log", "--diff-filter=A", "--format=%H", "--", f"exports/archive/{name}")
    revs = out.decode("utf-8").split()
    if not revs:
        raise SystemExit(f"no commit adds exports/archive/{name}")
    return revs[-1]


def _minimal_zip(member: str, scrape_timestamp: str, generated_at: str | None) -> bytes:
    entries = {member: {"scrapeTimestamp": scrape_timestamp}}
    if generated_at is not None:
        entries["manifest.json"] = {"generatedAt": generated_at}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for name in sorted(entries):
            info = zipfile.ZipInfo(name, date_time=(2020, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            body = json.dumps(entries[name], sort_keys=True, separators=(",", ":")) + "\n"
            zf.writestr(info, body.encode("utf-8"), compresslevel=9)
    return buf.getvalue()


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    records = {}
    for name in SOURCE_ARCHIVES:
        commit = _adding_commit(name)
        source = _git("show", f"{commit}:exports/archive/{name}")
        with zipfile.ZipFile(io.BytesIO(source)) as zf:
            member = next(n for n in zf.namelist() if re.match(r"dynasty_data_.*\.json$", n))
            raw = json.loads(zf.read(member))
            manifest = (
                json.loads(zf.read("manifest.json")) if "manifest.json" in zf.namelist() else {}
            )
        scrape = raw["scrapeTimestamp"]
        generated = manifest.get("generatedAt")
        pinned = _minimal_zip(member, scrape, generated)
        (OUT_DIR / name).write_bytes(pinned)
        records[name] = {
            "addedInCommit": commit,
            "sourceSha256": hashlib.sha256(source).hexdigest(),
            "payloadMember": member,
            "scrapeTimestamp": scrape,
            "manifestGeneratedAt": generated,
            "pinnedSha256": hashlib.sha256(pinned).hexdigest(),
        }
    doc = {
        "purpose": (
            "Archive-selection inputs of tests/idp_accuracy/test_backtest.py: each source "
            "export's generation instant and manifest generatedAt, under its own name. "
            "Built by tests/fixtures/idp_backtest_20260909/build_fixture.py."
        ),
        "extraction": "payload scrapeTimestamp + manifest.json generatedAt; nothing else",
        "archives": records,
    }
    PROVENANCE.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {len(records)} minimal archives + {PROVENANCE.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
