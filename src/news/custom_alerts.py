"""User-defined custom alerts.

Two rule kinds are supported:

* ``value_crosses`` — fires when ``rankDerivedValue`` crosses a target.
  Direction is one of ``"above"`` or ``"below"``; the rule fires once
  per cooldown window when the threshold is crossed in the configured
  direction.
* ``rank_change`` — fires when ``canonicalConsensusRank`` shifts by
  more than N positions in either direction (``window_days`` is
  informational only — the rank diff comes from ``rankChange`` on the
  contract row, which the rankings pipeline already stamps).

Cooldown
────────
Each (alertId, playerName) pair carries a ``last_fired_at`` timestamp
in user_kv under ``customAlertsState``.  An alert that just fired
won't fire again for ``COOLDOWN_HOURS`` (24h default), so a daily
cron over the same payload won't send duplicates.

Storage
───────
Rules live in user_kv under ``customAlerts``:

    [
      {
        "id": "...",
        "kind": "value_crosses",
        "displayName": "Caleb Williams",
        "params": {"threshold": 7000, "direction": "above"},
        "channels": ["email", "push"],
        "createdAt": "..."
      },
      ...
    ]

Evaluation
──────────
``evaluate_alerts(rules, players, now=None)`` returns ``Hit`` records
the dispatcher should deliver.  No I/O, no email/push side effects;
the cron handler in server.py wires those up.
"""
from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

_LOGGER = logging.getLogger(__name__)

COOLDOWN_HOURS = 24
SUPPORTED_KINDS = frozenset({"value_crosses", "rank_change"})
SUPPORTED_CHANNELS = frozenset({"email", "push"})


@dataclass
class Hit:
    rule_id: str
    kind: str
    display_name: str
    title: str
    body: str
    state_key: str
    channels: tuple[str, ...]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def new_rule_id() -> str:
    return f"alert_{secrets.token_hex(6)}"


def validate_rule(payload: Any) -> dict[str, Any]:
    """Parse + sanitize a user-submitted rule.  Raises ValueError on
    malformed input.  Returns the canonical rule dict ready to merge
    into ``customAlerts``.
    """
    if not isinstance(payload, dict):
        raise ValueError("rule must be an object")

    kind = str(payload.get("kind") or "").strip()
    if kind not in SUPPORTED_KINDS:
        raise ValueError(f"unknown rule kind: {kind!r}")

    name = str(payload.get("displayName") or "").strip()
    if not name or len(name) > 80:
        raise ValueError("displayName required (≤80 chars)")

    raw_params = payload.get("params") or {}
    if not isinstance(raw_params, dict):
        raise ValueError("params must be an object")

    if kind == "value_crosses":
        try:
            threshold = float(raw_params.get("threshold"))
        except (TypeError, ValueError) as exc:
            raise ValueError("threshold must be numeric") from exc
        direction = str(raw_params.get("direction") or "").lower()
        if direction not in ("above", "below"):
            raise ValueError("direction must be 'above' or 'below'")
        params = {"threshold": int(round(threshold)), "direction": direction}

    else:  # rank_change
        try:
            min_delta = int(raw_params.get("minDelta") or 0)
        except (TypeError, ValueError) as exc:
            raise ValueError("minDelta must be an integer") from exc
        if min_delta < 1 or min_delta > 200:
            raise ValueError("minDelta must be between 1 and 200")
        params = {"minDelta": min_delta}

    if "channels" not in payload:
        raw_channels = ["email"]
    else:
        raw_channels = payload.get("channels")
    if isinstance(raw_channels, str):
        raw_channels = [raw_channels]
    if not isinstance(raw_channels, list):
        raise ValueError("channels must be a list")
    channels = [c for c in raw_channels if c in SUPPORTED_CHANNELS]
    if not channels:
        raise ValueError("at least one valid channel required (email, push)")

    rule_id = str(payload.get("id") or "").strip() or new_rule_id()

    return {
        "id": rule_id,
        "kind": kind,
        "displayName": name,
        "params": params,
        "channels": channels,
        "createdAt": payload.get("createdAt") or _iso(_utc_now()),
    }


def _state_key(rule_id: str, display_name: str) -> str:
    return f"{rule_id}::{display_name.lower()}"


