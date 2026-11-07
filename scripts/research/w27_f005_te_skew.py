"""W27-F005 TE retail-premium skew -- offline methodology research.  NOT ACTIVATED.

Question (owner directive 2026-11-07, docs/owner/SESSION_RESUMPTION_DIRECTIVE_2026-11-07.md
section 3): on the pinned board, top-250 tight ends carry ``marketGapDirection`` =
``retail_premium`` 22 times and ``consensus_premium`` once.  Is that a genuine market
difference, TE-premium scoring, positional calibration, replacement level, market-source
behaviour, a wrong transformation, or a methodology mismatch?

What this script does (read-only; it writes only the ``--out`` JSON when asked):

1. Pins the board: the archived raw payload AND the repository tree the contract build
   reads (source CSVs, ``data/scrape_state``, ``config/weights``) at the git revision that
   added the archive (``scripts/research_pinned_board.py``).  Every build runs with the
   network refused and the Sleeper league-context lookup replaced by its offline
   fallback, so no result depends on a live service.
2. Re-measures KTC's own TE++ uplift from the paired KTC boards (``ktc`` vs ``ktcSfTep``)
   with an independent binned-median computation, and compares it to the production
   curve's constants (read from the pinned ``config/weights/te_premium_curve.json`` and
   evaluated here, not through ``src.league_intel.te_premium``).
3. Decomposes each row's incumbent gap ``log(market / model)`` exactly into a TIER term
   (KTC Market's own value at our board's rank minus our value -- shared by every asset at
   that rank, whatever its position) and an ORDINAL term (KTC Market's value minus its
   value at our board's rank -- the player-specific disagreement).
4. Measures every source's tight-end posture on the KTC base -> KTC TE++ axis
   (theta = 0 prices TEs like KTC's base board, theta = 1 like KTC's TE++ board),
   scale-free by quantile matching against KTC's base board.
5. Candidates: C1 scale-neutral (quantile-matched) gap -- label-only; C2 counterfactual
   "TEP-native sources converted with KTC's measured curve instead of the flat 1.10" --
   value-changing, run through the production build with the registry patched IN
   PROCESS ONLY, and cross-checked by an independent log-linear re-blend oracle;
   leave-KTC-out diagnostic; C3 position re-centring (forced symmetry, computed only to
   show what it would erase).
6. ``--history``: point-in-time evaluation over the daily archives since KTC Market was
   first captured (2026-09-08): does a label at t predict KTC Market's relative move to
   t + horizon?  Labels use only data at t (no look-ahead); every board is rebuilt from
   its own pinned tree with TODAY's code (stated limitation).

Nothing here edits ``src/``, ``config/``, feature flags or any served path.
"""

from __future__ import annotations

import argparse
import contextlib
import copy
import datetime as dt
import hashlib
import json
import math
import re
import socket
import statistics
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from scripts.research_pinned_board import csv_tree, load_archive  # noqa: E402

DEFAULT_ARCHIVE = "exports/archive/dynasty_export_20261106_194518.zip"
OFFENSE = ("QB", "RB", "WR", "TE")
CONTROLS = ("QB", "RB", "WR")
#: The /edge and /rankings label population (``tests/api/test_audit_w27_f005_regression.py``).
LABEL_RANK_LIMIT = 250
#: Mirrors of ``frontend/lib/thresholds.js`` -- read, never redefined for production.
MIN_RATIO = 0.05  # MARKET_GAP_MIN_VALUE_RATIO
PANEL_RATIO = 0.15  # PREMIUM_SUMMARY_VALUE_RATIO
KTC_VOTERS = ("ktcCrowdSfTep", "ktcTradesSfTep")
KTC_BASE_KEY = "ktc"
KTC_TEPP_KEY = "ktcSfTep"
#: Registry entries flagged ``is_tep_premium`` that take the flat native multiplier
#: (KTC's two voters are exempt from every TE transform and stay untouched).
TEP_NATIVE_NON_KTC = (
    "idpTradeCalc",
    "dlfValuesSfTep",
    "dynastyNerdsSfTep",
    "fantasyProsFitzmaurice",
    "yahooBoone",
    "draftSharks",
)
#: The first archive whose tree carries KTC Market (``ktcCrowdTradesSfTep``).
HISTORY_START = "20260908"
TIER_TABLE_RANKS = (1, 11, 26, 51, 101, 151, 201, 251, 301, 401)
_ARCHIVE_RE = re.compile(r"dynasty_export_(\d{8})_(\d{6})\.zip$")


# ── small numeric helpers ───────────────────────────────────────────────


def _pos_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(out) or out <= 0:
        return None
    return out


def _r(value: float | None, nd: int = 4) -> float | None:
    return None if value is None else round(float(value), nd)


def _median(values: Iterable[float]) -> float | None:
    vals = [v for v in values if v is not None]
    return statistics.median(vals) if vals else None


