"""W13 evidence: run the BDVM engine for real against the live contract.

Builds the §8.3 reconstructed baseline from the ALREADY-CACHED 2025
nflverse weekly stats (no network), then feeds the records straight into
run_valuation via projection_records -- so nothing is written under
data/bdvm/ and the running server's behaviour is unchanged.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path("/home/user/riskittogetthebrisket")
sys.path.insert(0, str(REPO))

from src.bdvm.baseline import build_baseline_records  # noqa: E402
from src.bdvm.params import load_param_set  # noqa: E402
from src.bdvm.service import run_valuation  # noqa: E402
from src.nfl_data import ingest  # noqa: E402
from src.utils.name_clean import normalize_player_name  # noqa: E402

OUT = Path(sys.argv[1])
contract = json.loads((Path("/tmp/w13-contract-full.json")).read_text())
scoring = (contract.get("sleeper") or {}).get("scoringSettings") or {}
print("scoring keys:", len(scoring))

weekly = ingest.fetch_weekly_stats([2025])
print("weekly rows:", len(weekly))

as_of = datetime.now(timezone.utc).date().isoformat()
records, summary = build_baseline_records(
    season=2026,
    as_of=as_of,
    weekly_rows=weekly,
    scoring_settings=scoring,
    name_normalizer=normalize_player_name,
)
print("baseline summary:", json.dumps(summary)[:600])

payload = run_valuation(
    contract,
    league_key="dynasty_main",
    params=load_param_set(),
    idp_enabled=True,
    scoring_profile="superflex_tep15_ppr1",
    projection_records=records,
    snapshot_as_of=as_of,
    season=2026,
    context={},
    events=[],
    schedule_weeks=None,
    actuals=(None, {}),
)
print("status:", payload.get("status"))
print("players:", len(payload.get("players") or []))
print("unpriced:", len(payload.get("unpriced") or []))
print("picks:", len(payload.get("picks") or []))
OUT.write_text(json.dumps(payload, indent=1, default=str))
print("written", OUT, OUT.stat().st_size)
