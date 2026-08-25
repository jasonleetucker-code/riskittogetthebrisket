"""V1-102 (#780) — the evidence the existing suites do not already carry.

ACCEPTANCE, verbatim from ``docs/OWNER_FEATURE_INVENTORY.md`` §13.6:

    #780 — repair/verify configurable-hours temporary password/pass
    generation end to end, including actual authentication, expiry and
    revocation/fail-closed semantics.

The capability is ALREADY IMPLEMENTED on main (``src/api/guest_passes.py``
plus the three ``/api/admin/guest-pass*`` endpoints and the ``/admin``
panel). This file therefore adds guards ONLY where nothing deterministic
proves a clause. Reuse over duplication — what already exists:

| clause | already proven by |
|---|---|
| generation returns a pass + plaintext | ``test_guest_passes.py::test_create_returns_pass_and_plaintext_token`` |
| plaintext never persisted | ``test_guest_passes.py::test_token_is_not_stored_in_plaintext``, ``::test_to_dict_omits_token_hash`` |
| no plaintext over the wire | ``test_admin_endpoints.py::test_guest_pass_list_returns_metadata_without_token`` |
| duration is range-checked | ``test_guest_passes.py::test_create_rejects_zero_duration``, ``::test_create_rejects_excessive_duration`` |
| expiry fails closed (unit) | ``test_guest_passes.py::test_validate_rejects_expired_token`` |
| revocation fails closed (unit) | ``test_guest_passes.py::test_validate_rejects_revoked_token`` |
| create/list/revoke over HTTP, admin-gated | ``test_admin_endpoints.py::test_guest_pass_create_*``, ``::test_guest_pass_list_*``, ``::test_guest_pass_revoke_marks_revoked`` |
| ACTUAL AUTHENTICATION (happy path) | ``test_admin_endpoints.py::test_guest_pass_login_creates_time_bounded_session`` |
| unknown token refused at login | ``test_admin_endpoints.py::test_invalid_guest_token_returns_401`` |
| the deployed panel renders it | ``tests/e2e/specs/admin-guest-pass.spec.js`` (production build) |

WHAT WAS MISSING, and is added here:

1. **Fail-closed at the AUTHENTICATION boundary.** The unit tests prove
   ``validate()`` rejects an expired or revoked token. Nothing proved
   that ``/api/auth/login`` — the surface a real guest actually uses —
   refuses one. The acceptance names "expiry and revocation/fail-closed
   semantics" in the same breath as "actual authentication", so the
   guard belongs at that boundary, not only under it.
2. **The configured duration is HONOURED**, not merely range-checked.
   Rejecting 0 and 10⁶ says nothing about whether asking for 3 hours
   gets you 3 hours — a `create()` that ignored its argument and always
   minted 12h would pass every existing test.
3. **The session is bounded BY the pass**, not by the standard ceiling.
4. **Generation is cryptographically appropriate** — a CSPRNG, not
   ``random``. ``len(token) >= 20`` is an entropy proxy that
   ``"a" * 32`` would satisfy.
5. **One owner.** The endpoints delegate to ``guest_passes`` rather than
   re-deriving, and no second temp-password/auth subsystem exists.
"""

from __future__ import annotations

import ast
import re
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import server
from src.api import guest_passes

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def _known_allowlist(monkeypatch):
    monkeypatch.setattr(server, "PRIVATE_APP_ALLOWED_USERNAMES", frozenset({"admin"}))
    monkeypatch.setattr(server, "JASON_LOGIN_USERNAME", "admin")
    monkeypatch.setattr(server, "JASON_LOGIN_PASSWORD", "admin-pwd")
    yield


@pytest.fixture
def db(monkeypatch, tmp_path):
    """Isolated pass store — same pattern as test_admin_endpoints."""
    path = tmp_path / "guest_passes.sqlite"
    monkeypatch.setattr(guest_passes, "_DEFAULT_DB_PATH", path)
    monkeypatch.setattr(guest_passes, "_setup_done_paths", set())
    return path


