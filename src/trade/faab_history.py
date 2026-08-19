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
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

from src.trade import faab_comparability as _comparability
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
        # MISSING IS NEVER ZERO — and never 100 either (audit 2026-08-17).
        #
        # This was ``int(settings.get("waiver_budget") or 0) or 100``,
        # which is the example this repo's own coercion-gate docstring
        # uses ("An unknown FAAB budget becomes ``or 100``") and it was
        # still live.  ``budget`` is the DENOMINATOR of every ``bidPct``
        # below, and this module's own header records that the league ran
        # **$1,000 in 2024 and $200** in another season — so fabricating
        # 100 does not produce a slightly-off percentage, it produces one
        # wrong by up to 10x, in the priors the recommender bids against.
        #
        # Two distinct unknowns were both being answered with 100:
        #   * the key is ABSENT — we do not know the budget;
        #   * the budget is genuinely 0 — a league with no FAAB, where a
        #     percentage of budget is not a defined quantity at all.
        # Neither is 100.  Both mean "this season cannot contribute a
        # percentage", so the season is skipped with a reason rather than
        # contributing fabricated ones.
        raw_budget = settings.get("waiver_budget")
        try:
            budget = int(raw_budget) if raw_budget is not None else 0
        except (TypeError, ValueError):
            budget = 0
        season = str(league.get("season") or "")
        if budget <= 0:
            log.warning(
                "faab history: league %s (season %s) has no usable waiver_budget (%r) — "
                "skipping; a bid percentage has no denominator here",
                league_id,
                season or "?",
                raw_budget,
            )
            league_id = str(league.get("previous_league_id") or "").strip()
            continue

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
            r.get("roster_id"): str(r.get("owner_id") or "") for r in rosters if isinstance(r, dict)
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
        priors.owner_aggression[owner] = (
            (statistics.fmean(vals) / league_mean) if league_mean else 1.0
        )

    for week, vals in by_week.items():
        priors.by_week[week] = statistics.fmean(vals)

    return priors


# ── Cross-league crowd bids (KTC waiver database) ──────────────────
#
# A SECOND, INDEPENDENT market signal, and deliberately kept separate
# from the Sleeper history above.
#
#   Sleeper history  what OUR league pays.  Full transaction history,
#                    but one league's culture and a small sample.
#   Crowd history    what OTHER leagues pay for the same player, right
#                    now, in comparable formats.  Much wider, but only
#                    a ~5-day 200-row rolling window per fetch, so it
#                    has to be ACCUMULATED — a single scrape is a
#                    snapshot, not a history.
#
# The crowd feed is MyFantasyLeague-only and anonymous; it is a crowd,
# not a panel of experts.  It is used to price the MARKET (how
# contested a claim will be), never to price the PLAYER — our board
# owns that, and letting a hype cycle bid up our own valuation is
# exactly the double-count the engine exists to prevent.

CROWD_RETENTION_DAYS = 120


def crowd_history_path(league_key: str) -> Path:
    """Per-league partition, because the format gate that decides which
    crowd leagues are comparable is a league-format property."""
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in str(league_key or "default"))
    return HISTORY_DIR / f"crowd_history_{safe}.json"


def merge_crowd_rows(
    existing: dict[str, Any] | None,
    rows: Iterable[dict[str, Any]],
    *,
    now_iso: str,
    retention_days: int = CROWD_RETENTION_DAYS,
) -> dict[str, Any]:
    """Accumulate a fetched crowd snapshot into the persisted history.

    Dedup is by the KTC waiver row id, which is stable across fetches —
    the feed re-serves the same recent claims every scrape, so without
    it a 2-hourly refresh would multiply every row by ~60.  Existing
    rows win, so a re-fetch never rewrites history.

    Rows older than ``retention_days`` are pruned on write: bidding
    behaviour drifts across a season, and an unbounded file would let
    2024's market outvote this week's.
    """
    payload: dict[str, Any] = dict(existing or {})
    by_id: dict[str, dict[str, Any]] = {}
    for row in payload.get("rows") or []:
        if isinstance(row, dict) and row.get("id") is not None:
            by_id[str(row["id"])] = row

    added = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        rid = row.get("id")
        if rid is None:
            continue
        key = str(rid)
        if key in by_id:
            continue  # existing wins
        by_id[key] = {**row, "firstSeenAt": now_iso}
        added += 1

    cutoff = _iso_days_before(now_iso, retention_days)
    kept = [r for r in by_id.values() if str(r.get("date") or "") >= cutoff]

    payload["schemaVersion"] = 1
    payload["rows"] = sorted(kept, key=lambda r: str(r.get("date") or ""), reverse=True)
    payload["updatedAt"] = now_iso
    payload["addedLastRun"] = added
    payload["prunedOlderThan"] = cutoff
    return payload


