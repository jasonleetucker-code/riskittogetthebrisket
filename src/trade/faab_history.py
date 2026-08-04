"""Historical FAAB bid history — fetch, persist, and summarise.

The FAAB engine's market model needs to know how THIS league actually
bids, not how a generic league bids.  Sleeper exposes every completed
``waiver`` / ``free_agent`` transaction with its winning
``settings.waiver_bid``, and leagues chain backwards through
``previous_league_id``, so a dynasty league's whole bidding history is
reachable.

What this module deliberately does differently from
``src/api/faab_analytics.py``
─────────────────────────────────────────────────────────────────────
``faab_analytics`` gates its league average/median on ``bid > 0``.  In
this league 45-64% of completed adds cost exactly $0, so excluding
them reports a median winning bid of 2% of budget when the true median
is 0% — a 200x overstatement that then feeds the old recommender's
league-calibration blend and budget-environment scaling.  **Zero bids
are real bids and are kept here**, and ``zeroBidShare`` is reported
explicitly because "how often does a claim go uncontested" is the
single most important number in the market model.

Everything is normalised to **percent of that season's original
budget**, never dollars: this league ran a $1,000 budget in 2024, $200
in 2025 and $100 in 2026, so raw dollar comparisons across seasons are
meaningless.
"""

from __future__ import annotations

import json
import logging
import statistics
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from src.utils.config_loader import repo_root, save_json

log = logging.getLogger(__name__)

SLEEPER_API = "https://api.sleeper.app/v1"
HISTORY_DIR = repo_root() / "data" / "faab"
_MAX_WEEK = 18
_HTTP_TIMEOUT = 25


def history_path(league_key: str) -> Path:
    """Per-league partition.  Bid history is roster-scoped, therefore
    league-scoped (CLAUDE.md), and two leagues sharing a scoring
    profile have completely different bidding cultures."""
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in str(league_key or "default"))
    return HISTORY_DIR / f"bid_history_{safe}.json"


# ── Fetch ──────────────────────────────────────────────────────────


def _get(url: str) -> Any:
    with urllib.request.urlopen(url, timeout=_HTTP_TIMEOUT) as resp:  # noqa: S310
        return json.loads(resp.read())


def fetch_bid_history(
    sleeper_league_id: str,
    *,
    max_seasons: int = 10,
) -> dict[str, Any]:
    """Walk the league chain backwards and collect every completed
    waiver / free-agent add with its winning bid.

    Network-bound and slow (one request per league-week), so callers
    should persist the result rather than calling this per request.
    Never raises on a single failed week — a mid-chain gap yields a
    shorter history, not an exception.
    """
    seasons: list[dict[str, Any]] = []
    league_id: str | None = str(sleeper_league_id)
    seen: set[str] = set()

    # Sleeper terminates a league chain with either null or the string
    # "0"; walking to "0" is a guaranteed 404 and a misleading log line.
    while (
        league_id
        and league_id not in ("0", "")
        and league_id not in seen
        and len(seasons) < max_seasons
    ):
        seen.add(league_id)
        try:
            league = _get(f"{SLEEPER_API}/league/{league_id}")
        except Exception as exc:  # noqa: BLE001 — a broken chain link ends the walk
            log.warning("faab history: league %s unreadable: %s", league_id, exc)
            break
        if not isinstance(league, dict):
            break

        settings = league.get("settings") or {}
        budget = int(settings.get("waiver_budget") or 0) or 100
        season = str(league.get("season") or "")

        rows: list[dict[str, Any]] = []
        for week in range(1, _MAX_WEEK + 1):
            try:
                txs = _get(f"{SLEEPER_API}/league/{league_id}/transactions/{week}")
            except Exception:  # noqa: BLE001 — week not played yet
                break
            if not isinstance(txs, list):
                break
            for tx in txs:
                if not isinstance(tx, dict):
                    continue
                if tx.get("type") not in ("waiver", "free_agent"):
                    continue
                if tx.get("status") != "complete":
                    continue
                bid = (tx.get("settings") or {}).get("waiver_bid")
                adds = tx.get("adds") or {}
                if bid is None or not isinstance(adds, dict) or not adds:
                    continue
                roster_ids = tx.get("roster_ids") or []
                for player_id in adds:
                    rows.append(
                        {
                            "playerId": str(player_id),
                            "bid": int(bid),
                            "bidPct": 100.0 * float(bid) / float(budget),
                            "week": week,
                            "rosterId": roster_ids[0] if roster_ids else None,
                            "type": str(tx.get("type")),
                            "createdAt": int(tx.get("status_updated") or tx.get("created") or 0),
                        }
                    )

        rosters = []
        try:
            rosters = _get(f"{SLEEPER_API}/league/{league_id}/rosters") or []
        except Exception:  # noqa: BLE001
            rosters = []
        roster_to_owner = {
            r.get("roster_id"): str(r.get("owner_id") or "")
            for r in rosters
            if isinstance(r, dict)
        }
        for row in rows:
            row["ownerId"] = roster_to_owner.get(row.get("rosterId")) or ""

        seasons.append(
            {
                "season": season,
                "leagueId": league_id,
                "budget": budget,
                "teamCount": int(settings.get("num_teams") or 0) or None,
                "adds": rows,
            }
        )
        league_id = league.get("previous_league_id")

    return {
        "schemaVersion": 1,
        "sleeperLeagueId": str(sleeper_league_id),
        "seasons": seasons,
        "totalAdds": sum(len(s["adds"]) for s in seasons),
    }


