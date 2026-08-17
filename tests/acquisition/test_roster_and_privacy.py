"""C1-U8 — roster reconstruction (``C1-ACQ-02``) and the privacy boundary.

ROSTER
──────
An interval query is the easy half.  The half worth testing is that the
answer says how much it is guessing: ``exact`` when every covering
holding is dated, ``partial`` when one is inferred, and ``unavailable``
when the instant precedes every recorded event.

That last distinction is the one a caller will get wrong if we let them:
an empty roster and "no evidence covers this instant" render identically
and mean opposite things.

PRIVACY
───────
This is real managers' real transaction history.  The tests assert the
boundary structurally — no public surface may import the package — so
the guard survives a refactor that moves a route, rather than depending
on someone remembering.
"""

from __future__ import annotations

import ast
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.acquisition import store as store_mod
from src.acquisition.roster import (
    FIDELITY_EXACT,
    FIDELITY_PARTIAL,
    FIDELITY_UNAVAILABLE,
    roster_at,
)

REPO = Path(__file__).resolve().parents[2]
LEAGUE = "dynasty_main"

_T0 = datetime(2026, 8, 1, tzinfo=timezone.utc)
_T1 = _T0 + timedelta(days=10)
_T2 = _T0 + timedelta(days=20)


def _ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


@pytest.fixture
def db(tmp_path):
    store_mod._reset_setup_cache_for_tests()
    path = tmp_path / "retention" / "acquisition.sqlite"
    yield path
    store_mod._reset_setup_cache_for_tests()


def _seed(path, holdings, *, earliest_event_ms: int | None = _ms(_T0)) -> None:
    store_mod.replace_derivations(LEAGUE, holdings, [], path=path)
    if earliest_event_ms is None:
        return
    from src.acquisition.events import AcquisitionEvent

    store_mod.write_events(
        [
            AcquisitionEvent(
                league_key=LEAGUE,
                source_ref="tx:seed",
                asset_id="player:seed",
                asset_kind="player",
                event_type="TRADE",
                after_owner_rid=1,
                occurred_at_ms=earliest_event_ms,
            )
        ],
        path=path,
    )


def _holding(asset_id, owner, acquired, disposed=None, method="TRADE", seq=1):
    return {
        "league_key": LEAGUE,
        "asset_id": asset_id,
        "owner_rid": owner,
        "sequence_num": seq,
        "acquired_at_ms": acquired,
        "acquired_ref": "tx:x",
        "acquired_method": method,
        "disposed_at_ms": disposed,
        "disposed_ref": None,
        "disposed_method": None,
        "basis_value": None,
        "basis_fidelity": None,
        "basis_missing_reason": None,
        "order_fidelity": "ordered",
    }


class TestRosterAtADate:
    def test_an_asset_held_across_the_instant_is_included(self, db):
        _seed(db, [_holding("player:A", 1, _ms(_T0), _ms(_T2))])
        result = roster_at(LEAGUE, _T1, path=db)
        assert [a["assetId"] for a in result["assets"]] == ["player:A"]
        assert result["fidelity"] == FIDELITY_EXACT

    def test_an_asset_disposed_before_the_instant_is_excluded(self, db):
        _seed(db, [_holding("player:A", 1, _ms(_T0), _ms(_T1))])
        assert roster_at(LEAGUE, _T2, path=db)["assets"] == []

    def test_an_asset_acquired_after_the_instant_is_excluded(self, db):
        _seed(db, [_holding("player:A", 1, _ms(_T2))])
        assert roster_at(LEAGUE, _T1, path=db)["assets"] == []

    def test_it_can_be_scoped_to_one_roster(self, db):
        _seed(
            db,
            [
                _holding("player:A", 1, _ms(_T0)),
                _holding("player:B", 2, _ms(_T0)),
            ],
        )
        mine = roster_at(LEAGUE, _T1, owner_rid=1, path=db)
        assert [a["assetId"] for a in mine["assets"]] == ["player:A"]

    def test_an_undated_holding_degrades_fidelity_to_partial(self, db):
        _seed(db, [_holding("player:A", 1, None, method="IMPORT_UNKNOWN")])
        result = roster_at(LEAGUE, _T1, path=db)
        assert result["assets"], "an inferred membership is still a membership"
        assert result["fidelity"] == FIDELITY_PARTIAL
        assert result["inferredMemberships"] == 1


