"""Back up the auction store, RESTORE the copy, and verify it — every run.

A backup nobody has restored is a hope.  Each run:

1. takes an ONLINE copy with SQLite's backup API (WAL-safe; never a raw file
   copy that would miss the -wal);
2. opens that copy as a fresh store in a scratch directory and runs the full
   per-room verification — invariants, command-log replay equals the stored
   state, awards table equals the sales;
3. only then keeps the copy (gzip) and records ``last_verified_backup`` in
   the live store, which the commissioner's preflight shows.

Retention: the newest ``--keep`` copies (default 48 ≈ two days hourly).

This bounds the recovery point for a PROCESS or DATABASE fault to about an
hour.  It is ON-HOST: losing the whole disk also loses these copies.  The
nightly state backup (``deploy/backup/riskit-state-backup.sh``) and any
off-host copy remain the protection against host loss — see
``docs/auction/ROOKIE_AUCTION_ROOM.md`` §Recovery.

Exit codes: 0 verified; 1 verification failed (copy kept aside as
``*.FAILED``); 2 store unavailable.
"""

from __future__ import annotations

import argparse
import gzip
import os
import shutil
import sqlite3
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.auction.store import StoreUnavailable, db_path, open_store  # noqa: E402


def run(db: Path, dest: Path, keep: int) -> int:
    if not db.exists():
        print(f"auction store not found at {db}", file=sys.stderr)
        return 2
    try:
        live = open_store(db)
    except StoreUnavailable as exc:
        print(f"auction store unavailable: {exc}", file=sys.stderr)
        return 2
    dest.mkdir(parents=True, exist_ok=True)
    for stale in dest.glob("auction-*.sqlite.gz.partial"):
        stale.unlink(missing_ok=True)  # a previous run died mid-write
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / "auction" / "auction.sqlite"
        copy.parent.mkdir(parents=True)
        src = sqlite3.connect(str(db))
        dst = sqlite3.connect(str(copy))
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()
        restored = open_store(copy)
        with restored.read() as conn:
            rooms = [r["id"] for r in conn.execute("SELECT id FROM rooms")]
        failures = []
        for rid in rooms:
            try:
                rep = restored.verify_room(rid)
                if not (rep["replay_matches"] and rep["awards_match"]):
                    failures.append((rid, rep))
            except Exception as exc:  # noqa: BLE001 - report every room
                failures.append((rid, repr(exc)))
        restored.close()  # release the scratch copy before it is archived/removed
        target = dest / f"auction-{stamp}.sqlite.gz"
        if failures:
            bad = dest / f"auction-{stamp}.sqlite.FAILED"
            shutil.copy2(copy, bad)
            print(
                f"VERIFY FAILED for {len(failures)} room(s): {failures}; copy kept at {bad}",
                file=sys.stderr,
            )
            return 1
        # Write under a temporary name and rename only after the archive is
        # complete and on disk: a run killed mid-write (or by the unit's
        # timeout) must never leave a truncated file under a verified name.
        partial = target.with_name(target.name + ".partial")
        with open(copy, "rb") as fin, open(partial, "wb") as raw:
            with gzip.GzipFile(filename=target.name[:-3], mode="wb", fileobj=raw) as fout:
                shutil.copyfileobj(fin, fout)
            raw.flush()
            os.fsync(raw.fileno())
        os.replace(partial, target)
    with live.write() as conn:
        conn.execute(
            "INSERT INTO meta (key, value) VALUES ('last_verified_backup', ?)"
            " ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (f"{stamp} — {len(rooms)} room(s) restored and verified ({target.name})",),
        )
    copies = sorted(dest.glob("auction-*.sqlite.gz"))
    for old in copies[:-keep] if keep > 0 else []:
        old.unlink(missing_ok=True)
    print(f"verified backup {target} ({len(rooms)} rooms)")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Back up, restore and verify the auction store")
    ap.add_argument("--db", type=Path, default=None)
    ap.add_argument("--dest", type=Path, default=None)
    ap.add_argument("--keep", type=int, default=48)
    args = ap.parse_args(argv)
    db = args.db or db_path()
    dest = args.dest or (db.parent / "backups")
    t0 = time.time()
    code = run(db, dest, args.keep)
    print(f"elapsed {time.time() - t0:.1f}s")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
