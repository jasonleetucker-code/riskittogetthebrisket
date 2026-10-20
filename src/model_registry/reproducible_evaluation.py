"""Reproducible model-evaluation receipts — the evidence a generic promotion gate reads.

Why this module exists (chaseTradeMarket P5 / gap G11)
──────────────────────────────────────────────────────
``evaluation_receipt.EvaluationReceipt`` already carries the four AL-0 input pins
(``codeSha``, ``sourceHashes``, ``snapshotHash``, ``scoringFingerprint``), and each
may be an explicit ``unobserved`` / ``not_applicable``. That is right for a
RETROSPECTIVE adapter that must describe evidence honestly as it finds it. It is
not enough for a PROMOTION: a version promoted on an evaluation whose code
revision was ``unobserved`` cannot be reproduced, and the master plan §3.5 rule —
pinned inputs and provenance for every model experiment: code SHA, source hashes,
board/snapshot hash, model version, scoring config, timestamp — is then a
description rather than a guarantee.

This module adds the stricter, promotable form without forking the receipt:

* :class:`EvaluationProvenance` — the exact pins of ONE evaluation run, validated
  at construction: a 40-hex git commit and a clean tree, a sha256 per named input,
  a sha256 snapshot hash, the ``mv:<family>:<token>`` model version, the
  evaluation instant (timezone-aware) and the scoring fingerprint or an explicit
  ``not_applicable`` with a reason.
* :func:`reproducible_evaluation_receipt` — builds the ordinary AL-0 EVALUATION
  receipt with those pins and the provenance carried verbatim in the body, so the
  receipt's ``contentHash`` is a function of every pin.
* :func:`evaluation_record` — the compact block stored on ``ModelVersion.holdout``:
  the criterion, ``measuredAt`` (= the provenance instant, never the wall clock at
  serialisation) and the receipt identity + content hash.
* :func:`verify_evaluation_record` — the check the generic promotion gate runs:
  the receipt presented IS the one the registry recorded (content hash), it
  evaluates THIS version against THIS champion, its verdict says the challenger
  was better, its holdout design covers what the family requires, and every
  required pin is a concrete value.

Determinism (A10): nothing here reads a clock. The same pins and results build a
byte-identical receipt; changing any pin changes its ``contentHash``.

A receipt still PROMOTES NOTHING (A5). The gate reads it; the decision to promote
is the family policy's (``promotion_gates``), and for ``chase_trade_market`` that
policy additionally requires an explicit owner approval and never lifts the
source's vote hold.
"""

from __future__ import annotations

import math
import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from src.model_registry.evaluation_receipt import (
    PIN_KEYS,
    VERDICT_CHALLENGER_BETTER,
    EvaluationReceipt,
)
from src.model_registry.learning_receipt import (
    KIND_EVALUATION,
    LearningReceipt,
    NotApplicable,
    ReceiptError,
    iso,
)

REPO = Path(__file__).resolve().parents[2]

#: A full git commit id. A short SHA is refused: it is a label, not an identity,
#: and it collides as the history grows.
CODE_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
#: A content hash: bare 64-hex or ``sha256:``-prefixed.
SHA256_RE = re.compile(r"^(?:sha256:)?[0-9a-f]{64}$")
#: ``mv:<family>:<token>`` (``learning_receipt.model_version_id``).
MODEL_VERSION_ID_RE = re.compile(r"^mv:[^:\s]+:[^:\s]+$")

PROVENANCE_SCHEMA = "reproducible-evaluation/v1"


def _require_sha256(value: Any, what: str) -> str:
    text = str(value or "").strip()
    if not SHA256_RE.match(text):
        raise ReceiptError(f"{what} must be a sha256 content hash, not {value!r}")
    return text


