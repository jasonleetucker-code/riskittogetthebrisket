"""W16: 90d board count vs the 30d-hardcoded drill-down receipts."""

from __future__ import annotations
import json
import time
from pathlib import Path
from src.intel import store, service  # noqa: F401

SCRATCH = Path(
    "/tmp/claude-0/-home-user-riskittogetthebrisket/"
    "0f0078ff-84f2-50d3-bce6-2bb1d1d8e920/scratchpad/intel_probe3"
)
SCRATCH.mkdir(parents=True, exist_ok=True)
for f in SCRATCH.glob("*"):
    f.unlink()
store.DATA_DIR = SCRATCH

NOW = int(time.time() * 1000)
DAY = 86400_000
events = []


def ev(tx, owner, action, asset, age_days):
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
            "ts": NOW - age_days * DAY,
            "week": 1,
        }
    )


ev("TX_RECENT", "uA", "add", "p1", 3)
ev("TX_RECENT", "uB", "drop", "p1", 3)
ev("TX_OLD", "uB", "add", "p1", 45)
ev("TX_OLD", "uA", "drop", "p1", 45)

state = {
    "generatedAt": "2026-08-04T00:00:00+00:00",
    "members": {"uA": {"leagues": ["L1"]}, "uB": {"leagues": ["L1"]}},
    "leagues": {"L1": {"leagueId": "L1", "holdings": {}}},
    "events": events,
}
store.save_state(state, league_key="probe3")
service._SNAPSHOT_CACHE.clear()
service._LEDGER_SYNCED.clear()

board = service.build_summary_payload("probe3", window="90d")
row = next(a for a in board["assets"] if a["assetId"] == "p1")
detail = service.build_player_payload("probe3", "p1")
print(
    json.dumps(
        {
            "board_window": board["window"],
            "board_90d_volume": row["windows"]["90d"]["volume"],
            "board_30d_volume": row["windows"]["30d"]["volume"],
            "drilldown_window_field": detail.get("window"),
            "drilldown_movement_rows": len(detail.get("movements") or []),
        },
        indent=2,
    )
)
