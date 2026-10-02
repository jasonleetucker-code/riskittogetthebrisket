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


# --- One raw-evidence contract on every insertion path -------------------------------
#
# ``append_evidence`` validated raw evidence while ``save_report`` inserted its ``raw``
# argument directly, so the brief path could commit evidence the other path refuses —
# and advance the campaign checkpoint and knowledge revision with it.


def _counts(store):
    return {
        table: store.connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in ("state", "evidence", "knowledge", "history")
    }


def _without(key):
    payload = evidence()
    del payload[key]
    return payload


MALFORMED_RAW = {
    "missing_source": _without("source"),
    "empty_source": {**evidence(), "source": ""},
    "missing_at": _without("at"),
    "missing_repo_head": _without("repo_head"),
    "empty_repo_head": {**evidence(), "repo_head": ""},
    "missing_content": _without("content"),
    "missing_complete": _without("complete"),
    "not_an_object": ["source", "at"],
}

MALFORMED_PRODUCER = {
    "not_an_object": "claude-opus",
    "empty_object": {},
    "unknown_field": {"model": "m", "confidence": "high"},
    "empty_string": {"model": ""},
    "blank_string": {"provider": "   "},
    "null_value": {"model": None},
    "non_string": {"session_id": 7},
    "overlong": {"session_id": "x" * 201},
    "padded": {"model": "  m  "},
    "invisible": {"model": "\u200b"},
    "control_character": {"provider": "a\nb"},
}


def _save(store, raw, *, expected_campaign=0, expected_knowledge=1, **knowledge_extra):
    store.save_report(
        evidence_id="report",
        raw=raw,
        checkpoint={"last_receipt": "report"},
        knowledge=knowledge("new", evidence_ids=["report"], **knowledge_extra),
        expected_campaign=expected_campaign,
        expected_knowledge=expected_knowledge,
    )


def _seeded(tmp_path):
    store = StewardStore(tmp_path / "state.db")
    store.append_evidence("raw", evidence())
    store.remember(knowledge(), expected_revision=0)
    return store


@pytest.mark.parametrize("case", sorted(MALFORMED_RAW))
def test_save_report_refuses_raw_evidence_append_evidence_refuses(tmp_path, case):
    store = _seeded(tmp_path)
    with pytest.raises(ValueError):
        store.append_evidence("direct", MALFORMED_RAW[case])
    before = _counts(store)
    with pytest.raises(ValueError):
        _save(store, MALFORMED_RAW[case])
    assert _counts(store) == before
    assert store.read("campaign") == (0, None)
    assert store.read("knowledge_revision")[0] == 1
    assert store.raw_evidence("report") is None
    assert [r["id"] for r in store.retrieve("campaign")["records"]] == ["one"]
    store.close()


@pytest.mark.parametrize("case", sorted(MALFORMED_PRODUCER))
def test_malformed_producer_is_refused_on_every_insertion_path(tmp_path, case):
    store = _seeded(tmp_path)
    raw = {**evidence(), "producer": MALFORMED_PRODUCER[case]}
    before = _counts(store)
    with pytest.raises(ValueError, match="producer"):
        store.append_evidence("direct", raw)
    with pytest.raises(ValueError, match="producer"):
        _save(store, raw)
    assert _counts(store) == before
    store.close()


def test_structured_producer_round_trips_and_legacy_stays_explicitly_unattributed(tmp_path):
    from src.steward.store import producer_attribution

    store = _seeded(tmp_path)
    attributed = {**evidence(), "producer": {"session_id": "s-1", "provider": "anthropic"}}
    _save(store, attributed)
    assert store.raw_evidence("report") == attributed
    assert producer_attribution(store.raw_evidence("report")) == {
        "status": "attributed",
        "session_id": "s-1",
        "provider": "anthropic",
    }
    # Only what was supplied is reported; the model is never inferred from ``source``.
    legacy = store.raw_evidence("raw")
    assert "producer" not in legacy
    assert producer_attribution(legacy) == {"status": "unattributed"}
    assert producer_attribution({**evidence(), "source": "claude-opus session"}) == {
        "status": "unattributed"
    }
    store.close()


def test_legacy_database_rows_are_readable_and_never_rewritten(tmp_path):
    path = tmp_path / "state.db"
    legacy = sqlite3.connect(path)
    legacy.executescript(
        "CREATE TABLE evidence (id TEXT PRIMARY KEY, payload TEXT NOT NULL);"
        "PRAGMA user_version=1;"
    )
    # A historical row written before this contract existed, with a free-text source.
    stored = (
        '{"at":"2026-09-10T00:00:00Z","complete":true,"content":"x","repo_head":"%s","source":"steward brief"}'
        % ("a" * 40)
    )
    legacy.execute("INSERT INTO evidence VALUES ('old', ?)", (stored,))
    legacy.commit()
    legacy.close()
    store = StewardStore(path)
    from src.steward.store import producer_attribution

    assert producer_attribution(store.raw_evidence("old")) == {"status": "unattributed"}
    row = store.connection.execute("SELECT payload FROM evidence WHERE id='old'").fetchone()
    assert row[0] == stored
    with pytest.raises(sqlite3.IntegrityError):
        store.connection.execute("UPDATE evidence SET payload='{}' WHERE id='old'")
    store.close()


def test_valid_raw_with_stale_campaign_revision_commits_nothing(tmp_path):
    store = _seeded(tmp_path)
    store.write("campaign", {"next": "x"}, expected_revision=0)
    before = _counts(store)
    with pytest.raises(ConflictError):
        _save(store, {**evidence(), "producer": {"model": "m"}}, expected_campaign=0)
    assert _counts(store) == before
    assert store.raw_evidence("report") is None
    assert store.read("campaign") == (1, {"next": "x"})
    store.close()


def test_lower_authority_supersession_through_save_report_commits_nothing(tmp_path):
    store = _seeded(tmp_path)
    before = _counts(store)
    with pytest.raises(ValueError, match="lower authority"):
        _save(store, evidence(), supersedes="one", authority="observation", layer="owner")
    assert _counts(store) == before
    assert store.raw_evidence("report") is None
    assert store.read("campaign") == (0, None)
    assert store.retrieve("campaign")["records"][0]["id"] == "one"
    store.close()


def test_history_rows_are_immutable(tmp_path):
    store = _seeded(tmp_path)
    with pytest.raises(sqlite3.IntegrityError):
        store.connection.execute("UPDATE history SET payload='{}'")
    with pytest.raises(sqlite3.IntegrityError):
        store.connection.execute("DELETE FROM history")
    store.close()


def test_stored_producer_is_rechecked_not_trusted_on_read():
    from src.steward.store import producer_attribution

    assert producer_attribution({**evidence(), "producer": {"model": "x" * 200}}) == {
        "status": "attributed",
        "model": "x" * 200,
    }
    for stored in ({"foo": 1}, {"model": ""}, "claude", [], {}):
        assert producer_attribution({**evidence(), "producer": stored}) == {
            "status": "unattributed",
            "reason": "malformed_producer",
        }
    assert producer_attribution(["not", "an", "object"]) == {"status": "unattributed"}
