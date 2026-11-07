"""O7 prep (local): strip the private census evidence to the minimum the server-side
extraction needs, then render the one-shot server script with that input embedded.

Kept per trade: season, trade instant, census classes and fit, and per
asset: kind, family, draftKind, history key (``player:<sleeperPlayerId>``, public Sleeper
player id), pick season + round (picks get NO key: unpriced by construction).  DROPPED: transaction ids, roster ids, manager ids, team
labels, league ids, from/to, draft keys, week, observation ids.  Trade order is
shuffled with a fixed seed so nothing positional survives.

Usage: ``python scripts/research_o7/prep_input.py <census_private.json> <out_dir>``.
Writes ``o7_input.json`` and ``o7_run.py`` (template + embedded input) to ``out_dir``,
which must be outside the repository (the input is transaction-level).
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PRIVATE = Path(sys.argv[1])
OUT = Path(sys.argv[2])

ASSET_KEEP = ("kind", "family", "draftKind")


def main() -> int:
    priv = json.loads(PRIVATE.read_text(encoding="utf-8"))
    trades = []
    for r in priv["trades"]:
        assets = []
        for a in r["assets"]:
            out = {k: a.get(k) for k in ASSET_KEEP}
            if a["kind"] == "player":
                out["key"] = f"player:{a['playerId']}"
            elif a["kind"] == "pick":
                pk = a.get("pick") or {}
                out["pickSeason"] = pk.get("season")
                out["pickRound"] = pk.get("round")
            assets.append(out)
        trades.append(
            {
                "season": r["season"],
                "instant": r["instant"],
                "classes": r["classes"],
                "fit": r["fit"]["fit"],
                "assets": assets,
            }
        )
    random.Random(20261027).shuffle(trades)
    payload = {"schema": "o7_input/v1", "trades": trades}
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    for bad in ("txid", "rosterIds", "managerIds", "teamLabels", "leagueId", '"from"', '"to"'):
        assert bad not in text, bad
    (OUT / "o7_input.json").write_text(text, encoding="utf-8")
    template = (HERE / "server_extraction.py").read_text(encoding="utf-8")
    token = '"__O7_INPUT__"'
    assert template.count(token) == 1
    rendered = template.replace(token, repr(text))
    (OUT / "o7_run.py").write_bytes(rendered.replace("\r\n", "\n").encode("utf-8"))
    print(f"trades={len(trades)} assets={sum(len(t['assets']) for t in trades)} bytes={len(text)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
