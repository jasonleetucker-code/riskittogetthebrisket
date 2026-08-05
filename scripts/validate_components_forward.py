#!/usr/bin/env python3
"""Score every stored component against the outcome that was recorded later.

**The one measurement in this package that cannot be reconstructed
wrongly, because nothing is reconstructed.**  Every other study replays a
past board from committed inputs and has to defend that replay against
look-ahead.  This one reads rows the production board WROTE on the day,
against forward returns ``snapshot.label_outcomes`` filled in once the
horizon had actually elapsed.  Signal and outcome were recorded weeks
apart by two different code paths.  There is no window to leak through.

**Why this exists: Sharp Flow.**  Sharp Flow cannot be backtested at all,
and the reason is not the one the repo recorded for months.  The recorded
reason — ``src/sharp/`` recomputes the qualified cohort live per request
with no as-of concept — is true and is a blocker.  The terminal reason is
upstream of it: ``scripts/crawl_sharp_activity.py`` crawls only managers
who qualify *at crawl time*, so a manager qualified at a past date but
not now had their movements **never collected**.  The movement corpus is
survivorship-biased on a proxy for the outcome, and no as-of filter can
recover data that was never gathered.  A historical Sharp Flow number
would be plausible and wrong.

Forward-only measurement is the sound route, and it needed no new
collection — ``snapshot.write_board`` has been storing
``component_sharp_flow`` per player per day all along.  This script is
the arm that reads it.

It is not Sharp-Flow-specific: every stored component and the served
ranking key are measured on the same rows, so the components are
comparable to each other and to the thing users actually see.

Exit codes follow the repo's convention: 0 success, 1 soft failure (no
database, no labelled rows), 2 refusing to measure (a horizon nobody
stored).
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from src.consensus_edge import MODEL_VERSION  # noqa: E402
from src.consensus_edge import backtest as bt  # noqa: E402
from src.consensus_edge import snapshot as snap  # noqa: E402

OUT_DIR = REPO / "docs" / "measurements"

# Stored columns worth scoring, and what each one is.
SERIES: dict[str, str] = {
    "conviction": "the served ranking key (score x confidence/100)",
    "score": "the composite, before the confidence weighting",
    "component_mispricing": "Market Mispricing alone",
    "component_sharp_flow": "Sharp Flow alone",
    "component_opportunity": "Opportunity alone",
}

_EXCESS_COLUMN = {7: "fwd_excess_7d", 14: "fwd_excess_14d", 30: "fwd_excess_30d"}

# An origin with fewer than this many labelled pairs is not a
# cross-section, it is an anecdote. Matches the floor `evaluate_fold`
# applies in the panel studies so the two report comparable things.
_MIN_PAIRS = 20


def log(msg: str) -> None:
    print(f"[ce-forward] {msg}", flush=True)


def measure(
    column: str,
    *,
    horizon_days: int,
    path: Path | None = None,
) -> dict:
    """Per-origin Spearman of one stored column against stored outcome.

    Each origin date is its own cross-section. They are NOT pooled into
    one correlation: pooling would let a date with many rows dominate,
    and — worse — would mix cohorts whose excess returns are centred on
    different days, which is exactly the confound the cohort-excess
    definition exists to remove.

    Origins are reported unaggregated as well as summarised, because
    "one origin carried it" and "every origin agreed" are different
    findings that the mean alone cannot tell apart.
    """
    excess = _EXCESS_COLUMN[horizon_days]
    target = path or snap.DB_PATH
    conn = snap.connect(target)
    try:
        rows = conn.execute(
            f"SELECT as_of, {column}, {excess} FROM board_snapshots "  # noqa: S608
            f"WHERE {column} IS NOT NULL AND {excess} IS NOT NULL"
        ).fetchall()
    finally:
        conn.close()

    by_origin: dict[str, list[tuple[float, float]]] = {}
    for as_of, value, outcome in rows:
        by_origin.setdefault(str(as_of), []).append((float(value), float(outcome)))

    per_origin = []
    for as_of in sorted(by_origin):
        pairs = by_origin[as_of]
        if len(pairs) < _MIN_PAIRS:
            per_origin.append(
                {"origin": as_of, "n": len(pairs), "rho": None, "reason": "too few pairs"}
            )
            continue
        rho = bt.spearman([p[0] for p in pairs], [p[1] for p in pairs])
        per_origin.append({"origin": as_of, "n": len(pairs), "rho": rho})

    usable = [o for o in per_origin if o.get("rho") is not None]
    mean = sum(o["rho"] for o in usable) / len(usable) if usable else None
    positive = sum(1 for o in usable if o["rho"] > 0)
    return {
        "column": column,
        "describes": SERIES.get(column, ""),
        "labelledRows": len(rows),
        "origins": per_origin,
        "originsUsable": len(usable),
        "originsPositive": positive,
        "meanSpearman": mean,
        "verdict": _verdict(column, usable, mean, positive),
    }


def _verdict(column: str, usable: list, mean: float | None, positive: int) -> str:
    """Stated in the same shape as the panel studies' verdicts.

    The three-origin floor is the same one `backtest._verdict` applies
    and is not a rounding of "we would like more data": below it, the
    sign of the mean is determined by which way one cross-section
    happened to fall.
    """
    if not usable:
        return f"{column}: no origin has enough labelled rows to correlate"
    if len(usable) < 3:
        return (
            f"underpowered: {len(usable)} usable origin(s). A direction cannot be "
            f"called from this; mean rho {mean:+.3f} is reported for completeness only."
        )
    agreement = positive / len(usable)
    if mean is None:
        return "no correlation computable"
    if agreement >= 0.7 and mean > 0:
        return f"positive and consistent (mean rho {mean:+.3f} over {len(usable)} origins)"
    if agreement <= 0.3 and mean < 0:
        return f"negative and consistent (mean rho {mean:+.3f} over {len(usable)} origins)"
    return (
        f"no effect detected (mean rho {mean:+.3f} over {len(usable)} origins; "
        f"{positive}/{len(usable)} positive)"
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--horizon-days", type=int, default=14, choices=(7, 14, 30))
    ap.add_argument("--db", type=Path, default=None, help="snapshot database (default: prod path)")
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    if args.horizon_days not in _EXCESS_COLUMN:
        print(f"[ce-forward] unsupported horizon {args.horizon_days}", file=sys.stderr)
        return 2

    target = args.db or snap.DB_PATH
    if not target.exists():
        print(
            f"[ce-forward] no snapshot database at {target}. This measurement is "
            "forward-only by construction: it reads what the production board "
            "wrote on the day, so it exists only where the board has been "
            "running. Nothing to reconstruct.",
            file=sys.stderr,
        )
        return 1

    cov = snap.coverage(target)
    log(f"database {target}")
    log(f"coverage: {cov}")

    runs = {name: measure(name, horizon_days=args.horizon_days, path=target) for name in SERIES}
    labelled = max((r["labelledRows"] for r in runs.values()), default=0)
    if not labelled:
        print(
            "[ce-forward] no rows carry BOTH a component value and a labelled "
            f"{args.horizon_days}d outcome yet. Run "
            "`scripts/snapshot_consensus_edge.py --label` once the horizon has "
            "elapsed; until then there is nothing to correlate.",
            file=sys.stderr,
        )
        return 1

    for name, run in runs.items():
        log(f"  {name:24s} {run['verdict']}")

    summary = {
        "modelVersion": MODEL_VERSION,
        "measuredAt": datetime.now(timezone.utc).isoformat(),
        "horizonDays": args.horizon_days,
        "target": "cohort-excess market return, as recorded by label_outcomes",
        "database": str(target),
        "coverage": cov,
        "runs": runs,
        "caveats": [
            "Forward-only: the signal was written by the production board on the "
            "origin date and the outcome by a separate labelling pass after the "
            "horizon elapsed. Nothing here is reconstructed, so nothing here can "
            "leak — which is why this is the ONLY sound route for Sharp Flow.",
            "Sharp Flow rows exist only where the qualified-manager ledger is "
            "populated. An empty component column is 'no ledger', not 'no "
            "signal' — read labelledRows before reading meanSpearman.",
            "Origins are correlated separately and averaged, never pooled: "
            "pooling would let one busy date dominate and would mix cohorts "
            "centred on different days.",
            "Origins are NOT non-overlapping. Consecutive daily snapshots share "
            "most of their holding period, so the origin count is a count of "
            "cross-sections and not of independent observations. Read a "
            "consistent sign across origins as the finding, not the origin "
            "count as a sample size.",
            "The board is behind a feature flag defaulting OFF. These numbers "
            "describe the shadow board, which is the board that was scored.",
        ],
    }

    if args.dry_run:
        print(json.dumps(summary, indent=2, default=str))
        return 0

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = args.out or (
        OUT_DIR / f"consensus-edge-forward-{date.today().isoformat()}-h{args.horizon_days}.json"
    )
    out.write_text(json.dumps(summary, indent=2, default=str) + "\n", encoding="utf-8")
    log(f"wrote {out.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
