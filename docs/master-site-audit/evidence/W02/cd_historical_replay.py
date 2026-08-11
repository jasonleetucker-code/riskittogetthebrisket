#!/usr/bin/env python3
"""Corridor replay — CURRENT canonical code against HISTORICAL market data.

The correction pass. The prior conclusion ("the platform does not retain
the inputs needed to characterise board-over-board behaviour") was drawn
from the export bundle alone and is wrong: git history retains all 24
per-source CSVs at every automated-refresh commit.

``--matrix``   build the historical compatibility matrix (no replays).
``--replay``   matrix, then replay every usable snapshot and measure.

Methodology, frozen
-------------------

Every replay is **current code + historical inputs**, never historical
code. We are testing today's corridor/replacement methodology against past
market states; running old code would confound methodology drift with data
drift.

Four redirects make that real, and each was found by instrumenting an
actual build (``cd_input_manifest.py``) rather than by reading the source:

1. ``CSVs/site_raw/*`` — 22 market-data CSVs, redirected via the
   pipeline's own ``csv_root`` parameter.
2. ``data/scrape_state/*_last_success`` — 22 freshness stamps. Traced to
   ``_build_source_timestamps`` → stamped as ``sourceTimestamps`` only,
   so **diagnostic, not value-affecting**. Redirected anyway: a replay
   should not read today's clock state at all.
3. ``data/snapshots/ranks_last.json`` — read AND **written** by every
   build. Redirected so a replay loop cannot mutate live state or make
   its own runs order-dependent.
4. ``https://api.sleeper.app/v1/league/...`` — a **live network call on
   the contract path**. It derives ``tep_multiplier`` from the league's
   ``bonus_rec_te``, so it genuinely affects values. Left unpinned, every
   historical replay would silently use *today's* league scoring. It is
   pinned to one recorded context and held constant across all
   snapshots, so league configuration is a controlled constant and only
   market data varies.

Leakage assertion
-----------------

Every replay runs under the same instrumentation. A read of
``CSVs/site_raw/`` outside the historical root, or any network access, is
a **hard failure** that discards the snapshot rather than quietly
producing a contaminated number.
"""

from __future__ import annotations

import argparse
import builtins
import contextlib
import hashlib
import io
import json
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
OUT = Path(__file__).resolve().parent


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True, check=False
    ).stdout


class LeakageError(RuntimeError):
    """A historical replay touched current-tree market data or the network."""


class Replay:
    """One historical snapshot, replayed under current code."""

    def __init__(self, sha: str, when: str, root: Path):
        self.sha = sha
        self.when = when
        self.root = root  # isolated input root for this snapshot
        self.leaks: list[str] = []

    @contextlib.contextmanager
    def guard(self):
        """Fail loudly on any current-tree market read or network access."""
        real_open, real_p_open = builtins.open, Path.open
        real_rt, real_rb = Path.read_text, Path.read_bytes
        real_url = urllib.request.urlopen
        allowed = str(self.root.resolve())
        forbidden = str((ROOT / "CSVs" / "site_raw").resolve())

        def check(p):
            try:
                s = str(Path(p).resolve())
            except (TypeError, ValueError, OSError):
                return
            if s.startswith(forbidden) and not s.startswith(allowed):
                self.leaks.append(s)

        def o(f, mode="r", *a, **k):
            check(f)
            return real_open(f, mode, *a, **k)

        def po(self_, mode="r", *a, **k):
            check(self_)
            return real_p_open(self_, mode, *a, **k)

        def rt(self_, *a, **k):
            check(self_)
            return real_rt(self_, *a, **k)

        def rb(self_, *a, **k):
            check(self_)
            return real_rb(self_, *a, **k)

        def net(req, *a, **k):
            self.leaks.append(f"NETWORK {getattr(req, 'full_url', req)}")
            raise LeakageError("network access during a historical replay")

        builtins.open, Path.open = o, po
        Path.read_text, Path.read_bytes = rt, rb
        urllib.request.urlopen = net
        try:
            yield
        finally:
            builtins.open, Path.open = real_open, real_p_open
            Path.read_text, Path.read_bytes = real_rt, real_rb
            urllib.request.urlopen = real_url


