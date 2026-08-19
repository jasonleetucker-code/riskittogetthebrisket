"""FAAB v2 — contention-aware rival-bid estimation.

Models the waiver wire as a sealed first-price auction: for each
opponent, estimate the bid they would plausibly place on the add
target, then recommend the minimum that clears the expected top
rival (``clearing = topRival + 1``) — never above the player's own
value ceiling (that gate lives in
``src/trade/faab_recommender.py::recommend_faab``).

Per-opponent expected bid::

    exp_bid = min(base_bid × agg × need_f × intel_f,
                  base_bid × 2.5)          # stacked-multiplier cap
              × 1.15                       # safety margin
    exp_bid = min(exp_bid, opponent.faabRemaining)

Factors
───────
``agg``      Historical aggression: ``clamp(their avgBid ÷ league
             median winning bid, 0.5, 2.0)``.  Requires
             ``winningCount ≥ 3``; below that the owner defaults to
             1.0 with a ``lowSample`` flag.  Winning-bid selection
             bias is irreducible (Sleeper never exposes losing
             bids), so every output here is an ESTIMATE, not a
             prediction — surfaced via ``estimateOnly`` + notes.
``need_f``   Positional need from the existing roster-analysis
             helpers (``src.trade.suggestions.analyze_roster``):
             need → 1.0, neutral → 0.55, surplus → 0.25.
``intel_f``  Cross-league intel from the Insider Trading crawl
             snapshot (league-partitioned:
             ``data/intel/snapshot_<leagueKey>.json``), read
             DEFENSIVELY as plain JSON — no import dependency on
             ``src/intel/`` (which may not be merged/deployed).
             Player-level signal (this owner added THIS player in
             another league recently) → 1.25; position-level signal
             → 1.10; none/missing → 1.0.
"""

from __future__ import annotations

import json
import re
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# ── Tunables ───────────────────────────────────────────────────

# Positional-need multipliers (see module docstring).
NEED_FACTORS: dict[str, float] = {
    "need": 1.0,
    "neutral": 0.55,
    "surplus": 0.25,
}

# Aggression clamp + minimum winning-bid sample to trust an owner's
# historical average.
AGG_CLAMP = (0.5, 2.0)
AGG_MIN_WINNING_BIDS = 3

# Intel multipliers.
INTEL_PLAYER_FACTOR = 1.25
INTEL_POSITION_FACTOR = 1.10

# Stacked-multiplier cap (before margin): no combination of factors
# projects a rival above 2.5× the base value bid.
STACK_CAP_MULT = 2.5

# Sealed-auction safety margin on every rival estimate.
SAFETY_MARGIN = 1.15

# Intel recency window: only add-events inside this window count as
# a live signal (the snapshot itself retains 45 days).
INTEL_WINDOW_MS = 14 * 24 * 3600 * 1000

# Intel snapshot location — SEAM RESOLUTION between #538 (FAAB v2)
# and #534 (Insider Trading): the intel pipeline persists snapshots
# LEAGUE-PARTITIONED at ``data/intel/snapshot_<leagueKey>.json``
# (intel is roster-scoped → league-scoped per CLAUDE.md).  The path
# derivation here must mirror ``src/intel/store.py::snapshot_path``
# — same directory, same ``snapshot_<key>.json`` naming, same key
# sanitisation — WITHOUT importing ``src.intel`` (this module's
# defensive no-import contract; drift is pinned by a parity test in
# tests/trade/test_faab_contention.py).  A legacy single-file
# ``data/intel/snapshot.json`` never shipped; reading it would pin
# ``intel_f`` at 1.0 forever.
_REPO_ROOT = Path(__file__).resolve().parents[2]
INTEL_DATA_DIR = _REPO_ROOT / "data" / "intel"
DEFAULT_INTEL_LEAGUE_KEY = "default"


def intel_snapshot_path(league_key: str | None = None) -> Path:
    """The league's intel snapshot partition (see seam note above)."""
    safe = re.sub(r"[^A-Za-z0-9_-]", "_", str(league_key or DEFAULT_INTEL_LEAGUE_KEY))
    return INTEL_DATA_DIR / f"snapshot_{safe}.json"


# Staleness ceilings (seconds) for the recommend endpoint's
# ``staleInputs`` stamp.  An input is stale when its timestamp is
# missing or older than its ceiling.
STALENESS_MAX_AGE_S: dict[str, float] = {
    "rosters": 24 * 3600,  # overlay refreshes every 15 min; a day means it broke
    "leagueAnalytics": 7 * 24 * 3600,  # public snapshot refresh cadence
    "trending": 3 * 3600,  # adapter TTL is 15 min
    "intel": 48 * 3600,  # intel crawl is daily
}


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


