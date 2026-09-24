#!/usr/bin/env python3
"""Backtest: family-head selection vs family-capped voting.

For each day in the window, rebuilds the board from THAT day's own inputs —
the day's last export-archive payload, the source CSVs as committed at that
moment, and dataset state replayed from git history up to that moment — the
same replay ``scripts/backtest_source_freshness.py`` uses, whose helpers this
reuses.  Two variants, both with freshness weighting ON (production today):

* ``select`` — ``source_family_cap`` OFF: the registry-first member of each
               correlation family votes, the rest are superseded;
* ``cap``    — ``source_family_cap`` ON: every member votes with its own
               effective weight, the family total capped at one provider.

``cap`` vs ``select`` isolates the family change.  Reports per day: rows and
ranks moved (overall and by rank band), sources that newly vote, how many
rows cross a count-aware blend rung (1 / 2 / 3-4 / 5+ voters) because family
members now count as observations, and row weight states.

Writes ``<out>/summary.json``.  Usage:

    python scripts/backtest_family_cap.py --out DIR [--start D --end D]
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import tempfile
import zipfile
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.backtest_source_freshness import (  # noqa: E402
    archive_time,
    build_tree,
    compare,
    day_archives,
    replay_states,
    row_state_stats,
)
from src.api import data_contract as dc  # noqa: E402
from src.api import feature_flags  # noqa: E402
from src.sources.dataset_state import save_state, state_path  # noqa: E402

RANK_BANDS = ((1, 50), (51, 150), (151, 300), (301, 500), (501, 800))


def _voters(row: dict) -> list[str]:
    meta = row.get("sourceRankMeta") or {}
    return [
        k
        for k, m in meta.items()
        if isinstance(m, dict)
        and m.get("contributedToBlend") is not False
        and not m.get("hampelDropped")
        and (m.get("appliedWeight") or 0) > 0
    ]


def _rung(n: int) -> str:
    return "1" if n <= 1 else "2" if n == 2 else "3-4" if n <= 4 else "5+"


def _set_family_cap(on: bool) -> None:
    os.environ["RISKIT_FEATURE_SOURCE_FAMILY_CAP"] = "1" if on else "0"
    feature_flags.reload()


def build(raw: dict, root: Path) -> dict[str, dict]:
    contract = dc.build_api_data_contract(raw, csv_root=root)
    return {
        r["displayName"]: {
            "value": r.get("rankDerivedValue"),
            "rank": r.get("canonicalConsensusRank"),
            "assetClass": r.get("assetClass"),
            "position": r.get("position"),
            "state": r.get("sourceWeightState"),
            "retained": r.get("retainedAuthority"),
            "voters": _voters(r),
            "superseded": sorted(
                k
                for k, m in (r.get("sourceRankMeta") or {}).items()
                if (m or {}).get("supersededBy")
            ),
        }
        for r in contract["playersArray"]
    }


def by_band(select: dict, cap: dict) -> list[dict]:
    out = []
    for lo, hi in RANK_BANDS:
        pct, moves = [], []
        for name, a in select.items():
            b = cap.get(name)
            if not b or not a.get("rank") or not lo <= a["rank"] <= hi:
                continue
            if (a.get("value") or 0) > 0 and (b.get("value") or 0) > 0:
                pct.append(abs(b["value"] - a["value"]) / a["value"] * 100)
            if b.get("rank"):
                moves.append(abs(b["rank"] - a["rank"]))
        out.append(
            {
                "band": f"{lo}-{hi}",
                "rows": len(pct),
                "medianAbsPct": round(statistics.median(pct), 3) if pct else None,
                "maxAbsPct": round(max(pct), 3) if pct else None,
                "maxRankMove": max(moves) if moves else None,
            }
        )
    return out


def family_effects(select: dict, cap: dict) -> dict:
    newly: Counter[str] = Counter()
    crossings: Counter[str] = Counter()
    for name, a in select.items():
        b = cap.get(name)
        if not b:
            continue
        for key in set(b["voters"]) & set(a["superseded"]):
            newly[key] += 1
        # Off-cap rows carry no per-source meta on older payloads; only rows
        # with voters on both sides say anything about rungs.
        if a["voters"] and b["voters"] and _rung(len(a["voters"])) != _rung(len(b["voters"])):
            crossings[f"{_rung(len(a['voters']))}->{_rung(len(b['voters']))}"] += 1
    return {"newlyVoting": dict(newly.most_common()), "rungCrossings": dict(crossings)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--start", default="2026-09-10")
    parser.add_argument("--end", default="2026-09-24")
    parser.add_argument("--since", default="2026-04-01")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)

    days = day_archives(args.start, args.end)
    cuts = [archive_time(p) for _, p in days]
    print(f"replaying dataset state for {len(cuts)} cut(s) ...", flush=True)
    states = replay_states(cuts, args.since)

    per_day: dict[str, dict] = {}
    with tempfile.TemporaryDirectory() as tmp:
        for (day, archive), cut in zip(days, cuts):
            root = Path(tmp) / day
            build_tree(root, cut)
            sdir = root / "data" / "scrape_state"
            for key, st in states[cut].items():
                save_state(state_path(sdir, key), st)
            with zipfile.ZipFile(archive) as z:
                member = next(
                    n for n in z.namelist() if n.startswith("dynasty_data_") and n.endswith(".json")
                )
                raw = json.loads(z.read(member))
            _set_family_cap(False)
            select = build(raw, root)
            _set_family_cap(True)
            cap = build(raw, root)
            per_day[day] = {
                "asOf": raw.get("scrapeTimestamp"),
                "capVsSelect": compare(select, cap),
                "byRankBand": by_band(select, cap),
                **family_effects(select, cap),
                "rowStatesSelect": row_state_stats(select),
                "rowStatesCap": row_state_stats(cap),
            }
            d = per_day[day]["capVsSelect"]
            print(
                f"{day}: {d['changed']} changed, median {d['medianAbsPct']}%, "
                f"rungs {per_day[day]['rungCrossings']}",
                flush=True,
            )
    os.environ.pop("RISKIT_FEATURE_SOURCE_FAMILY_CAP", None)
    feature_flags.reload()
    (args.out / "summary.json").write_text(
        json.dumps({"window": [args.start, args.end], "days": per_day}, indent=1, sort_keys=True)
    )
    print(f"wrote {args.out / 'summary.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
