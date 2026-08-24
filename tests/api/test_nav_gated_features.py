"""V1-131 / audit F-25 — the nav must not offer a page whose endpoints 503.

This is the BACKEND half. It does two things the frontend test cannot:

1. **Reproduces the defect's precondition against the real router.** The
   frontend gate is only worth having if the endpoints genuinely refuse
   while the flag is off, so that is asserted here against the mounted
   ``src/consensus_edge/api.py`` rather than assumed from its source.

2. **Pins the capability channel.** ``/api/auth/status`` is the one probe
   the shell already makes on every route (``useAuth``), so the nav
   capability rides it instead of adding a second request — V1-108
   ("non-data routes stop fetching the contract") is VERIFIED and a new
   per-page fetch to learn a boolean would regress it.

A correction to the row's own wording, recorded by measurement rather
than inherited: the row says "its three endpoints 503". The BOARD
endpoints do. ``/methodology`` deliberately does not — it answers 200
with ``enabled: false`` so a user can read what the feature claims
without seeing a board. The requirement is unaffected (the page is still
unusable), and that endpoint is why an honest capability signal exists at
all.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import server
from src.api import feature_flags


@pytest.fixture(autouse=True)
def _known_allowlist(monkeypatch):
    monkeypatch.setattr(
        server,
        "PRIVATE_APP_ALLOWED_USERNAMES",
        frozenset({"jasonleetucker"}),
    )
    yield


def _authed(monkeypatch, username: str = "jasonleetucker") -> None:
    monkeypatch.setattr(server, "_is_authenticated", lambda r: True)
    monkeypatch.setattr(server, "_get_auth_session", lambda r: {"username": username})


def _raises() -> bool:
    """A capability resolver that blows up, standing in for a renamed or
    broken feature module."""
    raise RuntimeError("feature module moved")


def _set_contract(monkeypatch, loaded: bool) -> None:
    """The SECOND condition the board handlers gate on: without a loaded
    contract they answer 503 data_not_ready even with the flag on."""
    monkeypatch.setattr(
        server, "latest_contract_data", {"players": {}} if loaded else None, raising=False
    )


def _set_flag(monkeypatch, name: str, value: bool) -> None:
    """Force one flag's effective value without touching the registry."""
    real = feature_flags.is_enabled
    monkeypatch.setattr(
        feature_flags,
        "is_enabled",
        lambda n, _r=real, _n=name, _v=value: _v if n == _n else _r(n),
    )


# ── 1. the precondition: the board really does refuse while off ──────


# /methodology is deliberately absent — it is the documented exception.
BOARD_ENDPOINTS = [
    "/api/consensus-edge/players",
    "/api/consensus-edge/top",
    "/api/consensus-edge/health",
]


@pytest.mark.parametrize("path", BOARD_ENDPOINTS)
def test_board_endpoints_503_while_the_flag_is_off(monkeypatch, path):
    """The reason the nav entry was a dead end. Measured, not assumed.

    Authenticated, because these routes gate on auth BEFORE the flag —
    anonymously they answer 401. That ordering is why the nav gate is
    the right repair: the dead end is what a SIGNED-IN user hits, which
    is exactly who the nav offers the entry to.
    """
    _authed(monkeypatch)
    _set_flag(monkeypatch, "consensus_edge", False)
    with TestClient(server.app, raise_server_exceptions=True) as c:
        res = c.get(path)
    assert res.status_code == 503, f"{path} answered {res.status_code}, expected 503"
    assert (res.json() or {}).get("flag") == "consensus_edge"


def test_methodology_is_the_documented_exception(monkeypatch):
    """Corrects the row's "three endpoints" wording with a measurement.

    If this ever starts 503-ing, the capability signal below is still
    correct but this file's rationale needs rewriting — so it is pinned
    rather than left as a comment.
    """
    _authed(monkeypatch)
    _set_flag(monkeypatch, "consensus_edge", False)
    with TestClient(server.app, raise_server_exceptions=True) as c:
        res = c.get("/api/consensus-edge/methodology")
    assert res.status_code == 200
    assert res.json()["enabled"] is False


