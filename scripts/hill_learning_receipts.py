"""Record AL-0 learning receipts for Hill model-registry activity (AL-1a step 4).

The Hill refit (``.github/workflows/refit-hill-curves.yml``) runs on a CI runner
with no persistent ``data/learning/``, and CI must never commit receipts. What
it commits is the evidence, under ``config/model_registry/``:

* ``hill_scope_masters.json`` -- every challenger, verdict and promotion;
* ``training_runs/<challengerHash>.json`` -- the full pinned run record;
* ``hill_autopilot_runs.jsonl`` -- one Autopilot adjudication per refit.

That evidence reaches the box by deploy, and ``deploy/deploy.sh`` runs this
script after the code lands. It READS the committed files (never writes them)
and appends receipts to the box-local store ``data/learning/receipts.sqlite``
through the AL-0 Hill adapters (``src/model_registry/learning_adapters.py``, via
``src/model_registry/producer_receipts.py`` section 4):

* MODEL (+ CHALLENGER for a challenger / rejected entry) per registry entry,
  carrying its status, notes and promotion lifecycle facts as data;
* MODEL + FEATURES per training run (the integrity-checked artifact, else the
  registry summary when the artifact was pruned);
* OBSERVATION per Autopilot adjudication, carrying the outcome verbatim --
  e.g. ``AUTO_PROMOTION_BLOCKED`` / ``no_independent_validation_target``.

No Hill holdout EVALUATION is emitted: it is scored on the fit's own snapshot,
so it is retrospective, and the receipt contract has no retrospective marker.

Idempotent: every receipt's identity is the producer's id plus a content
revision (sha256 of the canonical JSON it is derived from), so a re-run over the
same artifacts stores only duplicates -- never a new row, never a conflict.

Never promotes: it calls no ``promote`` / ``apply``, takes no ``--override-scope``,
and writes nothing under ``config/`` or ``src/``.

Writes only when ``RISKIT_RECEIPTS_ENABLED=1`` (fail closed, as the source-quality
evaluator): the box's deploy sets it, any other invocation builds and reports.

Exit codes:
  0  receipts built (and, when enabled, stored: written / duplicates only)
  1  partial: some item was refused, or the store reported a conflict / rejection
     or could not be written -- everything else was still recorded
  2  refused: the registry or run log is missing or corrupt; nothing was written
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.model_registry import producer_receipts as pr  # noqa: E402
from src.model_registry.feature_dictionary import load_dictionary  # noqa: E402
from src.model_registry.learning_receipt import LearningReceipt, ReceiptError  # noqa: E402
from src.model_registry.training_run import (  # noqa: E402
    TRAINING_RUNS_DIRNAME,
    TrainingRunError,
    load_training_run,
)
from src.model_registry.versioning import DEFAULT_REGISTRY_DIR  # noqa: E402

EXIT_OK = 0
EXIT_PARTIAL = 1
EXIT_REFUSED = 2

REGISTRY_FILE = "hill_scope_masters.json"
RUN_LOG_FILE = "hill_autopilot_runs.jsonl"


class InputRefused(RuntimeError):
    """A committed artifact is missing or corrupt: fail closed, write nothing."""


def load_registry(registry_dir: Path) -> dict[str, Any]:
    path = registry_dir / REGISTRY_FILE
    if not path.is_file():
        raise InputRefused(f"{path}: Hill registry is missing")
    try:
        blob = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InputRefused(f"{path}: Hill registry is unreadable: {exc}") from exc
    if not isinstance(blob, dict) or not isinstance(blob.get("versions"), list):
        raise InputRefused(f"{path}: Hill registry has no 'versions' list")
    if "championVersion" not in blob:
        raise InputRefused(f"{path}: Hill registry carries no 'championVersion'")
    champion = blob["championVersion"]
    if champion is not None and (not isinstance(champion, int) or isinstance(champion, bool)):
        raise InputRefused(f"{path}: championVersion {champion!r} is not a version number")
    seen: set[int] = set()
    for i, v in enumerate(blob["versions"]):
        n = v.get("version") if isinstance(v, dict) else None
        if not isinstance(n, int) or isinstance(n, bool):
            raise InputRefused(f"{path}: versions[{i}] is not an entry with an integer version")
        if n in seen:
            raise InputRefused(f"{path}: version {n} appears twice")
        seen.add(n)
    if champion is not None and champion not in seen:
        raise InputRefused(f"{path}: championVersion {champion} is not a registry entry")
    return blob


def load_run_log(registry_dir: Path) -> list[dict[str, Any]]:
    path = registry_dir / RUN_LOG_FILE
    if not path.is_file():
        raise InputRefused(f"{path}: Hill Autopilot run log is missing")
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise InputRefused(f"{path}: Hill Autopilot run log is unreadable: {exc}") from exc
    lines: list[dict[str, Any]] = []
    for no, raw in enumerate(text.splitlines(), start=1):
        if not raw.strip():
            continue
        try:
            line = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise InputRefused(f"{path}:{no}: corrupt run-log line: {exc}") from exc
        if not isinstance(line, dict):
            raise InputRefused(f"{path}:{no}: run-log line is not a JSON object")
        lines.append(line)
    return lines


def training_run_records(
    registry: dict[str, Any], registry_dir: Path
) -> tuple[list[tuple[str, dict[str, Any]]], list[dict[str, str]]]:
    """``[(label, record)]`` for every training run, plus per-item refusals.

    A referenced artifact is loaded through ``training_run.load_training_run``,
    which refuses one that does not hash to its summary (an edited artifact is
    never laundered into evidence). A pruned artifact falls back to the summary
    the registry kept (``recordForm: summary``). An unreferenced artifact still on
    disk is adapted directly; the adapter verifies its own ``pinsHash``."""
    records: list[tuple[str, dict[str, Any]]] = []
    refused: list[dict[str, str]] = []
    referenced: set[str] = set()
    for v in registry["versions"]:
        summary = v.get("trainingRun")
        if not summary:
            continue
        label = f"v{v['version']} trainingRun"
        if not isinstance(summary, dict):
            refused.append({"item": label, "reason": "trainingRun is not an object"})
            continue
        rel = summary.get("artifact")
        if rel:
            referenced.add(str(rel))
        try:
            if rel and not (registry_dir / str(rel)).is_file():
                records.append((f"{label} (artifact {rel} pruned; summary)", dict(summary)))
            else:
                records.append((label, load_training_run(summary, registry_dir=registry_dir)))
        except (TrainingRunError, OSError, ValueError) as exc:
            refused.append({"item": label, "reason": f"{type(exc).__name__}: {exc}"})
    for path in sorted((registry_dir / TRAINING_RUNS_DIRNAME).glob("*.json")):
        rel = f"{TRAINING_RUNS_DIRNAME}/{path.name}"
        if rel in referenced:
            continue
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            refused.append({"item": rel, "reason": f"unreadable artifact: {exc}"})
            continue
        if not isinstance(record, dict):
            refused.append({"item": rel, "reason": "artifact is not a JSON object"})
            continue
        records.append((f"{rel} (unreferenced)", record))
    return records, refused


def build_receipts(
    registry_dir: Path,
) -> tuple[list[LearningReceipt], list[dict[str, str]], dict[str, Any]]:
    """Every receipt for the committed Hill evidence. Raises :class:`InputRefused`."""
    registry = load_registry(registry_dir)
    run_log = load_run_log(registry_dir)
    champion = registry["championVersion"]
    versions = {v["version"]: v for v in registry["versions"]}
    receipts: list[LearningReceipt] = []
    refused: list[dict[str, str]] = []

    for n in sorted(versions):
        try:
            receipts += pr.hill_registry_version_receipts(versions[n], champion_version=champion)
        except (ReceiptError, ValueError, TypeError, KeyError) as exc:
            refused.append({"item": f"registry v{n}", "reason": f"{type(exc).__name__}: {exc}"})

    records, run_refusals = training_run_records(registry, registry_dir)
    refused += run_refusals
    dictionary = load_dictionary()
    for label, record in records:
        try:
            receipts += pr.hill_training_run_receipts(record, dictionary=dictionary)
        except (ReceiptError, ValueError, TypeError, KeyError) as exc:
            refused.append({"item": label, "reason": f"{type(exc).__name__}: {exc}"})

    for i, line in enumerate(run_log, start=1):
        try:
            receipts.append(pr.hill_autopilot_run_receipt(line, versions_by_number=versions))
        except (ReceiptError, ValueError, TypeError, KeyError) as exc:
            refused.append(
                {"item": f"{RUN_LOG_FILE}:{i}", "reason": f"{type(exc).__name__}: {exc}"}
            )

    # One receipt per identity. Two raw refits on unchanged data share one
    # training run, so they yield the same receipt: keep one. The same identity
    # with DIFFERENT content cannot arise from content-revisioned ids; if it does,
    # it is refused here rather than handed to the store as a conflict.
    unique: dict[str, LearningReceipt] = {}
    for r in receipts:
        prior = unique.get(r.receipt_id)
        if prior is None:
            unique[r.receipt_id] = r
        elif prior.content_hash() != r.content_hash():
            refused.append(
                {"item": r.receipt_id, "reason": "one identity derived with two contents"}
            )
    out = list(unique.values())
    stats = {
        "registryVersions": len(versions),
        "trainingRuns": len(records),
        "autopilotRuns": len(run_log),
        "evaluationsWithheld": len(versions),
        "evaluationsWithheldReason": pr.HILL_EVALUATION_WITHHELD,
        "byKind": dict(sorted(Counter(r.kind for r in out).items())),
    }
    return out, refused, stats


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument(
        "--registry-dir",
        type=Path,
        default=DEFAULT_REGISTRY_DIR,
        help="committed Hill registry directory (default config/model_registry)",
    )
    ap.add_argument(
        "--store",
        type=Path,
        default=None,
        help="learning-receipt store (default data/learning/receipts.sqlite)",
    )
    ap.add_argument("--dry-run", action="store_true", help="build and validate; write nothing")
    args = ap.parse_args(argv)

    try:
        receipts, refused, stats = build_receipts(args.registry_dir)
    except InputRefused as exc:
        print(f"ERROR: hill learning receipts refused: {exc}; nothing written", file=sys.stderr)
        return EXIT_REFUSED

    summary: dict[str, Any] = {**stats, "receipts": len(receipts), "refused": refused}
    for item in refused:
        print(f"WARNING: refused {item['item']}: {item['reason']}", file=sys.stderr)

    if args.dry_run or not pr.receipts_enabled():
        summary["written"] = None
        summary["notWrittenBecause"] = (
            "--dry-run"
            if args.dry_run
            else f"{pr.RECEIPTS_ENABLED_ENV} is not 1 (only the box's deploy writes receipts)"
        )
        print(json.dumps(summary, sort_keys=True))
        return EXIT_PARTIAL if refused else EXIT_OK

    from src.model_registry.receipt_store import append_receipts  # noqa: PLC0415

    try:
        result = append_receipts(receipts, path=args.store)
    except (ReceiptError, OSError, sqlite3.Error) as exc:
        print(
            f"WARNING: hill learning receipts NOT written: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return EXIT_PARTIAL
    summary.update(
        written=result["written"],
        duplicates=result["duplicates"],
        contentConflicts=result["contentConflicts"],
        rejected=result["rejected"],
    )
    print(json.dumps(summary, sort_keys=True))
    if refused or result["contentConflicts"] or result["rejected"]:
        print(
            "WARNING: hill learning receipts recorded with refusals / conflicts / rejections",
            file=sys.stderr,
        )
        return EXIT_PARTIAL
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
