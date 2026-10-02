"""Prospective learning receipts for the shadow and evaluation producers (AL-1a).

AL-0 (``learning_receipt`` / ``evaluation_receipt`` / ``receipt_store``) built the
substrate and adapted committed evidence. AL-1a makes the producers that run on
the box emit receipts AS THEY RUN, in the owner order of
``docs/research/ADAPTIVE_LEARNING_2026-09-26.md`` §35 T2:

1. **sparse-evidence shadow** (``src/api/sparse_evidence_shadow.py``, the
   ``dynasty-sparse-evidence-shadow`` timer) — per board: OBSERVATION, FEATURES,
   a MODEL for the served incumbent and for candidate C, the CHALLENGER pairing,
   and one PREDICTION per side. It settles no outcome, so it emits no OUTCOME or
   EVALUATION receipt.
2. **robust-filter shadow** (``src/robust_filter_shadow/``, the
   ``dynasty-joint-filter-shadow`` timer) — the same per-board set, plus an
   EVALUATION receipt per preregistered evaluation run, because that producer
   already settles outcomes (``outcomes.evaluate``) with its own sample sizes and
   an ``INSUFFICIENT`` verdict.
3. **source-quality evaluator** (``scripts/source_quality_eval.py``) — the
   AL-0 adapter (``learning_adapters.source_quality_receipts``) called at the
   moment the evaluator appends its archive lines.
4. **Hill refits** (``scripts/hill_learning_receipts.py``, run by ``deploy/deploy.sh``
   after the code lands) -- MODEL (+ CHALLENGER) per registry entry, MODEL +
   FEATURES per training run, one OBSERVATION per Autopilot adjudication, read from
   the COMMITTED ``config/model_registry/`` evidence through the AL-0 Hill adapters.
   The refit itself runs on a CI runner with no persistent store and commits no
   receipt. No Hill holdout EVALUATION: it is retrospective (section 4 below).

Rules this module keeps (pinned by ``tests/model_registry/test_producer_receipts.py``):

* **Point into the producer's own store, copy nothing.** Every receipt
  references its producer's native ledger line, panel or evaluation file by key
  (``producedFor`` = that run's native id). No row, value or vote is copied.
* **Point in time.** A per-board receipt's ``cutoff`` is the producer record's
  own ``recordedAt`` — stamped after the build that read its inputs, so every
  input was known by then. A board whose ``scrapeTimestamp`` cannot be proven at
  or before that instant is reported ``Unobserved``, never offered as an input.
* **Missing stays missing.** Absent pins become ``Unobserved`` slots with a
  reason; nothing is defaulted to 0.
* **Idempotent.** Every receipt identity is a function of the producer's own
  record key / model version / evaluated record set, and every body is a pure
  function of the stored record, so a re-run on an unchanged board is a stored
  duplicate, never a second receipt and never a conflict. Callers pass the line
  AS STORED (a recorder that finds its key already present returns a freshly
  stamped copy, which must not be used).
* **Never breaks a producer.** :func:`emit_safely` is the only entry point the
  producers call. Any failure — an adapter refusing a malformed record, an
  unreachable store, a path the store refuses — is logged and swallowed; the
  producer's exit code and outputs are unchanged.
* **Never promotes.** Every MODEL / CHALLENGER / EVALUATION body carries
  ``promotes: False``; nothing here writes a PROMOTION RECORD, moves a champion
  pointer, flips a flag or touches a served value.
* **Prospective only.** The AL-0 receipt contract has no retrospective marker:
  every receipt it accepts reads as a point-in-time, forward-looking record. A
  hindsight replay (the robust-filter ``historical_replay`` mode: archived inputs
  rebuilt through today's code) therefore yields NO receipt -- the builders here
  refuse a non-live record or evaluation rather than invent a marker the
  contract does not define. Replays stay in the producer's own ledger, labelled.
* **Unknown is not zero.** A producer block the record does not carry (counts,
  evidence states, safeguards, voting families, ...) is published as an
  ``unobserved`` state with a reason, never as ``{}`` / ``[]`` / 0. Only inside a
  PRESENT block may an absent key read as zero, because the producer builds that
  block with ``collections.Counter`` (:data:`COUNTS_SEMANTICS`).
"""

from __future__ import annotations

import hashlib
import logging
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

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
from src.history.asof import FIDELITY_NEAREST_PRIOR
from src.model_registry.feature_dictionary import FeatureDictionary, validate_manifest
from src.model_registry.learning_receipt import (
    KIND_CHALLENGER,
    KIND_FEATURES,
    KIND_MODEL,
    KIND_OBSERVATION,
    KIND_PREDICTION,
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
    prediction_id,
)

# ── shared ──────────────────────────────────────────────────────────────────

BATCH3_POLICY = "Batch 3 section N (docs/EXECUTION_PLAN.md section 0, Valuation Trust Program)"

PROVIDER_FAMILY_V2: Mapping[str, Any] = {"name": "provider_family", "version": 2}

#: The shadow producers count with ``collections.Counter`` and publish
#: ``dict(counter)`` (``robust_filter_shadow.record.shadow_record``,
#: ``api.sparse_evidence_shadow.shadow_rows`` / ``assemble_record``): inside a
#: block the producer DID write, a key it never incremented is ABSENT, and that
#: absence means zero occurrences. The block is carried verbatim with this note
#: rather than re-keyed. A block the record does not carry at all is a different
#: statement -- unknown -- and is published as ``unobserved`` (:func:`_counter_block`),
#: never as ``{}``.
COUNTS_SEMANTICS = (
    "verbatim producer collections.Counter block: within this PRESENT block an absent "
    "key counted zero occurrences (a missing block is published as unobserved, never zero)"
)

#: The one switch that lets a box-canonical run write receipts
#: (:func:`receipts_enabled`). Fail closed: unset, or any value but ``"1"``, is off.
RECEIPTS_ENABLED_ENV = "RISKIT_RECEIPTS_ENABLED"

_LOGGER = logging.getLogger(__name__)

_NO_REGISTRY = (
    "no model registry exists for this shadow family; the version is identified by the "
    "code revision, pipeline identity and flag snapshot recorded on every run, and the "
    "per-run pins travel on that run's FEATURES and PREDICTION receipts"
)


def receipts_enabled() -> bool:
    """True only when the operator explicitly enabled receipts for this run.

    For producers whose runs are canonical only on the box (the source-quality
    evaluator, run by hand): a run anywhere else writes no receipt."""
    return os.environ.get(RECEIPTS_ENABLED_ENV, "").strip() == "1"


def _missing(what: str, value: Any) -> dict[str, Any]:
    state = "absent" if value is None else f"not a block ({type(value).__name__})"
    return Unobserved(
        f"the producer record carries no {what} ({state}); unknown, never zero or empty"
    ).to_dict()


def _mapping_block(value: Any, what: str) -> dict[str, Any]:
    """A producer mapping verbatim, or ``unobserved`` when the record lacks it."""
    return dict(value) if isinstance(value, Mapping) else _missing(what, value)


