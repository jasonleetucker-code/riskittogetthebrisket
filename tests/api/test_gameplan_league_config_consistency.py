"""W18-F005 — "my league" resolves through the canonical registry.

Before this fix, ``src/api/gameplan.py``'s two scoring-fit resolvers
(``_resolve_reception_fit`` / ``_resolve_scoring_fit``) and
``src/league_comparison/service.py::build_comparison`` each read
``config/league_comparison.json``'s own hard-coded ``my_league.id`` — a
SECOND, independent, off-registry notion of "which league is mine" that
could not agree with (and could not even see) the registry's
``defaultLeagueKey``, and that silently ignored the ``league_key`` a
caller actually requested.  Two live consumers behind LIVE feature
flags (``reception_scoring_fit``, ``idp_scoring_fit``) served every
requested league's gameplan the SAME "my league" scoring card,
regardless of which league was asked for.

The repair: both resolvers now call
``src.api.league_registry.get_sleeper_league_id(league_key)`` — the
same canonical owner every other league-scoped consumer in this
codebase already uses (``server.py::_resolve_league_for_request``,
``src/league_intel/*``, etc).

This file proves two things:

1. POSITIVE CONTROL — requesting two different registered leagues
   (``dynasty_main`` / ``dynasty_new``) resolves two DIFFERENT Sleeper
   ids for "my league", each matching the registry's own answer for
   that league.
2. MUTATION / RED-GREEN — reintroducing the exact defect (a resolver
   that ignores its ``league_key`` argument and always answers with the
   registry's DEFAULT league — the shape the old hard-coded config read
   actually had, one fixed value with no per-league awareness)
   reproduces the wrong-league bug; the real code does not.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.api import feature_flags, gameplan, league_registry

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def real_registry(monkeypatch):
    """Point the league registry at the real repo file (the global
    conftest points ``LEAGUE_REGISTRY_PATH`` at ``/nonexistent`` to
    keep other suites hermetic)."""
    monkeypatch.setenv(
        "LEAGUE_REGISTRY_PATH", str(REPO_ROOT / "config" / "leagues" / "registry.json")
    )
    league_registry.reload_registry()
    yield league_registry
    monkeypatch.undo()
    league_registry.reload_registry()


@pytest.fixture(autouse=True)
def _clear_gameplan_caches():
    gameplan.invalidate_reception_fit_cache()
    gameplan.invalidate_scoring_fit_cache()
    yield
    gameplan.invalidate_reception_fit_cache()
    gameplan.invalidate_scoring_fit_cache()


def _capture_fetch_league_scoring(monkeypatch: pytest.MonkeyPatch, target: str) -> list[str]:
    """Stub ``fetch_league_scoring`` to record every league id it is
    called with, and return a minimal-but-valid scoring card so the
    caller doesn't crash before recording the call."""
    calls: list[str] = []

    def fake(league_id, *, refresh=False):
        calls.append(league_id)
        from src.league_comparison.sleeper_scoring import LeagueScoringInfo

        return LeagueScoringInfo(
            league_id=league_id,
            name="stub",
            season="2025",
            season_type="regular",
            scoring_settings={"rec": 1.0},
            scoring_hash="stubhash",
        )

    monkeypatch.setattr(target, fake)
    return calls


class TestReceptionFitResolvesTheRequestedLeague:
    """``_resolve_reception_fit`` — positive control + mutation proof."""

    def test_two_leagues_resolve_two_different_sleeper_ids(self, real_registry, monkeypatch):
        monkeypatch.setenv("RISKIT_FEATURE_RECEPTION_SCORING_FIT", "1")
        feature_flags.reload()
        monkeypatch.setattr(
            "src.nfl_data.reception_depth.load_reception_depth", lambda *a, **k: {"x": 1}
        )
        monkeypatch.setattr("src.nfl_data.ingest.fetch_weekly_stats", lambda *a, **k: [])
        calls = _capture_fetch_league_scoring(
            monkeypatch, "src.league_comparison.sleeper_scoring.fetch_league_scoring"
        )

        main_id = real_registry.get_sleeper_league_id("dynasty_main")
        new_id = real_registry.get_sleeper_league_id("dynasty_new")
        assert main_id and new_id and main_id != new_id, (
            "fixture registry must carry two distinct, resolvable leagues"
        )

        gameplan._resolve_reception_fit("dynasty_main")
        gameplan.invalidate_reception_fit_cache()
        gameplan._resolve_reception_fit("dynasty_new")
        feature_flags.reload()

        # Call order inside the resolver is mine-then-baseline, so index
        # 0 is "my league" for the dynasty_main request and index 2 is
        # "my league" for the dynasty_new request (index 1/3 = baseline,
        # unchanged across both calls).
        assert len(calls) == 4, f"expected 4 fetch_league_scoring calls, got {calls!r}"
        assert calls[0] == main_id
        assert calls[2] == new_id
        assert calls[0] != calls[2], (
            "the reception-fit resolver returned the SAME 'my league' id for two "
            "different requested leagues -- the exact W18-F005 defect"
        )

    def test_reintroducing_the_hardcoded_bypass_reproduces_the_wrong_league_bug(
        self, real_registry, monkeypatch
    ):
        """RED/GREEN mutation proof.

        A resolver that ignores ``league_key`` (exactly the shape of the
        old ``cfg.get('my_league').get('id')`` read -- one config value,
        no per-league awareness) makes a ``dynasty_new`` request silently
        resolve ``dynasty_main``'s scoring card.  The real code does not.
        """
        monkeypatch.setenv("RISKIT_FEATURE_RECEPTION_SCORING_FIT", "1")
        feature_flags.reload()
        monkeypatch.setattr(
            "src.nfl_data.reception_depth.load_reception_depth", lambda *a, **k: {"x": 1}
        )
        monkeypatch.setattr("src.nfl_data.ingest.fetch_weekly_stats", lambda *a, **k: [])
        calls = _capture_fetch_league_scoring(
            monkeypatch, "src.league_comparison.sleeper_scoring.fetch_league_scoring"
        )

        main_id = real_registry.get_sleeper_league_id("dynasty_main")
        new_id = real_registry.get_sleeper_league_id("dynasty_new")
        assert main_id != new_id

        real_get_sleeper_league_id = league_registry.get_sleeper_league_id

        # --- RED: reintroduce the exact W18-F005 shape ---------------
        def buggy_get_sleeper_league_id(key=None):
            return main_id  # ignores `key`, same as a hardcoded config value

        monkeypatch.setattr(
            "src.api.league_registry.get_sleeper_league_id", buggy_get_sleeper_league_id
        )
        gameplan._resolve_reception_fit("dynasty_new")
        assert calls, "mutated resolver never reached fetch_league_scoring"
        assert calls[0] == main_id, (
            "MUTATION DID NOT REPRODUCE THE DEFECT: expected the mutated resolver to "
            "request dynasty_main's card for a dynasty_new lookup"
        )
        assert calls[0] != new_id

        # --- restore GREEN: undo just this one patch, same request ---
        monkeypatch.setattr(
            "src.api.league_registry.get_sleeper_league_id", real_get_sleeper_league_id
        )
        gameplan.invalidate_reception_fit_cache()
        calls.clear()
        gameplan._resolve_reception_fit("dynasty_new")
        feature_flags.reload()
        assert calls[0] == new_id, (
            "REGRESSION: restoring the real get_sleeper_league_id did not fix the "
            "wrong-league resolution"
        )


