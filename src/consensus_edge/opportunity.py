"""Whether the value gap is likely to persist — where that is knowable.

A mispricing is a claim that the market will move toward our number.
That claim is much weaker when the gap exists *because* our inputs are
stale: a player whose role collapsed last week is not underpriced, he is
correctly repriced and our board has not caught up.  Opportunity/Risk is
the check on that.

**Most of it cannot be computed here, and this module refuses rather
than approximates.**  The platform has no forward-looking projection
feed (`src/bdvm/projections.py`: "the platform currently has **zero**
forward-looking statistical projection sources"), the usage-transition
detector was measured firing on 17.8% of active players every week and
is flagged off, and the rank-history log this would otherwise read is
absent outside production.

So the design borrows the one pattern in this repo that already handles
"an axis we cannot evidence": ``league_intel/adjustment.py``'s ABSENT
tier, where an unevidenced axis returns *exactly* neutral and the caller
structurally cannot smuggle in an effect.  Here that means an axis with
no evidence contributes nothing AND is named in ``absentAxes``, so a
reader can see what was not consulted.

The reason this module exists at all, rather than being deferred: the
composite must be able to say "opportunity was not assessed" as a
distinct state from "opportunity looks fine".  Those are different, and
only one of them should support a Strong Buy.
"""

from __future__ import annotations

from typing import Any

# Evidence tiers, mirroring league_intel/adjustment.py.
TIER_ABSENT = "absent"
TIER_OBSERVED = "observed"

UNSCORED_NO_EVIDENCE = "no_opportunity_evidence_available"


def _axis(name: str, value: float | None, tier: str, detail: str | None = None) -> dict[str, Any]:
    return {"axis": name, "score": value, "tier": tier, "detail": detail}


def rank_momentum_axis(rank_history: list[dict[str, Any]] | None) -> dict[str, Any]:
    """Direction of the player's own board movement over recent snapshots.

    Momentum is NOT a buy signal on its own — the frontend
    ``signal-engine.js`` treats a rising value as a buy, which is
    momentum-chasing dressed as valuation. Here it is used only in its
    defensible direction: as a *risk* check on whether a gap is being
    closed already, or is widening because something changed.

    Returns ABSENT without history, which is the normal case outside
    production (``data/rank_history.jsonl`` is gitignored).
    """
    if not rank_history or len(rank_history) < 3:
        return _axis("rankMomentum", None, TIER_ABSENT, "no rank history available")

    values = [
        float(p["rankDerivedValue"])
        for p in rank_history
        if isinstance(p, dict) and isinstance(p.get("rankDerivedValue"), (int, float))
    ]
    if len(values) < 3:
        return _axis("rankMomentum", None, TIER_ABSENT, "rank history carries no values")

    first, last = values[0], values[-1]
    if first <= 0:
        return _axis("rankMomentum", None, TIER_ABSENT, "non-positive baseline value")

    change = (last - first) / first
    # Bounded and gentle: this axis modulates, it does not drive.
    return _axis(
        "rankMomentum",
        max(-1.0, min(1.0, change * 2.0)),
        TIER_OBSERVED,
        f"board value moved {change:+.1%} over {len(values)} snapshots",
    )


def assess(
    *,
    rank_history: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Combine whatever opportunity evidence exists into one score.

    Returns ``score = None`` with a reason when nothing is evidenced —
    never 0.0, which would read as "assessed and found neutral".
    """
    axes = [rank_momentum_axis(rank_history)]

    observed = [a for a in axes if a["tier"] == TIER_OBSERVED and a["score"] is not None]
    absent = [a["axis"] for a in axes if a["tier"] == TIER_ABSENT]

    result: dict[str, Any] = {
        "score": None,
        "reason": None,
        "axes": axes,
        "absentAxes": absent,
        "observedAxes": [a["axis"] for a in observed],
    }
    if not observed:
        result["reason"] = UNSCORED_NO_EVIDENCE
        return result

    result["score"] = sum(float(a["score"]) for a in observed) / len(observed)
    return result
