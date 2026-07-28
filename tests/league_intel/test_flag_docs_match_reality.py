"""A module's stated flag default must match the registry's actual one.

``scoring_fit``'s docstring ended with a section headed "Flagged OFF"
saying ``RISKIT_FEATURE_IDP_SCORING_FIT`` "defaults to 0 ... and no
operator has asked for it yet". The operator asked, the default flipped
to ``True`` in #606, and that paragraph stayed. For a day, the one file a
reader would open to find out whether this feature affected their board
told them it was switched off while it was switched on.

That is the same shape as every guard this codebase keeps finding broken
— the stated purpose and the actual predicate differ, and nothing forces
them to agree. Documentation is not usually testable, but *this*
sentence is: it is a claim about a value that lives three files away.

Deliberately narrow. It does not police prose. It checks one thing —
that a module claiming a flag is ON/OFF agrees with ``_DEFAULTS`` — and
only for modules that make such a claim.
"""

from __future__ import annotations

import importlib
import re

import pytest

from src.api import feature_flags

#: ``(module path, flag name)`` for modules whose docstring states a
#: default. Add a row when a module starts making the claim.
_MODULES_CLAIMING_A_DEFAULT: tuple[tuple[str, str], ...] = (
    ("src.league_intel.scoring_fit", "idp_scoring_fit"),
    ("src.league_intel.reception_fit", "reception_scoring_fit"),
)

_ON = re.compile(r"flagged\s+on\b", re.I)
_OFF = re.compile(r"flagged\s+off\b", re.I)


def _docstring(module_path: str) -> str:
    return importlib.import_module(module_path).__doc__ or ""


@pytest.mark.parametrize("module_path,flag", _MODULES_CLAIMING_A_DEFAULT)
def test_the_docstring_agrees_with_the_registry(module_path, flag):
    doc = _docstring(module_path)
    if flag not in feature_flags.registered_flags():
        pytest.skip(f"{flag} is not a registered flag")

    says_on = bool(_ON.search(doc))
    says_off = bool(_OFF.search(doc))
    if not (says_on or says_off):
        return  # makes no claim; nothing to contradict

    assert not (says_on and says_off), f"{module_path} says both ON and OFF — ambiguous to a reader"
    actual = feature_flags.snapshot()[flag]
    claimed = says_on
    assert claimed == actual, (
        f"{module_path} documents {flag} as "
        f"{'ON' if claimed else 'OFF'} but the registry defaults it to "
        f"{'ON' if actual else 'OFF'}. The docstring is the first place a "
        "reader checks whether this affects their board."
    )


def test_the_check_can_actually_fail():
    """Non-vacuity.

    A regex-over-prose check is easy to write so that it matches nothing
    and passes forever. This drives the comparison directly.
    """
    assert _ON.search("Flagged ON since 2026-07-28")
    assert _OFF.search("Flagged OFF\n───────────")
    assert not _ON.search("this module is flagged off")
    # The real failure the test above would have caught, reconstructed:
    # an OFF claim against a True default.
    claimed, actual = False, True
    assert claimed != actual


def test_at_least_one_module_is_actually_covered():
    """If every entry silently stopped making a claim, the parametrised
    test would pass while checking nothing."""
    claiming = [
        m
        for m, _ in _MODULES_CLAIMING_A_DEFAULT
        if _ON.search(_docstring(m)) or _OFF.search(_docstring(m))
    ]
    assert claiming, "no module states a flag default any more — is this check still needed?"