class TestScoringFitResolvesTheRequestedLeague:
    """``_resolve_scoring_fit`` — the same defect, the IDP-fit twin."""

    def test_two_leagues_resolve_two_different_sleeper_ids(self, real_registry, monkeypatch):
        monkeypatch.setenv("RISKIT_FEATURE_IDP_SCORING_FIT", "1")
        feature_flags.reload()
        monkeypatch.setattr("src.nfl_data.ingest.fetch_weekly_defensive_stats", lambda *a, **k: [])
        calls = _capture_fetch_league_scoring(
            monkeypatch, "src.league_comparison.sleeper_scoring.fetch_league_scoring"
        )

        main_id = real_registry.get_sleeper_league_id("dynasty_main")
        new_id = real_registry.get_sleeper_league_id("dynasty_new")
        assert main_id and new_id and main_id != new_id

        gameplan._resolve_scoring_fit("dynasty_main")
        gameplan.invalidate_scoring_fit_cache()
        gameplan._resolve_scoring_fit("dynasty_new")
        feature_flags.reload()

        assert len(calls) == 4, f"expected 4 fetch_league_scoring calls, got {calls!r}"
        assert calls[0] == main_id
        assert calls[2] == new_id
        assert calls[0] != calls[2], (
            "the scoring-fit resolver returned the SAME 'my league' id for two "
            "different requested leagues -- the exact W18-F005 defect"
        )


class TestCrossConsumerAgreement:
    """The concrete W18-F005 / P1-12-R16 acceptance bar: two independent
    consumers -- ``src/league_comparison/service.py::build_comparison``
    and ``src/api/gameplan.py``'s resolvers -- must resolve the exact
    same Sleeper id for "my league", for the same registry state.
    Before this fix they could not even structurally agree: one read
    the registry, the other read a hard-coded config file the registry
    knows nothing about.
    """

    def test_service_and_gameplan_resolve_the_same_my_league_id(
        self, real_registry, monkeypatch, tmp_path
    ):
        from src.league_comparison import historical_stats as _stats_mod
        from src.league_comparison import service as _service

        monkeypatch.setenv("RISKIT_FEATURE_IDP_SCORING_FIT", "1")
        feature_flags.reload()
        monkeypatch.setattr("src.nfl_data.ingest.fetch_weekly_defensive_stats", lambda *a, **k: [])
        # build_comparison needs SOME stat rows to avoid an all-seasons-
        # unavailable warning path; None is a valid "season not covered"
        # signal it already handles, well short of the full fixture used
        # by tests/league_comparison/test_service.py.
        monkeypatch.setattr(_stats_mod, "load_season_rows", lambda season: None)
        monkeypatch.setattr(_service, "_cache_dir", lambda: tmp_path / "lc_cache")
        calls = _capture_fetch_league_scoring(
            monkeypatch, "src.league_comparison.sleeper_scoring.fetch_league_scoring"
        )

        gameplan._resolve_scoring_fit("dynasty_main")
        assert calls, "gameplan resolver never reached fetch_league_scoring"
        gameplan_my_id = calls[0]
        calls.clear()

        _service.build_comparison(refresh=True)
        assert calls, "build_comparison never reached fetch_league_scoring"
        service_my_id = calls[0]
        feature_flags.reload()

        registry_id = real_registry.get_sleeper_league_id("dynasty_main")
        assert gameplan_my_id == service_my_id == registry_id, (
            "service.py and gameplan.py disagree on 'my league' for the same "
            f"registry state: gameplan={gameplan_my_id!r} service={service_my_id!r} "
            f"registry={registry_id!r}"
        )