def _iso_days_before(now_iso: str, days: int) -> str:
    """``now - days`` as a date string, for lexicographic comparison
    against the feed's ``YYYY-MM-DDT...`` dates."""
    try:
        base = datetime.fromisoformat(str(now_iso).replace("Z", "+00:00"))
    except ValueError:
        return ""
    return (base - timedelta(days=max(0, int(days)))).date().isoformat()


def load_crowd_history(league_key: str) -> dict[str, Any] | None:
    path = crowd_history_path(league_key)
    try:
        if not path.exists():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 — defensive by contract
        log.warning("crowd history read failed (%s): %s", path, exc)
        return None
    return payload if isinstance(payload, dict) else None


def save_crowd_history(league_key: str, payload: dict[str, Any]) -> Path:
    path = crowd_history_path(league_key)
    save_json(path, payload)
    return path


@dataclass
class CrowdMarket:
    """The external waiver market, as far as we can honestly read it.

    Holds the per-player index AND the provenance a consumer needs to know
    whether it may use it: how fresh the ledger is, which comparability tiers
    the retained rows came from, what was excluded and why, and whether the
    population contains any IDP league at all.

    ``state`` is one of:

    ``fresh``    the ledger was updated inside ``maxFileAgeDays``.
    ``stale``    it exists but has not been refreshed inside that budget.  A
                 snapshot proves when it was taken, not that it is still true
                 (the same posture ``league_registry.scoring_evidence_state``
                 takes), so stale evidence is RETAINED and readable — only its
                 authority expires.
    ``missing``  no ledger, or nothing in it survived classification.

    Only ``fresh`` authorises pricing today's market.
    """

    index: dict[str, dict[str, Any]] = field(default_factory=dict)
    state: str = "missing"
    as_of: str | None = None
    age_days: float | None = None
    rows_total: int = 0
    rows_used: int = 0
    tier_counts: dict[str, int] = field(default_factory=dict)
    excluded_counts: dict[str, int] = field(default_factory=dict)
    prices_idp: bool = False
    target_budget: float | None = None

    @property
    def usable(self) -> bool:
        return self.state == "fresh" and bool(self.index)

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "asOf": self.as_of,
            "ageDays": round(self.age_days, 2) if self.age_days is not None else None,
            "rowsTotal": self.rows_total,
            "rowsUsed": self.rows_used,
            "tierCounts": dict(sorted(self.tier_counts.items())),
            "excludedCounts": dict(sorted(self.excluded_counts.items())),
            "pricesIdp": self.prices_idp,
            "pricedPlayers": len(self.index),
            # Dynasty status of this feed is asserted by the SOURCE, not
            # verified per league — recorded so a consumer can see which kind
            # of evidence it holds (owner spec section 5).
            "dynastyProvenance": _comparability.DYNASTY_PROVENANCE_SOURCE_LEVEL,
        }


