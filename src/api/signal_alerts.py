"""Signal alert tracking + delivery helpers.

Detects when a roster player's signal flipped into an actionable
state (``RISK`` / ``SELL`` / ``BUY``) since the last run for that
user, and queues a delivery via whatever transport is configured
(email today; push hook scaffolded for later).

State model
-----------
For each (username, leagueKey, signalKey) triple we persist two
facts:

* ``last_seen_signal`` — the most recent signal the user saw for
  this player+tag IN THIS LEAGUE.  Compared against the current
  signal to decide whether to alert.
* ``last_notified_at`` — when we last fired an alert for this
  triple, so we don't spam the user if they ignore two evaluations
  in a row.

Stored in user_kv under ``signalAlertStateByLeague[leagueKey]``.
Legacy ``signalAlertState`` (un-nested) is read as a fallback for
the default league only so pre-migration state keeps working —
see ``_load_alert_state``.

Why per-league — the scenario this fixes: a SELL signal fires for
Ja'Marr Chase in league A at 10am → alert sent → same signal
fires for the same user's league B roster at 11am.  Under the old
single-bucket scheme the 12-hour cooldown saw "already notified"
and silently dropped league B's alert.  Nested by league each
cooldown is independent.

Delivery is pluggable — the default ``delivery_email`` uses the
existing ``ALERT_TO`` / ``ALERT_FROM`` / ``ALERT_PASSWORD`` SMTP
settings from ``server.py``.  For each user the function gets
``username, display_name, payload`` where ``payload`` is a structured
dict so tests can inspect what would be delivered without actually
sending mail.

No-op when unauthenticated or when the user doesn't have an email
on record (Sleeper login doesn't collect one today).  The function
structure is also push-notification-ready for later wiring.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from src.api import user_kv as _user_kv

_LOGGER = logging.getLogger(__name__)

# Signals we actually fire notifications for.  HOLD / STRONG_HOLD
# are omitted because "stable" isn't actionable; MONITOR is borderline
# — include it so a user's first-time-flipped-to-MONITOR is surfaced,
# but skip if the user is already MONITORing that player.
ACTIONABLE_SIGNALS = frozenset({"RISK", "SELL", "BUY", "MONITOR"})

# Minimum hours between alerts for the same (user, league, PLAYER).  Stops
# a rapid-fire RISK → SELL → RISK flicker from spamming.  W12-F005: the unit is
# the player, not the rule tag -- a flip that arrives with a different firing
# rule is a different tag-bearing signal key but the same player, and used to
# start a fresh, cooldown-free row (so it fired twice with no prior signal).
_MIN_NOTIFY_INTERVAL_HOURS: float = 12.0

_PLAYER_STATE_PREFIX = "player:"


def _player_state_key(entry: dict[str, Any]) -> str:
    """The per-player cooldown row key (Sleeper id, else normalized name)."""
    sid = str(entry.get("sleeperId") or "").strip()
    if sid:
        return f"{_PLAYER_STATE_PREFIX}sid:{sid}"
    name = " ".join(str(entry.get("name") or "").lower().split())
    return f"{_PLAYER_STATE_PREFIX}name:{name}" if name else ""


def _utc_now_ms() -> int:
    import time

    return int(time.time() * 1000)


def _load_alert_state(
    user_state: dict[str, Any],
    league_key: str | None,
) -> dict[str, Any]:
    """Return the signalAlertState bucket for a specific league.

    Resolution order (each step is also a one-time implicit
    migration — whatever wins the read is what subsequent writes
    use):

      1. ``signalAlertStateByLeague[leagueKey]`` (new shape)
      2. Legacy flat ``signalAlertState`` IF this is the user's
         default-league query (empty league_key or matches
         registry default).  Pre-migration state doesn't lose
         its cooldowns on upgrade.
      3. Empty dict.

    We don't auto-rewrite the legacy field on read — too easy to
    race a concurrent write.  The first write through
    ``detect_signal_transitions`` below stores to the new shape
    and leaves the legacy field alone; on the next read the
    legacy bucket may drift out of date, which is fine because
    once the new shape is populated we never read the legacy one
    again for that league.
    """
    by_league = user_state.get("signalAlertStateByLeague") or {}
    if not isinstance(by_league, dict):
        by_league = {}
    key = str(league_key or "").strip()
    if key and isinstance(by_league.get(key), dict):
        return dict(by_league[key])
    # Legacy fallback — only for the default-league request path.
    # We assume the caller passes "" / None only for default-league
    # scrape runs; a new-league run passes an explicit key and
    # correctly gets an empty state on first evaluation.
    if not key:
        legacy = user_state.get("signalAlertState") or {}
        if isinstance(legacy, dict):
            return dict(legacy)
    return {}


def _next_alert_state(
    user_state: dict[str, Any],
    signals: list[dict[str, Any]],
    league_key: str | None,
    transitions: list[dict[str, Any]],
    written: dict[str, tuple[dict[str, Any] | None, dict[str, Any]]] | None = None,
) -> dict[str, dict[str, Any]]:
    """Pure: the league bucket after this sweep; appends the transitions.

    ``written`` (optional out-param) maps every row an EMITTED transition
    wrote to ``(prior_row_or_None, row_written)`` so a failed delivery can
    put the rows back (``_restore_alert_state``).
    """
    alert_state = _load_alert_state(user_state, league_key)

    now = _utc_now_ms()
    min_interval_ms = int(_MIN_NOTIFY_INTERVAL_HOURS * 3600 * 1000)

    new_state: dict[str, dict[str, Any]] = dict(alert_state)

    for entry in signals:
        if not isinstance(entry, dict):
            continue
        if entry.get("dismissed"):
            continue
        signal = str(entry.get("signal") or "")
        if signal not in ACTIONABLE_SIGNALS:
            continue
        key = str(entry.get("signalKey") or "").strip()
        alias_key = str(entry.get("aliasSignalKey") or "").strip()
        # Use the alias-first key for state tracking so a rename
        # doesn't re-fire the alert.
        state_key = alias_key or key
        if not state_key:
            continue
        prev = alert_state.get(state_key) or {}
        prev_signal = str(prev.get("signal") or "")
        prev_notified_at = int(prev.get("notifiedAt") or 0)
        # Skip when the signal hasn't changed.
        if prev_signal == signal:
            # Still refresh the "last seen" mark so we never re-fire
            # after a quiet period.
            new_state[state_key] = {
                "signal": signal,
                "notifiedAt": prev_notified_at,
            }
            continue
        # The cooldown belongs to the PLAYER (W12-F005).  Read the row from
        # ``new_state`` so a second entry for the same player in one sweep is
        # also held back.
        player_key = _player_state_key(entry)
        player_prev = new_state.get(player_key) or {} if player_key else {}
        player_notified_at = int(player_prev.get("notifiedAt") or 0)
        last_notified_at = max(prev_notified_at, player_notified_at)
        # Skip when we notified too recently.
        if last_notified_at and now - last_notified_at < min_interval_ms:
            new_state[state_key] = {
                "signal": signal,
                "notifiedAt": prev_notified_at,
            }
            continue
        # Emit a transition.  The prior signal is this player's last ALERTED
        # signal even when the firing rule (tag) is new.
        transitions.append(
            {
                "signalKey": state_key,
                "name": entry.get("name"),
                "pos": entry.get("pos"),
                "signal": signal,
                "priorSignal": prev_signal or str(player_prev.get("signal") or "") or None,
                "reason": entry.get("reason") or "",
                "sleeperId": entry.get("sleeperId") or "",
            }
        )
        row = {"signal": signal, "notifiedAt": now}
        new_state[state_key] = dict(row)
        if written is not None:
            written[state_key] = (alert_state.get(state_key), dict(row))
        if player_key:
            new_state[player_key] = dict(row)
            if written is not None:
                written[player_key] = (alert_state.get(player_key), dict(row))

    return new_state


def _store_alert_state(
    user_state: dict[str, Any],
    league_key: str | None,
    new_state: dict[str, dict[str, Any]],
) -> None:
    """Write one league's bucket into ``user_state`` in place.

    Persist the updated state even when no transitions fired -- we still want
    to remember "last seen" so the first evaluation after a quiet period
    doesn't flood the user.

    Storage shape: when a league_key is present, nest under
    ``signalAlertStateByLeague[leagueKey]``, leaving every other league's
    bucket as it is NOW.  When absent (legacy single-league callers) keep
    writing the flat field -- that's what pre-migration state reads on the
    next run.
    """
    key = str(league_key or "").strip()
    if key:
        existing_by_league = user_state.get("signalAlertStateByLeague") or {}
        if not isinstance(existing_by_league, dict):
            existing_by_league = {}
        user_state["signalAlertStateByLeague"] = {**existing_by_league, key: new_state}
    else:
        user_state["signalAlertState"] = new_state


def detect_signal_transitions(
    username: str,
    signals: list[dict[str, Any]],
    *,
    path: Any = None,
    league_key: str | None = None,
) -> list[dict[str, Any]]:
    """Public entry: see ``_detect_signal_transitions`` (docstring below)."""
    return _detect_signal_transitions(username, signals, path=path, league_key=league_key)


def _restore_alert_state(
    username: str,
    league_key: str | None,
    written: dict[str, tuple[dict[str, Any] | None, dict[str, Any]]],
    *,
    path: Any = None,
) -> None:
    """Undo the rows a delivery that FAILED had marked as notified.

    A row is put back only if it still holds exactly what the sweep wrote, so
    a concurrent sweep's newer write is never clobbered.  The transition then
    re-detects on the next sweep (a failed send must not consume the cooldown).
    """

    def _undo(user_state: dict[str, Any]) -> None:
        bucket = _load_alert_state(user_state, league_key)
        for key, (prior, row) in written.items():
            if bucket.get(key) != row:
                continue
            if prior is None:
                bucket.pop(key, None)
            else:
                bucket[key] = prior
        _store_alert_state(user_state, league_key, bucket)

    _user_kv.mutate_user_state(username, _undo, path=path)


def _detect_signal_transitions(
    username: str,
    signals: list[dict[str, Any]],
    *,
    path: Any = None,
    league_key: str | None = None,
    written: dict[str, tuple[dict[str, Any] | None, dict[str, Any]]] | None = None,
) -> list[dict[str, Any]]:
    """Compare the live signal list to the user's last-seen state
    and return the subset that represents a newly-actionable
    transition.

    A transition qualifies when:
      * ``signal in ACTIONABLE_SIGNALS``
      * AND either no prior signal exists OR the prior signal was
        different
      * AND we haven't already notified on this PLAYER (in this league)
        within _MIN_NOTIFY_INTERVAL_HOURS -- whatever the rule tag

    ``league_key`` scopes the cooldown state.  Omitted / empty →
    treated as the legacy single-league path (reads + writes the
    un-nested ``signalAlertState`` for back-compat with pre-
    multi-league deployments).  Passed explicitly for each
    active league during the alert sweep so cooldowns don't
    bleed.

    Writes the new state back to user_kv.  Returns the list of
    alerts to deliver (the caller actually sends them).
    """
    if not username or not signals:
        return []

    transitions: list[dict[str, Any]] = []

    # The whole evaluation runs on the CURRENT state, inside the user_kv write
    # lock: reading first and rewriting the field later discarded whatever
    # another league's (or the migration's) concurrent write put there.
    def _evaluate(user_state: dict[str, Any]) -> None:
        transitions.clear()
        if written is not None:
            written.clear()
        new_state = _next_alert_state(user_state, signals, league_key, transitions, written)
        _store_alert_state(user_state, league_key, new_state)

    _user_kv.mutate_user_state(username, _evaluate, path=path)
    return transitions


def format_alert_email(
    display_name: str,
    transitions: list[dict[str, Any]],
) -> dict[str, str]:
    """Format the digest email body + subject.  Plain text for
    simplicity and spam-filter friendliness.
    """
    count = len(transitions)
    subject = f"[Brisket] {count} signal update{'' if count == 1 else 's'}" f" for your roster"
    lines: list[str] = []
    lines.append(f"Hi {display_name},")
    lines.append("")
    lines.append(f"{count} of your players had a signal change since your last check:")
    lines.append("")
    for t in transitions:
        arrow = f"{t.get('priorSignal') or '—'} → {t['signal']}"
        lines.append(f"  • {t['name']} ({t.get('pos') or '—'})  {arrow}")
        if t.get("reason"):
            lines.append(f"    {t['reason']}")
    lines.append("")
    lines.append("See the terminal:  https://chaseupside.com/")
    lines.append("")
    lines.append("To stop receiving these, sign in and dismiss the signal — it'll be")
    lines.append("suppressed for 7 days.  You can change the alert cadence on /settings.")
    lines.append("")
    lines.append("— Risk It")
    return {"subject": subject, "body": "\n".join(lines)}


def process_user_alerts(
    username: str,
    *,
    signals: list[dict[str, Any]],
    display_name: str | None = None,
    email: str | None = None,
    delivery: Callable[[str, str, str], bool] | None = None,
    path: Any = None,
    league_key: str | None = None,
) -> dict[str, Any]:
    """End-to-end: detect transitions + deliver via ``delivery``.

    Returns a summary dict suitable for logging:

        {
          "transitions":  int,
          "delivered":    bool,
          "reason":       "ok" | "no_transitions" | "no_email" | "delivery_error"
        }

    ``delivery`` is called as ``delivery(to, subject, body) -> bool``
    so tests can pass a stub to inspect the payload without SMTP.

    ``league_key`` scopes the cooldown (see ``detect_signal_transitions``).
    Omitted → legacy single-league behaviour.
    """
    written: dict[str, tuple[dict[str, Any] | None, dict[str, Any]]] = {}
    transitions = _detect_signal_transitions(
        username,
        signals,
        path=path,
        league_key=league_key,
        written=written,
    )
    if not transitions:
        return {"transitions": 0, "delivered": False, "reason": "no_transitions"}
    if not email:
        return {
            "transitions": len(transitions),
            "delivered": False,
            "reason": "no_email",
        }
    if delivery is None:
        # No delivery hook configured — we still did the transition
        # detection (so state writes happen); caller can inspect
        # the dict and deliver later.
        return {
            "transitions": len(transitions),
            "delivered": False,
            "reason": "no_delivery_configured",
        }

    formatted = format_alert_email(display_name or username, transitions)
    try:
        ok = delivery(email, formatted["subject"], formatted["body"])
    except Exception as exc:  # noqa: BLE001
        _LOGGER.warning("signal alert delivery failed for %s: %s", username, exc)
        _restore_alert_state(username, league_key, written, path=path)
        return {
            "transitions": len(transitions),
            "delivered": False,
            "reason": f"delivery_error:{type(exc).__name__}",
        }
    delivered = bool(ok)
    if not delivered:
        _restore_alert_state(username, league_key, written, path=path)
    result: dict[str, Any] = {
        "transitions": len(transitions),
        "delivered": delivered,
        "reason": "ok" if ok else "delivery_returned_false",
    }
    if delivered:
        # W12-F006 (owner decision 2026-11-07): the players this email actually
        # told the user about, by canonical (Sleeper) id -> terminal signal.
        # The BDVM detector reads it to avoid a second email for the same
        # player.  Only a DELIVERED email counts; a transition without a
        # Sleeper id is omitted (no canonical id -> no cross-detector merge).
        result["notifiedPlayerSignals"] = {
            str(t["sleeperId"]): str(t["signal"]) for t in transitions if t.get("sleeperId")
        }
    return result
