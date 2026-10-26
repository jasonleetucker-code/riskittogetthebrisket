#!/usr/bin/env python3
"""Lane C-market baseline: canonical cross-position (IDP vs offense) diagnostics.  RESEARCH ONLY.

Owner authorization: ``docs/owner/IDP_VALUATION_ACCURACY_DIRECTIVE_2026-10-25.md`` §6C, §9,
Lane C ("market and cross-position valuation research").  This script changes NO value,
rank, weight, vote, curve, bridge, flag default or served behaviour.  Every alternative
below (a removed source, a re-seeded or rescaled bridge ladder, a rescaled bridge market)
is a SHADOW contract built in a separate interpreter through the canonical entry point
``build_api_data_contract``; nothing is written back and nothing imports this file.

What it produces (one JSON evidence file, aggregates and public NFL player names only):

1. ``baseline`` — from the pinned served artifact: the top 100 / top 200 overall with
   positions, the top 25 DL / LB / DB with values, the highest-ranked defenders with their
   per-source contributions, offense-vs-IDP rank-band counts and value quantiles,
   source coverage and confidence buckets per position, a missing / stale /
   quarantined / withheld evidence census.
2. ``starterBenchByTier`` — how the 12 live ``dynasty_main`` rosters' players split
   between weekly best-ball starters and bench, by canonical price band.  Each week's
   lineup is the exact optimum (``src.ros.lineup.solve_optimal_assignment``) under that
   week's realized league-scored points (``src.nfl_data.realized_points``).  Aggregated
   over teams; no team, manager or roster listing is emitted.
3. ``idpTradeCalcNative`` — the raw IDP Trade Calculator distribution
   (``canonicalSiteValues.idpTradeCalc``): offense vs IDP, where its k-th defender sits on
   its OWN combined board, against where the k-th defender sits on the canonical board;
   plus ``nativeLevelRatios`` (IDP value / offense value at equal depth on the canonical
   board and on each cross-position bridge's own scale).
4. ``bridgeTrace`` + ``perturbations`` — how cross-position level enters consensus (which
   voters are anchors, which coordinate pool / Hill master each vote is priced on, which
   market seeds the shared-market ladder) and how far IDP-vs-offense placement moves when
   that anchor is removed, re-seeded or rescaled.  MEASUREMENT ONLY.
5. ``leagueFormatAlignment`` — the external market's STATED format (observed in the pinned
   archive's capture evidence and on the vendor's own pages) against the verified
   ``dynasty_main`` card, with each measurable mismatch quantified (IDP scoring vs the
   vendor-stated "Big 3" card, reception scoring vs ".5 PPR"), plus a descriptive
   card-alignment measurement of each cross-position market's IDP ORDER against
   league-scored, Big 3 and tackle-heavy production.
6. ``correlationReproduction`` — Investigation B's value-vs-production Spearman claims
   (``docs/valuation/IDP_REPLACEMENT_AND_SCORING_2026-10-20.md`` §6) re-run under pinned
   inputs, on (a) the pinned in-season board (hindsight, in-sample), (b) a point-in-time
   pre-season board (latest archive strictly before the 2026 week-1 kickoff, rebuilt from
   that day's source tree), (c) Investigation B's own served 2026-08-25 board.
7. ``verdict`` — the author's judgement on the shared-market anchor (see ``VERDICT``).

Pinned inputs (recorded in the output): repository tree ``--csv-rev`` (default
``bdbc83a1f``) for the source CSVs / scrape stamps / weights the contract build reads;
the archive ``--archive``; 2026 regular-season weeks 1..``--weeks`` (default 6).

Network: the public Sleeper API (league card, rosters, player directory, weekly stats,
matchups for the scorer check) plus two public vendor pages read once (the IDP Trade
Calculator home page and The IDP Show's published "Big 3" scoring page), all cached as
RAW response bytes under ``--cache-dir`` (gitignored ``data/``) and receipted by sha256.  A
cached response is reused, so a re-run reproduces the same inputs; ``--refresh`` refetches.
``--offline`` refuses any uncached request.  When a Lane A manifest is present
(``--manifest``, default ``docs/valuation/idp_accuracy/MANIFEST.json``) the receipts, served
board hash, archive hash and scoring fingerprint are cross-checked against it.

Usage::

    python scripts/idp_accuracy/market_baseline.py            # full run (~4 min)
    python scripts/idp_accuracy/market_baseline.py --offline  # re-run from the cache
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import html as htmllib
import importlib.util
import io
import json
import math
import os
import re
import statistics
import subprocess
import sys
import tempfile
import time
import zipfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "scripts"
sys.path.insert(0, str(REPO))

LEAGUE_KEY = "dynasty_main"
LEAGUE_ID = "1312006700437352448"
SEASON = 2026
SLEEPER = "https://api.sleeper.app/v1"
PINNED_ARCHIVE = "exports/archive/dynasty_export_20261025_120337.zip"
PINNED_CSV_REV = "bdbc83a1f"
#: Latest archive strictly before the 2026 week-1 kickoff (NE @ SEA, 2026-09-09 20:20 ET =
#: 2026-09-10 00:20 UTC, nflverse ``games.csv``).  Its scrape stamp is 21:15:25 UTC.
PRESEASON_ARCHIVE = "exports/archive/dynasty_export_20260909_211525.zip"
#: The automated data-refresh commit that landed that scrape's CSVs (21:17:57 UTC,
#: before kickoff), so the pre-season build reads that day's source boards, not today's.
PRESEASON_CSV_REV = "bd7eda6052a3c40e3dceb2d3bf3f6c8f128078e1"
KICKOFF_UTC = "2026-09-10T00:20:00+00:00"
#: Investigation B's in-season board (its ``b8008c2a4`` tree is not reachable; the main
#: commit current at that archive's time is used instead and labelled as such).
B_INSEASON_ARCHIVE = "exports/archive/dynasty_export_20261020_052241.zip"
B_INSEASON_CSV_REV = "21009b964c3791829613ad4f4a75ff27536f6d28"
OUT_DEFAULT = "docs/valuation/idp_accuracy/evidence/c_market_baseline_2026-10-25.json"
#: Raw-bytes cache (a different directory from the earlier re-serialized JSON cache, so a
#: stale cache from before receipts existed can never be mistaken for a receipted one).
CACHE_DEFAULT = "data/research_cache/idp_c_market_raw"
MANIFEST_DEFAULT = "docs/valuation/idp_accuracy/MANIFEST.json"

IDPTC_URL = "https://idptradecalculator.com/"
BIG3_URL = "https://www.theidpshow.com/p/big-3-scoring"
#: The IDP Trade Calculator's own page states its IDP basis in the meta description
#: ("... using Big 3 scoring"); The IDP Show publishes what "Big 3" means.  Each parsed
#: label maps to the Sleeper scoring key(s) it prices, so the stated card can be scored on
#: the same stat lines as the league card.  (Return yards price both defensive return keys.)
BIG3_LABEL_TO_SLEEPER: dict[str, tuple[str, ...]] = {
    "Solo Tackles": ("idp_tkl_solo",),
    "Assisted Tackles": ("idp_tkl_ast",),
    "Passes Defended": ("idp_pass_def",),
    "Force Fumble": ("idp_ff",),
    "Fumble Recovery": ("idp_fum_rec",),
    "Sack": ("idp_sack",),
    "Sack Yards": ("idp_sack_yd",),
    "QB Hit": ("idp_qb_hit",),
    "Tackle for Loss": ("idp_tkl_loss",),
    "INT": ("idp_int",),
    "TD": ("idp_def_td",),
    "Safety": ("idp_safe",),
    "Blocked Kick": ("idp_blk_kick",),
    "Return Yards (Defense)": ("idp_int_ret_yd", "idp_fum_ret_yd"),
}
_NUM = r"([0-9]*\.?[0-9]+)"
#: Regexes over the whitespace-collapsed text of the vendor page (tags stripped to a
#: space, so a tag between a label and its colon still matches).
_BIG3_PATTERNS: dict[str, str] = {
    "Solo Tackles": rf"\bSolo Tackles\s*:\s*{_NUM}",
    "Assisted Tackles": rf"\bAssisted Tackles\s*:\s*{_NUM}",
    "Passes Defended": rf"\bPasses Defended\s*:\s*{_NUM}",
    "Force Fumble": rf"\bForce Fumble\s*:\s*{_NUM}",
    "Fumble Recovery": rf"\bFumble Recovery\s*:\s*{_NUM}",
    "Sack": rf"\bSack\s*:\s*{_NUM}",
    "Sack Yards": rf"\bSack Yards\s*\(if applicable\)\s*:\s*1 yard\s*=\s*{_NUM}",
    "QB Hit": rf"\bQB Hit\s*:\s*{_NUM}",
    "Tackle for Loss": rf"\bTackle for Loss\s*:\s*{_NUM}",
    "INT": rf"\bINT\s*:\s*{_NUM}",
    "TD": rf"\bTD\s*:\s*{_NUM}",
    "Safety": rf"\bSafety\s*:\s*{_NUM}",
    "Blocked Kick": rf"\bBlocked Kick\s*:\s*{_NUM}",
    "Return Yards (Defense)": rf"\bReturn Yards\s*\(Defense\)\s*:\s*1 yard\s*=\s*{_NUM}",
}
VENDOR_UA = "Mozilla/5.0 (compatible; riskit-research/1.0; public page read, 1 GET)"
#: The author's judgement, stamped into the evidence so a consumer can find it without
#: reading prose.  It is NOT computed: the numbers it rests on are in ``evidencePaths`` and
#: ``docs/valuation/idp_accuracy/C_MARKET_CROSS_POSITION.md`` argues it.  A test keeps the
#: report and this block in agreement.
VERDICT: dict[str, Any] = {
    "kind": "AUTHOR_JUDGEMENT (not computed)",
    "question": "Is the shared-market cross-position anchor independently justified for "
    "dynasty_main?",
    "answer": "NOT_JUSTIFIED",
    "meaning": "No evidence in this lane shows the anchor represents THIS league.  The level "
    "comes from two external vendor boards.  One states a basis that differs from the "
    "verified card (Big 3 IDP scoring, .5 PPR, a TE premium, no IDP-starter or best-ball "
    "statement); the other is league-synced in name, but the sync cannot be verified.  They "
    "agree on the median IDP level and disagree about WHO the elite defenders are, and their "
    "agreement is consensus about market price rather than evidence of league utility.  It "
    "is NOT a finding that the level is wrong.",
    "levelCorrectness": "UNRESOLVED",
    "levelCorrectnessOwner": "Lanes B and D: replacement-adjusted marginal best-ball utility "
    "and an independent out-of-sample backtest",
    "evidencePaths": [
        "leagueFormatAlignment.mismatches",
        "leagueFormatAlignment.cardAlignment2026wk",
        "nativeLevelRatios",
        "bridgeTrace.topIdpLevelAttribution",
        "perturbations",
        "correlationReproduction",
    ],
}

OFFENSE = ("QB", "RB", "WR", "TE")
IDP = ("DL", "LB", "DB")
POSITIONS = OFFENSE + IDP
#: Rank bands for the offense-vs-IDP distribution (inclusive).
RANK_BANDS: tuple[tuple[int, int], ...] = (
    (1, 25),
    (26, 50),
    (51, 100),
    (101, 150),
    (151, 200),
    (201, 300),
    (301, 400),
    (401, 500),
    (501, 800),
)
TOP_KS = (1, 3, 5, 10, 25, 50, 108)
#: League-wide weekly starter demand, from the verified roster format (12 teams x
#: 9 IDP slots; 12 x (QB 1 + RB 2 + WR 3 + TE 2 + FLEX 2 + SUPER_FLEX 1) offense).
#: Recomputed from the live card in ``league_format``; these are only defaults for tests.
IDP_STARTERS_DEFAULT = 108
OFFENSE_STARTERS_DEFAULT = 132
MIN_GAMES = 3
BOOT = 1000
SEED = 20261020  # Investigation B's seed, so CIs are reproducible against its numbers
#: Investigation B's tackle-heavy REFERENCE card (illustrative, no provider's card) —
#: imported by value from ``scripts/idp_replacement_research.py::REFERENCE_TACKLE_HEAVY``
#: rather than re-authored; ``tests`` pin that the two stay identical.
TACKLE_KEYS = ("idp_tkl_solo", "idp_tkl_ast", "idp_tkl")

#: Bridge-level perturbations (offline shadow builds; MEASUREMENT ONLY).
VARIANTS: dict[str, str] = {
    "baseline": "the pinned build, unchanged (control: must equal the in-process build)",
    "no_idpTradeCalc": "idpTradeCalc removed everywhere (vote AND ladder seed); the next "
    "usable bridge (draftSharks) seeds the shared-market ladder",
    "no_draftSharks": "draftSharks + draftSharksIdp removed (the league-synced bridge)",
    "no_idpShowCombined": "idpShowCombined removed (the third cross-market anchor)",
    "ladder_seed_draftSharks": "same voters; the shared-market ladder is seeded by "
    "draftSharks instead of idpTradeCalc (registry order swapped, limit 1)",
    "ladder_multi_bridge": "same voters; ladder seeded by every usable bridge "
    "(RISKIT_FEATURE_MULTI_BRIDGE_LADDER=1 in the worker process only)",
    "ladder_ranks_x0.80": "shared-market ladder ranks x0.80 (translated IDP-only votes "
    "land 20% higher on the combined board)",
    "ladder_ranks_x1.25": "shared-market ladder ranks x1.25",
    "idptc_idp_values_x0.80": "idpTradeCalc DL/LB/DB values x0.80 in its CSV (its "
    "cross-position level 20% lower; offense and picks untouched)",
    "idptc_idp_values_x1.25": "idpTradeCalc DL/LB/DB values x1.25",
    "ds_idp_values_x0.80": "draftSharksIdp '3D Value +' x0.80 (its IDP level lower against "
    "its own offense half)",
    "ds_idp_values_x1.25": "draftSharksIdp '3D Value +' x1.25",
}


# ═══════════════════════════════════════════════════════════════════════════
# loading helpers
# ═══════════════════════════════════════════════════════════════════════════


def _load_script(name: str, path: Path):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def rpb():
    """The shared archive + CSV-tree pin (``scripts/research_pinned_board.py``)."""
    return _load_script("research_pinned_board", SCRIPTS / "research_pinned_board.py")


def lu():
    """Investigation B's light helpers: Fetcher, pos_group, BANDS, preseason_values."""
    return _load_script(
        "low_value_asset_lineup_utility", SCRIPTS / "low_value_asset_lineup_utility.py"
    )


