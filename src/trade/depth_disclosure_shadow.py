"""Hidden SHADOW COUNTERS for the low-value depth disclosure (LVA Package 4).

Owner decision 2026-10-21 (``docs/owner/LVA_OWNER_DECISIONS_2026-10-21.md``,
Package 4: "Authorize implementation of the hidden shadow counters behind a
default-OFF flag, with appropriate private access protections.  No user-facing
display or public probing functionality is authorized.  Measure realistic
firing frequencies and false positives, then return for a separate display
decision.").  Design gate G3 (``docs/trade/LOW_VALUE_DEPTH_DISCLOSURE_DESIGN_2026-10-20.md``
§10).

What this does, with ``low_value_depth_disclosure_shadow`` ON: on each private
2-team trade evaluation (the calculator's ``/api/trade/simulate`` and the War
Room's ``/api/trade/analyze``) it asks the one owner
(``src/trade/depth_disclosure.py``) whether the depth note WOULD fire for each
team, and adds the answer to per-league, per-UTC-day, per-surface COUNTS.

What it never does:

* change a response -- the caller passes the finished simulation, this module
  reads it and returns nothing the route uses (byte-identity pinned by test);
* store a name, a value, a gap or a line -- only counts of aggregate buckets
  (outcome / reason, region transition, band pair, piece class, package shape);
* run with the flag OFF -- :func:`record_evaluation` re-checks the flag itself,
  so a forgotten call-site gate still records nothing;
* read Team Context -- the rule reads market (asset-only) fairness, and the War
  Room Team Context integration is held until #1890 is settled.

False-positive evidence it records (design §11 limits): for every team whose
received package holds low-value extras, whether removing them changes its
fairness REGION (``transition:<real>><without>``), the band pair
(``bandPair:<real>><without>`` -- ``fair>slight`` is a band-edge cliff fire),
whether the guard suppressed it, and the piece classes involved.  No outcome or
user evidence exists, so "false positive" is measured only as these proxies.

Counting unit: a DISTINCT trade per (league, UTC day, surface).  The War Room
re-posts on every debounced edit and toggle, so counting requests would weight
a trade by how often its builder iterated.  A repeat of the same trade (same
team, same assets on both sides) that day adds only to ``trade.requests`` /
``trade.repeatRequests``.  The in-memory signature set is never persisted (it
holds hashes of asset ids, not names) and resets on a restart, so a restart can
count a trade twice.

Off the request path: :func:`submit_evaluation` snapshots the few simulation
fields the rule reads and hands them to one background worker, so a request
never waits on the store and the Analyze stage timings are not affected.

Storage: ``data/trade/depth_disclosure_shadow/<leagueKey>.json`` (gitignored,
box-local), aggregate-only, bounded to ``retentionDays`` days.  Read privately
through ``GET /api/trade/depth-disclosure-shadow`` (admin + league member).
"""

from __future__ import annotations

import copy
import hashlib
import json
import logging
import threading
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

from src.trade import depth_disclosure as dd

log = logging.getLogger(__name__)

FLAG = "low_value_depth_disclosure_shadow"
COUNTERS_VERSION = "lvd_shadow_counters_v1"
SURFACES = ("calculator", "war_room")
PERSPECTIVES = ("self", "partner")

REPO_ROOT = Path(__file__).resolve().parents[2]
SHADOW_DIR = REPO_ROOT / "data" / "trade" / "depth_disclosure_shadow"

_lock = threading.Lock()
_LINES_CACHE: OrderedDict[tuple, dd.DepthLines | str] = OrderedDict()
_LINES_CACHE_MAX = 8
#: (league, day, surface) -> trade signatures already counted (hashes only).
_SEEN: dict[tuple[str, str, str], set[str]] = {}
_SEEN_MAX_PER_KEY = 50_000
#: The simulation fields the rule and the evidence gates read.
_SNAPSHOT_KEYS = (
    "team",
    "receiving",
    "sending",
    "unresolvedIn",
    "unresolvedOut",
    "ownedPickChecks",
    "pickOwnership",
    "ownershipEvidence",
)
_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="lvd-shadow")


def enabled() -> bool:
    from src.api import feature_flags  # noqa: PLC0415

    return feature_flags.is_enabled("low_value_depth_disclosure_shadow")


def _path_for(league_key: str, root: Path | None = None) -> Path:
    safe = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in str(league_key))
    return (root or SHADOW_DIR) / f"{safe or 'unknown'}.json"


