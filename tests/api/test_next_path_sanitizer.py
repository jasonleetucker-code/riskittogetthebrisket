"""``?next=`` must reduce to a same-origin path, or be refused.

``_sanitize_next_path`` guards the post-login redirect.  It used to be a
list of string tests — reject ``http://``, ``https://``, anything not
starting with ``/``, anything starting with ``//``, CR and LF — and it was
bypassed by a character it did not name.

``/\\attacker.tld`` starts with ``/``, does not start with ``//``, carries
no scheme prefix and contains no newline, so every guard passed and the
value was returned verbatim.  Browsers normalise ``\\`` to ``/`` when
resolving a URL, so the victim landed on the protocol-relative
``//attacker.tld`` — an arbitrary host, reached from the real domain, after
authenticating.  Driven end to end in Chromium by the master site audit
(finding ``W22-F001``).

The repair is parse-and-compare plus an explicit refusal of the characters
that make the trick work, rather than one more entry on a blocklist that
has already been shown to be incomplete.  These tests pin both halves: the
bypass stays closed, and ordinary paths still round-trip.
"""

from __future__ import annotations

import pytest

import server


# ── The bypass, and its neighbours ────────────────────────────────────

# Every one of these passed the old string tests and reached the browser.
OPEN_REDIRECT_ATTEMPTS = [
    "/\\attacker.tld",  # the reported bypass
    "/\\\\attacker.tld",  # doubled, in case one is stripped
    "\\\\attacker.tld",  # no leading slash at all
    "/\\/attacker.tld",  # mixed separators
    "/legit/\\attacker.tld",  # backslash after a plausible prefix
    "/\tattacker.tld",  # TAB — browsers strip it, then it is //
    "/\nattacker.tld",  # LF
    "/\rattacker.tld",  # CR
]


@pytest.mark.parametrize("raw", OPEN_REDIRECT_ATTEMPTS)
def test_backslash_and_control_characters_cannot_reach_another_origin(raw):
    """The characters that make the bypass work are refused outright.

    Note what is NOT asserted: that the value is *normalised* into some
    safe path.  Refusing is the stronger property — it keeps the output a
    subset of the input, so this function can never invent a destination.
    """
    assert server._sanitize_next_path(raw) == "/"


# The bypasses the old implementation did catch.  They must stay caught —
# the rewrite replaced the string tests wholesale, so these are not
# redundant with the block above.
CLASSIC_ATTEMPTS = [
    "http://attacker.tld",
    "https://attacker.tld",
    "//attacker.tld",
    "javascript:alert(1)",
    "data:text/html,<script>alert(1)</script>",
    "relative/path",
    "",
    "   ",
]


@pytest.mark.parametrize("raw", CLASSIC_ATTEMPTS)
def test_absolute_and_relative_urls_are_still_refused(raw):
    assert server._sanitize_next_path(raw) == "/"


def test_none_falls_back_to_the_default():
    assert server._sanitize_next_path(None) == "/"
    assert server._sanitize_next_path(None, "/rankings") == "/rankings"


# ── Legitimate paths still work ───────────────────────────────────────

# A redirect guard that refuses everything is secure and useless; the
# reason the original was written as a blocklist was to keep these working.
LEGITIMATE = [
    "/",
    "/rankings",
    "/trade",
    "/league?tab=rosTradeDeadline",
    "/rankings?pos=TE&view=app",
    "/draft#board",
    "/market/sharp-roster-percentage",
]


@pytest.mark.parametrize("raw", LEGITIMATE)
def test_same_origin_paths_round_trip(raw):
    assert server._sanitize_next_path(raw) == raw


def test_surrounding_whitespace_is_trimmed_not_rejected():
    assert server._sanitize_next_path("  /rankings  ") == "/rankings"


def test_a_percent_encoded_backslash_is_data_not_a_separator():
    """``%5C`` is an encoded byte in a query value, not a path separator.

    Refusing it would break legitimate links; the browser never turns it
    into a ``/`` because it is not decoded during URL resolution.
    """
    assert server._sanitize_next_path("/p?q=a%5Cb") == "/p?q=a%5Cb"
