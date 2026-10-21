"""H3 / H4 on the two E_BASELINE IDPTC partial-fallback boards (prereg §8).

Run from the repository root: python docs/sources/outlier_integrity_v2/replay/checks/h3_h4_e_baseline_check.py
Prints Justin Jefferson's IDP Trade Calculator observation under the incumbent
and V2-NOHIST (the B2 row proof does not need the history lane) and the B2
provenance block. Read-only.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.getcwd())

from scripts import joint_filter_shadow as J  # noqa: E402
from src.robust_filter_shadow import oiv2_replay as RP  # noqa: E402

for board in ("dynasty_export_20260803_235610.zip", "dynasty_export_20260806_150742.zip"):
    commit, cut = J.archive_add_commits()[board]
    _data, raw, site = J.load_archive(J.ARCHIVE_DIR / board)
    rep = J.StateReplayer()
    rep.advance(cut)
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        J.materialize_tree(root, commit, site)
        rep.write(root / "data" / "scrape_state")
        payload = (raw["players"].get("Justin Jefferson") or {}).get("_canonicalSiteValues", {})
        print(board, "payload JJ idptc", payload.get("idpTradeCalc"))
        for cfg in ("inc", "v2nh"):
            c = RP.build(raw, root, RP.CONFIGS[cfg])
            for r in c["playersArray"]:
                if r.get("displayName") == "Justin Jefferson":
                    m = (r.get("sourceRankMeta") or {}).get("idpTradeCalc") or {}
                    print(
                        " ",
                        cfg,
                        "vote",
                        m.get("valueContribution"),
                        "integrity",
                        m.get("integrity"),
                        "prov",
                        (r.get("sourceProvenance") or {}).get("idpTradeCalc"),
                        "dropped",
                        r.get("droppedSources"),
                        "value",
                        r.get("rankDerivedValue"),
                    )
            if cfg == "v2nh":
                prov = (c["sourceIntegrity"].get("provenance") or {}).get("idpTradeCalc")
                print("  provenance", json.dumps(prov)[:300])
    rep.close()
