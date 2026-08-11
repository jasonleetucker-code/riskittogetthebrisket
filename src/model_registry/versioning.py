"""Model versions, provenance, and the champion pointer.

Every fitted parameter set gets an identity: a monotonic version, the
exact parameters, when it was fitted, what produced it, and a
fingerprint of every training input.  Without the fingerprints
"version 7" is a label; with them it is reproducible.

The champion pointer is the only thing that says which version is
authoritative.  Rollback is therefore a pointer move plus a file
rewrite, not a hand-edit of constants — which is the whole point:
a human reverting a bad refit at 2am should type one command, not
retype eight floats from a diff.

Storage is a single JSON document per model id under
``config/model_registry/``.  JSON because every other tunable in this
repo is JSON config, and because a human needs to be able to read the
history without running anything.

Pure computation over supplied paths.  No network.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

REPO = Path(__file__).resolve().parents[2]
DEFAULT_REGISTRY_DIR = REPO / "config" / "model_registry"

# A version is one of these and nothing else.  "rejected" is retained
# rather than deleted: a challenger that lost is evidence about the
# search space, and deleting it invites refitting the same loser.
VERSION_STATUSES: tuple[str, ...] = ("champion", "challenger", "retired", "rejected")


class RegistryError(RuntimeError):
    """Raised for any operation that would leave the registry incoherent."""


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def fingerprint_file(path: Path) -> str:
    """Content hash of a training input.

    Short sha256.  The point is not cryptographic strength, it is
    being able to answer "was this version fitted on the same data I
    am looking at now" without storing the data.
    """
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return f"sha256:{h.hexdigest()[:16]}"


def fingerprint_inputs(paths: Mapping[str, Path]) -> dict[str, str]:
    """Fingerprint each named training input; missing files are stamped.

    A missing input is recorded as ``"missing"`` rather than skipped.
    Silently omitting it would make a version fitted on five sources
    indistinguishable from one fitted on six.
    """
    out: dict[str, str] = {}
    for label, path in sorted(paths.items()):
        out[label] = fingerprint_file(path) if path.exists() else "missing"
    return out


@dataclass(frozen=True)
class ModelVersion:
    """One fitted parameter set, with everything needed to judge it.

    ``confidence`` and ``qualified`` are the directive's "do not
    present low-confidence output as precise" clause made structural:
    a version that has never been evaluated out of sample is
    ``qualified=False``, and any consumer that surfaces its output is
    obliged to say so.
    """

    model_id: str
    version: int
    params: dict[str, float]
    fitted_at: str
    producer: str
    status: str = "challenger"
    training_inputs: dict[str, str] = field(default_factory=dict)
    holdout: dict[str, Any] | None = None
    notes: tuple[str, ...] = ()
    promoted_at: str | None = None
    retired_at: str | None = None
    #: When this version's params were written into ``player_valuation.py``.
    #: ADR-008 split promote from apply so a human performs the second step;
    #: without this the registry records the first and not the second, so it
    #: cannot answer "are the live constants the champion?" — the question
    #: the split exists to make askable.  Accepts the sentinel
    #: ``UNKNOWN_HISTORICAL_APPLY_TIME`` for state predating this field:
    #: fabricating a precise timestamp would be worse than admitting the
    #: gap, and ``None`` would read as "never applied".
    applied_at: str | None = None
    #: Per-scope evidence at promotion time (see ``scope_validation``).
    #: Stored rather than recomputed so a reader sees what the gate actually
    #: concluded, not what it would conclude against today's code.
    scope_validation: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.status not in VERSION_STATUSES:
            raise RegistryError(
                f"unknown status {self.status!r}; expected one of {VERSION_STATUSES}"
            )
        if self.version < 1:
            raise RegistryError(f"version must be >= 1, got {self.version}")

    @property
    def qualified(self) -> bool:
        """True only if this version has a recorded out-of-sample score.

        Deliberately not defaulting to True.  The seeded champion is
        unqualified until someone evaluates it, and that is an honest
        statement about it rather than a defect.
        """
        return bool(self.holdout) and self.holdout.get("criterion") is not None

    @property
    def confidence(self) -> str:
        """Coarse label, sized to what is actually known.

        Three buckets, not a number: a continuous confidence score
        here would itself be an unvalidated model, which is the
        failure mode this package exists to prevent.
        """
        if not self.qualified:
            return "unvalidated"
        sources = (self.holdout or {}).get("perSource") or {}
        return "measured" if len(sources) >= 3 else "provisional"

    def to_dict(self) -> dict[str, Any]:
        return {
            "modelId": self.model_id,
            "version": self.version,
            "params": dict(self.params),
            "fittedAt": self.fitted_at,
            "producer": self.producer,
            "status": self.status,
            "trainingInputs": dict(self.training_inputs),
            "holdout": self.holdout,
            "qualified": self.qualified,
            "confidence": self.confidence,
            "notes": list(self.notes),
            "promotedAt": self.promoted_at,
            "retiredAt": self.retired_at,
            "appliedAt": self.applied_at,
            "scopeValidation": dict(self.scope_validation),
        }

    @classmethod
    def from_dict(cls, blob: Mapping[str, Any]) -> ModelVersion:
        return cls(
            model_id=str(blob["modelId"]),
            version=int(blob["version"]),
            params={str(k): float(v) for k, v in (blob.get("params") or {}).items()},
            fitted_at=str(blob.get("fittedAt") or ""),
            producer=str(blob.get("producer") or "unknown"),
            status=str(blob.get("status") or "challenger"),
            training_inputs={str(k): str(v) for k, v in (blob.get("trainingInputs") or {}).items()},
            holdout=blob.get("holdout"),
            notes=tuple(blob.get("notes") or ()),
            promoted_at=blob.get("promotedAt"),
            retired_at=blob.get("retiredAt"),
            applied_at=blob.get("appliedAt"),
            scope_validation={
                str(k): str(v) for k, v in (blob.get("scopeValidation") or {}).items()
            },
        )


class ModelRegistry:
    """Versions of one model id, plus the champion pointer."""

    def __init__(self, model_id: str, versions: Iterable[ModelVersion] = ()) -> None:
        self.model_id = model_id
        self._versions: list[ModelVersion] = sorted(versions, key=lambda v: v.version)
        self._validate()

    # ── persistence ────────────────────────────────────────────────

    @classmethod
    def path_for(cls, model_id: str, registry_dir: Path | None = None) -> Path:
        safe = re.sub(r"[^a-z0-9_]+", "_", model_id.lower())
        return (registry_dir or DEFAULT_REGISTRY_DIR) / f"{safe}.json"

    @classmethod
    def load(cls, model_id: str, registry_dir: Path | None = None) -> ModelRegistry:
        path = cls.path_for(model_id, registry_dir)
        if not path.exists():
            raise RegistryError(f"no registry for model {model_id!r} at {path}")
        blob = json.loads(path.read_text())
        return cls(
            model_id=str(blob.get("modelId") or model_id),
            versions=[ModelVersion.from_dict(v) for v in blob.get("versions") or []],
        )

    def save(self, registry_dir: Path | None = None) -> Path:
        path = self.path_for(self.model_id, registry_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "modelId": self.model_id,
            "schemaVersion": 1,
            "updatedAt": _utcnow(),
            "championVersion": self.champion.version if self.has_champion else None,
            "versions": [v.to_dict() for v in self._versions],
        }
        path.write_text(json.dumps(payload, indent=2, sort_keys=False) + "\n")
        return path

    # ── invariants ─────────────────────────────────────────────────

    def _validate(self) -> None:
        seen: set[int] = set()
        for v in self._versions:
            if v.model_id != self.model_id:
                raise RegistryError(
                    f"version {v.version} belongs to {v.model_id!r}, not {self.model_id!r}"
                )
            if v.version in seen:
                raise RegistryError(f"duplicate version {v.version} for {self.model_id!r}")
            seen.add(v.version)
        champions = [v for v in self._versions if v.status == "champion"]
        if len(champions) > 1:
            raise RegistryError(
                f"{self.model_id!r} has {len(champions)} champions "
                f"({[c.version for c in champions]}); exactly one is allowed"
            )

    # ── reads ──────────────────────────────────────────────────────

    @property
    def versions(self) -> tuple[ModelVersion, ...]:
        return tuple(self._versions)

    @property
    def has_champion(self) -> bool:
        return any(v.status == "champion" for v in self._versions)

    @property
    def champion(self) -> ModelVersion:
        for v in self._versions:
            if v.status == "champion":
                return v
        raise RegistryError(f"{self.model_id!r} has no champion")

    def get(self, version: int) -> ModelVersion:
        for v in self._versions:
            if v.version == version:
                return v
        raise RegistryError(f"{self.model_id!r} has no version {version}")

    def next_version(self) -> int:
        return (max((v.version for v in self._versions), default=0)) + 1

    # ── writes ─────────────────────────────────────────────────────

    @staticmethod
    def _require_measurement_time(version: ModelVersion) -> None:
        """A recorded criterion must carry the date it was measured on.

        The criterion's ABSOLUTE level drifts ~19 points on identical
        parameters across 7 days, against a 25-point promotion margin — so
        two undated scores sitting in one file look directly comparable and
        are not.  ``HoldoutResult.to_dict`` has stamped ``measuredAt`` since
        `705cdc03e` (2026-08-05); this stops any other path from writing a
        score without one.

        Enforced on the WRITE path only.  The three stored versions predate
        that commit and legitimately have nulls; guarding in
        ``__post_init__`` would make the shipped registry unloadable, which
        is rewriting history rather than annotating it.
        """
        holdout = version.holdout or {}
        if holdout.get("criterion") is None:
            return
        if holdout.get("measuredAt") or holdout.get("measuredAtUnknownHistorical"):
            return
        raise RegistryError(
            f"v{version.version} records a holdout criterion with no measuredAt; "
            "an undated score cannot be compared with a dated one, because the "
            "criterion's absolute level drifts week to week. Set measuredAt, or "
            "measuredAtUnknownHistorical for a pre-existing record whose date is "
            "genuinely unrecoverable."
        )

    def add(self, version: ModelVersion) -> ModelVersion:
        """Register a new version.  Never auto-promotes."""
        if version.status == "champion":
            raise RegistryError(
                "add() cannot introduce a champion directly — register the "
                "version, then promote() it, so the transition is recorded"
            )
        self._require_measurement_time(version)
        self._versions.append(version)
        self._versions.sort(key=lambda v: v.version)
        self._validate()
        return version

    def seed_champion(self, version: ModelVersion) -> ModelVersion:
        """Install the first champion for a model that has none.

        Separate from ``promote`` because there is no incumbent to
        compare against: seeding is an act of recording what is
        ALREADY live, not a claim that it won anything.
        """
        if self.has_champion:
            raise RegistryError(
                f"{self.model_id!r} already has a champion (v{self.champion.version}); "
                "use promote()"
            )
        self._require_measurement_time(version)
        seeded = replace(version, status="champion", promoted_at=_utcnow())
        self._versions.append(seeded)
        self._versions.sort(key=lambda v: v.version)
        self._validate()
        return seeded

    def promote(self, version: int, *, reason: str) -> ModelVersion:
        """Make ``version`` the champion; retire the incumbent.

        The reason is mandatory and stored.  A promotion with no stated
        reason is indistinguishable from an accident.
        """
        if not reason.strip():
            raise RegistryError("promote() requires a non-empty reason")
        target = self.get(version)
        if target.status == "champion":
            raise RegistryError(f"v{version} is already champion")
        if target.status == "retired":
            raise RegistryError(
                f"v{version} is retired; use rollback() to reinstate a former champion"
            )

        now = _utcnow()
        out: list[ModelVersion] = []
        for v in self._versions:
            if v.status == "champion":
                out.append(replace(v, status="retired", retired_at=now))
            elif v.version == version:
                out.append(
                    replace(
                        v,
                        status="champion",
                        promoted_at=now,
                        notes=(*v.notes, f"promoted: {reason.strip()}"),
                    )
                )
            else:
                out.append(v)
        self._versions = sorted(out, key=lambda v: v.version)
        self._validate()
        return self.champion

    def reject(self, version: int, *, reason: str) -> ModelVersion:
        """Mark a challenger as having lost.  Kept, not deleted."""
        if not reason.strip():
            raise RegistryError("reject() requires a non-empty reason")
        target = self.get(version)
        if target.status == "champion":
            raise RegistryError(f"v{version} is the champion; it cannot be rejected")
        out = [
            replace(v, status="rejected", notes=(*v.notes, f"rejected: {reason.strip()}"))
            if v.version == version
            else v
            for v in self._versions
        ]
        self._versions = sorted(out, key=lambda v: v.version)
        self._validate()
        return self.get(version)

    def rollback(self, *, to_version: int | None = None, reason: str) -> ModelVersion:
        """Reinstate a previous champion — the single documented undo.

        With no ``to_version`` this reinstates the most recently
        retired champion, which is what "undo the last refit" means.
        Only a FORMER champion can be rolled back to: rolling back to
        something that was never live is not a rollback, it is an
        unvalidated promotion wearing the word.
        """
        if not reason.strip():
            raise RegistryError("rollback() requires a non-empty reason")

        former = [v for v in self._versions if v.status == "retired" and v.promoted_at]
        if not former:
            raise RegistryError(f"{self.model_id!r} has no former champion to roll back to")
        if to_version is None:
            target = max(former, key=lambda v: (v.retired_at or "", v.version))
        else:
            target = self.get(to_version)
            if target.status != "retired" or not target.promoted_at:
                raise RegistryError(
                    f"v{to_version} was never a champion; rollback targets former " "champions only"
                )

        now = _utcnow()
        out: list[ModelVersion] = []
        for v in self._versions:
            if v.status == "champion":
                out.append(
                    replace(
                        v,
                        status="retired",
                        retired_at=now,
                        notes=(*v.notes, f"rolled back: {reason.strip()}"),
                    )
                )
            elif v.version == target.version:
                out.append(
                    replace(
                        v,
                        status="champion",
                        promoted_at=now,
                        retired_at=None,
                        notes=(*v.notes, f"reinstated: {reason.strip()}"),
                    )
                )
            else:
                out.append(v)
        self._versions = sorted(out, key=lambda v: v.version)
        self._validate()
        return self.champion
