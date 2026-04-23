"""Signal alert tracking + delivery helpers.

Detects when a roster player's signal flipped into an actionable
state (``RISK`` / ``SELL`` / ``BUY``) since the last run for that
user, and queues a delivery via whatever transport is configured
(email today; push hook scaffolded for later).

State model
-----------
For each (username, signalKey) pair we persist two facts:

* ``last_seen_signal`` — the most recent signal the user saw for
  this player+tag.  Compared against the current signal to decide
  whether to alert.
* ``last_notified_at`` — when we last fired an alert for this
  key, so we don't spam the user if they ignore two evaluations
  in a row.

Both are stored in user_kv under the ``signalAlertState`` key.

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

# Minimum hours between alerts for the same (user, signalKey).  Stops
# a rapid-fire RISK → SELL → RISK flicker from spamming.
_MIN_NOTIFY_INTERVAL_HOURS: float = 12.0


def _utc_now_ms() -> int:
    import time
    return int(time.time() * 1000)


def detect_signal_transitions(
    username: str,
    signals: list[dict[str, Any]],
    *,
    path: Any = None,
) -> list[dict[str, Any]]:
    """Compare the live signal list to the user's last-seen state
    and return the subset that represents a newly-actionable
    transition.

    A transition qualifies when:
      * ``signal in ACTIONABLE_SIGNALS``
      * AND either no prior signal exists OR the prior signal was
        different
      * AND we haven't already notified on this same (key, signal)
        within _MIN_NOTIFY_INTERVAL_HOURS

    Writes the new state back to user_kv.  Returns the list of
    alerts to deliver (the caller actually sends them).
    """
    if not username or not signals:
        return []

    user_state = _user_kv.get_user_state(username, path=path)
    alert_state = user_state.get("signalAlertState") or {}
    if not isinstance(alert_state, dict):
        alert_state = {}

    now = _utc_now_ms()
    min_interval_ms = int(_MIN_NOTIFY_INTERVAL_HOURS * 3600 * 1000)

    transitions: list[dict[str, Any]] = []
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
        # Skip when we notified too recently.
        if prev_notified_at and now - prev_notified_at < min_interval_ms:
            new_state[state_key] = {
                "signal": signal,
                "notifiedAt": prev_notified_at,
            }
            continue
        # Emit a transition.
        transitions.append({
            "signalKey": state_key,
            "name": entry.get("name"),
            "pos": entry.get("pos"),
            "signal": signal,
            "priorSignal": prev_signal or None,
            "reason": entry.get("reason") or "",
            "sleeperId": entry.get("sleeperId") or "",
        })
        new_state[state_key] = {
            "signal": signal,
            "notifiedAt": now,
        }

    # Persist the updated state even when no transitions fired —
    # we still want to remember "last seen" so the first evaluation
    # after a quiet period doesn't flood the user.
    _user_kv.merge_user_state(
        username,
        {"signalAlertState": new_state},
        path=path,
    )
    return transitions


def format_alert_email(
    display_name: str,
    transitions: list[dict[str, Any]],
) -> dict[str, str]:
    """Format the digest email body + subject.  Plain text for
    simplicity and spam-filter friendliness.
    """
    count = len(transitions)
    subject = (
        f"[Brisket] {count} signal update{'' if count == 1 else 's'}"
        f" for your roster"
    )
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
    lines.append("See the terminal:  https://riskittogetthebrisket.org/")
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
    """
    transitions = detect_signal_transitions(username, signals, path=path)
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
        return {
            "transitions": len(transitions),
            "delivered": False,
            "reason": f"delivery_error:{type(exc).__name__}",
        }
    return {
        "transitions": len(transitions),
        "delivered": bool(ok),
        "reason": "ok" if ok else "delivery_returned_false",
    }
