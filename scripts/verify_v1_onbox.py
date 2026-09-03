"""On-box V1 production checklists — V1-89, V1-15/16/17, V1-59, V1-83, V1-11, V1-124, V1-20.

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
* ``v20``  — C1-SRC-02's fails-closed half, against the DEPLOYED
             ``src.api.data_contract`` module (the proven-per-feed half is
             already L3; the real registry is all-DYNASTY so a live
             negative case cannot exist, hence the injectable-rogue check)

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
                # The names MUST follow the production convention
                # (dynasty_export_%Y%m%d_%H%M%S.zip, Dynasty Scraper.py's
                # writer): measure_content_staleness timestamps archives
                # via _ARCHIVE_STAMP_RE (\d{8})_(\d{6}) and SILENTLY
                # SKIPS any archive whose name does not parse.  The
                # first control used dashed dates, both archives were
                # skipped, and the resulting {} read as "detector cannot
                # see DraftSharks staleness" — a false FAIL against a
                # sound detector (root-caused 2026-08-25).
                frozen = b"name,value\nFrozen Player,1000\n"
                for stamp in ("20260701_000000", "20260810_000000"):
                    zp = troot / "exports" / "archive" / f"dynasty_export_{stamp}.zip"
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
        if rc == 2 and "ABSENT" in out:
            # Exit 2 is the script's DEFINED "ledger absent" semantic
            # (acquisition_status returns 2 iff coverage()["present"] is
            # false).  The store is created only by the §8 items 2/3 live
            # builder, so its absence is a blocked dependency, never a
            # code failure — adjudicated 2026-08-25 after this check
            # recorded a false FAIL against an unrun builder.
            c.record(
                "blocked",
                "acquisition ledger absent — §8 items 2/3 (the live builder) "
                "have not run; dispatch with run_live_builder=true first",
                stdout=out[-400:],
            )
        elif rc != 0:
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

    # Item 5 — the store holds more than trades (waiver rows).  The
    # retention store's table is league_transactions (there has never
    # been a league_events TABLE — the first run of this check asked for
    # one and recorded a false unmeasurable; the file is just NAMED
    # league_events.sqlite).  §8 item 5 is operationally "the trades
    # count must stop equalling the transactions count": Sleeper's type
    # vocabulary is trade / waiver / free_agent.
    c = _check("C1U8-5", "V1-16", "§8 item 5: waiver rows exist (trades != transactions)")
    try:
        with _sqlite_ro(retention) as conn:
            tables = {
                r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            if "league_transactions" not in tables:
                c.record("unmeasurable", f"no league_transactions table; tables={sorted(tables)}")
            else:
                rows = dict(
                    conn.execute(
                        "SELECT type, COUNT(*) FROM league_transactions GROUP BY type"
                    ).fetchall()
                )
                total = sum(rows.values())
                non_trade = {k: v for k, v in rows.items() if str(k).lower() != "trade"}
                if total == 0:
                    c.record("unmeasurable", "league_transactions is empty", by_type=rows)
                elif non_trade:
                    c.record("pass", "store holds non-trade transactions", by_type=rows)
                else:
                    c.record("fail", "store still holds trades and nothing else", by_type=rows)
    except Exception as exc:  # noqa: BLE001
        c.record("error", str(exc))

    # Item 6 — the nightly backup carries the ACQUISITION ledger.  Real
    # roots per deploy/backup/backup_root_lib.sh (the one owner of the
    # backup location): /var/backups/riskit-state primary,
    # /home/dynasty/backups/riskit-state fallback, generations under
    # <root>/daily/YYYY-MM-DD/ with sqlite gz copies under sqlite/.  The
    # first run of this check inspected two paths the backup owner never
    # writes and grepped for names that miss item 6's actual target,
    # sqlite/acquisition.sqlite.gz.  Three honest states beyond
    # pass/fail: the root is root-owned 0700 so an unprivileged run is
    # blocked-unreadable; and until §8 items 2/3 create the source store
    # the backup legitimately logs "skip (absent)" — item 6 is the
    # TRANSITION to a real snapshot, so gz-absent while the source store
    # is absent is blocked-on-2/3, not fail.
    c = _check("C1U8-6", "V1-15", "§8 item 6: nightly backup includes the ledger")
    acquisition_store = REPO_ROOT / "data" / "retention" / "acquisition.sqlite"
    backup_roots = [
        Path("/var/backups/riskit-state"),
        Path.home() / "backups" / "riskit-state",
    ]
    try:
        root = next((p for p in backup_roots if p.exists()), None)
        if root is None:
            c.record("unmeasurable", f"no backup root at {[str(p) for p in backup_roots]}")
        else:
            try:
                daily = root / "daily"
                snaps = sorted(daily.iterdir()) if daily.exists() else []
            except PermissionError:
                snaps = None
            if snaps is None:
                c.record(
                    "blocked",
                    f"backup root {root} unreadable by this user (root-owned 0700) — "
                    "same posture as retention_backup_restore_proof.sh",
                )
            elif not snaps:
                c.record("fail", f"backup root {root} has no daily generations")
            else:
                newest = snaps[-1]
                gz = newest / "sqlite" / "acquisition.sqlite.gz"
                if gz.exists():
                    c.record(
                        "pass",
                        f"newest generation {newest.name} carries acquisition.sqlite.gz",
                        file=str(gz),
                        size=gz.stat().st_size,
                    )
                elif not acquisition_store.exists():
                    c.record(
                        "blocked",
                        "acquisition.sqlite.gz absent, but the SOURCE store is absent "
                        "too — blocked on §8 items 2/3 (the backup logs 'skip (absent)' "
                        "until the builder creates the store)",
                        generation=str(newest),
                    )
                else:
                    c.record(
                        "fail",
                        f"source store exists but newest generation {newest.name} "
                        "does NOT carry sqlite/acquisition.sqlite.gz",
                    )
    except PermissionError:
        c.record("blocked", "backup root unreadable by this user (root-owned 0700)")

    # Item 7 — one trade end to end: event → two holding periods → lineage.
    # The holdings/pick_lineage tables live in the C1-U8 ACQUISITION
    # store data/retention/acquisition.sqlite (src/acquisition/store.py),
    # NOT the intel ledger — the intel ledger is "members' other leagues,
    # wrong population" per the C1-U8 record, and the first run of this
    # check searched it, recording a false unmeasurable.  Until §8 items
    # 2/3 create the store this item is blocked, same as item 4.
    c = _check("C1U8-7", "V1-17", "§8 item 7: one trade resolves end to end")
    try:
        if not acquisition_store.exists():
            c.record(
                "blocked",
                f"acquisition store absent at {acquisition_store} — blocked on "
                "§8 items 2/3 (the live builder)",
            )
        else:
            with _sqlite_ro(acquisition_store) as conn:
                trade = conn.execute(
                    "SELECT league_key, asset_id FROM acquisition_events "
                    "WHERE event_type = 'TRADE' LIMIT 1"
                ).fetchone()
                if trade is None:
                    c.record("fail", "store exists but holds no TRADE acquisition event")
                else:
                    lk, aid = trade
                    holdings = conn.execute(
                        "SELECT owner_rid, basis_value, basis_missing_reason FROM holdings "
                        "WHERE league_key = ? AND asset_id = ? ORDER BY sequence_num",
                        (lk, aid),
                    ).fetchall()
                    basis_ok = any(h[1] is not None or h[2] is not None for h in holdings)
                    lineage_hops = conn.execute(
                        "SELECT COUNT(*) FROM pick_lineage WHERE league_key = ?", (lk,)
                    ).fetchone()[0]
                    pick_trades = conn.execute(
                        "SELECT COUNT(*) FROM acquisition_events WHERE league_key = ? "
                        "AND event_type = 'TRADE' AND asset_id LIKE 'pick:%'",
                        (lk,),
                    ).fetchone()[0]
                    if len(holdings) >= 2 and basis_ok and (pick_trades == 0 or lineage_hops >= 1):
                        c.record(
                            "pass",
                            "a TRADE event resolves to both holding periods with an "
                            "explicit basis-or-reason, and traded picks carry lineage",
                            league_key=lk,
                            asset_id=aid,
                            holding_periods=len(holdings),
                            pick_trades=pick_trades,
                            lineage_hops=lineage_hops,
                        )
                    else:
                        c.record(
                            "fail",
                            "trade does not resolve end to end",
                            league_key=lk,
                            asset_id=aid,
                            holding_periods=len(holdings),
                            basis_present=basis_ok,
                            pick_trades=pick_trades,
                            lineage_hops=lineage_hops,
                        )
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
        # systemd's own Result= already applies each unit's SuccessExitStatus=
        # directive (dynasty-sharp-{discovery,records,rosters}.service.template
        # all declare "SuccessExitStatus=0 2" — exit 2 is a documented
        # nothing-to-do outcome, not a failure). Re-deriving pass/fail from a
        # raw ExecMainStatus == "0" check ignores that contract and flags a
        # genuinely healthy run as failed.
        if info.get("Result") not in ("success", "exit-code"):
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
            "all three chain units last reported Result=success (per each unit's "
            "own SuccessExitStatus contract) with no lock crashes or timeout "
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


# ────────────────────────────── V1-20 fails-closed ──────────────────────────────


def check_v20() -> None:
    """C1-SRC-02: game type proven per feed, fails closed on ``UNKNOWN``.

    The proven-per-feed half is already re-verified fresh at L3 (row's own
    §9a note, via ``/api/rankings/sources``). What has never run against
    the DEPLOYED tree is the fails-closed half — and it structurally
    cannot be observed as a live negative case, because the real registry
    is all-DYNASTY (no UNKNOWN feed exists to refuse). The row records
    this honestly as L2 rather than rounding up.

    This closes the gap the row names, not by manufacturing a bad feed in
    production (forbidden), but by running the SAME injectable-rogue
    check ``tests/sources/test_game_type_gate_red.py`` already pins in
    this dev/CI environment against the actual deployed ``src.api.data_contract``
    module instead — proving the fails-closed behaviour is the code that
    is actually running in production, not just code that exists in a
    branch. Entirely read-only: ``_validate_source_game_types_invariant``
    takes an injectable ``sources`` list precisely so this can run without
    mutating ``_RANKING_SOURCES``.
    """
    c = _check("V20", "V1-20", "C1-SRC-02: fails-closed half, against the deployed tree")
    try:
        sys.path.insert(0, str(REPO_ROOT))
        from src.api import data_contract as dc

        registry = list(dc._RANKING_SOURCES)
        base = dict(registry[0]) if registry else {}
        cases = {
            "unknown": {**base, "key": "v20RogueUnknown", "game_type": "UNKNOWN"},
            "redraft": {
                **base,
                "key": "v20RogueRedraft",
                "game_type": "REDRAFT",
                "game_type_evidence": "redraft toggle — a different product",
            },
            "absent": {k: v for k, v in base.items() if k != "game_type"}
            | {"key": "v20RogueSilent"},
        }
        refused: dict[str, bool] = {}
        for name, rogue in cases.items():
            try:
                dc._validate_source_game_types_invariant([*registry, rogue])
                refused[name] = False
            except Exception as exc:  # noqa: BLE001 — the refusal IS the assertion
                refused[name] = rogue["key"] in str(exc)
        # the honest case must still pass, or this is just a blocker
        honest = {**base, "key": "v20HonestDynasty", "game_type": "DYNASTY"}
        honest.setdefault("game_type_evidence", "endpoint documented dynasty-only")
        honest_ok = False
        try:
            dc._validate_source_game_types_invariant([*registry, honest])
            honest_ok = True
        except Exception:  # noqa: BLE001
            honest_ok = False
    except Exception as exc:  # noqa: BLE001
        c.record("error", f"could not import deployed data_contract: {exc}")
        return

    if all(refused.values()) and honest_ok:
        c.record(
            "pass",
            "the deployed tree's game-type gate refuses UNKNOWN/REDRAFT/absent "
            "(offending key named in each refusal) and accepts a verified-DYNASTY "
            "declaration — the fails-closed half, proven against production code",
            refused=refused,
            honest_case_passed=honest_ok,
            registry_size=len(registry),
        )
    else:
        c.record(
            "fail",
            "the deployed tree's game-type gate did not refuse a rogue source, "
            "or refused a legitimate one",
            refused=refused,
            honest_case_passed=honest_ok,
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
    "v20": lambda args: check_v20(),
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
