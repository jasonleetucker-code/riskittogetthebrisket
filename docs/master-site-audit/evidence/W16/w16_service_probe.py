"""W16: run the REAL build_summary_payload against a synthetic snapshot in a
scratch DATA_DIR (no repo writes) to test the home-league exclusion claim."""

from __future__ import annotations
import json
import time
from pathlib import Path
from src.intel import store, ledger, service, ingest  # noqa: F401

SCRATCH = Path(
    "/tmp/claude-0/-home-user-riskittogetthebrisket/0f0078ff-84f2-50d3-bce6-2bb1d1d8e920/scratchpad/intel_probe"
)
SCRATCH.mkdir(parents=True, exist_ok=True)
for f in SCRATCH.glob("*"):
    f.unlink()
store.DATA_DIR = SCRATCH  # snapshot_path + ledger.default_path both read this

NOW = int(time.time() * 1000)
DAY = 86400_000
HOME = "HOME_LEAGUE_1"  # the league the user is asking about
AWAY = "AWAY_LEAGUE_2"

events = []


def ev(tx, league, owner, action, asset, ts):
    events.append(
        {
            "eventId": f"{tx}:{owner}:{action}:{asset}",
            "txId": tx,
            "leagueId": league,
            "ownerId": owner,
            "assetId": asset,
            "assetType": "player",
            "action": action,
            "txType": "trade",
            "ts": ts,
            "week": 1,
        }
    )


# One trade INSIDE the home league, one in an away league. Different assets.
ev("TX_HOME", HOME, "uA", "add", "pHOME", NOW - 2 * DAY)
ev("TX_HOME", HOME, "uB", "drop", "pHOME", NOW - 2 * DAY)
ev("TX_AWAY", AWAY, "uA", "add", "pAWAY", NOW - 2 * DAY)
ev("TX_AWAY", AWAY, "uB", "drop", "pAWAY", NOW - 2 * DAY)

state = {
    "generatedAt": "2026-08-04T00:00:00+00:00",
    "season": "2026",
    "leagueKey": "probe",
    "homeLeagueId": HOME,
    "members": {"uA": {"displayName": "A"}, "uB": {"displayName": "B"}},
    "leagues": {HOME: {"leagueId": HOME, "holdings": {}}, AWAY: {"leagueId": AWAY, "holdings": {}}},
    "events": events,
}
store.save_state(state, league_key="probe")
service._SNAPSHOT_CACHE.clear()
service._LEDGER_SYNCED.clear()

payload = service.build_summary_payload("probe", limit=50)
assets = {a["assetId"]: a["windows"]["30d"] for a in payload["assets"]}
out = {
    "ledgerPath": str(ledger.default_path()),
    "snapshotPath": str(store.snapshot_path("probe")),
    "boardAssets": sorted(assets),
    "homeLeagueTradeOnBoard": "pHOME" in assets,
    "awayLeagueTradeOnBoard": "pAWAY" in assets,
    "pHOME_window30d": assets.get("pHOME"),
    "payloadKeys": sorted(payload.keys()),
    "hasCoverageBlock": any(
        k.lower().startswith("coverage") or k in ("earliestObservedTs", "retentionDays")
        for k in payload
    ),
}
print(json.dumps(out, indent=2))
