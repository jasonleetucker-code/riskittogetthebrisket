"""MD-113 (TE basis) and MD-108 (pick market) -- measured, research-only evidence.

NOT ACTIVATED.  This script reads the current board inputs, rebuilds the contract
in-process (network refused) under named counterfactuals, and writes two evidence
JSON files.  It changes no served value, weight, flag, source registry or config:
every counterfactual is a context manager that restores what it touched, and the only
files written are the ``--out-*`` paths.

Part A (``te``): how many TE rows/votes the ADR-015 base -> TE++ conversion touches,
how large the lift is, what it does to value and rank versus no conversion, the TE
BUY/SELL split under each variant, the TE share of league starter demand (resolved
through ``src/ros/lineup.py``, never a constant) against the TE share of board value.

Part B (``picks``): provider coverage per pick class, the age of each provider's pick
rows, single-provider reliance, the confidence distribution, observed-versus-derived
provenance, and what an explicit staleness withhold of frozen vendor pick rows would
change.

Pure functions (no I/O, no globals) are the testable core; ``main`` is the thin shell.
"""

from __future__ import annotations

import argparse
import contextlib
import copy
import hashlib
import json
import math
import sys
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

OFFENSE = ("QB", "RB", "WR", "TE")
#: The /edge and /rankings label population (rank <= 250) and the 5% value-ratio gate;
#: mirrors of the constants in ``scripts/research/w27_f005_te_skew.py`` (read, never edited).
LABEL_RANK_LIMIT = 250
MIN_RATIO = 0.05
SOURCE_STALENESS_BUDGET_DAYS = 14  # config/source_staleness.json contentStaleness.defaultDays

#: Named TE counterfactuals.  ``None`` means "not passed" (the production default).
TE_VARIANTS: dict[str, dict[str, float | None]] = {
    "incumbent_adr015": {"tep_multiplier": None, "tep_native_multiplier": None},
    "flat_1_15_pre_adr015": {"tep_multiplier": 1.15, "tep_native_multiplier": None},
    "no_non_tep_lift": {"tep_multiplier": 1.0, "tep_native_multiplier": None},
    "no_te_lift_any_source": {"tep_multiplier": 1.0, "tep_native_multiplier": 1.0},
}


# ── small numeric helpers (pure) ────────────────────────────────────────


def _num(x: Any) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def quantile(values: Sequence[float], q: float) -> float | None:
    """Linear-interpolated quantile; ``None`` for an empty input (never 0)."""
    vals = sorted(float(v) for v in values)
    if not vals:
        return None
    if len(vals) == 1:
        return vals[0]
    pos = (len(vals) - 1) * q
    lo = math.floor(pos)
    hi = math.ceil(pos)
    return vals[lo] + (vals[hi] - vals[lo]) * (pos - lo)


def summarize(values: Iterable[float | None]) -> dict[str, Any]:
    vals = [float(v) for v in values if v is not None]
    if not vals:
        return {"n": 0, "min": None, "p10": None, "median": None, "p90": None, "max": None}
    return {
        "n": len(vals),
        "min": round(min(vals), 4),
        "p10": round(quantile(vals, 0.10), 4),
        "median": round(quantile(vals, 0.50), 4),
        "p90": round(quantile(vals, 0.90), 4),
        "max": round(max(vals), 4),
    }


def share_of(parts: Mapping[str, float | None]) -> dict[str, float | None]:
    """Each part's share of the total of the *measured* parts; ``None`` stays ``None``."""
    total = sum(v for v in parts.values() if v is not None)
    return {k: (None if v is None or total <= 0 else round(v / total, 4)) for k, v in parts.items()}


# ── row accessors (pure) ────────────────────────────────────────────────


def row_pos(row: Mapping[str, Any]) -> str:
    return str(row.get("position") or "").strip().upper()


def row_name(row: Mapping[str, Any]) -> str:
    return str(row.get("displayName") or row.get("canonicalName") or "")


def row_value(row: Mapping[str, Any]) -> float | None:
    return _num(row.get("rankDerivedValue"))


def row_rank(row: Mapping[str, Any]) -> int | None:
    r = row.get("canonicalConsensusRank")
    return int(r) if isinstance(r, (int, float)) and not isinstance(r, bool) else None


