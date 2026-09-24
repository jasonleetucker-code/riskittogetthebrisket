"""Source freshness — how current a source's CONTRIBUTION is, relative to its own rhythm.

One owner.  Owner directive 2026-09-23 (``docs/sources/SOURCE_FRESHNESS_WEIGHTING.md``).
Every constant lives in ``config/sources/freshness_v1.json``; this module
contains the rules, not the numbers.

The question answered is NOT "was it downloaded recently?" (that is fetch
freshness, ``scripts/watchdog_freshness.py``) but "how many of this
provider's NORMAL update cycles has the information it is contributing
missed?":

    r         = age / E          (E = the source's expected interval)
    freshness = curve(r)         (1.0 for one full normal interval, then
                                  decays smoothly; < quarantineBelow ⇒ 0)

The same 72 hours is severe for a source that normally changes twice a day
and nothing at all for a weekly one — there is deliberately no universal
absolute grace floor.

Which clock ``age`` is measured on depends on the provider's publication
STYLE, classified from its own change history (never from branding):

* ``SNAPSHOT``   — each change republishes the board: age since the last
  broad dataset change, shared by every row.
* ``BATCH`` / ``INCREMENTAL`` / ``UNKNOWN`` — a row's age is measured from
  ``max(row changed, last broad change)``: a broad batch refreshes the
  board, a 2-row edit refreshes exactly those 2 rows.  ``UNKNOWN`` (too few
  events to classify) takes these conservative clocks and is flagged.
* ``EXPLICIT_UPSTREAM_TIMESTAMP`` — the vendor states when it published;
  that timestamp is the clock (ignored if in the future or older than an
  observed content change).

``E`` is learned from the source's own closed broad-change intervals (p75,
same season phase first), clamped to per-source ``[minHours, maxHours]``.
The currently-open gap is never in the sample and a long closed gap is one
sample capped by ``maxHours``, so an outage cannot teach the system that
"slow is normal".  Subsets with no learnable cadence inherit the player
subset's ``E`` (flagged) before falling back to the configured seed.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from src.sources.dataset_state import SUBSET_PICKS, SUBSET_PLAYERS, parse_iso

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = REPO_ROOT / "config" / "sources" / "freshness_v1.json"

STYLE_SNAPSHOT = "SNAPSHOT"
STYLE_BATCH = "BATCH"
STYLE_INCREMENTAL = "INCREMENTAL"
STYLE_UNKNOWN = "UNKNOWN"
STYLE_EXPLICIT = "EXPLICIT_UPSTREAM_TIMESTAMP"

STATE_ON_SCHEDULE = "ON_SCHEDULE"
STATE_OVERDUE = "OVERDUE"
STATE_STALE = "STALE"
STATE_SEVERELY_STALE = "SEVERELY_STALE"
STATE_QUARANTINED = "QUARANTINED"
STATE_UNMEASURED = "UNMEASURED"

CADENCE_LEARNED_PHASE = "learned_same_phase"
CADENCE_LEARNED_ANY = "learned_any_phase"
CADENCE_INHERITED = "inherited_from_players"
CADENCE_SEED = "configured_seed"


# ── Candidate curves (r = age / E) ───────────────────────────────────────
def _curve_c1(r: float) -> float:
    """Exponential after one interval, half-life one interval."""
    return 1.0 if r <= 1.0 else 2.0 ** (-(r - 1.0))


def _curve_c2(r: float) -> float:
    """Logistic centred at 2.5 intervals, normalised so f(0) = 1."""

    def f(x: float) -> float:
        return 1.0 / (1.0 + math.exp(2.0 * (x - 2.5)))

    return min(1.0, f(r) / f(0.0))


def _curve_c3(r: float) -> float:
    """Half-normal after one interval, sigma 1.2 intervals."""
    return 1.0 if r <= 1.0 else math.exp(-((r - 1.0) ** 2) / (2.0 * 1.2**2))


def _curve_c4(r: float) -> float:
    """Eased exponential: full authority for one normal interval, then
    ``2^(−(r−1)²/r)`` — zero slope at r = 1 (no kink), converging to one
    halving per further missed interval."""
    return 1.0 if r <= 1.0 else 2.0 ** (-((r - 1.0) ** 2) / r)


CURVES = {"C1": _curve_c1, "C2": _curve_c2, "C3": _curve_c3, "C4": _curve_c4}


def freshness_from_ratio(r: float, curve: str = "C4") -> float:
    if r is None or not math.isfinite(r) or r < 0:
        return 1.0
    return float(CURVES[curve](r))


# ── Config ───────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class SourceCadence:
    seed_hours: float
    min_hours: float
    max_hours: float
    style: str | None = None


@dataclass(frozen=True)
class FreshnessConfig:
    version: str
    curve: str
    quarantine_below: float
    fresh_for_confidence: float
    state_bands: tuple[tuple[float, str], ...]
    style_min_events: int
    style_lookback_events: int
    snapshot_broad_share: float
    snapshot_median_changed_fraction: float
    incremental_broad_share: float
    cadence_percentile: float
    cadence_min_intervals: int
    cadence_trailing_days: float
    in_season_months: frozenset[int]
    health_factors: Mapping[str, float]
    coverage_floor_fraction: float
    default_cadence: SourceCadence
    sources: Mapping[str, SourceCadence] = field(default_factory=dict)
    raw: Mapping[str, Any] = field(default_factory=dict)

    def cadence_for(self, key: str) -> SourceCadence:
        return self.sources.get(key, self.default_cadence)


def _cadence(d: Mapping[str, Any], default: SourceCadence | None = None) -> SourceCadence:
    base = default or SourceCadence(72.0, 24.0, 336.0)
    return SourceCadence(
        seed_hours=float(d.get("seedHours", base.seed_hours)),
        min_hours=float(d.get("minHours", base.min_hours)),
        max_hours=float(d.get("maxHours", base.max_hours)),
        style=d.get("style"),
    )


def load_config(path: Path | None = None, *, curve: str | None = None) -> FreshnessConfig:
    data = json.loads(Path(path or CONFIG_PATH).read_text(encoding="utf-8"))
    style = data.get("styleClassification") or {}
    cad = data.get("cadence") or {}
    default = _cadence(data.get("defaultCadence") or {})
    sources = {
        str(k): _cadence(v, default)
        for k, v in (data.get("sources") or {}).items()
        if isinstance(v, Mapping)
    }
    bands = tuple(
        (float(b["minFreshness"]), str(b["state"]))
        for b in sorted(data.get("stateBands") or [], key=lambda b: -float(b["minFreshness"]))
    )
    return FreshnessConfig(
        version=str(data.get("version") or "freshness_v1"),
        curve=str(curve or data.get("curve") or "C4"),
        quarantine_below=float(data.get("quarantineBelow", 0.02)),
        fresh_for_confidence=float(data.get("freshForConfidence", 0.5)),
        state_bands=bands,
        style_min_events=int(style.get("minEvents", 5)),
        style_lookback_events=int(style.get("lookbackEvents", 20)),
        snapshot_broad_share=float(style.get("snapshotBroadShare", 0.8)),
        snapshot_median_changed_fraction=float(style.get("snapshotMedianChangedFraction", 0.25)),
        incremental_broad_share=float(style.get("incrementalBroadShare", 0.2)),
        cadence_percentile=float(cad.get("percentile", 0.75)),
        cadence_min_intervals=int(cad.get("minIntervals", 5)),
        cadence_trailing_days=float(cad.get("trailingDays", 120)),
        in_season_months=frozenset(int(m) for m in cad.get("inSeasonMonths", [9, 10, 11, 12, 1])),
        health_factors={str(k): float(v) for k, v in (data.get("healthFactors") or {}).items()},
        coverage_floor_fraction=float((data.get("coverage") or {}).get("floorFraction", 0.8)),
        default_cadence=default,
        sources=sources,
        raw=data,
    )


_CONFIG_CACHE: dict[str, FreshnessConfig] = {}


def default_config() -> FreshnessConfig:
    cfg = _CONFIG_CACHE.get("default")
    if cfg is None:
        cfg = load_config()
        _CONFIG_CACHE["default"] = cfg
    return cfg


# ── Classification + cadence ─────────────────────────────────────────────
def classify_style(
    history: list[Mapping[str, Any]], cfg: FreshnessConfig, *, override: str | None = None
) -> tuple[str, dict[str, Any]]:
    """Publication style from the subset's own change events."""
    events = [e for e in history if isinstance(e, Mapping)][-cfg.style_lookback_events :]
    evidence: dict[str, Any] = {"events": len(events)}
    if override:
        evidence["override"] = override
        return override, evidence
    if len(events) < cfg.style_min_events:
        return STYLE_UNKNOWN, evidence
    broad_share = sum(1 for e in events if e.get("broad")) / len(events)
    fractions = sorted(
        float(e.get("rowsChanged") or 0) / max(1.0, float(e.get("rowsTotal") or 0)) for e in events
    )
    mid = len(fractions) // 2
    median_fraction = (
        fractions[mid] if len(fractions) % 2 else (fractions[mid - 1] + fractions[mid]) / 2.0
    )
    evidence.update(
        {"broadShare": round(broad_share, 3), "medianChangedFraction": round(median_fraction, 3)}
    )
    if (
        broad_share >= cfg.snapshot_broad_share
        and median_fraction >= cfg.snapshot_median_changed_fraction
    ):
        return STYLE_SNAPSHOT, evidence
    if broad_share <= cfg.incremental_broad_share:
        return STYLE_INCREMENTAL, evidence
    return STYLE_BATCH, evidence