def _require_aware(value: Any, what: str) -> datetime:
    if not isinstance(value, datetime):
        raise ReceiptError(f"{what} must be a datetime, not {value!r}")
    if value.tzinfo is None:
        raise ReceiptError(f"{what} is naive; an evaluation instant must carry a zone")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class EvaluationProvenance:
    """Every pin of one evaluation run. Invalid pins refuse at construction."""

    code_sha: str
    code_tree_clean: bool
    input_hashes: Mapping[str, str]
    snapshot_hash: str
    model_version_id: str
    evaluated_at: datetime
    scoring_fingerprint: str | NotApplicable
    #: Optional runtime identity that can move a fit (e.g. numpy/scipy/BLAS
    #: versions — the preregistration pins them). Strings only; never a guess.
    environment: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not CODE_SHA_RE.match(str(self.code_sha or "")):
            raise ReceiptError(
                f"codeSha must be a full 40-hex git commit, not {self.code_sha!r}; "
                "a short or 'unknown' revision cannot be reproduced"
            )
        if not isinstance(self.code_tree_clean, bool):
            raise ReceiptError("codeTreeClean must be a bool (true only for a clean tree)")
        if not isinstance(self.input_hashes, Mapping) or not self.input_hashes:
            raise ReceiptError(
                "inputHashes must name at least one input; an evaluation that read nothing "
                "is not an evaluation, and an unnamed input cannot be re-fetched"
            )
        for label, digest in self.input_hashes.items():
            if not str(label or "").strip():
                raise ReceiptError("every input hash needs a non-empty label")
            _require_sha256(digest, f"input hash {label!r}")
        _require_sha256(self.snapshot_hash, "snapshotHash")
        if not MODEL_VERSION_ID_RE.match(str(self.model_version_id or "")):
            raise ReceiptError(
                f"modelVersionId must be 'mv:<family>:<token>', not {self.model_version_id!r}"
            )
        _require_aware(self.evaluated_at, "evaluatedAt")
        fp = self.scoring_fingerprint
        if isinstance(fp, NotApplicable):
            if not str(fp.reason or "").strip():
                raise ReceiptError("a not_applicable scoring fingerprint must say why")
        elif not str(fp or "").strip():
            raise ReceiptError(
                "scoringFingerprint must be a value or an explicit NotApplicable(reason)"
            )
        for k, v in self.environment.items():
            if not isinstance(k, str) or not isinstance(v, str) or not v.strip():
                raise ReceiptError(f"environment entries are non-empty strings: {k!r}={v!r}")

    @property
    def model_family(self) -> str:
        return self.model_version_id.split(":")[1]

    def input_pins(self) -> dict[str, Any]:
        """The AL-0 ``inputPins`` (``evaluation_receipt.PIN_KEYS``), all stated."""
        pins: dict[str, Any] = {
            "codeSha": self.code_sha,
            "sourceHashes": {str(k): str(v) for k, v in sorted(self.input_hashes.items())},
            "snapshotHash": self.snapshot_hash,
            "scoringFingerprint": self.scoring_fingerprint,
        }
        if set(pins) != set(PIN_KEYS):  # the AL-0 pin vocabulary moved; refuse, never drift
            raise ReceiptError(f"pin vocabulary drifted: {sorted(PIN_KEYS)}")
        return pins

    def to_dict(self) -> dict[str, Any]:
        fp = self.scoring_fingerprint
        return {
            "schema": PROVENANCE_SCHEMA,
            "codeSha": self.code_sha,
            "codeTreeClean": self.code_tree_clean,
            "inputHashes": {str(k): str(v) for k, v in sorted(self.input_hashes.items())},
            "snapshotHash": self.snapshot_hash,
            "modelVersionId": self.model_version_id,
            "evaluatedAt": iso(self.evaluated_at),
            "scoringFingerprint": fp.to_dict() if isinstance(fp, NotApplicable) else fp,
            "environment": dict(sorted(self.environment.items())),
        }


def git_code_identity(repo: Path = REPO) -> tuple[str, bool]:
    """``(HEAD commit, tree is clean)`` for the checkout that runs the evaluation.

    Raises :class:`ReceiptError` when git cannot answer — an evaluation run outside
    a git checkout has no reproducible code identity, and ``"unknown"`` is never
    substituted for one."""

    def _run(*args: str) -> str:
        proc = subprocess.run(
            ["git", *args], cwd=str(repo), capture_output=True, text=True, check=False
        )
        if proc.returncode != 0:
            raise ReceiptError(f"git {' '.join(args)} failed; no reproducible code identity")
        return proc.stdout

    sha = _run("rev-parse", "HEAD").strip()
    dirty = _run("status", "--porcelain", "--untracked-files=no").strip()
    if not CODE_SHA_RE.match(sha):
        raise ReceiptError(f"git rev-parse HEAD returned {sha!r}, not a full commit id")
    return sha, not dirty


