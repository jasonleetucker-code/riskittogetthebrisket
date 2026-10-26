#!/usr/bin/env python3
"""Per-league projection scoring coverage, before vs after source vocabularies.

For each league card pinned in the 2026-10-01 scoring census
(``../scoring-census-2026-10-01/census.json``), and for each projection lane
(declared source × position family), build one synthetic record carrying
EXACTLY the source's declared vocabulary and report:

* ``before`` — what ``unscoredKeys`` used to say: the realized engine's own
  play-by-play-only rules (position-blind), nothing about the source;
* ``after``  — ``src.bdvm.source_vocabulary.record_coverage``: source
  vocabulary gaps + family-scoped play-by-play rules, or ``unverifiable``.

Each unscored rule is priced with the census's REALIZED 2025 points for that
family (signed — a penalty omitted overstates a total), so the largest
contributors rank by measured impact, never by key count.  Reporting only.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO_ROOT))

from src.bdvm.projections import ProjectionRecord  # noqa: E402
from src.bdvm.source_vocabulary import (  # noqa: E402
    PBP_SUPPLEMENT_KEYS,
    declared_capabilities,
    family_of,
    record_coverage,
)

LANES = (
    ("clayProjections", ("QB", "RB", "WR", "TE", "EDGE", "LB", "CB")),
    ("idpShowProjections", ("EDGE", "LB", "CB")),
)


def _points(rule: dict | None, fam: str) -> float:
    if not rule or not rule.get("realized"):
        return 0.0
    return float((rule["realized"].get("byFamily") or {}).get(fam, 0.0))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--census",
        type=Path,
        default=REPO_ROOT / "docs/research/bdvm-v1/scoring-census-2026-10-01/census.json",
    )
    ap.add_argument("--out", required=True, type=Path)
    a = ap.parse_args()
    census = json.loads(a.census.read_text(encoding="utf-8"))
    caps = declared_capabilities()
    out: dict = {"scope": "LOCAL, reporting only", "census": a.census.name, "leagues": {}}
    for league in census["leagues"]:
        # census.json pins the card by hash; its rules list carries every
        # NONZERO rule with its weight, which is all coverage depends on.
        rules = {r["key"]: r for r in league["rules"]}
        card = {k: r["weight"] for k, r in rules.items()}
        lanes: list[dict] = []
        for source, positions in LANES:
            for pos in positions:
                fam = family_of(pos)
                if not league["idpEnabled"] and fam in ("DL", "LB", "DB"):
                    continue
                vocab = caps[source].vocabulary_by_family.get(fam)
                if not vocab:
                    continue
                rec = ProjectionRecord(
                    source=source,
                    player_key="probe",
                    position=pos,
                    season=2026,
                    as_of="2026-10-01",
                    games=17.0,
                    stat_line={c: 1.0 for c in vocab},
                )
                _fpg, _n, before = rec.resolve_fpg_detailed(card)
                after = record_coverage(rec, card, engine_unscored=before)
                lanes.append(_lane(source, pos, fam, before, after, rules))
        for label, declared in (
            ("reconstructedBaseline (PBP built)", ()),
            (
                "reconstructedBaseline (no PBP artifact)",
                tuple(k for k in sorted(PBP_SUPPLEMENT_KEYS) if card.get(k)),
            ),
            ("reconstructedBaseline (legacy snapshot, coverage not recorded)", None),
        ):
            for pos in ("WR", "LB"):
                fam = family_of(pos)
                if not league["idpEnabled"] and fam == "LB":
                    continue
                rec = ProjectionRecord(
                    source="reconstructedBaseline",
                    player_key="probe",
                    position=pos,
                    season=2026,
                    as_of="2026-10-01",
                    games=16.0,
                    fpg=10.0,
                    scoring_native=True,
                    is_proxy=True,
                    declared_unscored=declared,
                )
                lanes.append(
                    _lane(label, pos, fam, (), record_coverage(rec, card), rules, proxy=True)
                )
        out["leagues"][league["leagueKey"]] = {"idpEnabled": league["idpEnabled"], "lanes": lanes}
    a.out.write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    for lk, blob in out["leagues"].items():
        print(f"== {lk}")
        for ln in blob["lanes"]:
            top = ", ".join(f"{k} {p:+.0f}" for k, p in ln["afterTop"][:6])
            print(
                f"  {ln['lane']:<62} {ln['position']:<5} {ln['status']:<12} "
                f"before {ln['beforeCount']:>2} ({ln['beforePoints']:+.0f}) -> "
                f"after {ln['afterCount']:>2} ({ln['afterPoints']:+.0f})  [{top}]"
            )
    return 0


def _lane(source, pos, fam, before, after, rules, proxy=False) -> dict:
    after_keys = list(after.unscored_keys)
    before_keys = sorted(set(before))
    scored = sorted(((k, _points(rules.get(k), fam)) for k in after_keys), key=lambda t: -abs(t[1]))
    return {
        "lane": source,
        "position": pos,
        "family": fam,
        "status": after.status,
        "reason": after.reason,
        "beforeCount": len(before_keys),
        "beforePoints": round(sum(_points(rules.get(k), fam) for k in before_keys), 1),
        "afterCount": len(after_keys),
        "afterPoints": round(sum(p for _k, p in scored), 1),
        "afterTop": [(k, round(p, 1)) for k, p in scored],
        "newlyReported": sorted(set(after_keys) - set(before_keys)),
        "noLongerReported": sorted(set(before_keys) - set(after_keys)),
    }


if __name__ == "__main__":
    raise SystemExit(main())
