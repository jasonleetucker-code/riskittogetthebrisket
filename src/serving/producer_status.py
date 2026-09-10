"""Private producer diagnostics and explicit source cutover evidence."""

from __future__ import annotations

import json
import math
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from src.serving.artifacts import (
    ArtifactError,
    ArtifactStore,
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


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic_json(root: Path, name: str, value: dict) -> None:
    _mkdir(root)
    destination = root / name
    _check_path(destination)
    temporary = root / f".{name}.{uuid.uuid4().hex}.tmp"
    try:
        _write_new(temporary, json.dumps(value, sort_keys=True, allow_nan=False).encode())
        os.replace(temporary, destination)
        _sync_directory(root)
    finally:
        temporary.unlink(missing_ok=True)


def pending_source_refresh(store: ArtifactStore) -> dict | None:
    path = store.root / REQUEST_FILE
    _check_path(path)
    try:
        with path.open("rb") as handle:
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


def request_source_refresh(store: ArtifactStore, trigger: str = "manual") -> dict:
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
    with _publish_lock(store.root / "source-request.lock", 2):
        existing = pending_source_refresh(store)
        if existing:
            return {**existing, "coalesced": True}
        request = {
            "schemaVersion": 1,
            "outcome": "queued",
            "requestId": uuid.uuid4().hex,
            "trigger": trigger,
            "requestedAt": _now(),
        }
        _atomic_json(store.root, REQUEST_FILE, request)
        return {**request, "coalesced": False}


def claim_source_refresh(store: ArtifactStore) -> dict | None:
    """Called only inside the source lease; preserve requests arriving afterward."""
    with _publish_lock(store.root / "source-request.lock", 2):
        path = store.root / REQUEST_FILE
        _check_path(path)
        if not path.exists():
            return None
        request = pending_source_refresh(store)
        claim = (
            {**request, "outcome": "claimed", "claimedAt": _now()}
            if request
            else {"schemaVersion": 1, "outcome": "invalid_request", "claimedAt": _now()}
        )
        _atomic_json(store.root, CLAIM_FILE, claim)
        path.unlink()
        _sync_directory(store.root)
        return claim


class ProducerJournal:
    """Callbacks are invoked under the source lease; a busy process writes nothing.

    Only operational metadata is retained. Event payloads from provider callbacks
    are deliberately excluded; status never stores source rows, cookies or rosters.
    """

    def __init__(self, store: ArtifactStore):
        from src.serving.producer import source_parity_contract, source_parity_hash

        self.store = store
        self.source_parity = source_parity_contract()
        self.source_parity_hash = source_parity_hash()
        self.accepted_generation = ""
        self.league_report: dict = {}
        self.input_manifest: dict = {}
        self.state: dict = {"schemaVersion": 1, "pid": os.getpid(), "events": []}

    def _save(self) -> None:
        self.state["updatedAt"] = _now()
        _atomic_json(self.store.root, STATUS_FILE, self.state)

    def event(self, name: str, *, level="info", message="", **meta) -> None:
        if name == "producer_started":
            self.source_parity = meta["sourceParity"]
            self.source_parity_hash = meta["sourceParityHash"]
            self.state.update(outcome="running", startedAt=_now())
            self.state["refreshRequest"] = claim_source_refresh(self.store)
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
            _atomic_json(self.store.root, RECEIPT_FILE, receipt)
            self.state["acceptedGeneration"] = self.accepted_generation
        self._save()


def source_receipt_ready(store: ArtifactStore, *, max_age_seconds: float = 14400) -> bool:
    """Fail closed before disabling the old source owner at prepared-mode startup.

    Required supplemental failures still permit legacy canonical publication,
    but they cannot establish a healthy source-ownership cutover receipt.
    """
    from src.serving.producer import (
        MIRROR_FILES,
        SUPPLEMENTAL_SOURCES,
        source_parity_contract,
        source_parity_hash,
    )

    try:
        if (
            isinstance(max_age_seconds, bool)
            or not math.isfinite(max_age_seconds)
            or max_age_seconds <= 0
        ):
            return False
        path = store.root / RECEIPT_FILE
        _check_path(path)
        receipt = json.loads(path.read_bytes())
        if receipt.get("schemaVersion") != 1 or receipt.get("outcome") != "success":
            return False
        if receipt.get("sourceParityHash") != source_parity_hash():
            return False
        if receipt.get("sourceParity") != source_parity_contract():
            return False
        now = datetime.now(timezone.utc)
        for field in ("completedAt", "sourceProducedAt"):
            instant = datetime.fromisoformat(receipt[field].replace("Z", "+00:00"))
            age = (now - instant).total_seconds()
            if not -60 <= age <= max_age_seconds:
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
        artifact = store.read_current("canonical-serving", "default")
        return (
            artifact.generation_id == receipt.get("acceptedGeneration")
            and artifact.manifest.get("inputGenerations", {}).get("sourceCycle")
            == source_parity_hash()
            and artifact.manifest.get("sourceAsOf") == receipt.get("sourceProducedAt")
        )
    except (ArtifactError, OSError, ValueError, TypeError, KeyError, AttributeError):
        return False