@pytest.fixture(autouse=True)
def _drain_no_rate_limit_budget():
    """Leave the shared rate-limit bucket as we found it.

    `/api/auth/status` and `/api/auth/login` are both in
    `_PUBLIC_API_EXACT`, so every request this module makes spends from a
    60/min per-IP budget that the WHOLE suite shares — and under
    `TestClient` every test is the same client IP. This file adds dozens
    of such calls, which is enough to push a later, unrelated test over
    the edge and make it fail with 429 instead of its real assertion.

    That is not hypothetical: it is how
    `test_public_league_privacy_boundary.py::test_the_csv_variant_is_closed_too`
    started reporting "answered 429 anonymously" for a route this change
    never touches.

    `reset_for_tests` is the limiter's own sanctioned hook. Nothing about
    production rate limiting changes, and no assertion anywhere is
    weakened — this only stops one module's request volume from becoming
    another module's failure.
    """
    from src.api import rate_limit  # noqa: PLC0415

    rate_limit.reset_for_tests()
    yield
    rate_limit.reset_for_tests()


def _anonymous(monkeypatch) -> None:
    monkeypatch.setattr(server, "_get_auth_session", lambda r: None)
    monkeypatch.setattr(server, "_is_authenticated", lambda r: False)


def _login(client: TestClient, token: str):
    return client.post("/api/auth/login", json={"username": "", "password": token})


# ── 1. fail closed at the AUTHENTICATION boundary ────────────────────


def test_expired_token_is_refused_at_login(db, monkeypatch):
    """The acceptance's "expiry ... fail-closed semantics", at the door a
    guest actually uses rather than at the helper underneath it."""
    _pass, token = guest_passes.create(duration_hours=1.0, db_path=db)
    # Travel past the expiry rather than sleeping.  `guest_passes.time`
    # IS the stdlib module, so the replacement must close over the REAL
    # function captured first — a lambda calling `time.time()` after the
    # patch calls itself and recurses until the stack dies.
    real_time = time.time
    monkeypatch.setattr(guest_passes.time, "time", lambda: real_time() + 3 * 3600)
    _anonymous(monkeypatch)
    with TestClient(server.app, raise_server_exceptions=True) as c:
        res = _login(c, token)
    assert res.status_code == 401, res.text
    # And the refusal must not confirm the token ever existed.
    assert "expire" not in res.text.lower()


def test_revoked_token_is_refused_at_login(db, monkeypatch):
    """The acceptance's "revocation ... fail-closed semantics"."""
    pass_row, token = guest_passes.create(duration_hours=12.0, db_path=db)
    assert guest_passes.revoke(pass_row.id, db_path=db) is True
    _anonymous(monkeypatch)
    with TestClient(server.app, raise_server_exceptions=True) as c:
        res = _login(c, token)
    assert res.status_code == 401, res.text


def test_revocation_takes_effect_immediately(db, monkeypatch):
    """A pass that authenticated a moment ago must stop doing so.

    Revocation that only applied to future logins would leave a
    compromised credential live for its full configured window.
    """
    pass_row, token = guest_passes.create(duration_hours=12.0, db_path=db)
    _anonymous(monkeypatch)
    with TestClient(server.app, raise_server_exceptions=True) as c:
        assert _login(c, token).status_code == 200
        guest_passes.revoke(pass_row.id, db_path=db)
        assert _login(c, token).status_code == 401


# ── 2. the configured duration is HONOURED ───────────────────────────


