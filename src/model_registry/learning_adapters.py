"""Producer adapters: existing model evidence -> learning receipts (AL-0, plan §23 item 5).

Two producers, and neither changes:

(a) **Hill** — ``src/model_registry/training_run.py`` run records / registry
    summaries, and the holdout records ``src/model_registry/holdout.py`` writes
    onto registry versions (``config/model_registry/hill_scope_masters.json``).
(b) **#1589 source quality** — ``src/source_quality/evaluate.archive_records``
    lines (``evaluations.jsonl``), optionally joined to the run's full
    ``results_<date>.json`` for per-stratum sample sizes.

Why (b) is source quality and not the #1590 robust-filter shadow ledger: the
#1589 archive is committed, complete evaluation evidence (a preregistration hash,
a code revision, a panel digest, a bootstrap interval and a gate disposition per
candidate), and its strata carry real cell counts — including one EMPTY stratum
(``inSeason``: 0 cells) that exercises ``insufficient_sample`` on real data. The
#1590 ledger lives under gitignored ``data/robust_filter_shadow/``; what is
committed of it is a one-off replay summary, so it could not round-trip as the
producer actually writes it. The #1590 store is registered in
``learning_receipt.NATIVE_STORES`` for AL-1a.

Adapter contract (A6): an adapter READS a producer's output and returns
receipts. It never writes, normalizes or re-derives the producer's output, and
it never mutates its input (pinned by deep-copy and file-hash checks). Anything
the producer did not record is an explicit ``Unobserved`` slot, never a guess.
"""

from __future__ import annotations

import hashlib
from datetime import date
from typing import Any, Mapping, Sequence

from src.model_registry.evaluation_receipt import (
    VERDICT_CHALLENGER_BETTER,
    VERDICT_CHAMPION_RETAINED,
    VERDICT_INCONCLUSIVE,
    VERDICT_INSUFFICIENT,
    CohortResult,
    Estimate,
    EvaluationReceipt,
    cohort_result,
)
from src.model_registry.feature_dictionary import FeatureDictionary, validate_manifest
from src.model_registry.learning_receipt import (
    KIND_CHALLENGER,
    KIND_FEATURES,
    KIND_MODEL,
    ROLE_ARTIFACT,
    ROLE_INPUT,
    LearningReceipt,
    NotApplicable,
    ReceiptError,
    StoreRef,
    Unobserved,
    build_receipt,
    canonical_json,
    iso,
    model_version_id,
    parse_instant,
)

# ── (a) Hill ────────────────────────────────────────────────────────────────

HILL_FAMILY = "hill_scope_masters"
HILL_PRODUCER = "hill_training_run"
HILL_REGISTRY_PRODUCER = "hill_model_registry"
HILL_POLICY = "Hill Autopilot (docs/valuation/HILL_AUTOPILOT_V2.md)"
HILL_FEATURES: tuple[Mapping[str, Any], ...] = (
    {"name": "source_board_native_value", "version": 1},
    {"name": "canonical_training_percentile", "version": 1},
    {"name": "provider_family", "version": 1},
)
_HILL_RECORD_KEYS = (
    "challengerHash",
    "modelHash",
    "pinsHash",
    "codeHash",
    "manifestHash",
    "trainingCutoff",
)


def hill_version_id_for_run(record: Mapping[str, Any]) -> str:
    return model_version_id(HILL_FAMILY, f"ch-{record['challengerHash']}")


def hill_version_id_for_registry(version: int) -> str:
    return model_version_id(HILL_FAMILY, f"v{int(version)}")


def _verify_full_record(record: Mapping[str, Any]) -> bool:
    """True for a full run record whose pins hash to its own ``pinsHash``.

    A summary (no ``inputs``) is accepted as a summary. A full record that does
    not hash to its own pins is refused: a receipt must never launder an edited
    run record into evidence."""
    if "inputs" not in record:
        return False
    from src.model_registry.training_run import pins_hash  # noqa: PLC0415 (read-only)

    if pins_hash(record) != record.get("pinsHash"):
        raise ReceiptError("training-run record does not hash to its own pinsHash")
    return True


