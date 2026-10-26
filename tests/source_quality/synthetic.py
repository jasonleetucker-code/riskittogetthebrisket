"""Synthetic point-in-time panels with a KNOWN lead/lag structure."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

import numpy as np

from src.source_quality import panel as pn

START = date(2026, 4, 1)


def spec(key: str, family: str, universes=("OFFENSE",), cadence: float = 24.0) -> pn.SourceSpec:
    return pn.SourceSpec(
        key=key,
        family=family,
        csv_file=f"{key}.csv",
        signal="rank",
        universes=frozenset(universes),
        cadence_hours=cadence,
    )


def build_panel(
    *,
    days: int = 120,
    players: int = 120,
    lags: dict[str, int] | None = None,
    noise: dict[str, float] | None = None,
    seed: int = 7,
) -> tuple[pn.ObservationPanel, list[date]]:
    """Families observe one latent value path; ``lag`` days behind it, plus noise.

    A lag-0 family publishes what the others publish ``lag`` days later: it LEADS.
    """
    lags = lags or {"lead": 0, "a": 4, "b": 4, "c": 4, "d": 4}
    noise = noise or {}
    rng = np.random.default_rng(seed)
    base = np.sort(rng.normal(0, 1.5, players))[::-1]
    steps = rng.normal(0, 0.12, (players, days + 20))
    path = base[:, None] + np.cumsum(steps, axis=1)
    specs = [spec(f"src_{f}", f) for f in lags]
    versions: dict[str, list[pn.Version]] = {}
    for f, lag in lags.items():
        key = f"src_{f}"
        vs = []
        for d in range(days):
            t = 20 + d - lag
            vals = path[:, t] + rng.normal(0, noise.get(f, 0.05), players)
            order = np.argsort(-vals)
            rows = tuple(
                pn.Row(f"player {i}", float(r + 1), None, False) for r, i in enumerate(order)
            )
            when = datetime.combine(START + timedelta(days=d), time(12, 0), tzinfo=timezone.utc)
            vs.append(
                pn.Version(key, when, "synthetic", rows, {"kept": players}, pn._hash_rows(rows))
            )
        versions[key] = vs
    dates = [START + timedelta(days=d) for d in range(days)]
    return pn.ObservationPanel(specs, versions), dates