@pytest.mark.parametrize("hours", [0.5, 1.0, 3.0, 24.0, 720.0])
def test_configured_duration_is_honored(db, hours):
    """Range-checking is not honouring.

    A ``create()`` that ignored its argument and always minted 12 h
    would pass every pre-existing duration test; this is what makes the
    "configurable-hours" clause true rather than merely accepted.
    """
    before = time.time()
    pass_row, _token = guest_passes.create(duration_hours=hours, db_path=db)
    after = time.time()
    expected_lo = before + hours * 3600.0
    expected_hi = after + hours * 3600.0
    assert (
        expected_lo - 1 <= pass_row.expires_at_epoch <= expected_hi + 1
    ), f"asked for {hours}h, got {(pass_row.expires_at_epoch - before) / 3600:.4f}h"


def test_distinct_durations_produce_distinct_expiries(db):
    """Guards the degenerate pass of the test above: a constant would
    satisfy a single-value check but not two that must differ."""
    short, _ = guest_passes.create(duration_hours=1.0, db_path=db)
    long_, _ = guest_passes.create(duration_hours=48.0, db_path=db)
    assert long_.expires_at_epoch - short.expires_at_epoch == pytest.approx(47 * 3600, abs=5)


# ── 3. the SESSION is bounded by the pass ────────────────────────────


def test_session_cookie_is_bounded_by_the_pass_not_the_ceiling(db, monkeypatch):
    """A short pass must not mint a standard-length session.

    The existing end-to-end test asserts ``expiresAtEpoch`` is present in
    the body; presence is not a bound. This asserts the cookie's own
    max-age, which is what a browser acts on.
    """
    _pass, token = guest_passes.create(duration_hours=1.0, db_path=db)
    _anonymous(monkeypatch)
    with TestClient(server.app, raise_server_exceptions=True) as c:
        res = _login(c, token)
    assert res.status_code == 200, res.text
    cookie = res.headers.get("set-cookie", "")
    m = re.search(r"[Mm]ax-[Aa]ge=(\d+)", cookie)
    assert m, f"no Max-Age on the guest session cookie: {cookie!r}"
    max_age = int(m.group(1))
    assert 0 < max_age <= 3600 + 5, f"1h pass minted a {max_age}s cookie"
    assert (
        max_age < server.JASON_AUTH_COOKIE_MAX_AGE
    ), "guest session took the standard ceiling instead of the pass's remaining life"


def test_guest_session_is_not_admin(db, monkeypatch):
    """A temporary password must not be able to mint more of itself."""
    _pass, token = guest_passes.create(duration_hours=12.0, db_path=db)
    _anonymous(monkeypatch)
    with TestClient(server.app, raise_server_exceptions=True) as c:
        assert _login(c, token).status_code == 200
        # Cookie is on the client now; the admin mint route must refuse.
        res = c.post("/api/admin/guest-pass", json={"durationHours": 1})
    assert res.status_code in (401, 403), res.text


# ── 4. generation is cryptographically appropriate ───────────────────


def test_token_generation_uses_a_csprng():
    """Structural: ``secrets``, never ``random``.

    Asserted on the AST rather than by statistics — a distribution test
    over a handful of samples cannot distinguish ``random`` from
    ``secrets``, and that is precisely the substitution that would
    matter here.
    """
    src = (REPO_ROOT / "src" / "api" / "guest_passes.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    imported = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    assert "secrets" in imported, "guest_passes must generate tokens with `secrets`"
    assert "random" not in imported, "`random` is not a CSPRNG — tokens must not use it"

    calls = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and isinstance(n.func.value, ast.Name)
        and n.func.value.id == "secrets"
    ]
    assert calls, "no secrets.* call found in guest_passes"


def test_tokens_are_unique_and_high_entropy(db):
    tokens = {guest_passes.create(duration_hours=1.0, db_path=db)[1] for _ in range(50)}
    assert len(tokens) == 50, "token collision in 50 draws"
    for t in tokens:
        # 24 URL-safe bytes -> 32 chars, ~192 bits.
        assert len(t) >= 32, f"token too short: {len(t)}"
        assert re.fullmatch(r"[A-Za-z0-9_-]+", t), f"non-URL-safe token: {t!r}"
    # Not a constant-ish string: at least 12 distinct characters.
    assert all(len(set(t)) >= 12 for t in tokens)


