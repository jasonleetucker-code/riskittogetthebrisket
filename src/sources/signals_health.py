"""Signals collection HEALTH report — per family, read-only, box-local.

Plan PR-H (owner directive 2026-10-19, Phase 9; plan §5.5 "health mode").
``scripts/verify_signals_health.py`` is the thin CLI; the workflow
``signals-health-probe.yml`` (``mode: health``) runs it on the production
host from the DEPLOYED checkout.

What it answers, per registry key (per family for IDP):

* is the board CSV exactly ``render_board_csv`` of the release that claims it
  (``latest.json``), and of that family's last GOOD release (a family carried
  through a family-scoped quarantine points at its ``carriedFrom``)?
* does ``<key>_last_success`` agree with what was actually published or
  verified — never newer than the last verification, never present without
  one?
* the dataset clocks, the freshness/health/coverage factors the contract
  would apply (through the freshness owner, ``src.sources.freshness``) and
  which source-health alerts would fire (through the alert owner,
  ``src.api.source_health_alerts.detect_content_alerts``) — reused, never
  re-derived;
* the collector, renewal and alert-sweep units; the owner session's health
  CLASS (never a token, fingerprint, pool id or session timestamp in public);
  whether the last service run was a min-interval skip; the quarantine
  census; the SERVED flag state from local ``/api/status``; ``MemAvailable``.

PRIVACY: the repository is public, so the CLI prints ONLY
:func:`public_projection` — an explicit allowlist of key paths whose leaves
are booleans, numbers, ``None`` or identifier-shaped enums (a timestamp, a
name or a path cannot pass :func:`assert_public_safe`).  The full report is
written 0600 to the private Signals store on the box.
"""

from __future__ import annotations

import json
import re
import subprocess
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from src.sources import signals as S

SIGNALS_KEYS: tuple[str, ...] = ("signalsSf", *S.IDP_FAMILY_BOARDS.values())
SIGNALS_FLAGS: tuple[str, ...] = (
    "signals_active_source",
    "signals_idp_shared_market",
    "signals_idp_family_quarantine",
    # Registered by the per-family activation unit (PR-I); reported as
    # ``registered: false`` until that build is deployed.
    "signals_idp_dl_vote",
    "signals_idp_lb_vote",
    "signals_idp_db_vote",
    "signals_idp_xwalk_v2",
)
UNITS: dict[str, str] = {
    "collector": "dynasty-signals-values",
    "renewal": "dynasty-signals-auth-renew",
    "alertSweep": "dynasty-signal-alerts",
}
#: A service start this much after the marker's ``lastRunAt`` means the run
#: never reached the network decision — a ``--min-interval-hours`` skip.
SKIP_DETECTION_SLACK_SECONDS = 120
STAMP_AGREEMENT_SECONDS = 120

ShowFn = Callable[[str, tuple[str, ...]], Mapping[str, str]]
StatusFn = Callable[[], Mapping[str, Any] | None]


# ── small readers ────────────────────────────────────────────────────────


def _read_json(path: Path) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _parse_ts(text: Any) -> datetime | None:
    if text in (None, ""):
        return None
    if isinstance(text, (int, float)):
        return datetime.fromtimestamp(float(text), tz=timezone.utc)
    s = str(text).strip()
    if s.isdigit():
        return datetime.fromtimestamp(int(s), tz=timezone.utc)
    dt = S.parse_iso(s)
    if dt is not None:
        return dt
    # systemd: "Mon 2026-10-19 19:26:18 UTC"
    m = re.search(r"(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2})", s)
    if m:
        return datetime.fromisoformat(f"{m.group(1)}T{m.group(2)}+00:00")
    return None


def _hours(a: datetime | None, b: datetime | None) -> float | None:
    if a is None or b is None:
        return None
    return round((a - b).total_seconds() / 3600.0, 1)


