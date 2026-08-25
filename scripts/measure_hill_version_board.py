#!/usr/bin/env python3
"""Capture the canonical board as a chosen Hill-master version would price it.

EVALUATION ONLY — this script promotes nothing, writes no config, and
never touches ``src/canonical/player_valuation.py``.  It exists so the
question "what would promoting this challenger do to the board?" can be
ANSWERED before anyone answers it with a promotion.

Why it is needed
----------------
``scripts/model_registry.py validate`` compares two scalars: the
challenger's held-out criterion against the champion's.  That number is
computed by ``src/model_registry/holdout.py``, which says plainly what it
does and does not mean — it measures generalization across value-publishing
markets, and it scores ONE of the four scope masters
(``hill_masters.VALIDATED_PARAMS`` is literally the OFFENSE pair).  A
promotion moves all eight constants.

So a better criterion tells you nothing about what the other six numbers
do to real player values, and there is no other instrument in the repo
that answers it.  This is that instrument: it runs the REAL contract build
through the REAL entry point with one version's params substituted, and
emits a ``scripts/golden_board.py`` capture, so the answer is a
``scripts/board_diff.py`` run rather than an opinion.

    python scripts/measure_hill_version_board.py 2 --out /tmp/v2.json
    python scripts/measure_hill_version_board.py 5 --out /tmp/v5.json
    python scripts/board_diff.py /tmp/v2.json /tmp/v5.json

How the substitution is done, and why it is safe
------------------------------------------------
The constants are patched as module ATTRIBUTES on
``src.canonical.player_valuation`` before any consumer imports them.  That
ordering is load-bearing and asserted, not assumed:
``src/canonical/rank_coordinates.py`` builds ``_CURVE_BY_POOL`` from them at
import time, so patching after that import would silently measure the
champion while claiming to measure the challenger — the exact class of
false result this script exists to prevent.  Nothing is written to disk
except the capture the caller names.

The capture pins its three inputs (the frozen export, the per-source CSVs
and the freshness stamps) the same way ``golden_board.py`` does, and
``board_diff.py`` refuses to compare captures whose inputs differ — so a
data refresh landing mid-run cannot be reported as a curve effect.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

REGISTRY = REPO / "config" / "model_registry" / "hill_scope_masters.json"


def params_for(version: str) -> dict[str, float]:
    blob = json.loads(REGISTRY.read_text())
    for entry in blob.get("versions") or ():
        if str(entry.get("version")) == str(version):
            return {str(k): float(v) for k, v in (entry.get("params") or {}).items()}
    raise SystemExit(f"no version {version!r} in {REGISTRY.relative_to(REPO)}")


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("version", help="Hill scope-master version to price the board with")
    ap.add_argument("--out", type=Path, required=True, help="where to write the capture")
    ap.add_argument("--input", type=Path, default=None, help="export to build from")
    args = ap.parse_args()

    params = params_for(args.version)
    if not params:
        raise SystemExit(f"version {args.version} records no params")

    import src.canonical.player_valuation as pv

    # See the module docstring: patching after a consumer has bound these
    # would measure the champion under the challenger's name.
    for late in ("src.canonical.rank_coordinates", "src.api.data_contract"):
        if late in sys.modules:
            raise SystemExit(f"{late} was imported before the patch; capture would be wrong")

    for name, value in params.items():
        if not hasattr(pv, name):
            raise SystemExit(f"{name!r} is not a player_valuation constant")
        print(f"  {name}: {getattr(pv, name)} -> {value}", file=sys.stderr)
        setattr(pv, name, float(value))

    from scripts.golden_board import DEFAULT_INPUT, capture

    cap = capture(args.input or DEFAULT_INPUT)
    cap["hillMasterVersion"] = str(args.version)
    cap["hillMasterParams"] = params
    args.out.write_text(json.dumps(cap, indent=2, sort_keys=True) + "\n")
    print(f"wrote {args.out}  totals={cap['totals']}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