def _rank(values: list[float]) -> list[float]:
    """Average ranks (1-based), ties shared -- for a Spearman correlation."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def spearman(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 3 or len(xs) != len(ys):
        return None
    rx, ry = _rank(xs), _rank(ys)
    mx, my = statistics.fmean(rx), statistics.fmean(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = math.sqrt(sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry))
    return None if den == 0 else num / den


# ── pinned, offline builds ──────────────────────────────────────────────


def git(*args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(REPO), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def archive_revision(archive: str) -> str:
    """The commit that ADDED the archive: its tree is the one that built it."""
    rel = Path(archive)
    if rel.is_absolute():
        rel = rel.relative_to(REPO)
    out = git("log", "--diff-filter=A", "--format=%H", "--", rel.as_posix())
    revs = out.split()
    if not revs:
        raise SystemExit(f"no commit adds {rel}; cannot pin its tree")
    return revs[-1]


@contextlib.contextmanager
def offline_build() -> Iterator[list[str]]:
    """Refuse the network and give the league-context lookup its offline fallback.

    ``_resolve_league_context`` would otherwise try Sleeper on every build; its fallback
    (default roster count, no TE bonus) is what an offline machine gets anyway.  Any
    other connection attempt is refused and recorded."""
    from src.api import data_contract as dc  # noqa: PLC0415

    blocked: list[str] = []
    orig_connect = socket.socket.connect
    orig_ctx = dc._resolve_league_context
    default_size = dc._ROOKIE_ANCHOR_LEAGUE_SIZE_DEFAULT

    def _refuse(self: socket.socket, address: Any) -> None:  # noqa: ARG001
        blocked.append(str(address))
        raise OSError("network refused: offline research build")

    def _offline_ctx(default_roster_count: int = default_size) -> dict[str, Any]:
        return {
            "roster_count": int(default_roster_count),
            "bonus_rec_te": 0.0,
            "fetched_from_sleeper": False,
        }

    socket.socket.connect = _refuse  # type: ignore[method-assign]
    dc._resolve_league_context = _offline_ctx
    try:
        yield blocked
    finally:
        socket.socket.connect = orig_connect  # type: ignore[method-assign]
        dc._resolve_league_context = orig_ctx


@contextlib.contextmanager
def tep_native_as_base(keys: Iterable[str]) -> Iterator[None]:
    """RESEARCH COUNTERFACTUAL, in-process only: treat ``keys`` as non-TEP sources.

    Their TE contributions then take the measured base -> TE++ curve instead of the
    flat native multiplier.  The registry list is restored element-for-element."""
    from src.api import data_contract as dc  # noqa: PLC0415

    wanted = frozenset(keys)
    if not wanted:
        yield
        return
    original = list(dc._RANKING_SOURCES)
    dc._RANKING_SOURCES[:] = [
        dict(s, is_tep_premium=False) if s.get("key") in wanted else s for s in original
    ]
    try:
        yield
    finally:
        dc._RANKING_SOURCES[:] = original


def build_contract(
    raw: dict[str, Any],
    csv_root: Path | None,
    *,
    source_overrides: dict[str, dict[str, Any]] | None = None,
    native_as_base: Iterable[str] = (),
) -> tuple[dict[str, Any], list[str]]:
    from src.api.data_contract import build_api_data_contract  # noqa: PLC0415

    with offline_build() as blocked, tep_native_as_base(native_as_base):
        contract = build_api_data_contract(
            copy.deepcopy(raw), csv_root=csv_root, source_overrides=source_overrides
        )
    return contract, list(blocked)


def board_sha256(rows: list[dict[str, Any]]) -> str:
    blob = json.dumps(
        sorted(
            (str(r.get("displayName")), r.get("rankDerivedValue"), r.get("canonicalConsensusRank"))
            for r in rows
        ),
        separators=(",", ":"),
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


# ── row accessors ───────────────────────────────────────────────────────


def _pos(row: dict[str, Any]) -> str:
    return str(row.get("position") or "").strip().upper()


def _name(row: dict[str, Any]) -> str:
    return str(row.get("displayName") or row.get("canonicalName") or "")


def _model(row: dict[str, Any]) -> float | None:
    return _pos_float(row.get("rankDerivedValue"))


def _market_norm(row: dict[str, Any]) -> float | None:
    return _pos_float((row.get("ktcMarket") or {}).get("normalizedValue"))


def _market_raw(row: dict[str, Any]) -> float | None:
    return _pos_float((row.get("ktcMarket") or {}).get("value"))


def _site(row: dict[str, Any], key: str) -> float | None:
    return _pos_float((row.get("canonicalSiteValues") or {}).get(key))


def _label_eligible(row: dict[str, Any]) -> bool:
    rank = row.get("canonicalConsensusRank")
    return (
        _pos(row) in OFFENSE
        and rank is not None
        and rank <= LABEL_RANK_LIMIT
        and not row.get("quarantined")
    )


def signed_gap(market: float | None, model: float | None) -> float | None:
    """Independent re-statement of the incumbent: (market - model) / mean(both).

    Positive = KTC Market above our model (``retail_premium``)."""
    if market is None or model is None:
        return None
    return (market - model) / ((market + model) / 2.0)


# ── 1. KTC's own TE++ uplift, re-measured ───────────────────────────────


def load_curve(csv_root: Path | None) -> dict[str, float]:
    root = csv_root if csv_root is not None else REPO
    data = json.loads(
        (root / "config" / "weights" / "te_premium_curve.json").read_text(encoding="utf-8")
    )
    lo, hi = data["observed_ratio_range"]
    return {
        "a": float(data["a"]),
        "k": float(data["k"]),
        "floor": float(data["floor"]),
        "ceiling": float(hi),
        "rangeLow": float(lo),
    }


def curve_uplift(value: float, curve: dict[str, float]) -> float:
    """``min(ceiling, max(floor, 1 + a * v^-k))`` -- evaluated here, independently."""
    return min(curve["ceiling"], max(curve["floor"], 1.0 + curve["a"] * value ** (-curve["k"])))


def soft_knee(value: float, knee: float = 9900.0, top: float = 9999.0) -> float:
    """The documented C1 soft ceiling, restated: identity below the knee."""
    if value <= knee:
        return value
    return top - (top - knee) * math.exp(-(value - knee) / (top - knee))


def ktc_uplift_oracle(rows: list[dict[str, Any]], curve: dict[str, float]) -> dict[str, Any]:
    by_pos: dict[str, dict[str, Any]] = {}
    for pos in OFFENSE:
        pairs = [
            (_site(r, KTC_BASE_KEY), _site(r, KTC_TEPP_KEY))
            for r in rows
            if _pos(r) == pos and _site(r, KTC_BASE_KEY) and _site(r, KTC_TEPP_KEY)
        ]
        ratios = [b / a for a, b in pairs]
        by_pos[pos] = {
            "n": len(pairs),
            "identical": sum(1 for a, b in pairs if a == b),
            "medianRatio": _r(_median(ratios)),
        }
    te = sorted(
        (
            (_site(r, KTC_BASE_KEY), _site(r, KTC_TEPP_KEY))
            for r in rows
            if _pos(r) == "TE" and _site(r, KTC_BASE_KEY) and _site(r, KTC_TEPP_KEY)
        ),
        key=lambda p: -p[0],
    )
    bands = {"TE1-12": (0, 12), "TE13-24": (12, 24), "TE25-40": (24, 40), "TE41+": (40, 10**6)}
    band_out = {}
    for label, (lo, hi) in bands.items():
        sub = te[lo:hi]
        if sub:
            band_out[label] = {
                "n": len(sub),
                "actualMedian": _r(_median(b / a for a, b in sub)),
                "curveMedian": _r(_median(curve_uplift(a, curve) for a, _ in sub)),
            }
    resid = [math.log((b / a) / curve_uplift(a, curve)) for a, b in te]
    return {
        "byPosition": by_pos,
        "teBands": band_out,
        "teMedianLogResidualActualOverCurve": _r(_median(resid)),
        "teMeanLogResidualActualOverCurve": _r(statistics.fmean(resid) if resid else None),
        "curveConstants": {k: _r(v, 6) for k, v in curve.items()},
    }


# ── 2/3. label census and the tier / ordinal decomposition ──────────────


def census(
    rows: list[dict[str, Any]], ratio_of: Callable[[dict[str, Any]], float | None], min_ratio: float
) -> dict[str, dict[str, int]]:
    out = {p: {"sell": 0, "buy": 0, "belowGate": 0, "unmeasured": 0} for p in OFFENSE}
    for row in rows:
        if not _label_eligible(row):
            continue
        s = ratio_of(row)
        cell = out[_pos(row)]
        if s is None:
            cell["unmeasured"] += 1
        elif abs(s) < min_ratio:
            cell["belowGate"] += 1
        elif s > 0:
            cell["sell"] += 1
        else:
            cell["buy"] += 1
    return out


def scale_decomposition(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Exact split ``log(m / v) = tier + ordinal`` over the KTC-priced universe.

    ``q`` = KTC Market's own normalized value at our board's rank within the universe of
    rows both boards price.  tier = log(q / v): how differently the two VALUE CURVES
    price that rank.  ordinal = log(m / q): whether KTC ranks the player above (+) or
    below (-) our board, expressed in KTC's own value units.  Because ``q`` is a
    permutation of ``m``, the ordinal terms sum to zero over the universe by
    construction -- C1 assumes the two boards agree on the value distribution and
    disagree only on who occupies each rank."""
    universe = [r for r in rows if _model(r) and _market_norm(r)]
    market_sorted = sorted((_market_norm(r) for r in universe), reverse=True)
    model_sorted = sorted((_model(r) for r in universe), reverse=True)
    order = sorted(universe, key=lambda r: (-_model(r), _name(r)))
    per_row: dict[str, dict[str, float]] = {}
    for i, row in enumerate(order):
        m, v, q = _market_norm(row), _model(row), market_sorted[i]
        per_row[_name(row)] = {
            "tier": math.log(q / v),
            "ordinal": math.log(m / q),
            "total": math.log(m / v),
            "c1": (m - q) / ((m + q) / 2.0),
            "boardRankInUniverse": i + 1,
        }
    tier_table = [
        {
            "rank": k,
            "ktcMarket": _r(market_sorted[k - 1], 1),
            "board": _r(model_sorted[k - 1], 1),
            "logMarketOverBoard": _r(math.log(market_sorted[k - 1] / model_sorted[k - 1])),
        }
        for k in TIER_TABLE_RANKS
        if k <= len(universe)
    ]
    pos_summary = {}
    for pos in OFFENSE:
        cells = [per_row[_name(r)] for r in universe if _label_eligible(r) and _pos(r) == pos]
        if not cells:
            continue
        pos_summary[pos] = {
            "n": len(cells),
            "totalMedian": _r(_median(c["total"] for c in cells)),
            "tierMedian": _r(_median(c["tier"] for c in cells)),
            "ordinalMedian": _r(_median(c["ordinal"] for c in cells)),
            "ordinalPositiveShare": _r(sum(c["ordinal"] > 0 for c in cells) / len(cells), 3),
            "tierShareOfTotal": _r(
                _median(c["tier"] for c in cells) / _median(c["total"] for c in cells)
                if _median(c["total"] for c in cells)
                else None,
                3,
            ),
        }
    return {
        "universeSize": len(universe),
        "ordinalSumOverUniverse": _r(sum(c["ordinal"] for c in per_row.values()), 9),
        "maxDecompositionError": _r(
            max(
                (abs(c["tier"] + c["ordinal"] - c["total"]) for c in per_row.values()), default=0.0
            ),
            12,
        ),
        "tierCurve": tier_table,
        "byPosition": pos_summary,
        "_perRow": per_row,
    }


