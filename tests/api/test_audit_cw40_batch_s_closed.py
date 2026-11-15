"""CW-40 Batch S (security / auth / ops) -- findings CONFIRMED CLOSED on ``main`` (2026-11-07).

Re-adjudicated offline from the live code path (TestClient, synthetic inputs), not from the
August repro or the CW-07 label:

* W22-F001  open redirect through ``next=/\\evil.com`` -- end to end through the login route;
* W22-F002  rate-limit key is attacker-chosen (``X-Forwarded-For``) -- rotating the header from
  an UNTRUSTED peer must not mint new identities;
* W22-F003  login has no throttle -- repeated wrong passwords with rotating spoofed headers get a
  429 + ``Retry-After`` before any credential comparison;
* W03-F010  ``POST /api/rankings/overrides`` rewrites the shared rank snapshot -- the snapshot and
  its write path are deleted; ``_stamp_rank_changes`` writes nothing.

Unit-level pins already exist (``test_next_path_sanitizer.py``, ``test_client_ip_trust.py``,
``test_login_throttle.py``, ``tests/history/test_temporal_red.py``); these add the end-to-end
and behavioral guarantees the unit tests do not.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import server
from src.api import data_contract, rate_limit

REPO = Path(__file__).resolve().parents[2]
OWNER = "owneruser"
OWNER_PW = "correct-horse-not-a-real-secret"


@pytest.fixture(autouse=True)
def _login_env(monkeypatch):
    # TestClient's peer is the literal host "testclient": NOT a trusted proxy unless listed.
    monkeypatch.delenv("RATE_LIMIT_TRUSTED_PROXIES", raising=False)
    monkeypatch.setattr(server, "JASON_LOGIN_USERNAME", OWNER)
    monkeypatch.setattr(server, "JASON_LOGIN_PASSWORD", OWNER_PW)
    monkeypatch.setattr(server._guest_passes, "validate", lambda pw: None)
    rate_limit.reset_for_tests()
    yield
    rate_limit.reset_for_tests()


@pytest.mark.parametrize(
    "evil",
    ["/\\evil.com", "/\\\\evil.com", "/\\tevil.com", "//evil.com", "https://evil.com", "/%0d%0a"],
)
def test_w22_f001_login_never_returns_a_cross_origin_redirect(evil):
    client = TestClient(server.app)
    res = client.post(
        "/api/auth/login",
        json={"username": OWNER, "password": OWNER_PW, "next": evil},
    )
    assert res.status_code == 200, res.text
    redirect = res.json()["redirect"]
    # "/%0d%0a" is a same-origin path (percent-encoded, data not a separator); everything else
    # must collapse to the default.
    assert redirect in (
        "/",
        evil if evil == "/%0d%0a" else "/",
    ), f"next={evil!r} leaked into the redirect: {redirect!r}"


def test_w22_f001_same_origin_next_still_round_trips():
    client = TestClient(server.app)
    res = client.post(
        "/api/auth/login",
        json={"username": OWNER, "password": OWNER_PW, "next": "/trade?x=1"},
    )
    assert res.json()["redirect"] == "/trade?x=1"


def test_w22_f002_f003_rotating_spoofed_xff_cannot_evade_the_login_throttle():
    """The August repro: 200 wrong passwords, a fresh X-Forwarded-For each, zero 429.

    The peer here is untrusted, so the spoofed headers are ignored and every attempt is charged
    to the one TCP peer; the failure throttle must trip.
    """
    client = TestClient(server.app)
    codes = []
    for i in range(30):
        res = client.post(
            "/api/auth/login",
            json={"username": OWNER, "password": f"wrong-{i}"},
            headers={"X-Forwarded-For": f"198.51.100.{i}", "X-Real-IP": f"203.0.113.{i}"},
        )
        codes.append(res.status_code)
    assert 429 in codes, f"no throttle in {len(codes)} wrong-password attempts: {codes}"
    blocked = client.post(
        "/api/auth/login",
        json={"username": OWNER, "password": OWNER_PW},
        headers={"X-Forwarded-For": "192.0.2.250"},
    )
    # The correct password is refused DURING backoff: the check precedes the comparison.
    assert blocked.status_code == 429
    assert int(blocked.headers["Retry-After"]) >= 1


def test_w22_f002_public_limiter_key_ignores_spoofed_header_from_untrusted_peer():
    client = TestClient(server.app)
    seen_429 = False
    for i in range(80):
        res = client.get("/api/health", headers={"X-Forwarded-For": f"198.51.100.{i % 250}"})
        if res.status_code == 429:
            seen_429 = True
            break
    assert seen_429, "80 public requests with rotating X-Forwarded-For never hit the 60/min limit"


def test_w03_f010_rank_change_stamping_is_read_only(tmp_path):
    """No build kind may write a rank baseline: ``rankChange`` is derived, not stored."""
    assert "write_snapshot" not in inspect.signature(data_contract._stamp_rank_changes).parameters
    source = inspect.getsource(data_contract._stamp_rank_changes)
    for forbidden in ("write_text", "open(", "json.dump", "os.replace", "rename("):
        assert forbidden not in source, f"_stamp_rank_changes contains {forbidden!r}"
    ledger = tmp_path / "absent_ledger.sqlite"
    rows = [{"canonicalConsensusRank": 5, "displayName": "A"}]
    data_contract._stamp_rank_changes(rows, board_date="2026-11-07", ledger_path=ledger)
    assert rows[0]["rankChange"] is None  # no comparator -> None, never 0
    assert list(tmp_path.iterdir()) == [], "stamping created a file"


def test_w03_f010_no_executable_reference_to_the_retired_snapshot_file():
    offenders = []
    base = REPO / "src"
    for path in [REPO / "server.py", *sorted(base.rglob("*.py"))]:
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if "ranks_last.json" in line and not line.lstrip().startswith(("#", '"', "'")):
                offenders.append(f"{path.relative_to(REPO)}:{n}: {line.strip()[:80]}")
    assert offenders == [], offenders