def systemd_show(unit: str, props: tuple[str, ...]) -> dict[str, str]:
    try:
        cp = subprocess.run(
            ["systemctl", "show", unit, *[f"-p{p}" for p in props], "--no-pager"],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {}
    if cp.returncode != 0:
        return {}
    out: dict[str, str] = {}
    for line in (cp.stdout or "").splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            out[k] = v
    return out


def local_status(url: str = "http://127.0.0.1:8000/api/status") -> dict[str, Any] | None:
    try:
        with urllib.request.urlopen(url, timeout=20) as resp:  # noqa: S310 — fixed local URL
            data = json.loads(resp.read().decode("utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def mem_available_mb(meminfo: Path = Path("/proc/meminfo")) -> int | None:
    try:
        for line in meminfo.read_text(encoding="ascii").splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) // 1024
    except (OSError, ValueError, IndexError):
        return None
    return None


# ── sections ─────────────────────────────────────────────────────────────


def units_section(show: ShowFn) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for role, unit in UNITS.items():
        timer = show(f"{unit}.timer", ("LoadState", "ActiveState", "UnitFileState"))
        svc = show(
            f"{unit}.service",
            ("LoadState", "ActiveState", "Result", "ExecMainStatus", "ExecMainStartTimestamp"),
        )
        out[role] = {
            "timerInstalled": timer.get("LoadState") == "loaded",
            "timerEnabled": timer.get("UnitFileState") == "enabled",
            "timerActive": timer.get("ActiveState") == "active",
            "serviceLoaded": svc.get("LoadState") == "loaded",
            "serviceRunning": svc.get("ActiveState") in ("active", "activating"),
            "serviceLastResult": svc.get("Result") or None,
            "serviceLastExit": _int_or_none(svc.get("ExecMainStatus")),
            "_serviceLastStart": svc.get("ExecMainStartTimestamp") or None,
        }
    return out


def _int_or_none(v: Any) -> int | None:
    try:
        return int(str(v))
    except (TypeError, ValueError):
        return None


def session_section(auth_store: Any | None) -> dict[str, Any]:
    from src.sources import signals_auth as SA  # noqa: PLC0415

    try:
        store = auth_store if auth_store is not None else SA.SignalsStore.open()
        st = SA.status(store)
    except Exception as exc:  # noqa: BLE001 — report, never traceback
        return {"state": "error", "error": type(exc).__name__}
    failure = st.get("lastFailure") or {}
    episode = st.get("episode") or {}
    return {
        "state": st.get("state"),
        "acquisitionState": st.get("acquisitionState"),
        "renewalObserved": bool(st.get("renewCount")),
        "lastFailureClass": failure.get("class"),
        "consecutiveTransientFailures": st.get("consecutiveTransientFailures"),
        "episodeOpen": bool(episode),
        "episodeFailureClass": episode.get("failureClass"),
        "reconnectNoticeDelivered": bool(episode.get("noticeDeliveredAt")) if episode else None,
        # private only (leading underscore never reaches the projection)
        "_lastRenewedAt": st.get("lastRenewedAt"),
        "_accessTokenExpiresAt": st.get("accessTokenExpiresAt"),
    }


def collection_section(store_root: Path, units: Mapping[str, Any]) -> dict[str, Any]:
    marker = _read_json(S.values_root(store_root) / S.PROVISIONED_MARKER) or {}
    last_run = _parse_ts(marker.get("lastRunAt"))
    svc_start = _parse_ts((units.get("collector") or {}).get("_serviceLastStart"))
    skipped = None
    if last_run is not None and svc_start is not None:
        skipped = (svc_start - last_run).total_seconds() > SKIP_DETECTION_SLACK_SECONDS
    datasets: dict[str, Any] = {}
    census: dict[str, Any] = {}
    for key in S.VALUE_DATASETS:
        ds = marker.get("datasets", {}).get(key) or {}
        datasets[key] = {"lastOutcome": ds.get("outcome")}
        qdir = S.values_root(store_root) / key / "quarantine"
        scopes = {"release": 0, "family": 0}
        for q in sorted(qdir.glob("*.json")) if qdir.is_dir() else []:
            rec = _read_json(q) or {}
            scopes["family" if rec.get("scope") == "family" else "release"] += 1
        census[key] = scopes
    return {
        "provisioned": S.private_store_provisioned(store_root),
        "lastRunOk": marker.get("lastRunOk"),
        "collectionRan": None if skipped is None else not skipped,
        "skippedByMinInterval": skipped,
        "datasets": datasets,
        "quarantineCensus": census,
        "_lastRunAt": marker.get("lastRunAt"),
        "_lastSuccessAt": marker.get("lastSuccessAt"),
    }


def _release(store_root: Path, dataset: str, sha: str | None) -> Mapping[str, Any] | None:
    if not sha:
        return None
    rel = _read_json(S.values_root(store_root) / dataset / "releases" / f"{sha}.json")
    return rel if isinstance(rel, dict) else None


def _family_rows(spec: S.ValueDatasetSpec, release: Mapping[str, Any] | None, key: str) -> list:
    rows = list((release or {}).get("boardRows") or [])
    return [r for r in rows if spec.board_key_for(r) == key]


def _last_good_release(
    store_root: Path, spec: S.ValueDatasetSpec, latest: Mapping[str, Any] | None, key: str
) -> Mapping[str, Any] | None:
    """The release whose rows are this family's last GOOD board: ``latest``
    unless a family-scoped quarantine carried it, then its ``carriedFrom``
    chain (bounded)."""
    rel = latest
    for _ in range(64):
        scope = (rel or {}).get("familyScope") or {}
        if key not in (scope.get("quarantinedFamilies") or []):
            return rel
        nxt = _release(store_root, spec.key, scope.get("carriedFrom"))
        if nxt is None:
            return None
        rel = nxt
    return None


def boards_section(
    store_root: Path,
    state_dir: Path,
    *,
    now: datetime,
) -> dict[str, Any]:
    from src.sources import dataset_state as DS  # noqa: PLC0415

    out: dict[str, Any] = {}
    for spec in S.VALUE_DATASETS.values():
        dsdir = S.values_root(store_root) / spec.key
        latest = _read_json(dsdir / "latest.json")
        latest = latest if isinstance(latest, dict) else None
        fetch = _read_json(dsdir / "fetch_state.json") or {}
        last_status = fetch.get("lastBoardStatus") or {}
        verified_at = max(
            (
                t
                for t in (
                    _parse_ts(fetch.get("lastPublishedAt")),
                    _parse_ts(fetch.get("lastVerifiedUnchangedAt")),
                )
                if t is not None
            ),
            default=None,
        )
        for key in spec.output_keys():
            csv_path = S.board_csv_path(store_root, key)
            csv_bytes = csv_path.read_bytes() if csv_path.is_file() else None
            expect_latest = (
                S.render_board_csv(_family_rows(spec, latest, key)).encode("utf-8")
                if latest is not None
                else None
            )
            good = _last_good_release(store_root, spec, latest, key)
            expect_good = (
                S.render_board_csv(_family_rows(spec, good, key)).encode("utf-8")
                if good is not None
                else None
            )
            stamp_path = Path(state_dir) / f"{key}_last_success"
            try:
                stamp = _parse_ts(stamp_path.read_text(encoding="ascii").strip())
            except (OSError, ValueError):
                stamp = None
            board_state = (last_status.get(key) or {}).get("state")
            if stamp is None:
                stamp_ok = None if verified_at is None else board_state != S.BOARD_ACCEPTED
            elif verified_at is None:
                stamp_ok = False  # a success stamp with no verification behind it
            elif board_state == S.BOARD_ACCEPTED:
                stamp_ok = abs((stamp - verified_at).total_seconds()) <= STAMP_AGREEMENT_SECONDS
            else:
                stamp_ok = stamp <= verified_at
            ds_state = DS.load_state(DS.state_path(Path(state_dir), key)) or {}
            upstream = _parse_ts((ds_state.get("upstream") or {}).get("publishedAt"))
            out[key] = {
                "dataset": spec.key,
                "family": {v: k for k, v in spec.family_boards.items()}.get(key),
                "boardState": board_state,
                "boardReason": (last_status.get(key) or {}).get("reason"),
                "boardRows": (last_status.get(key) or {}).get("rows"),
                "csvPresent": csv_bytes is not None,
                "csvMatchesLatest": (None if expect_latest is None else csv_bytes == expect_latest),
                "csvMatchesLastGood": None if expect_good is None else csv_bytes == expect_good,
                "lastGoodIsLatest": None if good is None else good is latest,
                "lastSuccessPresent": stamp is not None,
                "lastSuccessAgreesWithVerification": stamp_ok,
                "lastSuccessAgeHours": _hours(now, stamp),
                "datasetHealth": (ds_state.get("health") or {}).get("state"),
                "upstreamAgeHours": _hours(now, upstream),
                "consecutiveFailures": fetch.get("consecutiveFailures"),
                "lastOutcome": fetch.get("lastOutcome"),
                "_lastSuccessAt": stamp.isoformat() if stamp else None,
                "_upstreamPublishedAt": (ds_state.get("upstream") or {}).get("publishedAt"),
                "_latestContentSha256": (latest or {}).get("contentSha256"),
            }
    return out


def weighting_section(state_dir: Path, *, now: datetime) -> dict[str, Any]:
    """Freshness / health / coverage factors and would-alert booleans,
    through their owners (no second freshness rule, no second alert rule)."""
    try:
        from src.api.source_health_alerts import detect_content_alerts  # noqa: PLC0415
        from src.sources.freshness import load_source_weightings  # noqa: PLC0415

        weightings = load_source_weightings(list(SIGNALS_KEYS), state_dir=state_dir, as_of=now)
        dicts = {k: w.to_dict() for k, w in weightings.items()}
        alerts = detect_content_alerts({"sources": dicts})
    except Exception as exc:  # noqa: BLE001 — report, never traceback
        return {"error": type(exc).__name__}
    out: dict[str, Any] = {}
    for key, w in weightings.items():
        players = w.subsets.get("players")
        mine = [a.source for a in alerts if _alert_key(a.source) == key]
        out[key] = {
            "measured": w.measured,
            "health": w.health_state,
            "healthFactor": w.health_factor,
            "coverageFactor": round(w.coverage_factor, 4),
            "freshness": None if players is None else round(float(players.freshness), 4),
            "freshnessState": None if players is None else players.state,
            "wouldAlertContentStale": any(a.startswith("content:") for a in mine),
            "wouldAlertHealth": any(a.startswith("health:") for a in mine),
            "wouldAlertCoverage": any(a.startswith("coverage:") for a in mine),
        }
    return out


def _alert_key(source: str) -> str | None:
    """``content:<key>/<subset>`` · ``health:<key>:<state>`` · ``coverage:<key>``."""
    parts = str(source).split(":")
    return parts[1].split("/")[0] if len(parts) >= 2 else None


def served_section(status: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(status, Mapping):
        return {"statusReachable": False}
    flags = status.get("featureFlags") or {}
    absent = set(status.get("served_private_absent_by_design") or [])
    out_flags: dict[str, Any] = {}
    for name in SIGNALS_FLAGS:
        entry = flags.get(name)
        if isinstance(entry, Mapping):
            out_flags[name] = {"registered": True, "enabled": bool(entry.get("enabled"))}
        elif isinstance(entry, bool):
            out_flags[name] = {"registered": True, "enabled": entry}
        else:
            out_flags[name] = {"registered": False, "enabled": None}
    return {
        "statusReachable": True,
        "flags": out_flags,
        "absentByDesign": {k: k in absent for k in SIGNALS_KEYS},
    }


# ── assembly + public projection ─────────────────────────────────────────


def build_health_report(
    app_dir: Path,
    *,
    now: datetime | None = None,
    show: ShowFn = systemd_show,
    status_fetch: StatusFn = local_status,
    auth_store: Any | None = None,
    meminfo: Path = Path("/proc/meminfo"),
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    store_root = Path(app_dir) / "data" / "sources" / "signals"
    state_dir = Path(app_dir) / "data" / "scrape_state"
    units = units_section(show)
    return {
        "mode": "health",
        "units": units,
        "session": session_section(auth_store),
        "collection": collection_section(store_root, units),
        "boards": boards_section(store_root, state_dir, now=now),
        "weighting": weighting_section(state_dir, now=now),
        "served": served_section(status_fetch()),
        "alertRouting": {
            "sweepTimerActive": (units.get("alertSweep") or {}).get("timerActive"),
        },
        "memAvailableMb": mem_available_mb(meminfo),
    }


#: Explicit allowlist of public key paths (``*`` = any one key at that
#: level).  Anything not listed — every ``_``-prefixed private field among
#: it — never reaches stdout.
PUBLIC_PATHS: tuple[str, ...] = (
    "mode",
    "units.*.timerInstalled",
    "units.*.timerEnabled",
    "units.*.timerActive",
    "units.*.serviceLoaded",
    "units.*.serviceRunning",
    "units.*.serviceLastResult",
    "units.*.serviceLastExit",
    "session.state",
    "session.acquisitionState",
    "session.renewalObserved",
    "session.lastFailureClass",
    "session.consecutiveTransientFailures",
    "session.episodeOpen",
    "session.episodeFailureClass",
    "session.reconnectNoticeDelivered",
    "session.error",
    "collection.provisioned",
    "collection.lastRunOk",
    "collection.collectionRan",
    "collection.skippedByMinInterval",
    "collection.datasets.*.lastOutcome",
    "collection.quarantineCensus.*.release",
    "collection.quarantineCensus.*.family",
    "boards.*.dataset",
    "boards.*.family",
    "boards.*.boardState",
    "boards.*.boardReason",
    "boards.*.boardRows",
    "boards.*.csvPresent",
    "boards.*.csvMatchesLatest",
    "boards.*.csvMatchesLastGood",
    "boards.*.lastGoodIsLatest",
    "boards.*.lastSuccessPresent",
    "boards.*.lastSuccessAgreesWithVerification",
    "boards.*.lastSuccessAgeHours",
    "boards.*.datasetHealth",
    "boards.*.upstreamAgeHours",
    "boards.*.consecutiveFailures",
    "boards.*.lastOutcome",
    "weighting.error",
    "weighting.*.measured",
    "weighting.*.health",
    "weighting.*.healthFactor",
    "weighting.*.coverageFactor",
    "weighting.*.freshness",
    "weighting.*.freshnessState",
    "weighting.*.wouldAlertContentStale",
    "weighting.*.wouldAlertHealth",
    "weighting.*.wouldAlertCoverage",
    "served.statusReachable",
    "served.flags.*.registered",
    "served.flags.*.enabled",
    "served.absentByDesign.*",
    "alertRouting.sweepTimerActive",
    "memAvailableMb",
)

_SAFE_STRING = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")
#: A 12-hex content/rule hash prefix (never a token: 48 bits, hex only).
_HEX12 = re.compile(r"^[0-9a-f]{12}$")


def _project(node: Any, parts: list[str], out: dict[str, Any]) -> None:
    if not parts or not isinstance(node, Mapping):
        return
    head, rest = parts[0], parts[1:]
    keys = [k for k in node if not str(k).startswith("_")] if head == "*" else [head]
    for k in keys:
        if k not in node:
            continue
        if rest:
            child = out.setdefault(k, {})
            if isinstance(child, dict):
                _project(node[k], rest, child)
        else:
            out[k] = node[k]


def _prune(node: Any) -> Any:
    if isinstance(node, dict):
        return {k: _prune(v) for k, v in node.items() if not (isinstance(v, dict) and not v)}
    return node


class PublicLeak(ValueError):
    """A value outside the public shape reached the projection."""


def assert_public_safe(node: Any, path: str = "") -> None:
    """Leaves must be bool / number / None / identifier-shaped strings (or a
    12-hex hash prefix).

    A timestamp, a name (spaces), a path or a token cannot match
    ``_SAFE_STRING``; keys obey the same rule."""
    if isinstance(node, Mapping):
        for k, v in node.items():
            if not _SAFE_STRING.match(str(k)):
                raise PublicLeak(f"unsafe key at {path or '<root>'}")
            assert_public_safe(v, f"{path}.{k}" if path else str(k))
        return
    if node is None or isinstance(node, (bool, int, float)):
        return
    if isinstance(node, str) and (_SAFE_STRING.match(node) or _HEX12.match(node)):
        return
    raise PublicLeak(f"unsafe value at {path}")


def public_projection(report: Mapping[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for path in PUBLIC_PATHS:
        _project(report, path.split("."), out)
    out = _prune(out)
    assert_public_safe(out)
    return out
