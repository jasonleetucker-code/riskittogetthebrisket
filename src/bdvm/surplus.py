"""Season starter surplus (BDVM module 8) — the option-value core.

    SSV(t) = E[max(0, X - R)] · G,  X ~ Normal(µ, σ)
           = [(µ-R)·Φ(z) + σ·φ(z)] · G,   z = (µ-R)/σ

You are never forced to start a below-replacement outcome, so a
player's season is a call option on his own production struck at
replacement level.  This is the central V1 HYPOTHESIS, not a law:
``surplus_mode`` exposes the two simpler formulations for the mandatory
ablation (master prompt §3.3); the option form stays champion unless
rolling out-of-sample testing says otherwise.
"""

from __future__ import annotations

import math

SQRT2 = math.sqrt(2.0)
SQRT2PI = math.sqrt(2.0 * math.pi)

SURPLUS_MODES = ("option", "truncated", "plain")


def norm_pdf(z: float) -> float:
    return math.exp(-0.5 * z * z) / SQRT2PI


def norm_cdf(z: float) -> float:
    return 0.5 * (1.0 + math.erf(z / SQRT2))


def expected_positive_surplus(mu: float, sigma: float, replacement: float) -> float:
    """E[max(0, X - R)] per game under X ~ Normal(mu, sigma)."""
    if sigma <= 1e-9:
        return max(0.0, mu - replacement)
    z = (mu - replacement) / sigma
    return (mu - replacement) * norm_cdf(z) + sigma * norm_pdf(z)


def season_starter_value(
    mu: float,
    sigma: float,
    replacement: float,
    games: float,
    *,
    mode: str = "option",
) -> float:
    """Season surplus under the selected formulation.

    ``option``     E[max(0, X−R)]·G   (champion)
    ``truncated``  max(0, µ−R)·G      (ablation baseline B-truncated)
    ``plain``      (µ−R)·G            (ablation baseline B-plain; can go negative)
    """
    if mode == "option":
        return expected_positive_surplus(mu, sigma, replacement) * games
    if mode == "truncated":
        return max(0.0, mu - replacement) * games
    if mode == "plain":
        return (mu - replacement) * games
    raise ValueError(f"unknown surplus mode {mode!r}; expected one of {SURPLUS_MODES}")


def probability_above(mu: float, sigma: float, replacement: float) -> float:
    """P(X > R) — the probability the season out-produces replacement."""
    if sigma <= 1e-9:
        return 1.0 if mu > replacement else 0.0
    return norm_cdf((mu - replacement) / sigma)
