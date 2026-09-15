"""Background-only producer status reads for the web process."""

from __future__ import annotations

import json
import math
import threading
from datetime import datetime, timezone

from src.serving.artifacts import ArtifactError, PublishLockTimeout, _check_path, _publish_lock
from src.serving.producer_status import (
    RECEIPT_FILE,
    STATUS_FILE,
    pending_source_refresh,
    pending_league_refresh,
)


def _read(root, name):
    path = root / name
    _check_path(path)
    with path.open("rb") as stream:
        raw = stream.read(262145)
    if len(raw) > 262144:
        raise ValueError("producer status exceeds bound")
    value = json.loads(raw)
    if not isinstance(value, dict) or value.get("schemaVersion") != 1:
        raise ValueError("invalid producer status")
    return value


class ProducerStatusReader:
    """Cache bounded diagnostics; a held OS lease proves a live source owner."""

    def __init__(self, store, *, alert=None, observe_source=True):
        self.store = store
        self.alert = alert
        self.observe_source = observe_source
        self._alerted = None
        self._current = (
            {"owner": "standalone", "status_summary": "unknown", "running": False}
            if observe_source
            else {"owner": "embedded"}
        )
        self._artifacts = {"observed": False}
        self._stop = threading.Event()
        self._thread = None
        self.last_error = None

    def snapshot(self):
        return dict(self._current)

    def artifact_snapshot(self):
        """Only cached, bounded aggregate fields; never scan disk on a request."""
        return dict(self._artifacts)

    def _refresh_artifacts(self):
        try:
            report = self.store.read_retention_report()
            fields = (
                "bytesBefore",
                "bytesAfter",
                "generationCount",
                "protectedCount",
                "deletedCount",
                "budgetBytes",
                "minFreeBytes",
                "freeBytes",
                "oldestRetainedAt",
                "capacityFailureCount",
                "lastCapacityFailureAt",
                "blocked",
                "capacityBlocked",
                "unknownAcceptanceCount",
                "shortenedRollbackWindow",
                "observedAt",
            )
            self._artifacts = {
                "observed": report.get("status") in {"ok", "blocked"},
                **{
                    key: report[key][:80] if isinstance(report[key], str) else report[key]
                    for key in fields
                    if key in report
                    and isinstance(report[key], (str, int, float, bool, type(None)))
                    and (not isinstance(report[key], float) or math.isfinite(report[key]))
                },
            }
        except (OSError, ValueError, TypeError, ArtifactError) as exc:
            self._artifacts = {"observed": False, "observationError": type(exc).__name__}

    def refresh(self):
        self._refresh_artifacts()
        if not self.observe_source:
            return
        try:
            state = _read(self.store.root, STATUS_FILE)
            try:
                receipt = _read(self.store.root, RECEIPT_FILE)
            except (OSError, ValueError, ArtifactError):
                receipt = {}
            try:
                with _publish_lock(self.store.root / "producer.lock", 0):
                    running = False
            except PublishLockTimeout:
                running = True
            outcome = state.get("outcome")
            interrupted = outcome == "running" and not running
            summary = "running" if running else "interrupted" if interrupted else outcome
            if summary not in {"running", "interrupted", "success", "blocked", "failed"}:
                summary = "unknown"
            progress = state.get("progress") or {}
            if not isinstance(progress, dict) or not isinstance(state.get("runs", []), list):
                raise ValueError("invalid producer progress/history shape")
            failure = summary if summary in {"blocked", "failed", "interrupted"} else None
            now = datetime.now(timezone.utc)
            recent = []
            for run in (state.get("runs") or [])[-200:]:
                try:
                    age = (
                        now - datetime.fromisoformat(run["timestamp"].replace("Z", "+00:00"))
                    ).total_seconds()
                    if 0 <= age <= 86400 and run.get("outcome") in {"success", "blocked", "failed"}:
                        recent.append({k: run.get(k) for k in ("outcome", "timestamp", "duration")})
                except (TypeError, ValueError, KeyError, AttributeError):
                    continue
            successes = sum(run["outcome"] == "success" for run in recent)
            self._current = {
                "owner": "standalone",
                "running": running,
                "is_running": running,
                "interrupted": interrupted,
                "status_summary": summary,
                "error": failure,
                "last_error": failure,
                "started_at": state.get("startedAt"),
                "finished_at": state.get("finishedAt"),
                "last_heartbeat": state.get("updatedAt"),
                "last_success_at": receipt.get("completedAt"),
                "last_scrape": receipt.get("sourceProducedAt"),
                "last_duration_sec": state.get("durationSeconds"),
                "current_step": str(progress.get("step") or "")[:80] or None,
                "current_source": str(progress.get("source") or "")[:80] or None,
                "progress_step_index": progress.get("index"),
                "progress_step_total": progress.get("total"),
                "pendingRefresh": pending_source_refresh(self.store),
                "pendingLeagueRefresh": pending_league_refresh(self.store),
                "queue_wait_seconds": state.get("queueWaitSeconds"),
                "scrape_success_rate_24h": {
                    "total": len(recent),
                    "success": successes,
                    "failure": len(recent) - successes,
                    "rate": successes / len(recent) if recent else None,
                },
                "last_n_scrapes": recent[-20:],
                "observedAt": datetime.now(timezone.utc).isoformat(),
            }
            self.last_error = None
            alert_key = (failure, state.get("finishedAt") or state.get("startedAt"))
            if failure and self.alert and alert_key != self._alerted:
                self._alerted = alert_key
                try:
                    self.alert(
                        f"Source refresh {failure}",
                        "The standalone source producer did not publish new data. The accepted board remains available; inspect producer status for details.",
                    )
                except Exception:
                    # Notification delivery cannot stop observing source health.
                    pass
        except (OSError, ValueError, TypeError, AttributeError, ArtifactError) as exc:
            self.last_error = type(exc).__name__
            # Retain last observations but do not imply that an old lease is live.
            self._current = {
                **self._current,
                "running": False,
                "is_running": False,
                "status_summary": "unknown",
                "observationError": self.last_error,
            }

    def start(self, interval=5):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()

        def run():
            while not self._stop.is_set():
                self.refresh()
                self._stop.wait(interval)

        self._thread = threading.Thread(target=run, name="producer-status-reader", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