# ── Intel snapshot (defensive, import-free) ────────────────────


def load_intel_snapshot(
    path: Path | None = None,
    league_key: str | None = None,
) -> dict[str, Any] | None:
    """Read the Phase-5 intel snapshot as plain JSON.

    ``league_key`` selects the league's snapshot partition (the FAAB
    endpoint passes its resolved league; snapshots are per-league —
    see the seam note on ``intel_snapshot_path``).  An explicit
    ``path`` wins over ``league_key`` for tests.  Returns ``None``
    when the file is missing, unreadable, or not a JSON object.
    Never raises and never imports ``src.intel`` — the Insider Trading
    may not be merged/deployed alongside this module.
    """
    p = path or intel_snapshot_path(league_key)
    try:
        if not p.exists():
            return None
        raw = json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 — defensive read by contract
        log.warning("intel snapshot read failed (%s): %s", p, exc)
        return None
    return raw if isinstance(raw, dict) else None


def build_intel_index(
    snapshot: dict[str, Any] | None,
    *,
    id_to_position: dict[str, str] | None = None,
    now_ms: int | None = None,
    window_ms: int = INTEL_WINDOW_MS,
) -> dict[str, dict[str, set[str]]]:
    """Index recent intel ADD events per owner.

    Returns ``{ownerId: {"playerIds": set, "positions": set}}`` from
    the snapshot's ``events`` list (shape: ``{ownerId, assetId,
    assetType, action, ts, ...}``).  Positions resolve through the
    caller-supplied ``id_to_position`` map (Sleeper player id →
    normalized position, typically built from the live contract);
    unresolvable ids still register at the player level.
    """
    index: dict[str, dict[str, set[str]]] = {}
    if not isinstance(snapshot, dict):
        return index
    events = snapshot.get("events")
    if not isinstance(events, list):
        return index
    now = int(now_ms if now_ms is not None else time.time() * 1000)
    cutoff = now - int(window_ms)
    pos_map = id_to_position or {}
    for e in events:
        if not isinstance(e, dict):
            continue
        if e.get("action") != "add":
            continue
        if str(e.get("assetType") or "player") != "player":
            continue
        ts = e.get("ts")
        if not isinstance(ts, (int, float)) or ts < cutoff or ts > now:
            continue
        owner = str(e.get("ownerId") or "").strip()
        asset = str(e.get("assetId") or "").strip()
        if not owner or not asset:
            continue
        entry = index.setdefault(owner, {"playerIds": set(), "positions": set()})
        entry["playerIds"].add(asset)
        pos = pos_map.get(asset)
        if pos:
            entry["positions"].add(str(pos).upper())
    return index


def intel_factor(
    intel_index: dict[str, dict[str, set[str]]] | None,
    owner_id: str,
    add_player_id: str | None,
    add_position: str | None,
) -> tuple[float, str]:
    """Return ``(factor, level)`` for one opponent.

    Precedence: player-level (1.25) beats position-level (1.10);
    no signal or no index → (1.0, "none").
    """
    if not intel_index:
        return 1.0, "none"
    entry = intel_index.get(str(owner_id))
    if not isinstance(entry, dict):
        return 1.0, "none"
    if add_player_id and str(add_player_id) in (entry.get("playerIds") or set()):
        return INTEL_PLAYER_FACTOR, "player"
    if add_position and str(add_position).upper() in (entry.get("positions") or set()):
        return INTEL_POSITION_FACTOR, "position"
    return 1.0, "none"


# ── Per-factor helpers ─────────────────────────────────────────


def aggression_factor(
    aggression_entry: dict[str, Any] | None,
    league_median_winning_bid: float | None,
) -> tuple[float, bool]:
    """Return ``(agg, low_sample)`` for one opponent.

    ``agg = clamp(avgBid ÷ league median winning bid, 0.5, 2.0)``,
    requiring ``winningCount ≥ 3``.  Any missing/degenerate input →
    neutral 1.0 with ``low_sample=True``.
    """
    if not isinstance(aggression_entry, dict):
        return 1.0, True
    try:
        winning_count = int(aggression_entry.get("winningCount") or 0)
    except (TypeError, ValueError):
        winning_count = 0
    avg_bid = aggression_entry.get("avgBid")
    if (
        winning_count < AGG_MIN_WINNING_BIDS
        or not isinstance(avg_bid, (int, float))
        or avg_bid <= 0
        or not isinstance(league_median_winning_bid, (int, float))
        or league_median_winning_bid <= 0
    ):
        return 1.0, True
    return _clamp(float(avg_bid) / float(league_median_winning_bid), *AGG_CLAMP), False