# ── 4. tight-end posture on the KTC base -> TE++ axis ───────────────────


def _te_lift_vs_ktc_base(
    rows: list[dict[str, Any]], value_of: Callable[[dict[str, Any]], float | None]
) -> tuple[dict[str, float], int]:
    """Median, by position, of log(KTC-base value at the source's rank / KTC-base value).

    Quantile matching against KTC's base board makes every source comparable whatever
    its native scale (ranks, 0-100 indices, 0-9999 values).  Positive = the source ranks
    the player above where KTC's base board does."""
    offense = [r for r in rows if _pos(r) in OFFENSE]
    universe = [r for r in offense if value_of(r) and _site(r, KTC_BASE_KEY)]
    base_sorted = sorted((_site(r, KTC_BASE_KEY) for r in universe), reverse=True)
    order = sorted(universe, key=lambda r: (-value_of(r), _name(r)))
    by_pos: dict[str, list[float]] = {p: [] for p in OFFENSE}
    for i, row in enumerate(order):
        if not _label_eligible(row):
            continue
        by_pos[_pos(row)].append(math.log(base_sorted[i] / _site(row, KTC_BASE_KEY)))
    return {p: statistics.median(v) for p, v in by_pos.items() if v}, len(universe)


def te_posture(
    rows: list[dict[str, Any]], source_keys: Iterable[str], registry_tep: dict[str, bool]
) -> dict[str, Any]:
    ref, _n = _te_lift_vs_ktc_base(rows, lambda r: _site(r, KTC_TEPP_KEY))
    denom = ref.get("TE")
    out: dict[str, Any] = {
        "ktcTeppReference": {p: _r(v) for p, v in ref.items()},
        "sources": {},
    }
    targets = [(k, (lambda key: (lambda r: _site(r, key)))(k)) for k in source_keys]
    targets.append(("__board__", _model))
    for key, fn in targets:
        lifts, n = _te_lift_vs_ktc_base(rows, fn)
        if "TE" not in lifts or not denom:
            continue
        out["sources"][key] = {
            "n": n,
            "registryTepNative": registry_tep.get(key),
            "teLift": _r(lifts["TE"]),
            "controls": {p: _r(lifts.get(p)) for p in CONTROLS},
            "theta": _r(lifts["TE"] / denom, 3),
        }
    return out


