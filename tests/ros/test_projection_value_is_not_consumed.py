"""``RankedRow.projection_value`` is carried but never consumed.

Collaborative audit, finding A-1.

``aggregate.py`` had an ``if row.projection_value ... else`` whose two
branches were byte-identical — both called ``rank_to_score``.  The field's
docstring said the projection "overrides the rank-derived score for this
contribution".  It never did.

This is not a hypothetical dead field.  DraftSharks is the highest-weighted
ROS source (base_weight 1.25, ``is_projection_source: True``), it parses a
real projection in ``src/ros/sources/draftsharks_ros.py``, and
``src/ros/scrape.py`` populates ``projection_value`` from it.  The value
travelled through two modules and was then discarded by a "PR1 stub".

These tests pin the CURRENT, HONEST behaviour: ``rosValue`` is purely
rank-derived.  They are deliberately written to fail if someone wires
projections in without updating the documentation and the ROS engine doc —
that would be a live change to every ROS value and needs its own evidence,
not a silent branch flip.
"""

from __future__ import annotations

from src.ros.aggregate import RankedRow, SourceSnapshot, aggregate
from src.ros.parse import rank_to_score


_NOW = "2026-04-28T12:00:00+00:00"
_FRESH = "2026-04-28T11:00:00+00:00"

_LEAGUE = {
    "is_superflex": True,
    "is_2qb": False,
    "is_te_premium": True,
    "idp_enabled": True,
}


def _snapshot(rows: list[RankedRow], *, key: str = "draftSharksRos") -> SourceSnapshot:
    return SourceSnapshot(
        source_key=key,
        base_weight=1.0,
        is_ros=True,
        is_dynasty=False,
        is_te_premium=False,
        is_superflex=True,
        is_2qb=False,
        is_idp=False,
        status="ok",
        scraped_at=_FRESH,
        player_count=300,
        has_valid_cache=True,
        rows=rows,
    )


def _value_for(name: str, result) -> float:
    players = result["players"] if isinstance(result, dict) else result
    for row in players:
        if row["canonicalName"] == name:
            return float(row["rosValue"])
    raise AssertionError(f"{name} not in aggregate output")


class TestProjectionValueDoesNotChangeTheOutput:
    def test_a_wild_projection_does_not_move_ros_value(self):
        """The load-bearing assertion.

        Two identical rows differing ONLY in ``projection_value``.  If the
        projection were consumed, these could not agree.
        """
        without = aggregate([_snapshot([RankedRow("Player A", "WR", 5, 300)])], league=_LEAGUE, now_iso=_NOW)
        with_proj = aggregate(
            [_snapshot([RankedRow("Player A", "WR", 5, 300, projection_value=9999.0)])],
            league=_LEAGUE,
            now_iso=_NOW,
        )
        assert _value_for("Player A", without) == _value_for("Player A", with_proj)

    def test_ros_value_equals_the_pure_rank_score(self):
        """Single source at weight 1.0 — the blend is a passthrough, so the
        output must be exactly ``rank_to_score``.  This pins the unit: a
        normalized log-rank index on 0-100, not points."""
        result = aggregate(
            [_snapshot([RankedRow("Player A", "WR", 5, 300, projection_value=1234.0)])],
            league=_LEAGUE,
            now_iso=_NOW,
        )
        assert _value_for("Player A", result) == round(rank_to_score(5, 300), 2)

    def test_ordering_follows_rank_not_projection(self):
        """A worse-ranked player with a huge projection must still rank
        below a better-ranked player with none."""
        result = aggregate(
            [
                _snapshot(
                    [
                        RankedRow("Better Rank", "WR", 2, 300),
                        RankedRow("Big Projection", "WR", 100, 300, projection_value=5000.0),
                    ]
                )
            ],
            league=_LEAGUE,
            now_iso=_NOW,
        )
        assert _value_for("Better Rank", result) > _value_for("Big Projection", result)


class TestTheFieldIsDocumentedAsUnconsumed:
    def test_docstring_does_not_claim_an_override(self):
        """The comment on the field claimed it "overrides the rank-derived
        score".  While that is false, the comment is a trap for the next
        reader — it is the reason this dead branch survived review."""
        import inspect

        from src.ros import aggregate as agg

        src = inspect.getsource(agg)
        field_doc = src[src.index("class RankedRow") : src.index("class SourceSnapshot")]
        assert "overrides the rank-derived score" not in field_doc, (
            "RankedRow.projection_value is documented as overriding the "
            "rank-derived score, but aggregate() never reads it. Either wire "
            "it up (a live ROS value change needing its own evidence) or keep "
            "the docstring honest."
        )
