"""The canonical package-construction substrate (V1-36 / C3-PKG-01).

These test MECHANICS, not objectives.  Nothing here asserts that a package is
good — that is each product's own question and stays in its own module.
"""

from __future__ import annotations

import pytest

from src.packages import (
    EligibilityPolicy,
    by_value_desc,
    PackageAsset,
    PackageShape,
    adapt_assets,
    enumerate_packages,
    package_key,
    side_key,
)


def _a(name: str, value: float | None = 1000.0, position: str = "RB", asset_id: str = ""):
    return PackageAsset(asset_id=asset_id, name=name, position=position, value=value)


def _run(ours, theirs, **kw):
    packages, report = enumerate_packages(ours, theirs, adapt=False, **kw)
    return list(packages), report


# ── Identity ─────────────────────────────────────────────────────────


def test_identity_prefers_the_canonical_asset_id():
    a = _a("2027 Early 1st", asset_id="mpick:2027:r1:t-early")
    assert a.key == "id:mpick:2027:r1:t-early"
    assert a.key_is_name_fallback is False


def test_two_assets_sharing_a_display_name_are_two_assets():
    """The defect the name-keyed dedup produced.

    A manager holding his own 2027 1st and one acquired from another team
    holds TWO assets against ONE board row.  ``finder``'s retired
    ``_deduplicate`` keyed on display names and collapsed them.
    """
    own = _a("2027 Early 1st", asset_id="pick:lg:2027:r1:o4")
    acquired = _a("2027 Early 1st", asset_id="pick:lg:2027:r1:o9")
    assert own.key != acquired.key
    assert side_key([own, acquired]) == tuple(sorted([own.key, acquired.key]))
    assert len(set(side_key([own, acquired]))) == 2


def test_a_name_fallback_is_marked_rather_than_assumed_equivalent():
    a = _a("Josh Allen")
    assert a.key == "name:josh allen"
    assert a.key_is_name_fallback is True


def test_package_identity_is_directional():
    x, y = _a("X"), _a("Y")
    assert package_key([x], [y]) != package_key([y], [x])


def test_package_identity_ignores_order_within_a_side():
    x, y, z = _a("X"), _a("Y"), _a("Z")
    assert package_key([x, y], [z]) == package_key([y, x], [z])


# ── Value known / unknown ────────────────────────────────────────────


def test_an_unpriced_asset_is_unknown_not_zero():
    a = _a("Ghost", value=None)
    assert a.value_known is False
    assert a.value is not 0  # noqa: F632 — the point is that it is None


def test_unpriced_assets_are_excluded_by_default_and_counted():
    """Excluded, and the count says so — never silently absent."""
    ours = [_a("Priced", 1000.0), _a("Unpriced", None)]
    packages, report = _run(ours, [_a("Target", 900.0)])
    assert report.our_excluded_unpriced == 1
    assert all(all(x.value_known for x in p.send) for p in packages)


def test_unpriced_assets_can_be_admitted_when_a_product_says_so():
    ours = [_a("Unpriced", None)]
    packages, report = _run(
        ours, [_a("Target", 900.0)], policy=EligibilityPolicy(allow_unknown_value=True)
    )
    assert report.our_excluded_unpriced == 0
    assert len(packages) == 1


# ── Self-trade and duplicates ────────────────────────────────────────


def test_an_asset_never_appears_on_both_sides():
    shared = _a("Shared", asset_id="p1")
    packages, _r = _run([shared], [shared])
    assert packages == []


def test_the_same_asset_twice_on_one_side_is_refused():
    dup = _a("Dup", asset_id="p1")
    packages, _r = _run([dup, dup], [_a("Other", asset_id="p2")], shapes=[PackageShape(2, 1)])
    assert packages == []


def test_duplicate_packages_are_suppressed_and_counted():
    ours = [_a("A", asset_id="a"), _a("B", asset_id="b")]
    theirs = [_a("T", asset_id="t")]
    packages, report = _run(ours, theirs, shapes=[PackageShape(1, 1), PackageShape(1, 1)])
    assert len(packages) == 2  # A->T and B->T
    assert report.duplicates_suppressed == 2  # the repeated shape's re-emissions


