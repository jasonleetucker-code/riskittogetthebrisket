"""Manager-discovery graph for Sharp Tracker.

Sleeper publishes **no global directory** of users or leagues — verified
against the official docs and live. Every read must start from a known
`user_id`, `username`, `league_id`, or `draft_id`. There is therefore no
way to enumerate managers, and any claim of global coverage would be
false.

What IS public and unauthenticated is outward traversal:

    league ──/league/{id}/users──▶ members
    member ──/user/{id}/leagues/nfl/{season}──▶ their other leagues
    …and repeat.

So the cohort is grown as a breadth-first spiderweb from seeds in
``config/sharp/discovery_seeds.json``, compounding each generation.

──────────────────────────────────────────────────────────────────────
Discovery eligibility is NOT signal eligibility
──────────────────────────────────────────────────────────────────────
This distinction is the whole reason this module exists separately from
``src/intel/league_filter.py``, and getting it wrong throws away the
best seeds available.

    DISCOVERY  "can this league introduce us to managers?"
               → almost always yes, including REDRAFT and best-ball.

    SIGNAL     "may this league's trades count as dynasty buy/sell?"
               → dynasty and keeper only (``league_filter.is_eligible``).

A large redraft tournament is one of the *highest-yield* seeds there is:
it places many otherwise-unrelated managers in one place, and most of
them also play dynasty elsewhere. Its own transactions are never
counted — redraft trade behaviour inverts a dynasty signal — but the
user ids it yields are exactly what the graph needs.

The shipped seed is The Megalabowl (2022, ``settings.type = 0``, i.e.
redraft). Under a signal-only filter it would have been discarded and
the graph would never have started. It is marked ``discoveryOnly`` and
traversed for members alone.

──────────────────────────────────────────────────────────────────────
Measured expansion (live, 2026-07-29)
──────────────────────────────────────────────────────────────────────
From the 13 Megalabowl members: 35 distinct 2026 leagues, 20 of them
dynasty/keeper — a branching factor of ~2.7 leagues per user, ~1.5 of
them dynasty. At ~12 members per league that puts generation 2 near 240
users and generation 3 in the thousands, which is why ``maxGenerations``
defaults to 4 rather than something larger: the graph does not need
depth, it needs breadth, and depth is where the call budget goes.

──────────────────────────────────────────────────────────────────────
Operational rules
──────────────────────────────────────────────────────────────────────
* Never runs during a user-facing request. Background job only.
* Hard call budget per run, with a resumable frontier persisted between
  runs, so a partial crawl continues rather than restarting.
* ~0.12s between calls (~500/min) against Sleeper's documented "stay
  under 1000 per minute" — deliberately half the ceiling.
* Every user is keyed on the stable global ``user_id``, never username.
* Discovered users/leagues/memberships land in the shared ledger.
"""

from __future__ import annotations

import json
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Iterable

from src.intel import league_filter, ledger

log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
SEEDS_PATH = REPO_ROOT / "config" / "sharp" / "discovery_seeds.json"
SLEEPER_BASE = "https://api.sleeper.app/v1"

HttpGet = Callable[[str], Any]


@lru_cache(maxsize=4)
def load_seeds(path: str | None = None) -> dict[str, Any]:
    target = Path(path) if path else SEEDS_PATH
    with target.open(encoding="utf-8") as fh:
        return json.load(fh)


def _default_http_get(url: str) -> Any:
    """Live fetch through the sleeper overlay's urllib + circuit-breaker
    plumbing (returns parsed JSON, or None on any failure)."""
    from src.api import sleeper_overlay

    return sleeper_overlay._http_get_json(url)