def _snapshot_slot(record: Mapping[str, Any], cutoff) -> StoreRef | Unobserved:
    snap = record.get("snapshot") or {}
    if not snap.get("resolved"):
        return Unobserved("the run recorded no resolved board snapshot")
    key = f"{snap.get('path')}@sha256:{snap.get('sha256')}"
    if snap.get("scrapeTimestamp"):
        return StoreRef(
            store="board_snapshot",
            key=key,
            role=ROLE_INPUT,
            known_at=parse_instant(snap["scrapeTimestamp"], what="snapshot scrapeTimestamp"),
            fidelity="exact",
            basis="snapshot scrapeTimestamp pinned by training_run._snapshot_pin",
        )
    return Unobserved(
        f"snapshot {key} pinned without its scrapeTimestamp (registry summary); its instant "
        "cannot be proven here, so it is not offered as a point-in-time input"
    )


def _input_refs(record: Mapping[str, Any], cutoff) -> tuple[list[StoreRef], list[str]]:
    refs: list[StoreRef] = []
    missing: list[str] = []
    commit = record.get("inputsCommit")
    for rel, pin in sorted((record.get("inputs") or {}).items()):
        sha = pin.get("sha256")
        if not sha or sha == "missing":
            missing.append(rel)
            continue
        ds = pin.get("datasetState") or {}
        clock = ds.get("lastAnyMeaningfulChangeAt") if ds.get("measured") else None
        if clock:
            known_at = parse_instant(clock, what=f"{rel} data clock")
            basis = (
                "dataset-state lastAnyMeaningfulChangeAt (refused by the run if after the cutoff)"
            )
        elif commit and record.get("reproducible") is True:
            known_at = cutoff
            basis = f"bytes materialized at inputs commit {commit} (at or before the cutoff)"
        else:
            missing.append(rel)
            continue
        refs.append(
            StoreRef(
                store="repo_file",
                key=f"{rel}@sha256:{sha}",
                role=ROLE_INPUT,
                known_at=known_at,
                fidelity="exact",
                basis=basis,
            )
        )
    return refs, missing


