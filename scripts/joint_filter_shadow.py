#!/usr/bin/env python3
"""Joint robust-filter shadow ledger (Batch 3 Unit F).

Runs the #1571 filter half (``joint_outlier_sparse_challenger``; the sparse half
``joint_sparse_limited_evidence`` pinned OFF) beside the incumbent Hampel filter
in SHADOW, and appends one record per board to an append-only ledger under
gitignored ``data/robust_filter_shadow/``. It never writes a served value, never
flips a flag and never promotes anything.

Subcommands:

``record``      the newest production payload on this box (``exports/latest`` or
                ``data/``), built through the deployed code and the live tree.
                What the ``dynasty-joint-filter-shadow`` timer runs.
                ``--then-evaluate`` also refreshes the live evaluation.
``backfill``    every archived scrape in ``exports/archive``, each rebuilt from
                its OWN point-in-time inputs (the archive's payload, the CSVs
                committed with it, per-source dataset state replayed from git
                history up to that commit). Labelled "archived inputs rebuilt
                through today's pipeline code" -- never what production served.
``evaluate``    the preregistered outcome evaluation over the ledger.
``adversarial`` constructed trap / stale-cluster / correlated-family /
                broken-scale cases on real rows (function level and, with
                ``--full-pipeline``, through the whole build).
``summary``     a compact per-board census for committing as evidence.

Exit codes (repo convention):
    0  recorded / evaluated (including an idempotent no-op)
    1  soft failure (no payload found, git history unavailable, write error)
    2  a built contract came back structurally wrong
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import io
import json
import os
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.robust_filter_shadow import ledger as L  # noqa: E402
from src.robust_filter_shadow import record as R  # noqa: E402

ARCHIVE_DIR = REPO_ROOT / "exports" / "archive"
STATE_REPLAY_SINCE = "2026-04-01"  # the production backfill's own window
TOLERABLE_FOR_S1 = frozenset({"KTC_TradeDB", "KTC_WaiverDB"})


def log(msg: str) -> None:
    print(f"[joint-filter-shadow] {msg}", flush=True)


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _git(*args: str, binary: bool = False) -> Any:
    out = subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True, check=True)
    return out.stdout if binary else out.stdout.decode("utf-8")


class CatFile:
    """One ``git cat-file --batch`` process for many blob reads."""

    def __init__(self) -> None:
        self.proc = subprocess.Popen(
            ["git", "cat-file", "--batch"],
            cwd=REPO_ROOT,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
        )

    def read(self, spec: str) -> bytes | None:
        assert self.proc.stdin is not None and self.proc.stdout is not None
        self.proc.stdin.write(spec.encode("utf-8") + b"\n")
        self.proc.stdin.flush()
        header = self.proc.stdout.readline().decode("utf-8").split()
        if len(header) < 3 or header[1] == "missing":
            return None
        data = self.proc.stdout.read(int(header[2]))
        self.proc.stdout.read(1)
        return data

    def close(self) -> None:
        if self.proc.stdin:
            self.proc.stdin.close()
        self.proc.wait(timeout=30)


# ── board identity / pins ───────────────────────────────────────────────


def _degraded(payload: dict) -> list[str]:
    """Critical sources the scrape failed -- the contract's own definition.

    The same rule as ``tests/archive_fixtures._degraded_critical_sources`` (a
    test pins that they agree), restated here because the box timer must not
    import from ``tests/``.
    """
    from src.api.data_contract import (  # noqa: PLC0415
        TOLERABLE_PARTIAL_SOURCES,
        critical_primary_for_run_source,
    )

    settings = payload.get("settings") if isinstance(payload.get("settings"), dict) else {}
    summary = settings.get("sourceRunSummary") if isinstance(settings, dict) else None
    if not isinstance(summary, dict):
        return []
    degraded = set()
    for key in ("partialSources", "failedSources", "timedOutSources"):
        for src in summary.get(key) or []:
            name = str(src)
            if (
                name not in TOLERABLE_PARTIAL_SOURCES
                and critical_primary_for_run_source(name) is not None
            ):
                degraded.add(name)
    return sorted(degraded)


def _completeness(payload: dict) -> str:
    degraded = _degraded(payload)
    if not degraded:
        return "complete"
    if set(degraded) <= TOLERABLE_FOR_S1:
        return "degraded_only:" + ",".join(degraded)
    return "degraded:" + ",".join(degraded)


def _league_snapshots() -> dict[str, str]:
    leagues = REPO_ROOT / "data" / "leagues"
    if not leagues.is_dir():
        return {}
    return {p.name: R.file_sha256(p) for p in sorted(leagues.glob("*.json"))}


def _base_pins() -> dict[str, Any]:
    from src.api import data_contract as dc  # noqa: PLC0415
    from src.api import feature_flags  # noqa: PLC0415
    from src.api import value_replay as vr  # noqa: PLC0415

    return {
        "codeRevision": vr._git("rev-parse", "HEAD"),
        "workingTreeDirty": vr._dirty(),
        "pipelineFingerprint": R.pipeline_fingerprint(REPO_ROOT),
        "flagsAtRecord": feature_flags.snapshot(),
        "variants": {
            "incumbent": {R.CHALLENGER_FLAG: False, R.SPARSE_FLAG: False},
            "challenger": {R.CHALLENGER_FLAG: True, R.SPARSE_FLAG: False},
        },
        "hampel": {
            "k": dc._HAMPEL_K,
            "minN": dc._HAMPEL_MIN_N,
            "minThreshold": dc._HAMPEL_MIN_THRESHOLD,
        },
        "familyCap": dc.FAMILY_WEIGHT_CAP_DEFAULT,
        "contractVersion": dc.CONTRACT_VERSION,
        "localLeagueSnapshots": _league_snapshots(),
    }


def _check_contract(contract: Any) -> bool:
    return isinstance(contract, dict) and isinstance(contract.get("playersArray"), list)


def record_board(
    raw: dict,
    *,
    mode: str,
    board: dict[str, Any],
    pins: dict[str, Any],
    base: Path,
    csv_root: Path | None,
) -> tuple[dict[str, Any], bool] | None:
    """Build both variants, append the record, write the panel."""
    incumbent, challenger = R.build_pair(raw, csv_root)
    if not (_check_contract(incumbent) and _check_contract(challenger)):
        return None
    comparison = R.shadow_record(incumbent, challenger)
    panel = R.observation_panel(incumbent)
    from src.api.data_contract import correlation_group_for  # noqa: PLC0415

    families = sorted(
        {correlation_group_for(s) for row in panel["rows"].values() for s in row["o"]}
    )
    board = {
        **board,
        "votingSources": sorted({s for row in panel["rows"].values() for s in row["o"]}),
        "votingFamilies": families,
        "boardHashIncumbent": _board_hash(incumbent),
        "boardHashChallenger": _board_hash(challenger),
    }
    rec = R.assemble_record(
        mode=mode, board=board, pins=pins, comparison=comparison, recorded_at=_now()
    )
    path, _written_panel = L.write_panel(base, R.panel_identity(board, pins), panel)
    rec["panel"] = str(path.relative_to(base)).replace("\\", "/")
    # Panel identity is a subset of the fields already in the key; re-key is unnecessary.
    written = L.append_record(L.ledger_path(base), rec)
    return rec, written


def _board_hash(contract: dict) -> str:
    from src.api import value_replay as vr  # noqa: PLC0415

    return vr.board_hash(contract)


# ── live record ─────────────────────────────────────────────────────────


def newest_live_payload() -> tuple[Path, bytes, dict] | None:
    for directory in (REPO_ROOT / "exports" / "latest", REPO_ROOT / "data"):
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("dynasty_data*.json"), reverse=True):
            try:
                data = path.read_bytes()
                raw = json.loads(data)
            except (OSError, ValueError) as exc:
                log(f"skip {path.name}: {exc}")
                continue
            if isinstance(raw, dict):
                return path, data, raw
    return None


def cmd_record(args: argparse.Namespace) -> int:
    found = newest_live_payload()
    if found is None:
        log("no payload under exports/latest or data/ -- nothing to record")
        return 1
    path, data, raw = found
    pins = {
        **_base_pins(),
        "csvTreeSha256": R.tree_sha256(REPO_ROOT, ["CSVs/site_raw"], "*.csv"),
        "stateTreeSha256": R.tree_sha256(REPO_ROOT, ["data/scrape_state"], "*_dataset.json"),
        "inputs": "live tree (CSVs/site_raw, data/scrape_state) at record time",
    }
    board = {
        "source": str(path.relative_to(REPO_ROOT)).replace("\\", "/"),
        "payloadSha256": hashlib.sha256(data).hexdigest(),
        "scrapeTimestamp": raw.get("scrapeTimestamp") or raw.get("date"),
        "completeness": _completeness(raw),
    }
    result = record_board(
        raw, mode=R.MODE_LIVE, board=board, pins=pins, base=args.dir, csv_root=None
    )
    if result is None:
        log("a built contract had no playersArray")
        return 2
    rec, written = result
    log(
        f"{'recorded' if written else 'already recorded'} {board['source']} "
        f"disagree_rows={rec['counts'].get('rowsDisagree', 0)} "
        f"safeguards={rec['safeguardsFired']}"
    )
    if args.then_evaluate:
        return cmd_evaluate(
            argparse.Namespace(dir=args.dir, mode=R.MODE_LIVE, out=None, sensitivities=False)
        )
    return 0


# ── historical backfill ─────────────────────────────────────────────────


def archive_add_commits() -> dict[str, tuple[str, datetime]]:
    """``{archive name: (commit, committer time)}`` for the commit that added it."""
    out = _git(
        "log",
        "--diff-filter=A",
        "--format=@@%H %cI",
        "--name-only",
        "HEAD",
        "--",
        "exports/archive",
    )
    found: dict[str, tuple[str, datetime]] = {}
    current: tuple[str, datetime] | None = None
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("@@"):
            sha, _, stamp = line[2:].partition(" ")
            current = (sha, datetime.fromisoformat(stamp))
        elif current and line.endswith(".zip"):
            found.setdefault(Path(line).name, current)
    return found


def load_archive(path: Path) -> tuple[bytes, dict, dict[str, bytes]]:
    with zipfile.ZipFile(path) as zf:
        names = sorted(
            n for n in zf.namelist() if n.startswith("dynasty_data_") and n.endswith(".json")
        )
        data = zf.read(names[-1])
        site = {
            Path(n).name: zf.read(n)
            for n in zf.namelist()
            if n.startswith("site_raw/") and n.endswith(".csv")
        }
    return data, json.loads(data), site


class StateReplayer:
    """Per-source dataset state replayed from git history, advanced in time order.

    The same observation sequence ``scripts/backfill_source_datasets.py`` uses
    (committer time, ``observe`` per committed CSV version), snapshotted at each
    board's cut instead of only at the end -- so no future change is visible.
    """

    def __init__(self, since: str = STATE_REPLAY_SINCE) -> None:
        from scripts.backfill_source_datasets import history  # noqa: PLC0415
        from scripts.record_source_datasets import broad_policy, recorded_sources  # noqa: PLC0415

        self.sources = [
            (key, str(path.relative_to(REPO_ROOT)).replace("\\", "/"), signal)
            for key, path, signal in recorded_sources()
        ]
        self.policy = broad_policy()
        self.history = {key: history(rel, "HEAD", since) for key, rel, _s in self.sources}
        self.position = {key: 0 for key, _r, _s in self.sources}
        self.state: dict[str, dict | None] = {key: None for key, _r, _s in self.sources}
        self.cat = CatFile()
        self.since = since

    def advance(self, cut: datetime) -> None:
        from src.sources.dataset_integrity import FAILED, ParsedBoard, parse_board  # noqa: PLC0415
        from src.sources.dataset_state import observe  # noqa: PLC0415

        for key, rel, signal in self.sources:
            commits = self.history[key]
            while self.position[key] < len(commits) and commits[self.position[key]][1] <= cut:
                sha, stamp = commits[self.position[key]]
                blob = self.cat.read(f"{sha}:{rel}")
                if blob is None:
                    board = ParsedBoard(health=FAILED, errors=["missing at commit"])
                else:
                    board = parse_board(blob.decode("utf-8", errors="replace"), signal=signal)
                self.state[key] = observe(
                    self.state[key],
                    source_key=key,
                    board=board,
                    observed_at=stamp,
                    policy=self.policy,
                )
                self.position[key] += 1

    def write(self, state_dir: Path) -> None:
        from src.sources.dataset_state import save_state, state_path  # noqa: PLC0415
        from src.sources.freshness import STYLE_SNAPSHOT, classify_style, default_config  # noqa: PLC0415

        cfg = default_config()
        state_dir.mkdir(parents=True, exist_ok=True)
        for key, state in self.state.items():
            if state is None:
                continue
            snapshot = copy.deepcopy(state)
            for subset in snapshot.get("subsets", {}).values():
                style, _ = classify_style(subset.get("changeHistory") or [], cfg)
                if style == STYLE_SNAPSHOT:
                    subset["rowChangedAt"] = {}
            save_state(state_path(state_dir, key), snapshot)

    def close(self) -> None:
        self.cat.close()


def materialize_tree(root: Path, commit: str, site_overlay: dict[str, bytes]) -> None:
    """``root/CSVs/site_raw`` as committed at ``commit``, overlaid with the archive's copies."""
    data = _git("archive", commit, "CSVs/site_raw", binary=True)
    with tarfile.open(fileobj=io.BytesIO(data)) as tar:
        tar.extractall(root, filter="data")  # noqa: S202 -- our own repository's archive
    target = root / "CSVs" / "site_raw"
    target.mkdir(parents=True, exist_ok=True)
    for name, blob in site_overlay.items():
        (target / name).write_bytes(blob)


