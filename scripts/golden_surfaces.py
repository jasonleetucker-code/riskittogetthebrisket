#!/usr/bin/env python3
"""Capture the decision surfaces the board harness cannot see.

WHY THIS EXISTS
---------------
``scripts/golden_board.py`` captures the ``/api/data`` contract — every
value, rank, tier and confidence bucket.  That is the right baseline
for the value pipeline, and it is blind to most of what the 2026-08-04
audit found.  The trade verdict, the FAAB bid, the ROS buy/sell ladder
and news polarity are all decisions made *outside* the contract: they
consume it, or bypass it entirely.  A change to any of them moves what
the user is told while every board number stays byte-identical, so the
board diff prints "no change" and the regression ships.

The remediation plan requires each batch to state a MEASURED effect.
For batches C3, C5, C9 and C11 that is only possible if these surfaces
are captured too.

SHAPE
-----
Emits the same ``{"rows": {key: {...}}}`` shape as the board capture,
so ``scripts/board_diff.py`` diffs it with no second differ:

    python scripts/golden_surfaces.py --out /tmp/surfaces_after.json
    python scripts/board_diff.py tests/fixtures/golden/surfaces.json \
        /tmp/surfaces_after.json --surfaces

JS surfaces live in the sibling ``golden_surfaces.mjs`` (node imports
``frontend/lib/*`` directly) and are merged in here so one command
captures everything.

PURITY IS THE WHOLE CONTRACT
----------------------------
Every surface must be a pure call over a FIXED input grid — no clock,
no network, no filesystem, no live contract.  A surface that reads
``datetime.now()`` differs from itself between captures and turns the
diff into noise, which is worse than not measuring at all.

Surfaces are added by the batch that needs them.  Inventing a fixture
for a module nobody is editing yet bakes in a guess about the shape of
its fix.

Exit codes: 0 success, 1 nothing captured, 2 error.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

JS_HARNESS = Path(__file__).resolve().parent / "golden_surfaces.mjs"


def _num(v):
    if isinstance(v, bool) or v is None:
        return v
    if isinstance(v, float):
        return round(v, 6)
    return v


# ── ROS buy/sell ladder ───────────────────────────────────────────────
# Enumerated rather than sampled.  The defect (R-2) is that the ladder
# LEAVES GAPS — bands that fall through to the catch-all — and a gap is
# invisible to spot checks by construction: every probe you think to
# write lands on a band you were already thinking about.  Walking the
# whole grid is what makes "every team from 60-100% playoff odds gets
# the same advice as one at 0%" fall out of a diff.
_ROS_PLAYOFF_STEPS = [round(i * 0.05, 2) for i in range(21)]
_ROS_CHAMP_STEPS = [0.0, 0.01, 0.02, 0.05, 0.10, 0.25, 0.50]


def _ros_direction_rows() -> dict[str, dict]:
    from src.ros.direction import classify_team

    rows: dict[str, dict] = {}
    for playoff in _ROS_PLAYOFF_STEPS:
        for champ in _ROS_CHAMP_STEPS:
            for age_heavy in (False, True):
                profile = {"vetCount": 5} if age_heavy else {"vetCount": 0}
                out = classify_team(
                    playoff_odds_pct=playoff,
                    championship_odds_pct=champ,
                    team_ros_strength_percentile=0.5,
                    roster_age_profile=profile,
                )
                key = f"ros_direction/p={playoff:.2f},c={champ:.2f},age={int(age_heavy)}"
                rows[key] = {
                    "value": playoff,
                    "label": out.get("label"),
                    "recommendation": (out.get("recommendation") or "")[:60],
                }
    return rows


# ── FAAB bid desk ─────────────────────────────────────────────────────
# The grid varies the two quantities W-2 says the bid should NOT be a
# pure function of (the candidate's value and the best asset on the
# wire) while holding budget fixed, plus a budget sweep.  The audit's
# reproduction — the same player worth $7 on a rich wire and $30 on a
# picked-over one — is the (2000, 9000) vs (2000, 2200) pair.
_FAAB_CASES = [
    (2000.0, 9000.0, 100),
    (2000.0, 2200.0, 100),
    (9000.0, 9000.0, 100),
    (500.0, 9000.0, 100),
    (2000.0, 9000.0, 12),
    (2000.0, 9000.0, 0),
    (5000.0, 5000.0, 50),
]


def _faab_rows() -> dict[str, dict]:
    from src.trade.waiver import _compute_faab_bid

    rows: dict[str, dict] = {}
    for value, pool_max, budget in _FAAB_CASES:
        agg, rea, low = _compute_faab_bid(value, budget=budget, top_value_in_pool=pool_max)
        key = f"faab_bid/v={value:.0f},pool={pool_max:.0f},budget={budget}"
        rows[key] = {
            "value": agg,
            "aggressive": agg,
            "reasonable": rea,
            "lowball": low,
            # A bid is only meaningful as a share of what the manager
            # actually holds; recording it makes W-2's "percentile with
            # a dollar sign" visible as a constant fraction.
            "label": f"{(agg / budget * 100):.0f}%" if budget else "no-budget",
        }
    return rows


# ── News polarity ─────────────────────────────────────────────────────
# E-2: every WATCH item is stamped positive, including "released" and
# "waived".  These headlines are the ones the audit names plus enough
# neighbours to show the rule is a keyword coin-flip rather than a
# reading of the sentence.
_HEADLINES = [
    "Star RB released by the Panthers",
    "Veteran WR waived after failed physical",
    "QB placed on injured reserve",
    "Rookie TE questionable for Sunday",
    "RB signs three-year extension",
    "WR traded to the Chiefs",
    "LB suspended six games",
    "QB named week 1 starter",
    "RB out for the season with a torn ACL",
    "Team signs veteran kicker",
]


def _news_polarity_rows() -> dict[str, dict]:
    from src.news.providers._rss import classify

    rows: dict[str, dict] = {}
    for headline in _HEADLINES:
        severity, kind, impact = classify(headline)
        rows[f"news_polarity/{headline[:44]}"] = {
            "value": None,
            "severity": severity,
            "kind": kind,
            "impact": impact,
            "label": f"{severity}/{impact}",
        }
    return rows


_SURFACES = {
    "ros_direction": _ros_direction_rows,
    "faab_bid": _faab_rows,
    "news_polarity": _news_polarity_rows,
}


def _js_rows() -> dict[str, dict]:
    """Capture the frontend surfaces by running the node harness."""
    proc = subprocess.run(
        ["node", str(JS_HARNESS)],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"node harness failed: {proc.stderr.strip()[:400]}")
    return json.loads(proc.stdout).get("rows") or {}


def capture() -> dict:
    rows: dict[str, dict] = {}
    captured: list[str] = []
    for name, fn in _SURFACES.items():
        produced = fn()
        rows.update({k: {kk: _num(vv) for kk, vv in v.items()} for k, v in produced.items()})
        captured.append(f"{name}({len(produced)})")

    js = _js_rows()
    rows.update(js)
    captured.append(f"js({len(js)})")

    return {
        "kind": "surfaces",
        # No scrapeTimestamp: these surfaces are pure functions over a
        # fixed grid, so unlike the board capture there is no input
        # snapshot for them to drift against.
        "surfaces": captured,
        "totals": {"rows": len(rows)},
        "rows": rows,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    try:
        snap = capture()
    except Exception as exc:  # noqa: BLE001 — the harness must report, not crash
        print(f"error: surface capture failed: {exc}", file=sys.stderr)
        return 2

    if not snap["rows"]:
        print("error: captured zero surface rows", file=sys.stderr)
        return 1

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(snap, indent=1, sort_keys=True), encoding="utf-8")
    print(
        f"captured {snap['totals']['rows']} surface rows [{', '.join(snap['surfaces'])}] -> {args.out}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