def is_label_row(row: Mapping[str, Any]) -> bool:
    rank = row_rank(row)
    return (
        row_pos(row) in OFFENSE
        and rank is not None
        and rank <= LABEL_RANK_LIMIT
        and not row.get("quarantined")
    )


# ── Part A pure functions ───────────────────────────────────────────────


def te_vote_census(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Which TE rows/votes the per-vote TE transforms touched, read from the stamps.

    ``tepBoostApplied`` = the non-TEP basis conversion (or its flat fallback);
    ``tepNativeCorrectionApplied`` = the flat 1.10 on TEP-native boards.  KTC TE++
    boards are exempt from both, so they appear only in ``exemptVotes``.
    """
    te_rows = [r for r in rows if row_pos(r) == "TE" and r.get("assetClass") != "pick"]
    converted_rows = native_rows = 0
    converted_votes = native_votes = exempt_votes = 0
    by_source: Counter[str] = Counter()
    lifts: list[float] = []
    for row in te_rows:
        got_conv = got_native = False
        for src, meta in (row.get("sourceRankMeta") or {}).items():
            if not isinstance(meta, dict):
                continue
            if meta.get("tepBoostApplied"):
                converted_votes += 1
                got_conv = True
                by_source[str(src)] += 1
                lift = _num(meta.get("tepMultiplier"))
                if lift is not None:
                    lifts.append(lift)
            elif meta.get("tepNativeCorrectionApplied"):
                native_votes += 1
                got_native = True
            elif str(src).startswith("ktc"):
                exempt_votes += 1
        converted_rows += got_conv
        native_rows += got_native
    return {
        "teRows": len(te_rows),
        "rowsWithConvertedVote": converted_rows,
        "convertedVotes": converted_votes,
        "rowsWithNativeFlatVote": native_rows,
        "nativeFlatVotes": native_votes,
        "ktcExemptVotes": exempt_votes,
        "convertedVotesBySource": dict(sorted(by_source.items())),
        "liftPerVote": summarize(lifts),
    }


def edge_split(
    rows: Sequence[Mapping[str, Any]], min_ratio: float = MIN_RATIO
) -> dict[str, dict[str, int]]:
    """BUY/SELL census from the contract's own ``marketGap*`` stamps, per offense position.

    ``retail_premium`` (market above our model) reads SELL, ``consensus_premium`` BUY;
    below ``min_ratio`` is HOLD; a row with no stamped ratio is ``unmeasured``."""
    out = {p: {"sell": 0, "buy": 0, "hold": 0, "unmeasured": 0} for p in OFFENSE}
    for row in rows:
        if not is_label_row(row):
            continue
        cell = out[row_pos(row)]
        ratio = _num(row.get("marketGapValueRatio"))
        direction = row.get("marketGapDirection")
        if ratio is None or direction not in ("retail_premium", "consensus_premium"):
            cell["unmeasured"] += 1
        elif ratio < min_ratio:
            cell["hold"] += 1
        elif direction == "retail_premium":
            cell["sell"] += 1
        else:
            cell["buy"] += 1
    return out


def diff_boards(
    base: Sequence[Mapping[str, Any]], alt: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    """Value and rank effect of ``alt`` versus ``base``, joined on display name."""
    alt_by = {row_name(r): r for r in alt}
    pct: dict[str, list[float]] = defaultdict(list)
    changed: Counter[str] = Counter()
    te_rank_moves: list[int] = []
    all_rank_moves: list[int] = []
    movers: list[tuple[float, str, float, float, int | None, int | None]] = []
    for row in base:
        other = alt_by.get(row_name(row))
        v0, v1 = row_value(row), row_value(other) if other else None
        if v0 is None or v1 is None or v0 <= 0:
            continue
        pos = "PICK" if row.get("assetClass") == "pick" else row_pos(row)
        if abs(v1 - v0) >= 1:
            changed[pos] += 1
        pct[pos].append((v1 - v0) / v0)
        r0, r1 = row_rank(row), row_rank(other) if other else None
        if r0 is not None and r1 is not None:
            all_rank_moves.append(abs(r1 - r0))
            if pos == "TE":
                te_rank_moves.append(abs(r1 - r0))
        if pos == "TE":
            movers.append(((v1 - v0) / v0, row_name(row), v0, v1, r0, r1))
    movers.sort(key=lambda t: (-abs(t[0]), t[1]))
    return {
        "rowsChangedByPosition": dict(sorted(changed.items())),
        "pctChangeByPosition": {k: summarize(v) for k, v in sorted(pct.items())},
        "rankDisplacementAll": summarize(all_rank_moves),
        "rankDisplacementTE": summarize(te_rank_moves),
        "topTeMovers": [
            {
                "name": n,
                "valueBase": round(v0),
                "valueAlt": round(v1),
                "pct": round(p, 4),
                "rankBase": r0,
                "rankAlt": r1,
            }
            for p, n, v0, v1, r0, r1 in movers[:10]
        ],
    }


def te_rank_bands(rows: Sequence[Mapping[str, Any]], cuts: Sequence[int]) -> dict[str, int]:
    """How many TEs sit inside each overall-rank cutoff."""
    ranks = [row_rank(r) for r in rows if row_pos(r) == "TE" and r.get("assetClass") != "pick"]
    return {f"top{c}": sum(1 for r in ranks if r is not None and r <= c) for c in cuts}


def positional_pool_value(
    rows: Sequence[Mapping[str, Any]], pos: str, pool_size: int
) -> float | None:
    """Sum of ``rankDerivedValue`` of the ``pool_size`` highest-valued rows at ``pos``.

    ``None`` when the position has fewer priced rows than the pool (a short pool is
    unknown, not a smaller number)."""
    vals = sorted(
        (
            v
            for r in rows
            if row_pos(r) == pos and r.get("assetClass") != "pick"
            for v in [row_value(r)]
            if v is not None
        ),
        reverse=True,
    )
    if pool_size <= 0 or len(vals) < pool_size:
        return None
    return float(sum(vals[:pool_size]))


def value_at_positional_rank(rows: Sequence[Mapping[str, Any]], pos: str, n: int) -> float | None:
    """The n-th highest priced value at ``pos`` (1-based); ``None`` if there is none."""
    vals = sorted(
        (
            v
            for r in rows
            if row_pos(r) == pos and r.get("assetClass") != "pick"
            for v in [row_value(r)]
            if v is not None
        ),
        reverse=True,
    )
    return float(vals[n - 1]) if 1 <= n <= len(vals) else None


def demand_vs_value(
    rows: Sequence[Mapping[str, Any]],
    demand: Mapping[str, float],
    team_count: int,
) -> dict[str, Any]:
    """TE (and every offense position) share of lineup demand versus share of board value.

    Pools are ``team_count x demand[pos]`` rounded, per position: the league-wide starter
    pool under the named demand basis.  Shares are over offense positions only."""
    pools = {p: int(round(team_count * float(demand.get(p, 0.0)))) for p in OFFENSE}
    pool_value = {p: positional_pool_value(rows, p, pools[p]) for p in OFFENSE}
    demand_share = share_of({p: float(demand.get(p, 0.0)) for p in OFFENSE})
    return {
        "starterPoolSize": pools,
        "starterPoolValue": {p: None if v is None else round(v) for p, v in pool_value.items()},
        "demandShare": demand_share,
        "starterPoolValueShare": share_of(pool_value),
    }


def label_population_value_share(rows: Sequence[Mapping[str, Any]]) -> dict[str, float | None]:
    """Share of summed board value by offense position over the rank<=250 label population."""
    sums: dict[str, float] = {p: 0.0 for p in OFFENSE}
    for r in rows:
        if is_label_row(r) and (v := row_value(r)) is not None:
            sums[row_pos(r)] += v
    return share_of(sums)


# ── Part B pure functions ───────────────────────────────────────────────


def pick_class(name: str) -> dict[str, Any] | None:
    """(year, round, grade) of a board pick name, via the identity owner; else ``None``."""
    from src.identity.picks import parse_board_pick_name  # noqa: PLC0415

    ref = parse_board_pick_name(name)
    if ref is None:
        return None
    return {
        "year": ref.year,
        "round": ref.round_num,
        "grade": ref.grade,
        "tier": ref.tier,
        "slot": ref.slot,
    }


def is_pick_row(row: Mapping[str, Any]) -> bool:
    return row.get("assetClass") == "pick"


def pick_class_table(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Per (year, grade) counts of evidence state, provenance class and confidence.

    Rows whose name does not parse are counted under ``unparsed`` (never dropped)."""
    cells: dict[str, dict[str, Counter[str]]] = defaultdict(
        lambda: {
            "rows": Counter(),
            "evidenceState": Counter(),
            "provenance": Counter(),
            "confidence": Counter(),
            "votingProviderCount": Counter(),
        }
    )
    unparsed = 0
    for row in rows:
        if not is_pick_row(row):
            continue
        cls = pick_class(row_name(row))
        if cls is None:
            unparsed += 1
            continue
        cell = cells[f"{cls['year']}:{cls['grade']}"]
        cell["rows"]["n"] += 1
        ev = row.get("pickEvidence") or {}
        cell["evidenceState"][str(ev.get("state"))] += 1
        cell["provenance"][str((row.get("pickValueProvenance") or {}).get("class"))] += 1
        cell["confidence"][str(row.get("confidenceBucket"))] += 1
        cell["votingProviderCount"][str(len(ev.get("votingProviders") or []))] += 1
    return {
        "cells": {
            k: {m: dict(sorted(c.items())) for m, c in v.items()} for k, v in sorted(cells.items())
        },
        "unparsed": unparsed,
    }


def provenance_by_confidence(rows: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, int]]:
    """Cross-tab of ``pickValueProvenance.class`` against ``confidenceBucket``."""
    out: dict[str, Counter[str]] = defaultdict(Counter)
    for row in rows:
        if is_pick_row(row):
            out[str((row.get("pickValueProvenance") or {}).get("class"))][
                str(row.get("confidenceBucket"))
            ] += 1
    return {k: dict(sorted(v.items())) for k, v in sorted(out.items())}


