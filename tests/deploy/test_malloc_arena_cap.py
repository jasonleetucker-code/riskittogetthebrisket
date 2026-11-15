"""The backend unit caps glibc malloc arenas (WA-17, website audit 2026-11-12).

The backend's heap reached 2.8 GB against ``MemoryHigh`` 2.56 GB twice on
2026-11-12; the kernel throttled the service until the healthcheck watchdog
restarted it.  glibc's default is 8 arenas per core, and freed memory stays
in the arena that owns it.  Measured locally on a cold-start burst (14 heavy
routes x 3, concurrent): RSS 481 -> 889 MiB by default, 472 -> 754 MiB with
``MALLOC_ARENA_MAX=2``.

Pinned: the cap is in the unit (glibc reads it once, before the interpreter
starts, so ``.env`` loaded by the app would be too late), it survives the
reconciler's rendering, and its reason travels with it.  That the cap
actually limits the arena count is pinned in
``tests/diagnostics/test_heap_report.py::test_arena_count_honours_malloc_arena_max``.
"""

from __future__ import annotations

import re
import sys

import pytest

from tests.deploy.test_runtime_reconciler import ENV, SYSD, _render

UNIT = SYSD / "dynasty.service.template"
_CAP = re.compile(r"^Environment=MALLOC_ARENA_MAX=(\d+)\s*$", re.M)


def _service_section(text: str) -> str:
    m = re.search(r"^\[Service\]\n(.*?)(?=^\[|\Z)", text, re.M | re.S)
    assert m, "unit has no [Service] section"
    return m.group(1)


def test_the_unit_caps_malloc_arenas_at_two():
    caps = _CAP.findall(_service_section(UNIT.read_text(encoding="utf-8")))
    assert caps == ["2"], f"expected exactly one MALLOC_ARENA_MAX=2 in [Service], got {caps}"


def test_the_cap_is_documented_with_its_measurement():
    """A number without its reasoning gets 'tuned' away later."""
    text = UNIT.read_text(encoding="utf-8")
    before = text[: _CAP.search(text).start()]
    comment = before[before.rfind("\n\n") :]
    for needle in ("WA-17", "889", "754", "Rollback"):
        assert needle in comment, f"the MALLOC_ARENA_MAX comment lost {needle!r}"


@pytest.mark.skipif(sys.platform == "win32", reason="sources the POSIX reconciler")
def test_the_cap_survives_rendering():
    unit = _render("backend", UNIT, **ENV)
    assert _CAP.findall(_service_section(unit)) == ["2"]
