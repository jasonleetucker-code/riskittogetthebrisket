#!/usr/bin/env python3
"""Forward validation scoreboard (DYN10 V1): does a value predict the market?

Research tooling.  It changes nothing served and registers nothing in the
Hill independent-validation registry.  Logic lives in
``src/backtesting/forward_scoreboard.py``; this script builds the input,
runs the measurement and writes it.

Two input modes:

* **archive** (default, reproducible in CI): build a TEMPORARY temporal
  ledger from the committed ``exports/archive/*.zip`` with the canonical
  builder's archive stage plus the bundles' KTC-mode CSVs, then measure.
  The production ledger (``data/temporal_ledger.sqlite``) is never touched.
* **--ledger PATH**: measure an existing ledger.  It is copied into a temp
  dir with SQLite's backup API (a read-only source connection) and
  measured from the copy, so the original cannot be written.

Never pointed at ``data/market_trades/`` or ``docs/market_trades/``: those
hold the Chase Trade Market ledger and its preregistration, whose reserved
outcomes the owner forbade examining.

Exit codes (repo convention): 0 a measurement was written (or printed with
``--dry-run``); 1 soft failure (no archive, nothing measurable, write
error); 2 refusing to measure (a forbidden input, the production ledger as
a build target, or a non-positive horizon).
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import sys
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from src.backtesting import forward_scoreboard as fs  # noqa: E402
from src.history import store  # noqa: E402

OUT_DIR = REPO / "docs" / "measurements"
DEFAULT_ARCHIVE = REPO / "exports" / "archive"

# Inputs this tool refuses to read (owner: reserved CTM outcomes).
FORBIDDEN_INPUT_ROOTS: tuple[Path, ...] = (
    REPO / "data" / "market_trades",
    REPO / "docs" / "market_trades",
)


def log(msg: str) -> None:
    print(f"[forward-scoreboard] {msg}", flush=True)


def _forbidden(path: Path) -> Path | None:
    resolved = path.resolve()
    for root in FORBIDDEN_INPUT_ROOTS:
        root_r = root.resolve()
        if resolved == root_r or root_r in resolved.parents:
            return root
    return None


def _code_sha() -> dict[str, object]:
    def git(*args: str) -> str | None:
        try:
            proc = subprocess.run(
                ["git", *args],
                cwd=REPO,
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=True,
            )
        except (OSError, subprocess.CalledProcessError):
            return None
        return proc.stdout.strip()

    sha = git("rev-parse", "HEAD")
    status = git("status", "--porcelain", "--", "src", "scripts")
    return {"codeSha": sha, "codeDirty": (bool(status) if status is not None else None)}


def _copy_ledger(source: Path, dest: Path) -> None:
    """Copy a live SQLite ledger without writing it (WAL-safe)."""
    src = sqlite3.connect(f"file:{source}?mode=ro", uri=True, timeout=10.0)
    try:
        dst = sqlite3.connect(str(dest))
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--archive-dir", type=Path, default=DEFAULT_ARCHIVE)
    ap.add_argument(
        "--ledger",
        type=Path,
        default=None,
        help="measure an existing ledger (copied read-only) instead of the archive",
    )
    ap.add_argument("--horizons", type=int, nargs="+", default=list(fs.DEFAULT_HORIZONS))
    ap.add_argument("--out", type=Path, default=None, help="JSON path")
    ap.add_argument("--summary", type=Path, default=None, help="markdown path")
    ap.add_argument("--dry-run", action="store_true", help="print JSON, write nothing")
    args = ap.parse_args(argv)

    if any(h <= 0 for h in args.horizons):
        print(f"[forward-scoreboard] horizons must be positive: {args.horizons}", file=sys.stderr)
        return 2
    for candidate in (args.archive_dir, args.ledger):
        if candidate is None:
            continue
        root = _forbidden(candidate)
        if root is not None:
            print(
                f"[forward-scoreboard] refusing to read {candidate}: inputs under "
                f"{root.relative_to(REPO)} are reserved (owner rule)",
                file=sys.stderr,
            )
            return 2

    with tempfile.TemporaryDirectory(prefix="forward-scoreboard-") as tmp:
        ledger = Path(tmp) / "temporal_ledger.sqlite"
        inputs: dict[str, object]
        if args.ledger is not None:
            if not args.ledger.is_file():
                print(f"[forward-scoreboard] no ledger at {args.ledger}", file=sys.stderr)
                return 1
            _copy_ledger(args.ledger, ledger)
            not_fresh: list[list[str]] = []
            inputs = {
                "mode": "ledger",
                "ledger": str(args.ledger),
                # Reads are not knowledge-time bounded (see CAVEATS), so say how
                # many corrections the ledger holds.  Read from the COPY.
                "ledgerCorrections": store.coverage(ledger).get("corrections"),
            }
            log(f"measuring a read-only copy of {args.ledger}")
        else:
            try:
                build = fs.build_archive_ledger(args.archive_dir, ledger)
            except fs.ArchiveUnavailable as exc:
                print(f"[forward-scoreboard] {exc}", file=sys.stderr)
                return 1
            except ValueError as exc:
                print(f"[forward-scoreboard] {exc}", file=sys.stderr)
                return 2
            try:
                archive_dir = str(args.archive_dir.resolve().relative_to(REPO))
            except ValueError:
                archive_dir = str(args.archive_dir)
            inputs = {"mode": "archive", "archiveDir": archive_dir, "ledgerBuild": build}
            not_fresh = build["notFresh"]
            log(f"temporary ledger built: {build['payloadBackfill']}")
            log(f"producer carry-forward masked: {not_fresh}")

        result = fs.measure(ledger, horizons=args.horizons, not_fresh=not_fresh)

    measured = any(
        (s.get("byGroup") or {}).get(fs.GROUP_ALL, {}).get("foldsUsable")
        for block in result["horizons"].values()
        for s in [block["board"], *block["sources"].values()]
    )
    payload = {
        "schema": result["schema"],
        "measuredAt": datetime.now(timezone.utc).isoformat(),
        **_code_sha(),
        "inputs": inputs,
        **{k: v for k, v in result.items() if k != "schema"},
    }

    if args.dry_run:
        print(json.dumps(payload, indent=2, default=str))
        return 0 if measured else 1

    out = args.out or OUT_DIR / f"forward-scoreboard-{date.today().isoformat()}.json"
    summary = args.summary or out.with_suffix(".md")
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
        summary.write_text(
            fs.render_markdown(
                payload, title=f"Forward validation scoreboard — {payload['measuredAt'][:10]}"
            ),
            encoding="utf-8",
        )
    except OSError as exc:
        print(f"[forward-scoreboard] write failed: {exc}", file=sys.stderr)
        return 1
    log(f"wrote {out}")
    log(f"wrote {summary}")
    if not measured:
        log("nothing measurable: no series has a usable ALL cross-section at any horizon")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
