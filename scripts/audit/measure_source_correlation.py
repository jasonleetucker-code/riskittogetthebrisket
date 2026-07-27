"""Measure which ranking sources actually agree, and which merely share a name.

T4-1. The standing claim is that ``source_count >= 2`` inflates
confidence because one publisher ships several sources — DLF alone has
four registry entries — so a player on ``dlfSf + dlfRookieSf +
flockFantasySf + flockFantasySfRookies`` reaches "high" confidence off
two publishers.

``docs/collaborative-model-audit/CLAIM_REGISTRY.md`` deferred the fix
with the right instruction: *"clusters should be measured, not assumed
from publisher names."* This is that measurement.

WHAT IT MEASURES, AND WHY RAW CORRELATION IS THE WRONG STATISTIC
────────────────────────────────────────────────────────────────
Raw rank correlation between any two dynasty sources is ~0.95, because
every source agrees that the best player is better than the worst. That
shared market signal swamps the thing we care about, which is whether
two sources make the same MISTAKES.

So this converts each source to percentile rank, subtracts the
cross-source consensus percentile, and correlates the RESIDUALS. Two
sources that are genuinely one opinion will deviate from consensus
together; two independent ones will not.

MEASURED 2026-07-27, and it does not support the name-based fix
────────────────────────────────────────────────────────────────
Raw Spearman is useless as a discriminator, exactly as expected::

    same-publisher   median rho +0.951
    cross-publisher  median rho +0.952

On residuals a same-publisher effect appears in the median, but the
sample is four pairs and their spread is enormous::

    same-publisher   median +0.199  mean +0.086
      ktc / ktcSfTep                        +0.609
      dlfRookieSf / dlfSf                   +0.245
      flockFantasySf / flockFantasySfRookies +0.154
      fantasyProsFitzmaurice / fantasyProsSf -0.664   <-- ANTI-correlated

    cross-publisher  median -0.040  mean -0.025

Two conclusions, and the second is the useful one.

**The name-based fix would be wrong in at least one case.** FantasyPros'
two boards are strongly ANTI-correlated on residuals: Fitzmaurice is one
analyst deliberately departing from the consensus his own employer
publishes. Collapsing them into one "FantasyPros family" would discard
genuine independent signal — the opposite of the intent.

**The real non-independence is cross-publisher, and invisible to
names.** The strongest residual correlations in the entire matrix are
between different publishers::

    ktc / otcffbSf                    +0.891
    idpTradeCalc / ktcSfTep           +0.698
    dynastyNerdsSfTep / fpFitzmaurice +0.681
    idpShow / idpTradeCalc            +0.669

``ktc`` and ``otcffbSf`` deviate from consensus together more tightly
than any two boards from the same publisher. That is a real
independence problem and no amount of publisher-name clustering finds
it.

WHY THIS SHIPS AS A MEASUREMENT AND NOT AS A CONFIDENCE CHANGE
──────────────────────────────────────────────────────────────
Four same-publisher pairs is not enough to re-bucket a user-visible
field on every player, and the measured clusters that DO look real need
a second season of data before they are worth acting on. Shipping the
instrument, with its findings, is the honest increment. Re-run it when
the source registry changes.

Usage::

    python3 scripts/audit/measure_source_correlation.py
    python3 scripts/audit/measure_source_correlation.py --json
    python3 scripts/audit/measure_source_correlation.py --min-overlap 100
"""

from __future__ import annotations

import argparse
import csv
import itertools
import json
import statistics
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.utils.name_clean import resolve_canonical_name  # noqa: E402

DEFAULT_CSV_DIR = REPO_ROOT / "CSVs" / "site_raw"

#: Registry-key prefixes that belong to one publisher. Used ONLY to
#: label pairs for the same-vs-cross comparison — nothing in the
#: pipeline consumes this, precisely because the measurement above says
#: it is not a reliable proxy for shared opinion.
PUBLISHER_PREFIXES: dict[str, str] = {
    "dlf": "DLF",
    "fantasypros": "FantasyPros",
    "flock": "Flock",
    "draftsharks": "DraftSharks",
    "ktc": "KTC",
}

_NAME_COLUMNS = ("name", "player", "playername", "player_name")
_RANK_COLUMNS = ("rank", "effectiverank", "overallrank")
_VALUE_COLUMNS = ("value", "normalizedvalue", "trade_value")

MIN_SOURCE_ROWS = 40
MIN_PAIR_OVERLAP = 30


def publisher_of(source_key: str) -> str:
    lowered = source_key.lower()
    for prefix, publisher in PUBLISHER_PREFIXES.items():
        if lowered.startswith(prefix):
            return publisher
    return source_key