#: League context pinned across every snapshot. Recorded, not inferred:
#: holding it constant is what makes the comparison purely market-state.
PINNED_LEAGUE_CONTEXT = {
    "roster_count": 12,
    "bonus_rec_te": 0.5,
    "fetched_from_sleeper": False,
    "_pinned_by": "cd_historical_replay",
}


def required_csvs() -> list[str]:
    """Market-data CSVs a contract build actually reads (instrumented)."""
    man = OUT / "cd_input_manifest.json"
    if man.is_file():
        data = json.loads(man.read_text())
        paths = data.get("byClass", {}).get("MARKET DATA (must redirect)") or []
        if paths:
            return sorted(paths)
    from src.api.data_contract import _SOURCE_CSV_PATHS

    out = []
    for cfg in _SOURCE_CSV_PATHS.values():
        p = cfg if isinstance(cfg, str) else str((cfg or {}).get("path") or "")
        if p:
            out.append(p)
    return sorted(set(out))


def refresh_commits(limit: int = 400) -> list[tuple[str, str]]:
    """Automated-refresh commits, newest first, as (sha, iso-date)."""
    raw = _git(
        "log",
        f"-{limit}",
        "--format=%H\t%aI",
        "--grep=automated data refresh",
        "origin/main",
    )
    out = []
    for line in raw.strip().splitlines():
        if "\t" in line:
            sha, when = line.split("\t", 1)
            out.append((sha.strip(), when.strip()))
    return out


def blob_at(sha: str, path: str) -> bytes | None:
    r = subprocess.run(["git", "cat-file", "-p", f"{sha}:{path}"], cwd=ROOT, capture_output=True)
    return r.stdout if r.returncode == 0 else None


def board_at(sha: str) -> tuple[str, bytes] | None:
    names = _git("ls-tree", "--name-only", f"{sha}:exports/latest").split()
    cands = sorted(
        (n for n in names if n.startswith("dynasty_data_") and n.endswith(".json")), reverse=True
    )
    if not cands:
        return None
    b = blob_at(sha, f"exports/latest/{cands[0]}")
    return (cands[0], b) if b else None


def matrix(commits, needed) -> list[dict]:
    rows = []
    for sha, when in commits:
        present, missing = [], []
        hashes = {}
        for rel in needed:
            b = blob_at(sha, rel)
            if b is None:
                missing.append(rel)
            else:
                present.append(rel)
                hashes[rel] = hashlib.sha256(b).hexdigest()
        board = board_at(sha)
        if board is None:
            usable, reason = "unusable", "no exports/latest board in tree"
        elif missing:
            usable, reason = "partial", f"{len(missing)} required CSV(s) absent"
        else:
            usable, reason = "usable", "all required inputs present"
        rows.append(
            {
                "sha": sha,
                "timestamp": when,
                "day": when[:10],
                "requiredInputs": len(needed),
                "present": len(present),
                "missing": missing,
                "sourcesNotYetExisting": missing,
                "boardFile": board[0] if board else None,
                "boardSha256": hashlib.sha256(board[1]).hexdigest() if board else None,
                "csvHashes": hashes,
                "usable": usable,
                "reason": reason,
            }
        )
    return rows


def materialise(entry: dict, dest: Path) -> None:
    """Write this snapshot's historical inputs into an isolated root."""
    (dest / "CSVs" / "site_raw").mkdir(parents=True, exist_ok=True)
    for rel in entry["csvHashes"]:
        b = blob_at(entry["sha"], rel)
        if b is None:
            raise LeakageError(f"blob vanished: {rel}@{entry['sha']}")
        (dest / rel).parent.mkdir(parents=True, exist_ok=True)
        (dest / rel).write_bytes(b)
    for sub in ("data/scrape_state", "data/snapshots"):
        (dest / sub).mkdir(parents=True, exist_ok=True)


