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

Privacy: the repository is PUBLIC, so whatever this prints lands in a
readable Actions log and artifact.  It prints ONLY ``public_projection`` —
counts, distributions, states and per-criterion pass/fail — and refuses to
print anything carrying a player name or a per-player/vendor number
(``assert_public_safe``).  The full report (watch list, largest
disagreements, membership names) is written 0600 to the private Signals store
on the box, ``data/sources/signals/reports/``.

Read-only except ``--collect``, which starts the existing
``dynasty-signals-values.service`` once (``sudo -n systemctl start``) exactly
as its timer does.  In ``--mode legacy`` (the default, round 1) the contract
is built in-process three times (no Signals / shipped / IDP promoted) and
never published.

Round 2 (``docs/valuation/evidence/signals-idp-v2-2026-10-19/``) adds
``--mode diagnose`` (D1), ``--mode gate`` (E1 / E2) and ``--mode
native-offline`` (Tier 1a): a frozen, hashed input tree; flags read from the
local ``/api/status`` (fail closed); one subprocess per build; a deploy guard
over HEAD, its tree, the config tree and the backend receipt; verdicts from
the embedded, test-pinned ``gates.json``; and an allowlisted public
projection checked against a name blocklist.  See the "v2" section below.

Exit 0 when the checks ran (a failed CHECK is a finding printed in the JSON);
3 when a deploy moved the checkout mid-run; 2 when the script itself could
not run (only the exception's class is printed; the traceback stays in a 0600
file on the box).
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import logging
import math
import os
import re
import shutil
import sqlite3
import statistics
import subprocess
import sys
import time
import traceback
import urllib.request
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
    # Exit code + unit result only: free text from systemctl stays on the box.
    return {"startExit": rc, **result}


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