def load_source(path: Path) -> dict[str, float]:
    """``{canonical name: ordering key}``. Lower is better.

    Prefers an explicit rank column, falls back to negated value, then
    to file order. Ordering is all this needs — the residual step
    converts to percentile anyway, so the absolute scale never matters
    and sources on different scales stay comparable.
    """
    out: dict[str, float] = {}
    try:
        handle = path.open(newline="", encoding="utf-8", errors="replace")
    except OSError:
        return out
    with handle as f:
        reader = csv.DictReader(f)
        columns = reader.fieldnames or []
        lowered = {c.lower(): c for c in columns}
        name_col = next((lowered[c] for c in _NAME_COLUMNS if c in lowered), None)
        rank_col = next((lowered[c] for c in _RANK_COLUMNS if c in lowered), None)
        value_col = next((lowered[c] for c in _VALUE_COLUMNS if c in lowered), None)
        if not name_col:
            return out
        for index, row in enumerate(reader):
            name = resolve_canonical_name(row.get(name_col, ""))
            if not name:
                continue
            key: float | None = None
            if rank_col and row.get(rank_col):
                try:
                    key = float(row[rank_col])
                except ValueError:
                    key = None
            if key is None and value_col and row.get(value_col):
                try:
                    key = -float(row[value_col])
                except ValueError:
                    key = None
            out.setdefault(name, key if key is not None else float(index + 1))
    return out


def to_percentiles(ordering: dict[str, float]) -> dict[str, float]:
    ranked = sorted(ordering, key=lambda n: ordering[n])
    total = len(ranked)
    return {name: (i + 1) / total for i, name in enumerate(ranked)}


def pearson(a: dict[str, float], b: dict[str, float], min_overlap: int) -> tuple[float | None, int]:
    common = sorted(set(a) & set(b))
    if len(common) < min_overlap:
        return None, len(common)
    xs = [a[n] for n in common]
    ys = [b[n] for n in common]
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    den = (sum((x - mx) ** 2 for x in xs) * sum((y - my) ** 2 for y in ys)) ** 0.5
    return (num / den if den else None), len(common)


def measure(csv_dir: Path, min_overlap: int = MIN_PAIR_OVERLAP) -> dict[str, Any]:
    sources = {p.stem: load_source(p) for p in sorted(csv_dir.glob("*.csv"))}
    sources = {k: v for k, v in sources.items() if len(v) >= MIN_SOURCE_ROWS}
    if len(sources) < 2:
        return {"error": f"fewer than two usable sources in {csv_dir}"}

    percentiles = {k: to_percentiles(v) for k, v in sources.items()}
    every_name = set().union(*percentiles.values())
    consensus = {
        n: statistics.fmean([percentiles[k][n] for k in percentiles if n in percentiles[k]])
        for n in every_name
    }
    residuals = {
        k: {n: percentiles[k][n] - consensus[n] for n in percentiles[k]} for k in percentiles
    }

    pairs: list[dict[str, Any]] = []
    for x, y in itertools.combinations(sorted(residuals), 2):
        rho, overlap = pearson(residuals[x], residuals[y], min_overlap)
        if rho is None:
            continue
        pairs.append(
            {
                "a": x,
                "b": y,
                "residualCorrelation": round(rho, 4),
                "overlap": overlap,
                "samePublisher": publisher_of(x) == publisher_of(y),
            }
        )

    same = [p["residualCorrelation"] for p in pairs if p["samePublisher"]]
    cross = [p["residualCorrelation"] for p in pairs if not p["samePublisher"]]
    return {
        "sourceCount": len(sources),
        "pairCount": len(pairs),
        "samePublisher": {
            "n": len(same),
            "median": round(statistics.median(same), 4) if same else None,
            "mean": round(statistics.fmean(same), 4) if same else None,
        },
        "crossPublisher": {
            "n": len(cross),
            "median": round(statistics.median(cross), 4) if cross else None,
            "mean": round(statistics.fmean(cross), 4) if cross else None,
        },
        "pairs": sorted(pairs, key=lambda p: -p["residualCorrelation"]),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dir", default=str(DEFAULT_CSV_DIR))
    parser.add_argument("--min-overlap", type=int, default=MIN_PAIR_OVERLAP)
    parser.add_argument("--json", action="store_true", help="Emit the full result as JSON.")
    parser.add_argument("--top", type=int, default=10)
    args = parser.parse_args()

    result = measure(Path(args.dir), min_overlap=args.min_overlap)
    if "error" in result:
        print(f"[source-correlation] {result['error']}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, indent=2))
        return 0

    same, cross = result["samePublisher"], result["crossPublisher"]
    print(f"[source-correlation] {result['sourceCount']} sources, {result['pairCount']} pairs")
    print(f"  same-publisher  n={same['n']:<4} median={same['median']} mean={same['mean']}")
    print(f"  cross-publisher n={cross['n']:<4} median={cross['median']} mean={cross['mean']}")
    print("\n  same-publisher pairs:")
    for p in [q for q in result["pairs"] if q["samePublisher"]]:
        print(f"    {p['residualCorrelation']:+.3f}  {p['a']:<24} {p['b']:<24} n={p['overlap']}")
    print(f"\n  most-correlated pairs overall (top {args.top}):")
    for p in result["pairs"][: args.top]:
        tag = "same" if p["samePublisher"] else "CROSS"
        print(
            f"    {p['residualCorrelation']:+.3f}  {p['a']:<24} {p['b']:<24} "
            f"n={p['overlap']:<4} {tag}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
