#!/usr/bin/env python3
"""Continuous Improvement System CLI — versioning, validation, rollback.

Subcommands
-----------
    status      Show the champion, its confidence, and the version log.
    sources     Print the train/holdout split so it can be checked.
    evaluate    Score a (c, s) pair — or the champion — out of sample.
    register    Record a challenger produced by a refit.
    validate    Champion vs challenger on the held-out criterion.
    promote     Make a challenger the champion (records the reason).
    rollback    Reinstate the previous champion. THE undo.
    apply       Write the champion's params into player_valuation.py.

Rollback, in full, is:

    python3 scripts/model_registry.py rollback --reason "bad refit"
    python3 scripts/model_registry.py apply

Exit codes:
    0   success / promote
    1   no-op (no drift, or challenger rejected)
    2   error
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from src.model_registry.holdout import (  # noqa: E402
    HoldoutError,
    evaluate_offense_master,
    source_roles,
)
from src.model_registry.promotion import decide_promotion  # noqa: E402
from src.model_registry.versioning import (  # noqa: E402
    ModelRegistry,
    ModelVersion,
    RegistryError,
    fingerprint_inputs,
)

MODEL_ID = "hill_scope_masters"
PLAYER_VALUATION = REPO / "src" / "canonical" / "player_valuation.py"

CONSTANT_NAMES: tuple[str, ...] = (
    "HILL_GLOBAL_PERCENTILE_C",
    "HILL_GLOBAL_PERCENTILE_S",
    "HILL_PERCENTILE_C",
    "HILL_PERCENTILE_S",
    "IDP_HILL_PERCENTILE_C",
    "IDP_HILL_PERCENTILE_S",
    "HILL_ROOKIE_PERCENTILE_C",
    "HILL_ROOKIE_PERCENTILE_S",
)


def read_committed_constants() -> dict[str, float]:
    text = PLAYER_VALUATION.read_text()
    out: dict[str, float] = {}
    for name in CONSTANT_NAMES:
        m = re.search(rf"^{re.escape(name)}:\s*float\s*=\s*([0-9.]+)\s*$", text, re.MULTILINE)
        if not m:
            raise RegistryError(f"could not find {name!r} in {PLAYER_VALUATION}")
        out[name] = float(m.group(1))
    return out


def write_committed_constants(params: dict[str, float]) -> None:
    text = PLAYER_VALUATION.read_text()
    for name in CONSTANT_NAMES:
        if name not in params:
            raise RegistryError(f"champion params missing {name!r}")
        literal = f"{params[name]:.4f}" if name.endswith("_C") else f"{params[name]:.3f}"
        text, n = re.subn(
            rf"^({re.escape(name)}:\s*float\s*=\s*)[0-9.]+(\s*)$",
            rf"\g<1>{literal}\g<2>",
            text,
            flags=re.MULTILINE,
        )
        if n != 1:
            raise RegistryError(f"expected 1 match for {name!r}, got {n}")
    PLAYER_VALUATION.write_text(text)


def _git_sha() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(REPO),
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except Exception:  # noqa: BLE001
        return "unknown"


def _training_input_paths() -> dict[str, Path]:
    return {role.label: REPO / role.path for role in source_roles() if role.role == "train"}


def _load_or_seed() -> ModelRegistry:
    """Load the registry, seeding from live constants on first use.

    Seeding records what is ALREADY live as v1 champion.  It is not a
    claim that those constants won anything — ``qualified`` stays False
    until someone evaluates them.
    """
    try:
        return ModelRegistry.load(MODEL_ID)
    except RegistryError:
        reg = ModelRegistry(MODEL_ID)
        reg.seed_champion(
            ModelVersion(
                model_id=MODEL_ID,
                version=1,
                params=read_committed_constants(),
                fitted_at="unknown",
                producer="seeded from committed constants in player_valuation.py",
                training_inputs=fingerprint_inputs(_training_input_paths()),
                notes=(
                    "seeded, not validated: these constants were live before the "
                    "registry existed and carry no out-of-sample score",
                ),
            )
        )
        reg.save()
        return reg


# ── subcommands ────────────────────────────────────────────────────


def cmd_status(args: argparse.Namespace) -> int:
    reg = _load_or_seed()
    champ = reg.champion
    print(f"model: {reg.model_id}")
    print(f"champion: v{champ.version}  confidence={champ.confidence}")
    if not champ.qualified:
        print(
            "  WARNING: champion has no out-of-sample score. Its output must not "
            "be presented as validated. Run `evaluate --champion`."
        )
    else:
        print(f"  held-out criterion: {champ.holdout['criterion']:.1f} (lower is better)")
    print(f"  fitted: {champ.fitted_at}   producer: {champ.producer}")
    print()
    print(f"{'ver':>4}  {'status':<11}{'confidence':<13}{'criterion':>11}  fitted")
    for v in reg.versions:
        crit = (v.holdout or {}).get("criterion")
        crit_s = f"{crit:.1f}" if crit is not None else "-"
        print(f"{v.version:>4}  {v.status:<11}{v.confidence:<13}{crit_s:>11}  {v.fitted_at}")
    return 0


def cmd_sources(args: argparse.Namespace) -> int:
    print(f"{'source':<20}{'role':<10}{'rows':>7}  path")
    for role in source_roles():
        path = REPO / role.path
        rows = "missing"
        if path.exists():
            with path.open(encoding="utf-8") as f:
                rows = str(max(0, sum(1 for _ in f) - 1))
        print(f"{role.label:<20}{role.role:<10}{rows:>7}  {role.path}")
    print()
    print(
        "Holdout boards are value-publishing dynasty markets the fit never reads.\n"
        "They measure generalization across markets, NOT accuracy: every board is\n"
        "another consensus market pricing the same players off the same news."
    )
    return 0


def cmd_evaluate(args: argparse.Namespace) -> int:
    if args.champion:
        reg = _load_or_seed()
        params = reg.champion.params
        c, s = params["HILL_PERCENTILE_C"], params["HILL_PERCENTILE_S"]
        label = f"champion v{reg.champion.version}"
    else:
        c, s = args.c, args.s
        label = f"c={c} s={s}"

    try:
        result = evaluate_offense_master(c, s)
    except HoldoutError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    print(f"held-out evaluation — {label}")
    print(f"  criterion (mean per-source RMSE): {result.criterion:.1f}")
    for src, rmse in sorted(result.per_source.items()):
        print(f"    {src:<20}{rmse:>9.1f}   n={result.per_source_rows[src]}")
    for src, why in sorted(result.skipped.items()):
        print(f"    {src:<20}{'skipped':>9}   {why}")

    if args.champion and args.record:
        reg = _load_or_seed()
        champ = reg.champion
        updated = [
            ModelVersion(
                model_id=v.model_id,
                version=v.version,
                params=v.params,
                fitted_at=v.fitted_at,
                producer=v.producer,
                status=v.status,
                training_inputs=v.training_inputs,
                holdout=result.to_dict() if v.version == champ.version else v.holdout,
                notes=v.notes,
                promoted_at=v.promoted_at,
                retired_at=v.retired_at,
            )
            for v in reg.versions
        ]
        ModelRegistry(MODEL_ID, updated).save()
        print(f"  recorded against champion v{champ.version}")
    return 0


def cmd_register(args: argparse.Namespace) -> int:
    reg = _load_or_seed()
    params = json.loads(Path(args.params).read_text())
    params = {str(k): float(v) for k, v in params.items()}
    missing = [n for n in CONSTANT_NAMES if n not in params]
    if missing:
        print(f"ERROR: params missing {missing}", file=sys.stderr)
        return 2

    try:
        result = evaluate_offense_master(params["HILL_PERCENTILE_C"], params["HILL_PERCENTILE_S"])
    except HoldoutError as exc:
        print(f"ERROR: challenger could not be evaluated: {exc}", file=sys.stderr)
        return 2

    version = ModelVersion(
        model_id=MODEL_ID,
        version=reg.next_version(),
        params=params,
        fitted_at=args.fitted_at or "unknown",
        producer=args.producer or f"scripts/fit_hill_curve_percentile.py @ {_git_sha()}",
        status="challenger",
        training_inputs=fingerprint_inputs(_training_input_paths()),
        holdout=result.to_dict(),
    )
    reg.add(version)
    reg.save()
    print(f"registered challenger v{version.version}  criterion={result.criterion:.1f}")
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    reg = _load_or_seed()
    champ = reg.champion
    try:
        challenger = reg.get(args.version)
    except RegistryError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    champ_crit = (champ.holdout or {}).get("criterion")
    chal_crit = (challenger.holdout or {}).get("criterion")
    if chal_crit is None:
        print(f"ERROR: challenger v{challenger.version} has no held-out score", file=sys.stderr)
        return 2

    decision = decide_promotion(champ_crit, chal_crit)
    print(f"champion   v{champ.version}: {champ_crit if champ_crit is not None else 'unmeasured'}")
    print(f"challenger v{challenger.version}: {chal_crit:.1f}")
    print(f"verdict: {'PROMOTE' if decision.promote else 'REJECT'} — {decision.reason}")
    if decision.alarm:
        print("ALARM: regression large enough to suspect the fit or its inputs.")
    return 0 if decision.promote else 1


def cmd_promote(args: argparse.Namespace) -> int:
    reg = _load_or_seed()
    try:
        champ = reg.promote(args.version, reason=args.reason)
    except RegistryError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    reg.save()
    print(f"champion is now v{champ.version}")
    print("Run `apply` to write these constants into player_valuation.py.")
    return 0


def cmd_rollback(args: argparse.Namespace) -> int:
    reg = _load_or_seed()
    try:
        champ = reg.rollback(to_version=args.to_version, reason=args.reason)
    except RegistryError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    reg.save()
    print(f"rolled back — champion is now v{champ.version}")
    print("Run `apply` to write these constants into player_valuation.py.")
    return 0


def cmd_apply(args: argparse.Namespace) -> int:
    reg = _load_or_seed()
    champ = reg.champion
    live = read_committed_constants()
    if live == champ.params:
        print(f"player_valuation.py already matches champion v{champ.version} — no change")
        return 1
    if args.dry_run:
        print(f"would write champion v{champ.version}:")
        for name in CONSTANT_NAMES:
            if live.get(name) != champ.params.get(name):
                print(f"  {name}: {live.get(name)} -> {champ.params.get(name)}")
        return 0
    write_committed_constants(champ.params)
    print(f"wrote champion v{champ.version} into {PLAYER_VALUATION.relative_to(REPO)}")
    print("Run the test suite before committing.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status", help="show champion + version log").set_defaults(fn=cmd_status)
    sub.add_parser("sources", help="print the train/holdout split").set_defaults(fn=cmd_sources)

    p_eval = sub.add_parser("evaluate", help="score a (c, s) pair out of sample")
    p_eval.add_argument("--c", type=float, help="Hill midpoint")
    p_eval.add_argument("--s", type=float, help="Hill slope")
    p_eval.add_argument("--champion", action="store_true", help="score the current champion")
    p_eval.add_argument("--record", action="store_true", help="store the score on the champion")
    p_eval.set_defaults(fn=cmd_evaluate)

    p_reg = sub.add_parser("register", help="record a challenger from a refit")
    p_reg.add_argument("--params", required=True, help="JSON file of the 8 constants")
    p_reg.add_argument("--producer", help="what produced it")
    p_reg.add_argument("--fitted-at", help="ISO 8601 timestamp")
    p_reg.set_defaults(fn=cmd_register)

    p_val = sub.add_parser("validate", help="champion vs challenger")
    p_val.add_argument("version", type=int)
    p_val.set_defaults(fn=cmd_validate)

    p_pro = sub.add_parser("promote", help="make a challenger the champion")
    p_pro.add_argument("version", type=int)
    p_pro.add_argument("--reason", required=True)
    p_pro.set_defaults(fn=cmd_promote)

    p_rb = sub.add_parser("rollback", help="reinstate the previous champion")
    p_rb.add_argument("--to-version", type=int, default=None)
    p_rb.add_argument("--reason", required=True)
    p_rb.set_defaults(fn=cmd_rollback)

    p_ap = sub.add_parser("apply", help="write champion params into player_valuation.py")
    p_ap.add_argument("--dry-run", action="store_true")
    p_ap.set_defaults(fn=cmd_apply)

    args = ap.parse_args()
    if getattr(args, "cmd", None) == "evaluate" and not args.champion:
        if args.c is None or args.s is None:
            ap.error("evaluate requires --c and --s, or --champion")
    try:
        return int(args.fn(args))
    except RegistryError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