# ── 2. the capability channel ────────────────────────────────────────


@pytest.mark.parametrize("path", BOARD_ENDPOINTS)
def test_board_endpoints_401_anonymously(monkeypatch, path):
    """Auth is checked before the flag. Recorded because the 401 masked
    the 503 on the first run of this file and would otherwise be
    rediscovered by whoever touches it next."""
    monkeypatch.setattr(server, "_get_auth_session", lambda r: None)
    monkeypatch.setattr(server, "_is_authenticated", lambda r: False)
    _set_flag(monkeypatch, "consensus_edge", False)
    with TestClient(server.app, raise_server_exceptions=True) as c:
        assert c.get(path).status_code == 401


def test_auth_status_reports_the_capability_off(monkeypatch):
    _authed(monkeypatch)
    _set_flag(monkeypatch, "consensus_edge", False)
    with TestClient(server.app, raise_server_exceptions=True) as c:
        body = c.get("/api/auth/status").json()
    assert body["authenticated"] is True
    assert body["features"]["consensusEdge"]["available"] is False


def test_auth_status_reports_the_capability_on(monkeypatch):
    _authed(monkeypatch)
    _set_flag(monkeypatch, "consensus_edge", True)
    with TestClient(server.app, raise_server_exceptions=True) as c:
        body = c.get("/api/auth/status").json()
    assert body["features"]["consensusEdge"]["available"] is True


def test_capability_tracks_the_endpoints_rather_than_a_constant(monkeypatch):
    """The signal must be the SAME fact the router gates on.

    A hardcoded ``False`` would pass both tests above while silently
    hiding the page from the operator who turned the flag on to evaluate
    it — which ADR-023 explicitly preserves. So assert the two agree in
    both directions, on the same process, in one test.
    """
    _authed(monkeypatch)
    for enabled in (True, False):
        _set_flag(monkeypatch, "consensus_edge", enabled)
        with TestClient(server.app, raise_server_exceptions=True) as c:
            reported = c.get("/api/auth/status").json()["features"]["consensusEdge"]["available"]
            board = c.get("/api/consensus-edge/players").status_code
        assert reported is enabled
        assert (
            board != 503
        ) is enabled, f"capability says {reported} but the board answered {board}"


def test_values_are_real_booleans(monkeypatch):
    """The frontend gate offers only on ``=== true``.

    Anything truthy-but-not-true (1, "yes") would be silently treated as
    "do not offer" there, so a non-boolean here is a wire-format bug that
    presents as a vanished menu entry.
    """
    _authed(monkeypatch)
    with TestClient(server.app, raise_server_exceptions=True) as c:
        features = c.get("/api/auth/status").json()["features"]
    assert features
    for key, block in features.items():
        assert isinstance(block, dict), f"{key} is {type(block).__name__}, not an object"
        assert isinstance(
            block.get("available"), bool
        ), f"{key}.available is {type(block.get('available')).__name__}, not bool"


# ── 3. it fails closed, and it cannot take auth down ─────────────────


def test_unknown_flag_yields_false_and_does_not_raise(monkeypatch):
    """Fail closed, per flag.

    ``feature_flags.is_enabled`` raises KeyError for an unregistered
    flag. Letting that escape would 500 ``/api/auth/status`` — the probe
    the whole shell depends on — so a flag rename would log every user
    out of their own chrome. Not offering a destination is the safe
    failure; losing the nav, the switchers and the login affordance is
    not.
    """
    monkeypatch.setattr(
        server,
        "_NAV_GATED_CAPABILITIES",
        {"phantom": _raises},
    )
    assert server._nav_gated_features() == {"phantom": {"available": False}}


