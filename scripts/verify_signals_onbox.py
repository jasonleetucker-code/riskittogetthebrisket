#!/usr/bin/env python3
"""Signals Fantasy production verification + IDP crosswalk evaluation.

Runs ON the production host (workflow ``signals-onbox-verification.yml``),
from the deployed checkout, against the box's own inputs.  It is the evidence
for two things:

* OFFENSE is live: the timer, the owner session, a real collection, the
  private board, and the in-process contract seeing ``signalsSf`` vote — plus
  its whole-board impact and the FantasyCalc family-cap proof.
* IDP Candidate A (``docs/sources/SIGNALS_FANTASY_INTEGRATION.md`` §10): the
  preregistered champion-vs-challenger metrics, the watch list, the
  diagnostic Candidate B and the completed-trade check — the inputs to the
  promotion gate.

Privacy: prints counts, distributions, states and watch-list rows only.  It
never prints a token, a session field beyond its health, or a raw Signals
payload; per-player numbers appear only for the preregistered watch list.

Read-only except ``--collect``, which starts the existing
``dynasty-signals-values.service`` once (``sudo -n systemctl start``) exactly
as its timer does.  The contract is built in-process three times (no Signals /
shipped / IDP promoted) and never published.

Exit 0 when the checks ran (a failed CHECK is a finding printed in the JSON);
non-zero only when the script itself could not run.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import sqlite3
import statistics
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Iterable, Mapping

SIGNALS_IDP = {"signalsIdpDl": "DL", "signalsIdpLb": "LB", "signalsIdpDb": "DB"}
UNIT = "dynasty-signals-values"


# ── small helpers ────────────────────────────────────────────────────────


def _run(cmd: list[str], timeout: int = 60) -> tuple[int, str]:
    try:
        cp = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return cp.returncode, (cp.stdout or "") + (cp.stderr or "")
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 127, str(exc)


def _systemctl(*args: str, sudo: bool = False, timeout: int = 60) -> tuple[int, str]:
    cmd = ["systemctl", *args]
    rc, out = _run(cmd, timeout)
    if rc != 0 and sudo:
        rc, out = _run(["sudo", "-n", *cmd], timeout)
    return rc, out


def _show(unit: str, *props: str) -> dict[str, str]:
    rc, out = _systemctl("show", unit, *[f"-p{p}" for p in props], "--no-pager")
    res: dict[str, str] = {}
    for line in out.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            res[k] = v
    return res if rc == 0 else {"error": out.strip()[:300]}


def _pct(values: list[float], q: float) -> float | None:
    if not values:
        return None
    xs = sorted(values)
    idx = min(len(xs) - 1, max(0, int(round(q * (len(xs) - 1)))))
    return round(xs[idx], 4)


def _dist(values: list[float]) -> dict[str, Any]:
    return {
        "n": len(values),
        "median": round(statistics.median(values), 4) if values else None,
        "p90": _pct(values, 0.90),
        "max": round(max(values), 4) if values else None,
    }


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


@contextlib.contextmanager
def _flags(**env: str):
    """Set RISKIT_FEATURE_* env for one build, reloading the flag cache."""
    from src.api import feature_flags

    saved = {k: os.environ.get(k) for k in env}
    try:
        os.environ.update(env)
        feature_flags.reload()
        yield
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        feature_flags.reload()


# ── 1-3: infrastructure ──────────────────────────────────────────────────


def check_timer(app_dir: Path) -> dict[str, Any]:
    timer = _show(
        f"{UNIT}.timer", "LoadState", "ActiveState", "UnitFileState", "NextElapseUSecRealtime"
    )
    service = _show(
        f"{UNIT}.service",
        "LoadState",
        "Result",
        "ExecMainStatus",
        "ExecMainStartTimestamp",
        "ExecMainExitTimestamp",
        "ExecStart",
        "WorkingDirectory",
    )
    exec_start = service.get("ExecStart", "")
    return {
        "timerInstalled": timer.get("LoadState") == "loaded",
        "timerEnabled": timer.get("UnitFileState") == "enabled",
        "timerActive": timer.get("ActiveState") == "active",
        "nextRun": timer.get("NextElapseUSecRealtime"),
        "serviceLoaded": service.get("LoadState") == "loaded",
        "serviceLastResult": service.get("Result"),
        "serviceLastExit": service.get("ExecMainStatus"),
        "serviceLastStart": service.get("ExecMainStartTimestamp"),
        "serviceLastExitAt": service.get("ExecMainExitTimestamp"),
        "servicePointsAtDeployedCheckout": str(app_dir) in exec_start
        or str(app_dir) == service.get("WorkingDirectory"),
        "serviceRunsCollector": "fetch_signals_values.py" in exec_start,
    }


def check_session() -> dict[str, Any]:
    from src.sources import signals_auth as SA

    try:
        st = SA.status(SA.SignalsStore.open())
    except Exception as exc:  # noqa: BLE001 — report, never traceback
        return {"state": "error", "error": type(exc).__name__}
    # Health only — never a fingerprint, pool id or anything token-adjacent.
    keep = ("state", "acquisitionState", "capturedAt", "lastRenewedAt", "accessTokenExpiresAt")
    return {k: st.get(k) for k in keep}


def run_collection(timeout: int = 900) -> dict[str, Any]:
    rc, out = _systemctl("start", f"{UNIT}.service", sudo=True, timeout=timeout)
    result = _show(f"{UNIT}.service", "Result", "ExecMainStatus", "ExecMainExitTimestamp")
    return {"startExit": rc, "startOutput": out.strip()[-400:], **result}


def collector_state(app_dir: Path) -> dict[str, Any]:
    store = app_dir / "data" / "sources" / "signals"
    cs = _read_json(store / "values" / "collector_state.json") or {}
    out: dict[str, Any] = {
        "lastRunAt": cs.get("lastRunAt"),
        "lastRunOk": cs.get("lastRunOk"),
        "lastSuccessAt": cs.get("lastSuccessAt"),
        "requests": cs.get("requests"),
        "datasets": {},
    }
    for ds_dir in sorted((store / "values").glob("*/")):
        latest = _read_json(ds_dir / "latest.json")
        fetch = _read_json(ds_dir / "fetch_state.json") or {}
        if not isinstance(latest, dict):
            continue
        rel = latest  # latest.json IS the last-good release (written last)
        excluded = rel.get("excluded")
        out["datasets"][ds_dir.name] = {
            "asOf": rel.get("asOf"),
            "publicationDate": rel.get("publicationDate"),
            "fetchedAt": rel.get("fetchedAt"),
            "parserVersion": rel.get("parserVersion"),
            "contentSha256": (rel.get("contentSha256") or "")[:12],
            "previousContentSha256": (rel.get("previousContentSha256") or "")[:12] or None,
            "observations": len(rel.get("observations") or []),
            "rowCount": rel.get("rowCount"),
            "basisCounts": rel.get("basisCounts"),
            "excluded": (
                {k: (len(v) if isinstance(v, (list, dict)) else v) for k, v in excluded.items()}
                if isinstance(excluded, dict)
                else (len(excluded) if isinstance(excluded, list) else excluded)
            ),
            "boardRowCounts": rel.get("boardRowCounts"),
            "lastAttemptAt": fetch.get("lastAttemptAt"),
            "lastPublishedAt": fetch.get("lastPublishedAt"),
            "lastVerifiedUnchangedAt": fetch.get("lastVerifiedUnchangedAt"),
            "consecutiveFailures": fetch.get("consecutiveFailures"),
            "lastOutcome": fetch.get("lastOutcome"),
        }
    out["boards"] = {
        p.stem: sum(1 for _ in p.open(encoding="utf-8")) - 1
        for p in sorted((store / "board").glob("*.csv"))
    }
    return out


# ── 4-5: contract builds ─────────────────────────────────────────────────


def build_three(app_dir: Path) -> tuple[dict, dict, dict, str]:
    from src.api.data_contract import build_api_data_contract
    from src.sources.signals import newest_raw_payload

    raw, path = newest_raw_payload(app_dir)
    if raw is None:
        raise SystemExit("no raw payload on this host")

    def _build() -> dict:
        with contextlib.redirect_stdout(io.StringIO()):
            return build_api_data_contract(json.loads(json.dumps(raw)), csv_root=app_dir)

    with _flags(
        RISKIT_FEATURE_SIGNALS_ACTIVE_SOURCE="0", RISKIT_FEATURE_SIGNALS_IDP_SHARED_MARKET="0"
    ):
        champion = _build()
    with _flags(
        RISKIT_FEATURE_SIGNALS_ACTIVE_SOURCE="1", RISKIT_FEATURE_SIGNALS_IDP_SHARED_MARKET="0"
    ):
        shipped = _build()
    with _flags(
        RISKIT_FEATURE_SIGNALS_ACTIVE_SOURCE="1", RISKIT_FEATURE_SIGNALS_IDP_SHARED_MARKET="1"
    ):
        promoted = _build()
    return champion, shipped, promoted, path.name if path else "?"


def _rows(contract: Mapping[str, Any]) -> dict[str, dict]:
    return {str(r.get("displayName")): r for r in contract.get("playersArray") or []}


def _top(rows: Mapping[str, dict], n: int, positions: Iterable[str] | None = None) -> set[str]:
    pos = set(positions) if positions else None
    ranked = [
        (r.get("canonicalConsensusRank"), name)
        for name, r in rows.items()
        if isinstance(r.get("canonicalConsensusRank"), int)
        and (pos is None or str(r.get("position") or "") in pos)
    ]
    ranked.sort()
    return {name for _r, name in ranked[:n]}


def _movement(before: Mapping[str, dict], after: Mapping[str, dict], names: Iterable[str]):
    abs_moves, rel_moves, rank_moves, moved = [], [], [], 0
    for n in names:
        a, b = before.get(n, {}), after.get(n, {})
        va, vb = a.get("rankDerivedValue"), b.get("rankDerivedValue")
        if isinstance(va, (int, float)) and isinstance(vb, (int, float)):
            d = abs(float(vb) - float(va))
            abs_moves.append(d)
            rel_moves.append(d / max(1.0, float(va)))
            moved += d > 0
        ra, rb = a.get("canonicalConsensusRank"), b.get("canonicalConsensusRank")
        if isinstance(ra, int) and isinstance(rb, int):
            rank_moves.append(float(abs(rb - ra)))
    return {
        "rowsCompared": len(abs_moves),
        "rowsMoved": moved,
        "absValue": _dist(abs_moves),
        "relValue": _dist(rel_moves),
        "rank": _dist(rank_moves),
    }


def _membership(before: Mapping[str, dict], after: Mapping[str, dict], n: int, positions=None):
    b, a = _top(before, n, positions), _top(after, n, positions)
    return {"entered": sorted(a - b), "left": sorted(b - a)}


def offense_report(champion: dict, shipped: dict, collector: dict) -> dict[str, Any]:
    c, s = _rows(champion), _rows(shipped)
    offense = [n for n, r in s.items() if str(r.get("position") or "") in {"QB", "RB", "WR", "TE"}]
    joined = voted = dropped = both = 0
    pre_auth, post_auth, fam_max = [], [], 0.0
    conf_changed = 0
    for n in offense:
        r = s[n]
        meta = (r.get("sourceRankMeta") or {}).get("signalsSf")
        if "signalsSf" in (r.get("sourceNativeValues") or {}):
            joined += 1
        if isinstance(meta, dict):
            if meta.get("hampelDropped"):
                dropped += 1
            elif float(meta.get("appliedWeight") or 0) > 0:
                voted += 1
            fc = (r.get("sourceRankMeta") or {}).get("fantasyCalc")
            if (
                isinstance(fc, dict)
                and not fc.get("hampelDropped")
                and not meta.get("hampelDropped")
            ):
                both += 1
                pre = float(meta.get("preFamilyWeight") or meta.get("appliedWeight") or 0) + float(
                    fc.get("preFamilyWeight") or fc.get("appliedWeight") or 0
                )
                post = float(meta.get("appliedWeight") or 0) + float(fc.get("appliedWeight") or 0)
                pre_auth.append(pre)
                post_auth.append(post)
                fam_max = max(fam_max, post)
        if r.get("confidenceBucket") != c.get(n, {}).get("confidenceBucket"):
            conf_changed += 1
    avail = shipped.get("privateSourceAvailability", {}).get("signalsSf", {})
    return {
        "availability": avail,
        "collected": (collector.get("datasets") or {}).get("offense"),
        "boardRows": (collector.get("boards") or {}).get("signalsSf"),
        "rowsJoined": joined,
        "rowsVoted": voted,
        "rowsOutlierDropped": dropped,
        "movementAllRows": _movement(c, s, s.keys()),
        "top50": _membership(c, s, 50),
        "top200": _membership(c, s, 200),
        "confidenceBucketsChanged": conf_changed,
        "fantasyCalcFamilyCap": {
            "rowsWithBoth": both,
            "combinedPreCapAuthority": _dist(pre_auth),
            "combinedPostCapAuthority": _dist(post_auth),
            "maxCombinedPostCap": round(fam_max, 4),
        },
    }


def _family_ladders() -> dict[str, list[int]]:
    from src.api import data_contract as dc

    lad = getattr(dc, "_LAST_BRIDGE_LADDER", None)
    if lad is None:
        return {}
    return {k: list(v) for k, v in (lad.position_ladders or {}).items()}


def _candidate_b_rank(k: int, n: int, ladder: list[int]) -> float | None:
    if not ladder or n < 1:
        return None
    if n == 1 or len(ladder) == 1:
        return float(ladder[0])
    q = (k - 1) / (n - 1)
    pos = q * (len(ladder) - 1)
    lo = int(pos)
    hi = min(len(ladder) - 1, lo + 1)
    return ladder[lo] + (ladder[hi] - ladder[lo]) * (pos - lo)


def idp_report(
    shipped: dict, promoted: dict, ladders_promoted: Mapping[str, list[int]]
) -> dict[str, Any]:
    from src.canonical.player_valuation import rank_to_percentile, percentile_to_value
    from src.canonical.rank_coordinates import RANK_POOL_SHARED_MARKET, curve_for_pool

    s, p = _rows(shipped), _rows(promoted)
    hc, hs = curve_for_pool(RANK_POOL_SHARED_MARKET)
    per_family: dict[str, Any] = {}
    all_idp = [n for n, r in s.items() if str(r.get("position") or "") in {"DL", "LB", "DB"}]
    for key, fam in SIGNALS_IDP.items():
        rows = [n for n in all_idp if s[n].get("position") == fam]
        collected = sum(1 for n in rows if key in (s[n].get("sourceNativeValues") or {}))
        shadow = [(n, (s[n].get("sourceShadowMeta") or {}).get(key)) for n in rows]
        shadow = [(n, m) for n, m in shadow if isinstance(m, dict)]
        withheld: dict[str, int] = {}
        translated = 0
        disagreements = []
        b_vs_a = []
        n_family = sum(1 for _n, m in shadow if m.get("familyRank"))
        ladder = ladders_promoted.get(fam) or []
        for n, m in shadow:
            if m.get("withheldReason"):
                withheld[m["withheldReason"]] = withheld.get(m["withheldReason"], 0) + 1
                continue
            translated += 1
            others = [
                float(mm["valueContribution"])
                for kk, mm in (p[n].get("sourceRankMeta") or {}).items()
                if kk != key
                and isinstance(mm, dict)
                and not mm.get("hampelDropped")
                and isinstance(mm.get("valueContribution"), (int, float))
            ]
            if others:
                med = statistics.median(others)
                disagreements.append((abs(m["wouldContribute"] - med) / max(1.0, med), n, m, med))
            rb = _candidate_b_rank(int(m["familyRank"]), n_family, ladder)
            if rb is not None:
                vb = float(
                    percentile_to_value(
                        rank_to_percentile(rb, reference_n=500), midpoint=hc, slope=hs
                    )
                )
                b_vs_a.append(abs(vb - m["wouldContribute"]) / max(1.0, m["wouldContribute"]))
        votes = [(p[n].get("sourceRankMeta") or {}).get(key) for n in rows]
        votes = [v for v in votes if isinstance(v, dict)]
        dropped = sum(1 for v in votes if v.get("hampelDropped"))
        pools = sorted({str(v.get("rankCoordinatePool")) for v in votes})
        mismatched = sum(
            1
            for n, r in p.items()
            if key in (r.get("sourceRankMeta") or {}) and r.get("position") != fam
        )
        disagreements.sort(key=lambda t: -t[0])
        per_family[fam] = {
            "key": key,
            "collectedOnBoardRows": collected,
            "translated": translated,
            "withheld": withheld,
            "extrapolated": sum(1 for v in votes if v.get("method") == "extrapolated"),
            "familyLadderDepth": len(ladder),
            "votesWhenPromoted": len(votes),
            "outlierDroppedWhenPromoted": dropped,
            "outlierDropRate": round(dropped / len(votes), 4) if votes else None,
            "coordinatePools": pools,
            "familyMismatches": mismatched,
            "relDisagreementVsRowMedian": _dist([d for d, *_ in disagreements]),
            "candidateBvsA_relDiff": _dist(b_vs_a),
            "largestDisagreements": [
                {
                    "player": n,
                    "familyRank": m["familyRank"],
                    "translatedRank": m["translatedRank"],
                    "wouldContribute": m["wouldContribute"],
                    "rowOthersMedian": round(med),
                }
                for _d, n, m, med in disagreements[:5]
            ],
            "movementIfPromoted": _movement(s, p, rows),
        }

    def _share(rows: Mapping[str, dict], n: int) -> dict[str, int]:
        top = _top(rows, n)
        return {f: sum(1 for x in top if rows[x].get("position") == f) for f in ("DL", "LB", "DB")}

    return {
        "families": per_family,
        "combinedMovementIfPromoted": _movement(s, p, all_idp),
        "nonIdpRowsMovedIfPromoted": sum(
            1
            for n in s
            if n not in set(all_idp)
            and s[n].get("rankDerivedValue") != p.get(n, {}).get("rankDerivedValue")
        ),
        "top50": _membership(s, p, 50),
        "top100": _membership(s, p, 100),
        "top200": _membership(s, p, 200),
        "idpTop100": _membership(s, p, 100, {"DL", "LB", "DB"}),
        "familyShareOverallTop200": {"shipped": _share(s, 200), "promoted": _share(p, 200)},
        "confidenceBucketsChanged": sum(
            1
            for n in all_idp
            if s[n].get("confidenceBucket") != p.get(n, {}).get("confidenceBucket")
        ),
        "independentFamilyCountChanged": sum(
            1
            for n in all_idp
            if s[n].get("independentSourceCount") != p.get(n, {}).get("independentSourceCount")
        ),
    }


def watch_list(shipped: dict, promoted: dict) -> list[dict[str, Any]]:
    """The preregistered watch list (§10.5) — interpretation only."""
    s, p = _rows(shipped), _rows(promoted)
    picks: list[tuple[str, str]] = []
    # The #1627 case: the LB the IDPTC backbone ranks IDP #4.
    idp_by_idptc = sorted(
        (
            (-float((r.get("canonicalSiteValues") or {}).get("idpTradeCalc") or 0), n)
            for n, r in s.items()
            if r.get("position") in {"DL", "LB", "DB"}
            and float((r.get("canonicalSiteValues") or {}).get("idpTradeCalc") or 0) > 0
        )
    )
    for i, (_v, n) in enumerate(idp_by_idptc[:8], start=1):
        if s[n].get("position") == "LB":
            picks.append((n, f"idptc_idp_rank_{i}_lb"))
            break
    for key, fam in SIGNALS_IDP.items():
        by_rank = {
            int(m.get("familyRank")): n
            for n, r in s.items()
            for m in [(r.get("sourceShadowMeta") or {}).get(key)]
            if isinstance(m, dict) and m.get("familyRank")
        }
        for k, label in ((1, "elite"), (12, "mid"), (36, "deep")):
            if k in by_rank:
                picks.append((by_rank[k], f"{fam}_{label}"))
    for name in ("Myles Garrett", "Travis Hunter", "DJ Rogers"):
        if name in s:
            picks.append((name, "1627_watch"))
    out = []
    for n, why in picks:
        rs, rp = s.get(n, {}), p.get(n, {})
        metas = rp.get("sourceRankMeta") or {}
        sig = {k: metas.get(k) for k in SIGNALS_IDP if k in metas}
        others = sorted(
            int(m["valueContribution"])
            for k, m in metas.items()
            if k not in SIGNALS_IDP
            and isinstance(m, dict)
            and isinstance(m.get("valueContribution"), (int, float))
        )
        out.append(
            {
                "player": n,
                "why": why,
                "position": rs.get("position"),
                "valueShipped": rs.get("rankDerivedValue"),
                "valuePromoted": rp.get("rankDerivedValue"),
                "rankShipped": rs.get("canonicalConsensusRank"),
                "rankPromoted": rp.get("canonicalConsensusRank"),
                "shadow": rs.get("sourceShadowMeta"),
                "signalsVoteWhenPromoted": {
                    k: {
                        "effectiveRank": m.get("effectiveRank"),
                        "valueContribution": m.get("valueContribution"),
                        "hampelDropped": m.get("hampelDropped"),
                        "pool": m.get("rankCoordinatePool"),
                    }
                    for k, m in sig.items()
                },
                "otherSourceContributions": others,
            }
        )
    return out


# ── 6: completed-trade check (§10.7) ─────────────────────────────────────


def trade_check(app_dir: Path, shipped: dict, promoted: dict) -> dict[str, Any]:
    db = app_dir / "data" / "market_trades" / "underlying_trades.sqlite"
    if not db.is_file():
        return {"available": False, "reason": "ledger_not_built_on_this_host"}
    by_sid: dict[str, tuple[dict, dict]] = {}
    s, p = _rows(shipped), _rows(promoted)
    for n, r in s.items():
        sid = str(r.get("playerId") or "")
        if sid:
            by_sid[sid] = (r, p.get(n, {}))
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        rows = con.execute("SELECT disposition, record_json FROM underlying_trades").fetchall()
    finally:
        con.close()
    census: dict[str, int] = {}
    gaps_a, gaps_b = [], []
    skipped: dict[str, int] = {}
    for disposition, record in rows:
        try:
            g = json.loads(record)
        except ValueError:
            continue
        sides = g.get("sides") or []
        assets = [a for side in sides for a in (side or [])]
        has_idp = any(str(a.get("position") or "") in {"DL", "LB", "DB"} for a in assets)
        if not has_idp:
            continue
        census[str(disposition)] = census.get(str(disposition), 0) + 1
        if disposition not in ("NATIVE_COMPARABLE", "VALIDATED_TRANSFORMABLE"):
            continue
        if len(sides) != 2:
            skipped["not_two_team"] = skipped.get("not_two_team", 0) + 1
            continue
        if any(a.get("kind") != "player" for a in assets):
            skipped["has_non_player_asset"] = skipped.get("has_non_player_asset", 0) + 1
            continue
        totals_a, totals_b, ok = [0.0, 0.0], [0.0, 0.0], True
        for i, side in enumerate(sides):
            for a in side:
                sid = str(a.get("canonicalId") or "").removeprefix("player:")
                pair = by_sid.get(sid)
                va = pair[0].get("rankDerivedValue") if pair else None
                vb = pair[1].get("rankDerivedValue") if pair else None
                if not isinstance(va, (int, float)) or not isinstance(vb, (int, float)):
                    ok = False
                    break
                totals_a[i] += float(va)
                totals_b[i] += float(vb)
            if not ok:
                break
        if not ok:
            skipped["unpriced_asset"] = skipped.get("unpriced_asset", 0) + 1
            continue
        gaps_a.append(abs(totals_a[0] - totals_a[1]))
        gaps_b.append(abs(totals_b[0] - totals_b[1]))
    med_a = statistics.median(gaps_a) if gaps_a else None
    med_b = statistics.median(gaps_b) if gaps_b else None
    return {
        "available": True,
        "idpTradesByDisposition": census,
        "scored": len(gaps_a),
        "skipped": skipped,
        "medianAbsGapChampion": med_a,
        "medianAbsGapCandidateA": med_b,
        "relChange": round((med_b - med_a) / med_a, 4) if med_a else None,
        "sufficient": len(gaps_a) >= 30,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--app-dir", default=os.getcwd())
    ap.add_argument("--collect", action="store_true", help="start one real collection first")
    ap.add_argument("--skip-builds", action="store_true")
    args = ap.parse_args()
    app_dir = Path(args.app_dir).resolve()
    sys.path.insert(0, str(app_dir))
    os.chdir(app_dir)
    os.environ.setdefault("RISKIT_SIGNALS_AUTH_DIR", "/var/lib/signals-auth")

    report: dict[str, Any] = {"utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    rc, sha = _run(["git", "-C", str(app_dir), "rev-parse", "HEAD"])
    report["deployedCommit"] = sha.strip() if rc == 0 else None
    report["timer"] = check_timer(app_dir)
    report["session"] = check_session()
    if args.collect:
        report["collection"] = run_collection()
    report["collector"] = collector_state(app_dir)
    if not args.skip_builds:
        champion, shipped, promoted, payload = build_three(app_dir)
        ladders = _family_ladders()  # from the PROMOTED build (last built)
        report["payload"] = payload
        report["privateSourceAvailability"] = shipped.get("privateSourceAvailability")
        report["offense"] = offense_report(champion, shipped, report["collector"])
        report["idp"] = idp_report(shipped, promoted, ladders)
        report["idp"]["familyLadderDepths"] = {k: len(v) for k, v in ladders.items()}
        report["watchList"] = watch_list(shipped, promoted)
        report["trades"] = trade_check(app_dir, shipped, promoted)
    print(json.dumps(report, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