def _is_in_season(dt: datetime, cfg: FreshnessConfig) -> bool:
    return dt.month in cfg.in_season_months


def _percentile(values: list[float], p: float) -> float:
    vals = sorted(values)
    if len(vals) == 1:
        return vals[0]
    k = (len(vals) - 1) * p
    lo, hi = math.floor(k), math.ceil(k)
    if lo == hi:
        return vals[int(k)]
    return vals[lo] + (vals[hi] - vals[lo]) * (k - lo)


def broad_intervals_hours(
    history: list[Mapping[str, Any]], as_of: datetime, cfg: FreshnessConfig
) -> list[tuple[float, datetime]]:
    """Closed intervals between consecutive broad changes, ending ≤ as_of,
    within the trailing window.  The open gap since the last change is
    never included."""
    times = sorted(
        t
        for t in (
            parse_iso(e.get("at")) for e in history if isinstance(e, Mapping) and e.get("broad")
        )
        if t is not None and t <= as_of
    )
    out: list[tuple[float, datetime]] = []
    window_s = cfg.cadence_trailing_days * 86400.0
    for a, b in zip(times, times[1:]):
        if (as_of - b).total_seconds() > window_s:
            continue
        hours = (b - a).total_seconds() / 3600.0
        if hours > 0:
            out.append((hours, b))
    return out


