"""Build one board offline and dump a compact, deterministic summary + full contract.

Evidence for ``docs/picks/PICK_CLASS_GUARD_EVIDENCE_2026-11-21.md``.

usage (from the repository root):
    python docs/picks/evidence/pick_class_guard_2026-11-21/build_board.py <mode> <board> <out>
  mode  : head | off | on
          head = the PRE-CHANGE src/api/data_contract.py, loaded as an overlay
                 module (first: mkdir -p .pick_guard_head_overlay/api &&
                 git show 110d1f54ce:src/api/data_contract.py \
                   > .pick_guard_head_overlay/api/data_contract.py ;
                 delete the directory afterwards, never commit it),
          off  = this branch, flag pick_class_tether_guard OFF,
          on   = this branch, flag ON.
  board : pinned | latest | archive:<zipname>
          pinned = tests/fixtures/pinned_board (2026-11-15, every input frozen);
          latest = exports/latest/dynasty_data_2026-11-21.json + the tracked CSVs;
          archive:<zip> = an exports/archive payload + the tracked CSVs.
Writes <out>.contract.json (sorted keys) and <out>.rows.json.  The clock is
frozen at the board's own scrape time and the temporal ledger is absent, so two
runs of one mode produce the same bytes.
"""

from __future__ import annotations

import json
import os
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

REPO = Path.cwd()
sys.path.insert(0, str(REPO))

mode, board, out_prefix = sys.argv[1], sys.argv[2], sys.argv[3]
# parents[2] of the overlay module must be the repo root (config paths are
# resolved relative to data_contract.py's own location).
OVERLAY = REPO / ".pick_guard_head_overlay" / "api"

os.environ.pop("RISKIT_FEATURE_PICK_CLASS_TETHER_GUARD", None)
if mode == "on":
    os.environ["RISKIT_FEATURE_PICK_CLASS_TETHER_GUARD"] = "1"

if mode == "head":
    import src.api  # noqa: E402

    src.api.__path__.insert(0, str(OVERLAY))

from src.api import data_contract as dc  # noqa: E402
from src.api import feature_flags  # noqa: E402

feature_flags.reload()
if mode == "head":
    assert ".pick_guard_head_overlay" in dc.__file__, dc.__file__
    assert not hasattr(dc, "PICK_CLASS_TETHER_GUARD_FLAG")
else:
    assert ".pick_guard_head_overlay" not in dc.__file__
    assert feature_flags.is_enabled("pick_class_tether_guard") is (mode == "on")

from tests import archive_fixtures as af  # noqa: E402
from src.history import store as ledger_store  # noqa: E402

if board == "pinned":
    raw, _label = af.pinned_board_payload()
    with af.pinned_build_environment() as root:
        contract = dc.build_api_data_contract(raw, csv_root=root)
elif board == "latest":
    raw = json.loads(
        (REPO / "exports/latest/dynasty_data_2026-11-21.json").read_text(encoding="utf-8")
    )
    ledger_store.DB_PATH = REPO / "data" / "__no_ledger__" / "temporal_ledger.sqlite"
    as_of = datetime.fromisoformat(str(raw["scrapeTimestamp"]).replace("Z", "+00:00"))
    with af.frozen_build_clock(as_of.astimezone(timezone.utc)):
        contract = dc.build_api_data_contract(raw)
elif board.startswith("archive:"):
    name = board.split(":", 1)[1]
    with zipfile.ZipFile(REPO / "exports" / "archive" / name) as zf:
        member = [
            n for n in zf.namelist() if n.startswith("dynasty_data_") and n.endswith(".json")
        ][0]
        raw = json.loads(zf.read(member))
    ledger_store.DB_PATH = REPO / "data" / "__no_ledger__" / "temporal_ledger.sqlite"
    as_of = datetime.fromisoformat(str(raw["scrapeTimestamp"]).replace("Z", "+00:00"))
    with af.frozen_build_clock(as_of.astimezone(timezone.utc)):
        contract = dc.build_api_data_contract(raw)
else:
    raise SystemExit(f"unknown board {board}")

health = dc.validate_api_data_contract(contract)
rows = {}
for r in contract["playersArray"]:
    rows[str(r.get("canonicalName"))] = {
        "assetClass": r.get("assetClass"),
        "value": r.get("rankDerivedValue"),
        "rank": r.get("canonicalConsensusRank"),
        "tier": r.get("canonicalTierId"),
        "prov": r.get("pickValueProvenance"),
        "anchor": r.get("pickRookieAnchor"),
        "conf": r.get("confidenceBasis"),
        "sites": {
            k: v
            for k, v in (r.get("canonicalSiteValues") or {}).items()
            if k in ("ktcCrowdSfTep", "ktcTradesSfTep", "idpTradeCalc", "ktc")
        },
        "rookie": r.get("rookie"),
        "yearsExp": r.get("yearsExp"),
    }
summary = {
    "mode": mode,
    "board": board,
    "currentDraftYear": contract.get("currentDraftYear"),
    "pickClassTetherGuard": contract.get("pickClassTetherGuard"),
    "health": {
        "ok": health.get("ok"),
        "status": health.get("status"),
        "errors": health.get("errors"),
        "structuralErrors": health.get("structuralErrors"),
        "warningCount": len(health.get("warnings") or []),
    },
    "rows": rows,
}
Path(out_prefix + ".rows.json").write_text(
    json.dumps(summary, sort_keys=True, indent=1, default=str), encoding="utf-8"
)
Path(out_prefix + ".contract.json").write_text(
    json.dumps(contract, sort_keys=True, default=str), encoding="utf-8"
)
print(mode, board, "ok=", health.get("ok"), "errors=", (health.get("errors") or [])[:5])
