#!/usr/bin/env python3
"""Backtest: production vs KTC split vs freshness weighting, and the curve choice.

For each day in the window, rebuilds the board from THAT day's own inputs —
the day's last export-archive payload, the source CSVs as committed at that
moment (``git archive``), and the per-source dataset state replayed from git
history up to that moment (so no future change is visible) — under:

* ``production``   — the current ``main`` code (``--baseline-worktree``), run
                     in a subprocess so its registry and pipeline are untouched;
* ``split``        — this branch with ``source_freshness_weighting`` OFF
                     (KTC Crowd + Trades voting, KTC Market benchmark-only);
* ``fresh_C1..C4`` — this branch with freshness weighting ON under each
                     candidate curve (C4 is the configured default).

``split`` vs ``production`` isolates the KTC signal split; ``fresh_*`` vs
``split`` isolates freshness weighting.  Plus two synthetic probes: how fast
a fast source that stops updating loses authority, and how slowly a
legitimate monthly source does, under each curve.

Writes ``<out>/summary.json``.  Deterministic for a
given repo state.  Usage:

    python scripts/backtest_source_freshness.py --baseline-worktree PATH --out DIR
"""

from __future__ import annotations

import argparse
import copy
import io
import json
import os
import statistics
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.record_source_datasets import broad_policy, recorded_sources  # noqa: E402
from src.api import data_contract as dc  # noqa: E402
from src.api import feature_flags  # noqa: E402
from src.sources import freshness as fr  # noqa: E402
from src.sources.dataset_integrity import parse_board  # noqa: E402
from src.sources.dataset_state import observe, save_state, state_path  # noqa: E402

CURVES = ("C1", "C2", "C3", "C4")
ROW_FIELDS = ("rankDerivedValue", "canonicalConsensusRank", "assetClass", "position")

_BASELINE_BUILD = r"""
import json, sys
sys.path.insert(0, '.')
from src.api.data_contract import build_api_data_contract
raw = json.load(open(sys.argv[1]))
c = build_api_data_contract(raw, csv_root=sys.argv[2])
rows = {r['displayName']: [r.get('rankDerivedValue'), r.get('canonicalConsensusRank'),
        r.get('assetClass'), r.get('position')] for r in c['playersArray']}
json.dump(rows, open(sys.argv[3], 'w'))
"""


def _git(*args: str, binary: bool = False):
    out = subprocess.run(["git", *args], cwd=REPO_ROOT, check=True, capture_output=True)
    return out.stdout if binary else out.stdout.decode()


def day_archives(start: str, end: str) -> list[tuple[str, Path]]:
    """The LAST export archive of each day in [start, end]."""
    by_day: dict[str, Path] = {}
    for p in sorted((REPO_ROOT / "exports" / "archive").glob("dynasty_export_*.zip")):
        day = p.name.split("_")[2]
        iso = f"{day[:4]}-{day[4:6]}-{day[6:8]}"
        if start <= iso <= end:
            by_day[iso] = p
    return sorted(by_day.items())


def archive_time(path: Path) -> datetime:
    _, _, day, hms = path.stem.split("_")
    return datetime.strptime(day + hms, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)


def build_tree(root: Path, as_of: datetime) -> None:
    """CSVs/site_raw exactly as committed at ``as_of``."""
    sha = _git(
        "rev-list", "-1", f"--before={as_of.isoformat()}", "HEAD", "--", "CSVs/site_raw"
    ).strip()
    data = _git("archive", sha, "CSVs/site_raw", binary=True)
    with tarfile.open(fileobj=io.BytesIO(data)) as tar:
        tar.extractall(root)  # noqa: S202 — our own repository's archive