def need_level_for(
    opponent_players: list[str],
    add_position: str | None,
    asset_pool: list[Any],
) -> str:
    """Classify one opponent's need at ``add_position``.

    Runs the existing ``analyze_roster`` helper over the opponent's
    roster names against the (unfiltered) asset pool.  Returns
    ``"need"`` / ``"surplus"`` / ``"neutral"`` — a position outside
    the starter-needs map, or an empty roster read, is neutral.
    """
    if not add_position or not opponent_players or not asset_pool:
        return "neutral"
    from src.trade.suggestions import analyze_roster  # noqa: PLC0415 — avoid import cycle at module load

    try:
        analysis = analyze_roster([str(n) for n in opponent_players], asset_pool)
    except Exception as exc:  # noqa: BLE001 — a single bad roster must not kill the estimate
        log.warning("contention roster analysis failed: %s", exc)
        return "neutral"
    pos = str(add_position).upper()
    if pos in analysis.need_positions:
        return "need"
    if pos in analysis.surplus_positions:
        return "surplus"
    return "neutral"


def build_opponent_asset_pool(contract: dict[str, Any]) -> list[Any]:
    """UNFILTERED asset pool for opponent roster analysis.

    ``build_asset_pool_from_contract`` defaults to the blended-board top-150
    quality gate — correct for trade suggestions, wrong here: an
    opponent's depth chart is mostly outside the top 150, and a
    truncated pool would misread every roster as all-need.
    """
    from src.trade.suggestions import build_asset_pool_from_contract  # noqa: PLC0415

    return build_asset_pool_from_contract(contract, board_top_n=0)


def player_position_map(contract: dict[str, Any] | None) -> dict[str, str]:
    """``sleeper player id → position`` from the live contract's
    ``playersArray`` (rows stamp ``playerId``).  Used to resolve
    position-level intel signals."""
    out: dict[str, str] = {}
    if not isinstance(contract, dict):
        return out
    for row in contract.get("playersArray") or []:
        if not isinstance(row, dict):
            continue
        pid = str(row.get("playerId") or "").strip()
        pos = str(row.get("position") or "").strip().upper()
        if pid and pos:
            out[pid] = pos
    return out


# ── Main estimator ─────────────────────────────────────────────