# ── 5. counterfactual oracle and impacts ────────────────────────────────


def native_to_curve_oracle(rows: list[dict[str, Any]], curve: dict[str, float]) -> dict[str, float]:
    """Independent prediction of C2's TE values from the incumbent's own stamps.

    For each tight end: every voting TEP-native contribution c is un-corrected
    (c / native multiplier) and re-lifted with the curve evaluated here; the value moves
    by the applied-weight-weighted mean log change of its contributions.  A log-linear
    sensitivity of the blend -- deliberately NOT the production blend (no Hampel, no
    trimming, no family cap re-run)."""
    out: dict[str, float] = {}
    for row in rows:
        if _pos(row) != "TE" or not _model(row):
            continue
        dropped = set(row.get("droppedSources") or [])
        num = den = 0.0
        for key, meta in sorted((row.get("sourceRankMeta") or {}).items()):
            w = _pos_float(meta.get("appliedWeight"))
            c = _pos_float(meta.get("valueContribution"))
            if not w or not c or meta.get("contributedToBlend") is False or key in dropped:
                continue
            delta = 0.0
            if meta.get("tepNativeCorrectionApplied"):
                mult = _pos_float(meta.get("tepNativeCorrection")) or 1.0
                pre = c / mult
                delta = math.log(soft_knee(pre * curve_uplift(pre, curve)) / c)
            num += w * delta
            den += w
        if den > 0:
            out[_name(row)] = _model(row) * math.exp(num / den)
    return out


