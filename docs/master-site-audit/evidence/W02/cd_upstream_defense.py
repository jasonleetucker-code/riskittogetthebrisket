#!/usr/bin/env python3
"""What does the pipeline ALREADY do before the corridor gets a turn?

Step 3 of the final corridor pass, and the most important remaining
methodological question: the old corridor catches some single-source and
correlated-source anomalies, so before removing it we must know whether
those classes are already handled upstream — and demonstrate it on the
executable path rather than assert it.

Anomalies are injected into the **source CSVs** and the whole pipeline is
rebuilt, so every upstream layer sees them exactly as it would in
production: value-range suppression, the shared-market crosswalk, the
Hampel per-player outlier filter, the count-aware blend, the
single-source haircut, and only then the corridor.

Reuses the leak-guarded isolated-root machinery from
``cd_historical_replay`` so an injected run cannot read current-tree
market data or reach the network.

Per player and anomaly it reports what each layer actually did:

* was the bad source DROPPED by Hampel (``droppedSources``)?
* what did the bad source contribute, if kept?
* what happened to the blended value versus the clean baseline?
* did the OLD corridor fire?
* would the HULL invariant fire?
"""

from __future__ import annotations

import argparse
import contextlib
import csv
import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
OUT = Path(__file__).resolve().parent

import importlib.util  # noqa: E402

_spec = importlib.util.spec_from_file_location("cd_replay", OUT / "cd_historical_replay.py")
R = importlib.util.module_from_spec(_spec)
sys.modules["cd_replay"] = R
_spec.loader.exec_module(R)


def _rank_col(rows: list[dict]) -> str | None:
    for c in ("rank", "value", "Value", "3D Value +", "boone_value"):
        if rows and c in rows[0]:
            return c
    return None


def perturb_csv(path: Path, players: set[str], factor: float) -> int:
    """Scale a source's own numbers for chosen players, in place.

    Rank-signal CSVs carry a rank (smaller = better), so an "inflated
    value" anomaly means DIVIDING the rank. Value-signal CSVs carry a
    value, so it means multiplying. Getting that backwards would inject
    the opposite anomaly and quietly invert the whole experiment.
    """
    if not path.is_file():
        return 0
    rows = list(csv.DictReader(path.open(newline="", encoding="utf-8-sig")))
    if not rows:
        return 0
    col = _rank_col(rows)
    if col is None:
        return 0
    is_rank = col == "rank"
    hit = 0
    for r in rows:
        nm = (r.get("name") or "").strip()
        if nm not in players:
            continue
        try:
            v = float(r[col])
        except (TypeError, ValueError):
            continue
        r[col] = f"{max(1.0, v / factor) if is_rank else v * factor:g}"
        hit += 1
    if hit:
        with path.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
    return hit


def build(dest: Path, entry: dict):
    import src.api.data_contract as dc

    raw = json.loads(R.board_at(entry["sha"])[1])
    rp = R.Replay(entry["sha"], entry["timestamp"], dest)
    saved_ctx, saved_snap = dc._resolve_league_context, dc._RANK_SNAPSHOT_PATH
    dc._resolve_league_context = lambda *a, **k: dict(R.PINNED_LEAGUE_CONTEXT)
    dc._RANK_SNAPSHOT_PATH = dest / "data" / "snapshots" / "ranks_last.json"
    try:
        with rp.guard(), contextlib.redirect_stdout(io.StringIO()):
            return dc.build_api_data_contract(raw, csv_root=dest)
    finally:
        dc._resolve_league_context, dc._RANK_SNAPSHOT_PATH = saved_ctx, saved_snap


def row_view(contract, names: set[str]) -> dict[str, dict]:
    out = {}
    for r in contract.get("playersArray") or []:
        nm = str(r.get("displayName"))
        if nm not in names:
            continue
        contribs = {
            k: float(m.get("valueContribution") or 0)
            for k, m in (r.get("sourceRankMeta") or {}).items()
            if isinstance(m, dict) and float(m.get("valueContribution") or 0) > 0
        }
        v = float(r.get("rankDerivedValue") or 0)
        hull_bad = (
            bool(contribs)
            and len(contribs) >= 2
            and (v > max(contribs.values()) or v < min(contribs.values()))
        )
        clamp = (
            r.get("marketCorridorClamp") if isinstance(r.get("marketCorridorClamp"), dict) else None
        )
        out[nm] = {
            "value": v,
            "contribs": contribs,
            "dropped": list(r.get("droppedSources") or []),
            "corridorFired": bool(clamp and clamp.get("applied")),
            "corridorOriginal": (clamp or {}).get("originalValue"),
            "hullViolated": hull_bad,
            "sourceCount": len(contribs),
        }
    return out