# ── Cardinality and asymmetry ────────────────────────────────────────


def test_asymmetric_packages_are_allowed():
    """2-for-1 and 3-for-2 are valid trades and must not be refused."""
    ours = [_a(f"O{i}", 1000 + i, asset_id=f"o{i}") for i in range(3)]
    theirs = [_a(f"T{i}", 1000 + i, asset_id=f"t{i}") for i in range(3)]
    packages, report = _run(ours, theirs, max_per_side=3, max_side_difference=1)
    shapes = {(len(p.send), len(p.receive)) for p in packages}
    assert (2, 1) in shapes
    assert (3, 2) in shapes
    assert "2-for-1" in report.shapes


def test_asymmetry_is_bounded():
    """Unbounded enumeration produces shapes nobody would consider."""
    ours = [_a(f"O{i}", 1000 + i, asset_id=f"o{i}") for i in range(4)]
    theirs = [_a(f"T{i}", 1000 + i, asset_id=f"t{i}") for i in range(4)]
    packages, _r = _run(ours, theirs, max_per_side=4, max_side_difference=1)
    for p in packages:
        assert abs(len(p.send) - len(p.receive)) <= 1


@pytest.mark.parametrize("diff", [0, 1, 2])
def test_the_asymmetry_bound_is_the_products_to_choose(diff):
    ours = [_a(f"O{i}", 1000 + i, asset_id=f"o{i}") for i in range(3)]
    theirs = [_a(f"T{i}", 1000 + i, asset_id=f"t{i}") for i in range(3)]
    packages, _r = _run(ours, theirs, max_per_side=3, max_side_difference=diff)
    assert packages
    for p in packages:
        assert abs(len(p.send) - len(p.receive)) <= diff


def test_a_shape_larger_than_the_pool_is_skipped_not_an_error():
    packages, _r = _run([_a("Only", asset_id="o")], [_a("One", asset_id="t")], max_per_side=3)
    assert {(len(p.send), len(p.receive)) for p in packages} == {(1, 1)}


def test_a_package_must_have_assets_on_both_sides():
    with pytest.raises(ValueError):
        PackageShape(0, 1)


# ── Truncation is never silent ───────────────────────────────────────


def test_the_pool_bound_keeps_the_most_valuable_and_reports_itself():
    ours = [_a(f"O{i:02d}", 100 + i, asset_id=f"o{i}") for i in range(20)]
    packages, report = _run(ours, [_a("T", 500.0, asset_id="t")], pool_limit=5)
    assert report.our_truncated_to == 5
    assert report.truncated is True
    kept = {a.name for p in packages for a in p.send}
    assert kept == {f"O{i:02d}" for i in range(15, 20)}  # the five most valuable


def test_no_truncation_reports_none_not_zero():
    """``0`` would read as "truncated to nothing"."""
    _packages, report = _run([_a("A", asset_id="a")], [_a("B", asset_id="b")])
    assert report.our_truncated_to is None
    assert report.truncated is False


def test_a_package_budget_reports_exhaustion():
    ours = [_a(f"O{i}", 1000 + i, asset_id=f"o{i}") for i in range(10)]
    theirs = [_a(f"T{i}", 1000 + i, asset_id=f"t{i}") for i in range(10)]
    packages, report = _run(ours, theirs, max_packages=7)
    assert len(packages) == 7
    assert report.budget_exhausted is True
    assert report.truncated is True


def test_name_keyed_assets_are_counted():
    """Weaker dedup identity is visible rather than assumed away."""
    _p, report = _run([_a("No Id")], [_a("Also No Id")])
    assert report.name_keyed_assets == 2


# ── Eligibility ──────────────────────────────────────────────────────


