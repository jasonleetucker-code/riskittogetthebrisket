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
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from src.model_registry.hill_masters import (  # noqa: E402
    CONSTANT_NAMES,
    MODEL_ID,
    PLAYER_VALUATION,
    VALIDATED_PARAMS,
    git_sha as _git_sha,
    load_or_seed_registry as _load_or_seed,
    read_committed_constants,
    training_input_paths as _training_input_paths,
    write_committed_constants,
)
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

    # SCORE BOTH CURVES FRESH, ON ONE SNAPSHOT.
    #
    # This used to read the two STORED criteria and hand them straight to
    # ``decide_promotion``.  ``promotion.py``'s module docstring says the
    # comparison must be made on ONE snapshot with both curves scored
    # against it, because the criterion's absolute level drifts with the
    # market while the paired delta does not.  Stored scores are stamped
    # whenever someone last ran ``evaluate --record``; a challenger's is
    # stamped at ``register`` time.  Those dates coincide only by luck.
    #
    # Measured 2026-08-05 on the live registry, margin 25.0:
    #
    #   stored vs stored (what this did)   +12.79  REJECT (right, by luck)
    #   both scored fresh (correct)        +22.44  REJECT
    #   champion re-recorded only          +31.91  PROMOTE  <- WRONG
    #
    # That third row is the trap: "just re-record the champion" looks
    # like a data fix and is the one action that produces a false
    # PROMOTE, because refreshing only the staler side inflates the gap
    # by exactly the drift removed.  The champion's stored score was 7
    # days old, the challenger's 1.
    #
    # This matters more than an advisory CLI normally would.  It used to
    # matter absolutely: ``cmd_promote`` had NO gate of any kind, so this
    # verdict was the only thing between a human and ``promote`` +
    # ``apply``.  ``ModelRegistry.promote`` now runs the per-scope gate
    # (``src/model_registry/scope_validation.py``) and refuses a changed
    # routed scope with no evidence of its own.  That gate and this
    # verdict answer DIFFERENT questions and neither replaces the other:
    # the gate asks "was each scope that moved scored by something?" and
    # this asks "did the OFFENSE curve actually beat the incumbent, on
    # scores measured at the same time?".  A challenger can pass the gate
    # and lose here, and vice versa.
    #
    # ``auto_refit_hill_curves.py`` already did it correctly
    # (both fresh, then decide) — two code paths, one contract, one of
    # them wrong.  This is now the same path.
    try:
        champ_eval = evaluate_offense_master(*(champ.params[k] for k in VALIDATED_PARAMS))
        chal_eval = evaluate_offense_master(*(challenger.params[k] for k in VALIDATED_PARAMS))
    except (HoldoutError, KeyError) as exc:
        print(f"ERROR: the gate could not be evaluated: {exc}", file=sys.stderr)
        print("Refusing to treat an unevaluable gate as a pass.", file=sys.stderr)
        return 2

    champ_crit = champ_eval.criterion
    chal_crit = chal_eval.criterion

    decision = decide_promotion(champ_crit, chal_crit)
    print(f"champion   v{champ.version}: {champ_crit:.4f}  (scored now)")
    print(f"challenger v{challenger.version}: {chal_crit:.4f}  (scored now)")

    # Show the stored figures alongside rather than silently correcting
    # them, so a stale registry is visible instead of merely bypassed.
    for label, ver, fresh in (
        ("champion", champ, champ_crit),
        ("challenger", challenger, chal_crit),
    ):
        stored = (ver.holdout or {}).get("criterion")
        if isinstance(stored, (int, float)) and abs(stored - fresh) > 0.05:
            when = (ver.holdout or {}).get("measuredAt") or "date not recorded"
            print(
                f"  note: {label} v{ver.version} has a STORED criterion of {stored:.4f} "
                f"({when}), {fresh - stored:+.4f} from today's. The verdict above uses "
                f"today's; run `evaluate --champion --record` to refresh the file."
            )

    print(f"verdict: {'PROMOTE' if decision.promote else 'REJECT'} — {decision.reason}")
    if decision.alarm:
        print("ALARM: regression large enough to suspect the fit or its inputs.")
    return 0 if decision.promote else 1


def cmd_promote(args: argparse.Namespace) -> int:
    """Promote a challenger, subject to the per-scope evidence gate.

    ``--override-scope`` is the owner escape hatch the gate documents:
    GLOBAL and IDP may never get an external holdout, and a permanently
    unpromotable model is its own failure mode.  It requires
    ``--override-reason`` for the same purpose ``--reason`` is required —
    an unrecorded exception is indistinguishable from an accident — and
    the recorded state says ``OVERRIDDEN_BY_OWNER``, never a
    ``VALIDATED_*`` one.  A decision is not a measurement.
    """
    reg = _load_or_seed()
    try:
        champ = reg.promote(
            args.version,
            reason=args.reason,
            override_scopes=args.override_scope or (),
            override_reason=args.override_reason or "",
        )
    except RegistryError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    reg.save()
    print(f"champion is now v{champ.version}")
    for scope in sorted(champ.scope_validation):
        print(f"  {scope}: {champ.scope_validation[scope]}")
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
    p_pro.add_argument(
        "--override-scope",
        action="append",
        metavar="SCOPE",
        help="accept a changed routed scope that has no evidence of its own "
        "(repeatable); requires --override-reason",
    )
    p_pro.add_argument(
        "--override-reason",
        default="",
        help="why the owner accepts the overridden scopes' risk",
    )
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
