"""C6-MGR-01 — Manager Scout is PRIVATE decision intelligence.

OWNER_PRODUCT_BACKLOG_SPEC §7: "Private only.  Do not publish opponent-facing
Buyer/Seller recommendations or negotiation tendencies on ``/league``."  The
boundary is held four ways, each tested here:

1. the route is not on any public allowlist and 401s anonymously;
2. no public-league module can import the scout;
3. the public field blocklist refuses the scout's block names, so a future
   edit that wires them into a public payload fails at build time;
4. the public ``/league`` contract, built end to end from fixtures, carries
   none of them.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

REPO = Path(__file__).resolve().parents[2]

SCOUT_FIELDS = (
    "managerScout",
    "tradeTendencies",
    "waiverTendencies",
    "faabTendencies",
    "lineupTendencies",
)


def test_the_route_is_not_public():
    import server

    assert server._is_public_api_path("/api/manager-scout") is False


def test_an_anonymous_caller_gets_401():
    import server

    with TestClient(server.app) as c:
        res = c.get("/api/manager-scout")
    assert res.status_code == 401
    assert res.json()["error"] == "auth_required"


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_no_public_league_module_imports_the_scout():
    offenders = [
        str(p.relative_to(REPO))
        for p in (REPO / "src" / "public_league").rglob("*.py")
        if any(n.startswith("src.intel.manager_scout") for n in _imports(p))
    ]
    assert not offenders, offenders


@pytest.mark.parametrize("field", SCOUT_FIELDS)
def test_the_public_payload_guard_refuses_scout_fields(field):
    from src.public_league.public_contract import assert_public_payload_safe

    with pytest.raises(AssertionError):
        assert_public_payload_safe({"sections": {"x": [{field: {}}]}})


def test_the_public_league_contract_carries_no_scout_field():
    from src.public_league import build_public_contract, build_public_snapshot
    from tests.public_league.fixtures import build_stub_client, install_stubs

    install_stubs(build_stub_client())
    contract = build_public_contract(build_public_snapshot("L2025", max_seasons=2))
    blob = json.dumps(contract)
    for field in SCOUT_FIELDS:
        assert f'"{field}"' not in blob
