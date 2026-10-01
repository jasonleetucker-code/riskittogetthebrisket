"""Pinned, reproducible, point-in-time Hill training runs (owner Section D items 2 and 6).

Before this module a refit pinned only the board snapshot and its sha256 (H9 of
``docs/valuation/HILL_SOURCE_ALIGNMENT_AUDIT_2026-09-24.md``). Nothing recorded the
code identity, the source dataset states, their freshness/health/coverage AS OF the
fit, the provider families, the training populations, a training cutoff, or a
hash that could prove a second refit on the same evidence produced the same
challenger.

What a run records (``TrainingRun.record`` — stored on the registry challenger as
``trainingRun`` and written as the run artifact):

* code: ``codeSha`` (label) and ``codeHash`` over the files that implement the fit,
  plus a digest of the canonical percentile coordinate (the fit-relevant behaviour
  of ``player_valuation`` without its live constants, which change on promotion);
* the manifest hash and substrate version (``training_manifest``);
* every input file (trainers AND holdouts): full sha256, bytes, rows read, pick
  rows dropped, players kept, source key, provider family, live role, signal,
  spacing evidence, population, universe, game type;
* each source's dataset state (``data/scrape_state/<key>_dataset.json``): its
  sha256, data-as-of clock, freshness and freshness state assessed AT THE
  CUTOFF — never today's freshness on yesterday's snapshot — health and
  coverage;
* the board snapshot: path, sha256, scrape timestamp;
* per scope: trainers, holdouts, exclusions with reasons, training and holdout
  families, measured dependences, fit skips;
* the fit configuration, per-source fits, scope masters;
* ``modelHash`` (the emitted params), ``pinsHash`` (everything above that is
  evidence, minus labels and wall-clock), ``challengerHash`` (both).

Point in time: a run REFUSES any input observed after its training cutoff — a
snapshot scraped later, or a dataset state whose data clock is later. A replay
(``replay``) materializes every input from the newest commit at or before the
cutoff, so it cannot read later data at all; two replays from the same pins give
the same ``challengerHash`` (pinned by ``tests/model_registry/test_training_run.py``
and demonstrated in ``docs/valuation/evidence/hill-trainer-repair-2026-10-01/``).

This module never writes ``player_valuation.py`` and never promotes. It produces
evidence; the registry records it; Hill Autopilot decides.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

from src.canonical.player_valuation import PERCENTILE_REFERENCE_N, training_percentiles
from src.canonical.tail_policy import clamp_percentile
from src.model_registry.training_manifest import (
    FIT_TOP_N,
    LOADER_CSV,
    LOADER_CSV_CONCAT,
    ROLE_EXCLUDED,
    SCOPES,
    SUBSTRATE_VERSION,
    TrainingManifest,
    default_manifest,
    load_board_values,
    source_key_for_path,
)

REPO = Path(__file__).resolve().parents[2]
FITTER_PATH = REPO / "scripts" / "fit_hill_curve_percentile.py"
FRESHNESS_CONFIG_REL = "config/sources/freshness_v1.json"
STATE_DIR_REL = "data/scrape_state"
SNAPSHOT_DIR_REL = "exports/latest"

#: The files whose bytes ARE the fit. A change to any of them changes ``codeHash``.
CODE_FILES: tuple[str, ...] = (
    "scripts/fit_hill_curve_percentile.py",
    "src/model_registry/training_manifest.py",
    "src/model_registry/training_run.py",
    "src/canonical/tail_policy.py",
    "src/identity/picks.py",
)

#: Every key a ``trainingRun`` record must carry (owner Section D item 2).
REQUIRED_PIN_FIELDS: tuple[str, ...] = (
    "substrateVersion",
    "manifestHash",
    "codeSha",
    "codeHash",
    "trainingCutoff",
    "inputsOrigin",
    "inputsCommit",
    "reproducible",
    "snapshot",
    "freshnessConfig",
    "inputs",
    "scopes",
    "gameFormat",
    "config",
    "perSourceFits",
    "masters",
    "modelHash",
    "pinsHash",
    "challengerHash",
)

#: Labels and provenance pointers: recorded, but not evidence, so not hashed.
_UNHASHED_FIELDS = frozenset(
    {
        "codeSha",
        "inputsOrigin",
        "inputsCommit",
        "reproducible",
        "modelHash",
        "pinsHash",
        "challengerHash",
        "recordedAt",
    }
)


class TrainingRunError(RuntimeError):
    """A run that would not be point-in-time or reproducible if it proceeded."""


@dataclass(frozen=True)
class TrainingRun:
    params: dict[str, float]
    record: dict[str, Any]

    @property
    def challenger_hash(self) -> str:
        return str(self.record["challengerHash"])


# ── hashing ──────────────────────────────────────────────────────────────────


def _canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _sha256_text_normalized(path: Path) -> str:
    """Hash a SOURCE file with line endings normalized.

    A Windows checkout may hold CRLF where CI holds LF; that is the same code."""
    return _sha256_bytes(path.read_bytes().replace(b"\r\n", b"\n"))


def code_identity() -> dict[str, Any]:
    files = {rel: _sha256_text_normalized(REPO / rel) for rel in CODE_FILES}
    coordinate = [
        round(clamp_percentile(p, reference_n=PERCENTILE_REFERENCE_N), 12)
        for p in training_percentiles(1200)
    ]
    digest = _sha256_bytes(_canonical_json(coordinate).encode("utf-8"))
    return {
        "files": files,
        "percentileReferenceN": PERCENTILE_REFERENCE_N,
        "percentileCoordinateDigest": digest,
        "codeHash": _sha256_bytes(
            _canonical_json({"files": files, "coordinate": digest}).encode("utf-8")
        ),
    }


# ── the fitter, imported by path (it is a script) ───────────────────────────

_FITTER = None


def _fitter():
    global _FITTER
    if _FITTER is None:
        spec = importlib.util.spec_from_file_location("hill_fitter_for_training_run", FITTER_PATH)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _FITTER = module
    return _FITTER


# ── point-in-time guards ─────────────────────────────────────────────────────


def _parse_ts(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _require_aware(cutoff: datetime) -> datetime:
    if cutoff.tzinfo is None:
        raise TrainingRunError("training cutoff must be timezone-aware")
    return cutoff.astimezone(timezone.utc)


def _snapshot_pin(root: Path, snapshot: Path | None, cutoff: datetime) -> tuple[dict, bool]:
    if snapshot is None:
        return {"resolved": False}, True
    if not snapshot.is_file():
        raise TrainingRunError(f"board snapshot does not exist: {snapshot}")
    raw = json.loads(snapshot.read_text(encoding="utf-8"))
    scraped = _parse_ts(raw.get("scrapeTimestamp"))
    if scraped is None:
        raise TrainingRunError(
            f"board snapshot {snapshot.name} carries no scrapeTimestamp; a snapshot whose "
            "time cannot be proven cannot be proven to precede the training cutoff"
        )
    if scraped > cutoff:
        raise TrainingRunError(
            f"board snapshot {snapshot.name} was scraped {scraped.isoformat()}, after the "
            f"training cutoff {cutoff.isoformat()}"
        )
    try:
        rel = snapshot.resolve().relative_to(root.resolve()).as_posix()
        inside = True
    except ValueError:
        rel, inside = str(snapshot), False
    return (
        {
            "resolved": True,
            "path": rel,
            "sha256": _sha256_file(snapshot),
            "bytes": snapshot.stat().st_size,
            "scrapeTimestamp": raw.get("scrapeTimestamp"),
        },
        inside,
    )


def _freshness_config(root: Path) -> tuple[Path, dict[str, str]]:
    local = root / FRESHNESS_CONFIG_REL
    path = local if local.is_file() else REPO / FRESHNESS_CONFIG_REL
    return path, {
        "path": FRESHNESS_CONFIG_REL,
        "origin": "inputs" if path == local else "repo",
        "sha256": _sha256_text_normalized(path),
    }


def _dataset_state_pin(
    root: Path, source_key: str, cutoff: datetime, cfg_path: Path
) -> dict[str, Any]:
    from src.sources.dataset_state import load_state  # noqa: PLC0415
    from src.sources.freshness import assess_source, load_config  # noqa: PLC0415

    path = root / STATE_DIR_REL / f"{source_key}_dataset.json"
    if not path.is_file():
        return {"measured": False, "reason": "no dataset state file"}
    state = load_state(path) or {}
    for subset, sub in (state.get("subsets") or {}).items():
        for clock in ("lastAnyMeaningfulChangeAt", "lastBroadDatasetChangeAt"):
            at = _parse_ts((sub or {}).get(clock))
            if at is not None and at > cutoff:
                raise TrainingRunError(
                    f"{source_key} dataset state {subset}.{clock} = {at.isoformat()} is after "
                    f"the training cutoff {cutoff.isoformat()}"
                )
    weighting = assess_source(source_key, state, as_of=cutoff, cfg=load_config(cfg_path))
    players = weighting.subsets.get("players")
    sub = players.to_dict() if players is not None else {}
    return {
        "measured": weighting.measured,
        "stateSha256": _sha256_file(path),
        "health": weighting.health_state,
        "healthFactor": weighting.health_factor,
        "coverage": None if weighting.coverage is None else round(weighting.coverage, 4),
        "coverageFactor": round(weighting.coverage_factor, 4),
        "rowCount": weighting.row_count,
        "playersFingerprint": ((state.get("subsets") or {}).get("players") or {}).get(
            "fingerprint"
        ),
        "dataAsOf": sub.get("sourceDataAsOf"),
        "lastAnyMeaningfulChangeAt": sub.get("lastAnyMeaningfulChangeAt"),
        "lastBroadDatasetChangeAt": sub.get("lastBroadDatasetChangeAt"),
        "ageHours": sub.get("ageHours"),
        "freshness": sub.get("freshness"),
        "freshnessState": sub.get("state"),
    }


# ── the run ──────────────────────────────────────────────────────────────────


def _input_pins(
    m: TrainingManifest, root: Path, cutoff: datetime, cfg_path: Path
) -> dict[str, dict[str, Any]]:
    uses: dict[str, list[str]] = {}
    for b in m.boards:
        if b.role == ROLE_EXCLUDED:
            continue
        for rel in b.paths:
            uses.setdefault(rel, []).append(f"{b.scope}:{b.label}:{b.role}")
    pins: dict[str, dict[str, Any]] = {}
    for rel, board in m.input_paths().items():
        path = root / rel
        key = source_key_for_path(rel) or board.source_key
        base = {
            "sourceKey": key,
            "usedBy": sorted(uses.get(rel, [])),
            "family": board.family,
            "liveRole": board.live_role,
            "csvSignal": board.csv_signal,
            "spacingEvidence": board.spacing_evidence,
            "population": board.population,
            "universe": board.universe,
            "gameType": board.game_type,
            "valueColumn": board.value_column,
        }
        if not path.is_file():
            pins[rel] = {
                **base,
                "sha256": "missing",
                "rowsRead": 0,
                "picksDropped": 0,
                "datasetState": {"measured": False, "reason": "input missing"},
            }
            continue
        values = load_board_values(path, str(board.value_column))
        trained = (
            min(len(values.values), FIT_TOP_N)
            if board.loader in (LOADER_CSV, LOADER_CSV_CONCAT)
            else len(values.values)
        )
        pins[rel] = {
            **base,
            "sha256": _sha256_file(path),
            "bytes": path.stat().st_size,
            **values.to_pin(),
            "windowRows": trained,
            "datasetState": _dataset_state_pin(root, key, cutoff, cfg_path),
        }
    return pins


def _scope_pins(m: TrainingManifest, fit: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for scope in SCOPES:
        out[scope] = {
            "trainers": [b.label for b in m.trainers(scope)],
            "holdouts": [b.label for b in m.holdouts(scope)],
            "excluded": {b.label: b.exclusion_reason for b in m.excluded(scope)},
            "trainingFamilies": sorted(m.training_families(scope)),
            "holdoutFamilies": sorted(m.holdout_families(scope)),
            "measuredDependence": {
                b.label: sorted(d.trainer_family for d in b.measured_dependence)
                for b in m.holdouts(scope)
                if b.measured_dependence
            },
            "fitSkipped": dict(sorted((fit.get("skipped") or {}).get(scope, {}).items())),
        }
    return out


def execute(
    *,
    root: Path,
    cutoff: datetime,
    code_sha: str | None = None,
    snapshot: Path | None = None,
    manifest: TrainingManifest | None = None,
    inputs_origin: str = "worktree",
    inputs_commit: str | None = None,
    reproducible: bool = True,
    log: Callable[[str], None] | None = None,
) -> TrainingRun:
    """Fit every scope from the files under ``root`` as of ``cutoff``, fully pinned."""
    cut = _require_aware(cutoff)
    m = manifest or default_manifest()
    fitter = _fitter()
    snap = snapshot if snapshot is not None else fitter._latest_snapshot(root)
    snapshot_pin, snapshot_inside = _snapshot_pin(root, snap, cut)
    cfg_path, cfg_pin = _freshness_config(root)
    inputs = _input_pins(m, root, cut, cfg_path)

    try:
        fit = fitter.fit_scopes(root=root, snapshot=snap, manifest=m, log=log)
    except FileNotFoundError as exc:
        raise TrainingRunError(str(exc)) from exc
    params = {str(k): float(v) for k, v in fit["constants"].items()}

    code = code_identity()
    game_types = {pin["gameType"] for pin in inputs.values()}
    record: dict[str, Any] = {
        "substrateVersion": SUBSTRATE_VERSION,
        "manifestHash": m.manifest_hash(),
        "codeSha": code_sha or "unknown",
        "codeHash": code["codeHash"],
        "code": code,
        "trainingCutoff": cut.isoformat(),
        "inputsOrigin": inputs_origin,
        "inputsCommit": inputs_commit,
        "reproducible": bool(reproducible and snapshot_inside),
        "snapshot": snapshot_pin,
        "freshnessConfig": cfg_pin,
        "inputs": inputs,
        "scopes": _scope_pins(m, fit),
        "gameFormat": {
            "gameType": game_types.pop() if len(game_types) == 1 else "MIXED_OR_UNKNOWN",
            "population": "players_only",
            "note": "TE basis lift and league scoring are serve-time steps, not training inputs",
        },
        "config": {
            "fitTopN": FIT_TOP_N,
            "minCombinedRows": fitter.MIN_COMBINED_ROWS,
            "minRookieRows": fitter.MIN_ROOKIE_ROWS,
            "percentileReferenceN": PERCENTILE_REFERENCE_N,
            "cGrid": "0.005 + 0.005*i, i in [0, 100)",
            "sGrid": "0.4 + 0.02*i, i in [0, 106)",
            "refine": "dc in +-{0.001, 0.002}, ds in +-{0.005, 0.01}",
            "masterCombine": "unweighted mean of per-source curves (authority weighting H4: not applied)",
            "constantRounding": {"c": 4, "s": 3},
            "policy": m.policy.to_dict(),
        },
        "perSourceFits": {
            scope: [
                {
                    "label": f["label"],
                    "c": round(f["c"], 6),
                    "s": round(f["s"], 6),
                    "rmse": round(f["rmse"], 3),
                    "n": f["n"],
                }
                for f in fits
            ]
            for scope, fits in fit["perSource"].items()
        },
        "masters": {
            scope: {k: round(v, 6 if k != "rmse" else 3) for k, v in master.items()}
            for scope, master in fit["masters"].items()
        },
    }
    model_hash = _sha256_bytes(_canonical_json(params).encode("utf-8"))
    evidence = {k: v for k, v in record.items() if k not in _UNHASHED_FIELDS}
    pins_hash = _sha256_bytes(_canonical_json(evidence).encode("utf-8"))
    record["modelHash"] = model_hash
    record["pinsHash"] = pins_hash
    record["challengerHash"] = _sha256_bytes(f"{pins_hash}:{model_hash}".encode("utf-8"))
    return TrainingRun(params=params, record=record)


# ── git: point-in-time materialization ──────────────────────────────────────


def _git(*args: str, repo: Path = REPO, binary: bool = False):
    proc = subprocess.run(["git", *args], cwd=str(repo), capture_output=True, check=False)
    if proc.returncode != 0:
        raise TrainingRunError(
            f"git {' '.join(args)} failed: {proc.stderr.decode('utf-8', 'replace').strip()}"
        )
    return proc.stdout if binary else proc.stdout.decode("utf-8").strip()


def commit_time(sha: str, *, repo: Path = REPO) -> datetime:
    when = _parse_ts(_git("show", "-s", "--format=%cI", sha, repo=repo))
    if when is None:
        raise TrainingRunError(f"cannot read the commit time of {sha}")
    return when.astimezone(timezone.utc)


def commit_at_or_before(
    cutoff: datetime, *, repo: Path = REPO, ref: str = "HEAD"
) -> tuple[str, datetime]:
    """The newest commit on ``ref`` whose committer time is at or before ``cutoff``."""
    cut = _require_aware(cutoff)
    sha = _git("rev-list", "-1", f"--before={cut.isoformat()}", ref, repo=repo)
    if not sha:
        raise TrainingRunError(f"no commit on {ref} at or before {cut.isoformat()}")
    when = commit_time(sha, repo=repo)
    if when > cut:  # defence in depth: rev-list --before is a committer-date filter
        raise TrainingRunError(f"{sha} is after the cutoff")
    return sha, when


def materialize_inputs(
    commit: str, dest: Path, *, paths: Iterable[str], repo: Path = REPO
) -> dict[str, bool]:
    """Write each path's bytes AT ``commit`` under ``dest``. Absent paths are reported."""
    present: dict[str, bool] = {}
    for rel in sorted(set(paths)):
        try:
            data = _git("show", f"{commit}:{rel}", repo=repo, binary=True)
        except TrainingRunError:
            present[rel] = False
            continue
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        present[rel] = True
    return present


