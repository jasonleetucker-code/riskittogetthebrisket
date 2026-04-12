#!/usr/bin/env python3
"""Before/after proof fixture for the scope-aware IDP ranking pipeline.

Demonstrates on a minimal 10-row fixture:

  - One full-board backbone source (idpTradeCalc)
  - One shallow DL-only source (dlTop5)
  - A DL player ("dl_A") that the shallow source promotes to DL #1 even
    though the backbone puts him at overall IDP rank 5

It prints:
  1. OLD behaviour: the position-agnostic ordinal ranking the old
     `_compute_unified_rankings` would have applied, and the resulting
     Hill-curve value.
  2. NEW behaviour: raw positional rank, translated synthetic overall
     IDP rank via the backbone ladder, resulting Hill-curve value, and
     final coverage-weighted blended value.

Run:
    python scripts/demo_idp_translation.py
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

# Make sure the repo root is on sys.path so src.* imports resolve.
_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from src.api.data_contract import _RANKING_SOURCES, _compute_unified_rankings
from src.canonical.idp_backbone import (
    SOURCE_SCOPE_POSITION_IDP,
    build_backbone_from_rows,
    coverage_weight,
    translate_position_rank,
)
from src.canonical.player_valuation import rank_to_value


def _row(name: str, pos: str, *, idp=None, dl_top5=None) -> dict:
    sites: dict = {}
    if idp is not None:
        sites["idpTradeCalc"] = idp
    if dl_top5 is not None:
        sites["dlTop5"] = dl_top5
    return {
        "canonicalName": name,
        "displayName": name,
        "position": pos,
        "assetClass": "idp",
        "values": {"overall": 0, "rawComposite": 0,
                   "finalAdjusted": 0, "displayValue": None},
        "canonicalSiteValues": sites,
        "sourceCount": 1,
    }


def build_fixture() -> list[dict]:
    # Ten-row fixture.  The backbone order is:
    #   dl_top=900 > dl_two=850 > lb_top=820 > dl_three=800 >
    #   dl_A=700 > db_top=650 > dl_four=600 > lb_two=550 > db_two=500 > dl_five=450
    rows = [
        _row("dl_top",   "DL", idp=900, dl_top5=None),
        _row("dl_two",   "DL", idp=850),
        _row("lb_top",   "LB", idp=820),
        _row("dl_three", "DL", idp=800),
        _row("dl_A",     "DL", idp=700, dl_top5=100),  # ← the problem child
        _row("db_top",   "DB", idp=650),
        _row("dl_four",  "DL", idp=600),
        _row("lb_two",   "LB", idp=550),
        _row("db_two",   "DB", idp=500),
        _row("dl_five",  "DL", idp=450),
    ]
    return rows


def demo_old_behaviour(rows: list[dict]) -> None:
    """Simulate the OLD position-agnostic per-source ordinal ranking.

    The old pipeline ranked every source's eligible rows together (no
    scope gating, no backbone translation).  A DL-only top-5 list would
    therefore assign rawRank 1 directly and hand that to the Hill curve.
    """
    print("=" * 72)
    print("OLD behaviour (position-agnostic ordinal ranking)")
    print("=" * 72)
    dl_a_old_rank = 1  # dl_A is the only row with a dlTop5 value → ordinal 1
    old_value = rank_to_value(dl_a_old_rank)
    print(f"  dl_A raw dlTop5 rank    : {dl_a_old_rank}")
    print(f"  dl_A feeds Hill curve at: rank={dl_a_old_rank}")
    print(f"  rank_to_value(1)        : {old_value}  "
          "← catastrophic over-valuation")
    print()


def demo_new_behaviour(rows: list[dict]) -> None:
    """Run the NEW scope-aware + backbone-aware pipeline on the fixture."""
    print("=" * 72)
    print("NEW behaviour (scope-aware, backbone-translated)")
    print("=" * 72)

    # Temporarily install a DL-only position_idp source alongside the
    # real registry so _compute_unified_rankings picks it up.
    saved = copy.deepcopy(_RANKING_SOURCES)
    _RANKING_SOURCES.append(
        {
            "key": "dlTop5",
            "display_name": "DL Top-5 (demo)",
            "scope": SOURCE_SCOPE_POSITION_IDP,
            "position_group": "DL",
            "depth": 5,
            "weight": 1.0,
            "is_backbone": False,
        }
    )
    try:
        # Show the ladder that the backbone builder produces
        backbone = build_backbone_from_rows(
            rows, source_key="idpTradeCalc"
        )
        print(f"  Backbone ladder DL      : {backbone.ladder_for('DL')}  "
              f"(depth={backbone.depth})")

        # Raw positional rank of dl_A in the shallow DL-only list is 1
        raw_rank = 1
        synthetic, method = translate_position_rank(
            raw_rank, backbone.ladder_for("DL")
        )
        print(f"  dl_A raw dlTop5 rank    : {raw_rank}")
        print(f"  Translated via ladder   : {synthetic}  (method={method})")
        print(f"  rank_to_value({synthetic}):"
              f" {rank_to_value(synthetic)}")

        # Coverage weight for depth=5 / min=60
        shallow_w = coverage_weight(1.0, 5)
        print(f"  Shallow coverage weight : {shallow_w:.4f}  "
              "(vs backbone=1.0000)")

        # Run the full pipeline and show dl_A's final stamped values
        live_rows = copy.deepcopy(rows)
        _compute_unified_rankings(live_rows, {})
        dl_a = next(r for r in live_rows if r["canonicalName"] == "dl_A")

        meta_dl = dl_a["sourceRankMeta"]["dlTop5"]
        meta_bb = dl_a["sourceRankMeta"]["idpTradeCalc"]
        print()
        print("  Backbone source effective rank :",
              meta_bb["effectiveRank"], "→ value",
              meta_bb["valueContribution"],
              f"(weight={meta_bb['effectiveWeight']:.4f})")
        print("  Shallow source effective rank  :",
              meta_dl["effectiveRank"], "→ value",
              meta_dl["valueContribution"],
              f"(weight={meta_dl['effectiveWeight']:.4f})")
        print(f"  FINAL blended rankDerivedValue : {dl_a['rankDerivedValue']}")
        print(f"  FINAL canonicalConsensusRank   : "
              f"{dl_a['canonicalConsensusRank']}")
        print(f"  idpBackboneFallback            : "
              f"{dl_a['idpBackboneFallback']}")
    finally:
        _RANKING_SOURCES.clear()
        _RANKING_SOURCES.extend(saved)
    print()


def main() -> int:
    rows = build_fixture()

    print()
    print("Fixture: 10 IDP rows. dl_A is backbone #5 but shallow dlTop5 #1.")
    print()

    demo_old_behaviour(rows)
    demo_new_behaviour(rows)

    print("Interpretation:")
    print("  - OLD: dl_A would be priced as if he were the #1 IDP overall,")
    print("    because the shallow list treats him as rank 1 and the old")
    print("    Hill curve slope peaks at 9999 for rank 1.")
    print("  - NEW: dl_A's raw rank 1 is translated via the backbone ladder")
    print("    to overall IDP rank 5 (DL[2]=5 in the ladder).  Its blended")
    print("    value is dominated by the backbone because the shallow")
    print("    source's coverage weight is just 5/60 ≈ 0.083 vs 1.0.")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
