"""Global test fixtures."""

from __future__ import annotations

import os
import tempfile

import pytest

# Allow ``import server`` in tests without a real JASON_LOGIN_PASSWORD.
# The placeholder "changeme" is acceptable for unit/integration tests;
# production rejects ALLOW_DEFAULT_LOGIN_DEV=1 by design.
os.environ.setdefault("ALLOW_DEFAULT_LOGIN_DEV", "1")

# ── The suite must not write into the real retention stores ──────────
# C1A wired retention recorders into two LIVE code paths —
# ``league_registry.write_scoring_snapshot`` and
# ``sleeper_overlay._build_trades_block`` — which this suite exercises
# with fixture data. Measured before this redirect: a full run left
# leagues "111", "222", "L-MAIN", "L-SIDE", "LM", "LS", "LT" and four
# fixture leagues' trades sitting in ``data/retention/*.sqlite``.
#
# Those stores are append-only evidence about production, and this
# tranche exists to protect them. A test run that can contaminate them
# is a test run that corrupts the thing under test. Set BEFORE
# ``src.retention`` is imported — the module reads it at import time —
# which conftest guarantees, since collection imports test modules after
# this file runs.
#
# ``setdefault``: an operator who deliberately points it somewhere keeps
# their choice.
os.environ.setdefault(
    "RISKIT_RETENTION_DIR",
    os.path.join(tempfile.gettempdir(), f"riskit-retention-test-{os.getpid()}"),
)

# ── The suite does not depend on the live site being up ───────────────
# ``server`` reads UPTIME_CHECK_ENABLED at import (production default
# True) and its lifespan runs ``check_uptime_once`` — a blocking
# ``urlopen`` against UPTIME_CHECK_URL — on a worker thread the shutdown
# then joins.  Every ``TestClient`` therefore made a real request to
# production and every ``__exit__`` waited on it.
#
# Measured 2026-08-12, while production's ``/api/`` was accepting
# connections and not answering: 6.07s per TestClient, of which startup
# was 0.009s.  Two tests went 12.59s → 1.94s with the watchdog off.  The
# whole ``PR Validation`` job stopped fitting in its 20-minute budget and
# was killed three times — including on a previously-green commit — so a
# production outage read as a broken pull request instead of failing
# anything honestly.
#
# ``setdefault``, not an assignment: a test that wants the watchdog sets
# the variable itself, and the production default is untouched.  The
# boundary is here rather than a pytest sniff inside ``server`` — product
# code must not behave differently because it suspects it is under test.
# ``.github/workflows/pr-validation.yml`` states it again in the
# unit-test step so the CI policy is visible rather than inherited.
os.environ.setdefault("UPTIME_CHECK_ENABLED", "0")

# ── Sleeper league context isolation ──────────────────────────────────
# ``src/api/data_contract.py::_resolve_league_context`` reads the
# operator's Sleeper league to derive the roster count (rookie-pick
# anchor) and the TE-premium multiplier (``bonus_rec_te``).  During
# tests we must not hit the live Sleeper API — it is slow and flaky, and
# a live fetch would make every fixture's expected TE value depend on
# whatever the commissioner set this season.
#
# CORRECTED 2026-07-27 (collaborative audit).  This comment used to
# justify the isolation by saying "the operator's league has
# bonus_rec_te=0.5".  That is no longer true and contradicts
# ``data_contract.py``'s own retraction: the 2026 league reports
# ``bonus_rec_te = 0.0`` — a real, exposed zero, not missing data — and
# no other TE-touching key advantages the position either
# (``bonus_fd_te`` is 1.0, but so are ``bonus_fd_wr`` and
# ``bonus_fd_rb``).  Measured 2026 TE premium: ×1.000.
#
# Worth stating plainly: the fallback below lands on the same numbers the
# live league would produce today, so the suite agrees with reality by
# coincidence rather than by construction.  That means the live
# derivation branch is NOT exercised by this suite — a test that wants it
# must monkeypatch explicitly, as noted below.
#
# Clearing the env var makes ``_resolve_league_context`` return its
# fallback dict (roster_count=12, bonus_rec_te=0.0, derived TEP=1.0),
# which matches the pre-derivation behavior of every fixture-based
# test in this suite.  Tests that WANT to exercise derivation
# explicitly monkeypatch ``_resolve_league_context`` or
# ``_derive_tep_multiplier_from_league``.
os.environ.pop("SLEEPER_LEAGUE_ID", None)

# The league registry (``src/api/league_registry``) is the new source
# of truth for Sleeper league IDs — ``_resolve_league_context`` now
# reads from it first, falling back to the env var.  For tests we
# point the registry at a non-existent file so its env-var fallback
# path kicks in, and because we've cleared SLEEPER_LEAGUE_ID above,
# the registry returns None.  Net effect: no live Sleeper fetches,
# same as before the registry existed.
os.environ["LEAGUE_REGISTRY_PATH"] = "/nonexistent/path/for/tests.json"
try:
    from src.api import league_registry as _league_registry

    _league_registry.reload_registry()
except Exception:  # noqa: BLE001 — conftest must never block collection
    pass

# The cache is keyed by the env var, but some tests import
# data_contract before pytest runs this conftest (in which case the
# cache may already carry a live Sleeper snapshot from a prior dev
# session).  Clear it defensively.
try:
    from src.api import data_contract as _data_contract

    _data_contract._LEAGUE_CONTEXT_CACHE.clear()
    _data_contract._LEAGUE_CONTEXT_CACHE["context"] = None
    _data_contract._LEAGUE_CONTEXT_CACHE["fetched_at"] = 0.0
