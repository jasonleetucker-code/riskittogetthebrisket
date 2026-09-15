"""Existing VPS source cycle, shared by legacy web and standalone producers.

Importing this module starts no job and imports no web application or scraper.
The injected publisher owns canonical build/history and atomic serving promotion.
The source set is intentionally different from GitHub's scheduled-refresh job.
"""

from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import json
import logging
import os
import shutil
import sys
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.serving.artifacts import ArtifactStore, PublishLockTimeout, _mkdir, _publish_lock
from src.serving.producer_status import source_receipt_ready as source_receipt_ready

log = logging.getLogger(__name__)
SOURCE_CYCLE_VERSION = 1
MIRROR_FILES = (
    "ktc.csv",
    "ktcSfTep.csv",
    "ktcCrowdSfTep.csv",
    "ktcTradesSfTep.csv",
    "ktcCrowdTradesSfTep.csv",
    "idpTradeCalc.csv",
)
SUPPLEMENTAL_SOURCES = (
    ("dynastyNerdsSfTep", "scripts/fetch_dynasty_nerds.py", ("--mirror-data-dir",)),
    ("fantasyProsSf", "scripts/fetch_fantasypros_offense.py", ("--mirror-data-dir",)),
    ("fantasyProsIdp", "scripts/fetch_fantasypros_idp.py", ("--mirror-data-dir",)),
    ("idpShow", "scripts/fetch_idpshow.py", ()),
)


def source_parity_contract() -> dict:
    """The source ownership cutover contract; no secret or league payload."""
    root = Path(__file__).resolve().parents[2]

    def digest(relative):
        return hashlib.sha256((root / relative).read_bytes()).hexdigest()

    return {
        "version": SOURCE_CYCLE_VERSION,
        "coreScript": "Dynasty Scraper.py",
        "coreScriptDigest": digest("Dynasty Scraper.py"),
        "coreSourcePolicy": "unchanged SITES configuration",
        "supplemental": [
            {
                "source": source,
                "script": script,
                "scriptDigest": digest(script),
                "args": list(args),
                "condition": "idpshow_session.json exists" if source == "idpShow" else "always",
            }
            for source, script, args in SUPPLEMENTAL_SOURCES
        ],
        "mirrorFiles": list(MIRROR_FILES),
        "additionalFeedOwner": ".github/workflows/scheduled-refresh.yml",
        "replaces": "server.run_scraper source orchestration only",
    }


def source_parity_hash() -> str:
    return hashlib.sha256(json.dumps(source_parity_contract(), sort_keys=True).encode()).hexdigest()


@dataclass(frozen=True)
class ProducerConfig:
    repo_dir: Path
    data_dir: Path
    timeout_seconds: float = 7200
    retention_floor: float = 0.75
    disk_min_mb: int = 500
    artifact_root: Path | None = None
    publication_requires_disk: bool = False
    lease_wait_seconds: float = 0

    @property
    def serving_root(self) -> Path:
        return ArtifactStore(self.artifact_root).root


@dataclass(frozen=True)
class ProducerResult:
    outcome: str
    raw: dict | None = None
    source: dict = field(default_factory=dict)
    duration: float = 0.0
    player_count: int = 0
    site_count: int = 0
    total_sites: int = 0
    reason: str = ""
    source_evidence: dict = field(default_factory=dict)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_scraper(config: ProducerConfig):
    path = config.repo_dir / "Dynasty Scraper.py"
    spec = importlib.util.spec_from_file_location("Dynasty_Scraper", str(path))
    if spec is None or spec.loader is None:
        raise RuntimeError("scraper module is unavailable")
    scraper = importlib.util.module_from_spec(spec)
    sys.modules["Dynasty_Scraper"] = scraper
    spec.loader.exec_module(scraper)
    scraper.SCRIPT_DIR = str(config.data_dir)
    return scraper


def _mirror_source_csvs(config: ProducerConfig) -> list[dict]:
    src_raw = config.data_dir / "exports" / "latest" / "site_raw"
    dst_raw = config.repo_dir / "CSVs" / "site_raw"
    evidence = []
    for filename in MIRROR_FILES:
        source = src_raw / filename
        if not source.exists():
            outcome = "source_missing"
        elif not dst_raw.exists():
            outcome = "destination_missing"
        else:
            shutil.copy2(source, dst_raw / filename)
            outcome = "copied"
        evidence.append({"file": filename, "outcome": outcome})
    return evidence