class _Budget:
    """Hard call cap with an inter-call sleep.

    Same shape as ``src.intel.crawler._CallBudget`` — a crawl that can
    exhaust its budget mid-run must stop cleanly and leave a resumable
    frontier, not raise.
    """

    def __init__(
        self,
        budget: int,
        sleep_s: float,
        http_get: HttpGet,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> None:
        self.remaining = max(0, int(budget))
        self.used = 0
        self._sleep_s = max(0.0, float(sleep_s))
        self._http_get = http_get
        self._sleep_fn = sleep_fn

    def can_call(self) -> bool:
        return self.remaining > 0

    def get(self, url: str) -> Any:
        if self.remaining <= 0:
            return None
        if self.used > 0 and self._sleep_s > 0:
            self._sleep_fn(self._sleep_s)
        self.remaining -= 1
        self.used += 1
        return self._http_get(url)


@dataclass
class DiscoveryResult:
    # KNOWN vs EXPANDED are different populations and conflating them
    # undercounts the cohort.  A manager found at the generation
    # boundary is fully recorded — id, username, membership — and is
    # perfectly scoreable; we simply have not walked THEIR leagues yet.
    # ``users_discovered`` is everyone we know about (the cohort input);
    # ``users_expanded`` is how far the traversal actually reached.
    users_discovered: int = 0
    users_expanded: int = 0
    leagues_discovered: int = 0
    leagues_expanded: int = 0
    signal_eligible_leagues: int = 0
    discovery_only_leagues: int = 0
    calls_used: int = 0
    budget_exhausted: bool = False
    generations_completed: int = 0
    excluded_from_signal: dict[str, int] = field(default_factory=dict)
    frontier_users: list[str] = field(default_factory=list)
    frontier_leagues: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "usersDiscovered": self.users_discovered,
            "usersExpanded": self.users_expanded,
            "leaguesDiscovered": self.leagues_discovered,
            "leaguesExpanded": self.leagues_expanded,
            "signalEligibleLeagues": self.signal_eligible_leagues,
            "discoveryOnlyLeagues": self.discovery_only_leagues,
            "callsUsed": self.calls_used,
            "budgetExhausted": self.budget_exhausted,
            "generationsCompleted": self.generations_completed,
            "excludedFromSignal": self.excluded_from_signal,
            "frontierUsers": len(self.frontier_users),
            "frontierLeagues": len(self.frontier_leagues),
            "errors": self.errors,
        }


def _league_roster_count_ok(league: dict[str, Any], cfg: dict[str, Any]) -> bool:
    """Skip degenerate leagues.

    A 2-team test league yields almost no managers per call, and a
    64-team league is usually a tournament shell whose 'members' are not
    really co-competitors. Both are poor value per request.
    """
    try:
        n = int(league.get("total_rosters") or 0)
    except (TypeError, ValueError):
        return False
    lo = int(cfg.get("minLeagueRosters", 6))
    hi = int(cfg.get("maxLeagueRosters", 32))
    return lo <= n <= hi