def _is_cooldown(state: dict[str, Any], key: str, now: datetime) -> bool:
    info = state.get(key) or {}
    last = info.get("lastFiredAt")
    if not isinstance(last, str):
        return False
    try:
        last_dt = datetime.strptime(last, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc,
        )
    except ValueError:
        return False
    return now - last_dt < timedelta(hours=COOLDOWN_HOURS)


def _row_for(players_array: list[dict[str, Any]], display_name: str) -> dict[str, Any] | None:
    needle = display_name.strip().lower()
    if not needle:
        return None
    for row in players_array:
        if not isinstance(row, dict):
            continue
        candidates = (
            row.get("displayName"),
            row.get("canonicalName"),
            row.get("name"),
        )
        for c in candidates:
            if isinstance(c, str) and c.strip().lower() == needle:
                return row
    return None


def evaluate_alerts(
    rules: list[dict[str, Any]],
    players_array: list[dict[str, Any]],
    *,
    state: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> list[Hit]:
    """Return Hit records for every rule that fires now.

    ``state`` is the user's ``customAlertsState`` map; the caller is
    expected to update ``state[hit.state_key]["lastFiredAt"]`` after
    a successful dispatch so the cooldown window starts.  This
    function is pure — it does not mutate ``state``.
    """
    if not rules:
        return []
    now = now or _utc_now()
    state = state or {}

    out: list[Hit] = []

    for rule in rules:
        if not isinstance(rule, dict):
            continue
        kind = rule.get("kind")
        if kind not in SUPPORTED_KINDS:
            continue
        display_name = str(rule.get("displayName") or "").strip()
        if not display_name:
            continue
        rule_id = str(rule.get("id") or "")
        skey = _state_key(rule_id, display_name)
        if _is_cooldown(state, skey, now):
            continue

        row = _row_for(players_array, display_name)
        if row is None:
            continue

        params = rule.get("params") or {}
        channels = tuple(rule.get("channels") or ["email"])

        if kind == "value_crosses":
            value = row.get("rankDerivedValue")
            if not isinstance(value, (int, float)):
                continue
            threshold = int(params.get("threshold") or 0)
            direction = str(params.get("direction") or "")
            v = int(round(float(value)))
            crossed = (
                (direction == "above" and v >= threshold)
                or (direction == "below" and v <= threshold)
            )
            if not crossed:
                continue
            arrow = "↑" if direction == "above" else "↓"
            title = f"{display_name} {arrow} {threshold}"
            body = f"Value is now {v:,} (threshold {threshold:,})."
            out.append(Hit(
                rule_id=rule_id,
                kind=kind,
                display_name=display_name,
                title=title,
                body=body,
                state_key=skey,
                channels=channels,
            ))
            continue

        if kind == "rank_change":
            change = row.get("rankChange")
            if not isinstance(change, (int, float)):
                continue
            min_delta = int(params.get("minDelta") or 0)
            if abs(int(change)) < min_delta:
                continue
            rank = row.get("canonicalConsensusRank")
            arrow = "↑" if change > 0 else "↓"
            title = f"{display_name} rank {arrow} {abs(int(change))}"
            body_parts = [f"Rank moved {int(change):+d} positions"]
            if isinstance(rank, int):
                body_parts.append(f"now #{rank}")
            out.append(Hit(
                rule_id=rule_id,
                kind=kind,
                display_name=display_name,
                title=" · ".join(body_parts[:1]),
                body=" · ".join(body_parts) + ".",
                state_key=skey,
                channels=channels,
            ))
            continue

    return out


def mark_fired(state: dict[str, Any], hit: Hit, *, now: datetime | None = None) -> dict[str, Any]:
    """Return a NEW state dict with ``hit.state_key`` updated to the
    current timestamp.  Caller persists into user_kv."""
    now = now or _utc_now()
    new_state = dict(state)
    new_state[hit.state_key] = {"lastFiredAt": _iso(now)}
    return new_state


def prune_state_for_removed_rule(
    state: dict[str, Any], rule_id: str
) -> dict[str, Any]:
    """Drop cooldown entries for a deleted rule so its state_key
    namespace doesn't accumulate forever in user_kv."""
    return {
        k: v for k, v in state.items()
        if not (isinstance(k, str) and k.startswith(f"{rule_id}::"))
    }