def _run_supplemental_sources(config: ProducerConfig, emit: Callable) -> None:
    # Refresh Dynasty Nerds SF-TEP rankings.  The DN board is
    # inlined in the page HTML as a ``window.DR_DATA`` JS
    # constant — no Playwright required — so we run the plain
    # ``scripts/fetch_dynasty_nerds.py`` helper inline on every
    # scheduled scrape cycle.  Failure is logged and ignored so
    # a transient network error cannot fail the entire scrape.
    try:
        from scripts import fetch_dynasty_nerds as _dn_fetch

        rc = _dn_fetch.main(["--mirror-data-dir"])
        emit(
            "source_attempt",
            source="dynastyNerdsSfTep",
            outcome="success" if rc == 0 else "failed",
            exitCode=rc,
        )
        if rc == 2:
            # Schema / row-count regression — surface loudly as
            # a structured scrape event so /api/status shows the
            # failure instead of burying it as a log line.
            emit(
                "dynasty_nerds_schema_regression",
                level="error",
                message=("Dynasty Nerds fetch exit=2 (DR_DATA shape changed or rows below floor)"),
                exit_code=rc,
            )
        elif rc != 0:
            emit(
                "dynasty_nerds_fetch_failed",
                level="warning",
                message=f"Dynasty Nerds fetch returned exit={rc}",
                exit_code=rc,
            )
    except Exception as _dn_err:
        emit("source_attempt", source="dynastyNerdsSfTep", outcome="failed", exitCode=None)
        emit(
            "dynasty_nerds_fetch_exception",
            level="warning",
            message=f"Dynasty Nerds fetch raised: {_dn_err}",
        )

    # Refresh FantasyPros Dynasty Superflex (offense) rankings.
    # The dynasty-superflex page inlines an ``ecrData = {...}``
    # JS constant, so a plain ``requests.get`` with a browser
    # UA returns the full payload.  The fetch script extracts
    # QB/RB/WR/TE consensus ECR ranks and writes a rank-signal CSV.
    try:
        from scripts import fetch_fantasypros_offense as _fpoff_fetch

        rc = _fpoff_fetch.main(["--mirror-data-dir"])
        emit(
            "source_attempt",
            source="fantasyProsSf",
            outcome="success" if rc == 0 else "failed",
            exitCode=rc,
        )
        if rc == 2:
            emit(
                "fantasypros_offense_schema_regression",
                level="error",
                message=(
                    "FantasyPros Offense fetch exit=2 "
                    "(ecrData shape changed or rows below floor)"
                ),
                exit_code=rc,
            )
        elif rc != 0:
            emit(
                "fantasypros_offense_fetch_failed",
                level="warning",
                message=f"FantasyPros Offense fetch returned exit={rc}",
                exit_code=rc,
            )
    except Exception as _fpoff_err:
        emit("source_attempt", source="fantasyProsSf", outcome="failed", exitCode=None)
        emit(
            "fantasypros_offense_fetch_exception",
            level="warning",
            message=f"FantasyPros Offense fetch raised: {_fpoff_err}",
        )

    # Refresh FantasyPros Dynasty IDP rankings.  The combined
    # + DL/LB/DB pages inline their rankings in a JS
    # ``ecrData = {...}`` constant, so a plain ``requests.get``
    # with a browser UA returns the full payload.  The fetch
    # script derives per-player effective overall ranks via
    # anchor curves fit on the combined/individual overlap
    # and writes a rank-signal CSV.
    try:
        from scripts import fetch_fantasypros_idp as _fp_fetch

        rc = _fp_fetch.main(["--mirror-data-dir"])
        emit(
            "source_attempt",
            source="fantasyProsIdp",
            outcome="success" if rc == 0 else "failed",
            exitCode=rc,
        )
        if rc == 2:
            emit(
                "fantasypros_idp_schema_regression",
                level="error",
                message=(
                    "FantasyPros IDP fetch exit=2 " "(ecrData shape changed or rows below floor)"
                ),
                exit_code=rc,
            )
        elif rc != 0:
            emit(
                "fantasypros_idp_fetch_failed",
                level="warning",
                message=f"FantasyPros IDP fetch returned exit={rc}",
                exit_code=rc,
            )
    except Exception as _fp_err:
        emit("source_attempt", source="fantasyProsIdp", outcome="failed", exitCode=None)
        emit(
            "fantasypros_idp_fetch_exception",
            level="warning",
            message=f"FantasyPros IDP fetch raised: {_fp_err}",
        )

    # Refresh The IDP Show (Adamidp) rankings.  The fetcher
    # reads cookies from ``idpshow_session.json`` at the repo
    # root — if the file is missing (e.g. fresh deploy before
    # the operator has pasted cookies) we skip silently.
    # When cookies have expired the fetcher returns non-zero
    # and we surface it as a warning so the stale-data banner
    # knows to prompt a cookie refresh.
    _idpshow_session = config.repo_dir / "idpshow_session.json"
    if _idpshow_session.exists():
        try:
            from scripts import fetch_idpshow as _idpshow_fetch

            rc = _idpshow_fetch.main([])
            emit(
                "source_attempt",
                source="idpShow",
                outcome="success" if rc == 0 else "failed",
                exitCode=rc,
            )
            if rc != 0:
                emit(
                    "idpshow_fetch_failed",
                    level="warning",
                    message=(
                        f"IDP Show fetch returned exit={rc}.  "
                        f"Session cookies may have expired — "
                        f"refresh idpshow_session.json."
                    ),
                    exit_code=rc,
                )
        except Exception as _idpshow_err:
            emit("source_attempt", source="idpShow", outcome="failed", exitCode=None)
            emit(
                "idpshow_fetch_exception",
                level="warning",
                message=f"IDP Show fetch raised: {_idpshow_err}",
            )
    else:
        emit("source_attempt", source="idpShow", outcome="skipped", reason="session_missing")
        log.info(
            "IDP Show skipped — idpshow_session.json missing; "
            "operator must paste cookies into that file to enable."
        )