def save_bid_history(league_key: str, payload: dict[str, Any]) -> Path:
    path = history_path(league_key)
    save_json(path, payload)
    return path


def load_bid_history(league_key: str) -> dict[str, Any] | None:
    """Read the persisted history.  ``None`` when absent or corrupt —
    the engine degrades to its configured priors and says so."""
    path = history_path(league_key)
    try:
        if not path.exists():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 — defensive by contract
        log.warning("faab history read failed (%s): %s", path, exc)
        return None
    return payload if isinstance(payload, dict) else None


# ── Summarise ──────────────────────────────────────────────────────


@dataclass
class MarketPriors:
    """League-fitted market parameters.

    Every field is a percentage of the ORIGINAL budget, so a league
    that changed its budget between seasons still aggregates
    correctly.
    """

    sample_size: int = 0
    zero_bid_share: float = 0.0
    median_pct: float = 0.0
    mean_pct: float = 0.0
    p75_pct: float = 0.0
    p90_pct: float = 0.0
    max_pct: float = 0.0
    nonzero_median_pct: float = 0.0
    owner_aggression: dict[str, float] = field(default_factory=dict)
    owner_sample: dict[str, int] = field(default_factory=dict)
    by_week: dict[int, float] = field(default_factory=dict)
    seasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "sampleSize": self.sample_size,
            "zeroBidShare": round(self.zero_bid_share, 4),
            "medianPct": round(self.median_pct, 3),
            "meanPct": round(self.mean_pct, 3),
            "p75Pct": round(self.p75_pct, 3),
            "p90Pct": round(self.p90_pct, 3),
            "maxPct": round(self.max_pct, 3),
            "nonzeroMedianPct": round(self.nonzero_median_pct, 3),
            "ownerAggression": {k: round(v, 3) for k, v in self.owner_aggression.items()},
            "ownerSample": self.owner_sample,
            "seasons": self.seasons,
        }


def _percentile(sorted_vals: list[float], q: float) -> float:
    if not sorted_vals:
        return 0.0
    idx = min(len(sorted_vals) - 1, max(0, int(round(q * (len(sorted_vals) - 1)))))
    return float(sorted_vals[idx])


def summarize_bid_history(payload: dict[str, Any] | None) -> MarketPriors:
    """Fit the market priors.

    Unlike the legacy analytics summariser this KEEPS $0 bids — they
    are the modal outcome and dropping them is what made the old
    league-calibration signal read ~200x hot.
    """
    priors = MarketPriors()
    if not isinstance(payload, dict):
        return priors

    all_pct: list[float] = []
    by_owner: dict[str, list[float]] = {}
    by_week: dict[int, list[float]] = {}
    seasons: list[str] = []

    for season in payload.get("seasons") or []:
        if not isinstance(season, dict):
            continue
        if season.get("season"):
            seasons.append(str(season["season"]))
        for row in season.get("adds") or []:
            if not isinstance(row, dict):
                continue
            try:
                pct = float(row.get("bidPct"))
            except (TypeError, ValueError):
                continue
            all_pct.append(pct)
            owner = str(row.get("ownerId") or "")
            if owner:
                by_owner.setdefault(owner, []).append(pct)
            try:
                by_week.setdefault(int(row.get("week") or 0), []).append(pct)
            except (TypeError, ValueError):
                pass

    if not all_pct:
        return priors

    all_pct.sort()
    nonzero = [p for p in all_pct if p > 0]

    priors.sample_size = len(all_pct)
    priors.zero_bid_share = 1.0 - (len(nonzero) / len(all_pct))
    priors.median_pct = statistics.median(all_pct)
    priors.mean_pct = statistics.fmean(all_pct)
    priors.p75_pct = _percentile(all_pct, 0.75)
    priors.p90_pct = _percentile(all_pct, 0.90)
    priors.max_pct = all_pct[-1]
    priors.nonzero_median_pct = statistics.median(nonzero) if nonzero else 0.0
    priors.seasons = sorted(set(seasons), reverse=True)

    league_mean = priors.mean_pct or 1.0
    for owner, vals in by_owner.items():
        priors.owner_sample[owner] = len(vals)
        priors.owner_aggression[owner] = (statistics.fmean(vals) / league_mean) if league_mean else 1.0

    for week, vals in by_week.items():
        priors.by_week[week] = statistics.fmean(vals)

    return priors


def owner_aggression_factor(
    priors: MarketPriors,
    owner_id: str,
    *,
    clamp: tuple[float, float] = (0.5, 2.0),
    min_sample: int = 3,
) -> tuple[float, bool]:
    """``(factor, low_sample)`` for one manager.

    Below ``min_sample`` observed adds the manager defaults to neutral
    with ``low_sample=True`` — the engine surfaces that rather than
    pretending to know a tendency from two claims.
    """
    n = priors.owner_sample.get(str(owner_id), 0)
    if n < min_sample:
        return 1.0, True
    factor = priors.owner_aggression.get(str(owner_id), 1.0)
    return max(clamp[0], min(clamp[1], float(factor))), False
