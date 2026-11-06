#!/usr/bin/env python3
"""Prospective weekly IDP opportunity study — freeze, receipt, predict (SHADOW ONLY).

Preregistration: docs/projections/IDP_OPPORTUNITY_PROSPECTIVE_PREREGISTRATION_2026-11-01.md

    freeze            fit every in-package parameter ONCE on 2026 weeks <= 8 that are
                      final now, and write the frozen-parameter artifact
    receipt --week W  write the week-W freeze receipt naming the frozen artifact's
                      git blob and freeze commit (run AFTER the artifact is committed)
    predict --week W  apply the frozen parameters to week W (features from weeks < W
                      only) and write the pre-kickoff prediction file; never refits
    evaluate --week W score the six models on the final week W exactly as preregistered;
                      refuses a week without a pre-kickoff receipt or that is not final

Changes no value, rank, vote, flag or route.  Exit codes: 0 ok; 2 refused (missing
data, unresolved lineup demand, artifact not committed); 1 unexpected error.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.ros.idp_opportunity import EVIDENCE_TYPE  # noqa: E402
from src.ros.idp_opportunity import sources as S  # noqa: E402
from src.ros.idp_opportunity.model import Card  # noqa: E402
from src.ros.idp_opportunity.prospective import (  # noqa: E402
    PROSPECTIVE_MODELS,
    FrozenParams,
    fit_frozen,
    predict_week,
)

PREREG = "docs/projections/IDP_OPPORTUNITY_PROSPECTIVE_PREREGISTRATION_2026-11-01.md"
OUT_DIR = Path("docs/projections/evidence/idp_opportunity/prospective")
FROZEN = OUT_DIR / "frozen_params_2026.json"
SEASON = 2026
FIRST_EVAL_WEEK = 9
FIRST_FIT_WEEK = 2


def _backtest_helpers() -> Any:
    """Reuse the retrospective script's card / lineup-demand / provenance helpers."""
    spec = importlib.util.spec_from_file_location(
        "_idp_bt", ROOT / "scripts" / "idp_opportunity_backtest.py"
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _git(*a: str) -> str | None:
    try:
        return subprocess.run(
            ["git", *a], cwd=ROOT, capture_output=True, text=True, check=True, encoding="utf-8"
        ).stdout.strip()
    except Exception:  # noqa: BLE001
        return None


def _load(args: argparse.Namespace, through_week: int) -> tuple[Any, dict[str, Any], Any]:
    """SeasonData with Sleeper weeks 1..through_week, plus an input-hash report."""
    cache = Path(args.cache_dir)
    base = S.NFLVERSE_RELEASE_BASE
    report: dict[str, Any] = {}
    players_csv, report["nflverse_players"] = S.cached_download(
        f"{base}/players/players.csv", cache, "players.csv", refresh=args.refresh
    )
    games_csv, report["nflverse_games"] = S.cached_download(
        f"{base}/schedules/games.csv", cache, "games.csv", refresh=args.refresh
    )
    sleeper_players, report["sleeper_players"] = S.load_sleeper_players(cache, refresh=args.refresh)
    paths = {}
    for key, path in (
        ("stats_player_week", f"stats_player/stats_player_week_{SEASON}.csv"),
        ("roster", f"rosters/roster_{SEASON}.csv"),
    ):
        p, h = S.cached_download(
            f"{base}/{path}", cache, path.replace("/", "__"), refresh=args.refresh
        )
        paths[key], report[key] = p, h
    if None in (players_csv, games_csv) or not sleeper_players or None in paths.values():
        raise SystemExit(2)
    games = S.parse_games(games_csv, SEASON)
    weeks = list(range(1, through_week + 1))
    sleeper_weeks, srep = S.load_sleeper_weeks(SEASON, weeks, cache, refresh=args.refresh)
    team_of, trep = S.load_sleeper_team_weeks(SEASON, weeks, cache, refresh=args.refresh)
    report["sleeperStats"] = srep
    report["sleeperTeamStats"] = trep
    _, offense = S.parse_stats_player_week(paths["stats_player_week"], SEASON)
    data, census = S.build_season(
        SEASON,
        sleeper_weeks,
        sleeper_players,
        S.parse_players_csv(players_csv),
        S.parse_roster_crosswalk(paths["roster"]),
        team_of,
        offense,
        games["schedule"],
        {},  # injury report NOT used: the replacement term is dropped (prereg §2)
    )
    report["identityCensus"] = census
    return data, report, games


def _card(args: argparse.Namespace, bt: Any) -> tuple[Card, dict[str, Any]]:
    from src.league_comparison.sleeper_scoring import scoring_fingerprint

    settings, source = bt._load_card(args)
    return Card.from_settings(settings), {
        "source": source,
        "fingerprint": scoring_fingerprint(settings),
        "settingsSha256": hashlib.sha256(
            json.dumps(settings, sort_keys=True).encode("utf-8")
        ).hexdigest(),
    }


def cmd_freeze(args: argparse.Namespace) -> int:
    bt = _backtest_helpers()
    cache = Path(args.cache_dir)
    try:
        top_n, demand = bt._resolve_top_n(args, cache)
    except bt.DemandRefused as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    card, card_rec = _card(args, bt)
    _, _, games = _load(args, 1)
    fit_weeks = [w for w in games["finalWeeks"] if FIRST_FIT_WEEK <= w < FIRST_EVAL_WEEK]
    if not fit_weeks:
        print("refused: no final fit weeks", file=sys.stderr)
        return 2
    data, inputs, _ = _load(args, max(fit_weeks))
    fp, diag = fit_frozen(data, card, fit_weeks)
    artifact = {
        "artifact": "idp_opportunity_prospective_frozen_params",
        "evidenceType": EVIDENCE_TYPE,
        "shadowOnly": True,
        "preregistration": PREREG,
        "season": SEASON,
        "firstEvaluationWeek": FIRST_EVAL_WEEK,
        "frozenAtUtc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        **bt._code_provenance(),
        "card": card_rec,
        "lineupDemand": {**demand, "topN": top_n},
        "models": list(PROSPECTIVE_MODELS),
        "providerChampion": "Sleeper/RotoWire, scored from the pre-kickoff archive by the "
        "evaluation runner (not fitted, not in this artifact)",
        "params": fp.to_dict(),
        "fit": diag,
        "excluded": {
            "injuryReplacementTerm": "dropped (hurt in the retrospective study)",
            "week8": "not final at freeze time" if 8 not in fit_weeks else "included",
        },
        "inputs": inputs,
    }
    out = ROOT / FROZEN
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(artifact, indent=1, sort_keys=True, default=str) + "\n", encoding="utf-8"
    )
    print(f"wrote {out} (fit weeks {fit_weeks})")
    return 0