def replay_states(cuts: list[datetime], since: str) -> dict[datetime, dict[str, dict]]:
    """Dataset state per source as of each cut — one replay per source."""
    policy = broad_policy()
    out: dict[datetime, dict[str, dict]] = {c: {} for c in cuts}
    for key, csv_path, signal in recorded_sources():
        rel = str(csv_path.relative_to(REPO_ROOT))
        log = _git("log", "--reverse", "--format=%H %cI", f"--since={since}", "HEAD", "--", rel)
        commits = [
            (sha, datetime.fromisoformat(stamp))
            for sha, _, stamp in (line.partition(" ") for line in log.splitlines())
            if sha
        ]
        state = None
        pending = list(cuts)
        for sha, stamp in commits:
            while pending and stamp > pending[0]:
                if state is not None:
                    out[pending[0]][key] = copy.deepcopy(state)
                pending.pop(0)
            text = _git("show", f"{sha}:{rel}")
            state = observe(
                state,
                source_key=key,
                board=parse_board(text, signal=signal),
                observed_at=stamp,
                policy=policy,
            )
        for cut in pending:
            if state is not None:
                out[cut][key] = copy.deepcopy(state)
    return out


def _set_curve(curve: str | None) -> None:
    fr._CONFIG_CACHE["default"] = fr.load_config(curve=curve) if curve else fr.load_config()
    dc._SOURCE_WEIGHTING_CACHE.clear()


def _set_flag(on: bool) -> None:
    os.environ["RISKIT_FEATURE_SOURCE_FRESHNESS_WEIGHTING"] = "1" if on else "0"
    feature_flags.reload()


def build_branch(raw: dict, root: Path) -> dict[str, dict]:
    contract = dc.build_api_data_contract(raw, csv_root=root)
    return {
        r["displayName"]: {
            "value": r.get("rankDerivedValue"),
            "rank": r.get("canonicalConsensusRank"),
            "assetClass": r.get("assetClass"),
            "position": r.get("position"),
            "state": r.get("sourceWeightState"),
            "retained": r.get("retainedAuthority"),
        }
        for r in contract["playersArray"]
    }


def build_baseline(worktree: Path, payload: Path, root: Path, scratch: Path) -> dict[str, dict]:
    out = scratch / "baseline_rows.json"
    subprocess.run(
        [sys.executable, "-c", _BASELINE_BUILD, str(payload), str(root), str(out)],
        cwd=worktree,
        check=True,
        capture_output=True,
    )
    rows = json.loads(out.read_text())
    return {
        k: {"value": v[0], "rank": v[1], "assetClass": v[2], "position": v[3]}
        for k, v in rows.items()
    }


def compare(a: dict, b: dict, top: int = 25) -> dict:
    """b relative to a."""
    diffs = []
    rank_diffs = []
    for name, ra in a.items():
        rb = b.get(name)
        if not rb or not ra.get("value") or not rb.get("value"):
            continue
        dv = rb["value"] - ra["value"]
        diffs.append((dv, dv / ra["value"], name, ra["assetClass"], ra["value"], rb["value"]))
        if ra.get("rank") and rb.get("rank"):
            rank_diffs.append((rb["rank"] - ra["rank"], name, ra["rank"], rb["rank"]))
    changed = [d for d in diffs if d[0] != 0]
    by_class: dict[str, list[float]] = {}
    for d in changed:
        by_class.setdefault(d[3] or "?", []).append(abs(d[1]))
    return {
        "compared": len(diffs),
        "changed": len(changed),
        "medianAbsPct": round(statistics.median([abs(d[1]) for d in changed]) * 100, 2)
        if changed
        else 0.0,
        "p90AbsPct": round(
            sorted(abs(d[1]) for d in changed)[int(0.9 * (len(changed) - 1))] * 100, 2
        )
        if changed
        else 0.0,
        "byAssetClass": {
            k: {"changed": len(v), "medianAbsPct": round(statistics.median(v) * 100, 2)}
            for k, v in by_class.items()
        },
        "topValueMoves": [
            {
                "player": d[2],
                "assetClass": d[3],
                "from": d[4],
                "to": d[5],
                "pct": round(d[1] * 100, 1),
            }
            for d in sorted(changed, key=lambda d: -abs(d[0]))[:top]
        ],
        "topRankMoves": [
            {"player": r[1], "from": r[2], "to": r[3], "delta": r[0]}
            for r in sorted(rank_diffs, key=lambda r: -abs(r[0]))[:top]
            if r[0] != 0
        ],
    }


