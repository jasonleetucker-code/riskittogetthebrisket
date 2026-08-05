"""W08 evidence: the /trade "Raw" value mode is not cross-class comparable.

``values.raw`` is the legacy scraper composite (``_rawComposite``); ``values.full``
is the canonical board (``rankDerivedValue``). The ratio between them is NOT
constant across asset classes, so switching the /trade value-mode dropdown
re-weights offense against IDP.

Run:
    .venv/bin/python docs/master-site-audit/evidence/W08/raw_mode_class_drift.py
"""

from __future__ import annotations

import json
import re
import statistics
import subprocess
import sys
import tempfile
from pathlib import Path

BACKEND = "http://127.0.0.1:8000"
COOKIES = "/tmp/audit-cookies-w08.txt"
OFFENSE = {"QB", "RB", "WR", "TE"}
IDP = {"DL", "LB", "DB"}


def main() -> int:
    tmp = Path(tempfile.mkdtemp()) / "c.json"
    subprocess.run(
        ["curl", "-s", "-b", COOKIES, f"{BACKEND}/api/dynasty-data", "-o", str(tmp)],
        check=True,
    )
    data = json.loads(tmp.read_text())
    data = data.get("data", data)

    groups: dict[str, list[float]] = {"offense": [], "idp": [], "pick": []}
    exemplars: dict[tuple[int, str], tuple[str, int, int]] = {}
    for row in data["playersArray"]:
        rdv = row.get("rankDerivedValue")
        raw = (row.get("values") or {}).get("rawComposite")
        if not rdv or not raw:
            continue
        name = row["displayName"]
        if re.match(r"^20\d{2}\s", name):
            group = "pick"
        elif row.get("position") in OFFENSE:
            group = "offense"
        elif row.get("position") in IDP:
            group = "idp"
        else:
            continue
        groups[group].append(raw / rdv)
        if group in ("offense", "idp"):
            exemplars[(int(rdv), group)] = (name, int(rdv), int(raw))

    for group, ratios in groups.items():
        ratios.sort()
        print(
            f"{group:<8} n={len(ratios):<4} median rawComposite/board = "
            f"{statistics.median(ratios):.4f}"
        )
    off_med = statistics.median(groups["offense"])
    idp_med = statistics.median(groups["idp"])
    print(f"\noffense is {100 * (off_med / idp_med - 1):.2f}% heavier than IDP in Raw mode")

    print("\nboard-equal offense/IDP pairs (identical rankDerivedValue, different Raw):")
    shown = 0
    for (rdv, group), (name, _, raw) in sorted(exemplars.items()):
        if group != "offense":
            continue
        peer = exemplars.get((rdv, "idp"))
        if not peer:
            continue
        print(
            f"  board {rdv:>5}: {name:<20} raw {raw:>5}   vs   "
            f"{peer[0]:<20} raw {peer[2]:>5}   Raw-mode gap {raw - peer[2]:>+6}"
        )
        shown += 1
        if shown >= 8:
            break
    return 0


if __name__ == "__main__":
    sys.exit(main())
