"""The ceiling budget separates "what the limits permit" from "what is used".

``scripts/memory_ceiling_budget.py`` reads the repo's unit templates and does
arithmetic.  Pinned here:

* size parsing (base-1024, ``infinity`` is no limit, junk is no limit, never 0);
* the last directive wins, comments are ignored;
* ceiling oversubscription and co-resident usage are two separate numbers;
* the policy invariants the repo's REAL templates must keep.  The one that
  matters for a limit change: a unit may drop ``MemoryHigh``, but a unit with a
  ``MemoryHigh`` and no ``MemoryMax`` throttles forever and is never killed.

No test pins today's numeric limits -- changing them is a reviewed decision
(``docs/ops/BACKEND_MEMORY_POLICY_2026-10-21.md``), not something a test should
silently veto.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import memory_ceiling_budget as mcb

REPO = Path(__file__).resolve().parents[2]
MIB = 1024**2


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("3G", 3 * 1024**3),
        ("2560M", 2560 * MIB),
        ("512K", 512 * 1024),
        ("1.5G", int(1.5 * 1024**3)),
        ("1024", 1024),
        ("infinity", None),
        ("none", None),
        ("", None),
        ("3GB", None),
        ("-1", None),
    ],
)
def test_parse_size(text, expected):
    assert mcb.parse_size(text) == expected


def test_last_directive_wins_and_comments_are_ignored():
    text = (
        "# MemoryMax=9G\nMemoryHigh=1G\n[Service]\nMemoryMax=2G\n  MemoryMax=3G  \n#MemoryHigh=8G\n"
    )
    assert mcb.unit_limits(text) == {"MemoryHigh": 1024**3, "MemoryMax": 3 * 1024**3}


def test_percentages_resolve_against_the_host_and_are_unknown_without_one():
    host = 8000 * MIB
    assert mcb.parse_size("80%", host_bytes=host) == 6400 * MIB
    assert mcb.parse_size("12.5%", host_bytes=host) == 1000 * MIB
    assert mcb.parse_size("500‰", host_bytes=host) == 4000 * MIB
    assert mcb.parse_size("50%") is None  # no host size: cannot resolve
    assert mcb.unit_limits("MemoryMax=50%\n", host_bytes=host) == {"MemoryMax": 4000 * MIB}


def test_a_percentage_without_a_host_does_not_become_no_limit():
    # the earlier, resolvable assignment stands rather than reading as "unlimited"
    assert mcb.unit_limits("MemoryMax=2G\nMemoryMax=50%\n", host_bytes=None) == {
        "MemoryMax": 2 * 1024**3
    }


def test_an_empty_assignment_resets_the_limit():
    assert mcb.unit_limits("MemoryHigh=1G\nMemoryMax=2G\nMemoryMax=\n") == {
        "MemoryHigh": 1024**3,
        "MemoryMax": None,
    }


def test_a_rejected_value_is_ignored_like_systemd_ignores_it():
    assert mcb.unit_limits("MemoryMax=2G\nMemoryMax=lots\n") == {"MemoryMax": 2 * 1024**3}


def test_cli_percentage_override_uses_the_given_host(capsys):
    assert (
        mcb.main(["--host-mib", "8000", "--set", "dynasty.MemoryMax=45%", "--format", "json"]) == 0
    )
    rows = json.loads(capsys.readouterr().out)["units"]
    assert next(r for r in rows if r["unit"] == "dynasty")["memory_max_mib"] == 3600.0
    assert mcb.main(["--set", "dynasty.MemoryMax=lots"]) == 2


def test_infinity_clears_a_limit_rather_than_becoming_zero():
    assert mcb.unit_limits("MemoryMax=infinity\n") == {"MemoryMax": None}


def _units():
    return {
        "dynasty": {"MemoryHigh": 2560 * MIB, "MemoryMax": 3072 * MIB},
        "dynasty-frontend": {"MemoryHigh": 1536 * MIB, "MemoryMax": 2048 * MIB},
        "dynasty-ktc-trades": {"MemoryMax": 512 * MIB},
    }


def test_ceiling_sums_are_reported_against_host_ram_without_calling_it_usage():
    out = mcb.budget(_units(), host_mib=5000)
    assert out["sum_memory_max_all_mib"] == 5632
    assert out["oversubscription_mib"] == 632
    assert out["sum_memory_max_always_on_mib"] == 5120  # backend + frontend only
    assert out["oversubscription_always_on_mib"] == 120
    assert "usage_margin_mib" not in out


def test_usage_margin_is_a_separate_number_from_oversubscription():
    out = mcb.budget(_units(), host_mib=7941, usage={"backend": 3430, "other": 689})
    assert out["oversubscription_mib"] < 0  # ceilings fit
    assert out["usage_total_mib"] == 4119
    assert out["usage_margin_mib"] == 3822


def test_overrides_edit_a_copy_and_none_removes_the_limit():
    base = _units()
    out = mcb.apply_overrides(base, ["dynasty.MemoryMax=3584M", "dynasty.MemoryHigh=none"])
    assert out["dynasty"] == {"MemoryHigh": None, "MemoryMax": 3584 * MIB}
    assert base["dynasty"]["MemoryHigh"] == 2560 * MIB  # input untouched
    report = mcb.budget(out)
    assert next(r for r in report["units"] if r["unit"] == "dynasty")["memory_high_mib"] is None


@pytest.mark.parametrize(
    "bad", ["dynasty.MemorySwapMax=0", "dynasty=3G", "MemoryMax=3G", "dynasty.MemoryMax"]
)
def test_bad_overrides_are_refused(bad):
    with pytest.raises(ValueError):
        mcb.apply_overrides(_units(), [bad])


def test_high_above_max_and_high_without_max_are_violations():
    out = mcb.budget(
        {
            "a": {"MemoryHigh": 4 * 1024**3, "MemoryMax": 3 * 1024**3},
            "b": {"MemoryHigh": 1024**3},
            "c": {"MemoryMax": 1024**3},
        }
    )
    assert len(out["violations"]) == 2
    assert any("a: MemoryHigh above MemoryMax" in v for v in out["violations"])
    assert any("b: MemoryHigh with no MemoryMax" in v for v in out["violations"])


def test_reading_a_units_dir_uses_the_stem_and_skips_unlimited_units(tmp_path: Path):
    (tmp_path / "svc.service.template").write_text("MemoryMax=1G\n", encoding="utf-8")
    (tmp_path / "plain.service").write_text("MemoryHigh=512M\nMemoryMax=1G\n", encoding="utf-8")
    (tmp_path / "nolimits.service.template").write_text("[Service]\nNice=5\n", encoding="utf-8")
    (tmp_path / "x.timer.template").write_text("MemoryMax=9G\n", encoding="utf-8")
    assert mcb.read_units(tmp_path) == {
        "plain": {"MemoryHigh": 512 * MIB, "MemoryMax": 1024 * MIB},
        "svc": {"MemoryMax": 1024 * MIB},
    }


# ── invariants the REAL templates must keep ──────────────────────────────


def test_real_units_keep_the_policy_invariants():
    units = mcb.read_units(REPO / "deploy" / "systemd")
    assert "dynasty" in units and "dynasty-frontend" in units
    report = mcb.budget(units)
    assert report["violations"] == []
    for name in ("dynasty", "dynasty-frontend"):
        assert units[name].get("MemoryMax") is not None, f"{name} must keep a hard MemoryMax"


def test_cli_text_and_json_and_errors(capsys, tmp_path: Path):
    assert mcb.main(["--set", "dynasty.MemoryMax=3584M", "--usage", "backend=3430"]) == 0
    assert "co-resident usage total" in capsys.readouterr().out
    assert mcb.main(["--format", "json", "--host-mib", "1000"]) == 0
    assert json.loads(capsys.readouterr().out)["host_mib"] == 1000
    assert mcb.main(["--set", "nonsense"]) == 2
    assert mcb.main(["--usage", "backend=lots"]) == 2
    assert (
        mcb.main(["--units-dir", str(tmp_path / "missing")]) == 2
    )  # no units dir is an error, not an empty report