def replay_one(entry: dict) -> dict | None:
    """Build the contract for one historical snapshot. None if leaked."""
    import src.api.data_contract as dc

    with tempfile.TemporaryDirectory(prefix="cd_replay_") as td:
        dest = Path(td)
        materialise(entry, dest)
        board = board_at(entry["sha"])
        raw = json.loads(board[1])

        rp = Replay(entry["sha"], entry["timestamp"], dest)

        saved_ctx = dc._resolve_league_context
        saved_snap = dc._RANK_SNAPSHOT_PATH
        saved_state = dc.Path if False else None  # noqa: F841
        dc._resolve_league_context = lambda *a, **k: dict(PINNED_LEAGUE_CONTEXT)
        dc._RANK_SNAPSHOT_PATH = dest / "data" / "snapshots" / "ranks_last.json"
        try:
            with rp.guard(), contextlib.redirect_stdout(io.StringIO()):
                contract = dc.build_api_data_contract(
                    raw, csv_root=dest, suppress_market_corridor_clamp=False
                )
        except LeakageError as exc:
            print(f"    !! LEAK on {entry['sha'][:9]}: {exc}")
            return None
        finally:
            dc._resolve_league_context = saved_ctx
            dc._RANK_SNAPSHOT_PATH = saved_snap

        if rp.leaks:
            print(f"    !! LEAK on {entry['sha'][:9]}: {sorted(set(rp.leaks))[:3]}")
            return None
        return contract


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--matrix", action="store_true")
    ap.add_argument("--replay", action="store_true")
    ap.add_argument("--per-day", type=int, default=1)
    ap.add_argument("--limit", type=int, default=400)
    args = ap.parse_args()
    if not (args.matrix or args.replay):
        ap.error("pass --matrix or --replay")

    needed = required_csvs()
    print(f"== required market-data inputs (instrumented from current HEAD): {len(needed)} ==")
    for p in needed:
        print(f"   {p}")

    commits = refresh_commits(args.limit)
    print(f"\n== automated-refresh commits found: {len(commits)} ==")
    if commits:
        print(f"   newest {commits[0][1]}  oldest {commits[-1][1]}")

    rows = matrix(commits, needed)

    # One representative snapshot per day, newest-first within the day.
    by_day: dict[str, list[dict]] = {}
    for r in rows:
        by_day.setdefault(r["day"], []).append(r)
    reps = [sorted(v, key=lambda r: r["timestamp"], reverse=True)[0] for v in by_day.values()]
    reps.sort(key=lambda r: r["timestamp"])

    print(f"\n== compatibility matrix: {len(rows)} commits over {len(by_day)} distinct days ==")
    print(f"  {'day':<12}{'timestamp':<26}{'sha':<11}{'present':>9}{'missing':>9}  usable")
    for r in reps:
        print(
            f"  {r['day']:<12}{r['timestamp']:<26}{r['sha'][:9]:<11}"
            f"{r['present']:>9}{len(r['missing']):>9}  {r['usable']}"
        )

    usable = [r for r in reps if r["usable"] == "usable"]
    print(f"\n  usable representative days: {len(usable)} of {len(reps)}")

    payload = {
        "codeSha": _git("rev-parse", "HEAD").strip(),
        "requiredInputs": needed,
        "commitsScanned": len(rows),
        "distinctDays": len(by_day),
        "matrix": rows,
        "representativeDays": reps,
        "pinnedLeagueContext": PINNED_LEAGUE_CONTEXT,
    }
    (OUT / "cd_historical_matrix.json").write_text(json.dumps(payload, indent=1))
    print(f"\nwrote {OUT / 'cd_historical_matrix.json'}")

    if not args.replay:
        return 0

    print(f"\n== replaying {len(usable)} usable day(s), current code + historical inputs ==")
    results = []
    for r in usable:
        c = replay_one(r)
        if c is None:
            continue
        rows_a = c.get("playersArray") or []
        idp = [
            x
            for x in rows_a
            if x.get("canonicalConsensusRank") and str(x.get("assetClass") or "") != "offense"
        ]
        clamped = [
            x
            for x in idp
            if isinstance(x.get("marketCorridorClamp"), dict)
            and x["marketCorridorClamp"].get("applied")
        ]
        results.append(
            {
                "day": r["day"],
                "sha": r["sha"],
                "timestamp": r["timestamp"],
                "boardSha256": r["boardSha256"],
                "csvHashes": r["csvHashes"],
                "totalRows": len(rows_a),
                "idpRows": len(idp),
                "clamped": len(clamped),
            }
        )
        print(
            f"  {r['day']}  {r['sha'][:9]}  rows={len(rows_a):<5} idp={len(idp):<4} "
            f"clamped={len(clamped)}"
        )

    (OUT / "cd_historical_replays.json").write_text(json.dumps(results, indent=1))
    print(f"\nwrote {OUT / 'cd_historical_replays.json'}  ({len(results)} successful replays)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
