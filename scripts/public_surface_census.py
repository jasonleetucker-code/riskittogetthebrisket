"""Read-only census of identifying fields in public JSON payloads.

Counts, by leaf field name, every value that is a Sleeper-user-id-shaped
string (15-20 digits), a 32-hex avatar hash, or a dict key of either shape,
plus the named display fields.  Used by ``docs/security/PUBLIC_SURFACE_CENSUS_2026-11-15.md``
(owner decision brief 11).  It reads files or URLs you name; one request each,
no crawling.  It changes nothing.

    python scripts/public_surface_census.py league.json dc.json
    python scripts/public_surface_census.py https://chaseupside.com/api/public/league
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any

SLEEPER_ID = re.compile(r"^\d{15,20}$")
AVATAR_HASH = re.compile(r"^[0-9a-f]{32}$")
NAME_FIELDS = frozenset(
    {
        "displayName",
        "displayNames",
        "teamName",
        "currentTeamName",
        "originDisplayName",
        "winnerDisplayName",
        "currentOwner",
        "originalOwner",
    }
)


def census(payload: Any) -> dict[str, Counter]:
    """``{"ids": Counter(field), "idKeys": Counter, "avatars": Counter,
    "names": Counter, "distinctIds": Counter}``; leaf name is the nearest
    dict key (list items inherit their list's key)."""
    out: dict[str, Counter] = {k: Counter() for k in ("ids", "idKeys", "avatars", "names")}
    distinct: set[str] = set()

    def walk(value: Any, field: str) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if isinstance(key, str) and SLEEPER_ID.match(key):
                    out["idKeys"][field + ".{id}"] += 1
                    distinct.add(key)
                walk(item, str(key))
        elif isinstance(value, list):
            for item in value:
                walk(item, field)
        elif isinstance(value, str):
            if SLEEPER_ID.match(value):
                out["ids"][field] += 1
                distinct.add(value)
            elif AVATAR_HASH.match(value):
                out["avatars"][field] += 1
            elif field in NAME_FIELDS:
                out["names"][field] += 1

    walk(payload, "$")
    out["distinctIds"] = Counter({"distinct": len(distinct)})
    return out


def _load(source: str) -> Any:
    if source.startswith(("http://", "https://")):
        with urllib.request.urlopen(source, timeout=60) as resp:  # noqa: S310 - operator-named URL
            return json.loads(resp.read().decode("utf-8"))
    return json.loads(Path(source).read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("sources", nargs="+", help="JSON file paths or http(s) URLs")
    args = parser.parse_args(argv)
    for source in args.sources:
        result = census(_load(source))
        print(f"== {source}")
        for kind in ("ids", "idKeys", "avatars", "names"):
            for field, count in result[kind].most_common():
                print(f"  {kind:8s} {field:32s} {count}")
        print(f"  distinct Sleeper-id-shaped values: {result['distinctIds']['distinct']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
