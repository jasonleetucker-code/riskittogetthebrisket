#!/usr/bin/env python3
"""Is a candidate projection source usable, and is it independent?

Reproduces the measurements in
``docs/projections/PROJECTION_SOURCE_ASSESSMENT.md``.

Two questions, deliberately separate, because a source can fail either
one on its own:

* **basis** — can the numbers be scored under THIS league's card?  A
  source publishing points TOTALS rather than stat lines cannot be
  rescored, and one publishing no scoring metadata cannot even be
  checked.  Unverified fails closed.
* **independence** — does the source already vote in this platform?
  Signal independence (CLAUDE.md §3.3) says a body of evidence affects a
  conclusion once, so a provider's projection sitting beside that same
  provider's rank manufactures agreement out of one opinion.

The comparison against realized totals is reported but deliberately NOT
treated as identifying the basis: a forward projection is systematically
less extreme than a realized season, so regression to the mean is
confounded with any scoring difference.

Exit codes: 0 measured, 2 inputs unavailable.
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
from pathlib import Path
from typing import Any, Sequence

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

CARD_FIXTURE = REPO / "tests/nfl_data/fixtures/live_scoring_cards_2026-07-28.json"


def _spearman(pairs: Sequence[tuple[float, float]]) -> float:
    """Rank correlation with ties averaged.  Hand-rolled to keep this
    script dependency-free — scipy is not a runtime dependency here."""
    if len(pairs) < 3:
        return float("nan")

    def ranks(values: Sequence[float]) -> list[float]:
        order = sorted(range(len(values)), key=lambda i: values[i])
        out = [0.0] * len(values)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
                j += 1
            avg = (i + j) / 2.0 + 1
            for k in range(i, j + 1):
                out[order[k]] = avg
            i = j + 1
        return out

    rx = ranks([p[0] for p in pairs])
    ry = ranks([p[1] for p in pairs])
    mx, my = statistics.mean(rx), statistics.mean(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = (sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry)) ** 0.5
    return num / den if den else float("nan")


def _num(row: dict[str, Any], col: str) -> float | None:
    try:
        return float((row.get(col) or "").replace(",", ""))
    except (AttributeError, ValueError):
        return None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source-csv", default="CSVs/site_raw/draftSharksSf.csv")
    ap.add_argument("--projection-column", default="1yr. Proj")
    ap.add_argument("--rank-column", default="Rank")
    ap.add_argument("--name-column", default="Player")
    ap.add_argument("--position-column", default="Fantasy Position")
    ap.add_argument(
        "--peer-board",
        default="CSVs/site_raw/draftSharksRosSf.csv",
        help="another board from the SAME provider, to test independence",
    )
    ap.add_argument("--weekly-csv", help="nflverse weekly CSV, for the basis comparison")
    ap.add_argument("--league-key", default="dynasty_main")
    args = ap.parse_args(argv)

    from src.utils.name_clean import normalize_player_name as clean

    src = Path(args.source_csv)
    if not src.exists():
        print(f"source not found: {src}", file=sys.stderr)
        return 2

    rows = list(csv.DictReader(src.open()))
    entries: dict[str, tuple[float, float, str]] = {}
    for r in rows:
        name = clean(r.get(args.name_column) or "")
        proj = _num(r, args.projection_column)
        rank = _num(r, args.rank_column)
        pos = (r.get(args.position_column) or "").split("/")[0].strip().upper()
        if name and proj and proj > 0 and rank and rank > 0:
            entries[name] = (rank, proj, pos)

    print(f"source={src.name}  rows={len(rows)}  usable={len(entries)}")
    if not entries:
        print("no usable rows", file=sys.stderr)
        return 2

    print(
        "\n-- independence: is the projection a different opinion from the provider's own rank? --"
    )
    pairs = [(v[0], -v[1]) for v in entries.values()]
    print(f"   own rank vs projection      n={len(pairs):>4}  rho = {_spearman(pairs):+.3f}")
    by_pos: dict[str, list[tuple[float, float]]] = {}
    for v in entries.values():
        by_pos.setdefault(v[2], []).append((v[0], -v[1]))
    for pos, pp in sorted(by_pos.items()):
        if len(pp) >= 9:
            print(f"     {pos:<4}                     n={len(pp):>4}  rho = {_spearman(pp):+.3f}")

    peer = Path(args.peer_board)
    if peer.exists():
        peer_rank: dict[str, float] = {}
        for r in csv.DictReader(peer.open()):
            nm = clean(r.get("sourceName") or r.get("canonicalName") or "")
            rk = _num(r, "rank")
            if nm and rk and rk > 0:
                peer_rank[nm] = rk
        common = [n for n in entries if n in peer_rank]
        if len(common) >= 3:
            print(
                f"   peer board vs projection    n={len(common):>4}  "
                f"rho = {_spearman([(peer_rank[n], -entries[n][1]) for n in common]):+.3f}"
            )
            print(
                f"   peer board vs own rank      n={len(common):>4}  "
                f"rho = {_spearman([(peer_rank[n], entries[n][0]) for n in common]):+.3f}"
            )

    if args.weekly_csv:
        print("\n-- basis: scale against OUR league-scored realized totals --")
        print("   NOTE: a forward projection is systematically less extreme than a")
        print("   realized season, so this CANNOT separate 'different card' from")
        print("   'projection shrinkage'.  Reported, not treated as identifying.")
        from src.nfl_data import realized_points as rp

        card = json.loads(CARD_FIXTURE.read_text())[args.league_key]
        card = card.get("scoring_settings", card)
        realized: dict[str, float] = {}
        with Path(args.weekly_csv).open(newline="") as fh:
            for r in csv.DictReader(fh):
                if str(r.get("season_type") or "REG").upper() != "REG":
                    continue
                nm = clean(r.get("player_display_name") or "")
                if not nm:
                    continue
                realized[nm] = realized.get(nm, 0.0) + float(
                    rp.compute_weekly_points(r, card).fantasy_points
                )
        matched = [
            (n, entries[n][1], realized[n], entries[n][2])
            for n in entries
            if n in realized and realized[n] > 50
        ]
        print(f"   matched (realized > 50 pts): {len(matched)}")
        ratios_by_pos: dict[str, list[float]] = {}
        for _n, proj, real, pos in matched:
            ratios_by_pos.setdefault(pos, []).append(proj / real)
        for pos, rs in sorted(ratios_by_pos.items()):
            print(f"     {pos:<4} n={len(rs):>4}  median source/ours = {statistics.median(rs):.3f}")
        allr = [p / r for _n, p, r, _pos in matched]
        if allr:
            print(f"   overall median ratio: {statistics.median(allr):.3f}   (1.00 = same basis)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