def iter_archives(include_degraded: bool) -> Iterator[tuple[Path, bytes, dict, dict, str]]:
    for path in sorted(ARCHIVE_DIR.glob("dynasty_export_*.zip")):
        try:
            data, raw, site = load_archive(path)
        except (OSError, ValueError, zipfile.BadZipFile, IndexError) as exc:
            log(f"skip {path.name}: {exc}")
            continue
        completeness = _completeness(raw)
        if completeness == "complete" or (
            include_degraded and completeness.startswith("degraded_only:")
        ):
            yield path, data, raw, site, completeness


def cmd_backfill(args: argparse.Namespace) -> int:
    from src.api import value_replay as vr  # noqa: PLC0415

    if vr._dirty():
        log("WARNING: working tree is dirty; records will carry workingTreeDirty=true")
    try:
        if _git("rev-parse", "--is-shallow-repository").strip() == "true":
            # A shallow clone replays dataset state from whatever history it
            # happens to hold, and the boards would look complete while their
            # freshness clocks were not (same refusal as consensus_edge.panel).
            log("shallow clone: run `git fetch --unshallow` first")
            return 1
        adds = archive_add_commits()
    except subprocess.CalledProcessError as exc:
        log(f"git history unavailable: {exc}")
        return 1
    archives = list(iter_archives(args.include_degraded))
    if args.limit:
        archives = archives[-args.limit :]
    if not archives:
        log("no archives to replay")
        return 1
    plan = []
    for path, data, raw, site, completeness in archives:
        commit, cut = adds.get(path.name, (None, None))
        if commit is None:
            log(f"skip {path.name}: no commit adds it (untracked archive)")
            continue
        plan.append((cut, path, data, raw, site, completeness, commit))
    plan.sort(key=lambda item: item[0])
    base_pins = _base_pins()
    replayer = StateReplayer()
    written = skipped = 0
    try:
        for cut, path, data, raw, site, completeness, commit in plan:
            replayer.advance(cut)
            with tempfile.TemporaryDirectory(prefix="jfs-") as tmp:
                root = Path(tmp)
                materialize_tree(root, commit, site)
                replayer.write(root / "data" / "scrape_state")
                pins = {
                    **base_pins,
                    "csvCommit": commit,
                    "csvTreeSha256": R.tree_sha256(root, ["CSVs/site_raw"], "*.csv"),
                    "stateTreeSha256": R.tree_sha256(root, ["data/scrape_state"], "*_dataset.json"),
                    "archiveSiteRawOverlay": sorted(site),
                    "stateReplay": {
                        "method": "git_history_replay",
                        "since": replayer.since,
                        "through": cut.isoformat(),
                    },
                    "inputs": "archived payload + CSVs committed with the archive + replayed dataset state",
                }
                board = {
                    "archive": path.name,
                    "payloadSha256": hashlib.sha256(data).hexdigest(),
                    "scrapeTimestamp": raw.get("scrapeTimestamp") or raw.get("date"),
                    "completeness": completeness,
                }
                result = record_board(
                    raw, mode=R.MODE_REPLAY, board=board, pins=pins, base=args.dir, csv_root=root
                )
            if result is None:
                log(f"{path.name}: built contract had no playersArray")
                return 2
            rec, was_written = result
            written += was_written
            skipped += not was_written
            log(
                f"{path.name} [{completeness}] disagree_rows={rec['counts'].get('rowsDisagree', 0)} "
                f"K={rec['counts'].get('obsIncumbentOnlyDrop', 0)} "
                f"X={rec['counts'].get('obsChallengerOnlyDrop', 0)} "
                f"safeguards={rec['safeguardsFired']} {'new' if was_written else 'exists'}"
            )
    finally:
        replayer.close()
    log(f"done: {written} written, {skipped} already present")
    return 0


