#!/usr/bin/env python3
"""Corridor replay — what does a contract build ACTUALLY read?

Requirement 2 of the historical-replay correction: an exhaustive manifest
of every input the current ``build_api_data_contract`` path consumes,
"traced from executable current HEAD" rather than assumed.

Static grepping is not enough here — it finds the reads it can see and
silently misses dynamic paths, lazily-imported helpers and network calls.
So this instruments the interpreter instead: ``builtins.open``,
``Path.open`` / ``read_text`` / ``read_bytes`` and
``urllib.request.urlopen`` are wrapped for the duration of one real
build, and every access is recorded with a traceback-derived caller.

Run ``--manifest`` to print and persist the result.
"""

from __future__ import annotations

import argparse
import builtins
import contextlib
import io
import json
import sys
import traceback
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
OUT = Path(__file__).resolve().parent

READS: list[dict] = []
WRITES: list[dict] = []
NETWORK: list[dict] = []


def _caller() -> str:
    for fr in reversed(traceback.extract_stack()[:-2]):
        f = fr.filename
        if "cd_input_manifest" in f or "/importlib" in f or f.startswith("<"):
            continue
        try:
            rel = str(Path(f).resolve().relative_to(ROOT))
        except ValueError:
            continue
        if rel.startswith(("src/", "scripts/", "server.py")):
            return f"{rel}:{fr.lineno}"
    return "?"


def _record(path, mode: str) -> None:
    try:
        p = Path(path).resolve()
    except (TypeError, ValueError, OSError):
        return
    try:
        rel = str(p.relative_to(ROOT))
    except ValueError:
        rel = str(p)
    entry = {"path": rel, "mode": mode, "caller": _caller()}
    (WRITES if any(m in mode for m in ("w", "a", "x", "+")) else READS).append(entry)


@contextlib.contextmanager
def instrument():
    real_open = builtins.open
    real_p_open = Path.open
    real_rt = Path.read_text
    real_rb = Path.read_bytes
    real_url = urllib.request.urlopen

    def my_open(file, mode="r", *a, **k):
        _record(file, mode)
        return real_open(file, mode, *a, **k)

    def my_p_open(self, mode="r", *a, **k):
        _record(self, mode)
        return real_p_open(self, mode, *a, **k)

    def my_rt(self, *a, **k):
        _record(self, "r")
        return real_rt(self, *a, **k)

    def my_rb(self, *a, **k):
        _record(self, "rb")
        return real_rb(self, *a, **k)

    def my_url(req, *a, **k):
        url = getattr(req, "full_url", None) or str(req)
        NETWORK.append({"url": url, "caller": _caller()})
        return real_url(req, *a, **k)

    builtins.open = my_open
    Path.open = my_p_open
    Path.read_text = my_rt
    Path.read_bytes = my_rb
    urllib.request.urlopen = my_url
    try:
        yield
    finally:
        builtins.open = real_open
        Path.open = real_p_open
        Path.read_text = real_rt
        Path.read_bytes = real_rb
        urllib.request.urlopen = real_url


#: Roots whose contents are METHODOLOGY, not market data. A historical
#: replay deliberately keeps these at current HEAD — the experiment is
#: "current methodology against past market states".
METHODOLOGY_PREFIXES = ("config/", "src/", "scripts/", "CSVs/Draft Data", "requirements")

#: Roots that carry MARKET DATA. A historical replay must redirect these
#: or it is not historical.
DATA_PREFIXES = ("CSVs/site_raw/", "exports/", "data/")


def classify(rel: str) -> str:
    if rel.startswith("CSVs/site_raw/"):
        return "MARKET DATA (must redirect)"
    if rel.startswith(DATA_PREFIXES):
        return "STATE/DATA (must redirect or neutralise)"
    if rel.startswith(METHODOLOGY_PREFIXES):
        return "methodology/config (keep current)"
    if ".venv" in rel or "site-packages" in rel or rel.startswith("/"):
        return "interpreter/library"
    return "UNCLASSIFIED — decide explicitly"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", action="store_true")
    args = ap.parse_args()
    if not args.manifest:
        ap.error("pass --manifest")

    from src.api.data_contract import build_api_data_contract

    board = sorted((ROOT / "exports/latest").glob("dynasty_data_*.json"), reverse=True)[0]
    raw = json.loads(board.read_bytes())

    with instrument(), contextlib.redirect_stdout(io.StringIO()):
        build_api_data_contract(raw)

    # Collapse to unique (path, caller) and drop library noise.
    def interesting(entries):
        seen, out = set(), []
        for e in entries:
            if classify(e["path"]) == "interpreter/library":
                continue
            k = (e["path"], e["caller"])
            if k in seen:
                continue
            seen.add(k)
            out.append(e)
        return sorted(out, key=lambda e: (classify(e["path"]), e["path"]))

    reads, writes = interesting(READS), interesting(WRITES)

    print("== inputs a contract build ACTUALLY reads (instrumented, current HEAD) ==")
    cur = None
    for e in reads:
        c = classify(e["path"])
        if c != cur:
            print(f"\n-- {c} --")
            cur = c
        print(f"  {e['path']:<52}  <- {e['caller']}")

    print("\n== WRITES during a build (mutation risk in a replay) ==")
    if writes:
        for e in writes:
            print(f"  {e['path']:<52}  <- {e['caller']}  mode={e['mode']}")
    else:
        print("  none")

    print("\n== NETWORK during a build (nondeterminism / current-state leak) ==")
    if NETWORK:
        for e in NETWORK:
            print(f"  {e['url']}  <- {e['caller']}")
    else:
        print("  none reached on this build")

    by_class: dict[str, list[str]] = {}
    for e in reads:
        by_class.setdefault(classify(e["path"]), []).append(e["path"])
    print("\n== summary ==")
    for c, ps in sorted(by_class.items()):
        print(f"  {c:<40} {len(set(ps))} path(s)")

    payload = {
        "codeSha": __import__("subprocess")
        .run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True)
        .stdout.strip(),
        "reads": reads,
        "writes": writes,
        "network": NETWORK,
        "byClass": {c: sorted(set(p)) for c, p in by_class.items()},
    }
    (OUT / "cd_input_manifest.json").write_text(json.dumps(payload, indent=1))
    print(f"\nwrote {OUT / 'cd_input_manifest.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