def missing_expected_sites(result: dict | None) -> list[str]:
    """Anchor sources the scrape was expected to produce and did not.

    Audit O-3.  The payload declares its own load-bearing inputs in
    ``coverageAudit.expectedSites`` — ``{"offense": ["ktc"], "idp":
    ["idpTradeCalc"]}`` on live data — so "did we lose an anchor?" is
    answerable without inventing a threshold or hardcoding a source
    name here.  A source counts as produced only if it actually carried
    players; present-but-empty is exactly the degraded case the guard
    exists to catch.

    Returns ``[]`` on any shape surprise.  This runs on the scrape path
    and a diagnostic that can crash the scrape is worse than the defect
    it reports — but note that an empty list from a MALFORMED payload
    means "no anchors known to be missing", not "all anchors present",
    which is why the ratio test is kept alongside it rather than
    replaced by it.
    """
    try:
        audit = (result or {}).get("coverageAudit") or {}
        expected_block = audit.get("expectedSites") or {}
        expected: set[str] = set()
        for names in expected_block.values():
            if isinstance(names, (list, tuple)):
                expected.update(str(n) for n in names if n)
        if not expected:
            return []

        def _reported_rows(block: object, field: str) -> bool:
            """True only when the block states a positive row count.

            Absent, null or non-numeric means the source did not report
            producing anything — which is treated the same as zero HERE
            because this guard's question is "can we prove the anchor
            arrived?", and unproven must not read as arrived.  Written
            out rather than as ``or 0`` so the reasoning is visible:
            the coercion gate flags that shape precisely because it
            usually hides this decision instead of stating it.
            """
            if not isinstance(block, dict):
                return False
            count = block.get(field)
            return isinstance(count, (int, float)) and count > 0

        produced: set[str] = set()
        for site in (result or {}).get("sites") or []:
            if _reported_rows(site, "playerCount"):
                produced.add(str(site.get("key") or ""))
        for key, stats in ((result or {}).get("siteStats") or {}).items():
            if _reported_rows(stats, "count"):
                produced.add(str(key))

        return sorted(expected - produced)
    except Exception:  # noqa: BLE001 — never break the scrape over a diagnostic
        return []


