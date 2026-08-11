#!/usr/bin/env python3
"""B2 — measure what the curve-routing repair does to the served board.

Two modes:

  ``--dump OUT.json``     build the board from the pinned raw export and
                          write a compact per-row record.  Run once in a
                          worktree at the B2 baseline and once on the
                          repaired tree — the script is copied into the
                          baseline worktree so both sides run the SAME
                          measurement code against DIFFERENT pipeline
                          code.

  ``--compare BEFORE AFTER``  diff the two dumps and print the impact
                          tables the B2 authorization asks for.

Deliberately reads one pinned raw payload (``--board``, default the B2
baseline export) so the only thing that differs between the two dumps is
the pipeline.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

DEFAULT_BOARD = ROOT / "exports" / "latest" / "dynasty_data_2026-08-11.json"

IDP_POSITIONS = {"DL", "EDGE", "LB", "DB", "CB", "S", "DE", "DT", "IDP"}
POSITION_BUCKETS = (
    ("offense", {"QB", "RB", "WR", "TE", "K"}),
    ("dl_edge", {"DL", "EDGE", "DE", "DT"}),
    ("lb", {"LB"}),
    ("db", {"DB", "CB", "S"}),
)


def bucket_for(position: str, asset_class: str) -> str:
    if asset_class == "pick":
        return "picks"
    pos = (position or "").upper()
    for name, members in POSITION_BUCKETS:
        if pos in members:
            return name
    return "other"


def dump(board_path: Path, out_path: Path) -> None:
    from src.api.data_contract import build_api_data_contract

    raw_bytes = board_path.read_bytes()
    raw = json.loads(raw_bytes)
    with contextlib.redirect_stdout(io.StringIO()):
        contract = build_api_data_contract(raw)

    rows = []
    for row in contract.get("playersArray") or []:
        meta = row.get("sourceRankMeta") or {}
        rows.append(
            {
                "name": row.get("displayName"),
                "position": row.get("position"),
                "assetClass": row.get("assetClass"),
                "value": row.get("rankDerivedValue"),
                "rank": row.get("canonicalConsensusRank"),
                "droppedSources": list(row.get("droppedSources") or []),
                "clamp": row.get("marketCorridorClamp"),
                "sources": {
                    key: {
                        "effectiveRank": m.get("effectiveRank"),
                        "value": m.get("valueContribution"),
                        "path": m.get("valueContributionPath"),
                        "method": m.get("method"),
                        "pool": m.get("rankCoordinatePool"),
                    }
                    for key, m in meta.items()
                    if isinstance(m, dict)
                },
            }
        )
    out = {
        "boardPath": str(board_path.relative_to(ROOT)),
        "boardSha256": hashlib.sha256(raw_bytes).hexdigest()[:16],
        "rowCount": len(rows),
        "rows": rows,
    }
    out_path.write_text(json.dumps(out, indent=1))
    print(f"wrote {out_path} — {len(rows)} rows from {out['boardPath']} ({out['boardSha256']})")


def _pct(part: int, whole: int) -> str:
    return f"{100.0 * part / whole:.1f}%" if whole else "n/a"


def _stats(values: list[float]) -> str:
    if not values:
        return "n=0"
    s = sorted(values)
    p90 = s[min(len(s) - 1, int(round(0.90 * (len(s) - 1))))]
    return (
        f"n={len(s)} mean={statistics.fmean(s):.2f} median={statistics.median(s):.2f} "
        f"p90={p90:.2f} max={s[-1]:.2f}"
    )


def compare(before_path: Path, after_path: Path) -> None:
    before = json.loads(before_path.read_text())
    after = json.loads(after_path.read_text())

    print("== inputs ==")
    for label, blob in (("before", before), ("after", after)):
        print(
            f"  {label}: {blob['rowCount']} rows from {blob['boardPath']} "
            f"sha256_16={blob['boardSha256']}"
        )
    if before["boardSha256"] != after["boardSha256"]:
        print("  !! different raw payloads — the comparison is not attributable")

    b_rows = {r["name"]: r for r in before["rows"]}
    a_rows = {r["name"]: r for r in after["rows"]}
    common = sorted(set(b_rows) & set(a_rows))

    print("\n== membership ==")
    print(f"  before priced: {sum(1 for r in before['rows'] if r['value'] is not None)}")
    print(f"  after  priced: {sum(1 for r in after['rows'] if r['value'] is not None)}")
    print(f"  only in before: {sorted(set(b_rows) - set(a_rows))[:10]}")
    print(f"  only in after:  {sorted(set(a_rows) - set(b_rows))[:10]}")
    # Equal priced COUNTS are not equal priced SETS.  The served board keeps
    # a fixed top-``OVERALL_RANK_LIMIT`` window, so a repriced row does not
    # merely move — it can evict another row from the board entirely.
    # Reporting only the totals renders that as "no change".
    lost = [n for n in common if b_rows[n]["value"] is not None and a_rows[n]["value"] is None]
    gained = [n for n in common if b_rows[n]["value"] is None and a_rows[n]["value"] is not None]
    print(f"  priced before but NOT after: {len(lost)}")
    for n in sorted(lost, key=lambda n: -(b_rows[n]["value"] or 0)):
        print(
            f"    {n:<26} {b_rows[n]['position']:<5} was {b_rows[n]['value']:>5} @ #{b_rows[n]['rank']}"
        )
    print(f"  priced after but NOT before: {len(gained)}")
    for n in sorted(gained, key=lambda n: -(a_rows[n]["value"] or 0)):
        print(
            f"    {n:<26} {a_rows[n]['position']:<5} now {a_rows[n]['value']:>5} @ #{a_rows[n]['rank']}"
        )

    # ── per-source contribution changes ──
    print("\n== per-source contribution changes (the direct effect) ==")
    per_source: dict[str, list[float]] = {}
    per_source_pool: dict[str, set[str]] = {}
    for name in common:
        for key, b_meta in (b_rows[name]["sources"] or {}).items():
            a_meta = (a_rows[name]["sources"] or {}).get(key)
            if not a_meta:
                continue
            bv, av = b_meta.get("value"), a_meta.get("value")
            if bv is None or av is None:
                continue
            if bv != av:
                per_source.setdefault(key, []).append(100.0 * (av - bv) / bv if bv else 0.0)
            per_source_pool.setdefault(key, set()).add(str(a_meta.get("pool")))
    if not per_source:
        print("  no per-source contribution changed")
    for key in sorted(per_source, key=lambda k: -len(per_source[k])):
        deltas = per_source[key]
        print(
            f"  {key:<20} rows_changed={len(deltas):<5} "
            f"median={statistics.median(deltas):+.1f}% "
            f"mean={statistics.fmean(deltas):+.1f}% "
            f"min={min(deltas):+.1f}% max={max(deltas):+.1f}% "
            f"pool={sorted(per_source_pool.get(key, set()))}"
        )

    # ── board value changes ──
    print("\n== board value changes (rankDerivedValue) ==")
    changed: list[tuple[str, str, float, float, float]] = []
    unchanged = 0
    for name in common:
        bv, av = b_rows[name]["value"], a_rows[name]["value"]
        if bv is None or av is None:
            continue
        if bv == av:
            unchanged += 1
            continue
        pct = 100.0 * (av - bv) / bv if bv else 0.0
        changed.append(
            (name, bucket_for(b_rows[name]["position"], b_rows[name]["assetClass"]), bv, av, pct)
        )
    total = unchanged + len(changed)
    print(f"  rows compared: {total}   unchanged: {unchanged}   changed: {len(changed)}")
    if changed:
        abs_pcts = [abs(c[4]) for c in changed]
        print(f"  |Δ%| over changed rows: {_stats(abs_pcts)}")
        for threshold in (5, 10, 25, 50):
            n = sum(1 for p in abs_pcts if p > threshold)
            print(f"    |Δ| > {threshold:>2}% : {n:>4} rows ({_pct(n, total)} of compared)")

        print("\n  by bucket:")
        for bucket in ("offense", "dl_edge", "lb", "db", "picks", "other"):
            rows_in = [c for c in changed if c[1] == bucket]
            pop = sum(
                1
                for n in common
                if bucket_for(b_rows[n]["position"], b_rows[n]["assetClass"]) == bucket
            )
            if not pop:
                continue
            if rows_in:
                pcts = [c[4] for c in rows_in]
                print(
                    f"    {bucket:<9} changed {len(rows_in):>4}/{pop:<4} "
                    f"median={statistics.median(pcts):+.1f}% "
                    f"mean={statistics.fmean(pcts):+.1f}% "
                    f"min={min(pcts):+.1f}% max={max(pcts):+.1f}%"
                )
            else:
                print(f"    {bucket:<9} changed    0/{pop:<4}")

        print("\n  largest 12 absolute moves:")
        for name, bucket, bv, av, pct in sorted(changed, key=lambda c: -abs(c[3] - c[2]))[:12]:
            print(f"    {name:<28} {bucket:<8} {bv:>5} → {av:>5}  ({pct:+.1f}%)")

    # ── rank changes ──
    print("\n== rank changes (canonicalConsensusRank) ==")
    moves: list[tuple[str, str, int, int]] = []
    same = 0
    for name in common:
        br, ar = b_rows[name]["rank"], a_rows[name]["rank"]
        if br is None or ar is None:
            continue
        if br == ar:
            same += 1
        else:
            moves.append(
                (name, bucket_for(b_rows[name]["position"], b_rows[name]["assetClass"]), br, ar)
            )
    print(f"  ranked both sides: {same + len(moves)}   unchanged: {same}   moved: {len(moves)}")
    if moves:
        deltas = [abs(m[3] - m[2]) for m in moves]
        print(f"  |Δrank| over moved rows: {_stats([float(d) for d in deltas])}")
        print("  largest 12 rank moves:")
        for name, bucket, br, ar in sorted(moves, key=lambda m: -abs(m[3] - m[2]))[:12]:
            print(f"    {name:<28} {bucket:<8} #{br:>4} → #{ar:>4}  ({ar - br:+d})")

    # ── offense vs IDP balance ──
    print("\n== offense / IDP balance in the top 100 ==")
    for label, blob in (("before", before), ("after", after)):
        ranked = [r for r in blob["rows"] if r["rank"] is not None]
        top = sorted(ranked, key=lambda r: r["rank"])[:100]
        idp = sum(1 for r in top if (r["position"] or "").upper() in IDP_POSITIONS)
        picks = sum(1 for r in top if r["assetClass"] == "pick")
        print(
            f"  {label}: IDP {idp:>3}/100   picks {picks:>3}/100   offense {100 - idp - picks:>3}/100"
        )

    print("\n== IDP value at representative board ranks ==")
    print(f"  {'rank':>6}  {'before':>28}  {'after':>28}")
    for target in (1, 5, 10, 25, 50, 100, 150, 200, 300):
        cells = []
        for blob in (before, after):
            idp_ranked = sorted(
                (
                    r
                    for r in blob["rows"]
                    if r["rank"] is not None and (r["position"] or "").upper() in IDP_POSITIONS
                ),
                key=lambda r: r["rank"],
            )
            if target <= len(idp_ranked):
                row = idp_ranked[target - 1]
                cells.append(f"{row['name'][:20]:<20} {row['value']:>6}")
            else:
                cells.append(f"{'—':<20} {'—':>6}")
        print(f"  IDP#{target:<3}  {cells[0]:>28}  {cells[1]:>28}")

    remeasure_f002(before, after)
    remeasure_f003(before, after)


def remeasure_f002(before: dict, after: dict) -> None:
    """W02-F002 — Hampel ejection of the designated IDP market anchor.

    Eligibility mirrors the finding's own reproduction: IDP rows carrying an
    ``idpTradeCalc`` stamp and at least four stamped sources.
    """
    print("\n== W02-F002 remeasure: Hampel ejects idpTradeCalc on IDP rows ==")
    for label, blob in (("before", before), ("after", after)):
        idp = [r for r in blob["rows"] if r["assetClass"] == "idp" and (r["sources"] or {})]
        eligible = [r for r in idp if "idpTradeCalc" in r["sources"] and len(r["sources"]) >= 4]
        ejected = [r for r in eligible if "idpTradeCalc" in (r["droppedSources"] or [])]
        high = 0
        for r in ejected:
            anchor = (r["sources"].get("idpTradeCalc") or {}).get("value")
            peers = [
                m["value"]
                for k, m in r["sources"].items()
                if k != "idpTradeCalc" and m.get("value") is not None
            ]
            if anchor is not None and peers and anchor > statistics.median(peers):
                high += 1
        print(
            f"  {label}: ejected {len(ejected)}/{len(eligible)} eligible "
            f"({_pct(len(ejected), len(eligible))})   HIGH {high}/{len(ejected)}   "
            f"IDP rows with any dropped source: {sum(1 for r in idp if r['droppedSources'])}"
        )


def remeasure_f003(before: dict, after: dict) -> None:
    """W02-F003 — corridor clamp: is the per-bucket P90 machinery still inert?"""
    print("\n== W02-F003 remeasure: market corridor clamp ==")
    for label, blob in (("before", before), ("after", after)):
        clamped = [r for r in blob["rows"] if r.get("clamp")]
        eligible = [r for r in blob["rows"] if r["assetClass"] == "idp" and r["rank"] is not None]
        capped = sum(1 for r in clamped if (r["clamp"] or {}).get("cappedByMaxBand"))
        at_band = 0
        up = down = 0
        for r in clamped:
            c = r["clamp"] or {}
            anchor, direction = c.get("marketAnchor"), c.get("direction")
            if direction == "down":
                down += 1
            elif direction == "up":
                up += 1
            # Against ``clampedValue``, NOT ``rankDerivedValue`` — later
            # passes (two-way boost, pick tether) can move the served value
            # after the clamp, and comparing to those would understate how
            # often the clamp itself lands on the band edge.
            if anchor is None or c.get("clampedValue") is None:
                continue
            # ``direction`` names which way the value MOVED, so "up" lands on
            # the LOWER band edge.  Same convention as the finding's own
            # reproduction snippet: ``anchor * (1.15 if down else 0.85)``.
            edge = anchor * (1.0 + c.get("bandPct", 0.0) * (1 if direction == "down" else -1))
            if abs(round(edge) - c["clampedValue"]) <= 1:
                at_band += 1
        bands = sorted({(r["clamp"] or {}).get("bandPct") for r in clamped})
        print(
            f"  {label}: clamped {len(clamped)} rows "
            f"({_pct(len(clamped), len(eligible))} of {len(eligible)} ranked IDP rows)   "
            f"cappedByMaxBand {capped}/{len(clamped)} ({_pct(capped, len(clamped))})   "
            f"on the band edge {at_band}/{len(clamped)} "
            f"({_pct(at_band, len(clamped))})   up {up} / down {down}   "
            f"distinct bandPct {bands}"
        )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--board", type=Path, default=DEFAULT_BOARD)
    ap.add_argument("--dump", type=Path)
    ap.add_argument("--compare", nargs=2, type=Path, metavar=("BEFORE", "AFTER"))
    args = ap.parse_args()

    if args.dump:
        dump(args.board, args.dump)
        return 0
    if args.compare:
        compare(args.compare[0], args.compare[1])
        return 0
    ap.error("pass --dump or --compare")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
