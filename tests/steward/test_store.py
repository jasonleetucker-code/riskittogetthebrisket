import sqlite3
from src.steward.store import ConflictError, StewardStore
import pytest


def evidence():
    return {
        "source": "owner directive",
        "at": "2026-09-10T00:00:00Z",
        "repo_head": "a" * 40,
        "content": "Use report-only state",
        "complete": True,
    }


def knowledge(key="one", **extra):
    return {
        "id": key,
        "layer": "owner",
        "topic": "campaign",
        "summary": "report-only",
        "authority": "owner",
        "evidence_ids": ["raw"],
        "repo_head": "a" * 40,
        "at": "2026-09-10T00:00:00Z",
        **extra,
    }


def test_two_connections_reject_lost_update_and_resume(tmp_path):
    path = tmp_path / "state.db"
    a, b = StewardStore(path), StewardStore(path)
    assert b.read("campaign") == (0, None)
    a.write("campaign", {"partial": ["todo-1"], "next": "test"}, expected_revision=0)
    with pytest.raises(ConflictError):
        b.write("campaign", {"partial": []}, expected_revision=0)
    a.close()
    assert b.read("campaign") == (1, {"partial": ["todo-1"], "next": "test"})
    b.close()


def test_supersession_atomicity_and_provenance(tmp_path):
    store = StewardStore(tmp_path / "state.db")
    store.append_evidence("raw", evidence())
    store.remember(knowledge(), expected_revision=0)
    with pytest.raises(ConflictError):
        store.remember(knowledge("two", supersedes="one"), expected_revision=0)
    assert store.retrieve("campaign")["records"][0]["id"] == "one"
    with pytest.raises(ValueError):
        store.remember(
            knowledge("bad", supersedes="one", authority="observation"), expected_revision=1
        )
    store.remember(
        knowledge("two", supersedes="one", summary="updated policy"), expected_revision=1
    )
    result = store.retrieve("campaign")
    assert result["retrieval_revision"] == result["knowledge_revision"] == 2
    assert [r["id"] for r in result["records"]] == ["two"]
    assert store.raw_evidence(result["records"][0]["evidence_ids"][0]) == evidence()
    assert store.retrieve("campaign", limit_chars=1)["omitted"] == 1
    with pytest.raises(sqlite3.IntegrityError):
        store.connection.execute("DELETE FROM evidence")
    store.close()


def test_backup_restore_and_future_schema_refusal(tmp_path):
    original = StewardStore(tmp_path / "state.db")
    original.write("campaign", {"next": "verify"}, expected_revision=0)
    original.backup(tmp_path / "backup.db")
    restored = StewardStore(tmp_path / "backup.db")
    assert restored.read("campaign") == original.read("campaign")
    with pytest.raises(FileExistsError):
        original.backup(tmp_path / "backup.db")
    restored.connection.execute("PRAGMA user_version=999")
    restored.close()
    with pytest.raises(ValueError, match="unsupported"):
        StewardStore(tmp_path / "backup.db")
    original.close()


def test_report_generation_rolls_back_all_tables_on_knowledge_conflict(tmp_path):
    store = StewardStore(tmp_path / "state.db")
    store.append_evidence("raw", evidence())
    store.remember(knowledge(), expected_revision=0)
    compiled = knowledge("new", evidence_ids=["report"], supersedes="one")
    with pytest.raises(ConflictError):
        store.save_report(
            evidence_id="report",
            raw=evidence(),
            checkpoint={"last_receipt": "report"},
            knowledge=compiled,
            expected_campaign=0,
            expected_knowledge=0,
        )
    assert store.read("campaign") == (0, None)
    assert store.raw_evidence("report") is None
    assert store.retrieve("campaign")["records"][0]["id"] == "one"
    store.save_report(
        evidence_id="report",
        raw=evidence(),
        checkpoint={"last_receipt": "report"},
        knowledge=compiled,
        expected_campaign=0,
        expected_knowledge=1,
    )
    assert store.read("campaign")[1]["last_receipt"] == "report"
    assert store.retrieve("campaign")["records"][0]["id"] == "new"
    store.close()
