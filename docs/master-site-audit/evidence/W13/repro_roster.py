"""W13: roster / trade-eval / surplus-ablation evidence with a real snapshot."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path("/home/user/riskittogetthebrisket")
sys.path.insert(0, str(REPO))

from src.bdvm.baseline import build_baseline_records  # noqa: E402
from src.bdvm.league_config import from_contract  # noqa: E402
from src.bdvm.params import load_param_set  # noqa: E402
from src.bdvm.roster import analyze_rosters, scan_double_positive_trades  # noqa: E402
from src.bdvm.service import run_valuation  # noqa: E402
from src.nfl_data import ingest  # noqa: E402
from src.utils.name_clean import normalize_player_name  # noqa: E402

OUT = Path(sys.argv[1])
contract = json.loads(Path("/tmp/w13-contract-full.json").read_text())
scoring = (contract.get("sleeper") or {}).get("scoringSettings") or {}
weekly = ingest.fetch_weekly_stats([2025])
as_of = datetime.now(timezone.utc).date().isoformat()
records, _ = build_baseline_records(
    season=2026,
    as_of=as_of,
    weekly_rows=weekly,
    scoring_settings=scoring,
    name_normalizer=normalize_player_name,
)
P = load_param_set()


def value(mode):
    return run_valuation(
        contract,
        league_key="dynasty_main",
        params=P,
        idp_enabled=True,
        scoring_profile="superflex_tep15_ppr1",
        projection_records=records,
        snapshot_as_of=as_of,
        season=2026,
        surplus_mode=mode,
        context={},
        events=[],
        schedule_weeks=None,
        actuals=(None, {}),
    )


res = {}
vals = {m: value(m) for m in ("option", "truncated", "plain")}
v = vals["option"]


# --- surplus ablation actually changes numbers ---
def tv(pay, name):
    for p in pay["players"]:
        if p["name"] == name:
            return round(p["tradeValue"]["balanced"], 1)
    return None


sample = [p["name"] for p in v["players"][:6]]
res["surplusAblation"] = {n: {m: tv(vals[m], n) for m in vals} for n in sample}

# --- roster analysis ---
cfg = from_contract(
    contract,
    league_key="dynasty_main",
    registry_roster_settings=None,
    idp_enabled=True,
    scoring_profile="superflex_tep15_ppr1",
    waiver_buffer=P["replacement"]["waiver_buffer"],
    default_buffer=float(P["replacement"]["default_buffer"]),
)
analysis = analyze_rosters(v, contract, P, league_cfg_meta=cfg.to_meta())
rosters = analysis.get("rosters") or []
unpriced_names = {p["name"] for p in v["picks"] if not p.get("distribution")}
held = []
for r in rosters:
    names = [a.get("name") for a in (r.get("assets") or [])]
    held.append(
        {
            "team": r.get("name"),
            "assets": len(names),
            "pickCount": r.get("pickCount"),
            "unpricedPicksHeld": sorted(n for n in names if n in unpriced_names),
            "capitals": r.get("capitals"),
        }
    )
res["rosters"] = held
res["rosterCount"] = len(rosters)
res["unpricedPickNames"] = sorted(unpriced_names)

# --- trade scan ---
scan = scan_double_positive_trades(analysis, P, team=None)
res["tradeScan"] = {
    "tradeCount": len(scan.get("trades") or []),
    "keys": sorted(scan.keys()),
    "sample": (scan.get("trades") or [None])[0],
}
OUT.write_text(json.dumps(res, indent=1, default=str))
print(json.dumps(res["surplusAblation"], indent=1))
print("rosters:", res["rosterCount"])
for h in held:
    print(
        " ",
        h["team"],
        "assets",
        h["assets"],
        "picks",
        h["pickCount"],
        "unpricedHeld",
        h["unpricedPicksHeld"],
    )
print("trades:", res["tradeScan"]["tradeCount"])
