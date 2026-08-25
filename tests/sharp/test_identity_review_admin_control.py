"""V1-104 — the human-review control over sharp identity mappings.

Inventory 6.9's V1-required scope (narrow: sharp identities only): a human
admin must be able to review/approve/reject identity candidates, the decision
must actually move the canonical cohort owner, and every decision must leave
an audit trail naming WHO decided and WHEN.

What this file pins beyond ``test_curated_wiring.py`` (which tests the gate
helper in isolation) and ``test_curated_model.py`` (which tests the model):

* the REAL route enforces the gate — deleting the guard from
  ``decide_candidate`` or ``refresh_curated`` turns these RED, because the
  spies prove a refused request never reaches the decision or the refresh;
* the audit trail's "who" is the AUTHENTICATED session identity, never a
  body-supplied claim — before 2026-08-25 the route read ``reviewer`` from
  the request body with a constant ``"admin"`` default, and the admin UI
  never sends one, so every real decision was recorded under the same name;
* an approval changes what the canonical cohort selection
  (``curated_cohort_members`` — the function ``src/sharp/cohort.py``
  consumes) returns, and a rejection never does;
* both decisions land in ``sharp_review_decisions`` with reviewer, reason
  and a real ``decided_ms``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import server
from src.sharp import curated, curated_service

SNAPSHOT = Path(__file__).parents[2] / "config" / "sharp" / "curated_universe.json"


def _snapshot():
    return json.loads(SNAPSHOT.read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def _stub_allowlist(monkeypatch):
    monkeypatch.setattr(
        server,
        "PRIVATE_APP_ALLOWED_USERNAMES",
        frozenset({"jasonleetucker"}),
    )
    yield


def _authed_admin(monkeypatch):
    monkeypatch.setattr(server, "_is_authenticated", lambda r: True)
    monkeypatch.setattr(
        server,
        "_get_auth_session",
        lambda r: {"username": "jasonleetucker"},
    )


def _authed_guest(monkeypatch):
    """A session that exists but is NOT allowlisted — the guest-pass shape."""
    monkeypatch.setattr(server, "_is_authenticated", lambda r: True)
    monkeypatch.setattr(
        server,
        "_get_auth_session",
        lambda r: {"username": "guest", "auth_method": "guest_pass"},
    )


# ── the route gate, exercised through the real app ─────────────────


def test_review_decision_no_session_is_401():
    with TestClient(server.app, raise_server_exceptions=True) as c:
        res = c.post("/api/sharp/review/some-candidate", json={"decision": "approve"})
    assert res.status_code == 401
    assert res.json().get("error") == "auth_required"


def test_review_decision_guest_session_is_403_and_never_decides(monkeypatch):
    calls: list[tuple] = []

    def spy(*args, **kwargs):
        calls.append((args, kwargs))
        return {"candidateId": "x", "decision": "approve", "status": "verified"}

    monkeypatch.setattr(curated_service.curated, "review_candidate", spy)
    _authed_guest(monkeypatch)
    with TestClient(server.app, raise_server_exceptions=True) as c:
        res = c.post("/api/sharp/review/some-candidate", json={"decision": "approve"})
    assert res.status_code == 403, res.text
    assert res.json().get("error") == "admin_required"
    assert calls == [], "a 403'd request must never record a review decision"


def test_curated_refresh_guest_session_is_403_and_never_refreshes(monkeypatch):
    calls: list[dict] = []

    def spy(**kwargs):
        calls.append(kwargs)
        return {}

    monkeypatch.setattr(curated_service, "_refresh_pipeline", spy)
    _authed_guest(monkeypatch)
    with TestClient(server.app, raise_server_exceptions=True) as c:
        res = c.post("/api/sharp/curated/refresh", json={})
    assert res.status_code == 403, res.text
    assert res.json().get("error") == "admin_required"
    assert calls == [], "a 403'd request must never spend the refresh budget"


def test_admin_decision_is_attributed_to_the_session_not_the_body(monkeypatch):
    """The audit "who" comes from the authenticated session.

    The body carries a spoofed ``reviewer`` claim; the recorded reviewer must
    be the allowlisted session's username. Pre-fix this recorded the body
    claim (or the constant "admin" — the admin UI sends no reviewer at all).
    """
    captured: list[dict] = []

    def spy(candidate_id, decision, *, reviewer="admin", reason=None, **kwargs):
        captured.append(
            {
                "candidateId": candidate_id,
                "decision": decision,
                "reviewer": reviewer,
                "reason": reason,
            }
        )
        return {"candidateId": candidate_id, "decision": decision, "status": "rejected_match"}

    monkeypatch.setattr(curated_service.curated, "review_candidate", spy)
    _authed_admin(monkeypatch)
    with TestClient(server.app, raise_server_exceptions=True) as c:
        res = c.post(
            "/api/sharp/review/some-candidate",
            json={"decision": "reject", "reviewer": "somebody_else", "reason": "not them"},
        )
    assert res.status_code == 200, res.text
    assert len(captured) == 1
    assert captured[0]["reviewer"] == "jasonleetucker"
    assert captured[0]["reviewer"] != "somebody_else"
    assert captured[0]["reason"] == "not them"


# ── the decision moves the canonical cohort owner ──────────────────


def _prepare_candidate(ledger, *, user_id="900001"):
    """Import the workbook and walk one Sleeper candidate to a stable
    platform id (the precondition for approval), without deciding it."""
    curated.import_snapshot(_snapshot(), ledger_path=ledger)
    conn = curated.ensure_schema(ledger)
    try:
        row = conn.execute(
            """
            SELECT candidate_id, person_id, candidate_username
              FROM sharp_identity_candidates
             WHERE platform='sleeper'
             ORDER BY confidence DESC, candidate_id
             LIMIT 1
            """
        ).fetchone()
        candidate_id = str(row["candidate_id"])
        person_id = str(row["person_id"])
        username = str(row["candidate_username"])
    finally:
        conn.close()
    curated.inspect_sleeper_candidates(
        ledger_path=ledger,
        fetch_json=lambda _url: (200, {"user_id": user_id, "username": username}),
        request_sleep=0,
        budget=1,
    )
    return {"candidate_id": candidate_id, "person_id": person_id, "user_id": user_id}


def _decision_rows(ledger, candidate_id):
    conn = curated.ensure_schema(ledger)
    try:
        return [
            dict(row)
            for row in conn.execute(
                """
                SELECT decision, reviewer, reason, decided_ms
                  FROM sharp_review_decisions
                 WHERE candidate_id=?
                 ORDER BY decided_ms
                """,
                (candidate_id,),
            ).fetchall()
        ]
    finally:
        conn.close()


def test_approval_promotes_the_identity_into_the_curated_cohort(tmp_path):
    ledger = tmp_path / "intel.sqlite"
    prepared = _prepare_candidate(ledger)

    # Before any human decision the behavioral cohort is empty — candidate
    # existence, API existence and name resemblance verify nothing.
    assert curated.curated_cohort_members(mode="curated_industry", ledger_path=ledger) == []

    curated.review_candidate(
        prepared["candidate_id"],
        "approve",
        reviewer="jasonleetucker",
        reason="ownership corroborated",
        ledger_path=ledger,
    )

    members = curated.curated_cohort_members(mode="curated_industry", ledger_path=ledger)
    keys = {member.manager_key: member for member in members}
    assert f"sleeper:{prepared['user_id']}" in keys
    assert keys[f"sleeper:{prepared['user_id']}"].person_id == prepared["person_id"]

    # ...and the decision is in the audit trail with who + when.
    rows = _decision_rows(ledger, prepared["candidate_id"])
    assert [row["decision"] for row in rows] == ["approve"]
    assert rows[0]["reviewer"] == "jasonleetucker"
    assert rows[0]["reason"] == "ownership corroborated"
    assert int(rows[0]["decided_ms"]) > 0


def test_rejection_is_audited_and_never_creates_a_cohort_member(tmp_path):
    ledger = tmp_path / "intel.sqlite"
    prepared = _prepare_candidate(ledger)

    curated.review_candidate(
        prepared["candidate_id"],
        "reject",
        reviewer="jasonleetucker",
        reason="handle collision",
        ledger_path=ledger,
    )

    assert curated.curated_cohort_members(mode="curated_industry", ledger_path=ledger) == []
    conn = curated.ensure_schema(ledger)
    try:
        status = conn.execute(
            "SELECT verification_status FROM sharp_identity_candidates WHERE candidate_id=?",
            (prepared["candidate_id"],),
        ).fetchone()["verification_status"]
        verified_accounts = conn.execute(
            "SELECT COUNT(*) FROM sharp_platform_accounts WHERE platform='sleeper' AND verification_status='verified'"
        ).fetchone()[0]
    finally:
        conn.close()
    assert status == "rejected_match"
    assert verified_accounts == 0

    rows = _decision_rows(ledger, prepared["candidate_id"])
    assert [row["decision"] for row in rows] == ["reject"]
    assert rows[0]["reviewer"] == "jasonleetucker"
    assert rows[0]["reason"] == "handle collision"
    assert int(rows[0]["decided_ms"]) > 0
