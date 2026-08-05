import json
import sys

sys.path.insert(0, "/home/user/riskittogetthebrisket")
from pathlib import Path
from src.sharp import cohort as sharp_cohort
from src.sharp import market as sharp_market

DB = Path(
    "/tmp/claude-0/-home-user-riskittogetthebrisket/0f0078ff-84f2-50d3-bce6-2bb1d1d8e920/scratchpad/w15/synthetic.sqlite3"
)

CFG = {
    "enabled": False,  # FFPC ingestion switched OFF
    "allowCuratedInCombinedSignals": True,  # but curated flag left ON
    "allowProvisionalPublicInCombinedSignals": False,
    "curatedManagers": [
        {
            "managerKey": "ffpc:site-user-999",
            "verified": True,
            "allowedToContribute": True,
            "weight": 0.9,
            "publicDisplayName": "Curated Guy",
            "sourceRationale": "test",
        }
    ],
    "seedLeagues": [],
}

# 1. What THE cohort definition says
members, cov = sharp_cohort.cohort_members(ledger_path=DB, ffpc_config=CFG)
curated_via_cohort = [
    m.manager_key for m in members if m.qualification_method == "curated_high_stakes"
]

# 2. What src/sharp/service.py::cohort_status computes for the SAME config
service_curated = (
    sharp_market.curated_members(CFG) if CFG.get("allowCuratedInCombinedSignals") else []
)
print(
    json.dumps(
        {
            "cohort_members_curated": curated_via_cohort,
            "cohort_coverage_curatedManagers": cov["curatedManagers"],
            "cohort_coverage_curatedContributionEnabled": cov["curatedContributionEnabled"],
            "service_cohort_status_curated_count": len(service_curated),
            "service_status_would_be": "ok" if (0 > 0 or service_curated) else "cohort_building",
            "market_status_would_be": "ok" if members else "cohort_building",
        },
        indent=2,
    )
)