def discover(
    *,
    http_get: HttpGet | None = None,
    seeds: dict[str, Any] | None = None,
    budget: int | None = None,
    max_generations: int | None = None,
    ledger_path: Path | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> DiscoveryResult:
    """Run one budgeted BFS expansion and persist what it finds.

    Idempotent against the ledger: users, leagues, and memberships all
    upsert on their primary keys, so re-running discovers nothing new
    rather than duplicating. Returns counts plus the unfinished frontier
    so the next run resumes instead of restarting.
    """
    seeds = seeds or load_seeds()
    trav = seeds.get("traversal") or {}
    limits = seeds.get("limits") or {}
    http = http_get or _default_http_get

    b = _Budget(
        budget if budget is not None else int(trav.get("callBudgetPerRun", 2500)),
        float(trav.get("sleepSecondsBetweenCalls", 0.12)),
        http,
        sleep_fn=sleep_fn,
    )
    max_gen = max_generations if max_generations is not None else int(trav.get("maxGenerations", 4))
    seasons = [str(s) for s in (trav.get("seasons") or ["2026"])]
    per_user_cap = int(trav.get("perUserLeagueCap", 40))
    max_users = int(limits.get("maxUsersPerRun", 20000))
    max_leagues = int(limits.get("maxLeaguesPerRun", 5000))

    result = DiscoveryResult()

    # ``known_users`` is every manager id we have seen at all — the
    # cohort input.  ``seen_users`` is the subset we have EXPANDED
    # (walked their leagues).  The boundary generation lands in the
    # first and not the second, and is still fully usable.
    known_users: set[str] = set()
    seen_users: set[str] = set()
    # Same known/expanded split for leagues.  ``known_leagues`` is also
    # the DEDUP GATE: a popular league surfaces via many members, and
    # counting it once per referrer would inflate every league statistic
    # — the exact double-count this codebase exists to have stamped out.
    known_leagues: set[str] = set()
    seen_leagues: set[str] = set()
    # (id, generation) queues.  Leagues expand into users; users expand
    # into leagues.  Alternating levels is what makes this a spiderweb
    # rather than a single hop.
    league_q: deque[tuple[str, int]] = deque()
    user_q: deque[tuple[str, int]] = deque()

    # Seeds — leagues may be discovery-only (redraft tournaments etc.).
    for entry in seeds.get("seedLeagues") or []:
        lid = str((entry or {}).get("leagueId") or "").strip()
        if lid:
            league_q.append((lid, 0))
    for entry in seeds.get("seedUsers") or []:
        uid = str((entry or {}).get("userId") or "").strip()
        if uid:
            user_q.append((uid, 0))

    users_batch: list[dict[str, Any]] = []
    leagues_batch: list[dict[str, Any]] = []
    memberships: list[tuple[str, str, str | None]] = []
    deepest = 0

    while (league_q or user_q) and b.can_call():
        # ── league -> members ─────────────────────────────────────────
        if league_q:
            lid, gen = league_q.popleft()
            if lid in seen_leagues or gen > max_gen:
                continue
            seen_leagues.add(lid)
            known_leagues.add(lid)
            deepest = max(deepest, gen)
            if len(known_leagues) > max_leagues:
                result.errors.append(f"maxLeaguesPerRun ({max_leagues}) reached — traversal capped")
                break

            members = b.get(f"{SLEEPER_BASE}/league/{lid}/users")
            if not isinstance(members, list):
                result.errors.append(f"league_users_fetch_failed:{lid}")
                continue

            for m in members:
                if not isinstance(m, dict):
                    continue
                uid = str(m.get("user_id") or "").strip()
                if not uid:
                    continue
                memberships.append((lid, uid, None))
                users_batch.append(
                    {
                        "user_id": uid,
                        "username": m.get("username"),
                        "display_name": m.get("display_name"),
                    }
                )
                known_users.add(uid)
                if uid not in seen_users and len(known_users) < max_users:
                    user_q.append((uid, gen + 1))
            continue

        # ── user -> their leagues ─────────────────────────────────────
        uid, gen = user_q.popleft()
        known_users.add(uid)
        if uid in seen_users or gen > max_gen:
            continue
        seen_users.add(uid)
        deepest = max(deepest, gen)

        for season in seasons:
            if not b.can_call():
                break
            raw = b.get(f"{SLEEPER_BASE}/user/{uid}/leagues/nfl/{season}")
            if not isinstance(raw, list):
                result.errors.append(f"user_leagues_fetch_failed:{uid}:{season}")
                continue
            for lg in raw[:per_user_cap]:
                if not isinstance(lg, dict):
                    continue
                lid = str(lg.get("league_id") or "").strip()
                # Gate on KNOWN, not expanded: otherwise a league shared
                # by N members is counted N times before it is ever
                # walked.
                if not lid or lid in known_leagues:
                    continue
                if not _league_roster_count_ok(lg, trav):
                    continue
                known_leagues.add(lid)

                # SIGNAL eligibility is decided here and recorded; it
                # never gates DISCOVERY.  A redraft league still gets
                # traversed for the managers it introduces.
                signal_ok = league_filter.is_eligible(lg)
                if signal_ok:
                    result.signal_eligible_leagues += 1
                else:
                    result.discovery_only_leagues += 1
                    label = league_filter.type_label(lg)
                    result.excluded_from_signal[label] = (
                        result.excluded_from_signal.get(label, 0) + 1
                    )

                settings = lg.get("settings") if isinstance(lg.get("settings"), dict) else {}
                leagues_batch.append(
                    {
                        "league_id": lid,
                        "season": lg.get("season"),
                        "previous_league_id": lg.get("previous_league_id"),
                        "name": lg.get("name"),
                        "total_rosters": lg.get("total_rosters"),
                        "settings_json": json.dumps(
                            {
                                "type": settings.get("type"),
                                "bestBall": settings.get("best_ball"),
                                "signalEligible": signal_ok,
                            }
                        ),
                    }
                )
                league_q.append((lid, gen + 1))

    result.calls_used = b.used
    result.budget_exhausted = not b.can_call() and bool(league_q or user_q)
    result.generations_completed = deepest
    result.users_discovered = len(known_users)
    result.users_expanded = len(seen_users)
    result.leagues_discovered = len(known_leagues)
    result.leagues_expanded = len(seen_leagues)
    result.frontier_users = [u for u, _ in user_q]
    result.frontier_leagues = [lg for lg, _ in league_q]

    # Persist. Every write upserts on a primary key, so a re-run adds
    # nothing rather than duplicating.
    conn = ledger.connect(ledger_path)
    try:
        if users_batch:
            ledger.upsert_users(users_batch, conn=conn)
        if leagues_batch:
            ledger.upsert_leagues(leagues_batch, conn=conn)
        if memberships:
            ledger.upsert_memberships(memberships, conn=conn)
    finally:
        conn.close()

    log.info("sharp.discovery: %s", result.to_dict())
    return result


def signal_eligible_league_ids(
    *,
    ledger_path: Path | None = None,
) -> list[str]:
    """Discovered leagues whose transactions MAY feed the dynasty board.

    Redraft and best-ball leagues are stored (they earned their place by
    introducing managers) but never returned here.
    """
    conn = ledger.connect(ledger_path)
    try:
        rows = conn.execute("SELECT league_id, settings_json FROM leagues").fetchall()
    finally:
        conn.close()
    out = []
    for row in rows:
        try:
            settings = json.loads(row["settings_json"] or "{}")
        except (ValueError, TypeError):
            continue
        if settings.get("signalEligible"):
            out.append(str(row["league_id"]))
    return out


def graph_stats(*, ledger_path: Path | None = None) -> dict[str, Any]:
    """Honest coverage numbers for the Sharp Tracker onboarding copy."""
    conn = ledger.connect(ledger_path)
    try:
        users = conn.execute("SELECT COUNT(*) c FROM sleeper_users").fetchone()["c"]
        leagues = conn.execute("SELECT COUNT(*) c FROM leagues").fetchone()["c"]
        memberships = conn.execute("SELECT COUNT(*) c FROM league_memberships").fetchone()["c"]
    finally:
        conn.close()
    eligible = len(signal_eligible_league_ids(ledger_path=ledger_path))
    return {
        "observedUsers": users,
        "observedLeagues": leagues,
        "signalEligibleLeagues": eligible,
        "discoveryOnlyLeagues": max(0, leagues - eligible),
        "memberships": memberships,
        "complete": False,
        "note": (
            "Grown outward from seed leagues. Sleeper has no global directory, "
            "so this is an observable subset and never all of Sleeper."
        ),
    }


def seed_league_ids(seeds: dict[str, Any] | None = None) -> list[str]:
    seeds = seeds or load_seeds()
    return [
        str((e or {}).get("leagueId"))
        for e in (seeds.get("seedLeagues") or [])
        if (e or {}).get("leagueId")
    ]


def add_seed_leagues(league_ids: Iterable[str], *, path: Path | None = None) -> int:
    """Register newly joined leagues as seeds.

    Every league joined is a new branch of the web, so this is the hook
    that makes the cohort compound over time without a code change.
    """
    target = Path(path) if path else SEEDS_PATH
    with target.open(encoding="utf-8") as fh:
        seeds = json.load(fh)
    existing = {str(e.get("leagueId")) for e in (seeds.get("seedLeagues") or [])}
    added = 0
    for lid in league_ids:
        lid = str(lid).strip()
        if not lid or lid in existing:
            continue
        seeds.setdefault("seedLeagues", []).append({"leagueId": lid, "note": "auto-added"})
        existing.add(lid)
        added += 1
    if added:
        with target.open("w", encoding="utf-8") as fh:
            json.dump(seeds, fh, indent=2)
            fh.write("\n")
        load_seeds.cache_clear()
    return added