def _carried(container: Any, key: str, what: str) -> Any:
    """A producer field verbatim (an explicit ``None`` included -- that is the
    producer's own statement), or ``unobserved`` when the container or key is absent."""
    if not isinstance(container, Mapping):
        return _missing(what, None)
    if key not in container:
        return _missing(what, None)
    value = container[key]
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, (list, tuple)):
        return list(value)
    return value


def _counter_block(value: Any, what: str) -> dict[str, Any]:
    """A producer ``Counter`` block plus its absent-key semantics -- only when present."""
    if isinstance(value, Mapping):
        return {"counts": dict(value), "semantics": COUNTS_SEMANTICS}
    return _missing(what, value)


def _sha(obj: Any) -> str:
    return hashlib.sha256(canonical_json(obj).encode("utf-8")).hexdigest()


def _instant_or_none(value: Any) -> datetime | None:
    try:
        return parse_instant(value, what="instant")
    except (ReceiptError, ValueError):
        return None


def _require(value: Any, what: str) -> str:
    text = str(value or "").strip()
    if not text or text == "None":
        raise ReceiptError(f"producer record lacks {what}")
    return text


def _board_slot(board: Mapping[str, Any], cutoff: datetime) -> StoreRef | Unobserved:
    """The served payload the run read, by content address, at its OWN scrape time."""
    payload = str(board.get("payloadSha256") or "")
    source = str(board.get("source") or "")
    if not payload or payload == "None" or not source:
        return Unobserved("the producer record names no payload hash / source")
    scraped = _instant_or_none(board.get("scrapeTimestamp"))
    if scraped is None:
        return Unobserved(
            f"payload {source} states no provable scrapeTimestamp "
            f"({board.get('scrapeTimestamp')!r}); its instant cannot be proven to precede the run"
        )
    if scraped > cutoff:
        return Unobserved(
            f"payload {source} scrapeTimestamp {iso(scraped)} is after the run's recordedAt "
            f"{iso(cutoff)}; it is not offered as a point-in-time input"
        )
    return StoreRef(
        store="repo_file",
        key=f"{source}@sha256:{payload}",
        role=ROLE_INPUT,
        known_at=scraped,
        fidelity="exact",
        basis="the board's own scrapeTimestamp; the run read the payload before recordedAt",
    )


def _tree_state_token(dirty: Any) -> str:
    """A dirty tree's content is not determined by its revision; an unknown state is named
    as unknown rather than assumed clean."""
    if dirty is False:
        return ""
    return "-dirty" if dirty is True else "-treeunknown"


def _flags_token(flags: Any) -> str:
    """``fmissing`` when the record carries no flag snapshot (unknown); ``fnone`` for a
    PRESENT empty snapshot (a real statement: no flags). ``fnone`` keeps its historical
    spelling so no identity minted from present data changes."""
    if not isinstance(flags, Mapping):
        return "fmissing"
    if not flags:
        return "fnone"
    return "f" + _sha(dict(flags))[:8]


def _model_receipt(
    *, producer: str, family: str, mvid: str, body: Mapping[str, Any]
) -> LearningReceipt:
    return build_receipt(
        kind=KIND_MODEL,
        producer=producer,
        native_id=mvid,
        model_family=family,
        model_version_id=mvid,
        slots={"definition": NotApplicable(_NO_REGISTRY)},
        body={**dict(body), "promotes": False},
    )


def _challenger_receipt(
    *, producer: str, family: str, challenger: str, champion: str, body: Mapping[str, Any]
) -> LearningReceipt:
    return build_receipt(
        kind=KIND_CHALLENGER,
        producer=producer,
        native_id=f"{challenger}|vs|{champion}",
        model_family=family,
        model_version_id=challenger,
        slots={"definition": NotApplicable(_NO_REGISTRY)},
        body={
            "challengerModelVersionId": challenger,
            "championModelVersionId": champion,
            "status": "SHADOW",
            "decidedBy": BATCH3_POLICY,
            **dict(body),
            "promotes": False,
        },
    )


def _prediction_receipt(
    *,
    producer: str,
    family: str,
    store: str,
    ledger_key: str,
    native: str,
    mvid: str,
    cutoff: datetime,
    body: Mapping[str, Any],
) -> LearningReceipt:
    return build_receipt(
        kind=KIND_PREDICTION,
        producer=producer,
        native_id=native,
        model_family=family,
        model_version_id=mvid,
        prediction_id=prediction_id(producer, native),
        cutoff=cutoff,
        slots={
            "predictionSet": StoreRef(
                store=store,
                key=ledger_key,
                role=ROLE_ARTIFACT,
                known_at=cutoff,
                fidelity="exact",
                basis="the ledger line's own recordedAt; the line is appended right after it",
                produced_for=native,
            )
        },
        body=dict(body),
    )


# ── emission (never breaks a producer) ───────────────────────────────────────


def emit_safely(
    build: Callable[[], Iterable[LearningReceipt]],
    *,
    label: str,
    path: Path | None = None,
    log: Callable[[str], None] = print,
) -> dict[str, Any]:
    """Build receipts and append them; NEVER raise.

    Returns ``{"ok": bool, ...}``: the store's ``written`` / ``duplicates`` /
    ``contentConflicts`` / ``rejected`` on success, ``error`` on failure. The
    producer ignores the result — a receipt failure is a log line, not a
    producer failure, and the producer's own outputs are already durable by the
    time this runs."""
    try:
        # Lazy (and re-read per call): an import error is isolated like any other.
        from src.model_registry.receipt_store import append_receipts  # noqa: PLC0415

        receipts = list(build())
        result = append_receipts(receipts, path=path)
    except Exception as exc:  # noqa: BLE001 -- a receipt failure must never break a producer
        message = f"{type(exc).__name__}: {exc}"
        # An unwritable / unreachable store (permissions, a read-only mount, a
        # locked database) is named as such: it is the failure an operator can fix.
        cause = (
            "the receipt store is unwritable or unreachable"
            if isinstance(exc, (OSError, sqlite3.Error))
            else "the receipts could not be built or stored"
        )
        warning = f"WARNING: learning receipts NOT written ({label}): {cause}: {message}"
        _LOGGER.warning(warning)
        log(f"{warning} receipt_failures=1")
        return {"ok": False, "error": message, "cause": cause, "receiptFailures": 1}
    summary = (
        f"learning receipts ({label}): written={result['written']} "
        f"duplicates={result['duplicates']} conflicts={len(result['contentConflicts'])} "
        f"rejected={len(result['rejected'])}"
    )
    if result["contentConflicts"] or result["rejected"]:
        _LOGGER.warning(summary)
        summary = f"WARNING: {summary}"
    log(summary)
    return {"ok": True, **result, "receiptFailures": 0}


# ── 1. sparse-evidence shadow ────────────────────────────────────────────────

