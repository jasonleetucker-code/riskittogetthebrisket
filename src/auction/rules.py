"""Room rules / configuration for the rookie auction room.

Two kinds of rule live here and they are deliberately labelled apart:

* **Binding owner rules** (owner directive 2026-09-29) — twelve seats, rookie
  only, six rounds, at most twelve simultaneously open nominations,
  points-for (lowest→highest) nomination order supplied by the owner, $0
  opening bids and $0 wins, whole-dollar positive increments, private
  proxy maxima, per-seat budgets, 08:00–21:00 America/New_York activity.
* **Proposed mock defaults** — everything the owner has NOT yet confirmed for
  an official room (65 active-hour clocks, one-active-hour extension,
  13-active-hour nomination timeout, tie behaviour, withdrawal policy,
  outage policy, the six-rounds-means-six-nominations interpretation).
  Mocks run on them freely.  An official room cannot start until every one
  of them is confirmed on the consolidated rule-confirmation screen
  (``PROPOSED_RULE_KEYS`` / ``confirmations``).
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from src.auction.schedule import ActiveWindow

RULE_VERSION = "rookie-auction-rules-v1"

HOUR = 3600

# Hard input bound for any dollar amount.  Far above any real budget (the
# league pool is ~$1,200) and far below float/int trouble.
MAX_DOLLARS = 1_000_000

BINDING_OWNER_RULES: dict[str, str] = {
    "seats": "12 official manager seats",
    "pool": "Rookie-only auction",
    "rounds": "Six rounds",
    "max_open": "At most 12 simultaneously open nominations",
    "order": "Nomination order by points-for, lowest to highest; the owner supplies/confirms the list",
    "opening_bid": "Opening bid $0; a player can be won for $0; $0-budget managers may participate",
    "increments": "Positive bids in whole $1 increments",
    "proxy": "Private maximum (proxy) bidding: A max $50 vs B max $39 => A leads at $40",
    "budgets": "Individually configurable budgets, initially from current draft-capital data, commissioner overrides",
    "quiet_hours": "Activity pauses 9 PM and resumes 8 AM America/New_York daily",
    "early_end": "End early when every manager's actual draft money has been spent (open auctions drain)",
}

# Proposed mock defaults that an OFFICIAL room must confirm before it starts.
PROPOSED_RULE_KEYS: dict[str, str] = {
    "rounds_meaning": "Six rounds = six nomination opportunities per manager (up to 72 nominations), NOT six purchases; no purchase minimum, no $1-per-slot reserve",
    "order_repeats": "The confirmed nomination order repeats every round (not a snake); the nominator's nomination is a binding $0 bid",
    "auction_clock": "Each auction runs 65 ACTIVE hours (quiet hours excluded)",
    "extension": "A public competitive change in the last active hour extends the clock to at least one active hour from that bid; private ceiling raises never extend",
    "nomination_timeout": "A manager on the nomination clock has 13 active hours, with reminders, then the turn is passed (audited). No automatic substitute nomination or spending",
    "tie_rule": "Equal maxima: the earlier server-accepted bid at that maximum wins",
    "withdrawal": "Non-leaders may disable a future proxy (history is kept); the current leader cannot withdraw and cannot reduce below the binding price",
    "outage": "If the service was unreachable, affected clocks pause; the commissioner resumes with an announced fair remaining window (default at least one active hour)",
    "money_spent_end": "All money spent = every settled balance is $0: stop new nominations, drain open auctions normally, then complete",
    "rights_exhausted_end": "When every nomination opportunity is used or passed, drain open auctions and finish with unspent balances disclosed",
    "commissioner_corrections": "Commissioner corrections are audited compensating events with a reason; never deletion; never revealing hidden maxima",
}

TIMING_PRESETS: dict[str, dict[str, Any]] = {
    # The proposed official shape.
    "official": {
        "auction_active_seconds": 65 * HOUR,
        "extension_active_seconds": 1 * HOUR,
        "nomination_timeout_active_seconds": 13 * HOUR,
        "window": ActiveWindow().to_dict(),
    },
    # Mock rehearsal on real clocks and real quiet hours, but shorter.
    "rehearsal": {
        "auction_active_seconds": 13 * HOUR,
        "extension_active_seconds": 1 * HOUR,
        "nomination_timeout_active_seconds": 4 * HOUR,
        "window": ActiveWindow().to_dict(),
    },
    # Accelerated mock: minutes, no nightly pause.
    "fast": {
        "auction_active_seconds": 10 * 60,
        "extension_active_seconds": 2 * 60,
        "nomination_timeout_active_seconds": 5 * 60,
        "window": ActiveWindow(enabled=False).to_dict(),
    },
}


def default_rules(preset: str = "official") -> dict[str, Any]:
    if preset not in TIMING_PRESETS:
        raise ValueError(f"unknown timing preset {preset!r}")
    rules: dict[str, Any] = {
        "rule_version": RULE_VERSION,
        "timing_preset": preset,
        "seat_count": 12,
        "rounds": 6,
        "max_open": 12,
        "end_when_money_spent": True,
        "tie_rule": "earliest_accepted",
        "withdraw_policy": "non_leader_disable",
        "outage_threshold_seconds": 5 * 60,
        "resume_min_active_seconds": 1 * HOUR,
        "auto_nomination_queue": True,
        "confirmations": {},
    }
    rules.update(deepcopy(TIMING_PRESETS[preset]))
    return rules


def window_of(rules: dict[str, Any]) -> ActiveWindow:
    return ActiveWindow.from_dict(rules.get("window"))


def validate_rules(rules: dict[str, Any]) -> None:
    """Raise ``ValueError`` on a malformed configuration."""

    def pos_int(key: str, *, allow_none: bool = False, minimum: int = 1) -> None:
        v = rules.get(key)
        if v is None and allow_none:
            return
        if isinstance(v, bool) or not isinstance(v, int) or v < minimum:
            raise ValueError(f"rule {key} must be an integer >= {minimum}")

    pos_int("seat_count", minimum=2)
    pos_int("rounds")
    pos_int("max_open")
    pos_int("auction_active_seconds", minimum=60)
    pos_int("extension_active_seconds", minimum=0)
    pos_int("nomination_timeout_active_seconds", allow_none=True, minimum=60)
    pos_int("outage_threshold_seconds", minimum=30)
    pos_int("resume_min_active_seconds", minimum=0)
    if rules.get("seat_count", 0) > 32:
        raise ValueError("seat_count too large")
    if rules.get("rounds", 0) > 20:
        raise ValueError("rounds too large")
    if rules.get("max_open", 0) > 12:
        raise ValueError("at most 12 simultaneously open lots (owner rule)")
    if rules.get("tie_rule") != "earliest_accepted":
        raise ValueError("only the earliest_accepted tie rule is implemented")
    window_of(rules)


def unconfirmed_rules(rules: dict[str, Any]) -> list[str]:
    confirmations = rules.get("confirmations") or {}
    return [k for k in PROPOSED_RULE_KEYS if not confirmations.get(k)]