def expected_interval_hours(
    history: list[Mapping[str, Any]],
    as_of: datetime,
    cadence: SourceCadence,
    cfg: FreshnessConfig,
    *,
    inherited: float | None = None,
) -> tuple[float, str, float | None]:
    """``(E_hours, cadenceSource, observedPercentileHours)`` — clamped."""
    intervals = broad_intervals_hours(history, as_of, cfg)
    phase = _is_in_season(as_of, cfg)
    same_phase = [h for h, end in intervals if _is_in_season(end, cfg) == phase]
    observed: float | None = None
    if len(same_phase) >= cfg.cadence_min_intervals:
        observed = _percentile(same_phase, cfg.cadence_percentile)
        source = CADENCE_LEARNED_PHASE
    elif len(intervals) >= cfg.cadence_min_intervals:
        observed = _percentile([h for h, _ in intervals], cfg.cadence_percentile)
        source = CADENCE_LEARNED_ANY
    elif inherited is not None:
        return inherited, CADENCE_INHERITED, None
    else:
        return (
            max(cadence.min_hours, min(cadence.max_hours, cadence.seed_hours)),
            CADENCE_SEED,
            None,
        )
    e = max(cadence.min_hours, min(cadence.max_hours, observed))
    return e, source, observed


# ── Assessment ───────────────────────────────────────────────────────────
@dataclass
class SubsetFreshness:
    source_key: str
    subset: str
    style: str
    style_evidence: dict[str, Any]
    expected_hours: float
    cadence_source: str
    observed_cadence_hours: float | None
    clock: str
    clock_at: datetime | None
    last_any_change_at: datetime | None
    last_broad_change_at: datetime | None
    as_of: datetime
    age_hours: float | None
    freshness: float
    state: str
    row_changed_at: Mapping[str, str] = field(default_factory=dict)
    curve: str = "C4"
    quarantine_below: float = 0.02
    state_bands: tuple[tuple[float, str], ...] = ()

    def row_freshness(self, row_key: str | None) -> tuple[float, float | None]:
        """``(freshness, age_hours)`` for one row.  SNAPSHOT/EXPLICIT styles
        share the source clock; other styles use the row's own clock."""
        if self.clock_at is None:
            return 1.0, None
        clock = self.clock_at
        if self.style not in (STYLE_SNAPSHOT, STYLE_EXPLICIT) and row_key:
            row_at = parse_iso(self.row_changed_at.get(row_key))
            if row_at is not None and row_at > clock:
                clock = row_at
        age = max(0.0, (self.as_of - clock).total_seconds() / 3600.0)
        f = freshness_from_ratio(age / self.expected_hours, self.curve)
        if f < self.quarantine_below:
            f = 0.0
        return f, age

    def to_dict(self) -> dict[str, Any]:
        return {
            "subset": self.subset,
            "publicationStyle": self.style,
            "styleEvidence": self.style_evidence,
            "freshnessClock": self.clock,
            "sourceDataAsOf": _iso(self.clock_at),
            "lastAnyMeaningfulChangeAt": _iso(self.last_any_change_at),
            "lastBroadDatasetChangeAt": _iso(self.last_broad_change_at),
            "ageHours": None if self.age_hours is None else round(self.age_hours, 1),
            "expectedCadenceHours": round(self.expected_hours, 1),
            "cadenceSource": self.cadence_source,
            "observedCadenceHours": None
            if self.observed_cadence_hours is None
            else round(self.observed_cadence_hours, 1),
            "ageOverExpected": None
            if self.age_hours is None
            else round(self.age_hours / self.expected_hours, 2),
            "freshness": round(self.freshness, 4),
            "state": self.state,
        }


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def state_for(freshness: float, cfg: FreshnessConfig) -> str:
    if freshness <= 0.0:
        return STATE_QUARANTINED
    for threshold, name in cfg.state_bands:
        if freshness >= threshold:
            return name
    return STATE_SEVERELY_STALE