SCENARIOS = [
    ("one_source_x5", ["idpShow"], 5.0),
    ("one_source_x20", ["idpShow"], 20.0),
    ("anchor_source_x5", ["idpTradeCalc"], 5.0),
    ("correlated_3_sources_x5", ["idpShow", "dlfIdp", "fantasyProsIdp"], 5.0),
    ("correlated_4_sources_x5", ["idpShow", "dlfIdp", "fantasyProsIdp", "draftSharksIdp"], 5.0),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--tail903", action="store_true")
    args = ap.parse_args()
    if not args.run:
        ap.error("pass --run")

    import tempfile

    from src.canonical import tail_policy

    mat = json.loads((OUT / "cd_historical_matrix.json").read_text())
    entry = sorted(
        [r for r in mat["representativeDays"] if r["usable"] == "usable"],
        key=lambda r: r["day"],
    )[-1]
    print(f"== upstream-defense audit on {entry['day']} ({entry['sha'][:9]}) ==")

    prev = tail_policy.TAIL_SATURATION_RANK
    if args.tail903:
        tail_policy.TAIL_SATURATION_RANK = 903
        print("   TAIL_SATURATION_RANK=903 (experimental)")
    try:
        with tempfile.TemporaryDirectory(prefix="cd_up_") as td:
            dest = Path(td)
            R.materialise(entry, dest)
            base = build(dest, entry)

        # Pick well-covered IDP victims: 5+ sources so Hampel is armed.
        victims = []
        for r in base.get("playersArray") or []:
            if str(r.get("assetClass") or "") != "idp" or not r.get("canonicalConsensusRank"):
                continue
            n = len(
                [
                    1
                    for m in (r.get("sourceRankMeta") or {}).values()
                    if isinstance(m, dict) and float(m.get("valueContribution") or 0) > 0
                ]
            )
            if n >= 5:
                victims.append(str(r.get("displayName")))
            if len(victims) >= 6:
                break
        names = set(victims)
        print(f"   victims (>=5 sources): {victims}")

        clean = row_view(base, names)
        results = {"day": entry["day"], "victims": victims, "scenarios": {}}

        for label, srcs, factor in SCENARIOS:
            with tempfile.TemporaryDirectory(prefix="cd_up_") as td:
                dest = Path(td)
                R.materialise(entry, dest)
                touched = 0
                for s in srcs:
                    touched += perturb_csv(dest / "CSVs" / "site_raw" / f"{s}.csv", names, factor)
                bad = build(dest, entry)
            view = row_view(bad, names)

            caught = kept = 0
            moved = []
            corridor_fired = hull_fired = 0
            for nm in victims:
                c, b = clean.get(nm, {}), view.get(nm, {})
                if not c or not b:
                    continue
                dropped_bad = [s for s in srcs if s in (b.get("dropped") or [])]
                if dropped_bad:
                    caught += 1
                else:
                    kept += 1
                if c["value"]:
                    moved.append(abs(b["value"] - c["value"]) / c["value"])
                corridor_fired += 1 if b["corridorFired"] else 0
                hull_fired += 1 if b["hullViolated"] else 0
            moved.sort()
            rec = {
                "sourcesPerturbed": srcs,
                "factor": factor,
                "csvRowsTouched": touched,
                "hampelDropped": caught,
                "hampelKept": kept,
                "victims": len(victims),
                "medianBlendMovePct": round(100.0 * moved[len(moved) // 2], 2) if moved else None,
                "maxBlendMovePct": round(100.0 * moved[-1], 2) if moved else None,
                "oldCorridorFired": corridor_fired,
                "hullFired": hull_fired,
            }
            results["scenarios"][label] = rec
            print(
                f"\n-- {label}  ({', '.join(srcs)} x{factor}, {touched} csv rows) --\n"
                f"   Hampel dropped the bad source on {caught}/{len(victims)} victims"
                f"   (kept on {kept})\n"
                f"   blend moved: median {rec['medianBlendMovePct']}%  max {rec['maxBlendMovePct']}%\n"
                f"   old corridor fired on {corridor_fired}/{len(victims)};"
                f"   hull fired on {hull_fired}/{len(victims)}"
            )
    finally:
        tail_policy.TAIL_SATURATION_RANK = prev

    name = "cd_upstream_defense_tail903.json" if args.tail903 else "cd_upstream_defense.json"
    (OUT / name).write_text(json.dumps(results, indent=1, default=str))
    print(f"\nwrote {OUT / name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
