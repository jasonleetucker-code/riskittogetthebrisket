#!/usr/bin/env python3
"""Prospective weekly IDP study — EVALUATE a final week (SHADOW ONLY).

Preregistration: docs/projections/IDP_OPPORTUNITY_PROSPECTIVE_PREREGISTRATION_2026-11-01.md

    evaluate --week W   score PROV + the five in-package models on final week W exactly as
                        preregistered; refuses a week without a pre-kickoff receipt, that
                        is not final, or whose frozen / code blobs differ from the receipt
                        (unless --allow-deviation, which only LABELS the output)

Deliberately a separate script: ``scripts/idp_opportunity_prospective.py`` is a code blob
pinned by every freeze receipt and must stay byte-identical.  Its helpers are imported,
never copied.  Logic: ``src/ros/idp_opportunity/prospective_eval.py``.

Changes no value, rank, vote, flag or route.  Exit codes: 0 ok; 2 refused; 1 unexpected.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.ros.idp_opportunity import EVIDENCE_TYPE  # noqa: E402
from src.ros.idp_opportunity import sources as S  # noqa: E402
from src.ros.idp_opportunity.prospective import FrozenParams, predict_week  # noqa: E402


def _frozen_script():
    spec = importlib.util.spec_from_file_location(
        "_idp_prospective_frozen", ROOT / "scripts" / "idp_opportunity_prospective.py"
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


_P = _frozen_script()
PREREG = _P.PREREG
OUT_DIR = _P.OUT_DIR
FROZEN = _P.FROZEN
SEASON = _P.SEASON
FIRST_EVAL_WEEK = _P.FIRST_EVAL_WEEK
_backtest_helpers = _P._backtest_helpers
_git = _P._git
_load = _P._load
_card = _P._card


def _blob(path: str) -> str | None:
    return _git("hash-object", path) if (ROOT / path).is_file() else None


def _added_at(path: str) -> str | None:
    """Committer time of the commit that ADDED ``path`` (earliest), or None."""
    lines = (_git("log", "--diff-filter=A", "--format=%cI", "--", path) or "").splitlines()
    return lines[-1] if lines else None


def _last_modified_at(path: str) -> str | None:
    """Committer time of the LATEST commit that touched ``path``, or None."""
    return (_git("log", "-1", "--format=%cI", "--", path) or "").strip() or None


def cmd_evaluate(args: argparse.Namespace) -> int:
    """Score the six models on a final week exactly as preregistered (DESCRIPTIVE per week)."""
    from src.public_league.metrics import host_lineups_open_from_week
    from src.public_league.sleeper_client import fetch_nfl_state
    from src.public_league.snapshot import SeasonSnapshot
    from src.ros import weekly_projection_archive as arch
    from src.ros.idp_opportunity.prospective_eval import (
        GitFacts,
        evaluate_week,
        select_prov,
        team_kickoffs,
        verify_gate,
    )
    from src.ros.sleeper_weekly_projections import CENSUS_SOURCE_KEY

    week = args.week
    bt = _backtest_helpers()
    frozen = json.loads((ROOT / FROZEN).read_text(encoding="utf-8"))
    fp = FrozenParams.from_dict(frozen["params"])
    card, card_rec = _card(args, bt)
    rel_receipt = (OUT_DIR / "freeze_receipts" / f"week{week:02d}.json").as_posix()
    receipt = (
        json.loads((ROOT / rel_receipt).read_text(encoding="utf-8"))
        if (ROOT / rel_receipt).is_file()
        else None
    )
    data, inputs, games = _load(args, week)
    if week not in data.stats:
        print(f"refused: week {week} outcomes unavailable (never treated as zero)", file=sys.stderr)
        return 2
    cache = Path(args.cache_dir)
    games_csv, _ = S.cached_download(
        f"{S.NFLVERSE_RELEASE_BASE}/schedules/games.csv", cache, "games.csv", refresh=False
    )
    kick = team_kickoffs(games_csv, SEASON).get(week, {}) if games_csv else {}
    league_path, league_hash = S.cached_download(
        f"https://api.sleeper.app/v1/league/{args.league_id}",
        cache,
        f"sleeper_league_{args.league_id}.json",
        refresh=True,
    )
    league = json.loads(league_path.read_text(encoding="utf-8")) if league_path else {}
    if args.nfl_state_json:
        nfl_state = json.loads(Path(args.nfl_state_json).read_text(encoding="utf-8"))
    else:
        nfl_state = fetch_nfl_state()
    snap = SeasonSnapshot(
        season=str(SEASON),
        league_id="",
        league=league,
        users=[],
        rosters=[],
        matchups_by_week={},
        transactions_by_week={},
        drafts=[],
        draft_picks_by_draft={},
        traded_picks=[],
        winners_bracket=[],
        losers_bracket=[],
    )
    # finality owner: scoring finished (every game has a result) AND the host has awarded
    # the week's lineups (host_lineups_open_from_week); an unknown answer fails closed
    open_from, fin_reason = host_lineups_open_from_week(snap, nfl_state)
    scoring_done = week in games["finalWeeks"]
    host_done = fin_reason is None or (open_from is not None and week < open_from)
    script_rel = "scripts/idp_opportunity_prospective.py"
    code_paths = (
        "src/ros/idp_opportunity/prospective.py",
        "src/ros/idp_opportunity/model.py",
        script_rel,
    )
    facts = GitFacts(
        receipt_commit_iso=_added_at(rel_receipt),
        receipt_last_commit_iso=_last_modified_at(rel_receipt),
        receipt_clean=receipt is not None
        and _git("ls-files", "--error-unmatch", rel_receipt) is not None
        and not _git("status", "--porcelain", "--", rel_receipt),
        frozen_blob_now=_blob(FROZEN.as_posix()),
        code_blobs_now={p: _blob(p) for p in code_paths},
        frozen_params_path_clean=not _git("status", "--porcelain", "--", FROZEN.as_posix()),
    )
    gate = verify_gate(
        week=week,
        receipt=receipt,
        frozen=frozen,
        card_fingerprint=card_rec["fingerprint"],
        first_kickoff=games["firstKickoffUtc"].get(week),
        week_final=bool(scoring_done and host_done),
        finality_reason=fin_reason if scoring_done else "games_incomplete",
        git=facts,
        retrospective=args.retrospective,
        allow_deviation=args.allow_deviation,
    )
    if not gate.ok:
        print("refused: " + "; ".join(sorted(gate.refusals)), file=sys.stderr)
        return 2

    # in-package predictions: the committed pre-kickoff file when it is provably
    # pre-kickoff and pinned to the frozen blob, else regenerated deterministically
    pred_rel = (OUT_DIR / "predictions" / f"week{week:02d}.json").as_posix()
    committed = None
    first_ko = games["firstKickoffUtc"].get(week)
    if (ROOT / pred_rel).is_file() and not args.retrospective:
        obj = json.loads((ROOT / pred_rel).read_text(encoding="utf-8"))
        at = _added_at(pred_rel)
        if (
            at
            and first_ko
            and datetime.fromisoformat(at) < first_ko
            and obj.get("frozenParamsBlob") == facts.frozen_blob_now
            and not _git("status", "--porcelain", "--", pred_rel)
        ):
            committed = obj
    if committed is not None:
        pred_rows, pred_path_used = committed["rows"], "committed_predictions"
    else:
        pred_rows, pred_path_used = predict_week(data, card, fp, week), "regenerated_from_frozen"
    root = Path(args.archive_root) if args.archive_root else arch.ARCHIVE_ROOT
    caps, unreadable, cap_hashes = [], 0, []
    for rec in arch.list_captures(SEASON, week, source_key=CENSUS_SOURCE_KEY, base_dir=root):
        if not rec.readable:
            unreadable += 1
            continue
        caps.append((rec.fetched_at, arch.load_capture(rec.path).get("rows") or []))
        cap_hashes.append({"fetchedAt": rec.fetched_at, "sha256": rec.content_sha256})
    prov = select_prov(
        caps,
        season=SEASON,
        week=week,
        kickoff_by_team=kick,
        card_settings=card.settings,
        unreadable=unreadable,
    )
    dec_inputs, dec_hash = None, None
    if args.decision_inputs:
        raw = Path(args.decision_inputs).read_bytes()
        dec_inputs, dec_hash = json.loads(raw.decode("utf-8")), hashlib.sha256(raw).hexdigest()
    result = evaluate_week(
        data=data,
        card=card,
        frozen=frozen,
        week=week,
        prediction_rows=pred_rows,
        prov=prov,
        decision_inputs=dec_inputs,
    )
    if args.retrospective:
        label = "RETROSPECTIVE_NOT_PROSPECTIVE: not a preregistered evaluation week"
    elif gate.deviations:
        label = "DEVIATION: preregistered receipt/blob checks overridden"
    else:
        label = "PROSPECTIVE"
    out_obj = {
        "evaluation": "idp_opportunity_prospective_week",
        "label": label,
        "evidenceType": EVIDENCE_TYPE,
        "shadowOnly": True,
        "preregistration": PREREG,
        "season": SEASON,
        "gate": gate.to_dict(),
        "predictionPath": pred_path_used,
        "predictionPathLimitation": None
        if pred_path_used == "committed_predictions"
        else "regenerated: stat corrections to weeks < W landing after W's kickoff would be "
        "inside the features",
        "receipt": {"path": rel_receipt, "blob": _blob(rel_receipt)} if receipt else None,
        "frozenParamsBlob": facts.frozen_blob_now,
        "codeBlobs": {
            **facts.code_blobs_now,
            "src/ros/idp_opportunity/prospective_eval.py": _blob(
                "src/ros/idp_opportunity/prospective_eval.py"
            ),
            "src/ros/idp_opportunity/evaluate.py": _blob("src/ros/idp_opportunity/evaluate.py"),
        },
        "card": card_rec,
        "inputs": {**inputs, "sleeperLeague": league_hash, "decisionInputsSha256": dec_hash},
        "provCaptures": cap_hashes,
        "result": result,
    }
    name = f"retrospective_week{week:02d}.json" if args.retrospective else f"week{week:02d}.json"
    out = ROOT / OUT_DIR / "evaluations" / name
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(out_obj, indent=1, sort_keys=True, default=str) + "\n", encoding="utf-8"
    )
    print(f"wrote {out} ({label})")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("command", choices=("evaluate",))
    ap.add_argument("--week", type=int, default=FIRST_EVAL_WEEK)
    ap.add_argument("--cache-dir", default=str(ROOT / "data" / "cache" / "idp_opportunity"))
    ap.add_argument("--scoring-card", default=None)
    ap.add_argument("--league-id", default="1312006700437352448")
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--allow-deviation", action="store_true", help="label, not hide")
    ap.add_argument(
        "--retrospective",
        action="store_true",
        help="evaluate a week < 9 as a labelled NON-prospective demonstration",
    )
    ap.add_argument("--archive-root", default=None)
    ap.add_argument("--nfl-state-json", default=None)
    ap.add_argument("--decision-inputs", default=None)
    args = ap.parse_args(argv)
    if args.retrospective:
        if not 2 <= args.week < FIRST_EVAL_WEEK:
            print("refused: --retrospective is for weeks 2..8 only", file=sys.stderr)
            return 2
    elif args.week < FIRST_EVAL_WEEK:
        print("refused: evaluation weeks start at 9", file=sys.stderr)
        return 2
    return cmd_evaluate(args)


if __name__ == "__main__":
    sys.exit(main())
