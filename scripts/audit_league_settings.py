"""Read-only league-rules drift and fingerprint audit.

Does not modify production configuration. Use --live for one Sleeper host GET
or --snapshot for deterministic archived evidence, explicitly labelled.  Add
--baseline to diff the observed scoring card, key by key, against an archived
card (the registry itself carries no scoring card, so roster-shape MATCH says
nothing about scoring).
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


def canonical_scoring_fingerprint(card: Any) -> str | None:
    """The canonical ``sf1:`` scoring identity, from its single owner.

    ``rules_fingerprint`` below hashes the WHOLE settings block (waiver days,
    invite flags, ...) so it moves on non-scoring edits.  The identity the
    product compares leagues on (CLAUDE.md "factual scoring identity") is
    ``src.league_comparison.sleeper_scoring.scoring_fingerprint``; this script
    imports it rather than re-implementing it, and it returns ``None`` (never
    a hash of ``{}``) when there is no card.
    """
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from src.league_comparison.sleeper_scoring import scoring_fingerprint  # noqa: PLC0415

    return scoring_fingerprint(card)


def scoring_card_diff(baseline: Any, observed: Any) -> dict[str, Any]:
    """Key-by-key comparison of two Sleeper scoring cards.

    Absent and explicit-zero are reported separately (``is_zero``): a key that
    was added at 0.0 changes no rate, which is the same normalisation the
    canonical fingerprint applies.  Non-numeric values raise (fail closed).
    """
    if not isinstance(baseline, dict) or not isinstance(observed, dict):
        raise ValueError("scoring cards must be JSON objects")
    changed: list[dict[str, Any]] = []
    added: list[dict[str, Any]] = []
    removed: list[dict[str, Any]] = []
    for key in sorted(set(baseline) | set(observed)):
        in_base, in_obs = key in baseline, key in observed
        if in_base and in_obs:
            if float(baseline[key]) != float(observed[key]):
                changed.append({"key": key, "baseline": baseline[key], "observed": observed[key]})
        elif in_obs:
            added.append(
                {"key": key, "value": observed[key], "is_zero": float(observed[key]) == 0.0}
            )
        else:
            removed.append(
                {"key": key, "value": baseline[key], "is_zero": float(baseline[key]) == 0.0}
            )
    rate_changes = (
        len(changed)
        + sum(1 for row in added if not row["is_zero"])
        + sum(1 for row in removed if not row["is_zero"])
    )
    return {
        "baseline_keys": len(baseline),
        "observed_keys": len(observed),
        "changed": changed,
        "added": added,
        "removed": removed,
        "rate_changes": rate_changes,
        "status": "SCORING_DRIFT" if rate_changes else "SCORING_MATCH",
    }


def audit(
    registry: dict[str, Any],
    snapshot: dict[str, Any],
    league_id: str,
    baseline: dict[str, Any] | None = None,
) -> dict[str, Any]:
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
    report: dict[str, Any] = {
        "league_id": league_id,
        "league_key": row.get("key"),
        "season": snapshot.get("season"),
        "rules_fingerprint_schema": "league-rules-sha256-v1",
        "rules_fingerprint": fingerprint(snapshot),
        "scoring_fingerprint_sf1": canonical_scoring_fingerprint(snapshot["scoring_settings"]),
        "scoring_keys": len(snapshot["scoring_settings"]),
        "registry_shape": configured,
        "sleeper_shape": observed,
        "drift": drift,
        "status": "DRIFT" if drift else "MATCH",
        "notes": [
            "The registry scoringProfile is a descriptive label, not proof of exact scoring compatibility.",
            "The registry carries NO scoring card, so a MATCH status covers roster shape only; "
            "scoring drift is detected only against an explicit --baseline card.",
            "This audit does not claim the scoring engine consumes every key or validate downstream feature propagation.",
        ],
    }
    if baseline is not None:
        base_id = baseline.get("league_id")
        if base_id is not None and str(base_id) != league_id:
            raise ValueError(f"Baseline league_id {base_id} does not match requested {league_id}")
        diff = scoring_card_diff(baseline.get("scoring_settings"), snapshot["scoring_settings"])
        base_sf1 = canonical_scoring_fingerprint(baseline.get("scoring_settings"))
        diff["baseline_sf1"] = base_sf1
        diff["observed_sf1"] = report["scoring_fingerprint_sf1"]
        report["scoring_baseline"] = diff
    return report


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
    parser.add_argument(
        "--baseline",
        type=Path,
        help="Archived Sleeper league JSON whose scoring card is diffed key by key "
        "against the observed card (e.g. config/league_intel/sleeper_league_snapshot_*.json)",
    )
    parser.add_argument("--timeout", type=int, default=15)
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit 1 if registry and host differ, or the --baseline scoring card has drifted",
    )
    args = parser.parse_args(argv)
    try:
        registry = _read_json(args.registry)
        snapshot = _live(args.league_id, args.timeout) if args.live else _read_json(args.snapshot)
        baseline = _read_json(args.baseline) if args.baseline else None
        report = audit(registry, snapshot, args.league_id, baseline)
        report["evidence_source"] = (
            "LIVE_SLEEPER_API" if args.live else "EXPLICIT_ARCHIVED_SNAPSHOT"
        )
        print(json.dumps(report, indent=2, sort_keys=True))
        scoring_drift = report.get("scoring_baseline", {}).get("status") == "SCORING_DRIFT"
        return int(args.strict and (bool(report["drift"]) or scoring_drift))
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
