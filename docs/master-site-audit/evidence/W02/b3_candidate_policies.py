#!/usr/bin/env python3
"""B3 §9-§10 — evaluation criteria first, then candidate corridor policies.

Run on ONE pinned board so every candidate sees identical inputs.

CRITERIA ARE DECLARED BEFORE THE NUMBERS (§10). They are printed first and
are not adjusted afterwards; where no objective ground truth exists the
tradeoff is reported rather than scored.

Candidates:

  A  current       per-bucket P90, capped at 0.15          true pipeline run
  B  uncapped      per-bucket P90, no hard maximum         true pipeline run
  C  evidence-     empirical band, and only clamp rows     post-hoc on B
     gated         carrying enough independent evidence
  D  safety rail   clamp only genuinely pathological       post-hoc on B
                   drift, not normal disagreement
  E  none          no corridor at all                      true pipeline run

A, B and E are real pipeline builds (E via the existing
``suppress_market_corridor_clamp``; B by patching the module's cap dict
in-process for the duration of one build — a diagnostic, never written to
disk). C and D are derived post-hoc from the same drift data and are
labelled as such: they do not yet exist in production, so measuring them
truly would mean shipping them, which §9 explicitly does not authorize.
The post-hoc derivation is exact for "which rows would clamp and to what
value"; it does not re-run the downstream passes, so its rank and
composition figures are computed by re-sorting the value column.
"""

from __future__ import annotations

import contextlib
import io
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
OUT = Path(__file__).resolve().parent

IDP_FAMILY = {
    "dl_edge": {"DL", "EDGE", "DE", "DT"},
    "lb": {"LB"},
    "db": {"DB", "CB", "S"},
}

CRITERIA = """
EVALUATION CRITERIA — declared before any candidate is measured (B3 §10).
Not a score. Where no objective ground truth exists the tradeoff is
reported, not invented.

 1. Pathology containment. Does the policy still catch a value that is
    wrong rather than merely contested — the single-source explosion the
    corridor was built for?
 2. Preservation of well-evidenced disagreement. A row where several
    independent sources agree with each other and disagree with one
    dissenting source is the board working, not failing. A policy that
    overrides those rows at a HIGHER rate than thin rows is inverted.
 3. No hidden second weighting of the anchor. `idpTradeCalc` already
    votes. A policy that also lets it veto gives it two bites; the size
    of the second bite is a cost, not a feature.
 4. Robustness to one missing source. Behaviour should not hinge on
    whether one board happened to cover a player.
 5. Understandable provenance. A reader must be able to see why a value
    is what it is.
 6. Low sensitivity to arbitrary constants. A policy whose entire
    behaviour is decided by one hand-set number is fragile by
    construction.
 7. Board coherence. Positional and top-of-board composition should not
    move for reasons unrelated to evidence.

NOT a criterion: which board "looks right". No objective per-player ground
truth for dynasty IDP value exists on this timeframe, so any candidate
selected on eyeball plausibility would be selected on nothing.
"""


def board_path() -> Path:
    files = sorted((ROOT / "exports" / "latest").glob("dynasty_data_*.json"), reverse=True)
    if not files:
        raise SystemExit("no exported board")
    return files[0]


def build(**kwargs) -> dict:
    from src.api.data_contract import build_api_data_contract

    raw = json.loads(board_path().read_bytes())
    with contextlib.redirect_stdout(io.StringIO()):
        return build_api_data_contract(raw, **kwargs)


def rows_by_name(contract: dict) -> dict[str, dict]:
    return {str(r.get("displayName")): r for r in contract.get("playersArray") or []}


def _q(vals: list[float], p: float) -> float:
    if not vals:
        return float("nan")
    s = sorted(vals)
    return s[min(len(s) - 1, int(round(p * (len(s) - 1))))]


def _pct(a: int, b: int) -> str:
    return f"{100.0 * a / b:.1f}%" if b else "n/a"


def family(row: dict) -> str:
    pos = str(row.get("position") or "").upper()
    for name, members in IDP_FAMILY.items():
        if pos in members:
            return name
    return "other"