def _snapshot_at(commit: str, *, repo: Path = REPO) -> str | None:
    listing = _git("ls-tree", "--name-only", commit, f"{SNAPSHOT_DIR_REL}/", repo=repo)
    names = sorted(
        n
        for n in listing.splitlines()
        if Path(n).name.startswith("dynasty_data_") and n.endswith(".json")
    )
    return names[-1] if names else None


def replay(
    *,
    commit: str | None = None,
    cutoff: datetime | None = None,
    repo: Path = REPO,
    manifest: TrainingManifest | None = None,
    workdir: Path | None = None,
    snapshot_rel: str | None = None,
) -> TrainingRun:
    """Refit from git: every input as it stood at ``commit`` (or the newest commit at
    or before ``cutoff``). The run cannot read later data — it is not on disk."""
    if commit is None and cutoff is None:
        raise TrainingRunError("replay needs a commit or a cutoff")
    if commit is None:
        commit, _when = commit_at_or_before(cutoff, repo=repo)  # type: ignore[arg-type]
    sha = _git("rev-parse", commit, repo=repo)
    at = commit_time(sha, repo=repo)
    cut = _require_aware(cutoff) if cutoff is not None else at
    if at > cut:
        raise TrainingRunError(f"commit {sha[:12]} ({at.isoformat()}) is after the cutoff")
    m = manifest or default_manifest()
    # A verification replays the snapshot its record names; a fresh replay takes
    # the newest snapshot (by the date in its name) present at the commit.
    snap_rel = snapshot_rel or _snapshot_at(sha, repo=repo)
    keys = {source_key_for_path(rel) for rel in m.input_paths()} | {b.source_key for b in m.boards}
    paths = [
        *m.input_paths(),
        FRESHNESS_CONFIG_REL,
        *(f"{STATE_DIR_REL}/{k}_dataset.json" for k in sorted(k for k in keys if k)),
        *([snap_rel] if snap_rel else []),
    ]
    with tempfile.TemporaryDirectory(prefix="hill-replay-", dir=workdir) as td:
        root = Path(td)
        materialize_inputs(sha, root, paths=paths, repo=repo)
        return execute(
            root=root,
            cutoff=cut,
            code_sha=_git("rev-parse", "--short", "HEAD", repo=repo),
            snapshot=(root / snap_rel) if snap_rel else None,
            manifest=m,
            inputs_origin=f"git:{sha}",
            inputs_commit=sha,
            reproducible=True,
        )


