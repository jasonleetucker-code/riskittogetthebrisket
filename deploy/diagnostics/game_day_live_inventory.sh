#!/usr/bin/env bash
# Game Day live-collector evidence, read from the production host.
#
# WHY THIS EXISTS
# ---------------
# On 2026-09-27 (Week 3, games live) production Game Day served a generation
# 51 minutes old against a 3-minute freshness budget.  The collector
# (``dynasty-game-day-live.timer`` -> ``scripts/run_game_day_live.py``) runs
# only on the box and writes only to gitignored ``data/game_day/live/``, so
# why it stopped publishing is unobservable from anywhere else.  This
# collects: timer/service state, the service journal, the collector's own
# state + tick log + lock, the current league-week generation/state stamps,
# any running tick process with its elapsed time, and host load.
#
# CONTRACT
# --------
# READ-ONLY.  It does not start, stop, restart or reload any unit, and writes
# nothing.  Every read is ``systemctl show/status/list-timers``,
# ``journalctl``, ``ps``, or a file read.  A missing file is reported, never
# an error.

set -Euo pipefail

APP_DIR="${APP_DIR:-/home/dynasty/trade-calculator}"
VENV_DIR="${VENV_DIR:-/home/dynasty/.venvs/trade-calculator}"
SERVICE_NAME="${SERVICE_NAME:-dynasty}"
UNIT="${SERVICE_NAME}-game-day-live"
JOURNAL_LINES="${JOURNAL_LINES:-200}"
LIVE="${APP_DIR}/data/game_day/live"

section() { printf '\n### %s\n' "$*"; }

section "host"
echo "utc: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "deployed_sha: $(git -C "${APP_DIR}" rev-parse HEAD 2>/dev/null || echo UNKNOWN)"
uptime || true
nproc 2>/dev/null | sed 's/^/nproc: /' || true
free -m 2>/dev/null || true

section "timer + service state"
systemctl list-timers --all --no-pager 2>/dev/null | grep -E "NEXT|game-day" || true
for u in "${UNIT}.timer" "${UNIT}.service"; do
  echo "--- ${u}"
  systemctl show "${u}" --no-pager \
    -p ActiveState -p SubState -p Result -p ExecMainStartTimestamp \
    -p ExecMainExitTimestamp -p ExecMainStatus -p ExecMainPID \
    -p NRestarts -p LastTriggerUSec -p NextElapseUSecRealtime -p UnitFileState \
    -p TimeoutStartUSec 2>/dev/null || echo "(systemctl show failed)"
done

section "running tick processes (pid, elapsed, cpu, rss, cmd)"
ps -eo pid,etime,pcpu,rss,args 2>/dev/null | grep -E "run_game_day_live|PID" | grep -v grep || true

section "top CPU processes"
ps -eo pid,etime,pcpu,pmem,args --sort=-pcpu 2>/dev/null | head -15 || true

section "journal (last ${JOURNAL_LINES} lines, 4h)"
JCTL=(journalctl)
if ! journalctl -n 1 -u "${UNIT}.service" >/dev/null 2>&1; then
  JCTL=(sudo -n journalctl)
fi
"${JCTL[@]}" -u "${UNIT}.service" --since "-4h" --no-pager -o short-iso 2>&1 \
  | grep -v -E "exit 2|status=2/INVALIDARGUMENT" | tail -n "${JOURNAL_LINES}" || true

section "collector state + lock"
PY="${VENV_DIR}/bin/python"
[ -x "${PY}" ] || PY="$(command -v python3)"
"${PY}" - "${LIVE}" <<'PYEOF'
import json, os, sys, time
from pathlib import Path

live = Path(sys.argv[1])
coll = live / "_collector"
now = time.time()


def show(path, keys=None):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        print(f"{path}: MISSING")
        return None
    except Exception as exc:  # noqa: BLE001
        print(f"{path}: unreadable {type(exc).__name__}: {exc}")
        return None
    age = now - path.stat().st_mtime
    view = {k: data.get(k) for k in keys} if keys and isinstance(data, dict) else data
    print(f"{path} (mtime {age:.0f}s ago): {json.dumps(view, default=str)[:3000]}")
    return data


show(coll / "state.json", ["nextDueAt", "lastTickAt", "lastOutcome", "cadence", "sourceHealth"])
show(coll / "tick.lock")

ticks = coll / "ticks.jsonl"
if ticks.exists():
    lines = ticks.read_text(encoding="utf-8").splitlines()
    print(f"\nticks.jsonl: {len(lines)} lines; last 40 (summarized):")
    for line in lines[-40:]:
        try:
            t = json.loads(line)
        except Exception:  # noqa: BLE001
            continue
        leagues = {
            k: (v.get("outcome"), v.get("error"), v.get("simulationSeconds") or v.get("elapsedSeconds"))
            for k, v in (t.get("leagues") or {}).items()
        }
        print(
            t.get("startedAt"), "->", t.get("finishedAt"), t.get("outcome"),
            "exit", t.get("exitCode"), "phase", (t.get("cadence") or {}).get("phase"),
            "req", len(t.get("requests") or []), "err", t.get("error"), leagues,
        )
else:
    print("ticks.jsonl: MISSING")

print("\nleague-week generations (current season dirs, newest weeks):")
for key_dir in sorted(p for p in live.iterdir() if p.is_dir() and not p.name.startswith("_")) if live.is_dir() else []:
    for season_dir in sorted(p for p in key_dir.iterdir() if p.is_dir() and p.name.isdigit())[-1:]:
        weeks = sorted(
            (p for p in season_dir.iterdir() if p.is_dir() and p.name.startswith("week_")),
            key=lambda p: int(p.name[5:]) if p.name[5:].isdigit() else -1,
        )[-2:]
        for wk in weeks:
            print(f"-- {key_dir.name}/{season_dir.name}/{wk.name}")
            gpath = wk / "generation.json"
            if gpath.exists():
                try:
                    g = json.loads(gpath.read_text(encoding="utf-8"))
                    print(
                        f"   generation (mtime {now - gpath.stat().st_mtime:.0f}s ago):",
                        {k: g.get(k) for k in ("generationId", "sequence", "producer", "computedAt", "inputsFetchedAt", "schemaVersion", "draws", "seed")},
                    )
                except Exception as exc:  # noqa: BLE001
                    print("   generation unreadable", exc)
            show(wk / "state.json", ["generationId", "lastVerifiedAt", "lastTickFinishedAt", "lastTickOk", "lastTickOutcome", "lastError", "refreshStartedAt", "latestInputFingerprint", "cadence"])
            idx = wk / "generations.jsonl"
            if idx.exists():
                rows = idx.read_text(encoding="utf-8").splitlines()
                print(f"   generations.jsonl: {len(rows)} rows; last 8:")
                for r in rows[-8:]:
                    print("    ", r[:300])
PYEOF
exit 0