def value_impacts(
    before: list[dict[str, Any]], after: list[dict[str, Any]], top: int = 12
) -> dict[str, Any]:
    a_by = {_name(r): r for r in after}
    pct: dict[str, list[float]] = {}
    movers = []
    rank_moves = []
    changed = {}
    for row in before:
        name = _name(row)
        other = a_by.get(name)
        v0, v1 = _model(row), _model(other) if other else None
        pos = _pos(row)
        if v0 is None or v1 is None:
            continue
        if abs(v1 - v0) >= 1:
            changed[pos] = changed.get(pos, 0) + 1
        p = (v1 - v0) / v0
        pct.setdefault(pos, []).append(p)
        r0, r1 = row.get("canonicalConsensusRank"), other.get("canonicalConsensusRank")
        if r0 is not None and r1 is not None:
            rank_moves.append(abs(r1 - r0))
        if pos == "TE":
            movers.append((p, name, v0, v1, r0, r1))
    movers.sort(key=lambda t: (-abs(t[0]), t[1]))
    return {
        "rowsChangedByPosition": dict(sorted(changed.items())),
        "medianPctChangeByPosition": {k: _r(_median(v)) for k, v in sorted(pct.items())},
        "maxPctChangeByPosition": {k: _r(max(v, key=abs)) for k, v in sorted(pct.items())},
        "rankDisplacement": {
            "median": _r(_median(rank_moves), 1),
            "max": max(rank_moves) if rank_moves else None,
        },
        "topTeMovers": [
            {
                "name": n,
                "before": round(v0),
                "after": round(v1),
                "pct": _r(p),
                "rankBefore": r0,
                "rankAfter": r1,
            }
            for p, n, v0, v1, r0, r1 in movers[:top]
        ],
    }


def label_flips(
    rows: list[dict[str, Any]], before: Callable, after: Callable, min_ratio: float = MIN_RATIO
) -> dict[str, Any]:
    def lab(s: float | None) -> str:
        if s is None:
            return "unmeasured"
        if abs(s) < min_ratio:
            return "hold"
        return "sell" if s > 0 else "buy"

    flips: dict[str, dict[str, int]] = {}
    examples: list[dict[str, Any]] = []
    for row in sorted(rows, key=lambda r: (r.get("canonicalConsensusRank") or 10**6, _name(r))):
        if not _label_eligible(row):
            continue
        b, a = lab(before(row)), lab(after(row))
        if a == b:
            continue
        key = f"{b}->{a}"
        flips.setdefault(_pos(row), {}).setdefault(key, 0)
        flips[_pos(row)][key] += 1
        if _pos(row) == "TE":
            examples.append(
                {
                    "name": _name(row),
                    "rank": row.get("canonicalConsensusRank"),
                    "before": b,
                    "after": a,
                    "beforeRatio": _r(before(row)),
                    "afterRatio": _r(after(row)),
                }
            )
    return {
        "byPosition": {k: dict(sorted(v.items())) for k, v in sorted(flips.items())},
        "teExamples": examples,
    }


# ── pinned single-archive analysis ──────────────────────────────────────