def hill_receipts_from_training_run(
    record: Mapping[str, Any], *, dictionary: FeatureDictionary
) -> list[LearningReceipt]:
    """MODEL + FEATURES receipts for one Hill training run (full record or summary)."""
    absent = [k for k in _HILL_RECORD_KEYS if not record.get(k)]
    if absent:
        raise ReceiptError(f"not a Hill training-run record: missing {absent}")
    full = _verify_full_record(record)
    cutoff = parse_instant(record["trainingCutoff"], what="trainingCutoff")
    mvid = hill_version_id_for_run(record)
    challenger = str(record["challengerHash"])
    # When was the run record WRITTEN? Nothing records it: the record is
    # content-addressed (challengerHash = pins + model), ``recordedAt`` is reserved
    # in training_run._UNHASHED_FIELDS but never set, and ``trainingCutoff`` is the
    # INPUT cutoff — a lower bound on the write time, which is the unsafe direction
    # for a "known at" claim. So the write time is reported as unavailable, and the
    # ref is accepted only because it is this receipt's OWN output (producedFor =
    # the challenger hash this MODEL receipt describes; hill_training_run writes
    # the store), never because of its role label.
    run_ref = StoreRef(
        store="hill_training_run",
        key=f"challenger:{challenger}",
        role=ROLE_ARTIFACT,
        known_at=None,
        fidelity="unavailable",
        basis=(
            "the run record carries no write time (recordedAt is never set); it was written "
            "at or after trainingCutoff, which bounds its inputs, not its writing"
        ),
        produced_for=challenger,
    )
    scopes = {
        scope: {
            "promotable": (blob or {}).get("promotable"),
            "nonPromotableReasons": list((blob or {}).get("nonPromotableReasons") or []),
        }
        for scope, blob in sorted((record.get("scopes") or {}).items())
    }
    model = build_receipt(
        kind=KIND_MODEL,
        producer=HILL_PRODUCER,
        native_id=challenger,
        model_family=HILL_FAMILY,
        model_version_id=mvid,
        cutoff=cutoff,
        slots={"trainingRun": run_ref},
        body={
            "recordForm": "full" if full else "summary",
            "challengerHash": challenger,
            "modelHash": record["modelHash"],
            "pinsHash": record["pinsHash"],
            "evidenceHash": record.get("evidenceHash"),
            "codeHash": record["codeHash"],
            "codeSha": record.get("codeSha"),
            "manifestHash": record["manifestHash"],
            "substrateVersion": record.get("substrateVersion"),
            "reproducible": record.get("reproducible"),
            "inputsOrigin": record.get("inputsOrigin"),
            "inputsCommit": record.get("inputsCommit"),
            "scopes": scopes,
            "promotes": False,
        },
    )
    input_refs, missing = _input_refs(record, cutoff) if full else ([], [])
    features = build_receipt(
        kind=KIND_FEATURES,
        producer=HILL_PRODUCER,
        native_id=challenger,
        model_family=HILL_FAMILY,
        model_version_id=mvid,
        cutoff=cutoff,
        slots={
            "boardSnapshot": _snapshot_slot(record, cutoff),
            "inputs": (
                input_refs[0]
                if input_refs
                else Unobserved(
                    "per-input pins are not in a registry summary; the full artifact holds them"
                    if not full
                    else "no input was readable at the cutoff"
                )
            ),
        },
        refs=tuple(input_refs[1:]),
        body={
            "featureManifestHash": validate_manifest(
                dictionary, consumer=HILL_FAMILY, features=HILL_FEATURES
            ),
            "features": [dict(f) for f in HILL_FEATURES],
            "manifestHash": record["manifestHash"],
            "inputsContentHash": record.get("inputsContentHash"),
            "inputCount": len(input_refs) if full else None,
            "inputsNotOffered": missing,
        },
    )
    return [model, features]


def _codesha_from_producer(producer: Any) -> str | Unobserved:
    text = str(producer or "")
    if "@" in text:
        sha = text.rsplit("@", 1)[1].strip()
        if sha:
            return sha
    return Unobserved(f"registry producer {text!r} names no code revision")


def hill_receipts_from_registry_version(
    version: Mapping[str, Any], *, champion_version: int | None
) -> list[LearningReceipt]:
    """MODEL + (CHALLENGER) + EVALUATION receipts for one Hill registry version.

    The holdout score is evidence, not a gate: every Hill evaluation receipt's
    verdict is ``inconclusive``, and the registry ``status`` (set by Hill
    Autopilot or a human) is carried as the producer's own disposition."""
    n_version = int(version["version"])
    mvid = hill_version_id_for_registry(n_version)
    status = str(version.get("status"))
    fitted = version.get("fittedAt")
    try:
        fitted_at = parse_instant(fitted, what="fittedAt") if fitted else None
    except ReceiptError:
        fitted_at = None  # e.g. 'unknown' on an Autopilot composite
    # The registry entry for version n is written by the registry producer FOR
    # version n, so it is the MODEL / CHALLENGER receipts' own output (both carry
    # nativeId ``v<n>``). That — not the role label — is what lets an entry whose
    # fittedAt is unrecorded ('unknown' on an Autopilot composite) be cited.
    reg_ref = StoreRef(
        store="model_registry",
        key=f"{HILL_FAMILY}#v{n_version}",
        role=ROLE_ARTIFACT,
        known_at=fitted_at,
        fidelity="exact" if fitted_at else "unavailable",
        basis="registry fittedAt" if fitted_at else f"registry fittedAt is {fitted!r}",
        produced_for=f"v{n_version}",
    )
    receipts = [
        build_receipt(
            kind=KIND_MODEL,
            producer=HILL_REGISTRY_PRODUCER,
            native_id=f"v{n_version}",
            model_family=HILL_FAMILY,
            model_version_id=mvid,
            slots={"registryVersion": reg_ref},
            body={
                "version": n_version,
                "status": status,
                "producer": version.get("producer"),
                "trainingInputs": dict(version.get("trainingInputs") or {}),
                "promotes": False,
            },
        )
    ]
    if status in ("challenger", "rejected"):
        receipts.append(
            build_receipt(
                kind=KIND_CHALLENGER,
                producer=HILL_REGISTRY_PRODUCER,
                native_id=f"v{n_version}",
                model_family=HILL_FAMILY,
                model_version_id=mvid,
                slots={"registryVersion": reg_ref},
                body={
                    "challengerModelVersionId": mvid,
                    "championVersionAtRead": champion_version,
                    "status": status,
                    "notes": list(version.get("notes") or []),
                    "decidedBy": HILL_POLICY,
                    "promotes": False,
                },
            )
        )
    receipts.append(_hill_evaluation(version, mvid, fitted_at, champion_version, fitted))
    return receipts


