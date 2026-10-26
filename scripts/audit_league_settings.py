"""Read-only league-rules drift and fingerprint audit.

Does not modify production configuration. Use --live for one Sleeper host GET
or --snapshot for deterministic archived evidence, explicitly labelled.
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen

DEFAULT_LEAGUE_ID = "1312006700437352448"
ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REGISTRY = ROOT / "config/leagues/registry.json"
NON_RULE_SETTINGS = frozenset({"leg", "last_scored_leg", "last_report", "daily_waivers_last_ran"})
NON_STARTER_SLOTS = frozenset({"BN", "IR", "TAXI", "RESERVE"})
SLOT_NAMES = {"SFLEX": "SUPER_FLEX"}


def _read_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return data


def _normalized_slot(raw: str) -> str:
    key = str(raw).strip().upper()
    return SLOT_NAMES.get(key, key)


def _registry_league(registry: dict[str, Any], sleeper_id: str) -> dict[str, Any]:
    for row in registry.get("leagues", []):
        if str(row.get("sleeperLeagueId")) == sleeper_id:
            return row
    raise ValueError(f"League {sleeper_id} is not present in the registry")


def _registry_shape(row: dict[str, Any]) -> dict[str, Any]:
    roster = row.get("rosterSettings") or {}
    starters = {
        _normalized_slot(k): int(v) for k, v in (roster.get("starters") or {}).items() if int(v) > 0
    }
    return {
        "teams": int(roster["teamCount"]),
        "roster_size": int(roster["rosterSize"]),
        "taxi_size": int(roster.get("taxiSize", 0)),
        "best_ball": bool(row.get("bestBall")),
        "starters": dict(sorted(starters.items())),
    }


def _host_shape(snapshot: dict[str, Any]) -> dict[str, Any]:
    settings = snapshot.get("settings") or {}
    slots = [_normalized_slot(x) for x in snapshot.get("roster_positions") or []]
    if not slots or not isinstance(snapshot.get("scoring_settings"), dict):
        raise ValueError("Sleeper response missing roster_positions or scoring_settings")
    starters = Counter(x for x in slots if x not in NON_STARTER_SLOTS)
    return {
        "teams": int(settings["num_teams"]),
        "roster_size": len([x for x in slots if x not in {"IR", "TAXI", "RESERVE"}]),
        "taxi_size": int(settings.get("taxi_slots", 0)),
        "best_ball": bool(settings.get("best_ball", 0)),
        "starters": dict(sorted(starters.items())),
    }


def fingerprint(snapshot: dict[str, Any]) -> str:
    """Hash effective Sleeper rules, excluding transient game progress."""
    if not isinstance(snapshot.get("scoring_settings"), dict):
        raise ValueError("Missing Sleeper scoring settings")
    shape = _host_shape(snapshot)
    raw_settings = snapshot.get("settings") or {}
    payload = {
        "schema": "league-rules-sha256-v1",
        "league_id": str(snapshot.get("league_id") or ""),
        "season": str(snapshot.get("season") or ""),
        "shape": shape,
        "scoring_settings": snapshot["scoring_settings"],
        "settings": {k: v for k, v in raw_settings.items() if k not in NON_RULE_SETTINGS},
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def audit(registry: dict[str, Any], snapshot: dict[str, Any], league_id: str) -> dict[str, Any]:
    reported_id = snapshot.get("league_id")
    if reported_id is not None and str(reported_id) != league_id:
        raise ValueError(f"Snapshot league_id {reported_id} does not match requested {league_id}")
    row = _registry_league(registry, league_id)
    configured = _registry_shape(row)
    observed = _host_shape(snapshot)
    drift = [
        {"setting": k, "registry": configured[k], "sleeper": observed[k]}
        for k in configured
        if configured[k] != observed[k]
    ]
    return {
        "league_id": league_id,
        "league_key": row.get("key"),
        "season": snapshot.get("season"),
        "rules_fingerprint_schema": "league-rules-sha256-v1",
        "rules_fingerprint": fingerprint(snapshot),
        "scoring_keys": len(snapshot["scoring_settings"]),
        "registry_shape": configured,
        "sleeper_shape": observed,
        "drift": drift,
        "status": "DRIFT" if drift else "MATCH",
        "notes": [
            "The registry scoringProfile is a descriptive label, not proof of exact scoring compatibility.",
            "This audit does not claim the scoring engine consumes every key or validate downstream feature propagation.",
        ],
    }


def _live(league_id: str, timeout: int) -> dict[str, Any]:
    url = f"https://api.sleeper.app/v1/league/{league_id}"
    with urlopen(url, timeout=timeout) as response:
        result = json.load(response)
    if not isinstance(result, dict):
        raise ValueError("Sleeper API returned a non-object")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--league-id", default=DEFAULT_LEAGUE_ID)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--live", action="store_true", help="Fetch current Sleeper rules; never fall back silently"
    )
    source.add_argument(
        "--snapshot", type=Path, help="Explicit archived JSON file; not a live check"
    )
    parser.add_argument("--timeout", type=int, default=15)
    parser.add_argument("--strict", action="store_true", help="Exit 1 if registry and host differ")
    args = parser.parse_args(argv)
    try:
        registry = _read_json(args.registry)
        snapshot = _live(args.league_id, args.timeout) if args.live else _read_json(args.snapshot)
        report = audit(registry, snapshot, args.league_id)
        report["evidence_source"] = (
            "LIVE_SLEEPER_API" if args.live else "EXPLICIT_ARCHIVED_SNAPSHOT"
        )
        print(json.dumps(report, indent=2, sort_keys=True))
        return int(args.strict and bool(report["drift"]))
    except (OSError, URLError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(
            json.dumps(
                {
                    "status": "UNVERIFIED",
                    "reason": str(exc),
                    "evidence_source": "LIVE_SLEEPER_API"
                    if args.live
                    else "EXPLICIT_ARCHIVED_SNAPSHOT",
                }
            ),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