def describe(label: str, note: str, clamps: list[dict], base: dict[str, dict]) -> dict:
    """clamps: [{name, anchor, original, clamped, direction, band, bucket, sources}]"""
    pop = [
        r for r in base.values() if r.get("assetClass") == "idp" and r.get("canonicalConsensusRank")
    ]
    print(f"\n── {label} ── {note}")
    if not clamps:
        print(f"  rows affected: 0 of {len(pop)} ranked IDP rows")
        return {"label": label, "affected": 0, "population": len(pop)}
    up = sum(1 for c in clamps if c["direction"] == "up")
    moves = [100.0 * (c["clamped"] - c["original"]) / c["original"] for c in clamps]
    absmoves = [abs(m) for m in moves]
    print(
        f"  rows affected: {len(clamps)} of {len(pop)} ranked IDP rows "
        f"({_pct(len(clamps), len(pop))})   up {up} / down {len(clamps) - up}"
    )
    print(
        f"  |Δvalue%|: median={statistics.median(absmoves):.1f} "
        f"p90={_q(absmoves, 0.90):.1f} max={max(absmoves):.1f}   "
        f"signed median={statistics.median(moves):+.1f}"
    )
    by_fam: dict[str, int] = {}
    for c in clamps:
        by_fam[c["family"]] = by_fam.get(c["family"], 0) + 1
    fam_pop: dict[str, int] = {}
    for r in pop:
        fam_pop[family(r)] = fam_pop.get(family(r), 0) + 1
    print(
        "  by family: "
        + "  ".join(
            f"{k} {by_fam.get(k, 0)}/{fam_pop.get(k, 0)}" for k in ("dl_edge", "lb", "db", "other")
        )
    )
    by_bucket: dict[str, int] = {}
    for c in clamps:
        by_bucket[c["bucket"]] = by_bucket.get(c["bucket"], 0) + 1
    bucket_pop: dict[str, int] = {}
    for r in pop:
        b = str(r.get("confidenceBucket") or "")
        bucket_pop[b] = bucket_pop.get(b, 0) + 1
    print(
        "  by confidence: "
        + "  ".join(
            f"{b} {by_bucket.get(b, 0)}/{bucket_pop.get(b, 0)}"
            f" ({_pct(by_bucket.get(b, 0), bucket_pop.get(b, 0))})"
            for b in ("high", "medium", "low")
        )
    )
    by_src: dict[int, int] = {}
    for c in clamps:
        by_src[c["sources"]] = by_src.get(c["sources"], 0) + 1
    src_pop: dict[int, int] = {}
    for r in pop:
        n = len(r.get("sourceRankMeta") or {})
        src_pop[n] = src_pop.get(n, 0) + 1
    print(
        "  by source count: "
        + "  ".join(
            f"{n}→{by_src.get(n, 0)}/{src_pop.get(n, 0)}" for n in sorted(src_pop) if src_pop[n]
        )
    )
    thirds = sorted(pop, key=lambda r: r.get("canonicalConsensusRank") or 10**6)
    cut = max(1, len(thirds) // 3)
    zones = {"top": thirds[:cut], "mid": thirds[cut : 2 * cut], "tail": thirds[2 * cut :]}
    names = {c["name"] for c in clamps}
    print(
        "  by board zone: "
        + "  ".join(
            f"{z} {sum(1 for r in rs if str(r.get('displayName')) in names)}/{len(rs)}"
            for z, rs in zones.items()
        )
    )
    print("  largest 6 moves:")
    for c in sorted(clamps, key=lambda c: -abs(c["clamped"] - c["original"]))[:6]:
        print(
            f"    {c['name'][:26]:<26} {c['original']:>5} → {c['clamped']:>5} "
            f"(anchor {c['anchor']:>5}, {c['bucket']}, {c['sources']} src)"
        )
    return {
        "label": label,
        "affected": len(clamps),
        "population": len(pop),
        "up": up,
        "down": len(clamps) - up,
        "medianAbsMovePct": statistics.median(absmoves),
        "p90AbsMovePct": _q(absmoves, 0.90),
        "maxAbsMovePct": max(absmoves),
        "byFamily": by_fam,
        "byConfidence": by_bucket,
        "bySourceCount": {str(k): v for k, v in by_src.items()},
    }


def clamp_records(contract: dict) -> list[dict]:
    out = []
    for r in contract.get("playersArray") or []:
        c = r.get("marketCorridorClamp")
        if not c:
            continue
        out.append(
            {
                "name": str(r.get("displayName")),
                "anchor": c["marketAnchor"],
                "original": c["originalValue"],
                "clamped": c["clampedValue"],
                "direction": c["direction"],
                "band": c["bandPct"],
                "bucket": c["confidenceBucket"],
                "sources": len(r.get("sourceRankMeta") or {}),
                "family": family(r),
                "cappedByMaxBand": c["cappedByMaxBand"],
            }
        )
    return out


def main() -> int:
    import src.api.data_contract as dc

    print(CRITERIA)
    print(f"pinned board: {board_path().relative_to(ROOT)}")

    a_contract = build()
    base = rows_by_name(a_contract)
    a = clamp_records(a_contract)

    # B — same code, hard cap removed for one build only.
    original_cap = dict(dc._MARKET_CORRIDOR_MAX_BAND_BY_ASSET_CLASS)
    try:
        dc._MARKET_CORRIDOR_MAX_BAND_BY_ASSET_CLASS.clear()
        b_contract = build()
        b = clamp_records(b_contract)
    finally:
        dc._MARKET_CORRIDOR_MAX_BAND_BY_ASSET_CLASS.clear()
        dc._MARKET_CORRIDOR_MAX_BAND_BY_ASSET_CLASS.update(original_cap)
    assert dc._MARKET_CORRIDOR_MAX_BAND_BY_ASSET_CLASS == {"idp": 0.15}, "cap not restored"

    results = []
    results.append(
        describe(
            "A  current (bucket P90 capped at 0.15)",
            "true pipeline run — the shipped policy",
            a,
            base,
        )
    )
    results.append(
        describe(
            "B  uncapped (bucket P90, no hard maximum)",
            "true pipeline run — the empirical machinery allowed to decide",
            b,
            base,
        )
    )

    # C — evidence-gated: keep B's empirical band, but only clamp rows that
    # do NOT carry independent corroboration. A row where >=3 sources voted
    # and confidence is high/medium is the board working.
    c = [r for r in b if not (r["sources"] >= 3 and r["bucket"] in ("high", "medium"))]
    results.append(
        describe(
            "C  evidence-gated empirical band",
            "POST-HOC on B — clamp only rows without independent corroboration "
            "(<3 sources or low confidence)",
            c,
            base,
        )
    )

    # D — safety rail: only genuinely pathological drift. Threshold declared
    # structurally (2x the board's own P90 drift) rather than hand-picked.
    drifts = [abs(r["original"] - r["anchor"]) / r["anchor"] for r in b]
    rail = 2.0 * _q(drifts, 0.90) if drifts else 1.0
    d = [r for r in b if abs(r["original"] - r["anchor"]) / r["anchor"] > rail]
    results.append(
        describe(
            "D  safety rail only",
            f"POST-HOC on B — clamp only drift > {rail:.3f} (2x the board's own P90 drift)",
            d,
            base,
        )
    )

    results.append(describe("E  no corridor", "true pipeline run via suppress flag", [], base))

    # composition, true runs only
    print("\n── board composition, true pipeline runs only ──")
    e_contract = build(suppress_market_corridor_clamp=True)
    for label, contract in (
        ("A current", a_contract),
        ("B uncapped", b_contract),
        ("E none", e_contract),
    ):
        ranked = [r for r in contract.get("playersArray") or [] if r.get("canonicalConsensusRank")]
        ranked.sort(key=lambda r: r["canonicalConsensusRank"])
        line = []
        for n in (100, 200, 400):
            top = ranked[:n]
            idp = sum(1 for r in top if r.get("assetClass") == "idp")
            line.append(f"top{n} IDP {idp}")
        print(f"  {label:<12} " + "   ".join(line))

    (OUT / "b3_candidate_policies.json").write_text(
        json.dumps({"criteria": CRITERIA.strip(), "results": results}, indent=1)
    )
    print(f"\nwrote {OUT / 'b3_candidate_policies.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