def test_min_value_excludes_and_counts():
    packages, report = _run(
        [_a("Cheap", 100.0, asset_id="c"), _a("Real", 5000.0, asset_id="r")],
        [_a("T", 4000.0, asset_id="t")],
        policy=EligibilityPolicy(min_value=700),
    )
    assert report.our_excluded_ineligible == 1
    assert {a.name for p in packages for a in p.send} == {"Real"}


def test_positionless_rows_are_excluded_by_default():
    packages, report = _run(
        [_a("Placeholder", 5000.0, position="", asset_id="p")],
        [_a("T", 4000.0, asset_id="t")],
    )
    assert report.our_excluded_ineligible == 1
    assert packages == []


def test_a_product_can_keep_positionless_rows():
    """Picks carry no position in the finder's legacy players dict."""
    packages, _r = _run(
        [_a("2027 Early 1st", 5000.0, position="", asset_id="p")],
        [_a("T", 4000.0, asset_id="t")],
        policy=EligibilityPolicy(require_position=False),
    )
    assert len(packages) == 1


def test_excluded_keys_remove_assets_already_in_the_trade():
    a = _a("A", asset_id="a")
    packages, _r = _run(
        [a, _a("B", asset_id="b")],
        [_a("T", asset_id="t")],
        policy=EligibilityPolicy(excluded_keys=frozenset({a.key})),
    )
    assert {x.name for p in packages for x in p.send} == {"B"}


# ── Adapters ─────────────────────────────────────────────────────────


def test_adapt_reads_the_field_names_this_repo_already_uses():
    class _Legacy:
        def __init__(self):
            self.player_id = "12345"
            self.name = "Josh Allen"
            self.position = "QB"
            self.display_value = 9000

    (adapted,) = adapt_assets([_Legacy()])
    assert (adapted.asset_id, adapted.name, adapted.position, adapted.value) == (
        "12345",
        "Josh Allen",
        "QB",
        9000.0,
    )
    assert adapted.value_known is True


def test_adapt_treats_a_missing_value_as_unknown_not_zero():
    class _Unpriced:
        name = "Ghost"
        position = "WR"

    (adapted,) = adapt_assets([_Unpriced()])
    assert adapted.value is None
    assert adapted.value_known is False


def test_sources_round_trip_so_products_score_what_was_enumerated():
    class _Thing:
        def __init__(self, n):
            self.name = n
            self.position = "RB"
            self.display_value = 1000
            self.player_id = n

    ours, theirs = [_Thing("A")], [_Thing("B")]
    packages, _r = enumerate_packages(ours, theirs)
    (pair,) = list(packages)
    send, receive = pair.sources()
    assert send[0] is ours[0]
    assert receive[0] is theirs[0]


# ── Pool ordering ────────────────────────────────────────────────────


def test_unpriced_assets_sort_last_by_rule_not_by_a_fabricated_zero():
    """``-(value or 0)`` would be a decision-path coercion.

    Pool order decides what survives truncation, so treating "we could not
    price this" as "worth nothing" is a fabricated number on a decision path —
    and it would sort an unpriced asset ABOVE anything genuinely worth less
    than zero, which is the wrong end entirely.
    """
    priced_high = _a("High", 5000.0, asset_id="h")
    priced_low = _a("Low", 10.0, asset_id="l")
    unpriced = _a("Unknown", None, asset_id="u")
    ordered = sorted([unpriced, priced_low, priced_high], key=by_value_desc)
    assert [a.name for a in ordered] == ["High", "Low", "Unknown"]


def test_the_default_pool_order_survives_truncation_correctly():
    ours = [
        _a("Unpriced", None, asset_id="u"),
        _a("Cheap", 5.0, asset_id="c"),
        _a("Dear", 9000.0, asset_id="d"),
    ]
    packages, _report = _run(
        ours,
        [_a("T", 100.0, asset_id="t")],
        policy=EligibilityPolicy(allow_unknown_value=True),
        pool_limit=1,
    )
    assert {a.name for p in packages for a in p.send} == {"Dear"}
