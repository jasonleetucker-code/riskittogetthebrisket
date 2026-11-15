#!/usr/bin/env python3
"""Draft valuation Batch D operator CLI — evaluate, diagnose, roll back, resume.

Owner decision 12 (2026-10-18); policy ``config/draft_valuation/promotion_policy.json``
(preregistered thresholds, ``promotionMode`` dry_run | live).  ``dynasty_main`` only.

Subcommands::

    evaluate  [--league dynasty_main] [--year Y] [--export FILE | --contract FILE]
              [--observed-nfl-season S] [--alerts-out FILE] [--no-persist] [--skip-ledger]
        One scheduled readiness evaluation (run by scheduled-refresh.yml after
        each fresh build).  Year defaults to the league's upcoming rookie draft
        (``pick_lifecycle.league_draft_years``).  Before the class window opens
        no contract is built and no candidate exists.  Records go to the
        repo-tracked ``config/draft_valuation/`` stores; every NEW state
        transition prints one ``::warning`` annotation and, with
        ``--alerts-out``, one markdown block for the workflow's alert step.
    status    --league L --year Y     operator diagnostic: state, gates, window.
    rollback  --league L --year Y --reason TEXT
        Restore the previous generation and record ROLLED_BACK (held until resume).
    resume    --league L --year Y --reason TEXT
        Clear a rollback hold; automatic promotion may run again.

Exit codes: 0 done (evaluate always exits 0 once it has recorded an outcome,
including ERROR_* states — those are alerts, not crashes); 1 an operator
command was refused; 2 bad input / unexpected failure.
"""

from __future__ import annotations

import argparse
import dataclasses
import glob
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.draft.rookie_auction import promotion  # noqa: E402
from src.draft.rookie_auction.published import GenerationError  # noqa: E402
from src.identity.pick_lifecycle import LeagueDraftEvidence  # noqa: E402


def _now(args) -> datetime:
    if getattr(args, "now", None):
        ts = datetime.fromisoformat(args.now.replace("Z", "+00:00"))
        if ts.tzinfo is None:
            raise SystemExit("--now needs a timezone")
        return ts.astimezone(timezone.utc)
    return datetime.now(timezone.utc)


def _emit_alerts(alerts, alerts_out: str | None) -> None:
    for text in alerts:
        first, _, rest = text.partition("\n")
        body = rest.replace("%", "%25").replace("\r", "").replace("\n", "%0A")
        print(f"::warning title=Draft valuation::{first}%0A{body}", file=sys.stderr)
    if alerts and alerts_out:
        with open(alerts_out, "a", encoding="utf-8") as fh:
            for text in alerts:
                fh.write("```\n" + text + "\n```\n\n")


def _raw_payload(args) -> tuple[dict | None, str | None]:
    if args.contract:
        return None, None
    exports = (
        [args.export]
        if args.export
        else sorted(glob.glob(str(ROOT / "exports/latest/dynasty_data_*.json")))
    )
    if not exports:
        return None, "no export found under exports/latest/"
    try:
        return json.loads(Path(exports[-1]).read_text(encoding="utf-8")), None
    except (OSError, ValueError) as exc:
        return None, f"export unreadable: {exc}"


def _contract(args, raw: dict | None) -> tuple[dict | None, str | None]:
    """The canonical contract, with ``contractHealth`` as the server stamps it."""
    try:
        from src.api.data_contract import (  # noqa: PLC0415
            build_api_data_contract,
            validate_api_data_contract,
        )

        if args.contract:
            contract = json.loads(Path(args.contract).read_text(encoding="utf-8"))
        elif raw is not None:
            contract = build_api_data_contract(raw)
        else:
            return None, "no input"
        if not isinstance(contract.get("contractHealth"), dict):
            report = validate_api_data_contract(contract)
            contract["contractHealth"] = {
                "ok": bool(report.get("ok")),
                "status": report.get("status"),
                "errorCount": int(report.get("errorCount", 0)),
                "warningCount": int(report.get("warningCount", 0)),
                "checkedAt": report.get("checkedAt"),
            }
        return contract, None
    except Exception as exc:  # noqa: BLE001 — becomes ERROR_CONTRACT_UNAVAILABLE
        return None, f"{type(exc).__name__}: {exc}"


def _evidence(sleeper_block, league_key: str) -> LeagueDraftEvidence | None:
    """This league's draft evidence: the scrape's own block, else its snapshot."""
    from src.api import draft_class_evidence as dce  # noqa: PLC0415
    from src.api import league_registry  # noqa: PLC0415

    lid = league_registry.get_sleeper_league_id(league_key)
    if not lid:
        return None
    block = sleeper_block if isinstance(sleeper_block, dict) else {}
    ev = LeagueDraftEvidence.from_dict(block.get(dce.SLEEPER_BLOCK_FIELD))
    if ev is None or ev.sleeper_league_id != str(lid):
        ev = dce.read_snapshot(lid)
    if ev is None:
        return None
    if ev.league_key is None:
        ev = dataclasses.replace(ev, league_key=league_key)
    return ev if ev.league_key == league_key else None