def _hill_evaluation(version, mvid, fitted_at, champion_version, fitted) -> LearningReceipt:
    n_version = int(version["version"])
    ev_native_id = f"v{n_version}:holdout"
    # The holdout block of registry version n is written by the registry producer
    # at fit time FOR this evaluation, so it is the evaluation receipt's own output
    # (producedFor = this receipt's nativeId). Citing the whole version entry here
    # would be another receipt's artifact and, with fittedAt unrecorded, could not
    # be compared with any cutoff.
    holdout_ref = StoreRef(
        store="model_registry",
        key=f"{HILL_FAMILY}#v{n_version}/holdout",
        role=ROLE_ARTIFACT,
        known_at=fitted_at,
        fidelity="exact" if fitted_at else "unavailable",
        basis="registry fittedAt" if fitted_at else f"registry fittedAt is {fitted!r}",
        produced_for=ev_native_id,
    )
    holdout = version.get("holdout") or None
    cohorts: list[CohortResult] = []
    if not holdout:
        overall = cohort_result(
            {"holdoutSource": "ALL"},
            n=None,
            n_reason="this registry version carries no holdout record",
            insufficient=True,
        )
    else:
        per = holdout.get("perSource") or {}
        rows = holdout.get("perSourceRows") or {}
        skipped = holdout.get("skipped") or {}
        for src in sorted(set(holdout.get("holdoutSources") or []) | set(per) | set(skipped)):
            if src in per and isinstance(rows.get(src), int):
                cohorts.append(
                    cohort_result(
                        {"holdoutSource": src},
                        n=rows[src],
                        metrics={"rmse": Estimate(point=float(per[src]))},
                    )
                )
            else:
                cohorts.append(
                    cohort_result(
                        {"holdoutSource": src},
                        n=rows.get(src) if isinstance(rows.get(src), int) else None,
                        n_reason="holdout source skipped or unscored",
                        insufficient=True,
                        note=str(skipped.get(src) or "not scored"),
                    )
                )
        scored = [c for c in cohorts if c.status == "ok"]
        criterion = holdout.get("criterion")
        scored_ns = [c.n for c in scored]
        # Missing is never zero: one scored source of unknown size makes the total unknown.
        total_n = None if any(n is None for n in scored_ns) else sum(scored_ns)
        if scored and isinstance(criterion, (int, float)):
            overall = cohort_result(
                {"holdoutSource": "ALL"},
                n=total_n,
                n_reason=(
                    None if total_n is not None else "a scored holdout source recorded no row count"
                ),
                metrics={
                    str(holdout.get("criterionName") or "criterion"): Estimate(
                        point=float(criterion)
                    )
                },
                missing_count=len(cohorts) - len(scored),
            )
        else:
            overall = cohort_result(
                {"holdoutSource": "ALL"},
                n=0 if not scored else None,
                n_reason="no holdout source was scored",
                insufficient=True,
            )
    inputs = dict(version.get("trainingInputs") or {})
    snap = inputs.get("boardSnapshot")
    ev = EvaluationReceipt(
        producer=HILL_REGISTRY_PRODUCER,
        native_id=ev_native_id,
        model_family=HILL_FAMILY,
        model_version_id=mvid,
        role="champion" if champion_version == n_version else "challenger",
        champion_model_version_id=(
            hill_version_id_for_registry(champion_version) if champion_version is not None else None
        ),
        task="hill_curve_generalization",
        target=str(
            (holdout or {}).get("criterionUnits")
            or "holdout board values on the 0-9999 scale (lower RMSE is better)"
        ),
        horizon="cross_sectional_same_snapshot",
        cohort_keys=("holdoutSource",),
        cutoff=fitted_at,
        point_in_time_rule=(
            "holdout boards are read from the same snapshot the fit used; families on both sides "
            "of the split are excluded by the training manifest (training_manifest rule 3)"
        ),
        feature_manifest_hash=Unobserved(
            "registry versions written before AL-0 carry no per-run feature manifest"
        ),
        input_pins={
            "codeSha": _codesha_from_producer(version.get("producer")),
            "sourceHashes": inputs or Unobserved("no training-input fingerprints recorded"),
            "snapshotHash": snap or Unobserved("no board snapshot fingerprint recorded"),
            "scoringFingerprint": NotApplicable(
                "Hill masters price dynasty market percentiles; league scoring is a serve-time step"
            ),
        },
        prediction_set=Unobserved(
            "per-row holdout predictions are not persisted by src/model_registry/holdout.py"
        ),
        outcome_set=Unobserved(
            "holdout boards are scored at fit time; their fingerprints are not recorded in the registry"
        ),
        preregistration=Unobserved(
            "the holdout criterion is fixed in code (src/model_registry/holdout.py); no "
            "preregistration document exists for Hill holdouts"
        ),
        overall=overall,
        cohorts=cohorts,
        holdout_design=("source_family",),
        proposed_verdict=VERDICT_INCONCLUSIVE,
        verdict_basis=(
            "a holdout score is not a gate; the promotion decision is the registry status set by "
            f"{HILL_POLICY}, recorded here as the producer disposition"
        ),
        family_policy=HILL_POLICY,
        refs=(holdout_ref,),
        extra={
            "producerDisposition": str(version.get("status")),
            "uncertainty": "not computed by src/model_registry/holdout.py",
            "semantics": dict((holdout or {}).get("_semantics") or {}),
        },
    )
    return ev.to_learning_receipt()


