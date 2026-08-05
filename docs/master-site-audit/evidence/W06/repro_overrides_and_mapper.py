#!/usr/bin/env python3
"""W06 reproduction: id_overrides precedence + unified_mapper ladder.

Run:  .venv/bin/python docs/master-site-audit/evidence/W06/repro_overrides_and_mapper.py
"""

from __future__ import annotations
import json
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO))
from src.identity import unified_mapper as um  # noqa: E402

print("== A. id_overrides.json as shipped ==")
print("   live override keys:", list(um._load_overrides().keys()))

print("\n== B. override precedence (docstring: 'short-circuits the match ladder') ==")
ov = {
    "999": {
        "gsis_id": "00-9999999",
        "espn_id": "123",
        "full_name": "OVERRIDE NAME",
        "position": "WR",
        "team": "ZZZ",
    }
}
p = Path(tempfile.mkdtemp()) / "ov.json"
p.write_text(json.dumps(ov))
um.reload_overrides()
directory = {
    "999": {
        "player_id": "999",
        "gsis_id": "00-0000001",
        "espn_id": "1",
        "full_name": "DIRECTORY NAME",
        "position": "RB",
        "team": "AAA",
    }
}
r = um.resolve_player(directory, sleeper_id="999", overrides_path=p)
print("   directory HAS 999 ->", r.match_method, "/", r.full_name, "/ gsis", r.gsis_id)
print("   EXPECTED per docstring: manual_override / OVERRIDE NAME / 00-9999999")
r2 = um.resolve_player({}, sleeper_id="999", overrides_path=p)
print("   directory EMPTY      ->", r2.match_method, "/", r2.full_name)
um.reload_overrides()

print("\n== C. homonym without a position: caller-supplied team is ignored ==")
d = {
    "4984": {
        "player_id": "4984",
        "gsis_id": "00-0034857",
        "espn_id": "3918298",
        "full_name": "Josh Allen",
        "position": "QB",
        "team": "BUF",
    },
    "5537": {
        "player_id": "5537",
        "gsis_id": "00-0035691",
        "espn_id": "3915511",
        "full_name": "Josh Allen",
        "position": "LB",
        "team": "JAX",
    },
}
for team in ("JAX", "BUF"):
    g = um.resolve_player(d, name="Josh Allen", team=team)
    print(
        f"   name='Josh Allen' team={team} -> {g.full_name} {g.position}/{g.team} "
        f"conf={g.confidence} method={g.match_method}"
    )
d2 = {k: d[k] for k in ("5537", "4984")}
g = um.resolve_player(d2, name="Josh Allen", team="BUF")
print(f"   same call, dict order reversed -> {g.position}/{g.team}  (answer flips)")

print("\n== D. resolve_many index rebuild ==")
big = {
    str(i): {
        "player_id": str(i),
        "gsis_id": f"00-{i:07d}",
        "espn_id": str(100000 + i),
        "full_name": f"Player{i} Surname{i % 500}",
        "position": "WR",
        "team": "AAA",
    }
    for i in range(11000)
}
inputs = [{"sleeper_id": str(i)} for i in range(200)]
t0 = time.perf_counter()
um.resolve_many(big, inputs)
many = time.perf_counter() - t0
t0 = time.perf_counter()
um._index_directory(big)
one = time.perf_counter() - t0
print(f"   resolve_many(200 rows, 11k directory): {many:.3f}s")
print(f"   one _index_directory build           : {one:.3f}s")
print(
    f"   ratio                                : {many/one:.0f}x "
    f"(docstring: 'index is built once, not per-row')"
)