def assess_subset(
    source_key: str,
    subset: str,
    subset_state: Mapping[str, Any] | None,
    *,
    as_of: datetime,
    cfg: FreshnessConfig,
    upstream: Mapping[str, Any] | None = None,
    inherited_expected: float | None = None,
) -> SubsetFreshness:
    cadence = cfg.cadence_for(source_key)
    st = subset_state or {}
    history = list(st.get("changeHistory") or [])
    style, evidence = classify_style(history, cfg, override=cadence.style)
    expected, cadence_source, observed = expected_interval_hours(
        history, as_of, cadence, cfg, inherited=inherited_expected
    )
    last_any = parse_iso(st.get("lastAnyMeaningfulChangeAt"))
    last_broad = parse_iso(st.get("lastBroadDatasetChangeAt"))
    row_changed_at: Mapping[str, str] = st.get("rowChangedAt") or {}
    if (last_broad and last_broad > as_of) or (last_any and last_any > as_of):
        # Evaluating a PAST board against today's state: rebuild both clocks
        # from the change history as it stood at ``as_of``.  Per-row clocks
        # cannot be rebuilt (only the latest map is kept), so rows fall back
        # to the source clock — older, never fresher, than the truth.
        first = parse_iso(st.get("firstObservedAt"))
        past = [
            (t, bool(e.get("broad")))
            for e in history
            if isinstance(e, Mapping)
            for t in [parse_iso(e.get("at"))]
            if t is not None and t <= as_of
        ]
        baseline = [first] if first is not None and first <= as_of else []
        broad_times = [t for t, b in past if b] + baseline
        any_times = [t for t, _ in past] + baseline
        last_broad = max(broad_times) if broad_times else None
        last_any = max(any_times) if any_times else None
        row_changed_at = {}
    clock_name = "lastBroadDatasetChangeAt"
    clock_at = last_broad
    if style == STYLE_EXPLICIT:
        # The vendor's own timestamp — but never FRESHER than the content we
        # observed: a cosmetic chart edit moves the vendor's clock without
        # moving the data, so the clock is the earlier of the two.  A genuine
        # republish moves both.
        published = parse_iso((upstream or {}).get("publishedAt"))
        if published is not None and published <= as_of:
            if last_broad is None or published <= last_broad:
                clock_name = "upstreamPublishedAt"
                clock_at = published
    base = SubsetFreshness(
        source_key=source_key,
        subset=subset,
        style=style,
        style_evidence=evidence,
        expected_hours=expected,
        cadence_source=cadence_source,
        observed_cadence_hours=observed,
        clock=clock_name,
        clock_at=clock_at,
        last_any_change_at=last_any,
        last_broad_change_at=last_broad,
        as_of=as_of,
        age_hours=None,
        freshness=1.0,
        state=STATE_UNMEASURED,
        row_changed_at=row_changed_at,
        curve=cfg.curve,
        quarantine_below=cfg.quarantine_below,
        state_bands=cfg.state_bands,
    )
    if clock_at is None:
        return base
    f, age = base.row_freshness(None)
    base.age_hours = age
    base.freshness = f
    base.state = state_for(f, cfg)
    return base