except Exception:  # noqa: BLE001 — conftest must never block collection
    pass


# ── Live-data CI tiering ──────────────────────────────────────────────
# A handful of tests assert against the LIVE scraped board
# (``exports/latest/dynasty_data_*.json`` / ``CSVs/site_raw/*``).  They
# are correctness-valuable but DATA-COUPLED: a routine source row-count
# dip or scrape churn fails them with NO code defect, and because CI
# runs ``pytest -x`` that single failure blocks EVERY PR (it did so
# repeatedly this audit — e.g. a yahooBoone row dip stalled all PRs).
# Mark these modules ``livedata`` so CI runs them as a NON-blocking
# advisory tier while the pure-logic suite stays the hard gate.
# Module-granularity by design: one central, reviewable policy instead
# of editing ~16 files; a new live-data test just adds its module here.
# (test_source_floor_invariant.py is intentionally NOT here — it is the
# pure static pre-merge guard and must keep blocking.)
_LIVEDATA_MODULES = frozenset(
    {
        "test_launch_readiness.py",
        "test_source_monitoring.py",
        # ``test_footballguys_source.py`` was listed here and does not
        # exist — a dead exemption.  Removed 2026-07-27;
        # ``test_livedata_policy.py`` now fails on a stale entry, since
        # an exemption list nobody can check is how the pick-anchor
        # split below went unnoticed.
        "test_picks_end_to_end.py",
        "test_pick_refinement.py",
        "test_pick_rookie_anchor.py",
        "test_player_identity_regression.py",
        "test_single_curve_live.py",
        "test_single_authority.py",
        "test_per_source_freshness.py",
        # ``test_data_contract.py`` was listed here and is 100% SYNTHETIC:
        # every test builds its input from ``_minimal_raw_payload()`` and
        # the module contains no reference to exports/, CSVs/, data/ or
        # the live contract.  The exemption moved 33 tests covering
        # ``build_api_data_contract`` — rank assignment, value-direct
        # voting, the single-source haircut, OVERALL_RANK_LIMIT,
        # legacy-dict mirroring, IDP integrity guardrails, hillCurves
        # stamping — out of the hard gate, so a real regression in the
        # core blend could not fail a PR.  This is the same defect the
        # module docstring of ``test_livedata_policy.py`` records for
        # ``test_pick_rookie_anchor.py``, in a second file.
        #
        # Removed 2026-08-04 (audit finding Q-1).  Unlike the pick-anchor
        # case no split was needed — the module is synthetic in whole, so
        # it simply rejoins the blocking tier.  Verified: 33 passed in
        # 1.37s with no data files present.
        "test_dlf_source.py",
        # ``test_dlf_scraper.py`` was listed here and is WHOLLY PURE.
        # Its own docstring says so — "these tests exercise the
        # offline-safe pure functions: HTML table parsing, paywall
        # detection, and CSV write" — and it reads only inline HTML
        # fixtures and ``tmp_path``.  Its single mention of
        # ``CSVs/site_raw/`` asserts that a CONFIG STRING starts with
        # that prefix; it never touches the tree.
        #
        # Removed 2026-08-04.  Same shape as the ``test_data_contract.py``
        # case above and no split needed: 13 tests, 0.28s, no data files
        # present.  They guard DLF's HTML parse and paywall detection —
        # the ingestion path for four registry sources — and a real
        # regression there could not fail a PR while they sat in the
        # advisory tier.
        #
        # STILL OPEN: ``test_dlf_source.py`` (above) carries
        # ``TestDlfCsvEnrichment``, whose own comment says it builds a
        # temporary CSV "without touching the real CSVs/site_raw tree".
        # That one needs the pick-anchor treatment — a split, not a
        # removal, because the rest of the module genuinely reads live
        # data.  ``test_livedata_policy.py`` records it as open.
        "test_fantasypros_idp_integration.py",
        "test_ktc_reconciliation.py",
        "test_fetch_flock_fantasy_rookies.py",
        # ``test_faab_calibration.py`` — added 2026-08-16.  Its own
        # docstring says what it is: "These are the tests that would
        # catch a recalibration going wrong.  They run against the REAL
        # exported board rather than a synthetic one."  Its anchors are
        # resolved FROM that board (``resolve_anchors(values, league)``),
        # so when a scrape loses a market the replacement line moves and
        # value points that were at replacement no longer are.  Measured
        # during the 2026-08-16 KTC outage: a 1,000-value player priced
        # at 2% of budget instead of 0% and recommended $7 instead of
        # $1, with ``faab_engine`` byte-identical.
        #
        # The ENGINE's deterministic invariants are unaffected and stay
        # in the blocking tier: ``tests/trade/test_faab_engine.py``
        # builds a SYNTHETIC board and already pins
        # ``objective_ceiling(v_repl - 1) == 0``,
        # ``objective_ceiling(v_allin) == 1``, the monotonicity of the
        # curve and the raw-ceiling cap.  What moves to the advisory
        # tier is only the claim that TODAY'S REAL BOARD lands its
        # anchors where the two managers said they should — a
        # calibration claim about live data, which is what this tier is
        # for.
        "test_faab_calibration.py",
    }
)


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "livedata: asserts against the live scraped board/exports; "
        "data-coupled — runs as a non-blocking advisory CI tier, not "
        "the hard gate (see _LIVEDATA_MODULES in tests/conftest.py).",
    )


def pytest_collection_modifyitems(config, items):
    for item in items:
        try:
            fname = item.path.name
        except Exception:  # noqa: BLE001 — never block collection
            continue
        if fname in _LIVEDATA_MODULES:
            item.add_marker(pytest.mark.livedata)
