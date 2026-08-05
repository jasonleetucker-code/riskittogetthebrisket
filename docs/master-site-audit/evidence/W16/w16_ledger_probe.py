"""W16: exercise the intel ledger/crawler counting rules on a throwaway DB."""

from __future__ import annotations
import json
import time
from pathlib import Path
from src.intel import crawler, ledger, signals

NOW = int(time.time() * 1000)
DAY = 86400_000
out = {}

# --- 1. three-team trade through the REAL crawler extractor ---------
rid_to_owner = {"1": "uA", "2": "uB", "3": "uC"}
pool = {"uA", "uB", "uC"}
tx3 = {
    "status": "complete",
    "type": "trade",
    "transaction_id": "T3",
    "created": NOW - 2 * DAY,
    "adds": {"p1": "2", "p2": "3", "p3": "1"},
    "drops": {"p1": "1", "p2": "2", "p3": "3"},
    "draft_picks": [
        {"season": "2027", "round": 1, "roster_id": 1, "owner_id": 2, "previous_owner_id": 1},
        {"season": "2027", "round": 1, "roster_id": 3, "owner_id": 2, "previous_owner_id": 3},
    ],
}
seen = set()
ev3 = crawler._events_from_tx(tx3, "L1", 1, rid_to_owner, pool, seen)
out["three_team_events"] = len(ev3)
out["three_team_event_ids"] = sorted(e["eventId"] for e in ev3)
# re-extract the same tx (a refetch) with the same seen-set
ev3b = crawler._events_from_tx(tx3, "L1", 1, rid_to_owner, pool, seen)
out["refetch_events"] = len(ev3b)

# waiver + failed tx
wv = {
    "status": "complete",
    "type": "waiver",
    "transaction_id": "W1",
    "created": NOW - 3 * DAY,
    "adds": {"p1": "1"},
    "drops": {"p9": "1"},
    "settings": {"waiver_bid": 42},
}
failed = {
    "status": "failed",
    "type": "waiver",
    "transaction_id": "W2",
    "created": NOW - 3 * DAY,
    "adds": {"p1": "2"},
    "settings": {"waiver_bid": 99},
}
evw = crawler._events_from_tx(wv, "L1", 1, rid_to_owner, pool, seen)
evf = crawler._events_from_tx(failed, "L1", 1, rid_to_owner, pool, seen)
out["waiver_events"] = len(evw)
out["failed_tx_events"] = len(evf)
out["waiver_faab"] = [e["faabBid"] for e in evw]
out["counterparty_present"] = sorted({str(e.get("counterpartyUserId")) for e in ev3})

# an older trade, 45 days back, for window separation
old = {
    "status": "complete",
    "type": "trade",
    "transaction_id": "T_OLD",
    "created": NOW - 45 * DAY,
    "adds": {"p1": "3"},
    "drops": {"p1": "2"},
}
evo = crawler._events_from_tx(old, "L1", 1, rid_to_owner, pool, seen)

path = Path(
    "/tmp/claude-0/-home-user-riskittogetthebrisket/0f0078ff-84f2-50d3-bce6-2bb1d1d8e920/scratchpad/w16.sqlite3"
)
path.unlink(missing_ok=True)
all_ev = ev3 + evw + evf + evo
r1 = ledger.ingest_events(all_ev, path=path)
r2 = ledger.ingest_events(all_ev, path=path)  # idempotency
out["ingest_first"] = [r1.movements_seen, r1.movements_inserted, r1.transactions_inserted]
out["ingest_second"] = [r2.movements_seen, r2.movements_inserted, r2.transactions_inserted]

conn = ledger.connect(path)
for win in ("7d", "30d", "90d"):
    since, until = signals.window_bounds(win, NOW)
    trades = ledger.asset_signals(
        since_ms=since,
        until_ms=until,
        tx_types=ledger.TRADE_TX_TYPES,
        user_ids=sorted(pool),
        conn=conn,
    )
    wvs = ledger.asset_signals(
        since_ms=since,
        until_ms=until,
        tx_types=ledger.WAIVER_TX_TYPES,
        user_ids=sorted(pool),
        conn=conn,
    )
    out[f"trades_{win}"] = {
        r["assetId"]: {"buys": r["buys"], "sells": r["sells"], "volume": r["volume"]}
        for r in trades
    }
    out[f"waivers_{win}"] = {r["assetId"]: {"buys": r["buys"], "sells": r["sells"]} for r in wvs}
conn.close()
print(json.dumps(out, indent=2))