SPARSE_FAMILY = "sparse_evidence_estimator"
SPARSE_PRODUCER = "sparse_evidence_shadow"
SPARSE_STORE = "sparse_evidence_shadow_ledger"
SPARSE_SCHEMA = "sparse-evidence-shadow/v1"
SPARSE_FLAG = "sparse_evidence_estimator"
SPARSE_PREREGISTRATION = "docs/valuation/evidence/sparse-evidence-2026-10-01/PREREGISTRATION.md"
SPARSE_FEATURES: tuple[Mapping[str, Any], ...] = (
    {"name": "single_family_observation", "version": 1},
    {"name": "censored_family_bound", "version": 1},
    {"name": "sparse_evidence_state", "version": 1},
    PROVIDER_FAMILY_V2,
)


def sparse_model_ids(record: Mapping[str, Any]) -> tuple[str, str]:
    """``(incumbent, challenger)`` model version ids for one shadow record.

    The incumbent is the served pipeline at the record's code revision and flag
    snapshot with the estimator flag OFF; the challenger is the same with it ON
    under the recorded estimator version. A dirty working tree is named in the
    token, because its content is not determined by the revision."""
    pins = record.get("pins") or {}
    code = _require(pins.get("codeRevision"), "pins.codeRevision")[:12]
    estimator = _require(
        pins.get("estimator") or (record.get("identity") or {}).get("estimator"),
        "the estimator version",
    )
    dirty = _tree_state_token(pins.get("workingTreeDirty"))
    flags = _flags_token(pins.get("flagsAtRecord"))
    return (
        model_version_id(SPARSE_FAMILY, f"served-{code}{dirty}-{flags}"),
        model_version_id(SPARSE_FAMILY, f"{estimator}-{code}{dirty}-{flags}"),
    )


def sparse_evidence_receipts(
    record: Mapping[str, Any], *, ledger_name: str, dictionary: FeatureDictionary
) -> list[LearningReceipt]:
    """The prospective receipts for one STORED sparse-evidence shadow line.

    ``ledger_name`` is the file the line lives in (``ledger-YYYY-MM.jsonl``)."""
    if record.get("schema") != SPARSE_SCHEMA:
        raise ReceiptError(f"not a {SPARSE_SCHEMA} line: schema={record.get('schema')!r}")
    key = _require(record.get("key"), "key")
    cutoff = parse_instant(record.get("recordedAt"), what="recordedAt")
    board, pins = record.get("board") or {}, record.get("pins") or {}
    inc, ch = sparse_model_ids(record)
    code = _require(pins.get("codeRevision"), "pins.codeRevision")
    estimator = str(pins.get("estimator") or (record.get("identity") or {}).get("estimator"))
    inputs_sha = str(pins.get("inputsSha256") or "")
    # The recorder hashes its inputs (``value_replay.pins``) AFTER both builds have
    # read them (``api/sparse_evidence_shadow.py::record_board``); moving the hash
    # would change the record key even with no race. So the pin is the observation
    # nearest the read, before recordedAt -- never claimed as the bytes read.
    inputs: StoreRef | Unobserved = (
        StoreRef(
            store="repo_file",
            key=(
                f"sparse-evidence-shadow live inputs (source CSVs, freshness state, config, "
                f"fetch stamps, league snapshots)@sha256:{inputs_sha}"
            ),
            role=ROLE_INPUT,
            known_at=cutoff,
            fidelity=FIDELITY_NEAREST_PRIOR,
            basis=(
                "this box's source CSVs, dataset state, freshness config and league snapshots, "
                "hashed after the builds read their inputs and before recordedAt; a write "
                "between read and hash is invisible, so this is not a proven pin of the bytes "
                "read"
            ),
        )
        if inputs_sha and inputs_sha != "None"
        else Unobserved("the record pins no inputsSha256")
    )
    flags = pins.get("flagsAtRecord")
    flags_hash = _sha(dict(flags)) if isinstance(flags, Mapping) else None

    model_common = {
        "codeRevision": code,
        "workingTreeDirty": pins.get("workingTreeDirty"),
        "flagsAtRecordSha256": flags_hash,
        "flag": SPARSE_FLAG,
    }
    receipts = [
        _model_receipt(
            producer=SPARSE_PRODUCER,
            family=SPARSE_FAMILY,
            mvid=inc,
            body={
                **model_common,
                "role": "incumbent",
                "flagValue": False,
                "singleSourceRetention": pins.get("singleSourceRetention"),
                "status": "SERVED_AT_RECORD",
            },
        ),
        _model_receipt(
            producer=SPARSE_PRODUCER,
            family=SPARSE_FAMILY,
            mvid=ch,
            body={
                **model_common,
                "role": "challenger",
                "flagValue": True,
                "estimator": estimator,
                "status": "SHADOW",
            },
        ),
        _challenger_receipt(
            producer=SPARSE_PRODUCER,
            family=SPARSE_FAMILY,
            challenger=ch,
            champion=inc,
            body={"flag": SPARSE_FLAG, "preregistration": SPARSE_PREREGISTRATION},
        ),
    ]
    observation = build_receipt(
        kind=KIND_OBSERVATION,
        producer=SPARSE_PRODUCER,
        native_id=key,
        model_family=SPARSE_FAMILY,
        model_version_id=None,
        cutoff=cutoff,
        slots={"board": _board_slot(board, cutoff), "inputs": inputs},
        body={
            "payloadSha256": board.get("payloadSha256"),
            "source": board.get("source"),
            "scrapeTimestamp": board.get("scrapeTimestamp"),
            "payloadAgeHours": board.get("payloadAgeHours"),
            "staleBudgetHours": board.get("staleBudgetHours"),
        },
    )
    features = build_receipt(
        kind=KIND_FEATURES,
        producer=SPARSE_PRODUCER,
        native_id=key,
        model_family=SPARSE_FAMILY,
        model_version_id=ch,
        cutoff=cutoff,
        slots={"inputs": inputs},
        body={
            "featureManifestHash": validate_manifest(
                dictionary, consumer=SPARSE_FAMILY, features=SPARSE_FEATURES
            ),
            "features": [dict(f) for f in SPARSE_FEATURES],
            "codeRevision": code,
            "workingTreeDirty": pins.get("workingTreeDirty"),
            "flagsAtRecordSha256": flags_hash,
            "estimator": estimator,
        },
    )
    receipts += [observation, features]
    chain = {
        "observationReceiptId": observation.receipt_id,
        "featuresReceiptId": features.receipt_id,
        "challengerReceiptId": receipts[2].receipt_id,
    }
    model_ids = {"incumbent": receipts[0].receipt_id, "challenger": receipts[1].receipt_id}
    for side, mvid, board_hash in (
        ("incumbent", inc, board.get("boardHashIncumbent")),
        ("challenger", ch, board.get("boardHashChallenger")),
    ):
        native = f"{key}|{side}"
        receipts.append(
            _prediction_receipt(
                producer=SPARSE_PRODUCER,
                family=SPARSE_FAMILY,
                store=SPARSE_STORE,
                ledger_key=f"{ledger_name}#{key}/{side}",
                native=native,
                mvid=mvid,
                cutoff=cutoff,
                body={
                    "side": side,
                    "target": (
                        "the published value of every single-family row the estimator scoped "
                        "on this board; to be judged against later boards"
                    ),
                    "horizon": "not declared by the producer; no outcome is settled yet",
                    "outcomeSettled": False,
                    "boardHash": board_hash,
                    "producerCounts": _counter_block(record.get("counts"), "counts block"),
                    "evidenceStates": _counter_block(
                        record.get("evidenceStates"), "evidenceStates block"
                    ),
                    "modelReceiptId": model_ids[side],
                    **chain,
                },
            )
        )
    return receipts