def reference_tackle_heavy_card() -> dict[str, float]:
    """Investigation B's illustrative tackle-heavy IDP card, read from its source file
    (parsed with ``ast`` so its network/board stack is not imported)."""
    import ast  # noqa: PLC0415

    tree = ast.parse((SCRIPTS / "idp_replacement_research.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "REFERENCE_TACKLE_HEAVY" for t in node.targets
        ):
            return {str(k): float(v) for k, v in ast.literal_eval(node.value).items()}
    raise RuntimeError("REFERENCE_TACKLE_HEAVY not found in idp_replacement_research.py")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(*args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(REPO), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


# ═══════════════════════════════════════════════════════════════════════════
# pure board analysis (unit-tested on synthetic contracts)
# ═══════════════════════════════════════════════════════════════════════════


def _num(x: Any) -> float | None:
    return float(x) if isinstance(x, (int, float)) and not isinstance(x, bool) else None


def board_rows(contract: Mapping[str, Any]) -> list[dict[str, Any]]:
    """One normalized record per ``playersArray`` row.  ``value`` is the served
    ``rankDerivedValue`` (None = unpriced, never 0); ``rank`` the served
    ``canonicalConsensusRank`` (None = unranked)."""
    out = []
    for r in contract.get("playersArray") or []:
        cls = str(r.get("assetClass") or "")
        pos = str(r.get("position") or "").upper() or None
        v = _num(r.get("rankDerivedValue"))
        out.append(
            {
                "name": r.get("displayName") or r.get("canonicalName"),
                "pid": str(r.get("playerId") or "") or None,
                "cls": cls,
                "pos": pos,
                "group": (
                    "pick"
                    if cls == "pick"
                    else "idp"
                    if pos in IDP
                    else "offense"
                    if pos in OFFENSE
                    else "other"
                ),
                "value": v if v is not None and v > 0 else None,
                "rank": r.get("canonicalConsensusRank"),
                "confidence": r.get("confidenceBucket"),
                "quarantined": bool(r.get("quarantined")),
                "sites": dict(r.get("canonicalSiteValues") or {}),
                "meta": dict(r.get("sourceRankMeta") or {}),
                "effective": dict(r.get("effectiveSourceRanks") or {}),
                "freshnessExcluded": list(r.get("freshnessExcludedSources") or []),
                "dropped": list(r.get("droppedSources") or []),
                "weightState": r.get("sourceWeightState"),
                "anchorValue": _num(r.get("anchorValue")),
                "subgroupValue": _num(r.get("subgroupBlendValue")),
                "alpha": _num(r.get("alphaShrinkage")),
                "sourceCount": r.get("sourceCount"),
                "anomalyFlags": list(r.get("anomalyFlags") or []),
                "rookie": bool(r.get("rookie")),
            }
        )
    return out


def ranked(rows: Iterable[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return sorted((r for r in rows if isinstance(r.get("rank"), int)), key=lambda r: r["rank"])


def by_value(rows: Iterable[Mapping[str, Any]], group: str | None = None, pos=None):
    sel = [
        r
        for r in rows
        if r.get("value") is not None
        and (group is None or r["group"] == group)
        and (pos is None or r["pos"] == pos)
    ]
    return sorted(sel, key=lambda r: (-r["value"], str(r["name"])))


def quantiles(values: Sequence[float], ps=(0, 10, 25, 50, 75, 90, 100)) -> dict | None:
    xs = sorted(float(v) for v in values if v is not None)
    if not xs:
        return None
    out = {}
    for p in ps:
        # linear interpolation (numpy default) without importing numpy here
        k = (len(xs) - 1) * p / 100.0
        lo, hi = math.floor(k), math.ceil(k)
        out[f"p{p}"] = round(xs[lo] + (xs[hi] - xs[lo]) * (k - lo), 1)
    out["n"] = len(xs)
    out["mean"] = round(statistics.fmean(xs), 1)
    return out


def top_overall(rows, n: int) -> dict:
    top = ranked(rows)[:n]
    return {
        "n": len(top),
        "positionCounts": dict(Counter(r["pos"] or "?" for r in top)),
        "groupCounts": dict(Counter(r["group"] for r in top)),
        "rows": [
            {"rank": r["rank"], "name": r["name"], "pos": r["pos"], "value": r["value"]}
            for r in top
        ],
    }


def top_by_position(rows, pos: str, n: int = 25) -> list[dict]:
    return [
        {
            "posRank": i + 1,
            "name": r["name"],
            "overallRank": r["rank"],
            "value": r["value"],
            "confidence": r["confidence"],
        }
        for i, r in enumerate(by_value(rows, pos=pos)[:n])
    ]


def band_counts(rows) -> list[dict]:
    rk = ranked(rows)
    out = []
    for lo, hi in RANK_BANDS:
        cell = [r for r in rk if lo <= r["rank"] <= hi]
        c = Counter(r["group"] for r in cell)
        out.append(
            {
                "band": f"{lo}-{hi}",
                "offense": c.get("offense", 0),
                "idp": c.get("idp", 0),
                "pick": c.get("pick", 0),
                "other": c.get("other", 0),
                "idpShareOfPlayers": (
                    round(c["idp"] / (c["idp"] + c["offense"]), 3)
                    if (c.get("idp", 0) + c.get("offense", 0))
                    else None
                ),
            }
        )
    return out


def kth_values(rows, ks: Sequence[int] = TOP_KS, *, offense_ks: Sequence[int] | None = None):
    """Value and overall rank of the k-th best offense player and k-th best defender,
    and the IDP/offense value ratio at equal k (a level comparison, not a verdict)."""
    off, idp = by_value(rows, "offense"), by_value(rows, "idp")
    out = []
    for k in ks:
        o = off[k - 1] if len(off) >= k else None
        d = idp[k - 1] if len(idp) >= k else None
        out.append(
            {
                "k": k,
                "offense": None if o is None else {"name": o["name"], "pos": o["pos"],
                                                   "value": o["value"], "rank": o["rank"]},
                "idp": None if d is None else {"name": d["name"], "pos": d["pos"],
                                               "value": d["value"], "rank": d["rank"]},
                "idpOverOffenseValue": (
                    round(d["value"] / o["value"], 3) if o is not None and d is not None else None
                ),
            }
        )  # fmt: skip
    return out


def placement_metrics(rows) -> dict:
    """The compact IDP-vs-offense placement summary every perturbation is compared on."""
    rk = ranked(rows)
    idp = by_value(rows, "idp")
    out: dict[str, Any] = {
        "topDefender": None
        if not idp
        else {"name": idp[0]["name"], "pos": idp[0]["pos"], "rank": idp[0]["rank"],
              "value": idp[0]["value"]},
        "idpInTopN": {
            str(n): sum(1 for r in rk if r["rank"] <= n and r["group"] == "idp")
            for n in (25, 50, 100, 200, 300)
        },
        "familyKthOverallRank": {
            pos: {str(k): (lst[k - 1]["rank"] if len(lst) >= k else None) for k in (1, 3, 10, 25)}
            for pos in IDP
            for lst in [by_value(rows, pos=pos)]
        },
        "kth": kth_values(rows, (1, 10, 25, 50, 108)),
    }  # fmt: skip
    return out


def compare_placement(base_rows, var_rows, *, idp_n=IDP_STARTERS_DEFAULT,
                      off_n=OFFENSE_STARTERS_DEFAULT) -> dict:  # fmt: skip
    """How far a variant moved IDP placement relative to offense, on the BASELINE's
    top-``idp_n`` defenders and top-``off_n`` offense players (matched by name)."""
    vb = {r["name"]: r for r in var_rows}
    b_idp = by_value(base_rows, "idp")[:idp_n]
    b_off = by_value(base_rows, "offense")[:off_n]

    def _ratios(lst):
        rs, missing = [], 0
        for r in lst:
            v = vb.get(r["name"])
            if v is None or v.get("value") is None:
                missing += 1
                continue
            rs.append(math.log(v["value"] / r["value"]))
        return rs, missing

    ri, mi = _ratios(b_idp)
    ro, mo = _ratios(b_off)
    gi = math.exp(statistics.fmean(ri)) if ri else None
    go = math.exp(statistics.fmean(ro)) if ro else None
    rank_shift = []
    for r in b_idp:
        v = vb.get(r["name"])
        if v and isinstance(v.get("rank"), int) and isinstance(r.get("rank"), int):
            rank_shift.append(v["rank"] - r["rank"])
    bm, vm = placement_metrics(base_rows), placement_metrics(var_rows)
    mi_med = math.exp(statistics.median(ri)) if ri else None
    mo_med = math.exp(statistics.median(ro)) if ro else None
    return {
        "idpGeoMeanValueRatio": None if gi is None else round(gi, 4),
        "offenseGeoMeanValueRatio": None if go is None else round(go, 4),
        "idpRelativeToOffense": None if gi is None or go is None else round(gi / go, 4),
        # The median is robust to a handful of rows falling to the single-source haircut
        # (x0.30) when a variant leaves them one voter; the geo-mean is not.
        "idpMedianValueRatio": None if mi_med is None else round(mi_med, 4),
        "offenseMedianValueRatio": None if mo_med is None else round(mo_med, 4),
        "idpRelativeToOffenseMedian": (
            None if mi_med is None or mo_med is None else round(mi_med / mo_med, 4)
        ),
        "idpRowsHalvedOrWorse": sum(1 for x in ri if x < math.log(0.5)),
        "offenseRowsHalvedOrWorse": sum(1 for x in ro if x < math.log(0.5)),
        "idpRowsUnpricedInVariant": mi,
        "offenseRowsUnpricedInVariant": mo,
        "idpMedianOverallRankShift": statistics.median(rank_shift) if rank_shift else None,
        "idpMeanAbsOverallRankShift": (
            round(statistics.fmean(abs(x) for x in rank_shift), 1) if rank_shift else None
        ),
        "topDefenderRank": {"baseline": (bm["topDefender"] or {}).get("rank"),
                            "variant": (vm["topDefender"] or {}).get("rank"),
                            "variantName": (vm["topDefender"] or {}).get("name")},
        "idpInTop100": {"baseline": bm["idpInTopN"]["100"], "variant": vm["idpInTopN"]["100"]},
        "idpInTop200": {"baseline": bm["idpInTopN"]["200"], "variant": vm["idpInTopN"]["200"]},
    }  # fmt: skip


def coverage_by_position(rows) -> dict:
    """Which sources actually voted (``effectiveSourceRanks``), how many, and the
    confidence buckets, per position (players only)."""
    out = {}
    for pos in POSITIONS:
        sel = [r for r in rows if r["pos"] == pos and r["value"] is not None]
        if not sel:
            continue
        voters = Counter(k for r in sel for k in r["effective"])
        nvote = [len(r["effective"]) for r in sel]
        top = by_value(sel)[: (36 if pos in IDP else 24)]
        out[pos] = {
            "pricedRows": len(sel),
            "votingSourcesPerRow": quantiles(nvote, (0, 25, 50, 75, 100)),
            "rowsBySource": dict(voters.most_common()),
            "confidenceBuckets": dict(Counter(r["confidence"] or "none" for r in sel)),
            "confidenceBucketsTopStarterPool": dict(
                Counter(r["confidence"] or "none" for r in top)
            ),
            "singleVoterRows": sum(1 for n in nvote if n == 1),
        }
    return out


def evidence_census(contract: Mapping[str, Any], rows) -> dict:
    """Missing / stale / quarantined / withheld evidence, by group and source."""
    by_group: dict[str, Any] = {}
    for g in ("offense", "idp", "pick"):
        sel = [r for r in rows if r["group"] == g]
        by_group[g] = {
            "rows": len(sel),
            "priced": sum(1 for r in sel if r["value"] is not None),
            "unpriced": sum(1 for r in sel if r["value"] is None),
            "ranked": sum(1 for r in sel if isinstance(r["rank"], int)),
            "quarantined": sum(1 for r in sel if r["quarantined"]),
            "sourceWeightState": dict(Counter(r["weightState"] or "none" for r in sel)),
            "freshnessExcludedBySource": dict(
                Counter(k for r in sel for k in r["freshnessExcluded"]).most_common()
            ),
            "outlierDroppedBySource": dict(
                Counter(k for r in sel for k in r["dropped"]).most_common()
            ),
            "anomalyFlags": dict(Counter(f for r in sel for f in r["anomalyFlags"]).most_common()),
        }
    status = (contract.get("sourceVotingStatus") or {}).get("sources") or []
    return {
        "byGroup": by_group,
        "rowsUnpricedByBoard": contract.get("rowsUnpricedByBoard"),
        "sourceVotingStatus": [
            {
                "key": s.get("key"),
                "coverage": s.get("coverage"),
                "status": s.get("status"),
                "voting": s.get("voting"),
                "daysSinceUpdate": s.get("daysSinceUpdate"),
                "freshnessPct": s.get("freshnessPct"),
                "effectiveWeight": s.get("effectiveWeight"),
                "contributingByUniverse": s.get("contributingByUniverse"),
            }
            for s in status
        ],
    }


# Which market fixes each IDP vote's CROSS-POSITION level.  A vote in the shared-market
# pool carries an offense-relative level; this names the market that level came from.
def level_source(src_key: str, meta: Mapping[str, Any], ladder_seeds: Sequence[str]) -> str:
    if meta.get("sharedMarketTranslated"):
        # an IDP-only ordinal crosswalked onto the bridge ladder: its level is the seed's
        return "+".join(ladder_seeds) if ladder_seeds else "unknown_seed"
    if src_key.startswith("draftSharks"):
        return "draftSharks"
    if src_key.startswith("idpShow"):
        return "idpShow"
    return src_key


def bridge_trace(contract: Mapping[str, Any], rows, *, anchor_keys: Iterable[str],
                 ladder_seeds: Sequence[str], idp_n: int = IDP_STARTERS_DEFAULT) -> dict:  # fmt: skip
    """How IDP rows get their offense-relative level on this board."""
    anchor_keys = set(anchor_keys)
    pools = Counter()
    for r in rows:
        if r["group"] not in ("idp", "offense"):
            continue
        for k, m in r["meta"].items():
            pools[(r["group"], k, m.get("rankCoordinatePool"), m.get("method"),
                   bool(m.get("sharedMarketTranslated")))] += 1  # fmt: skip
    pool_table = [
        {"group": g, "source": k, "rankCoordinatePool": p, "method": meth,
         "sharedMarketTranslated": t, "rows": n}
        for (g, k, p, meth, t), n in sorted(pools.items(), key=lambda x: (x[0][0], x[0][1]))
    ]  # fmt: skip
    top = by_value(rows, "idp")[:idp_n]
    anchor_sets = Counter()
    level_share = defaultdict(float)
    anchor_weight_total = 0.0
    no_sub = 0
    for r in top:
        contrib = {
            k: m
            for k, m in r["meta"].items()
            if k in r["effective"] and m.get("contributedToBlend") is not False
        }
        anchors = {k: m for k, m in contrib.items() if m.get("isAnchor")}
        subs = {k: m for k, m in contrib.items() if not m.get("isAnchor")}
        anchor_sets[",".join(sorted(anchors)) or "(none)"] += 1
        alpha = r["alpha"] if r["alpha"] is not None else 0.10
        a_share = 1.0 if not subs else (1.0 - alpha) if anchors else 0.0
        s_share = 1.0 - a_share
        if not subs:
            no_sub += 1
        for grp, share in ((anchors, a_share), (subs, s_share)):
            tot = sum(float(m.get("appliedWeight") or 0) for m in grp.values())
            for k, m in grp.items():
                w = float(m.get("appliedWeight") or 0)
                if tot > 0 and share > 0:
                    level_share[level_source(k, m, ladder_seeds)] += share * w / tot
        anchor_weight_total += a_share
    n = len(top) or 1
    return {
        "anchorKeys": sorted(anchor_keys),
        "ladderSeeds": list(ladder_seeds),
        "crossPositionBridges": [
            {k: b.get(k) for k in ("bridgeKey", "family", "kind", "comparability", "state",
                                   "usable", "capability")}
            for b in ((contract.get("crossPositionBridges") or {}).get("bridges") or [])
        ],
        "hillCurves": {
            k: {kk: v.get(kk) for kk in ("c", "s", "midpoint", "routed")}
            for k, v in (contract.get("hillCurves") or {}).items()
            if isinstance(v, dict) and "c" in v
        },
        "votePoolCensus": pool_table,
        "topIdpRows": len(top),
        "topIdpAnchorVoterSets": dict(anchor_sets.most_common()),
        "topIdpRowsWithNoSubgroupVote": no_sub,
        "topIdpMeanAnchorWeight": round(anchor_weight_total / n, 3),
        "topIdpLevelAttribution": {
            k: round(v / n, 3) for k, v in sorted(level_share.items(), key=lambda x: -x[1])
        },
        "levelAttributionMethod": (
            "per row: anchor block weight (1 - alphaShrinkage) when a subgroup vote exists, "
            "else 1; within a block, each contributing source's appliedWeight share.  A "
            "shared-market-translated (IDP-only) vote is attributed to the ladder seed.  An "
            "APPROXIMATION: the blend is a count-aware weighted mean-median, not a weighted "
            "mean, so shares describe influence, not exact derivatives."
        ),
    }  # fmt: skip


def idptc_native(
    rows, *, key: str = "idpTradeCalc", ks: Sequence[int] = TOP_KS, same_scale: bool = True
) -> dict:
    """The raw IDP Trade Calculator board (``canonicalSiteValues[key]``), on its own terms.

    ``same_scale`` False (a native scale that is not 0-9999, e.g. Draft Sharks 3D Value +)
    drops the canonical/native value ratios, which would be meaningless."""
    pts = [r for r in rows if r["group"] in ("offense", "idp") and _num(r["sites"].get(key))]
    pts.sort(key=lambda r: (-float(r["sites"][key]), str(r["name"])))
    native_rank = {r["name"]: i + 1 for i, r in enumerate(pts)}
    with_picks = [
        r for r in rows if r["group"] in ("offense", "idp", "pick") and _num(r["sites"].get(key))
    ]
    with_picks.sort(key=lambda r: (-float(r["sites"][key]), str(r["name"])))
    native_rank_picks = {r["name"]: i + 1 for i, r in enumerate(with_picks)}
    # canonical player-only rank (by served value), so both sides exclude picks
    canon_players = by_value([r for r in rows if r["group"] in ("offense", "idp")])
    canon_rank = {r["name"]: i + 1 for i, r in enumerate(canon_players)}
    idp_native = [r for r in pts if r["group"] == "idp"]
    idp_canon = by_value(rows, "idp")
    kth = []
    for k in ks:
        n = idp_native[k - 1] if len(idp_native) >= k else None
        c = idp_canon[k - 1] if len(idp_canon) >= k else None
        kth.append(
            {
                "k": k,
                "idptcKthDefender": None if n is None else n["name"],
                "idptcPlayerRank": None if n is None else native_rank[n["name"]],
                "idptcRankWithPicks": None if n is None else native_rank_picks[n["name"]],
                "idptcValue": None if n is None else float(n["sites"][key]),
                "canonicalKthDefender": None if c is None else c["name"],
                "canonicalPlayerRank": None if c is None else canon_rank[c["name"]],
                "canonicalServedRank": None if c is None else c["rank"],
                "canonicalValue": None if c is None else c["value"],
            }
        )
    # control: the same k-th comparison for OFFENSE (does the consensus compress the
    # top of every population, or only the defenders?)
    off_native = [r for r in pts if r["group"] == "offense"]
    off_canon = by_value(rows, "offense")
    kth_off = []
    for k in (1, 10, 25, 50, 132):
        n = off_native[k - 1] if len(off_native) >= k else None
        c = off_canon[k - 1] if len(off_canon) >= k else None
        if n is None or c is None:
            continue
        kth_off.append(
            {
                "k": k,
                "nativeKth": n["name"],
                "nativeValue": float(n["sites"][key]),
                "canonicalKth": c["name"],
                "canonicalValue": c["value"],
                "canonicalOverNative": round(c["value"] / float(n["sites"][key]), 3)
                if float(n["sites"][key])
                else None,
            }
        )
    for e in kth if same_scale else ():
        if e["idptcValue"] and e["canonicalValue"]:
            e["canonicalOverNative"] = round(e["canonicalValue"] / e["idptcValue"], 3)
    top_n_counts = {}
    for n in (25, 50, 100, 200, 300):
        top_n_counts[str(n)] = {
            "idptcIdp": sum(1 for r in pts[:n] if r["group"] == "idp"),
            "canonicalIdp": sum(1 for r in canon_players[:n] if r["group"] == "idp"),
        }
    both = [r for r in idp_native if r["name"] in canon_rank]
    return {
        "sourceKey": key,
        "rowsWithValue": {
            "offense": sum(1 for r in pts if r["group"] == "offense"),
            "idp": len(idp_native),
            "pick": sum(1 for r in with_picks if r["group"] == "pick"),
        },
        "valueQuantiles": {
            "offense": quantiles([float(r["sites"][key]) for r in pts if r["group"] == "offense"]),
            "idp": quantiles([float(r["sites"][key]) for r in idp_native]),
        },
        "kthDefenderPlacement": kth,
        "kthOffenseControl": kth_off if same_scale else None,
        "idpCountInTopNPlayers": top_n_counts,
        "idpRankAgreement": {
            "n": len(both),
            "spearmanIdptcVsCanonicalAmongIdp": _spearman(
                [native_rank[r["name"]] for r in both], [canon_rank[r["name"]] for r in both]
            ),
        },
        "rankBasis": "player-only ranks (picks excluded) on both boards unless 'WithPicks'",
    }


# ── statistics (Investigation B's estimator: Spearman, percentile bootstrap) ────


def _rankdata(xs: Sequence[float]) -> list[float]:
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    ranks = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        avg = (i + j) / 2 + 1
        for t in range(i, j + 1):
            ranks[order[t]] = avg
        i = j + 1
    return ranks


def _pearson(a: Sequence[float], b: Sequence[float]) -> float | None:
    n = len(a)
    if n < 3:
        return None
    ma, mb = statistics.fmean(a), statistics.fmean(b)
    sa = math.sqrt(sum((x - ma) ** 2 for x in a))
    sb = math.sqrt(sum((y - mb) ** 2 for y in b))
    if sa == 0 or sb == 0:
        return None
    return sum((x - ma) * (y - mb) for x, y in zip(a, b)) / (sa * sb)


def _spearman(xs, ys) -> float | None:
    if len(xs) < 3:
        return None
    r = _pearson(_rankdata(list(xs)), _rankdata(list(ys)))
    return None if r is None else round(r, 3)


def spearman_ci(xs, ys, *, boot: int = BOOT, seed: int = SEED, min_n: int = 12) -> dict:
    """Same estimator and seed as ``scripts/idp_replacement_research.py::spearman_ci``
    (numpy percentile bootstrap over players), so CIs are comparable to Investigation B."""
    import numpy as np  # noqa: PLC0415
    from scipy import stats as sps  # noqa: PLC0415

    n = len(xs)
    if n < min_n:
        return {"n": n, "rho": None, "ci95": None}
    x, y = np.asarray(xs, float), np.asarray(ys, float)

    def rho(a, b):
        ra, rb = sps.rankdata(a), sps.rankdata(b)
        if ra.std() == 0 or rb.std() == 0:
            return float("nan")
        return float(np.corrcoef(ra, rb)[0, 1])

    r0 = rho(x, y)
    rng = np.random.default_rng(seed)
    bs = []
    for _ in range(boot):
        idx = rng.integers(0, n, n)
        v = rho(x[idx], y[idx])
        if v == v:
            bs.append(v)
    lo, hi = np.percentile(bs, [2.5, 97.5])
    return {"n": n, "rho": round(r0, 3), "ci95": [round(float(lo), 3), round(float(hi), 3)]}


def diff_ci(a: tuple, b: tuple, *, boot: int = BOOT, seed: int = SEED) -> dict | None:
    """rho(a) - rho(b), independent samples (Investigation B's ``diff_ci``)."""
    import numpy as np  # noqa: PLC0415
    from scipy import stats as sps  # noqa: PLC0415

    (ax, ay), (bx, by) = a, b
    if len(ax) < 12 or len(bx) < 12:
        return None
    ax, ay, bx, by = (np.asarray(v, float) for v in (ax, ay, bx, by))

    def rho(p, q):
        rp, rq = sps.rankdata(p), sps.rankdata(q)
        if rp.std() == 0 or rq.std() == 0:
            return float("nan")
        return float(np.corrcoef(rp, rq)[0, 1])

    rng = np.random.default_rng(seed + 7)
    d = []
    for _ in range(boot):
        i = rng.integers(0, len(ax), len(ax))
        j = rng.integers(0, len(bx), len(bx))
        v = rho(ax[i], ay[i]) - rho(bx[j], by[j])
        if v == v:
            d.append(v)
    lo, hi = np.percentile(d, [2.5, 97.5])
    return {"diff": round(rho(ax, ay) - rho(bx, by), 3), "ci95": [round(lo, 3), round(hi, 3)]}


# ── best-ball starter/bench aggregation ────────────────────────────────────


def starter_bench_by_tier(
    team_pools: Sequence[Sequence[Mapping[str, Any]]],
    weekly_points: Mapping[str, Mapping[int, float]],
    weeks: Sequence[int],
    slots: Sequence[str],
    band_of,
    band_order: Sequence[str],
) -> dict:
    """Aggregate weekly best-ball starts by price band and group, over every team.

    ``team_pools``: per team, ``[{sid, position, fantasyPositions, value, group}]``.
    Each week the exact optimal lineup is solved on that week's realized points (a
    player with no stat line that week scored 0 that week — a real realized zero in
    best ball, not a missing value).  A player's ``startShare`` is starts / weeks.
    Classification: ``regular`` >= 50% of weeks, ``spot`` > 0, ``never`` = 0."""
    from src.ros.lineup import (  # noqa: PLC0415
        OBJECTIVE_REALIZED_POINTS,
        RosterPlayer,
        solve_optimal_assignment,
    )

    cells: dict[tuple[str, str], Counter] = defaultdict(Counter)
    slot_points: dict[str, list[float]] = defaultdict(list)
    for pool in team_pools:
        starts: Counter = Counter()
        for w in weeks:
            rp = [
                RosterPlayer(
                    player_id=p["sid"],
                    canonical_name=p["sid"],
                    position=p["position"],
                    ros_value=float(weekly_points.get(p["sid"], {}).get(w, 0.0)),
                    fantasy_positions=tuple(p.get("fantasyPositions") or ()),
                )
                for p in pool
            ]
            sol = solve_optimal_assignment(rp, list(slots), objective=OBJECTIVE_REALIZED_POINTS)
            for idx, pl in sol.items():
                starts[pl.player_id] += 1
                slot_points[slots[idx]].append(float(pl.ros_value or 0.0))
        for p in pool:
            share = starts.get(p["sid"], 0) / len(weeks) if weeks else 0.0
            role = "regular" if share >= 0.5 else "spot" if share > 0 else "never"
            cells[(p["group"], band_of(p["value"]))][role] += 1
    table = []
    for g in ("offense", "idp", "kicker", "other"):
        for b in band_order:
            c = cells.get((g, b))
            if not c:
                continue
            tot = sum(c.values())
            table.append({"group": g, "band": b, "players": tot, "regularStarter": c["regular"],
                          "spotStarter": c["spot"], "neverStarted": c["never"],
                          "regularShare": round(c["regular"] / tot, 3)})  # fmt: skip
    return {
        "teams": len(team_pools),
        "weeks": list(weeks),
        "slotsPerWeek": len(slots),
        "table": table,
        "meanStarterPointsBySlot": {
            s: round(statistics.fmean(v), 2) for s, v in sorted(slot_points.items()) if v
        },
    }


# ── native level, served-board hash, receipts ───────────────────────────────


def native_level_ratios(
    rows,
    *,
    offense_key: str | None,
    idp_key: str | None,
    ks: Sequence[int] = (1, 3, 10, 25, 50, 108),
    off_pool: int = OFFENSE_STARTERS_DEFAULT,
    idp_pool: int = IDP_STARTERS_DEFAULT,
) -> dict:
    """IDP value / offense value at equal depth k, on one market's own scale.

    ``offense_key`` / ``idp_key`` name ``canonicalSiteValues`` entries (None = the served
    ``rankDerivedValue``).  A level comparison only: it says where a market puts the k-th
    defender against its own k-th offense player and nothing about whether that is right.
    Players with no value on the market are absent, never 0."""

    def vals(group: str, key: str | None) -> list[float]:
        out = []
        for r in rows:
            if r["group"] != group:
                continue
            v = r["value"] if key is None else _num(r["sites"].get(key))
            if v is not None and v > 0:
                out.append(float(v))
        return sorted(out, reverse=True)

    o, i = vals("offense", offense_key), vals("idp", idp_key)
    at_k = [
        {"k": k, "offense": o[k - 1], "idp": i[k - 1], "idpOverOffense": round(i[k - 1] / o[k - 1], 3)}
        for k in ks
        if len(o) >= k and len(i) >= k
    ]  # fmt: skip
    pools = None
    if len(o) >= off_pool and len(i) >= idp_pool:
        pools = {
            "offenseTop": off_pool,
            "idpTop": idp_pool,
            "medianRatio": round(statistics.median(i[:idp_pool]) / statistics.median(o[:off_pool]), 3),
            "meanRatio": round(statistics.fmean(i[:idp_pool]) / statistics.fmean(o[:off_pool]), 3),
        }  # fmt: skip
    return {"offenseKey": offense_key or "rankDerivedValue", "idpKey": idp_key or "rankDerivedValue",
            "nOffense": len(o), "nIdp": len(i), "atEqualDepth": at_k, "starterPools": pools}  # fmt: skip


def redact_endpoint(path: str) -> str:
    """A Sleeper endpoint path with the league id replaced by a placeholder.  The evidence
    names endpoints, never the raw league id (public artifacts carry no raw Sleeper id)."""
    return path.replace(LEAGUE_ID, "{leagueId}")


def served_board_sha256(players_array: Iterable[Mapping[str, Any]]) -> str:
    """The served-board hash Lane A pins in ``MANIFEST.json`` (same fields, same canonical
    JSON), so the two lanes can prove they analyze the same board."""
    key = sorted(
        (
            str(r.get("displayName")),
            str(r.get("playerId") or ""),
            r.get("rankDerivedValue"),
            r.get("canonicalConsensusRank"),
            r.get("confidenceBucket"),
            bool(r.get("quarantined")),
        )
        for r in players_array
    )
    return hashlib.sha256(
        json.dumps(key, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class RawFetcher:
    """GET with a RAW-bytes cache and one sha256 receipt per URL.

    Same call shape as Investigation B's ``Fetcher`` (``get(url, max_age_s=)`` returns parsed
    JSON) but the cache holds the response BODY byte for byte, so a receipt hash is the
    hash of what the server sent and can be compared with another lane's.  A cached body is
    reused (``max_age_s`` is accepted for parity and ignored): a re-run reproduces the same
    inputs.  ``refresh`` refetches; ``offline`` refuses any uncached request."""

    MIN_INTERVAL_S = 0.25  # < 5 requests/second

    def __init__(self, cache_dir: Path, *, offline: bool = False, refresh: bool = False) -> None:
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.offline, self.refresh = offline, refresh
        self.receipts: dict[str, dict[str, Any]] = {}
        self.calls = 0
        self._last = 0.0
        self._session = None

    def _path(self, url: str) -> Path:
        return self.cache_dir / f"{hashlib.sha256(url.encode()).hexdigest()[:24]}.bin"

    def get_bytes(self, url: str, *, headers: Mapping[str, str] | None = None) -> bytes:
        path = self._path(url)
        if self.refresh and url not in self.receipts:
            path.unlink(missing_ok=True)
        if not path.exists():
            if self.offline:
                raise RuntimeError(f"offline and not cached: {url}")
            import requests  # noqa: PLC0415

            self._session = self._session or requests.Session()
            wait = self.MIN_INTERVAL_S - (time.time() - self._last)
            if wait > 0:
                time.sleep(wait)
            resp = self._session.get(url, timeout=60, headers=dict(headers or {}))
            self._last = time.time()
            resp.raise_for_status()
            self.calls += 1
            path.write_bytes(resp.content)
        blob = path.read_bytes()
        self.receipts[url] = {
            "sha256": hashlib.sha256(blob).hexdigest(),
            "bytes": len(blob),
            "fetchedAtUtc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(path.stat().st_mtime)),
        }
        return blob

    def get(self, url: str, *, max_age_s: float | None = None) -> Any:  # noqa: ARG002
        return json.loads(self.get_bytes(url))

    def get_text(self, url: str, *, headers: Mapping[str, str] | None = None) -> str:
        return self.get_bytes(url, headers=headers).decode("utf-8", errors="replace")


def crosscheck_manifest(
    manifest: Mapping[str, Any],
    *,
    receipts: Mapping[str, Mapping[str, Any]],
    served_sha: str,
    archive_sha: str,
    live_fingerprint: str | None,
    archived_fingerprint: str | None,
    roster_fingerprint: str | None = None,
) -> dict:
    """Compare this run's pinned inputs with Lane A's manifest.  Every item is reported as
    ``match`` / ``differs`` / ``absent`` (an input one side does not have), never silently
    skipped.  A Sleeper endpoint can legitimately differ (a roster moved after the
    manifest was cut), which is why each is reported and none is asserted."""
    api = ((manifest.get("datasets") or {}).get("sleeperPublicApi")) or {}
    endpoints = {}
    for url, rec in sorted(receipts.items()):
        if not url.startswith(SLEEPER):
            continue
        path = url[len(SLEEPER) :]
        theirs = (api.get(path) or {}).get("sha256")
        endpoints[redact_endpoint(path)] = (
            "absent" if theirs is None else "match" if theirs == rec.get("sha256") else "differs"
        )  # fmt: skip

    def cmp(a, b):
        return "absent" if a is None or b is None else "match" if a == b else "differs"

    card = manifest.get("scoringCard") or {}
    return {
        "manifestVersion": manifest.get("manifestVersion"),
        "pinnedMainSha": (manifest.get("repo") or {}).get("pinnedSha"),
        "servedBoardSha256": cmp((manifest.get("servedBoard") or {}).get("servedBoardSha256"), served_sha),
        "archiveSha256": cmp((manifest.get("pinnedArchive") or {}).get("sha256"), archive_sha),
        "scoringFingerprintLive": cmp(card.get("scoringFingerprint"), live_fingerprint),
        "scoringFingerprintArchived": cmp(card.get("scoringFingerprint"), archived_fingerprint),
        "rosterFormatFingerprint": cmp(
            (manifest.get("rosterFormat") or {}).get("rosterFormatFingerprint"), roster_fingerprint
        ),
        "sleeperEndpoints": endpoints,
        "sleeperEndpointCounts": dict(Counter(endpoints.values())),
    }  # fmt: skip


# ── vendor-stated format (pages) and the scoring mismatches it implies ─────────


def _page_text(raw_html: str) -> str:
    t = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", raw_html)
    t = re.sub(r"(?s)<[^>]+>", " ", t)
    return re.sub(r"\s+", " ", htmllib.unescape(t)).strip()


def parse_big3_page(raw_html: str) -> dict[str, float]:
    """The point values The IDP Show prints on its "Big 3 Scoring" page, by label.  A label
    the page does not carry is ABSENT from the result (never defaulted)."""
    text = _page_text(raw_html)
    out: dict[str, float] = {}
    for label, pat in _BIG3_PATTERNS.items():
        m = re.search(pat, text)
        if m:
            out[label] = float(m.group(1))
    return out


def big3_sleeper_card(parsed: Mapping[str, float]) -> dict[str, float]:
    """Parsed Big 3 labels -> Sleeper ``idp_*`` keys.  A page that did not yield EVERY label
    returns ``{}``: a partial card must never be scored as if it were the whole of Big 3."""
    if any(label not in parsed for label in BIG3_LABEL_TO_SLEEPER):
        return {}
    card: dict[str, float] = {}
    for label, keys in BIG3_LABEL_TO_SLEEPER.items():
        for k in keys:
            card[k] = float(parsed[label])
    return card


def parse_idptc_page(raw_html: str) -> dict[str, Any]:
    """What the IDP Trade Calculator home page states about its own basis."""
    title = re.search(r"(?is)<title>(.*?)</title>", raw_html)
    meta = re.search(r'(?is)<meta\s+name="description"\s+content="([^"]*)"', raw_html)
    desc = htmllib.unescape(meta.group(1)).strip() if meta else None
    basis = re.search(r"(?i)\busing\s+(.+?)\s+scoring\b", desc or "")
    h5 = [
        re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", m))).strip()
        for m in re.findall(r"(?is)<h5[^>]*>(.*?)</h5>", raw_html)
    ]
    headline = next((x for x in h5 if re.search(r"(?i)\d+\s*-\s*Team", x)), None)
    hm = re.search(r"(?i)(\d+)\s*-\s*Team\s*/\s*(\d*\.?\d+)\s*PPR", headline or "")
    updated = next(
        (m.group(1) for x in h5 if (m := re.search(r"(?i)Updated:\s*([0-9/]+)", x))), None
    )
    text = _page_text(raw_html)
    return {
        "title": htmllib.unescape(title.group(1)).strip() if title else None,
        # only the basis the description names (the sentence itself is the vendor's text)
        "statedIdpScoringBasis": basis.group(1).strip() if basis else None,
        "headline": headline,
        "teams": int(hm.group(1)) if hm else None,
        "ppr": float(hm.group(2)) if hm else None,
        "pageUpdated": updated,
        "toggleControls": {
            "superflex": 'id="toggleButton"' in raw_html,
            "tePremium": 'id="toggleButtonTEP"' in raw_html,
        },
        "pageTextChars": len(text),
        # absence on a ~13 kB home page: the page does not STATE these (the vendor may
        # still apply a basis it does not print)
        "pageMentions": {
            term: bool(re.search(term, text, re.I))
            for term in ("starter", "lineup", "roster", "best ?ball", "te premium", "tackle")
        },
    }


def idp_card_comparison(card: Mapping[str, float], big3: Mapping[str, float]) -> list[dict]:
    """The league's IDP rules beside the vendor-stated Big 3 card, key by key."""
    rows = []
    for label, keys in BIG3_LABEL_TO_SLEEPER.items():
        for k in keys:
            lg, b3 = card.get(k), big3.get(k)
            rows.append(
                {
                    "stat": label,
                    "sleeperKey": k,
                    "league": lg,
                    "big3": b3,
                    "leagueOverBig3": round(lg / b3, 3) if lg is not None and b3 else None,
                }
            )
    return rows


def pooled_ratio_ci(
    num: Mapping[str, float],
    den: Mapping[str, float],
    sids: Sequence[str],
    *,
    boot: int = BOOT,
    seed: int = SEED,
) -> dict:
    """sum(num)/sum(den) over ``sids`` with a percentile bootstrap resampling PLAYERS (a
    player's weeks are one cluster).  Below 12 players, or a zero denominator: unavailable."""
    import numpy as np  # noqa: PLC0415

    ids = [s for s in sids if s in num and s in den]
    n = len(ids)
    if n < 12 or sum(den[s] for s in ids) == 0:
        return {"n": n, "ratio": None, "ci95": None}
    a = np.asarray([num[s] for s in ids], float)
    b = np.asarray([den[s] for s in ids], float)
    idx = np.random.default_rng(seed).integers(0, n, (boot, n))
    sa, sb = a[idx].sum(1), b[idx].sum(1)
    ok = sb != 0
    lo, hi = np.percentile(sa[ok] / sb[ok], [2.5, 97.5])
    return {"n": n, "ratio": round(float(a.sum() / b.sum()), 4),
            "ci95": [round(float(lo), 4), round(float(hi), 4)]}  # fmt: skip


def season_totals(
    table: Mapping[str, Mapping[int, float]],
) -> tuple[dict[str, float], dict[str, int]]:
    """Per player: points summed over scored weeks, and the number of those weeks."""
    return ({s: float(sum(w.values())) for s, w in table.items()},
            {s: len(w) for s, w in table.items()})  # fmt: skip


def scoring_drift(
    pts_a: Mapping[str, Mapping[int, float]],
    pts_b: Mapping[str, Mapping[int, float]],
    sids: Sequence[str],
    *,
    min_games: int = MIN_GAMES,
) -> dict:
    """How much one scoring card moves the SAME players' points relative to another:
    pooled sum(a)/sum(b) with a cluster-bootstrap CI, and the Spearman between the two
    points-per-game orders (1.0 = the card changes levels, not order)."""
    ta, ga = season_totals(pts_a)
    tb, _ = season_totals(pts_b)
    ids = [s for s in sids if ga.get(s, 0) >= min_games and s in tb]
    out = pooled_ratio_ci(ta, tb, ids)
    out["spearmanPpg"] = _spearman([ta[s] / ga[s] for s in ids], [tb[s] / ga[s] for s in ids])
    out["meanPpgA"] = round(statistics.fmean(ta[s] / ga[s] for s in ids), 2) if ids else None
    out["meanPpgB"] = round(statistics.fmean(tb[s] / ga[s] for s in ids), 2) if ids else None
    return out


def _receipt(fetch: RawFetcher, url: str) -> dict:
    return {"url": url, **fetch.receipts[url]}


def stated_format(fetch: RawFetcher, archive_path: Path, *, vendor_pages: bool = True) -> dict:
    """What the IDP Trade Calculator STATES about its basis, from two evidence kinds:

    * the pinned archive's own capture evidence (the DOM checkbox state the scraper read
      back, the value column it used) and the board settings it stamped;
    * two public vendor pages, read once: the calculator's home page (header, meta
      description) and The IDP Show's "Big 3 Scoring" page that defines the scoring the
      home page names.

    Anything a page does not print stays absent (never defaulted).  A page that cannot be
    read is ``UNAVAILABLE`` with the reason, and the Big 3 card is then ``{}``."""
    out: dict[str, Any] = {"idpTradeCalc": {}, "theIdpShowBig3": {"sleeperCard": {}}}
    try:
        with zipfile.ZipFile(archive_path) as zf:
            cap = json.loads(zf.read("identity_capture_manifest.json"))
            board = next(n for n in zf.namelist() if re.match(r"dynasty_data_.*\.json$", n))
            settings = json.loads(zf.read(board)).get("settings") or {}
        src = (cap.get("sources") or {}).get("idpTradeCalc") or {}
        out["idpTradeCalc"]["archiveObserved"] = {
            "toggles": src.get("toggles"),
            "boardSettings": {"superflex": settings.get("superflex"), "tep": settings.get("tep")},
        }
    except (OSError, KeyError, StopIteration, ValueError) as exc:
        out["idpTradeCalc"]["archiveObserved"] = {
            "status": "UNAVAILABLE", "reason": f"{type(exc).__name__}: {exc}"}  # fmt: skip
    if not vendor_pages:
        for k, v in (("idpTradeCalc", IDPTC_URL), ("theIdpShowBig3", BIG3_URL)):
            out[k]["page"] = {"url": v, "status": "UNAVAILABLE", "reason": "vendor pages skipped"}
        return out
    try:
        html_ = fetch.get_text(IDPTC_URL, headers={"User-Agent": VENDOR_UA})
        out["idpTradeCalc"]["page"] = {**_receipt(fetch, IDPTC_URL), **parse_idptc_page(html_)}
    except Exception as exc:  # noqa: BLE001 - recorded, never fatal: this block is evidence
        out["idpTradeCalc"]["page"] = {"url": IDPTC_URL, "status": "UNAVAILABLE",
                                       "reason": f"{type(exc).__name__}: {exc}"}  # fmt: skip
    try:
        html_ = fetch.get_text(BIG3_URL, headers={"User-Agent": VENDOR_UA})
        parsed = parse_big3_page(html_)
        text = _page_text(html_)
        date = re.search(
            r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]* \d{1,2}, \d{4}\b", text
        )
        out["theIdpShowBig3"]["page"] = {
            **_receipt(fetch, BIG3_URL),
            "publishedLabel": date.group(0) if date else None,
            "statesPreferredSettings": bool(re.search(r"our preferred IDP scoring settings", text)),
            "parsedLabels": parsed,
            "labelsMissing": [k for k in BIG3_LABEL_TO_SLEEPER if k not in parsed],
        }
        out["theIdpShowBig3"]["sleeperCard"] = big3_sleeper_card(parsed)
    except Exception as exc:  # noqa: BLE001
        out["theIdpShowBig3"]["page"] = {"url": BIG3_URL, "status": "UNAVAILABLE",
                                         "reason": f"{type(exc).__name__}: {exc}"}  # fmt: skip
    return out


RECEPTION_KEYS = ("rec", "rec_0_4", "rec_5_9", "rec_10_19", "rec_20_29", "rec_30_39", "rec_40p")
RECEPTION_POSITION_BONUS = {"WR": "bonus_rec_wr", "TE": "bonus_rec_te", "RB": "bonus_rec_rb"}


def reception_points(
    stats: Mapping[int, Mapping[str, Any]], card: Mapping[str, float], pos_of
) -> tuple[dict[str, float], dict[str, float]]:
    """Per player (weeks with gp > 0): receptions, and the points the card attaches to
    RECEIVING A CATCH (flat rate + the catch-length tier + the position's reception
    bonus), excluding receiving yards, touchdowns and first downs."""
    recs: dict[str, float] = defaultdict(float)
    pts: dict[str, float] = defaultdict(float)
    for dump in stats.values():
        for sid, line in (dump or {}).items():
            if float(line.get("gp") or 0) <= 0 or float(line.get("rec") or 0) <= 0:
                continue
            sid = str(sid)
            bonus = RECEPTION_POSITION_BONUS.get(pos_of(sid))
            keys = RECEPTION_KEYS + ((bonus,) if bonus else ())
            recs[sid] += float(line["rec"])
            pts[sid] += sum(float(line.get(k) or 0) * float(card.get(k) or 0) for k in keys)
    return dict(recs), dict(pts)


# ── privacy guard ──────────────────────────────────────────────────────────


_FORBIDDEN_KEYS = {"ownerid", "userid", "user_id", "owner_id", "rosterid", "roster_id",
                   "teamname", "sleeperteamname", "manager", "managername"}  # fmt: skip


def assert_aggregate_only(payload: Any, forbidden_strings: Iterable[str]) -> None:
    """Raise if the evidence carries a manager/team name, user/owner id, roster id
    field, the Sleeper league id, or any other string in ``forbidden_strings``."""
    bad = {s for s in forbidden_strings if s and len(str(s)) >= 3}

    def walk(x, path="$"):
        if isinstance(x, dict):
            for k, v in x.items():
                if str(k).lower() in _FORBIDDEN_KEYS:
                    raise AssertionError(f"forbidden key {k!r} at {path}")
                if str(k) in bad:
                    raise AssertionError(f"forbidden string as key at {path}")
                walk(v, f"{path}.{k}")
        elif isinstance(x, (list, tuple)):
            for i, v in enumerate(x):
                walk(v, f"{path}[{i}]")
        elif isinstance(x, str) and (x in bad or any(b in x for b in bad if len(b) >= 10)):
            raise AssertionError(f"forbidden string at {path}")

    walk(payload)


# ═══════════════════════════════════════════════════════════════════════════
# contract builds (in-process for the baseline, subprocess for perturbations)
# ═══════════════════════════════════════════════════════════════════════════


def _is_idp_position(pos: object) -> bool:
    """True for any spelling of a defender's position, through the repo's one position
    normalizer (``POSITION_ALIASES``).  The IDPTC CSV spells edge rushers ``ED`` and safeties
    ``S``; a private spelling list that missed ``ED`` left all 98 edge rushers (including the
    top defender) out of an earlier version of the IDPTC level perturbation."""
    from src.utils.name_clean import normalize_position  # noqa: PLC0415

    return normalize_position(pos) in IDP


def _scale_csv(path: Path, *, value_col: str, pos_col: str, f: float) -> int:
    """Multiply ``value_col`` by ``f`` on every defender row (any spelling) of a vendor CSV."""
    text = path.read_text(encoding="utf-8")
    rd = csv.DictReader(io.StringIO(text))
    fields = rd.fieldnames or []
    out_rows, n = [], 0
    for row in rd:
        if _is_idp_position(row.get(pos_col)):
            try:
                row[value_col] = repr(round(float(row[value_col]) * f, 3))
                n += 1
            except (TypeError, ValueError):
                pass
        out_rows.append(row)
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=fields, lineterminator="\n")
    w.writeheader()
    w.writerows(out_rows)
    path.write_text(buf.getvalue(), encoding="utf-8")
    return n


def _scale_raw_site(raw: dict, key: str, names: set[str], f: float) -> int:
    """Scale ``players[name][key]`` and ``players[name]._canonicalSiteValues[key]``."""
    n = 0
    for name, p in (raw.get("players") or {}).items():
        if name not in names or not isinstance(p, dict):
            continue
        hit = False
        if _num(p.get(key)) is not None:
            p[key] = round(float(p[key]) * f, 3)
            hit = True
        csv_ = p.get("_canonicalSiteValues")
        if isinstance(csv_, dict) and _num(csv_.get(key)) is not None:
            csv_[key] = round(float(csv_[key]) * f, 3)
            hit = True
        n += hit
    return n


def idp_raw_names(raw: Mapping[str, Any]) -> set[str]:
    """Names of the raw payload's defenders, by the archive's own name-keyed Sleeper position
    map (``sleeper.positions``).  The raw ``players`` dict is what the contract reads, and it
    is keyed by display name, so this is the set a level perturbation has to move: it does
    not depend on how a vendor CSV spells a name (``D.J.`` / ``DJ``) or a position, and a
    name shared with an offense player (``Josh Allen``) resolves to the one entry the
    contract actually prices."""
    positions = (raw.get("sleeper") or {}).get("positions") or {}
    return {n for n in (raw.get("players") or {}) if _is_idp_position(positions.get(n))}


def build_contract(archive: str, csv_rev: str, variant: str = "baseline") -> tuple[dict, dict]:
    """Build one contract for ``variant`` in THIS process.  Returns (contract, provenance).

    Call it in a fresh interpreter for any variant other than ``baseline``: variants
    monkeypatch module attributes and set a feature-flag env var."""
    R = rpb()
    _, _, blob, raw = R.load_archive(archive)
    prov: dict[str, Any] = {"variant": variant, "archive": archive,
                            "archiveRawSha256": hashlib.sha256(blob).hexdigest()}  # fmt: skip
    overrides = None
    with R.csv_tree(csv_rev) as (root, csv_prov):
        prov["csvTree"] = csv_prov
        from src.api import data_contract as dc  # noqa: PLC0415

        if variant == "no_idpTradeCalc":
            overrides = {"idpTradeCalc": {"include": False}}
        elif variant == "no_draftSharks":
            overrides = {"draftSharks": {"include": False}, "draftSharksIdp": {"include": False}}
        elif variant == "no_idpShowCombined":
            overrides = {"idpShowCombined": {"include": False}}
        elif variant.startswith("idptc_idp_values_x"):
            f = float(variant.rsplit("x", 1)[1])
            csv_path = root / "CSVs/site_raw/idpTradeCalc.csv"
            # The contract reads IDPTC values from the RAW payload (players[name]
            # .idpTradeCalc / ._canonicalSiteValues), not from the CSV; scale both so the
            # perturbation is coherent wherever a consumer reads it.  Defenders are chosen
            # for the raw payload by its own Sleeper position map (see ``idp_raw_names``).
            prov["rowsScaledCsv"] = _scale_csv(csv_path, value_col="value", pos_col="position", f=f)
            names = idp_raw_names(raw)
            prov["rowsScaledRaw"] = _scale_raw_site(raw, "idpTradeCalc", names, f)
        elif variant.startswith("ds_idp_values_x"):
            f = float(variant.rsplit("x", 1)[1])
            prov["rowsScaled"] = _scale_csv(root / "CSVs/site_raw/draftSharksIdp.csv",
                                            value_col="3D Value +", pos_col="Fantasy Position",
                                            f=f)  # fmt: skip
        elif variant == "ladder_multi_bridge":
            os.environ["RISKIT_FEATURE_MULTI_BRIDGE_LADDER"] = "1"
            from src.api import feature_flags as ff  # noqa: PLC0415

            ff.reload()
        elif variant == "ladder_seed_draftSharks" or variant.startswith("ladder_ranks_x"):
            import dataclasses  # noqa: PLC0415

            original = dc.build_bridge_ladder
            factor = float(variant.rsplit("x", 1)[1]) if "ranks_x" in variant else None

            def patched(assessments, rows, **kw):
                a = list(assessments)
                if factor is None:
                    a.sort(key=lambda x: 0 if x.descriptor.bridge_key == "draftSharks" else 1)
                lad = original(a, rows, **kw)
                if factor is not None:
                    lad = dataclasses.replace(
                        lad, ladder=tuple(max(1, int(round(x * factor))) for x in lad.ladder)
                    )
                prov["ladderContributors"] = list(lad.contributors)
                prov["ladderHead"] = list(lad.ladder[:5])
                return lad

            dc.build_bridge_ladder = patched
        elif variant != "baseline":
            raise SystemExit(f"unknown variant {variant!r}")
        contract = dc.build_api_data_contract(raw, csv_root=root, source_overrides=overrides)
    prov["sourceOverrides"] = overrides
    return contract, prov


def _worker(args) -> int:
    contract, prov = build_contract(args.archive, args.csv_rev, args.variant)
    rows = board_rows(contract)
    slim = [{k: r[k] for k in ("name", "group", "pos", "value", "rank")} for r in rows]
    bt = next(
        (b for b in ((contract.get("crossPositionBridges") or {}).get("bridges") or [])
         if b.get("bridgeKey") == "idpTradeCalc"), None)  # fmt: skip
    # served IDP site values of the two perturbed markets, so the parent can PROVE how many
    # rows a level perturbation actually moved (a partial perturbation must not pass silently)
    idp_sites = {
        key: {str(r["name"]): _num(r["sites"].get(key)) for r in rows
              if r["group"] == "idp" and _num(r["sites"].get(key))}
        for key in ("idpTradeCalc", "draftSharksIdp")
    }  # fmt: skip
    Path(args.variant_out).write_text(
        json.dumps({"provenance": prov, "rows": slim, "idpSites": idp_sites,
                    "idptcBridgeCapability": (bt or {}).get("capability"),
                    "idptcTopIdpSite": next((r["sites"].get("idpTradeCalc")
                                             for r in by_value(rows, "idp")), None)}),
        encoding="utf-8",
    )  # fmt: skip
    return 0


def scaled_share(base: Mapping[str, float], var: Mapping[str, float], f: float,
                 *, tol: float = 0.005) -> dict:  # fmt: skip
    """How many of the baseline's served site values the variant moved by ``f`` (within
    rounding: ``tol`` relative, never tighter than half a unit, because Draft Sharks values
    are whole numbers).  ``share`` is scaled / baseline rows."""
    scaled = sum(
        1
        for n, v in base.items()
        if v and var.get(n) is not None and abs(var[n] - v * f) <= max(0.5, tol * v)
    )
    return {
        "scaled": scaled,
        "of": len(base),
        "share": round(scaled / len(base), 4) if base else None,
    }


def run_variants(archive: str, csv_rev: str, names: Iterable[str], scratch: Path) -> dict:
    out = {}
    for name in names:
        dst = scratch / f"variant_{name}.json"
        t = time.time()
        cmd = [sys.executable, str(Path(__file__).resolve()), "--variant", name,
               "--variant-out", str(dst), "--archive", archive, "--csv-rev", csv_rev]  # fmt: skip
        env = {k: v for k, v in os.environ.items() if not k.startswith("RISKIT_FEATURE_")}
        proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(REPO), env=env)
        if proc.returncode != 0:
            out[name] = {"error": proc.stderr[-2000:]}
            continue
        out[name] = json.loads(dst.read_text(encoding="utf-8"))
        out[name]["seconds"] = round(time.time() - t, 1)
        print(f"  variant {name}: {out[name]['seconds']}s", flush=True)
    return out


# ═══════════════════════════════════════════════════════════════════════════
# Sleeper: card, rosters, players, weekly realized points
# ═══════════════════════════════════════════════════════════════════════════


def sleeper_inputs(fetch, weeks: Sequence[int]) -> dict:
    league = fetch.get(f"{SLEEPER}/league/{LEAGUE_ID}", max_age_s=6 * 3600)
    rosters = fetch.get(f"{SLEEPER}/league/{LEAGUE_ID}/rosters", max_age_s=6 * 3600)
    pdb = fetch.get(f"{SLEEPER}/players/nfl", max_age_s=7 * 86400)
    stats = {w: fetch.get(f"{SLEEPER}/stats/nfl/regular/{SEASON}/{w}") for w in weeks}
    matchups = {w: fetch.get(f"{SLEEPER}/league/{LEAGUE_ID}/matchups/{w}") for w in weeks}
    return {"league": league, "rosters": rosters, "pdb": pdb, "stats": stats,
            "matchups": matchups}  # fmt: skip


def weekly_points(stats: Mapping[int, Mapping[str, Any]], card: Mapping[str, float], pdb,
                  pos_of, *, require_gp: bool = True) -> dict[str, dict[int, float]]:  # fmt: skip
    """Host-native player-week points (``compute_weekly_points(..., source="sleeper")`` over
    Sleeper's own stat line).  ``require_gp`` is Investigation B's filter (a line with
    ``gp > 0``, which is also what defines a game played for points per game); Lane A's
    wider check drops it and covers every line the host scores."""
    from src.nfl_data.realized_points import compute_weekly_points  # noqa: PLC0415

    pts: dict[str, dict[int, float]] = defaultdict(dict)
    for w, dump in stats.items():
        for sid, line in (dump or {}).items():
            sid = str(sid)
            if require_gp and float(line.get("gp") or 0) <= 0:
                continue
            row = {**line, "player_id": sid, "season": SEASON, "week": w}
            res = compute_weekly_points(row, dict(card), position=pos_of(sid), source="sleeper")
            if res is not None:
                pts[sid][w] = float(res.fantasy_points)
    return pts


def scorer_check(pts, matchups) -> dict:
    """Our host-native points against Sleeper's awarded ``players_points``.  A rostered
    player-week we computed no points for is either awarded zero (no stat line: a real zero
    in best ball) or a miss (``nonzeroHostPointsWithNoScoredLine``)."""
    diffs = []
    missing = 0
    no_line_zero = 0
    for w, ms in matchups.items():
        for m in ms or []:
            for sid, hp in (m.get("players_points") or {}).items():
                got = pts.get(str(sid), {}).get(w)
                if got is None:
                    if abs(float(hp)) > 0.001:
                        missing += 1
                    else:
                        no_line_zero += 1
                    continue
                diffs.append(abs(got - float(hp)))
    return {
        "playerWeeksCompared": len(diffs),
        "within0.01": sum(1 for d in diffs if d <= 0.01),
        "maxAbsDiff": round(max(diffs), 4) if diffs else None,
        "nonzeroHostPointsWithNoScoredLine": missing,
        "noScoredLineAwardedZero": no_line_zero,
    }


def values_by_sid(contract: Mapping[str, Any]) -> dict[str, float]:
    """Sleeper id -> served value for every priced PLAYER row (Investigation B's join:
    ``playerId`` first, then the contract's name -> id map)."""
    sl = contract.get("sleeper") or {}
    n2i = {str(k): str(v) for k, v in (sl.get("playerIds") or {}).items()}
    out = {}
    for r in contract.get("playersArray") or []:
        if str(r.get("assetClass") or "") == "pick":
            continue
        v = _num(r.get("rankDerivedValue"))
        if v is None or v <= 0:
            continue
        sid = r.get("playerId")
        if not sid:
            for f in ("displayName", "canonicalName", "legacyRef"):
                sid = n2i.get(str(r.get(f) or ""))
                if sid:
                    break
        if sid:
            out[str(sid)] = v
    return out


def correlation_block(vals: Mapping[str, float | None], ppg, pos_of) -> dict:
    def pairs(positions):
        xs, ys = [], []
        for sid, v in vals.items():
            if v is None or pos_of(sid) not in positions:
                continue
            p = ppg(sid)
            if p is None:
                continue
            xs.append(v)
            ys.append(p)
        return xs, ys

    block = {"offense": spearman_ci(*pairs(OFFENSE)), "idp": spearman_ci(*pairs(IDP))}
    for p in POSITIONS:
        block[p] = spearman_ci(*pairs((p,)))
    block["offenseMinusIdp"] = diff_ci(pairs(OFFENSE), pairs(IDP))
    return block


def card_alignment(site_vals: Mapping[str, float], ppg_league, refs: Mapping[str, Any],
                   pos_of) -> dict:  # fmt: skip
    """Descriptive: does a market's IDP ORDER track league-card production more closely than
    production under each reference card (``refs``: name -> points-per-game function)?  Same
    players on every side; one set of bootstrap resamples shared by all references, so the
    references are compared on identical draws.  Each ref cell: rho under the reference,
    ``leagueMinusRef`` with a paired-bootstrap 95% CI and a two-sided bootstrap p-value."""
    import numpy as np  # noqa: PLC0415
    from scipy import stats as sps  # noqa: PLC0415

    out = {}
    for grp, positions in (("IDP", IDP), *(((p, (p,)) for p in IDP))):
        sids = [
            s
            for s, v in site_vals.items()
            if v is not None
            and pos_of(s) in positions
            and ppg_league(s) is not None
            and all(f(s) is not None for f in refs.values())
        ]
        if len(sids) < 12:
            out[grp] = {"n": len(sids), "rhoLeague": None, "references": {}}
            continue
        x = np.asarray([site_vals[s] for s in sids], float)
        a = np.asarray([ppg_league(s) for s in sids], float)
        bs = {name: np.asarray([f(s) for s in sids], float) for name, f in refs.items()}

        def rho(p, q):
            return float(np.corrcoef(sps.rankdata(p), sps.rankdata(q))[0, 1])

        rng = np.random.default_rng(SEED + 11)
        draws: dict[str, list[float]] = {name: [] for name in refs}
        for _ in range(BOOT):
            i = rng.integers(0, len(sids), len(sids))
            for name, b in bs.items():
                draws[name].append(rho(x[i], a[i]) - rho(x[i], b[i]))
        cell: dict[str, Any] = {}
        for name, b in bs.items():
            arr = np.asarray(draws[name], float)
            lo, hi = np.percentile(arr, [2.5, 97.5])
            tail = min(int((arr <= 0).sum()), int((arr >= 0).sum()))
            cell[name] = {
                "rho": round(rho(x, b), 3),
                "leagueMinusRef": round(rho(x, a) - rho(x, b), 3),
                "ci95": [round(float(lo), 3), round(float(hi), 3)],
                "pBoot": round(min(1.0, (2 * tail + 1) / (len(arr) + 1)), 4),
            }
        out[grp] = {"n": len(sids), "rhoLeague": round(rho(x, a), 3), "references": cell}
    return out


def holm(pvals: Mapping[str, float]) -> dict[str, float]:
    """Holm step-down adjusted p-values over one family."""
    items = sorted(pvals.items(), key=lambda kv: kv[1])
    m = len(items)
    out, running = {}, 0.0
    for i, (k, p) in enumerate(items):
        running = max(running, min(1.0, (m - i) * p))
        out[k] = round(running, 4)
    return out


# ═══════════════════════════════════════════════════════════════════════════
# main
# ═══════════════════════════════════════════════════════════════════════════


def roster_format_fingerprint(league: Mapping[str, Any]) -> str:
    """``rf1:`` fingerprint of the roster format, defined exactly as Lane A's manifest
    defines it (roster_positions, num_teams, taxi/reserve slots, best_ball, type), so the
    two lanes can prove they read the same format."""
    s = league.get("settings") or {}
    body = {
        "roster_positions": list(league.get("roster_positions") or []),
        "num_teams": s.get("num_teams"),
        "taxi_slots": s.get("taxi_slots"),
        "reserve_slots": s.get("reserve_slots"),
        "best_ball": s.get("best_ball"),
        "type": s.get("type"),
    }
    blob = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    return "rf1:" + hashlib.sha256(blob).hexdigest()[:16]


def league_format(league: Mapping[str, Any], contract: Mapping[str, Any]) -> dict:
    from src.league_comparison.sleeper_scoring import scoring_fingerprint  # noqa: PLC0415

    card = {k: float(v) for k, v in (league.get("scoring_settings") or {}).items()
            if isinstance(v, (int, float))}  # fmt: skip
    rp = list(league.get("roster_positions") or [])
    starters = [p for p in rp if p != "BN"]
    sc = Counter(starters)
    teams = int((league.get("settings") or {}).get("num_teams") or 0)
    idp_slots = sum(sc.get(p, 0) for p in ("DL", "LB", "DB", "IDP_FLEX"))
    off_slots = sum(sc.get(p, 0) for p in ("QB", "RB", "WR", "TE", "FLEX", "SUPER_FLEX",
                                           "REC_FLEX", "WRRB_FLEX"))  # fmt: skip
    archived = (contract.get("sleeper") or {}).get("scoringSettings") or {}
    return {
        "leagueKey": LEAGUE_KEY,
        "season": league.get("season"),
        "scoringFingerprintLive": scoring_fingerprint(card),
        "scoringFingerprintArchived": scoring_fingerprint(archived),
        "rosterFormatFingerprint": roster_format_fingerprint(league),
        "teams": teams,
        "rosterSpots": len(rp),
        "starterSlots": dict(sc),
        "starterSlotCount": len(starters),
        "idpStarterSlotsPerTeam": idp_slots,
        "offenseStarterSlotsPerTeam": off_slots,
        "leagueWideIdpStarters": teams * idp_slots,
        "leagueWideOffenseStarters": teams * off_slots,
        "idpShareOfNonKickerStarters": round(idp_slots / (idp_slots + off_slots), 3)
        if (idp_slots + off_slots)
        else None,
        "superflex": sc.get("SUPER_FLEX", 0) > 0,
        "bestBall": (league.get("settings") or {}).get("best_ball") == 1,
        "teKeys": {k: card.get(k) for k in ("bonus_rec_te", "bonus_fd_te", "rec") if k in card},
        "receptionKeys": {k: v for k, v in sorted(card.items()) if k.startswith("rec_")},
        "idpKeys": {k: v for k, v in sorted(card.items()) if k.startswith("idp_")},
        "passTd": card.get("pass_td"),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--archive", default=PINNED_ARCHIVE)
    ap.add_argument("--csv-rev", default=PINNED_CSV_REV)
    ap.add_argument("--weeks", type=int, default=6)
    ap.add_argument("--cache-dir", type=Path, default=REPO / CACHE_DEFAULT)
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--refresh", action="store_true", help="refetch cached responses")
    ap.add_argument("--manifest", default=None, help="Lane A MANIFEST.json to cross-check "
                    f"(default {MANIFEST_DEFAULT} when present)")  # fmt: skip
    ap.add_argument("--no-vendor-pages", action="store_true",
                    help="do not read the two public vendor pages (stated-format block UNAVAILABLE)")  # fmt: skip
    ap.add_argument("--out", default=OUT_DEFAULT)
    ap.add_argument("--skip-perturbations", action="store_true")
    ap.add_argument("--variant", help=argparse.SUPPRESS)
    ap.add_argument("--variant-out", help=argparse.SUPPRESS)
    args = ap.parse_args()
    if args.variant:
        return _worker(args)
    return run(args)


def run(args) -> int:  # noqa: PLR0915
    t0 = time.time()
    L = lu()
    weeks = list(range(1, args.weeks + 1))
    print("building pinned contract ...", flush=True)
    contract, prov = build_contract(args.archive, args.csv_rev)
    rows = board_rows(contract)

    fetch = RawFetcher(args.cache_dir, offline=args.offline, refresh=args.refresh)
    sl = sleeper_inputs(fetch, weeks)
    pdb = sl["pdb"]

    def pos_of(sid: str) -> str:
        return L.pos_group((pdb.get(str(sid)) or {}).get("position"))

    fmt = league_format(sl["league"], contract)
    card = {k: float(v) for k, v in (sl["league"].get("scoring_settings") or {}).items()
            if isinstance(v, (int, float))}  # fmt: skip
    ref_card = {**card, **reference_tackle_heavy_card()}
    pts = weekly_points(sl["stats"], card, pdb, pos_of)
    pts_ref = weekly_points(sl["stats"], ref_card, pdb, pos_of)
    scorer = scorer_check(pts, sl["matchups"])
    # Lane A's wider check (no gp filter): every stat line the host scores.  Investigation B's
    # 3,299 and Lane A's 3,710 are the same scorer with and without the gp > 0 filter.
    scorer_all = scorer_check(weekly_points(sl["stats"], card, pdb, pos_of, require_gp=False),
                              sl["matchups"])  # fmt: skip

    # The league card beside the scoring the two cross-position bridges STATE.
    stated = stated_format(fetch, REPO / args.archive, vendor_pages=not args.no_vendor_pages)
    big3_card = stated["theIdpShowBig3"]["sleeperCard"]
    pts_big3 = weekly_points(sl["stats"], {**card, **big3_card}, pdb, pos_of) if big3_card else None
    half_ppr_card = {**card, **{k: 0.0 for k in RECEPTION_KEYS}, "rec": 0.5,
                     **{b: 0.0 for b in RECEPTION_POSITION_BONUS.values()}}  # fmt: skip
    pts_half = weekly_points(sl["stats"], half_ppr_card, pdb, pos_of)

    def ppg_of(table, min_g=MIN_GAMES):
        def f(sid):
            wk = table.get(str(sid)) or {}
            return None if len(wk) < min_g else sum(wk.values()) / len(wk)

        return f

    ppg, ppg_ref = ppg_of(pts), ppg_of(pts_ref)
    card_refs = {"tackleHeavy": ppg_ref}
    if pts_big3 is not None:
        card_refs["big3"] = ppg_of(pts_big3)
    idp_n = fmt["leagueWideIdpStarters"] or IDP_STARTERS_DEFAULT
    off_n = fmt["leagueWideOffenseStarters"] or OFFENSE_STARTERS_DEFAULT

    # ── 1. baseline diagnostics ──────────────────────────────────────────
    idp_top = by_value(rows, "idp")[:10]
    baseline = {
        "top100": top_overall(rows, 100),
        "top200": top_overall(rows, 200),
        "top25ByPosition": {p: top_by_position(rows, p, 25) for p in IDP},
        "highestRankedDefenders": [
            {
                "name": r["name"],
                "pos": r["pos"],
                "rank": r["rank"],
                "value": r["value"],
                "confidence": r["confidence"],
                "anchorValue": r["anchorValue"],
                "subgroupValue": r["subgroupValue"],
                "votes": {
                    k: {
                        "effectiveRank": m.get("effectiveRank"),
                        "valueContribution": m.get("valueContribution"),
                        "appliedWeight": m.get("appliedWeight"),
                        "isAnchor": m.get("isAnchor"),
                        "pool": m.get("rankCoordinatePool"),
                        "contributed": m.get("contributedToBlend", True) is not False,
                    }
                    for k, m in r["meta"].items()
                },  # fmt: skip
            }
            for r in idp_top
        ],
        "rankBands": band_counts(rows),
        "valueQuantiles": {
            "offense": quantiles([r["value"] for r in by_value(rows, "offense")]),
            "idp": quantiles([r["value"] for r in by_value(rows, "idp")]),
            "offenseTopStarterPool": quantiles(
                [r["value"] for r in by_value(rows, "offense")[:off_n]]
            ),
            "idpTopStarterPool": quantiles([r["value"] for r in by_value(rows, "idp")[:idp_n]]),
        },
        "rankQuantiles": {
            g: quantiles([r["rank"] for r in ranked(rows) if r["group"] == g])
            for g in ("offense", "idp", "pick")
        },
        "kthValues": kth_values(rows),
        "placement": placement_metrics(rows),
        "coverageByPosition": coverage_by_position(rows),
        "evidenceCensus": evidence_census(contract, rows),
    }

    # ── 2. starters vs bench by price band (live rosters, weekly best ball) ──
    from src.api import league_registry  # noqa: PLC0415
    from src.ros.lineup import resolve_starter_slots  # noqa: PLC0415

    slots, slot_src = resolve_starter_slots(
        roster_positions=sl["league"].get("roster_positions"),
        roster_settings=league_registry.get_league_roster_settings(LEAGUE_KEY),
    )
    vals = values_by_sid(contract)

    def group_of(sid):
        p = pos_of(sid)
        return (
            "idp" if p in IDP else "offense" if p in OFFENSE else "kicker" if p == "K" else "other"
        )

    team_pools = []
    for r in sl["rosters"]:
        pool = []
        for sid in (str(p) for p in (r.get("players") or [])):
            m = pdb.get(sid) or {}
            pool.append({"sid": sid, "position": str(m.get("position") or "").upper(),
                         "fantasyPositions": [str(x).upper() for x in
                                              (m.get("fantasy_positions") or []) if x],
                         "value": vals.get(sid), "group": group_of(sid)})  # fmt: skip
        team_pools.append(pool)
    sbt = starter_bench_by_tier(team_pools, pts, weeks, slots, L.band_of, L.BAND_ORDER)
    sbt["slotSource"] = slot_src
    sbt["rostersFetchedAt"] = (
        "Sleeper /rosters, receipt in inputs.sleeperReceipts (reused from the raw cache)"
    )
    sbt["rosteredPlayers"] = sum(len(p) for p in team_pools)
    sbt["priceBands"] = [b[0] for b in L.BANDS] + [L.UNVALUED]
    sbt["note"] = (
        "Rosters are TODAY's; weeks 1-6 are replayed on them (a player acquired mid-season "
        "is credited with weeks he was elsewhere).  Realized production, not expected; "
        "'unvalued' = no canonical price (UNKNOWN, never 0)."
    )

    # ── 3. IDPTC native distribution ─────────────────────────────────────
    native = idptc_native(rows)
    ds_native = None
    # Draft Sharks' combined board is two keys (offense + IDP halves of one session)
    ds_rows = []
    for r in rows:
        k = "draftSharksIdp" if r["group"] == "idp" else "draftSharks"
        v = _num(r["sites"].get(k))
        if v is not None and r["group"] in ("offense", "idp"):
            ds_rows.append({**r, "sites": {**r["sites"], "dsCombined": v}})
    ds_native = idptc_native(ds_rows, key="dsCombined", same_scale=False)
    level = {
        "canonical": native_level_ratios(rows, offense_key=None, idp_key=None,
                                         off_pool=off_n, idp_pool=idp_n),
        "idpTradeCalc": native_level_ratios(rows, offense_key="idpTradeCalc",
                                            idp_key="idpTradeCalc", off_pool=off_n, idp_pool=idp_n),
        "draftSharks": native_level_ratios(rows, offense_key="draftSharks",
                                           idp_key="draftSharksIdp", off_pool=off_n, idp_pool=idp_n),
        "note": "IDP value / offense value at equal depth k on each market's OWN scale.  "
        "Draft Sharks' 3D Value + is a vendor value-over-replacement number in whole units "
        "(its best offense player is 100); deep-k ratios there are coarse and its scale is "
        "not the canonical one, so compare the markets by the direction and rough size of the "
        "ratio, not by value.  A level comparison, not a verdict on any level.",
    }  # fmt: skip

    # ── 4. bridge trace + perturbations ──────────────────────────────────
    from src.api import data_contract as dc  # noqa: PLC0415
    from src.api import feature_flags as ff  # noqa: PLC0415

    anchor_keys, _ = dc._anchor_key_sets(dc._active_sources(None))
    usable = [b for b in ((contract.get("crossPositionBridges") or {}).get("bridges") or [])
              if b.get("usable")]  # fmt: skip
    multi = ff.is_enabled("multi_bridge_ladder")
    seeds = [b["bridgeKey"] for b in (usable if multi else usable[:1])]
    trace = bridge_trace(contract, rows, anchor_keys=anchor_keys, ladder_seeds=seeds, idp_n=idp_n)
    trace["multiBridgeLadderFlag"] = multi
    trace["alphaShrinkage"] = dc._ALPHA_SHRINKAGE
    trace["hierarchicalBlendScope"] = "IDP and pick rows (offense: flat count-aware blend)"

    perturb: dict[str, Any] = {}
    if not args.skip_perturbations:
        scratch = Path(tempfile.mkdtemp(prefix="idp_c_market_"))
        res = run_variants(args.archive, args.csv_rev, VARIANTS, scratch)
        base_v = res.get("baseline", {}).get("rows")
        in_proc = [{k: r[k] for k in ("name", "group", "pos", "value", "rank")} for r in rows]
        perturb["controlBaselineMatchesInProcess"] = base_v == in_proc
        for name, desc in VARIANTS.items():
            r = res.get(name) or {}
            if "error" in r:
                perturb[name] = {"description": desc, "error": r["error"]}
                continue
            prov_v = {k: v for k, v in r["provenance"].items() if k != "csvTree"}
            for prefix, key in (("idptc_idp_values_x", "idpTradeCalc"),
                                ("ds_idp_values_x", "draftSharksIdp")):  # fmt: skip
                if name.startswith(prefix):
                    cov = scaled_share(res["baseline"]["idpSites"][key], r["idpSites"][key],
                                       float(name.rsplit("x", 1)[1]))  # fmt: skip
                    prov_v["idpRowsMovedByTheFactor"] = cov
                    if cov["share"] is None or cov["share"] < 0.99:
                        raise SystemExit(f"{name}: only {cov} of the served IDP rows moved")
            perturb[name] = {
                "description": desc,
                "provenance": prov_v,
                "idptcTopIdpSiteValue": r.get("idptcTopIdpSite"),
                "vsBaseline": compare_placement(in_proc, r["rows"], idp_n=idp_n, off_n=off_n),
                "placement": placement_metrics(r["rows"]),
            }
        for f in scratch.glob("*.json"):
            f.unlink()
        scratch.rmdir()

    # ── 5. league-format alignment of the cross-position markets ─────────
    idptc_by_sid, ds_by_sid = {}, {}
    n2i = {str(k): str(v) for k, v in ((contract.get("sleeper") or {}).get("playerIds")
                                       or {}).items()}  # fmt: skip
    for r in rows:
        sid = r["pid"] or n2i.get(str(r["name"]))
        if not sid or r["group"] != "idp":
            continue
        if _num(r["sites"].get("idpTradeCalc")):
            idptc_by_sid[sid] = float(r["sites"]["idpTradeCalc"])
        if _num(r["sites"].get("draftSharksIdp")) is not None:
            ds_by_sid[sid] = float(r["sites"]["draftSharksIdp"])
    canon_idp = {s: v for s, v in vals.items() if pos_of(s) in IDP}

    # Pools for the scoring-mismatch measurements.  "marketStarters" = the defenders (offense
    # players) the CANONICAL board prices inside the league-wide starter count, chosen by price
    # and not by realized points, so the pool is not selected on the outcome it is scored on.
    def pool(positions, table, top_n=None):
        ids = {s for s in table if pos_of(s) in positions}
        if top_n is not None:
            priced = sorted(
                (x for x in vals if pos_of(x) in positions), key=lambda x: (-vals[x], x)
            )
            ids &= set(priced[:top_n])
        return sorted(ids)

    def drift_block(pts_a, pts_b, positions, top_n):
        out = {"all": scoring_drift(pts_a, pts_b, pool(positions, pts_a)),
               "marketStarters": scoring_drift(pts_a, pts_b, pool(positions, pts_a, top_n))}  # fmt: skip
        out["byPosition"] = {p: scoring_drift(pts_a, pts_b, pool((p,), pts_a)) for p in positions}
        return out

    big3_play = None
    if big3_card:
        play = ("idp_sack", "idp_qb_hit", "idp_tkl_loss")
        big3_play = {"keys": list(play),
                     "league": round(sum(card[k] for k in play), 3),
                     "big3": round(sum(big3_card[k] for k in play), 3)}  # fmt: skip
        big3_play["leagueOverBig3"] = round(big3_play["league"] / big3_play["big3"], 3)
    recs, rpts = reception_points(sl["stats"], card, pos_of)
    per_catch = {p: pooled_ratio_ci(rpts, recs, sorted(s for s in recs if pos_of(s) == p))
                 for p in ("RB", "WR", "TE")}  # fmt: skip
    per_catch["RB+WR+TE"] = pooled_ratio_ci(
        rpts, recs, sorted(s for s in recs if pos_of(s) in ("RB", "WR", "TE")))  # fmt: skip
    idptc_page = stated["idpTradeCalc"].get("page") or {}
    idptc_obs = (stated["idpTradeCalc"].get("archiveObserved") or {}).get("toggles") or {}
    mismatches = {
        "idpScoring": {
            "stated": "The IDP Show 'Big 3' (named by the calculator's own page; defined on "
            "The IDP Show's published page)"
            if big3_card
            else "UNAVAILABLE",
            "perKey": idp_card_comparison(card, big3_card) if big3_card else None,
            "sackPlay": big3_play,
            "leagueCardPointsOverBig3Points": (
                drift_block(pts, pts_big3, IDP, idp_n) if pts_big3 is not None else None
            ),
        },
        "receptionScoring": {
            "stated": f"{idptc_page.get('ppr')} PPR (page header {idptc_page.get('headline')!r})",
            "leagueAttachedPointsPerCatch": per_catch,
            "leagueCardPointsOverHalfPprCounterfactual": drift_block(pts, pts_half, OFFENSE, off_n),
            "counterfactual": "same stat lines scored on the league card with ONLY the "
            "reception rules replaced (rec 0.5, no catch-length tiers, no position reception "
            "bonus); first-down, yardage, TD and passing rules unchanged, so the ratio isolates "
            "the reception-pricing mismatch and is not a full re-score under a '.5 PPR' card",
        },
        "tePremium": {
            "stated": "TEP toggle ON (observed): " + json.dumps(idptc_obs.get("tePremium")),
            "magnitudeStated": None,
            "leagueBonusRecTe": card.get("bonus_rec_te"),
            "leagueBonusFdTe": card.get("bonus_fd_te"),
            "leagueBonusFdWr": card.get("bonus_fd_wr"),
            "verdict": "MISMATCH: the card pays TEs nothing extra per catch",
        },
        "teams": {
            "stated": idptc_page.get("teams"),
            "league": fmt["teams"],
            "verdict": None
            if idptc_page.get("teams") is None
            else ("MATCH" if idptc_page.get("teams") == fmt["teams"] else "MISMATCH"),
        },  # fmt: skip
        "superflex": {
            "stated": "Superflex toggle ON (observed): " + json.dumps(idptc_obs.get("superflex")),
            "leagueSuperFlexSlots": fmt["starterSlots"].get("SUPER_FLEX", 0),
            "verdict": "MATCH" if fmt["superflex"] else "MISMATCH",
        },  # fmt: skip
        "notStatedByTheCalculator": [
            "IDP starter counts",
            "best ball",
            "roster size",
            "lineup requirements beyond Superflex",
        ],
        "notStatedEvidence": idptc_page.get("pageMentions"),
    }
    alignment = {
        "statedFormat": stated,
        "statedAssumptions": {
            "draftSharks": {
                "leagueSync": "the vendor page is driven with its league selector set to "
                "this league's synced copy (scripts/fetch_draftsharks.py LEAGUE_ID, a "
                "Draft Sharks league id, not the Sleeper id); the vendor applies scoring "
                "client-side",
                "idpScoring": "UNVERIFIED: the fetcher proves the values MOVE when the synced "
                "league is activated, not that the vendor reproduces this card's custom keys "
                "(tiered reception, TFL, PD); it is not observable from the CSV",
            },
        },
        "verifiedLeagueCard": fmt,
        "mismatches": mismatches,
        "implied": {
            "idptcIdpShareTop200Players": round(
                native["idpCountInTopNPlayers"]["200"]["idptcIdp"] / 200, 3
            ),
            "canonicalIdpShareTop200Players": round(
                native["idpCountInTopNPlayers"]["200"]["canonicalIdp"] / 200, 3
            ),
            "leagueIdpShareOfStartingSlots": fmt["idpShareOfNonKickerStarters"],
            "caveat": "a starting-slot share is not a value share (replacement depth "
            "differs by position); shown only to place the market's IDP share in context",
        },
        "cardAlignment2026wk": {
            "method": "Spearman(market IDP value, 2026 wk1-N league-card ppg) minus "
            "Spearman(same, ppg under a reference card), same players, paired bootstrap on "
            "shared resamples; DESCRIPTIVE (the boards already know these games: in-sample).  "
            "References: 'tackleHeavy' = Investigation B's illustrative card; 'big3' = the "
            "card the calculator itself names (absent when the vendor page was unavailable)",
            "references": sorted(card_refs),
            "idpTradeCalc": card_alignment(idptc_by_sid, ppg, card_refs, pos_of),
            "draftSharksIdp": card_alignment(ds_by_sid, ppg, card_refs, pos_of),
            "canonical": card_alignment(canon_idp, ppg, card_refs, pos_of),
        },
    }
    # Holm step-down over one family per reference card (3 markets x {IDP, DL, LB, DB}).
    holm_by_ref, family_sizes = {}, {}
    for ref in card_refs:
        fam = {
            f"{m}:{g}": cell["references"][ref]["pBoot"]
            for m in ("idpTradeCalc", "draftSharksIdp", "canonical")
            for g, cell in alignment["cardAlignment2026wk"][m].items()
            if ref in (cell.get("references") or {})
        }
        holm_by_ref[ref], family_sizes[ref] = holm(fam), len(fam)
    alignment["cardAlignment2026wk"]["holmAdjustedP"] = holm_by_ref
    alignment["cardAlignment2026wk"]["familySize"] = family_sizes

    # ── 6. Investigation B correlation reproduction ──────────────────────
    print("building pre-season and B-repro boards ...", flush=True)
    pre_contract, pre_prov = build_contract(PRESEASON_ARCHIVE, PRESEASON_CSV_REV)
    b_contract, b_prov = build_contract(B_INSEASON_ARCHIVE, B_INSEASON_CSV_REV)
    b_served_pre, b_pre_meta = L.preseason_values()
    b_recorded = json.loads(
        (REPO / "docs/valuation/evidence/idp_replacement_2026-10-20/idp_replacement.json")
        .read_text(encoding="utf-8")
    )["Q5_correlation"]  # fmt: skip
    pit_vals = values_by_sid(pre_contract)
    # sorted: set iteration order varies with the per-process hash seed, which changed the
    # bootstrap resamples (and so the CI endpoints) between otherwise identical runs
    common = sorted(set(pit_vals) & {k for k, v in b_served_pre.items() if v is not None})
    same_cohort = {
        "sampleType": "OUT-OF-SAMPLE; the SAME players (priced on both pre-season boards), "
        "so a difference is board date + methodology, not cohort",
        "pointInTime_20260909": correlation_block({k: pit_vals[k] for k in common}, ppg, pos_of),
        "investigationB_served_20260825": correlation_block(
            {k: b_served_pre[k] for k in common}, ppg, pos_of
        ),
    }
    corr = {
        "outcome": f"2026 regular-season weeks 1-{args.weeks} league-scored points per game "
        f"(players with >= {MIN_GAMES} games with gp > 0), live dynasty_main card",
        "cohort": "every priced player row (rankDerivedValue > 0) joined by Sleeper id, "
        "position from the Sleeper player directory; picks and K excluded",
        "pinnedInSeason_20261025": {
            "sampleType": "IN-SAMPLE / hindsight: the board was built after weeks 1-6",
            **correlation_block(vals, ppg, pos_of),
        },
        "pointInTimePreseason_20260909": {
            "sampleType": "OUT-OF-SAMPLE for 2026 data: archive scraped 2026-09-09 21:15 UTC, "
            "source tree at that day's refresh commit, both before kickoff.  Methodology is "
            "TODAY's code (not the code served that day)",
            "provenance": {k: v for k, v in pre_prov.items()},
            **correlation_block(pit_vals, ppg, pos_of),
        },
        "investigationB_servedPreseason_20260825": {
            "sampleType": "OUT-OF-SAMPLE: Investigation B's served 2026-08-25 board, values "
            "exactly as served that day",
            "artifact": b_pre_meta.get("artifact"),
            **correlation_block(b_served_pre, ppg, pos_of),
        },
        "investigationB_inSeasonRebuild_20261020": {
            "sampleType": "IN-SAMPLE: B's 2026-10-20 archive rebuilt with today's code and the "
            "main tree current at that archive (B's own b8008c2a4 tree is not reachable)",
            "provenance": b_prov,
            **correlation_block(values_by_sid(b_contract), ppg, pos_of),
        },
        "preseasonSameCohort": same_cohort,
        "investigationB_recorded": {
            "valueToday_vs_ppg2026ytd": {
                g: b_recorded["valueToday_vs_ppg2026ytd"][g]["all"] for g in ("offense", "idp")
            },
            "valuePreseasonServed_vs_ppg2026ytd": {
                g: b_recorded["valuePreseasonServed_vs_ppg2026ytd"][g]["all"]
                for g in ("offense", "idp")
            },
        },  # fmt: skip
    }

    # ── provenance + privacy ─────────────────────────────────────────────
    archive_path = REPO / args.archive
    with zipfile.ZipFile(archive_path) as zf:
        site_raw = {n: hashlib.sha256(zf.read(n)).hexdigest()
                    for n in zf.namelist() if n.startswith("site_raw/")}  # fmt: skip
    served_sha = served_board_sha256(contract.get("playersArray") or [])
    receipts = {
        redact_endpoint(url[len(SLEEPER):]): rec
        for url, rec in sorted(fetch.receipts.items())
        if url.startswith(SLEEPER)
    }  # fmt: skip
    manifest_path = Path(args.manifest) if args.manifest else REPO / MANIFEST_DEFAULT
    crosscheck: dict[str, Any] = {"status": "UNAVAILABLE", "reason": "no Lane A manifest found"}
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        crosscheck = {
            "manifestSha256": sha256_file(manifest_path),
            **crosscheck_manifest(
                manifest,
                receipts=fetch.receipts,
                served_sha=served_sha,
                archive_sha=sha256_file(archive_path),
                live_fingerprint=fmt["scoringFingerprintLive"],
                archived_fingerprint=fmt["scoringFingerprintArchived"],
                roster_fingerprint=fmt["rosterFormatFingerprint"],
            ),
        }
    out = {
        "purpose": "Lane C-market baseline (directive 2026-10-25 §6C/§9). RESEARCH ONLY: "
        "no served value, rank, weight, curve, bridge or flag changed.",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "generatedBy": "scripts/idp_accuracy/market_baseline.py",
        "inputs": {
            "codeSha": git("rev-parse", "HEAD"),
            "scriptSha256": sha256_file(Path(__file__).resolve()),
            "pinnedMainSha": git("rev-parse", PINNED_CSV_REV),
            "leagueKey": LEAGUE_KEY,
            "archive": args.archive,
            "archiveSha256": sha256_file(archive_path),
            "archiveSiteRawSha256": site_raw,
            "contractBuild": prov,
            "scrapeTimestamp": contract.get("scrapeTimestamp"),
            "scoringWeeks": weeks,
            "week7": "EXCLUDED (in progress on 2026-10-25)",
            "kickoffUtc": KICKOFF_UTC,
            "servedBoardSha256": served_sha,
            "sleeperReceipts": receipts,
            "laneAManifestCrosscheck": crosscheck,
            "rosterCount": len(sl["rosters"]),
            "scorerCheck": scorer,
            "scorerCheckNoGpFilter": scorer_all,
            "hillParamSet": ((contract.get("hillCurves") or {}).get("provenance") or {}).get(
                "paramSetId"
            ),
            "packageModelUntouched": "geom_q078_v1 (not read or exercised by this script)",
        },
        "leagueFormat": fmt,
        "baseline": baseline,
        "starterBenchByTier": sbt,
        "idpTradeCalcNative": native,
        "draftSharksCombinedNative": ds_native,
        "nativeLevelRatios": level,
        "bridgeTrace": trace,
        "perturbations": perturb,
        "leagueFormatAlignment": alignment,
        "correlationReproduction": corr,
        "verdict": VERDICT,
        "timingSec": round(time.time() - t0, 1),
    }
    teams = (contract.get("sleeper") or {}).get("teams") or []
    forbidden = {LEAGUE_ID, str(sl["league"].get("name") or "")}
    for t in teams:
        forbidden |= {str(t.get("name") or ""), str(t.get("sleeperTeamName") or ""),
                      str(t.get("ownerId") or "")}  # fmt: skip
    for r in sl["rosters"]:
        forbidden |= {str(r.get("owner_id") or "")}
    forbidden.discard("")
    assert_aggregate_only(out, forbidden)
    dst = REPO / args.out
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(json.dumps(out, indent=1, default=str) + "\n", encoding="utf-8")
    print(f"wrote {args.out} in {out['timingSec']}s", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
