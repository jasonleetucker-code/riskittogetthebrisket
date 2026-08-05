"""W16: member payload tradeCount vs the real number of trades."""

from __future__ import annotations
import json
import time
from pathlib import Path
from src.intel import store, service, ledger  # noqa: F401

SCRATCH = Path(
    "/tmp/claude-0/-home-user-riskittogetthebrisket/"
    "0f0078ff-84f2-50d3-bce6-2bb1d1d8e920/scratchpad/intel_probe2"
)
SCRATCH.mkdir(parents=True, exist_ok=True)
for f in SCRATCH.glob("*"):
    f.unlink()
store.DATA_DIR = SCRATCH

NOW = int(time.time() * 1000)
events = []


def ev(tx, owner, action, asset):
    events.append(
        {
            "eventId": f"{tx}:{owner}:{action}:{asset}",
            "txId": tx,
            "leagueId": "L1",
            "ownerId": owner,
            "assetId": asset,
            "assetType": "player",
            "action": action,
            "txType": "trade",
            "ts": NOW - 86400_000,
            "week": 1,
        }
    )


# ONE trade: uA sends p1+p2, receives p3.  Exactly 1 trade, 3 assets.
for a in ("p1", "p2"):
    ev("TX1", "uA", "drop", a)
    ev("TX1", "uB", "add", a)
ev("TX1", "uA", "add", "p3")
ev("TX1", "uB", "drop", "p3")

state = {
    "generatedAt": "2026-08-04T00:00:00+00:00",
    "members": {"uA": {"leagues": ["L1"]}, "uB": {"leagues": ["L1"]}},
    "leagues": {"L1": {"leagueId": "L1", "holdings": {}}},
    "events": events,
}
store.save_state(state, league_key="probe2")
service._SNAPSHOT_CACHE.clear()
service._LEDGER_SYNCED.clear()

payload = service.build_member_payload("probe2", "uA")
print(
    json.dumps(
        {
            "realDistinctTrades": 1,
            "reportedTradeCount": payload["tradeCount"],
            "movementCount": payload["movementCount"],
            "assetRows": [
                {"assetId": r["assetId"], "tradeCount": r["tradeCount"]} for r in payload["assets"]
            ],
        },
        indent=2,
    )
)
