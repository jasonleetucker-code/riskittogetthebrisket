"""Tests for ``src/api/guest_passes.py``.

Covers create / validate / revoke / list / purge + duration bounds
and storage-format invariants (token hash, never plaintext).
"""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from src.api import guest_passes


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    """Each test gets its own SQLite file so they don't interleave."""
    return tmp_path / "guest_passes.sqlite"


# ── Create ────────────────────────────────────────────────────────────


def test_create_returns_pass_and_plaintext_token(db_path: Path):
    pass_row, token = guest_passes.create(
        duration_hours=1.0, note="Brent (12h)", created_by="admin",
        db_path=db_path,
    )
    assert pass_row.id > 0
    assert pass_row.note == "Brent (12h)"
    assert pass_row.created_by == "admin"
    assert pass_row.is_active
    assert not pass_row.is_revoked
    assert not pass_row.is_expired
    # Plaintext token is URL-safe + has reasonable entropy.
    assert isinstance(token, str)
    assert len(token) >= 20
    # The DB file should exist now.
    assert db_path.exists()


def test_create_rejects_zero_duration(db_path: Path):
    with pytest.raises(ValueError):
        guest_passes.create(duration_hours=0, db_path=db_path)


def test_create_rejects_excessive_duration(db_path: Path):
    with pytest.raises(ValueError):
        guest_passes.create(
            duration_hours=guest_passes._MAX_DURATION_HOURS + 1,
            db_path=db_path,
        )


def test_create_truncates_long_note(db_path: Path):
    long_note = "x" * 1000
    pass_row, _ = guest_passes.create(
        duration_hours=1.0, note=long_note, db_path=db_path,
    )
    assert len(pass_row.note) <= 200


def test_token_is_not_stored_in_plaintext(db_path: Path, tmp_path: Path):
    """Critical: the SQLite DB must contain the SHA-256 hash of the
    token, NOT the plaintext.  Anyone reading the DB file should not
    be able to recover valid tokens."""
    _pass, token = guest_passes.create(
        duration_hours=1.0, db_path=db_path,
    )
    raw = db_path.read_bytes()
    assert token.encode("utf-8") not in raw, (
        "plaintext token leaked into SQLite file!"
    )
    # Hash IS present.
    expected_hash = guest_passes._hash_token(token)
    assert expected_hash.encode("utf-8") in raw


# ── Validate ──────────────────────────────────────────────────────────


def test_validate_returns_pass_for_fresh_token(db_path: Path):
    created, token = guest_passes.create(
        duration_hours=1.0, db_path=db_path,
    )
    found = guest_passes.validate(token, db_path=db_path)
    assert found is not None
    assert found.id == created.id


def test_validate_rejects_unknown_token(db_path: Path):
    guest_passes.create(duration_hours=1.0, db_path=db_path)
    assert guest_passes.validate("not-a-real-token", db_path=db_path) is None


def test_validate_rejects_empty_or_invalid_inputs(db_path: Path):
    assert guest_passes.validate("", db_path=db_path) is None
    assert guest_passes.validate(None, db_path=db_path) is None  # type: ignore[arg-type]
    assert guest_passes.validate(123, db_path=db_path) is None  # type: ignore[arg-type]


def test_validate_rejects_expired_token(db_path: Path, monkeypatch):
    """Time-skip the system clock past the pass's expiry; validate
    must refuse the token even though it's still in the DB."""
    _pass, token = guest_passes.create(
        duration_hours=1.0, db_path=db_path,
    )
    # Advance time past expiry.
    real_time = time.time
    monkeypatch.setattr(
        guest_passes.time, "time", lambda: real_time() + 3600 + 1,
    )
    assert guest_passes.validate(token, db_path=db_path) is None


def test_validate_rejects_revoked_token(db_path: Path):
    pass_row, token = guest_passes.create(
        duration_hours=1.0, db_path=db_path,
    )
    revoked = guest_passes.revoke(pass_row.id, db_path=db_path)
    assert revoked is True
    assert guest_passes.validate(token, db_path=db_path) is None


# ── Revoke ────────────────────────────────────────────────────────────


def test_revoke_returns_false_when_already_revoked(db_path: Path):
    pass_row, _ = guest_passes.create(
        duration_hours=1.0, db_path=db_path,
    )
    assert guest_passes.revoke(pass_row.id, db_path=db_path) is True
    # Second revoke is a no-op.
    assert guest_passes.revoke(pass_row.id, db_path=db_path) is False


def test_revoke_returns_false_for_unknown_id(db_path: Path):
    assert guest_passes.revoke(99999, db_path=db_path) is False


# ── List ──────────────────────────────────────────────────────────────


def test_list_passes_returns_all_by_default(db_path: Path):
    p1, _ = guest_passes.create(duration_hours=1.0, note="a", db_path=db_path)
    p2, _ = guest_passes.create(duration_hours=2.0, note="b", db_path=db_path)
    guest_passes.revoke(p1.id, db_path=db_path)
    rows = guest_passes.list_passes(db_path=db_path)
    ids = {r.id for r in rows}
    assert ids == {p1.id, p2.id}
    # Newest first.
    assert rows[0].id == p2.id


def test_list_passes_active_only_excludes_revoked_and_expired(
    db_path: Path, monkeypatch,
):
    p1, _ = guest_passes.create(
        duration_hours=1.0, note="active", db_path=db_path,
    )
    p2, _ = guest_passes.create(
        duration_hours=1.0, note="revoked", db_path=db_path,
    )
    guest_passes.revoke(p2.id, db_path=db_path)
    p3, _ = guest_passes.create(
        duration_hours=0.02, note="expired", db_path=db_path,  # ~72s
    )
    # Expire p3 explicitly with a time skip well past 72s.
    real_time = time.time
    monkeypatch.setattr(
        guest_passes.time, "time", lambda: real_time() + 600,
    )
    rows = guest_passes.list_passes(
        include_inactive=False, db_path=db_path,
    )
    active_ids = {r.id for r in rows}
    assert active_ids == {p1.id}, (
        "active-only filter must drop revoked + expired"
    )


# ── Purge ─────────────────────────────────────────────────────────────


def test_purge_expired_keeps_grace_window(db_path: Path, monkeypatch):
    _pass, _ = guest_passes.create(
        duration_hours=0.02, db_path=db_path,  # ~72s
    )
    # Advance past expiry but within the default 7-day grace.
    real_time = time.time
    monkeypatch.setattr(
        guest_passes.time, "time", lambda: real_time() + 3600,
    )
    deleted = guest_passes.purge_expired(db_path=db_path)
    assert deleted == 0  # still within grace
    # Now fast-forward beyond the grace + lower it artificially.
    deleted = guest_passes.purge_expired(
        grace_seconds=0, db_path=db_path,
    )
    assert deleted == 1


# ── GuestPass dataclass ───────────────────────────────────────────────


def test_to_dict_omits_token_hash(db_path: Path):
    pass_row, _ = guest_passes.create(
        duration_hours=1.0, db_path=db_path,
    )
    d = pass_row.to_dict()
    # Must not leak the hash either — admin UI doesn't need it.
    assert "token_hash" not in d
    assert "tokenHash" not in d
    # Required public fields.
    for key in (
        "id", "note", "createdBy", "createdAtEpoch", "expiresAtEpoch",
        "revokedAtEpoch", "isRevoked", "isExpired", "isActive",
    ):
        assert key in d