# ── (b) #1589 source quality ────────────────────────────────────────────────

SQ_FAMILY = "source_quality_weights"
SQ_PRODUCER = "source_quality_eval"
SQ_SCHEMA = "source-quality-eval/v1"
SQ_POLICY = "Batch 3 section N (docs/EXECUTION_PLAN.md section 0, Valuation Trust Program)"
SQ_CHAMPION = model_version_id(SQ_FAMILY, "equal_family_c0")
SQ_FEATURES: tuple[Mapping[str, Any], ...] = (
    {"name": "source_universe_log_rank", "version": 1},
    {"name": "family_evidence_age_days", "version": 1},
    {"name": "provider_family", "version": 1},
)

#: The producer's fixed disposition vocabulary (``evaluate.gates``) -> ours.
#: Anything else is refused, never guessed.
SQ_DISPOSITION_TO_VERDICT: Mapping[str, str] = {
    "DOES_NOT_MEET_PREREGISTERED_GATE": VERDICT_CHAMPION_RETAINED,
    "MEETS_PREREGISTERED_GATE": VERDICT_CHALLENGER_BETTER,
    "INSUFFICIENT_EVIDENCE": VERDICT_INCONCLUSIVE,
    "NOT_RUN": VERDICT_INSUFFICIENT,
}


