from __future__ import annotations

import sqlite3

import pytest

from src.intel import ledger


def test_locked_database_is_never_quarantined_or_rebuilt(tmp_path):
    path = tmp_path / "ledger.sqlite3"
    ledger.reset_setup_cache()
    conn = ledger.connect(path)
    conn.execute("INSERT INTO meta(key, value) VALUES ('sentinel', 'preserve-me')")
    conn.commit()
    conn.close()

    writer = sqlite3.connect(path)
    writer.execute("PRAGMA journal_mode=DELETE")
    writer.execute("BEGIN EXCLUSIVE")
    writer.execute("UPDATE meta SET value='held' WHERE key='sentinel'")

    ledger.reset_setup_cache()
    with pytest.raises(sqlite3.OperationalError, match="locked"):
        ledger.connect(path)

    assert path.exists()
    assert list(tmp_path.glob("ledger.sqlite3.corrupt*")) == []

    writer.rollback()
    writer.close()
    ledger.reset_setup_cache()
    check = ledger.connect(path)
    assert (
        check.execute("SELECT value FROM meta WHERE key='sentinel'").fetchone()[0] == "preserve-me"
    )
    check.close()


def test_proven_non_database_file_is_quarantined_and_rebuilt(tmp_path):
    path = tmp_path / "ledger.sqlite3"
    path.write_bytes(b"this is not sqlite")
    ledger.reset_setup_cache()

    conn = ledger.connect(path)
    version = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0]
    conn.close()

    assert version == str(ledger.SCHEMA_VERSION)
    quarantined = list(tmp_path.glob("ledger.sqlite3.corrupt-*"))
    assert len(quarantined) == 1
    assert quarantined[0].read_bytes() == b"this is not sqlite"
