"""Age helpers for player records.

Sleeper's ``/v1/players/nfl`` payload exposes ``birth_date`` in
ISO ``YYYY-MM-DD`` form for almost every active NFL player.  This
module converts that into the integer ``age`` the contract layer
and frontend age-curve overlay expect.
"""
from __future__ import annotations

from datetime import date


def age_from_birthdate(bd: str | None, *, today: date | None = None) -> int | None:
    """Convert an ISO ``YYYY-MM-DD`` birth_date to integer age.

    Returns ``None`` for empty / malformed input or implausible ages
    (the Sleeper dump occasionally has corrupt rows; clamping to
    15..50 filters those without affecting any real NFL player).

    ``today`` is injected for deterministic testing.
    """
    if not bd:
        return None
    try:
        parts = str(bd).split("-")
        if len(parts) != 3:
            return None
        # ``date(...)`` validates calendar correctness — Feb 31, month 99,
        # etc. raise ValueError instead of producing a wrong-but-numeric age.
        born = date(int(parts[0]), int(parts[1]), int(parts[2]))
    except (ValueError, IndexError, AttributeError, TypeError):
        return None
    ref = today or date.today()
    age = ref.year - born.year - ((ref.month, ref.day) < (born.month, born.day))
    return age if 15 <= age <= 50 else None