# ── 2. robust-filter shadow ──────────────────────────────────────────────────

ROBUST_FAMILY = "joint_robust_filter"
ROBUST_PRODUCER = "robust_filter_shadow"
ROBUST_STORE = "robust_filter_shadow_ledger"
ROBUST_SCHEMA = "joint-filter-shadow/v1"
#: The only robust-filter mode that is a forward-looking run (``record.MODE_LIVE``;
#: a test pins the two equal). ``historical_replay`` rebuilds archived inputs
#: through today's code, i.e. with hindsight, and is never receipted.
ROBUST_LIVE_MODE = "live_shadow"
ROBUST_PREREGISTRATION = "docs/valuation/evidence/joint-filter-shadow-2026-10-01/PREREGISTRATION.md"
ROBUST_FEATURES: tuple[Mapping[str, Any], ...] = (
    {"name": "source_board_scale_vote", "version": 1},
    {"name": "precap_evidence_weight", "version": 1},
    PROVIDER_FAMILY_V2,
)

#: The producer's fixed verdict vocabulary (``outcomes.VERDICT_*``) -> ours.
#: Anything else is refused, never guessed.
ROBUST_VERDICT_TO_VERDICT: Mapping[str, str] = {
    "PROMOTION_ELIGIBLE_PENDING_INDEPENDENT_REVIEW": VERDICT_CHALLENGER_BETTER,
    "NOT_BETTER": VERDICT_CHAMPION_RETAINED,
    "INCONCLUSIVE": VERDICT_INCONCLUSIVE,
    "INSUFFICIENT": VERDICT_INSUFFICIENT,
}

_SIDES = {"K": "rescued", "X": "rejected", "R": "agreed"}


def robust_model_ids(record: Mapping[str, Any]) -> tuple[str, str]:
    """``(incumbent Hampel, challenger joint filter)`` model version ids."""
    pins = record.get("pins") or {}
    code = _require(pins.get("codeRevision"), "pins.codeRevision")[:12]
    fp = _require(pins.get("pipelineFingerprint"), "pins.pipelineFingerprint")[:12]
    version = _require(pins.get("challengerVersion"), "pins.challengerVersion")
    dirty = _tree_state_token(pins.get("workingTreeDirty"))
    flags = _flags_token(pins.get("flagsAtRecord"))
    return (
        model_version_id(ROBUST_FAMILY, f"hampel-{code}-{fp}{dirty}-{flags}"),
        model_version_id(ROBUST_FAMILY, f"{version}-{code}-{fp}{dirty}-{flags}"),
    )


def _require_live(mode: Any, what: str) -> None:
    if mode != ROBUST_LIVE_MODE:
        raise ReceiptError(
            f"{what} is mode {mode!r}, not {ROBUST_LIVE_MODE!r}: a hindsight replay is never "
            "receipted, because the AL-0 receipt contract has no retrospective marker and "
            "every receipt it holds reads as prospective"
        )


def _robust_model_receipts(record: Mapping[str, Any]) -> tuple[LearningReceipt, LearningReceipt]:
    """``(incumbent, challenger)`` MODEL receipts named by one ledger line's pins."""
    pins = record.get("pins") or {}
    inc, ch = robust_model_ids(record)
    flags = pins.get("flagsAtRecord")
    model_common = {
        "codeRevision": pins.get("codeRevision"),
        "pipelineFingerprint": pins.get("pipelineFingerprint"),
        "workingTreeDirty": pins.get("workingTreeDirty"),
        "flagsAtRecordSha256": _sha(dict(flags)) if isinstance(flags, Mapping) else None,
        "hampel": _mapping_block(pins.get("hampel"), "pins.hampel block"),
        "familyCap": pins.get("familyCap"),
    }
    variants = pins.get("variants")
    variants = variants if isinstance(variants, Mapping) else {}
    return (
        _model_receipt(
            producer=ROBUST_PRODUCER,
            family=ROBUST_FAMILY,
            mvid=inc,
            body={
                **model_common,
                "role": "incumbent",
                "variantFlags": _mapping_block(
                    variants.get("incumbent"), "pins.variants.incumbent block"
                ),
                "status": "SERVED_AT_RECORD",
            },
        ),
        _model_receipt(
            producer=ROBUST_PRODUCER,
            family=ROBUST_FAMILY,
            mvid=ch,
            body={
                **model_common,
                "role": "challenger",
                "challengerVersion": pins.get("challengerVersion"),
                "variantFlags": _mapping_block(
                    variants.get("challenger"), "pins.variants.challenger block"
                ),
                "status": "SHADOW",
            },
        ),
    )