def cmd_receipt(args: argparse.Namespace) -> int:
    rel = FROZEN.as_posix()
    blob = _git("rev-parse", f"HEAD:{rel}")
    commit = _git("log", "-1", "--format=%H", "--", rel)
    if not blob or not commit or _git("status", "--porcelain", "--", rel):
        print("refused: frozen artifact is not committed clean", file=sys.stderr)
        return 2
    frozen = json.loads((ROOT / FROZEN).read_text(encoding="utf-8"))
    receipt = {
        "receipt": "idp_opportunity_prospective_freeze",
        "week": args.week,
        "season": SEASON,
        "preregistration": PREREG,
        "frozenParams": {"path": rel, "blob": blob, "freezeCommit": commit},
        "cardFingerprint": frozen["card"]["fingerprint"],
        "lineupTopN": frozen["lineupDemand"]["topN"],
        "fitWeeks": frozen["fit"]["fitWeeks"],
        "code": {
            "baseCommit": _git("rev-parse", "HEAD"),
            "src/ros/idp_opportunity/prospective.py": _git(
                "rev-parse", "HEAD:src/ros/idp_opportunity/prospective.py"
            ),
            "src/ros/idp_opportunity/model.py": _git(
                "rev-parse", "HEAD:src/ros/idp_opportunity/model.py"
            ),
            "scripts/idp_opportunity_prospective.py": _git(
                "rev-parse", "HEAD:scripts/idp_opportunity_prospective.py"
            ),
        },
        "providerChampionRule": "latest data/projections/weekly_archive capture strictly before "
        "each player's own game kickoff; no such row -> excluded and counted, never 0",
        "refit": False,
        "evidenceOfTime": "push time on GitHub (and PR timeline) must precede the week's first "
        "kickoff; committer date alone is not proof",
    }
    out = ROOT / OUT_DIR / "freeze_receipts" / f"week{args.week:02d}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(receipt, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {out}")
    return 0


