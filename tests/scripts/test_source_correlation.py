"""T4-1: the source-correlation instrument.

The finding this tool produced matters more than the tool: publisher
NAME does not predict shared opinion, so the proposed name-based
confidence fix is unsupported and in one case backwards.

These tests pin the statistic's behaviour on synthetic sources where the
right answer is known by construction, because the real-CSV numbers move
every scrape and a test asserting them would be measuring the market
rather than the code.
"""

from __future__ import annotations

import csv

import pytest

from scripts.audit.measure_source_correlation import (
    measure,
    publisher_of,
    to_percentiles,
)


def _write(tmp_path, name, ordered_players):
    path = tmp_path / f"{name}.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["name", "rank"])
        for i, p in enumerate(ordered_players, start=1):
            w.writerow([p, i])
    return path


_POOL = [f"player {i:03d}" for i in range(60)]


def test_identical_sources_correlate_perfectly_on_residuals(tmp_path):
    """Two byte-identical boards are one opinion, and the statistic has
    to say so — otherwise it cannot detect the thing it exists for."""
    _write(tmp_path, "aaSf", _POOL)
    _write(tmp_path, "bbSf", _POOL)
    # A third, different source so the consensus is not just these two.
    _write(tmp_path, "ccSf", list(reversed(_POOL)))
    result = measure(tmp_path, min_overlap=30)
    pair = next(p for p in result["pairs"] if {p["a"], p["b"]} == {"aaSf", "bbSf"})
    assert pair["residualCorrelation"] > 0.9


def test_opposed_sources_correlate_negatively(tmp_path):
    """The control. Without it, a statistic stuck near +1 would pass the
    test above and be useless."""
    _write(tmp_path, "aaSf", _POOL)
    _write(tmp_path, "bbSf", list(reversed(_POOL)))
    _write(tmp_path, "ccSf", _POOL[::2] + _POOL[1::2])
    result = measure(tmp_path, min_overlap=30)
    pair = next(p for p in result["pairs"] if {p["a"], p["b"]} == {"aaSf", "bbSf"})
    assert pair["residualCorrelation"] < -0.5


def test_the_shared_market_signal_is_removed(tmp_path):
    """The reason residuals are used at all.

    These three boards agree on the broad ordering and differ in the
    details — which is what real dynasty sources look like. Raw rank
    correlation would read ~0.9+ for every pair and discriminate
    nothing. On residuals they must not all look identical.
    """
    a = list(_POOL)
    b = list(_POOL)
    b[10], b[11] = b[11], b[10]
    c = list(_POOL)
    c[40], c[41] = c[41], c[40]
    _write(tmp_path, "aaSf", a)
    _write(tmp_path, "bbSf", b)
    _write(tmp_path, "ccSf", c)
    result = measure(tmp_path, min_overlap=30)
    rhos = [p["residualCorrelation"] for p in result["pairs"]]
    assert len(rhos) == 3
    assert max(rhos) - min(rhos) > 0.05, (
        "residuals collapsed to one value — the statistic is not "
        "discriminating between near-identical boards"
    )


def test_pairs_below_the_overlap_floor_are_dropped(tmp_path):
    """Two boards sharing five players cannot support a correlation, and
    reporting one would be a number with no evidence behind it."""
    _write(tmp_path, "aaSf", _POOL)
    _write(tmp_path, "bbSf", _POOL)
    _write(tmp_path, "ccSf", [f"other {i}" for i in range(50)] + _POOL[:5])
    result = measure(tmp_path, min_overlap=30)
    keys = [{p["a"], p["b"]} for p in result["pairs"]]
    assert {"aaSf", "bbSf"} in keys
    assert {"aaSf", "ccSf"} not in keys


def test_publisher_labelling_groups_known_families():
    assert publisher_of("dlfSf") == publisher_of("dlfRookieIdp") == "DLF"
    assert publisher_of("ktc") == publisher_of("ktcSfTep") == "KTC"
    assert publisher_of("fantasyProsSf") == publisher_of("fantasyProsFitzmaurice")
    # Different publishers that a naive prefix rule might merge.
    assert publisher_of("idpTradeCalc") != publisher_of("idpShow")


def test_percentiles_are_scale_free():
    """Sources publish ranks, 0-9999 values, and 0-100 indices. The
    residual step only works if all three land on one scale."""
    ranks = to_percentiles({"a": 1.0, "b": 2.0, "c": 3.0})
    values = to_percentiles({"a": -9999.0, "b": -5000.0, "c": -10.0})
    assert ranks == values
    assert ranks["a"] == pytest.approx(1 / 3)
    assert ranks["c"] == pytest.approx(1.0)


def test_too_few_sources_is_an_error_not_a_fabricated_result(tmp_path):
    _write(tmp_path, "aaSf", _POOL)
    assert "error" in measure(tmp_path, min_overlap=30)
