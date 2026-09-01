"""The Live Waiver Opportunity layer — short-term signal on top of dynasty value.

Full design record: ``docs/faab-live-opportunity-model.md``.

Canonical dynasty value (``rankDerivedValue``) moves on a scrape/refit
cadence and answers "what is this player worth long-term."  It has NO
path for a depth-chart promotion, an injury vacancy, or a breakout game
to move a FAAB dollar figure the same day it happens.  Reproduced live
against the real 2026-09-01 board: eleven of thirteen human-reviewed
benchmark waiver targets priced at exactly $0 under BOTH pre-existing
FAAB formulas, because the canonical board had not yet recognized any
of them as above replacement.

This module answers a DIFFERENT, narrower question than canonical
value does: "how much immediate football opportunity does this player
have RIGHT NOW, on top of what the dynasty board already says."  It
never touches ``rankDerivedValue`` and is never a second canonical
player-value owner — the same posture ``src/bdvm/`` already
establishes ("never touches rankDerivedValue... additive by
construction").

    opportunity_value(player) = dynasty_value
                                 + retention(dynasty_value) x short_term_surplus

``short_term_surplus`` is a SUM of independently-observed axes, each
bounded to [-1, 1] before scaling — never a single opaque number — so
every contribution is inspectable for the "Why this bid?" UI panel and
for the factor-weight audit this repo requires (CLAUDE.md "no mystery
constants").  A player with no evidence on any axis gets
``short_term_surplus == 0`` and ``hasEvidence == False``: MISSING
EVIDENCE degrades this ADDITIVE LAYER to zero, which is a different
claim from MISSING DYNASTY VALUE (which is never coerced to zero
anywhere in this codebase) — the base ``dynasty_value`` this layer sits
on top of is untouched either way.

Reuse, not reinvention — every axis below delegates to the existing
canonical owner rather than re-deriving its own copy:

  * role/usage    -> ``src.consensus_edge.opportunity.snap_trend_axis``
                      (playerctx snap share trend) plus a small new
                      depth-rank axis reading the SAME playerctx record.
  * structured events -> ``src.bdvm.events`` (the closed ontology's own
                      ``effective_impact``, so the speculation-confidence
                      gate — an auto-classified news event can only
                      widen sigma, never move ``mu_pct`` — is enforced
                      exactly once, by its owner, not re-implemented
                      here).
  * market heat (Sleeper trending) -> deliberately NOT read here.  It
    is demand evidence, not worth evidence, and only ever enters
    ``faab_engine``'s Stage E market layer
    (``faab_recommender._trending_share``).  Keeping it out of this
    file is what keeps worth and demand from collapsing into one axis.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from src.trade.faab_engine import FaabConfig

TIER_ABSENT = "absent"
TIER_OBSERVED = "observed"


def _axis(name: str, score: float | None, tier: str, detail: str | None = None) -> dict[str, Any]:
    return {"axis": name, "score": score, "tier": tier, "detail": detail}


def _load_playerctx_record(sleeper_id: str | None) -> dict[str, Any] | None:
    """The playerctx record for one Sleeper player id, or ``None``.

    Defensive by construction — a missing/corrupt snapshot must read
    as "no role evidence", never as an error the caller has to guard
    against separately from a genuinely-uncovered player.
    """
    if not sleeper_id:
        return None
    try:
        from src.playerctx.service import load_playerctx  # noqa: PLC0415
    except Exception:  # noqa: BLE001 — optional dependency, never fatal
        return None
    snapshot = load_playerctx()
    if not isinstance(snapshot, dict):
        return None
    gsis = (snapshot.get("sleeperIndex") or {}).get(str(sleeper_id))
    if not gsis:
        return None
    players = snapshot.get("players") or {}
    rec = players.get(gsis)
    return rec if isinstance(rec, dict) else None


def role_trend_axis(player_context: dict[str, Any] | None) -> dict[str, Any]:
    """Delegates verbatim to the canonical owner — no second copy."""
    from src.consensus_edge.opportunity import snap_trend_axis  # noqa: PLC0415

    return snap_trend_axis(player_context)


def depth_rank_axis(
    player_context: dict[str, Any] | None,
    *,
    config: FaabConfig | None = None,
) -> dict[str, Any]:
    """Current team depth-chart standing — a LEVEL, complementing the
    role-trend axis' momentum.  Rank 1 (the starter) saturates
    positive; a deep bench slot saturates negative.

    ``depthRankSaturation`` is category C (documented reasoning: a
    plain, legible bound rather than a fitted one — no outcome data
    yet ties a specific depth-chart slot to a specific FAAB result).
    """
    cfg = config or FaabConfig()
    depth = (player_context or {}).get("depth")
    if not isinstance(depth, dict):
        return _axis("depthRank", None, TIER_ABSENT, "no player-context depth-chart record")
    rank = depth.get("rank")
    if not isinstance(rank, (int, float)) or rank < 1:
        return _axis("depthRank", None, TIER_ABSENT, "depth-chart record carries no rank")

    saturation = max(1.0, cfg.num("opportunity", "depthRankSaturation", 3.0))
    # rank 1 -> +1.0, rank >= 1+saturation -> -1.0, linear between.
    score = max(-1.0, min(1.0, 1.0 - 2.0 * (float(rank) - 1.0) / saturation))
    return _axis("depthRank", score, TIER_OBSERVED, f"depth-chart rank {int(rank)}")


def event_axis(
    player_key: str | None,
    *,
    season: int | None = None,
    today: str | None = None,
    config: FaabConfig | None = None,
) -> tuple[dict[str, Any], float]:
    """Structured-event opportunity signal, plus a separate
    availability factor in [0, 1].

    Returns ``(axis, availability_factor)``.  The axis reads ``mu_pct``
    (projected-production delta) summed across every matching event's
    ``effective_impact`` — the SAME decay/speculation-gate math BDVM's
    valuation engine uses, called through its owner rather than
    reimplemented.  ``availability_factor`` reads the same events'
    ``games_delta`` so an injured/suspended player's short-term surplus
    is damped toward zero regardless of how good his role looks on
    paper — this is what makes an IR'd player in a league with no IR
    slot (directive Part IX, Jer'Zhan Newton) score differently from a
    healthy one with an identical depth-chart slot.
    """
    cfg = config or FaabConfig()
    if not player_key:
        return _axis("events", None, TIER_ABSENT, "no player key"), 1.0

    try:
        from src.bdvm import events as _bdvm_events  # noqa: PLC0415
    except Exception:  # noqa: BLE001 — optional dependency, never fatal
        return _axis("events", None, TIER_ABSENT, "event ledger unavailable"), 1.0

    as_of = today or datetime.now(timezone.utc).date().isoformat()
    season_year = season or _current_nfl_season(as_of)
    try:
        all_events = _bdvm_events.load_events_file(season_year)
    except Exception:  # noqa: BLE001 — a corrupt ledger must not break FAAB
        return _axis("events", None, TIER_ABSENT, "event ledger unreadable"), 1.0

    matching = [e for e in all_events if e.player_key == player_key]
    if not matching:
        return _axis("events", None, TIER_ABSENT, "no events for this player"), 1.0

    mu_total = 0.0
    games_delta_total = 0.0
    applied = 0
    for ev in matching:
        try:
            impact = _bdvm_events.effective_impact(ev, as_of)
        except _bdvm_events.EventError:
            continue
        if not impact:
            continue
        applied += 1
        mu_total += float(impact.get("mu_pct", 0.0))
        games_delta_total += float(impact.get("games_delta", 0.0))

    if applied == 0:
        return _axis("events", None, TIER_ABSENT, "every event fully decayed or reflected"), 1.0

    saturation = max(1e-6, cfg.num("opportunity", "eventMuSaturation", 0.20))
    score = max(-1.0, min(1.0, mu_total / saturation))

    # Availability: a meaningfully negative games_delta (injury/
    # suspension outweighing any return-from-injury credit) means the
    # player is unlikely to take the field soon.  Linear floor rather
    # than a hard cutoff, so a minor ding does not fully zero a player
    # who will plausibly play through it.
    floor_games = max(0.1, cfg.num("opportunity", "availabilityGamesDeltaFloor", 3.0))
    availability = max(0.0, min(1.0, 1.0 + games_delta_total / floor_games))

    return (
        _axis(
            "events",
            score,
            TIER_OBSERVED,
            f"{applied} active event(s), net {mu_total:+.1%} projected-production signal",
        ),
        availability,
    )


def _current_nfl_season(as_of: str) -> int:
    """Calendar NFL season for a date — Sept-Dec -> that year, Jan -> prior
    year.  Mirrors ``src/bdvm/actuals.py``'s ``current_nfl_season`` rule
    (never ``currentDraftYear``, which points a year ahead the whole
    autumn); duplicated as a tiny pure function rather than imported to
    avoid pulling BDVM's heavier actuals module into the FAAB path for
    one date computation.
    """
    d = date.fromisoformat(str(as_of)[:10])
    if d.month >= 3:
        return d.year
    return d.year - 1


def short_term_surplus(
    *,
    sleeper_id: str | None = None,
    player_name: str | None = None,
    config: FaabConfig | None = None,
    today: str | None = None,
) -> dict[str, Any]:
    """The bounded, inspectable short-term signal — in [-1, 1] before
    scaling to board-value units, and the axes that produced it.

    Unweighted mean of every OBSERVED axis (mirrors
    ``consensus_edge.opportunity.assess``'s aggregation — one owner
    convention for "combine independent evidence axes" rather than a
    second one invented here), scaled by ``shortTermSurplusScale``
    (category C: a documented fraction of a typical replacement band,
    not yet fitted) and damped by the events axis' availability factor.
    """
    cfg = config or FaabConfig()
    player_context = _load_playerctx_record(sleeper_id)

    from src.utils.name_clean import normalize_player_name  # noqa: PLC0415

    player_key = normalize_player_name(player_name) if player_name else None

    axes = [role_trend_axis(player_context), depth_rank_axis(player_context, config=cfg)]
    ev_axis, availability = event_axis(player_key, today=today, config=cfg)
    axes.append(ev_axis)

    observed = [a for a in axes if a["tier"] == TIER_OBSERVED and a["score"] is not None]
    if not observed:
        return {
            "surplus": 0.0,
            "hasEvidence": False,
            "availability": availability,
            "axes": axes,
        }

    mean_score = sum(float(a["score"]) for a in observed) / len(observed)
    scale = cfg.num("opportunity", "shortTermSurplusScale", 250.0)
    surplus = mean_score * scale * availability
    return {
        "surplus": surplus,
        "hasEvidence": True,
        "availability": availability,
        "axes": axes,
    }


def retention(dynasty_value: float, *, config: FaabConfig | None = None) -> float:
    """Share of ``short_term_surplus`` that should move the bid.

    Category D — explicitly provisional (directive part VI): flat at
    1.0 (fully additive, no discount) until outcome data from the
    shadow-comparison log exists to fit a real shape.  Its PRESENCE,
    not its initial value, is what keeps a small change in
    ``dynasty_value`` from ever producing a discontinuity in
    ``opportunity_value`` — ``short_term_surplus`` is bounded
    independently of ``dynasty_value``, so this function can only ever
    scale that bounded quantity, never amplify it.
    """
    cfg = config or FaabConfig()
    return max(0.0, min(1.0, cfg.num("opportunity", "retentionFlat", 1.0)))


def opportunity_value(
    dynasty_value: float,
    *,
    sleeper_id: str | None = None,
    player_name: str | None = None,
    config: FaabConfig | None = None,
    today: str | None = None,
) -> dict[str, Any]:
    """The one entry point: dynasty value plus the live opportunity layer.

    Never negative (a below-zero opportunity signal can reduce toward
    ``dynasty_value`` but not below it — the layer names a REASON to
    price a player higher than the slow-moving board says, not a
    reason to price him lower than a value the canonical pipeline
    already stands behind).
    """
    cfg = config or FaabConfig()
    result = short_term_surplus(
        sleeper_id=sleeper_id, player_name=player_name, config=cfg, today=today
    )
    r = retention(dynasty_value, config=cfg)
    surplus = max(0.0, result["surplus"])
    value = float(dynasty_value) + r * surplus
    return {
        "value": value,
        "dynastyValue": float(dynasty_value),
        "shortTermSurplus": round(surplus, 1),
        "retention": r,
        "hasEvidence": result["hasEvidence"],
        "availability": result["availability"],
        "axes": result["axes"],
    }
