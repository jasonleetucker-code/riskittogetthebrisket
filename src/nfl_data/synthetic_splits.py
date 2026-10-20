"""Detect provider stat lines whose reception-distance bands are SYNTHETIC.

Sleeper's weekly projections (``company: "rotowire"``) publish the six
reception-distance band keys this league pays for — ``rec_0_4`` …
``rec_40p``.  They are not a projection of how a player's catches are
distributed by distance.  Every band is a FIXED share of the projected
receptions, identical for every player:

    rec_0_4  0.2   rec_5_9  0.2   rec_10_19 0.3
    rec_20_29 0.2  rec_30_39 0.1  rec_40p   0.1

Measured on the live provider feed: every row with a reception
projection carries exactly this split, to the provider's two-decimal
publication rounding.  2026 weeks 7 and 8, fetched 2026-10-19T22:28Z:
349 of 349 and 356 of 356 rows (committed as
``tests/fixtures/li_scoring/sleeper_projection_band_lines_2026_w7_w8.json``);
the earlier week-3 work measured 174 of 174 and 177 of 177, and the
committed sample ``tests/fixtures/game_day/sleeper_projections/2026_w3_rotowire_sample.json``
reproduces it on every pass-catcher.  The shares sum to
**1.1**, not 1.0 — the bands over-allocate receptions by 10%, so they are
not even internally consistent with the ``rec`` they were split from.
A deep-threat WR and a checkdown RB get the same distance profile.

This module only DETECTS and LABELS that split.  It changes no score: a
league scored on these bands still adds their points (the exact scorer is
a dot product and is not this module's to alter), so a consumer must read
the label to know that part of the total is an imputed component rather
than provider evidence.  Replacing the split with a measured per-player
reception-depth shape is a separate, value-moving unit.

A REALIZED line can never match: realized bands are integer counts that
partition the receptions (they sum to ``rec``), while this split sums to
``1.1 x rec``; beyond rounding slack the two are disjoint for any
``rec > 0.3``.  Zero or absent receptions never match (no division, no
artefact).

Pure: no I/O, no clock, no globals beyond the declared constants.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Any

__all__ = [
    "PUBLICATION_HALF_UNIT",
    "RECEPTION_BAND_KEYS",
    "SLEEPER_RECEPTION_BAND_SHARES",
    "detect_synthetic_reception_split",
    "synthetic_band_keys",
]

#: The six Sleeper reception-distance band keys, in distance order.
RECEPTION_BAND_KEYS: tuple[str, ...] = (
    "rec_0_4",
    "rec_5_9",
    "rec_10_19",
    "rec_20_29",
    "rec_30_39",
    "rec_40p",
)

#: The fixed per-band share of projected receptions the provider applies
#: (measured; see the module docstring).  Read-only.
SLEEPER_RECEPTION_BAND_SHARES: Mapping[str, float] = MappingProxyType(
    {
        "rec_0_4": 0.2,
        "rec_5_9": 0.2,
        "rec_10_19": 0.3,
        "rec_20_29": 0.2,
        "rec_30_39": 0.1,
        "rec_40p": 0.1,
    }
)

#: Half of the provider's last published decimal (values are published to
#: two decimals).  This is publication precision, not a tuning tolerance.
#: BOTH numbers in the comparison are rounded: the provider splits its
#: UNROUNDED receptions and then rounds ``rec`` and every band separately
#: (measured: ``rec`` 0.18 with ``rec_10_19`` 0.06, i.e. 0.3 x ~0.185).  So
#: a band may sit up to ``share x half-unit`` (from ``rec``) plus one
#: half-unit (its own rounding) from ``share x published rec``.
PUBLICATION_HALF_UNIT = 0.005


def _num(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if out == out else None  # NaN is not a number here


def detect_synthetic_reception_split(stats: Mapping[str, Any], *, tol: float = 1e-6) -> bool:
    """True iff ``stats``' reception bands are the provider's fixed split.

    Conditions, all required:

    * ``rec`` is present, numeric and strictly positive (zero or absent
      receptions -> ``False``; nothing is divided);
    * at least one band key is present (a line without bands carries no
      split to detect);
    * every band equals ``share x rec`` within the provider's publication
      rounding of both numbers (``(1 + share) x`` :data:`PUBLICATION_HALF_UNIT`)
      plus ``tol`` float slack.
      An ABSENT band is compared as a published zero — the provider omits
      zero-valued keys — so it only matches where ``share x rec`` itself
      rounds to zero; it can never manufacture a match elsewhere.
    """
    rec = _num(stats.get("rec"))
    if rec is None or rec <= 0.0:
        return False
    if not any(key in stats for key in RECEPTION_BAND_KEYS):
        return False
    for key in RECEPTION_BAND_KEYS:
        if key in stats:
            published = _num(stats.get(key))
            if published is None:
                return False
        else:
            published = 0.0
        share = SLEEPER_RECEPTION_BAND_SHARES[key]
        slack = PUBLICATION_HALF_UNIT * (1.0 + share) + float(tol)
        if abs(published - share * rec) > slack:
            return False
    return True


def synthetic_band_keys(stats: Mapping[str, Any], *, tol: float = 1e-6) -> tuple[str, ...]:
    """The band keys present in ``stats`` that are synthetic, in distance order.

    Empty unless :func:`detect_synthetic_reception_split` fires.  Only keys
    the line actually carries are named — an absent band contributes no
    points, so it is not part of the imputed component.
    """
    if not detect_synthetic_reception_split(stats, tol=tol):
        return ()
    return tuple(key for key in RECEPTION_BAND_KEYS if key in stats)
