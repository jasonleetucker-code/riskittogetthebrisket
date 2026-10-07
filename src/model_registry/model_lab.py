"""Model Lab — one read-only, private view over the EXISTING model owners (AL-0b / IC-5).

What this is
────────────
``docs/research/ADAPTIVE_LEARNING_2026-09-26.md`` §33 asks for a backend contract that
answers, per model family: MODEL (champion version), CHALLENGERS, DATA (training /
evaluation window), SAMPLE SIZE, LAST EVALUATED, METRICS, CALIBRATION, DRIFT,
PROMOTION STATUS, ROLLBACK VERSION and DATA QUALITY / COVERAGE.  This module assembles
that answer from the stores that already own each fact.  It is a VIEW:

* **no second registry** — Hill versions, champion pointer and rollback targets come
  from ``config/model_registry/hill_scope_masters.json`` (``versioning.ModelRegistry``'s
  document); Hill Autopilot verdicts from ``hill_autopilot_runs.jsonl``;
* **no second receipt store** — receipt counts come from
  ``receipt_store.iter_receipts`` over ``data/learning/receipts.sqlite`` (read-only,
  ``mode=ro``);
* **no second gate** — every gate result is the verdict the owning evaluator
  RECORDED (the Autopilot run line, the shadow evaluation file, the
  source-quality results, the Consensus Edge validation report), never a verdict
  re-derived here against today's code;
* **writes nothing** — no file, no flag, no champion pointer, no receipt
  (``tests/model_registry/test_model_lab.py`` proves the tree is byte-identical
  after a build and that the module names no write call).

Missing is never zero.  Every field is either an observed value or an explicit
``{"state": "unobserved" | "not_applicable" | "unmeasured", "reason": ...}`` block (the
AL-0 slot vocabulary of ``learning_receipt.Unobserved`` / ``NotApplicable``, plus
``unmeasured`` for drift, where no drift monitor exists: "unmeasured" is not "no drift").

Challenger lab states are a fixed vocabulary (:data:`LAB_STATES`):

* ``CHAMPION`` — the version the family's own pointer names as authoritative;
* ``SHADOW`` — running beside the champion on live inputs without being served;
* ``HELD`` — evaluated, promotion withheld by a gate (reason carried);
* ``REJECTED`` — lost; retained as evidence, never dropped (plan §30);
* ``INSUFFICIENT_EVIDENCE`` — cannot be judged from its own record yet;
* ``RETIRED`` — a former champion.

Each challenger also carries its family's NATIVE status verbatim (``nativeStatus``),
so the mapping is auditable rather than a relabelling.

Private: served only at ``GET /api/model-lab`` behind the session gate
(``model_lab_api``).  Development metrics are not for ordinary league users (§33).
"""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from src.model_registry.learning_receipt import NotApplicable, Unobserved

REPO = Path(__file__).resolve().parents[2]

#: Bump on any change to the payload's shape.
MODEL_LAB_SCHEMA = "model-lab/v1"

LAB_CHAMPION = "CHAMPION"
LAB_SHADOW = "SHADOW"
LAB_HELD = "HELD"
LAB_REJECTED = "REJECTED"
LAB_INSUFFICIENT = "INSUFFICIENT_EVIDENCE"
LAB_RETIRED = "RETIRED"
LAB_STATES: tuple[str, ...] = (
    LAB_CHAMPION,
    LAB_SHADOW,
    LAB_HELD,
    LAB_REJECTED,
    LAB_INSUFFICIENT,
    LAB_RETIRED,
)

#: Every family block carries exactly these keys (§33's eleven questions, plus
#: identity and provenance).  A value is observed data or an explicit state block.
FAMILY_FIELDS: tuple[str, ...] = (
    "family",
    "name",
    "domain",
    "owners",
    "artifacts",
    "champion",
    "challengers",
    "challengerStates",
    "drift",
    "calibration",
    "lastEvaluation",
    "gate",
    "promotionAuthority",
    "productionState",
    "rollback",
    "decisionReason",
    "dataQuality",
    "receipts",
)

#: Every OBSERVED champion block carries exactly these keys.
CHAMPION_FIELDS: tuple[str, ...] = (
    "version",
    "createdAt",
    "trainedAt",
    "dataThrough",
    "featureDictionary",
    "trainingWindow",
    "validationWindows",
    "target",
    "targetLineage",
    "sampleSize",
    "metrics",
)

#: Every challenger row carries exactly these keys.
CHALLENGER_FIELDS: tuple[str, ...] = (
    "version",
    "state",
    "nativeStatus",
    "createdAt",
    "metrics",
    "reason",
)

NO_DRIFT_MONITOR = (
    "no drift monitor exists for this family (AL-0 defines DRIFT receipts, "
    "but no producer emits one); unmeasured is not 'no drift'"
)


# ── state blocks ─────────────────────────────────────────────────────────────


def unobserved(reason: str) -> dict[str, Any]:
    """The AL-0 ``Unobserved`` slot: the evidence exists in principle, not here."""
    return Unobserved(reason).to_dict()


def not_applicable(reason: str) -> dict[str, Any]:
    return NotApplicable(reason).to_dict()


def unmeasured(reason: str = NO_DRIFT_MONITOR) -> dict[str, Any]:
    return {"state": "unmeasured", "reason": reason}


def is_state_block(value: Any) -> bool:
    return (
        isinstance(value, Mapping)
        and value.get("state") in {"unobserved", "not_applicable", "unmeasured"}
        and bool(str(value.get("reason") or "").strip())
    )


def _value(container: Any, key: str, reason: str) -> Any:
    """``container[key]`` when present and not None, else an explicit unobserved block."""
    if isinstance(container, Mapping) and container.get(key) is not None:
        return container[key]
    return unobserved(reason)


def _instant(container: Any, key: str, reason: str) -> Any:
    """A timestamp field only when it is a provable, timezone-aware instant.

    A sentinel such as ``"unknown"`` (the seeded Hill v1's ``fittedAt``) or
    ``UNKNOWN_HISTORICAL_APPLY_TIME`` is reported as unobserved WITH the raw value,
    never passed through as if it were a time."""
    raw = container.get(key) if isinstance(container, Mapping) else None
    if raw is None:
        return unobserved(reason)
    if _parse_instant(raw) is None:
        return unobserved(f"{reason}: recorded as {raw!r}, not a provable instant")
    return raw


# ── read-only file access ────────────────────────────────────────────────────


