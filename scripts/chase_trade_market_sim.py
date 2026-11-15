#!/usr/bin/env python3
"""chaseTradeMarket simulation + power study (P6a / G12s) — SYNTHETIC ONLY.

    python scripts/chase_trade_market_sim.py scenario [--seed N] [--ablations] [--inner-cv]
    python scripts/chase_trade_market_sim.py power --leagues 20,40,80 --trades-per-league 15,30 \\
        --replicates 3 [--target pairwise_accuracy=0.8] [--observed-train-trades N] \\
        [--maturity-effect 0.3] [--out report.json] [--markdown report.md]
    python scripts/chase_trade_market_sim.py examples [--seed N]
    python scripts/chase_trade_market_sim.py components [--leagues 40,160]

Every world is invented (``syn-`` ids); nothing here opens a store, the
network or a canonical value, so output is safe to print and commit.
``--observed-train-trades`` takes the real on-box count of eligible training
trades (an aggregate number) and turns the required count into a shortfall;
without it the shortfall is reported as UNKNOWN, never zero.  The real-graph
run (simulating on the measured trade-graph topology) belongs to P6 on the
box, after P2's evidence fields land.

Exit codes: 0 ok · 1 error.
"""

from __future__ import annotations

import os

# Small dense matrices + multi-threaded BLAS are pathologically slow (measured
# ~40x on a 4-core runner); the production unit pins one thread too (plan §7).
for _var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_var, "1")

import argparse  # noqa: E402
import json  # noqa: E402
import math  # noqa: E402
import re  # noqa: E402
import sys  # noqa: E402
from dataclasses import replace  # noqa: E402
from pathlib import Path  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.trade import market_trade_sim as sim  # noqa: E402
from src.trade import market_trade_sim_bench as bench  # noqa: E402


def _ints(text: str) -> list[int]:
    return [int(x) for x in text.split(",") if x.strip()]


def _floats(text: str) -> list[float]:
    return [float(x) for x in text.split(",") if x.strip()]


def _targets(items: list[str] | None) -> dict[str, float]:
    out: dict[str, float] = {}
    for item in items or ["pairwise_accuracy=0.80"]:
        name, _, val = item.partition("=")
        out[name.strip()] = float(val)
    return out