@dataclass
class SourceWeighting:
    """Everything that decides one source's effective weight."""

    source_key: str
    measured: bool
    subsets: dict[str, SubsetFreshness]
    health_state: str | None
    health_factor: float
    coverage: float | None
    coverage_factor: float
    row_count: int | None
    rolling_median_rows: float | None
    health_errors: list[str] = field(default_factory=list)

    def subset_for(self, is_pick: bool) -> SubsetFreshness | None:
        return self.subsets.get(SUBSET_PICKS if is_pick else SUBSET_PLAYERS) or self.subsets.get(
            SUBSET_PLAYERS
        )

    def factor_for_row(self, *, is_pick: bool, row_key: str | None) -> tuple[float, float | None]:
        """``(freshness, age_hours)`` for one contract row."""
        sub = self.subset_for(is_pick)
        if sub is None:
            return 1.0, None
        return sub.row_freshness(row_key)

    def to_dict(self) -> dict[str, Any]:
        return {
            "sourceKey": self.source_key,
            "measured": self.measured,
            "health": self.health_state,
            "healthFactor": self.health_factor,
            "healthErrors": self.health_errors,
            "coverage": None if self.coverage is None else round(self.coverage, 3),
            "coverageFactor": round(self.coverage_factor, 4),
            "rowCount": self.row_count,
            "rollingMedianRows": self.rolling_median_rows,
            "subsets": {k: v.to_dict() for k, v in self.subsets.items()},
        }


def assess_source(
    source_key: str,
    state: Mapping[str, Any] | None,
    *,
    as_of: datetime,
    cfg: FreshnessConfig | None = None,
) -> SourceWeighting:
    cfg = cfg or default_config()
    if not state:
        return SourceWeighting(
            source_key=source_key,
            measured=False,
            subsets={},
            health_state=None,
            health_factor=1.0,
            coverage=None,
            coverage_factor=1.0,
            row_count=None,
            rolling_median_rows=None,
        )
    subsets_state = state.get("subsets") or {}
    upstream = state.get("upstream") or {}
    subsets: dict[str, SubsetFreshness] = {}
    players = assess_subset(
        source_key,
        SUBSET_PLAYERS,
        subsets_state.get(SUBSET_PLAYERS),
        as_of=as_of,
        cfg=cfg,
        upstream=upstream,
    )
    if subsets_state.get(SUBSET_PLAYERS):
        subsets[SUBSET_PLAYERS] = players
    if subsets_state.get(SUBSET_PICKS):
        subsets[SUBSET_PICKS] = assess_subset(
            source_key,
            SUBSET_PICKS,
            subsets_state.get(SUBSET_PICKS),
            as_of=as_of,
            cfg=cfg,
            upstream=upstream,
            inherited_expected=players.expected_hours
            if players.cadence_source != CADENCE_SEED
            else None,
        )

    health = state.get("health") or {}
    health_state = health.get("state")
    health_factor = cfg.health_factors.get(str(health_state), 1.0)

    counts_p = list((subsets_state.get(SUBSET_PLAYERS) or {}).get("rowCountHistory") or [])
    counts_k = list((subsets_state.get(SUBSET_PICKS) or {}).get("rowCountHistory") or [])
    totals = [a + b for a, b in zip(counts_p, counts_k)] if counts_k else counts_p
    row_count = sum(int((subsets_state.get(s) or {}).get("rowCount") or 0) for s in subsets_state)
    vals = sorted(v for v in totals if v > 0)
    median = None
    if vals:
        mid = len(vals) // 2
        median = float(vals[mid]) if len(vals) % 2 else (vals[mid - 1] + vals[mid]) / 2.0
    coverage = (row_count / median) if (median and row_count) else None
    coverage_factor = 1.0
    if coverage is not None:
        coverage_factor = min(1.0, coverage / cfg.coverage_floor_fraction)
    return SourceWeighting(
        source_key=source_key,
        measured=True,
        subsets=subsets,
        health_state=health_state,
        health_factor=health_factor,
        coverage=coverage,
        coverage_factor=coverage_factor,
        row_count=row_count or None,
        rolling_median_rows=median,
        health_errors=list(health.get("errors") or []),
    )


def load_source_weightings(
    source_keys: list[str],
    *,
    state_dir: Path,
    as_of: datetime,
    cfg: FreshnessConfig | None = None,
) -> dict[str, SourceWeighting]:
    from src.sources.dataset_state import load_state, state_path  # noqa: PLC0415

    cfg = cfg or default_config()
    return {
        key: assess_source(key, load_state(state_path(state_dir, key)), as_of=as_of, cfg=cfg)
        for key in source_keys
    }
