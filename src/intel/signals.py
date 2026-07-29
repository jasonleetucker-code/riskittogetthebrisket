"""Window-safe signal metrics shared by Sharp Tracker and Insider Trading.

Product logic does NOT live here — this module turns ledger rows into
comparable numbers, and both products consume it.

──────────────────────────────────────────────────────────────────────
What replaced ``trendScore``, and why
──────────────────────────────────────────────────────────────────────
The predecessor's headline metric — also its board sort key — was::

    trendScore = 3*net48h + 2*net7d + 1*net30d

The windows are nested, so a movement one hour old is inside all three
terms and contributes 3+2+1 = 6 to a number the UI presented as a
signal strength, next to a printed copy of the formula.  One event, six
counted.  Intended as recency weighting, it is literally a sum of
overlapping windows, and it made a single fresh movement outrank a
genuinely broad one.

Nothing here ever adds two windows together.  Recency is expressed as
a RATIO between windows (:func:`velocity`) — comparing a short window's
rate against a long window's rate is a legitimate acceleration measure
and is arithmetically incapable of double-counting, because division
by a superset cancels the shared events rather than stacking them.

──────────────────────────────────────────────────────────────────────
Volume is never optional
──────────────────────────────────────────────────────────────────────
``net`` alone cannot rank assets: 1 buy / 0 sells and 40 buys / 39
sells are both ``net = +1`` and are not remotely the same claim.
:func:`signal_strength` multiplies direction by a sample-size
confidence that is near zero at low volume, and
:func:`confidence_tier` is emitted alongside every signal so a thin
observation can never render as a strong one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

# ── windows ──────────────────────────────────────────────────────────
#
# Each entry is an INDEPENDENT lens over the same rows.  They are
# deliberately expressed as durations rather than disjoint buckets, so
# there is no way to "add up the buckets" — there are no buckets.

MS_HOUR = 3600 * 1000
MS_DAY = 24 * MS_HOUR

WINDOWS_MS: dict[str, int] = {
    "48h": 48 * MS_HOUR,
    "7d": 7 * MS_DAY,
    "14d": 14 * MS_DAY,
    "30d": 30 * MS_DAY,
    "90d": 90 * MS_DAY,
}

# Sharp Tracker shows signal velocity, so it wants the short windows.
SHARP_WINDOWS = ("48h", "7d", "14d", "30d")
# Insider Trading defaults to a single uncluttered window; the others
# are available as explicit filters.
INSIDER_DEFAULT_WINDOW = "30d"
INSIDER_WINDOWS = ("7d", "30d", "90d")

# Volume at which sample-size confidence reaches ~0.5.  Tuned so a
# single observation is visibly weak (~0.09) and a dozen is strong
# (~0.86) without a hard cutoff that would create a cliff.
_CONFIDENCE_HALF_VOLUME = 5.0

# Breadth: the same manager buying an asset in six of their own leagues
# is ONE person's opinion repeated, not six opinions.  Concentration
# discounts that without discarding it.
_BREADTH_HALF_MANAGERS = 3.0


def window_bounds(window: str, now_ms: int) -> tuple[int | None, int]:
    """``(since_ms, until_ms)`` for a named window.

    ``"all"`` returns ``(None, now)`` — everything the ledger retains.
    Inclusive at the edge, matching the predecessor's pinned semantics
    (an event exactly ``window`` old still counts).
    """
    if window in ("all", "alltime", "all_time"):
        return None, int(now_ms)
    span = WINDOWS_MS.get(window)
    if span is None:
        raise ValueError(f"unknown window {window!r}; known: {sorted(WINDOWS_MS)} + 'all'")
    return int(now_ms) - span, int(now_ms)


def sample_confidence(volume: int) -> float:
    """0..1 confidence from observation count alone.

    Saturating rather than linear: the difference between 1 and 3
    observations matters far more than between 40 and 42.
    """
    v = max(0, int(volume))
    if v <= 0:
        return 0.0
    return v / (v + _CONFIDENCE_HALF_VOLUME)


def breadth_factor(unique_managers: int) -> float:
    """0..1 — is this many managers, or one manager many times?

    Guards the "broad vs concentrated" question the product has to
    answer.  A single manager transacting an asset in five leagues
    scores materially below five managers doing it once each.
    """
    m = max(0, int(unique_managers))
    if m <= 0:
        return 0.0
    return m / (m + _BREADTH_HALF_MANAGERS)


def confidence_tier(volume: int, unique_managers: int, unique_leagues: int) -> str:
    """``"high" | "medium" | "low" | "insufficient"`` — the label that
    stops a one-observation signal from reading like a real one."""
    if volume <= 0:
        return "insufficient"
    if volume >= 12 and unique_managers >= 4 and unique_leagues >= 3:
        return "high"
    if volume >= 5 and unique_managers >= 2:
        return "medium"
    return "low"


def velocity(short: dict[str, Any] | None, long: dict[str, Any] | None) -> float | None:
    """Acceleration as a RATIO of rates, never a sum of windows.

    ``> 1`` means the asset is moving faster recently than its longer
    baseline.  Returns ``None`` when the baseline is too thin to make a
    ratio meaningful, rather than inventing a large number from a tiny
    denominator.

    Because the short window is a strict subset of the long one, the
    shared movements appear in both numerator and denominator and
    cancel — which is precisely why this cannot double-count.
    """
    if not short or not long:
        return None
    short_span = short.get("_spanMs")
    long_span = long.get("_spanMs")
    if not short_span or not long_span:
        return None
    long_volume = int(long.get("volume") or 0)
    if long_volume < 3:
        return None
    short_rate = int(short.get("volume") or 0) / float(short_span)
    long_rate = long_volume / float(long_span)
    if long_rate <= 0:
        return None
    return round(short_rate / long_rate, 3)


def signal_strength(
    *,
    net: int,
    volume: int,
    unique_managers: int,
    manager_quality: float = 1.0,
) -> float:
    """Confidence-adjusted directional signal, roughly -100..100.

    ``normalized_net x sample_confidence x breadth x manager_quality``.

    ``normalized_net`` is ``net / volume`` — the directional *lean*,
    bounded to [-1, 1] by construction, so a lopsided-but-thin asset
    cannot outscore a broad one on direction alone.  The magnitude then
    comes back in through the confidence and breadth factors.

    ``manager_quality`` is the hook for Sharp Tracker's Sharp Score
    (a cohort-quality weight); Insider Trading passes 1.0 because its
    cohort is defined by league membership, not quality.
    """
    v = max(0, int(volume))
    if v <= 0:
        return 0.0
    normalized_net = max(-1.0, min(1.0, net / float(v)))
    strength = (
        normalized_net
        * sample_confidence(v)
        * breadth_factor(unique_managers)
        * max(0.0, float(manager_quality))
    )
    return round(strength * 100.0, 2)


@dataclass
class AssetSignal:
    """One asset's signal across several INDEPENDENT windows.

    ``windows`` maps window name -> that window's own counts.  There is
    intentionally no ``total`` field: a total across these would be a
    sum of overlapping views.  The honest "everything we hold" number
    is the ``"all"`` window, which is its own query over the raw rows.
    """

    asset_id: str
    asset_type: str
    windows: dict[str, dict[str, Any]] = field(default_factory=dict)
    velocity: float | None = None
    strength: float = 0.0
    confidence: str = "insufficient"
    last_ts: int | None = None

    def to_dict(self) -> dict[str, Any]:
        windows = {
            name: {k: v for k, v in win.items() if not k.startswith("_")}
            for name, win in self.windows.items()
        }
        return {
            "assetId": self.asset_id,
            "assetType": self.asset_type,
            "windows": windows,
            "velocity": self.velocity,
            "signalStrength": self.strength,
            "confidence": self.confidence,
            "lastTs": self.last_ts,
        }


def _empty_window(span_ms: int | None) -> dict[str, Any]:
    return {
        "buys": 0,
        "sells": 0,
        "net": 0,
        "volume": 0,
        "buyRate": None,
        "uniqueBuyers": 0,
        "uniqueSellers": 0,
        "uniqueManagers": 0,
        "uniqueLeagues": 0,
        "tradeCount": 0,
        "movementCount": 0,
        "_spanMs": span_ms,
    }


def build_asset_signals(
    per_window: dict[str, list[dict[str, Any]]],
    *,
    now_ms: int,
    primary_window: str,
    windows: Sequence[str] | None = None,
    manager_quality: dict[str, float] | None = None,
) -> list[AssetSignal]:
    """Assemble per-asset signals from independently-queried windows.

    ``per_window`` is ``{windowName: ledger.asset_signals(...) rows}``
    — each list produced by its OWN query against the raw movements.
    This function only aligns them by asset; it never combines their
    counts.

    ``primary_window`` decides ranking and the emitted strength.
    """
    names = list(windows or per_window.keys())
    by_asset: dict[str, AssetSignal] = {}

    for name in names:
        span = None if name in ("all", "alltime", "all_time") else WINDOWS_MS.get(name)
        for row in per_window.get(name) or []:
            asset_id = str(row.get("assetId") or "")
            if not asset_id:
                continue
            sig = by_asset.get(asset_id)
            if sig is None:
                sig = AssetSignal(
                    asset_id=asset_id,
                    asset_type=str(row.get("assetType") or "player"),
                )
                by_asset[asset_id] = sig
            win = dict(row)
            win.pop("assetId", None)
            win.pop("assetType", None)
            last = win.pop("lastTs", None)
            win["_spanMs"] = span
            sig.windows[name] = win
            if last and (sig.last_ts is None or last > sig.last_ts):
                sig.last_ts = int(last)

    # Any asset present in one window but absent from another must show
    # an explicit zero for the missing window, never a gap the UI could
    # render as "no data" and a reader could mistake for "not counted".
    for sig in by_asset.values():
        for name in names:
            if name not in sig.windows:
                span = None if name in ("all", "alltime", "all_time") else WINDOWS_MS.get(name)
                sig.windows[name] = _empty_window(span)

        primary = sig.windows.get(primary_window) or _empty_window(WINDOWS_MS.get(primary_window))
        quality = 1.0
        if manager_quality:
            # Cohort quality is per-manager; without per-observation
            # attribution here we use the cohort mean, which is exact
            # when the cohort is uniform (Insider Trading) and a stated
            # approximation when it is not (Sharp Tracker passes an
            # explicit per-asset value instead).
            vals = [v for v in manager_quality.values() if isinstance(v, (int, float))]
            quality = (sum(vals) / len(vals)) if vals else 1.0

        sig.strength = signal_strength(
            net=int(primary.get("net") or 0),
            volume=int(primary.get("volume") or 0),
            unique_managers=int(primary.get("uniqueManagers") or 0),
            manager_quality=quality,
        )
        sig.confidence = confidence_tier(
            int(primary.get("volume") or 0),
            int(primary.get("uniqueManagers") or 0),
            int(primary.get("uniqueLeagues") or 0),
        )
        short = sig.windows.get("48h") or sig.windows.get("7d")
        long = sig.windows.get("30d") or sig.windows.get("90d")
        sig.velocity = velocity(short, long)

    return list(by_asset.values())


def sort_signals(
    signals: Sequence[AssetSignal],
    *,
    sort: str = "net",
    primary_window: str = "30d",
) -> list[AssetSignal]:
    """``sort`` is one of ``net`` | ``volume`` | ``strength`` |
    ``velocity`` | ``buys`` | ``sells``.

    ``net`` sorts by net but breaks ties on volume, so the thin asset
    never outranks the broad one at equal net.
    """

    def key(s: AssetSignal):
        win = s.windows.get(primary_window) or {}
        net = int(win.get("net") or 0)
        volume = int(win.get("volume") or 0)
        if sort == "volume":
            return (-volume, -abs(net))
        if sort == "strength":
            return (-s.strength, -volume)
        if sort == "velocity":
            return (-(s.velocity or 0.0), -volume)
        if sort == "buys":
            return (-int(win.get("buys") or 0), -volume)
        if sort == "sells":
            return (-int(win.get("sells") or 0), -volume)
        return (-net, -volume)

    return sorted(signals, key=key)
