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

Schedule v2 — the owner's step schedule (owner directive 2026-10-19,
``docs/sources/UNIVERSAL_FRESHNESS_SCHEDULE_2026-10-19.md``; flag
``source_freshness_schedule_v2``, DEFAULT OFF — implementation and
percentages owner-approved, activation HELD for the owner (owner decision
2026-10-20 on PR #1831, Option B); off is everything above byte for byte).  Every dynasty ranking source's freshness becomes a
step function of WHOLE DAYS since its last GENUINE publisher update::

    days      = floor((asOf - clock) / 24 h)      (UTC instants)
    freshness = 1.00 (0-7) | 0.75 (8-14) | 0.50 (15-21) | 0.25 (22-30) | 0 (>30)

Numbers in ``config/sources/freshness_schedule_v2.json``.  The clock rules
are the v1 rules with two changes, both about what counts as evidence:

* a vendor-stated publication time (``upstream.publishedAt``) is the clock
  for EVERY source whose fetcher records one — not only those declared
  ``EXPLICIT_UPSTREAM_TIMESTAMP`` — still never later than the last content
  change we observed (a cosmetic vendor edit moves the vendor's stamp, not
  the data);
* an update time we cannot establish for a source we ARE tracking is NEVER
  fresh: when the only clock is the first-observation baseline (a fetch
  time; the content was published at some unknown time at or before it) the
  vote is ``unknownUpdateTimeFreshness`` (0), with ``clockBasis: unknown``.

A board that predates every observation we hold for a source (a historical
replay from before its tracking began), or a source with no recorded state
at all, has NO freshness measurement: it keeps the long-standing unmeasured
posture (base weight, ``UNMEASURED``, ``clockBasis:
not_tracked_at_board_time``) exactly as under v1 and as a board with no
dataset-state directory does.  Zeroing it would retroactively strip every
source from every replay older than its tracking — a measurement gap read as
evidence about the source.

A successful re-download of unchanged content moves no clock
(``dataset_state.observe``), so it can never reset the schedule.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from collections import Counter

from src.sources.dataset_state import DEFAULT_POLICY, SUBSET_PICKS, SUBSET_PLAYERS, parse_iso

#: A subset spans several asset universes (offense and IDP players on one board)
#: only when each universe has at least this many tracked rows.
UNIVERSE_MIN_ROWS = 5

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

#: Which freshness rule a weighting was computed under.
SCHEDULE_V1 = "v1_cadence_curve"
SCHEDULE_V2 = "v2_step_schedule"
SCHEDULE_CONFIG_PATH = REPO_ROOT / "config" / "sources" / "freshness_schedule_v2.json"

#: What a freshness clock rests on (``clockBasis``; schedule v2).
CLOCK_BASIS_PUBLISHER = "publisher_timestamp"
CLOCK_BASIS_CONTENT = "content_change_observed"
CLOCK_BASIS_UNKNOWN = "unknown"
#: The board predates every observation the dataset state holds for this
#: source (or no state exists): the freshness record does not reach the
#: board's time, so there is no measurement to apply — the long-standing
#: replay posture (base weight, ``UNMEASURED``), stated, never a clock.
CLOCK_BASIS_NOT_TRACKED = "not_tracked_at_board_time"

SECONDS_PER_DAY = 86400.0


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


# ── Schedule v2: the owner's step schedule ───────────────────────────────
def whole_days_elapsed(clock: datetime, as_of: datetime) -> int:
    """Whole 24-hour periods from ``clock`` to ``as_of`` (UTC instants).

    ``floor(seconds / 86400)``, so 7 d 23 h 59 m is day 7 and exactly 8 x 24 h
    is day 8.  Time-zone and calendar independent.  A clock later than the
    board's own time is day 0, never negative.
    """
    seconds = (as_of - clock).total_seconds()
    if seconds <= 0:
        return 0
    return int(math.floor(seconds / SECONDS_PER_DAY))


@dataclass(frozen=True)
class StepSchedule:
    """``(maxDays, freshness)`` steps, inclusive upper bounds, ascending."""

    version: str
    steps: tuple[tuple[int, float], ...]
    beyond: float
    unknown: float
    exempt_keys: frozenset[str] = frozenset()

    def freshness_for_days(self, days: int) -> float:
        for max_days, freshness in self.steps:
            if days <= max_days:
                return freshness
        return self.beyond

    @property
    def max_days(self) -> int:
        return self.steps[-1][0] if self.steps else -1

    def describe(self) -> str:
        parts = []
        lo = 0
        for max_days, freshness in self.steps:
            parts.append(f"{lo}-{max_days}d {freshness:g}")
            lo = max_days + 1
        parts.append(f">{self.max_days}d {self.beyond:g}")
        return ", ".join(parts)


class StepScheduleError(ValueError):
    """The v2 schedule file is malformed (fails loudly, never a silent default)."""


def load_step_schedule(path: Path | None = None) -> StepSchedule:
    data = json.loads(Path(path or SCHEDULE_CONFIG_PATH).read_text(encoding="utf-8"))
    raw_steps = data.get("schedule")
    if not isinstance(raw_steps, list) or not raw_steps:
        raise StepScheduleError("freshness schedule v2: 'schedule' must be a non-empty list")
    steps: list[tuple[int, float]] = []
    for item in raw_steps:
        max_days = int(item["maxDays"])
        freshness = float(item["freshness"])
        if not 0.0 <= freshness <= 1.0:
            raise StepScheduleError(f"freshness schedule v2: freshness {freshness} not in [0, 1]")
        if steps and (max_days <= steps[-1][0] or freshness > steps[-1][1]):
            raise StepScheduleError(
                "freshness schedule v2: steps must have ascending maxDays and "
                "non-increasing freshness"
            )
        steps.append((max_days, freshness))
    beyond = float(data.get("beyondMaxFreshness", 0.0))
    unknown = float(data.get("unknownUpdateTimeFreshness", 0.0))
    if beyond > steps[-1][1] or not 0.0 <= beyond <= 1.0 or not 0.0 <= unknown <= 1.0:
        raise StepScheduleError("freshness schedule v2: beyond/unknown freshness out of range")
    return StepSchedule(
        version=str(data.get("version") or "freshness_schedule_v2"),
        steps=tuple(steps),
        beyond=beyond,
        unknown=unknown,
        exempt_keys=frozenset(str(k) for k in (data.get("exemptKeys") or {})),
    )


_SCHEDULE_CACHE: dict[str, StepSchedule] = {}


def default_step_schedule() -> StepSchedule:
    sched = _SCHEDULE_CACHE.get("default")
    if sched is None:
        sched = load_step_schedule()
        _SCHEDULE_CACHE["default"] = sched
    return sched


def active_schedule() -> str:
    """The freshness rule in force: the v1 cadence curve unless the
    ``source_freshness_schedule_v2`` flag is on (default OFF; activation is
    held for the owner — owner decision 2026-10-20, PR #1831 Option B).

    The board reads the flag itself (``data_contract._source_weighting_resolution``,
    where it is part of the memo key); diagnostics that compute weightings
    outside a board build (the source-weighting report, the inventory, the
    advisory source-health check) call this so they cannot disagree with the
    board.  Explicit callers that pin a rule (training-run receipts, the
    robust-filter shadow harness) keep passing their own."""
    from src.api.feature_flags import is_enabled  # noqa: PLC0415

    return SCHEDULE_V2 if is_enabled("source_freshness_schedule_v2") else SCHEDULE_V1


def weighting_descriptor(schedule: str, cfg: "FreshnessConfig | None" = None) -> dict[str, str]:
    """``configVersion`` / ``curve`` / ``formula`` for the board-level stamp.

    Under v1 exactly the strings the summary has always carried, so a
    rollback is byte-identical."""
    if schedule == SCHEDULE_V2:
        sched = default_step_schedule()
        return {
            "configVersion": sched.version,
            "curve": "STEP_V2",
            "formula": (
                "effective = base x freshness(whole days since last genuine update: "
                f"{sched.describe()}) x health x coverage"
            ),
        }
    cfg = cfg or default_config()
    return {
        "configVersion": cfg.version,
        "curve": cfg.curve,
        "formula": "effective = base x freshness(age / expectedCadence) x health x coverage",
    }


# ── Config ───────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class SourceCadence:
    seed_hours: float
    min_hours: float
    max_hours: float
    style: str | None = None
    # The ``styleFlag`` that WITHDREW this source's configured publication
    # style (the flag is off), else ``None``.  A withdrawn
    # ``EXPLICIT_UPSTREAM_TIMESTAMP`` is a per-source rollback of the
    # publisher clock, which :func:`publisher_clock_style` honours under every
    # freshness schedule.
    style_withheld_by: str | None = None


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


def style_flag_states() -> tuple[tuple[str, bool], ...]:
    """Every flag a configured ``styleFlag`` may name, with its state.

    A source's declared publication ``style`` can sit behind its own rollback
    flag (``"styleFlag"`` beside ``"style"`` in ``freshness_v1.json``):
    ``fantasyProsIdp``'s ``EXPLICIT_UPSTREAM_TIMESTAMP`` (owner closeout
    2026-10-18 Decision 5) is in force only while
    ``fantasypros_idp_upstream_clock`` is on.  Each flag is read by LITERAL
    name so the flag-reachability scan sees the gate.  Part of every cache
    key that holds a parsed config, so a flag flip is never served stale.
    """
    from src.api.feature_flags import is_enabled  # noqa: PLC0415

    return (("fantasypros_idp_upstream_clock", is_enabled("fantasypros_idp_upstream_clock")),)


def _cadence(
    d: Mapping[str, Any],
    default: SourceCadence | None = None,
    flags: Mapping[str, bool] | None = None,
) -> SourceCadence:
    base = default or SourceCadence(72.0, 24.0, 336.0)
    style = d.get("style")
    flag = d.get("styleFlag")
    withheld_by: str | None = None
    if style and flag:
        states = dict(flags if flags is not None else style_flag_states())
        if str(flag) not in states:
            raise ValueError(f"freshness config names an unknown styleFlag: {flag!r}")
        if not states[str(flag)]:
            style = None
            withheld_by = str(flag)
    return SourceCadence(
        seed_hours=float(d.get("seedHours", base.seed_hours)),
        min_hours=float(d.get("minHours", base.min_hours)),
        max_hours=float(d.get("maxHours", base.max_hours)),
        style=style,
        style_withheld_by=withheld_by,
    )


def load_config(path: Path | None = None, *, curve: str | None = None) -> FreshnessConfig:
    data = json.loads(Path(path or CONFIG_PATH).read_text(encoding="utf-8"))
    style = data.get("styleClassification") or {}
    cad = data.get("cadence") or {}
    flags = dict(style_flag_states())
    default = _cadence(data.get("defaultCadence") or {}, flags=flags)
    sources = {
        str(k): _cadence(v, default, flags)
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
    # Keyed by the style-flag states too: a flag flip must not be served from
    # a config parsed under the other state.  ``"default"`` is kept as the
    # plain key while every style flag is in its default state, so callers
    # that substitute a variant config under it keep working.
    states = style_flag_states()
    key = "default" if all(on for _f, on in states) else f"default:{states!r}"
    cfg = _CONFIG_CACHE.get(key)
    if cfg is None:
        cfg = load_config()
        _CONFIG_CACHE[key] = cfg
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
    # The clock is the FIRST OBSERVATION of the board (a fetch time), not a
    # dataset change: the content was published at or before it, so the age
    # measured from it is only a LOWER bound.  See :func:`assess_subset`.
    clock_is_baseline: bool = False
    # Schedule v2 (owner directive 2026-10-19).  ``schedule`` is SCHEDULE_V1
    # unless the weighting was computed under the step schedule; every v2
    # field below is inert under v1.
    schedule: str = SCHEDULE_V1
    step: StepSchedule | None = None
    clock_basis: str | None = None
    # The first-observation baseline instant (a fetch time), when the subset
    # still declares one: a row whose clock IS this instant has an unknown
    # genuine-update time.
    baseline_at: datetime | None = None
    # universe -> clock, computed once per build for one key->universe map
    # (the map is fixed within a build; ~7,700 row lookups would otherwise each
    # re-parse every row clock).
    _universe_cache: dict = field(default_factory=dict, repr=False, compare=False)

    def universe_clock(self, universe: str, key_universe: Mapping[str, str]) -> datetime | None:
        """The latest broad change WITHIN one asset universe of this subset.

        A board that prices offense and IDP players together (IDP Trade
        Calculator) can publish an IDP-only update large enough to count as a
        broad change for the whole board. Offense rows that did not move gain
        nothing from it: their universe's clock is the latest time at which at
        least the broad-change threshold of THAT universe's rows last changed
        together, read from the per-row clocks the state already keeps.

        ``None`` when the subset does not genuinely span universes (fewer than
        two universes with ``UNIVERSE_MIN_ROWS`` tracked rows), when per-row
        clocks are not kept, or when the style's clock is the vendor's own
        timestamp -- callers then keep the source clock.
        """
        if self.style == STYLE_EXPLICIT or not self.row_changed_at:
            return None
        # Identity (``is``) of the held map, never ``id()``: a freed map's id can
        # be reused by a later build's map.
        if self._universe_cache.get("_map") is not key_universe:
            self._universe_cache.clear()
            self._universe_cache["_map"] = key_universe
            self._universe_cache["_clocks"] = self._universe_clocks(key_universe)
        return self._universe_cache["_clocks"].get(universe)

    def _universe_clocks(self, key_universe: Mapping[str, str]) -> dict[str, datetime | None]:
        per_universe: dict[str, list[datetime]] = {}
        for key, at in self.row_changed_at.items():
            u = key_universe.get(key)
            t = parse_iso(at)
            if u is not None and t is not None:
                per_universe.setdefault(u, []).append(t)
        populated = [u for u, ts in per_universe.items() if len(ts) >= UNIVERSE_MIN_ROWS]
        if len(populated) < 2:
            return {}
        clocks: dict[str, datetime | None] = {}
        for u, times in per_universe.items():
            counts = Counter(times)
            need = max(
                DEFAULT_POLICY.min_rows, int(round(DEFAULT_POLICY.min_fraction * len(times)))
            )
            qualifying = [t for t, n in counts.items() if n >= need]
            clocks[u] = max(qualifying) if qualifying else None
        return clocks

    def row_freshness(
        self, row_key: str | None, *, clock_cap: datetime | None = None
    ) -> tuple[float, float | None]:
        """``(freshness, age_hours)`` for one row.  SNAPSHOT/EXPLICIT styles
        share the source clock; other styles use the row's own clock.

        ``clock_cap`` (a universe clock) can only make the source clock OLDER:
        the effective clock is ``min(source clock, cap)``, so this correction
        never credits a row with fresher evidence than the whole board had."""
        if self.schedule == SCHEDULE_V2:
            return self._row_freshness_v2(row_key, clock_cap=clock_cap)
        if self.clock_at is None:
            return 1.0, None
        clock = self._row_clock(row_key, clock_cap)
        age = max(0.0, (self.as_of - clock).total_seconds() / 3600.0)
        f = freshness_from_ratio(age / self.expected_hours, self.curve)
        if f < self.quarantine_below:
            f = 0.0
        return f, age

    def _row_clock(self, row_key: str | None, clock_cap: datetime | None) -> datetime:
        clock = self.clock_at
        assert clock is not None
        if clock_cap is not None and clock_cap < clock:
            clock = clock_cap
        if self.style not in (STYLE_SNAPSHOT, STYLE_EXPLICIT) and row_key:
            row_at = parse_iso(self.row_changed_at.get(row_key))
            if row_at is not None and row_at > clock:
                clock = row_at
        return clock

    def row_clock_known(self, clock: datetime) -> bool:
        """Is ``clock`` evidence of a genuine update (schedule v2)?

        A vendor-stated publication time is.  An observed content change is.
        The first-observation baseline is NOT: it is the time we first
        fetched the board, and the content was published at some unknown
        time at or before it."""
        if self.clock_basis == CLOCK_BASIS_PUBLISHER:
            return True
        return self.baseline_at is None or clock != self.baseline_at

    def _row_freshness_v2(
        self, row_key: str | None, *, clock_cap: datetime | None
    ) -> tuple[float, float | None]:
        step = self.step or default_step_schedule()
        if self.clock_at is None:
            # Not tracked at the board's time: no measurement to apply.
            return 1.0, None
        clock = self._row_clock(row_key, clock_cap)
        age = max(0.0, (self.as_of - clock).total_seconds() / 3600.0)
        if not self.row_clock_known(clock):
            return step.unknown, age
        return step.freshness_for_days(whole_days_elapsed(clock, self.as_of)), age

    def to_dict(self) -> dict[str, Any]:
        baseline = self.clock_is_baseline

        def _change(dt: datetime | None) -> str | None:
            # A data clock that IS the first-observation baseline is a fetch
            # time, not a dataset change, and is not published as one.
            if baseline and dt is not None and dt == self.clock_at:
                return None
            return _iso(dt)

        return {
            "subset": self.subset,
            "publicationStyle": self.style,
            "styleEvidence": self.style_evidence,
            "freshnessClock": self.clock,
            # Never a fetch time presented as the data's as-of (D1).
            "sourceDataAsOf": None if baseline else _iso(self.clock_at),
            "clockIsObservationBaseline": baseline,
            "observationBaselineAt": _iso(self.clock_at) if baseline else None,
            "ageIsLowerBound": baseline,
            "lastAnyMeaningfulChangeAt": _change(self.last_any_change_at),
            "lastBroadDatasetChangeAt": _change(self.last_broad_change_at),
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
            **(self._schedule_v2_fields() if self.schedule == SCHEDULE_V2 else {}),
        }

    def genuine_update_at(self) -> datetime | None:
        """The board-level genuine-update clock (schedule v2), or ``None``
        when it cannot be established."""
        if self.clock_at is None or self.clock_basis in (
            CLOCK_BASIS_UNKNOWN,
            CLOCK_BASIS_NOT_TRACKED,
        ):
            return None
        return self.clock_at

    def _schedule_v2_fields(self) -> dict[str, Any]:
        """Additive v2 fields (absent under v1, so a rollback is byte-identical)."""
        genuine = self.genuine_update_at()
        days = None if genuine is None else whole_days_elapsed(genuine, self.as_of)
        row_level = self.style not in (STYLE_SNAPSHOT, STYLE_EXPLICIT) and bool(self.row_changed_at)
        return {
            "freshnessSchedule": SCHEDULE_V2,
            "clockBasis": self.clock_basis,
            "lastGenuineUpdateAt": _iso(genuine),
            "daysSinceGenuineUpdate": days,
            "freshnessPct": None
            if self.clock_basis == CLOCK_BASIS_NOT_TRACKED
            else round(self.freshness * 100.0, 1),
            # BATCH / INCREMENTAL boards age each row from its own last
            # change when that is newer than the board clock, so a row the
            # vendor revised after the last broad publication can vote at a
            # higher step than the board-level figure above.
            "rowLevelClock": row_level,
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


def publisher_clock_style(
    style: str,
    evidence: dict[str, Any],
    cadence: SourceCadence,
    upstream: Mapping[str, Any] | None,
    *,
    as_of: datetime,
    schedule: str,
) -> tuple[str, dict[str, Any]]:
    """THE one owner of "does this source age from its publisher's clock".

    Returns the (style, evidence) :func:`assess_subset` uses; the clock rule
    itself (the vendor's ``upstream.publishedAt``, never later than the last
    observed content change) is applied there, once, for every schedule.

    * **v1 cadence curve** — only a source whose config DECLARES
      ``EXPLICIT_UPSTREAM_TIMESTAMP`` (``classify_style``'s override; e.g.
      ``fantasyProsIdp`` under ``fantasypros_idp_upstream_clock``, owner
      closeout 2026-10-18 Decision 5).
    * **v2 step schedule** (owner directive 2026-10-19 §2) — additionally
      EVERY source whose fetcher records a vendor publication time at or
      before the board, generalising the per-source declaration rather than
      duplicating it.  A source whose declared publisher clock was withdrawn
      by its own ``styleFlag`` (``cadence.style_withheld_by``) is NOT
      re-promoted: a per-source rollback lever is never bypassed by another
      flag.
    """
    if schedule != SCHEDULE_V2 or style == STYLE_EXPLICIT:
        return style, evidence
    if cadence.style_withheld_by is not None:
        return style, {**evidence, "publisherClockWithheldBy": cadence.style_withheld_by}
    vendor_published = parse_iso((upstream or {}).get("publishedAt"))
    if vendor_published is None or vendor_published > as_of:
        return style, evidence
    return STYLE_EXPLICIT, {**evidence, "explicitFromRecordedUpstream": True}


def assess_subset(
    source_key: str,
    subset: str,
    subset_state: Mapping[str, Any] | None,
    *,
    as_of: datetime,
    cfg: FreshnessConfig,
    upstream: Mapping[str, Any] | None = None,
    inherited_expected: float | None = None,
    schedule: str = SCHEDULE_V1,
    step: StepSchedule | None = None,
) -> SubsetFreshness:
    cadence = cfg.cadence_for(source_key)
    st = subset_state or {}
    history = list(st.get("changeHistory") or [])
    style, evidence = classify_style(history, cfg, override=cadence.style)
    v2 = schedule == SCHEDULE_V2
    style, evidence = publisher_clock_style(
        style, evidence, cadence, upstream, as_of=as_of, schedule=schedule
    )
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
        # to the source clock — older than the truth, EXCEPT on a board that
        # prices several asset universes: there the universe correction
        # (``universe_clock``) needs row clocks, so a past offense row keeps the
        # board clock an IDP-only publication may have moved (a known limit of
        # replaying past boards against today's state).
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
    # D1 (2026-10-07): FETCHED RECENTLY is not CONTENT FRESH.  On the first
    # observation of a board ``dataset_state.observe`` stamps the data clocks
    # with the observation (fetch) time and declares the subset
    # ``firstObservationIsBaseline``.  While that baseline is still the clock,
    # the content was published at some unknown time AT OR BEFORE it, so the
    # age measured from it is a LOWER bound: it can prove a board is at least
    # so stale (that decay is evidence and is kept unchanged — no blend weight
    # moves), but it can never prove one fresh, and the fetch time is never
    # published as ``sourceDataAsOf``.  A vendor-stated publication time is a
    # real clock and is not a baseline.
    first_observed = parse_iso(st.get("firstObservedAt"))
    clock_is_baseline = bool(
        st.get("firstObservationIsBaseline") is True
        and clock_name == "lastBroadDatasetChangeAt"
        and clock_at is not None
        and first_observed is not None
        and clock_at == first_observed
    )
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
        clock_is_baseline=clock_is_baseline,
    )
    if v2:
        return _finish_subset_v2(
            base, st, first_observed=first_observed, step=step or default_step_schedule(), cfg=cfg
        )
    if clock_at is None:
        return base
    f, age = base.row_freshness(None)
    base.age_hours = age
    base.freshness = f
    state = state_for(f, cfg)
    if clock_is_baseline and state == STATE_ON_SCHEDULE:
        # A lower-bound age cannot prove the board is on schedule.  The
        # factor stays exactly as computed (no blend weight moves) — only
        # the claim is withdrawn.
        state = STATE_UNMEASURED
    base.state = state
    return base


def _finish_subset_v2(
    base: SubsetFreshness,
    st: Mapping[str, Any],
    *,
    first_observed: datetime | None,
    step: StepSchedule,
    cfg: FreshnessConfig,
) -> SubsetFreshness:
    """Clock basis, factor and state under the owner's step schedule.

    The state keeps the v1 vocabulary so every existing reader works
    unchanged: the v1 bands map the steps exactly (1.0 ON_SCHEDULE, 0.75
    OVERDUE, 0.5 STALE, 0.25 SEVERELY_STALE, 0 QUARANTINED).  An update time
    we cannot establish (baseline-only clock) is ``UNMEASURED`` and votes at
    ``step.unknown`` (0) — unless even its lower-bound age is past the last
    step, which proves it stale (QUARANTINED).  No clock at the board's time
    (the board predates our tracking) is not a measurement at all:
    ``UNMEASURED`` at 1.0, ``clockBasis: not_tracked_at_board_time``."""
    base.schedule = SCHEDULE_V2
    base.step = step
    if (
        st.get("firstObservationIsBaseline") is True
        and first_observed is not None
        and first_observed <= base.as_of
    ):
        base.baseline_at = first_observed
    if base.clock_at is None:
        base.clock_basis = CLOCK_BASIS_NOT_TRACKED
    elif base.clock == "upstreamPublishedAt":
        base.clock_basis = CLOCK_BASIS_PUBLISHER
    elif base.row_clock_known(base.clock_at):
        base.clock_basis = CLOCK_BASIS_CONTENT
    else:
        base.clock_basis = CLOCK_BASIS_UNKNOWN
    f, age = base.row_freshness(None)
    base.age_hours = age
    base.freshness = f
    if base.clock_basis == CLOCK_BASIS_NOT_TRACKED:
        base.state = STATE_UNMEASURED
    elif base.clock_basis == CLOCK_BASIS_UNKNOWN:
        lower_bound_days = (
            None if base.clock_at is None else whole_days_elapsed(base.clock_at, base.as_of)
        )
        base.state = (
            STATE_QUARANTINED
            if lower_bound_days is not None and lower_bound_days > step.max_days
            else STATE_UNMEASURED
        )
    else:
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
    schedule: str = SCHEDULE_V1

    def subset_for(self, is_pick: bool) -> SubsetFreshness | None:
        return self.subsets.get(SUBSET_PICKS if is_pick else SUBSET_PLAYERS) or self.subsets.get(
            SUBSET_PLAYERS
        )

    def factor_for_row(
        self,
        *,
        is_pick: bool,
        row_key: str | None,
        universe: str | None = None,
        key_universe: Mapping[str, str] | None = None,
    ) -> tuple[float, float | None]:
        """``(freshness, age_hours)`` for one contract row.

        With ``universe`` and ``key_universe`` (row key -> universe for this
        source's rows), a subset spanning offense and IDP ages each row from its
        own universe's broad-change clock, capped at the source clock."""
        sub = self.subset_for(is_pick)
        if sub is None:
            return 1.0, None
        cap = None
        if universe is not None and key_universe:
            cap = sub.universe_clock(universe, key_universe)
        return sub.row_freshness(row_key, clock_cap=cap)

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
            **({"freshnessSchedule": SCHEDULE_V2} if self.schedule == SCHEDULE_V2 else {}),
        }


def assess_source(
    source_key: str,
    state: Mapping[str, Any] | None,
    *,
    as_of: datetime,
    cfg: FreshnessConfig | None = None,
    schedule: str = SCHEDULE_V1,
    step: StepSchedule | None = None,
) -> SourceWeighting:
    cfg = cfg or default_config()
    if schedule == SCHEDULE_V2:
        step = step or default_step_schedule()
        if source_key in step.exempt_keys:
            # Not a dynasty ranking voter (the KTC Market benchmark): v1.
            schedule = SCHEDULE_V1
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
            schedule=schedule,
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
        schedule=schedule,
        step=step,
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
            schedule=schedule,
            step=step,
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
        schedule=schedule,
    )


def load_source_weightings(
    source_keys: list[str],
    *,
    state_dir: Path,
    as_of: datetime,
    cfg: FreshnessConfig | None = None,
    schedule: str = SCHEDULE_V1,
) -> dict[str, SourceWeighting]:
    from src.sources.dataset_state import load_state, state_path  # noqa: PLC0415

    cfg = cfg or default_config()
    step = default_step_schedule() if schedule == SCHEDULE_V2 else None
    return {
        key: assess_source(
            key,
            load_state(state_path(state_dir, key)),
            as_of=as_of,
            cfg=cfg,
            schedule=schedule,
            step=step,
        )
        for key in source_keys
    }
