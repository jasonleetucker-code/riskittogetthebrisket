#!/usr/bin/env python3
"""Restore-verify the newest state-backup generation, read-only.

Why this exists: the post-deploy proof deliberately does NOT restore the two
largest ledgers (``temporal_ledger.sqlite``, ``intel_ledger.sqlite3``), and the
README told an operator to check them "by hand".  A backup that has never been
restored is a hope, not a backup, so this does the hand check:

* picks the newest dated generation under ``--root`` / the default roots;
* for every ``sqlite/*.gz``: gunzip into a SCRATCH directory (the generation is
  never written), open the copy read-only and run ``PRAGMA quick_check`` (or
  the full ``integrity_check`` with ``--full``), and count its tables;
* for every ``dirs/*.tar.gz``: read the whole archive (``tarfile`` walk).

Needs read access to the generation, which is root-only (0600) on the box:
``sudo python3 scripts/verify_state_backup_restore.py --scratch-dir /var/tmp``.
Exit: 0 every artifact verified, 1 any artifact failed, 2 no generation found.
Missing is never a pass: a generation with no artifacts exits 1.
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import re
import shutil
import sqlite3
import sys
import tarfile
import tempfile
import time
from pathlib import Path
from typing import Any

DEFAULT_ROOTS = ("/var/backups/riskit-state", "/home/dynasty/backups/riskit-state")
_DATED = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_CHUNK = 1 << 20


def find_generation(roots: list[str]) -> Path | None:
    """The newest dated generation across ``roots`` (unreadable roots skipped)."""
    best: Path | None = None
    for root in roots:
        daily = Path(root) / "daily"
        try:
            names = sorted(n for n in os.listdir(daily) if _DATED.match(n))
        except OSError:
            continue
        for name in reversed(names):
            cand = daily / name
            if cand.is_dir():
                if best is None or cand.name > best.name:
                    best = cand
                break
    return best


def _gunzip_to(src: Path, dest: Path) -> int:
    total = 0
    with gzip.open(src, "rb") as fin, open(dest, "wb") as fout:
        while True:
            chunk = fin.read(_CHUNK)
            if not chunk:
                break
            fout.write(chunk)
            total += len(chunk)
    return total


def verify_sqlite(artifact: Path, scratch: Path, *, full: bool) -> dict[str, Any]:
    res: dict[str, Any] = {"artifact": f"sqlite/{artifact.name}", "ok": False}
    started = time.monotonic()
    fd, tmp_name = tempfile.mkstemp(prefix="restore-", suffix=".sqlite", dir=scratch)
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        res["bytes"] = _gunzip_to(artifact, tmp)
        con = sqlite3.connect(f"file:{tmp}?mode=ro", uri=True)
        try:
            pragma = "integrity_check" if full else "quick_check"
            rows = [r[0] for r in con.execute(f"PRAGMA {pragma}")]
            res["check"] = pragma
            res["tables"] = con.execute(
                "SELECT count(*) FROM sqlite_master WHERE type='table'"
            ).fetchone()[0]
        finally:
            con.close()
        if rows != ["ok"]:
            res["error"] = "; ".join(str(r) for r in rows[:3])
        elif res["tables"] == 0:
            res["error"] = "restored database has no tables"
        else:
            res["ok"] = True
    except (OSError, EOFError, sqlite3.Error) as exc:
        res["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        tmp.unlink(missing_ok=True)
        res["seconds"] = round(time.monotonic() - started, 1)
    return res


def verify_tar(artifact: Path) -> dict[str, Any]:
    res: dict[str, Any] = {"artifact": f"dirs/{artifact.name}", "ok": False}
    try:
        with tarfile.open(artifact, "r:gz") as tar:
            members = 0
            for member in tar:
                members += 1
                if member.isfile():
                    handle = tar.extractfile(member)
                    while handle is not None and handle.read(_CHUNK):
                        pass
        res["members"] = members
        res["ok"] = members > 0
        if members == 0:
            res["error"] = "archive is empty"
    except (OSError, EOFError, tarfile.TarError) as exc:
        res["error"] = f"{type(exc).__name__}: {exc}"
    return res


def verify_generation(
    gen: Path, scratch: Path, *, full: bool = False, only: list[str] | None = None
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []

    def wanted(name: str) -> bool:
        return not only or any(o in name for o in only)

    sqlite_dir, dirs_dir = gen / "sqlite", gen / "dirs"
    for art in sorted(sqlite_dir.glob("*.gz")) if sqlite_dir.is_dir() else []:
        if wanted(art.name):
            results.append(verify_sqlite(art, scratch, full=full))
    for art in sorted(dirs_dir.glob("*.tar.gz")) if dirs_dir.is_dir() else []:
        if wanted(art.name):
            results.append(verify_tar(art))
    return {
        "generation": gen.name,
        "ok": bool(results) and all(r["ok"] for r in results),
        "verified": sum(1 for r in results if r["ok"]),
        "failed": [r["artifact"] for r in results if not r["ok"]],
        "artifacts": results,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Restore-verify the newest state-backup generation.")
    ap.add_argument("--root", action="append", help="backup root (repeatable)")
    ap.add_argument("--generation", help="explicit generation directory")
    ap.add_argument("--scratch-dir", default=None, help="where to restore copies (deleted after)")
    ap.add_argument("--full", action="store_true", help="integrity_check instead of quick_check")
    ap.add_argument("--only", action="append", help="substring filter, e.g. temporal_ledger")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    if args.generation:
        gen: Path | None = Path(args.generation)
    else:
        gen = find_generation(args.root or list(DEFAULT_ROOTS))
    if gen is None or not gen.is_dir():
        print("no readable backup generation found", file=sys.stderr)
        return 2
    scratch = Path(tempfile.mkdtemp(prefix="riskit-restore-verify-", dir=args.scratch_dir))
    try:
        report = verify_generation(gen, scratch, full=args.full, only=args.only)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        for r in report["artifacts"]:
            tail = f"  {r['error']}" if r.get("error") else ""
            print(("OK   " if r["ok"] else "FAIL ") + r["artifact"] + tail)
        print(
            f"generation {report['generation']}: {report['verified']} verified, "
            f"{len(report['failed'])} failed"
        )
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