def reproducible_evaluation_receipt(
    *, provenance: EvaluationProvenance, **evaluation: Any
) -> LearningReceipt:
    """An AL-0 EVALUATION receipt whose pins are the provenance's, all concrete.

    ``evaluation`` is every other :class:`EvaluationReceipt` field except
    ``model_version_id`` / ``input_pins`` / ``model_family``, which come from the
    provenance so they cannot disagree with it. The provenance is carried verbatim
    in ``body.extra.provenance``; the evaluation cutoff may not be after the
    evaluation instant (an evaluation cannot read data from its own future)."""
    for owned in ("model_version_id", "input_pins", "model_family"):
        if owned in evaluation:
            raise ReceiptError(f"{owned} is taken from the provenance; do not pass it")
    cutoff = evaluation.get("cutoff")
    if cutoff is not None and _require_aware(cutoff, "cutoff") > provenance.evaluated_at:
        raise ReceiptError(
            f"cutoff {iso(cutoff)} is after evaluatedAt {iso(provenance.evaluated_at)}"
        )
    extra = dict(evaluation.pop("extra", {}) or {})
    if "provenance" in extra:
        raise ReceiptError("extra.provenance is reserved for the EvaluationProvenance")
    extra["provenance"] = provenance.to_dict()
    receipt = EvaluationReceipt(
        model_family=provenance.model_family,
        model_version_id=provenance.model_version_id,
        input_pins=provenance.input_pins(),
        extra=extra,
        **evaluation,
    )
    return receipt.to_learning_receipt()


def _overall_point(body: Mapping[str, Any], criterion_name: str) -> float:
    metrics = ((body.get("overallResult") or {}).get("metrics")) or {}
    est = metrics.get(criterion_name)
    if not isinstance(est, Mapping) or est.get("point") is None:
        raise ReceiptError(
            f"the receipt's overall result reports no {criterion_name!r} metric; "
            "the criterion a registry records must be one the evaluation measured"
        )
    point = float(est["point"])
    if not math.isfinite(point):
        raise ReceiptError(f"criterion {criterion_name!r} is not finite")
    return point


def evaluation_record(receipt: LearningReceipt, *, criterion_name: str) -> dict[str, Any]:
    """The block a ``ModelVersion.holdout`` stores for a reproducible evaluation.

    Carries ``criterion`` (so ``ModelVersion.qualified`` is true only with a real
    measurement) and ``measuredAt`` (= the provenance's evaluation instant), plus
    the receipt identity and content hash the promotion gate re-verifies."""
    if receipt.kind != KIND_EVALUATION:
        raise ReceiptError(f"an evaluation record needs an EVALUATION receipt, not {receipt.kind}")
    body = receipt.body
    provenance = (body.get("extra") or {}).get("provenance")
    if not isinstance(provenance, Mapping) or provenance.get("schema") != PROVENANCE_SCHEMA:
        raise ReceiptError(
            "the receipt carries no reproducible provenance; build it with "
            "reproducible_evaluation_receipt"
        )
    return {
        "criterion": _overall_point(body, criterion_name),
        "criterionName": criterion_name,
        "measuredAt": provenance["evaluatedAt"],
        "evaluationReceipt": {
            "receiptId": receipt.receipt_id,
            "contentHash": receipt.content_hash(),
            "modelVersionId": receipt.model_version_id,
            "verdict": body.get("verdict"),
        },
        "provenance": dict(provenance),
    }


def _pin_is_concrete(value: Any) -> bool:
    if isinstance(value, Mapping) and value.get("state") in ("unobserved", "not_applicable"):
        return False
    return value not in (None, "", {}, [])


