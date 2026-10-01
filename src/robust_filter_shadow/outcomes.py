"""Preregistered outcome evaluation for the joint robust filter shadow ledger.

Every definition, constant and the decision rule below is fixed by
``docs/valuation/evidence/joint-filter-shadow-2026-10-01/PREREGISTRATION.md``
(committed before any outcome was computed). If this module and that document
disagree, the document wins and this module is the defect.

Pure functions over ledger records and observation panels; no I/O.
"""

from __future__ import annotations

import math
import random
import statistics
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any

PRIMARY_HORIZON = 7
SECONDARY_HORIZONS = (3, 14, 21)
MIN_GAP = 0.01
BOOTSTRAP_RESAMPLES = 4000
BOOTSTRAP_SEED = 1571
BLOCK_DAYS = 7
MIN_OBS_PER_SIDE = 30
MIN_ORIGIN_DAYS = 10
MIN_BLOCKS = 4
G1_NONINFERIORITY = 0.005
MIN_EFFECT = 0.10
KTC_SPLIT_SOURCES = ("ktcCrowdSfTep", "ktcTradesSfTep")
SIDE_RESCUED = "K"  # incumbent drops, challenger keeps
SIDE_REJECTED = "X"  # incumbent keeps, challenger drops
SIDE_AGREED = "R"  # both drop

VERDICT_ELIGIBLE = "PROMOTION_ELIGIBLE_PENDING_INDEPENDENT_REVIEW"
VERDICT_NOT_BETTER = "NOT_BETTER"
VERDICT_INCONCLUSIVE = "INCONCLUSIVE"
VERDICT_INSUFFICIENT = "INSUFFICIENT"


def family_function(*, merge_ktc: bool = False) -> Callable[[str], str]:
    """B10 correlation group per source; S6 merges KTC Crowd and KTC Trades."""
    from src.api.data_contract import correlation_group_for  # noqa: PLC0415

    def family_of(source: str) -> str:
        group = correlation_group_for(source)
        if merge_ktc and group in ("ktcCrowd", "ktcTrades"):
            return "ktc"
        return group

    return family_of


def leave_family_out(
    observations: Mapping[str, float],
    exclude: Iterable[str],
    family_of: Callable[[str], str],
) -> float | None:
    """Equal-family median (log scale) over families NOT in ``exclude``.

    Each family contributes the median of its members' log votes; the target
    is the median of those family medians, defined only with at least two
    families. Unweighted on purpose (see the preregistration §3).
    """
    excluded = set(exclude)
    by_family: dict[str, list[float]] = defaultdict(list)
    for source, value in observations.items():
        if value is None or value <= 0:
            continue
        family = family_of(source)
        if family in excluded:
            continue
        by_family[family].append(math.log(value))
    if len(by_family) < 2:
        return None
    return statistics.median(statistics.median(v) for v in by_family.values())


def _clip(x: float) -> float:
    return max(-1.0, min(1.0, x))


@dataclass(frozen=True)
class Board:
    """One ledger record joined to its observation panel."""

    record: Mapping[str, Any]
    panel: Mapping[str, Any]
    at: datetime

    @property
    def day(self) -> date:
        return self.at.date()

    @property
    def rows(self) -> Mapping[str, Any]:
        return self.panel.get("rows") or {}

    def votes(self, name: str) -> dict[str, float]:
        row = self.rows.get(name) or {}
        return {s: float(v) for s, v in (row.get("o") or {}).items()}

    @property
    def fingerprint(self) -> str | None:
        return (self.record.get("pins") or {}).get("pipelineFingerprint")

    @property
    def ktc_split_voting(self) -> bool:
        for row in self.rows.values():
            votes = row.get("o") or {}
            if all(s in votes for s in KTC_SPLIT_SOURCES):
                return True
        return False


def parse_time(text: Any) -> datetime | None:
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def daily_boards(boards: Iterable[Board]) -> dict[date, Board]:
    """The last board of each UTC day (the origin/target thinning rule)."""
    by_day: dict[date, Board] = {}
    for board in sorted(boards, key=lambda b: b.at):
        by_day[board.day] = board
    return by_day