def promotion_reason(result: dict, previous_raw: dict | None, retention_floor: float = 0.75) -> str:
    """The existing missing-anchor, half-source and population-collapse guards."""
    missing = missing_expected_sites(result)
    player_count = len(result.get("players") or {})
    sites = result.get("sites") or []
    site_count = len([site for site in sites if site.get("playerCount", 0) > 0])
    previous_count = len((previous_raw or {}).get("players") or {})
    retention = player_count / previous_count if previous_count > 0 else 1.0
    if missing:
        return f"MISSING ANCHOR SOURCE(S): {', '.join(missing)}"
    if previous_count > 0 and retention < retention_floor:
        return (
            f"PLAYER POPULATION COLLAPSE: {player_count}/{previous_count} "
            f"({retention:.1%} retained; floor={retention_floor:.0%})"
        )
    if sites and site_count < len(sites) / 2:
        return f"only {site_count}/{len(sites)} sites"
    return ""


def _check_disk_space(config: ProducerConfig) -> tuple[bool, int]:
    try:
        free_mb = shutil.disk_usage(str(config.data_dir)).free // (1024 * 1024)
        return free_mb >= config.disk_min_mb, free_mb
    except OSError:
        # Preserve the legacy guard's explicit fail-open behavior.
        return True, -1


