"""Durable, crash-surviving telemetry for the production scrape.

THE PROBLEM THIS SOLVES
-----------------------
``server.py``'s ``scrape_status`` dict — every phase, every source event,
the whole run_events ring buffer — is **in memory only**. When the
dynasty process is OOM-killed or wedged, 100% of it is lost, which is
exactly the moment the evidence matters. Production has now suffered
repeated multi-minute total outages during the scrape's KTC phase and
two separate fixes failed to stop them, because nobody can see what the
box was doing while it was silent.

So this module writes the same event stream to disk as it happens.

WHERE IT WRITES, AND WHY THAT EXACT DIRECTORY
---------------------------------------------
``data/diagnostics/`` — **not** ``data/scrape_state/``, and the
distinction is load-bearing:

* ``.gitignore`` has a bare ``data/``, so both are untracked by default.
* ``deploy/deploy.sh`` uses ``git reset --hard``, which discards TRACKED
  changes and leaves untracked files alone. Untracked ⇒ survives deploys.
* BUT ``.github/workflows/scheduled-refresh.yml`` runs
  ``git add -f`` over ``data/scrape_state/`` (and CSVs/, exports/,
  data/raw/, data/ros/, …) **from the GitHub Actions runner**. Anything
  written there becomes a TRACKED file — and a tracked file is exactly
  what ``git reset --hard`` overwrites on the next production deploy,
  replacing the box's real telemetry with the runner's. Writing the
  evidence into a force-added directory would destroy the evidence.

``data/diagnostics/`` appears in no force-add list, so it stays untracked
and stays local to the box that produced it.

DURABILITY: ``flush()``, DELIBERATELY NOT ``fsync()``
-----------------------------------------------------
The threat model is process death (SIGKILL/OOM), not power loss. Once a
line is flushed it belongs to the kernel's page cache and survives the
writing process being killed outright. ``fsync`` would buy only
power-loss durability, at the cost of real disk I/O on every sample — on
a box we already suspect of resource exhaustion. Flush is the correct
stopping point.

NOTHING HERE MAY RAISE
----------------------
This sits on the scrape's critical path. Instrumentation that can break
the thing it instruments is worse than no instrumentation, so every
public function swallows its own errors (the ``# noqa: BLE001 —
monitoring helper must never raise`` idiom used elsewhere in this repo).
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DIAGNOSTICS_DIR = REPO_ROOT / "data" / "diagnostics"

EVENTS_PATH = DIAGNOSTICS_DIR / "scrape_events.jsonl"
SAMPLES_PATH = DIAGNOSTICS_DIR / "scrape_samples.jsonl"
PHASE_PATH = DIAGNOSTICS_DIR / "scrape_phase.json"

# One rotation generation, so a long-lived box cannot fill its disk with
# telemetry. 8 MB holds many days of 5-second samples.
MAX_BYTES = 8 * 1024 * 1024

_ENV_FLAG = "RISKIT_SCRAPE_TELEMETRY"


def enabled() -> bool:
    """Kill switch, matching ``SCRAPE_REAP_ORPHAN_BROWSERS``'s convention.

    Default ON: this exists to diagnose a live, unexplained outage, and a
    diagnostic that ships switched off diagnoses nothing.
    """
    return os.getenv(_ENV_FLAG, "1") != "0"


def utc_now_iso() -> str:
    return (
        time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + f".{int(time.time() % 1 * 1000):03d}Z"
    )


def _ensure_dir() -> bool:
    try:
        DIAGNOSTICS_DIR.mkdir(parents=True, exist_ok=True)
        return True
    except OSError:
        return False


def _rotate_if_needed(path: Path) -> None:
    try:
        if path.exists() and path.stat().st_size > MAX_BYTES:
            path.replace(path.with_suffix(path.suffix + ".1"))
    except OSError:
        pass


def append_jsonl(path: Path, payload: dict) -> None:
    """Append one JSON line and flush. Never raises."""
    if not enabled():
        return
    try:
        if not _ensure_dir():
            return
        _rotate_if_needed(path)
        line = json.dumps(payload, default=str, separators=(",", ":"))
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
            fh.flush()
    except Exception:  # noqa: BLE001 — monitoring helper must never raise
        pass


def record(event: str, **fields) -> None:
    """Record one scrape event to the durable event stream."""
    payload = {"ts": utc_now_iso(), "event": event}
    payload.update(fields)
    append_jsonl(EVENTS_PATH, payload)


def record_sample(payload: dict) -> None:
    """Record one resource sample (written by the out-of-process sampler)."""
    append_jsonl(SAMPLES_PATH, payload)


def set_phase(phase: str, source: str | None = None, **fields) -> None:
    """Publish the current phase for the out-of-process sampler to read.

    The sampler is a separate process and cannot see ``scrape_status`` in
    the server's memory, so the phase is handed over through this tiny
    file. Written atomically (temp + replace) so a sampler reading
    concurrently never sees a half-written document.
    """
    if not enabled():
        return
    try:
        if not _ensure_dir():
            return
        payload = {"ts": utc_now_iso(), "phase": phase, "source": source}
        payload.update(fields)
        tmp = PHASE_PATH.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, default=str)
            fh.flush()
        tmp.replace(PHASE_PATH)
    except Exception:  # noqa: BLE001 — monitoring helper must never raise
        pass


def read_phase() -> dict:
    """Current phase as published by ``set_phase``. ``{}`` when unknown."""
    try:
        with open(PHASE_PATH, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001 — monitoring helper must never raise
        return {}


def tail_jsonl(path: Path, limit: int) -> list[dict]:
    """Last ``limit`` parsed lines of a telemetry file. Never raises.

    Tolerates a torn final line (the writer may have been killed
    mid-write) by skipping anything that will not parse.
    """
    if limit <= 0:
        return []
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            lines = fh.readlines()
    except Exception:  # noqa: BLE001 — monitoring helper must never raise
        return []
    out: list[dict] = []
    for line in lines[-limit:]:
        line = line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
        except ValueError:
            continue
        if isinstance(parsed, dict):
            out.append(parsed)
    return out
