"""The curated Sharp surface must actually be reachable, and gated.

Every module here was complete and tested before this file existed -- and
none of it was wired to anything. ``curated_service`` was imported by no
production code, so its six endpoints 404'd; ``consensus`` was called by
nobody, so the person-level concentration safeguard never ran. Tests that
only exercise a module in isolation cannot catch that, so these assert the
connections themselves.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.responses import JSONResponse

import server
from src.sharp import curated_service, market

CURATED_ROUTES = (
    "/api/sharp/people",
    "/api/sharp/people/{person_id}",
    "/api/sharp/review",
    "/api/sharp/review/{candidate_id}",
    "/api/sharp/curated/summary",
    "/api/sharp/curated/refresh",
)


def _paths():
    return [getattr(route, "path", None) for route in server.app.routes]


@pytest.mark.parametrize("path", CURATED_ROUTES)
def test_every_curated_route_is_registered_on_the_real_app(path):
    assert _paths().count(path) == 1


def test_curated_routes_are_not_publicly_readable():
    for path in CURATED_ROUTES:
        assert not server._is_public_api_path(path.replace("{person_id}", "x"))


def test_registration_does_not_depend_on_import_side_effects():
    """Re-running the registrar must be a no-op, not a duplicate route.

    This is what lets ``server.py`` call it explicitly regardless of whether
    the module's own import-time call already ran.
    """
    curated_service._register_http_routes()
    for path in CURATED_ROUTES:
        assert _paths().count(path) == 1


def _admin_gated(monkeypatch, *, verdict):
    """Point the gate resolver at a stub ``_require_admin_session``."""
    monkeypatch.setitem(
        curated_service.sys.modules,
        "server",
        SimpleNamespace(_require_admin_session=lambda _request: verdict),
    )


def test_identity_review_refuses_a_non_admin(monkeypatch):
    denied = JSONResponse(status_code=403, content={"error": "admin_required"})
    _admin_gated(monkeypatch, verdict=denied)
    assert curated_service._require_admin(object()) is denied


def test_identity_review_allows_an_admin(monkeypatch):
    _admin_gated(monkeypatch, verdict={"username": "jason"})
    assert curated_service._require_admin(object()) is None


def test_the_admin_gate_fails_closed_when_unavailable(monkeypatch):
    """No resolvable gate must refuse, never fall through to allowing."""
    monkeypatch.delitem(curated_service.sys.modules, "server", raising=False)
    monkeypatch.setitem(curated_service.sys.modules, "__main__", SimpleNamespace())
    response = curated_service._require_admin(object())
    assert isinstance(response, JSONResponse)
    assert response.status_code == 503


def test_market_calls_person_consensus_and_never_replaces_movement_counts(monkeypatch):
    """One person's three leagues are three movements but ONE vote."""
    movements = [
        {
            "canonicalAssetId": "player:1",
            "displayName": "Test Player",
            "assetType": "player",
            "managerKey": "sleeper:1",
            "canonicalManagerKey": "person:a",
            "action": "add",
            "leagueKey": f"sleeper:L{index}",
            "transactionKey": f"tx{index}",
            "movementKey": f"mv{index}",
            "platform": "sleeper",
            "timestampMs": 1_000 + index,
        }
        for index in range(3)
    ]
    monkeypatch.setattr(
        market.platform_ledger, "query_movements", lambda **_kwargs: list(movements)
    )
    monkeypatch.setattr(
        market,
        "cohort_members",
        lambda **_kwargs: (
            [
                market.CohortMember(
                    manager_key="sleeper:1",
                    platform="sleeper",
                    qualification_method="curated_industry",
                    quality=0.9,
                    person_id="person:a",
                    network="Network A",
                )
            ],
            {},
        ),
    )

    payload = market.market_payload(window="30d", now_ms=10_000)
    row = next(item for item in payload["assets"] if item["assetId"] == "player:1")

    # Raw movement counts are untouched -- they remain the audit trail.
    assert row["buys"] == 3
    assert row["uniqueLeagues"] == 3
    # ...but the person view collapses them to a single expert's opinion.
    assert row["personConsensus"]["personVotes"] == 1
    assert row["personConsensus"]["personBuys"] == 1
    assert row["personConsensus"]["personNet"] == 1


def test_curated_qualifications_do_not_fall_back_to_the_automated_cohort(monkeypatch):
    """``industry``/``super``/``both`` answer a question about researched
    experts. Serving the automated cohort when the curated one is empty would
    answer it with a population that never met that bar."""
    monkeypatch.setattr(
        market.platform_records, "build_manager_records", lambda **_kwargs: ([], {})
    )
    monkeypatch.setattr(
        market.sharp_score,
        "score_managers",
        lambda _records: [
            SimpleNamespace(
                user_id="sleeper:9", score=99.0, qualified=True, methodology_version="v2"
            )
        ],
    )
    monkeypatch.setattr(market.curated_model, "curated_cohort_members", lambda **_kwargs: [])

    for qualification in ("industry", "super", "both"):
        members, coverage = market.cohort_members(
            qualification=qualification, ffpc_config={"enabled": False}
        )
        assert members == []
        assert coverage["curatedIndustryTrackedAccounts"] == 0

    # ...while "all" still includes the automated cohort.
    members, _ = market.cohort_members(qualification="all", ffpc_config={"enabled": False})
    assert [item.manager_key for item in members] == ["sleeper:9"]


def test_an_unbuilt_curated_store_degrades_instead_of_breaking_the_board(monkeypatch):
    def explode(**_kwargs):
        raise RuntimeError("no such table: sharp_platform_accounts")

    monkeypatch.setattr(market.curated_model, "curated_cohort_members", explode)
    assert market.curated_industry_members("industry") == []
