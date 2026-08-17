"""C1-U9 RED — `C1-SRC-02` is recorded COMPLETE and is not enforced.

WHAT THE MANIFEST SAYS
──────────────────────
``docs/C_SERIES_SCOPE_MANIFEST.md`` records `C1-SRC-02` — "Game type
proven per feed, fails closed on ``UNKNOWN``" — as **COMPLETE for current
sources**, owner ``_RANKING_SOURCES``, evidence "existing tests".

WHAT THE CODE SAYS
──────────────────
There is no ``game_type`` field anywhere in ``_RANKING_SOURCES``,
``server.py`` or ``Dynasty Scraper.py``. There is no fail-closed
behaviour, because there is no state that could be unknown. And there is
no test.

The dynasty-only property is true of today's 21 sources because whoever
registered each one hand-verified it **in a comment**. That is an
unenforced convention: append one entry with a CSV path and it votes
immediately, whatever board it came from.

``docs/MULTI_FORMAT_SOURCE_NORMALIZATION_SPEC.md`` is unambiguous about
the standard this has to meet:

    "Only ``DYNASTY`` observations are eligible for the dynasty
    ranking/value archive and any downstream canonical valuation use.
    ``UNKNOWN/UNVERIFIED`` fails closed and must not be silently
    accepted."  (§1.1)

and §16 item 8 asks for exactly the regression fixture that is missing:
proof that a redraft board cannot be accepted merely because it came
from a provider we trust.

So the manifest row is corrected to what was actually true, and the
guarantee is implemented for the first time. These tests fail today.
"""

from __future__ import annotations

import pytest

from src.api import data_contract as dc


class TestEveryBlendSourceDeclaresItsGameType:
    def test_the_closed_vocabulary_exists(self):
        assert hasattr(
            dc, "GAME_TYPES"
        ), "there is no game-type vocabulary at all — C1-SRC-02 is prose, not a gate"
        assert "DYNASTY" in dc.GAME_TYPES
        assert (
            "UNKNOWN" in dc.GAME_TYPES
        ), "UNKNOWN must be REPRESENTABLE, or 'fails closed on unknown' is meaningless"

    def test_every_registered_source_declares_one(self):
        missing = [s["key"] for s in dc._RANKING_SOURCES if not s.get("game_type")]
        assert not missing, (
            f"{len(missing)} blend sources declare no game type: {missing[:8]}. "
            "A source that votes on dynasty value without saying it IS dynasty is "
            "trusted because of who published it, which is the exact inference the "
            "spec forbids."
        )

    def test_every_declared_value_is_in_the_vocabulary(self):
        bad = [
            (s["key"], s.get("game_type"))
            for s in dc._RANKING_SOURCES
            if s.get("game_type") not in dc.GAME_TYPES
        ]
        assert not bad, bad

    def test_every_blend_source_is_verified_dynasty(self):
        offenders = [
            (s["key"], s.get("game_type"))
            for s in dc._RANKING_SOURCES
            if s.get("game_type") != "DYNASTY"
        ]
        assert not offenders, (
            f"non-dynasty or unverified sources are in the blend: {offenders}. "
            "This is a dynasty product; a redraft or unproven board may not price a "
            "dynasty asset."
        )

    def test_each_source_records_HOW_its_game_type_was_established(self):
        """The spec asks for the *evidence*, not just the label — "explicit
        provider labeling, documented endpoint semantics, page controls,
        source metadata, or another reproducible proof"."""
        missing = [
            s["key"]
            for s in dc._RANKING_SOURCES
            if not str(s.get("game_type_evidence") or "").strip()
        ]
        assert not missing, (
            f"{len(missing)} sources declare a game type with no evidence for it: "
            f"{missing[:8]}. A label nobody can check is the comment we already had."
        )


class TestTheGateFailsClosed:
    def test_a_validator_exists_and_is_called_at_import(self):
        assert hasattr(dc, "_validate_source_game_types_invariant"), (
            "nothing validates game type; an unverified source appended to the registry "
            "would vote on the next build"
        )

    def test_an_unknown_game_type_is_refused(self):
        rogue = dict(dc._RANKING_SOURCES[0])
        rogue["key"] = "rogueUnknown"
        rogue["game_type"] = "UNKNOWN"
        with pytest.raises(Exception) as exc:
            dc._validate_source_game_types_invariant([*dc._RANKING_SOURCES, rogue])
        assert "rogueUnknown" in str(exc.value)

    def test_a_verified_redraft_board_is_refused(self):
        """§16 item 8's regression fixture. A provider we trust for
        dynasty does not make its redraft endpoint dynasty."""
        rogue = dict(dc._RANKING_SOURCES[0])
        rogue["key"] = "ktcRedraft"
        rogue["game_type"] = "REDRAFT"
        rogue["game_type_evidence"] = "KTC's redraft toggle — a different product"
        with pytest.raises(Exception) as exc:
            dc._validate_source_game_types_invariant([*dc._RANKING_SOURCES, rogue])
        assert "ktcRedraft" in str(exc.value)

    def test_an_absent_game_type_is_refused_rather_than_defaulted(self):
        rogue = {k: v for k, v in dc._RANKING_SOURCES[0].items() if k != "game_type"}
        rogue["key"] = "rogueSilent"
        with pytest.raises(Exception) as exc:
            dc._validate_source_game_types_invariant([*dc._RANKING_SOURCES, rogue])
        assert "rogueSilent" in str(exc.value)

    def test_a_verified_dynasty_source_passes(self):
        """The gate must accept the honest case, or it is just a blocker."""
        ok = dict(dc._RANKING_SOURCES[0])
        ok["key"] = "someNewDynastyBoard"
        ok["game_type"] = "DYNASTY"
        ok["game_type_evidence"] = "endpoint /dynasty/rankings, documented as dynasty-only"
        dc._validate_source_game_types_invariant([*dc._RANKING_SOURCES, ok])


class TestTheGateIsReachableFromTheRegistrySurface:
    def test_game_type_is_exported_on_the_public_registry(self):
        rows = dc.get_ranking_source_registry()
        assert rows
        assert all(
            "gameType" in r for r in rows
        ), "the registry surface hides game type, so no consumer can check it"
