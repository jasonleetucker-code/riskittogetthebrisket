"""Workstream G2: run the IDP source-integrity evaluation on one archived board.

SHADOW RESEARCH ONLY.  Builds the board in-process from a tracked archive and the
repository tree of the refresh that added it, evaluates it with
``src.robust_filter_shadow.idp_source_integrity_g2`` and writes one JSON record.
It changes no served value, flag, weight, vote or file outside ``--out``.

Board roles (``docs/valuation/idp_accuracy/g2_source_integrity/BOARDS.json``):

* ``dev``      -- development / calibration boards (already spent by V2).
* ``heldout``  -- the G2 held-out board(s).  Run ONCE, at the evaluator commit.

A board inside the Outlier Integrity V2.1 seal (added at or after V2.1's T0 and
before the latest possible end of its held-out window) is REFUSED in every role:
reading it for source-integrity analysis would contaminate V2.1's held-out set.

Usage::

    python scripts/research_idp_source_integrity_g2.py --board dynasty_export_X.zip --role dev --out OUT.json
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from scripts.research_pinned_board import csv_tree, load_archive  # noqa: E402

BOARDS = REPO / "docs/valuation/idp_accuracy/g2_source_integrity/BOARDS.json"
#: V2.1 T0 (commit 180d2463d2 on claude/outlier-integrity-v2) and the latest
#: possible end of its held-out window (WINDOW_END max 2026-12-02 + 7-day H_TARGET).
V21_SEAL_START = datetime(2026, 10, 20, 20, 0, 30, tzinfo=timezone.utc)
V21_SEAL_END = datetime(2026, 12, 9, 0, 0, 0, tzinfo=timezone.utc)
IDP_SOURCES = (
    "idpTradeCalc",
    "draftSharksIdp",
    "fantasyProsIdp",
    "dlfIdp",
    "dlfRookieIdp",
    "idpShowCombined",
    "idpShow",
)
#: The DLF IDP hold flag: ON in production (owner-held).  The "dlfRestored"
#: variant turns it OFF in-process only, to evaluate DLF's would-be votes and
#: the incumbent filter's reaction to them.  Nothing is persisted.
DLF_HOLD_FLAG = "dlf_offense_only_vote"
VARIANTS = {"served": [], "dlfRestored": [(DLF_HOLD_FLAG, False)]}


def git(*args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(REPO), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def add_commit(archive_rel: str) -> tuple[str, datetime]:
    out = git("log", "--diff-filter=A", "--format=%H %cI", "--", archive_rel).splitlines()
    if not out:
        raise SystemExit(f"no add commit for {archive_rel}")
    sha, when = out[-1].split()
    return sha, datetime.fromisoformat(when).astimezone(timezone.utc)


def in_v21_seal(when: datetime) -> bool:
    return V21_SEAL_START <= when < V21_SEAL_END


def ranked_content(blob: str) -> dict[str, float]:
    """``{vendor name: rank-ish}`` of one CSV version (rank column, else value)."""
    rows = list(csv.DictReader(io.StringIO(blob)))
    if not rows:
        return {}
    cols = rows[0].keys()
    name = next((c for c in ("name", "Player", "player") if c in cols), None)
    rank = next((c for c in ("originalRank", "Rank", "rank") if c in cols), None)
    val = next((c for c in ("value", "3D Value +", "normalizedValue") if c in cols), None)
    out: dict[str, float] = {}
    for i, r in enumerate(rows):
        key = (r.get(name) or "").strip()
        try:
            x = float(r.get(rank)) if rank else -float(r.get(val)) if val else float(i)
        except (TypeError, ValueError):
            x = float(i)
        # a name listed twice keeps one entry per occurrence
        while key in out:
            key += "#2"
        out[key] = x
    return out


def changed_rows(old: dict[str, float], new: dict[str, float]) -> int:
    """Rows whose rank-ish changed, appeared or vanished -- a rename at an
    unchanged rank-ish (one vanished + one appeared at the same number) is not a change."""
    moved = sum(1 for k in old.keys() & new.keys() if old[k] != new[k])
    gone = sorted(old[k] for k in old.keys() - new.keys())
    came = sorted(new[k] for k in new.keys() - old.keys())
    renames = 0
    pool = list(came)
    for x in gone:
        if x in pool:
            pool.remove(x)
            renames += 1
    return moved + (len(gone) - renames) + (len(came) - renames)


def content_clocks(rev: str, sources=IDP_SOURCES, depth: int = 160) -> dict[str, dict]:
    """Git-observed last byte change and last BROAD change of each CSV at ``rev``."""
    from src.robust_filter_shadow.idp_source_integrity_g2 import THRESHOLDS  # noqa: PLC0415

    min_rows, min_frac = THRESHOLDS["broadChangeMinRows"], THRESHOLDS["broadChangeMinFraction"]
    out: dict[str, dict] = {}
    for src in sources:
        path = f"CSVs/site_raw/{src}.csv"
        log = git("log", f"-{depth}", "--format=%H %cI", rev, "--", path).splitlines()
        if not log:
            out[src] = {"lastByteChange": None, "lastBroadChange": None}
            continue
        commits = [(line.split()[0], line.split()[1]) for line in log]

        def iso(s: str) -> str:
            return datetime.fromisoformat(s).astimezone(timezone.utc).isoformat()

        broad = None
        newer = None  # (when, content) of the newer version in the walk
        for sha, when in commits:
            try:
                content = ranked_content(git("show", f"{sha}:{path}"))
            except subprocess.CalledProcessError:
                content = {}
            if newer is not None:
                n = changed_rows(content, newer[1])
                if n >= min_rows and n >= min_frac * max(len(newer[1]), 1):
                    broad = newer[0]
                    break
            newer = (when, content)
        out[src] = {
            "lastByteChange": iso(commits[0][1]),
            "lastBroadChange": iso(broad) if broad else None,
            "searchDepthCommits": len(commits),
            "broadFoundWithinDepth": broad is not None,
        }
    return out


def admit(board: str, role: str) -> tuple[dict, str, str, datetime]:
    """Registration, add commit and the V2.1 seal -- all decided from git
    metadata BEFORE any archive byte is read (deviation D4: the seal check used
    to run after ``load_archive``)."""
    manifest = json.loads(BOARDS.read_text(encoding="utf-8"))
    entry = next((b for b in manifest["boards"] if b["board"] == board), None)
    if entry is None or entry["role"] != role:
        raise SystemExit(f"{board} is not registered with role {role!r} in {BOARDS.name}")
    rel = f"exports/archive/{board}"
    rev, when = add_commit(rel)
    if in_v21_seal(when):
        raise SystemExit(f"{board}: inside the Outlier Integrity V2.1 held-out seal; refused")
    if rev != entry["addCommit"]:
        raise SystemExit(f"{board}: add commit {rev} != registered {entry['addCommit']}")
    return entry, rel, rev, when


def run(board: str, role: str, out: Path, seed: int) -> dict:
    from src.api import value_replay as vr  # noqa: PLC0415
    from src.robust_filter_shadow import idp_source_integrity_g2 as g2  # noqa: PLC0415

    entry, rel, rev, when = admit(board, role)
    zpath, member, blob, raw = load_archive(rel)
    zsha = hashlib.sha256(zpath.read_bytes()).hexdigest()
    if zsha != entry["zipSha256"]:
        raise SystemExit(f"{board}: zip sha256 {zsha} != registered {entry['zipSha256']}")
    lineage = json.loads((REPO / "config/sources/source_lineage.json").read_text(encoding="utf-8"))
    clocks = content_clocks(rev)
    record: dict = {
        "schema": g2.SCHEMA,
        "board": board,
        "role": role,
        "zipSha256": zsha,
        "payloadSha256": hashlib.sha256(blob).hexdigest(),
        "addCommit": rev,
        "addCommitTime": when.isoformat(),
        "evaluatorCommit": git("rev-parse", "HEAD"),
        "seed": seed,
        "contentClocks": clocks,
        "variants": {},
    }
    with csv_tree(rev) as (root, prov):
        record["csvTree"] = prov
        tables = g2.read_csv_tables(root / "CSVs" / "site_raw", IDP_SOURCES)
        record["csvTableSha256"] = {
            s: hashlib.sha256((root / "CSVs/site_raw" / f"{s}.csv").read_bytes()).hexdigest()
            for s in sorted(tables)
        }
        for name, flags in VARIANTS.items():
            t0 = time.perf_counter()
            contract = vr.build(raw, {"csv_root": root, "flags": flags})
            build_s = time.perf_counter() - t0
            panel = g2.extract_panel(contract, tables, lineage)
            vs = contract.get("sourceVotingStatus") or {}
            ev = g2.evaluate_panel(panel, voting_status=vs, content_clocks=clocks, lineage=lineage)
            rec = {
                "flags": flags,
                "buildSeconds": round(build_s, 2),
                "panelDigest": g2.digest(panel),
                "evaluation": ev,
            }
            if name == "served":
                rec["eGates"] = g2.run_e_gates(
                    panel, seed=seed, voting_status=vs, content_clocks=clocks, lineage=lineage
                )
                rec["bGates"] = g2.b_gates(ev, tables)
            record["variants"][name] = rec
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(record, indent=1, sort_keys=True, default=str) + "\n", encoding="utf-8"
    )
    return record


def exploratory(board: str, role: str, out: Path) -> dict:
    """Deviation D1 (logged in DEVIATIONS.md): vendor join coverage by vendor
    order band, served build only.  Added after the held-out read; never a gate.
    Applies the same registration, hash and V2.1-seal guards as ``run``."""
    from src.api import value_replay as vr  # noqa: PLC0415
    from src.robust_filter_shadow import idp_source_integrity_g2 as g2  # noqa: PLC0415

    entry, rel, rev, _when = admit(board, role)
    zpath, _member, _blob, raw = load_archive(rel)
    if hashlib.sha256(zpath.read_bytes()).hexdigest() != entry["zipSha256"]:
        raise SystemExit(f"{board}: zip sha256 mismatch")
    with csv_tree(rev) as (root, _prov):
        tables = g2.read_csv_tables(root / "CSVs" / "site_raw", IDP_SOURCES)
        contract = vr.build(raw, {"csv_root": root, "flags": VARIANTS["served"]})
        cov = g2.vendor_join_coverage(contract, tables)
    record = {
        "schema": g2.SCHEMA + "#exploratory-D1",
        "board": board,
        "role": role,
        "evaluatorCommit": git("rev-parse", "HEAD"),
        "vendorJoinCoverage": cov,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(record, indent=1, sort_keys=True, default=str) + "\n", encoding="utf-8"
    )
    return record


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--board", required=True)
    ap.add_argument("--role", required=True, choices=("dev", "heldout"))
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--seed", type=int, default=20261027)
    ap.add_argument("--exploratory", action="store_true", help="deviation D1 coverage only")
    args = ap.parse_args(argv)
    if args.exploratory:
        exploratory(args.board, args.role, args.out)
        return 0
    rec = run(args.board, args.role, args.out, args.seed)
    served = rec["variants"]["served"]
    verdicts = {k: v.get("verdict") for k, v in sorted(served["eGates"].items())}
    verdicts.update(
        {k: v.get("verdict") for k, v in sorted(served["bGates"].items()) if k != "summary"}
    )
    print(json.dumps(verdicts, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
