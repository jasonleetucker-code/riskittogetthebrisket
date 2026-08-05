"""The post-login redirect must never leave the origin.

`_sanitize_next_path` guarded with a blocklist — reject `http://`,
`https://`, `//`, newline — and a backslash walked through it:
`/login?next=/\\attacker.tld` satisfied every check, and browsers normalise
`\\` to `/`, so the redirect resolved to `//attacker.tld`.

That is the standard credential-phishing amplifier. The link is on the real
domain, the login page is the real login page, the password is real, and the
victim lands on the attacker's site with no cue that the origin changed.
Audit finding W22-F001; reproduced end to end in Chromium before the fix.

The guard is now an allowlist, so the tests below are written the way the
threat is: a corpus of encodings a browser might resolve differently than a
naive string check, each of which must come back as the default. A blocklist
only has to miss one.
"""

from __future__ import annotations

import os
import unittest

os.environ.setdefault("ALLOW_DEFAULT_LOGIN_DEV", "1")

import server  # noqa: E402


class TestSanitizeNextPathRejectsOffOrigin(unittest.TestCase):
    # Each entry must resolve to the default, not to another origin.
    HOSTILE = [
        "/\\evil.com",  # the live bypass: browsers read \ as /
        "/\\/evil.com",
        "/\\\\evil.com",
        "\\\\evil.com",
        "//evil.com",
        "///evil.com",
        "http://evil.com",
        "https://evil.com",
        "HTTP://evil.com",
        "HtTpS://evil.com",
        "javascript:alert(1)",
        "data:text/html,<script>alert(1)</script>",
        "/\tevil.com",  # control chars some clients strip before resolving
        "/\nevil.com",
        "/\revil.com",
        "/\x00evil.com",
        "\x0b//evil.com",
        "evil.com",  # no leading slash at all
        "../evil",
    ]

    def test_every_hostile_form_falls_back_to_default(self):
        for raw in self.HOSTILE:
            with self.subTest(raw=raw):
                self.assertEqual(server._sanitize_next_path(raw), "/")

    def test_hostile_forms_respect_a_custom_default(self):
        for raw in self.HOSTILE:
            with self.subTest(raw=raw):
                self.assertEqual(server._sanitize_next_path(raw, default="/login"), "/login")

    def test_empty_and_missing(self):
        self.assertEqual(server._sanitize_next_path(None), "/")
        self.assertEqual(server._sanitize_next_path(""), "/")
        self.assertEqual(server._sanitize_next_path("   "), "/")


class TestSanitizeNextPathKeepsRealDestinations(unittest.TestCase):
    """The fix must not break the feature it guards."""

    LEGITIMATE = [
        "/",
        "/rankings",
        "/trade",
        "/league?tab=power",
        "/league/franchise/jasonleetucker",
        "/rankings?pos=TE&sort=value",
        "/players/compare?a=1&b=2",
        "/a/b#section",
    ]

    def test_same_origin_paths_survive(self):
        for raw in self.LEGITIMATE:
            with self.subTest(raw=raw):
                self.assertEqual(server._sanitize_next_path(raw), raw)

    def test_returns_the_validated_string_not_the_raw_input(self):
        """Never hand back a string that was not the one checked.

        Returning `raw` after validating a normalized copy would redirect
        to something this function never examined.
        """
        out = server._sanitize_next_path("/rankings")
        self.assertEqual(out, "/rankings")
        self.assertNotIn("\\", server._sanitize_next_path("/ok\\path"))


if __name__ == "__main__":
    unittest.main()
