"""Scoring-parity taxonomy: every nflverse-path vs host-native player-week mismatch, classified.

Owner master directive 2026-11-08 section 7, Priority 2 (exact league scoring parity).
Research-only: imports production code, changes none of it, writes only ``--out``
and gitignored caches under ``data/idp_accuracy/``.

Truth is Sleeper's own ``players_points`` (``/league/<id>/matchups/<week>``).  The
host-native scorer (``compute_weekly_points(..., source="sleeper")``) reconciles to it
on every scored player-week (see ``scorer_reconcile.py``); this script therefore
measures the OTHER path, the nflverse path ``src/bdvm/actuals.py`` runs, against it:

    nflverse stats_player_week row -> normalize_weekly_row -> pbp supplement
        -> compute_weekly_points (source="nflverse")

It REUSES ``scorer_reconcile.reconcile_host`` / ``reconcile_nflverse`` (the census
behind the "91.5%" figure) and adds a single deterministic classifier that puts EVERY
mismatching player-week into exactly one class:

    implementation_error | source_data_disagreement | missing_stat_category |
    incorrect_player_identity | incorrect_position_classification |
    unavailable_evidence | irreconcilable_provider_semantics | rounding | unexplained

Run it twice, on two source trees, with identical pinned inputs:

    python scripts/idp_accuracy/scoring_parity_taxonomy.py --out <main.json>
    # in a throwaway worktree of PR #1938 (never merged), same cache + pbp artifact:
    python scripts/idp_accuracy/scoring_parity_taxonomy.py --out <pr1938.json>

Pinning: the Sleeper responses are cached by ``common.Fetcher`` and the nflverse
weekly rows are cached once in ``data/idp_accuracy/taxonomy/``; both are hashed into
the output.  Public artifact rules: public NFL player names / Sleeper ids and
aggregates only; no roster id, team, manager or user id.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.idp_accuracy import scorer_reconcile as sr  # noqa: E402
from scripts.idp_accuracy.common import (  # noqa: E402
    IDP_GROUPS,
    LEAGUE_ID,
    LEAGUE_KEY,
    REPO,
    SEASON,
    WEEKS,
    Fetcher,
    sha256_bytes,
    sha256_file,
)
from src.league_comparison.sleeper_scoring import scoring_fingerprint  # noqa: E402
from src.nfl_data import nflverse_direct, pbp_weekly, scoring_coverage  # noqa: E402
from src.nfl_data.realized_points import compute_weekly_points  # noqa: E402

TOL = sr.TOL
ROUNDING_CEILING = 0.02  # a diff with NO differing scoring key and |d| <= this is rounding
CARD_FINGERPRINT = "sf1:9e51824690d091f9"
TAXONOMY_DIR = REPO / "data/idp_accuracy/taxonomy"
ROWS_CACHE = TAXONOMY_DIR / f"nflverse_rows_{SEASON}_w{min(WEEKS)}_{max(WEEKS)}.json"

CLASSES = (
    "implementation_error",
    "source_data_disagreement",
    "missing_stat_category",
    "incorrect_player_identity",
    "incorrect_position_classification",
    "unavailable_evidence",
    "irreconcilable_provider_semantics",
    "rounding",
    "unexplained",
)


# ── pinned nflverse rows ──────────────────────────────────────────────────────


def pinned_rows() -> tuple[list[dict[str, Any]], str]:
    """The nflverse weekly rows, fetched at most once and then reused (hash recorded)."""
    TAXONOMY_DIR.mkdir(parents=True, exist_ok=True)
    if not ROWS_CACHE.exists():
        rows = [
            r
            for r in nflverse_direct.fetch_weekly_stats([SEASON])
            if str(r.get("season_type") or "REG").upper() == "REG"
            and sr._num(r.get("week")) is not None
            and int(r["week"]) in WEEKS
        ]
        if not rows:
            raise SystemExit(
                "nflverse weekly rows unavailable (network?); refusing to pin an empty set"
            )
        ROWS_CACHE.write_text(json.dumps(rows, sort_keys=True, default=str), encoding="utf-8")
    blob = ROWS_CACHE.read_bytes()
    return json.loads(blob), sha256_bytes(blob)


# ── the classifier ────────────────────────────────────────────────────────────


def _scored_by_nflverse(key: str) -> bool:
    return scoring_coverage.classify(key, pbp_supplement=True) == scoring_coverage.Coverage.SCORED


def classify_exception(
    e: dict[str, Any], supplement: dict[str, Any] | None, group_from_listing: str | None
) -> tuple[str, str, str]:
    """(class, subclass, detail) for ONE mismatching player-week.  Pure.

    ``e`` is a ``scorer_reconcile.reconcile_nflverse`` exception.  The class is chosen
    from the key with the largest |host - nflverse| points, then refined by evidence on
    the row itself (never by who the player is).
    """
    cat = e["category"]
    if cat in ("identity_name_collision_dropped", "identity_join_miss"):
        return ("incorrect_player_identity", cat, "name key did not resolve to one nflverse player")
    if cat == "stat_source_gap_week_missing":
        return (
            "unavailable_evidence",
            cat,
            "host paid points; no nflverse row/week for the player",
        )
    if cat == "unexplained":
        return ("unexplained", cat, "host-native scorer matched, nflverse differs, no key diff")
    dk: dict[str, list[float]] = e.get("keysDifferHostVsNflverse") or {}
    if not dk:
        d = abs(e.get("diff", 0.0))
        if d <= ROUNDING_CEILING:
            return ("rounding", "no_key_diff", f"|diff| {d:.4f} <= {ROUNDING_CEILING}")
        return ("unexplained", "no_key_diff", f"|diff| {d:.4f} with no differing scoring key")
    dom = max(dk, key=lambda k: abs(dk[k][1] - dk[k][0]))
    host_pts, nfl_pts = dk[dom]
    attribution = set(e.get("attribution") or ())
    group = e["group"]
    # 1. position: the nflverse listing maps to a different lineup group than Sleeper's AND the
    #    key is one whose RATE depends on position (every IDP rate is position-agnostic on this card)
    if (
        group_from_listing
        and group_from_listing != group
        and dom.startswith(("bonus_fd_", "bonus_rec_"))
    ):
        return (
            "incorrect_position_classification",
            f"{group}_vs_nflverse_{group_from_listing}",
            f"position-scoped key {dom} paid under the provider's listing, not the host's",
        )
    # 2. the nflverse path emits no such key at all -> a missing category
    if not _scored_by_nflverse(dom):
        return ("missing_stat_category", dom, f"nflverse path has no scorer for {dom}")
    # 3. defects the reconciler can name from the raw row
    if "IDPA-DEFECT-01" in attribution and dom == "idp_tkl_ast":
        # The host pays a non-IDP-listed player's assists, but nflverse's assist column also
        # lumps in special-teams assists the host does not pay, and no source separates them
        # (the supplement carries no st_tkl_ast).  Un-gating would trade an under-pay for an
        # over-pay, so this is a provider-semantics limit rather than a code defect.
        return (
            "irreconcilable_provider_semantics",
            "non_idp_listed_assists_inseparable_from_special_teams",
            "def_tackle_assists cannot be split into defensive vs special-teams assists",
        )
    if "IDPA-DEFECT-01" in attribution:
        return (
            "implementation_error",
            "idp_gate_non_idp_listed_player",
            "sleeper_stat_line_from_row emits def_* only under `if _is_idp_position(pos)`",
        )
    if "IDPA-DEFECT-02" in attribution:
        return (
            "missing_stat_category",
            "blocked_kick_not_a_miss",
            "fg_blocked / pat_blocked unmapped",
        )
    if "IDPA-DEFECT-03" in attribution:
        return (
            "missing_stat_category",
            "defensive_fumble_return_td",
            "fumble_recovery_tds not mapped to idp_def_td",
        )
    # 4. special-teams tackles: nflverse tackle columns include them, Sleeper pays them as st_*
    st_solo = float((supplement or {}).get("st_tkl_solo") or 0)
    if dom == "idp_tkl_solo" and nfl_pts > host_pts and st_solo > 0:
        return (
            "implementation_error",
            "special_teams_tackle_paid_twice",
            f"weekly solo column includes {st_solo:g} ST tackle(s) AND st_tkl_solo supplement pays them",
        )
    if dom == "idp_tkl_ast" and nfl_pts > host_pts and st_solo > 0:
        return (
            "irreconcilable_provider_semantics",
            "special_teams_assists_lumped",
            "nflverse def_tackle_assists includes ST assists; supplement carries no st_tkl_ast",
        )
    # 5. a solo/assist count difference with no independent evidence of its cause.  The
    #    special-teams-assist rule above keys on a special-teams SOLO count (a PROXY: the
    #    supplement carries no assist evidence), so rows landing here may be the same
    #    special-teams-assist defect; they are labelled as unattributed rather than as proven
    #    provider disagreement.
    if dom in ("idp_tkl_ast", "idp_tkl_solo"):
        return (
            "source_data_disagreement",
            "unattributed_solo_assist_split",
            f"{dom}: host {host_pts:+.3f} vs nflverse {nfl_pts:+.3f} points; cause not "
            "established (provider split or special-teams assists)",
        )
    return (
        "source_data_disagreement",
        dom,
        f"{dom}: host {host_pts:+.3f} vs nflverse {nfl_pts:+.3f} points",
    )


# ── measurement ───────────────────────────────────────────────────────────────


def _bucket() -> dict[str, float]:
    return {"playerWeeks": 0, "netPoints": 0.0, "absPoints": 0.0}


def _add(b: dict[str, float], pts: float) -> None:
    b["playerWeeks"] += 1
    b["netPoints"] = round(b["netPoints"] + pts, 4)
    b["absPoints"] = round(b["absPoints"] + abs(pts), 4)


def build_taxonomy() -> dict[str, Any]:
    f = Fetcher()
    league = f.league()
    assert str(league.get("league_id")) == LEAGUE_ID, "wrong league"
    card = {
        k: float(v)
        for k, v in (league.get("scoring_settings") or {}).items()
        if sr._num(v) is not None
    }
    fp = scoring_fingerprint(league["scoring_settings"])
    assert fp == CARD_FINGERPRINT, f"scoring card drifted: {fp}"
    pdb = f.players()
    host = sr.reconcile_host(f, card, pdb)
    recs = host.pop("records")

    rows, rows_sha = pinned_rows()
    # reconcile_nflverse fetches live by default; hand it the pinned rows instead
    nflverse_direct.fetch_weekly_stats = lambda seasons, **_k: list(rows)  # type: ignore[assignment]
    nfl = sr.reconcile_nflverse(card, pdb, recs, f)
    if nfl.get("status") != "OK":
        raise SystemExit(f"nflverse path unavailable: {nfl}")
    assert nfl["nflverseRowsCanonicalSha256"], "rows hash missing"

    from src.bdvm.baseline import normalize_weekly_row  # noqa: PLC0415
    from src.bdvm.context import TRUE_POSITION_MAP  # noqa: PLC0415
    from src.utils.name_clean import normalize_player_name  # noqa: PLC0415

    pbp_dir = REPO / "data/idp_accuracy/pbp_weekly"
    stats_obj = pbp_weekly.default_pbp_stats(SEASON, out_dir=pbp_dir)
    raw_by: dict[tuple[str, int], dict] = {}
    for r in rows:
        nm = str(r.get("player_display_name") or r.get("player_name") or "").strip()
        raw_by[(normalize_player_name(nm), int(r["week"]))] = r

    by_class: dict[str, dict] = {c: _bucket() for c in CLASSES}
    by_sub: dict[str, dict] = defaultdict(_bucket)
    by_class_pos: dict[str, dict[str, dict]] = {c: defaultdict(_bucket) for c in CLASSES}
    by_side: dict[str, dict[str, dict]] = {
        "IDP": {c: _bucket() for c in CLASSES},
        "OFFENSE": {c: _bucket() for c in CLASSES},
    }
    classified: list[dict[str, Any]] = []
    for e in nfl["exceptions"]:
        raw = raw_by.get((normalize_player_name(str(e["name"] or "")), e["week"]))
        supplement = None
        listing_group = None
        if raw is not None and stats_obj is not None:
            supplement = pbp_weekly.attach_supplement(normalize_weekly_row(raw), stats_obj).get(
                "pbp_derived"
            )
        if raw is not None:
            listing = str(raw.get("position") or "").upper()
            listing_group = sr.lineup_position(TRUE_POSITION_MAP.get(listing, listing))
        cls, sub, detail = classify_exception(e, supplement, listing_group)
        # points: nflverse - host for a scored mismatch; the unmatched host award otherwise
        pts = e["diff"] if "diff" in e else -float(e["awarded"])
        side = "IDP" if e["group"] in IDP_GROUPS else "OFFENSE"
        _add(by_class[cls], pts)
        _add(by_sub[f"{cls}:{sub}"], pts)
        _add(by_class_pos[cls][e["group"]], pts)
        _add(by_side[side][cls], pts)
        classified.append(
            {
                "week": e["week"],
                "sid": e["sid"],
                "name": e["name"],
                "group": e["group"],
                "awarded": e["awarded"],
                "computed": e.get("computed"),
                "diff": round(pts, 4),
                "class": cls,
                "subclass": sub,
                "detail": detail,
                "keysDiffer": e.get("keysDifferHostVsNflverse") or {},
                "multiKey": len(e.get("keysDifferHostVsNflverse") or {}) > 1,
            }
        )

    census = nfl["census"]
    joined = census.get("match", 0) + sum(
        1
        for c in classified
        if c["class"] not in ("incorrect_player_identity", "unavailable_evidence")
    )
    total_pw = len(recs)
    scored_by_host = sum(1 for r in recs if r["computed"] is not None)

    # which card keys did the host actually pay on rostered player-weeks, and can nflverse score them
    host_key_points: dict[str, dict[str, float]] = defaultdict(
        lambda: {"playerWeeks": 0, "points": 0.0}
    )
    for w in WEEKS:
        stats = f.stats(w) or {}
        for sid in {r["sid"] for r in recs if r["week"] == w}:
            line = stats.get(sid)
            if not line:
                continue
            res = compute_weekly_points(
                {**line, "player_id": sid, "season": SEASON, "week": w}, card, source="sleeper"
            )
            for k, _raw, _rate, awarded in res.components if res else ():
                if awarded:
                    host_key_points[k]["playerWeeks"] += 1
                    host_key_points[k]["points"] = round(host_key_points[k]["points"] + awarded, 4)
    paid_keys = {
        k: {
            **v,
            "nflverseCoverage": scoring_coverage.classify(k, pbp_supplement=True).value,
        }
        for k, v in sorted(host_key_points.items())
    }

    wide = wide_sample_impact(f, card, pdb, rows, stats_obj)
    return {
        "league": {"key": LEAGUE_KEY, "sleeperId": LEAGUE_ID, "season": SEASON},
        "scoringFingerprint": fp,
        "weeks": list(WEEKS),
        "inputs": {
            "sleeperResponses": f.receipts,
            "nflverseRowsFile": str(ROWS_CACHE.relative_to(REPO)),
            "nflverseRowsFileSha256": rows_sha,
            "nflverseRowsCanonicalSha256": nfl["nflverseRowsCanonicalSha256"],
            "nflverseRowCount": len(rows),
            "pbpArtifactSha256": nfl["pbpArtifactSha256"],
            "pbpWeeksCovered": nfl["pbpWeeksCovered"],
        },
        "sample": {
            "rosteredPlayerWeeks": total_pw,
            "hostScored": scored_by_host,
            "hostWithinTol": host["distribution"]["withinTol"],
            "nflverseJoinedAndScored": sum(
                v
                for k, v in census.items()
                if k in ("match", "scorer_defect", "stat_source_disagreement")
            ),
        },
        "nflverseCensus": census,
        "nflverseWithinTol": census.get("match", 0),
        "nflverseDistribution": nfl["distribution"],
        "nflverseDistributionByGroup": nfl["distributionByGroup"],
        "taxonomy": {
            "byClass": by_class,
            "bySubclass": dict(sorted(by_sub.items())),
            "byClassAndPosition": {c: dict(v) for c, v in by_class_pos.items() if v},
            "bySide": by_side,
            "totalMismatchingPlayerWeeks": len(classified),
            "multiKeyRows": sum(1 for c in classified if c["multiKey"]),
            "note": "class and subclass are assigned by the DOMINANT differing key (largest "
            "|host - nflverse| points), not by cause; multiKey marks rows where more than one "
            "key differs",
        },
        "hostPaidKeysOnRosteredPlayerWeeks": paid_keys,
        "mismatches": classified,
        "wideSampleBdvmImpact": wide,
        "_joined": joined,
    }


# ── downstream impact on BDVM in-season values (descriptive) ──────────────────


def wide_sample_impact(
    f: Fetcher, card: dict[str, float], pdb: dict, rows: list[dict], stats_obj: Any
) -> dict[str, Any]:
    """How far the nflverse path's mean PPG sits from the host-native mean PPG, per player.

    BDVM blends realized PPG as ``mu_post = w*mu_prior + (1-w)*mu_recent`` with
    ``w = n_prior/(n_prior+weeks)`` (``src/bdvm/ros.py``), so a scoring-path difference
    moves ``mu_post`` by ``(1-w) * dPPG`` whatever the projection.  Every player with a
    nflverse row AND a Sleeper stat line is compared on the SAME weeks, joined by GSIS
    id (identity is a separate census class, not mixed into this number).
    """
    from src.bdvm.baseline import normalize_weekly_row  # noqa: PLC0415
    from src.bdvm.context import TRUE_POSITION_MAP  # noqa: PLC0415
    from src.bdvm.ros import ros_projection_weight  # noqa: PLC0415

    params = json.loads((REPO / "config/bdvm/params_v1.json").read_text(encoding="utf-8"))
    gsis_to_sid = {
        str(m["gsis_id"]): sid for sid, m in pdb.items() if isinstance(m, dict) and m.get("gsis_id")
    }
    from src.utils.name_clean import normalize_player_name  # noqa: PLC0415

    host_by: dict[tuple[str, int], float] = {}
    for w in WEEKS:
        for sid, line in (f.stats(w) or {}).items():
            if not isinstance(line, dict):
                continue
            res = compute_weekly_points(
                {**line, "player_id": sid, "season": SEASON, "week": w}, card, source="sleeper"
            )
            if res is not None and float(line.get("gp") or 0) > 0:
                host_by[(sid, w)] = res.fantasy_points
    # Sleeper's directory carries a GSIS id for only a minority of players, so fall back to
    # a UNIQUE normalized-name match among players that have a host line (ambiguous -> skipped)
    name_sids: dict[str, set[str]] = defaultdict(set)
    for sid in {s for (s, _w) in host_by}:
        meta = pdb.get(sid) or {}
        nm = meta.get("full_name") or f"{meta.get('first_name', '')} {meta.get('last_name', '')}"
        name_sids[normalize_player_name(str(nm))].add(sid)
    join_counts: Counter = Counter()
    per_name: dict[int, str] = {}
    per: dict[str, dict[str, Any]] = {}
    for raw in rows:
        sid = gsis_to_sid.get(str(raw.get("player_id") or ""))
        if sid is not None:
            join_counts["gsis"] += 1
        else:
            cands = name_sids.get(
                normalize_player_name(
                    str(raw.get("player_display_name") or raw.get("player_name") or "")
                )
            )
            if cands and len(cands) == 1:
                sid = next(iter(cands))
                join_counts["name"] += 1
            else:
                join_counts["unjoined"] += 1
        w = int(raw["week"])
        if sid is None or (sid, w) not in host_by:
            continue
        listing = str(raw.get("position") or "").upper()
        nrow = normalize_weekly_row(raw)
        if stats_obj is not None:
            nrow = pbp_weekly.attach_supplement(nrow, stats_obj)
        rp = compute_weekly_points(nrow, card, position=TRUE_POSITION_MAP.get(listing, listing))
        if rp is None:
            continue
        p = per.setdefault(sid, {"nfl": [], "host": [], "group": None})
        per_name[id(p)] = str(raw.get("player_display_name") or "")
        p["nfl"].append(rp.fantasy_points)
        p["host"].append(host_by[(sid, w)])
        p["group"] = sr.lineup_position(str((pdb.get(sid) or {}).get("position") or ""))
    thresholds = (0.01, 0.1, 0.25, 0.5)
    out: dict[str, dict[str, Any]] = {}
    for side in ("IDP", "OFFENSE", "ALL"):
        deltas = []
        labels: list[tuple] = []
        for p in per.values():
            is_idp = p["group"] in IDP_GROUPS
            if side != "ALL" and (side == "IDP") != is_idp:
                continue
            n = len(p["nfl"])
            d_ppg = sum(p["nfl"]) / n - sum(p["host"]) / n
            w_proj = ros_projection_weight(float(n), is_idp=is_idp, params=params)
            deltas.append((1.0 - w_proj) * d_ppg)
            labels.append((abs(deltas[-1]), per_name.get(id(p)), p["group"], n))
        a = sorted(abs(x) for x in deltas)
        out[side] = {
            "largestMoves": [
                {"name": nm, "group": g, "weeks": n, "absDeltaMuPost": round(v, 3)}
                for v, nm, g, n in sorted(labels, key=lambda t: -t[0])[:5]
            ],
            "playersWithSamples": len(deltas),
            "moved": {f">{t}": sum(1 for x in a if x > t) for t in thresholds},
            "maxAbsDeltaMuPost": round(a[-1], 4) if a else None,
            "meanAbsDeltaMuPost": round(sum(a) / len(a), 5) if a else None,
            "meanSignedDeltaMuPost": round(sum(deltas) / len(deltas), 5) if deltas else None,
            "p95AbsDeltaMuPost": round(a[int(0.95 * (len(a) - 1))], 4) if a else None,
        }
    return {
        "method": "dMuPost = (1 - n_prior/(n_prior+weeks)) * (mean nflverse-path PPG - mean "
        "host-native PPG) over the same weeks; params config/bdvm/params_v1.json; descriptive only",
        "join": "GSIS id where Sleeper's directory has one, else unique normalized name; "
        "rows with neither are skipped (identity is a separate census class)",
        "joinCounts": dict(join_counts),
        "bySide": out,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--label", default="main")
    args = ap.parse_args()
    out = build_taxonomy()
    out.pop("_joined", None)
    out["sourceTree"] = {
        "label": args.label,
        "realizedPointsSha256": sha256_file(REPO / "src/nfl_data/realized_points.py"),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=1, default=str) + "\n", encoding="utf-8")
    t = out["taxonomy"]
    print(json.dumps({"census": out["nflverseCensus"], "byClass": t["byClass"]}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
