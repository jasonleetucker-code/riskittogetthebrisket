#!/usr/bin/env python3
"""Prospective weekly IDP opportunity study — freeze, receipt, predict (SHADOW ONLY).

Preregistration: docs/projections/IDP_OPPORTUNITY_PROSPECTIVE_PREREGISTRATION_2026-11-01.md

    freeze            fit every in-package parameter ONCE on 2026 weeks <= 8 that are
                      final now, and write the frozen-parameter artifact
    receipt --week W  write the week-W freeze receipt naming the frozen artifact's
                      git blob and freeze commit (run AFTER the artifact is committed)
    predict --week W  apply the frozen parameters to week W (features from weeks < W
                      only) and write the pre-kickoff prediction file; never refits

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


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("command", choices=("freeze", "receipt", "predict"))
    ap.add_argument("--week", type=int, default=FIRST_EVAL_WEEK)
    ap.add_argument("--cache-dir", default=str(ROOT / "data" / "cache" / "idp_opportunity"))
    ap.add_argument("--scoring-card", default=None)
    ap.add_argument("--league-id", default="1312006700437352448")
    ap.add_argument("--refresh", action="store_true")
    args = ap.parse_args(argv)
    if args.command != "freeze" and args.week < FIRST_EVAL_WEEK:
        print("refused: evaluation weeks start at 9", file=sys.stderr)
        return 2
    return {"freeze": cmd_freeze, "receipt": cmd_receipt, "predict": cmd_predict}[args.command](
        args
    )


if __name__ == "__main__":
    sys.exit(main())
