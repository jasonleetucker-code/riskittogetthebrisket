"""One-shot migration: legacy ``signalAlertState`` →
``signalAlertStateByLeague[defaultLeagueKey]``.

Pre-multi-league users stored their alert cooldown state in a flat
``signalAlertState`` dict.  The multi-league upgrade (PR #273)
introduced ``signalAlertStateByLeague[leagueKey]`` but kept the
legacy field as a read fallback to avoid resetting everyone's
cooldowns.

Now that all users have run through the new write path at least
once, we can migrate any residual legacy state into the default
league's bucket and drop the flat field.  This is a no-op for
anyone who already has the nested shape.

Idempotent — running the migration twice is a no-op.  Every user
is processed independently; a failure on one user doesn't stop
the pass.

Called from:
    POST /api/admin/migrate-signal-state  (admin-gated)
    scripts/migrate_signal_state.py       (one-shot CLI)
"""

from __future__ import annotations

import logging
from typing import Any

from src.api import user_kv

_LOGGER = logging.getLogger(__name__)


def migrate_user(
    username: str,
    *,
    default_league_key: str,
    path: Any = None,
) -> dict[str, Any]:
    """Migrate one user's state.  Returns a diagnostic dict:

    {
      "username": str,
      "action": "migrated" | "skipped" | "noop",
      "reason": str,
      "keys_moved": int,
    }
    """
    # Cheap unlocked pre-check so a user with nothing to migrate is never
    # written; the decision that writes is re-made under the lock below.
    if _plan(user_kv.get_user_state(username, path=path), default_league_key)[0] == "noop":
        return {
            "username": username,
            "action": "noop",
            "reason": "no_legacy_state",
            "keys_moved": 0,
        }

    outcome: list[tuple[str, str, int]] = []

    # Re-plan and apply on the CURRENT state inside the user_kv write lock:
    # rewriting ``signalAlertStateByLeague`` from a copy read earlier
    # discarded a league bucket a concurrent alert sweep had just written.
    def _apply(state: dict[str, Any]) -> None:
        outcome.clear()
        action, reason, keys_moved, next_by_league = _plan(state, default_league_key)
        if next_by_league is not None:
            state["signalAlertStateByLeague"] = next_by_league
        if action != "noop":
            # Drop legacy field — we've captured everything useful.
            state["signalAlertState"] = {}
        outcome.append((action, reason, keys_moved))

    user_kv.mutate_user_state(username, _apply, path=path)
    action, reason, keys_moved = outcome[0]
    return {
        "username": username,
        "action": action,
        "reason": reason,
        "keys_moved": keys_moved,
    }


def _plan(
    state: dict[str, Any], default_league_key: str
) -> tuple[str, str, int, dict[str, Any] | None]:
    """Pure: ``(action, reason, keys_moved, next signalAlertStateByLeague)``.

    ``next`` is ``None`` when the per-league map is left untouched."""
    legacy = state.get("signalAlertState")
    by_league = state.get("signalAlertStateByLeague") or {}
    if not isinstance(by_league, dict):
        by_league = {}

    if not isinstance(legacy, dict) or not legacy:
        return "noop", "no_legacy_state", 0, None
    if (
        default_league_key in by_league
        and isinstance(by_league[default_league_key], dict)
        and by_league[default_league_key]
    ):
        # Already migrated — just drop the legacy field.
        return "skipped", "already_migrated", 0, None

    # Merge legacy into default-league bucket.  If the league bucket
    # already exists, prefer the newer entries per-key (by ``notifiedAt``).
    existing = dict(by_league.get(default_league_key) or {})
    for sig_key, legacy_entry in legacy.items():
        if not isinstance(legacy_entry, dict):
            continue
        new_entry = existing.get(sig_key)
        if not new_entry:
            existing[sig_key] = legacy_entry
            continue
        # Keep the higher notifiedAt timestamp.
        if int(legacy_entry.get("notifiedAt") or 0) > int(new_entry.get("notifiedAt") or 0):
            existing[sig_key] = legacy_entry

    keys_moved = len(existing) - len(by_league.get(default_league_key) or {})
    return "migrated", "ok", keys_moved, {**by_league, default_league_key: existing}


def migrate_all(
    *,
    default_league_key: str,
    path: Any = None,
) -> dict[str, Any]:
    """Run ``migrate_user`` over every user in user_kv.  Returns a
    summary dict with per-action counts + a per-user report."""
    try:
        states = user_kv.all_user_states(path=path)
    except Exception as exc:  # noqa: BLE001
        _LOGGER.warning("signal_state_migration all_user_states failed: %s", exc)
        return {"error": str(exc), "processed": 0, "results": []}

    results: list[dict[str, Any]] = []
    counts: dict[str, int] = {"migrated": 0, "skipped": 0, "noop": 0, "error": 0}
    for username in states or {}:
        try:
            r = migrate_user(
                username,
                default_league_key=default_league_key,
                path=path,
            )
        except Exception as exc:  # noqa: BLE001
            r = {
                "username": username,
                "action": "error",
                "reason": str(exc),
                "keys_moved": 0,
            }
        results.append(r)
        counts[r.get("action", "error")] = counts.get(r.get("action", "error"), 0) + 1

    return {
        "processed": len(results),
        "counts": counts,
        "results": results,
    }