def estimate_rival_bids(
    *,
    base_bid: int,
    add_position: str | None,
    add_player_id: str | None = None,
    opponents: list[dict[str, Any]],
    asset_pool: list[Any] | None = None,
    contract: dict[str, Any] | None = None,
    team_aggression: dict[str, Any] | None = None,
    league_median_winning_bid: float | None = None,
    intel_index: dict[str, dict[str, set[str]]] | None = None,
    intel_available: bool = False,
) -> dict[str, Any]:
    """Estimate every opponent's expected bid on the add target.

    ``opponents`` are Sleeper team dicts (``ownerId``, ``name``,
    ``players``, ``faabRemaining``) — the caller must already have
    excluded the requesting user's own team.  ``team_aggression``
    should be pre-filtered to CURRENT owner ids (departed-owner
    history is looked up per current opponent anyway, so stale
    entries are inert — but filtering keeps the payload honest).

    Returns::

        {
            "topRival": int,          # highest expected rival bid
            "clearing": int,          # topRival + 1
            "perOpponent": [{ownerId, teamName, expBid, faabRemaining,
                             needLevel, aggression, lowSample,
                             intelLevel, capped, balanceUnknown}, ...],
            "estimateOnly": True,     # winning-bid selection bias
            "notes": [str, ...],
        }

    Rows with a missing/non-integer ``faabRemaining`` are flagged
    ``balanceUnknown`` and EXCLUDED from ``topRival``/``clearing`` —
    an unverifiable rival (who might be broke) must never raise the
    user's bid.  Callers should gate on the SHARE of usable balances
    before invoking (the endpoint skips contention entirely when
    fewer than half the rivals carry one).
    """
    notes: list[str] = [
        "Rival bids are estimates from winning-bid history only — "
        "Sleeper never exposes losing bids, so selection bias is irreducible."
    ]
    per_opponent: list[dict[str, Any]] = []

    base = max(0, int(base_bid))
    if base <= 0:
        return {
            "topRival": 0,
            "clearing": 1,
            "perOpponent": [],
            "estimateOnly": True,
            "notes": notes + ["No positive value bid to model rivals against."],
        }

    if asset_pool is None and isinstance(contract, dict):
        asset_pool = build_opponent_asset_pool(contract)
    asset_pool = asset_pool or []

    if not intel_available:
        notes.append("Intel snapshot missing — rival intel factor defaulted to 1.0.")

    aggression = team_aggression or {}
    low_sample_owners: list[str] = []

    for team in opponents or []:
        if not isinstance(team, dict):
            continue
        owner_id = str(team.get("ownerId") or "").strip()
        if not owner_id:
            continue

        agg, low_sample = aggression_factor(
            aggression.get(owner_id),
            league_median_winning_bid,
        )
        if low_sample:
            low_sample_owners.append(owner_id)

        need_level = need_level_for(
            team.get("players") or [],
            add_position,
            asset_pool,
        )
        need_f = NEED_FACTORS.get(need_level, NEED_FACTORS["neutral"])

        intel_f, intel_level = intel_factor(
            intel_index if intel_available else None,
            owner_id,
            add_player_id,
            add_position,
        )

        raw = min(base * agg * need_f * intel_f, base * STACK_CAP_MULT)
        exp = raw * SAFETY_MARGIN

        faab_remaining = team.get("faabRemaining")
        if not isinstance(faab_remaining, int):
            faab_remaining = None
        balance_unknown = faab_remaining is None
        capped = False
        if faab_remaining is not None and exp > faab_remaining:
            exp = float(faab_remaining)
            capped = True

        per_opponent.append(
            {
                "ownerId": owner_id,
                "teamName": str(team.get("name") or ""),
                "expBid": max(0, int(round(exp))),
                "faabRemaining": faab_remaining,
                "needLevel": need_level,
                "aggression": round(agg, 3),
                "lowSample": low_sample,
                "intelLevel": intel_level,
                "capped": capped,
                # An absent balance is unverifiable — the row is shown
                # as an estimate but EXCLUDED from the topRival /
                # clearing math (conservative: a rival that might be
                # broke must never raise the user's bid).
                "balanceUnknown": balance_unknown,
            }
        )

    per_opponent.sort(key=lambda r: -r["expBid"])
    top_rival = max(
        (r["expBid"] for r in per_opponent if not r["balanceUnknown"]),
        default=0,
    )
    unknown_balance_count = sum(1 for r in per_opponent if r["balanceUnknown"])
    if unknown_balance_count:
        notes.append(
            f"{unknown_balance_count} opponent(s) have no visible FAAB balance — "
            "shown as estimates but excluded from the clearing price "
            "(an unverifiable rival must never raise your bid)."
        )
    if low_sample_owners:
        notes.append(
            f"{len(low_sample_owners)} opponent(s) below the "
            f"{AGG_MIN_WINNING_BIDS}-winning-bid sample floor — their "
            "aggression defaulted to neutral (1.0)."
        )

    return {
        "topRival": int(top_rival),
        "clearing": int(top_rival) + 1,
        "perOpponent": per_opponent,
        "estimateOnly": True,
        "notes": notes,
    }


# ── Freshness stamps ───────────────────────────────────────────


def _parse_iso_ts(value: Any) -> float | None:
    """ISO-8601 string → epoch seconds; None on anything unparsable."""
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    try:
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except ValueError:
        return None


def input_age_seconds(as_of: Any, *, now: float | None = None) -> float | None:
    """Age of one stamped input in seconds, or ``None`` when unmeasurable.

    ``None`` covers a missing stamp and an unparsable one alike, and callers
    must treat it as NOT FRESH — unmeasurable freshness is not freshness.
    Kept distinct from a large age so a caller can say *when* an observation
    was made rather than implying it knows.
    """
    ts = _parse_iso_ts(as_of)
    if ts is None:
        return None
    return max(0.0, (time.time() if now is None else float(now)) - ts)


def input_is_stale(key: str, as_of: Any, *, now: float | None = None) -> bool:
    """Is this input past the ceiling ``STALENESS_MAX_AGE_S`` sets for it?

    THE one staleness rule for FAAB inputs, so a consumer of a stamped input
    never invents its own budget.  A key with no configured ceiling is never
    stale (same rule ``stale_inputs`` applies); an unmeasurable age always is.
    """
    max_age = STALENESS_MAX_AGE_S.get(str(key))
    if max_age is None:
        return False
    age = input_age_seconds(as_of, now=now)
    return age is None or age > float(max_age)


def stale_inputs(
    inputs_as_of: dict[str, Any],
    *,
    now: float | None = None,
) -> list[str]:
    """Names of inputs whose timestamp is missing or older than its
    ceiling in ``STALENESS_MAX_AGE_S``.  Keys without a configured
    ceiling are ignored."""
    return [
        key
        for key in STALENESS_MAX_AGE_S
        if key in inputs_as_of and input_is_stale(key, inputs_as_of.get(key), now=now)
    ]
