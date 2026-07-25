"""Expected-source structural pruning (Source Audit correctness).

Pins the 2026-07-25 fix for the "DLF RK / Flock RK: Expected but did
not match" false alarms: rookie-translation sources rank the CURRENT
rookie class only, so they are structurally expected for rookies alone
— never for veterans (a second-year player like Colston Loveland is
inside their scope+depth window but can never appear on a
current-class-only board) and never for pick rows.
"""

from __future__ import annotations

import unittest

from src.api.data_contract import _RANKING_SOURCES, _expected_sources_for_position

_ROOKIE_XLATE_KEYS = {
    str(s.get("key") or "") for s in _RANKING_SOURCES if s.get("needs_rookie_translation")
}


class TestRookieSourceExpectation(unittest.TestCase):
    def test_registry_still_has_rookie_translation_sources(self):
        # Guard the guard: if the flag disappears from the registry the
        # other tests here would vacuously pass.
        self.assertTrue(_ROOKIE_XLATE_KEYS)

    def test_veteran_never_expects_rookie_boards(self):
        off, idp = _expected_sources_for_position("TE", is_rookie=False, player_effective_rank=30)
        self.assertFalse((_ROOKIE_XLATE_KEYS & off) | (_ROOKIE_XLATE_KEYS & idp))

    def test_rookie_expects_rookie_boards(self):
        off, _idp = _expected_sources_for_position("TE", is_rookie=True, player_effective_rank=10)
        self.assertTrue(_ROOKIE_XLATE_KEYS & off)

    def test_idp_rookie_expects_idp_rookie_board(self):
        _off, idp = _expected_sources_for_position("DB", is_rookie=True, player_effective_rank=10)
        self.assertIn("dlfRookieIdp", idp)
        _off2, idp2 = _expected_sources_for_position(
            "DB", is_rookie=False, player_effective_rank=10
        )
        self.assertNotIn("dlfRookieIdp", idp2)

    def test_picks_never_expect_rookie_boards(self):
        off, idp = _expected_sources_for_position("PICK", is_rookie=True)
        self.assertFalse((_ROOKIE_XLATE_KEYS & off) | (_ROOKIE_XLATE_KEYS & idp))


if __name__ == "__main__":
    unittest.main()
