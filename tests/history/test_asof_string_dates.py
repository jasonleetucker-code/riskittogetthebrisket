"""F-5 — the string path must obey the same rule as the object path.

`store.as_of_date` accepts `date | datetime | str`.  The OBJECT path has
a clear rule: a tz-aware datetime is converted to its UTC date, and a
NAIVE datetime is refused with `ObservationError` because "as-of instants
must be UTC-aware".

The STRING path had no such rule.  It ran `strptime(s, "%Y-%m-%d")`, so an
ISO-8601 *datetime* string escaped as a raw
`ValueError: unconverted data remains: T23:00:00` — not the module's own
error type, and not the module's own policy.  A caller cannot catch that
with `except ObservationError`, and the message says nothing about the
UTC-awareness rule that actually governs instants here.

The repair adds no policy.  It makes the string path answer exactly what
the object path answers for the same instant.
"""

from __future__ import annotations

import unittest
from datetime import date, datetime, timedelta, timezone

from src.history.store import ObservationError, as_of_date


class TestPlainDates(unittest.TestCase):
    def test_a_date_string_passes_through(self):
        self.assertEqual(as_of_date("2026-08-18"), "2026-08-18")

    def test_a_date_object_passes_through(self):
        self.assertEqual(as_of_date(date(2026, 8, 18)), "2026-08-18")


class TestTheStringPathMatchesTheObjectPath(unittest.TestCase):
    """Same instant, two spellings, one answer."""

    def test_a_utc_datetime_string_resolves_like_the_object(self):
        obj = datetime(2026, 8, 18, 23, 0, tzinfo=timezone.utc)
        self.assertEqual(as_of_date("2026-08-18T23:00:00+00:00"), as_of_date(obj))

    def test_a_zulu_suffix_is_accepted(self):
        self.assertEqual(as_of_date("2026-08-18T23:00:00Z"), "2026-08-18")

    def test_an_offset_that_crosses_midnight_converts_to_utc(self):
        """The whole point of normalising to UTC: 2026-08-18 23:00-05:00
        is 2026-08-19 in UTC, and both spellings must agree."""
        obj = datetime(2026, 8, 18, 23, 0, tzinfo=timezone(timedelta(hours=-5)))
        self.assertEqual(
            as_of_date("2026-08-18T23:00:00-05:00"), obj.astimezone(timezone.utc).date().isoformat()
        )
        self.assertEqual(as_of_date("2026-08-18T23:00:00-05:00"), "2026-08-19")

    def test_a_naive_datetime_string_is_refused_the_same_way(self):
        with self.assertRaises(ObservationError) as ctx:
            as_of_date("2026-08-18T23:00:00")
        self.assertIn("UTC-aware", str(ctx.exception))


class TestFailuresAreTheModulesOwnType(unittest.TestCase):
    def test_garbage_raises_observation_error_not_value_error(self):
        for bad in ("not a date", "2026-13-45", "", "18/08/2026"):
            with self.subTest(value=bad):
                with self.assertRaises(ObservationError):
                    as_of_date(bad)


if __name__ == "__main__":
    unittest.main()
