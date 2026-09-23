#!/usr/bin/env python3
"""Seed every source's dataset state from its git history.

Git records a tracked CSV only when its content changes, so the commit
history of ``CSVs/site_raw/<key>.csv`` is a complete, timestamped record of
every board the refresh pipeline ever committed.  Replaying it in commit
order through :func:`src.sources.dataset_state.observe` reconstructs the
change history, both change clocks and per-row observation age — which is
what lets cadence be learned on day one instead of months from now.

Deterministic: same history → byte-identical state.  Needs a history that
reaches back far enough (``git fetch --shallow-since=YYYY-MM-DD``); a shallow
clone simply seeds from what it has, and the report says where it started.
Observation time = the commit's committer time (the refresh commits minutes
after the scrape; that lag is far below any source's cadence).

Usage:
    python scripts/backfill_source_datasets.py [--since 2026-04-01] [--ref origin/main]
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.record_source_datasets import (  # noqa: E402
    DEFAULT_STATE_DIR,
    broad_policy,
    recorded_sources,
)
from src.sources.dataset_integrity import FAILED, ParsedBoard, parse_board  # noqa: E402
from src.sources.dataset_state import observe, save_state, state_path  # noqa: E402
from src.sources.freshness import STYLE_SNAPSHOT, classify_style, default_config  # noqa: E402


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO_ROOT, check=True, capture_output=True, text=True
    ).stdout


def history(
    rel_path: str, ref: str, since: str | None, until: str | None = None
) -> list[tuple[str, datetime]]:
    cmd = ["log", "--reverse", "--format=%H %cI", ref]
    if since:
        cmd.append(f"--since={since}")
    if until:
        # As-of replay for backtests: nothing committed after ``until`` is seen.
        cmd.append(f"--until={until}")
    cmd += ["--", rel_path]
    out = []
    for line in _git(*cmd).splitlines():
        sha, _, stamp = line.partition(" ")
        if sha and stamp:
            out.append((sha, datetime.fromisoformat(stamp)))
    return out


def backfill_source(
    key: str,
    rel_path: str,
    signal: str,
    *,
    ref: str,
    since: str | None,
    state_dir: Path,
    until: str | None = None,
) -> dict:
    policy = broad_policy()
    state = None
    commits = history(rel_path, ref, since, until)
    for sha, stamp in commits:
        try:
            text = _git("show", f"{sha}:{rel_path}")
        except subprocess.CalledProcessError:
            board = ParsedBoard(health=FAILED, errors=["missing at commit"])
        else:
            board = parse_board(text, signal=signal)
        state = observe(state, source_key=key, board=board, observed_at=stamp, policy=policy)
    if state is None:
        return {"key": key, "commits": 0}
    # Snapshot subsets do not need per-row clocks: every change republishes.
    cfg = default_config()
    for subset in state.get("subsets", {}).values():
        style, _ = classify_style(subset.get("changeHistory") or [], cfg)
        if style == STYLE_SNAPSHOT:
            subset["rowChangedAt"] = {}
    state["backfill"] = {
        "method": "git_history_replay",
        "ref": ref,
        "since": since,
        "firstCommitAt": commits[0][1].isoformat() if commits else None,
        "commits": len(commits),
    }
    save_state(state_path(state_dir, key), state)
    return {"key": key, "commits": len(commits), "first": commits[0][1].isoformat()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--ref", default="HEAD")
    parser.add_argument("--since", default=None)
    parser.add_argument("--until", default=None, help="As-of replay: ignore later commits")
    parser.add_argument("--state-dir", type=Path, default=DEFAULT_STATE_DIR)
    parser.add_argument("--only", nargs="*")
    args = parser.parse_args(argv)
    for key, csv_path, signal in recorded_sources():
        if args.only and key not in args.only:
            continue
        rel = str(csv_path.relative_to(REPO_ROOT))
        summary = backfill_source(
            key,
            rel,
            signal,
            ref=args.ref,
            since=args.since,
            state_dir=args.state_dir,
            until=args.until,
        )
        print(f"{key:26s} commits={summary['commits']:4d} first={summary.get('first')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
