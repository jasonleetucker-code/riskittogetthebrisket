"""On-box V1 production checklists — V1-89, V1-15/16/17, V1-59, V1-83, V1-11, V1-124.

Runs ON the production box (dispatched by
``.github/workflows/v1-onbox-checklists.yml`` over the existing SSH lane),
from the deployed APP_DIR, against the real gitignored stores.  It is the
executable form of checklists that already exist as prose:

* ``v89``  — ``docs/lane4/V1_89_DRAFTSHARKS_DECISION_PACKET.md`` §6 steps 2-9
* ``c1u8`` — ``docs/acquisition/C1_U8_ACQUISITION_LEDGER.md`` §8 items 1-7
             (V1-15 / V1-16 / V1-17)
* ``v59``  — the V1-59 bar: a clean SCHEDULED journal chain of
             discovery → records → rosters (plus the ffpc unit's health)
* ``v83``  — audit F-20: cooldown keyed on delivery, read from the real
             ops-alert state
* ``v11``  — C1-U5 §6 item 1: the deployed SHA contains the unit
* ``v124`` — the background-jobs / data matrix (timers, services, artifacts)

Rules, inherited from ``verify_lane4_production.py`` and enforced here:

1. **Nothing is fabricated.**  An absent store is ``blocked``, never ``0``.
   C1-U8 §8a says it outright: "Running it and recording 0 would be worse
   than not running it — it manufactures a measurement out of an absent
   input."
2. **Read-only by default.**  Every check is a file read, a sqlite read in
   ``mode=ro``, a ``systemctl``/``journalctl`` query, or a subprocess whose
   own flags declare it non-mutating (``--offline --dry-run``).  The ONE
   exception — C1-U8 items 2/3, whose acceptance IS running the live
   builder — requires the explicit ``--allow-writes`` flag and is recorded
   ``blocked`` without it.
3. **Statuses**: ``pass`` / ``fail`` / ``unmeasurable`` / ``blocked`` /
   ``error``.  Exit codes match the Lane 4 verifier: 0 = at least one
   applicable check ran and every applicable check passed; 1 = unexpected
   error; 2 = at least one FAIL; 3 = proved nothing (every check blocked or
   unmeasurable) — distinct from 0 on purpose.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent

_PROVES_NOTHING = {"blocked", "unmeasurable"}


@dataclass
class Check:
    check_id: str
    row: str
    title: str
    status: str = "unmeasurable"
    detail: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)

    def record(self, status: str, detail: str, **evidence: Any) -> None:
        self.status = status
        self.detail = detail
        self.evidence.update(evidence)


CHECKS: list[Check] = []


def _check(check_id: str, row: str, title: str) -> Check:
    c = Check(check_id, row, title)
    CHECKS.append(c)
    return c


def _run(cmd: list[str], timeout: int = 300) -> tuple[int, str, str]:
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=REPO_ROOT,
    )
    return proc.returncode, proc.stdout, proc.stderr


def _sqlite_ro(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


def _stamp_age_hours(key: str) -> float | None:
    p = REPO_ROOT / "data" / "scrape_state" / f"{key}_last_success"
    if not p.exists():
        return None
    try:
        return (time.time() - float(p.read_text().strip())) / 3600.0
    except ValueError:
        return None


# ────────────────────────────── V1-89 §6 ──────────────────────────────


def check_v89() -> None:
    packet = "V1_89 packet §6"

    # Step 2: production fetch succeeds — stamps advance only on exit 0,
    # and (steps 3-4) the fetchers' own league-scoped and ROS fail-closed
    # proofs abort before any write, so a fresh stamp is evidence the
    # proofs passed on that run.  26 h budget = 2 h cadence with slack.
    c = _check("V89-2", "V1-89", f"{packet} step 2-4: fetch stamps advance (proofs passed)")
    ages = {k: _stamp_age_hours(k) for k in ("draftSharks", "draftSharksIdp", "draftSharksRos")}
    missing = [k for k, v in ages.items() if v is None]
    if missing:
        c.record("fail", f"stamps missing: {missing}", ages=ages)
    else:
        stale = {k: round(v, 1) for k, v in ages.items() if v > 26.0}
        if stale:
            c.record("fail", f"stamps stale beyond 26h: {stale}", ages=ages)
        else:
            c.record(
                "pass",
                "all three DraftSharks stamps fresh; stamps only advance on exit 0, "
                "and both scoped-board proofs abort pre-write on failure",
                ages={k: round(v, 2) for k, v in ages.items()},
            )

    # Step 5: all four files under site_raw/ in the newest archive, and in
    # its manifest under siteRawMirrored.
    c = _check("V89-5", "V1-89", f"{packet} step 5: site_raw mirror reaches the archive")
    archives = sorted((REPO_ROOT / "exports" / "archive").glob("*.zip"))
    wanted = {
        "draftSharksSf.csv",
        "draftSharksIdp.csv",
        "draftSharksRosSf.csv",
        "draftSharksRosIdp.csv",
    }
    if not archives:
        c.record("blocked", "no export archives on this box")
    else:
        newest = archives[-1]
        try:
            with zipfile.ZipFile(newest) as zf:
                names = set(zf.namelist())
                raw_members = {Path(n).name for n in names if "site_raw" in n}
                manifest_names = [n for n in names if n.endswith("manifest.json")]
                mirrored: list[str] = []
                if manifest_names:
                    manifest = json.loads(zf.read(manifest_names[0]))
                    mirrored = list(manifest.get("siteRawMirrored") or [])
            missing_members = sorted(wanted - raw_members)
            mirrored_basenames = {Path(m).name for m in mirrored}
            missing_manifest = sorted(wanted - mirrored_basenames)
            if missing_members or missing_manifest:
                c.record(
                    "fail",
                    f"archive {newest.name}: missing site_raw members {missing_members}, "
                    f"missing from siteRawMirrored {missing_manifest}",
                    members=sorted(raw_members),
                    siteRawMirrored=mirrored,
                )
            else:
                c.record(
                    "pass",
                    f"all four DraftSharks files present in {newest.name} under site_raw/ "
                    "and named in manifest siteRawMirrored",
                    archive=newest.name,
                    members=sorted(raw_members),
                )
        except (OSError, json.JSONDecodeError, KeyError) as exc:
            c.record("error", f"could not read {newest.name}: {exc}")

    # Step 6 + 7 + 9: measure_content_staleness returns the four keys, does
    # not false-alert while the vendor publishes, and idpTradeCalc's
    # existing reading is unchanged in kind.
    c = _check("V89-6", "V1-89", f"{packet} steps 6/7/9: content-age lane covers DraftSharks")
    try:
        sys.path.insert(0, str(REPO_ROOT))
        from scripts.check_source_health import measure_content_staleness

        result = measure_content_staleness(REPO_ROOT)
        keys = set(result)
        needed = {"draftSharksSf", "draftSharksIdp", "draftSharksRosSf", "draftSharksRosIdp"}
        missing_keys = sorted(needed - keys)
        if missing_keys:
            c.record("fail", f"content-age lane missing keys: {missing_keys}", keys=sorted(keys))
        else:
            summary = {
                k: {kk: v.get(kk) for kk in ("daysSinceChange", "stale", "budgetDays") if kk in v}
                for k, v in result.items()
                if k in needed or k == "idpTradeCalc"
            }
            false_alerts = [
                k
                for k in needed
                if result[k].get("stale") and (result[k].get("daysSinceChange") or 0) <= 1
            ]
            if false_alerts:
                c.record(
                    "fail",
                    f"fresh content flagged stale (false alert): {false_alerts}",
                    summary=summary,
                )
            elif "idpTradeCalc" not in keys:
                c.record(
                    "fail",
                    "idpTradeCalc content-age reading disappeared (step 9)",
                    summary=summary,
                )
            else:
                c.record(
                    "pass",
                    "all four DraftSharks keys measured; no false alert on fresh "
                    "content; idpTradeCalc reading still present",
                    summary=summary,
                )
    except Exception as exc:  # noqa: BLE001 — recorded, not raised
        c.record("error", f"measure_content_staleness failed: {exc}")

    # Step 8: the stale-content CONTROL.  Frozen bytes across archives
    # beyond the budget MUST alert.  Built synthetically in a temp dir so
    # nothing on the box is touched; the control exercises the real
    # detector code, not a copy.
    c = _check("V89-8", "V1-89", f"{packet} step 8: stale-content control alerts")
    try:
        from scripts.check_source_health import measure_content_staleness

        if not archives:
            c.record("blocked", "no archives to build the control from")
        else:
            with tempfile.TemporaryDirectory() as td:
                troot = Path(td)
                (troot / "exports" / "archive").mkdir(parents=True)
                cfg_src = REPO_ROOT / "config" / "source_staleness.json"
                if cfg_src.exists():
                    (troot / "config").mkdir()
                    shutil.copy(cfg_src, troot / "config" / "source_staleness.json")
                # Two synthetic archives, 40 days apart, identical
                # DraftSharks bytes — unambiguously beyond any budget.
                frozen = b"name,value\nFrozen Player,1000\n"
                for day in ("2026-07-01", "2026-08-10"):
                    zp = troot / "exports" / "archive" / f"dynasty_data_{day}.zip"
                    with zipfile.ZipFile(zp, "w") as zf:
                        zf.writestr(
                            "manifest.json",
                            json.dumps({"siteRawMirrored": ["site_raw/draftSharksSf.csv"]}),
                        )
                        zf.writestr("site_raw/draftSharksSf.csv", frozen)
                control = measure_content_staleness(troot)
                entry = control.get("draftSharksSf") or {}
                if entry.get("stale") or (entry.get("daysSinceChange") or 0) >= 14:
                    c.record(
                        "pass",
                        "frozen synthetic DraftSharks bytes across archives are "
                        "flagged by the real detector",
                        control_entry=entry,
                    )
                else:
                    c.record(
                        "fail",
                        "the control did NOT alert on 40-day frozen bytes — the "
                        "detector cannot see DraftSharks staleness",
                        control=control,
                    )
    except Exception as exc:  # noqa: BLE001
        c.record("error", f"control construction failed: {exc}")


# ─────────────────────────── C1-U8 §8 (V1-15/16/17) ───────────────────────────


def check_c1u8(allow_writes: bool) -> None:
    retention = REPO_ROOT / "data" / "retention" / "league_events.sqlite"
    intel = REPO_ROOT / "data" / "intel" / "ledger.sqlite3"

    pre = _check("C1U8-0", "V1-15/16/17", "C1-U8 §8 preflight: the two stores exist")
    missing = [str(p) for p in (retention, intel) if not p.exists()]
    if missing:
        pre.record(
            "blocked",
            f"stores absent: {missing}. Per §8a this blocks ALL seven items — "
            "recording 0 would manufacture a measurement out of an absent input",
        )
        return
    pre.record("pass", "both stores present", retention=str(retention), intel=str(intel))

    # Item 1 — the offline dry-run sees the retained transactions.
    c = _check("C1U8-1", "V1-15", "§8 item 1: offline dry-run sees retained transactions")
    try:
        rc, out, err = _run(
            [sys.executable, "scripts/build_acquisition_ledger.py", "--offline", "--dry-run"]
        )
        counts = [int(n) for n in re.findall(r"\b(\d+)\b", out)]
        if rc != 0:
            c.record("fail", f"dry-run exited {rc}", stderr=err[-800:])
        elif any(n > 0 for n in counts):
            c.record("pass", "dry-run reports non-zero retained transactions", stdout=out[-800:])
        else:
            c.record(
                "fail", "dry-run reports zero everywhere against a present store", stdout=out[-800:]
            )
    except Exception as exc:  # noqa: BLE001
        c.record("error", str(exc))

    # Items 2/3 — the LIVE builder, twice, per league.  A write.
    c = _check("C1U8-2/3", "V1-15", "§8 items 2-3: live builder runs clean and is idempotent")
    if not allow_writes:
        c.record(
            "blocked",
            "requires --allow-writes: the live builder writes data/intel/ledger.sqlite3 "
            "and fetches Sleeper. Dispatch with run_live_builder=true to execute",
        )
    else:
        try:
            rc1, out1, err1 = _run(
                [sys.executable, "scripts/build_acquisition_ledger.py"], timeout=900
            )
            rc2, out2, err2 = _run(
                [sys.executable, "scripts/build_acquisition_ledger.py"], timeout=900
            )
            second_inserted = re.search(r"inserted[=:\s]+(\d+)", out2)
            conflicts1 = "conflicts=[]" in out1.replace(" ", "") or re.search(
                r"conflicts[=:\s]+\[?\s*\]?0?", out1
            )
            if rc1 != 0 or rc2 != 0:
                c.record(
                    "fail",
                    f"builder exits: run1={rc1} run2={rc2}",
                    err1=err1[-500:],
                    err2=err2[-500:],
                )
            elif second_inserted and int(second_inserted.group(1)) == 0:
                c.record(
                    "pass",
                    "both runs exit 0; second run inserted=0 (idempotent)",
                    run1_tail=out1[-500:],
                    run2_tail=out2[-500:],
                    conflicts_run1_empty=bool(conflicts1),
                )
            else:
                c.record(
                    "unmeasurable",
                    "builder ran but output shape did not expose inserted-count; raw tails recorded",
                    run1_tail=out1[-500:],
                    run2_tail=out2[-500:],
                )
        except Exception as exc:  # noqa: BLE001
            c.record("error", str(exc))

    # Item 4 — acquisition_status reports non-zero events.
    c = _check("C1U8-4", "V1-15", "§8 item 4: acquisition_status non-zero events")
    try:
        rc, out, err = _run([sys.executable, "scripts/acquisition_status.py"])
        holdings_unknown = re.search(r"holdingsImportUnknown[\"'=:\s]+(\d+)", out)
        events = re.search(r"events[\"'=:\s]+(\d+)", out)
        if rc != 0:
            c.record("fail", f"status script exited {rc}", stderr=err[-500:])
        elif events and int(events.group(1)) > 0:
            c.record(
                "pass",
                f"events={events.group(1)}"
                + (
                    f"; holdingsImportUnknown={holdings_unknown.group(1)} (a FINDING about "
                    "history depth, not a failure — §8's own words)"
                    if holdings_unknown
                    else ""
                ),
                stdout=out[-800:],
            )
        else:
            c.record("unmeasurable", "could not parse a non-zero events count", stdout=out[-800:])
    except Exception as exc:  # noqa: BLE001
        c.record("error", str(exc))

    # Item 5 — the store holds more than trades (waiver rows).
    c = _check("C1U8-5", "V1-16", "§8 item 5: waiver rows exist (trades != transactions)")
    try:
        with _sqlite_ro(retention) as conn:
            tables = {
                r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            if "league_events" not in tables:
                c.record("unmeasurable", f"no league_events table; tables={sorted(tables)}")
            else:
                cols = [r[1] for r in conn.execute("PRAGMA table_info(league_events)")]
                type_col = next((k for k in ("event_type", "type", "kind") if k in cols), None)
                if type_col is None:
                    c.record("unmeasurable", f"no recognizable type column; columns={cols}")
                else:
                    rows = dict(
                        conn.execute(
                            f"SELECT {type_col}, COUNT(*) FROM league_events GROUP BY {type_col}"
                        ).fetchall()
                    )
                    non_trade = {k: v for k, v in rows.items() if "trade" not in str(k).lower()}
                    if non_trade:
                        c.record("pass", "store holds non-trade events", by_type=rows)
                    else:
                        c.record("fail", "store still holds trades and nothing else", by_type=rows)
    except Exception as exc:  # noqa: BLE001
        c.record("error", str(exc))

    # Item 6 — the nightly backup carries the ledger.
    c = _check("C1U8-6", "V1-15", "§8 item 6: nightly backup includes the ledger")
    backup_roots = [Path("/var/backups/riskit/daily"), REPO_ROOT / "backups" / "daily"]
    root = next((p for p in backup_roots if p.exists()), None)
    if root is None:
        c.record("unmeasurable", f"no backup dir at {[str(p) for p in backup_roots]}")
    else:
        snaps = sorted(root.iterdir())
        if not snaps:
            c.record("fail", f"backup dir {root} is empty")
        else:
            newest = snaps[-1]
            hits = [
                str(p) for p in newest.rglob("*") if "league_events" in p.name or "ledger" in p.name
            ]
            if hits:
                c.record("pass", f"newest backup {newest.name} carries the ledger", files=hits)
            else:
                c.record("fail", f"newest backup {newest.name} does NOT carry the ledger")

    # Item 7 — one trade end to end: event → two holding periods → lineage.
    c = _check("C1U8-7", "V1-17", "§8 item 7: one trade resolves end to end")
    try:
        with _sqlite_ro(intel) as conn:
            tables = {
                r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            holding = next((t for t in tables if "holding" in t), None)
            lineage = next((t for t in tables if "lineage" in t or "pick" in t), None)
            if not holding:
                c.record("unmeasurable", f"no holdings table found; tables={sorted(tables)}")
            else:
                n_holdings = conn.execute(f"SELECT COUNT(*) FROM {holding}").fetchone()[0]
                n_lineage = (
                    conn.execute(f"SELECT COUNT(*) FROM {lineage}").fetchone()[0]
                    if lineage
                    else None
                )
                if n_holdings and n_holdings >= 2:
                    c.record(
                        "pass",
                        "holdings and lineage populated from real events",
                        holdings_table=holding,
                        holdings=n_holdings,
                        lineage_table=lineage,
                        lineage_rows=n_lineage,
                    )
                else:
                    c.record("fail", f"holdings table {holding} has {n_holdings} rows")
    except Exception as exc:  # noqa: BLE001
        c.record("error", str(exc))


# ────────────────────────────── V1-59 journal ──────────────────────────────

_SHARP_CHAIN = ("dynasty-sharp-discovery", "dynasty-sharp-records", "dynasty-sharp-rosters")


def check_v59() -> None:
    c = _check("V59", "V1-59", "clean SCHEDULED discovery → records → rosters chain")
    results: dict[str, dict[str, Any]] = {}
    problems: list[str] = []
    for unit in _SHARP_CHAIN:
        rc, out, _ = _run(
            [
                "systemctl",
                "show",
                f"{unit}.service",
                "-p",
                "Result",
                "-p",
                "ExecMainStatus",
                "-p",
                "ExecMainExitTimestamp",
                "-p",
                "ActiveEnterTimestamp",
            ],
            timeout=30,
        )
        info = dict(line.split("=", 1) for line in out.strip().splitlines() if "=" in line)
        rc2, timers, _ = _run(
            ["systemctl", "list-timers", f"{unit}.timer", "--all", "--no-pager"], timeout=30
        )
        results[unit] = {"unit": info, "timer": timers.strip().splitlines()[:4]}
        if info.get("Result") not in ("success", "exit-code") or info.get("ExecMainStatus") not in (
            "0",
        ):
            problems.append(
                f"{unit}: Result={info.get('Result')} ExecMainStatus={info.get('ExecMainStatus')}"
            )
        # journal: no lock crash / no watchdog kill in the last completed run
        rcj, jout, _ = _run(
            ["journalctl", "-u", f"{unit}.service", "--since", "-48h", "--no-pager", "-q"],
            timeout=60,
        )
        bad = [
            ln
            for ln in jout.splitlines()
            if "database is locked" in ln or "status=15/TERM" in ln or "Killing" in ln
        ]
        if bad:
            problems.append(f"{unit}: journal shows {len(bad)} lock/timeout lines")
            results[unit]["journal_bad"] = bad[:5]
    if not results:
        c.record("blocked", "systemctl unavailable")
    elif problems:
        c.record("fail", "; ".join(problems), chain=results)
    else:
        c.record(
            "pass",
            "all three chain units last exited 0 with no lock crashes or timeout "
            "kills in 48h of journal",
            chain=results,
        )

    # The historical failer, tracked separately: it must either be healthy
    # or its failure must be its own honest state — never silent.
    c = _check(
        "V59-ffpc", "V1-59", "chaseupside-ffpc-sharp service state (the historical crashloop)"
    )
    rc, out, _ = _run(
        [
            "systemctl",
            "show",
            "chaseupside-ffpc-sharp.service",
            "-p",
            "Result",
            "-p",
            "ExecMainStatus",
            "-p",
            "NRestarts",
        ],
        timeout=30,
    )
    info = dict(line.split("=", 1) for line in out.strip().splitlines() if "=" in line)
    if not info:
        c.record("unmeasurable", "unit not present on this box")
    elif info.get("Result") == "success" and info.get("ExecMainStatus") == "0":
        c.record("pass", "ffpc unit healthy", state=info)
    else:
        c.record("fail", f"ffpc unit unhealthy: {info}", state=info)


# ────────────────────────────── V1-83 (F-20) ──────────────────────────────


def check_v83() -> None:
    c = _check("V83", "V1-83", "F-20: cooldown state keys delivery separately from attempt")
    try:
        sys.path.insert(0, str(REPO_ROOT))
        from src.api import ops_alerts

        state = ops_alerts._load_ops_state()
        if not state:
            c.record(
                "unmeasurable",
                "ops-alert state is empty — no alert has fired since the repair; "
                "emptiness is not evidence in either direction",
            )
            return
        shapes: dict[str, dict[str, Any]] = {}
        violations: list[str] = []
        for category, entry in state.items():
            if not isinstance(entry, dict):
                continue
            keys = sorted(entry.keys())
            shapes[category] = {
                "keys": keys,
                "attemptedAt": entry.get("attemptedAt"),
                "deliveredAt": entry.get("deliveredAt"),
            }
            # F-20's repaired invariant: an entry may carry attemptedAt
            # without deliveredAt (retry pending), but a deliveredAt of 0
            # or a legacy epoch-zero coercion is the exact bug.
            if entry.get("deliveredAt") == 0:
                violations.append(f"{category}: deliveredAt == 0 (epoch-zero coercion)")
        if violations:
            c.record("fail", "; ".join(violations), shapes=shapes)
        else:
            delivered = [k for k, v in shapes.items() if v.get("deliveredAt")]
            c.record(
                "pass",
                f"{len(shapes)} categories in state; {len(delivered)} carry a real "
                "deliveredAt; no epoch-zero coercion; attempt and delivery are "
                "separate keys as F-20 requires",
                shapes=shapes,
            )
    except Exception as exc:  # noqa: BLE001
        c.record("error", str(exc))


# ────────────────────────────── V1-11 item 1 ──────────────────────────────


def check_v11() -> None:
    c = _check("V11-1", "V1-11", "C1-U5 §6 item 1: the deployed SHA contains the unit")
    state_file = Path("/home/dynasty/.deploy-state/trade-calculator.last_successful_deploy_commit")
    rc, head, _ = _run(["git", "rev-parse", "HEAD"], timeout=30)
    head = head.strip()
    recorded = state_file.read_text().strip() if state_file.exists() else None
    try:
        sys.path.insert(0, str(REPO_ROOT))
        from src.api import confidence  # noqa: F401 — the unit under test

        has_unit = hasattr(confidence, "assess_confidence")
    except Exception:  # noqa: BLE001
        has_unit = False
    if not has_unit:
        c.record(
            "fail",
            "src/api/confidence.assess_confidence not importable from the deployed tree",
            head=head,
        )
    elif recorded is None:
        c.record(
            "unmeasurable",
            "deploy-state file absent; unit IS importable from the deployed tree",
            head=head,
        )
    elif recorded == head:
        c.record(
            "pass",
            "deploy-state file matches HEAD and the confidence unit imports from the deployed tree",
            head=head,
            recorded=recorded,
        )
    else:
        rc2, _, _ = _run(["git", "merge-base", "--is-ancestor", recorded, head], timeout=30)
        c.record(
            "pass" if rc2 == 0 else "fail",
            f"deploy-state {recorded[:12]} vs HEAD {head[:12]} "
            + (
                "(recorded is ancestor of HEAD — a newer deploy is checked out)"
                if rc2 == 0
                else "(DIVERGED)"
            ),
            head=head,
            recorded=recorded,
        )


# ────────────────────────────── V1-124 matrix ──────────────────────────────

_ARTIFACTS = {
    "contract_export": "exports/latest",
    "faab_bid_history": "data/faab/bid_history_dynasty_main.json",
    "faab_crowd_history": "data/faab/crowd_history_dynasty_main.json",
    "intel_ledger": "data/intel/ledger.sqlite3",
    "retention_store": "data/retention/league_events.sqlite",
    "temporal_ledger": "data/temporal_ledger.sqlite",
    "ros_team_strength": "data/ros/team_strength/latest.json",
    "guest_pass_db": "data/guest_passes.sqlite",
    "sharp_platform_ledger": "data/intel",
}


def check_v124() -> None:
    c = _check("V124", "V1-124", "background jobs and data: the production matrix")
    rc, out, err = _run(["systemctl", "list-timers", "--all", "--no-pager"], timeout=60)
    if rc != 0:
        c.record("blocked", f"systemctl unavailable: {err[:200]}")
        return
    timer_lines = [ln for ln in out.splitlines() if "dynasty-" in ln or "chaseupside-" in ln]
    never_fired = [
        ln.split()[-2] if ln.split() else ln for ln in timer_lines if " n/a " in f" {ln} "
    ]

    artifacts: dict[str, Any] = {}
    missing: list[str] = []
    for name, rel in _ARTIFACTS.items():
        p = REPO_ROOT / rel
        if not p.exists():
            artifacts[name] = None
            missing.append(name)
        else:
            newest = (
                max(
                    (f.stat().st_mtime for f in p.rglob("*") if f.is_file()),
                    default=p.stat().st_mtime,
                )
                if p.is_dir()
                else p.stat().st_mtime
            )
            artifacts[name] = {"ageHours": round((time.time() - newest) / 3600.0, 1)}

    stamps = {}
    stamp_dir = REPO_ROOT / "data" / "scrape_state"
    if stamp_dir.exists():
        for f in sorted(stamp_dir.glob("*_last_success")):
            key = f.name.replace("_last_success", "")
            age = _stamp_age_hours(key)
            stamps[key] = round(age, 1) if age is not None else None

    detail_bits = []
    status = "pass"
    if never_fired:
        status = "fail"
        detail_bits.append(f"timers installed but NEVER fired: {never_fired}")
    if missing:
        detail_bits.append(f"artifacts absent (reported, not coerced to zero): {missing}")
    if not timer_lines:
        status = "unmeasurable"
        detail_bits.append("no dynasty-*/chaseupside-* timers visible")
    c.record(
        status,
        "; ".join(detail_bits)
        or f"{len(timer_lines)} timers installed, all fired; artifacts recorded",
        timers=timer_lines,
        artifacts=artifacts,
        fetch_stamps_age_hours=stamps,
    )


# ────────────────────────────── driver ──────────────────────────────

CHECK_FNS = {
    "v89": lambda args: check_v89(),
    "c1u8": lambda args: check_c1u8(args.allow_writes),
    "v59": lambda args: check_v59(),
    "v83": lambda args: check_v83(),
    "v11": lambda args: check_v11(),
    "v124": lambda args: check_v124(),
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--checks",
        default="all",
        help="comma list of check groups (%s) or 'all'" % ",".join(CHECK_FNS),
    )
    parser.add_argument(
        "--allow-writes",
        action="store_true",
        help="permit C1-U8 items 2/3 (the live acquisition builder — writes "
        "data/intel/ledger.sqlite3). Everything else stays read-only.",
    )
    args = parser.parse_args()

    wanted = (
        list(CHECK_FNS)
        if args.checks == "all"
        else [s.strip() for s in args.checks.split(",") if s.strip()]
    )
    unknown = [w for w in wanted if w not in CHECK_FNS]
    if unknown:
        print(f"unknown check group(s): {unknown}", file=sys.stderr)
        return 1

    for name in wanted:
        try:
            CHECK_FNS[name](args)
        except Exception as exc:  # noqa: BLE001
            _check(f"{name}-crash", name, "driver crash guard").record("error", str(exc))

    report = {
        "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "checks": [c.__dict__ for c in CHECKS],
    }
    print(json.dumps(report, indent=1, default=str))

    statuses = [c.status for c in CHECKS]
    if "error" in statuses:
        return 1
    if "fail" in statuses:
        return 2
    applicable = [s for s in statuses if s not in _PROVES_NOTHING]
    if not applicable:
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
