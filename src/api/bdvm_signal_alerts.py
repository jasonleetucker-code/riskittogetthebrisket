"""BDVM market-signal alert tracking (fundamental-vs-market transitions).

Fires when a rostered player's BDVM signal (``src/bdvm/market.py::
buy_hold_sell`` — STRONG_BUY / BUY / HOLD / SELL / STRONG_SELL /
NO_MARKET) flips into an actionable state since the user's last sweep.
Piggybacks on the daily ``/api/signal-alerts/run`` cron (same posture
as ops/source-health alerts: a broken detector degrades to an error
field in the sweep summary, never a failed sweep).

Deliberately a SEPARATE detector from ``signal_alerts.py``:

* Different label sets — the terminal engine speaks RISK/SELL/BUY/
  MONITOR; BDVM speaks STRONG_BUY..STRONG_SELL/NO_MARKET.  Appending
  BDVM entries to the terminal signal list would silently drop
  STRONG_* under the terminal's ACTIONABLE_SIGNALS.
* Different state namespace — ``bdvmSignalAlertStateByLeague`` keyed
  ``bdvm:{playerId}`` so terminal keys (``name::tag`` / ``sid:..``)
  can never collide.

Baseline seeding: the first sweep for a (user, league) — i.e. right
after the ``bdvm_engine`` flag turns on — records every currently
actionable signal WITHOUT firing.  Without this, flag-on day would
flood every user with an alert for each rostered player already
sitting in BUY/SELL.  The seeded entries carry ``notifiedAt: 0`` so a
genuine change right after baseline alerts immediately.

Honesty rules inherited from BDVM: entries only exist for players the
board actually priced; NO_MARKET is an absence, never alerted on; a
non-ok values payload yields zero entries (never fabricated).
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Iterable

from src.api import user_kv as _user_kv

_LOGGER = logging.getLogger(__name__)

# STRONG_* included (unlike the terminal set) — they are BDVM's most
# actionable outputs.  HOLD is stability; NO_MARKET is an absence.
ACTIONABLE_BDVM_SIGNALS = frozenset({"STRONG_BUY", "BUY", "SELL", "STRONG_SELL"})

# Same flicker guard as signal_alerts: BUY → HOLD → BUY inside a half
# day must not spam.
_MIN_NOTIFY_INTERVAL_HOURS: float = 12.0

_STATE_FIELD = "bdvmSignalAlertStateByLeague"


def _utc_now_ms() -> int:
    import time

    return int(time.time() * 1000)


def roster_bdvm_entries(
    values_payload: dict[str, Any] | None,
    roster_player_ids: Iterable[str],
) -> list[dict[str, Any]]:
    """Intersect the whole-league BDVM board with one roster.

    The board is league-wide (every priced player); alerts are
    roster-scoped like every other user alert, so the caller passes
    the user's rostered playerIds (from the BDVM roster analysis).
    Non-ok payloads yield [] — nothing is fabricated.
    """
    if not isinstance(values_payload, dict) or values_payload.get("status") != "ok":
        return []
    wanted = {str(pid) for pid in roster_player_ids or () if str(pid)}
    if not wanted:
        return []
    entries: list[dict[str, Any]] = []
    for player in values_payload.get("players") or []:
        if not isinstance(player, dict):
            continue
        pid = str(player.get("playerId") or "")
        if pid not in wanted:
            continue
        signal_block = player.get("signal") or {}
        market = player.get("market") or {}
        trade_value = player.get("tradeValue") or {}
        entries.append(
            {
                "playerId": pid,
                "name": player.get("name"),
                "pos": player.get("position"),
                "signal": str(signal_block.get("signal") or ""),
                "reason": str(signal_block.get("reason") or ""),
                "gap": market.get("gap"),
                "fundamental": trade_value.get("balanced"),
                "marketValue": market.get("marketValue"),
            }
        )
    return entries


def _load_state(
    user_state: dict[str, Any],
    league_key: str | None,
) -> tuple[dict[str, Any], bool]:
    """Return (league bucket, existed).  ``existed=False`` marks the
    first-ever sweep for this (user, league) — the baseline-seeding
    case.  An empty-but-present bucket counts as existed."""
    by_league = user_state.get(_STATE_FIELD) or {}
    if not isinstance(by_league, dict):
        by_league = {}
    key = str(league_key or "").strip()
    bucket = by_league.get(key)
    if isinstance(bucket, dict):
        return dict(bucket), True
    return {}, False


def _persist_state(
    username: str,
    user_state: dict[str, Any],
    league_key: str | None,
    new_state: dict[str, Any],
    *,
    path: Any = None,
) -> None:
    key = str(league_key or "").strip()
    existing_by_league = user_state.get(_STATE_FIELD) or {}
    if not isinstance(existing_by_league, dict):
        existing_by_league = {}
    # merge_user_state is a shallow top-level merge; nesting one extra
    # level keeps each league's bucket atomic (same shape rationale as
    # signalAlertStateByLeague).
    next_by_league = {**existing_by_league, key: new_state}
    _user_kv.merge_user_state(username, {_STATE_FIELD: next_by_league}, path=path)


def detect_bdvm_transitions(
    username: str,
    entries: list[dict[str, Any]],
    *,
    path: Any = None,
    league_key: str | None = None,
) -> tuple[list[dict[str, Any]], str]:
    """Compare live BDVM signals to last-seen state.

    Returns ``(transitions, mode)`` where mode is:
      * ``"baseline_seeded"`` — first sweep for this (user, league);
        actionable signals recorded silently, nothing fired.
      * ``"ok"`` — normal comparison ran (transitions may be empty).
      * ``"no_entries"`` — nothing to compare (empty roster slice or
        non-ok board); state untouched so a later real first sweep
        still gets baseline treatment.
    """
    if not username or not entries:
        return [], "no_entries"

    user_state = _user_kv.get_user_state(username, path=path)
    alert_state, existed = _load_state(user_state, league_key)

    if not existed:
        seeded = {
            f"bdvm:{e['playerId']}": {"signal": str(e.get("signal") or ""), "notifiedAt": 0}
            for e in entries
            if isinstance(e, dict)
            and e.get("playerId")
            and str(e.get("signal") or "") in ACTIONABLE_BDVM_SIGNALS
        }
        _persist_state(username, user_state, league_key, seeded, path=path)
        return [], "baseline_seeded"

    now = _utc_now_ms()
    min_interval_ms = int(_MIN_NOTIFY_INTERVAL_HOURS * 3600 * 1000)

    transitions: list[dict[str, Any]] = []
    new_state: dict[str, dict[str, Any]] = dict(alert_state)

    for entry in entries:
        if not isinstance(entry, dict):
            continue
        signal = str(entry.get("signal") or "")
        if signal not in ACTIONABLE_BDVM_SIGNALS:
            continue
        pid = str(entry.get("playerId") or "").strip()
        if not pid:
            continue
        state_key = f"bdvm:{pid}"
        prev = alert_state.get(state_key) or {}
        prev_signal = str(prev.get("signal") or "")
        prev_notified_at = int(prev.get("notifiedAt") or 0)
        if prev_signal == signal:
            # Refresh last-seen so a quiet period never re-fires.
            new_state[state_key] = {"signal": signal, "notifiedAt": prev_notified_at}
            continue
        if prev_notified_at and now - prev_notified_at < min_interval_ms:
            new_state[state_key] = {"signal": signal, "notifiedAt": prev_notified_at}
            continue
        transitions.append(
            {
                "signalKey": state_key,
                "playerId": pid,
                "name": entry.get("name"),
                "pos": entry.get("pos"),
                "signal": signal,
                "priorSignal": prev_signal or None,
                "reason": entry.get("reason") or "",
                "gap": entry.get("gap"),
                "fundamental": entry.get("fundamental"),
                "marketValue": entry.get("marketValue"),
            }
        )
        new_state[state_key] = {"signal": signal, "notifiedAt": now}

    # Persist even when nothing fired — last-seen must stay current.
    _persist_state(username, user_state, league_key, new_state, path=path)
    return transitions, "ok"


def _fmt_value(v: Any) -> str:
    if isinstance(v, (int, float)):
        return f"{round(v):,}"
    return "—"


def _fmt_gap(v: Any) -> str:
    if not isinstance(v, (int, float)):
        return "—"
    rounded = round(v)
    return f"+{rounded:,}" if rounded > 0 else f"{rounded:,}"


def format_bdvm_alert_email(
    display_name: str,
    transitions: list[dict[str, Any]],
) -> dict[str, str]:
    """Plain-text digest, same tone as the terminal signal digest."""
    count = len(transitions)
    subject = (
        f"[Brisket] {count} BDVM market signal change{'' if count == 1 else 's'} on your roster"
    )
    lines: list[str] = []
    lines.append(f"Hi {display_name},")
    lines.append("")
    lines.append(
        f"{count} of your players changed fundamental-vs-market signal since your last check:"
    )
    lines.append("")
    for t in transitions:
        arrow = f"{t.get('priorSignal') or '—'} → {t['signal']}"
        lines.append(f"  • {t['name']} ({t.get('pos') or '—'})  {arrow}")
        lines.append(
            f"    fundamental {_fmt_value(t.get('fundamental'))} vs market "
            f"{_fmt_value(t.get('marketValue'))} (gap {_fmt_gap(t.get('gap'))})"
        )
        if t.get("reason"):
            lines.append(f"    {t['reason']}")
    lines.append("")
    lines.append("Full board:  https://chaseupside.com/bdvm")
    lines.append("")
    lines.append("BDVM signals compare projection-driven fundamental value against the")
    lines.append("market (KTC / IDP TradeCalc). They flow from the bdvm_engine feature —")
    lines.append("an operator can switch it off to stop these entirely.")
    lines.append("")
    lines.append("— Risk It")
    return {"subject": subject, "body": "\n".join(lines)}


def process_user_bdvm_alerts(
    username: str,
    *,
    entries: list[dict[str, Any]],
    display_name: str | None = None,
    email: str | None = None,
    delivery: Callable[[str, str, str], bool] | None = None,
    path: Any = None,
    league_key: str | None = None,
) -> dict[str, Any]:
    """End-to-end: detect + deliver.  Mirrors
    ``signal_alerts.process_user_alerts`` — reasons:
    ``baseline_seeded | no_entries | no_transitions | no_email |
    no_delivery_configured | delivery_error:* | ok |
    delivery_returned_false``."""
    transitions, mode = detect_bdvm_transitions(username, entries, path=path, league_key=league_key)
    if mode != "ok":
        return {"transitions": 0, "delivered": False, "reason": mode}
    if not transitions:
        return {"transitions": 0, "delivered": False, "reason": "no_transitions"}
    if not email:
        return {"transitions": len(transitions), "delivered": False, "reason": "no_email"}
    if delivery is None:
        return {
            "transitions": len(transitions),
            "delivered": False,
            "reason": "no_delivery_configured",
        }
    formatted = format_bdvm_alert_email(display_name or username, transitions)
    try:
        ok = delivery(email, formatted["subject"], formatted["body"])
    except Exception as exc:  # noqa: BLE001
        _LOGGER.warning("bdvm signal alert delivery failed for %s: %s", username, exc)
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