# ── evaluation / summary ────────────────────────────────────────────────


def load_boards(base: Path, mode: str) -> list:
    from src.robust_filter_shadow.outcomes import Board, parse_time  # noqa: PLC0415

    boards = []
    seen: dict[str, Any] = {}
    for rec in L.iter_records(L.ledger_path(base)):
        if rec.get("mode") != mode:
            continue
        # One record per board payload: the newest code revision wins, so a
        # re-run under new code supersedes (never mixes with) the old one.
        seen[(rec.get("board") or {}).get("payloadSha256")] = rec
    for rec in seen.values():
        at = parse_time((rec.get("board") or {}).get("scrapeTimestamp"))
        panel_path = base / str(rec.get("panel"))
        if at is None or not panel_path.exists():
            continue
        boards.append(Board(record=rec, panel=L.read_panel(panel_path), at=at))
    return boards


def cmd_evaluate(args: argparse.Namespace) -> int:
    from src.robust_filter_shadow import outcomes as O  # noqa: PLC0415

    boards = load_boards(args.dir, args.mode)
    if not boards:
        log(f"no {args.mode} records with panels -- nothing to evaluate")
        return 1
    result: dict[str, Any] = {
        "schema": f"{R.SCHEMA}/evaluation",
        "mode": args.mode,
        "label": R.LABELS[args.mode],
        "preregistration": "docs/valuation/evidence/joint-filter-shadow-2026-10-01/PREREGISTRATION.md",
        "computedAt": _now(),
        "codeRevisions": sorted(
            {str((b.record.get("pins") or {}).get("codeRevision")) for b in boards}
        ),
        "primary": O.evaluate(boards),
    }
    if getattr(args, "sensitivities", False):
        degraded = tuple(
            sorted({(b.record.get("board") or {}).get("completeness") for b in boards})
        )
        result["sensitivities"] = {
            "S1_all_archives": O.evaluate(boards, O.EvaluationConfig(completeness=degraded)),
            "S2_episode_dedupe": O.evaluate(boards, O.EvaluationConfig(episode_dedupe=True)),
            "S3_offense": O.evaluate(boards, O.EvaluationConfig(asset_class="offense")),
            "S3_idp": O.evaluate(boards, O.EvaluationConfig(asset_class="idp")),
            "S4_ktc_split_era": O.evaluate(boards, O.EvaluationConfig(ktc_split_only=True)),
            "S6_ktc_merged_targets": O.evaluate(boards, O.EvaluationConfig(merge_ktc=True)),
        }
    out = args.out or (args.dir / f"evaluation_{args.mode}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(result, indent=1, sort_keys=True, default=str) + "\n", encoding="utf-8"
    )
    decision = (result["primary"] or {}).get("decision") or {}
    log(f"evaluation -> {out} verdict={decision.get('verdict')}")
    return 0


