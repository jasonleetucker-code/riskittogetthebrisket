"""Render the evidence JSON into the markdown tables of ``D_BESTBALL.md``.

    python scripts/idp_accuracy/d_tables.py --write      # refresh the generated blocks in place
    python scripts/idp_accuracy/d_tables.py --check      # exit 1 if the write-up is stale

Every number in a results table of the write-up is generated here from
``evidence/bestball_archetypes.json``, never typed.  A generated block sits between
``<!-- table:NAME -->`` and ``<!-- /table:NAME -->``; ``tests/idp_accuracy`` re-renders and compares,
so the document cannot drift from the evidence it cites.

Research only.  Reads the evidence file and the write-up; writes only the write-up.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / "docs/valuation/idp_accuracy/evidence/bestball_archetypes.json"
DOC = ROOT / "docs/valuation/idp_accuracy/D_BESTBALL.md"


def _f(x: Any, nd: int = 2, pct: bool = False) -> str:
    if x is None:
        return "n/a"
    try:
        v = float(x)
    except (TypeError, ValueError):
        return str(x)
    if v != v:
        return "n/a"
    return f"{100 * v:.{nd}f}%" if pct else f"{v:.{nd}f}"


def _ci(est: dict | None, nd: int = 2, pct: bool = False) -> str:
    if not est or est.get("est") is None:
        return "n/a"
    lo, hi = est["ci95"]
    if lo is None:
        return _f(est["est"], nd, pct)
    return f"{_f(est['est'], nd, pct)} [{_f(lo, nd, pct)}, {_f(hi, nd, pct)}]"


def _table(header: list[str], rows: list[list[str]]) -> str:
    out = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    out += ["| " + " | ".join(r) + " |" for r in rows]
    return "\n".join(out)


def population(ev: dict) -> str:
    rows = []
    for r in ev["archetypeProfile"]:
        rows.append(
            [
                r["group"],
                str(r["n"]),
                _f(r["meanAppearances"], 1),
                _f(r["ppg"], 2),
                _f(r["ppgWhenActive"], 2),
                _f(r["weeklySd"], 2),
                _f(r["cvPooled"], 2),
                _f(r["pActive"], 2, True),
            ]
        )
    return _table(
        [
            "group",
            "n",
            "appearances (of 6)",
            "ppg",
            "ppg when active",
            "weekly SD",
            "SD / ppg",
            "active share",
        ],
        rows,
    )


def profile(ev: dict) -> str:
    rows = []
    for r in ev["archetypeProfile"]:
        if "eventsPerAppearance" not in r:
            continue
        e, s = r["eventsPerAppearance"], r["pointsShare"]
        rows.append(
            [
                r["group"],
                str(r["n"]),
                _f(e["tkl_solo"] + e["tkl_ast"], 2),
                _f(e["tkl_loss"], 2),
                _f(e["sack"], 2),
                _f(e["qb_hit"], 2),
                _f(e["pass_def"], 2),
                _f(s["tackles"], 0, True),
                _f(s["tfl"], 0, True),
                _f(s["passRush"], 0, True),
                _f(s["coverage"], 0, True),
                _f(s["other"], 0, True),
            ]
        )
    return _table(
        [
            "group",
            "n",
            "tackles /g",
            "TFL /g",
            "sacks /g",
            "QB hits /g",
            "PD /g",
            "tackle pts",
            "TFL pts",
            "pass-rush pts",
            "coverage pts",
            "other pts",
        ],
        rows,
    )


def premium(ev: dict) -> str:
    rows = []
    prof = {r["group"]: r for r in ev["archetypeProfile"]}
    for r in ev["volatilityPremium"]:
        p = prof.get(r["group"], {})
        rows.append(
            [
                r["group"],
                str(r["n"]),
                _f(p.get("ppg"), 2),
                _ci(r["J"], 2),
                _ci(r["JoverPpg"], 1, True),
                _f(r["JoverPpg"]["plugIn"], 1, True),
                _ci(r["JperWeeklySd"], 3),
                _f(r["plusSlopePerSd"]["est"], 3),
            ]
        )
    return _table(
        [
            "group",
            "n",
            "ppg",
            "volatility premium J, lineup ppg [95% CI]",
            "J / ppg [95% CI]",
            "J / ppg, plug-in",
            "J per 1 ppg of weekly SD [95% CI]",
            "local slope at +50% spread",
        ],
        rows,
    )


def contrasts(ev: dict) -> str:
    rows = []
    for c in ev["contrasts"]:
        a, b = c["JoverPpg"], c["JperWeeklySd"]
        rows.append(
            [
                c["contrast"],
                f"{c['nA']} / {c['nB']}",
                f"{_f(a['diff'], 1, True)} [{_f(a['ci95'][0], 1, True)}, {_f(a['ci95'][1], 1, True)}]",
                f"[{_f(a['ciBonferroni'][0], 1, True)}, {_f(a['ciBonferroni'][1], 1, True)}]",
                "yes" if a["ciExcludesZeroBonferroni"] else "no",
                f"{_f(b['diff'], 3)} [{_f(b['ci95'][0], 3)}, {_f(b['ci95'][1], 3)}]",
                "yes" if b["ciExcludesZeroBonferroni"] else "no",
            ]
        )
    return _table(
        [
            "contrast (A minus B)",
            "n A / n B",
            "J / ppg difference [95% CI]",
            "Bonferroni (5) interval",
            "excludes 0",
            "J per SD difference [95% CI]",
            "excludes 0 (Bonf.)",
        ],
        rows,
    )


def ranks(ev: dict) -> str:
    rows = []
    for r in ev["rankComparison"]["byFamily"]:
        rows.append(
            [
                r["family"],
                str(r["n"]),
                _ci(r["rhoPpgVsBestBall"], 3),
                _ci(r["rhoPpgVsDeterministicLineup"], 3),
                _ci(r["rhoGap"], 3),
                _ci(r["materialRankChangeShare"], 0, True),
                _ci(r["topThirdOverlap"], 0, True),
            ]
        )
    return _table(
        [
            "slot class",
            "n",
            "rank corr: ppg vs best-ball marginal [95% CI]",
            "ppg vs deterministic lineup",
            "gap (extra reordering from best ball)",
            "share ranked materially differently",
            "top-third overlap",
        ],
        rows,
    )


def movers(ev: dict) -> str:
    rows = []
    for fam, m in ev["rankMovers"].items():
        up = "; ".join(
            f"{g['name']} ({g['archetype']}, {_f(g['ppg'], 1)} ppg, CV {_f(g['cv'], 2)}, +{_f(g['ranksGained'], 0)})"
            for g in m["gainers"][:4]
        )
        dn = "; ".join(
            f"{g['name']} ({g['archetype']}, {_f(g['ppg'], 1)} ppg, CV {_f(g['cv'], 2)}, {_f(g['ranksGained'], 0)})"
            for g in m["losers"][:4]
        )
        rows.append([fam, str(m["familySize"]), up, dn])
    return _table(
        ["slot class", "n", "best-ball gains the most ranks", "best-ball loses the most ranks"],
        rows,
    )


def tiers(ev: dict, key: str = "premiumByPpgTier") -> str:
    rows = []
    for fam in ev[key]:
        for t in fam["tiers"]:
            rows.append(
                [
                    fam["family"],
                    t["tier"],
                    str(t["n"]),
                    f"{_f(t['range'][0], 1)} to {_f(t['range'][1], 1)}",
                    _f(t["ppg"], 2),
                    _ci(t["J"], 2),
                    _ci(t["JoverPpg"], 1, True),
                    _f(t["weeklySdOverPpg"], 2),
                ]
            )
    head = "ppg" if key == "premiumByPpgTier" else "SD / ppg (active)"
    return _table(
        [
            "slot class",
            "tier",
            "n",
            head + " range",
            "mean ppg",
            "J [95% CI]",
            "J / ppg [95% CI]",
            "SD / ppg",
        ],
        rows,
    )


def models(ev: dict) -> str:
    byg = ev["distributionChoice"]["byGroup"]
    names = [k for k in byg[0] if k != "group"]
    # collect every model name that appears anywhere
    allnames: list[str] = []
    for g in byg:
        for k in g:
            if k != "group" and k not in allnames:
                allnames.append(k)
    rows = []
    for g in byg:
        rows.append(
            [g["group"]] + [(_f(g[n]["JoverPpg"], 1, True) if n in g else "n/a") for n in allnames]
        )
    del names
    return _table(["group (J / ppg)"] + allnames, rows)


def _variant_table(
    ev: dict, metric: str, nd: int, pct: bool, pick, groups=None, head="group"
) -> str:
    sens = ev["sensitivity"]
    variants = [v for v in sens["variants"] if pick(v)]
    rows = []
    for g in sens["byGroup"]:
        if groups is not None and g["group"] not in groups:
            continue
        rows.append(
            [g["group"]] + [(_f(g[v][metric], nd, pct) if v in g else "n/a") for v in variants]
        )
    short = [v.split(" (")[0] if v.startswith("base") else v for v in variants]
    return _table([head] + short, rows)


_ARCHS = ("EDGE", "DT", "ILB", "CB", "S", "QB", "RB", "WR", "TE")


def sensitivity(ev: dict) -> str:
    """J / ppg does not depend on the replacement, so only the world-changing variants appear."""
    return _variant_table(
        ev, "JoverPpg", 1, True, lambda v: "replacement" not in v, head="group (J / ppg)"
    )


def sensitivity_rho(ev: dict) -> str:
    return _variant_table(
        ev,
        "rhoPpgVsBestBall",
        3,
        False,
        lambda v: True,
        _ARCHS,
        "archetype (rank corr: ppg vs best-ball marginal)",
    )


def sensitivity_m(ev: dict) -> str:
    return _variant_table(
        ev,
        "M",
        2,
        False,
        lambda v: v.startswith("base") or "replacement" in v,
        _ARCHS,
        "archetype (mean marginal vs replacement, lineup ppg)",
    )


def levels(ev: dict) -> str:
    """Marginal vs replacement is published as the plug-in only: see the replacement sensitivity."""
    rows = []
    for r in ev["volatilityPremium"]:
        rows.append(
            [
                r["group"],
                str(r["n"]),
                _f(r["M"]["plugIn"], 2),
                _f(r["Mdet"]["plugIn"], 2),
                _f(r["bestBallAdjustment"]["plugIn"], 2),
            ]
        )
    return _table(
        [
            "group",
            "n",
            "best-ball marginal vs replacement (lineup ppg)",
            "same marginal, deterministic ppg lineup",
            "difference",
        ],
        rows,
    )


def contrast_models(ev: dict) -> str:
    cm = ev["distributionChoice"]["contrastsByModel"]
    names = [k for k in cm[0] if k != "contrast"]
    rows = []
    for c in cm:
        rows.append([c["contrast"]] + [(_f(c[n], 1, True) if n in c else "n/a") for n in names])
    return _table(["contrast of J / ppg (A minus B), point estimate"] + names, rows)


def reliability(ev: dict) -> str:
    rel = ev["reliability"]
    rows = []
    for g, r in rel["splitHalf2025"].items():
        y = rel["yearOverYear2025to2026"].get(g, {})
        b = rel.get("shortSampleSpreadBias2025", {}).get(g, {})
        rows.append(
            [
                g,
                str(r["players"]),
                _f(r["meanHalfCorr"], 2),
                _f(r["cvHalfCorr"], 2),
                _f(r["cvFullSeasonReliabilitySpearmanBrown"], 2),
                _f(y.get("cvYoYCorr"), 2),
                _f(y.get("meanYoYCorr"), 2),
                _f(b.get("medianSdRatioFirst6OverFullSeason"), 2),
            ]
        )
    return _table(
        [
            "archetype",
            "players (2025)",
            "ppg split-half r",
            "CV split-half r",
            "CV full-season reliability (Spearman-Brown)",
            "CV year-over-year r",
            "ppg year-over-year r",
            "first-6-game SD / full-season SD (median)",
        ],
        rows,
    )


def role(ev: dict) -> str:
    rc = ev["roleChange"]
    rows = []
    for r in rc["byFamily"]:
        rows.append(
            [
                r["family"],
                str(r["n"]),
                _f(r["ppgEarlyVsLateSpearman"], 2),
                _f(r["bestBallMarginalEarlyVsLateSpearman"], 2),
                _f(r["volatilityPremiumEarlyVsLateSpearman"], 2),
            ]
        )
    return _table(
        [
            "slot class",
            "n",
            "ppg weeks 1-3 vs 4-6 (rank corr)",
            "best-ball marginal 1-3 vs 4-6",
            "volatility premium 1-3 vs 4-6",
        ],
        rows,
    )


def role_window(ev: dict) -> str:
    rows = [
        [r["group"], str(r["n"]), _f(r["JoverPpgEarly"], 1, True), _f(r["JoverPpgLate"], 1, True)]
        for r in ev["roleChange"]["volatilityPremiumByArchetypeByWindow"]
    ]
    return _table(["archetype", "n", "J / ppg, weeks 1-3", "J / ppg, weeks 4-6"], rows)


def variance(ev: dict) -> str:
    rows = []
    for r in ev["varianceAssumptions"]["scoreVarianceVsPoisson"]:
        d = r["eventDispersionIndex2025"]
        rows.append(
            [
                r["group"],
                str(r["playersWithRates"]),
                _f(r["observedOverPoissonScoreVariance"]["median"], 2),
                _f(d.get("sack"), 2),
                _f(d.get("tkl_loss"), 2),
                _f(d.get("qb_hit"), 2),
                _f(d.get("pass_def"), 2),
                _f(d.get("tkl_solo"), 2),
            ]
        )
    return _table(
        [
            "group",
            "players",
            "observed / Poisson score variance (median)",
            "sack dispersion",
            "TFL dispersion",
            "QB-hit dispersion",
            "PD dispersion",
            "solo-tackle dispersion",
        ],
        rows,
    )


def library(ev: dict) -> str:
    rows = [
        [
            r["family"],
            str(r["n"]),
            _f(r["libraryAssumedCv"], 2),
            _f(r["observedCv2026"], 2),
            _f(r["priorSeasonShapeCv"], 2),
            _f(r["observedOverAssumed"], 2),
        ]
        for r in ev["libraryVarianceAssumption"]["byFamily"]
    ]
    return _table(
        [
            "position family",
            "n",
            "library assumed CV",
            "observed SD/ppg (2026 wk 1-6)",
            "prior-season pooled SD/ppg",
            "observed / assumed",
        ],
        rows,
    )


def profile_split(ev: dict) -> str:
    rows = []
    for r in ev["profileSplit"]:
        rows.append(
            [
                r["group"],
                f"{r['nExplosiveHalf']} / {r['nStableHalf']}",
                _f(r["medianBigPlayShare"], 0, True),
                f"{_f(r['cvExplosive'], 2)} / {_f(r['cvStable'], 2)}",
                f"{_f(r['JoverPpgExplosive'], 1, True)} / {_f(r['JoverPpgStable'], 1, True)}",
                f"{_f(r['diff'], 1, True)} [{_f(r['ci95'][0], 1, True)}, {_f(r['ci95'][1], 1, True)}]",
                f"[{_f(r['ciBonferroni'][0], 1, True)}, {_f(r['ciBonferroni'][1], 1, True)}]",
            ]
        )
    return _table(
        [
            "archetype",
            "n explosive / stable half",
            "median big-play share",
            "SD/ppg explosive / stable",
            "J/ppg explosive / stable",
            "difference [95% CI]",
            "Bonferroni interval",
        ],
        rows,
    )


def fine(ev: dict) -> str:
    fr = ev["fineResolution"]
    rows = [[k, str(v)] for k, v in fr["playersWithAppearancesByProvenance"].items()]
    cc = fr["crossCheckNflverseVsSleeperDepth"]
    rows.append(
        [
            "cross-check: nflverse vs Sleeper depth chart agree / disagree",
            f"{cc['agree']} / {cc['disagree']} ({_f(cc['agreementRate'], 1, True)})",
        ]
    )
    return _table(["join (players with a 2026 appearance)", "count"], rows)


def realized(ev: dict) -> str:
    rows = [
        [
            r["family"],
            str(r["n"]),
            _f(r["spearmanModelVsRealized"], 2),
            _f(r["spearmanPpgVsRealized"], 2),
        ]
        for r in ev["realizedCheck"]["byFamily"]
    ]
    return _table(
        [
            "slot class",
            "n",
            "model marginal vs realized-weeks marginal (rank corr)",
            "ppg vs realized-weeks marginal",
        ],
        rows,
    )


def headline(ev: dict) -> str:
    h = ev["headline"]
    rows = []
    for tag, label in (("idp", "IDP (six archetypes)"), ("offense", "Offense (QB/RB/WR/TE)")):
        r = h.get(tag)
        if r:
            rows.append(
                [
                    label,
                    str(r["n"]),
                    _ci(r["J"], 2),
                    _ci(r["JoverPpg"], 1, True),
                    _f(r["JoverPpg"]["plugIn"], 1, True),
                    _ci(r["JperWeeklySd"], 3),
                ]
            )
    return _table(
        [
            "population",
            "n",
            "volatility premium J, lineup ppg [95% CI]",
            "J / ppg [95% CI]",
            "J / ppg, plug-in",
            "J per 1 ppg of weekly SD [95% CI]",
        ],
        rows,
    )


RENDERERS = {
    "headline": headline,
    "population": population,
    "profile": profile,
    "fine": fine,
    "premium": premium,
    "contrasts": contrasts,
    "profileSplit": profile_split,
    "ranks": ranks,
    "movers": movers,
    "tiersPpg": lambda ev: tiers(ev, "premiumByPpgTier"),
    "tiersCv": lambda ev: tiers(ev, "premiumByVolatilityTier"),
    "models": models,
    "sensitivity": sensitivity,
    "sensitivityRho": sensitivity_rho,
    "sensitivityM": sensitivity_m,
    "contrastModels": contrast_models,
    "levels": levels,
    "reliability": reliability,
    "role": role,
    "roleWindow": role_window,
    "variance": variance,
    "library": library,
    "realized": realized,
}

_BLOCK = re.compile(
    r"<!-- table:(?P<name>\w+) -->\n(?P<body>.*?)\n?<!-- /table:(?P=name) -->", re.S
)


def render_all(ev: dict) -> dict[str, str]:
    return {name: fn(ev) for name, fn in RENDERERS.items()}


def blocks_in(text: str) -> dict[str, str]:
    return {m.group("name"): m.group("body") for m in _BLOCK.finditer(text)}


def refresh(text: str, ev: dict) -> str:
    tables = render_all(ev)

    def sub(m: re.Match) -> str:
        name = m.group("name")
        if name not in tables:
            raise KeyError(f"unknown table block {name!r}")
        return f"<!-- table:{name} -->\n{tables[name]}\n<!-- /table:{name} -->"

    return _BLOCK.sub(sub, text)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)
    ev = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    text = DOC.read_text(encoding="utf-8")
    new = refresh(text, ev)
    if args.write:
        DOC.write_text(new, encoding="utf-8")
        print(f"refreshed {len(blocks_in(new))} generated tables in {DOC.relative_to(ROOT)}")
        return 0
    if args.check:
        if new != text:
            print(
                "D_BESTBALL.md is stale against the evidence; run d_tables.py --write",
                file=sys.stderr,
            )
            return 1
        return 0
    print(json.dumps({k: v for k, v in render_all(ev).items()}, indent=1)[:4000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
