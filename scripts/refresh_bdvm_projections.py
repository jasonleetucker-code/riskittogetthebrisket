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
SESSION_NAME = "idpshow_session.json"
DEFAULT_WORKDIR_SESSION = Path("/var/lib/idpshow-fetch") / SESSION_NAME
REMINT_HINT = (
    f"mint cookies per scripts/fetch_idpshow.py and place them at "
    f"{DEFAULT_WORKDIR_SESSION} (or pass --session)"
)


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
            os.fchmod(fd, 0o600)
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
        "--session",
        default=None,
        help=f"path to {SESSION_NAME} to stage into the repo root "
        f"(default probe: $BDVM_IDPSHOW_SESSION, then {DEFAULT_WORKDIR_SESSION})",
    )
    args = parser.parse_args()

    season = args.season if args.season is not None else _auto_season()
    log(f"refreshing BDVM projection snapshots for season {season}")

    wrote_any = False
    hard_error = False
    # Tracked separately from ``wrote_any`` because the two mean very
    # different things operationally.  The baseline stage is a
    # RECONSTRUCTED PROXY (realized production re-scored under this
    # league's rules) and it essentially always writes; clay and idpshow
    # are the only real forward-looking projection sources.  Without this
    # distinction the final log line read "done: snapshot(s) written" on
    # a box where both real sources had failed — which is what happened
    # on production 2026-07-30, where poppler was missing and the IDP
    # Show header format had changed.
    real_source_wrote = False

    if args.skip_baseline:
        log("baseline stage skipped by flag")
    else:
        rc = _run_stage(
            "baseline",
            [sys.executable, "scripts/bdvm_build_baseline.py", "--season", str(season)],
        )
        if rc == 0:
            wrote_any = True
        elif rc == 1:
            log("WARN: baseline built nothing; last-good snapshot untouched")
        else:
            log("ERROR: baseline stage hard-errored")
            hard_error = True

    if args.skip_clay:
        log("clay stage skipped by flag")
    else:
        rc = _run_stage(
            "clay",
            [sys.executable, "scripts/fetch_clay_projections.py", "--season", str(season)],
        )
        if rc == 0:
            wrote_any = True
            real_source_wrote = True
        elif rc == 1:
            log(
                "WARN: clay guide unavailable (CDN 404 / poppler missing?); "
                "prior Clay records stay on the board via the baseline carry-forward"
            )
        else:
            log("ERROR: clay stage hard-errored")
            hard_error = True

    if args.skip_idpshow:
        log("idpshow stage skipped by flag")
    else:
        _stage_session_file(args.session)
        repo_session = REPO / SESSION_NAME
        if not repo_session.exists():
            log(
                "WARN: no idpshow session cookies found - skipping the real-source "
                f"stage. Proxy-only snapshots remain flagged is_proxy; {REMINT_HINT}."
            )
        else:
            rc = _run_stage(
                "idpshow",
                [sys.executable, "scripts/fetch_idpshow_projections.py", "--season", str(season)],
            )
            if rc == 0:
                wrote_any = True
                real_source_wrote = True
            elif rc == 1:
                log(
                    "WARN: idpshow returned no usable data (expired cookies, paywall, "
                    "OR a changed column layout — check the report's unmappedColumns "
                    "before re-minting cookies; a header-format change presents "
                    "identically here). "
                    "Previously merged real records stay on the board via the baseline "
                    f"carry-forward; {REMINT_HINT}."
                )
            else:
                log("ERROR: idpshow stage hard-errored")
                hard_error = True

    if wrote_any:
        if real_source_wrote:
            log("done: snapshot(s) written, including at least one REAL source")
        else:
            # Deliberately still exit 0: the snapshot IS valid and the
            # board prices from it, every record carries is_proxy=True,
            # and the UI badges those rows. Turning this into a non-zero
            # exit would mark the systemd unit failed every week until an
            # operator installs poppler and mints cookies, which trains
            # people to ignore a red unit — worse than a precise log line.
            #
            # If a louder signal is wanted, the right place is
            # /api/status (a projectionSourceMix field), not the exit
            # code. Left as an explicit decision rather than an
            # accident; raised with the owner 2026-07-30.
            log(
                "done: PROXY-ONLY snapshot written — no real projection source "
                "landed (clay and idpshow both failed above). Every record is "
                "is_proxy=True: this is backward-looking realized production, "
                "not a forward projection."
            )
        return 0
    if hard_error:
        log("done: hard error and nothing written")
        return 2
    log("done: nothing written (soft); last-good snapshot still serves")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
