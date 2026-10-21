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

Storage: ``data/trade/depth_disclosure_shadow/<leagueKey>.json`` (gitignored,
box-local), aggregate-only, bounded to ``retentionDays`` days.  Read privately
through ``GET /api/trade/depth-disclosure-shadow`` (admin + league member).
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from collections import OrderedDict
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

    key = (
        str(league_key),
        contract_generation(contract),
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
        lines = lines_for(contract, league_key, roster_settings)
        teams = dd.evaluate_two_team(simulation, lines)
        increments = {p: perspective_counters(teams[p]) for p in PERSPECTIVES}
        trade = {"trades": 1}
        n_fire = sum(teams[p].fires for p in PERSPECTIVES)
        if n_fire:
            trade["trades.anyFire"] = 1
        if n_fire == 2:
            trade["trades.bothFire"] = 1
        if all(teams[p].state == dd.STATE_NOT_EVALUATED for p in PERSPECTIVES):
            trade["trades.notEvaluated"] = 1

        from src.valuation_math import fairness_bands  # noqa: PLC0415

        ts = now or datetime.now(timezone.utc)
        day = ts.astimezone(timezone.utc).date().isoformat()
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
            for p in PERSPECTIVES:
                _merge(block.setdefault(p, {}), increments[p])
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
