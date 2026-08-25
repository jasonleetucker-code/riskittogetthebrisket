#!/usr/bin/env python3
"""Weekly Hill refit — produces a CHALLENGER, never a champion.

What this used to do, and why it changed
────────────────────────────────────────
Until 2026-07-26 this script rewrote the eight ``HILL_*_C/S`` constants
in ``src/canonical/player_valuation.py`` and the pinned deltas in
``tests/canonical/test_ktc_reconciliation.py``, and the workflow
committed both to ``main``, triggering a deploy.  Three independent
defects meant nothing checked the result (ADR-008):

1. ``rebaseline_ktc_reconciliation`` recomputed the guard's expected
   values FROM the new constants, so its residual was zero by
   construction for any curve.
2. KTC is a TRAINING source for the very constants the guard scored,
   so even honest pins would have been training-set validation.
3. The guard is auto-marked ``livedata`` and the workflow ran
   ``pytest -m "not livedata"`` — 13 deselected, 0 run.  It was never
   executed at all.

All three are fixed here, and the fix for (3) is deliberately NOT
"un-mark the guard".  That marking exists because data-coupled
failures once stalled every PR, and it is still correct.  Instead the
refit calls the held-out evaluation DIRECTLY, so the gate cannot be
switched off by a marker policy tuned for a different purpose.

What it does now
────────────────
Fit → challenger → score champion and challenger on boards the fit
never reads → record both in the model registry → report.  This script
no longer writes ``player_valuation.py``, and does not import the
function that can.  Constants move only through
``scripts/model_registry.py promote`` + ``apply``, run by a human.

Exit codes (the workflow branches on these):
    0   champion stands — no drift, or the challenger did not clear
        the promotion margin.  The ordinary weekly outcome.
    1   challenger is PROMOTABLE — a human should review and promote.
    2   error — fit failed, or the gate could not be evaluated.
    3   REGRESSION ALARM — the challenger is far worse than the
        champion, which points at the fit or its inputs.

Usage:
    python3 scripts/auto_refit_hill_curves.py
    python3 scripts/auto_refit_hill_curves.py --dry-run
    python3 scripts/auto_refit_hill_curves.py --threshold 100
    python3 scripts/auto_refit_hill_curves.py --challenger-json c.json
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from src.model_registry.hill_masters import (  # noqa: E402
    CONSTANT_NAMES,
    MODEL_ID,
    VALIDATED_PARAMS,
    git_sha,
    load_or_seed_registry,
    read_committed_constants,
    training_input_paths,
)
from src.model_registry.holdout import HoldoutError, evaluate_offense_master  # noqa: E402
from src.model_registry.promotion import decide_promotion  # noqa: E402
from src.model_registry.versioning import (  # noqa: E402
    ModelVersion,
    RegistryError,
    fingerprint_inputs,
)

FIT_SCRIPT = REPO / "scripts" / "fit_hill_curve_percentile.py"

SCOPE_TO_CS = {
    "GLOBAL": ("HILL_GLOBAL_PERCENTILE_C", "HILL_GLOBAL_PERCENTILE_S"),
    "OFFENSE": ("HILL_PERCENTILE_C", "HILL_PERCENTILE_S"),
    "IDP": ("IDP_HILL_PERCENTILE_C", "IDP_HILL_PERCENTILE_S"),
    "ROOKIE": ("HILL_ROOKIE_PERCENTILE_C", "HILL_ROOKIE_PERCENTILE_S"),
}

DRIFT_RMSE_THRESHOLD: float = 50.0
DRIFT_GRID: tuple[float, ...] = (0.01, 0.05, 0.10, 0.20, 0.30, 0.50, 0.70, 0.90)

EXIT_CHAMPION_STANDS = 0
EXIT_PROMOTABLE = 1
EXIT_ERROR = 2
EXIT_ALARM = 3


def _hill(p: float, c: float, s: float) -> float:
    if p <= 0.0:
        return 9999.0
    return 9999.0 / (1.0 + (min(p, 1.0) / c) ** s)


def run_fit_with_json() -> dict[str, float]:
    """Run the fit script and capture its JSON output."""
    with tempfile.NamedTemporaryFile(mode="w+", suffix=".json", delete=False) as tmp:
        json_path = Path(tmp.name)
    try:
        subprocess.run(
            [sys.executable, str(FIT_SCRIPT), "--json-out", str(json_path)],
            capture_output=True,
            text=True,
            cwd=str(REPO),
            check=True,
        )
        return {str(k): float(v) for k, v in json.loads(json_path.read_text()).items()}
    finally:
        json_path.unlink(missing_ok=True)


def compute_scope_drift(committed: dict[str, float], fitted: dict[str, float]) -> dict[str, float]:
    """Per-scope RMSE of V_new(p) - V_old(p) over DRIFT_GRID."""
    out: dict[str, float] = {}
    for scope, (c_name, s_name) in SCOPE_TO_CS.items():
        c_old, s_old = committed[c_name], committed[s_name]
        c_new, s_new = fitted[c_name], fitted[s_name]
        sq = [(_hill(p, c_new, s_new) - _hill(p, c_old, s_old)) ** 2 for p in DRIFT_GRID]
        out[scope] = (sum(sq) / len(sq)) ** 0.5
    return out


def format_drift_report(
    committed: dict[str, float],
    fitted: dict[str, float],
    drift: dict[str, float],
    threshold: float,
) -> str:
    lines = [
        "Hill scope master drift report",
        "=" * 52,
        f"Threshold: {threshold:.1f} RMSE points",
        "",
        f"{'scope':<10}{'c_old':>10}{'c_new':>10}{'s_old':>10}{'s_new':>10}{'RMSE':>10}",
    ]
    for scope, (c_name, s_name) in SCOPE_TO_CS.items():
        marker = " *" if drift[scope] > threshold else ""
        lines.append(
            f"{scope:<10}{committed[c_name]:>10.4f}{fitted[c_name]:>10.4f}"
            f"{committed[s_name]:>10.3f}{fitted[s_name]:>10.3f}{drift[scope]:>10.2f}{marker}"
        )
    top = max(drift.items(), key=lambda kv: kv[1])
    lines += ["", f"Max drift: {top[0]} @ RMSE={top[1]:.2f}"]
    return "\n".join(lines)


def format_holdout(label: str, result) -> str:
    lines = [f"{label}: criterion {result.criterion:.1f}  (mean per-source RMSE, lower is better)"]
    for src, rmse in sorted(result.per_source.items()):
        lines.append(f"    {src:<20}{rmse:>9.1f}   n={result.per_source_rows[src]}")
    for src, why in sorted(result.skipped.items()):
        lines.append(f"    {src:<20}{'skipped':>9}   {why}")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--threshold", type=float, default=DRIFT_RMSE_THRESHOLD)
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="evaluate and report, but do not record the challenger",
    )
    ap.add_argument(
        "--challenger-json",
        type=Path,
        help=(
            "score this parameter set instead of running the fit — used to "
            "exercise the gate against a known-good or known-bad challenger"
        ),
    )
    ap.add_argument(
        "--force",
        action="store_true",
        help="evaluate even when drift is below the threshold",
    )
    args = ap.parse_args()

    # ── the live constants, and the champion of record ─────────────
    try:
        committed = read_committed_constants()
        registry = load_or_seed_registry()
    except (RegistryError, OSError) as exc:
        print(f"ERROR resolving champion: {exc}", file=sys.stderr)
        return EXIT_ERROR
    champion = registry.champion

    # A registry champion that has drifted from what is deployed means
    # someone hand-edited the constants.  Comparing a challenger to a
    # champion that is not live yields a correct-looking verdict about
    # the wrong incumbent.
    if champion.params != committed:
        print(
            f"ERROR: registry champion v{champion.version} does not match the "
            "constants in player_valuation.py. The registry is not describing "
            "what is deployed — reconcile with `scripts/model_registry.py status` "
            "before refitting.",
            file=sys.stderr,
        )
        return EXIT_ERROR

    # ── the challenger ─────────────────────────────────────────────
    if args.challenger_json:
        try:
            raw = json.loads(args.challenger_json.read_text())
            fitted = {str(k): float(v) for k, v in raw.items()}
        except (OSError, ValueError) as exc:
            print(f"ERROR reading --challenger-json: {exc}", file=sys.stderr)
            return EXIT_ERROR
        producer = f"injected via --challenger-json ({args.challenger_json.name})"
    else:
        try:
            fitted = run_fit_with_json()
        except subprocess.CalledProcessError as exc:
            print(f"ERROR running fit:\n{exc.stderr}", file=sys.stderr)
            return EXIT_ERROR
        except Exception as exc:  # noqa: BLE001
            print(f"ERROR running fit: {exc}", file=sys.stderr)
            return EXIT_ERROR
        producer = f"scripts/fit_hill_curve_percentile.py @ {git_sha()}"

    missing = [n for n in CONSTANT_NAMES if n not in fitted]
    if missing:
        print(f"ERROR: challenger is missing {missing}", file=sys.stderr)
        return EXIT_ERROR

    drift = compute_scope_drift(committed, fitted)
    print(format_drift_report(committed, fitted, drift, args.threshold))

    if max(drift.values()) <= args.threshold and not args.force:
        print("\nNo drift beyond threshold — champion stands, nothing to validate.")
        return EXIT_CHAMPION_STANDS

    # ── the gate ───────────────────────────────────────────────────
    # Evaluated HERE, not through pytest.  The guard that used to live
    # in the test suite was auto-marked livedata and deselected by the
    # workflow's own filter; a gate that depends on a marker policy is
    # a gate a marker policy can silently switch off.
    print("\n" + "=" * 52)
    print("Held-out validation — boards the fit never reads")
    print("=" * 52)
    try:
        champ_eval = evaluate_offense_master(*(champion.params[k] for k in VALIDATED_PARAMS))
        chal_eval = evaluate_offense_master(*(fitted[k] for k in VALIDATED_PARAMS))
    except HoldoutError as exc:
        print(f"ERROR: the gate could not be evaluated: {exc}", file=sys.stderr)
        print("Refusing to treat an unevaluable gate as a pass.", file=sys.stderr)
        return EXIT_ERROR

    print(format_holdout(f"champion v{champion.version}", champ_eval))
    print(format_holdout("challenger", chal_eval))

    decision = decide_promotion(champ_eval.criterion, chal_eval.criterion)
    print(f"\nverdict: {'PROMOTABLE' if decision.promote else 'REJECTED'}")
    print(f"reason:  {decision.reason}")
    print(
        f"\nNOTE: only {VALIDATED_PARAMS[0]} / {VALIDATED_PARAMS[1]} (the OFFENSE "
        "master) are validated out of sample. The other six constants are "
        "versioned but not gated — see ADR-008."
    )

    # ── record it, whatever the verdict ────────────────────────────
    recorded: int | None = None
    if args.dry_run:
        print("\nDry-run — challenger not recorded.")
    else:
        try:
            recorded = registry.next_version()
            registry.add(
                ModelVersion(
                    model_id=MODEL_ID,
                    version=recorded,
                    params=fitted,
                    fitted_at=datetime.now(timezone.utc).isoformat(),
                    producer=producer,
                    status="challenger",
                    training_inputs=fingerprint_inputs(training_input_paths()),
                    holdout=chal_eval.to_dict(),
                )
            )
            if not decision.promote:
                registry.reject(recorded, reason=decision.reason)
            registry.save()
            print(f"\nRecorded challenger v{recorded} in the registry.")
        except RegistryError as exc:
            print(f"ERROR recording challenger: {exc}", file=sys.stderr)
            return EXIT_ERROR

    if decision.alarm:
        print(
            "\nALARM: the challenger is far worse than the champion. That is a "
            "signal about the fit or its inputs, not about the curve — check for "
            "a collapsed or stale source before refitting.",
            file=sys.stderr,
        )
        return EXIT_ALARM

    if decision.promote:
        target = recorded if recorded is not None else "<version>"
        print(
            "\nA human must promote it — this script cannot. To land it:\n"
            "  python3 scripts/model_registry.py evaluate --champion --record\n"
            f"  python3 scripts/model_registry.py validate {target}\n"
            f'  python3 scripts/model_registry.py promote {target} --reason "held-out win"\n'
            "  python3 scripts/model_registry.py apply\n"
            "  # then run the suite and open a PR\n"
            "\n"
            "  # NOTE: `promote` runs the per-scope evidence gate and will REFUSE\n"
            "  # if this challenger moved GLOBAL or IDP — the held-out criterion\n"
            "  # above scores OFFENSE only. That is not a bug in the refit; it is\n"
            "  # the criterion's scope being stated. Measure the board effect with\n"
            "  # scripts/measure_hill_version_board.py before deciding whether to\n"
            "  # accept the risk with --override-scope + --override-reason."
        )
        return EXIT_PROMOTABLE

    print("\nChampion stands.")
    return EXIT_CHAMPION_STANDS


if __name__ == "__main__":
    raise SystemExit(main())
