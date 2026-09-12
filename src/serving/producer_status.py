"""Private producer diagnostics and explicit source cutover evidence."""

from __future__ import annotations

import json
import math
import os
import stat
import uuid
from datetime import datetime, timezone
from pathlib import Path

from src.serving.artifacts import (
    ArtifactError,
    ArtifactStore,
    CorruptArtifact,
    PublishLockTimeout,
    _check_path,
    _mkdir,
    _publish_lock,
    _sync_directory,
    _write_new,
)

STATUS_FILE = "source-producer-status.json"
RECEIPT_FILE = "source-producer-receipt.json"
REQUEST_FILE = "source-refresh.request"
CLAIM_FILE = "source-refresh-claim.json"
OWNERSHIP_ASSET = "source-ownership"
OWNERSHIP_KEY = "standalone"
OWNERSHIP_MODEL = "source-ownership-v1"
BOOTSTRAP_LEASE_WAIT_SECONDS = 2.0


class SourceOwnershipError(RuntimeError):
    """Prepared serving has no intact proof of the configured source owner."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic_json(root: Path, name: str, value: dict, *, store=None, queue=False) -> None:
    _mkdir(root)
    destination = root / name
    _check_path(destination)
    temporary = root / f".{name}.{uuid.uuid4().hex}.tmp"
    try:
        body = json.dumps(value, sort_keys=True, allow_nan=False).encode()
        if store is None:
            _write_new(temporary, body)
        else:
            store.write_new(temporary, body, queue=queue)
        os.replace(temporary, destination)
        _sync_directory(root)
    finally:
        temporary.unlink(missing_ok=True)


def _request_files(kind: str):
    if kind == "source":
        return REQUEST_FILE, CLAIM_FILE, "source-request.lock"
    if kind == "league":
        return "league-refresh.request", "league-refresh-claim.json", "league-request.lock"
    raise ValueError("unknown producer queue")


def _pending_refresh(store: ArtifactStore, kind: str) -> dict | None:
    path = store.request_root / _request_files(kind)[0]
    _check_path(path)
    try:
        descriptor = os.open(
            path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        )
        with os.fdopen(descriptor, "rb") as handle:
            if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                return None
            body = handle.read(4097)
        if len(body) > 4096:
            return None
        payload = json.loads(body)
        if (
            payload.get("schemaVersion") == 1
            and payload.get("outcome") == "queued"
            and isinstance(payload.get("requestId"), str)
            and len(payload["requestId"]) == 32
            and isinstance(payload.get("trigger"), str)
            and len(payload["trigger"]) <= 40
            and isinstance(payload.get("requestedAt"), str)
            and len(payload["requestedAt"]) <= 40
        ):
            return {
                key: payload[key]
                for key in ("schemaVersion", "outcome", "requestId", "trigger", "requestedAt")
            }
    except (OSError, ValueError, AttributeError):
        pass
    return None


def _request_refresh(store: ArtifactStore, kind: str, trigger: str) -> dict:
    """Queue bounded operational metadata for the OS-managed source service."""
    if (
        not isinstance(trigger, str)
        or not 1 <= len(trigger) <= 40
        or any(
            char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
            for char in trigger
        )
    ):
        raise ValueError("refresh trigger must be a short operational label")
    _mkdir(store.root)
    with store.request_lock(kind):
        existing = _pending_refresh(store, kind)
        if existing:
            return {**existing, "coalesced": True}
        request = {
            "schemaVersion": 1,
            "outcome": "queued",
            "requestId": uuid.uuid4().hex,
            "trigger": trigger,
            "requestedAt": _now(),
        }
        _atomic_json(store.request_root, _request_files(kind)[0], request, store=store, queue=True)
        return {**request, "coalesced": False}


def _claim_refresh(store: ArtifactStore, kind: str) -> dict | None:
    """Called only inside the source lease; preserve requests arriving afterward."""
    with store.request_lock(kind):
        path = store.request_root / _request_files(kind)[0]
        _check_path(path)
        if not path.exists():
            return None
        request = _pending_refresh(store, kind)
        claim = (
            {**request, "outcome": "claimed", "claimedAt": _now()}
            if request
            else {"schemaVersion": 1, "outcome": "invalid_request", "claimedAt": _now()}
        )
        _atomic_json(store.root, _request_files(kind)[1], claim, store=store)
        path.unlink()
        _sync_directory(store.request_root)
        return claim


def pending_source_refresh(store: ArtifactStore) -> dict | None:
    return _pending_refresh(store, "source")


def request_source_refresh(store: ArtifactStore, trigger: str = "manual") -> dict:
    return _request_refresh(store, "source", trigger)


def claim_source_refresh(store: ArtifactStore) -> dict | None:
    return _claim_refresh(store, "source")


def pending_league_refresh(store: ArtifactStore) -> dict | None:
    return _pending_refresh(store, "league")


def request_league_refresh(store: ArtifactStore, trigger: str = "manual") -> dict:
    return _request_refresh(store, "league", trigger)


def claim_league_refresh(store: ArtifactStore) -> dict | None:
    return _claim_refresh(store, "league")


class ProducerJournal:
    """Callbacks are invoked under the source lease; a busy process writes nothing.

    Only operational metadata is retained. Event payloads from provider callbacks
    are deliberately excluded; status never stores source rows, cookies or rosters.
    """

    def __init__(self, store: ArtifactStore, *, establish_ownership: bool = False):
        from src.serving.producer import source_parity_contract, source_parity_hash

        self.store = store
        self.establish_ownership = establish_ownership
        self.source_parity = source_parity_contract()
        self.source_parity_hash = source_parity_hash()
        self.accepted_generation = ""
        self.league_report: dict = {}
        self.input_manifest: dict = {}
        self.state: dict = {"schemaVersion": 1, "pid": os.getpid(), "events": []}

    def _save(self) -> None:
        self.state["updatedAt"] = _now()
        _atomic_json(self.store.root, STATUS_FILE, self.state, store=self.store)

    def event(self, name: str, *, level="info", message="", **meta) -> None:
        if name == "producer_started":
            # Read only after lease admission, so concurrent queued workers
            # cannot overwrite one another's completed-run history.
            try:
                path = self.store.root / STATUS_FILE
                _check_path(path)
                with path.open("rb") as stream:
                    previous = stream.read(262145)
                if len(previous) <= 262144:
                    runs = json.loads(previous).get("runs", [])
                    self.state["runs"] = runs[-200:] if isinstance(runs, list) else []
            except (OSError, ValueError, TypeError, AttributeError):
                self.state["runs"] = []
            self.source_parity = meta["sourceParity"]
            self.source_parity_hash = meta["sourceParityHash"]
            self.state.update(outcome="running", startedAt=_now())
            self.state["refreshRequest"] = claim_source_refresh(self.store)
            self.state["queueWaitSeconds"] = meta.get("queueWaitSeconds")
        # Keep event names and severity, not arbitrary third-party messages.
        self.state["events"] = (
            self.state["events"] + [{"event": name, "level": level, "at": _now()}]
        )[-200:]
        self._save()

    def progress(
        self, *, step=None, source=None, step_index=None, step_total=None, **_rest
    ) -> None:
        self.state["progress"] = {
            "step": step,
            "source": source,
            "index": step_index,
            "total": step_total,
        }
        self._save()

    def completed(self, result) -> None:
        self.state.update(
            outcome=result.outcome,
            finishedAt=_now(),
            durationSeconds=result.duration,
            playerCount=result.player_count,
            siteCount=result.site_count,
            totalSites=result.total_sites,
            sourceEvidence=result.source_evidence,
            leagueRefresh=self.league_report,
            canonicalInputs=self.input_manifest,
        )
        if result.outcome == "success" and self.accepted_generation:
            receipt = {
                "schemaVersion": 1,
                "outcome": "success",
                "completedAt": _now(),
                "acceptedGeneration": self.accepted_generation,
                "sourceProducedAt": result.source.get("producedAt"),
                "sourceParityHash": self.source_parity_hash,
                "sourceParity": self.source_parity,
                "sourceEvidence": result.source_evidence,
                "canonicalInputs": self.input_manifest,
            }
            _atomic_json(self.store.root, RECEIPT_FILE, receipt, store=self.store)
            self.state["acceptedGeneration"] = self.accepted_generation
            if self.establish_ownership:
                # The standalone cycle invokes this callback before releasing
                # producer.lock. Degraded accepted data must not mint proof,
                # but it does not erase a previously verified source owner.
                # Retain intact proof on ordinary cycles: each new proof pins
                # its referenced board for retention and is only needed when
                # establishing or renewing ownership after corruption/drift.
                if _ownership_proof_ready(self.store):
                    self.state["sourceOwnership"] = {"outcome": "retained"}
                else:
                    try:
                        _attest_current_source_ownership(self.store)
                    except SourceOwnershipError:
                        self.state["sourceOwnership"] = {
                            "outcome": "unverified",
                            "reason": "healthy_current_receipt_required",
                        }
                    else:
                        self.state["sourceOwnership"] = {"outcome": "verified"}
        # Attestation I/O failure is finalized by the cycle's failed callback;
        # do not leave a second, fabricated successful run in the journal.
        self.state["runs"] = (
            self.state.get("runs", [])
            + [
                {
                    "outcome": result.outcome,
                    "timestamp": self.state["finishedAt"],
                    "duration": result.duration,
                }
            ]
        )[-200:]
        self._save()


def _receipt_evidence_valid(receipt: dict, *, max_age_seconds: float | None) -> bool:
    """Shared proof rules. Only an already attested receipt may ignore elapsed age."""
    from src.serving.producer import (
        MIRROR_FILES,
        SUPPLEMENTAL_SOURCES,
        source_parity_contract,
        source_parity_hash,
    )

    try:
        if (
            type(receipt.get("schemaVersion")) is not int
            or receipt.get("schemaVersion") != 1
            or receipt.get("outcome") != "success"
        ):
            return False
        if receipt.get("sourceParityHash") != source_parity_hash():
            return False
        if receipt.get("sourceParity") != source_parity_contract():
            return False
        now = datetime.now(timezone.utc)
        for field in ("completedAt", "sourceProducedAt"):
            instant = datetime.fromisoformat(receipt[field].replace("Z", "+00:00"))
            age = (now - instant).total_seconds()
            if age < -60 or (max_age_seconds is not None and age > max_age_seconds):
                return False
        evidence = receipt["sourceEvidence"]
        mirrors = evidence["mirrors"]
        if [item.get("file") for item in mirrors] != list(MIRROR_FILES) or any(
            item.get("outcome") not in ("copied", "source_missing") for item in mirrors
        ):
            return False
        core = evidence["core"]
        if (
            core.get("completed") is not True
            or core.get("script") != "Dynasty Scraper.py"
            or not core.get("enabledSites")
        ):
            return False
        attempts = evidence["supplemental"]
        if [attempt.get("source") for attempt in attempts] != [
            entry[0] for entry in SUPPLEMENTAL_SOURCES
        ]:
            return False
        for attempt in attempts:
            if (
                attempt.get("source") == "idpShow"
                and attempt.get("outcome") == "skipped"
                and attempt.get("reason") == "session_missing"
            ):
                continue
            if attempt.get("outcome") != "success" or attempt.get("exitCode") != 0:
                return False
        generation = receipt.get("acceptedGeneration")
        return (
            isinstance(generation, str)
            and len(generation) == 64
            and all(char in "0123456789abcdef" for char in generation)
        )
    except (ArtifactError, OSError, ValueError, TypeError, KeyError, AttributeError):
        return False


def _current_receipt_matches(store: ArtifactStore, receipt: dict, max_age_seconds: float) -> bool:
    if not _receipt_evidence_valid(receipt, max_age_seconds=max_age_seconds):
        return False
    artifact = store.read_current("canonical-serving", "default")
    return (
        artifact.generation_id == receipt.get("acceptedGeneration")
        and artifact.manifest.get("inputGenerations", {}).get("sourceCycle")
        == receipt.get("sourceParityHash")
        and artifact.manifest.get("sourceAsOf") == receipt.get("sourceProducedAt")
    )


def _read_receipt(store: ArtifactStore) -> dict:
    path = store.root / RECEIPT_FILE
    _check_path(path)
    return json.loads(path.read_bytes())


def source_receipt_ready(store: ArtifactStore, *, max_age_seconds: float = 14400) -> bool:
    """Require a healthy current source cycle before the first ownership cutover.

    This remains the freshness/liveness check; it deliberately returns False on
    stale receipts. Later restarts use the separately persisted ownership proof.
    """
    try:
        if (
            isinstance(max_age_seconds, bool)
            or not math.isfinite(max_age_seconds)
            or max_age_seconds <= 0
        ):
            return False
        return _current_receipt_matches(store, _read_receipt(store), max_age_seconds)
    except (ArtifactError, OSError, ValueError, TypeError, KeyError, AttributeError):
        return False


def _validate_ownership_proof(artifact) -> None:
    receipt = json.loads(artifact.files["receipt.json"])
    if (
        artifact.manifest.get("modelVersion") != OWNERSHIP_MODEL
        or not _receipt_evidence_valid(receipt, max_age_seconds=None)
        or artifact.manifest.get("inputGenerations", {}).get("sourceCycle")
        != receipt.get("sourceParityHash")
        or artifact.manifest.get("configHash") != receipt.get("sourceParityHash")
        or artifact.manifest.get("sourceAsOf") != receipt.get("sourceProducedAt")
    ):
        raise CorruptArtifact("source ownership proof does not match current source policy")


def _ownership_proof_ready(store: ArtifactStore) -> bool:
    try:
        _validate_ownership_proof(store.read_current(OWNERSHIP_ASSET, OWNERSHIP_KEY))
        return True
    except (ArtifactError, OSError, ValueError, TypeError, KeyError, AttributeError):
        return False


def _attest_current_source_ownership(store: ArtifactStore) -> None:
    """Persist strict current evidence; caller MUST hold this root's producer.lock.

    Never short-circuit on an older ownership proof: the receipt must identify
    the canonical artifact accepted at this verification event. Keeping the
    source lease until publish returns prevents another source cycle replacing
    the canonical pointer between the current-generation check and attestation.
    """
    receipt = _read_receipt(store)
    if not _current_receipt_matches(store, receipt, 14400):
        raise SourceOwnershipError(
            "source ownership cutover or renewal requires a healthy current source receipt"
        )
    proof = store.publish(
        OWNERSHIP_ASSET,
        OWNERSHIP_KEY,
        {"receipt.json": json.dumps(receipt, sort_keys=True, allow_nan=False).encode()},
        {
            "modelVersion": OWNERSHIP_MODEL,
            "inputGenerations": {"sourceCycle": receipt["sourceParityHash"]},
            "configHash": receipt["sourceParityHash"],
            "sourceAsOf": receipt["sourceProducedAt"],
            # Renewal must not rewrite a corrupt immutable proof directory.
            "verifiedAt": _now(),
        },
        validator=_validate_ownership_proof,
    )
    _validate_ownership_proof(proof)


def enforce_source_ownership(
    store: ArtifactStore, *, lease_wait_seconds: float = BOOTSTRAP_LEASE_WAIT_SECONDS
) -> None:
    """Attest a healthy first cutover, then permit restarts with stale valid data.

    The immutable proof stores the exact receipt verified against the then-current
    canonical artifact. Later generations or upstream outages do not erase that
    evidence. Script/policy changes or corrupt proof require a fresh healthy
    receipt to renew ownership under the same strict first-cutover rules. Without
    that new proof they refuse startup. First attestation and renewal acquire a
    bounded source lease, then recheck and persist proof before releasing it.
    An already valid proof needs no source lease or source freshness upgrade.
    This proves ownership only: the web must independently load and validate its
    current canonical serving generation.
    """
    try:
        if (
            isinstance(lease_wait_seconds, bool)
            or not math.isfinite(lease_wait_seconds)
            or not 0 <= lease_wait_seconds <= 30
        ):
            raise SourceOwnershipError("bootstrap source lease wait must be in [0, 30] seconds")
        if _ownership_proof_ready(store):
            return
        _mkdir(store.root)
        with _publish_lock(store.root / "producer.lock", lease_wait_seconds):
            # Another bootstrap may have attested while this caller waited.
            if not _ownership_proof_ready(store):
                _attest_current_source_ownership(store)
    except PublishLockTimeout as exc:
        raise SourceOwnershipError(
            "source ownership bootstrap could not acquire the source lease; retry after the active cycle"
        ) from exc
    except SourceOwnershipError:
        raise
    except (ArtifactError, OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        raise SourceOwnershipError(
            "prepared serving requires intact verified source ownership"
        ) from exc