def _roster_fingerprint(contract: Mapping[str, Any]) -> str:
    sleeper = contract.get("sleeper") if isinstance(contract, Mapping) else None
    teams = sleeper.get("teams") if isinstance(sleeper, Mapping) else None
    parts = []
    for t in teams if isinstance(teams, list) else []:
        if not isinstance(t, Mapping):
            continue
        ol = t.get("optimalLineup") if isinstance(t.get("optimalLineup"), Mapping) else {}
        parts.append(
            [
                str(t.get("ownerId") or t.get("rosterId") or ""),
                sorted(str(p) for p in (t.get("players") or [])),
                sorted(str(p) for p in (ol.get("starters") or [])),
                bool(ol.get("available")),
            ]
        )
    blob = json.dumps(parts, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def lines_for(
    contract: Mapping[str, Any],
    league_key: str,
    roster_settings: Mapping[str, Any] | None,
) -> dd.DepthLines | str:
    """:func:`depth_disclosure.league_depth_lines`, cached per (league, board
    generation, rosters + lineups).  A roster move changes the key, so a stale
    line is never reused."""
    from src.api.trade_analyze_runtime import contract_generation  # noqa: PLC0415

    generation = contract_generation(contract)
    if generation is None:
        # No board stamp: a refresh with unchanged rosters would be invisible
        # to the key, so never reuse a line for an unstamped board.
        return dd.league_depth_lines(contract, league_key, roster_settings)
    key = (
        str(league_key),
        generation,
        _roster_fingerprint(contract),
        json.dumps((roster_settings or {}).get("starters") or {}, sort_keys=True, default=str),
    )
    with _lock:
        if key in _LINES_CACHE:
            _LINES_CACHE.move_to_end(key)
            return _LINES_CACHE[key]
    lines = dd.league_depth_lines(contract, league_key, roster_settings)
    with _lock:
        _LINES_CACHE[key] = lines
        while len(_LINES_CACHE) > _LINES_CACHE_MAX:
            _LINES_CACHE.popitem(last=False)
    return lines


# ── aggregate buckets ─────────────────────────────────────────────────────


def _bucket(n: int, cap: int) -> str:
    return f"{cap}+" if n >= cap else str(n)


def perspective_counters(d: dd.TeamDepthDisclosure) -> dict[str, int]:
    """The aggregate counter increments for one team's would-be note."""
    out: dict[str, int] = {}

    def add(k: str, n: int = 1) -> None:
        out[k] = out.get(k, 0) + n

    add("evaluations")
    add(f"outcome:{d.state}" + (f":{d.reason}" if d.reason else ""))
    if d.extra_groups:
        # A team with low-value extras: the population the false-positive
        # proxies are read over (fires vs the non-firing reasons).
        add("candidates")
        add(f"transition:{d.region}>{d.counterfactual_region}")
        add(f"bandPair:{d.band}>{d.counterfactual_band}")
    if d.fires:
        add("fires")
        for g in d.extra_groups:
            add(f"fire.pieces:{g}")
        add("fire.mix:" + "+".join(sorted(set(d.extra_groups))))
        add(f"fire.extraCount:{_bucket(len(d.extra_groups), 3)}")
        add(
            f"fire.shape:{_bucket(d.received_count, 4)}for{_bucket(d.given_count, 4)}"
        )  # received-for-given
        add(f"fire.transition:{d.region}>{d.counterfactual_region}")
        add(f"fire.bandPair:{d.band}>{d.counterfactual_band}")
    return out


def _merge(into: dict[str, int], add: Mapping[str, int]) -> None:
    for k, n in add.items():
        into[k] = int(into.get(k, 0)) + int(n)


def _empty_store(league_key: str) -> dict[str, Any]:
    return {
        "version": COUNTERS_VERSION,
        "leagueKey": str(league_key),
        "aggregateOnly": True,
        "days": {},
    }


def _load(path: Path, league_key: str) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return _empty_store(league_key)
    except (OSError, ValueError) as exc:
        log.warning("depth-disclosure shadow counters unreadable, starting fresh: %s", exc)
        return _empty_store(league_key)
    if not isinstance(raw, dict) or not isinstance(raw.get("days"), dict):
        return _empty_store(league_key)
    return raw


def _atomic_write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp-{int(time.time() * 1000)}")
    try:
        tmp.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")), "utf-8")
        tmp.replace(path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def trade_signature(simulation: Mapping[str, Any]) -> str:
    """A hash of the team and both sides' asset ids: the same trade asked again
    (another debounce, a Team Context toggle) has the same signature."""

    def refs(side: Any) -> list[str]:
        return sorted(dd._asset_ref(a).lower() for a in side or () if isinstance(a, Mapping))

    team = simulation.get("team") if isinstance(simulation.get("team"), Mapping) else {}
    blob = json.dumps(
        [
            str(team.get("ownerId") or ""),
            refs(simulation.get("receiving")),
            refs(simulation.get("sending")),
        ],
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def _first_sighting(league_key: str, day: str, surface: str, signature: str) -> bool:
    key = (str(league_key), day, surface)
    with _lock:
        for stale in [k for k in _SEEN if k[1] != day]:
            del _SEEN[stale]
        seen = _SEEN.setdefault(key, set())
        if signature in seen:
            return False
        if len(seen) >= _SEEN_MAX_PER_KEY:
            seen.clear()  # bounded; a later repeat may then count twice
        seen.add(signature)
        return True


def submit_evaluation(simulation: Mapping[str, Any], **kwargs: Any) -> None:
    """Snapshot what the rule reads and record it on the background worker.

    Returns at once; never raises.  The snapshot is a deep copy of a few small
    fields, so the route may keep mutating its result (Analyze adds
    ``analysis``) while the worker reads.
    """
    try:
        if not enabled():
            return
        snap = {k: copy.deepcopy(simulation.get(k)) for k in _SNAPSHOT_KEYS if k in simulation}
        _EXECUTOR.submit(record_evaluation, snap, **kwargs)
    except Exception as exc:  # noqa: BLE001 — shadow-only; never break the response
        log.warning("depth-disclosure shadow submit failed: %s", exc)


def flush(timeout: float = 30.0) -> None:
    """Wait for every submitted evaluation (tests; the worker is single)."""
    _EXECUTOR.submit(lambda: None).result(timeout=timeout)


def reset_for_tests() -> None:
    with _lock:
        _SEEN.clear()
        _LINES_CACHE.clear()


def record_evaluation(
    simulation: Mapping[str, Any],
    *,
    contract: Mapping[str, Any],
    league_key: str,
    roster_settings: Mapping[str, Any] | None,
    surface: str,
    now: datetime | None = None,
    root: Path | None = None,
) -> dict[str, Any] | None:
    """Count one private 2-team evaluation.  ``None`` (and nothing written)
    when the flag is OFF or the surface is not a private shadow surface.

    Never raises: a shadow counter must never break or alter a trade response.
    The return value is for tests and logging; no route reads it.
    """
    try:
        if not enabled() or surface not in SURFACES or not league_key:
            return None
        cfg = dd.load_config()
        ts = now or datetime.now(timezone.utc)
        day = ts.astimezone(timezone.utc).date().isoformat()
        increments: dict[str, dict[str, int]] = {}
        trade: dict[str, int] = {"requests": 1}
        if _first_sighting(league_key, day, surface, trade_signature(simulation)):
            lines = lines_for(contract, league_key, roster_settings)
            teams = dd.evaluate_two_team(simulation, lines)
            increments = {p: perspective_counters(teams[p]) for p in PERSPECTIVES}
            trade["trades"] = 1
            n_fire = sum(teams[p].fires for p in PERSPECTIVES)
            if n_fire:
                trade["trades.anyFire"] = 1
            if n_fire == 2:
                trade["trades.bothFire"] = 1
            if all(teams[p].state == dd.STATE_NOT_EVALUATED for p in PERSPECTIVES):
                trade["trades.notEvaluated"] = 1
        else:
            trade["repeatRequests"] = 1

        from src.valuation_math import fairness_bands  # noqa: PLC0415

        retention = int(cfg.get("retentionDays") or 180)
        path = _path_for(league_key, root)
        with _lock:
            store = _load(path, league_key)
            store["disclosureVersion"] = str(cfg["version"])
            store["config"] = {
                k: cfg.get(k) for k in ("rule", "threshold", "includePicks", "guard", "version")
            }
            day_block = store["days"].setdefault(day, {})
            block = day_block.setdefault(surface, {})
            _merge(block.setdefault("trade", {}), trade)
            for p, counts in increments.items():
                _merge(block.setdefault(p, {}), counts)
            _merge(block.setdefault("bandVersions", {}), {str(fairness_bands.CONFIG["version"]): 1})
            cutoff = (ts.astimezone(timezone.utc).date() - timedelta(days=retention)).isoformat()
            for d in [d for d in store["days"] if d < cutoff]:
                del store["days"][d]
            store["updatedAt"] = ts.astimezone(timezone.utc).isoformat()
            _atomic_write(path, store)
        return {"day": day, "surface": surface, "trade": trade, **increments}
    except Exception as exc:  # noqa: BLE001 — shadow-only; never break the response
        log.warning("depth-disclosure shadow counter failed: %s", exc)
        return None


def read_counters(
    league_key: str, *, days: int | None = None, root: Path | None = None
) -> dict[str, Any]:
    """The stored aggregate counters for one league, plus a ``totals`` roll-up
    per surface over the returned days.  Aggregate-only by construction."""
    path = _path_for(league_key, root)
    with _lock:
        store = _load(path, league_key)
    day_keys = sorted(store["days"])
    if days is not None and days > 0:
        day_keys = day_keys[-days:]
    totals: dict[str, dict[str, dict[str, int]]] = {}
    for d in day_keys:
        for surface, block in (store["days"][d] or {}).items():
            tgt = totals.setdefault(surface, {})
            for part, counts in (block or {}).items():
                if isinstance(counts, dict):
                    _merge(tgt.setdefault(part, {}), counts)
    return {
        "version": store.get("version", COUNTERS_VERSION),
        "disclosureVersion": store.get("disclosureVersion"),
        "config": store.get("config"),
        "leagueKey": str(league_key),
        "aggregateOnly": True,
        "updatedAt": store.get("updatedAt"),
        "days": {d: store["days"][d] for d in day_keys},
        "totals": totals,
    }