# ── 5. one owner ─────────────────────────────────────────────────────


def test_admin_endpoints_delegate_to_the_canonical_owner(db, monkeypatch):
    """create / list / revoke must call ``guest_passes``, not re-derive.

    Patching the owner and observing the endpoints follow is what proves
    delegation; a second implementation would sail past this.
    """
    monkeypatch.setattr(server, "_is_authenticated", lambda r: True)
    monkeypatch.setattr(server, "_get_auth_session", lambda r: {"username": "admin"})
    seen: list[str] = []

    sentinel_pass, sentinel_token = guest_passes.create(duration_hours=1.0, db_path=db)

    def fake_create(**kwargs):
        seen.append("create")
        return sentinel_pass, sentinel_token

    def fake_list(**kwargs):
        seen.append("list")
        return [sentinel_pass]

    def fake_revoke(pass_id, **kwargs):
        seen.append("revoke")
        return True

    monkeypatch.setattr(server._guest_passes, "create", fake_create)
    monkeypatch.setattr(server._guest_passes, "list_passes", fake_list)
    monkeypatch.setattr(server._guest_passes, "revoke", fake_revoke)

    with TestClient(server.app, raise_server_exceptions=True) as c:
        assert c.post("/api/admin/guest-pass", json={"durationHours": 2}).status_code == 200
        assert c.get("/api/admin/guest-passes").status_code == 200
        assert c.post(f"/api/admin/guest-pass/{sentinel_pass.id}/revoke").status_code == 200

    assert seen == ["create", "list", "revoke"], f"endpoints bypassed the owner: {seen}"


def test_no_second_temp_password_owner_exists():
    """Structural single-owner guard.

    The whole reason V1-102 was recorded NOT STARTED is that its
    capability was hard to see. The failure mode that recording invites
    is someone implementing a SECOND generator to satisfy the row — the
    duplicate auth subsystem it explicitly forbids. This fails if one
    appears.
    """
    offenders: list[str] = []
    token_gen = re.compile(r"token_urlsafe|token_hex|token_bytes")
    for path in list((REPO_ROOT / "src").rglob("*.py")) + [REPO_ROOT / "server.py"]:
        rel = path.relative_to(REPO_ROOT).as_posix()
        if rel == "src/api/guest_passes.py":
            continue  # the canonical owner
        text = path.read_text(encoding="utf-8", errors="ignore")
        if not token_gen.search(text):
            continue
        # A CSRF/session/nonce generator is a different concept; only
        # flag one that also talks about passwords or passes.
        if re.search(r"pass(word|_row|es)|guest", text, re.IGNORECASE):
            offenders.append(rel)
    assert offenders == [], (
        "a second temporary-password generator appears to exist in: "
        + ", ".join(offenders)
        + " — V1-102 requires ONE owner (src/api/guest_passes.py)"
    )


def test_the_admin_panel_is_wired_to_these_endpoints():
    """The production consumer calls the canonical routes.

    Cheap, and it closes the gap between "the backend is correct" and
    "the surface the owner uses reaches it". The rendered behaviour is
    proven separately against a real production build in
    ``tests/e2e/specs/admin-guest-pass.spec.js``.
    """
    panel = (REPO_ROOT / "frontend" / "components" / "admin" / "GuestPassPanel.jsx").read_text(
        encoding="utf-8"
    )
    for route in (
        "/api/admin/guest-pass",
        "/api/admin/guest-passes",
        "/revoke",
    ):
        assert route in panel, f"admin panel does not call {route}"
    admin_page = (REPO_ROOT / "frontend" / "app" / "admin" / "page.jsx").read_text(encoding="utf-8")
    assert "GuestPassPanel" in admin_page, "/admin does not mount the panel"
