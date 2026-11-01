"""AMATH VALUATION diagnostic D1 (read-only).

Question: does cross-family rank disagreement at t0 predict the size of the
later consensus revision over 28 days?  Uses only `git show` of committed
source CSVs (CSVs/site_raw) at or before each date; all dates <= 2026-10-13
(before the V2.1 sealed-board cutoff T0 2026-10-20T20:00Z).  Offense only.
Run from the repository root:  python -I <this file>
"""

from __future__ import annotations

import csv
import io
import json
import math
import re
import statistics
import subprocess
import sys
from datetime import date, timedelta

REPO = str(__import__("pathlib").Path(__file__).resolve().parents[4])
OFF = {"QB", "RB", "WR", "TE"}

# (csv key, name col, rank col or None (sort by value desc), value col, pos col)
SOURCES = {
    "ktcSfTep": ("name", None, "value", "position"),
    "fantasyCalc": ("name", "rank", "value", "position"),
    "dynastyDaddySf": ("name", "rank", "value", "position"),
    "dlfSf": ("name", "rank", None, "position"),
    "draftSharksSf": ("Player", "Rank", None, "Fantasy Position"),
    "fantasyProsSf": ("name", "Rank", None, "position"),
    "flockFantasySf": ("name", "Rank", None, "position"),
    "dynastyNerdsSfTep": ("Name", "Rank", None, "Pos"),
}


def git(*args: str) -> str:
    return subprocess.run(
        ["git", "-C", REPO, *args], capture_output=True, check=True
    ).stdout.decode("utf-8", errors="replace")


def norm(n: str) -> str:
    n = n.lower().replace(".", "").replace("'", "").replace("-", " ")
    n = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b", "", n)
    return " ".join(n.split())


_POSMAP: dict[str, str] = {}


def posmap() -> dict[str, str]:
    """name -> offense position from the CURRENT committed CSVs (positions are
    stable identity facts; older CSVs omit the column)."""
    if _POSMAP:
        return _POSMAP
    for key, (ncol, _r, _v, pcol) in SOURCES.items():
        try:
            txt = open(f"{REPO}/CSVs/site_raw/{key}.csv", encoding="utf-8").read()
        except OSError:
            continue
        for r in csv.DictReader(io.StringIO(txt)):
            pos = re.sub(r"\d", "", (r.get(pcol) or "")).strip().upper()
            nm = norm(r.get(ncol) or "")
            if nm and pos:
                _POSMAP.setdefault(nm, pos)
    return _POSMAP


def board(key: str, when: date) -> dict[str, float] | None:
    sha = git("log", "-1", f"--before={when.isoformat()}T23:59:59Z", "--format=%H", "origin/main", "--", f"CSVs/site_raw/{key}.csv").strip()
    if not sha:
        sha = git("log", "-1", f"--before={when.isoformat()}T23:59:59Z", "--format=%H", "--", f"CSVs/site_raw/{key}.csv").strip()
    if not sha:
        return None
    txt = git("show", f"{sha}:CSVs/site_raw/{key}.csv")
    ncol, rcol, vcol, pcol = SOURCES[key]
    rows = []
    for r in csv.DictReader(io.StringIO(txt)):
        pos = re.sub(r"\d", "", (r.get(pcol) or "")).strip().upper()
        if not pos:
            pos = posmap().get(norm(r.get(ncol) or ""), "")
        if pos not in OFF:
            continue
        try:
            sk = float(r[rcol]) if rcol else -float(r[vcol])
        except (TypeError, ValueError, KeyError):
            continue
        rows.append((sk, norm(r.get(ncol) or "")))
    rows.sort()
    out: dict[str, float] = {}
    for i, (_, nm) in enumerate(rows, 1):
        if nm and nm not in out:
            out[nm] = float(i)
    return out


def consensus(boards: dict[str, dict[str, float]], keys: list[str], nm: str):
    lr = [math.log(boards[k][nm]) for k in keys if nm in boards[k]]
    if len(lr) < 4:
        return None
    c = statistics.median(lr)
    d = statistics.median(abs(x - c) for x in lr)
    return c, d, len(lr)


def spearman(x: list[float], y: list[float]) -> float:
    def rk(v):
        o = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        i = 0
        while i < len(o):
            j = i
            while j + 1 < len(o) and v[o[j + 1]] == v[o[i]]:
                j += 1
            for t in range(i, j + 1):
                r[o[t]] = (i + j) / 2 + 1
            i = j + 1
        return r
    a, b = rk(x), rk(y)
    ma, mb = statistics.mean(a), statistics.mean(b)
    num = sum((p - ma) * (q - mb) for p, q in zip(a, b))
    den = math.sqrt(sum((p - ma) ** 2 for p in a) * sum((q - mb) ** 2 for q in b))
    return num / den if den else float("nan")


def main() -> None:
    t0s = [date(2026, 7, 20) + timedelta(days=7 * i) for i in range(9)]  # to 2026-09-14
    results = []
    pooled = {"top50": [], "51-150": [], "151-300": []}
    for t0 in t0s:
        t1 = t0 + timedelta(days=28)
        assert t1 <= date(2026, 10, 13)
        b0 = {k: board(k, t0) for k in SOURCES}
        b1 = {k: board(k, t1) for k in SOURCES}
        keys = [k for k in SOURCES if b0[k] and b1[k]]
        rows = []
        for nm in set().union(*(b0[k].keys() for k in keys)):
            ks = [k for k in keys if nm in b0[k] and nm in b1[k]]
            if len(ks) < 4:
                continue
            c0 = consensus(b0, ks, nm)
            c1 = consensus(b1, ks, nm)
            if not c0 or not c1:
                continue
            rows.append((math.exp(c0[0]), c0[1], abs(c1[0] - c0[0])))
        rec = {"t0": t0.isoformat(), "t1": t1.isoformat(), "sources": keys, "n": len(rows), "bands": {}}
        for band, lo, hi in (("top50", 0, 50), ("51-150", 50, 150), ("151-300", 150, 300)):
            sub = [r for r in rows if lo < r[0] <= hi]
            if len(sub) < 20:
                continue
            d = [r[1] for r in sub]
            rv = [r[2] for r in sub]
            # tercile contrast: mean revision in top vs bottom disagreement tercile
            srt = sorted(sub, key=lambda r: r[1])
            k3 = len(srt) // 3
            lo_t = statistics.mean(r[2] for r in srt[:k3])
            hi_t = statistics.mean(r[2] for r in srt[-k3:])
            rec["bands"][band] = {
                "n": len(sub),
                "spearman_disagreement_vs_abs_revision": round(spearman(d, rv), 3),
                "mean_abs_logrank_revision_low_disagreement_tercile": round(lo_t, 4),
                "mean_abs_logrank_revision_high_disagreement_tercile": round(hi_t, 4),
            }
            pooled[band].append(rec["bands"][band]["spearman_disagreement_vs_abs_revision"])
        results.append(rec)
    summary = {
        b: {
            "windows": len(v),
            "median_spearman": round(statistics.median(v), 3) if v else None,
            "min": min(v) if v else None,
            "max": max(v) if v else None,
            "windows_positive": sum(1 for x in v if x > 0),
        }
        for b, v in pooled.items()
    }
    json.dump({"windows": results, "summary": summary}, sys.stdout, indent=1)


if __name__ == "__main__":
    main()