def build_three(app_dir: Path, *, promote: bool = True) -> tuple[dict, dict, dict | None, str]:
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
    # "Promoted" = every Signals IDP family released.  Since the owner
    # directive of 2026-10-19 the master ALONE releases nothing (it would
    # rebuild the shipped board and report zero movement), and Candidate A can
    # never vote: a release needs the master, every family switch AND the
    # qualified translation (Candidate F, signals_idp_xwalk_v2).  The per-mode
    # build matrix (D1 / E1, Candidate A computed in-script) is PR-D's.
    if not promote:
        return champion, shipped, None, path.name if path else "?"
    with _flags(
        RISKIT_FEATURE_SIGNALS_ACTIVE_SOURCE="1",
        RISKIT_FEATURE_SIGNALS_IDP_SHARED_MARKET="1",
        RISKIT_FEATURE_SIGNALS_IDP_DL_VOTE="1",
        RISKIT_FEATURE_SIGNALS_IDP_LB_VOTE="1",
        RISKIT_FEATURE_SIGNALS_IDP_DB_VOTE="1",
        RISKIT_FEATURE_SIGNALS_IDP_XWALK_V2="1",
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
        signed: list[float] = []
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
                signed.append((m["wouldContribute"] - med) / max(1.0, med))
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
        # A Signals family entry joined to a row we hold at ANOTHER position:
        # the scope filter drops its vote, so count it from the evidence.
        mismatched = sum(
            1
            for r in s.values()
            if key in (r.get("sourceNativeValues") or {}) and r.get("position") != fam
        )
        signals_covered = {n for n in rows if key in (s[n].get("sourceNativeValues") or {})}
        on_bridge = {
            n
            for n in rows
            if ((s[n].get("canonicalSiteValues") or {}).get("idpTradeCalc") or 0) > 0
        }
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
            # Gate 6b: a consistent shift is invisible to |disagreement|.
            "signedRelBiasMedian": (round(statistics.median(signed), 4) if signed else None),
            "signedRelBias": _dist(signed),
            "bridgeRowsSignalsLacks": len(on_bridge - signals_covered),
            "signalsRowsBridgeLacks": len(signals_covered - on_bridge),
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
        # Gate 6: offense PLAYER rows must not move; current-year slot picks
        # tethered to the merged rookie pool may, and are reported apart.
        "offensePlayerRowsMovedIfPromoted": sum(
            1
            for n, r in s.items()
            if str(r.get("position") or "") in {"QB", "RB", "WR", "TE"}
            and r.get("rankDerivedValue") != p.get(n, {}).get("rankDerivedValue")
        ),
        "pickRowsMovedIfPromoted": _movement(
            s, p, [n for n, r in s.items() if str(r.get("position") or "") == "PICK"]
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


def _va_gap(give: list[int], recv: list[int]) -> int:
    from src.trade.suggestions import _va_gap as va_gap

    return va_gap(give, recv)


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
        vals_a: list[list[int]] = [[], []]
        vals_b: list[list[int]] = [[], []]
        ok = True
        for i, side in enumerate(sides):
            for a in side:
                sid = str(a.get("canonicalId") or "").removeprefix("player:")
                pair = by_sid.get(sid)
                va = pair[0].get("rankDerivedValue") if pair else None
                vb = pair[1].get("rankDerivedValue") if pair else None
                if not isinstance(va, (int, float)) or not isinstance(vb, (int, float)):
                    ok = False
                    break
                vals_a[i].append(int(va))
                vals_b[i].append(int(vb))
            if not ok:
                break
        if not ok:
            skipped["unpriced_asset"] = skipped.get("unpriced_asset", 0) + 1
            continue
        # The canonical comparison quantity is raw + Value Adjustment, never
        # a raw sum (CLAUDE.md "Trade comparison"; §10.7).
        gaps_a.append(abs(_va_gap(vals_a[0], vals_a[1])))
        gaps_b.append(abs(_va_gap(vals_b[0], vals_b[1])))
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


# ── public projection (the ONLY thing printed / uploaded) ────────────────
#
# The repository is PUBLIC: its Actions logs and artifacts are readable by
# anyone.  The full report names players and carries Signals' per-player
# family ranks, would-be contributions and private board values, so it is
# written to the box's private store only (``_write_private_report``).  What
# leaves the box is this projection: counts, distributions and pass/fail per
# preregistered gate criterion — never a player name, a per-player number, a
# vendor value or a session timestamp.  ``assert_public_safe`` enforces it.

_PUBLIC_FORBIDDEN_KEYS = frozenset(
    {
        "player",
        "players",
        "watchList",
        "largestDisagreements",
        "entered",
        "left",
        "shadow",
        "sourceShadowMeta",
        "sourceNativeValues",
        "familyRank",
        "translatedRank",
        "wouldContribute",
        "valueContribution",
        "effectiveRank",
        "valueShipped",
        "valuePromoted",
        "rankShipped",
        "rankPromoted",
        "rankDerivedValue",
        "otherSourceContributions",
        "rowOthersMedian",
        "capturedAt",
        "lastRenewedAt",
        "accessTokenExpiresAt",
        "startOutput",
    }
)


def _membership_counts(m: Mapping[str, Any]) -> dict[str, int]:
    return {"enteredCount": len(m.get("entered") or []), "leftCount": len(m.get("left") or [])}


def _watch_outcomes(watch: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Per watch-list entry: its preregistered LABEL (never a name) and
    whether Signals' promoted vote sits within the row's other contributions
    widened by 15% (gate criterion 3 — the IDP-local inflation case)."""
    out = []
    for w in watch:
        others = w.get("otherSourceContributions") or []
        votes = [
            v
            for v in (w.get("signalsVoteWhenPromoted") or {}).values()
            if isinstance(v.get("valueContribution"), (int, float))
        ]
        within = None
        if others and votes:
            lo, hi = min(others) / 1.15, max(others) * 1.15
            within = all(lo <= float(v["valueContribution"]) <= hi for v in votes)
        out.append(
            {
                "label": w.get("why"),
                "position": w.get("position"),
                "signalsVotes": len(votes),
                "signalsOutlierDropped": sum(1 for v in votes if v.get("hampelDropped")),
                "withinRowRange15pct": within,
            }
        )
    return out


def public_projection(report: Mapping[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {
        k: report.get(k)
        for k in (
            "utc",
            "deployedCommit",
            "deployedCommitAtEnd",
            "deployIntervened",
            "timer",
            "collector",
            "payload",
        )
    }
    if "idpPromotedBuild" in report:
        out["idpPromotedBuild"] = report["idpPromotedBuild"]
    sess = report.get("session") or {}
    out["session"] = {k: sess.get(k) for k in ("state", "acquisitionState", "error") if k in sess}
    if "collection" in report:
        out["collection"] = report["collection"]
    psa = report.get("privateSourceAvailability")
    if psa is not None:
        out["privateSourceAvailability"] = psa
    off = report.get("offense")
    if off:
        out["offense"] = {
            **{k: v for k, v in off.items() if k not in ("top50", "top200")},
            "top50": _membership_counts(off.get("top50") or {}),
            "top200": _membership_counts(off.get("top200") or {}),
        }
    idp = report.get("idp")
    if idp:
        fams = {
            fam: {k: v for k, v in rep.items() if k != "largestDisagreements"}
            for fam, rep in (idp.get("families") or {}).items()
        }
        out["idp"] = {
            **{
                k: v
                for k, v in idp.items()
                if k not in ("families", "top50", "top100", "top200", "idpTop100")
            },
            "families": fams,
            **{
                k: _membership_counts(idp.get(k) or {})
                for k in ("top50", "top100", "top200", "idpTop100")
            },
        }
    if "watchList" in report:
        out["watchList_outcomes"] = _watch_outcomes(report["watchList"])
    if "trades" in report:
        out["trades"] = report["trades"]
    return out


def assert_public_safe(obj: Any, player_names: Iterable[str]) -> None:
    """Refuse to emit anything carrying a forbidden key or a player name."""
    names = {str(n) for n in player_names if n}

    def walk(x: Any, path: str) -> None:
        if isinstance(x, Mapping):
            for k, v in x.items():
                if str(k) in _PUBLIC_FORBIDDEN_KEYS:
                    raise ValueError(f"public report carries forbidden key {path}.{k}")
                if str(k) in names:
                    raise ValueError(f"public report carries a player name as a key at {path}")
                walk(v, f"{path}.{k}")
        elif isinstance(x, (list, tuple)):
            for i, v in enumerate(x):
                walk(v, f"{path}[{i}]")
        elif isinstance(x, str) and x in names:
            raise ValueError(f"public report carries a player name at {path}")

    walk(obj, "$")


def _write_private_report(app_dir: Path, report: Mapping[str, Any]) -> Path:
    """The full report, 0600 inside the private, gitignored Signals store
    (already covered by the nightly state backup)."""
    out_dir = app_dir / "data" / "sources" / "signals" / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(out_dir, 0o700)
    path = out_dir / f"onbox_{str(report.get('utc') or 'unknown').replace(':', '')}.json"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, sort_keys=True, default=str)
    return path


# ══ v2: preregistered round 2 (signals-idp-v2-2026-10-19) ═════════════════
#
# ``--mode legacy`` (the default) is the round-1 run above, unchanged except
# that its public projection is now sanitised (no max / min, quantiles only
# at n >= 20).  The other modes implement the preregistration in
# ``docs/valuation/evidence/signals-idp-v2-2026-10-19/``:
#
# * ``diagnose`` (D1) — Candidate A, N0 and the haircut / Hampel / coverage /
#   Hill-and-pick decompositions on a tree pinned to IDP release
#   ``6ec7bff6bd11``.  It computes NO Candidate F, H or G statistic (the D1
#   quarantine) and refuses any other release.
# * ``gate`` (E1 / E2) — Candidate F per family in isolated builds, the
#   combined build, the negative controls and the verdicts.  It needs the
#   per-family flags of the implementation unit; until they are registered
#   in the deployed code every F build is refused (fail closed).
# * ``native-offline`` (Tier 1a) — the private release JSONs only, no
#   network and no build.
#
# Hardening shared by every v2 mode: inputs are copied into a frozen private
# tree with sha256 pins; flags come from the local ``/api/status`` (never
# ``.env``) and the run fails closed without them; every build runs in its
# own subprocess (module caches carry state between in-process builds) under
# ``nice`` / ``ionice``; a deploy that moves the checkout, the config tree or
# the backend receipt voids the run; the public projection is an explicit
# allowlist (``gates.json`` ``privacy.publicAllow``) checked against a name
# blocklist; standard error and tracebacks stay in a 0600 file on the box.

MODES = ("legacy", "diagnose", "gate", "native-offline")

#: The preregistered gates, embedded verbatim because only this file is
#: uploaded to the box.  ``tests/scripts/test_verify_signals_onbox_v2.py``
#: pins it to the committed ``gates.json``.
_GATES_JSON = r"""{
  "schema": "signals-idp-v2-gates/1",
  "preregistrationId": "signals-idp-v2-2026-10-19",
  "authority": "owner directive 2026-10-19 'Get Signals Fantasy IDP Fully Voting' (docs/owner/SIGNALS_IDP_VOTING_2026-10-19.md, release train 13)",
  "frozenAt": "the merge of this file to main; evaluation releases are defined against that merge time",
  "families": ["DL", "LB", "DB"],
  "familyKeys": {"DL": "signalsIdpDl", "LB": "signalsIdpLb", "DB": "signalsIdpDb"},
  "bridgeSource": "idpTradeCalc",
  "independentReference": "draftSharksIdp",
  "candidates": {
    "A": {
      "id": "signals-idp-A-family-ladder-v1",
      "status": "FAILED_ROUND_1",
      "promotable": false,
      "role": "comparison baseline and negative control NC1; never redefined"
    },
    "F": {
      "id": "signals-idp-F-coverage-aligned-v1",
      "status": "PREREGISTERED",
      "promotable": true,
      "vote": "for p in M_F in a tie group of size t starting at competition rank k: r_F(p) = mean(L^M[k-1 .. k+t-2]); vote = Hill_GLOBAL(r_F(p)) through the voting path's own pricing helper, fractional rank passed directly (never translate_position_rank); Signals-only rows withheld",
      "contributes": "within_family_order",
      "levelSource": "idpTradeCalc"
    },
    "N": {
      "id": "signals-idp-N-native-league-value-v1",
      "status": "SLOT_RESERVED",
      "promotable": "only if admitted under admissionRules, then under the same gates plus E2 rank-space consistency and the information diagnostic",
      "admissionRules": [
        "server observation reachable through an operation the shipped app itself issues",
        "covers DT, DE, LB, CB and S at or above the family board floors",
        "inputs are scoring and lineup settings only, no roster dependence (keyable by scoring_fingerprint); otherwise leagueKey-scoped and rejected",
        "deterministic across two reads at least 120 s apart; changes only with a publication",
        "S1 not falsified: family tops not within 5% of each other and normalised curves not within +/-5% at k = 12 and k = 24",
        "a dynasty trade value, not a projection: an age/horizon gradient consistent with dynasty value, rookies priced, DYNASTY game type proven per endpoint",
        "lineage established by observed code paths; the IDP half is not a FantasyCalc or KTC derivative",
        "licence: the attestation scope covers canonical use, else owner decision 6"
      ]
    },
    "diagnosticOnly": {
      "H": "smoothed geometric moving-window ranks (window 0.05 m)",
      "G": "F plus Signals-only rows interpolated between matched neighbours",
      "N0": "bridge-null voter: the bridge's own within-family order and coverage, priced as A (negative control NC4)",
      "K": "consensus-level (circular)",
      "I": "isotonic PAVA fit (in-sample)",
      "J": "Draft Sharks IDP as reference (the information diagnostic)",
      "B": "proportional percentile (existing diagnostic)",
      "FxDeepTail": "F priced with idp_deep_tail_native_challenger on"
    },
    "candidate4CompletedTrades": {
      "status": "UNSUPPORTED_2026",
      "reentry": "a census of IDP NATIVE_COMPARABLE / VALIDATED_TRANSFORMABLE underlying trades in data/market_trades/underlying_trades.sqlite (Sharp cohort included) of at least 30 per family with concentration and Kish tooling, plus a validated IDP-scoring translator or multi-season accumulation"
    }
  },
  "definitions": {
    "R_F": "board rows at position F with canonicalSiteValues[bridgeSource] > 0",
    "c(p)": "p's slot in family_ladder(F), ordered by (-v_beta, lower(pinned name key))",
    "S_F": "Signals phase-1 eligible set (a native value on the family board, the row held at position F)",
    "sigma": "Signals' order: competition ranks of the native value within the family",
    "M_F": "S_F intersect R_F; m = |M_F|; k_M(p) is p's competition rank within M_F",
    "L^M": "ascending list of c(q) for q in M_F",
    "Hill_G": "GLOBAL shared_market pricing through the voting path's own helper",
    "rookieRule": "Signals IDP rookie rows are withheld this round (rookie_unobservable_by_basis)",
    "withheldReasons": [
      "unmatched_in_reference",
      "family_positions_undefined_multi_bridge",
      "reference_withheld",
      "sleeper_id_contradiction",
      "not_a_within_family_rank",
      "family_mismatch",
      "rookie_unobservable_by_basis"
    ],
    "multiBridge": "more than one bridge contributor withholds every Signals vote (family_positions_undefined_multi_bridge) and fires an alert",
    "relativeMovement": "|v_variant - v_champion| / max(1, v_champion) per row",
    "newlyPricedRelativeMovement": 1.0,
    "newlyPricedNote": "a row priced in one build and unpriced in the other is counted as a 100% move (conservative) and also counted separately",
    "correctedPanel": "other sources on the row with appliedWeight > 0, not hampelDropped, contributedToBlend not False, numeric valueContribution; at least 2 required; unweighted median",
    "scriptPanel": "other sources on the row that are not hampelDropped with numeric valueContribution; at least 1 (the round-1 instrument, always printed)",
    "idpBands": {"elite": [1, 100], "starter": [101, 250], "bench": [251, 500], "deep": [501, null]},
    "combinedRankBands": {"top": [1, 250], "mid": [251, 500], "tail": [501, null]}
  },
  "evaluationReleases": {
    "baselineRelease": "6ec7bff6bd11",
    "R1": "the first Signals IDP release with asOf after the merge of this preregistration, contentSha256 != baselineRelease, and at least minRankChangeShare of matched rows changing within-family rank against baselineRelease; otherwise wait for the next release",
    "R2": "the next release after R1 meeting the same rule against R1",
    "minRankChangeShare": 0.10,
    "requireAgreement": ["R1", "R2"],
    "deadline": "2026-11-16",
    "deadlineOutcome": "BLOCKED: no_qualifying_release"
  },
  "d1": {
    "mode": "diagnose",
    "idpReleasePin": "6ec7bff6bd11",
    "offenseReleasePin": "05e513c37a91",
    "payloadRef": "f9d1994e59",
    "forbiddenCandidates": ["F", "H", "G"],
    "refuseOtherRelease": true
  },
  "engineering": [
    {"id": "G1", "criterion": "no Signals-created cross-family order", "metric": "createdCrossFamilyOrder", "op": "eq", "threshold": 0},
    {"id": "G2", "criterion": "every Signals vote in shared_market coordinates", "metric": "nonSharedMarketVotes", "op": "eq", "threshold": 0},
    {"id": "G8", "criterion": "tests: missing ladder, bad identity, unsupported family, stale source", "metric": "ci", "op": "ci", "threshold": null},
    {"id": "INT-DUP", "criterion": "duplicate Signals observations on a row", "metric": "duplicateSignalsObservationsOnRow", "op": "eq", "threshold": 0},
    {"id": "INT-SID", "criterion": "sleeper_id_contradiction among voting rows", "metric": "sidContradictionsVoting", "op": "eq", "threshold": 0},
    {"id": "INT-FAM", "criterion": "family-mismatched rows voting", "metric": "familyMismatchesVoting", "op": "eq", "threshold": 0},
    {"id": "INT-STALE", "criterion": "stale or invalid observations voting", "metric": "staleOrInvalidVoting", "op": "eq", "threshold": 0},
    {"id": "INT-SHADOW", "criterion": "shadow wouldContribute differs from the promoted valueContribution", "metric": "shadowPromotedMismatches", "op": "eq", "threshold": 0},
    {"id": "INT-EXTRAP", "criterion": "extrapolated votes", "metric": "extrapolatedVotes", "op": "eq", "threshold": 0},
    {"id": "INT-ROOKIE", "criterion": "rookie votes", "metric": "rookieVotes", "op": "eq", "threshold": 0},
    {"id": "G6b-structural", "criterion": "|b_F - b_N0| on the corrected panel; verifies coverage and permutation integrity under F; NOT evidence of valuation quality", "metric": "g6bStructuralGap", "op": "report", "threshold": 0.05}
  ],
  "empirical": [
    {"id": "G3", "criterion": "watch-list entries within the row range widened by 15%", "metric": "watchWithinRange", "op": "all", "threshold": null, "publicOnlyWhenEntriesAtLeast": 5},
    {"id": "G4", "criterion": "Signals' own Hampel drops", "metric": "ownHampelDropRate", "op": "le", "threshold": 0.05},
    {"id": "G4-X-elite-starter", "criterion": "Hampel drops of the independent-level anchor (draftSharksIdp) caused by Signals in the elite and starter bands", "metric": "causedIndependentAnchorDropsEliteStarter", "op": "eq", "threshold": 0},
    {"id": "G4-X-total", "criterion": "total Hampel drops caused by Signals in other sources, as a share of the family's voting observations", "metric": "causedDropShare", "op": "le", "threshold": 0.05},
    {"id": "G4-X-explained", "criterion": "every caused drop explained by its filter stamp", "metric": "causedDropsUnexplained", "op": "eq", "threshold": 0},
    {"id": "G5", "criterion": "family share of the overall top 200 moves", "metric": "top200ShareDeltaPp", "op": "abs_le", "threshold": 3.0},
    {"id": "G6-median", "criterion": "IDP relative movement median, served configuration, newly priced rows counted", "metric": "idpRelMovementMedian", "op": "le", "threshold": 0.02},
    {"id": "G6-p90", "criterion": "IDP relative movement p90, served configuration, newly priced rows counted", "metric": "idpRelMovementP90", "op": "le", "threshold": 0.08},
    {"id": "G6-offense", "criterion": "offense player rows moved (hard FAIL until the #1817 two-way fix is deployed)", "metric": "offensePlayerRowsMoved", "op": "eq", "threshold": 0},
    {"id": "G6b", "criterion": "per-family signed median of (vote - corrected-panel median) / corrected-panel median, at least 2 other voting sources", "metric": "signedBiasCorrectedPanel", "op": "abs_le", "threshold": 0.05},
    {"id": "G6-shift", "criterion": "board-level per-family mean shift; absolute and relative movement by mechanism class", "metric": "familyMeanShift", "op": "report", "threshold": null},
    {"id": "CONF", "criterion": "confidence transition matrix and unjustified-inflation attribution", "metric": "confidence", "op": "report", "threshold": null},
    {"id": "G7", "criterion": "independent fresh-context review, which must classify Signals' IDP horizon (dynasty vs seasonal)", "metric": "review", "op": "external", "threshold": null},
    {"id": "G9", "criterion": "completed trades: never presented as validation; INSUFFICIENT below the minimum", "metric": "trades", "op": "insufficient_below", "threshold": 30}
  ],
  "dispositions": {
    "panelDefects": "measurement correction (corrected panel); the script-panel number is always printed; needs owner decision 4",
    "borrowedLevelBias": "owner decision 1: (a) signed-bias gates not applicable to sources without a level, consequences gated instead (G4-X, G6-shift, confidence), or (b) G6b stays binding",
    "hillMisfitAndPickCoordinate": "reported; repair belongs to the Hill and bridge owners",
    "dlHaircutFlips": "owner decision 2: wait for the #1817 haircut finding or accept the flips explicitly; no new served haircut bound",
    "hampelKnockOn": "gated by G4-X; the filter belongs to the outlier lane",
    "allowed": ["REPAIRED", "MEASUREMENT_CORRECTION", "OWNER_ACCEPTED"]
  },
  "negativeControls": [
    {"id": "NC1", "control": "Candidate A at DB", "kind": "build"},
    {"id": "NC2", "control": "seeded random within-family permutation of Signals' matched order, median over draws, panel held fixed", "kind": "in_script", "draws": 200, "seed": 20261019},
    {"id": "NC3", "control": "fully reversed within-family order, panel held fixed", "kind": "in_script"},
    {"id": "NC4", "control": "N0 itself", "kind": "build"}
  ],
  "negativeControlRule": "each control must FAIL the check a revised or decomposed statistic is used for; if a control passes, that statistic is VOID for the round",
  "negativeControlScope": "NC2, NC3 and NC4 per family (void that family); NC1 at DB (voids every family); a control passes when |median| <= the statistic's threshold on at least minCell rows",
  "premises": [
    {"id": "P1", "premise": "haircut flips account for at least 80% of DL rows at or above the DL relative-movement p90 on the box board", "metric": "dlP90HaircutFlipShare", "op": "ge", "threshold": 0.80},
    {"id": "P2", "premise": "the box-board N0 LB and DB floor on the corrected panel lies within [-6%, 0%]", "metric": "n0SignedBiasCorrectedPanel", "op": "within", "threshold": [-0.06, 0.0]},
    {"id": "P3", "premise": "IDP Show is zero-weight on the evaluation board", "metric": "idpShowAppliedWeightRows", "op": "eq", "threshold": 0}
  ],
  "premiseRule": "a falsified premise voids every disposition that depends on it",
  "information": {
    "target": "draftSharksIdp",
    "builds": ["leave-target-out without the Signals family", "leave-target-out with the Signals family", "leave-target-out with N0 in place of Signals"],
    "minMatchedRowsPerFamily": 20,
    "minDiscordantPairs": 50,
    "spearmanMargin": 0.01,
    "sideWithSignalsPositive": 0.55,
    "sideWithSignalsNegative": 0.45,
    "verdicts": ["POSITIVE", "NEUTRAL", "NEGATIVE", "INSUFFICIENT"],
    "rule": "POSITIVE when the with-Signals Spearman against the target beats both the without-Signals and the N0 build by at least spearmanMargin AND Draft Sharks sides with Signals on at least sideWithSignalsPositive of at least minDiscordantPairs pairs where Signals and the bridge disagree; NEGATIVE when both Spearman deltas are at most -spearmanMargin AND the side-with share is at most sideWithSignalsNegative; INSUFFICIENT below minMatchedRowsPerFamily or minDiscordantPairs; otherwise NEUTRAL.  An information metric, never an agreement penalty",
    "activationWithoutPositive": "owner decision 3"
  },
  "reproduction": {
    "roundOneRun": "39066961689",
    "tolerances": {"count": "exact", "percentagePoints": 1.0, "tailRelative": 0.10},
    "figures": [
      {"id": "idpRowsMoving", "observed": 343, "of": 396, "kind": "count"},
      {"id": "idpRelMovementMedian", "observed": 0.0137, "kind": "percentage"},
      {"id": "idpRelMovementP90", "observed": 0.3007, "kind": "tail"},
      {"id": "signalsOutlierDropRate", "observed": 0.029, "kind": "percentage"},
      {"id": "lbSignedBias", "observed": -0.0624, "kind": "percentage"},
      {"id": "dbSignedBias", "observed": -0.0995, "kind": "percentage"},
      {"id": "offensePlayerRowsMoved", "observed": 1, "kind": "count"},
      {"id": "scorableIdpTrades", "observed": 0, "kind": "count"}
    ],
    "verdicts": ["REPRODUCED", "NOT_REPRODUCED", "EXPLAINED"]
  },
  "verdictValues": ["PASS", "FAIL", "INSUFFICIENT", "VOID", "REPORTED", "EXTERNAL"],
  "privacy": {
    "minCell": 20,
    "significantFigures": 2,
    "forbidMaxMin": true,
    "watchListPublic": "counts only, {entries, withinRange}, and only when entries >= 5",
    "publicAllow": [
      "schema",
      "mode",
      "matrixPart",
      "utc",
      "preregistrationId",
      "gatesSha256",
      "error",
      "deploy.**",
      "memory.**",
      "inputs.freezeManifestSha256",
      "inputs.fileCount",
      "inputs.flagsSource",
      "inputs.flagsSnapshotSha256",
      "inputs.payloadRef",
      "inputs.payloadName",
      "inputs.idpReleasePin",
      "inputs.idpReleaseFound",
      "inputs.offenseReleasePin",
      "inputs.offenseReleaseFound",
      "inputs.treeKind",
      "variants.*.status",
      "variants.*.refusedFlag",
      "variants.*.voteStates.**",
      "variants.*.voteStateAsIntended",
      "variants.*.contractHealthOk",
      "variants.*.bridgeContributors",
      "families.*.**",
      "board.**",
      "verdicts.**",
      "reproduction.**",
      "premises.**",
      "negativeControls.**",
      "information.**",
      "release.**",
      "coordinates.**",
      "nativeOffline.**",
      "trades.**"
    ]
  }
}
"""
GATES: dict[str, Any] = json.loads(_GATES_JSON)

FAMILIES = tuple(GATES["families"])
FAMILY_KEYS: dict[str, str] = dict(GATES["familyKeys"])
BRIDGE = str(GATES["bridgeSource"])
REFERENCE = str(GATES["independentReference"])
IDP_SHOW = "idpShowCombined"
OFFENSE_POSITIONS = frozenset({"QB", "RB", "WR", "TE"})
IDP_POSITIONS = frozenset(FAMILIES)
CANDIDATE_F_ID = str(GATES["candidates"]["F"]["id"])
MIN_CELL = int(GATES["privacy"]["minCell"])
SIG_FIGS = int(GATES["privacy"]["significantFigures"])

ACTIVE_FLAG = "signals_active_source"
MASTER_FLAG = "signals_idp_shared_market"
XWALK_FLAG = "signals_idp_xwalk_v2"
DEEP_TAIL_FLAG = "idp_deep_tail_native_challenger"
FAMILY_FLAGS = {
    "DL": "signals_idp_dl_vote",
    "LB": "signals_idp_lb_vote",
    "DB": "signals_idp_db_vote",
}

STATUS_URL = "http://127.0.0.1:8000/api/status"
FREEZE_PREFIX = "freeze-"
FREEZE_RETENTION_HOURS = 24
MIN_MEM_AVAILABLE_MB = 1536
CHILD_TIMEOUT_SECONDS = 1200
#: The job allows 30 minutes; builds stop starting after this budget so a
#: partial report is still printed and uploaded rather than killed silently.
TIME_BUDGET_SECONDS = 25 * 60
_DEADLINE: float | None = None
MATRIX_PARTS = ("all", "core", "extra")
_EXTRA_SUFFIXES = ("_noRetention", "_hampelOff", "_noRef", "_deepTail")
#: The only module constants a diagnostic build may override (in its own
#: subprocess, never the served process): the haircut retention and the
#: Hampel minimum, for the no-retention and Hampel-off counterfactuals.
PATCHABLE_CONSTANTS = frozenset({"_SINGLE_SOURCE_VALUE_RETENTION", "_HAMPEL_MIN_N"})
HAMPEL_OFF_MIN_N = 10**9

_META_FIELDS = (
    "valueContribution",
    "appliedWeight",
    "hampelDropped",
    "contributedToBlend",
    "method",
    "rankCoordinatePool",
    "effectiveRank",
    "rawRank",
    "isAnchor",
    "valueContributionPath",
)
_SHADOW_FIELDS = (
    "familyRank",
    "translatedRank",
    "wouldContribute",
    "withheldReason",
    "candidate",
    "levelSource",
    "contributes",
)


# ── privacy: sanitiser, allowlist, name blocklist, private stderr ────────

_QUANTILE_KEYS = frozenset({"median", "mean", "p10", "p25", "p75", "p90", "p95", "p99"})
_MAXMIN_KEY = re.compile(r"^(max|min)($|[A-Z0-9_])")


def _sig(x: Any, figs: int = SIG_FIGS) -> Any:
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return x
    if not math.isfinite(float(x)) or float(x) == 0.0:
        return float(x)
    return float(f"{float(x):.{figs}g}")


def sanitize_public(obj: Any, *, min_cell: int = MIN_CELL, figs: int = SIG_FIGS) -> Any:
    """Drop every ``max`` / ``min`` key and suppress quantiles of small cells.

    A dict carrying an integer ``n`` and any quantile key is a distribution:
    below ``min_cell`` its quantiles become ``None`` and it is marked
    ``suppressed``; otherwise they are rounded to ``figs`` significant
    figures.  Applied to every public projection, legacy included."""
    if isinstance(obj, Mapping):
        n = obj.get("n")
        is_dist = (
            isinstance(n, int) and not isinstance(n, bool) and any(k in obj for k in _QUANTILE_KEYS)
        )
        out: dict[str, Any] = {}
        for k, v in obj.items():
            if _MAXMIN_KEY.match(str(k)):
                continue
            if is_dist and k in _QUANTILE_KEYS:
                out[k] = None if n < min_cell else _sig(v, figs)
            else:
                out[k] = sanitize_public(v, min_cell=min_cell, figs=figs)
        if is_dist and n < min_cell:
            out["suppressed"] = f"n<{min_cell}"
        return out
    if isinstance(obj, (list, tuple)):
        return [sanitize_public(v, min_cell=min_cell, figs=figs) for v in obj]
    return obj


def _pattern_match(path: tuple[str, ...], pat: tuple[str, ...]) -> bool:
    if pat and pat[-1] == "**":
        head = pat[:-1]
        return len(path) >= len(head) and all(h in ("*", s) for h, s in zip(head, path))
    return len(path) == len(pat) and all(h in ("*", s) for h, s in zip(pat, path))


def _pattern_prefix(path: tuple[str, ...], pat: tuple[str, ...]) -> bool:
    head = pat[:-1] if pat and pat[-1] == "**" else pat
    if len(path) >= len(head) and not (pat and pat[-1] == "**"):
        return False
    return all(h in ("*", s) for h, s in zip(head, path))


def project_allowlist(obj: Mapping[str, Any], patterns: Iterable[str]) -> dict[str, Any]:
    """Only the key paths ``patterns`` name (``*`` = one segment, a trailing
    ``**`` = the whole subtree).  Anything not named is dropped."""
    pats = [tuple(p.split(".")) for p in patterns]

    def walk(node: Mapping[str, Any], path: tuple[str, ...]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for k, v in node.items():
            p = (*path, str(k))
            if any(_pattern_match(p, pat) for pat in pats):
                out[str(k)] = v
            elif isinstance(v, Mapping) and any(_pattern_prefix(p, pat) for pat in pats):
                sub = walk(v, p)
                if sub:
                    out[str(k)] = sub
        return out

    return walk(obj, ())


def collect_private_names(app_dir: Path, rows: Iterable[Mapping[str, Any]]) -> set[str]:
    """Every player name that could identify a private observation: board
    display names (picks excluded) and every name in the private Signals
    release JSONs."""
    names = {
        str(r.get("n") or r.get("displayName") or "")
        for r in rows
        if str(r.get("pos") or r.get("position") or "") != "PICK"
    }
    values = app_dir / "data" / "sources" / "signals" / "values"
    for path in sorted(values.glob("*/releases/*.json")) + sorted(values.glob("*/latest.json")):
        rel = _read_json(path)
        if not isinstance(rel, dict):
            continue
        for coll in ("observations", "boardRows"):
            for o in rel.get(coll) or []:
                if isinstance(o, Mapping):
                    for field in ("name", "canonicalName"):
                        if o.get(field):
                            names.add(str(o[field]))
    return {n.strip() for n in names if n and n.strip()}


def assert_public_safe_v2(obj: Any, names: Iterable[str]) -> None:
    """Forbidden keys anywhere, and no name as a case-insensitive,
    word-bounded substring of anything printed.  The error never carries
    the name it found."""
    assert_public_safe(obj, [])
    text = json.dumps(obj, sort_keys=True, default=str)
    ordered = sorted({n for n in names if len(n) >= 3}, key=len, reverse=True)
    for i in range(0, len(ordered), 400):
        chunk = "|".join(re.escape(n) for n in ordered[i : i + 400])
        if re.search(rf"(?<![A-Za-z0-9])(?:{chunk})(?![A-Za-z0-9])", text, re.IGNORECASE):
            raise ValueError("public report carries a player name")


def _public_excepthook(exc_type, exc, tb) -> None:  # noqa: ANN001 — hook signature
    """An uncaught exception prints only its class; the traceback (which
    can carry a name or a value) stays in the private log."""
    with contextlib.suppress(Exception):
        traceback.print_exception(exc_type, exc, tb, file=sys.stderr)
    sys.__stdout__.write(json.dumps({"error": exc_type.__name__}) + "\n")


@contextlib.contextmanager
def private_stderr(app_dir: Path, utc: str):
    """Standard error, the root logger and tracebacks go to a 0600 file in
    the private Signals store for the duration of the run."""
    reports = app_dir / "data" / "sources" / "signals" / "reports"
    try:
        reports.mkdir(parents=True, exist_ok=True)
        os.chmod(reports, 0o700)
        path = reports / f"verify-stderr-{utc.replace(':', '')}.log"
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        fh = os.fdopen(fd, "a", encoding="utf-8")
    except OSError:
        path = None
        fh = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115 — closed below
    root = logging.getLogger()
    saved = (sys.stderr, sys.excepthook, list(root.handlers))
    handler = logging.StreamHandler(fh)
    root.handlers = [handler]
    sys.stderr = fh
    sys.excepthook = _public_excepthook
    try:
        yield path
    finally:
        sys.stderr, sys.excepthook, root.handlers = saved[0], saved[1], saved[2]
        fh.close()


# ── deploy guard, served flags, memory ───────────────────────────────────


def _sha256_bytes(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def deploy_fingerprint(app_dir: Path) -> dict[str, Any]:
    """HEAD, its tree, the working config/ tree and the backend artifact
    receipt — a deploy that lands mid-run changes at least one."""
    rc, head = _run(["git", "-C", str(app_dir), "rev-parse", "HEAD"])
    rc_t, tree = _run(["git", "-C", str(app_dir), "rev-parse", "HEAD^{tree}"])
    h = hashlib.sha256()
    cfg = app_dir / "config"
    for p in sorted(cfg.rglob("*")) if cfg.is_dir() else []:
        if p.is_file():
            h.update(str(p.relative_to(cfg)).encode())
            h.update(b"\0")
            h.update(_sha256_file(p).encode())
    receipt = app_dir / ".backend-artifact-receipt.json"
    return {
        "head": head.strip() if rc == 0 else None,
        "tree": tree.strip() if rc_t == 0 else None,
        "config": h.hexdigest(),
        "receipt": _sha256_file(receipt) if receipt.is_file() else None,
    }


def compare_fingerprints(start: Mapping[str, Any], end: Mapping[str, Any]) -> dict[str, Any]:
    changed = {
        "headChanged": start.get("head") != end.get("head"),
        "treeChanged": start.get("tree") != end.get("tree"),
        "configChanged": start.get("config") != end.get("config"),
        "receiptChanged": start.get("receipt") != end.get("receipt"),
    }
    return {
        "deployedCommit": start.get("head"),
        "deployedCommitAtEnd": end.get("head"),
        **changed,
        "intervened": start.get("head") is None or any(changed.values()),
    }


def fetch_status(url: str = STATUS_URL, timeout: float = 10.0) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310 — loopback only
        return json.loads(resp.read().decode("utf-8"))


def served_flags(status: Mapping[str, Any]) -> dict[str, bool]:
    """The SERVED process's effective flags.  Fails closed: the verifier's
    own environment is not the service's (systemd loads ``.env``), and
    guessing a flag would measure a configuration nobody serves."""
    ff = status.get("featureFlags")
    if not isinstance(ff, Mapping) or not ff:
        raise RuntimeError("served_feature_flags_unreadable")
    out: dict[str, bool] = {}
    for name, val in ff.items():
        if isinstance(val, Mapping):
            if not isinstance(val.get("enabled"), bool):
                raise RuntimeError("served_feature_flags_unreadable")
            out[str(name)] = bool(val["enabled"])
        elif isinstance(val, bool):
            out[str(name)] = val
        else:
            raise RuntimeError("served_feature_flags_unreadable")
    return out


def mem_available_mb() -> int | None:
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) // 1024
    except (OSError, ValueError, IndexError):
        return None
    return None


# ── frozen input tree ────────────────────────────────────────────────────


def sweep_freezes(parent: Path, now: float, retention_hours: float = FREEZE_RETENTION_HOURS) -> int:
    """Remove frozen trees older than the retention (they hold private
    copies; the run's private report keeps their manifest)."""
    removed = 0
    for d in parent.glob(f"{FREEZE_PREFIX}*") if parent.is_dir() else []:
        try:
            if d.is_dir() and now - d.stat().st_mtime > retention_hours * 3600:
                shutil.rmtree(d)
                removed += 1
        except OSError:
            continue
    return removed


def _git_show(app_dir: Path, ref: str, rel: str) -> bytes | None:
    try:
        cp = subprocess.run(
            ["git", "-C", str(app_dir), "show", f"{ref}:{rel}"],
            capture_output=True,
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return cp.stdout if cp.returncode == 0 else None


def _git_ls(app_dir: Path, ref: str, rel: str) -> list[str]:
    rc, out = _run(["git", "-C", str(app_dir), "ls-tree", "-r", "--name-only", ref, "--", rel])
    return [line.strip() for line in out.splitlines() if line.strip()] if rc == 0 else []


def _write_private(path: Path, blob: bytes, mtime: float | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as fh:
        fh.write(blob)
    if mtime is not None:
        os.utime(path, (mtime, mtime))


def find_release(app_dir: Path, dataset: str, pin: str) -> tuple[dict | None, Path | None]:
    """The private release whose contentSha256 starts with ``pin``."""
    rel_dir = app_dir / "data" / "sources" / "signals" / "values" / dataset / "releases"
    for path in sorted(rel_dir.glob(f"{pin}*.json")) if rel_dir.is_dir() else []:
        rel = _read_json(path)
        if isinstance(rel, dict) and str(rel.get("contentSha256") or "").startswith(pin):
            return rel, path
    return None, None


def render_release_boards(release: Mapping[str, Any], dataset: str) -> dict[str, list[dict]]:
    """One board per registry key, rendered from the release JSON exactly as
    the collector renders it (``build_board_rows`` output -> CSV rows)."""
    from src.sources import signals as S  # noqa: PLC0415

    spec = S.VALUE_DATASETS[dataset]
    boards: dict[str, list[dict]] = {k: [] for k in spec.output_keys()}
    for r in release.get("boardRows") or []:
        key = spec.board_key_for(r)
        if key in boards:
            boards[key].append(dict(r))
    return boards


def _board_rel(key: str) -> str:
    return f"data/sources/signals/board/{key}.csv"


def build_freeze(
    app_dir: Path,
    freeze: Path,
    *,
    payload_ref: str | None,
    idp_pin: str | None,
    offense_pin: str | None,
) -> dict[str, Any]:
    """Copy (or, with ``payload_ref``, materialise from git) every input the
    contract build reads into ``freeze/tree``, render pinned Signals boards
    from their release JSONs, and record a sha256 per file.

    Private stores are always the box's own (git never holds them).  With a
    ``payload_ref`` the box's current ``signals*`` scrape-state stamps are
    copied into the historical tree (disclosed: git holds none)."""
    from src.api.data_contract import _SOURCE_CSV_PATHS  # noqa: PLC0415
    from src.sources import signals as S  # noqa: PLC0415

    tree = freeze / "tree"
    tree.mkdir(parents=True, exist_ok=True)
    info: dict[str, Any] = {"treeKind": "ref" if payload_ref else "served"}
    commit_time: float | None = None
    if payload_ref:
        rc, out = _run(["git", "-C", str(app_dir), "log", "-1", "--format=%ct", payload_ref])
        if rc != 0 or not out.strip().isdigit():
            raise RuntimeError("payload_ref_unavailable")
        commit_time = float(out.strip())
    private_rels: set[str] = set()
    rels: set[str] = set()
    for cfg in _SOURCE_CSV_PATHS.values():
        if isinstance(cfg, str):
            rels.add(cfg)
        elif isinstance(cfg, dict):
            if cfg.get("path"):
                rels.add(str(cfg["path"]))
                if cfg.get("private_marker"):
                    private_rels.add(str(cfg["path"]))
            if cfg.get("private_marker"):
                rels.add(str(cfg["private_marker"]))
                private_rels.add(str(cfg["private_marker"]))
    for rel in sorted(rels):
        dst = tree / rel
        if payload_ref and rel not in private_rels and not rel.startswith("data/sources/"):
            blob = _git_show(app_dir, payload_ref, rel)
            if blob is not None:
                _write_private(dst, blob, commit_time)
        elif (app_dir / rel).is_file():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(app_dir / rel, dst)
    state_src = app_dir / "data" / "scrape_state"
    if payload_ref:
        for rel in _git_ls(app_dir, payload_ref, "data/scrape_state"):
            blob = _git_show(app_dir, payload_ref, rel)
            if blob is not None:
                _write_private(tree / rel, blob, commit_time)
        for p in sorted(state_src.glob("signals*")) if state_src.is_dir() else []:
            shutil.copy2(p, tree / "data" / "scrape_state" / p.name)
    elif state_src.is_dir():
        shutil.copytree(state_src, tree / "data" / "scrape_state", dirs_exist_ok=True)
    # The raw payload.
    if payload_ref:
        names = sorted(
            n for n in _git_ls(app_dir, payload_ref, "exports/latest") if "dynasty_data_" in n
        )
        if not names:
            raise RuntimeError("payload_ref_has_no_payload")
        blob = _git_show(app_dir, payload_ref, names[-1])
        if blob is None:
            raise RuntimeError("payload_ref_unavailable")
        payload_path = tree / "data" / Path(names[-1]).name
        _write_private(payload_path, blob, commit_time)
    else:
        _raw, src = S.newest_raw_payload(app_dir)
        if src is None:
            raise RuntimeError("no_raw_payload")
        payload_path = tree / "data" / src.name
        payload_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, payload_path)
    info["payloadName"] = payload_path.name
    info["payloadPath"] = str(payload_path)
    # Pinned Signals releases, rendered from their JSONs.
    for dataset, pin, label in (("idp", idp_pin, "idp"), ("offense", offense_pin, "offense")):
        if not pin:
            continue
        info[f"{label}ReleasePin"] = pin
        release, _path = find_release(app_dir, dataset, pin)
        info[f"{label}ReleaseFound"] = release is not None
        if release is None:
            continue
        info[f"{label}ReleaseAsOf"] = release.get("asOf")
        for key, rows in render_release_boards(release, dataset).items():
            dst = tree / _board_rel(key)
            src = app_dir / _board_rel(key)
            mtime = src.stat().st_mtime if src.is_file() else None
            _write_private(dst, S.render_board_csv(rows).encode("utf-8"), mtime)
    # ``as_posix``: the keys (and so freezeManifestSha256) must not depend on
    # the OS path separator; on POSIX this equals ``str()``.
    manifest = {
        p.relative_to(tree).as_posix(): _sha256_file(p)
        for p in sorted(tree.rglob("*"))
        if p.is_file()
    }
    info["manifest"] = manifest
    info["fileCount"] = len(manifest)
    info["freezeManifestSha256"] = _sha256_bytes(
        json.dumps(manifest, sort_keys=True).encode("utf-8")
    )
    return info


def derive_tree(base: Path, dst: Path, boards: Mapping[str, list[dict] | None]) -> Path:
    """A variant tree: the frozen tree with some Signals boards replaced
    (``[]`` = an empty board: present, no rows, so it casts no vote).  The
    replaced file keeps the original's mtime so freshness is unchanged."""
    from src.sources import signals as S  # noqa: PLC0415

    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(base, dst, copy_function=shutil.copy2)
    for key, rows in boards.items():
        path = dst / _board_rel(key)
        mtime = path.stat().st_mtime if path.is_file() else None
        _write_private(path, S.render_board_csv(list(rows or [])).encode("utf-8"), mtime)
    return dst


# ── one build per subprocess ─────────────────────────────────────────────


def _compact_row(r: Mapping[str, Any]) -> dict[str, Any]:
    metas = r.get("sourceRankMeta") or {}
    shadow = r.get("sourceShadowMeta") or {}
    csv_vals = r.get("canonicalSiteValues") or {}
    native = r.get("sourceNativeValues") or {}
    return {
        "n": r.get("displayName"),
        "pos": r.get("position"),
        "pid": str(r.get("playerId") or ""),
        "v": r.get("rankDerivedValue"),
        "r": r.get("canonicalConsensusRank"),
        "idpRank": r.get("idpRank"),
        "conf": r.get("confidenceBucket"),
        "axes": r.get("confidenceAxes") if isinstance(r.get("confidenceAxes"), dict) else None,
        "isc": r.get("independentSourceCount"),
        "ss": bool(r.get("singleSourceValuePenaltyApplied")),
        "q": bool(r.get("quarantined")),
        "rookie": bool(r.get("rookie")),
        "age": r.get("age"),
        "dropped": list(r.get("droppedSources") or []),
        "fresh_excl": list(r.get("freshnessExcludedSources") or []),
        "csv": {k: csv_vals.get(k) for k in (BRIDGE, REFERENCE) if k in csv_vals},
        "native": {k: native.get(k) for k in FAMILY_KEYS.values() if k in native},
        "meta": {
            k: {f: m.get(f) for f in _META_FIELDS if f in m}
            for k, m in metas.items()
            if isinstance(m, dict)
        },
        "shadow": {
            k: {f: m.get(f) for f in _SHADOW_FIELDS if f in m}
            for k, m in shadow.items()
            if isinstance(m, dict)
        },
    }


def identity_census(rows: list[dict[str, Any]], csv_root: Path) -> dict[str, Any]:
    """Per family: how each Signals board row would join the board — by
    Sleeper id, by canonical name, unmatched, or onto a row at another
    position — plus Sleeper-id contradictions on name matches.  Mirrors the
    id-then-name rungs of the served join; counts only."""
    import csv as _csv  # noqa: PLC0415

    from src.api.data_contract import _canonical_match_key  # noqa: PLC0415

    by_sid = {r["pid"]: r for r in rows if r.get("pid")}
    by_name: dict[str, list[dict]] = {}
    for r in rows:
        by_name.setdefault(_canonical_match_key(str(r.get("n") or "")), []).append(r)
    out: dict[str, Any] = {}
    contradictions: dict[str, list[str]] = {}
    for fam, key in FAMILY_KEYS.items():
        path = csv_root / _board_rel(key)
        counts = {
            "boardRows": 0,
            "sidMatched": 0,
            "nameMatched": 0,
            "unmatched": 0,
            "ambiguousName": 0,
            "familyMismatched": 0,
            "sidContradictions": 0,
        }
        vocab: dict[str, int] = {}
        names: list[str] = []
        if path.is_file():
            with path.open(encoding="utf-8", newline="") as fh:
                for b in _csv.DictReader(fh):
                    counts["boardRows"] += 1
                    raw_pos = str(b.get("raw_position") or "").upper() or "UNKNOWN"
                    vocab[raw_pos] = vocab.get(raw_pos, 0) + 1
                    sid = str(b.get("sleeper_id") or "").strip()
                    row = by_sid.get(sid) if sid else None
                    if row is not None:
                        counts["sidMatched" if row.get("pos") == fam else "familyMismatched"] += 1
                        continue
                    cands = by_name.get(_canonical_match_key(str(b.get("name") or "")), [])
                    if not cands:
                        counts["unmatched"] += 1
                    elif len(cands) > 1:
                        counts["ambiguousName"] += 1
                    elif cands[0].get("pos") != fam:
                        counts["familyMismatched"] += 1
                    else:
                        counts["nameMatched"] += 1
                        if sid and cands[0].get("pid") and cands[0]["pid"] != sid:
                            counts["sidContradictions"] += 1
                            names.append(str(cands[0].get("n")))
        out[fam] = {**counts, "rawPositionVocabulary": vocab}
        contradictions[fam] = names
    return {"families": out, "private": {"sidContradictionRows": contradictions}}


def child_main(spec_path: str) -> int:
    """Build ONE contract in this process and write its compact rows (0600)
    beside the spec.  Prints one JSON line: ok, refused (with the flag
    name), or the error class."""
    spec = json.loads(Path(spec_path).read_text(encoding="utf-8"))
    code_dir = Path(spec["codeDir"])
    sys.path.insert(0, str(code_dir))
    os.chdir(code_dir)
    from src.api import feature_flags  # noqa: PLC0415

    feature_flags.reload()
    registered = set(feature_flags.registered_flags())
    for name in spec.get("toggles") or {}:
        if name not in registered:
            print(json.dumps({"refused": "unregistered_flag", "flag": name}))
            return 0
    from src.api import data_contract as dc  # noqa: PLC0415

    for name, value in (spec.get("patches") or {}).items():
        if name not in PATCHABLE_CONSTANTS or not hasattr(dc, name):
            print(json.dumps({"refused": "unpatchable_constant"}))
            return 0
        setattr(dc, name, value)
    raw = json.loads(Path(spec["payloadPath"]).read_text(encoding="utf-8"))
    csv_root = Path(spec["csvRoot"])
    with contextlib.redirect_stdout(io.StringIO()):
        contract = dc.build_api_data_contract(
            raw, csv_root=csv_root, source_overrides=spec.get("sourceOverrides") or None
        )
        health = dc.validate_api_data_contract(contract)
    lad = getattr(dc, "_LAST_BRIDGE_LADDER", None)
    rows = [_compact_row(r) for r in contract.get("playersArray") or []]
    psa = contract.get("privateSourceAvailability") or {}
    out = {
        "rows": rows,
        "voteStates": {k: v.get("voteState") for k, v in psa.items() if isinstance(v, dict)},
        "ladders": {k: list(v) for k, v in ((lad.position_ladders if lad else None) or {}).items()},
        "bridgeContributors": list(lad.contributors) if lad else [],
        "contractHealthOk": bool(health.get("ok")),
        "structurallyOk": health.get("structurallyOk"),
        "structuralErrorCount": len(health.get("structuralErrors") or []),
        "flagsSnapshot": feature_flags.snapshot(),
        "identity": identity_census(rows, csv_root) if spec.get("identityCensus") else None,
    }
    _write_private(Path(spec["outPath"]), json.dumps(out, default=str).encode("utf-8"))
    print(json.dumps({"ok": True}))
    return 0


def _nice_prefix() -> list[str]:
    prefix: list[str] = []
    if shutil.which("nice"):
        prefix += ["nice", "-n", "10"]
    if shutil.which("ionice"):
        prefix += ["ionice", "-c3"]
    return prefix


def run_variant(
    name: str,
    *,
    freeze: Path,
    code_dir: Path,
    csv_root: Path,
    payload_path: str,
    flags: Mapping[str, bool],
    toggles: Mapping[str, bool] | None = None,
    patches: Mapping[str, Any] | None = None,
    source_overrides: Mapping[str, Any] | None = None,
    identity: bool = False,
) -> dict[str, Any]:
    """Build one variant in a fresh subprocess.  ``flags`` is the served
    snapshot; ``toggles`` override it.  Every served flag is set explicitly
    in the child's environment, so the child never inherits this shell's
    (non-service) environment.  Returns the loaded compact build, or
    ``{"status": "refused" | "error", ...}``."""
    remaining = None if _DEADLINE is None else _DEADLINE - time.monotonic()
    if remaining is not None and remaining <= 60:
        return {"status": "refused", "reason": "time_budget_exhausted"}
    mem = mem_available_mb()
    if mem is not None and mem < MIN_MEM_AVAILABLE_MB:
        return {"status": "refused", "reason": "insufficient_memory"}
    work = freeze / "work"
    work.mkdir(parents=True, exist_ok=True)
    effective = {**dict(flags), **dict(toggles or {})}
    spec = {
        "codeDir": str(code_dir),
        "csvRoot": str(csv_root),
        "payloadPath": payload_path,
        "toggles": dict(toggles or {}),
        "patches": dict(patches or {}),
        "sourceOverrides": dict(source_overrides or {}),
        "identityCensus": identity,
        "outPath": str(work / f"{name}.rows.json"),
    }
    spec_path = work / f"{name}.spec.json"
    _write_private(spec_path, json.dumps(spec).encode("utf-8"))
    env = {k: v for k, v in os.environ.items() if not k.startswith("RISKIT_FEATURE_")}
    for flag, on in effective.items():
        env[f"RISKIT_FEATURE_{flag.upper()}"] = "1" if on else "0"
    cmd = [
        *_nice_prefix(),
        sys.executable,
        str(Path(__file__).resolve()),
        "--child",
        str(spec_path),
    ]
    try:
        cp = subprocess.run(
            cmd,
            cwd=str(code_dir),
            env=env,
            capture_output=True,
            text=True,
            timeout=min(CHILD_TIMEOUT_SECONDS, remaining) if remaining else CHILD_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return {"status": "error", "error": "TimeoutExpired"}
    if cp.stderr:
        sys.stderr.write(cp.stderr)
    lines = [ln for ln in (cp.stdout or "").splitlines() if ln.strip().startswith("{")]
    try:
        verdict = json.loads(lines[-1]) if lines else {}
    except ValueError:
        verdict = {}
    if verdict.get("refused"):
        return {
            "status": "refused",
            "reason": verdict["refused"],
            "refusedFlag": verdict.get("flag"),
        }
    if not verdict.get("ok") or cp.returncode != 0:
        return {"status": "error", "error": verdict.get("error") or f"exit_{cp.returncode}"}
    built = _read_json(Path(spec["outPath"]))
    if not isinstance(built, dict):
        return {"status": "error", "error": "rows_unreadable"}
    built["status"] = "built"
    built["requestedFlags"] = effective
    return built


def child_entry(argv: list[str]) -> int:
    """``--child <spec>``: everything printed is one JSON line."""
    try:
        return child_main(argv[argv.index("--child") + 1])
    except BaseException as exc:  # noqa: BLE001 — the class only, never the text
        traceback.print_exc(file=sys.stderr)
        print(json.dumps({"error": type(exc).__name__}))
        return 2


# ── statistics over compact builds (counts and distributions only) ───────

_CONF_ORDER = {"low": 0, "medium": 1, "high": 2}
_AXIS_ORDER = {"low": 0, "medium": 1, "high": 2}


def _num(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(float(x))


def _dist2(values: list[float]) -> dict[str, Any]:
    return {
        "n": len(values),
        "median": round(statistics.median(values), 4) if values else None,
        "p10": _pct(values, 0.10),
        "p90": _pct(values, 0.90),
    }


def _mean_cell(values: list[float]) -> dict[str, Any]:
    return {"n": len(values), "mean": round(statistics.fmean(values), 4) if values else None}


def _rowmap(build: Mapping[str, Any]) -> dict[str, dict]:
    return {str(r["n"]): r for r in build.get("rows") or [] if r.get("n")}


def _voting(meta: Mapping[str, Any] | None) -> bool:
    return (
        isinstance(meta, Mapping)
        and not meta.get("hampelDropped")
        and meta.get("contributedToBlend") is not False
        and float(meta.get("appliedWeight") or 0) > 0
        and _num(meta.get("valueContribution"))
    )


def _band(rank: Any, bands: Mapping[str, list]) -> str | None:
    if not _num(rank):
        return None
    for label, (lo, hi) in bands.items():
        if rank >= lo and (hi is None or rank <= hi):
            return label
    return None


def _spearman(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 3 or len(xs) != len(ys):
        return None

    def ranks(vals: list[float]) -> list[float]:
        order = sorted(range(len(vals)), key=lambda i: vals[i])
        out = [0.0] * len(vals)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and vals[order[j + 1]] == vals[order[i]]:
                j += 1
            for k in range(i, j + 1):
                out[order[k]] = (i + j) / 2.0 + 1.0
            i = j + 1
        return out

    rx, ry = ranks(xs), ranks(ys)
    mx, my = statistics.fmean(rx), statistics.fmean(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = math.sqrt(sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry))
    return round(num / den, 4) if den else None


def movement_v2(base: Mapping[str, dict], var: Mapping[str, dict], names: Iterable[str]) -> dict:
    """Relative movement with NEWLY PRICED / UNPRICED rows counted (as a
    100% move, the preregistered conservative rule) beside the both-priced
    view, absolute movement apart, and the classes the decomposition needs."""
    rel_all, rel_both, abs_both, signed, signed_rel = [], [], [], [], []
    moved = newly_priced = newly_unpriced = 0
    classes: dict[str, list[float]] = {}
    new_rel = float(GATES["definitions"]["newlyPricedRelativeMovement"])
    for n in names:
        a, b = base.get(n) or {}, var.get(n) or {}
        va, vb = a.get("v"), b.get("v")
        has_a, has_b = _num(va) and va > 0, _num(vb) and vb > 0
        if not has_a and not has_b:
            continue
        if has_a and has_b:
            d = float(vb) - float(va)
            rel = abs(d) / max(1.0, float(va))
            rel_both.append(rel)
            abs_both.append(abs(d))
            signed.append(d)
            signed_rel.append(d / max(1.0, float(va)))
            moved += d != 0
        else:
            rel = new_rel
            moved += 1
            newly_priced += has_b
            newly_unpriced += has_a
        rel_all.append(rel)
        ranked = "ranked" if isinstance(a.get("r"), int) else "offCap"
        flip = "haircutLifted" if a.get("ss") and not b.get("ss") else "noHaircutFlip"
        for cls in (ranked, flip):
            classes.setdefault(cls, []).append(rel)
    return {
        "rowsConsidered": len(rel_all),
        "rowsMoved": moved,
        "newlyPriced": newly_priced,
        "newlyUnpriced": newly_unpriced,
        "relValue": _dist2(rel_all),
        "relValueBothPriced": _dist2(rel_both),
        "absValueBothPriced": _dist2(abs_both),
        "meanShift": _mean_cell(signed),
        "meanRelShift": _mean_cell(signed_rel),
        "byClass": {k: _dist2(v) for k, v in sorted(classes.items())},
    }


def _panel(row: Mapping[str, Any], exclude: Iterable[str], corrected: bool) -> list[float]:
    skip = set(exclude)
    vals = []
    for k, m in (row.get("meta") or {}).items():
        if k in skip or not isinstance(m, Mapping):
            continue
        if corrected:
            if _voting(m):
                vals.append(float(m["valueContribution"]))
        elif not m.get("hampelDropped") and _num(m.get("valueContribution")):
            vals.append(float(m["valueContribution"]))
    return vals


def signed_bias(
    pairs: Iterable[tuple[float, Mapping[str, Any]]], exclude: Iterable[str], corrected: bool
) -> dict[str, Any]:
    """Signed median of (vote − panel median) / panel median.  ``pairs`` is
    (vote, the row whose other sources form the panel)."""
    need = 2 if corrected else 1
    excl = list(exclude)
    out: list[float] = []
    for vote, row in pairs:
        panel = _panel(row, excl, corrected)
        if len(panel) >= need:
            med = statistics.median(panel)
            out.append((vote - med) / max(1.0, med))
    return {"n": len(out), "median": round(statistics.median(out), 4) if out else None}


def _signals_votes(var: Mapping[str, dict], key: str) -> list[tuple[str, dict]]:
    return [(n, r["meta"][key]) for n, r in var.items() if isinstance(r["meta"].get(key), dict)]


def family_stats(
    served: Mapping[str, dict],
    var: Mapping[str, dict],
    fam: str,
    *,
    identity: Mapping[str, Any] | None = None,
    shadow_rows: Mapping[str, dict] | None = None,
    candidate_id: str | None = None,
) -> dict[str, Any]:
    """Every per-family statistic of one variant against the served build.

    ``shadow_rows`` is the build whose published shadow for this family is
    compared with this variant's votes (INT-SHADOW); only shadow entries of
    the same candidate (``candidate_id``; an entry without a ``candidate``
    field is Candidate A) are compared, so A's shadow is never held against
    an F vote."""
    key = FAMILY_KEYS[fam]
    signals_keys = set(FAMILY_KEYS.values())
    fam_rows = sorted({n for n, r in {**served, **var}.items() if r.get("pos") == fam})
    votes = _signals_votes(var, key)
    voting = [(n, m) for n, m in votes if _voting(m)]
    dropped = sum(1 for _n, m in votes if m.get("hampelDropped"))
    idp_bands = GATES["definitions"]["idpBands"]
    # Hampel drops Signals caused in OTHER sources on this family's rows.
    caused = caused_ref_es = unexplained = family_obs = 0
    caused_by_source: dict[str, int] = {}
    caused_by_role: dict[str, int] = {"anchor": 0, "subgroup": 0}
    for n in fam_rows:
        b, s = var.get(n) or {}, served.get(n) or {}
        for src, m in (b.get("meta") or {}).items():
            if _voting(m):
                family_obs += 1
            if src in signals_keys or not isinstance(m, Mapping) or not m.get("hampelDropped"):
                continue
            prior = (s.get("meta") or {}).get(src) or {}
            if prior.get("hampelDropped"):
                continue
            caused += 1
            caused_by_source[src] = caused_by_source.get(src, 0) + 1
            caused_by_role["anchor" if m.get("isAnchor") else "subgroup"] += 1
            if src == REFERENCE and _band(s.get("idpRank"), idp_bands) in ("elite", "starter"):
                caused_ref_es += 1
            if src not in (b.get("dropped") or []):
                unexplained += 1
    # Integrity.
    dup = sum(
        1
        for r in var.values()
        if sum(1 for k in signals_keys if _voting((r.get("meta") or {}).get(k))) > 1
    )
    stale_invalid = sum(
        1
        for n, m in votes
        if float(m.get("appliedWeight") or 0) > 0
        and not m.get("hampelDropped")
        and (
            key in (var[n].get("fresh_excl") or [])
            or not (_num(m.get("valueContribution")) and m["valueContribution"] > 0)
        )
    )
    sid_rows = set(
        ((identity or {}).get("private") or {}).get("sidContradictionRows", {}).get(fam) or []
    )
    shadow_mismatch = shadow_compared = 0
    a_id = str(GATES["candidates"]["A"]["id"])
    ref_rows = served if shadow_rows is None else shadow_rows
    for n, m in voting:
        sh = ((ref_rows.get(n) or {}).get("shadow") or {}).get(key) or {}
        if (sh.get("candidate") or a_id) != (candidate_id or a_id):
            continue
        if _num(sh.get("wouldContribute")):
            shadow_compared += 1
            shadow_mismatch += int(round(float(sh["wouldContribute"]))) != int(
                round(float(m["valueContribution"]))
            )
    # An upper bound a within-family rank can never legitimately exceed: the
    # family's board size (the larger of the census and the shadow count).
    census_rows = ((((identity or {}).get("families") or {}).get(fam)) or {}).get("boardRows") or 0
    board_size = max(
        census_rows,
        sum(1 for r in served.values() if isinstance((r.get("shadow") or {}).get(key), dict)),
    ) or len(votes)
    # Haircut transitions and the formula check.
    lifted = [
        n for n in fam_rows if (served.get(n) or {}).get("ss") and not (var.get(n) or {}).get("ss")
    ]
    imposed = [
        n for n in fam_rows if not (served.get(n) or {}).get("ss") and (var.get(n) or {}).get("ss")
    ]
    formula_mismatch = 0
    for n in fam_rows:
        r = var.get(n) or {}
        contrib = [
            float(m["valueContribution"]) for m in (r.get("meta") or {}).values() if _voting(m)
        ]
        if r.get("ss") and len(contrib) == 1 and _num(r.get("v")):
            expected = 0.30 * contrib[0]
            formula_mismatch += abs(float(r["v"]) - expected) > max(2.0, 0.01 * expected)
        elif n in lifted and contrib and _num(r.get("v")):
            formula_mismatch += not (min(contrib) - 1 <= float(r["v"]) <= max(contrib) + 1)
    mv_family = movement_v2(served, var, fam_rows)
    rels = []
    for n in fam_rows:
        a, b = (served.get(n) or {}).get("v"), (var.get(n) or {}).get("v")
        if _num(a) and a > 0 and _num(b) and b > 0:
            rels.append((abs(float(b) - float(a)) / max(1.0, float(a)), n))
        elif (_num(a) and a > 0) or (_num(b) and b > 0):
            rels.append((float(GATES["definitions"]["newlyPricedRelativeMovement"]), n))
    p90 = _pct([x for x, _n in rels], 0.90)
    tail = [n for x, n in rels if p90 is not None and x >= p90 and x > 0]
    lifted_set = set(lifted)
    # Confidence transitions.
    matrix: dict[str, int] = {}
    rises = rises_haircut = rises_independence = rises_agreement = 0
    for n in fam_rows:
        a, b = served.get(n) or {}, var.get(n) or {}
        ca, cb = a.get("conf"), b.get("conf")
        if ca != cb:
            matrix[f"{ca}->{cb}"] = matrix.get(f"{ca}->{cb}", 0) + 1
        if _CONF_ORDER.get(cb, -1) > _CONF_ORDER.get(ca, -1) >= 0:
            rises += 1
            rises_haircut += n in lifted_set
            ax_a, ax_b = a.get("axes") or {}, b.get("axes") or {}
            rises_independence += _AXIS_ORDER.get(ax_b.get("independence"), -1) > _AXIS_ORDER.get(
                ax_a.get("independence"), -1
            )
            rises_agreement += _AXIS_ORDER.get(ax_b.get("agreement"), -1) > _AXIS_ORDER.get(
                ax_a.get("agreement"), -1
            )
    vote_pairs = [
        (float(m["valueContribution"]), var[n])
        for n, m in votes
        if _num(m.get("valueContribution"))
    ]
    return {
        "key": key,
        "votes": len(votes),
        "votingObservations": len(voting),
        "ownHampelDrops": dropped,
        "ownHampelDropRate": round(dropped / len(votes), 4) if votes else None,
        "createdCrossFamilyOrder": sum(1 for n, _m in votes if var[n].get("pos") != fam)
        + sum(1 for _n, m in votes if _num(m.get("rawRank")) and m["rawRank"] > board_size),
        "nonSharedMarketVotes": sum(
            1 for _n, m in votes if m.get("rankCoordinatePool") != "shared_market"
        ),
        "extrapolatedVotes": sum(1 for _n, m in votes if m.get("method") == "extrapolated"),
        "rookieVotes": sum(1 for n, _m in voting if var[n].get("rookie")),
        "duplicateSignalsObservationsOnRow": dup,
        "familyMismatchesVoting": sum(1 for n, _m in voting if var[n].get("pos") != fam),
        "sidContradictionsVoting": sum(1 for n, _m in voting if n in sid_rows),
        "staleOrInvalidVoting": stale_invalid,
        "shadowPromotedCompared": shadow_compared,
        "shadowPromotedMismatches": shadow_mismatch if shadow_compared else None,
        "causedHampelDrops": caused,
        "causedHampelDropsBySource": caused_by_source,
        "causedHampelDropsByRole": caused_by_role,
        "causedIndependentAnchorDropsEliteStarter": caused_ref_es,
        "causedDropShare": round(caused / family_obs, 4) if family_obs else None,
        "causedDropsUnexplained": unexplained,
        "signedBiasScriptPanel": signed_bias(vote_pairs, signals_keys, corrected=False),
        "signedBiasCorrectedPanel": signed_bias(vote_pairs, signals_keys, corrected=True),
        "movement": mv_family,
        "haircut": {
            "lifted": len(lifted),
            "imposed": len(imposed),
            "formulaMismatches": formula_mismatch,
            "tailRows": len(tail),
            "tailShareInLiftedSet": round(sum(1 for n in tail if n in lifted_set) / len(tail), 4)
            if tail
            else None,
        },
        "confidence": {
            "transitions": matrix,
            "rises": rises,
            "risesWithHaircutLift": rises_haircut,
            "risesWithIndependenceAxisRise": rises_independence,
            "risesWithAgreementAxisRise": rises_agreement,
        },
    }


def board_stats(served: Mapping[str, dict], var: Mapping[str, dict]) -> dict[str, Any]:
    idp = sorted({n for n, r in {**served, **var}.items() if r.get("pos") in IDP_POSITIONS})

    def share(rows: Mapping[str, dict]) -> dict[str, int]:
        top = _top(
            {
                n: {"canonicalConsensusRank": r.get("r"), "position": r.get("pos")}
                for n, r in rows.items()
            },
            200,
        )
        return {f: sum(1 for x in top if rows[x].get("pos") == f) for f in FAMILIES}

    s_share, v_share = share(served), share(var)
    return {
        "idpMovement": movement_v2(served, var, idp),
        "offensePlayerRowsMoved": sum(
            1
            for n, r in served.items()
            if r.get("pos") in OFFENSE_POSITIONS and r.get("v") != (var.get(n) or {}).get("v")
        ),
        "pickMovement": movement_v2(
            served, var, [n for n, r in served.items() if r.get("pos") == "PICK"]
        ),
        "top200FamilyShare": {"served": s_share, "variant": v_share},
        "top200ShareDeltaPp": {f: round((v_share[f] - s_share[f]) / 2.0, 2) for f in FAMILIES},
    }


# ── the bridge coordinate: c(p), L^M, pick rows, Hill misfit ─────────────


def _hill_g(rank: float) -> float:
    """GLOBAL shared-market price at a (fractional) rank — the same
    functions the contract's shadow path calls.  Diagnostic only; every use
    is cross-checked against the build's own votes (``pricingAgreement``)."""
    from src.api.data_contract import _PERCENTILE_REFERENCE_N  # noqa: PLC0415
    from src.canonical.player_valuation import percentile_to_value, rank_to_percentile  # noqa: PLC0415
    from src.canonical.rank_coordinates import RANK_POOL_SHARED_MARKET, curve_for_pool  # noqa: PLC0415

    hc, hs = curve_for_pool(RANK_POOL_SHARED_MARKET)
    p = rank_to_percentile(float(rank), reference_n=_PERCENTILE_REFERENCE_N)
    return float(percentile_to_value(p, midpoint=hc, slope=hs))


def bridge_coordinates(build: Mapping[str, Any]) -> dict[str, Any]:
    """Reconstruct the bridge's combined order (descending bridge value, ties
    by lower-cased name, offense + picks + IDP) and its family slices.  The
    reconstruction is checked against the ladder the build actually used;
    only an exact match yields c(p) and pick counts."""
    rows = build.get("rows") or []
    combined = sorted(
        (
            (
                -float(r["csv"][BRIDGE]),
                str(r.get("n") or "").lower(),
                str(r.get("n")),
                str(r.get("pos") or ""),
            )
            for r in rows
            if _num((r.get("csv") or {}).get(BRIDGE))
            and float(r["csv"][BRIDGE]) > 0
            and str(r.get("pos") or "") in (OFFENSE_POSITIONS | IDP_POSITIONS | {"PICK"})
        )
    )
    families: dict[str, list[tuple[int, str, int]]] = {f: [] for f in FAMILIES}
    picks_above = 0
    for rank, (_v, _l, name, pos) in enumerate(combined, start=1):
        if pos == "PICK":
            picks_above += 1
        elif pos in IDP_POSITIONS:
            families[pos].append((rank, name, picks_above))
    used = build.get("ladders") or {}
    out: dict[str, Any] = {"exact": {}, "c": {}, "picksAbove": {}}
    for fam in FAMILIES:
        recon = [rank for rank, _n, _p in families[fam]]
        exact = bool(recon) and list(used.get(fam) or []) == recon
        out["exact"][fam] = exact
        if exact:
            out["c"][fam] = {name: rank for rank, name, _p in families[fam]}
            out["picksAbove"][fam] = {name: p for _r, name, p in families[fam]}
    return out


def coordinate_diagnostics(
    served: Mapping[str, Any],
    var: Mapping[str, Any] | None,
    *,
    shadow_candidate: str,
    split_coverage: bool = True,
) -> dict[str, Any]:
    """Per family: pick rows above each slot, the share of Signals votes past
    combined rank 500, within-family Spearman (Signals vs bridge order on
    M_F), the horizon age gradient, and the exact telescoping ln
    decomposition of the shadow vote against the row panel:

        ln(V/O) = [ln H(c_vote) − ln H(c_M)]   coverage
                + [ln H(c_M)    − ln H(c)]     ordering (Signals vs bridge)
                + [ln H(c)      − ln v_β]      Hill misfit at the bridge's slot
                + [ln v_β       − ln O]        reference placement

    by combined-rank band of c(p), on both panels.  ``V`` is the served
    build's shadow vote (``shadow_candidate`` names its method).

    ``H(c_M)`` is Candidate F's vote, so D1 (``split_coverage=False``, the
    quarantine) publishes only the sum ``coverageAndOrdering`` and no term
    that isolates it."""
    coords = bridge_coordinates(served)
    s_rows = _rowmap(served)
    v_rows = _rowmap(var) if var else {}
    bands = GATES["definitions"]["combinedRankBands"]
    out: dict[str, Any] = {
        "bridgeReconstructionExact": coords["exact"],
        "shadowCandidate": shadow_candidate,
    }
    for fam, key in FAMILY_KEYS.items():
        rep: dict[str, Any] = {}
        c_map = coords["c"].get(fam)
        votes = _signals_votes(v_rows, key) if v_rows else []
        ranks = [float(m["effectiveRank"]) for _n, m in votes if _num(m.get("effectiveRank"))]
        rep["votesBeyondRank500Share"] = (
            round(sum(1 for r in ranks if r > 500) / len(ranks), 4) if ranks else None
        )
        if not c_map:
            rep["state"] = "bridge_reconstruction_not_exact"
            out[fam] = rep
            continue
        picks = coords["picksAbove"][fam]
        rep["picksAboveSlot"] = {
            band: _dist2([float(picks[n]) for n in c_map if _band(c_map[n], bands) == band])
            for band in bands
        }
        matched = []
        for n, c in c_map.items():
            sh = ((s_rows.get(n) or {}).get("shadow") or {}).get(key) or {}
            if _num(sh.get("familyRank")):
                matched.append((n, float(sh["familyRank"]), c))
        m = len(matched)
        rep["matched"] = m
        if m < 3:
            rep["state"] = "too_few_matched"
            out[fam] = rep
            continue
        lm = sorted(c for _n, _k, c in matched)
        sig_sorted = sorted(matched, key=lambda t: t[1])
        k_m: dict[str, int] = {}
        prev, prev_rank = None, 0
        for idx, (n, k, _c) in enumerate(sig_sorted, start=1):
            rank = prev_rank if k == prev else idx
            prev, prev_rank = k, rank
            k_m[n] = rank
        beta_rank = {
            n: i for i, (n, _k, _c) in enumerate(sorted(matched, key=lambda t: t[2]), start=1)
        }
        rep["spearmanSignalsVsBridge"] = _spearman(
            [float(k_m[n]) for n, _k, _c in matched], [float(beta_rank[n]) for n, _k, _c in matched]
        )
        ages, resid = [], []
        for n, _k, _c in matched:
            age = (s_rows.get(n) or {}).get("age")
            if _num(age):
                ages.append(float(age))
                resid.append((k_m[n] - beta_rank[n]) / m)
        rep["horizonAgeGradient"] = {
            "n": len(ages),
            "spearmanAgeVsOrderingResidual": _spearman(ages, resid),
        }
        terms: dict[str, dict[str, list[float]]] = {}
        agree = checked = 0
        for n, _k, c in matched:
            row = s_rows.get(n) or {}
            sh = (row.get("shadow") or {}).get(key) or {}
            beta = (row.get("meta") or {}).get(BRIDGE) or {}
            if not (_num(sh.get("wouldContribute")) and _num(sh.get("translatedRank"))):
                continue
            vote, c_vote = float(sh["wouldContribute"]), float(sh["translatedRank"])
            checked += 1
            agree += abs(_hill_g(c_vote) - vote) <= 1.0
            if not (
                _num(beta.get("valueContribution")) and beta["valueContribution"] > 0 and vote > 0
            ):
                continue
            c_m = float(lm[k_m[n] - 1])
            h_vote, h_m, h_c = _hill_g(c_vote), _hill_g(c_m), _hill_g(float(c))
            v_beta = float(beta["valueContribution"])
            band = _band(c, bands) or "unbanded"
            cell = terms.setdefault(band, {})
            if min(h_vote, h_m, h_c) <= 0:
                continue
            if split_coverage:
                cell.setdefault("coverage", []).append(math.log(h_vote / h_m))
                cell.setdefault("ordering", []).append(math.log(h_m / h_c))
            else:
                cell.setdefault("coverageAndOrdering", []).append(math.log(h_vote / h_c))
            cell.setdefault("hillMisfit", []).append(math.log(h_c / v_beta))
            for label, corrected in (("Script", False), ("Corrected", True)):
                panel = _panel(row, FAMILY_KEYS.values(), corrected)
                if len(panel) >= (2 if corrected else 1):
                    o = statistics.median(panel)
                    if o > 0:
                        cell.setdefault(f"placement{label}Panel", []).append(math.log(v_beta / o))
                        cell.setdefault(f"total{label}Panel", []).append(math.log(vote / o))
        rep["pricingAgreement"] = {
            "checked": checked,
            "share": round(agree / checked, 4) if checked else None,
        }
        rep["decomposition"] = {
            band: {t: _dist2(vals) for t, vals in sorted(cell.items())}
            for band, cell in sorted(terms.items())
        }
        if checked and agree / checked < 0.99:
            rep["decompositionState"] = "VOID: in-script pricing disagrees with the build"
        out[fam] = rep
    return out


# ── negative controls and the information diagnostic ─────────────────────


def permutation_controls(
    var: Mapping[str, Any], fam: str, *, draws: int, seed: int
) -> dict[str, Any]:
    """NC2 / NC3 with the panel held fixed: the build's own Signals votes on
    this family, sorted, are reassigned to the matched rows in a permuted
    (NC2, median over ``draws``) or reversed (NC3) order.  Reuses the
    build's votes, so no second pricing is involved."""
    import random  # noqa: PLC0415

    key = FAMILY_KEYS[fam]
    rows = _rowmap(var)
    votes = [
        (
            float(m["effectiveRank"]) if _num(m.get("effectiveRank")) else 0.0,
            float(m["valueContribution"]),
            rows[n],
        )
        for n, m in _signals_votes(rows, key)
        if _num(m.get("valueContribution"))
    ]
    if len(votes) < 3:
        return {"NC2": {"n": len(votes), "median": None}, "NC3": {"n": len(votes), "median": None}}
    votes.sort(key=lambda t: (t[0], -t[1]))
    values = sorted((v for _r, v, _row in votes), reverse=True)
    targets = [row for _r, _v, row in votes]
    excl = list(FAMILY_KEYS.values())
    rng = random.Random(seed)
    meds = []
    for _ in range(draws):
        perm = values[:]
        rng.shuffle(perm)
        res = signed_bias(zip(perm, targets), excl, corrected=True)
        if res["median"] is not None:
            meds.append(res["median"])
    rev = signed_bias(zip(list(reversed(values)), targets), excl, corrected=True)
    return {
        "NC2": {"n": len(meds), "median": round(statistics.median(meds), 4) if meds else None},
        "NC3": rev,
    }


def information_diagnostic(
    served: Mapping[str, Any],
    without: Mapping[str, Any] | None,
    with_signals: Mapping[str, Any] | None,
    n0: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Leave-Draft-Sharks-out builds against Draft Sharks IDP, per family."""
    rules = GATES["information"]
    s_rows = _rowmap(served)
    builds = {"withoutSignals": without, "withSignals": with_signals, "n0": n0}
    out: dict[str, Any] = {}
    for fam, key in FAMILY_KEYS.items():
        covered = {
            n: float(r["csv"][REFERENCE])
            for n, r in s_rows.items()
            if r.get("pos") == fam
            and _num((r.get("csv") or {}).get(REFERENCE))
            and float(r["csv"][REFERENCE]) > 0
        }
        rep: dict[str, Any] = {"referenceCovered": len(covered)}
        for label, b in builds.items():
            if not b or b.get("status") != "built":
                rep[label] = {"state": "not_built"}
                continue
            rows = _rowmap(b)
            names = [n for n in covered if _num((rows.get(n) or {}).get("v")) and rows[n]["v"] > 0]
            ref_vc = {
                n: float(
                    ((s_rows[n].get("meta") or {}).get(REFERENCE) or {}).get("valueContribution")
                )
                for n in names
                if _num(
                    ((s_rows[n].get("meta") or {}).get(REFERENCE) or {}).get("valueContribution")
                )
            }
            rep[label] = {
                "n": len(names),
                "spearman": _spearman(
                    [covered[n] for n in names], [float(rows[n]["v"]) for n in names]
                ),
                "medianAbsLogError": {
                    "n": len(ref_vc),
                    "median": round(
                        statistics.median(
                            abs(math.log(float(rows[n]["v"]) / v))
                            for n, v in ref_vc.items()
                            if v > 0
                        ),
                        4,
                    )
                    if ref_vc
                    else None,
                },
            }
        pts = []
        for n, d in covered.items():
            r = s_rows.get(n) or {}
            sh = (r.get("shadow") or {}).get(key) or {}
            b = (r.get("csv") or {}).get(BRIDGE)
            if _num(sh.get("familyRank")) and _num(b) and b > 0:
                pts.append((float(sh["familyRank"]), float(b), d))
        discordant = with_sig = 0
        for i in range(len(pts)):
            for j in range(i + 1, len(pts)):
                si, bi, di = pts[i]
                sj, bj, dj = pts[j]
                sig = (sj > si) - (sj < si)
                beta = (bi > bj) - (bi < bj)
                dsr = (di > dj) - (di < dj)
                if not sig or not beta or not dsr or sig == beta:
                    continue
                discordant += 1
                with_sig += dsr == sig
        share = round(with_sig / discordant, 4) if discordant else None
        rep["discordantPairs"] = discordant
        rep["referenceSidesWithSignalsShare"] = share
        sp = {k: (rep.get(k) or {}).get("spearman") for k in builds}
        if (
            len(pts) < rules["minMatchedRowsPerFamily"]
            or discordant < rules["minDiscordantPairs"]
            or None in sp.values()
        ):
            verdict = "INSUFFICIENT"
        else:
            d_without = sp["withSignals"] - sp["withoutSignals"]
            d_n0 = sp["withSignals"] - sp["n0"]
            margin = rules["spearmanMargin"]
            if d_without >= margin and d_n0 >= margin and share >= rules["sideWithSignalsPositive"]:
                verdict = "POSITIVE"
            elif (
                d_without <= -margin
                and d_n0 <= -margin
                and share <= rules["sideWithSignalsNegative"]
            ):
                verdict = "NEGATIVE"
            else:
                verdict = "NEUTRAL"
        rep["matchedWithReference"] = len(pts)
        rep["verdict"] = verdict
        out[fam] = rep
    return out


# ── verdicts, reproduction, premises ─────────────────────────────────────


def judge(op: str, value: Any, threshold: Any) -> str:
    if op in ("external", "ci"):
        return "EXTERNAL"
    if op == "report":
        return "REPORTED"
    if value is None:
        return "INSUFFICIENT"
    if op == "eq":
        return "PASS" if value == threshold else "FAIL"
    if op == "le":
        return "PASS" if value <= threshold else "FAIL"
    if op == "ge":
        return "PASS" if value >= threshold else "FAIL"
    if op == "abs_le":
        return "PASS" if abs(value) <= threshold else "FAIL"
    if op == "within":
        lo, hi = threshold
        return "PASS" if lo <= value <= hi else "FAIL"
    if op == "all":
        return "PASS" if value is True else "FAIL"
    if op == "insufficient_below":
        return "INSUFFICIENT" if value < threshold else "REPORTED"
    raise ValueError(f"unknown op {op}")


def _metric_for(
    metric: str,
    fam_stats: Mapping[str, Any],
    board: Mapping[str, Any],
    fam: str,
    extra: Mapping[str, Any],
) -> Any:
    if metric in fam_stats and not isinstance(fam_stats[metric], Mapping):
        return fam_stats[metric]
    if metric == "signedBiasCorrectedPanel":
        cell = fam_stats.get(metric) or {}
        return cell.get("median") if (cell.get("n") or 0) >= MIN_CELL else None
    if metric == "top200ShareDeltaPp":
        # Every family's share counts: an isolated DL build that moves the
        # LB share by more than the threshold fails G5 too.
        deltas = [d for d in (board.get("top200ShareDeltaPp") or {}).values() if _num(d)]
        return max(deltas, key=abs) if deltas else None
    if metric == "idpRelMovementMedian":
        cell = (board.get("idpMovement") or {}).get("relValue") or {}
        return cell.get("median") if (cell.get("n") or 0) >= MIN_CELL else None
    if metric == "idpRelMovementP90":
        cell = (board.get("idpMovement") or {}).get("relValue") or {}
        return cell.get("p90") if (cell.get("n") or 0) >= MIN_CELL else None
    if metric == "offensePlayerRowsMoved":
        return board.get("offensePlayerRowsMoved")
    if metric in extra:
        return extra[metric]
    return None


def family_verdicts(
    fam: str,
    fam_stats: Mapping[str, Any],
    board: Mapping[str, Any],
    extra: Mapping[str, Any],
    *,
    void: Mapping[str, str] | None = None,
) -> dict[str, dict[str, Any]]:
    """PASS / FAIL / INSUFFICIENT / VOID per preregistered criterion, with
    engineering correctness and empirical quality kept apart."""
    out: dict[str, dict[str, Any]] = {"engineering": {}, "empirical": {}}
    for section in ("engineering", "empirical"):
        for crit in GATES[section]:
            cid = crit["id"]
            value = _metric_for(crit["metric"], fam_stats, board, fam, extra)
            verdict = judge(crit["op"], value, crit["threshold"])
            if void and cid in void:
                verdict = "VOID"
            entry: dict[str, Any] = {"verdict": verdict}
            if void and cid in void:
                entry["reason"] = void[cid]
            if verdict in ("PASS", "FAIL", "REPORTED") and not isinstance(value, Mapping):
                entry["value"] = value
            out[section][cid] = entry
    return out


def reproduction_verdicts(observed: Mapping[str, Any]) -> dict[str, Any]:
    tol = GATES["reproduction"]["tolerances"]
    out: dict[str, Any] = {}
    for fig in GATES["reproduction"]["figures"]:
        obs = observed.get(fig["id"])
        exp = fig["observed"]
        if obs is None:
            verdict = "INSUFFICIENT"
        elif fig["kind"] == "count":
            verdict = "REPRODUCED" if obs == exp else "NOT_REPRODUCED"
        elif fig["kind"] == "percentage":
            verdict = (
                "REPRODUCED"
                if abs(obs - exp) <= tol["percentagePoints"] / 100.0
                else "NOT_REPRODUCED"
            )
        else:
            verdict = (
                "REPRODUCED"
                if exp and abs(obs - exp) / abs(exp) <= tol["tailRelative"]
                else "NOT_REPRODUCED"
            )
        out[fig["id"]] = {
            "roundOne": exp,
            "observed": _sig(obs) if isinstance(obs, float) else obs,
            "verdict": verdict,
            "explained": None,
        }
    return out


def _legacy_movement(
    base: Mapping[str, dict], var: Mapping[str, dict], names: Iterable[str]
) -> dict:
    """Round 1's own definition (both rows priced; ``_movement``), kept for
    the reproduction table so like is compared with like."""
    rel, moved, compared = [], 0, 0
    for n in names:
        va, vb = (base.get(n) or {}).get("v"), (var.get(n) or {}).get("v")
        if _num(va) and _num(vb):
            compared += 1
            d = abs(float(vb) - float(va))
            rel.append(d / max(1.0, float(va)))
            moved += d > 0
    return {"rowsCompared": compared, "rowsMoved": moved, "rel": rel}


def _pseudo_contract(build: Mapping[str, Any]) -> dict[str, Any]:
    """Compact rows in the shape the round-1 helpers read."""
    return {
        "playersArray": [
            {
                "displayName": r.get("n"),
                "position": r.get("pos"),
                "playerId": r.get("pid"),
                "rankDerivedValue": r.get("v"),
                "canonicalConsensusRank": r.get("r"),
                "sourceRankMeta": r.get("meta"),
                "sourceShadowMeta": r.get("shadow"),
                "canonicalSiteValues": r.get("csv"),
                "sourceNativeValues": r.get("native"),
            }
            for r in build.get("rows") or []
        ]
    }


def reproduction_observed(
    app_dir: Path, served: Mapping[str, Any], a_all: Mapping[str, Any]
) -> dict[str, Any]:
    s, p = _rowmap(served), _rowmap(a_all)
    idp = [n for n, r in s.items() if r.get("pos") in IDP_POSITIONS]
    mv = _legacy_movement(s, p, idp)
    votes = [m for key in FAMILY_KEYS.values() for _n, m in _signals_votes(p, key)]
    observed: dict[str, Any] = {
        "idpRowsMoving": mv["rowsMoved"],
        "idpRowsCompared": mv["rowsCompared"],
        "idpRelMovementMedian": round(statistics.median(mv["rel"]), 4) if mv["rel"] else None,
        "idpRelMovementP90": _pct(mv["rel"], 0.90),
        "signalsOutlierDropRate": round(
            sum(1 for m in votes if m.get("hampelDropped")) / len(votes), 4
        )
        if votes
        else None,
        "offensePlayerRowsMoved": sum(
            1
            for n, r in s.items()
            if r.get("pos") in OFFENSE_POSITIONS and r.get("v") != (p.get(n) or {}).get("v")
        ),
    }
    for fam, label in (("LB", "lbSignedBias"), ("DB", "dbSignedBias")):
        key = FAMILY_KEYS[fam]
        pairs = []
        for n, r in s.items():
            sh = (r.get("shadow") or {}).get(key) or {}
            if r.get("pos") == fam and _num(sh.get("wouldContribute")) and n in p:
                pairs.append((float(sh["wouldContribute"]), p[n]))
        cell = signed_bias(pairs, [key], corrected=False)
        observed[label] = cell["median"] if cell["n"] >= MIN_CELL else None
    trades = trade_check(app_dir, _pseudo_contract(served), _pseudo_contract(a_all))
    observed["scorableIdpTrades"] = trades.get("scored") if trades.get("available") else None
    return observed


# ── evaluation releases (R1 / R2) and Tier 1a ────────────────────────────


def preregistration_merged_at(app_dir: Path) -> str | None:
    """When ``gates.json`` entered this checkout's first-parent history (the
    merge to main), from git — the anchor R1 is defined against."""
    rel = "docs/valuation/evidence/signals-idp-v2-2026-10-19/gates.json"
    rc, out = _run(
        [
            "git",
            "-C",
            str(app_dir),
            "log",
            "--first-parent",
            "--diff-filter=A",
            "--format=%cI",
            "--",
            rel,
        ]
    )
    lines = [ln.strip() for ln in out.splitlines() if ln.strip()] if rc == 0 else []
    return lines[-1] if lines else None


def _family_ranks(release: Mapping[str, Any]) -> dict[tuple[str, str], int]:
    out: dict[tuple[str, str], int] = {}
    for r in release.get("boardRows") or []:
        sid, fam = str(r.get("sleeper_id") or ""), str(r.get("position") or "")
        if sid and fam in IDP_POSITIONS and _num(r.get("rank")):
            out[(sid, fam)] = int(r["rank"])
    return out


def rank_change_share(a: Mapping[str, Any], b: Mapping[str, Any]) -> dict[str, Any]:
    ra, rb = _family_ranks(a), _family_ranks(b)
    common = sorted(set(ra) & set(rb))
    changed = sum(1 for k in common if ra[k] != rb[k])
    return {
        "common": len(common),
        "changed": changed,
        "share": round(changed / len(common), 4) if common else None,
    }


def release_qualification(app_dir: Path, *, role: str, r1_pin: str | None) -> dict[str, Any]:
    from src.sources.signals import parse_iso  # noqa: PLC0415

    rules = GATES["evaluationReleases"]
    latest = _read_json(app_dir / "data" / "sources" / "signals" / "values" / "idp" / "latest.json")
    ref_pin = rules["baselineRelease"] if role == "R1" else (r1_pin or "")
    ref, _ = find_release(app_dir, "idp", ref_pin) if ref_pin else (None, None)
    merged = preregistration_merged_at(app_dir)
    out: dict[str, Any] = {
        "role": role,
        "referenceRelease": ref_pin or None,
        "referenceFound": ref is not None,
    }
    if not isinstance(latest, dict) or ref is None:
        out["qualifies"] = None
        return out
    out["release"] = str(latest.get("contentSha256") or "")[:12]
    as_of, merged_dt = parse_iso(latest.get("asOf")), parse_iso(merged)
    out["asOfAfterPreregistration"] = (as_of > merged_dt) if as_of and merged_dt else None
    out["contentDiffers"] = out["release"] != ref_pin[:12]
    change = rank_change_share(ref, latest)
    out["rankChange"] = change
    out["meetsRankChangeShare"] = (
        change["share"] >= rules["minRankChangeShare"] if change["share"] is not None else None
    )
    checks = [out["asOfAfterPreregistration"], out["contentDiffers"], out["meetsRankChangeShare"]]
    out["qualifies"] = None if None in checks else all(checks)
    return out


def native_offline(app_dir: Path) -> dict[str, Any]:
    """Tier 1a: the private IDP releases only.  Booleans, counts and
    release-interval statistics; no value, ratio or name."""
    import gzip  # noqa: PLC0415

    from src.sources.signals import parse_iso  # noqa: PLC0415

    base = app_dir / "data" / "sources" / "signals" / "values" / "idp"
    releases = [
        r
        for r in (_read_json(p) for p in sorted((base / "releases").glob("*.json")))
        if isinstance(r, dict)
    ]
    releases.sort(key=lambda r: str(r.get("asOf") or ""))
    out: dict[str, Any] = {"releases": len(releases)}
    if not releases:
        out["state"] = "no_releases"
        return out
    latest = releases[-1]
    obs = [o for o in latest.get("observations") or [] if isinstance(o, Mapping)]
    vocab: dict[str, int] = {}
    for o in obs:
        raw = str(o.get("rawPosition") or "UNKNOWN")
        vocab[raw] = vocab.get(raw, 0) + 1
    out["rawPositionCounts"] = vocab
    tops: dict[str, list[float]] = {}
    for o in obs:
        if _num(o.get("nativeValue")) and o.get("position") in IDP_POSITIONS:
            tops.setdefault(str(o["position"]), []).append(float(o["nativeValue"]))
    s1 = {}
    if all(tops.get(f) for f in FAMILIES):
        curves = {f: sorted(v, reverse=True) for f, v in tops.items()}
        heads = [curves[f][0] for f in FAMILIES]
        s1["familyTopsWithin5pct"] = max(heads) / min(heads) <= 1.05
        for k in (12, 24):
            norm = [curves[f][k - 1] / curves[f][0] for f in FAMILIES if len(curves[f]) >= k]
            s1[f"normalisedCurvesWithin5pctAt{k}"] = (
                (max(norm) - min(norm)) <= 0.05 if len(norm) == len(FAMILIES) else None
            )
    out["s1"] = s1
    # Monotone share of value in the vendor composite, from the raw blob.
    monotone: dict[str, Any] = {"state": "raw_unavailable"}
    raw_sha = str(latest.get("rawSha256") or "")
    raw_path = base / "raw" / f"{raw_sha}.json.gz"
    if raw_sha and raw_path.is_file():
        try:
            pages = json.loads(gzip.decompress(raw_path.read_bytes()).decode("utf-8"))
        except (OSError, ValueError):
            pages = None
        items: list[Mapping[str, Any]] = []

        def walk(x: Any) -> None:
            if isinstance(x, Mapping):
                if "sleeperPlayerId" in x and "value" in x:
                    items.append(x)
                else:
                    for v in x.values():
                        walk(v)
            elif isinstance(x, list):
                for v in x:
                    walk(v)

        walk(pages)
        pairs_ok = pairs = 0
        by_fam: dict[str, list[tuple[float, float]]] = {}
        for it in items:
            data = it.get("data")
            if isinstance(data, str):
                with contextlib.suppress(ValueError):
                    data = json.loads(data)
            comp = data.get("composite") if isinstance(data, Mapping) else None
            if _num(comp) and _num(it.get("value")):
                by_fam.setdefault(str(it.get("family") or ""), []).append(
                    (float(comp), float(it["value"]))
                )
        for vals in by_fam.values():
            vals.sort()
            for (c1, v1), (c2, v2) in zip(vals, vals[1:]):
                if c1 == c2:
                    continue
                pairs += 1
                pairs_ok += v2 >= v1
        monotone = {
            "state": "measured" if pairs else "no_composite",
            "adjacentPairs": pairs,
            "monotoneShareAbove95pct": (pairs_ok / pairs > 0.95) if pairs else None,
        }
    out["valueMonotoneInComposite"] = monotone
    stamps = [str(o.get("valueAsOf") or "") for o in obs]
    out["timestampCensus"] = {
        "observations": len(stamps),
        "distinctValueAsOf": len({s for s in stamps if s}),
        "missingValueAsOf": sum(1 for s in stamps if not s),
        "equalToReleaseAsOf": sum(1 for s in stamps if s and s == latest.get("asOf")),
    }
    dates = [parse_iso(r.get("asOf")) for r in releases]
    dates = [d for d in dates if d is not None]
    gaps = [(b - a).total_seconds() / 86400.0 for a, b in zip(dates, dates[1:])]
    out["releaseIntervalDays"] = {
        "count": len(gaps),
        "medianDays": round(statistics.median(gaps), 2) if gaps else None,
    }
    if len(releases) >= 2:
        out["latestVsPreviousRankChange"] = rank_change_share(releases[-2], latest)
    return out


# ── the two build matrices ───────────────────────────────────────────────


def _n0_boards(served: Mapping[str, Any], value_as_of: str) -> dict[str, list[dict]]:
    """N0: the bridge's own within-family order and coverage, written as
    Signals boards (value = the bridge value, so the derived rank is the
    bridge's order).  Private: it lives only in the frozen tree."""
    boards: dict[str, list[dict]] = {k: [] for k in FAMILY_KEYS.values()}
    for fam, key in FAMILY_KEYS.items():
        rows = sorted(
            (
                (-float(r["csv"][BRIDGE]), str(r.get("n") or "").casefold(), r)
                for r in served.get("rows") or []
                if r.get("pos") == fam
                and _num((r.get("csv") or {}).get(BRIDGE))
                and float(r["csv"][BRIDGE]) > 0
            ),
            key=lambda t: (t[0], t[1]),
        )
        prev, prev_rank = None, 0
        for idx, (neg, _l, r) in enumerate(rows, start=1):
            rank = prev_rank if neg == prev else idx
            prev, prev_rank = neg, rank
            boards[key].append(
                {
                    "name": r.get("n"),
                    "rank": rank,
                    "value": -neg,
                    "sleeper_id": r.get("pid") or "",
                    "position": fam,
                    "raw_position": fam,
                    "team": "",
                    "basis": "NATIVE_VALUE",
                    "rank_derived": 1,
                    "value_as_of": value_as_of,
                    "dataset": "idp",
                }
            )
    return boards


def _board_value_as_of(tree: Path) -> str:
    import csv as _csv  # noqa: PLC0415

    path = tree / _board_rel(FAMILY_KEYS["DL"])
    if path.is_file():
        with path.open(encoding="utf-8", newline="") as fh:
            for row in _csv.DictReader(fh):
                return str(row.get("value_as_of") or "")
    return ""


def _variant_public(build: Mapping[str, Any], intended: Mapping[str, str] | None) -> dict[str, Any]:
    states = {k: v for k, v in (build.get("voteStates") or {}).items() if k.startswith("signals")}
    out: dict[str, Any] = {"status": build.get("status")}
    if build.get("status") == "built":
        out["voteStates"] = states
        out["voteStateAsIntended"] = (
            all(states.get(k) == v for k, v in intended.items()) if intended else None
        )
        out["contractHealthOk"] = build.get("contractHealthOk")
        out["bridgeContributors"] = len(build.get("bridgeContributors") or [])
    else:
        out["reason"] = build.get("reason") or build.get("error")
        if build.get("refusedFlag"):
            out["refusedFlag"] = build["refusedFlag"]
    return out


def _usable(build: Mapping[str, Any] | None, intended: Mapping[str, str] | None) -> bool:
    if not build or build.get("status") != "built":
        return False
    states = build.get("voteStates") or {}
    if intended and not all(states.get(k) == v for k, v in intended.items()):
        return False
    return len(build.get("bridgeContributors") or []) <= 1


def _active(*fams: str) -> dict[str, str]:
    return {FAMILY_KEYS[f]: "active" for f in fams}


def run_matrix(
    mode: str,
    *,
    freeze: Path,
    code_dir: Path,
    payload_path: str,
    flags: Mapping[str, bool],
    part: str = "all",
) -> tuple[dict[str, dict], dict[str, dict[str, str] | None]]:
    """Build every variant of ``mode`` (D1 ``diagnose`` or E ``gate``).

    D1 never builds Candidate F, H or G (the quarantine): its candidate is A
    via the round-1 master flag, isolated per family by EMPTY boards for the
    other families (no per-family flag exists in round-1 code).  The gate
    builds F through the implementation unit's flags; a flag the deployed
    code has not registered refuses the build (fail closed).

    ``part`` splits the matrix across dispatches when it would not fit the
    job's 30 minutes: ``core`` (the candidate, per-family and N0 builds) and
    ``extra`` (the counterfactual pairs and the leave-reference-out builds);
    the served build is part of both."""
    if part not in MATRIX_PARTS:
        raise ValueError(part)
    tree = freeze / "tree"
    variants_dir = freeze / "variants"
    common = {"freeze": freeze, "code_dir": code_dir, "payload_path": payload_path, "flags": flags}
    builds: dict[str, dict] = {}
    intended: dict[str, dict[str, str] | None] = {}

    forbidden = {XWALK_FLAG, *FAMILY_FLAGS.values()}

    def build(name: str, csv_root: Path, want: dict[str, str] | None, **kw: Any) -> dict:
        # The D1 quarantine, enforced: no diagnose build may switch on the
        # Candidate F machinery, whether by a toggle or inherited from the
        # served flags (a D1 run after F is switched on in production).
        if mode == "diagnose" and forbidden & {
            k for k, on in {**dict(flags), **(kw.get("toggles") or {})}.items() if on
        }:
            raise RuntimeError("d1_quarantine_violation")
        extra = name.endswith(_EXTRA_SUFFIXES)
        if name != "served" and ((part == "core" and extra) or (part == "extra" and not extra)):
            builds[name] = {"status": "skipped", "reason": f"matrix_part_{part}"}
            intended[name] = want
            return builds[name]
        builds[name] = run_variant(name, csv_root=csv_root, **common, **kw)
        intended[name] = want
        return builds[name]

    served = build("served", tree, None, identity=True)
    if served.get("status") != "built":
        return builds, intended
    no_ds = {REFERENCE: {"include": False}}
    if mode == "diagnose":
        a_toggle = {ACTIVE_FLAG: True, MASTER_FLAG: True}
        build(
            "noSignals",
            tree,
            {k: "rolled_back" for k in FAMILY_KEYS.values()},
            toggles={ACTIVE_FLAG: False},
        )
        build("A_all", tree, _active(*FAMILIES), toggles=a_toggle)
        for fam in FAMILIES:
            others = {FAMILY_KEYS[f]: [] for f in FAMILIES if f != fam}
            root = derive_tree(tree, variants_dir / f"A_{fam}", others)
            build(f"A_{fam}", root, _active(fam), toggles=a_toggle)
        n0_root = derive_tree(
            tree, variants_dir / "N0", _n0_boards(served, _board_value_as_of(tree))
        )
        build("N0", n0_root, _active(*FAMILIES), toggles=a_toggle)
        build("served_noRetention", tree, None, patches={"_SINGLE_SOURCE_VALUE_RETENTION": 1.0})
        build(
            "A_all_noRetention",
            tree,
            _active(*FAMILIES),
            toggles=a_toggle,
            patches={"_SINGLE_SOURCE_VALUE_RETENTION": 1.0},
        )
        build("served_hampelOff", tree, None, patches={"_HAMPEL_MIN_N": HAMPEL_OFF_MIN_N})
        build(
            "A_all_hampelOff",
            tree,
            _active(*FAMILIES),
            toggles=a_toggle,
            patches={"_HAMPEL_MIN_N": HAMPEL_OFF_MIN_N},
        )
        build("served_noRef", tree, None, source_overrides=no_ds)
        build("A_all_noRef", tree, _active(*FAMILIES), toggles=a_toggle, source_overrides=no_ds)
        build("N0_noRef", n0_root, _active(*FAMILIES), toggles=a_toggle, source_overrides=no_ds)
        return builds, intended
    if mode != "gate":
        raise ValueError(mode)
    f_base = {ACTIVE_FLAG: True, MASTER_FLAG: True, XWALK_FLAG: True}
    f_all = {**f_base, **{FAMILY_FLAGS[f]: True for f in FAMILIES}}
    for fam in FAMILIES:
        build(f"F_{fam}", tree, _active(fam), toggles={**f_base, FAMILY_FLAGS[fam]: True})
    build("F_all", tree, _active(*FAMILIES), toggles=f_all)
    build("F_all_deepTail", tree, _active(*FAMILIES), toggles={**f_all, DEEP_TAIL_FLAG: True})
    n0_root = derive_tree(tree, variants_dir / "N0F", _n0_boards(served, _board_value_as_of(tree)))
    build("N0F", n0_root, _active(*FAMILIES), toggles=f_all)
    build("served_noRef", tree, None, source_overrides=no_ds)
    build("F_all_noRef", tree, _active(*FAMILIES), toggles=f_all, source_overrides=no_ds)
    build("N0F_noRef", n0_root, _active(*FAMILIES), toggles=f_all, source_overrides=no_ds)
    return builds, intended


def _watch(served: Mapping[str, Any], var: Mapping[str, Any], fam: str | None) -> dict[str, Any]:
    outcomes = _watch_outcomes(watch_list(_pseudo_contract(served), _pseudo_contract(var)))
    if fam:
        outcomes = [w for w in outcomes if w.get("position") == fam]
    judged = [
        w["withinRowRange15pct"] for w in outcomes if w.get("withinRowRange15pct") is not None
    ]
    floor = int(GATES["empirical"][0].get("publicOnlyWhenEntriesAtLeast") or 5)
    out: dict[str, Any] = {"value": (all(judged) if judged else None)}
    if len(judged) >= floor:
        out["public"] = {"entries": len(judged), "withinRange": sum(1 for j in judged if j)}
    return out


def analyse(
    mode: str,
    app_dir: Path,
    builds: Mapping[str, dict],
    intended: Mapping[str, dict[str, str] | None],
) -> dict[str, Any]:
    served = builds["served"]
    s_rows = _rowmap(served)
    identity = served.get("identity") or {}
    cand = "A" if mode == "diagnose" else "F"
    rep: dict[str, Any] = {"families": {}, "board": {}, "verdicts": {}, "negativeControls": {}}
    for fam in FAMILIES:
        rep["families"][fam] = {
            "identity": (identity.get("families") or {}).get(fam),
            "variants": {},
        }
    # Where each family's shadow of the SAME candidate is published: D1's
    # served build carries A's shadow; in the gate, a family is in F shadow
    # (xwalk on, its own flag off) on another family's isolated build.
    cand_id = CANDIDATE_F_ID if cand == "F" else str(GATES["candidates"]["A"]["id"])
    shadow_refs: dict[str, Mapping[str, dict] | None] = {f: None for f in FAMILIES}
    if cand == "F":
        for fam in FAMILIES:
            for other in FAMILIES:
                b = builds.get(f"F_{other}")
                if other != fam and _usable(b, intended.get(f"F_{other}")):
                    shadow_refs[fam] = _rowmap(b)
                    break
            else:
                shadow_refs[fam] = {}
    # Per-variant statistics against the served build.
    for name, b in builds.items():
        if name == "served" or name.endswith("_noRef") or not _usable(b, intended.get(name)):
            continue
        v_rows = _rowmap(b)
        rep["board"][name] = board_stats(s_rows, v_rows)
        for fam in FAMILIES:
            if FAMILY_KEYS[fam] in (intended.get(name) or {}) or name.startswith(
                ("served", "noSignals")
            ):
                rep["families"][fam]["variants"][name] = family_stats(
                    s_rows,
                    v_rows,
                    fam,
                    identity=identity,
                    shadow_rows=shadow_refs.get(fam),
                    candidate_id=cand_id,
                )
    rep["coordinates"] = coordinate_diagnostics(
        served,
        builds.get(f"{cand}_all")
        if _usable(builds.get(f"{cand}_all"), intended.get(f"{cand}_all"))
        else None,
        shadow_candidate="A",
        split_coverage=mode != "diagnose",
    )
    n0_name = "N0" if mode == "diagnose" else "N0F"
    # Negative controls on the corrected-panel signed bias (§6.1).
    nc: dict[str, Any] = {}
    nc1_src = builds.get("A_all") if mode == "diagnose" else served
    if mode == "diagnose" and _usable(nc1_src, intended.get("A_all")):
        nc1 = rep["families"]["DB"]["variants"].get("A_all", {}).get("signedBiasCorrectedPanel")
    else:
        key, a_id = FAMILY_KEYS["DB"], str(GATES["candidates"]["A"]["id"])
        pairs = [
            (float(((r.get("shadow") or {}).get(key) or {})["wouldContribute"]), r)
            for r in s_rows.values()
            if r.get("pos") == "DB"
            and _num(((r.get("shadow") or {}).get(key) or {}).get("wouldContribute"))
            and (((r.get("shadow") or {}).get(key) or {}).get("candidate") or a_id) == a_id
        ]
        nc1 = signed_bias(pairs, FAMILY_KEYS.values(), corrected=True)
    nc["NC1"] = {"family": "DB", "signedBiasCorrectedPanel": nc1}
    draws = int(GATES["negativeControls"][1]["draws"])
    seed = int(GATES["negativeControls"][1]["seed"])
    thr = next(c["threshold"] for c in GATES["empirical"] if c["id"] == "G6b")
    void_all = (
        nc1 is not None
        and nc1.get("median") is not None
        and nc1["n"] >= MIN_CELL
        and abs(nc1["median"]) <= thr
    )
    for fam in FAMILIES:
        iso = builds.get(f"{cand}_{fam}")
        cell: dict[str, Any] = {}
        if _usable(iso, intended.get(f"{cand}_{fam}")):
            cell.update(permutation_controls(iso, fam, draws=draws, seed=seed))
        n0_stats = rep["families"][fam]["variants"].get(n0_name, {})
        cell["NC4"] = n0_stats.get("signedBiasCorrectedPanel")
        passes = [
            k
            for k in ("NC2", "NC3", "NC4")
            if isinstance(cell.get(k), Mapping)
            and cell[k].get("median") is not None
            and (cell[k].get("n") or 0) >= MIN_CELL
            and abs(cell[k]["median"]) <= thr
        ]
        cell["controlsPassingTheCheck"] = (["NC1"] if void_all else []) + passes
        cell["g6bCorrectedPanelVoid"] = bool(void_all or passes)
        nc[fam] = cell
    rep["negativeControls"] = nc
    # Verdicts per family on its isolated build.
    combined = builds.get(f"{cand}_all")
    for fam in FAMILIES:
        name = f"{cand}_{fam}"
        stats = rep["families"][fam]["variants"].get(name)
        if stats is None:
            reason = (builds.get(name) or {}).get("refusedFlag") or (builds.get(name) or {}).get(
                "reason"
            )
            rep["verdicts"][fam] = {"state": "VOID", "reason": reason or "variant_not_usable"}
            continue
        board = rep["board"][name]
        n0_stats = rep["families"][fam]["variants"].get(n0_name, {})
        b_f, b_n0 = (
            cell.get("median") if (cell.get("n") or 0) >= MIN_CELL else None
            for cell in (
                stats.get("signedBiasCorrectedPanel") or {},
                n0_stats.get("signedBiasCorrectedPanel") or {},
            )
        )
        watch = _watch(served, builds[name], fam)
        trades = trade_check(app_dir, _pseudo_contract(served), _pseudo_contract(builds[name]))
        extra = {
            "g6bStructuralGap": round(abs(b_f - b_n0), 4)
            if b_f is not None and b_n0 is not None
            else None,
            "watchWithinRange": watch["value"],
            "trades": trades.get("scored") if trades.get("available") else 0,
        }
        void = {}
        if nc[fam]["g6bCorrectedPanelVoid"]:
            void["G6b"] = "negative control passed: " + ",".join(nc[fam]["controlsPassingTheCheck"])
        verdicts = family_verdicts(fam, stats, board, extra, void=void)
        for section in verdicts.values():
            for entry in section.values():
                if isinstance(entry.get("value"), float):
                    entry["value"] = _sig(entry["value"])
        verdicts["candidate"] = (
            CANDIDATE_F_ID if cand == "F" else str(GATES["candidates"]["A"]["id"])
        )
        verdicts["promotable"] = cand == "F"
        if "public" in watch:
            verdicts["watchListCounts"] = watch["public"]
        else:
            rep.setdefault("privateWatchVerdicts", {})[fam] = verdicts["empirical"]["G3"]
            verdicts["empirical"]["G3"] = {"suppressed": "watch entries below the public floor"}
        verdicts["trades"] = {"available": trades.get("available"), "scored": trades.get("scored")}
        rep["verdicts"][fam] = verdicts
    if _usable(combined, intended.get(f"{cand}_all")):
        watch_all = _watch(served, combined, None)
        rep["verdicts"]["combined"] = {
            "candidate": f"{cand}_all",
            **(
                {"watchWithinRange": watch_all["value"], "watchListCounts": watch_all["public"]}
                if "public" in watch_all
                else {"watchSuppressed": "watch entries below the public floor"}
            ),
        }
    rep["information"] = information_diagnostic(
        served,
        builds.get("served_noRef"),
        builds.get(f"{cand}_all_noRef"),
        builds.get(f"{n0_name}_noRef"),
    )
    if mode == "diagnose":
        if _usable(builds.get("A_all"), intended.get("A_all")):
            rep["reproduction"] = reproduction_verdicts(
                reproduction_observed(app_dir, served, builds["A_all"])
            )
        premises: dict[str, Any] = {}
        dl = rep["families"]["DL"]["variants"].get("A_all", {}).get("haircut", {})
        p1 = dl.get("tailShareInLiftedSet")
        p2 = {
            fam: (
                rep["families"][fam]["variants"].get("N0", {}).get("signedBiasCorrectedPanel") or {}
            ).get("median")
            for fam in ("LB", "DB")
        }
        p3 = sum(
            1
            for r in s_rows.values()
            if r.get("pos") in IDP_POSITIONS
            and float(((r.get("meta") or {}).get(IDP_SHOW) or {}).get("appliedWeight") or 0) > 0
        )
        values = {"P1": p1, "P2": p2, "P3": p3}
        for prem in GATES["premises"]:
            val = values[prem["id"]]
            if prem["id"] == "P2":
                verdicts_p2 = [judge(prem["op"], v, prem["threshold"]) for v in val.values()]
                verdict = (
                    "INSUFFICIENT"
                    if "INSUFFICIENT" in verdicts_p2
                    else ("PASS" if all(v == "PASS" for v in verdicts_p2) else "FAIL")
                )
                premises["P2"] = {"value": {k: _sig(v) for k, v in val.items()}, "verdict": verdict}
            else:
                premises[prem["id"]] = {
                    "value": _sig(val),
                    "verdict": judge(prem["op"], val, prem["threshold"]),
                }
        rep["premises"] = premises
    return rep


# ── v2 entry point ────────────────────────────────────────────────────────


def v2_main(args: argparse.Namespace, app_dir: Path, code_dir: Path, utc: str) -> int:
    global _DEADLINE
    _DEADLINE = time.monotonic() + TIME_BUDGET_SECONDS
    report: dict[str, Any] = {
        "schema": "signals-idp-onbox-v2/1",
        "mode": args.mode,
        "utc": utc,
        "preregistrationId": GATES["preregistrationId"],
        "matrixPart": getattr(args, "matrix_part", "all"),
        "gatesSha256": _sha256_bytes(_GATES_JSON.encode("utf-8"))[:12],
    }
    start = deploy_fingerprint(app_dir)
    names: set[str] = collect_private_names(app_dir, [])
    reports_dir = app_dir / "data" / "sources" / "signals" / "reports"
    if args.mode == "native-offline":
        report["nativeOffline"] = native_offline(app_dir)
    else:
        mem = mem_available_mb()
        report["memory"] = {
            "memAvailableMbAtStart": mem,
            "requiredMb": MIN_MEM_AVAILABLE_MB,
            "sufficient": None if mem is None else mem >= MIN_MEM_AVAILABLE_MB,
        }
        flags = served_flags(fetch_status())
        flags_sha = _sha256_bytes(json.dumps(flags, sort_keys=True).encode("utf-8"))[:12]
        reports_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(reports_dir, 0o700)
        sweep_freezes(reports_dir, time.time())
        freeze = reports_dir / f"{FREEZE_PREFIX}{utc.replace(':', '')}"
        freeze.mkdir(mode=0o700, parents=True, exist_ok=False)
        if args.mode == "diagnose":
            pins = {
                "idp_pin": GATES["d1"]["idpReleasePin"],
                "offense_pin": GATES["d1"]["offenseReleasePin"] if args.payload_ref else None,
                "payload_ref": args.payload_ref,
            }
        else:
            pins = {"idp_pin": None, "offense_pin": None, "payload_ref": None}
        info = build_freeze(app_dir, freeze, **pins)
        report["inputs"] = {
            k: info.get(k)
            for k in (
                "treeKind",
                "payloadName",
                "fileCount",
                "freezeManifestSha256",
                "idpReleasePin",
                "idpReleaseFound",
                "offenseReleasePin",
                "offenseReleaseFound",
            )
        }
        report["inputs"].update(
            {
                "flagsSource": "local /api/status featureFlags",
                "flagsSnapshotSha256": flags_sha,
                "payloadRef": args.payload_ref,
            }
        )
        report["private"] = {"manifest": info["manifest"], "flags": flags, "freeze": str(freeze)}
        if args.mode == "diagnose" and not info.get("idpReleaseFound"):
            report["verdicts"] = {"state": "VOID", "reason": "d1_release_pin_absent"}
        else:
            if args.mode == "gate":
                report["release"] = release_qualification(
                    app_dir, role=args.release_role, r1_pin=args.r1_release
                )
            builds, intended = run_matrix(
                args.mode,
                freeze=freeze,
                code_dir=code_dir,
                payload_path=info["payloadPath"],
                flags=flags,
                part=args.matrix_part,
            )
            report["variants"] = {n: _variant_public(b, intended.get(n)) for n, b in builds.items()}
            served = builds.get("served") or {}
            names |= collect_private_names(app_dir, served.get("rows") or [])
            if served.get("status") == "built":
                report.update(analyse(args.mode, app_dir, builds, intended))
                if args.mode == "gate" and not (report.get("release") or {}).get("qualifies"):
                    report["verdicts"]["state"] = "INSUFFICIENT: not_a_qualifying_release"
            else:
                report["verdicts"] = {"state": "VOID", "reason": "served_build_failed"}
    end = deploy_fingerprint(app_dir)
    report["deploy"] = compare_fingerprints(start, end)
    allow = list(GATES["privacy"]["publicAllow"])
    public = sanitize_public(project_allowlist(report, allow))
    try:
        path = reports_dir / f"onbox_v2_{args.mode}_{utc.replace(':', '')}.json"
        reports_dir.mkdir(parents=True, exist_ok=True)
        _write_private(
            path, json.dumps(report, indent=2, sort_keys=True, default=str).encode("utf-8")
        )
        public["privateReport"] = str(path.relative_to(app_dir))
    except OSError as exc:
        public["privateReport"] = None
        public["privateReportError"] = type(exc).__name__
    assert_public_safe_v2(public, names)
    print(json.dumps(public, indent=2, sort_keys=True, default=str))
    return 3 if report["deploy"]["intervened"] else 0


def legacy_main(args: argparse.Namespace, app_dir: Path, utc: str) -> int:
    """Round 1's run, unchanged except the sanitised public projection."""
    report: dict[str, Any] = {"utc": utc}
    rc, sha = _run(["git", "-C", str(app_dir), "rev-parse", "HEAD"])
    report["deployedCommit"] = sha.strip() if rc == 0 else None
    report["timer"] = check_timer(app_dir)
    report["session"] = check_session()
    if args.collect:
        report["collection"] = run_collection()
    report["collector"] = collector_state(app_dir)
    if not args.skip_builds:
        champion, shipped, promoted, payload = build_three(app_dir, promote=args.candidate_f)
        report["payload"] = payload
        report["privateSourceAvailability"] = shipped.get("privateSourceAvailability")
        report["offense"] = offense_report(champion, shipped, report["collector"])
        if promoted is None:
            report["idpPromotedBuild"] = "quarantined_until_R1:candidate_f_not_requested"
        else:
            ladders = _family_ladders()  # from the PROMOTED build (last built)
            report["idp"] = idp_report(shipped, promoted, ladders)
            report["idp"]["familyLadderDepths"] = {k: len(v) for k, v in ladders.items()}
            report["watchList"] = watch_list(shipped, promoted)
            report["trades"] = trade_check(app_dir, shipped, promoted)
        names = [r.get("displayName") for r in shipped.get("playersArray") or []]
    else:
        names = []
    # A deploy that lands mid-run swaps the checkout under the in-process
    # builds, so the measurement could mix two code revisions.  The workflow
    # no longer shares the deploy concurrency group (a queued deploy would
    # cancel a pending run into silence), so this is checked, not assumed:
    # a changed HEAD makes the run unusable and it exits non-zero.
    rc_end, sha_end = _run(["git", "-C", str(app_dir), "rev-parse", "HEAD"])
    report["deployedCommitAtEnd"] = sha_end.strip() if rc_end == 0 else None
    report["deployIntervened"] = (
        report["deployedCommit"] is None
        or report["deployedCommitAtEnd"] != report["deployedCommit"]
    )
    public = sanitize_public(public_projection(report))
    try:
        private_path = _write_private_report(app_dir, report)
        public["privateReport"] = str(private_path.relative_to(app_dir))
    except OSError as exc:
        # The aggregates still print; the full report is simply not kept.
        public["privateReport"] = None
        public["privateReportError"] = type(exc).__name__
    assert_public_safe(public, names)
    print(json.dumps(public, indent=2, sort_keys=True, default=str))
    return 3 if report["deployIntervened"] else 0


_HEX = re.compile(r"^[0-9a-f]{7,40}$")


def main() -> int:
    if "--child" in sys.argv:
        return child_entry(sys.argv)
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--app-dir", default=os.getcwd())
    ap.add_argument(
        "--code-dir",
        default=None,
        help="where src/ lives (default: --app-dir; differs only in tests)",
    )
    ap.add_argument("--mode", choices=MODES, default="legacy")
    ap.add_argument("--collect", action="store_true", help="start one real collection first")
    ap.add_argument("--skip-builds", action="store_true")
    # Candidate F statistics are preregistered for the first qualifying release
    # (R1; plan 4.3 D1 quarantine): never computed unless explicitly asked for.
    # Legacy mode only -- the v2 modes own their F builds (gate) or refuse them
    # outright (diagnose's D1 quarantine).
    ap.add_argument("--candidate-f", action="store_true", help="build the F-promoted board")
    ap.add_argument(
        "--payload-ref",
        default=None,
        help="diagnose only: materialise the public inputs from this commit",
    )
    ap.add_argument("--release-role", choices=("R1", "R2"), default="R1")
    ap.add_argument("--matrix-part", choices=MATRIX_PARTS, default="all")
    ap.add_argument("--r1-release", default=None, help="gate R2 only: the R1 release (12 hex)")
    args = ap.parse_args()
    app_dir = Path(args.app_dir).resolve()
    code_dir = Path(args.code_dir).resolve() if args.code_dir else app_dir
    utc = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    refusal = None
    if args.collect and args.mode != "legacy":
        refusal = "collect_is_legacy_only"
    elif args.candidate_f and args.mode != "legacy":
        refusal = "candidate_f_is_legacy_only"
    elif args.payload_ref and (args.mode != "diagnose" or not _HEX.match(args.payload_ref)):
        refusal = "invalid_payload_ref"
    elif args.r1_release and not re.fullmatch(r"[0-9a-f]{12}", args.r1_release):
        refusal = "invalid_r1_release"
    elif args.mode == "gate" and args.release_role == "R2" and not args.r1_release:
        refusal = "r2_needs_r1_release"
    elif args.matrix_part != "all" and args.mode not in ("diagnose", "gate"):
        refusal = "matrix_part_needs_a_build_mode"
    if refusal:
        print(json.dumps({"error": "refused", "reason": refusal}))
        return 2
    sys.path.insert(0, str(code_dir))
    os.chdir(app_dir)
    os.environ.setdefault("RISKIT_SIGNALS_AUTH_DIR", "/var/lib/signals-auth")
    with private_stderr(app_dir, utc):
        try:
            if args.mode == "legacy":
                return legacy_main(args, app_dir, utc)
            return v2_main(args, app_dir, code_dir, utc)
        except BaseException as exc:  # noqa: BLE001 — the class only, never the text
            traceback.print_exc(file=sys.stderr)
            print(json.dumps({"error": type(exc).__name__}))
            return 2


if __name__ == "__main__":
    raise SystemExit(main())