def robust_filter_receipts(
    record: Mapping[str, Any], *, ledger_name: str, dictionary: FeatureDictionary
) -> list[LearningReceipt]:
    """The prospective receipts for one STORED robust-filter shadow ledger line.

    Only a ``live_shadow`` line is receipted (:func:`_require_live`)."""
    if record.get("schema") != ROBUST_SCHEMA:
        raise ReceiptError(f"not a {ROBUST_SCHEMA} line: schema={record.get('schema')!r}")
    _require_live(record.get("mode"), "the ledger line")
    key = _require(record.get("key"), "key")
    cutoff = parse_instant(record.get("recordedAt"), what="recordedAt")
    board, pins = record.get("board") or {}, record.get("pins") or {}
    inc, ch = robust_model_ids(record)
    flags = pins.get("flagsAtRecord")
    flags_hash = _sha(dict(flags)) if isinstance(flags, Mapping) else None
    receipts = [
        *_robust_model_receipts(record),
        _challenger_receipt(
            producer=ROBUST_PRODUCER,
            family=ROBUST_FAMILY,
            challenger=ch,
            champion=inc,
            body={"preregistration": ROBUST_PREREGISTRATION},
        ),
    ]

    def _tree(store: str, pin: str, glob: str, what: str) -> StoreRef | Unobserved:
        digest = str(pins.get(pin) or "")
        if not digest or digest == "None":
            return Unobserved(f"{glob} was absent at record time (the record pins {pin} None)")
        # The recorder hashes the tree BEFORE the build re-reads its files
        # (scripts/joint_filter_shadow.py::cmd_record); moving the hash would
        # change the ledger's own pins. A write landing between the hash and the
        # read is not excluded, so the pin is the tree state observed nearest
        # before the read -- not proven to be the bytes the build read.
        return StoreRef(
            store=store,
            key=f"{glob}@tree-sha256:{digest}",
            role=ROLE_INPUT,
            known_at=cutoff,
            fidelity=FIDELITY_NEAREST_PRIOR,
            basis=(
                f"{what} hashed immediately before the build re-read it, before recordedAt; a "
                "write between that hash and the read is not excluded, so this is the nearest "
                "prior observation of the tree, not a proven pin of the bytes read"
            ),
        )

    observation = build_receipt(
        kind=KIND_OBSERVATION,
        producer=ROBUST_PRODUCER,
        native_id=key,
        model_family=ROBUST_FAMILY,
        model_version_id=None,
        cutoff=cutoff,
        slots={
            "board": _board_slot(board, cutoff),
            "sourceCsvTree": _tree(
                "repo_file", "csvTreeSha256", "CSVs/site_raw/*.csv", "the source CSV tree"
            ),
            "datasetStateTree": _tree(
                "dataset_state",
                "stateTreeSha256",
                "data/scrape_state/*_dataset.json",
                "the dataset-state tree",
            ),
        },
        body={
            "mode": record.get("mode"),
            "label": record.get("label"),
            "payloadSha256": board.get("payloadSha256"),
            "source": board.get("source"),
            "scrapeTimestamp": board.get("scrapeTimestamp"),
            "completeness": board.get("completeness"),
            "votingSourceCount": (
                len(board["votingSources"])
                if isinstance(board.get("votingSources"), list)
                else _missing("board.votingSources list", board.get("votingSources"))
            ),
            "votingFamilies": (
                list(board["votingFamilies"])
                if isinstance(board.get("votingFamilies"), list)
                else _missing("board.votingFamilies list", board.get("votingFamilies"))
            ),
        },
    )
    panel = str(record.get("panel") or "")
    features = build_receipt(
        kind=KIND_FEATURES,
        producer=ROBUST_PRODUCER,
        native_id=key,
        model_family=ROBUST_FAMILY,
        model_version_id=ch,
        cutoff=cutoff,
        slots={
            "observationPanel": (
                StoreRef(
                    store=ROBUST_STORE,
                    key=panel,
                    role=ROLE_INPUT,
                    known_at=cutoff,
                    fidelity="exact",
                    basis=(
                        "the pre-filter votes computed by the build that finished before "
                        "recordedAt; persisted write-once under their full input identity"
                    ),
                )
                if panel and panel != "None"
                else Unobserved("the record names no observation panel")
            ),
        },
        body={
            "featureManifestHash": validate_manifest(
                dictionary, consumer=ROBUST_FAMILY, features=ROBUST_FEATURES
            ),
            "features": [dict(f) for f in ROBUST_FEATURES],
            "codeRevision": pins.get("codeRevision"),
            "pipelineFingerprint": pins.get("pipelineFingerprint"),
            "workingTreeDirty": pins.get("workingTreeDirty"),
            "flagsAtRecordSha256": flags_hash,
        },
    )
    receipts += [observation, features]
    chain = {
        "observationReceiptId": observation.receipt_id,
        "featuresReceiptId": features.receipt_id,
        "challengerReceiptId": receipts[2].receipt_id,
    }
    model_ids = {"incumbent": receipts[0].receipt_id, "challenger": receipts[1].receipt_id}
    shared = {
        "mode": record.get("mode"),
        "target": (
            "each filter's keep/drop decision per voting observation and the resulting "
            "published values on this board; judged later against leave-family-out consensus "
            "on later boards (the preregistered evaluation)"
        ),
        "outcomeSettled": False,
        "producerCounts": _counter_block(record.get("counts"), "counts block"),
        **chain,
    }
    for side, mvid, board_hash, extra in (
        (
            "incumbent",
            inc,
            board.get("boardHashIncumbent"),
            {"dropsCountKey": "incumbentDrops"},
        ),
        (
            "challenger",
            ch,
            board.get("boardHashChallenger"),
            {
                "dropsCountKey": "challengerDrops",
                "safeguardsFired": _counter_block(
                    record.get("safeguardsFired"), "safeguardsFired block"
                ),
                "topChurnVsIncumbent": _mapping_block(record.get("topChurn"), "topChurn block"),
            },
        ),
    ):
        native = f"{key}|{side}"
        receipts.append(
            _prediction_receipt(
                producer=ROBUST_PRODUCER,
                family=ROBUST_FAMILY,
                store=ROBUST_STORE,
                ledger_key=f"{ledger_name}#{key}/{side}",
                native=native,
                mvid=mvid,
                cutoff=cutoff,
                body={
                    "side": side,
                    "boardHash": board_hash,
                    "modelReceiptId": model_ids[side],
                    **extra,
                    **shared,
                },
            )
        )
    return receipts


def _estimate(ci: Any) -> Estimate | None:
    if not isinstance(ci, Mapping):
        return None
    point = ci.get("point")
    if isinstance(point, bool) or not isinstance(point, (int, float)):
        return None
    lo, hi = ci.get("lo95"), ci.get("hi95")
    if isinstance(lo, (int, float)) and isinstance(hi, (int, float)) and lo <= hi:
        return Estimate(
            point=float(point),
            interval=(float(lo), float(hi)),
            level=0.95,
            method=(
                f"date-block bootstrap ({ci.get('blocks')} blocks, "
                f"{ci.get('resamplesUsed')} resamples used)"
            ),
        )
    return Estimate(point=float(point))