def build_crowd_market(
    payload: dict[str, Any] | None,
    *,
    target: "_comparability.TargetFormat | None" = None,
    now_iso: str | None = None,
    policy: "_comparability.ComparabilityPolicy | None" = None,
) -> CrowdMarket:
    """Read the accumulated ledger into a usable, self-describing market.

    Classification runs HERE as well as at fetch time, deliberately.  The feed
    is a rolling window that has to be accumulated, so the ledger outlives any
    single fetch; re-classifying on read means tightening the policy applies to
    rows already stored instead of requiring the ledger to be thrown away and
    rebuilt over months.

    Rows persisted before the format evidence was captured carry no
    ``comparability`` block and no readable settings.  They are RETAINED and
    labelled ``unverified`` rather than discarded: they are real observations
    collected under the older, broader gate, and ``CROWD_RETENTION_DAYS``
    ages them out on its own.  What they may not do is pass as verified.
    """
    pol = policy or _comparability.ComparabilityPolicy()
    market = CrowdMarket(
        target_budget=(target.original_budget if target else None),
    )
    if not isinstance(payload, dict):
        return market

    rows = payload.get("rows")
    rows = rows if isinstance(rows, list) else []
    market.rows_total = len(rows)
    market.as_of = str(payload.get("updatedAt") or "") or None
    market.age_days = _age_days(market.as_of, now_iso)

    kept: list[tuple[dict[str, Any], str]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        tier, reasons = _row_tier(row, target, pol)
        if tier == _comparability.EXCLUDED:
            # ALL failing reasons, matching the fetch-time census.  A row can
            # fail several rules, so these counts can exceed the number of
            # excluded rows — the alternative, reporting only the first, hides
            # the second thing that is wrong with a league.
            for reason in reasons or ("excluded",):
                market.excluded_counts[reason] = market.excluded_counts.get(reason, 0) + 1
            continue
        market.tier_counts[tier] = market.tier_counts.get(tier, 0) + 1
        kept.append((row, tier))

    market.rows_used = len(kept)
    market.prices_idp = any(
        _comparability.source_format_from_settings(r.get("settings")).has_idp_slots is True
        for r, _ in kept
    )
    market.index = _index_rows(kept, target_budget=market.target_budget)

    if not market.index:
        market.state = "missing"
    elif market.age_days is None:
        # No ``updatedAt`` at all: unmeasurable freshness is NOT freshness.
        market.state = "stale"
    else:
        market.state = "fresh" if market.age_days <= pol.max_file_age_days else "stale"
    return market


def _row_tier(
    row: dict[str, Any],
    target: "_comparability.TargetFormat | None",
    policy: "_comparability.ComparabilityPolicy",
) -> tuple[str, tuple[str, ...]]:
    """``(tier, exclusion_reasons)`` for one stored row."""
    stamped = row.get("comparability")
    settings = row.get("settings")
    fmt = _comparability.source_format_from_settings(settings)
    has_evidence = any(
        v is not None
        for v in (fmt.superflex, fmt.tep_level, fmt.rosters_per_player, fmt.original_budget)
    )
    if target is None or not has_evidence:
        # Nothing to judge against, or a pre-stamp row.  Trust an explicit
        # stored exclusion if one exists; otherwise carry it as unverified.
        if isinstance(stamped, dict) and stamped.get("excluded"):
            reasons = stamped.get("reasons") or ["excluded_at_fetch"]
            return _comparability.EXCLUDED, tuple(str(r) for r in reasons)
        return _comparability.TIER_UNVERIFIED, ()
    verdict = _comparability.classify(fmt, target, policy=policy)
    if verdict.excluded:
        return _comparability.EXCLUDED, verdict.reasons or ("excluded",)
    return verdict.tier, ()


def _age_days(as_of: str | None, now_iso: str | None) -> float | None:
    """Age of the ledger in days, or ``None`` when it cannot be measured.

    Unmeasurable is a distinct state from fresh — the caller must not read a
    missing timestamp as a recent one.
    """
    if not as_of:
        return None
    try:
        then = datetime.fromisoformat(str(as_of).replace("Z", "+00:00"))
        now = (
            datetime.fromisoformat(str(now_iso).replace("Z", "+00:00"))
            if now_iso
            else datetime.now(timezone.utc)
        )
    except ValueError:
        return None
    if then.tzinfo is None:
        then = then.replace(tzinfo=timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return max(0.0, (now - then).total_seconds() / 86400.0)


def crowd_evidence_for(
    market: CrowdMarket,
    name: str,
    position: str | None = None,
) -> dict[str, Any] | None:
    """The one accessor the recommender should use.  Fails closed.

    Returns ``None`` — with the reason recorded on the returned market dict by
    the caller, never a silent absence — when:

    * the ledger is stale or missing (owner spec section 10: a stale source is
      never current);
    * the retained population cannot price this position.  Measured on the live
      feed, **no** external league in it starts an individual defensive player,
      so its median is offense-only evidence and section 7 forbids using it as
      an IDP clearing-price comp.

    A refusal is an answer.  Returning a number drawn from the wrong population
    would be indistinguishable from a right one.
    """
    from src.utils.name_clean import compact_name_key  # noqa: PLC0415

    if not isinstance(market, CrowdMarket) or not market.usable:
        return None
    if not _comparability.population_prices_position(position, any_idp_source=market.prices_idp):
        return None
    key = compact_name_key(str(name or ""))
    if not key:
        return None
    return market.index.get(key)


def crowd_refusal_reason(market: CrowdMarket, position: str | None = None) -> str | None:
    """Why ``crowd_evidence_for`` would decline, for the response provenance.

    "We have no crowd price for this player" and "we refuse to quote one from
    the wrong population" must not read the same.
    """
    if not isinstance(market, CrowdMarket):
        return "market_unavailable"
    if market.state == "missing":
        return "no_crowd_ledger"
    if market.state == "stale":
        return "crowd_ledger_stale"
    if not _comparability.population_prices_position(position, any_idp_source=market.prices_idp):
        return "population_cannot_price_idp"
    return None


def crowd_bid_index(payload: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    """``compact_name_key -> {medianPct, maxPct, claims, leagues}``.

    Compatibility wrapper over :func:`build_crowd_market` for callers that want
    the raw per-player index with no target league to classify against and no
    freshness judgement.  New code should use ``build_crowd_market`` +
    ``crowd_evidence_for``, which fail closed on a stale ledger and on a
    population that cannot price the position asked about.
    """
    if not isinstance(payload, dict):
        return {}
    rows = payload.get("rows")
    rows = rows if isinstance(rows, list) else []
    return _index_rows(
        [(r, _comparability.TIER_UNVERIFIED) for r in rows if isinstance(r, dict)],
        target_budget=None,
    )


def _index_rows(
    rows: Sequence[tuple[dict[str, Any], str]],
    *,
    target_budget: float | None,
) -> dict[str, dict[str, Any]]:
    """Aggregate retained crowd rows into a per-player market read.

    Median rather than mean, and **zeros retained**: a $0 add is the modal
    outcome and the single most informative thing the feed says about a player
    — dropping zeros is what made the legacy analytics read a quiet wire as a
    contested one.

    Every retained row contributes on the same footing.  Tiers are carried
    through as a COMPOSITION, not as weights: the owner spec is explicit that
    tier weights are evidence-gated, and no outcome data exists to fit them, so
    inventing one here would be a number nobody validated.
    """
    from src.utils.name_clean import compact_name_key  # noqa: PLC0415

    buckets: dict[str, list[float]] = {}
    leagues: dict[str, set[str]] = {}
    tiers: dict[str, dict[str, int]] = {}
    for row, tier in rows:
        if not isinstance(row, dict):
            continue
        name = row.get("added")
        pct = row.get("bidPct")
        if not name or not isinstance(pct, (int, float)):
            continue
        # Unresolvable KTC ids surface as "Player#1234" — they cannot
        # join our board by name, so they would only add noise.
        if str(name).startswith("Player#"):
            continue
        key = compact_name_key(str(name))
        if not key:
            continue
        buckets.setdefault(key, []).append(float(pct))
        counts = tiers.setdefault(key, {})
        counts[tier] = counts.get(tier, 0) + 1
        lid = str((row.get("settings") or {}).get("leagueId") or "")
        if lid:
            leagues.setdefault(key, set()).add(lid)

    total_claims = sum(len(v) for v in buckets.values()) or 1
    out: dict[str, dict[str, Any]] = {}
    for key, pcts in buckets.items():
        median_pct = round(statistics.median(pcts), 2)
        entry: dict[str, Any] = {
            "medianPct": median_pct,
            "maxPct": round(max(pcts), 2),
            "claims": len(pcts),
            "leagues": len(leagues.get(key, ())),
            # Share of ALL crowd claims in the window that were for this
            # player.  This — not the bid size — is what says "rivals
            # will contest him": a player taking 6% of every add across
            # comparable leagues is demonstrably in demand, however our
            # own board grades him.
            "shareOfClaims": round(len(pcts) / total_claims, 4),
            "tierCounts": dict(sorted(tiers.get(key, {}).items())),
        }
        # The same observation expressed on the asking league's own budget, so
        # a consumer never has to re-derive the conversion (spec section 3).
        equiv = _comparability.equivalent_on_budget(median_pct / 100.0, target_budget)
        if equiv is not None:
            entry["medianEquivalentDollars"] = round(equiv, 2)
        out[key] = entry
    return out


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