def analyse_archive(archive: str, *, counterfactuals: bool = True) -> dict[str, Any]:
    from src.api.data_contract import _RANKING_SOURCES  # noqa: PLC0415

    zpath, member, blob, raw = load_archive(archive)
    rev = archive_revision(archive)
    registry_tep = {str(s.get("key")): bool(s.get("is_tep_premium")) for s in _RANKING_SOURCES}
    out: dict[str, Any] = {
        "inputs": {
            "archive": zpath.relative_to(REPO).as_posix(),
            "archiveSha256": hashlib.sha256(zpath.read_bytes()).hexdigest(),
            "payloadMember": member,
            "payloadSha256": hashlib.sha256(blob).hexdigest(),
            "boardDate": raw.get("date"),
            "scrapeTimestamp": raw.get("scrapeTimestamp"),
            "treeRevision": rev,
        }
    }
    with csv_tree(rev) as (root, prov):
        out["inputs"]["treeContentSha256"] = prov["contentSha256"]
        curve = load_curve(root)
        contract, blocked = build_contract(raw, root)
        rows = contract["playersArray"]
        out["inputs"]["incumbentBoardSha256"] = board_sha256(rows)
        out["inputs"]["networkAttemptsRefused"] = len(blocked)

        # The incumbent, restated independently and checked against the stamps.
        def c0(row: dict[str, Any]) -> float | None:
            return signed_gap(_market_norm(row), _model(row))

        mismatch = 0
        for row in rows:
            s = c0(row)
            stamped = row.get("marketGapValueRatio")
            if s is None:
                mismatch += stamped is not None
                continue
            direction = "retail_premium" if s > 0 else ("consensus_premium" if s < 0 else "none")
            if (
                stamped is None
                or abs(abs(s) - stamped) > 1e-9
                or row.get("marketGapDirection") != direction
            ):
                mismatch += 1
        out["incumbentRestatementMismatches"] = mismatch

        decomposition = scale_decomposition(rows)
        per_row = decomposition.pop("_perRow")

        def c1(row: dict[str, Any]) -> float | None:
            cell = per_row.get(_name(row))
            return None if cell is None or not _model(row) or not _market_norm(row) else cell["c1"]

        # C3 (forced symmetry, shown only to be rejected): subtract the position median.
        pos_median = {
            p: _median(
                c0(r) for r in rows if _label_eligible(r) and _pos(r) == p and c0(r) is not None
            )
            for p in OFFENSE
        }

        def c3(row: dict[str, Any]) -> float | None:
            s = c0(row)
            return None if s is None else s - (pos_median.get(_pos(row)) or 0.0)

        out["ktcUpliftOracle"] = ktc_uplift_oracle(rows, curve)
        out["decomposition"] = decomposition
        offense_sources = sorted(
            str(s.get("key")) for s in _RANKING_SOURCES if str(s.get("scope")) == "overall_offense"
        )
        out["tePosture"] = te_posture(
            rows,
            ["ktcCrowdTradesSfTep", "idpTradeCalc", *offense_sources],
            registry_tep,
        )
        out["census"] = {
            "C0_incumbent_gate005": census(rows, c0, MIN_RATIO),
            "C0_incumbent_gate015": census(rows, c0, PANEL_RATIO),
            "C1_scaleNeutral_gate005": census(rows, c1, MIN_RATIO),
            "C1_scaleNeutral_gate015": census(rows, c1, PANEL_RATIO),
            "C3_positionRecentred_gate005": census(rows, c3, MIN_RATIO),
        }
        out["labelFlips_C0_to_C1"] = label_flips(rows, c0, c1)
        sleeper = contract.get("sleeper") or {}
        scoring = sleeper.get("scoringSettings") or {}
        positions = sleeper.get("rosterPositions") or []
        out["leagueFacts"] = {
            "scoringKeys": {
                k: scoring.get(k)
                for k in (
                    "rec",
                    "bonus_rec_te",
                    "bonus_fd_te",
                    "bonus_fd_wr",
                    "bonus_rec_wr",
                    "rec_td",
                )
            },
            "dedicatedTeSlots": sum(1 for p in positions if p == "TE"),
            "flexSlots": sum(1 for p in positions if p == "FLEX"),
            "superFlexSlots": sum(1 for p in positions if p == "SUPER_FLEX"),
            "boardTeBasisConstant": "tepp",
        }

        if counterfactuals:
            cf, _ = build_contract(raw, root, native_as_base=TEP_NATIVE_NON_KTC)
            cf_rows = cf["playersArray"]
            cf_by = {_name(r): r for r in cf_rows}
            converted = sum(
                1
                for r in cf_rows
                if _pos(r) == "TE"
                for k, m in (r.get("sourceRankMeta") or {}).items()
                if k in TEP_NATIVE_NON_KTC and m.get("tepBoostApplied")
            )

            def c2(row: dict[str, Any]) -> float | None:
                other = cf_by.get(_name(row))
                return None if other is None else signed_gap(_market_norm(other), _model(other))

            predicted = native_to_curve_oracle(rows, curve)

            def c2_oracle(row: dict[str, Any]) -> float | None:
                if _pos(row) != "TE":
                    return c0(row)
                v = predicted.get(_name(row))
                return signed_gap(_market_norm(row), v)

            errs = []
            for name, v_pred in predicted.items():
                other = cf_by.get(name)
                if other is None or not _model(other):
                    continue
                base = next((r for r in rows if _name(r) == name), None)
                if base is None or not _label_eligible(base):
                    continue
                errs.append((v_pred - _model(other)) / _model(other))
            cf_decomp = scale_decomposition(cf_rows)["_perRow"]

            def c1_on_c2(row: dict[str, Any]) -> float | None:
                other = cf_by.get(_name(row))
                cell = cf_decomp.get(_name(row))
                if other is None or cell is None or not _model(other) or not _market_norm(other):
                    return None
                return cell["c1"]

            out["C2_nativeAsBase"] = {
                "sourcesConverted": list(TEP_NATIVE_NON_KTC),
                "teSourceRowsNowOnCurve": converted,
                "census_gate005": census(rows, c2, MIN_RATIO),
                "census_C1_on_C2_gate005": census(rows, c1_on_c2, MIN_RATIO),
                "oracleCensus_gate005": census(rows, c2_oracle, MIN_RATIO),
                "oracleVsPipelineTeValue": {
                    "n": len(errs),
                    "medianAbsPctError": _r(_median(abs(e) for e in errs)),
                    "maxAbsPctError": _r(max((abs(e) for e in errs), default=None)),
                    "medianSignedPctError": _r(_median(errs)),
                },
                "valueImpacts": value_impacts(rows, cf_rows),
                "boardSha256": board_sha256(cf_rows),
                "tePosture": te_posture(cf_rows, [], registry_tep)["sources"].get("__board__"),
            }

            loo, _ = build_contract(
                raw, root, source_overrides={k: {"include": False} for k in KTC_VOTERS}
            )
            loo_by = {_name(r): r for r in loo["playersArray"]}

            def c_loo(row: dict[str, Any]) -> float | None:
                other = loo_by.get(_name(row))
                return None if other is None else signed_gap(_market_norm(row), _model(other))

            out["leaveKtcOut"] = {
                "census_gate005": census(rows, c_loo, MIN_RATIO),
                "teMedianSignedGap": _r(
                    _median(
                        c_loo(r)
                        for r in rows
                        if _label_eligible(r) and _pos(r) == "TE" and c_loo(r) is not None
                    )
                ),
                "tePosture": te_posture(loo["playersArray"], [], registry_tep)["sources"].get(
                    "__board__"
                ),
            }
    return out