def cmd_summary(args: argparse.Namespace) -> int:
    rows = []
    for rec in L.iter_records(L.ledger_path(args.dir)):
        if rec.get("mode") != args.mode:
            continue
        board, counts = rec.get("board") or {}, rec.get("counts") or {}
        rows.append(
            {
                "board": board.get("archive") or board.get("source"),
                "scrapeTimestamp": board.get("scrapeTimestamp"),
                "completeness": board.get("completeness"),
                "payloadSha256": board.get("payloadSha256"),
                "codeRevision": (rec.get("pins") or {}).get("codeRevision"),
                "votingFamilies": len(board.get("votingFamilies") or []),
                "filterRows": counts.get("filterRows", 0),
                "incumbentDrops": counts.get("incumbentDrops", 0),
                "challengerDrops": counts.get("challengerDrops", 0),
                "rowsDisagree": counts.get("rowsDisagree", 0),
                "obsIncumbentOnlyDrop": counts.get("obsIncumbentOnlyDrop", 0),
                "obsChallengerOnlyDrop": counts.get("obsChallengerOnlyDrop", 0),
                "rowsValueChanged": counts.get("rowsValueChanged", 0),
                "reproduced": [
                    counts.get("reproducedIncumbent", 0),
                    counts.get("reproducedChallenger", 0),
                    counts.get("reproductionChecked", 0),
                ],
                "safeguardsFired": rec.get("safeguardsFired"),
                "topChurn": rec.get("topChurn"),
            }
        )
    rows.sort(key=lambda r: str(r["scrapeTimestamp"]))
    out = args.out or (args.dir / f"summary_{args.mode}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": f"{R.SCHEMA}/summary",
        "mode": args.mode,
        "label": R.LABELS[args.mode],
        "boards": rows,
    }
    out.write_text(json.dumps(payload, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    log(f"summary of {len(rows)} boards -> {out}")
    return 0


def cmd_adversarial(args: argparse.Namespace) -> int:
    from src.robust_filter_shadow import adversarial as A  # noqa: PLC0415

    archives = list(iter_archives(False))
    if not archives:
        log("no complete archive for adversarial cases")
        return 1
    path, _data, raw, site, _c = archives[-1]
    adds = archive_add_commits()
    commit, cut = adds[path.name]
    replayer = StateReplayer()
    try:
        replayer.advance(cut)
        with tempfile.TemporaryDirectory(prefix="jfs-adv-") as tmp:
            root = Path(tmp)
            materialize_tree(root, commit, site)
            replayer.write(root / "data" / "scrape_state")
            result = A.run_all(raw, root, full_pipeline=args.full_pipeline)
    finally:
        replayer.close()
    result["board"] = {"archive": path.name, "csvCommit": commit}
    out = args.out or (args.dir / "adversarial.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(result, indent=1, sort_keys=True, default=str) + "\n", encoding="utf-8"
    )
    log(f"adversarial -> {out} all_expected={result.get('allExpected')}")
    return 0


def main(argv: list[str] | None = None) -> int:
    os.environ.setdefault("PYTHONUTF8", "1")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dir", type=Path, default=L.DEFAULT_DIR, help="ledger directory")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("record")
    p.add_argument("--then-evaluate", action="store_true")
    p = sub.add_parser("backfill")
    p.add_argument("--include-degraded", action="store_true", help="S1: KTC_TradeDB/WaiverDB-only")
    p.add_argument("--limit", type=int, default=0)
    p = sub.add_parser("evaluate")
    p.add_argument("--mode", default=R.MODE_REPLAY, choices=sorted(R.LABELS))
    p.add_argument("--out", type=Path)
    p.add_argument("--sensitivities", action="store_true")
    p = sub.add_parser("summary")
    p.add_argument("--mode", default=R.MODE_REPLAY, choices=sorted(R.LABELS))
    p.add_argument("--out", type=Path)
    p = sub.add_parser("adversarial")
    p.add_argument("--full-pipeline", action="store_true")
    p.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    handlers = {
        "record": cmd_record,
        "backfill": cmd_backfill,
        "evaluate": cmd_evaluate,
        "summary": cmd_summary,
        "adversarial": cmd_adversarial,
    }
    try:
        return handlers[args.command](args)
    except L.PanelConflict as exc:
        log(f"panel conflict (identity reused for different content): {exc}")
        return 2
    except OSError as exc:
        log(f"write/read failure: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