class TestUnavailableIsNotEmpty:
    def test_no_events_at_all_reports_unavailable(self, db):
        store_mod.connect(db).close()
        result = roster_at(LEAGUE, _T1, path=db)
        assert result["fidelity"] == FIDELITY_UNAVAILABLE
        assert result["missingReason"] == "no_recorded_events"

    def test_an_instant_before_the_first_event_reports_unavailable(self, db):
        _seed(db, [_holding("player:A", 1, _ms(_T1))], earliest_event_ms=_ms(_T1))
        result = roster_at(LEAGUE, _T0, path=db)
        assert result["fidelity"] == FIDELITY_UNAVAILABLE, (
            "an empty roster and 'we have no evidence covering this instant' render "
            "identically and mean opposite things"
        )
        assert result["missingReason"] == "before_first_recorded_event"

    def test_a_naive_instant_is_refused(self, db):
        with pytest.raises(ValueError, match="UTC-aware"):
            roster_at(LEAGUE, datetime(2026, 8, 1), path=db)


class TestThePrivacyBoundaryHolds:
    def _imports(self, path: Path) -> set[str]:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError):
            return set()
        names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.update(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                names.add(node.module)
        return names

    def test_no_public_league_surface_imports_the_package(self):
        offenders = [
            str(p.relative_to(REPO))
            for p in (REPO / "src" / "public_league").rglob("*.py")
            if any(n.startswith("src.acquisition") for n in self._imports(p))
        ]
        assert not offenders, (
            f"the public-league surface imports private acquisition history: {offenders}. "
            "The B8 boundary publishes factual retrospective content only through the "
            "public-league snapshots, which build from their own sources."
        )

    def test_the_frontend_does_not_reach_it(self):
        hits = [
            str(p.relative_to(REPO))
            for p in (REPO / "frontend").rglob("*.js*")
            if "node_modules" not in p.parts
            and "acquisition.sqlite" in p.read_text(encoding="utf-8", errors="ignore")
        ]
        assert not hits, hits

    def test_the_database_is_gitignored(self):
        import subprocess

        probe = REPO / "data" / "retention" / "acquisition.sqlite"
        out = subprocess.run(
            ["git", "check-ignore", "-q", str(probe)], cwd=REPO, capture_output=True
        )
        assert out.returncode == 0, (
            f"{probe} is not gitignored — private league history must never be able to "
            "reach public git history, deliberately or by a stray `git add -f`"
        )

    def test_it_lives_beside_the_other_private_store_not_inside_it(self):
        from src.retention.league_events import DB_PATH as EVENTS_DB

        assert (
            store_mod.DB_PATH.parent == EVENTS_DB.parent
        ), "same root so one env var redirects both"
        assert store_mod.DB_PATH != EVENTS_DB, (
            "separate FILE so 'back this up' and 'publish this' can never be the same "
            "gesture by accident"
        )
        assert store_mod.PRIVACY_CLASS == "private"


class TestTheRetentionInvariantSurvives:
    def test_acquisition_reads_retention_payloads_not_its_read_api(self):
        """``src/retention/__init__.py`` states that nothing there may be
        read by a decision path.  This package is a decision path, so it
        must consume raw transaction payloads (via the collector) rather
        than importing retention's read surface into a projection."""
        for module in ("events", "holdings", "basis", "roster", "store"):
            src = (REPO / "src" / "acquisition" / f"{module}.py").read_text(encoding="utf-8")
            assert "transaction_coverage" not in src, module
            assert "from src.retention.league_events import" not in src, module
