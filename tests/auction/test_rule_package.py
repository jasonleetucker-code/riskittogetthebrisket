"""The owner's consolidated rule-confirmation package covers every proposed
rule the launch checklist names — including open trade offers — and an
official room cannot start while any of them is unconfirmed."""

from __future__ import annotations

from src.auction.rules import PROPOSED_RULE_KEYS, default_rules, unconfirmed_rules

PACKAGE = {
    "auction_clock",
    "extension",
    "nomination_timeout",
    "tie_rule",
    "withdrawal",
    "outage",
    "rounds_meaning",
    "order_repeats",
    "money_spent_end",
    "rights_exhausted_end",
    "commissioner_corrections",
    "open_trade_offers",
}


def test_every_package_item_is_a_confirmable_rule():
    assert PACKAGE <= set(PROPOSED_RULE_KEYS)


def test_open_trade_offers_blocks_until_confirmed():
    rules = default_rules("official")
    rules["confirmations"] = {k: True for k in PROPOSED_RULE_KEYS if k != "open_trade_offers"}
    assert unconfirmed_rules(rules) == ["open_trade_offers"]
    rules["confirmations"]["open_trade_offers"] = True
    assert unconfirmed_rules(rules) == []
