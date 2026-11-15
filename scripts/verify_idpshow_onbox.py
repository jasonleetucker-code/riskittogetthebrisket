#!/usr/bin/env python3
"""IDP Show production verification: session, collector, upstream freshness.

Runs ON the production host (workflow ``idpshow-onbox-verification.yml``),
from the deployed checkout.  It answers three questions separately, because
each can fail on its own and a single "IDP Show is broken" hides which:

1. **Session** — is the browser-minted cookie jar the prod timer reads
   (``/var/lib/idpshow-fetch/idpshow_session.json``) present, readable, and
   inside its cookies' stated expiry?  Cookie NAMES and expiry times only;
   a cookie VALUE is never read into anything this script prints.
2. **Collector** — what did the ``dynasty-idpshow-fetch`` timer/service do
   last, and why?  Unit state plus the service journal's own ``[idpshow``
   lines (the fetch scripts' prefixes), capped and scrubbed.
3. **Upstream** — with that jar, is each article readable (not paywalled),
   which Datawrapper charts does it embed, what is each chart's latest
   published version and Datawrapper's own ``lastModifiedAt``, and does the
   widest chart's content differ from the CSV currently committed?  A
   successful login with an unchanged chart means the vendor has published
   nothing new — re-fetching cannot make it fresh.

Read-only, except ``--collect``, which starts the existing
``dynasty-idpshow-fetch.service`` once (``sudo -n systemctl start``) exactly
as its timer does.  The probe performs GETs only; it writes no CSV, stamp,
status or upstream file.

Privacy: the repository is PUBLIC, so this prints only states, counts,
timestamps, chart ids and versions (the chart id is already committed in
``data/scrape_state/idpShowCombined_upstream.json``) — never a cookie value,
never a player name.  ``assert_public_safe`` refuses otherwise.

Exit 0 when the checks ran (a failed CHECK is a finding in the JSON);
non-zero only when the script itself could not run.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Iterable, Mapping

UNIT = "dynasty-idpshow-fetch"
DEFAULT_WORK_DIR = Path("/var/lib/idpshow-fetch")
#: Journal lines kept: only the fetch scripts' own prefixes and the unit's
#: start/finish lines.  Anything else (git output, Python tracebacks quoting
#: locals) stays on the box.
_JOURNAL_KEEP = re.compile(r"\[idpshow|Started |Finished |Failed |Deactivated|exit-code|status=")
#: Long opaque tokens (a cookie value, a session id) are redacted from any
#: journal line before it is printed, as a second line of defence.
_TOKEN = re.compile(r"[A-Za-z0-9%_\-+/=.]{32,}")
BOARDS = {
    "idpShowCombined": {"combined": True, "csv": "CSVs/site_raw/idpShowCombined.csv"},
    "idpShow": {"combined": False, "csv": "CSVs/site_raw/idpShow.csv"},
}


def _run(cmd: list[str], timeout: int = 60) -> tuple[int, str]:
    try:
        cp = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return cp.returncode, (cp.stdout or "") + (cp.stderr or "")
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 127, str(exc)


def _systemctl(*args: str, sudo: bool = False, timeout: int = 60) -> tuple[int, str]:
    cmd = ["systemctl", *args]
    rc, out = _run(cmd, timeout)
    if rc != 0 and sudo:
        rc, out = _run(["sudo", "-n", *cmd], timeout)
    return rc, out


def _show(unit: str, *props: str) -> dict[str, str]:
    rc, out = _systemctl("show", unit, *[f"-p{p}" for p in props], "--no-pager")
    res: dict[str, str] = {}
    for line in out.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            res[k] = v
    return res if rc == 0 else {"error": "systemctl_show_failed"}


# ── 1. session ───────────────────────────────────────────────────────────


def check_session(work_dir: Path, now: float | None = None) -> dict[str, Any]:
    """Jar presence, age and cookie expiry — names and times, never values.

    ABSENT and UNREADABLE are different facts and are reported apart.
    """
    now = time.time() if now is None else now
    jar = work_dir / "idpshow_session.json"
    if not jar.exists():
        return {"state": "absent", "path": str(jar)}
    try:
        data = json.loads(jar.read_text(encoding="utf-8"))
    except PermissionError:
        return {"state": "unreadable", "path": str(jar)}
    except (OSError, ValueError):
        return {"state": "malformed", "path": str(jar)}
    st = jar.stat()
    cookies = [c for c in (data.get("cookies") or []) if isinstance(c, dict)]
    named = [c for c in cookies if c.get("name") and not str(c["name"]).startswith("_comment")]
    expiries: list[dict[str, Any]] = []
    for c in named:
        exp = c.get("expires", c.get("expirationDate"))
        try:
            exp_f = float(exp) if exp not in (None, "", -1) else None
        except (TypeError, ValueError):
            exp_f = None
        expiries.append(
            {
                "name": str(c["name"]),
                "expiresAt": (
                    time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(exp_f)) if exp_f else None
                ),
                "expired": None if exp_f is None else exp_f <= now,
            }
        )
    expired = [e["name"] for e in expiries if e["expired"]]
    return {
        "state": "present" if named else "empty",
        "path": str(jar),
        "modifiedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(st.st_mtime)),
        "ageHours": round((now - st.st_mtime) / 3600.0, 1),
        "mode": oct(st.st_mode & 0o777),
        "cookieCount": len(named),
        "cookies": sorted(expiries, key=lambda e: e["name"]),
        "expiredCookies": sorted(expired),
    }


# ── 2. collector ─────────────────────────────────────────────────────────


def _scrub(line: str) -> str:
    return _TOKEN.sub("<redacted>", line)[:300]


def check_collector(journal_lines: int = 400, keep: int = 60) -> dict[str, Any]:
    timer = _show(
        f"{UNIT}.timer",
        "LoadState",
        "ActiveState",
        "UnitFileState",
        "LastTriggerUSec",
        "NextElapseUSecRealtime",
    )
    service = _show(
        f"{UNIT}.service",
        "LoadState",
        "Result",
        "ExecMainStatus",
        "ExecMainStartTimestamp",
        "ExecMainExitTimestamp",
        "ExecStart",
        "WorkingDirectory",
        "User",
    )
    cmd = [
        "journalctl",
        "-u",
        f"{UNIT}.service",
        "-n",
        str(journal_lines),
        "--no-pager",
        "-o",
        "short-iso",
    ]
    rc, out = _run(cmd)
    if rc != 0:
        rc, out = _run(["sudo", "-n", *cmd])
    lines = [_scrub(ln) for ln in out.splitlines() if _JOURNAL_KEEP.search(ln)] if rc == 0 else []
    return {
        "timer": {
            "installed": timer.get("LoadState") == "loaded",
            "enabled": timer.get("UnitFileState") == "enabled",
            "active": timer.get("ActiveState") == "active",
            "lastTrigger": timer.get("LastTriggerUSec"),
            "nextRun": timer.get("NextElapseUSecRealtime"),
        },
        "service": {
            "loaded": service.get("LoadState") == "loaded",
            "lastResult": service.get("Result"),
            "lastExit": service.get("ExecMainStatus"),
            "lastStart": service.get("ExecMainStartTimestamp"),
            "lastExitAt": service.get("ExecMainExitTimestamp"),
            "user": service.get("User"),
            "workingDirectory": service.get("WorkingDirectory"),
        },
        "journalReadable": rc == 0,
        "journal": lines[-keep:],
    }


def run_collection(timeout: int = 900) -> dict[str, Any]:
    rc, _out = _systemctl("start", f"{UNIT}.service", sudo=True, timeout=timeout)
    result = _show(f"{UNIT}.service", "Result", "ExecMainStatus", "ExecMainExitTimestamp")
    # Exit code + unit result only: systemctl's free text stays on the box.
    return {"startExit": rc, **result}


# ── 3. upstream ──────────────────────────────────────────────────────────


def _load_fetcher(app_dir: Path):
    spec = importlib.util.spec_from_file_location(
        "_idpshow_fetcher", app_dir / "scripts" / "fetch_idpshow.py"
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def content_fingerprint(rows: Iterable[Mapping[str, Any]]) -> str:
    """Order-independent hash of (name, position, rank) — the exact columns
    the fetcher commits, so "differs from committed" means the vendor's
    ranking content changed, not its column order or whitespace."""
    keyed = sorted(
        (str(r.get("name") or "").strip(), str(r.get("position") or ""), int(r.get("rank") or 0))
        for r in rows
    )
    return hashlib.sha256(json.dumps(keyed).encode("utf-8")).hexdigest()[:16]


def committed_rows(path: Path) -> list[dict[str, Any]] | None:
    if not path.exists():
        return None
    with path.open(newline="", encoding="utf-8") as fh:
        return [
            {"name": r.get("name"), "position": r.get("position"), "rank": r.get("rank")}
            for r in csv.DictReader(fh)
            if (r.get("rank") or "").strip().isdigit()
        ]


def probe_board(
    fetcher, session, app_dir: Path, key: str, spec: Mapping[str, Any]
) -> dict[str, Any]:
    url = fetcher.COMBINED_ARTICLE_URL if spec["combined"] else fetcher.ARTICLE_URL
    out: dict[str, Any] = {"article": url}
    try:
        html = fetcher._fetch_article_html(session, url)
    except Exception as exc:  # noqa: BLE001 — a finding, not a crash
        out["articleState"] = "fetch_failed"
        out["error"] = type(exc).__name__ + ": " + _scrub(str(exc))
        return out
    paywalled = fetcher._looks_paywalled(html)
    out["articleState"] = "paywalled" if paywalled else "readable"
    if paywalled:
        return out
    charts: list[dict[str, Any]] = []
    widest: tuple[int, list[dict]] | None = None
    for cid in fetcher._extract_all_chart_ids(html):
        info: dict[str, Any] = {"chartId": cid}
        version = fetcher._resolve_latest_version(session, cid)
        info["latestVersion"] = version
        if version:
            meta = fetcher._chart_metadata(session, cid, version)
            info["lastModifiedAt"] = meta.get("lastModifiedAt")
            info["publishedAt"] = meta.get("publishedAt")
            try:
                rows = fetcher._parse_dataset(fetcher._fetch_dataset_csv(session, cid, version))
            except Exception as exc:  # noqa: BLE001
                info["datasetError"] = type(exc).__name__
                rows = []
            info["rows"] = len(rows)
            if rows and (widest is None or len(rows) > widest[0]):
                widest = (len(rows), rows)
        charts.append(info)
    out["charts"] = charts
    committed = committed_rows(app_dir / spec["csv"])
    out["committedRows"] = None if committed is None else len(committed)
    if widest is not None:
        live_fp = content_fingerprint(widest[1])
        out["widestChartRows"] = widest[0]
        out["liveFingerprint"] = live_fp
        if committed is not None:
            out["committedFingerprint"] = content_fingerprint(committed)
            out["upstreamDiffersFromCommitted"] = live_fp != out["committedFingerprint"]
    return out


def check_upstream(app_dir: Path, work_dir: Path) -> dict[str, Any]:
    fetcher = _load_fetcher(app_dir)
    # Point the fetcher at the prod jar WITHOUT copying it anywhere.
    fetcher.SESSION_PATH = work_dir / "idpshow_session.json"
    try:
        session = fetcher._build_session()
    except SystemExit as exc:
        return {"state": "client_unavailable", "error": _scrub(str(exc))}
    return {key: probe_board(fetcher, session, app_dir, key, spec) for key, spec in BOARDS.items()}


# ── output safety ────────────────────────────────────────────────────────


def assert_public_safe(obj: Any, secrets: Iterable[str], player_names: Iterable[str]) -> None:
    """Refuse to print a cookie value or a player name anywhere in ``obj``."""
    blocked = [s for s in secrets if s and len(s) >= 8]
    names = [n for n in player_names if n and len(n) >= 6]
    text = json.dumps(obj, default=str)
    for s in blocked:
        if s in text:
            raise SystemExit("refusing to print: a cookie value reached the public report")
    for n in names:
        if n in text:
            raise SystemExit("refusing to print: a player name reached the public report")


def _cookie_values(work_dir: Path) -> list[str]:
    try:
        data = json.loads((work_dir / "idpshow_session.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [str(c.get("value") or "") for c in data.get("cookies") or [] if isinstance(c, dict)]


def _player_names(app_dir: Path) -> list[str]:
    names: list[str] = []
    for spec in BOARDS.values():
        rows = committed_rows(app_dir / spec["csv"]) or []
        names.extend(str(r["name"]) for r in rows if r.get("name"))
    return names


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--app-dir", default=os.getcwd())
    ap.add_argument(
        "--work-dir", default=os.environ.get("IDPSHOW_FETCH_WORK_DIR", str(DEFAULT_WORK_DIR))
    )
    ap.add_argument("--collect", action="store_true", help="start the fetch service once first")
    ap.add_argument("--skip-probe", action="store_true", help="no network probe of the vendor")
    args = ap.parse_args(argv)
    app_dir = Path(args.app_dir).resolve()
    work_dir = Path(args.work_dir)
    sys.path.insert(0, str(app_dir))

    report: dict[str, Any] = {"utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    rc, sha = _run(["git", "-C", str(app_dir), "rev-parse", "HEAD"])
    report["deployedCommit"] = sha.strip() if rc == 0 else None
    report["session"] = check_session(work_dir)
    if args.collect:
        report["collection"] = run_collection()
    report["collector"] = check_collector()
    if not args.skip_probe and report["session"].get("state") == "present":
        report["upstream"] = check_upstream(app_dir, work_dir)
    elif not args.skip_probe:
        report["upstream"] = {"state": "skipped_no_usable_session"}
    assert_public_safe(report, _cookie_values(work_dir), _player_names(app_dir))
    print(json.dumps(report, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