def target_day(origin: date, horizon: int, available: Iterable[date]) -> date | None:
    """First available day in ``[origin + h, origin + h + max(1, h // 7)]``."""
    days = set(available)
    late = max(1, horizon // 7)
    for offset in range(horizon, horizon + late + 1):
        candidate = origin + timedelta(days=offset)
        if candidate in days:
            return candidate
    return None


@dataclass
class ObservationOutcome:
    day: date
    block: int
    side: str
    name: str
    source: str
    asset_class: str | None
    m: float
    r: float | None
    delisted: bool

    @property
    def outcome_class(self) -> str:
        if self.m >= 0.5:
            return "LED"
        if self.delisted:
            return "DELISTED"
        if self.r is not None and self.r >= 0.5:
            return "ABANDONED"
        return "UNRESOLVED"


@dataclass
class RowOutcome:
    day: date
    block: int
    name: str
    asset_class: str | None
    g1: float
    g1_persistence: float | None


def _sides(record: Mapping[str, Any]) -> Iterable[tuple[str, str, str, str | None]]:
    """``(side, name, source, asset_class)`` for every judged observation."""
    for row in record.get("rows") or []:
        if not row.get("filterRow"):
            continue
        for obs in row.get("obs") or []:
            inc, ch = obs.get("incumbent"), obs.get("challenger")
            if inc == "drop" and ch == "keep":
                side = SIDE_RESCUED
            elif inc == "keep" and ch == "drop":
                side = SIDE_REJECTED
            elif inc == "drop" and ch == "drop":
                side = SIDE_AGREED
            else:
                continue
            yield side, str(row["name"]), str(obs["source"]), row.get("assetClass")
    for name, source, asset_class in record.get("agreedDrops") or []:
        yield SIDE_AGREED, str(name), str(source), asset_class


def outcomes_at_horizon(
    by_day: Mapping[date, Board],
    horizon: int,
    family_of: Callable[[str], str],
    *,
    first_day: date,
    require_same_fingerprint: bool = True,
) -> dict[str, Any]:
    """Observation and row outcomes for every origin day at ``horizon``."""
    observations: list[ObservationOutcome] = []
    rows: list[RowOutcome] = []
    census: Counter[str] = Counter()
    for day in sorted(by_day):
        origin = by_day[day]
        tday = target_day(day, horizon, by_day)
        if tday is None:
            census["originsWithoutTarget"] += 1
            continue
        target = by_day[tday]
        if require_same_fingerprint and origin.fingerprint != target.fingerprint:
            census["pairsSkippedFingerprint"] += 1
            continue
        census["pairs"] += 1
        block = (day - first_day).days // BLOCK_DAYS
        for side, name, source, asset_class in _sides(origin.record):
            census[f"judged{side}"] += 1
            v0 = origin.votes(name)
            if source not in v0:
                census["sourceNotInPanel"] += 1
                continue
            family = family_of(source)
            c0 = leave_family_out(v0, {family}, family_of)
            c1 = leave_family_out(target.votes(name), {family}, family_of)
            if c0 is None or c1 is None:
                census[f"noTarget{side}"] += 1
                continue
            x = math.log(v0[source])
            gap = x - c0
            if abs(gap) < MIN_GAP:
                census[f"degenerate{side}"] += 1
                continue
            later = target.votes(name).get(source)
            r = None if later is None else _clip((math.log(later) - x) / (c0 - x))
            observations.append(
                ObservationOutcome(
                    day=day,
                    block=block,
                    side=side,
                    name=name,
                    source=source,
                    asset_class=asset_class,
                    m=_clip((c1 - c0) / gap),
                    r=r,
                    delisted=later is None,
                )
            )
        for row in origin.record.get("rows") or []:
            disputed = [
                o for o in row.get("obs") or [] if o.get("incumbent") != o.get("challenger")
            ]
            if not row.get("filterRow") or not disputed:
                continue
            vi, vc = row.get("valueIncumbent"), row.get("valueChallenger")
            if not vi or not vc or vi <= 0 or vc <= 0:
                census["rowsUnpriced"] += 1
                continue
            excluded = {family_of(o["source"]) for o in disputed}
            t1 = leave_family_out(target.votes(row["name"]), excluded, family_of)
            if t1 is None:
                census["rowsNoTarget"] += 1
                continue
            t0 = leave_family_out(origin.votes(row["name"]), excluded, family_of)
            g1 = abs(math.log(vc) - t1) - abs(math.log(vi) - t1)
            g0 = None if t0 is None else abs(math.log(vc) - t0) - abs(math.log(vi) - t0)
            rows.append(
                RowOutcome(
                    day=day,
                    block=block,
                    name=str(row["name"]),
                    asset_class=row.get("assetClass"),
                    g1=g1,
                    g1_persistence=None if g0 is None else g1 - g0,
                )
            )
    return {"observations": observations, "rows": rows, "census": dict(census)}


def _mean(values: Sequence[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _percentile(sorted_values: Sequence[float], q: float) -> float:
    if not sorted_values:
        return float("nan")
    pos = q * (len(sorted_values) - 1)
    lo = math.floor(pos)
    hi = math.ceil(pos)
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (pos - lo)


def block_bootstrap(
    units: Sequence[Any],
    statistic: Callable[[Sequence[Any]], float | None],
    *,
    block_of: Callable[[Any], int],
    resamples: int = BOOTSTRAP_RESAMPLES,
    seed: int = BOOTSTRAP_SEED,
) -> dict[str, Any]:
    """Percentile 95% interval from resampling whole calendar blocks."""
    point = statistic(units)
    by_block: dict[int, list[Any]] = defaultdict(list)
    for unit in units:
        by_block[block_of(unit)].append(unit)
    blocks = sorted(by_block)
    if point is None or not blocks:
        return {"point": point, "lo": None, "hi": None, "blocks": len(blocks), "used": 0}
    rng = random.Random(seed)
    draws: list[float] = []
    for _ in range(resamples):
        sample: list[Any] = []
        for _b in blocks:
            sample.extend(by_block[rng.choice(blocks)])
        value = statistic(sample)
        if value is not None:
            draws.append(value)
    draws.sort()
    return {
        "point": point,
        "lo": _percentile(draws, 0.025) if draws else None,
        "hi": _percentile(draws, 0.975) if draws else None,
        "blocks": len(blocks),
        "used": len(draws),
    }


def _delta(units: Sequence[ObservationOutcome]) -> float | None:
    k = [u.m for u in units if u.side == SIDE_RESCUED]
    x = [u.m for u in units if u.side == SIDE_REJECTED]
    if not k or not x:
        return None
    return sum(k) / len(k) - sum(x) / len(x)


def _side_mean(side: str) -> Callable[[Sequence[ObservationOutcome]], float | None]:
    def stat(units: Sequence[ObservationOutcome]) -> float | None:
        return _mean([u.m for u in units if u.side == side])

    return stat


def _round(value: float | None, digits: int = 4) -> float | None:
    return (
        None
        if value is None or (isinstance(value, float) and math.isnan(value))
        else round(value, digits)
    )


def _ci(result: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "point": _round(result.get("point")),
        "lo95": _round(result.get("lo")),
        "hi95": _round(result.get("hi")),
        "blocks": result.get("blocks"),
        "resamplesUsed": result.get("used"),
    }


def summarize_horizon(result: Mapping[str, Any]) -> dict[str, Any]:
    obs: list[ObservationOutcome] = result["observations"]
    rows: list[RowOutcome] = result["rows"]
    by_side = {
        s: [u for u in obs if u.side == s] for s in (SIDE_RESCUED, SIDE_REJECTED, SIDE_AGREED)
    }
    out: dict[str, Any] = {"census": result["census"], "sides": {}}
    for side, units in by_side.items():
        classes = Counter(u.outcome_class for u in units)
        r_values = [u.r for u in units if u.r is not None]
        out["sides"][side] = {
            "n": len(units),
            "originDays": len({u.day for u in units}),
            "meanLeadShare": _ci(
                block_bootstrap(units, _side_mean(side), block_of=lambda u: u.block)
            ),
            "classes": dict(sorted(classes.items())),
            "meanRetreatShare": _round(_mean(r_values)),
            "delisted": sum(1 for u in units if u.delisted),
        }
    judged = by_side[SIDE_RESCUED] + by_side[SIDE_REJECTED]
    out["delta"] = _ci(block_bootstrap(judged, _delta, block_of=lambda u: u.block))
    out["g1"] = _ci(
        block_bootstrap(rows, lambda us: _mean([u.g1 for u in us]), block_of=lambda u: u.block)
    )
    persistence = [u for u in rows if u.g1_persistence is not None]
    out["g1PersistenceRelative"] = _ci(
        block_bootstrap(
            persistence,
            lambda us: _mean([u.g1_persistence for u in us]),
            block_of=lambda u: u.block,
        )
    )
    out["g1Rows"] = len(rows)
    out["blocks"] = len({u.block for u in judged})
    out["originDays"] = len({u.day for u in judged})
    return out


def decide(
    primary: Mapping[str, Any], secondary: Mapping[int, Mapping[str, Any]]
) -> dict[str, Any]:
    """Apply the preregistered decision rule (§5)."""
    k, x = primary["sides"][SIDE_RESCUED], primary["sides"][SIDE_REJECTED]
    delta, g1 = primary["delta"], primary["g1"]
    minimum = {
        "rescuedObs": k["n"],
        "rejectedObs": x["n"],
        "originDays": primary["originDays"],
        "blocks": primary["blocks"],
    }
    met = (
        k["n"] >= MIN_OBS_PER_SIDE
        and x["n"] >= MIN_OBS_PER_SIDE
        and primary["originDays"] >= MIN_ORIGIN_DAYS
        and primary["blocks"] >= MIN_BLOCKS
    )
    secondary_positive = sum(
        1
        for s in secondary.values()
        if (s["delta"]["point"] or 0) > 0 and s["delta"]["point"] is not None
    )
    reasons: list[str] = []
    if not met or delta["lo95"] is None or g1["hi95"] is None:
        verdict = VERDICT_INSUFFICIENT
        reasons.append("minimum sample not met or interval undefined")
    elif delta["lo95"] > 0 and g1["hi95"] <= G1_NONINFERIORITY and secondary_positive >= 2:
        verdict = VERDICT_ELIGIBLE
    elif delta["hi95"] < 0 or g1["lo95"] > 0:
        verdict = VERDICT_NOT_BETTER
        if delta["hi95"] < 0:
            reasons.append(
                "rescued evidence was led-to LESS than rejected evidence (Δ upper95 < 0)"
            )
        if g1["lo95"] > 0:
            reasons.append(
                "challenger's published values sit further from later consensus (G1 lower95 > 0)"
            )
    else:
        verdict = VERDICT_INCONCLUSIVE
        reasons.append("no detectable advantage; near-ties keep the incumbent")
    accumulation = None
    if verdict in (VERDICT_INCONCLUSIVE, VERDICT_INSUFFICIENT) and delta["lo95"] is not None:
        half = (delta["hi95"] - delta["lo95"]) / 2.0
        blocks = max(1, primary["blocks"])
        needed = math.ceil(blocks * (half / MIN_EFFECT) ** 2) if half > 0 else blocks
        accumulation = {
            "minimumEffectOfInterest": MIN_EFFECT,
            "currentHalfWidth": round(half, 4),
            "currentBlocks": blocks,
            "projectedBlocksForHalfWidth": needed,
            "projectedAdditionalWeeks": max(0, needed - blocks),
            "note": "projection assuming SE ∝ 1/sqrt(blocks); not a promise",
        }
    return {
        "verdict": verdict,
        "reasons": reasons,
        "minimumSample": {**minimum, "met": met},
        "secondaryHorizonsWithPositiveDelta": secondary_positive,
        "accumulation": accumulation,
    }


@dataclass
class EvaluationConfig:
    completeness: tuple[str, ...] = ("complete",)
    merge_ktc: bool = False
    episode_dedupe: bool = False
    asset_class: str | None = None
    ktc_split_only: bool = False
    require_same_fingerprint: bool = True
    horizons: tuple[int, ...] = field(default=(PRIMARY_HORIZON, *SECONDARY_HORIZONS))


def _dedupe_episodes(result: dict[str, Any], origin_days: Sequence[date]) -> dict[str, Any]:
    """S2: keep only the first origin of each consecutive (name, source, side) run."""
    previous = {d: origin_days[i - 1] for i, d in enumerate(origin_days) if i}
    seen: dict[date, set[tuple[str, str, str]]] = defaultdict(set)
    for u in result["observations"]:
        seen[u.day].add((u.name, u.source, u.side))
    kept = [
        u
        for u in result["observations"]
        if (u.name, u.source, u.side) not in seen.get(previous.get(u.day), set())
    ]
    return {**result, "observations": kept}


def evaluate(boards: Sequence[Board], config: EvaluationConfig | None = None) -> dict[str, Any]:
    cfg = config or EvaluationConfig()
    selected = [
        b
        for b in boards
        if (b.record.get("board") or {}).get("completeness", "complete") in cfg.completeness
    ]
    by_day = daily_boards(selected)
    if cfg.ktc_split_only:
        first_split = min((d for d, b in by_day.items() if b.ktc_split_voting), default=None)
        by_day = {d: b for d, b in by_day.items() if first_split and d >= first_split}
    if not by_day:
        return {"boards": len(selected), "originDays": 0, "horizons": {}, "decision": None}
    first = min(by_day)
    family_of = family_function(merge_ktc=cfg.merge_ktc)
    origin_days = sorted(by_day)
    horizons: dict[int, dict[str, Any]] = {}
    for h in cfg.horizons:
        result = outcomes_at_horizon(
            by_day,
            h,
            family_of,
            first_day=first,
            require_same_fingerprint=cfg.require_same_fingerprint,
        )
        if cfg.episode_dedupe:
            result = _dedupe_episodes(result, origin_days)
        if cfg.asset_class:
            result = {
                **result,
                "observations": [
                    u for u in result["observations"] if u.asset_class == cfg.asset_class
                ],
                "rows": [u for u in result["rows"] if u.asset_class == cfg.asset_class],
            }
        horizons[h] = summarize_horizon(result)
    primary = horizons.get(PRIMARY_HORIZON)
    decision = (
        decide(primary, {h: horizons[h] for h in SECONDARY_HORIZONS if h in horizons})
        if primary
        else None
    )
    return {
        "boards": len(selected),
        "originDays": len(by_day),
        "span": [first.isoformat(), max(by_day).isoformat()],
        "horizons": {str(h): v for h, v in horizons.items()},
        "decision": decision,
    }