def row_state_stats(rows: dict) -> dict:
    states: dict[str, int] = {}
    retained = []
    for r in rows.values():
        if r.get("state"):
            states[r["state"]] = states.get(r["state"], 0) + 1
        if isinstance(r.get("retained"), (int, float)):
            retained.append(r["retained"])
    n = sum(states.values()) or 1
    return {
        "states": states,
        "degradedShare": round(
            (states.get("DEGRADED", 0) + states.get("SEVERELY_DEGRADED", 0)) / n, 4
        ),
        "meanRetainedAuthority": round(statistics.mean(retained), 4) if retained else None,
    }


def synthetic_probes() -> dict:
    """Authority vs age for a fast (12 h) and a monthly (35 d) source."""
    fast = [12, 24, 36, 48, 72, 96]
    monthly_days = [35, 45, 70, 105, 140]
    return {
        curve: {
            "fastSource_E12h": {
                f"{h}h": round(fr.freshness_from_ratio(h / 12.0, curve), 4) for h in fast
            },
            "monthlySource_E35d": {
                f"{d}d": round(fr.freshness_from_ratio(d / 35.0, curve), 4) for d in monthly_days
            },
        }
        for curve in CURVES
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--baseline-worktree", type=Path, required=True)
    parser.add_argument("--start", default="2026-09-10")
    parser.add_argument("--end", default="2026-09-23")
    parser.add_argument("--since", default="2026-04-01")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)

    days = day_archives(args.start, args.end)
    cuts = [archive_time(p) for _, p in days]
    print(f"replaying dataset state for {len(cuts)} cut(s) ...", flush=True)
    states = replay_states(cuts, args.since)

    per_day: dict[str, dict] = {}
    boards_last: dict[str, dict] = {}
    with tempfile.TemporaryDirectory() as tmp:
        for (day, archive), cut in zip(days, cuts):
            root = Path(tmp) / day
            build_tree(root, cut)
            sdir = root / "data" / "scrape_state"
            for key, st in states[cut].items():
                save_state(state_path(sdir, key), st)
            with zipfile.ZipFile(archive) as z:
                member = next(
                    n for n in z.namelist() if n.startswith("dynasty_data_") and n.endswith(".json")
                )
                raw = json.loads(z.read(member))
            payload_path = root / "payload.json"
            payload_path.write_text(json.dumps(raw))
            boards = {
                "production": build_baseline(args.baseline_worktree, payload_path, root, root)
            }
            _set_curve(None)
            _set_flag(False)
            boards["split"] = build_branch(raw, root)
            _set_flag(True)
            for curve in CURVES:
                _set_curve(curve)
                boards[f"fresh_{curve}"] = build_branch(raw, root)
            _set_curve(None)
            per_day[day] = {
                "asOf": raw.get("scrapeTimestamp"),
                "splitVsProduction": compare(boards["production"], boards["split"]),
                **{
                    f"fresh_{c}VsSplit": compare(boards["split"], boards[f"fresh_{c}"])
                    for c in CURVES
                },
                "fresh_C4VsProduction": compare(boards["production"], boards["fresh_C4"]),
                **{f"fresh_{c}RowStates": row_state_stats(boards[f"fresh_{c}"]) for c in CURVES},
            }
            boards_last = boards
            print(
                f"{day}: split {per_day[day]['splitVsProduction']['changed']} changed, "
                f"C4 {per_day[day]['fresh_C4VsSplit']['changed']} changed "
                f"(median {per_day[day]['fresh_C4VsSplit']['medianAbsPct']}%)",
                flush=True,
            )
    os.environ.pop("RISKIT_FEATURE_SOURCE_FRESHNESS_WEIGHTING", None)
    feature_flags.reload()

    summary = {
        "window": [args.start, args.end],
        "days": per_day,
        "syntheticProbes": synthetic_probes(),
        "lastDayBoards": {
            k: {n: r for n, r in v.items()}
            for k, v in boards_last.items()
            if k in ("production", "split", "fresh_C4")
        },
    }
    (args.out / "summary.json").write_text(json.dumps(summary, indent=1, sort_keys=True))
    print(f"wrote {args.out / 'summary.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