def _n(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _side_cohort(horizon: str, side: str, blob: Mapping[str, Any]) -> CohortResult:
    n = _n(blob.get("n"))
    est = _estimate(blob.get("meanLeadShare"))
    cohort = {"horizonDays": horizon, "side": f"{side}_{_SIDES[side]}"}
    if n is None:
        return cohort_result(
            cohort, n=None, n_reason="producer recorded no side count", insufficient=True
        )
    if n == 0 or est is None:
        return cohort_result(
            cohort, n=n, insufficient=True, note="no observations or no defined lead share"
        )
    return cohort_result(cohort, n=n, metrics={"meanLeadShare": est})


def _delta_cohort(horizon: str, summary: Mapping[str, Any]) -> CohortResult:
    sides = summary.get("sides") or {}
    ns = [_n((sides.get(s) or {}).get("n")) for s in ("K", "X")]
    n = None if any(v is None for v in ns) else sum(v for v in ns if v is not None)
    cohort = {"horizonDays": horizon, "side": "K_minus_X"}
    est = _estimate(summary.get("delta"))
    if n is None:
        return cohort_result(
            cohort, n=None, n_reason="a judged side recorded no count", insufficient=True
        )
    if n == 0 or est is None:
        return cohort_result(cohort, n=n, insufficient=True, note="delta undefined")
    return cohort_result(cohort, n=n, metrics={"deltaLeadShare": est})


def evaluator_revision_token(revision: str, *, dirty: bool | None, tree_digest: str | None) -> str:
    """The evaluator's code identity: its revision, plus a dirty tree's content.

    A dirty tree's code is not determined by its revision, so it is keyed by a
    digest of its uncommitted state: re-evaluating on the SAME dirty tree is a
    duplicate, on a different one a distinct receipt -- never a content conflict.
    An unknown tree state is refused rather than assumed clean."""
    revision = _require(revision, "the evaluator code revision")
    if dirty is None:
        raise ReceiptError("the evaluator tree state is unknown; it cannot be assumed clean")
    if not dirty:
        return revision
    return f"{revision}-dirty-{_require(tree_digest, 'the dirty evaluator tree digest')[:16]}"


def robust_evaluation_receipts(
    evaluation: Mapping[str, Any],
    records: Sequence[Mapping[str, Any]],
    **kwargs: Any,
) -> list[LearningReceipt]:
    """The EVALUATION receipt plus a MODEL receipt for every real model version it
    names, so no model id it references is an orphan. The record runs emit the
    same MODEL receipts, so a re-emission is a stored duplicate."""
    evaluation_receipt = robust_evaluation_receipt(evaluation, records, **kwargs)
    models: dict[str, LearningReceipt] = {}
    for record in sorted(records, key=lambda r: str(r.get("key"))):
        for model in _robust_model_receipts(record):
            models.setdefault(model.receipt_id, model)
    return [*models.values(), evaluation_receipt]


def robust_evaluation_receipt(
    evaluation: Mapping[str, Any],
    records: Sequence[Mapping[str, Any]],
    *,
    evaluation_name: str,
    evaluator_revision: str,
    evaluator_tree_dirty: bool | None,
    dictionary: FeatureDictionary,
    evaluator_tree_digest: str | None = None,
    ledger_name: str = "ledger.jsonl",
    preregistration_sha256: str | None = None,
) -> LearningReceipt:
    """One EVALUATION receipt for one preregistered LIVE evaluation run.

    ``records`` are the STORED ledger lines the evaluation read. The receipt's
    identity is (mode, evaluator code identity, the evaluated record set), and its
    body excludes the evaluation's ``computedAt`` wall clock, so re-evaluating an
    unchanged ledger under unchanged code is a duplicate, not a new receipt.

    Refused for a ``historical_replay`` evaluation, or one over any non-live line:
    its ``cutoff`` (the newest ``recordedAt``) would present a hindsight replay as a
    forward-looking evaluation with a chronological holdout, and the AL-0 contract
    has no retrospective marker to say otherwise."""
    if evaluation.get("schema") != f"{ROBUST_SCHEMA}/evaluation":
        raise ReceiptError(f"not a {ROBUST_SCHEMA}/evaluation: {evaluation.get('schema')!r}")
    if not records:
        raise ReceiptError("an evaluation with no evaluated records has nothing to receipt")
    mode = _require(evaluation.get("mode"), "mode")
    _require_live(mode, "the evaluation")
    for r in records:
        _require_live(r.get("mode"), f"evaluated ledger line {r.get('key')!r}")
    revision = evaluator_revision_token(
        evaluator_revision, dirty=evaluator_tree_dirty, tree_digest=evaluator_tree_digest
    )
    keys = sorted(_require(r.get("key"), "a record key") for r in records)
    digest = _sha(keys)
    recorded = [parse_instant(r.get("recordedAt"), what="record recordedAt") for r in records]
    cutoff = max(recorded)
    native = f"{mode}|{revision}|{digest}"
    ids = sorted({robust_model_ids(r) for r in records})
    mixed: dict[str, Any] | None = None
    if len(ids) == 1:
        champion, challenger = ids[0]
    else:
        champion = model_version_id(ROBUST_FAMILY, f"hampel-mixed-{digest[:12]}")
        challenger = model_version_id(ROBUST_FAMILY, f"joint-mixed-{digest[:12]}")
        mixed = {
            "championModelVersionId": champion,
            "challengerModelVersionId": challenger,
            "modelReceipt": Unobserved(
                f"a synthetic aggregate id over the {len(ids)} model-version pairs this "
                "evaluation pooled; no MODEL receipt exists or is emitted for it. Each real "
                "version in modelVersionsEvaluated has its own MODEL receipt"
            ).to_dict(),
        }

    primary = evaluation.get("primary") or {}
    decision = primary.get("decision")
    horizons = primary.get("horizons") or {}
    cohorts: list[CohortResult] = []
    for h in sorted(horizons, key=lambda x: int(x) if str(x).isdigit() else 10**6):
        summary = horizons[h] or {}
        for side in ("K", "X", "R"):
            cohorts.append(_side_cohort(str(h), side, (summary.get("sides") or {}).get(side) or {}))
        cohorts.append(_delta_cohort(str(h), summary))
    primary_summary = horizons.get("7")
    if primary_summary is None or decision is None:
        overall = cohort_result(
            {"horizonDays": "7", "side": "K_minus_X"},
            n=None,
            n_reason="the evaluation produced no primary-horizon result",
            insufficient=True,
        )
        producer_verdict = None
        verdict = VERDICT_INSUFFICIENT
    else:
        overall = _delta_cohort("7", primary_summary)
        producer_verdict = decision.get("verdict")
        if producer_verdict not in ROBUST_VERDICT_TO_VERDICT:
            raise ReceiptError(f"unmapped robust-filter verdict {producer_verdict!r}")
        verdict = ROBUST_VERDICT_TO_VERDICT[producer_verdict]

    ledger_ref = StoreRef(
        store=ROBUST_STORE,
        key=f"{ledger_name}#{mode}:records={len(keys)}:keys-sha256={digest}",
        role=ROLE_INPUT,
        known_at=cutoff,
        fidelity="exact",
        basis="the newest recordedAt among the evaluated ledger lines",
    )
    evaluation_ref = StoreRef(
        store=ROBUST_STORE,
        key=f"{evaluation_name}#{native}",
        role=ROLE_ARTIFACT,
        known_at=None,
        fidelity="unavailable",
        basis=(
            "the evaluation file is rewritten on every run; its computedAt is deliberately not "
            "part of this receipt, whose identity is the evaluated record set"
        ),
        produced_for=native,
    )
    fingerprints = sorted({str((r.get("pins") or {}).get("pipelineFingerprint")) for r in records})
    ev = EvaluationReceipt(
        producer=ROBUST_PRODUCER,
        native_id=native,
        model_family=ROBUST_FAMILY,
        model_version_id=challenger,
        role="challenger",
        champion_model_version_id=champion,
        task="robust_outlier_filtering",
        target=(
            "lead share: how far later leave-the-family-out equal-family consensus moved toward "
            "an observation each filter judged; delta = rescued minus rejected (> 0: the "
            "challenger kept the evidence the market later followed)"
        ),
        horizon="7d primary; 3d / 14d / 21d secondary",
        cohort_keys=("horizonDays", "side"),
        cutoff=cutoff,
        point_in_time_rule=(
            "each origin board is scored against the first board at least h days later in the "
            "same ledger (outcomes.target_day); targets exclude the judged family; boards are "
            "paired only within one pipeline fingerprint"
        ),
        feature_manifest_hash=validate_manifest(
            dictionary, consumer=ROBUST_FAMILY, features=ROBUST_FEATURES
        ),
        input_pins={
            "codeSha": revision,
            "sourceHashes": {
                "ledgerRecordKeysSha256": digest,
                "pipelineFingerprints": fingerprints,
            },
            "snapshotHash": Unobserved(
                "one observation panel per board; each ledger line names its own panel"
            ),
            "scoringFingerprint": NotApplicable(
                "dynasty market source evidence is scoring-independent; no league scoring enters"
            ),
        },
        prediction_set=ledger_ref,
        outcome_set=Unobserved(
            "outcomes are later boards' panels in the same ledger, formed inside the evaluation "
            "(outcomes.outcomes_at_horizon); per-observation targets are not persisted"
        ),
        preregistration=Unobserved(
            "the producer names its preregistration path but pins neither its hash nor its "
            "commit time; without a provable instant it cannot pass the point-in-time guard "
            "(pin: extra.preregistrationPin)"
        ),
        overall=overall,
        cohorts=cohorts,
        holdout_design=("chronological", "source_family"),
        proposed_verdict=verdict,
        verdict_basis=(
            f"producer verdict {producer_verdict} under {ROBUST_PREREGISTRATION}"
            if producer_verdict
            else "the evaluation produced no decision"
        ),
        family_policy=BATCH3_POLICY,
        refs=(evaluation_ref,),
        extra={
            "producerVerdict": producer_verdict,
            # A missing decision / field is unobserved, never "no reasons" or "{}":
            # "INSUFFICIENT with no reasons" and "no decision at all" must not read alike.
            "reasons": _carried(decision, "reasons", "decision.reasons"),
            "minimumSample": _carried(decision, "minimumSample", "decision.minimumSample"),
            "accumulation": _carried(decision, "accumulation", "decision.accumulation"),
            "boards": _carried(primary, "boards", "primary.boards"),
            "originDays": _carried(primary, "originDays", "primary.originDays"),
            "span": _carried(primary, "span", "primary.span"),
            "recordCodeRevisions": _carried(evaluation, "codeRevisions", "codeRevisions"),
            "modelVersionsEvaluated": [list(pair) for pair in ids],
            **({"mixedModelVersionIds": mixed} if mixed is not None else {}),
            "evaluatorRevision": _require(evaluator_revision, "the evaluator code revision"),
            "evaluatorTreeDirty": evaluator_tree_dirty,
            "preregistrationPin": {
                "path": evaluation.get("preregistration") or ROBUST_PREREGISTRATION,
                "sha256": preregistration_sha256,
            },
        },
    )
    return ev.to_learning_receipt()


# ── 3. source-quality evaluator ──────────────────────────────────────────────


def source_quality_run_receipts(
    lines: Sequence[Mapping[str, Any]],
    *,
    archive_key: str,
    results: Mapping[str, Any],
    results_key: str,
    dictionary: FeatureDictionary,
) -> list[LearningReceipt]:
    """MODEL + CHALLENGER + EVALUATION per candidate, for the lines this run appended.

    Delegates to the AL-0 adapter (``learning_adapters.source_quality_receipts``);
    there is one source-quality adapter, and this only calls it at run time."""
    from src.model_registry.learning_adapters import source_quality_receipts  # noqa: PLC0415

    out: list[LearningReceipt] = []
    for line in lines:
        out += source_quality_receipts(
            line,
            archive_key=archive_key,
            dictionary=dictionary,
            results=results,
            results_key=results_key,
        )
    return out


# ── 4. Hill refits: registry, training runs, Autopilot adjudications ─────────
#
# The refit workflow runs on a CI runner with no persistent ``data/learning/``,
# and CI must never commit receipts. What it DOES commit is the evidence:
# ``config/model_registry/hill_scope_masters.json`` (every challenger, verdict
# and promotion), ``config/model_registry/training_runs/<challengerHash>.json``
# (the full pinned run record) and ``config/model_registry/hill_autopilot_runs.jsonl``
# (one adjudication per refit). Those arrive on the box by deploy, and
# ``scripts/hill_learning_receipts.py`` -- run by ``deploy/deploy.sh`` after the
# code lands -- turns them into receipts here, through the AL-0 Hill adapters.
#
# Identity is the producer's own id plus a CONTENT revision. A registry entry is
# not immutable (``challenger`` -> ``rejected``, notes appended, ``promotedAt``
# set), so an id alone would make the next deploy's receipt a content CONFLICT.
# Each receipt therefore carries ``revision = sha256:<16 hex>`` of the canonical
# JSON of exactly what its body is derived from: the same content is a stored
# duplicate on every later run, a changed entry is a NEW receipt beside the old
# one. No correction links the two: a disposition change is a new state of the
# entry, not an error in the earlier receipt, and the store never infers an
# order no correction records. Canonical JSON, not the git blob: a Windows
# checkout rewrites the JSON files to CRLF, and the registry file's blob moves on
# every refit even for the ~170 entries that did not change.
#
# What is NOT receipted, deliberately:
#
# * **Hill holdout EVALUATION.** ``src/model_registry/holdout.py`` scores a
#   challenger on boards read from the SAME snapshot the fit used, so the
#   evaluation window ends before the fit: it is retrospective. The AL-0 receipt
#   contract has no retrospective marker -- every EVALUATION it holds reads as a
#   prospective record -- so, as with the robust-filter ``historical_replay``
#   (``_require_live``), none is emitted. The holdout numbers stay in the
#   registry, which every MODEL receipt points at.
# * **Autopilot forward-persistence evidence.** It re-scores fixed parameters on
#   later boards at adjudication time, overlapping run to run, and no prediction
#   was recorded before those boards existed. It stays on the adjudication's
#   source line (addressed by ``sourceRecord``), never an EVALUATION.
# * **PROMOTION RECORD.** An Autopilot adjudication (READY / HOLD /
#   ``AUTO_PROMOTION_BLOCKED``) answers plan section 19.1's PROMOTION RECORD
#   question, but AL-0 refuses that kind (A5). It is carried as an OBSERVATION of
#   what the producer had established at ``evaluatedAt``, labelled as such.

HILL_AUTOPILOT_PRODUCER = "hill_autopilot"
HILL_AUTOPILOT_RUN_LOG = "config/model_registry/hill_autopilot_runs.jsonl"

HILL_EVALUATION_WITHHELD = (
    "Hill holdout evaluations are scored on the fit's own snapshot (src/model_registry/holdout.py), "
    "so the window ends before the fit: retrospective. The AL-0 contract has no retrospective "
    "marker, so no EVALUATION receipt is emitted; the holdout stays in the registry entry the "
    "MODEL receipt points at"
)

_ADJUDICATION_KIND_NOTE = (
    "plan section 19.1 files an adjudication under PROMOTION RECORD; AL-0 refuses that kind (A5), "
    "so the producer's recorded adjudication is an OBSERVATION of what it had established at "
    "evaluatedAt. It promotes nothing and records no promotion"
)


def content_revision(obj: Any) -> str:
    """``sha256:<16 hex>`` of the canonical JSON of what a receipt is derived from."""
    return "sha256:" + _sha(obj)[:16]


def _revised(receipt: LearningReceipt, revision: str) -> LearningReceipt:
    """The same receipt under a content revision, validated again."""
    from dataclasses import replace  # noqa: PLC0415

    from src.model_registry.learning_receipt import validate_receipt  # noqa: PLC0415

    return validate_receipt(replace(receipt, revision=revision))


def hill_registry_version_receipts(
    version: Mapping[str, Any], *, champion_version: int | None
) -> list[LearningReceipt]:
    """MODEL (+ CHALLENGER for a challenger / rejected entry) for one registry entry.

    Delegates to the AL-0 adapter (``learning_adapters.hill_receipts_from_registry_version``)
    with the retrospective holdout EVALUATION withheld (:data:`HILL_EVALUATION_WITHHELD`).
    The revision covers the entry and the champion pointer, the only inputs of the bodies."""
    from src.model_registry.learning_adapters import (  # noqa: PLC0415
        hill_receipts_from_registry_version,
    )

    revision = content_revision({"registryVersion": version, "championVersion": champion_version})
    return [
        _revised(r, revision)
        for r in hill_receipts_from_registry_version(
            version, champion_version=champion_version, include_evaluation=False
        )
    ]


def hill_training_run_receipts(
    record: Mapping[str, Any], *, dictionary: FeatureDictionary
) -> list[LearningReceipt]:
    """MODEL + FEATURES for one training run: the full artifact record when it is
    present and verified, else the registry summary (``recordForm`` says which).

    Delegates to ``learning_adapters.hill_receipts_from_training_run``. The full and
    summary forms of one run are different content and so different revisions: an
    artifact pruned after 30 days adds a summary receipt, never a conflict."""
    from src.model_registry.learning_adapters import (  # noqa: PLC0415
        hill_receipts_from_training_run,
    )

    revision = content_revision(dict(record))
    return [
        _revised(r, revision)
        for r in hill_receipts_from_training_run(record, dictionary=dictionary)
    ]


def _registry_input(
    version: Mapping[str, Any] | None, n: Any, cutoff: datetime, role: str
) -> StoreRef | Unobserved | NotApplicable:
    if not isinstance(n, int) or isinstance(n, bool):
        return NotApplicable(f"the adjudication names no {role} version")
    if version is None:
        return Unobserved(f"{role} v{n} is not in the registry this run read")
    fitted = _instant_or_none(version.get("fittedAt"))
    if fitted is None:
        return Unobserved(
            f"{role} v{n} fittedAt is {version.get('fittedAt')!r}; its instant cannot be "
            "proven to precede the adjudication"
        )
    if fitted > cutoff:
        return Unobserved(
            f"{role} v{n} fittedAt {iso(fitted)} is after evaluatedAt {iso(cutoff)}; "
            "not offered as an input"
        )
    from src.model_registry.learning_adapters import HILL_FAMILY  # noqa: PLC0415

    return StoreRef(
        store="model_registry",
        key=f"{HILL_FAMILY}#v{n}/params",
        role=ROLE_INPUT,
        known_at=fitted,
        fidelity="exact",
        basis=(
            "registry fittedAt: the version's parameters exist from this instant; later "
            "disposition fields of the entry are not part of this reference"
        ),
    )


def _version_number(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def hill_autopilot_run_receipt(
    line: Mapping[str, Any],
    *,
    versions_by_number: Mapping[int, Mapping[str, Any]],
) -> LearningReceipt:
    """One OBSERVATION per committed Autopilot adjudication line.

    ``cutoff`` = the line's ``evaluatedAt`` (stamped after ``decide()``); the inputs
    are the champion and winner registry entries, offered only when their
    ``fittedAt`` is provably at or before it. The outcome, gates and
    independent-validation block are carried verbatim; a line written before a
    field existed publishes it ``unobserved`` (never ``passed``, never zero)."""
    from src.model_registry.learning_adapters import (  # noqa: PLC0415
        HILL_FAMILY,
        hill_version_id_for_registry,
    )

    if not isinstance(line, Mapping):
        raise ReceiptError("an Autopilot run-log line must be a JSON object")
    evaluated = parse_instant(line.get("evaluatedAt"), what="autopilot evaluatedAt")
    champion_n = _version_number(line.get("championVersion"))
    winner_n = _version_number(line.get("winnerVersion"))
    receipt = build_receipt(
        kind=KIND_OBSERVATION,
        producer=HILL_AUTOPILOT_PRODUCER,
        native_id=f"run@{iso(evaluated)}",
        model_family=HILL_FAMILY,
        model_version_id=hill_version_id_for_registry(winner_n) if winner_n is not None else None,
        cutoff=evaluated,
        slots={
            "champion": _registry_input(
                versions_by_number.get(champion_n) if champion_n is not None else None,
                line.get("championVersion"),
                evaluated,
                "champion",
            ),
            "winner": _registry_input(
                versions_by_number.get(winner_n) if winner_n is not None else None,
                line.get("winnerVersion"),
                evaluated,
                "winner",
            ),
        },
        body={
            "observes": "hill_autopilot_adjudication",
            "kindNote": _ADJUDICATION_KIND_NOTE,
            "sourceRecord": {
                "store": "repo_file",
                "path": HILL_AUTOPILOT_RUN_LOG,
                "lineSha256": _sha(dict(line)),
            },
            "evaluatedAt": iso(evaluated),
            "triggerSha": _carried(line, "triggerSha", "trigger SHA"),
            "championVersion": _carried(line, "championVersion", "champion version"),
            "championModelVersionId": (
                hill_version_id_for_registry(champion_n) if champion_n is not None else None
            ),
            "winnerVersion": _carried(line, "winnerVersion", "winner version"),
            "outcome": _carried(line, "outcome", "adjudication outcome"),
            "ready": _carried(line, "ready", "readiness"),
            "reason": _carried(line, "reason", "reason"),
            "gates": _carried(line, "gates", "gate results"),
            "safePromotionScope": _carried(line, "safePromotionScope", "safe promotion scope"),
            "requiredImprovement": _carried(line, "requiredImprovement", "required improvement"),
            "currentImprovement": _carried(line, "currentImprovement", "current improvement"),
            "independentValidation": _carried(
                line,
                "independentValidation",
                "independent-validation block (gate 7, owner decision 1 of 2026-10-01; "
                "earlier lines predate it, so it is neither passed nor not required)",
            ),
            "promotionApplied": Unobserved(
                "the run log records the adjudication, not whether the workflow's promote step "
                "applied it; the champion's registry MODEL receipt carries promotedAt / appliedAt"
            ).to_dict(),
            "promotes": False,
            "isPromotionRecord": False,
        },
    )
    return _revised(receipt, content_revision(dict(line)))