def cmd_predict(args: argparse.Namespace) -> int:
    bt = _backtest_helpers()
    frozen = json.loads((ROOT / FROZEN).read_text(encoding="utf-8"))
    fp = FrozenParams.from_dict(frozen["params"])
    card, card_rec = _card(args, bt)
    if card_rec["fingerprint"] != frozen["card"]["fingerprint"]:
        print("refused: scoring card differs from the frozen card", file=sys.stderr)
        return 2
    data, inputs, games = _load(args, args.week - 1)
    missing = [w for w in range(1, args.week) if w not in data.stats]
    if missing:
        print(f"refused: weeks {missing} unavailable (never treated as zero)", file=sys.stderr)
        return 2
    preds = predict_week(data, card, fp, args.week)
    out_obj = {
        "predictions": "idp_opportunity_prospective",
        "week": args.week,
        "season": SEASON,
        "generatedAtUtc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "firstKickoffUtc": str(games["firstKickoffUtc"].get(args.week)),
        **bt._code_provenance(),
        "frozenParamsBlob": _git("rev-parse", f"HEAD:{FROZEN.as_posix()}"),
        "inputs": inputs,
        "rows": preds,
    }
    out = ROOT / OUT_DIR / "predictions" / f"week{args.week:02d}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(out_obj, indent=1, sort_keys=True, default=str) + "\n", encoding="utf-8"
    )
    print(f"wrote {out} ({len(preds)} players)")
    return 0


def _blob(path: str) -> str | None:
    return _git("hash-object", path) if (ROOT / path).is_file() else None


def _added_at(path: str) -> str | None:
    """Committer time of the commit that ADDED ``path`` (earliest), or None."""
    lines = (_git("log", "--diff-filter=A", "--format=%cI", "--", path) or "").splitlines()
    return lines[-1] if lines else None


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
    pinned = ((receipt or {}).get("code") or {}).get(script_rel)
    code_paths = (
        "src/ros/idp_opportunity/prospective.py",
        "src/ros/idp_opportunity/model.py",
        script_rel,
    )
    facts = GitFacts(
        receipt_commit_iso=_added_at(rel_receipt),
        receipt_clean=receipt is not None
        and _git("ls-files", "--error-unmatch", rel_receipt) is not None
        and not _git("status", "--porcelain", "--", rel_receipt),
        frozen_blob_now=_blob(FROZEN.as_posix()),
        code_blobs_now={p: _blob(p) for p in code_paths},
        old_script_source=_git("cat-file", "blob", pinned) if pinned else None,
        new_script_source=(ROOT / script_rel).read_text(encoding="utf-8"),
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
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("command", choices=("freeze", "receipt", "predict", "evaluate"))
    ap.add_argument("--week", type=int, default=FIRST_EVAL_WEEK)
    ap.add_argument("--cache-dir", default=str(ROOT / "data" / "cache" / "idp_opportunity"))
    ap.add_argument("--scoring-card", default=None)
    ap.add_argument("--league-id", default="1312006700437352448")
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--allow-deviation", action="store_true", help="evaluate: label, not hide")
    ap.add_argument(
        "--retrospective",
        action="store_true",
        help="evaluate a week < 9 as a labelled NON-prospective demonstration",
    )
    ap.add_argument("--archive-root", default=None)
    ap.add_argument("--nfl-state-json", default=None)
    ap.add_argument("--decision-inputs", default=None)
    args = ap.parse_args(argv)
    if args.command == "evaluate" and args.retrospective:
        if not 2 <= args.week < FIRST_EVAL_WEEK:
            print("refused: --retrospective is for weeks 2..8 only", file=sys.stderr)
            return 2
    elif args.command != "freeze" and args.week < FIRST_EVAL_WEEK:
        print("refused: evaluation weeks start at 9", file=sys.stderr)
        return 2
    return {
        "freeze": cmd_freeze,
        "receipt": cmd_receipt,
        "predict": cmd_predict,
        "evaluate": cmd_evaluate,
    }[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
