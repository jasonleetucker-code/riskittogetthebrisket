"""``src.trade.ledger_sort`` — sorting ledger rows without fabricating a
missing timestamp.

This module exists because the original inline sort keys in
``waiver_ledger``, ``market_trade_ledger`` and ``comparable_trades`` all
used ``occurred_at_ms or 0`` as a fallback for a missing timestamp — the
exact "missing resolves to a fabricated number" pattern
``scripts/check_decision_coercions.py`` blocks on decision paths. These
tests pin the replacement's two guarantees: a missing timestamp is
never coerced to 0 anywhere (not even inside the sort key), and the
resulting order is unchanged from the old (coercing) implementation.
"""

from __future__ import annotations

from src.trade.ledger_sort import newest_first_key, oldest_first_key


# ── missing stays missing, never becomes 0 ──────────────────────────


def test_oldest_first_key_never_coerces_a_missing_timestamp_to_zero():
    key = oldest_first_key(None, "tx:a")
    assert key[1] is None
    assert key[1] != 0


def test_newest_first_key_never_coerces_a_missing_timestamp_to_zero():
    key = newest_first_key(None)
    assert key[1] is None
    assert key[1] != 0


def test_oldest_first_key_preserves_a_known_timestamp_exactly():
    assert oldest_first_key(1_700_000_000_000, "tx:a")[1] == 1_700_000_000_000


def test_newest_first_key_negates_a_known_timestamp_for_descending_order():
    # Negating a REAL known value is a sort-direction transform, not a
    # fabrication of a missing one.
    assert newest_first_key(1_700_000_000_000)[1] == -1_700_000_000_000


# ── deterministic sorting over mixed known/missing rows ─────────────


def test_oldest_first_sorts_undated_leading_then_ascending_with_tiebreak():
    rows = [
        {"occurredAtMs": 300, "ref": "b"},
        {"occurredAtMs": None, "ref": "z"},
        {"occurredAtMs": 100, "ref": "a"},
        {"occurredAtMs": None, "ref": "y"},
    ]
    rows.sort(key=lambda r: oldest_first_key(r["occurredAtMs"], r["ref"]))
    assert [r["ref"] for r in rows] == ["y", "z", "a", "b"]


def test_newest_first_sorts_dated_leading_descending_then_undated_trailing():
    rows = [
        {"occurredAtMs": 100, "ref": "a"},
        {"occurredAtMs": None, "ref": "z"},
        {"occurredAtMs": 300, "ref": "b"},
        {"occurredAtMs": None, "ref": "y"},
    ]
    rows.sort(key=lambda r: newest_first_key(r["occurredAtMs"]))
    assert [r["ref"] for r in rows[:2]] == ["b", "a"]
    assert {r["ref"] for r in rows[2:]} == {"y", "z"}


def test_all_known_timestamps_sort_as_plain_ascending_ints_oldest_first():
    rows = [{"occurredAtMs": ms, "ref": str(ms)} for ms in (500, 100, 300, 200, 400)]
    rows.sort(key=lambda r: oldest_first_key(r["occurredAtMs"], r["ref"]))
    assert [r["occurredAtMs"] for r in rows] == [100, 200, 300, 400, 500]


def test_all_known_timestamps_sort_as_plain_descending_ints_newest_first():
    rows = [{"occurredAtMs": ms, "ref": str(ms)} for ms in (500, 100, 300, 200, 400)]
    rows.sort(key=lambda r: newest_first_key(r["occurredAtMs"]))
    assert [r["occurredAtMs"] for r in rows] == [500, 400, 300, 200, 100]


def test_all_undated_rows_never_compare_none_across_the_tiebreak():
    # Every row lands in the same "unknown" group; the sort must fall
    # through to the tiebreak without ever raising on None comparison.
    rows = [{"occurredAtMs": None, "ref": r} for r in ("c", "a", "b")]
    rows.sort(key=lambda r: oldest_first_key(r["occurredAtMs"], r["ref"]))
    assert [r["ref"] for r in rows] == ["a", "b", "c"]
