"""Per-user betting settings + server-side guardrail enforcement.

Settings are stored per-user in ``user_kv`` under the ``bettingSettings``
key (small preference blob).  Defaults come from
``config/betting_sources.json`` so they can be tuned without code.

Guardrails (all enforced here, never trusted from the client):

1. unit_usd          — default stake per bet
2. per_bet_max_usd   — hard ceiling on any single bet
3. daily_cap_usd     — cap on total stake committed per UTC day
4. require_live_confirm + live_confirmed — real-money (prod) placement
   requires an explicit per-user acknowledgement
5. (manual approval is structural — nothing places without an API call;
   there is no hands-off auto mode)
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "betting_sources.json"

# Fallback defaults if the config file is missing/unreadable.
_HARD_DEFAULTS = {
    "unit_usd": 5.0,
    "per_bet_max_usd": 25.0,
    "daily_cap_usd": 50.0,
    "require_live_confirm": True,
}


def _load_config_defaults() -> dict[str, Any]:
    try:
        with _CONFIG_PATH.open("r", encoding="utf-8") as f:
            cfg = json.load(f)
    except (OSError, json.JSONDecodeError):
        return dict(_HARD_DEFAULTS)
    gd = cfg.get("guardrail_defaults") if isinstance(cfg, dict) else None
    if not isinstance(gd, dict):
        return dict(_HARD_DEFAULTS)
    out = dict(_HARD_DEFAULTS)
    for k in _HARD_DEFAULTS:
        if k in gd:
            out[k] = gd[k]
    return out


def _coerce_positive_float(value: Any, fallback: float) -> float:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return fallback
    return f if f > 0 else fallback


def effective_settings(user_settings: dict[str, Any] | None) -> dict[str, Any]:
    """Merge a user's stored ``bettingSettings`` over the config defaults."""
    defaults = _load_config_defaults()
    us = user_settings if isinstance(user_settings, dict) else {}
    return {
        "unit_usd": _coerce_positive_float(us.get("unit_usd"), defaults["unit_usd"]),
        "per_bet_max_usd": _coerce_positive_float(
            us.get("per_bet_max_usd"), defaults["per_bet_max_usd"]
        ),
        "daily_cap_usd": _coerce_positive_float(us.get("daily_cap_usd"), defaults["daily_cap_usd"]),
        # require_live_confirm is a safety floor: config can require it,
        # and a user cannot turn it off (only satisfy it via live_confirmed).
        "require_live_confirm": bool(defaults["require_live_confirm"]),
        "live_confirmed": bool(us.get("live_confirmed", False)),
    }


def sanitize_settings_patch(body: dict[str, Any]) -> dict[str, Any]:
    """Build a safe ``bettingSettings`` patch from a request body.

    Only the user-tunable fields are accepted; everything else (and any
    attempt to weaken ``require_live_confirm``) is ignored.
    """
    patch: dict[str, Any] = {}
    if "unit_usd" in body:
        patch["unit_usd"] = _coerce_positive_float(body.get("unit_usd"), _HARD_DEFAULTS["unit_usd"])
    if "per_bet_max_usd" in body:
        patch["per_bet_max_usd"] = _coerce_positive_float(
            body.get("per_bet_max_usd"), _HARD_DEFAULTS["per_bet_max_usd"]
        )
    if "daily_cap_usd" in body:
        patch["daily_cap_usd"] = _coerce_positive_float(
            body.get("daily_cap_usd"), _HARD_DEFAULTS["daily_cap_usd"]
        )
    if "live_confirmed" in body:
        patch["live_confirmed"] = bool(body.get("live_confirmed"))
    return patch


@dataclass
class GuardrailResult:
    ok: bool
    error: str = ""
    detail: dict[str, Any] | None = None


def check_bet_allowed(
    *,
    stake_usd: float,
    settings: dict[str, Any],
    committed_today_usd: float,
    is_live: bool,
) -> GuardrailResult:
    """Validate a proposed stake against all guardrails.

    ``settings`` is the output of ``effective_settings``.  ``is_live`` is
    True when ``KALSHI_ENV=prod`` (real money).
    """
    if stake_usd <= 0:
        return GuardrailResult(False, "invalid_stake", {"stake_usd": stake_usd})

    per_bet_max = float(settings.get("per_bet_max_usd", 0))
    if per_bet_max > 0 and stake_usd > per_bet_max:
        return GuardrailResult(
            False,
            "exceeds_per_bet_max",
            {"stake_usd": stake_usd, "per_bet_max_usd": per_bet_max},
        )

    daily_cap = float(settings.get("daily_cap_usd", 0))
    if daily_cap > 0 and (committed_today_usd + stake_usd) > daily_cap:
        return GuardrailResult(
            False,
            "exceeds_daily_cap",
            {
                "stake_usd": stake_usd,
                "committed_today_usd": committed_today_usd,
                "daily_cap_usd": daily_cap,
            },
        )

    if is_live and settings.get("require_live_confirm") and not settings.get("live_confirmed"):
        return GuardrailResult(
            False,
            "live_confirmation_required",
            {"hint": "Set live_confirmed=true in betting settings to enable real-money bets."},
        )

    return GuardrailResult(True)