def _observed_season(args) -> int | None:
    if args.observed_nfl_season is not None:
        return int(args.observed_nfl_season)
    try:
        from src.public_league.sleeper_client import fetch_nfl_state  # noqa: PLC0415

        state = fetch_nfl_state() or {}
        return int(state["season"])
    except Exception:  # noqa: BLE001 — unknown stays unknown (never guessed)
        return None


def cmd_evaluate(args) -> int:
    now = _now(args)
    raw, raw_error = _raw_payload(args)
    sleeper = (raw or {}).get("sleeper") if raw else None
    contract = None
    contract_error = raw_error
    if args.contract:
        contract, contract_error = _contract(args, None)
        sleeper = (contract or {}).get("sleeper")
    evidence = _evidence(sleeper, args.league)

    if args.year is not None:
        years = [int(args.year)]
    else:
        from src.api import league_registry  # noqa: PLC0415
        from src.api.draft_class_evidence import league_draft_years_for  # noqa: PLC0415

        ldy = league_draft_years_for(
            league_registry.get_sleeper_league_id(args.league),
            evidence=evidence,
            calendar_year=now.year,
        )
        years = [ldy.upcoming_draft_year]

    try:
        policy = promotion.load_promotion_policy()
    except promotion.PolicyError:
        policy = None
    summary = []
    for year in years:
        window_open = (
            policy is not None and promotion.class_window_gate(policy, year, now).outcome == "PASS"
        )
        if window_open and contract is None and not args.contract and raw is not None:
            contract, contract_error = _contract(args, raw)
        outcome = promotion.run_class_evaluation(
            league_key=args.league,
            draft_year=year,
            contract=contract,
            contract_error=contract_error if window_open else None,
            now=now,
            observed_nfl_season=_observed_season(args) if window_open else None,
            evidence=evidence,
            persist=not args.no_persist,
        )
        _emit_alerts(outcome.alerts, args.alerts_out)
        row = {
            "draftYear": year,
            "state": outcome.evaluation.state,
            "evaluationState": outcome.evaluation.evaluation_state,
            "servingState": outcome.evaluation.serving_state,
            "promotion": outcome.evaluation.promotion,
            "gates": [g.to_dict() for g in outcome.evaluation.gates],
            "reasons": list(outcome.evaluation.reasons),
            "evaluationRecord": str(outcome.evaluation_path) if outcome.evaluation_path else None,
            "newTransition": bool(outcome.transition),
        }
        if not args.skip_ledger:
            row["ledger"] = promotion.finalize_completed_class_step(
                league_key=args.league,
                draft_class=year - 1,
                evidence=evidence,
                live=bool(policy and policy.live and not args.no_persist),
            )
        summary.append(row)
    print(
        json.dumps(
            {"leagueKey": args.league, "now": now.isoformat(), "classes": summary},
            indent=1,
            default=str,
        )
    )
    return 0


def cmd_status(args) -> int:
    print(
        json.dumps(
            promotion.diagnose(args.league, args.year, now=_now(args)), indent=1, default=str
        )
    )
    return 0


def _operator(fn, args) -> int:
    try:
        pointer, alerts = fn(args.league, args.year, now=_now(args), reason=args.reason)
    except (GenerationError, LookupError) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 1
    _emit_alerts(alerts, args.alerts_out)
    print(json.dumps(pointer, indent=1))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    ev = sub.add_parser("evaluate")
    ev.add_argument("--league", default="dynasty_main")
    ev.add_argument("--year", type=int)
    src = ev.add_mutually_exclusive_group()
    src.add_argument("--export")
    src.add_argument("--contract")
    ev.add_argument("--observed-nfl-season", type=int)
    ev.add_argument("--alerts-out")
    ev.add_argument("--no-persist", action="store_true")
    ev.add_argument("--skip-ledger", action="store_true")
    ev.add_argument("--now", help=argparse.SUPPRESS)
    ev.set_defaults(func=cmd_evaluate)

    st = sub.add_parser("status")
    st.add_argument("--league", default="dynasty_main")
    st.add_argument("--year", type=int, required=True)
    st.add_argument("--now", help=argparse.SUPPRESS)
    st.set_defaults(func=cmd_status)

    for name, fn in (
        ("rollback", promotion.operator_rollback),
        ("resume", promotion.operator_resume),
    ):
        p = sub.add_parser(name)
        p.add_argument("--league", default="dynasty_main")
        p.add_argument("--year", type=int, required=True)
        p.add_argument("--reason", required=True)
        p.add_argument("--alerts-out")
        p.add_argument("--now", help=argparse.SUPPRESS)
        p.set_defaults(func=lambda a, fn=fn: _operator(fn, a))

    args = ap.parse_args(argv)
    try:
        return int(args.func(args))
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001
        print(f"draft_valuation: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
