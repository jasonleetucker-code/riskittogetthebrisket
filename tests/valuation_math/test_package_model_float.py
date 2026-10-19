"""Package model: config state + float determinism (Brisket Trade Advisor B0-e).

Pins:
* ``config_state()`` names what ``_config()`` actually read, so a caller that
  must not run on the KTC fallback (the public advisor) can refuse;
* the geometric utility is BIT-identical to the JS owner on the shared
  fixture (iterative ``w *= q`` + left fold in both languages — ``**`` and
  CPython's compensated ``sum()`` both diverged from V8);
* the rounded VA is unchanged against the previous formula except where the
  previous Python disagreed with JavaScript at an exact half-integer.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

import pytest

from src.valuation_math import package_model as pm
from src.valuation_math.ktc_va_core import js_round

REPO = Path(__file__).resolve().parents[2]
FLOAT_FIXTURE = json.loads(
    (REPO / "tests/fixtures/package_model_float_cases.json").read_text(encoding="utf-8")
)


@pytest.fixture
def fresh_config():
    pm._config.cache_clear()
    yield
    pm._config.cache_clear()


def test_committed_config_state_is_ok(fresh_config):
    assert pm.config_state() == "ok"
    assert pm.active_model_id() == pm.GEOM_Q078_V1


@pytest.mark.parametrize(
    ("text", "state"),
    [
        ('{"active": "geom_q999"}', "unknown_active"),
        ("{not json", "unreadable"),
        ("[1, 2]", "unreadable"),
    ],
)
def test_config_state_names_the_fallback(monkeypatch, tmp_path, fresh_config, text, state):
    bad = tmp_path / "package_model.json"
    bad.write_text(text, encoding="utf-8")
    monkeypatch.setattr(pm, "_CONFIG_PATH", bad)
    pm._config.cache_clear()
    assert pm.config_state() == state
    # The fallback itself is unchanged (a broken config never promotes a challenger).
    assert pm.active_model_id() == pm.KTC_2026_04


def test_missing_config_is_unreadable(monkeypatch, tmp_path, fresh_config):
    monkeypatch.setattr(pm, "_CONFIG_PATH", tmp_path / "absent.json")
    pm._config.cache_clear()
    assert pm.config_state() == "unreadable"


def test_geom_utility_is_bit_identical_to_the_js_owner():
    assert FLOAT_FIXTURE["q"] == pm.PACKAGE_MODELS[pm.GEOM_Q078_V1]["q"]
    assert len(FLOAT_FIXTURE["cases"]) >= 200
    for case in FLOAT_FIXTURE["cases"]:
        # ``float(str)`` parses the JS shortest round-trip decimal back to the
        # exact double JS computed: equality here is bit equality.
        assert pm.geom_utility(case["team1"]) == float(case["utility1"]), case
        assert pm.geom_utility(case["team2"]) == float(case["utility2"]), case
        got = pm.adjust_pair(case["team1"], case["team2"], model_id=pm.GEOM_Q078_V1)
        assert list(got) == case["expected"], case


def test_no_power_operator_or_builtin_sum_in_the_geom_path():
    import inspect

    src = inspect.getsource(pm.geom_utility) + inspect.getsource(pm._geom_pair)
    assert "**" not in src
    assert "sum(" not in src.replace("_left_sum(", "")


def _old_pair(a, b, q=0.78):
    """The pre-B0-e formula (``q**i`` + builtin ``sum``), for comparison only."""

    def pos(v):
        return sorted((float(x) for x in v if x > 0), reverse=True)

    def util(v):
        return sum(x * q**i for i, x in enumerate(pos(v)))

    t1, t2 = pos(a), pos(b)
    if not t1 or not t2:
        return (0, 0, False)
    d1 = sum(t1) - util(t1)
    d2 = sum(t2) - util(t2)
    value = js_round(abs(d1 - d2))
    if value <= 0:
        return (0, 0, False)
    return (value, 1 if d2 > d1 else 2, True)


def test_rounded_va_unchanged_on_a_seeded_suite():
    """Over 200,000 random pairs the new Python differs from the old in 2,
    and in both the OLD Python disagreed with JavaScript at an exact .5 (the
    new one agrees with JS); this suite pins the common case cheaply."""
    rng = random.Random(7)
    diffs = 0
    for _ in range(20_000):
        a = [rng.randint(1, 9999) for _ in range(rng.randint(1, 8))]
        b = [rng.randint(1, 9999) for _ in range(rng.randint(1, 8))]
        if _old_pair(a, b) != pm.adjust_pair(a, b, model_id=pm.GEOM_Q078_V1):
            diffs += 1
    assert diffs == 0


@pytest.mark.parametrize(
    ("a", "b", "js_value"),
    [
        # Measured with the PREVIOUS JS formula (Math.round of 852.5000000000011
        # and 1864.4999999999982): the old Python rounded the other way.
        ([750, 9696, 2616], [799, 76], 853),
        ([9342, 1700, 5449], [7872], 1864),
    ],
)
def test_the_two_previous_python_js_disagreements_now_agree_with_js(a, b, js_value):
    assert pm.adjust_pair(a, b, model_id=pm.GEOM_Q078_V1)[0] == js_value
    assert _old_pair(a, b)[0] != js_value