async def run_source_cycle(
    config: ProducerConfig,
    previous_raw: dict | Callable[[], dict] | None,
    *,
    publish: Callable[[dict, dict], Awaitable[Any]],
    progress: Callable[..., Any] | None = None,
    event: Callable[..., Any] | None = None,
    alert: Callable[[str, str], Any] | None = None,
    completed: Callable[[ProducerResult], Any] | None = None,
) -> ProducerResult:
    """Collect the existing VPS source set and publish only an accepted candidate.

    Both legacy and standalone callers must use this lease. ``previous_raw``
    must be the accepted serving generation, not the newest unvalidated scrape
    export. The publisher must raise on failure and preserve the old generation.
    An OS-owned lock covers collection through promotion and releases on exit.
    """
    start = time.monotonic()
    evidence = {"core": {}, "supplemental": [], "mirrors": []}

    def finish(result):
        if completed is not None:
            completed(result)
        return result

    def emit(name, level="info", message="", **meta):
        if name == "source_attempt":
            evidence["supplemental"].append(dict(meta))
        getattr(log, level if level in ("info", "warning", "error") else "info")(
            "producer event=%s message=%s", name, message
        )
        if event is not None:
            event(name, level=level, message=message, **meta)

    def notify(subject, body):
        if alert is not None:
            alert(subject, body)

    def phase(step, source, index, message):
        if progress is not None:
            progress(
                step=step,
                source=source,
                step_index=index,
                step_total=4,
                event="phase_start",
                message=message,
            )

    async def on_progress(payload):
        if progress is not None and isinstance(payload, dict):
            progress(
                step=payload.get("step"),
                source=payload.get("source"),
                step_index=payload.get("step_index"),
                step_total=payload.get("step_total"),
                event=payload.get("event"),
                message=payload.get("message"),
                level=payload.get("level", "info"),
                meta=payload.get("meta"),
            )

    result = None
    source = {}
    counts = {"player_count": 0, "site_count": 0, "total_sites": 0}
    try:
        _mkdir(config.serving_root)
        with _publish_lock(config.serving_root / "producer.lock", config.lease_wait_seconds):
            parity = source_parity_contract()
            parity_hash = hashlib.sha256(json.dumps(parity, sort_keys=True).encode()).hexdigest()
            emit(
                "producer_started",
                pid=os.getpid(),
                queueWaitSeconds=round(time.monotonic() - start, 3),
                sourceParityHash=parity_hash,
                sourceParity=parity,
            )
            try:
                if callable(previous_raw):
                    previous_raw = previous_raw()
                phase("bootstrap", "import_scraper", 1, "Importing scraper module")
                scraper = _load_scraper(config)
                phase("scrape", "Dynasty Scraper.py", 2, "Executing scraper.run()")
                result = await asyncio.wait_for(
                    scraper.run(progress_callback=on_progress), timeout=config.timeout_seconds
                )
                evidence["core"] = {
                    "completed": True,
                    "script": "Dynasty Scraper.py",
                    "enabledSites": sorted(
                        key for key, enabled in scraper.SITES.items() if enabled
                    ),
                }
                phase("validate", "result_payload", 3, "Validating scraper output")
                if not result or not result.get("players"):
                    raise RuntimeError("Scraper returned empty result")
                try:
                    evidence["mirrors"] = _mirror_source_csvs(config)
                except Exception as exc:  # noqa: BLE001
                    emit("source_csv_mirror_failed", level="warning", message=str(exc))
                _run_supplemental_sources(config, emit)
                counts = {
                    "player_count": len(result.get("players") or {}),
                    "site_count": len(
                        [s for s in result.get("sites", []) if s.get("playerCount", 0) > 0]
                    ),
                    "total_sites": len(result.get("sites", [])),
                }
                reason = promotion_reason(result, previous_raw, config.retention_floor)
                disk_ok, free_mb = _check_disk_space(config)
                if not disk_ok:
                    notify(
                        f"DISK SPACE CRITICALLY LOW: {free_mb}MB free",
                        f"Available: {free_mb}MB; minimum: {config.disk_min_mb}MB.",
                    )
                    emit("disk_space_low", level="error", freeMb=free_mb)
                    if config.publication_requires_disk and not reason:
                        reason = f"DISK SPACE LOW: {free_mb}MB free"
                if reason:
                    notify(
                        f"PARTIAL SCRAPE NOT PROMOTED: {reason}",
                        "The accepted serving generation is unchanged.",
                    )
                    emit("producer_blocked", level="warning", message=reason, **counts)
                    return finish(
                        ProducerResult(
                            "blocked",
                            previous_raw,
                            duration=time.monotonic() - start,
                            reason=reason,
                            source_evidence=evidence,
                            **counts,
                        )
                    )

                phase("publish", "serving_generation", 4, "Publishing accepted source candidate")
                if source_parity_contract() != parity:
                    raise RuntimeError(
                        "Source scripts changed during collection; retry on a stable checkout"
                    )
                result_date = str(result.get("date") or "").strip()
                candidate = config.data_dir / f"dynasty_data_{result_date}.json"
                source = {
                    "type": "scrape_run",
                    "path": str(candidate) if result_date and candidate.exists() else "",
                    "loadedAt": _utc_now(),
                    "producedAt": str(result.get("scrapeTimestamp") or ""),
                }
                await publish(result, source)
                # Only an accepted, fully published generation becomes a startup
                # recovery export. A failed canonical build must not replace it.
                if result_date:
                    try:
                        src_json = (
                            config.data_dir
                            / "exports"
                            / "latest"
                            / f"dynasty_data_{result_date}.json"
                        )
                        dst_json = (
                            config.repo_dir
                            / "exports"
                            / "latest"
                            / f"dynasty_data_{result_date}.json"
                        )
                        if src_json.exists():
                            shutil.copy2(src_json, dst_json)
                    except Exception as exc:  # noqa: BLE001
                        emit("accepted_export_mirror_failed", level="warning", message=str(exc))
                try:
                    from src.maintenance.retention import prune_data_dir  # noqa: PLC0415

                    retained = prune_data_dir(config.repo_dir)
                    if retained.total_deleted or retained.total_errors:
                        log.info("retention: %s", retained.summary())
                except Exception as exc:  # noqa: BLE001
                    emit("retention_prune_skipped", level="warning", message=str(exc))
                emit("producer_success", **counts)
                return finish(
                    ProducerResult(
                        "success",
                        result,
                        source,
                        time.monotonic() - start,
                        source_evidence=evidence,
                        **counts,
                    )
                )
            except Exception as exc:  # noqa: BLE001
                notify(f"Scrape failed: {type(exc).__name__}", f"Error: {exc}")
                emit("producer_failed", level="error", message=f"{type(exc).__name__}: {exc}")
                return finish(
                    ProducerResult(
                        "failed",
                        duration=time.monotonic() - start,
                        reason=f"{type(exc).__name__}: {exc}",
                        source_evidence=evidence,
                        **counts,
                    )
                )
            finally:
                emit("producer_finished")
    except PublishLockTimeout:
        # Do not overwrite another process's live status while it holds the lease.
        return ProducerResult(
            "busy",
            duration=time.monotonic() - start,
            reason="another source producer holds the lease",
        )