def _day_end(day: str):
    from src.source_quality.panel import day_end  # noqa: PLC0415 (the panel's own rule)

    return day_end(date.fromisoformat(str(day)))


def _estimate(blob: Any, label: str) -> Estimate | None:
    if not isinstance(blob, Mapping) or not isinstance(blob.get("point"), (int, float)):
        return None
    ci = blob.get("ci90")
    if isinstance(ci, (list, tuple)) and len(ci) == 2 and None not in ci:
        return Estimate(
            point=float(blob["point"]),
            interval=(float(ci[0]), float(ci[1])),
            level=0.90,
            method=f"seeded date-block bootstrap ({blob.get('blocks')} blocks x {blob.get('boot')} draws)",
        )
    return Estimate(point=float(blob["point"]))


def _metrics(blob: Mapping[str, Any]) -> dict[str, Estimate]:
    out = {}
    for key in ("deltaMALE", "championMALE"):
        est = _estimate(blob.get(key), key)
        if est is not None:
            out[key] = est
    return out


def _sq_cohorts(
    results: Mapping[str, Any], candidate: str
) -> tuple[CohortResult, list[CohortResult]]:
    gate = (results.get("gates") or {}).get(candidate) or {}
    strata = gate.get("strata") or {}
    built: dict[str, CohortResult] = {}
    for name, e in strata.items():
        cells = e.get("cells")
        n = cells if isinstance(cells, int) and not isinstance(cells, bool) else None
        metrics = _metrics(e)
        if e.get("status") == "ok" and metrics and n:
            built[name] = cohort_result({"stratum": name}, n=n, metrics=metrics)
        else:
            built[name] = cohort_result(
                {"stratum": name},
                n=n,
                n_reason=None if n is not None else "producer recorded no cell count",
                insufficient=True,
                note=f"producer stratum status {e.get('status')!r}, {e.get('blocks')} blocks",
            )
    if "ALL" not in built:
        overall = cohort_result(
            {"stratum": "ALL"},
            n=None,
            n_reason="producer recorded no ALL stratum",
            insufficient=True,
        )
    else:
        overall = built.pop("ALL")
    return overall, [built[k] for k in sorted(built)]