def value_basis_counts(rows: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    """``pickEvidence.valueBasis`` counts: what the VALUE rests on, as distinct from which
    providers corroborate it (a tethered slot's value is the rookie's, not a vendor's)."""
    return dict(
        sorted(
            Counter(
                str((r.get("pickEvidence") or {}).get("valueBasis")) for r in rows if is_pick_row(r)
            ).items()
        )
    )


def provider_coverage(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """For each voting provider, the (year, round) classes it priced and the classes
    that rest on exactly that provider alone."""
    per_provider: dict[str, Counter[str]] = defaultdict(Counter)
    sole: dict[str, Counter[str]] = defaultdict(Counter)
    for row in rows:
        if not is_pick_row(row):
            continue
        cls = pick_class(row_name(row))
        if cls is None:
            continue
        key = f"{cls['year']}:r{cls['round']}"
        providers = list((row.get("pickEvidence") or {}).get("votingProviders") or [])
        for p in providers:
            per_provider[p][key] += 1
        if len(providers) == 1:
            sole[providers[0]][key] += 1
    return {
        "pricedRowsByProviderAndClass": {
            p: dict(sorted(c.items())) for p, c in sorted(per_provider.items())
        },
        "soleProviderRowsByClass": {p: dict(sorted(c.items())) for p, c in sorted(sole.items())},
    }


def age_days(as_of_iso: str | None, now_iso: str | None) -> float | None:
    """Whole-precision days between two ISO-8601 UTC stamps; ``None`` if either is missing."""
    from datetime import datetime  # noqa: PLC0415

    if not as_of_iso or not now_iso:
        return None
    try:
        a = datetime.fromisoformat(str(as_of_iso).replace("Z", "+00:00"))
        b = datetime.fromisoformat(str(now_iso).replace("Z", "+00:00"))
    except ValueError:
        return None
    return round((b - a).total_seconds() / 86400.0, 2)


def change_gaps_days(history: Sequence[Mapping[str, Any]], only_broad: bool = True) -> list[float]:
    """Days between consecutive (broad) dataset changes of one subset."""
    stamps = [h["at"] for h in history if h.get("at") and (h.get("broad") or not only_broad)]
    out = []
    for prev, cur in zip(stamps, stamps[1:], strict=False):
        d = age_days(prev, cur)
        if d is not None:
            out.append(d)
    return out


def frozen_providers(
    subsets: Mapping[str, Mapping[str, Any]], now_iso: str, budget_days: float
) -> dict[str, dict[str, Any]]:
    """Providers whose PICK subset's last genuine content change is older than the budget.

    ``subsets`` maps source key -> {"sourceDataAsOf": iso}.  A source with no recorded
    clock is reported ``unknown`` (never fresh, never frozen by guess)."""
    out: dict[str, dict[str, Any]] = {}
    for key, sub in sorted(subsets.items()):
        age = age_days(sub.get("sourceDataAsOf"), now_iso)
        if age is None:
            out[key] = {"ageDays": None, "state": "unknown"}
        else:
            out[key] = {"ageDays": age, "state": "frozen" if age > budget_days else "current"}
    return out


def diff_pick_rows(
    base: Sequence[Mapping[str, Any]], alt: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    """What a counterfactual changed on pick rows: values, evidence state, confidence."""
    alt_by = {row_name(r): r for r in alt if is_pick_row(r)}
    pct: list[float] = []
    changed_value = 0
    state_moves: Counter[str] = Counter()
    conf_moves: Counter[str] = Counter()
    examples: list[dict[str, Any]] = []
    for row in base:
        if not is_pick_row(row):
            continue
        other = alt_by.get(row_name(row))
        if other is None:
            continue
        v0, v1 = row_value(row), row_value(other)
        if v0 is not None and v1 is not None and v0 > 0:
            if abs(v1 - v0) >= 1:
                changed_value += 1
            pct.append((v1 - v0) / v0)
        s0 = str((row.get("pickEvidence") or {}).get("state"))
        s1 = str((other.get("pickEvidence") or {}).get("state"))
        if s0 != s1:
            state_moves[f"{s0}->{s1}"] += 1
        c0, c1 = str(row.get("confidenceBucket")), str(other.get("confidenceBucket"))
        if c0 != c1:
            conf_moves[f"{c0}->{c1}"] += 1
        if v0 is not None and v1 is not None and abs(v1 - v0) >= 1:
            examples.append(
                {
                    "name": row_name(row),
                    "before": round(v0),
                    "after": round(v1),
                    "pct": round((v1 - v0) / v0, 4),
                }
            )
    examples.sort(key=lambda e: (-abs(e["pct"]), e["name"]))
    return {
        "pickRowsCompared": len(pct),
        "pickRowsValueChanged": changed_value,
        "pctChange": summarize(pct),
        "evidenceStateMoves": dict(sorted(state_moves.items())),
        "confidenceMoves": dict(sorted(conf_moves.items())),
        "largestMoves": examples[:8],
    }


def non_pick_collateral(
    base: Sequence[Mapping[str, Any]], alt: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    """Non-pick rows whose value moved (the documented IDP backbone coupling)."""
    alt_by = {row_name(r): r for r in alt if not is_pick_row(r)}
    moved: list[tuple[float, str]] = []
    n = 0
    for row in base:
        if is_pick_row(row):
            continue
        other = alt_by.get(row_name(row))
        v0, v1 = row_value(row), row_value(other) if other else None
        if v0 is None or v1 is None or v0 <= 0:
            continue
        n += 1
        if abs(v1 - v0) >= 1:
            moved.append(((v1 - v0) / v0, row_name(row)))
    return {
        "nonPickRowsCompared": n,
        "nonPickRowsValueChanged": len(moved),
        "maxAbsPct": round(max((abs(p) for p, _ in moved), default=0.0), 4) if moved else None,
    }


# ── builds (impure; network refused, everything restored) ───────────────


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_raw(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def build(
    raw: Mapping[str, Any],
    *,
    tep_multiplier: float | None = None,
    tep_native_multiplier: float | None = None,
    withhold: Callable[[Any, bool], bool] | None = None,
) -> tuple[dict[str, Any], int]:
    """Rebuild the contract in-process; returns (contract, refused network attempts).

    ``withhold(source_weighting, is_pick) -> bool`` is a research-only hook that forces
    the freshness weight to 0 (the existing 'observation withheld' state) for the
    observations it selects.  It patches the class for the duration of the build only."""
    from scripts.research.w27_f005_te_skew import offline_build  # noqa: PLC0415
    from src.api.data_contract import build_api_data_contract  # noqa: PLC0415
    from src.sources import freshness  # noqa: PLC0415

    cls = freshness.SourceWeighting
    original = cls.factor_for_row

    def patched(self: Any, **kwargs: Any) -> tuple[float, float | None]:
        fresh, age = original(self, **kwargs)
        if withhold is not None and withhold(self, bool(kwargs.get("is_pick"))):
            return 0.0, age
        return fresh, age

    with offline_build() as blocked:
        cls.factor_for_row = patched  # type: ignore[method-assign]
        try:
            contract = build_api_data_contract(
                copy.deepcopy(dict(raw)),
                tep_multiplier=tep_multiplier,
                tep_native_multiplier=tep_native_multiplier,
            )
        finally:
            cls.factor_for_row = original  # type: ignore[method-assign]
    return contract, len(blocked)


@contextlib.contextmanager
def _quiet() -> Iterator[None]:
    yield


def league_demand(league_key: str) -> dict[str, Any]:
    """Lineup demand for one registry league through the canonical resolver."""
    from src.api.league_registry import get_league_by_key  # noqa: PLC0415
    from src.ros.lineup import resolve_league_slot_demand  # noqa: PLC0415

    cfg = get_league_by_key(league_key)
    if cfg is None or not cfg.roster_settings:
        return {"leagueKey": league_key, "resolved": False}
    ld = resolve_league_slot_demand(roster_settings=cfg.roster_settings)
    if not ld.resolved:
        return {"leagueKey": league_key, "resolved": False}
    return {
        "leagueKey": league_key,
        "resolved": True,
        "teamCount": int(cfg.roster_settings.get("teamCount") or 0),
        "source": ld.source,
        "slots": list(ld.slots),
        "bases": {b: ld.by_basis(b) for b in ("dedicated", "even_split", "flex_priority")},
    }


# ── Part A driver ───────────────────────────────────────────────────────


def run_te(raw: Mapping[str, Any]) -> dict[str, Any]:
    boards: dict[str, list[dict[str, Any]]] = {}
    refused = 0
    for name, kw in TE_VARIANTS.items():
        contract, blocked = build(raw, **kw)  # type: ignore[arg-type]
        boards[name] = contract["playersArray"]
        refused += blocked
    base = boards["incumbent_adr015"]
    out: dict[str, Any] = {
        "variants": {k: dict(v) for k, v in TE_VARIANTS.items()},
        "networkAttemptsRefused": refused,
        "voteCensusIncumbent": te_vote_census(base),
        "voteCensusFlat115": te_vote_census(boards["flat_1_15_pre_adr015"]),
        "rankBands": {k: te_rank_bands(v, (50, 100, 250)) for k, v in boards.items()},
        "labelPopulationValueShare": {
            k: label_population_value_share(v) for k, v in boards.items()
        },
        "edgeSplit": {k: edge_split(v) for k, v in boards.items()},
        "incumbentVersus": {
            k: diff_boards(base, v) for k, v in boards.items() if k != "incumbent_adr015"
        },
        "replacementLevelValue": {},
        "demand": {},
    }
    leagues = {}
    for key in ("dynasty_main", "dynasty_new"):
        d = league_demand(key)
        leagues[key] = d
        out["demand"][key] = d
    for key, d in leagues.items():
        if not d.get("resolved"):
            continue
        tc = d["teamCount"]
        out.setdefault("demandVsValue", {})[key] = {
            basis: {variant: demand_vs_value(rows, dem, tc) for variant, rows in boards.items()}
            for basis, dem in d["bases"].items()
        }
        # Value at each position's own replacement rank (teamCount x dedicated slots),
        # for the incumbent and the no-lift board: a scarcity reference, not a premium.
        ded = d["bases"]["dedicated"]
        out["replacementLevelValue"][key] = {
            variant: {
                p: {
                    "rank": int(round(tc * float(ded.get(p, 0.0)))),
                    "value": value_at_positional_rank(
                        boards[variant], p, int(round(tc * float(ded.get(p, 0.0))))
                    ),
                }
                for p in OFFENSE
            }
            for variant in ("incumbent_adr015", "no_te_lift_any_source")
        }
    return out


# ── Part B driver ───────────────────────────────────────────────────────


def pick_subsets_from_contract(contract: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Picks-subset clock per source key, from the contract's own ``sourceWeighting``."""
    out: dict[str, dict[str, Any]] = {}
    for key, sw in ((contract.get("sourceWeighting") or {}).get("sources") or {}).items():
        sub = ((sw or {}).get("subsets") or {}).get("picks")
        if isinstance(sub, dict):
            out[key] = {
                "sourceDataAsOf": sub.get("sourceDataAsOf"),
                "ageHours": sub.get("ageHours"),
                "freshness": sub.get("freshness"),
                "state": sub.get("state"),
                "publicationStyle": sub.get("publicationStyle"),
                "expectedCadenceHours": sub.get("expectedCadenceHours"),
            }
    return out


def read_change_history(state_dir: Path, key: str) -> list[dict[str, Any]]:
    path = state_dir / f"{key}_dataset.json"
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return list(((data.get("subsets") or {}).get("picks") or {}).get("changeHistory") or [])


def run_picks(raw: Mapping[str, Any], state_dir: Path) -> dict[str, Any]:
    contract, refused = build(raw)
    rows = contract["playersArray"]
    picks = [r for r in rows if is_pick_row(r)]
    now_iso = str(contract.get("generatedAt") or raw.get("scrapeTimestamp") or "")
    subsets = pick_subsets_from_contract(contract)
    vendor_keys = ("idpTradeCalc", "ktcCrowdSfTep", "ktcTradesSfTep")
    frozen = frozen_providers(
        {k: subsets[k] for k in vendor_keys if k in subsets}, now_iso, SOURCE_STALENESS_BUDGET_DAYS
    )
    # Counterfactual: withhold, explicitly, every provider whose pick subset is frozen.
    frozen_keys = {k for k, v in frozen.items() if v["state"] == "frozen"}
    alt_contract, refused2 = build(
        raw, withhold=lambda sw, is_pick: is_pick and sw.source_key in frozen_keys
    )
    alt_rows = alt_contract["playersArray"]
    withheld_rows = sum(1 for r in alt_rows if is_pick_row(r) and r.get("freshnessExcludedSources"))
    return {
        "networkAttemptsRefused": refused + refused2,
        "contractGeneratedAt": contract.get("generatedAt"),
        "boardDate": raw.get("date"),
        "pickRows": len(picks),
        "provenanceCounts": dict(
            sorted(
                Counter(
                    str((r.get("pickValueProvenance") or {}).get("class")) for r in picks
                ).items()
            )
        ),
        "evidenceStateCounts": dict(
            sorted(Counter(str((r.get("pickEvidence") or {}).get("state")) for r in picks).items())
        ),
        "confidenceCounts": dict(
            sorted(Counter(str(r.get("confidenceBucket")) for r in picks).items())
        ),
        "classTable": pick_class_table(rows),
        "provenanceByConfidence": provenance_by_confidence(rows),
        "valueBasisCounts": value_basis_counts(rows),
        "providerCoverage": provider_coverage(rows),
        "providerPickClocks": subsets,
        "frozenProviders": frozen,
        "budgetDays": SOURCE_STALENESS_BUDGET_DAYS,
        "pickChangeGapsDays": {
            k: change_gaps_days(read_change_history(state_dir, k))
            for k in ("idpTradeCalc", "ktcCrowdSfTep", "ktcTradesSfTep")
        },
        "pickChangeCounts": {
            k: len(read_change_history(state_dir, k))
            for k in ("idpTradeCalc", "ktcCrowdSfTep", "ktcTradesSfTep")
        },
        "withholdCounterfactual": {
            "withheldProviders": sorted(frozen_keys),
            "pickRowsWithAWithheldVote": withheld_rows,
            "pickEffect": diff_pick_rows(rows, alt_rows),
            "collateralOnNonPickRows": non_pick_collateral(rows, alt_rows),
        },
    }


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("part", choices=("te", "picks"))
    ap.add_argument("--raw", default=str(REPO / "exports/latest/dynasty_data_2026-11-13.json"))
    ap.add_argument("--state-dir", default=str(REPO / "data/scrape_state"))
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    raw_path = Path(args.raw)
    raw = load_raw(raw_path)
    inputs = {
        "rawPayload": raw_path.relative_to(REPO).as_posix()
        if raw_path.is_relative_to(REPO)
        else str(raw_path),
        "rawPayloadSha256": sha256_file(raw_path),
        "boardDate": raw.get("date"),
        "scrapeTimestamp": raw.get("scrapeTimestamp"),
    }
    body = run_te(raw) if args.part == "te" else run_picks(raw, Path(args.state_dir))
    out = {"inputs": inputs, "result": body}
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
