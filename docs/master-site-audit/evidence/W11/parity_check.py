"""W11 evidence — diff the JS FAAB hint grid against the Python implementation.

Run from the repo root::

    node docs/master-site-audit/evidence/W11/parity_grid.js \
      | .venv/bin/python docs/master-site-audit/evidence/W11/parity_check.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from src.trade.waiver import _compute_faab_bid  # noqa: E402


def main() -> None:
    grid = json.load(sys.stdin)
    divergences = [
        (
            budget,
            value,
            (agg, reas, low),
            _compute_faab_bid(value, budget=budget, top_value_in_pool=top),
        )
        for budget, value, top, agg, reas, low in grid
        if _compute_faab_bid(value, budget=budget, top_value_in_pool=top) != (agg, reas, low)
    ]
    print(f"grid {len(grid)} divergences {len(divergences)}")
    for row in divergences[:10]:
        print(" ", row)


if __name__ == "__main__":
    main()
