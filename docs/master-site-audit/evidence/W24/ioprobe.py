"""pytest plugin: record every file opened during a run, under the repo's data trees.

Usage:
    .venv/bin/python -m pytest <targets> -p ioprobe -q

Writes the sorted set of touched paths to ``W24_IOPROBE_OUT`` (default
``/tmp/w24-ioprobe.txt``).  Used to prove that a ``livedata``-marked test
module never actually reads ``exports/``, ``CSVs/`` or ``data/``.
"""

from __future__ import annotations

import os
import sys

REPO = "/home/user/riskittogetthebrisket"
WATCHED = (f"{REPO}/exports", f"{REPO}/CSVs", f"{REPO}/data")
_HITS: set[str] = set()


def _hook(event: str, args: tuple) -> None:
    if event != "open":
        return
    path = args[0]
    if not isinstance(path, str):
        return
    full = path if path.startswith("/") else os.path.abspath(path)
    for w in WATCHED:
        if full.startswith(w):
            _HITS.add(full)


sys.addaudithook(_hook)


def pytest_sessionfinish(session, exitstatus):  # noqa: ARG001
    out = os.environ.get("W24_IOPROBE_OUT", "/tmp/w24-ioprobe.txt")
    with open(out, "w", encoding="utf-8") as fh:
        for p in sorted(_HITS):
            fh.write(p + "\n")
    print(f"\n[ioprobe] {len(_HITS)} distinct paths under exports/ CSVs/ data/ -> {out}")
