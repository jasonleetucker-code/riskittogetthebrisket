#!/usr/bin/env python3
"""Run the preregistered weekly IDP opportunity challenger backtest (SHADOW ONLY).

Preregistration: docs/projections/IDP_OPPORTUNITY_CHALLENGERS_PREREGISTRATION_2026-11-01.md

Reads public inputs (Sleeper weekly stats + player dump, nflverse CSVs), runs the
expanding-window evaluation in ``src.ros.idp_opportunity`` and writes one evidence
JSON.  Changes no value, rank, vote, flag or route.

Exit codes: 0 = evaluated; 2 = required data unavailable (nothing evaluated);
1 = unexpected error.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.ros.idp_opportunity import EVIDENCE_TYPE  # noqa: E402
from src.ros.idp_opportunity import sources as S  # noqa: E402
from src.ros.idp_opportunity.evaluate import (  # noqa: E402
    bootstrap_delta_mae,
    metrics,
    run_season,
)
from src.ros.idp_opportunity.model import MODELS, Card  # noqa: E402
from src.ros.idp_opportunity.positions import (  # noqa: E402
    CHALLENGER_SUBGROUPS,
    FAMILIES,
    SUBGROUPS,
)

DYNASTY_MAIN_LEAGUE_ID = "1312006700437352448"
DYNASTY_MAIN_LEAGUE_KEY = "dynasty_main"
#: The top-N values WRITTEN in the preregistration (§4).  Historical record only, NOT
#: a demand table: the DL value (24) came from a wrong slot comment ("DL DL IDP_FLEX
#: ..."); dynasty_main starts DL x3 / LB x3 / DB x3 with no IDP_FLEX.  The run derives
#: top-N from the canonical lineup owner and reports the preregistered value beside
#: it as a labelled deviation wherever they differ.
PREREGISTERED_TOP_N = (("DL", 24), ("LB", 36), ("DB", 36))
TOP_N_SUBGROUP = 12
FIRST_EVAL_WEEK = 3
LAST_REG_WEEK_2025 = 17


def _load_card(args: argparse.Namespace) -> tuple[dict[str, Any], str]:
    candidates = [Path(args.scoring_card)] if args.scoring_card else []
    candidates.append(ROOT / "data" / "leagues" / f"scoring_{args.league_id}.json")
    for path in candidates:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            settings = data.get("scoringSettings") or data.get("scoring_settings") or data
            return dict(settings), f"file:{path.name}"
    url = f"https://api.sleeper.app/v1/league/{args.league_id}"
    req = urllib.request.Request(url, headers={"User-Agent": "riskit-research/1.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310
        league = json.loads(resp.read().decode("utf-8"))
    return dict(league.get("scoring_settings") or {}), f"sleeper_api:league/{args.league_id}"


class DemandRefused(RuntimeError):
    """Top-N could not be derived from the canonical lineup owner.  The run stops
    (exit 2); nothing is defaulted."""


def _resolve_top_n(args: argparse.Namespace, cache: Path) -> tuple[dict[str, int], dict[str, Any]]:
    """Top-N per family = dedicated starter slots x team count, through the canonical
    owner, using the LIVE Sleeper ``roster_positions`` (first rung of the ladder)."""
    from src.api.league_registry import get_league_roster_settings
    from src.ros.lineup import resolve_league_slot_demand

    path, h = S.cached_download(
        f"https://api.sleeper.app/v1/league/{args.league_id}",
        cache,
        f"sleeper_league_{args.league_id}.json",
        refresh=True,  # live, never a stale cached copy
    )
    if path is None:
        raise DemandRefused(f"live league fetch failed: {h}")
    league = json.loads(path.read_text(encoding="utf-8"))
    roster_positions = league.get("roster_positions")
    settings = get_league_roster_settings(DYNASTY_MAIN_LEAGUE_KEY)
    demand = resolve_league_slot_demand(roster_positions=roster_positions, roster_settings=settings)
    if not demand.resolved:
        raise DemandRefused("lineup demand unresolved by src.ros.lineup")
    team_count = settings.get("teamCount") if isinstance(settings, dict) else None
    if not isinstance(team_count, int) or team_count <= 0:
        raise DemandRefused(f"team count unavailable: {team_count!r}")
    top_n: dict[str, int] = {}
    for fam in FAMILIES:
        per_team = demand.demand.dedicated.get(fam)
        if per_team is None:
            raise DemandRefused(f"no dedicated {fam} demand resolved")
        top_n[fam] = int(per_team) * team_count
    expected = dict(PREREGISTERED_TOP_N)
    record = {
        "source": demand.source,
        "slots": list(demand.slots),
        "dedicated": {f: demand.demand.dedicated.get(f) for f in FAMILIES},
        "teamCount": team_count,
        "topN": top_n,
        "leagueSha256": h,
        "preregisteredTopN": expected,
        "deviationFamilies": sorted(f for f in FAMILIES if top_n[f] != expected[f]),
    }
    return top_n, record


def _code_provenance() -> dict[str, Any]:
    """Pinned code identity: HEAD SHA plus whether the tree was dirty (CLAUDE.md §3.5)."""
    import subprocess

    def _git(*a: str) -> str | None:
        try:
            return subprocess.run(
                ["git", *a], cwd=ROOT, capture_output=True, text=True, check=True, encoding="utf-8"
            ).stdout.strip()
        except Exception:  # noqa: BLE001
            return None

    status = _git("status", "--porcelain", "--", "src", "scripts", "tests")
    return {
        "codeSha": _git("rev-parse", "HEAD"),
        "codeDirty": None if status is None else bool(status),
    }


def _head(url: str) -> str:
    try:
        req = urllib.request.Request(
            url, method="HEAD", headers={"User-Agent": "riskit-research/1.0"}
        )
        with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310
            return f"http_{resp.status}"
    except Exception as exc:  # noqa: BLE001
        return f"unavailable:{exc}"


def _r(x: Any) -> Any:
    if isinstance(x, float):
        return round(x, 4)
    if isinstance(x, dict):
        return {k: _r(v) for k, v in x.items()}
    if isinstance(x, list):
        return [_r(v) for v in x]
    return x


def _evaluate(preds: list, season: int, resamples: int, top_n: dict[str, int]) -> dict[str, Any]:
    by_model: dict[str, list] = defaultdict(list)
    for p in preds:
        by_model[p.model].append(p)
    out: dict[str, Any] = {
        "families": {},
        "familiesAtPreregisteredTopN": {},
        "subgroups": {},
        "challengers": {},
    }
    prereg = dict(PREREGISTERED_TOP_N)
    for fam in FAMILIES:
        fam_rows = {m: [p for p in by_model[m] if p.family == fam] for m in MODELS}
        out["families"][fam] = {m: metrics(fam_rows[m], top_n[fam]) for m in MODELS}
        if prereg[fam] != top_n[fam]:
            # DEVIATION record: the top-N hit rate at the (wrong) preregistered N
            out["familiesAtPreregisteredTopN"][fam] = {
                m: {
                    "topN": prereg[fam],
                    "topNHitMeanWeekly": metrics(fam_rows[m], prereg[fam])["topNHitMeanWeekly"],
                }
                for m in MODELS
            }
    for sg in SUBGROUPS:
        out["subgroups"][sg] = {
            m: metrics([p for p in by_model[m] if p.subgroup == sg], TOP_N_SUBGROUP) for m in MODELS
        }
    for name, sgs in CHALLENGER_SUBGROUPS:
        rows = {m: [p for p in by_model[m] if p.subgroup in sgs] for m in MODELS}
        boot = {
            m: bootstrap_delta_mae(rows[m], rows["C0"], resamples=resamples)
            for m in MODELS
            if m != "C0"
        }
        # POST-HOC, descriptive only (not preregistered): does the family-specific
        # opportunity layer add anything over snaps / role alone?
        increments = {
            m: bootstrap_delta_mae(rows[m], rows["M2"], resamples=resamples)
            for m in ("M3", "M4", "M5")
        }
        met = {m: metrics(rows[m], TOP_N_SUBGROUP * len(sgs)) for m in MODELS}
        primary = boot["M5"]
        accept = None
        if primary.get("nRows"):
            c0, m5 = met["C0"], met["M5"]
            crit1 = primary["ci98.33"][1] < 0
            crit2 = abs(m5["bias"]) <= abs(c0["bias"]) + 0.5
            sp5, sp0 = m5.get("spearmanMeanWeekly"), c0.get("spearmanMeanWeekly")
            crit3 = sp5 is not None and sp0 is not None and sp5 >= sp0
            accept = {
                "ciUpperBelowZero": crit1,
                "biasNotWorse": crit2,
                "spearmanNotLower": crit3,
                "verdict": "detectable_lift"
                if (crit1 and crit2 and crit3)
                else "no_detectable_lift",
            }
        out["challengers"][name] = {
            "subgroups": list(sgs),
            "metrics": met,
            "bootstrapVsC0": boot,
            "posthocIncrementVsM2": increments,
            "acceptance": accept if season == 2026 else "not_applicable_retrospective",
        }
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--seasons", type=int, nargs="+", default=[2026, 2025])
    ap.add_argument("--cache-dir", default=str(ROOT / "data" / "cache" / "idp_opportunity"))
    ap.add_argument("--scoring-card", default=None)
    ap.add_argument("--league-id", default=DYNASTY_MAIN_LEAGUE_ID)
    ap.add_argument("--archive-root", action="append", default=[])
    ap.add_argument(
        "--out",
        default=str(
            ROOT
            / "docs"
            / "projections"
            / "evidence"
            / "idp_opportunity"
            / "backtest_2026-11-01.json"
        ),
    )
    ap.add_argument("--resamples", type=int, default=2000)
    ap.add_argument("--refresh", action="store_true")
    args = ap.parse_args(argv)

    from src.league_comparison.sleeper_scoring import scoring_fingerprint
    from src.ros.weekly_projection_archive import ARCHIVE_ROOT

    cache = Path(args.cache_dir)
    try:
        top_n, demand_record = _resolve_top_n(args, cache)
    except DemandRefused as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    settings, card_source = _load_card(args)
    card = Card.from_settings(settings)
    evidence: dict[str, Any] = {
        "evidenceType": EVIDENCE_TYPE,
        "shadowOnly": True,
        "preregistration": "docs/projections/IDP_OPPORTUNITY_CHALLENGERS_PREREGISTRATION_2026-11-01.md",
        "generatedAtUtc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        **_code_provenance(),
        "card": {
            "source": card_source,
            "fingerprint": scoring_fingerprint(settings),
            "settingsSha256": hashlib.sha256(
                json.dumps(settings, sort_keys=True).encode("utf-8")
            ).hexdigest(),
            "idpRates": {k: card.rates[k] for k in card.idp_keys},
        },
        "lineupDemand": demand_record,
        "inputs": {},
        "availability": {},
        "seasons": {},
    }
    base = S.NFLVERSE_RELEASE_BASE
    players_csv, h = S.cached_download(
        f"{base}/players/players.csv", cache, "players.csv", refresh=args.refresh
    )
    evidence["inputs"]["nflverse_players"] = h
    games_csv, h = S.cached_download(
        f"{base}/schedules/games.csv", cache, "games.csv", refresh=args.refresh
    )
    evidence["inputs"]["nflverse_games"] = h
    sleeper_players, h = S.load_sleeper_players(cache, refresh=args.refresh)
    evidence["inputs"]["sleeper_players"] = h
    if players_csv is None or games_csv is None or not sleeper_players:
        print("required static inputs unavailable", file=sys.stderr)
        return 2
    nfl_players = S.parse_players_csv(players_csv)

    any_eval = False
    for season in args.seasons:
        label = "primary_2026" if season == 2026 else f"retrospective_{season}_with_2026_card"
        sinfo: dict[str, Any] = {"label": label}
        games = S.parse_games(games_csv, season)
        finals = [w for w in games["finalWeeks"] if w >= FIRST_EVAL_WEEK]
        if season != 2026:
            finals = [w for w in finals if w <= LAST_REG_WEEK_2025]
        sinfo["evalWeeks"] = finals
        avail = {}
        for key, path in (
            ("stats_player_week", f"stats_player/stats_player_week_{season}.csv"),
            ("injuries", f"injuries/injuries_{season}.csv"),
            ("ftn_charting", f"ftn_charting/ftn_charting_{season}.csv"),
            ("roster", f"rosters/roster_{season}.csv"),
        ):
            p, h = S.cached_download(
                f"{base}/{path}", cache, path.replace("/", "__"), refresh=args.refresh
            )
            avail[key] = {
                "available": p is not None,
                "sha256": h if p else None,
                "error": None if p else h,
            }
            sinfo[key] = p
        avail["pbp_participation"] = _head(
            f"{base}/pbp_participation/pbp_participation_{season}.csv"
        )
        evidence["availability"][str(season)] = avail
        if sinfo["ftn_charting"] is not None:
            sinfo["ftnLagDays"] = S.ftn_publication_lag_days(
                sinfo["ftn_charting"], games["lastGameday"]
            )
        roots = [Path(r) for r in args.archive_root] or [ARCHIVE_ROOT]
        weeks_needed = list(range(1, (max(finals) if finals else 0) + 1))
        sinfo["preKickoffArchive"] = S.count_prekickoff_snapshots(
            season, weeks_needed, games["firstKickoffUtc"], roots
        )
        if not finals or sinfo["stats_player_week"] is None or sinfo["roster"] is None:
            sinfo["status"] = "no_evaluable_weeks"
            evidence["seasons"][str(season)] = {
                k: v for k, v in sinfo.items() if not isinstance(v, Path)
            }
            continue
        sleeper_weeks, srep = S.load_sleeper_weeks(
            season, weeks_needed, cache, refresh=args.refresh
        )
        sinfo["sleeperStats"] = srep
        team_of, trep = S.load_sleeper_team_weeks(season, weeks_needed, cache, refresh=args.refresh)
        sinfo["sleeperTeamStats"] = trep
        _, offense = S.parse_stats_player_week(sinfo["stats_player_week"], season)
        injuries = S.parse_injuries(sinfo["injuries"], season) if sinfo["injuries"] else {}
        xwalk = S.parse_roster_crosswalk(sinfo["roster"])
        data, census = S.build_season(
            season,
            sleeper_weeks,
            sleeper_players,
            nfl_players,
            xwalk,
            team_of,
            offense,
            games["schedule"],
            injuries,
        )
        sinfo["identityCensus"] = census
        eval_weeks = [w for w in finals if w in sleeper_weeks]
        preds, diag = run_season(data, card, eval_weeks)
        sinfo["diagnostics"] = diag
        sinfo["results"] = _evaluate(preds, season, args.resamples, top_n)
        sinfo["status"] = "evaluated"
        any_eval = any_eval or bool(preds)
        evidence["seasons"][str(season)] = {
            k: v for k, v in sinfo.items() if not isinstance(v, Path)
        }
        print(f"season {season}: {len(preds) // len(MODELS)} player-weeks over weeks {eval_weeks}")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(_r(evidence), indent=1, sort_keys=True, default=str) + "\n", encoding="utf-8"
    )
    print(f"wrote {out}")
    return 0 if any_eval else 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(1)