def verify_evaluation_record(
    record: Mapping[str, Any] | None,
    receipt: LearningReceipt | None,
    *,
    expected_model_version_id: str,
    expected_champion_model_version_id: str | None,
    required_pins: Iterable[str],
    not_applicable_pins: Iterable[str] = (),
    required_holdout_designs: Iterable[str] = (),
    criterion_name: str | None = None,
) -> list[str]:
    """Every reason the recorded evaluation cannot support a promotion; ``[]`` if none.

    Fail closed: an absent record, an absent receipt, or a receipt whose content
    hash differs from the one the registry recorded is a refusal — the gate never
    trusts a summary it cannot re-derive."""
    if not isinstance(record, Mapping) or not record.get("evaluationReceipt"):
        return [
            "the challenger carries no reproducible evaluation record "
            "(holdout.evaluationReceipt); nothing measured it"
        ]
    if receipt is None:
        return [
            "promotion needs the evaluation receipt itself, not only its recorded hash: "
            "pass evaluation_receipt= so its content can be re-verified"
        ]
    problems: list[str] = []
    rec = record["evaluationReceipt"]
    if receipt.kind != KIND_EVALUATION:
        problems.append(f"the receipt is a {receipt.kind}, not an EVALUATION")
    if receipt.receipt_id != rec.get("receiptId"):
        problems.append("the receipt presented is not the one the registry recorded (receiptId)")
    if receipt.content_hash() != rec.get("contentHash"):
        problems.append(
            "the receipt's content hash differs from the recorded one: the evidence "
            "changed after it was recorded, or this is a different evaluation"
        )
    if receipt.model_version_id != expected_model_version_id:
        problems.append(
            f"the receipt evaluates {receipt.model_version_id!r}, not "
            f"{expected_model_version_id!r}"
        )
    body = receipt.body
    if body.get("role") != "challenger":
        problems.append(f"the receipt's role is {body.get('role')!r}, not 'challenger'")
    if body.get("championModelVersionId") != expected_champion_model_version_id:
        problems.append(
            f"the receipt compared against {body.get('championModelVersionId')!r}, but the "
            f"incumbent is {expected_champion_model_version_id!r}; a win against another "
            "champion is not a win against this one"
        )
    if body.get("verdict") != VERDICT_CHALLENGER_BETTER:
        problems.append(
            f"the evaluation verdict is {body.get('verdict')!r}; only "
            f"{VERDICT_CHALLENGER_BETTER!r} can support a promotion"
        )
    if body.get("promotes") is not False:
        problems.append("a receipt that claims to promote is malformed (A5)")
    designs = set(body.get("holdoutDesign") or ())
    missing_designs = sorted(set(required_holdout_designs) - designs)
    if missing_designs:
        problems.append(
            f"the family requires holdout design(s) {missing_designs}; the evaluation "
            f"used {sorted(designs)}"
        )
    provenance = (body.get("extra") or {}).get("provenance")
    if not isinstance(provenance, Mapping) or provenance.get("schema") != PROVENANCE_SCHEMA:
        problems.append("the receipt carries no reproducible provenance block")
        return problems
    if dict(provenance) != dict(record.get("provenance") or {}):
        problems.append("the registry's provenance differs from the receipt's")
    if record.get("measuredAt") != provenance.get("evaluatedAt"):
        problems.append("holdout.measuredAt is not the evaluation's own instant")
    if provenance.get("codeTreeClean") is not True:
        problems.append("the evaluation ran on a dirty tree; its code is not the commit it names")
    if provenance.get("modelVersionId") != receipt.model_version_id:
        problems.append("the provenance names a different model version than the receipt")
    pins = body.get("inputPins") or {}
    allowed_na = set(not_applicable_pins)
    for key in required_pins:
        value = pins.get(key)
        if key in allowed_na and isinstance(value, Mapping):
            if value.get("state") == "not_applicable" and str(value.get("reason") or "").strip():
                continue
        if not _pin_is_concrete(value):
            problems.append(f"input pin {key!r} is not a concrete value ({value!r})")
    if criterion_name is not None:
        # holdout.criterion is NOT covered by the receipt's content hash, and it is
        # what ModelVersion.qualified reads — so re-derive it from the receipt.
        try:
            measured: float | None = _overall_point(body, criterion_name)
        except ReceiptError as exc:
            problems.append(str(exc))
            measured = None
        if measured is not None and record.get("criterion") != measured:
            problems.append(
                f"holdout.criterion {record.get('criterion')!r} is not the receipt's "
                f"measured {criterion_name!r} ({measured!r})"
            )
    return problems
