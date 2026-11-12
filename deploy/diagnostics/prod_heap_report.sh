#!/usr/bin/env bash
# Read-only: what is the production backend's heap made of?  (WA-17)
#
# The backend appends heap snapshots to a box-local log
# (src/diagnostics/heap_report.py -> data/diagnostics/heap_reports.jsonl):
# at start, every HEAP_REPORT_INTERVAL_SEC, before each scrape and after
# each publish.  This script reads that log and prints:
#
#   * the series: process RSS and glibc's split of the heap into memory in
#     use and memory freed but retained (fragmentation), mmap, arena count;
#   * the latest type census, the largest module-level containers, and the
#     deep census: bytes reachable from each module-level object (the only
#     view that sees str / bytes payloads), against the heap in use;
#   * growth by type, by container and by deep root between the first and
#     last census of the CURRENT process (a restart starts a new heap).
#
# CONTRACT: READ-ONLY.  It reads one file and prints derived numbers.  It
# never restarts, reloads, deploys, writes, or imports the application.
# Every record is re-validated before printing: names must be identifiers
# (module / attribute / type names, ``[A-Za-z0-9_.()<>[]-]``, at most 160
# characters), numbers must be numbers; anything else is dropped, so a
# corrupt or tampered line cannot carry text into the job log.  Pinned by
# tests/deploy/test_prod_heap_report.py.
#
# Usage:
#   prod_heap_report.sh [max_records]     # on the box (APP_DIR overridable)
#   prod_heap_report.sh --filter [max_records] < heap_reports.jsonl
#
# Exit: 0 report printed; 2 bad arguments or no python3; 5 the log is
# missing or holds no valid record ("could not look" is never green).

set -uo pipefail

APP_DIR="${APP_DIR:-/home/dynasty/trade-calculator}"
LOG="${HEAP_REPORT_LOG:-${APP_DIR}/data/diagnostics/heap_reports.jsonl}"

mode=box
if [[ "${1:-}" == "--filter" ]]; then
  mode=filter
  shift
fi
max_records="${1:-400}"
if ! [[ "${max_records}" =~ ^[0-9]{1,5}$ ]] || (( max_records < 1 )); then
  echo "error: max_records must be a positive integer" >&2
  exit 2
fi
command -v python3 >/dev/null 2>&1 || { echo "error: python3 not found" >&2; exit 2; }