# ── 6. point-in-time history ────────────────────────────────────────────


def daily_archives(start: str, end: str | None) -> list[str]:
    """The last archive of each day in [start, end]."""
    by_day: dict[str, tuple[str, str]] = {}
    for path in sorted((REPO / "exports" / "archive").glob("dynasty_export_*.zip")):
        m = _ARCHIVE_RE.search(path.name)
        if not m:
            continue
        day, clock = m.group(1), m.group(2)
        if day < start or (end is not None and day > end):
            continue
        if day not in by_day or clock > by_day[day][0]:
            by_day[day] = (clock, path.relative_to(REPO).as_posix())
    return [by_day[d][1] for d in sorted(by_day)]


def compact_board(archive: str) -> dict[str, Any]:
    _zpath, _member, blob, raw = load_archive(archive)
    rev = archive_revision(archive)
    with csv_tree(rev) as (root, prov):
        contract, blocked = build_contract(raw, root)
    rows = contract["playersArray"]
    per_row = scale_decomposition(rows)["_perRow"]
    cells = {}
    for row in rows:
        m_raw, m_norm, v = _market_raw(row), _market_norm(row), _model(row)
        if not (m_raw and m_norm and v):
            continue
        cells[_name(row)] = {
            "pos": _pos(row),
            "eligible": _label_eligible(row),
            "mktRaw": m_raw,
            "c0": signed_gap(m_norm, v),
            "c1": per_row[_name(row)]["c1"],
        }
    return {
        "archive": archive,
        "date": str(raw.get("date")),
        "payloadSha256": hashlib.sha256(blob).hexdigest(),
        "treeRevision": rev,
        "treeContentSha256": prov["contentSha256"],
        "networkAttemptsRefused": len(blocked),
        "rows": cells,
    }