def worktree_inputs_state(
    manifest: TrainingManifest | None = None, *, repo: Path = REPO, snapshot: Path | None = None
) -> tuple[str, bool, datetime]:
    """``(head_sha, inputs_clean, head_commit_time)`` for a working-tree refit.

    Clean means every manifest input, every dataset-state file and the snapshot
    match HEAD exactly — then the run is reproducible from ``git:HEAD`` and its
    cutoff is HEAD's commit time."""
    m = manifest or default_manifest()
    head = _git("rev-parse", "HEAD", repo=repo)
    paths = [*m.input_paths(), STATE_DIR_REL, FRESHNESS_CONFIG_REL]
    if snapshot is not None:
        try:
            paths.append(snapshot.resolve().relative_to(repo.resolve()).as_posix())
        except ValueError:
            return head, False, commit_time(head, repo=repo)
        tracked = subprocess.run(
            ["git", "ls-files", "--error-unmatch", paths[-1]],
            cwd=str(repo),
            capture_output=True,
            check=False,
        )
        if tracked.returncode != 0:
            return head, False, commit_time(head, repo=repo)
    dirty = _git("status", "--porcelain", "--", *paths, repo=repo)
    return head, not dirty, commit_time(head, repo=repo)


# ── registry / Autopilot ────────────────────────────────────────────────────


def is_tournament_eligible(version: Any) -> bool:
    """Only a reproducible challenger fitted on the CURRENT substrate may compete.

    A challenger with no pins (every pre-repair version), one fitted on the
    pre-repair substrate (KTC pick rows in the OFFENSE fit), or one recorded as
    not reproducible cannot be re-derived from its own record, so it cannot be
    promoted on the strength of it."""
    run = getattr(version, "training_run", None) or {}
    return (
        run.get("substrateVersion") == SUBSTRATE_VERSION
        and run.get("reproducible") is True
        and bool(run.get("challengerHash"))
    )
