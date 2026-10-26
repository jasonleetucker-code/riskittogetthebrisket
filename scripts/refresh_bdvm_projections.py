"""Prod-side BDVM projection snapshot refresh (baseline + IDP Show).

Composes the two existing snapshot producers into the one command the
``dynasty-bdvm-refresh`` systemd timer runs weekly on the VPS:

1. ``scripts/bdvm_build_baseline.py`` — the BDVM §8.3 reconstructed
   baseline (public nflverse data, no credentials).  It carries prior
   real (non-proxy) records forward, so a baseline rebuild can never
   downgrade the serving board from real projections back to proxies.
2. ``scripts/fetch_clay_projections.py`` — Mike Clay's ESPN guide
   (public CDN PDF, no credentials; soft-skips if poppler-utils is
   missing).  The first real OFFENSE source, plus a second IDP feed.
3. ``scripts/fetch_idpshow_projections.py`` — The IDP Show real IDP
   projections (authenticated via ``idpshow_session.json``).

Real records supersede baseline proxies per player at merge, so order
matters: baseline first, real sources after.  Clay and IDP Show
records coexist (shared supersede policy replaces only a source's OWN
prior run), giving defenders covered by both a two-source consensus.

Both producers treat "today's snapshot already exists" as a no-op
success, so boot-time catch-up runs and manual reruns stay green.

WHY A PROD-SIDE TIMER AND NOT CI: ``GET /api/bdvm/values`` reads the
latest snapshot under ``data/bdvm/projections/<season>/`` — a LOCAL
file on the box serving the API (``data/`` is gitignored repo-wide).
The producer has to run where the reader lives, exactly like the
player-context refresh (see dynasty-playerctx-refresh.service.template).

Session cookies: the fetcher reads only the repo-root
``idpshow_session.json``.  The operator mints and refreshes cookies at
the rankings-fetch work dir (``/var/lib/idpshow-fetch/`` — see
scripts/fetch_idpshow.py), so before the IDP Show stage this script
stages the FRESHEST jar into the repo root: newest mtime wins, the
copy is atomic and 0600 from birth, and an unreadable candidate is a
warning, never a crash — session trouble must not break the exit-code
contract.  There is no copy-back: no fetcher ever mutates the jar.

Exit codes (systemd journal contract, playerctx style):
  0 - at least one stage wrote a snapshot
  1 - soft failure: no stage wrote anything; last-good snapshot untouched
  2 - a stage hard-errored (its own exit 2); last-good untouched

PARTIAL SUCCESS IS STILL 0 - by that convention and by the owner decision
recorded in ``_summarize`` (2026-07-30): a valid snapshot is served, and a
weekly unit that is permanently red trains people to ignore it.  That makes
the exit code UNABLE to say "a real source failed", so the run says it two
other ways, and "snapshot(s) written" must never be read as "every source
landed":

* the final log line NAMES every stage that failed, hard-errored or could
  not run (with its exit code), lists the real sources that actually made
  it into the snapshot, and lists any stage that was shadowed;
* ``data/bdvm/refresh_status.json`` (machine-readable, latest run only,
  overridable with $BDVM_REFRESH_STATUS_PATH) carries the same facts per
  stage: ``result`` is ``ok`` / ``proxy_only`` / ``degraded`` / ``failed``.
  Nothing reads it yet; the louder signal the owner was offered (a
  projectionSourceMix field on /api/status) is a separate change.
  A failure to write it is a warning, never an exit-code change.

OWNER GATE - IDP Show records are SHADOWED by default.  Merging them into a
snapshot changes the fundamental values BDVM serves, which is the owner's
call (``src/bdvm/idpshow_switch.py``).  With the switch off the fetcher
still runs and parses, writes its records to
``data/bdvm/shadow/idpshow_projections/`` (a tree BDVM does not read), and
this script reports the stage as SHADOWED - never as a real source in the
snapshot.  Activate with ``BDVM_IDPSHOW_MERGE_INTO_SNAPSHOT=1`` (the unit
reads ``.env``, so no unit change) or ``--merge-idpshow``.

Usage::

    python scripts/refresh_bdvm_projections.py                # season auto
    python scripts/refresh_bdvm_projections.py --season 2026
    python scripts/refresh_bdvm_projections.py --skip-idpshow
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from src.bdvm.idpshow_switch import MERGE_ENV_VAR, merge_into_snapshot_enabled  # noqa: E402

SESSION_NAME = "idpshow_session.json"
DEFAULT_WORKDIR_SESSION = Path("/var/lib/idpshow-fetch") / SESSION_NAME
REMINT_HINT = (
    f"mint cookies per scripts/fetch_idpshow.py and place them at "
    f"{DEFAULT_WORKDIR_SESSION} (or pass --session)"
)

STATUS_PATH_ENV = "BDVM_REFRESH_STATUS_PATH"
STATUS_SCHEMA_VERSION = 1

# Stage outcome vocabulary (the status file's per-stage ``status``).
OK = "ok"  # wrote / merged into the snapshot
SHADOW = "shadow"  # ran and parsed, but the owner-reserved merge is OFF
FAILED = "failed"  # soft failure (the stage's own exit 1)
ERROR = "error"  # hard error (any other non-zero exit)
UNAVAILABLE = "unavailable"  # could not run (no session cookies)
SKIPPED = "skipped"  # operator passed --skip-*
_NOT_LANDED = (FAILED, ERROR, UNAVAILABLE)


def log(msg: str) -> None:
    print(f"[bdvm-refresh] {msg}")


def _auto_season() -> int:
    """Target (upcoming) season.

    Prefer the contract's ``currentDraftYear`` (the number the rest of
    the platform runs on); fall back to a date rule (Jan/Feb belong to
    the previous season) only when no contract export is readable.
    """
    exports = sorted((REPO / "exports" / "latest").glob("dynasty_data_*.json"))
    if exports:
        try:
            payload = json.loads(exports[-1].read_text(encoding="utf-8"))
            year = payload.get("currentDraftYear")
            if isinstance(year, int) and 2000 < year < 2100:
                return year
        except (OSError, ValueError) as exc:
            log(f"WARN: could not read season from {exports[-1].name}: {exc}")
    now = datetime.now(timezone.utc)
    return now.year - 1 if now.month <= 2 else now.year


def _run_stage(name: str, cmd: list[str]) -> int:
    log(f"stage {name}: {' '.join(cmd)}")
    proc = subprocess.run(cmd, cwd=REPO)
    log(f"stage {name}: exit {proc.returncode}")
    return proc.returncode


def _atomic_copy_0600(src: Path, dst: Path) -> None:
    """Copy src → dst atomically, 0600 from birth (never a torn or
    world-readable cookie jar, even mid-copy)."""
    data = src.read_bytes()
    fd, tmp_name = tempfile.mkstemp(dir=str(dst.parent), prefix=f".{dst.name}.")
    try:
        try:
            os.write(fd, data)
            if hasattr(os, "fchmod"):
                os.fchmod(fd, 0o600)
            else:
                # Windows has no fchmod; mkstemp's file is already private to
                # the creating user there.  Same request by path.
                os.chmod(tmp_name, 0o600)
        finally:
            os.close(fd)
        os.replace(tmp_name, dst)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def _stage_session_file(explicit: str | None) -> Path | None:
    """Stage the freshest session jar into the repo root (newest wins).

    The fetcher reads only ``REPO/idpshow_session.json``; the operator
    re-mints cookies at the work-dir location.  An existing repo copy
    is therefore REPLACED whenever a candidate is newer (mtime) — a
    stale repo jar must never shadow a fresh re-mint forever.  Probe
    order: --session, $BDVM_IDPSHOW_SESSION, the shared work-dir jar.
    Any OSError on a candidate is a warning and the next candidate is
    tried; staging problems never break the exit-code contract.

    Returns the path staged from, or None when nothing was staged.
    """
    repo_session = REPO / SESSION_NAME
    candidates = [
        Path(explicit) if explicit else None,
        Path(os.environ["BDVM_IDPSHOW_SESSION"])
        if os.environ.get("BDVM_IDPSHOW_SESSION")
        else None,
        DEFAULT_WORKDIR_SESSION,
    ]
    for candidate in candidates:
        if candidate is None:
            continue
        try:
            if not candidate.is_file():
                continue
            if repo_session.exists() and repo_session.stat().st_mtime >= candidate.stat().st_mtime:
                continue  # repo copy is at least as fresh as this candidate
            _atomic_copy_0600(candidate, repo_session)
            log(f"staged session cookies from {candidate}")
            return candidate
        except OSError as exc:
            log(f"WARN: could not stage session cookies from {candidate}: {exc}")
    return None


def _status_path() -> Path:
    override = os.environ.get(STATUS_PATH_ENV)
    return Path(override) if override else REPO / "data" / "bdvm" / "refresh_status.json"


def _describe(outcome: dict) -> str:
    status = outcome["status"]
    code = outcome.get("exitCode")
    if status == FAILED:
        return f"exit {code}: no usable data"
    if status == ERROR:
        return f"exit {code}: hard error"
    if status == UNAVAILABLE:
        return outcome.get("detail") or "could not run"
    return status


def _summarize(
    outcomes: dict[str, dict], *, wrote_any: bool, hard_error: bool
) -> tuple[str, str, dict]:
    """(final log line, result, facts) from the per-stage outcomes.

    Pure, so the honesty contract is testable without a subprocess.  The
    line names every stage that did not land; it never says a source landed
    that did not.  ``result``: ``failed`` (nothing written), ``degraded``
    (written, but a stage failed / errored / could not run), ``proxy_only``
    (written, nothing failed, but no real source is in the snapshot) or
    ``ok``.
    """
    real_in = [n for n, o in outcomes.items() if o["kind"] == "real" and o["status"] == OK]
    not_landed = [n for n, o in outcomes.items() if o["status"] in _NOT_LANDED]
    shadowed = [n for n, o in outcomes.items() if o["status"] == SHADOW]
    skipped = [n for n, o in outcomes.items() if o["status"] == SKIPPED]
    facts = {
        "realSourcesInSnapshot": real_in,
        "failedStages": not_landed,
        "shadowStages": shadowed,
        "skippedStages": skipped,
    }
    failed_text = ", ".join(f"{n} ({_describe(outcomes[n])})" for n in not_landed)
    tail = ""
    if shadowed:
        tail += (
            f"; SHADOWED, not in the snapshot (owner-reserved merge switch off, see "
            f"{MERGE_ENV_VAR}): {', '.join(shadowed)}"
        )
    if skipped:
        tail += f"; skipped by flag: {', '.join(skipped)}"

    if not wrote_any:
        base = (
            "done: hard error and nothing written"
            if hard_error
            else "done: nothing written (soft); last-good snapshot still serves"
        )
        if not_landed:
            base += f"; FAILED stages: {failed_text}"
        return base + tail, "failed", facts

    if not_landed:
        line = (
            f"done (DEGRADED): snapshot(s) written, but stage(s) FAILED: {failed_text}; "
            f"real sources in the snapshot: {', '.join(real_in) or 'NONE'}"
        )
        if not real_in:
            line += " (proxy-only: backward-looking realized production, not a forward projection)"
        return line + tail, "degraded", facts

    if real_in:
        line = f"done: snapshot(s) written; real sources in the snapshot: {', '.join(real_in)}"
        return line + tail, "ok", facts

    # Deliberately still exit 0: the snapshot IS valid and the board prices
    # from it, every record carries is_proxy=True, and the UI badges those
    # rows. Turning this into a non-zero exit would mark the systemd unit
    # failed every week until an operator installs poppler and mints
    # cookies, which trains people to ignore a red unit - worse than a
    # precise log line.  The louder signal, if wanted, belongs in
    # /api/status (a projectionSourceMix field), not in the exit code.
    # Left as an explicit decision rather than an accident; raised with the
    # owner 2026-07-30.
    return (
        "done: PROXY-ONLY snapshot written - no real projection source landed. Every "
        "record is is_proxy=True: this is backward-looking realized production, "
        "not a forward projection" + tail,
        "proxy_only",
        facts,
    )


def _write_status(payload: dict) -> Path | None:
    """Atomically write the machine-readable run status.  Never raises."""
    path = _status_path()
    tmp_name: str | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".refresh_status.")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=1)
        os.replace(tmp_name, path)
        return path
    except OSError as exc:
        log(f"WARN: could not write run status {path}: {exc}")
        if tmp_name:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
        return None


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--season",
        type=int,
        default=None,
        help="target season (default: contract currentDraftYear, else date rule)",
    )
    parser.add_argument("--skip-baseline", action="store_true")
    parser.add_argument("--skip-clay", action="store_true")
    parser.add_argument("--skip-idpshow", action="store_true")
    parser.add_argument(
        "--merge-idpshow",
        action="store_true",
        help=(
            "OWNER-RESERVED: merge IDP Show records into the snapshot (also enabled by "
            f"{MERGE_ENV_VAR}=1). Default OFF: the stage writes a shadow file instead."
        ),
    )
    parser.add_argument(
        "--session",
        default=None,
        help=f"path to {SESSION_NAME} to stage into the repo root "
        f"(default probe: $BDVM_IDPSHOW_SESSION, then {DEFAULT_WORKDIR_SESSION})",
    )
    args = parser.parse_args()

    season = args.season if args.season is not None else _auto_season()
    idpshow_merging = merge_into_snapshot_enabled(args.merge_idpshow)
    log(f"refreshing BDVM projection snapshots for season {season}")

    wrote_any = False
    hard_error = False
    # Per-stage outcomes feed BOTH the final summary line and the status file.
    # ``kind`` separates the RECONSTRUCTED PROXY baseline (realized production
    # re-scored under this league's rules; it essentially always writes) from
    # the real forward-looking sources (clay, idpshow).  Without that split the
    # final line read "done: snapshot(s) written" on a box where both real
    # sources had failed (production 2026-07-30), and - after the
    # 2026-07-30 fix - "including at least one REAL source" while IDP Show had
    # failed every week for months (box audit 2026-10-26).
    outcomes: dict[str, dict] = {}

    def record(stage: str, kind: str, status: str, exit_code: int | None, detail: str = "") -> None:
        outcomes[stage] = {"kind": kind, "status": status, "exitCode": exit_code}
        if detail:
            outcomes[stage]["detail"] = detail

    if args.skip_baseline:
        log("baseline stage skipped by flag")
        record("baseline", "proxy", SKIPPED, None)
    else:
        rc = _run_stage(
            "baseline",
            [sys.executable, "scripts/bdvm_build_baseline.py", "--season", str(season)],
        )
        if rc == 0:
            wrote_any = True
            record("baseline", "proxy", OK, rc)
        elif rc == 1:
            log("WARN: baseline built nothing; last-good snapshot untouched")
            record("baseline", "proxy", FAILED, rc)
        else:
            log("ERROR: baseline stage hard-errored")
            hard_error = True
            record("baseline", "proxy", ERROR, rc)

    if args.skip_clay:
        log("clay stage skipped by flag")
        record("clay", "real", SKIPPED, None)
    else:
        rc = _run_stage(
            "clay",
            [sys.executable, "scripts/fetch_clay_projections.py", "--season", str(season)],
        )
        if rc == 0:
            wrote_any = True
            record("clay", "real", OK, rc)
        elif rc == 1:
            log(
                "WARN: clay guide unavailable (CDN 404 / poppler missing?); "
                "prior Clay records stay on the board via the baseline carry-forward"
            )
            record("clay", "real", FAILED, rc)
        else:
            log("ERROR: clay stage hard-errored")
            hard_error = True
            record("clay", "real", ERROR, rc)

    if args.skip_idpshow:
        log("idpshow stage skipped by flag")
        record("idpshow", "real", SKIPPED, None)
    else:
        _stage_session_file(args.session)
        repo_session = REPO / SESSION_NAME
        if not repo_session.exists():
            log(
                "WARN: no idpshow session cookies found - skipping the real-source "
                f"stage. Proxy-only snapshots remain flagged is_proxy; {REMINT_HINT}."
            )
            record("idpshow", "real", UNAVAILABLE, None, "no session cookies")
        else:
            cmd = [sys.executable, "scripts/fetch_idpshow_projections.py", "--season", str(season)]
            if idpshow_merging:
                cmd.append("--merge-into-snapshot")
            rc = _run_stage("idpshow", cmd)
            if rc == 0 and idpshow_merging:
                wrote_any = True
                record("idpshow", "real", OK, rc)
            elif rc == 0:
                # Parsed fine, but the owner-reserved merge is OFF: the records
                # sit in the shadow file and are NOT in any snapshot, so this
                # must not be counted as a real source landing.
                log(
                    "idpshow: records parsed to the SHADOW file only - NOT merged into the "
                    f"snapshot (owner-reserved; {MERGE_ENV_VAR}=1 or --merge-idpshow activates)"
                )
                record("idpshow", "real", SHADOW, rc, "parsed to shadow; merge switch off")
            elif rc == 1:
                log(
                    "WARN: idpshow returned no usable data (expired cookies, paywall, "
                    "OR a changed column layout - the parse report printed above and "
                    "data/bdvm/shadow/idpshow_projections/<season>/"
                    "idpshow_<date>_no_usable_table.json name the missing roles and the "
                    "raw headers; check them before re-minting cookies, a header-format "
                    "change presents identically here). "
                    "Previously merged real records stay on the board via the baseline "
                    f"carry-forward; {REMINT_HINT}."
                )
                record("idpshow", "real", FAILED, rc)
            else:
                log("ERROR: idpshow stage hard-errored")
                hard_error = True
                record("idpshow", "real", ERROR, rc)

    line, result, facts = _summarize(outcomes, wrote_any=wrote_any, hard_error=hard_error)
    exit_code = 0 if wrote_any else (2 if hard_error else 1)
    log(line)
    status_path = _write_status(
        {
            "schemaVersion": STATUS_SCHEMA_VERSION,
            "runAt": datetime.now(timezone.utc).isoformat(),
            "season": season,
            "exitCode": exit_code,
            "result": result,
            "snapshotWritten": wrote_any,
            "summary": line,
            **facts,
            "idpshowMergeSwitch": {"envVar": MERGE_ENV_VAR, "enabled": idpshow_merging},
            "stages": outcomes,
        }
    )
    if status_path is not None:
        log(f"run status written to {status_path}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
