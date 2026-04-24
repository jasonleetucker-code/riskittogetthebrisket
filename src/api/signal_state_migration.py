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
    state = user_kv.get_user_state(username, path=path)
    legacy = state.get("signalAlertState")
    by_league = state.get("signalAlertStateByLeague") or {}
    if not isinstance(by_league, dict):
        by_league = {}

    if not isinstance(legacy, dict) or not legacy:
        return {
            "username": username,
            "action": "noop",
            "reason": "no_legacy_state",
            "keys_moved": 0,
        }
    if default_league_key in by_league and isinstance(by_league[default_league_key], dict) and by_league[default_league_key]:
        # Already migrated — just drop the legacy field.
        user_kv.merge_user_state(
            username, {"signalAlertState": {}}, path=path,
        )
        return {
            "username": username,
            "action": "skipped",
            "reason": "already_migrated",
            "keys_moved": 0,
        }

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
    next_by_league = {**by_league, default_league_key: existing}

    user_kv.merge_user_state(
        username,
        {
            "signalAlertStateByLeague": next_by_league,
            # Drop legacy field — we've captured everything useful.
            "signalAlertState": {},
        },
        path=path,
    )
    return {
        "username": username,
        "action": "migrated",
        "reason": "ok",
        "keys_moved": keys_moved,
    }


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
    for username in (states or {}):
        try:
            r = migrate_user(
                username, default_league_key=default_league_key, path=path,
            )
        except Exception as exc:  # noqa: BLE001
            r = {
                "username": username, "action": "error",
                "reason": str(exc), "keys_moved": 0,
            }
        results.append(r)
        counts[r.get("action", "error")] = counts.get(r.get("action", "error"), 0) + 1

    return {
        "processed": len(results),
        "counts": counts,
        "results": results,
    }
