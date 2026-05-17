"""Tests for src.utils.age.age_from_birthdate."""

from __future__ import annotations

from datetime import date

from src.utils.age import age_from_birthdate


REF = date(2026, 5, 4)


class TestAgeFromBirthdate:
    def test_basic_age(self):
        assert age_from_birthdate("2000-01-15", today=REF) == 26

    def test_birthday_not_yet_passed(self):
        # Born May 5: birthday tomorrow → still age - 1
        assert age_from_birthdate("2000-05-05", today=REF) == 25

    def test_birthday_today(self):
        assert age_from_birthdate("2000-05-04", today=REF) == 26

    def test_birthday_yesterday(self):
        assert age_from_birthdate("2000-05-03", today=REF) == 26

    def test_empty_string(self):
        assert age_from_birthdate("", today=REF) is None

    def test_none(self):
        assert age_from_birthdate(None, today=REF) is None

    def test_malformed(self):
        assert age_from_birthdate("not-a-date", today=REF) is None

    def test_partial(self):
        assert age_from_birthdate("2000-01", today=REF) is None

    def test_out_of_range_too_young(self):
        # Younger than 15 — sleeper dump corruption.
        assert age_from_birthdate("2020-01-01", today=REF) is None

    def test_out_of_range_too_old(self):
        # Older than 50 — sleeper dump corruption.
        assert age_from_birthdate("1900-01-01", today=REF) is None

    def test_invalid_calendar_month(self):
        # Codex P2: month 99 must be rejected, not silently treated as
        # year-only math.
        assert age_from_birthdate("2000-99-15", today=REF) is None

    def test_invalid_calendar_day(self):
        # Feb 31 is not a real date.
        assert age_from_birthdate("2000-02-31", today=REF) is None

    def test_zero_month(self):
        assert age_from_birthdate("2000-00-15", today=REF) is None

    def test_uses_today_default_when_not_provided(self):
        # Just check it returns *something* sensible (an int) for a
        # realistic birth_date when today is not injected.
        result = age_from_birthdate("1995-06-15")
        assert isinstance(result, int)
        assert 15 <= result <= 50
