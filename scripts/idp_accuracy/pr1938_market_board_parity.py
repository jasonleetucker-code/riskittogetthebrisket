"""Is the market board (``/api/data``) the same under both realized-points scorers?

Research/measurement only; writes only ``--out``.  Builds the served contract
(``build_api_data_contract``) from ONE raw export twice, each in a fresh
interpreter so no module state is shared:

* ``current``   -- ``src/nfl_data/realized_points.py`` at ``--base-ref``
  (default ``origin/main``), installed as ``src.nfl_data.realized_points``
  BEFORE anything else is imported, so every importer gets it;
* ``corrected`` -- the working tree's file (PR #1938).

Per row (keyed by ``displayName``) it compares ``rankDerivedValue``,
``canonicalConsensusRank`` and ``confidenceBucket``, and reports the row count,
a hash of each arm's table and every row that differs.  The permanent guard is
``tests/idp_accuracy/test_market_board_does_not_read_realized_points.py``; this
script is the one-off measurement on a real export.

    python scripts/idp_accuracy/pr1938_market_board_parity.py \
        --export exports/latest/dynasty_data_2026-11-07.json \
        --out docs/valuation/idp_accuracy/evidence/pr1938_market_board_parity.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCORER = "src/nfl_data/realized_points.py"

# Run in a child interpreter: argv = repo, export path, out path, [scorer file].
_CHILD = r"""
import importlib.util, json, sys
repo, export, out = sys.argv[1], sys.argv[2], sys.argv[3]
sys.path.insert(0, repo)
if len(sys.argv) > 4:
    import src, src.nfl_data  # noqa: F401 -- the packages, so the submodule can be replaced
    spec = importlib.util.spec_from_file_location("src.nfl_data.realized_points", sys.argv[4])
    mod = importlib.util.module_from_spec(spec)
    sys.modules["src.nfl_data.realized_points"] = mod
    spec.loader.exec_module(mod)
from src.api.data_contract import build_api_data_contract
import src.nfl_data.realized_points as rp
with open(export, encoding="utf-8") as fh:
    raw = json.load(fh)
contract = build_api_data_contract(raw)
rows = {
    str(r.get("displayName")): [
        r.get("rankDerivedValue"), r.get("canonicalConsensusRank"), r.get("confidenceBucket")
    ]
    for r in contract.get("playersArray") or []
}
with open(out, "w", encoding="utf-8") as fh:
    json.dump({"scorerFile": rp.__file__, "rows": rows}, fh)
"""


def _sha(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True).encode()).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--base-ref", default="origin/main")
    ap.add_argument("--export", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    export = args.export.resolve()
    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        base_file = tmpdir / "current_realized_points.py"
        base_src = subprocess.run(
            ["git", "show", f"{args.base_ref}:{SCORER}"],
            cwd=REPO,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        base_file.write_text(base_src, encoding="utf-8")
        child = tmpdir / "child.py"
        child.write_text(_CHILD, encoding="utf-8")
        arms = {}
        for tag, extra in (("current", [str(base_file)]), ("corrected", [])):
            out = tmpdir / f"{tag}.json"
            subprocess.run(
                [sys.executable, str(child), str(REPO), str(export), str(out), *extra],
                check=True,
            )
            arms[tag] = json.loads(out.read_text(encoding="utf-8"))
    cur, cor = arms["current"]["rows"], arms["corrected"]["rows"]
    differing = sorted(k for k in set(cur) | set(cor) if cur.get(k) != cor.get(k))
    result = {
        "baseRef": args.base_ref,
        "export": str(export.relative_to(REPO)) if export.is_relative_to(REPO) else str(export),
        "exportSha256": hashlib.sha256(export.read_bytes()).hexdigest(),
        "currentScorerSha256": hashlib.sha256(base_src.encode("utf-8")).hexdigest(),
        "correctedScorerSha256": hashlib.sha256((REPO / SCORER).read_bytes()).hexdigest(),
        "currentArmLoaded": Path(arms["current"]["scorerFile"]).name,
        "correctedArmLoaded": Path(arms["corrected"]["scorerFile"]).name,
        "fields": ["rankDerivedValue", "canonicalConsensusRank", "confidenceBucket"],
        "rowsCurrent": len(cur),
        "rowsCorrected": len(cor),
        "tableSha256Current": _sha(cur),
        "tableSha256Corrected": _sha(cor),
        "rowsDiffering": len(differing),
        "differing": [
            {"row": k, "current": cur.get(k), "corrected": cor.get(k)} for k in differing
        ],
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")
    print(
        f"rows {len(cur)} / {len(cor)}; differing {len(differing)}; "
        f"current {result['tableSha256Current'][:16]} corrected {result['tableSha256Corrected'][:16]}"
    )
    return 0 if not differing else 1


if __name__ == "__main__":
    raise SystemExit(main())
