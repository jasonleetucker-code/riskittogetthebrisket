#!/usr/bin/env python3
"""Sum the memory ceilings the repo's systemd units declare, against host RAM.

OFFLINE and READ-ONLY.  It reads ``deploy/systemd/*.service[.template]`` and
does arithmetic.  It does not call systemctl, does not read any cgroup, and
changes no unit.

TWO DIFFERENT QUESTIONS, deliberately kept apart
------------------------------------------------
1. CEILING OVERSUBSCRIPTION -- do the declared ``MemoryMax`` values add up to
   more than the host has?  That is a statement about what the limits PERMIT,
   not about what the units USE.  A sum above host RAM is not an outage; it
   means "if every unit sat at its ceiling at once, the kernel OOM killer, not
   a unit limit, would pick the victim".  Reported as ``oversubscription_mib``.
2. CO-RESIDENT USAGE -- given MEASURED (or estimated) peak usage per consumer,
   how much of the host is left?  Supplied with ``--usage label=MIB`` and
   reported as ``usage_margin_mib``.  This is the number that says whether a
   proposed backend ceiling is survivable on this box.

Conflating the two is how a "worst case" gets quoted as if it were a forecast.

Policy checks (``violations``): a ``MemoryHigh`` above its own ``MemoryMax``
is meaningless, and a ``MemoryHigh`` with no ``MemoryMax`` leaves a unit that
throttles and is never killed -- the combination that stalls instead of
restarting.  ``MemoryHigh`` is a THROTTLE (cgroup v2 ``memory.high``), not a
warning level; this module never describes it as one.

Usage:
    python scripts/memory_ceiling_budget.py [--units-dir deploy/systemd]
        [--host-mib 7941] [--set UNIT.MemoryMax=3584M ...]
        [--usage backend=3430 --usage frontend=106 ...] [--format json|text]
    UNIT is the file stem without ``.service[.template]`` (``dynasty``,
    ``dynasty-frontend``).  A value of ``none``/``infinity`` clears a limit.
Exit codes: 0 report printed; 2 bad arguments or unreadable units dir.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_UNITS_DIR = REPO_ROOT / "deploy" / "systemd"

#: ``MemTotal`` of the production host, MEASURED: 8,326,946,816 B in
#: docs/performance/evidence/linux-inventory-2026-09-26.json and ``free -m``
#: total 7941 in the 2026-10-19 / 2026-10-21 restart diagnostics.  Swap: 0.
DEFAULT_HOST_MIB = 7941

#: Units that are always resident.  Everything else with a ceiling is a
#: timer-driven job that is normally not running.
ALWAYS_ON = frozenset({"dynasty", "dynasty-frontend"})

_UNITS = {"": 1, "B": 1, "K": 1024, "M": 1024**2, "G": 1024**3, "T": 1024**4}
_LIMIT_KEYS = ("MemoryHigh", "MemoryMax")
_LINE = re.compile(r"^\s*(?P<key>MemoryHigh|MemoryMax)\s*=\s*(?P<val>\S+)\s*$")


def parse_size(text: str) -> int | None:
    """systemd size (base 1024) in bytes; None for infinity / unparseable."""
    t = text.strip()
    if t.lower() in {"infinity", "none", ""}:
        return None
    m = re.fullmatch(r"(?P<n>\d+(?:\.\d+)?)(?P<u>[KMGTB]?)", t, re.IGNORECASE)
    if not m:
        return None
    return int(float(m["n"]) * _UNITS[m["u"].upper()])


def unit_limits(text: str) -> dict[str, int | None]:
    """Last ``MemoryHigh=`` / ``MemoryMax=`` in a unit file (systemd: last wins)."""
    found: dict[str, int | None] = {}
    for line in text.splitlines():
        m = _LINE.match(line)
        if m:
            found[m["key"]] = parse_size(m["val"])
    return found


def read_units(units_dir: Path) -> dict[str, dict[str, int | None]]:
    if not units_dir.is_dir():
        raise OSError(f"units dir not found: {units_dir}")
    units: dict[str, dict[str, int | None]] = {}
    for path in sorted(units_dir.glob("*.service*")):
        if path.suffix not in {".service", ".template"}:
            continue
        stem = path.name.removesuffix(".template").removesuffix(".service")
        limits = unit_limits(path.read_text(encoding="utf-8"))
        if limits:
            units[stem] = limits
    return units


def apply_overrides(
    units: dict[str, dict[str, int | None]], overrides: list[str]
) -> dict[str, dict[str, int | None]]:
    out = {k: dict(v) for k, v in units.items()}
    for item in overrides:
        m = re.fullmatch(r"(?P<unit>[\w@.-]+)\.(?P<key>MemoryHigh|MemoryMax)=(?P<val>\S+)", item)
        if not m:
            raise ValueError(f"bad --set {item!r}; expected UNIT.MemoryMax=3584M")
        out.setdefault(m["unit"], {})[m["key"]] = parse_size(m["val"])
    return out


def _mib(value: int | None) -> float | None:
    return None if value is None else round(value / 1024**2, 1)


def budget(
    units: dict[str, dict[str, int | None]],
    host_mib: float = DEFAULT_HOST_MIB,
    usage: dict[str, float] | None = None,
) -> dict:
    rows, violations = [], []
    for name, lim in sorted(units.items()):
        high, mx = lim.get("MemoryHigh"), lim.get("MemoryMax")
        rows.append({"unit": name, "memory_high_mib": _mib(high), "memory_max_mib": _mib(mx)})
        if high is not None and mx is not None and high > mx:
            violations.append(f"{name}: MemoryHigh above MemoryMax")
        if high is not None and mx is None:
            violations.append(f"{name}: MemoryHigh with no MemoryMax (throttles, is never killed)")
    maxes = {r["unit"]: r["memory_max_mib"] for r in rows if r["memory_max_mib"] is not None}
    sum_all = sum(maxes.values())
    sum_on = sum(v for k, v in maxes.items() if k in ALWAYS_ON)
    out = {
        "host_mib": host_mib,
        "units": rows,
        "sum_memory_max_all_mib": round(sum_all, 1),
        "sum_memory_max_always_on_mib": round(sum_on, 1),
        "oversubscription_mib": round(sum_all - host_mib, 1),
        "oversubscription_always_on_mib": round(sum_on - host_mib, 1),
        "violations": violations,
    }
    if usage:
        total = sum(usage.values())
        out["usage_mib"] = dict(usage)
        out["usage_total_mib"] = round(total, 1)
        out["usage_margin_mib"] = round(host_mib - total, 1)
    return out


def render_text(report: dict) -> str:
    lines = [f"memory ceiling budget (offline; host {report['host_mib']} MiB, no swap)", ""]
    lines.append(f"  {'unit':<34}{'MemoryHigh':>12}{'MemoryMax':>12}")
    for r in report["units"]:
        hi = "-" if r["memory_high_mib"] is None else f"{r['memory_high_mib']:g}M"
        mx = "-" if r["memory_max_mib"] is None else f"{r['memory_max_mib']:g}M"
        lines.append(f"  {r['unit']:<34}{hi:>12}{mx:>12}")
    lines += [
        "",
        f"  sum of every MemoryMax:        {report['sum_memory_max_all_mib']:g} MiB"
        f"  -> {report['oversubscription_mib']:+g} MiB vs host (ceilings, not usage)",
        f"  sum, always-on units only:     {report['sum_memory_max_always_on_mib']:g} MiB"
        f"  -> {report['oversubscription_always_on_mib']:+g} MiB vs host",
    ]
    if "usage_total_mib" in report:
        lines.append("")
        for k, v in report["usage_mib"].items():
            lines.append(f"  usage  {k:<26}{v:>10g} MiB")
        lines.append(
            f"  co-resident usage total:       {report['usage_total_mib']:g} MiB"
            f"  -> margin {report['usage_margin_mib']:+g} MiB"
        )
    for v in report["violations"]:
        lines.append(f"  VIOLATION: {v}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--units-dir", type=Path, default=DEFAULT_UNITS_DIR)
    ap.add_argument("--host-mib", type=float, default=DEFAULT_HOST_MIB)
    ap.add_argument("--set", dest="overrides", action="append", default=[])
    ap.add_argument("--usage", action="append", default=[], help="label=MIB, repeatable")
    ap.add_argument("--format", choices=("json", "text"), default="text")
    args = ap.parse_args(argv)
    try:
        usage = {}
        for item in args.usage:
            label, _, value = item.partition("=")
            usage[label] = float(value)
        units = apply_overrides(read_units(args.units_dir), args.overrides)
    except (OSError, ValueError) as exc:
        print(f"memory_ceiling_budget: {exc}", file=sys.stderr)
        return 2
    report = budget(units, args.host_mib, usage or None)
    print(json.dumps(report, indent=2) if args.format == "json" else render_text(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