def evaluate_history(boards: list[dict[str, Any]], horizon_days: int) -> dict[str, Any]:
    by_date = {dt.date.fromisoformat(b["date"]): b for b in boards}
    dates = sorted(by_date)
    result: dict[str, Any] = {"horizonDays": horizon_days, "labelDates": 0, "signals": {}}
    obs: dict[str, list[tuple[str, str, float, float]]] = {"c0": [], "c1": []}
    ics: dict[str, list[float]] = {"c0": [], "c1": []}
    persistence: dict[str, dict[str, list[int]]] = {"c0": {}, "c1": {}}
    for d in dates:
        target = d + dt.timedelta(days=horizon_days)
        outcome_dates = [x for x in dates if x >= target]
        if not outcome_dates:
            continue
        b0, b1 = by_date[d], by_date[outcome_dates[0]]
        common = [n for n in b0["rows"] if n in b1["rows"]]
        offense_moves = [
            math.log(b1["rows"][n]["mktRaw"] / b0["rows"][n]["mktRaw"])
            for n in common
            if b0["rows"][n]["pos"] in OFFENSE
        ]
        if len(offense_moves) < 50:
            continue
        drift = statistics.median(offense_moves)
        result["labelDates"] += 1
        for sig in ("c0", "c1"):
            xs, ys = [], []
            for n in sorted(common):
                cell = b0["rows"][n]
                if not cell["eligible"]:
                    continue
                move = math.log(b1["rows"][n]["mktRaw"] / cell["mktRaw"]) - drift
                s = cell[sig]
                xs.append(s)
                ys.append(move)
                if abs(s) >= MIN_RATIO:
                    obs[sig].append((cell["pos"], n, s, move))
                    later = b1["rows"][n][sig]
                    same = int((later > 0) == (s > 0) and abs(later) >= MIN_RATIO)
                    persistence[sig].setdefault(cell["pos"], []).append(same)
            ic = spearman(xs, ys)
            if ic is not None:
                ics[sig].append(-ic)  # positive = the gap predicted the move's direction
    for sig in ("c0", "c1"):
        per_pos: dict[str, Any] = {}
        for pos in OFFENSE + ("ALL",):
            cells = [o for o in obs[sig] if pos == "ALL" or o[0] == pos]
            if not cells:
                continue
            hits = [int((s > 0 and m < 0) or (s < 0 and m > 0)) for _p, _n, s, m in cells]
            sells = [m for _p, _n, s, m in cells if s > 0]
            buys = [m for _p, _n, s, m in cells if s < 0]
            players: dict[str, list[int]] = {}
            for (_p, n, _s, _m), h in zip(cells, hits):
                players.setdefault(n, []).append(h)
            per_pos[pos] = {
                "observations": len(cells),
                "distinctPlayers": len(players),
                "sellObs": len(sells),
                "buyObs": len(buys),
                "hitRate": _r(statistics.fmean(hits), 3),
                "playerClusteredHitRate": _r(
                    statistics.fmean(statistics.fmean(v) for v in players.values()), 3
                ),
                "meanRelMoveAfterSell": _r(statistics.fmean(sells) if sells else None),
                "meanRelMoveAfterBuy": _r(statistics.fmean(buys) if buys else None),
            }
        ic = ics[sig]
        result["signals"][sig] = {
            "byPosition": per_pos,
            "meanInformationCoefficient": _r(statistics.fmean(ic) if ic else None),
            "icStdev": _r(statistics.stdev(ic) if len(ic) > 1 else None),
            "icDates": len(ic),
            "labelPersistenceAtHorizon": {
                p: _r(statistics.fmean(v), 3) for p, v in sorted(persistence[sig].items())
            },
        }
    return result


def run_history(start: str, end: str | None, horizons: Iterable[int]) -> dict[str, Any]:
    boards = []
    failures = []
    for archive in daily_archives(start, end):
        try:
            boards.append(compact_board(archive))
        except Exception as exc:  # noqa: BLE001 -- a board that will not build is reported
            failures.append({"archive": archive, "error": repr(exc)[:200]})
    summary: dict[str, Any] = {
        "byHorizon": {str(h): evaluate_history(boards, h) for h in sorted(set(horizons))}
    }
    summary["boards"] = [
        {
            k: b[k]
            for k in (
                "archive",
                "date",
                "payloadSha256",
                "treeRevision",
                "treeContentSha256",
                "networkAttemptsRefused",
            )
        }
        | {"pricedRows": len(b["rows"])}
        for b in boards
    ]
    summary["buildFailures"] = failures
    # Per-date TE label census (does the skew persist through time?).
    summary["teCensusByDate"] = [
        {
            "date": b["date"],
            "c0": {
                "sell": sum(
                    1
                    for c in b["rows"].values()
                    if c["eligible"] and c["pos"] == "TE" and c["c0"] >= MIN_RATIO
                ),
                "buy": sum(
                    1
                    for c in b["rows"].values()
                    if c["eligible"] and c["pos"] == "TE" and c["c0"] <= -MIN_RATIO
                ),
            },
            "c1": {
                "sell": sum(
                    1
                    for c in b["rows"].values()
                    if c["eligible"] and c["pos"] == "TE" and c["c1"] >= MIN_RATIO
                ),
                "buy": sum(
                    1
                    for c in b["rows"].values()
                    if c["eligible"] and c["pos"] == "TE" and c["c1"] <= -MIN_RATIO
                ),
            },
        }
        for b in boards
    ]
    return summary


# ── CLI ─────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--archive", default=DEFAULT_ARCHIVE, help="pinned archive (repo-relative)")
    ap.add_argument("--out", type=Path, default=None, help="write the JSON result here")
    ap.add_argument(
        "--no-counterfactuals", action="store_true", help="skip the C2 and leave-KTC-out rebuilds"
    )
    ap.add_argument(
        "--history",
        action="store_true",
        help="also run the point-in-time evaluation over the daily archives",
    )
    ap.add_argument("--history-start", default=HISTORY_START)
    ap.add_argument("--history-end", default=None)
    ap.add_argument(
        "--horizons", type=int, nargs="+", default=[7, 14, 28], help="evaluation horizons in days"
    )
    args = ap.parse_args(argv)

    result: dict[str, Any] = {
        "finding": "W27-F005",
        "activationStatus": "NOT ACTIVATED",
        "codeRevision": git("rev-parse", "HEAD"),
        "pinned": analyse_archive(args.archive, counterfactuals=not args.no_counterfactuals),
    }
    if args.history:
        result["history"] = run_history(args.history_start, args.history_end, args.horizons)
    text = json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False)
    if args.out is not None:
        args.out.write_text(text + "\n", encoding="utf-8")
    else:
        sys.stdout.write(text + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
