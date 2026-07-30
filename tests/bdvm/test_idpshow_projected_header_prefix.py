"""The IDP Show sheet prefixes every stat header with "Projected ".

Measured against production on 2026-07-30.  The fetcher retrieved the
correct table and then mapped **zero** stat columns, because
``_HEADER_ALIASES`` holds ``"solo tackles"`` / ``"sacks"`` / ``"tfl"``
while the sheet ships ``"Projected Solo Tackles"`` /
``"Projected Sacks"`` / ``"Projected TFL"``.  With ``statColumns``
empty the table failed the ``usable`` gate and was rejected as
``not_a_projection_table``.

The visible symptom was worse than the cause: the caller
(``scripts/refresh_bdvm_projections.py``) reported
*"idpshow returned no usable data (expired cookies / paywall?)"* and told
the operator to re-mint cookies.  The cookies were valid and had been
staged successfully — a header-format change was being reported as an
auth failure, sending the operator after the wrong thing entirely.

These are the exact headers observed in the production report's
``unmappedColumns``.
"""

from __future__ import annotations

from src.bdvm.idpshow_projections import _HEADER_ALIASES, _STAT_FIELDS, _squeeze

# Verbatim from the live 2026-07-30 report.
LIVE_STAT_HEADERS = [
    "Projected Fantasy Points",
    "Projected Total Snaps",
    "Projected Solo Tackles",
    "Projected Assists",
    "Projected Sacks",
    "Projected QB Hits",
    "Projected TFL",
    "Projected INT",
    "Projected FR",
    "Projected FF",
    "Projected PD",
]


def _semantics(headers: list[str]) -> set[str]:
    out: set[str] = set()
    for col in headers:
        semantic = _HEADER_ALIASES.get(_squeeze(col))
        if semantic is not None:
            out.add(semantic)
    return out


def test_prefixed_stat_headers_map_to_stat_fields() -> None:
    mapped = _semantics(LIVE_STAT_HEADERS)
    stat_cols = mapped & _STAT_FIELDS
    assert len(stat_cols) >= 2, (
        "Prefixed stat headers map to no stat fields, so the table would be "
        f"rejected as not_a_projection_table. Mapped: {sorted(mapped)}. "
        "_squeeze() must strip a leading 'Projected '/'Proj ' before the "
        "alias lookup."
    )
    # The live sheet carries nine scored categories plus a points column.
    assert len(stat_cols) == 9, f"expected 9 stat columns, got {sorted(stat_cols)}"
    assert "fpts" in mapped, "'Projected Fantasy Points' must resolve to fpts"


def test_unscored_column_stays_unmapped() -> None:
    """ "Projected Total Snaps" is not a scored category.

    Stripping the prefix must not accidentally alias it onto
    ``"total"`` -> ``def_tackles``, which would invent tackle production
    out of a snap count.
    """
    assert _squeeze("Projected Total Snaps") == "total snaps"
    assert _HEADER_ALIASES.get("total snaps") is None
    assert _HEADER_ALIASES.get(_squeeze("Projected Total")) == "def_tackles"


def test_no_regression_on_aliases_that_spell_the_prefix_out() -> None:
    """Two aliases already included the word, and must still resolve.

    ``"projected points"`` and ``"proj pts"`` predate this fix; after
    stripping they become ``"points"`` and ``"pts"``, both of which are
    themselves aliases for ``fpts``. If either stopped resolving, the
    strip would have broken a working path to fix a broken one.
    """
    for header in ("Projected Points", "Proj Pts", "Points", "FPTS", "Pts/G"):
        semantic = _HEADER_ALIASES.get(_squeeze(header))
        assert semantic in ("fpts", "fpg"), f"{header!r} no longer resolves (got {semantic!r})"


def test_bare_headers_are_unaffected() -> None:
    """A sheet without the prefix must behave exactly as before."""
    bare = ["Solo Tackles", "Sacks", "TFL", "INT", "FF", "FR", "PD", "QB Hits", "Assists"]
    assert len(_semantics(bare) & _STAT_FIELDS) == 9
