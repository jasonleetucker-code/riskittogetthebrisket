"""Signal alert tracking + delivery helpers.

Detects when a roster player's signal flipped into an actionable
state (``RISK`` / ``SELL`` / ``BUY``) since the last run for that
user, and queues a delivery via whatever transport is configured
(email today; push hook scaffolded for later).

State model
-----------
For each (username, leagueKey, PLAYER) triple we persist two
facts:

* ``last_seen_signal`` — the most recent signal the user saw for
  this player IN THIS LEAGUE.  Compared against the current signal
  to decide whether to alert.
* ``last_notified_at`` — when we last fired an alert for this
  triple, so we don't spam the user if they ignore two evaluations
  in a row.

The third element is the PLAYER (``sid:<sleeperId>``), not the
``signalKey``.  The signal keys embed the firing rule's tag, which the
dismissal lifecycle wants and the cooldown must not have: a flip is
precisely when the tag changes, so a tag-keyed cooldown could never
engage on the case it was written for (W12-F005).

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
# but skip if the user is already MONITORing that player.  NO_DATA is
# absent by construction: it is the ENGINE saying it could not measure,
# which is never news about a player.
ACTIONABLE_SIGNALS = frozenset({"RISK", "SELL", "BUY", "MONITOR"})

# Minimum hours between alerts for the same (user, PLAYER).  Stops a
# rapid-fire RISK → SELL → RISK flicker from spamming.
_MIN_NOTIFY_INTERVAL_HOURS: float = 12.0


def _utc_now_ms() -> int:
    import time

    return int(time.time() * 1000)


def _cooldown_key(entry: dict[str, Any]) -> str:
    """Per-PLAYER key for the notification cooldown.

    Deliberately NOT ``signalKey`` / ``aliasSignalKey``.  Both of those
    embed the firing rule's tag (``sid:<id>::<tag>``), which is correct
    for the DISMISSAL lifecycle — a new reason should re-surface a
    player the user dismissed — but fatal for a cooldown: a different
    rule is a different state row, so ``prev_signal`` came back empty,
    the 12-hour branch was skipped entirely, and the alert fired
    immediately.  A flip is exactly when the tag changes, so the
    cooldown never engaged on the case it exists for, and the email
    rendered the reversal as "— → SELL", a first-ever signal (W12-F005).

    Falls back to the display name when Sleeper has no id for the row,
    which is the same identity ladder ``_signal_alias_key`` walks.
    """
    sid = str(entry.get("sleeperId") or "").strip()
    if sid:
        return f"sid:{sid}"
    name = str(entry.get("name") or "").strip().lower()
    return f"name:{name}" if name else ""


def _prev_for_player(
    alert_state: dict[str, Any],
    state_key: str,
    entry: dict[str, Any],
) -> dict[str, Any]:
    """Prior cooldown record for a player, migrating tag-keyed rows.

    Every row written before this key change is ``<player>::<tag>``.
    Ignoring them would drop every stored cooldown on deploy and flood
    the first sweep — the exact failure mode this key change exists to
    prevent — so a player with no player-keyed row inherits the most
    recently notified of their legacy tag rows.  The merged row is
    written back under the player key, so the migration happens once.
    """
    direct = alert_state.get(state_key)
    if isinstance(direct, dict):
        return direct

    prefixes = [f"{state_key}::"]
    name = str(entry.get("name") or "").strip()
    if name:
        prefixes.append(f"{name}::")  # pre-alias display-name keys
    best: dict[str, Any] | None = None
    for key, value in alert_state.items():
        if not isinstance(key, str) or not isinstance(value, dict):
            continue
        if not any(key.startswith(p) for p in prefixes):
            continue
        if best is None or int(value.get("notifiedAt") or 0) > int(best.get("notifiedAt") or 0):
            best = value
    return best or {}


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


def detect_signal_transitions(
    username: str,
    signals: list[dict[str, Any]],
    *,
    path: Any = None,
    league_key: str | None = None,
) -> list[dict[str, Any]]:
    """Compare the live signal list to the user's last-seen state
    and return the subset that represents a newly-actionable
    transition.

    A transition qualifies when:
      * ``signal in ACTIONABLE_SIGNALS``
      * AND either no prior signal exists OR the prior signal was
        different
      * AND we haven't already notified on this same
        (leagueKey, player) within _MIN_NOTIFY_INTERVAL_HOURS —
        keyed on the player, never on the firing rule

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

    user_state = _user_kv.get_user_state(username, path=path)
    alert_state = _load_alert_state(user_state, league_key)

    now = _utc_now_ms()
    min_interval_ms = int(_MIN_NOTIFY_INTERVAL_HOURS * 3600 * 1000)

    transitions: list[dict[str, Any]] = []
    new_state: dict[str, dict[str, Any]] = dict(alert_state)
    fired_this_run: set[str] = set()

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
        # The tag-bearing keys still travel with the transition (the UI
        # dismissal lifecycle is keyed on them), but the cooldown is
        # keyed on the PLAYER — see ``_cooldown_key``.
        dismissal_key = alias_key or key
        state_key = _cooldown_key(entry) or dismissal_key
        if not state_key:
            continue
        if state_key in fired_this_run:
            # The same player can appear twice in one payload (an
            # offense row and an IDP row for a two-way player).  One
            # player, one alert, one line in the digest.
            continue
        prev = _prev_for_player(alert_state, state_key, entry)
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
        fired_this_run.add(state_key)
        transitions.append(
            {
                "signalKey": dismissal_key or state_key,
                "cooldownKey": state_key,
                "name": entry.get("name"),
                "pos": entry.get("pos"),
                "signal": signal,
                "priorSignal": prev_signal or None,
                "reason": entry.get("reason") or "",
                "sleeperId": entry.get("sleeperId") or "",
            }
        )
        new_state[state_key] = {
            "signal": signal,
            "notifiedAt": now,
        }

    # Persist the updated state even when no transitions fired —
    # we still want to remember "last seen" so the first evaluation
    # after a quiet period doesn't flood the user.
    #
    # Storage shape: when a league_key is present, nest under
    # ``signalAlertStateByLeague[leagueKey]``.  When absent (legacy
    # single-league callers) keep writing the flat field — that's
    # what pre-migration state reads on the next run.
    key = str(league_key or "").strip()
    if key:
        # Merge with whatever other leagues are already stored so
        # we don't clobber them.  ``merge_user_state`` does shallow
        # dict-merge at the top level, so nesting one extra level
        # means each league's bucket updates atomically.
        existing_by_league = user_state.get("signalAlertStateByLeague") or {}
        if not isinstance(existing_by_league, dict):
            existing_by_league = {}
        next_by_league = {**existing_by_league, key: new_state}
        _user_kv.merge_user_state(
            username,
            {"signalAlertStateByLeague": next_by_league},
            path=path,
        )
    else:
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
    # Count PLAYERS, not rows.  One player can hold two rows in a
    # payload (offense + IDP for a two-way player), and the digest used
    # to report "2 of your players had a signal change" for one player.
    seen: set[str] = set()
    for t in transitions:
        ident = str(t.get("cooldownKey") or t.get("sleeperId") or t.get("name") or "").strip()
        seen.add(ident.lower())
    count = len(seen) or len(transitions)
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
    transitions = detect_signal_transitions(
        username,
        signals,
        path=path,
        league_key=league_key,
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