def _rel(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _artifact(root: Path, rel: str, role: str) -> dict[str, Any]:
    path = root / rel
    out: dict[str, Any] = {"path": rel, "role": role, "present": path.exists()}
    if path.is_file():
        out["modifiedAt"] = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()
    return out


def _read_json(path: Path) -> tuple[Any, str | None]:
    """``(document, None)`` or ``(None, reason)``.  Never raises, never writes."""
    if not path.is_file():
        return None, f"{path.name} is absent"
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except (OSError, ValueError) as exc:
        return None, f"{path.name} unreadable: {type(exc).__name__}: {exc}"


def _read_jsonl(path: Path) -> tuple[list[dict[str, Any]], str | None]:
    """Every parseable object line, plus a reason when the file is absent/unreadable.

    A malformed line is skipped AND counted (``_malformed`` on the result list's
    reason), never silently: the caller reports it as a data-quality fact."""
    if not path.is_file():
        return [], f"{path.name} is absent"
    rows: list[dict[str, Any]] = []
    bad = 0
    try:
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except ValueError:
                    bad += 1
                    continue
                if isinstance(obj, dict):
                    rows.append(obj)
                else:
                    bad += 1
    except OSError as exc:
        return [], f"{path.name} unreadable: {type(exc).__name__}: {exc}"
    return rows, (f"{bad} malformed line(s) skipped" if bad else None)


def _parse_instant(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo is not None else None


def _latest_by(rows: Sequence[Mapping[str, Any]], key: str) -> Mapping[str, Any] | None:
    """The row with the newest provable instant at ``key`` (file order breaks ties)."""
    best: tuple[datetime, int] | None = None
    best_row: Mapping[str, Any] | None = None
    for i, row in enumerate(rows):
        at = _parse_instant(row.get(key))
        if at is None:
            continue
        if best is None or (at, i) >= best:
            best, best_row = (at, i), row
    return best_row


# ── feature dictionary (consumed, never redefined) ───────────────────────────

_dictionary_lock = threading.Lock()
_dictionary_memo: dict[tuple[float, float], Any] = {}


def _dictionary() -> Any:
    """``feature_dictionary.load_dictionary()``, memoized on the two files' mtimes.

    Loading validates every definition owner by AST (~0.5 s); the dictionary
    changes only when its committed files do, so the mtimes are the cache key."""
    from src.model_registry.feature_dictionary import (
        DEFAULT_DICTIONARY_PATH,
        DEFAULT_LOCK_PATH,
        load_dictionary,
    )

    key = (DEFAULT_DICTIONARY_PATH.stat().st_mtime, DEFAULT_LOCK_PATH.stat().st_mtime)
    with _dictionary_lock:
        hit = _dictionary_memo.get(key)
    if hit is not None:
        return hit
    loaded = load_dictionary()
    with _dictionary_lock:
        _dictionary_memo.clear()
        _dictionary_memo[key] = loaded
    return loaded


def _feature_manifest(family: str, features: Sequence[Mapping[str, Any]] | None) -> Any:
    """The family's DECLARED feature manifest, validated against the dictionary owner.

    ``features`` is the producer's own manifest constant (``HILL_FEATURES`` etc.);
    ``validate_manifest`` returns the same ``featureManifestHash`` the producer's
    receipts pin, so the Lab names the identical definition set."""
    if not features:
        return not_applicable(
            "this family declares no feature manifest in the feature dictionary "
            "(config/model_registry/feature_dictionary.json)"
        )
    try:
        from src.model_registry.feature_dictionary import validate_manifest

        dictionary = _dictionary()
        manifest_hash = validate_manifest(dictionary, consumer=family, features=features)
    except Exception as exc:  # noqa: BLE001 — a broken dictionary is reported, not raised
        return unobserved(f"feature dictionary did not validate: {type(exc).__name__}: {exc}")
    return {
        "dictionaryVersion": dictionary.version,
        "featureManifestHash": manifest_hash,
        "features": [
            {"name": str(f["name"]), "version": int(f["version"])}
            for f in sorted(features, key=lambda f: (str(f["name"]), int(f["version"])))
        ],
    }


# ── AL-0 receipts (consumed through the store's own read API) ────────────────


def _receipt_index(store_path: Path | None) -> dict[str, Any]:
    """``family -> {kind: count}`` plus store state, via ``receipt_store.iter_receipts``.

    The store lives on the production box (``data/learning/``, gitignored); a
    checkout without it reports ``unobserved``, never "zero receipts"."""
    from src.model_registry import receipt_store

    path = store_path or receipt_store.DEFAULT_STORE_PATH
    if not Path(path).exists():
        return {
            "state": "unobserved",
            "reason": f"learning-receipt store {_rel(REPO, Path(path))} is absent on this host",
            "byFamily": {},
        }
    by_family: dict[str, dict[str, Any]] = {}
    try:
        for receipt in receipt_store.iter_receipts(Path(path), live_only=True):
            fam = str(receipt.get("modelFamily") or "")
            slot = by_family.setdefault(fam, {"byKind": {}, "latestCutoff": None, "total": 0})
            kind = str(receipt.get("kind") or "")
            slot["byKind"][kind] = slot["byKind"].get(kind, 0) + 1
            slot["total"] += 1
            cut = _parse_instant(receipt.get("cutoff"))
            prev = _parse_instant(slot["latestCutoff"])
            if cut is not None and (prev is None or cut > prev):
                slot["latestCutoff"] = cut.isoformat()
    except Exception as exc:  # noqa: BLE001
        return {
            "state": "unobserved",
            "reason": f"learning-receipt store unreadable: {type(exc).__name__}: {exc}",
            "byFamily": {},
        }
    return {"state": "observed", "byFamily": by_family}


def _family_receipts(index: Mapping[str, Any], family: str) -> dict[str, Any]:
    if index.get("state") != "observed":
        return unobserved(str(index.get("reason")))
    slot = (index.get("byFamily") or {}).get(family)
    if not slot:
        # The store IS readable and holds nothing for this family: a real zero.
        return {"state": "observed", "total": 0, "byKind": {}, "latestCutoff": None}
    return {"state": "observed", **slot}


def _challenger_states(rows: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    """Counts per lab state over an OBSERVED list (an absent state is a real 0 here)."""
    out = {s: 0 for s in LAB_STATES}
    for row in rows:
        out[str(row["state"])] += 1
    return out


def _challenger(
    *,
    version: Any,
    state: str,
    native_status: Any,
    created_at: Any,
    metrics: Any,
    reason: Any,
) -> dict[str, Any]:
    if state not in LAB_STATES:
        raise ValueError(f"unknown lab state {state!r}")
    return {
        "version": version,
        "state": state,
        "nativeStatus": native_status,
        "createdAt": created_at,
        "metrics": metrics,
        "reason": reason,
    }


def _family(**fields: Any) -> dict[str, Any]:
    missing = [k for k in FAMILY_FIELDS if k not in fields]
    extra = [k for k in fields if k not in FAMILY_FIELDS]
    if missing or extra:
        raise ValueError(f"family block fields wrong: missing={missing} extra={extra}")
    challengers = fields["challengers"]
    if isinstance(challengers, list):
        fields["challengerStates"] = _challenger_states(challengers)
    return {k: fields[k] for k in FAMILY_FIELDS}


def _flag_state(name: str) -> dict[str, Any]:
    """The flag as THIS process serves it.  The Model Lab is served by the same
    process that serves the board, so this is the production state, not a guess."""
    try:
        from src.api import feature_flags

        return {
            "flag": name,
            "enabled": bool(feature_flags.is_enabled(name)),
            "gateStatus": feature_flags.gate_status(name),
            "rollback": f"RISKIT_FEATURE_{name.upper()}=0 + restart",
        }
    except Exception as exc:  # noqa: BLE001
        return {"flag": name, **unobserved(f"flag unreadable: {type(exc).__name__}: {exc}")}


def _tail(path: Path) -> dict[str, Any] | None:
    """The final complete record of an append-only JSONL ledger, read from its tail
    by the ledger owner (``src.utils.append_ledger.last_record``)."""
    from src.utils.append_ledger import last_record

    return last_record(path)


def _count_lines(paths: Sequence[Path]) -> int:
    n = 0
    for path in paths:
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                n += chunk.count(b"\n")
    return n


def _sha256_file(path: Path) -> str | None:
    import hashlib

    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ═════════════════════════════════════════════════════════════════════════════
# Hill scope masters — config/model_registry/ (versioning + Hill Autopilot)
# ═════════════════════════════════════════════════════════════════════════════

HILL_FAMILY = "hill_scope_masters"
HILL_REGISTRY_REL = "config/model_registry/hill_scope_masters.json"
HILL_AUTOPILOT_RUNS_REL = "config/model_registry/hill_autopilot_runs.jsonl"
HILL_POLICY_REL = "config/model_registry/hill_autopilot_policy.json"
HILL_CONSTANTS_REL = "src/canonical/player_valuation.py"
NO_RUN = "no Hill Autopilot run recorded"


def _hill_metrics(holdout: Any) -> Any:
    if not isinstance(holdout, Mapping) or holdout.get("criterion") is None:
        return unobserved("no recorded holdout criterion for this version (qualified=false)")
    out: list[dict[str, Any]] = [
        {
            "name": str(holdout.get("criterionName") or "criterion"),
            "point": holdout.get("criterion"),
            "interval": None,
            "intervalReason": "the holdout records a point estimate; no interval",
            "units": holdout.get("criterionUnits"),
            "lowerIsBetter": True,
            "measuredAt": _value(
                holdout,
                "measuredAt",
                "this holdout predates the measuredAt stamp (versioning._require_measurement_time)",
            ),
        }
    ]
    for board, score in sorted((holdout.get("perSource") or {}).items()):
        out.append(
            {
                "name": f"rmse[{board}]",
                "point": score,
                "interval": None,
                "intervalReason": "per-board point estimate",
                "units": holdout.get("criterionUnits"),
                "lowerIsBetter": True,
                "rows": (holdout.get("perSourceRows") or {}).get(board),
            }
        )
    return out


def _hill_challenger_state(v: Mapping[str, Any], run: Mapping[str, Any] | None) -> tuple[str, str]:
    """Map one registry entry onto the lab vocabulary, using the verdict the latest
    Hill Autopilot run RECORDED (never re-derived against today's code)."""
    status = str(v.get("status") or "")
    notes = [str(n) for n in (v.get("notes") or [])]
    last_note = notes[-1] if notes else None
    if status == "rejected":
        return LAB_REJECTED, last_note or "registry status rejected (no reason recorded)"
    if status == "retired":
        return LAB_RETIRED, last_note or f"former champion, retired {v.get('retiredAt')}"
    holdout = v.get("holdout") or {}
    if not isinstance(holdout, Mapping) or holdout.get("criterion") is None:
        return LAB_INSUFFICIENT, "no out-of-sample holdout score recorded (qualified=false)"
    tr = v.get("trainingRun") or {}
    if not (isinstance(tr, Mapping) and tr.get("reproducible") is True):
        return (
            LAB_INSUFFICIENT,
            "legacy_substrate: no reproducible pinned training run, so it cannot be re-derived "
            "from its own record and may not compete (training_run.tournament_exclusion_reason)",
        )
    if run is None:
        return LAB_HELD, f"standing challenger; {NO_RUN}"
    number = v.get("version")
    excluded_block = run.get("excludedFromTournament") or {}
    excluded = (excluded_block.get("otherExclusions") or {}).get(str(number))
    if excluded:
        return LAB_HELD, f"excluded from the latest tournament: {excluded}"
    dupes = excluded_block.get("duplicates") or {}
    if str(number) in dupes or number in dupes:
        return LAB_HELD, "excluded from the latest tournament as a duplicate fit"
    competed = {t.get("version") for t in (run.get("tournament") or []) if isinstance(t, Mapping)}
    if number == run.get("winnerVersion"):
        return (
            LAB_HELD,
            f"latest tournament winner; Hill Autopilot {run.get('outcome')}: {run.get('reason')}",
        )
    if number in competed:
        return LAB_HELD, f"competed in the latest tournament (winner v{run.get('winnerVersion')})"
    return LAB_HELD, "standing challenger not yet adjudicated by a Hill Autopilot run"


def _live_constants_match(root: Path, champ: Mapping[str, Any] | None) -> dict[str, Any]:
    try:
        from src.model_registry.hill_masters import read_committed_constants

        live = read_committed_constants(root / HILL_CONSTANTS_REL)
    except Exception as exc:  # noqa: BLE001
        return {
            "liveConstantsMatchChampion": unobserved(
                f"served constants unreadable: {type(exc).__name__}: {exc}"
            )
        }
    params = dict((champ or {}).get("params") or {})
    if not params:
        return {
            "liveConstants": live,
            "liveConstantsMatchChampion": unobserved("the champion records no params"),
        }
    # ``write_committed_constants`` writes _C at 4 dp and _S at 3 dp.
    match = set(live) <= set(params) and all(
        abs(float(params[k]) - float(live[k])) < 5e-4 for k in live
    )
    return {"liveConstants": live, "liveConstantsMatchChampion": match}


def build_hill_family(root: Path, receipts: Mapping[str, Any]) -> dict[str, Any]:
    registry, reg_err = _read_json(root / HILL_REGISTRY_REL)
    runs, runs_note = _read_jsonl(root / HILL_AUTOPILOT_RUNS_REL)
    run = _latest_by(runs, "evaluatedAt")
    versions = [v for v in ((registry or {}).get("versions") or []) if isinstance(v, Mapping)]
    champ = next((v for v in versions if v.get("status") == "champion"), None)
    no_run = unobserved(runs_note or NO_RUN) if run is None else None

    artifacts = [
        _artifact(root, HILL_REGISTRY_REL, "version registry + champion pointer"),
        _artifact(root, HILL_AUTOPILOT_RUNS_REL, "Hill Autopilot adjudication log"),
        _artifact(root, HILL_POLICY_REL, "Hill Autopilot policy"),
        _artifact(root, HILL_CONSTANTS_REL, "served constants (production)"),
    ]

    # ── champion ────────────────────────────────────────────────────────────
    if champ is None:
        champion: Any = unobserved(reg_err or "the registry names no champion")
    else:
        from src.model_registry.learning_adapters import HILL_FEATURES

        holdout = champ.get("holdout") or {}
        tr = champ.get("trainingRun") or {}
        pre_substrate = (
            f"v{champ.get('version')} predates the pinned training-run substrate; "
            "its record carries input fingerprints but no training cutoff"
        )
        independence = (run or {}).get("holdoutIndependence") or {}
        validation: list[Any] = [
            {
                "design": "source_family holdout: boards from families the fit never read",
                "measuredAt": _value(
                    holdout, "measuredAt", "this holdout predates the measuredAt stamp"
                ),
                "boards": holdout.get("holdoutSources") or unobserved("holdout boards unrecorded"),
            }
        ]
        if run is not None:
            validation.append(
                {
                    "design": "paired re-score of the champion on the current holdout boards "
                    "(latest Hill Autopilot run)",
                    "measuredAt": run.get("evaluatedAt"),
                    "boards": sorted((run.get("championPerSource") or {}).keys()),
                }
            )
        champion = {
            "version": champ.get("version"),
            "createdAt": _instant(champ, "fittedAt", "fit time unrecorded"),
            "trainedAt": _instant(champ, "fittedAt", "fit time unrecorded"),
            "dataThrough": _value(tr, "trainingCutoff", pre_substrate),
            "featureDictionary": _feature_manifest(HILL_FAMILY, HILL_FEATURES),
            "trainingWindow": {
                "design": "one point-in-time board snapshot per fit",
                "cutoff": _value(tr, "trainingCutoff", pre_substrate),
                "trainingSources": holdout.get("trainingSources")
                or unobserved("training sources unrecorded"),
                "inputFingerprints": champ.get("trainingInputs")
                or unobserved("no input fingerprints recorded"),
            },
            "validationWindows": validation,
            "target": {
                "criterion": holdout.get("criterionName") or unobserved("criterion unrecorded"),
                "units": holdout.get("criterionUnits") or unobserved("units unrecorded"),
                "semantics": holdout.get("_semantics")
                or unobserved("the holdout records no measures / doesNotMeasure statement"),
            },
            "targetLineage": {
                "holdoutBoards": holdout.get("holdoutSources") or unobserved("unrecorded"),
                "lineageDependence": no_run
                or _value(
                    independence, "lineageDependence", "the run records no lineage dependence"
                ),
                "independentHoldout": no_run
                or _value(independence, "reason", "the run records no holdout-independence reason"),
                "independentValidation": no_run
                or _value(
                    run.get("independentValidation"),
                    "reason",
                    "the run predates the independent-validation gate",
                ),
            },
            "sampleSize": {
                "rowsPerHoldoutBoard": holdout.get("perSourceRows")
                or unobserved("rows per board unrecorded"),
                "rowsPerBoardLatestRescore": no_run
                or _value(run, "currentRows", "the run records no row counts"),
            },
            "metrics": {
                "registryHoldout": _hill_metrics(holdout),
                "latestPairedRescore": no_run
                or {
                    "name": "mean_per_source_rmse",
                    "point": run.get("championCriterion"),
                    "perBoard": run.get("championPerSource"),
                    "interval": None,
                    "intervalReason": "the Autopilot run records a point re-score",
                    "measuredAt": run.get("evaluatedAt"),
                },
            },
        }

    # ── challengers: every version, rejected and retired included ───────────
    challengers: list[dict[str, Any]] = []
    for v in versions:
        hold = v.get("holdout") or {}
        if v.get("status") == "champion":
            state = LAB_CHAMPION
            reason = ([str(n) for n in (v.get("notes") or [])] or ["the registry's champion"])[-1]
        else:
            state, reason = _hill_challenger_state(v, run)
        challengers.append(
            _challenger(
                version=v.get("version"),
                state=state,
                native_status=v.get("status"),
                created_at=_instant(v, "fittedAt", "fit time unrecorded"),
                metrics={
                    "criterion": _value(hold, "criterion", "no holdout criterion recorded"),
                    "measuredAt": _value(hold, "measuredAt", "no measuredAt stamp"),
                },
                reason=reason,
            )
        )

    # ── evaluation, gate, authority ─────────────────────────────────────────
    if run is None:
        last_eval: Any = no_run
        gate: Any = no_run
    else:
        last_eval = {
            "at": run.get("evaluatedAt"),
            "by": "Hill Autopilot (scripts/hill_autopilot.py)",
            "outcome": run.get("outcome"),
            "winnerVersion": run.get("winnerVersion"),
            "championVersion": run.get("championVersion"),
            "triggerSha": run.get("triggerSha"),
        }
        gate = {
            "result": _value(run, "outcome", "the run recorded no outcome"),
            "ready": run.get("ready"),
            "reason": run.get("reason"),
            "gates": _value(run, "gates", "the run recorded no gate map"),
            "independentValidation": _value(
                run, "independentValidation", "the run predates the independent-validation gate"
            ),
            "requiredImprovement": run.get("requiredImprovement"),
            "currentImprovement": run.get("currentImprovement"),
            "forward": {
                "days": run.get("forwardDays"),
                "winRate": run.get("forwardWinRate"),
                "medianImprovement": run.get("forwardMedianImprovement"),
            },
        }
    authority = {
        "mechanism": "Hill Autopilot (docs/valuation/HILL_AUTOPILOT_V2.md); the raw fitter never "
        "writes production",
        "automaticScope": no_run
        or _value(run, "safePromotionScope", "the run records no safe promotion scope"),
        "carriedFromIncumbent": "GLOBAL, IDP and ROOKIE are carried from the champion until they "
        "have their own promotable evidence (autopilot.compose_offense_only)",
        "independentTargetRequired": True,
        "independentTargetBasis": "owner methodology decision 2026-10-01: board-holdout gates are "
        "necessary, not sufficient (src/model_registry/independent_validation.py)",
        "manual": "scripts/model_registry.py promote + apply, run by a human (ADR-008, "
        "docs/roster-trade-intelligence/DECISIONS.md)",
    }

    # ── production + rollback ───────────────────────────────────────────────
    production: dict[str, Any] = {
        "served": "the champion's eight constants in src/canonical/player_valuation.py",
        "championVersion": _value(registry, "championVersion", "no champion pointer"),
        "championPromotedAt": _instant(champ, "promotedAt", "no promotion time recorded"),
        "championAppliedAt": _instant(
            champ, "appliedAt", "the registry records no apply time for this champion"
        ),
        **_live_constants_match(root, champ),
    }
    former = [v for v in versions if v.get("status") == "retired" and v.get("promotedAt")]
    if former:
        target = max(former, key=lambda v: (str(v.get("retiredAt") or ""), int(v["version"])))
        rollback: Any = {
            "version": target.get("version"),
            "retiredAt": target.get("retiredAt"),
            "mechanism": "ModelRegistry.rollback reinstates the most recently retired former "
            "champion; apply then writes its constants",
            "command": 'python scripts/model_registry.py rollback --reason "<why>" && '
            "python scripts/model_registry.py apply",
        }
    else:
        rollback = unobserved("the registry holds no former champion to roll back to")

    excluded = (run or {}).get("excludedFromTournament") or {}
    data_quality: dict[str, Any] = {
        "rowHealth": no_run or _value(run, "rowHealthDetail", "no row-health record"),
        "holdoutIndependence": no_run
        or _value(run.get("holdoutIndependence"), "reason", "no holdout-independence record"),
        "legacySubstrateChallengers": no_run
        or _value(excluded, "legacySubstrateCount", "no legacy-substrate count recorded"),
        "autopilotLog": runs_note or "all lines parsed",
        "registry": reg_err or "parsed",
    }

    if champ is None:
        decision = reg_err or "the registry names no champion"
    elif run is None:
        decision = (
            f"champion v{champ.get('version')}: "
            + ([str(n) for n in (champ.get("notes") or [])] or ["no reason recorded"])[-1]
        )
    else:
        decision = (
            f"champion v{champ.get('version')} retained; latest Hill Autopilot run "
            f"{run.get('evaluatedAt')}: {run.get('outcome')} — {run.get('reason')}"
        )

    return _family(
        family=HILL_FAMILY,
        name="Hill scope masters (percentile to value curves)",
        domain="dynasty valuation — canonical value scale",
        owners=[
            "src/model_registry/versioning.py",
            "src/model_registry/autopilot.py",
            "src/model_registry/independent_validation.py",
        ],
        artifacts=artifacts,
        champion=champion,
        challengers=challengers,
        challengerStates=None,
        drift=unmeasured(
            "no drift monitor exists for this family (the refit's scope RMSE comparison is a "
            "fit diagnostic, not a monitored drift receipt); unmeasured is not 'no drift'"
        ),
        calibration=not_applicable(
            "a deterministic curve scored by RMSE against market boards; it emits no "
            "probability to calibrate"
        ),
        lastEvaluation=last_eval,
        gate=gate,
        promotionAuthority=authority,
        productionState=production,
        rollback=rollback,
        decisionReason=decision,
        dataQuality=data_quality,
        receipts=_family_receipts(receipts, HILL_FAMILY),
    )


# ═════════════════════════════════════════════════════════════════════════════
# Shared: the Batch 3 shadow / evaluator families
# ═════════════════════════════════════════════════════════════════════════════

BATCH3_AUTHORITY = {
    "mechanism": "Batch 3 section N (docs/EXECUTION_PLAN.md section 0, Valuation Trust Program): "
    "a preregistered gate, independent fresh-context review, then explicit owner approval to "
    "flip the flag",
    "automatic": False,
    "note": "every receipt this family emits carries promotes: false; nothing here flips a flag",
}


def _evidence_file(
    root: Path, runtime_rel: str, committed_rel: str
) -> tuple[Any, str | None, str | None]:
    """``(document, origin_rel, reason)``: the production-host file when present, else
    the committed evidence file, labelled — never the one silently standing in for the
    other."""
    for rel in (runtime_rel, committed_rel):
        doc, err = _read_json(root / rel)
        if doc is not None:
            return doc, rel, None
    return None, None, f"neither {runtime_rel} nor {committed_rel} is present"


# ── source-quality weights (#1589) ───────────────────────────────────────────

SQ_FAMILY = "source_quality_weights"
SQ_RUNTIME_EVALS_REL = "data/source_quality/evaluations.jsonl"
SQ_COMMITTED_DIR_REL = "docs/valuation/evidence/source-quality-2026-10-01"
SQ_DISPOSITION_STATE = {
    "DOES_NOT_MEET_PREREGISTERED_GATE": LAB_REJECTED,
    "MEETS_PREREGISTERED_GATE": LAB_HELD,
    "INSUFFICIENT_EVIDENCE": LAB_INSUFFICIENT,
    "NOT_RUN": LAB_INSUFFICIENT,
}


def _ci_metric(name: str, blob: Any, *, higher_is_better: bool | None) -> dict[str, Any]:
    if not isinstance(blob, Mapping) or blob.get("point") is None:
        return {"name": name, **unobserved(f"{name} not recorded")}
    ci = blob.get("ci90")
    has_ci = isinstance(ci, (list, tuple)) and len(ci) == 2 and None not in ci
    return {
        "name": name,
        "point": blob.get("point"),
        "interval": list(ci) if has_ci else None,
        "level": 0.90 if has_ci else None,
        "method": f"seeded date-block bootstrap ({blob.get('blocks')} blocks x {blob.get('boot')} "
        "draws)"
        if has_ci
        else None,
        "se": blob.get("se"),
        "higherIsBetter": higher_is_better,
    }


def build_source_quality_family(root: Path, receipts: Mapping[str, Any]) -> dict[str, Any]:
    from src.model_registry.learning_adapters import SQ_CHAMPION, SQ_FEATURES

    origin = SQ_RUNTIME_EVALS_REL
    lines, note = _read_jsonl(root / SQ_RUNTIME_EVALS_REL)
    if not lines:
        origin = f"{SQ_COMMITTED_DIR_REL}/evaluations.jsonl"
        lines, note = _read_jsonl(root / origin)
    latest_at = _latest_by(lines, "evaluatedAt")
    latest_instant = (latest_at or {}).get("evaluatedAt")
    latest = [ln for ln in lines if ln.get("evaluatedAt") == latest_instant] if latest_at else []
    first = latest[0] if latest else None

    artifacts = [
        _artifact(root, SQ_RUNTIME_EVALS_REL, "evaluation archive (production host)"),
        _artifact(root, f"{SQ_COMMITTED_DIR_REL}/evaluations.jsonl", "committed evaluation"),
        _artifact(root, f"{SQ_COMMITTED_DIR_REL}/PREREGISTRATION.md", "preregistration"),
    ]
    none_msg = note or "no source-quality evaluation recorded"
    if first is None:
        champion: Any = {
            "version": SQ_CHAMPION,
            "createdAt": not_applicable("equal family weights are a rule, not a fit"),
            "trainedAt": not_applicable("equal family weights are a rule, not a fit"),
            "dataThrough": unobserved(none_msg),
            "featureDictionary": _feature_manifest(SQ_FAMILY, SQ_FEATURES),
            "trainingWindow": not_applicable("the champion is not fitted"),
            "validationWindows": unobserved(none_msg),
            "target": unobserved(none_msg),
            "targetLineage": unobserved(none_msg),
            "sampleSize": unobserved(none_msg),
            "metrics": unobserved(none_msg),
        }
    else:
        window = first.get("dataWindow")
        champion = {
            "version": SQ_CHAMPION,
            "createdAt": not_applicable("equal family weights are a rule, not a fit"),
            "trainedAt": not_applicable("equal family weights are a rule, not a fit"),
            "dataThrough": window[-1]
            if isinstance(window, list) and window
            else unobserved("evaluation records no data window"),
            "featureDictionary": _feature_manifest(SQ_FAMILY, SQ_FEATURES),
            "trainingWindow": not_applicable("the champion is not fitted"),
            "validationWindows": [
                {
                    "design": "walk-forward over the point-in-time panel (chronological)",
                    "dataWindow": window or unobserved("no data window recorded"),
                    "horizonDays": first.get("horizonDays"),
                    "panelDigest": first.get("panelDigest"),
                }
            ],
            "target": "leave-the-evaluated-family-out future market movement; MALE = mean "
            "absolute log error (learning_adapters.source_quality_receipts)",
            "targetLineage": {
                "preregistrationSha256": _value(first, "preregistrationSha256", "unpinned"),
                "note": "the evaluated family is left out of its own target",
            },
            "sampleSize": unobserved(
                "the archive line records bootstrap blocks, not cells; cells per stratum live in "
                "the full results file"
            )
            if not (first.get("championMALE") or {}).get("blocks")
            else {"bootstrapBlocks": (first.get("championMALE") or {}).get("blocks")},
            "metrics": [
                _ci_metric("championMALE", first.get("championMALE"), higher_is_better=False)
            ],
        }

    challengers = [
        _challenger(
            version=SQ_CHAMPION,
            state=LAB_CHAMPION,
            native_status="champion (served equal family weights)",
            created_at=not_applicable("a rule, not a fit"),
            metrics=[
                _ci_metric(
                    "championMALE", (first or {}).get("championMALE"), higher_is_better=False
                )
            ]
            if first
            else unobserved(none_msg),
            reason="equal-family champion retained (plan section 30, #1589)",
        )
    ]
    for ln in sorted(latest, key=lambda r: str(r.get("candidate"))):
        disp = str(ln.get("disposition") or "")
        state = SQ_DISPOSITION_STATE.get(disp)
        reasons = [*(ln.get("failed") or []), *(ln.get("missingEvidence") or [])]
        challengers.append(
            _challenger(
                version=ln.get("candidate"),
                state=state or LAB_INSUFFICIENT,
                native_status=disp or None,
                created_at=_instant(ln, "evaluatedAt", "unrecorded"),
                metrics=[
                    _ci_metric("deltaMALE", ln.get("deltaMALE"), higher_is_better=True),
                    _ci_metric("championMALE", ln.get("championMALE"), higher_is_better=False),
                ],
                reason="; ".join(str(r) for r in reasons)
                if reasons
                else (disp if state else f"unmapped disposition {disp!r}: reported, never guessed"),
            )
        )
    last_eval: Any = (
        {
            "at": latest_instant,
            "by": "scripts/source_quality_eval.py",
            "codeRevision": first.get("codeRevision"),
            "evidenceOrigin": origin,
            "status": first.get("status"),
        }
        if first
        else unobserved(none_msg)
    )
    gate: Any = (
        {
            "result": {str(ln.get("candidate")): ln.get("disposition") for ln in latest},
            "preregistration": f"{SQ_COMMITTED_DIR_REL}/PREREGISTRATION.md",
            "preregistrationSha256": first.get("preregistrationSha256"),
        }
        if first
        else unobserved(none_msg)
    )
    return _family(
        family=SQ_FAMILY,
        name="Source-quality authority weights",
        domain="dynasty valuation — source weighting",
        owners=["src/source_quality/evaluate.py", "scripts/source_quality_eval.py"],
        artifacts=artifacts,
        champion=champion,
        challengers=challengers,
        challengerStates=None,
        drift=unmeasured(),
        calibration=not_applicable("weights, not probabilities"),
        lastEvaluation=last_eval,
        gate=gate,
        promotionAuthority=BATCH3_AUTHORITY,
        productionState={
            "served": "equal family weights (the champion); candidates are evaluated, never served",
            "evaluatorStatus": (first or {}).get("status") or unobserved(none_msg),
        },
        rollback=not_applicable("the champion has never been replaced; nothing to roll back"),
        decisionReason="equal-family champion retained: "
        + (
            "; ".join(f"{ln.get('candidate')}: {ln.get('disposition')}" for ln in latest)
            if latest
            else none_msg
        ),
        dataQuality={
            "missingEvidence": sorted(
                {str(m) for ln in latest for m in (ln.get("missingEvidence") or [])}
            )
            if latest
            else unobserved(none_msg),
            "evidenceOrigin": origin,
            "archive": note or "all lines parsed",
        },
        receipts=_family_receipts(receipts, SQ_FAMILY),
    )


# ── sparse-evidence estimator (Batch 3 Unit E, #1591) ────────────────────────

SPARSE_FAMILY = "sparse_evidence_estimator"
SPARSE_LEDGER_DIR_REL = "data/sparse_evidence_shadow"
SPARSE_EVIDENCE_REL = "docs/valuation/evidence/sparse-evidence-2026-10-01"
SPARSE_VERDICT_STATE = {"does not meet gate": LAB_REJECTED, "meets gate": LAB_HELD}


def _sparse_ledger(root: Path) -> dict[str, Any]:
    from src.api.sparse_evidence_shadow import LEGACY_LEDGER_NAME
    from src.utils.append_ledger import ledger_files

    base = root / SPARSE_LEDGER_DIR_REL
    files = ledger_files(base, LEGACY_LEDGER_NAME) if base.is_dir() else []
    if not files:
        return unobserved(f"{SPARSE_LEDGER_DIR_REL}/ is absent on this host (production-only)")
    latest = _tail(files[-1])
    return {
        "state": "observed",
        "files": len(files),
        "records": _count_lines(files),
        "latest": latest,
    }


def build_sparse_family(root: Path, receipts: Mapping[str, Any]) -> dict[str, Any]:
    from src.api.sparse_evidence import ESTIMATOR_VERSION
    from src.model_registry.producer_receipts import SPARSE_FEATURES, sparse_model_ids

    results, err = _read_json(root / SPARSE_EVIDENCE_REL / "results.json")
    ledger = _sparse_ledger(root)
    latest = ledger.get("latest") if ledger.get("state") == "observed" else None
    ids: tuple[str, str] | None = None
    if latest:
        try:
            ids = sparse_model_ids(latest)
        except Exception:  # noqa: BLE001 — an unidentifiable record stays unidentified
            ids = None
    pins = (results or {}).get("pins") or {}
    payload = pins.get("payload") or {}
    verdict = (results or {}).get("verdict")
    gates = (results or {}).get("gates")
    no_eval = err or "no committed sparse-evidence evaluation"

    champion = {
        "version": ids[0]
        if ids
        else unobserved(
            "the served incumbent's version token is minted per shadow record "
            "(producer_receipts.sparse_model_ids); no shadow record on this host"
        ),
        "createdAt": not_applicable(
            "the incumbent 0.30 single-source retention is a rule, not a fit"
        ),
        "trainedAt": not_applicable("not fitted"),
        "dataThrough": ((latest or {}).get("board") or {}).get("scrapeTimestamp")
        or _value(payload, "scrapeTimestamp", no_eval),
        "featureDictionary": _feature_manifest(SPARSE_FAMILY, SPARSE_FEATURES),
        "trainingWindow": not_applicable("deterministic estimator; nothing is trained"),
        "validationWindows": [
            {
                "design": "one pinned board, preregistered structural gates G1-G6",
                "board": payload.get("scrapeTimestamp") or unobserved(no_eval),
                "evidence": f"{SPARSE_EVIDENCE_REL}/results.json",
            }
        ],
        "target": "preregistered structural gates on one board (PREREGISTRATION.md); the "
        "evaluation settles no outcome",
        "targetLineage": not_applicable("structural gates, no outcome target"),
        "sampleSize": {"boardRows": _value(results, "boardRows", no_eval)},
        "metrics": not_applicable("the incumbent is the reference the gates compare against"),
    }
    challenger_state = SPARSE_VERDICT_STATE.get(str(verdict or "").strip().lower())
    failed = [
        k for k, g in (gates or {}).items() if isinstance(g, Mapping) and g.get("pass") is False
    ]
    challengers = [
        _challenger(
            version=ids[0] if ids else "served incumbent",
            state=LAB_CHAMPION,
            native_status="SERVED_AT_RECORD (flag OFF)",
            created_at=not_applicable("a rule, not a fit"),
            metrics=not_applicable("reference side of the comparison"),
            reason="served while the sparse_evidence_estimator flag is OFF",
        ),
        _challenger(
            version=ids[1] if ids else ESTIMATOR_VERSION,
            state=challenger_state or LAB_INSUFFICIENT,
            native_status=verdict or unobserved(no_eval),
            created_at=not_applicable("a deterministic estimator version"),
            metrics=gates if isinstance(gates, Mapping) else unobserved(no_eval),
            reason=(
                f"preregistered verdict: {verdict} (failed: {', '.join(failed) or 'none'}); "
                "flag stays OFF; the shadow ledger keeps collecting outcome evidence"
            )
            if verdict
            else no_eval,
        ),
    ]
    return _family(
        family=SPARSE_FAMILY,
        name="Sparse-evidence estimator (single-family rows)",
        domain="dynasty valuation — single-source haircut",
        owners=["src/api/sparse_evidence.py", "src/api/sparse_evidence_shadow.py"],
        artifacts=[
            _artifact(root, SPARSE_LEDGER_DIR_REL, "shadow ledger (production host)"),
            _artifact(root, f"{SPARSE_EVIDENCE_REL}/results.json", "committed evaluation"),
            _artifact(root, f"{SPARSE_EVIDENCE_REL}/PREREGISTRATION.md", "preregistration"),
        ],
        champion=champion,
        challengers=challengers,
        challengerStates=None,
        drift=unmeasured(),
        calibration=unobserved(
            "the challenger's intervals are documented as uncalibrated (intervalLabel); no "
            "calibration evaluation exists"
        ),
        lastEvaluation={
            "at": unobserved("results.json records no evaluation instant"),
            "by": "preregistered one-board evaluation",
            "verdict": verdict,
            "codeRevision": pins.get("codeRevision"),
            "evidenceOrigin": f"{SPARSE_EVIDENCE_REL}/results.json",
        }
        if results
        else unobserved(no_eval),
        gate={
            "result": verdict,
            "gates": gates,
            "preregistration": (results or {}).get("preregistration"),
        }
        if results
        else unobserved(no_eval),
        promotionAuthority=BATCH3_AUTHORITY,
        productionState={
            **_flag_state("sparse_evidence_estimator"),
            "shadowLedger": {k: v for k, v in ledger.items() if k != "latest"},
            "latestShadowRecordAt": (latest or {}).get("recordedAt")
            or unobserved("no shadow record on this host"),
        },
        rollback={
            "served": "the incumbent is served; nothing to roll back",
            "ifEnabled": "RISKIT_FEATURE_SPARSE_EVIDENCE_ESTIMATOR=0 + restart",
        },
        decisionReason=(
            f"flag OFF; candidate C preregistered verdict: {verdict}" if verdict else no_eval
        ),
        dataQuality={
            "latestBoardAgeHours": ((latest or {}).get("board") or {}).get("payloadAgeHours")
            if latest
            else unobserved("no shadow record on this host"),
            "latestCounts": (latest or {}).get("counts")
            if latest
            else unobserved("no shadow record on this host"),
        },
        receipts=_family_receipts(receipts, SPARSE_FAMILY),
    )


# ── joint robust filter (Batch 2 Unit C, #1590) ──────────────────────────────

ROBUST_FAMILY = "joint_robust_filter"
ROBUST_DIR_REL = "data/robust_filter_shadow"
ROBUST_EVIDENCE_REL = "docs/valuation/evidence/joint-filter-shadow-2026-10-01"
ROBUST_VERDICT_STATE = {
    "PROMOTION_ELIGIBLE_PENDING_INDEPENDENT_REVIEW": LAB_HELD,
    "NOT_BETTER": LAB_REJECTED,
    "INCONCLUSIVE": LAB_SHADOW,
    "INSUFFICIENT": LAB_INSUFFICIENT,
}


def build_robust_family(root: Path, receipts: Mapping[str, Any]) -> dict[str, Any]:
    from src.api.joint_robust_filter import CHALLENGER_VERSION
    from src.model_registry.producer_receipts import ROBUST_FEATURES, robust_model_ids

    evaluation, origin, err = _evidence_file(
        root,
        f"{ROBUST_DIR_REL}/evaluation_live_shadow.json",
        f"{ROBUST_EVIDENCE_REL}/evaluation_historical_replay.json",
    )
    ledger_file = root / ROBUST_DIR_REL / "ledger.jsonl"
    latest = _tail(ledger_file) if ledger_file.is_file() else None
    ids: tuple[str, str] | None = None
    if latest:
        try:
            ids = robust_model_ids(latest)
        except Exception:  # noqa: BLE001
            ids = None
    primary = (evaluation or {}).get("primary") or {}
    decision = primary.get("decision") or {}
    verdict = decision.get("verdict")
    no_eval = err or "no joint-filter evaluation recorded"
    mode = (evaluation or {}).get("mode")
    horizons = primary.get("horizons") or {}

    metrics: Any
    if horizons:
        metrics = []
        for h in sorted(horizons, key=lambda x: int(x) if str(x).isdigit() else 0):
            d = (horizons[h] or {}).get("delta") or {}
            metrics.append(
                {
                    "name": f"delta[{h}d]",
                    "point": d.get("point"),
                    "interval": [d.get("lo95"), d.get("hi95")]
                    if d.get("lo95") is not None and d.get("hi95") is not None
                    else None,
                    "level": 0.95,
                    "method": f"date-block bootstrap ({d.get('blocks')} blocks, "
                    f"{d.get('resamplesUsed')} resamples)",
                    "higherIsBetter": True,
                }
            )
    else:
        metrics = unobserved(no_eval)

    champion = {
        "version": ids[0]
        if ids
        else unobserved(
            "the served Hampel incumbent's version token is minted per shadow record "
            "(producer_receipts.robust_model_ids); no shadow record on this host"
        ),
        "createdAt": not_applicable("the Hampel incumbent is a rule, not a fit"),
        "trainedAt": not_applicable("not fitted"),
        "dataThrough": ((latest or {}).get("board") or {}).get("scrapeTimestamp")
        or (primary.get("span") or [None])[-1]
        or unobserved(no_eval),
        "featureDictionary": _feature_manifest(ROBUST_FAMILY, ROBUST_FEATURES),
        "trainingWindow": not_applicable("deterministic filter; nothing is trained"),
        "validationWindows": [
            {
                "design": "date-block bootstrap over origin days (chronological)",
                "mode": mode or unobserved(no_eval),
                "span": primary.get("span") or unobserved(no_eval),
                "originDays": primary.get("originDays"),
                "boards": primary.get("boards"),
            }
        ],
        "target": "future lead share of the rescued / rejected / agreed sides "
        "(PREREGISTRATION.md, src/robust_filter_shadow/outcomes.py)",
        "targetLineage": {"preregistration": (evaluation or {}).get("preregistration")}
        if evaluation
        else unobserved(no_eval),
        "sampleSize": decision.get("minimumSample") or unobserved(no_eval),
        "metrics": not_applicable("the incumbent is the reference the deltas compare against"),
    }
    state = ROBUST_VERDICT_STATE.get(str(verdict or ""))
    challengers = [
        _challenger(
            version=ids[0] if ids else "served Hampel incumbent",
            state=LAB_CHAMPION,
            native_status="SERVED_AT_RECORD (flags OFF)",
            created_at=not_applicable("a rule, not a fit"),
            metrics=not_applicable("reference side of the comparison"),
            reason="served while joint_outlier_sparse_challenger is OFF",
        ),
        _challenger(
            version=ids[1] if ids else CHALLENGER_VERSION,
            state=state or LAB_INSUFFICIENT,
            native_status=verdict or unobserved(no_eval),
            created_at=not_applicable("a deterministic filter version"),
            metrics=metrics,
            reason="; ".join(str(r) for r in (decision.get("reasons") or []))
            or (no_eval if not verdict else f"verdict {verdict}"),
        ),
    ]
    replay_note = (
        "historical_replay: archived inputs rebuilt through today's code — NOT what production "
        "served; hindsight evidence only"
        if mode == "historical_replay"
        else None
    )
    return _family(
        family=ROBUST_FAMILY,
        name="Joint robust outlier filter",
        domain="dynasty valuation — per-player outlier filter",
        owners=["src/api/joint_robust_filter.py", "src/robust_filter_shadow/"],
        artifacts=[
            _artifact(root, f"{ROBUST_DIR_REL}/ledger.jsonl", "shadow ledger (production host)"),
            _artifact(
                root, f"{ROBUST_DIR_REL}/evaluation_live_shadow.json", "live evaluation (host)"
            ),
            _artifact(
                root,
                f"{ROBUST_EVIDENCE_REL}/evaluation_historical_replay.json",
                "committed replay evaluation",
            ),
            _artifact(root, f"{ROBUST_EVIDENCE_REL}/PREREGISTRATION.md", "preregistration"),
        ],
        champion=champion,
        challengers=challengers,
        challengerStates=None,
        drift=unmeasured(),
        calibration=not_applicable("a filter; it emits no probability"),
        lastEvaluation={
            "at": _value(evaluation, "computedAt", "the evaluation records no instant"),
            "by": "scripts/joint_filter_shadow.py evaluate",
            "mode": mode,
            "verdict": verdict,
            "evidenceOrigin": origin,
            "caveat": replay_note,
        }
        if evaluation
        else unobserved(no_eval),
        gate={
            "result": verdict,
            "reasons": decision.get("reasons"),
            "minimumSample": decision.get("minimumSample"),
            "preregistration": (evaluation or {}).get("preregistration"),
        }
        if evaluation
        else unobserved(no_eval),
        promotionAuthority={
            **BATCH3_AUTHORITY,
            "note": "PROMOTION_ELIGIBLE_PENDING_INDEPENDENT_REVIEW still requires independent "
            "review and owner approval; promotes: false on every receipt",
        },
        productionState={
            "flags": [
                _flag_state("joint_outlier_sparse_challenger"),
                _flag_state("joint_sparse_limited_evidence"),
            ],
            "shadowLedgerPresent": ledger_file.is_file(),
            "latestShadowRecordAt": (latest or {}).get("recordedAt")
            or unobserved("no shadow record on this host"),
            "latestShadowMode": (latest or {}).get("mode")
            or unobserved("no shadow record on this host"),
        },
        rollback={
            "served": "the Hampel incumbent is served; nothing to roll back",
            "ifEnabled": "RISKIT_FEATURE_JOINT_OUTLIER_SPARSE_CHALLENGER=0 + restart",
        },
        decisionReason=(f"flags OFF; preregistered verdict {verdict}" if verdict else no_eval)
        + (f" ({replay_note})" if replay_note else ""),
        dataQuality={
            "evidenceMode": mode or unobserved(no_eval),
            "latestBoardCompleteness": ((latest or {}).get("board") or {}).get("completeness")
            if latest
            else unobserved("no shadow record on this host"),
            "accumulation": decision.get("accumulation") or unobserved(no_eval),
        },
        receipts=_family_receipts(receipts, ROBUST_FAMILY),
    )


# ── Signals IDP shared-market crosswalk (#1627, preregistered 2026-10-04) ────

SIGNALS_FAMILY = "signals_idp_shared_market"
SIGNALS_PREREG_REL = "docs/sources/SIGNALS_FANTASY_INTEGRATION.md"
SIGNALS_REPORTS_REL = "data/sources/signals/reports"


def build_signals_family(root: Path, receipts: Mapping[str, Any]) -> dict[str, Any]:
    flag = _flag_state("signals_idp_shared_market")
    reports_dir = root / SIGNALS_REPORTS_REL
    reports = sorted(reports_dir.glob("onbox_*.json")) if reports_dir.is_dir() else []
    latest_doc, latest_err = (None, None)
    if reports:
        latest_doc, latest_err = _read_json(reports[-1])
    no_report = latest_err or (
        f"{SIGNALS_REPORTS_REL}/ holds no on-box report on this host (production-only)"
    )
    # Only identity fields are read from the private report: never a player, a
    # per-player number or a vendor value (scripts/verify_signals_onbox.py).
    report_identity = (
        {
            "file": _rel(root, reports[-1]),
            "utc": (latest_doc or {}).get("utc"),
            "deployedCommit": (latest_doc or {}).get("deployedCommit"),
            "deployIntervened": (latest_doc or {}).get("deployIntervened"),
        }
        if latest_doc is not None
        else unobserved(no_report)
    )
    prereg_sha = _sha256_file(root / SIGNALS_PREREG_REL)
    enabled = flag.get("enabled") is True
    no_results = (
        "the preregistered gate's per-criterion results (section 10.8) have not been recorded; "
        "the on-box report carries measurements, not an adjudicated verdict"
    )
    champion_desc = "Candidate A served (flag ON)" if enabled else "no Signals IDP vote (hold)"
    champion = {
        "version": champion_desc,
        "createdAt": not_applicable("a source-vote hold, not a fit"),
        "trainedAt": not_applicable("Candidate A fits no parameter (section 10.7)"),
        "dataThrough": unobserved(no_report) if latest_doc is None else latest_doc.get("utc"),
        "featureDictionary": not_applicable(
            "this family declares no feature manifest in the feature dictionary"
        ),
        "trainingWindow": not_applicable("Candidate A fits no parameter"),
        "validationWindows": unobserved(no_results),
        "target": "preregistered promotion gate, criteria 1-9 "
        f"({SIGNALS_PREREG_REL} section 10.6)",
        "targetLineage": "criterion 9: completed-trade evidence (section 10.7); recorded "
        "INSUFFICIENT below 30 covered trades",
        "sampleSize": unobserved(no_results),
        "metrics": unobserved(no_results),
    }
    challengers = [
        _challenger(
            version="no Signals IDP vote (hold)",
            state=LAB_RETIRED if enabled else LAB_CHAMPION,
            native_status="PRIVATE_SOURCE_VOTE_HOLDS: shared_market_crosswalk_in_shadow_pending_"
            "promotion",
            created_at=not_applicable("a hold"),
            metrics=not_applicable("reference side"),
            reason="the incumbent board with no Signals IDP vote (section 10.3)",
        ),
        _challenger(
            version="Candidate A: family rank to shared-market family ladder to GLOBAL curve",
            state=LAB_CHAMPION if enabled else LAB_SHADOW,
            native_status="flag ON" if enabled else "shadow (flag OFF)",
            created_at=not_applicable("preregistered rule, fits no parameter"),
            metrics=unobserved(no_results),
            reason=no_results,
        ),
    ]
    return _family(
        family=SIGNALS_FAMILY,
        name="Signals IDP shared-market crosswalk",
        domain="dynasty valuation — IDP source vote",
        owners=[
            "src/api/data_contract.py (PRIVATE_SOURCE_VOTE_HOLDS)",
            "scripts/verify_signals_onbox.py",
        ],
        artifacts=[
            _artifact(root, SIGNALS_PREREG_REL, "preregistration (section 10)"),
            _artifact(root, SIGNALS_REPORTS_REL, "private on-box reports (production host)"),
        ],
        champion=champion,
        challengers=challengers,
        challengerStates=None,
        drift=unmeasured(),
        calibration=not_applicable("a source crosswalk; it emits no probability"),
        lastEvaluation=report_identity,
        gate={
            "result": unobserved(no_results),
            "preregistration": SIGNALS_PREREG_REL,
            "preregistrationSha256": prereg_sha or unobserved("preregistration absent"),
            "criteria": "section 10.6 criteria 1-9 (7: independent fresh-context review)",
        },
        promotionAuthority={
            "mechanism": "all of section 10.6 criteria 1-8 hold on the production board, "
            "independent review approves, then the owner flips signals_idp_shared_market",
            "automatic": False,
        },
        productionState=flag,
        rollback={
            "served": "Candidate A is served (flag ON)" if enabled else "the hold is served",
            "command": "RISKIT_FEATURE_SIGNALS_IDP_SHARED_MARKET=0 + restart",
        },
        decisionReason=f"flag {'ON' if enabled else 'OFF'}; {no_results}",
        dataQuality={"onboxReports": len(reports), "latestReport": report_identity},
        receipts=_family_receipts(receipts, SIGNALS_FAMILY),
    )


# ── Consensus Edge (ship gate, ADR-023) ──────────────────────────────────────

CE_FAMILY = "consensus_edge"
CE_MEASUREMENTS_REL = "docs/measurements"
CE_PARAMS_REL = "config/consensus_edge/params_v1.json"
CE_DECISION_STATE = {"ship it (flag on)": LAB_CHAMPION, "do not ship yet": LAB_REJECTED}


def build_consensus_edge_family(root: Path, receipts: Mapping[str, Any]) -> dict[str, Any]:
    from src.consensus_edge import MODEL_VERSION
    from src.consensus_edge import params as ce_params

    flag = _flag_state("consensus_edge")
    enabled = flag.get("enabled") is True
    try:
        current_param_id: Any = ce_params.param_set_id(root / CE_PARAMS_REL)
    except Exception as exc:  # noqa: BLE001
        current_param_id = unobserved(f"params unreadable: {type(exc).__name__}: {exc}")
    folder = root / CE_MEASUREMENTS_REL
    docs = []
    for path in (
        sorted(folder.glob("consensus-edge-board-validation-*.json")) if folder.is_dir() else []
    ):
        doc, _err = _read_json(path)
        if isinstance(doc, Mapping):
            docs.append((path, doc))
    # The newest validation PER HORIZON: each horizon is its own preregistered run.
    by_horizon: dict[str, list[tuple[Path, Mapping[str, Any]]]] = {}
    for path, doc in docs:
        by_horizon.setdefault(str(doc.get("horizonDays")), []).append((path, doc))
    latest = []
    for group in by_horizon.values():
        newest = _latest_by([d for _, d in group], "measuredAt")
        latest.extend((p, d) for p, d in group if d is newest)
    latest_instant = max(
        (str(d.get("measuredAt")) for _, d in latest if _parse_instant(d.get("measuredAt"))),
        default=None,
    )
    no_eval = "no Consensus Edge board validation recorded under docs/measurements/"
    recommendations = sorted(
        {str((d.get("decision") or {}).get("recommendation")) for _, d in latest}
    )
    rec = recommendations[0] if len(recommendations) == 1 else None
    measured_param_ids = sorted({str(d.get("paramSetId")) for _, d in latest})
    measured_versions = sorted({str(d.get("modelVersion")) for _, d in latest})
    metrics: Any = (
        [
            {
                "name": f"medianExcessTop20[{d.get('horizonDays')}d]",
                "point": (d.get("decision") or {}).get("medianExcessTop20"),
                "interval": None,
                "intervalReason": "the validation reports a median and fold counts, no interval",
                "foldsBeatRandom": (d.get("decision") or {}).get("foldsBeatRandom"),
                "foldsUsable": d.get("foldsUsable"),
                "higherIsBetter": True,
            }
            for _, d in sorted(latest, key=lambda pd: int(pd[1].get("horizonDays") or 0))
        ]
        if latest
        else unobserved(no_eval)
    )
    state = CE_DECISION_STATE.get(str(rec or "").lower()) if rec else None
    if rec and state is None and rec.lower().startswith("inconclusive"):
        state = LAB_INSUFFICIENT
    model = _challenger(
        version=f"{MODEL_VERSION} / params {current_param_id}"
        if isinstance(current_param_id, str)
        else MODEL_VERSION,
        state=LAB_CHAMPION if enabled else (state or LAB_INSUFFICIENT),
        native_status=rec
        or (" | ".join(recommendations) if recommendations else unobserved(no_eval)),
        created_at=not_applicable("a model version constant, not a fit time"),
        metrics=metrics,
        reason=(
            "; ".join(str((d.get("decision") or {}).get("rationale")) for _, d in latest)
            if latest
            else no_eval
        ),
    )
    if enabled:
        champion: Any = {
            "version": model["version"],
            "createdAt": not_applicable("a model version constant"),
            "trainedAt": not_applicable("parameters are a declared set, not a fit"),
            "dataThrough": (latest[0][1].get("panelEnd") if latest else unobserved(no_eval)),
            "featureDictionary": not_applicable(
                "this family declares no feature manifest in the feature dictionary"
            ),
            "trainingWindow": not_applicable("not fitted"),
            "validationWindows": [
                {
                    "panelStart": d.get("panelStart"),
                    "panelEnd": d.get("panelEnd"),
                    "horizonDays": d.get("horizonDays"),
                }
                for _, d in latest
            ]
            or unobserved(no_eval),
            "target": (latest[0][1].get("target") if latest else unobserved(no_eval)),
            "targetLineage": unobserved("the validation records no target lineage"),
            "sampleSize": {
                "foldsUsable": {str(d.get("horizonDays")): d.get("foldsUsable") for _, d in latest}
            }
            if latest
            else unobserved(no_eval),
            "metrics": metrics,
        }
    else:
        champion = not_applicable(
            "no Consensus Edge model is served: the flag is OFF, so the incumbent is 'no "
            "Consensus Edge call' (ADR-023)"
        )
    stale = bool(latest) and (
        measured_param_ids != [current_param_id] or measured_versions != [MODEL_VERSION]
    )
    return _family(
        family=CE_FAMILY,
        name="Consensus Edge (buy / sell calls)",
        domain="market edge — private decision intelligence",
        owners=["src/consensus_edge/", "scripts/validate_consensus_edge_board.py"],
        artifacts=[
            _artifact(root, CE_PARAMS_REL, "parameter set"),
            *[_artifact(root, _rel(root, p), "board validation") for p, _ in latest],
        ],
        champion=champion,
        challengers=[model],
        challengerStates=None,
        drift=unmeasured(),
        calibration=unobserved(
            "the ship gate measures cohort excess return; no calibration " "evaluation exists"
        ),
        lastEvaluation={
            "at": latest_instant,
            "by": "scripts/validate_consensus_edge_board.py",
            "recommendation": rec or recommendations,
            "measuredParamSetIds": measured_param_ids,
            "measuredModelVersions": measured_versions,
        }
        if latest
        else unobserved(no_eval),
        gate={
            "result": rec or recommendations,
            "bar": (latest[0][1].get("decision") or {}).get("rationale") if latest else None,
            "measuredCurrentModel": (not stale) if latest else unobserved(no_eval),
        }
        if latest
        else unobserved(no_eval),
        promotionAuthority={
            "mechanism": "the preregistered ship gate in scripts/validate_consensus_edge_board.py "
            "must pass on a re-run before the default flips (ADR-023); not a judgement call",
            "automatic": False,
        },
        productionState={**flag, "modelVersion": MODEL_VERSION, "paramSetId": current_param_id},
        rollback={"command": "RISKIT_FEATURE_CONSENSUS_EDGE=0 + restart"},
        decisionReason=(
            f"flag {'ON' if enabled else 'OFF'}; latest ship gate: {rec or recommendations}"
            if latest
            else no_eval
        ),
        dataQuality={
            "validationMeasuredCurrentParams": (not stale) if latest else unobserved(no_eval),
            "foldsTruncated": {
                str(d.get("horizonDays")): d.get("foldsTruncated") for _, d in latest
            }
            if latest
            else unobserved(no_eval),
            "caveats": [c for _, d in latest for c in (d.get("caveats") or [])]
            if latest
            else unobserved(no_eval),
        },
        receipts=_family_receipts(receipts, CE_FAMILY),
    )


# ── BDVM parameter set ───────────────────────────────────────────────────────

BDVM_FAMILY = "bdvm_params"
BDVM_PARAMS_DIR_REL = "config/bdvm"


def build_bdvm_family(root: Path, receipts: Mapping[str, Any]) -> dict[str, Any]:
    from src.bdvm import params as bdvm_params

    flag = _flag_state("bdvm_engine")
    name = os.getenv("BDVM_PARAM_SET") or bdvm_params.DEFAULT_PARAM_SET
    sets: dict[str, Any] = {}
    folder = root / BDVM_PARAMS_DIR_REL
    for path in sorted(folder.glob("params_*.json")) if folder.is_dir() else []:
        doc, err = _read_json(path)
        if isinstance(doc, dict):
            sets[path.stem] = bdvm_params.ParamSet(path.stem, doc).to_meta()
        else:
            sets[path.stem] = unobserved(err or "unreadable")
    served = sets.get(name)
    no_eval = (
        "no BDVM evaluator exists: the parameters are declared starting priors, not backtested "
        "truth (config/bdvm/params_v1.json _comment); projection scorecards are unit IC-4"
    )
    if isinstance(served, Mapping) and "paramSetId" in served:
        champion: Any = {
            "version": served["paramSetId"],
            "createdAt": unobserved("the parameter file records no creation instant"),
            "trainedAt": not_applicable("starting priors, not fitted"),
            "dataThrough": not_applicable("priors carry no data window"),
            "featureDictionary": not_applicable(
                "this family declares no feature manifest in the feature dictionary"
            ),
            "trainingWindow": not_applicable("not fitted"),
            "validationWindows": unobserved(no_eval),
            "target": unobserved(no_eval),
            "targetLineage": unobserved(no_eval),
            "sampleSize": unobserved(no_eval),
            "metrics": unobserved(no_eval),
        }
    else:
        champion = unobserved(
            f"served parameter set {name!r} not found under {BDVM_PARAMS_DIR_REL}"
        )
    challengers = [
        _challenger(
            version=(
                meta.get("paramSetId")
                if isinstance(meta, Mapping) and "paramSetId" in meta
                else stem
            ),
            state=LAB_CHAMPION if stem == name else LAB_INSUFFICIENT,
            native_status="served" if stem == name else "present, not served",
            created_at=unobserved("the parameter file records no creation instant"),
            metrics=unobserved(no_eval),
            reason=f"selected by BDVM_PARAM_SET / default ({name})"
            if stem == name
            else "an alternative parameter set with no evaluation",
        )
        for stem, meta in sets.items()
    ]
    return _family(
        family=BDVM_FAMILY,
        name="BDVM fundamental valuation parameters",
        domain="fundamental dynasty value (BDVM)",
        owners=["src/bdvm/params.py"],
        artifacts=[
            _artifact(root, f"{BDVM_PARAMS_DIR_REL}/{s}.json", "parameter set") for s in sets
        ],
        champion=champion,
        challengers=challengers,
        challengerStates=None,
        drift=unmeasured(),
        calibration=unobserved(no_eval),
        lastEvaluation=unobserved(no_eval),
        gate=not_applicable("no promotion gate exists; a parameter change is an explicit edit"),
        promotionAuthority={
            "mechanism": "explicit owner-approved edit of config/bdvm/ (P6 / model-registry "
            "acceptance for learned methodology changes)",
            "automatic": False,
        },
        productionState={**flag, "servedParamSet": name, "meta": served or unobserved("absent")},
        rollback={
            "command": "BDVM_PARAM_SET=<previous stem> + restart, or "
            "RISKIT_FEATURE_BDVM_ENGINE=0 + restart",
        },
        decisionReason=f"served {name}; {no_eval}",
        dataQuality=unobserved(no_eval),
        receipts=_family_receipts(receipts, BDVM_FAMILY),
    )


# ═════════════════════════════════════════════════════════════════════════════
# Assembly
# ═════════════════════════════════════════════════════════════════════════════

FamilyBuilder = Callable[[Path, Mapping[str, Any]], dict[str, Any]]

FAMILY_BUILDERS: tuple[tuple[str, FamilyBuilder], ...] = (
    (HILL_FAMILY, build_hill_family),
    (SQ_FAMILY, build_source_quality_family),
    (SPARSE_FAMILY, build_sparse_family),
    (ROBUST_FAMILY, build_robust_family),
    (SIGNALS_FAMILY, build_signals_family),
    (CE_FAMILY, build_consensus_edge_family),
    (BDVM_FAMILY, build_bdvm_family),
)

#: Domains looked for and not found, stated so their absence is not mistaken for
#: an oversight (Game Day / projection evaluators are units IC-4 / AL-3).
NOT_COVERED: tuple[dict[str, str], ...] = (
    {
        "domain": "Game Day / weekly projections / playoff forecasts",
        "reason": "capture only — src/ros/game_day_archive.py, src/ros/forecast_archive.py; no "
        "evaluator or calibration scorer exists yet (AL-3 / IC-4)",
    },
)


def _unlisted_family(family: str, receipts: Mapping[str, Any]) -> dict[str, Any]:
    """A family that has receipts but no native owner wired here (§33: every family
    with at least one receipt appears).  Everything but its receipts is unobserved."""
    why = "receipts exist for this family but the Model Lab has no native owner for it yet"
    return _family(
        family=family,
        name=family,
        domain=unobserved(why),
        owners=[],
        artifacts=[],
        champion=unobserved(why),
        challengers=unobserved(why),
        challengerStates=unobserved(why),
        drift=unmeasured(),
        calibration=unobserved(why),
        lastEvaluation=unobserved(why),
        gate=unobserved(why),
        promotionAuthority=unobserved(why),
        productionState=unobserved(why),
        rollback=unobserved(why),
        decisionReason=why,
        dataQuality=unobserved(why),
        receipts=_family_receipts(receipts, family),
    )


def build_model_lab(
    root: Path | None = None, *, receipt_store_path: Path | None = None
) -> dict[str, Any]:
    """The whole Model Lab payload.  Pure read: no file, flag or pointer is written."""
    base = Path(root) if root is not None else REPO
    receipts = _receipt_index(receipt_store_path)
    families: list[dict[str, Any]] = []
    errors: dict[str, str] = {}
    for family_id, builder in FAMILY_BUILDERS:
        try:
            families.append(builder(base, receipts))
        except Exception as exc:  # noqa: BLE001 — one broken owner never hides the rest
            errors[family_id] = f"{type(exc).__name__}: {exc}"
            families.append(
                _family(
                    family=family_id,
                    name=family_id,
                    domain=unobserved("builder failed"),
                    owners=[],
                    artifacts=[],
                    champion=unobserved(f"builder failed: {errors[family_id]}"),
                    challengers=unobserved("builder failed"),
                    challengerStates=unobserved("builder failed"),
                    drift=unmeasured(),
                    calibration=unobserved("builder failed"),
                    lastEvaluation=unobserved("builder failed"),
                    gate=unobserved("builder failed"),
                    promotionAuthority=unobserved("builder failed"),
                    productionState=unobserved("builder failed"),
                    rollback=unobserved("builder failed"),
                    decisionReason=f"builder failed: {errors[family_id]}",
                    dataQuality=unobserved("builder failed"),
                    receipts=_family_receipts(receipts, family_id),
                )
            )
    known = {f for f, _ in FAMILY_BUILDERS}
    for family_id in sorted((receipts.get("byFamily") or {}).keys()):
        if family_id and family_id not in known:
            families.append(_unlisted_family(family_id, receipts))
    return {
        "schema": MODEL_LAB_SCHEMA,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "private": True,
        "readOnly": True,
        "labStates": list(LAB_STATES),
        "fieldVocabulary": {
            "unobserved": "the evidence exists in principle but could not be observed here",
            "not_applicable": "the field does not apply to this family",
            "unmeasured": "no monitor measures this; it is not the same as 'none'",
        },
        "receiptStore": {k: v for k, v in receipts.items() if k != "byFamily"},
        "families": families,
        "notCovered": list(NOT_COVERED),
        "builderErrors": errors,
    }


# ── brief memo (cheap endpoint) ──────────────────────────────────────────────

MEMO_TTL_SECONDS = 60.0
_memo_lock = threading.Lock()
_memo: dict[str, tuple[float, dict[str, Any]]] = {}


def cached_model_lab(
    *, ttl: float = MEMO_TTL_SECONDS, clock: Callable[[], float] = time.monotonic
) -> dict[str, Any]:
    """``build_model_lab()`` memoized for ``ttl`` seconds per process."""
    now = clock()
    with _memo_lock:
        hit = _memo.get("lab")
        if hit is not None and now - hit[0] < ttl:
            return hit[1]
    payload = build_model_lab()
    with _memo_lock:
        _memo["lab"] = (now, payload)
    return payload


def clear_memo() -> None:
    with _memo_lock:
        _memo.clear()