report() {
  python3 -c '
import json, re, sys

MAX = int(sys.argv[1])
NAME = re.compile(r"^[A-Za-z0-9_.()<>\[\]-]{1,160}$")
REASON = re.compile(r"^[A-Za-z0-9_]{1,40}$")
TS = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")

def num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None

def name(v):
    return v if isinstance(v, str) and NAME.match(v) else None

def clean(raw):
    if not isinstance(raw, dict):
        return None
    ts, reason = raw.get("ts"), raw.get("reason")
    if not (isinstance(ts, str) and TS.match(ts) and isinstance(reason, str) and REASON.match(reason)):
        return None
    m = raw.get("malloc") if isinstance(raw.get("malloc"), dict) else {}
    rec = {
        "ts": ts[:19], "reason": reason, "pid": num(raw.get("pid")),
        "rss": num(raw.get("process_rss_mib")),
        "arena": num(m.get("arena_mib")), "in_use": num(m.get("in_use_mib")),
        "free": num(m.get("free_mib")), "mmap": num(m.get("mmap_mib")),
        "arenas": num(m.get("arenas")),
        "containers": [], "types": None, "tracked": None, "deep": None,
        "census_ms": num(raw.get("census_ms")),
        "trim_before": None, "trim_after": None,
    }
    extra = raw.get("extra") if isinstance(raw.get("extra"), dict) else {}
    rec["trim_before"] = num(extra.get("trimRssBeforeMib"))
    rec["trim_after"] = num(extra.get("trimRssAfterMib"))
    for c in raw.get("containers") or []:
        if isinstance(c, dict) and name(c.get("name")) and name(c.get("kind")) and num(c.get("len")) is not None:
            rec["containers"].append((c["name"], c["kind"], c["len"]))
    t = raw.get("types")
    if isinstance(t, dict):
        rec["tracked"] = num(t.get("tracked_objects"))
        rec["types"] = [
            (r["type"], r["count"], r["mib"]) for r in (t.get("top") or [])
            if isinstance(r, dict) and name(r.get("type")) and num(r.get("count")) is not None and num(r.get("mib")) is not None
        ]
    d = raw.get("deep")
    if isinstance(d, dict) and isinstance(d.get("truncated"), bool):
        rec["deep"] = {
            "walked": num(d.get("walked_objects")),
            "mib": num(d.get("attributed_mib")),
            "truncated": d["truncated"],
            "top": [
                (r["name"], r["kind"], r["mib"], r["objects"]) for r in (d.get("top") or [])
                if isinstance(r, dict) and name(r.get("name")) and name(r.get("kind"))
                and num(r.get("mib")) is not None and num(r.get("objects")) is not None
            ],
        }
    return rec

records, dropped = [], 0
for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    try:
        rec = clean(json.loads(line))
    except ValueError:
        rec = None
    if rec is None:
        dropped += 1
    else:
        records.append(rec)
records = records[-MAX:]
if not records:
    print("error: no valid heap record (dropped=%d)" % dropped, file=sys.stderr)
    sys.exit(5)

def f(v):
    return "-" if v is None else str(v)

print("== series (MiB) == records=%d dropped=%d" % (len(records), dropped))
print("%-19s %-17s %7s %6s %6s %6s %6s %6s %6s %9s %s" % (
    "ts_utc", "reason", "pid", "rss", "arena", "in_use", "free", "mmap", "arenas", "objects", "trim"))
for r in records:
    trim = "" if r["trim_before"] is None else "%s->%s" % (f(r["trim_before"]), f(r["trim_after"]))
    print("%-19s %-17s %7s %6s %6s %6s %6s %6s %6s %9s %s" % (
        r["ts"], r["reason"], f(r["pid"]), f(r["rss"]), f(r["arena"]), f(r["in_use"]),
        f(r["free"]), f(r["mmap"]), f(r["arenas"]), f(r["tracked"]), trim))

last = records[-1]
if last["in_use"] is not None and last["free"] is not None and (last["in_use"] + last["free"]) > 0:
    share = 100.0 * last["free"] / (last["in_use"] + last["free"])
    print("latest: heap in use %s MiB, freed but retained %s MiB (%.0f%% of the arena heap), mmap %s MiB, arenas %s" % (
        f(last["in_use"]), f(last["free"]), share, f(last["mmap"]), f(last["arenas"])))

typed = [r for r in records if r["types"] is not None and r["pid"] == last["pid"]]
if typed:
    t = typed[-1]
    print("\n== type census %s (%s) objects=%s census_ms=%s ==" % (t["ts"], t["reason"], f(t["tracked"]), f(t["census_ms"])))
    for tname, count, mib in t["types"][:20]:
        print("  %-40s count=%-9d mib=%s" % (tname, count, mib))
deep = [r for r in records if r["deep"] is not None and r["pid"] == last["pid"]]
if deep:
    d = deep[-1]
    print("\n== deep census %s (%s): %s MiB reachable from module-level objects, heap in use %s MiB, walked=%s truncated=%s ==" % (
        d["ts"], d["reason"], f(d["deep"]["mib"]), f(d["in_use"]), f(d["deep"]["walked"]), d["deep"]["truncated"]))
    for rname, kind, mib, objects in d["deep"]["top"][:20]:
        print("  %-70s %-14s mib=%-8s objects=%d" % (rname, kind, mib, objects))
if len(deep) >= 2:
    a, b = deep[0], deep[-1]
    print("\n== growth by deep root, %s -> %s (pid %s) ==" % (a["ts"], b["ts"], f(b["pid"])))
    before = {n: m for n, _k, m, _o in a["deep"]["top"]}
    rows = sorted(((m - before.get(n, 0.0), n, m) for n, _k, m, _o in b["deep"]["top"]), reverse=True)[:15]
    for dm, n, m in rows:
        print("  %-70s d_mib=%+.1f mib=%s" % (n, dm, m))
print("\n== largest containers %s (%s) ==" % (last["ts"], last["reason"]))
for cname, kind, length in last["containers"][:20]:
    print("  %-70s %-10s len=%d" % (cname, kind, length))

if len(typed) >= 2:
    a, b = typed[0], typed[-1]
    print("\n== growth by type, %s -> %s (pid %s) ==" % (a["ts"], b["ts"], f(b["pid"])))
    before = {n: (c, m) for n, c, m in a["types"]}
    rows = []
    for n, c, m in b["types"]:
        c0, m0 = before.get(n, (0, 0.0))
        rows.append((m - m0, c - c0, n, m))
    for dm, dc, n, m in sorted(rows, reverse=True)[:15]:
        print("  %-40s d_mib=%+.1f d_count=%+d mib=%s" % (n, dm, dc, m))
same = [r for r in records if r["pid"] == last["pid"]]
if len(same) >= 2:
    a = same[0]
    print("\n== growth by container, %s -> %s (pid %s) ==" % (a["ts"], last["ts"], f(last["pid"])))
    before = {n: l for n, _k, l in a["containers"]}
    rows = sorted(((l - before.get(n, 0), n, l) for n, _k, l in last["containers"]), reverse=True)[:15]
    for dl, n, l in rows:
        print("  %-70s d_len=%+d len=%d" % (n, dl, l))
' "${max_records}"
}

if [[ "${mode}" == "filter" ]]; then
  report
  exit $?
fi

if [[ ! -r "${LOG}" ]]; then
  echo "error: heap report log not readable: ${LOG}" >&2
  echo "(the backend writes it from the first snapshot after a deploy that includes WA-17's heap report)" >&2
  exit 5
fi
echo "log: ${LOG} bytes=$(stat -c %s "${LOG}" 2>/dev/null || echo unknown)"
tail -n "${max_records}" "${LOG}" | report
exit $?
