"""KTC crowd-sourced FAAB bridge.

The Dynasty Scraper's ``scrape_ktc_waiver_database`` populates
``KTC_CROWD_DATA["waivers"]`` with crowd-sourced waiver claims
collected from KTC's public waiver database.  Each entry has the
shape::

    {
        "source":  "ktc",
        "date":    "...",
        "added":   "<player display name>",
        "dropped": "<player display name>" | "",
        "bid":     int,
        "bidPct":  "<float-as-string>" | "",
        "settings": {...},
    }

The per-pair FAAB recommender (``src/trade/faab_recommender.py``)
accepts an optional ``ktc_crowd_bids`` map of
``compact_name_key(name) → median_bid_percentage_of_budget`` to
blend into its calibration step.  This bridge produces that map.

The key is ``src/utils/name_clean.compact_name_key`` — family 2 in
that module's key registry.  The recommender must look the map up
with the SAME function; anything else (a bare ``strip().lower()``,
say) can only ever collide on single-token unpunctuated names, i.e.
essentially no NFL player.

Why a separate module?  Keeping the contract-shape sniff +
percent parsing isolated here means the recommender stays a pure
function of its dataclass-shaped inputs and the server endpoint
can swap in a different crowd source (e.g. RotoBaller, FFC) by
writing another adapter module without touching the recommender.
"""

from __future__ import annotations

import statistics
from typing import Any

from src.utils.name_clean import compact_name_key

# Deprecated private alias.  The compact key now has exactly one
# definition (``name_clean.compact_name_key``, family 2 in that
# module's key registry) so the producer here and the consumer in
# ``src/trade/faab_recommender._ktc_crowd_blend`` cannot drift apart
# again — they did until 2026-07-29, and the crowd calibration factor
# never fired in production as a result.
# (A private ``_normalize_name = compact_name_key`` alias sat here after
# the consolidation.  It was dead on arrival: this module calls
# ``compact_name_key`` directly, it is private so no external caller can
# depend on it, and a repo-wide grep found its only reference was a test
# asserting it existed.  Removed 2026-07-29 — an alias nothing reads is a
# promise the code does not keep.)


def _parse_bid_pct(bid_pct_raw: Any, bid: Any, settings: dict | None = None) -> float | None:
    """Resolve a single waiver entry's bid percentage.

    KTC publishes ``bidPct`` directly when the league reports it;
    when missing, derive from ``bid / settings.waiver_budget`` so
    multi-budget leagues normalize correctly.

    Returns ``None`` when neither path produces a usable number;
    the bridge skips the entry rather than dragging in junk.
    """
    # Direct bidPct field.
    #
    # ZERO IS A REAL BID, and it is the modal one: 28% of the KTC
    # waiver database's claims and roughly half of this league's own
    # adds cost nothing.  Excluding zeros — which this did, and which
    # ``src/api/faab_analytics.py`` still does — biases the resulting
    # median sharply upward and makes a quiet player look contested.
    # The gate is therefore ``>= 0``, not ``> 0``.
    try:
        if bid_pct_raw is not None and str(bid_pct_raw).strip() != "":
            n = float(str(bid_pct_raw).strip().replace("%", ""))
            if 0 <= n <= 200:  # >100% is rare but legal in some leagues
                return n
    except (TypeError, ValueError):
        pass

    # Derive from bid / waiver_budget.
    try:
        bid_n = float(bid) if bid is not None else 0.0
        if bid_n < 0:
            return None
        budget = None
        if isinstance(settings, dict):
            for k in ("waiver_budget", "waiverBudget", "faabBudget", "budget"):
                v = settings.get(k)
                if v is None:
                    continue
                try:
                    bn = float(v)
                except (TypeError, ValueError):
                    continue
                if bn > 0:
                    budget = bn
                    break
        if budget is None:
            return None
        return (bid_n / budget) * 100.0
    except (TypeError, ValueError):
        return None


def build_crowd_bid_map(
    ktc_crowd: dict[str, Any] | None,
    *,
    min_samples: int = 2,
) -> dict[str, float]:
    """Build the ``normalized_name → median_bid_pct`` map the
    recommender consumes.

    A player needs at least ``min_samples`` distinct historical
    bids before the median is exposed — single-bid samples are
    too noisy to drive recommendations.

    Returns an empty dict when the input is missing, malformed,
    or has no qualifying players.  The recommender already treats
    an empty map as "no crowd signal" so callers can pass through
    blindly.
    """
    if not isinstance(ktc_crowd, dict):
        return {}
    waivers = ktc_crowd.get("waivers")
    if not isinstance(waivers, list):
        return {}

    by_name: dict[str, list[float]] = {}
    for w in waivers:
        if not isinstance(w, dict):
            continue
        added = w.get("added")
        if not added:
            continue
        norm = compact_name_key(added)
        if not norm:
            continue
        pct = _parse_bid_pct(
            w.get("bidPct"),
            w.get("bid"),
            w.get("settings") if isinstance(w.get("settings"), dict) else None,
        )
        if pct is None:
            continue
        by_name.setdefault(norm, []).append(pct)

    floor = max(1, int(min_samples))
    out: dict[str, float] = {}
    for name, pcts in by_name.items():
        if len(pcts) < floor:
            continue
        out[name] = round(float(statistics.median(pcts)), 2)
    return out


def crowd_bid_map_from_contract(
    contract: dict[str, Any] | None,
    *,
    min_samples: int = 2,
) -> dict[str, float]:
    """Convenience wrapper that pulls ``ktcCrowd`` off a
    full-contract payload (as served from ``/api/data``) and
    returns the map.

    Returns an empty dict when the contract or ktcCrowd block is
    missing.  This is the typical entry point from the server
    endpoint."""
    if not isinstance(contract, dict):
        return {}
    ktc = contract.get("ktcCrowd")
    return build_crowd_bid_map(ktc, min_samples=min_samples)
