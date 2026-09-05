"""The session health check must not read a stale `origin/main` ref as evidence.

INCIDENT 2026-09-05 (docs/ops/INCIDENT_2026-09-05_FLOCK_ROOKIE_FLOOR.md §2)
──────────────────────────────────────────────────────────────────────────
`.claude/health-check.sh` attributes a stale checked-out contract by asking
what `origin/main` holds.  `_git` deliberately never fetches — a SessionStart
hook must not wait on the network — so `origin/main` is whatever the checkout
last saw.

On 2026-09-05 that ref was ~38h old and unfetched.  The probe read a 38h-old
contract off it and printed::

    WARNING: no successful scrape in 38h. Check scheduled-refresh workflow.
    (origin/main's contract is 38h old too — not a branch artifact.)

Both halves were false: production's last successful scrape was 1.2h old and
real `main` carried a 1.6h-old contract.  The second line is the damaging one
— it upgrades "I cannot tell" into a confident pipeline-outage claim, and it
triggered a full P0 incident response.

The file's own rule is "an unproven excuse must never silence a real alarm."
This test pins the converse: an unproven ref must not raise a false one.  A
ref older than the freshness budget is evidence in NEITHER direction, so it
must answer None ("cannot tell"), and the caller must say so explicitly
rather than implying the pipeline.

This is a behavioural test over the real script's own source: it extracts the
Python heredoc from the shell file and exercises the functions with a stubbed
`_git`.  No network, no git, no live board.
"""

from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / ".claude" / "health-check.sh"


def _load_probe_namespace() -> dict:
    """Exec the freshness probe's function definitions in isolation.

    The heredoc's trailing module-level code reads `exports/latest/` and
    prints; we cut at it so only the definitions run.
    """
    text = _SCRIPT.read_text(encoding="utf-8")
    blocks = re.findall(r"<<'PY'[^\n]*\n(.*?)\nPY\n", text, flags=re.DOTALL)
    assert blocks, "no python heredoc found in .claude/health-check.sh"
    src = max(blocks, key=len)
    cut = src.index("paths = sorted(")
    ns: dict = {}
    exec(compile(src[:cut], str(_SCRIPT), "exec"), ns)  # noqa: S102 - the file under test
    return ns


def _iso(hours_ago: float) -> str:
    return (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=hours_ago)).isoformat()


@pytest.fixture()
def ns():
    return _load_probe_namespace()


def _stub_git(ns, *, ref_age_h, contract_age_h):
    """Replace `_git` so it answers as a checkout whose origin/main ref is
    `ref_age_h` old and whose contract blob is `contract_age_h` old."""

    def fake(*args):
        if args[:2] == ("log", "-1"):
            return _iso(ref_age_h) + "\n" if ref_age_h is not None else None
        if args[0] == "ls-tree":
            return "exports/latest/dynasty_data_20260905.json\n"
        if args[0] == "show":
            return '{"scrapeTimestamp": "%s"}' % _iso(contract_age_h)
        return None

    ns["_git"] = fake


def test_stale_local_ref_answers_cannot_tell(ns):
    # The exact 2026-09-05 shape: a 38h-old unfetched ref carrying a 38h-old
    # contract, against a 24h budget.  It must NOT come back as a confident
    # "the pipeline is stale too".
    _stub_git(ns, ref_age_h=38.0, contract_age_h=38.0)
    assert ns["main_contract_age_h"](24) is None


def test_unreadable_local_ref_answers_cannot_tell(ns):
    _stub_git(ns, ref_age_h=None, contract_age_h=1.0)
    assert ns["main_contract_age_h"](24) is None


def test_current_ref_still_attributes_a_branch_artifact(ns):
    # The behaviour the block exists for must survive: a FRESH ref proving a
    # fresh main is still allowed to explain away an old checkout.
    _stub_git(ns, ref_age_h=0.5, contract_age_h=1.6)
    age = ns["main_contract_age_h"](24)
    assert age is not None and age < 24


def test_current_ref_can_still_confirm_a_real_outage(ns):
    # And a fresh ref showing a genuinely stale main must still report that
    # age, so the "not a branch artifact" line stays reachable.
    _stub_git(ns, ref_age_h=0.5, contract_age_h=40.0)
    age = ns["main_contract_age_h"](24)
    assert age is not None and age > 24


def test_caller_explains_an_unattributed_warning():
    """None must not print as silence.

    Without this line the reader sees a bare outage warning and no reason it
    went unexplained — which is how the false alarm read in the first place.
    """
    text = _SCRIPT.read_text(encoding="utf-8")
    assert "Cause NOT attributed" in text
    assert "git fetch origin main" in text