def source_quality_receipts(
    line: Mapping[str, Any],
    *,
    archive_key: str,
    dictionary: FeatureDictionary,
    results: Mapping[str, Any] | None = None,
    results_key: str | None = None,
) -> list[LearningReceipt]:
    """MODEL + CHALLENGER + EVALUATION receipts for one #1589 archive line."""
    if line.get("schema") != SQ_SCHEMA:
        raise ReceiptError(f"not a {SQ_SCHEMA} archive line: schema={line.get('schema')!r}")
    candidate = str(line.get("candidate") or "")
    disposition = str(line.get("disposition") or "")
    if disposition not in SQ_DISPOSITION_TO_VERDICT:
        raise ReceiptError(f"unmapped source-quality disposition {disposition!r}")
    window = line.get("dataWindow") or []
    if len(window) != 2:
        raise ReceiptError("archive line carries no two-date dataWindow")
    cutoff = _day_end(window[1])
    evaluated_at = parse_instant(line.get("evaluatedAt"), what="evaluatedAt")
    if evaluated_at < cutoff:
        raise ReceiptError("an evaluation cannot be recorded before its own data window ends")
    panel = str(line.get("panelDigest") or "")
    code = str(line.get("codeRevision") or "")
    prereg = str(line.get("preregistrationSha256") or "")
    if not (panel and code and prereg and candidate):
        raise ReceiptError(
            "archive line lacks panelDigest / codeRevision / preregistration / candidate"
        )
    weights_hash = hashlib.sha256(canonical_json(line.get("finalWeights")).encode()).hexdigest()[
        :16
    ]
    mvid = model_version_id(SQ_FAMILY, f"{candidate}-{weights_hash}")

    pins = (results or {}).get("pins") or {}
    if results is not None:
        if (
            pins.get("panelDigest") != panel
            or pins.get("codeRevision") != code
            or results.get("generatedAt") != line.get("evaluatedAt")
            or (pins.get("preregistration") or {}).get("sha256") != prereg
        ):
            raise ReceiptError("results file does not belong to this archive line")
        overall, cohorts = _sq_cohorts(results, candidate)
    else:
        overall = cohort_result(
            {"stratum": "ALL"},
            n=None,
            n_reason="the archive line records bootstrap blocks, not the cell count; join the run's results file for n",
            metrics=_metrics(
                {"deltaMALE": line.get("deltaMALE"), "championMALE": line.get("championMALE")}
            ),
        )
        cohorts = []

    # The evaluation run's own identity. The archive line and the results file
    # are THIS run's output, written at evaluatedAt (after the window cutoff), so
    # they name the run via producedFor — the only way a post-cutoff artifact is
    # accepted (learning_receipt.is_own_artifact).
    eval_native_id = f"{panel}|{code}|{line.get('evaluatedAt')}|{candidate}"
    archive_ref = StoreRef(
        store="source_quality_evaluations",
        key=f"{archive_key}#{candidate}@{line.get('evaluatedAt')}",
        role=ROLE_ARTIFACT,
        known_at=evaluated_at,
        fidelity="exact",
        basis="the producer's evaluatedAt",
        produced_for=eval_native_id,
    )
    panel_ref = StoreRef(
        store="source_quality_panel",
        key=f"panel:{panel}",
        role=ROLE_INPUT,
        known_at=cutoff,
        fidelity="exact",
        basis="ObservationPanel.truncated keeps only versions known at or before the window end",
    )
    refs: list[StoreRef] = [archive_ref, panel_ref]
    if results is not None and results_key:
        refs.append(
            StoreRef(
                store="source_quality_results",
                key=results_key,
                role=ROLE_ARTIFACT,
                known_at=evaluated_at,
                fidelity="exact",
                basis="the producer's generatedAt",
                produced_for=eval_native_id,
            )
        )
    prereg_pin = pins.get("preregistration") or {}
    # The preregistration is NOT this run's output (no producer writes that store),
    # so as an artifact it would have to carry a proven knownAt and pass the
    # point-in-time guard. The producer pins its sha256 and commit sha but not the
    # commit TIME, and an adapter does not shell out to invent one. So it is
    # reported unobserved, with the pin carried verbatim in extra.preregistrationPin
    # — never as an artifact with an unprovable instant.
    preregistration = Unobserved(
        "the producer pins the preregistration sha256 (and commit sha) but not its commit "
        "time; without a provable instant it cannot pass the point-in-time guard as an "
        "artifact (pin: extra.preregistrationPin)"
    )
    preregistration_pin = {
        "sha256": prereg,
        "path": prereg_pin.get("path"),
        "commit": prereg_pin.get("commit"),
    }
    source_hashes: dict[str, Any] = {"panelDigest": panel}
    if pins.get("census"):
        source_hashes["census"] = pins["census"].get("sha256")
    if pins.get("lineage"):
        source_hashes["lineage"] = pins["lineage"].get("sha256")
    impact = pins.get("impactPayload") or {}

    ev = EvaluationReceipt(
        producer=SQ_PRODUCER,
        native_id=eval_native_id,
        model_family=SQ_FAMILY,
        model_version_id=mvid,
        role="challenger",
        champion_model_version_id=SQ_CHAMPION,
        task="source_authority_weighting",
        target=(
            "leave-the-evaluated-family-out future market movement; MALE = mean absolute log "
            "error, deltaMALE = champion error minus candidate error (> 0: candidate better)"
        ),
        horizon=f"{line.get('horizonDays')}d",
        cohort_keys=("stratum",),
        cutoff=cutoff,
        point_in_time_rule=(
            "walk-forward over the point-in-time panel: a source version is selectable at t only "
            "when its git committer time is at or before t (src/source_quality/panel.py)"
        ),
        feature_manifest_hash=validate_manifest(
            dictionary, consumer=SQ_FAMILY, features=SQ_FEATURES
        ),
        input_pins={
            "codeSha": code,
            "sourceHashes": source_hashes,
            "snapshotHash": (
                impact.get("sha256")
                if impact.get("sha256")
                else Unobserved(
                    "the archive line does not pin the impact payload; the results file does"
                )
            ),
            "scoringFingerprint": NotApplicable(
                "dynasty market source evidence is scoring-independent; no league scoring enters"
            ),
        },
        prediction_set=Unobserved(
            "walk-forward predictions are not persisted; they are reproducible from panelDigest + codeRevision"
        ),
        outcome_set=Unobserved(
            "future-movement targets are formed inside the walk-forward from later panel versions; "
            "per-origin target ordering is enforced by src.source_quality.evaluate.walk_forward and "
            "is not re-checkable from the archive"
        ),
        preregistration=preregistration,
        overall=overall,
        cohorts=cohorts,
        holdout_design=("chronological", "source_family"),
        proposed_verdict=SQ_DISPOSITION_TO_VERDICT[disposition],
        verdict_basis=f"producer disposition {disposition} under preregistration {prereg[:12]}",
        family_policy=SQ_POLICY,
        refs=tuple(refs),
        extra={
            "producerDisposition": disposition,
            "producerStatus": line.get("status"),
            "failedGates": list(line.get("failed") or []),
            "missingEvidence": list(line.get("missingEvidence") or []),
            "dataWindow": list(window),
            "finalWeightsHash": weights_hash,
            "preregistrationPin": preregistration_pin,
        },
    )
    # The archive line is the EVALUATION run's output (producedFor names that run),
    # not the MODEL's or the CHALLENGER's, so on those receipts it is held to a
    # cutoff like any other artifact. Their cutoff is evaluatedAt: the weights and
    # the challenger designation come into existence in the run that writes the
    # archive, so nothing these receipts assert is known before it. The data
    # window the weights were fitted on travels in body.dataWindow.
    model = build_receipt(
        kind=KIND_MODEL,
        producer=SQ_PRODUCER,
        native_id=mvid,
        model_family=SQ_FAMILY,
        model_version_id=mvid,
        cutoff=evaluated_at,
        slots={"evaluationArchive": archive_ref},
        body={
            "dataWindow": list(window),
            "candidate": candidate,
            "finalWeightsHash": weights_hash,
            "codeRevision": code,
            "status": line.get("status"),
            "promotes": False,
        },
    )
    challenger = build_receipt(
        kind=KIND_CHALLENGER,
        producer=SQ_PRODUCER,
        native_id=f"{mvid}|vs|{SQ_CHAMPION}",
        model_family=SQ_FAMILY,
        model_version_id=mvid,
        cutoff=evaluated_at,
        slots={"evaluationArchive": archive_ref},
        body={
            "challengerModelVersionId": mvid,
            "championModelVersionId": SQ_CHAMPION,
            "status": line.get("status"),
            "decidedBy": SQ_POLICY,
            "promotes": False,
        },
    )
    return [model, challenger, ev.to_learning_receipt()]


def describe(receipts: Sequence[LearningReceipt]) -> list[dict[str, Any]]:
    """Compact, deterministic summary (kind, id, content hash) for evidence notes."""
    return [
        {
            "kind": r.kind,
            "receiptId": r.receipt_id,
            "contentHash": r.content_hash(),
            "cutoff": iso(r.cutoff),
        }
        for r in receipts
    ]