def load_config_overrides(path: Path) -> dict:
    """Aggregate-only SimConfig overrides from JSON — how the on-box run feeds
    the MEASURED shape of the real trade graph (topology mix, maturity
    distribution, activity spread, overlap, latency) into the generator.
    Unknown keys are refused, and so is any string that looks like a raw id,
    so an id can never ride into a synthetic world."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    fields = sim.SimConfig.__dataclass_fields__
    unknown = sorted(set(raw) - set(fields) - {"_comment"})
    if unknown:
        raise ValueError(f"unknown SimConfig keys: {unknown}")
    if re.search(r"\d{15,}", json.dumps(raw)):
        raise ValueError("config JSON contains a long numeric id; aggregates only")
    out = {}
    for k, v in raw.items():
        if k == "_comment":
            continue
        out[k] = (
            tuple(tuple(x) if isinstance(x, list) else x for x in v) if isinstance(v, list) else v
        )
    return out


def _base_config(args: argparse.Namespace) -> sim.SimConfig:
    cfg = sim.SimConfig(seed=args.seed)
    if getattr(args, "config_json", None):
        cfg = replace(cfg, **load_config_overrides(args.config_json))
    for name in (
        "maturity_effect",
        "q_true",
        "manager_multi_league_prob",
        "drift_sd_per_week",
        "noise_scale",
    ):
        val = getattr(args, name, None)
        if val is not None:
            cfg = replace(cfg, **{name: val})
    return cfg


def _estimators(args: argparse.Namespace) -> tuple[bench.EstimatorSpec, ...]:
    ests = bench.DEFAULT_ESTIMATORS
    if getattr(args, "ablations", False):
        ests = ests + bench.ABLATION_ESTIMATORS
    if getattr(args, "only", None):
        keep = set(args.only.split(","))
        ests = tuple(e for e in ests + bench.ABLATION_ESTIMATORS if e.name in keep)
    return ests


def cmd_scenario(args: argparse.Namespace) -> dict:
    cfg = _base_config(args)
    if args.leagues:
        cfg = replace(cfg, n_leagues=args.leagues)
    if args.trades_per_league:
        cfg = replace(cfg, trades_per_league=args.trades_per_league)
    ests = list(_estimators(args))
    cv_report = None
    if args.inner_cv:
        world = sim.generate_world(cfg)
        reserve = sim.reserved_components(
            world.component_ids, salt=bench.SplitSpec().reserve_salt, share=0.2
        )
        import numpy as np

        train, _, _ = sim.chronological_split(
            world.trades, cutoff_day=cfg.span_days - bench.SplitSpec().holdout_days, purge_days=7
        )
        train &= ~np.isin(world.trades.component, sorted(reserve))
        grid = [{"half_life_days": h} for h in (90.0, 45.0, 180.0, None)]
        base = next(e for e in ests if e.name == "geom_huber")
        cv = bench.select_by_inner_cv(world, world.trades.subset(train), base, grid, seed=cfg.seed)
        chosen = replace(cv["chosen"], name="geom_huber_innercv")
        ests.append(chosen)
        cv_report = {"scores": cv["scores"], "chosen_half_life_days": chosen.half_life_days}
    out = bench.run_scenario(cfg, ests)
    if cv_report:
        out["inner_cv"] = cv_report
    out["synthetic"] = True
    return out


def cmd_power(args: argparse.Namespace) -> dict:
    observed = {"train_trades": args.observed_train_trades}
    return bench.power_study(
        _base_config(args),
        leagues_grid=_ints(args.leagues),
        trades_per_league_grid=_floats(args.trades_per_league),
        replicates=args.replicates,
        estimators=_estimators(args),
        targets=_targets(args.target),
        observed=observed,
    )


def cmd_examples(args: argparse.Namespace) -> dict:
    cfg = replace(
        _base_config(args),
        n_leagues=args.leagues or 80,
        trades_per_league=args.trades_per_league or 30,
    )
    world = sim.generate_world(cfg)
    train, _, cutoff = sim.chronological_split(world.trades, cutoff_day=cfg.span_days, purge_days=0)
    fit = bench.fit_latent(
        world, world.trades.subset(train), bench.EstimatorSpec("geom_huber"), evidence_cutoff=cutoff
    )
    return {"synthetic": True, "examples": bench.worked_examples(world, fit, n_assets=args.n)}


def cmd_components(args: argparse.Namespace) -> dict:
    import numpy as np

    rows = []
    for p in _floats(args.overlap):
        for n in _ints(args.leagues):
            w = sim.generate_world(
                replace(
                    sim.SimConfig(seed=args.seed),
                    manager_multi_league_prob=p,
                    n_leagues=n,
                    trades_per_league=1,
                )
            )
            rows.append(
                {
                    "per_seat_overlap": p,
                    "leagues": n,
                    "components": len(w.component_ids),
                    "largest_component_leagues": int(np.bincount(w.leagues.component).max()),
                }
            )
    return {"synthetic": True, "rows": rows}


def _clean(obj):
    """Strict JSON: NaN/inf -> null (missing is never a number), numpy
    scalars -> Python, dataclass specs -> their name."""
    if isinstance(obj, dict):
        return {str(k): _clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_clean(v) for v in obj]
    if isinstance(obj, bench.EstimatorSpec):
        return obj.name
    if hasattr(obj, "item") and not isinstance(obj, (str, bytes)):
        obj = obj.item()
    if isinstance(obj, float) and not math.isfinite(obj):
        return None
    return obj


def _fmt(v, digits=3) -> str:
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:.{digits}f}"
    return str(v)


def render_power_markdown(report: dict) -> str:
    """Compact tables: per tier, supported accuracy (coverage) per estimator
    at every grid point, then the requirement table."""
    lines = ["# chaseTradeMarket power study — synthetic", ""]
    g = report["grid"]
    lines.append(
        f"Grid: leagues {g['leagues']} × trades/league {g['trades_per_league']}, {g['replicates']} replicates."
    )
    lines.append("")
    points = report["points"]
    ests = list(points[0]["metrics"]) if points else []
    tiers = sorted({t for p in points for e in p["metrics"].values() for t in e if ":" in t})
    for tier in tiers:
        lines += [
            f"## {tier}",
            "",
            "| leagues | tr/lg | train trades | comps | " + " | ".join(ests) + " |",
        ]
        lines.append("|" + "---|" * (4 + len(ests)))
        for p in points:
            cells = []
            for e in ests:
                row = p["metrics"][e].get(tier) or {}
                acc = (row.get("pairwise_accuracy") or {}).get("mean")
                cov = (row.get("supported_coverage") or {}).get("mean")
                app = (row.get("appeared_pairwise_accuracy") or {}).get("mean")
                cells.append(f"{_fmt(acc, 2)} ({_fmt(cov, 2)}) / {_fmt(app, 2)}")
            lines.append(
                f"| {p['n_leagues']} | {p['trades_per_league']:g} | {p['train_trades_mean']:.0f} | {p['components_mean']:.0f} | "
                + " | ".join(cells)
                + " |"
            )
        lines.append("")
    lines += [
        "Cell = supported pairwise accuracy (supported coverage) / all-appeared pairwise accuracy.",
        "",
    ]
    lines += [
        "## Requirements",
        "",
        "| estimator | tier | target | tr/lg | required train trades | ...touching the tier's domain"
        " | required total trades | required leagues | shortfall |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for key, req in sorted(report["requirements"].items()):
        est, tier, target, tpl = key.split("|")
        rt, rl, sf = req["required_train_trades"], req["required_leagues"], req["shortfall_trades"]
        tot = req.get("required_total_trades_incl_holdouts") or {}
        dom = req.get("required_train_trades_touching_domain") or {}
        lines.append(
            f"| {est} | {tier} | {target} | {tpl[4:]} | {rt['state']} {_fmt(rt.get('required'), 0)} | "
            f"{_fmt(dom.get('required'), 0)} | "
            f"{_fmt(tot.get('required'), 0)} | {rl['state']} {_fmt(rl.get('required'), 0)} | "
            f"{sf['state']} {_fmt(sf.get('shortfall'), 0)} |"
        )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("--seed", type=int, default=0)
        p.add_argument("--maturity-effect", dest="maturity_effect", type=float)
        p.add_argument("--q-true", dest="q_true", type=float)
        p.add_argument("--manager-overlap", dest="manager_multi_league_prob", type=float)
        p.add_argument("--drift", dest="drift_sd_per_week", type=float)
        p.add_argument("--noise", dest="noise_scale", type=float)
        p.add_argument("--out", type=Path, help="write JSON here instead of stdout")
        p.add_argument(
            "--config-json", dest="config_json", type=Path, help="aggregate SimConfig overrides"
        )

    p = sub.add_parser("scenario")
    common(p)
    p.add_argument("--leagues", type=int)
    p.add_argument("--trades-per-league", type=float)
    p.add_argument("--ablations", action="store_true")
    p.add_argument("--only", help="comma-separated estimator names")
    p.add_argument("--inner-cv", action="store_true")

    p = sub.add_parser("power")
    common(p)
    p.add_argument("--leagues", default="20,40,80,160")
    p.add_argument("--trades-per-league", default="15,30")
    p.add_argument("--replicates", type=int, default=3)
    p.add_argument("--target", action="append")
    p.add_argument("--observed-train-trades", type=float, default=None)
    p.add_argument("--ablations", action="store_true")
    p.add_argument("--only", help="comma-separated estimator names")
    p.add_argument("--markdown", type=Path)

    p = sub.add_parser("examples")
    common(p)
    p.add_argument("--leagues", type=int)
    p.add_argument("--trades-per-league", type=float)
    p.add_argument("--n", type=int, default=5)

    p = sub.add_parser("components")
    common(p)
    p.add_argument("--leagues", default="40,160")
    p.add_argument("--overlap", default="0,0.01,0.02,0.05,0.1,0.15")

    args = ap.parse_args(argv)
    try:
        report = {
            "scenario": cmd_scenario,
            "power": cmd_power,
            "examples": cmd_examples,
            "components": cmd_components,
        }[args.cmd](args)
    except Exception as exc:  # noqa: BLE001 — CLI boundary
        print(f"error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    text = json.dumps(_clean(report), indent=2, sort_keys=True, allow_nan=False)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    if args.cmd == "power" and getattr(args, "markdown", None):
        args.markdown.parent.mkdir(parents=True, exist_ok=True)
        args.markdown.write_text(render_power_markdown(report), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
