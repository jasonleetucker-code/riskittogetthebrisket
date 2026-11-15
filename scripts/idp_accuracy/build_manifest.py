"""Build the shared IDP-accuracy research manifest (directive §6A).

Owner directive ``docs/owner/IDP_VALUATION_ACCURACY_DIRECTIVE_2026-10-25.md``.
Writes ``docs/valuation/idp_accuracy/MANIFEST.json``: every pinned input every
IDP-accuracy lane (A scoring, B replacement, C market, D shadow fair value) must
use, with checksums, plus the owner's league checklist verified FROM the live
Sleeper snapshot (never from config or memory).

Research-only.  Reads production code, changes none of it.  Public-safe: the
league's scoring/roster RULES are recorded; no manager, team, user id or
per-team roster listing is written.

Run:  python scripts/idp_accuracy/build_manifest.py [--offline]
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.idp_accuracy.common import (  # noqa: E402
    HISTORY_FLOOR,
    LEAGUE_ID,
    LEAGUE_KEY,
    OUT_DIR,
    PINNED_ARCHIVE,
    PINNED_REPO_SHA,
    REPO,
    SEASON,
    WEEKS,
    Fetcher,
    sha256_bytes,
    sha256_file,
)
from src.league_comparison.sleeper_scoring import (  # noqa: E402
    FINGERPRINT_VERSION,
    normalize_scoring_settings,
    scoring_fingerprint,
)

OUT = OUT_DIR / "MANIFEST.json"
RECON = OUT_DIR / "evidence" / "scorer_reconciliation.json"

#: The owner's starting checklist (directive §1) — EXPECTATIONS to verify,
#: never values to hardcode into a model.
CHECKLIST_SLOTS = (
    ["QB"] + ["RB"] * 2 + ["WR"] * 3 + ["TE"] * 2 + ["FLEX"] * 2 + ["SUPER_FLEX", "K"]
    + ["DL"] * 3 + ["LB"] * 3 + ["DB"] * 3
)  # fmt: skip
IDP_SLOTS = {"DL", "LB", "DB", "IDP_FLEX", "DE", "DT", "CB", "S"}
TIERED_REC_KEYS = ("rec_0_4", "rec_5_9", "rec_10_19", "rec_20_29", "rec_30_39", "rec_40p")


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO, capture_output=True, text=True, check=True
    ).stdout.strip()


def _canon_sha(obj: Any) -> str:
    return sha256_bytes(json.dumps(obj, sort_keys=True, separators=(",", ":")).encode())


def repo_block() -> dict[str, Any]:
    head = _git("rev-parse", "HEAD")
    changed = _git("diff", "--name-only", PINNED_REPO_SHA, head).splitlines() if head else []
    trees = {
        p: {"pinned": _git("rev-parse", f"{PINNED_REPO_SHA}:{p}"), "head": _git("rev-parse", f"HEAD:{p}")}
        for p in ("CSVs", "config", "src")
    }  # fmt: skip
    return {
        "pinnedSha": PINNED_REPO_SHA,
        "pinnedCommitDate": _git("show", "-s", "--format=%cI", PINNED_REPO_SHA),
        "buildHead": head,
        "pathsChangedPinnedToBuildHead": changed,
        "gitTreeIds": trees,
        "note": "The served board is rebuilt from the pinned archive by today's "
        "build_api_data_contract, which also reads CSVs/ and config/ from the working "
        "tree; gitTreeIds proves those inputs are byte-identical at the pinned SHA and "
        "at the build head (only data/scrape_state fetch stamps moved).",
    }


def roster_format(league: dict) -> dict[str, Any]:
    rp = list(league.get("roster_positions") or [])
    s = league.get("settings") or {}
    starters = [p for p in rp if p not in ("BN", "IR", "TAXI")]
    fmt = {
        "roster_positions": rp,
        "num_teams": s.get("num_teams"),
        "rosterSize": len(rp),
        "starterSlots": starters,
        "starterCount": len(starters),
        "benchSlots": rp.count("BN"),
        "taxi_slots": s.get("taxi_slots"),
        "reserve_slots": s.get("reserve_slots"),
        "best_ball": s.get("best_ball"),
        "type": s.get("type"),
    }
    fmt["rosterFormatFingerprint"] = (
        "rf1:"
        + _canon_sha(
            {
                k: fmt[k]
                for k in (
                    "roster_positions",
                    "num_teams",
                    "taxi_slots",
                    "reserve_slots",
                    "best_ball",
                    "type",
                )
            }  # fmt: skip
        )[:16]
    )
    return fmt


def checklist(league: dict, card: dict[str, float], fmt: dict) -> list[dict[str, Any]]:
    starters = fmt["starterSlots"]
    idp_starters = [p for p in starters if p in IDP_SLOTS]
    rows = [
        ("12 teams", 12, fmt["num_teams"]),
        ("58 roster spots", 58, fmt["rosterSize"]),
        ("best ball", 1, fmt["best_ball"]),
        ("slot list", CHECKLIST_SLOTS, starters),
        ("21 starters", 21, len(starters)),
        ("9 IDP starters (108 league-wide)", 9, len(idp_starters)),
        ("no IDP FLEX", False, "IDP_FLEX" in starters),
        ("no taxi slots", 0, fmt["taxi_slots"]),
        ("no IR / reserve slots", 0, fmt["reserve_slots"]),
        ("6-pt passing TD", 6.0, card.get("pass_td")),
        (
            "tiered reception scoring present",
            True,
            all(card.get(k) for k in TIERED_REC_KEYS),
        ),
        ("enhanced TFL (idp_tkl_loss > idp_tkl_solo)", True,
         (card.get("idp_tkl_loss") or 0) > (card.get("idp_tkl_solo") or 0)),
        ("enhanced PD (idp_pass_def > idp_tkl_solo)", True,
         (card.get("idp_pass_def") or 0) > (card.get("idp_tkl_solo") or 0)),
        ("no conventional TE reception premium (bonus_rec_te == 0)", True,
         not card.get("bonus_rec_te")),
    ]  # fmt: skip
    out = []
    for item, expected, observed in rows:
        out.append(
            {
                "item": item,
                "expected": expected,
                "observed": observed,
                "pass": expected == observed,
            }  # fmt: skip
        )
    return out


def card_notes(card: dict[str, float]) -> dict[str, Any]:
    rec_tiers = {k: card.get(k) for k in TIERED_REC_KEYS}
    return {
        "receptionScoring": {
            "rec": card.get("rec"),
            "tiers": rec_tiers,
            "note": "Sleeper rec_<a>_<b> keys pay by the LENGTH of each reception (yards "
            "on that catch), on top of the flat rec rate; they are not volume tiers.",
        },
        "positionReceptionBonuses": {
            k: card.get(k, 0.0) for k in ("bonus_rec_te", "bonus_rec_wr", "bonus_rec_rb")
        },  # fmt: skip
        "positionFirstDownBonuses": {
            k: card.get(k, 0.0)
            for k in ("bonus_fd_qb", "bonus_fd_rb", "bonus_fd_wr", "bonus_fd_te")
        },  # fmt: skip
        "tePremium": {
            "verdict": "NONE on the 2026 card: bonus_rec_te = 0.0, and bonus_fd_te equals "
            "bonus_fd_wr / bonus_fd_rb (1.0). The only position-specific reception bonus is "
            f"bonus_rec_wr = {card.get('bonus_rec_wr', 0.0)} per WR catch (a WR premium, "
            "tiny). TE scarcity in this league comes from the 2 TE starting slots, not from "
            "scoring.",
            "interactionWithTeppBoards": "The canonical board is anchored on KTC TE++ boards "
            "(ktcCrowdSfTep / ktcTradesSfTep) and lifts non-TEP sources' TEs onto that TE++ "
            "basis (ADR-015, src/league_intel/te_premium.convert_te_value, CLAUDE.md step 5a). "
            "So served TE values embed a TE-PREMIUM-SCORING market price this league's card "
            "does not pay. The board is scoring-profile scoped and the target basis is a "
            "constant by design; whether two required TE slots justify a comparable premium "
            "is an evidence question for Lanes C/D (league-scored lineup utility), not a "
            "scoring fact. Recorded here so no lane assumes the TE++ uplift is earned by "
            "scoring.",
        },
        "idpPriceRatios": {
            "sack_over_solo": round(card["idp_sack"] / card["idp_tkl_solo"], 3),
            "tfl_over_solo": round(card["idp_tkl_loss"] / card["idp_tkl_solo"], 3),
            "pd_over_solo": round(card["idp_pass_def"] / card["idp_tkl_solo"], 3),
            "qbhit_over_solo": round(card["idp_qb_hit"] / card["idp_tkl_solo"], 3),
            "assist_over_solo": round(card["idp_tkl_ast"] / card["idp_tkl_solo"], 3),
            "stacking": "A sack line in Sleeper's feed normally ALSO carries the TFL and QB "
            "hit; every key is paid (verified 251/251 on awarded points; see "
            "evidence/scorer_reconciliation.json#stacking). A 1-sack/1-TFL/1-hit play pays "
            f"{round(card['idp_sack'] + card['idp_tkl_loss'] + card['idp_qb_hit'], 2)} + "
            "sack yards.",
        },
    }


def archive_block(path: Path) -> tuple[dict[str, Any], dict]:
    with zipfile.ZipFile(path) as zf:
        members = {n: sha256_bytes(zf.read(n)) for n in zf.namelist()}
        man = json.loads(zf.read("manifest.json"))
        member = next(
            n for n in zf.namelist() if n.startswith("dynasty_data_") and n.endswith(".json")
        )
        raw = json.loads(zf.read(member))
    rs = (raw.get("settings") or {}).get("sourceRunSummary") or {}
    sources = {
        k: {f: v.get(f) for f in ("state", "enabled", "startedAt", "finishedAt", "valueCount")}
        for k, v in (rs.get("sources") or {}).items()
        if v.get("enabled")
    }
    sl = raw.get("sleeper") or {}
    blk = {
        "path": str(path.relative_to(REPO)).replace("\\", "/"),
        "sha256": sha256_file(path),
        "members": members,
        "boardMember": member,
        "scrapeTimestamp": raw.get("scrapeTimestamp"),
        "exportGeneratedAt": man.get("generatedAt"),
        "siteRawFresh": man.get("siteRawFresh"),
        "siteRawPreservedNotRefetched": man.get("siteRawPreserved"),
        "scraperRun": {
            k: rs.get(k)
            for k in ("startedAt", "finishedAt", "overallStatus", "partialRun", "completeSources")
        },  # fmt: skip
        "scraperSources": sources,
        "sleeperBlock": {
            "leagueId": sl.get("leagueId"),
            "rosterFetchedAt": sl.get("rosterFetchedAt"),
            "scoringFingerprint": scoring_fingerprint(sl.get("scoringSettings")),
        },
        "historyFloor": HISTORY_FLOOR,
        "note": "The archive is the scraper's RAW payload. The canonical served board is "
        "what build_api_data_contract derives from it; use rankDerivedValue / "
        "canonicalConsensusRank / canonicalSiteValues / confidenceBucket / quarantined "
        "from that build, never a scraper _composite field.",
    }
    return blk, raw


def served_board(raw: dict) -> dict[str, Any]:
    from src.api.data_contract import build_api_data_contract  # noqa: PLC0415

    c = build_api_data_contract(raw)
    rows = c.get("playersArray") or []
    key = sorted(
        (
            str(r.get("displayName")),
            str(r.get("playerId") or ""),
            r.get("rankDerivedValue"),
            r.get("canonicalConsensusRank"),
            r.get("confidenceBucket"),
            bool(r.get("quarantined")),
        )
        for r in rows
    )
    by_class: dict[str, int] = {}
    for r in rows:
        by_class[str(r.get("assetClass"))] = by_class.get(str(r.get("assetClass")), 0) + 1
    svs = c.get("sourceVotingStatus") or {}
    return {
        "contractVersion": c.get("contractVersion"),
        "rows": len(rows),
        "rowsByAssetClass": by_class,
        "pricedRows": sum(1 for r in rows if (r.get("rankDerivedValue") or 0) > 0),
        "rankedRows": sum(1 for r in rows if r.get("canonicalConsensusRank")),
        "quarantinedRows": sum(1 for r in rows if r.get("quarantined")),
        "servedBoardSha256": _canon_sha(key),
        "servedBoardShaFields": [
            "displayName",
            "playerId",
            "rankDerivedValue",
            "canonicalConsensusRank",
            "confidenceBucket",
            "quarantined",
        ],  # fmt: skip
        "sourceVotingStatus": {
            "asOf": svs.get("asOf"),
            "freshnessSchedule": svs.get("freshnessSchedule"),
            "votingCount": svs.get("votingCount"),
            "registeredCount": svs.get("registeredCount"),
            "statusCounts": svs.get("statusCounts"),
            "sources": [
                {
                    k: s.get(k)
                    for k in (
                        "key",
                        "status",
                        "reason",
                        "dataAsOf",
                        "lastUpdate",
                        "ageDays",
                        "effectiveWeight",
                        "family",
                    )
                    if k in s
                }  # fmt: skip
                for s in (svs.get("sources") or [])
            ],
        },
        "hillCurvesSha256": _canon_sha(c.get("hillCurves")),
        "crossPositionBridgesSha256": _canon_sha(c.get("crossPositionBridges")),
    }


def projections_block() -> dict[str, Any]:
    d = REPO / "data/bdvm/projections"
    if not d.exists() or not any(d.iterdir()):
        return {
            "status": "UNAVAILABLE",
            "reason": "data/bdvm/projections/ is absent in this checkout (gitignored, "
            "box-local: produced on the production box by the weekly dynasty-bdvm-refresh "
            "timer). No projection snapshot may be pinned from this machine; any lane needing "
            "BDVM projections must rebuild the reconstructed baseline itself "
            "(scripts/bdvm_build_baseline.py) and record its own provenance, or mark the "
            "dependency UNAVAILABLE.",
        }
    files = sorted(p for p in d.rglob("*") if p.is_file())
    return {
        "status": "OK",
        "files": {str(p.relative_to(REPO)).replace("\\", "/"): sha256_file(p) for p in files},
    }


def versions_block() -> dict[str, Any]:
    from src.bdvm.params import load_param_set  # noqa: PLC0415

    def f(p: str) -> dict[str, str]:
        return {"path": p, "sha256": sha256_file(REPO / p)}

    fv = json.loads(
        (REPO / "config/league_valuation/fair_value_v1.json").read_text(encoding="utf-8")
    )
    bb = json.loads((REPO / "config/bestball/marginal_v1.json").read_text(encoding="utf-8"))
    br = json.loads((REPO / "config/bridges/bridges_v1.json").read_text(encoding="utf-8"))
    pm = json.loads((REPO / "config/trade/package_model.json").read_text(encoding="utf-8"))
    return {
        "bdvmParams": {
            **f("config/bdvm/params_v1.json"),
            "paramSetId": load_param_set().param_set_id,
        },
        "leagueFairValue": {
            **f("config/league_valuation/fair_value_v1.json"),
            "modelVersion": fv.get("modelVersion"),
            "paramSetId": fv.get("paramSetId"),
        },  # fmt: skip
        "bestballMarginal": {
            **f("config/bestball/marginal_v1.json"),
            "modelVersion": bb.get("modelVersion"),
        },  # fmt: skip
        "bridges": {**f("config/bridges/bridges_v1.json"), "version": br.get("version")},
        "packageModel": {**f("config/trade/package_model.json"), "active": pm.get("active")},
        "scoringFingerprintVersion": FINGERPRINT_VERSION,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()
    f = Fetcher(offline=args.offline)
    league = f.league()
    if str(league.get("league_id")) != LEAGUE_ID:
        raise SystemExit(f"wrong league: {league.get('league_id')}")
    raw_card = league.get("scoring_settings") or {}
    card = normalize_scoring_settings(raw_card) or {}
    fmt = roster_format(league)
    checks = checklist(league, card, fmt)
    # touch every dataset the scorer reconciliation reads so its checksum is pinned
    f.rosters()
    for w in WEEKS:
        f.matchups(w)
        f.stats(w)
    f.players()

    from src.api import league_registry  # noqa: PLC0415

    reg_id = league_registry.get_sleeper_league_id(LEAGUE_KEY)
    cfg = league_registry.get_league_by_key(LEAGUE_KEY)
    arch, raw = archive_block(PINNED_ARCHIVE)
    recon = json.loads(RECON.read_text(encoding="utf-8")) if RECON.exists() else {}
    nfl = recon.get("nflverse") or {}

    manifest = {
        "manifestVersion": "idp-accuracy-manifest/v1",
        "directive": "docs/owner/IDP_VALUATION_ACCURACY_DIRECTIVE_2026-10-25.md",
        "builtAtUtc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "builder": "scripts/idp_accuracy/build_manifest.py",
        "repo": repo_block(),
        "league": {
            "key": LEAGUE_KEY,
            "sleeperLeagueId": LEAGUE_ID,
            "registryResolvesTo": reg_id,
            "registryMatches": str(reg_id) == LEAGUE_ID,
            "registryScoringProfileLabel": getattr(cfg, "scoring_profile", None),
            "season": league.get("season"),
            "status": league.get("status"),
            "previousLeagueId": league.get("previous_league_id"),
            "snapshotFetchedAtUtc": f.receipts[f"https://api.sleeper.app/v1/league/{LEAGUE_ID}"][
                "fetchedAtUtc"
            ],
        },
        "scoringCard": {
            "source": f"GET https://api.sleeper.app/v1/league/{LEAGUE_ID} .scoring_settings",
            "scoringFingerprint": scoring_fingerprint(raw_card),
            "matchesArchiveSleeperBlock": scoring_fingerprint(raw_card)
            == arch["sleeperBlock"]["scoringFingerprint"],
            "rawCardSha256": _canon_sha(raw_card),
            "nonZeroRules": dict(sorted(card.items())),
            "zeroOrAbsentRulesCount": len(raw_card) - len(card),
            "notes": card_notes(card),
        },
        "rosterFormat": fmt,
        "ownerChecklist": {
            "items": checks,
            "discrepancies": [c for c in checks if not c["pass"]],
        },
        "statisticsCutoff": {
            "season": SEASON,
            "seasonType": "regular",
            "weeksIncluded": list(WEEKS),
            "weeksExcluded": {"7": "in progress on 2026-10-25 (not all games final)"},
            "sleeperLastScoredLeg": (league.get("settings") or {}).get("last_scored_leg"),
            "sleeperCurrentLeg": (league.get("settings") or {}).get("leg"),
        },
        "pinnedArchive": arch,
        "servedBoard": served_board(raw),
        "projectionProvenance": projections_block(),
        "modelVersions": versions_block(),
        "datasets": {
            "sleeperPublicApi": {
                u.replace("https://api.sleeper.app/v1", ""): r
                for u, r in sorted(f.receipts.items())
            },
            "nflverseStatsPlayerWeek2026": {
                "rowsScored": nfl.get("nflverseRegRowsWeeks1to6"),
                "canonicalRowsSha256": nfl.get("nflverseRowsCanonicalSha256"),
                "source": nfl.get("nflverseSource"),
            }
            if nfl
            else {"status": "UNAVAILABLE", "reason": "scorer_reconcile.py --nflverse not run"},
            "pbpWeekly2026": {
                "sha256": nfl.get("pbpArtifactSha256"),
                "weeksCovered": nfl.get("pbpWeeksCovered"),
                "builtBy": "src.nfl_data.pbp_weekly.persist_pbp_weekly "
                "(complete_through_week=6)",
            }
            if nfl
            else None,  # fmt: skip
            "cacheLocation": "data/idp_accuracy/cache/ (gitignored; key = sha256(url)[:24])",
        },
        "publicArtifactPolicy": "Rules, aggregates and public NFL player names only. No "
        "manager/team names, user ids or per-team roster listings.",
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(manifest, indent=1, default=str) + "\n", encoding="utf-8")
    print(json.dumps({"scoringFingerprint": manifest["scoringCard"]["scoringFingerprint"],
                      "rosterFormatFingerprint": fmt["rosterFormatFingerprint"],
                      "discrepancies": manifest["ownerChecklist"]["discrepancies"],
                      "servedBoardSha256": manifest["servedBoard"]["servedBoardSha256"]},
                     indent=1, default=str))  # fmt: skip
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