def test_auth_status_survives_a_broken_flag_registry(monkeypatch):
    _authed(monkeypatch)
    monkeypatch.setattr(
        server,
        "_NAV_GATED_CAPABILITIES",
        {"phantom": _raises},
    )
    with TestClient(server.app, raise_server_exceptions=True) as c:
        res = c.get("/api/auth/status")
    assert res.status_code == 200
    assert res.json()["features"] == {"phantom": {"available": False}}


def test_signed_out_response_is_unchanged(monkeypatch):
    """No capability leaks to an anonymous caller, and the shape is the
    same one the logged-out shell has always parsed.

    Safe because ``/consensus-edge`` is a private route: the logged-out
    nav already filters it by ``isPublicPath``, so the gate has nothing
    to add there.
    """
    monkeypatch.setattr(server, "_get_auth_session", lambda r: None)
    with TestClient(server.app, raise_server_exceptions=True) as c:
        body = c.get("/api/auth/status").json()
    assert body == {"authenticated": False}


# ── 4. availability is not the flag (the owner's truth table) ────────


@pytest.mark.parametrize(
    ("flag_on", "contract_loaded", "expected"),
    [
        (True, True, True),  # the only state that may be offered
        (True, False, False),  # flag on, board still 503 data_not_ready
        (False, True, False),  # flag off
        (False, False, False),
    ],
)
def test_capability_requires_flag_AND_data(monkeypatch, flag_on, contract_loaded, expected):
    """`available` must mean "the board can actually be served".

    This is the case a flag-only gate gets wrong, and it is not
    hypothetical: the board handlers answer 503 on TWO independent
    conditions, and for the whole window where the flag is on and no
    contract is loaded, a flag-keyed nav would advertise a dead page.
    """
    _authed(monkeypatch)
    _set_flag(monkeypatch, "consensus_edge", flag_on)
    # Patch the contract INSIDE the client context: entering it fires
    # FastAPI startup, which loads a real contract and would overwrite a
    # patch applied beforehand — silently turning the flag-on/no-data
    # case into flag-on/data-present and passing for the wrong reason.
    with TestClient(server.app, raise_server_exceptions=True) as c:
        _set_contract(monkeypatch, contract_loaded)
        body = c.get("/api/auth/status").json()
    assert body["features"]["consensusEdge"]["available"] is expected


@pytest.mark.parametrize(
    ("flag_on", "contract_loaded"),
    [(True, True), (True, False), (False, True), (False, False)],
)
def test_capability_and_the_board_never_disagree(monkeypatch, flag_on, contract_loaded):
    """One owner, checked in every combination.

    `src.consensus_edge.api.is_available` is the single predicate; the
    nav capability and the board handler must not be able to drift into
    disagreeing about whether the page works.
    """
    _authed(monkeypatch)
    _set_flag(monkeypatch, "consensus_edge", flag_on)
    with TestClient(server.app, raise_server_exceptions=True) as c:
        _set_contract(monkeypatch, contract_loaded)  # after startup — see above
        reported = c.get("/api/auth/status").json()["features"]["consensusEdge"]["available"]
        board = c.get("/api/consensus-edge/players").status_code
    assert reported is (board != 503), (
        f"capability says available={reported} but /players answered {board} "
        f"(flag_on={flag_on}, contract_loaded={contract_loaded})"
    )


def test_the_capability_asks_the_feature_rather_than_reading_a_flag(monkeypatch):
    """Structural: server.py must not re-derive feature health.

    A second derivation here is how the nav and the router start
    disagreeing. The registry holds callables that resolve the feature's
    own owner, so patching that owner must move the published answer.
    """
    _authed(monkeypatch)
    import src.consensus_edge.api as ce  # noqa: PLC0415

    monkeypatch.setattr(ce, "is_available", lambda: True)
    with TestClient(server.app, raise_server_exceptions=True) as c:
        assert c.get("/api/auth/status").json()["features"]["consensusEdge"]["available"] is True
    monkeypatch.setattr(ce, "is_available", lambda: False)
    with TestClient(server.app, raise_server_exceptions=True) as c:
        assert c.get("/api/auth/status").json()["features"]["consensusEdge"]["available"] is False
