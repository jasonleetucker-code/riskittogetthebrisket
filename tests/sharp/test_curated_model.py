from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from src.sharp import curated

SNAPSHOT = Path(__file__).parents[2] / "config" / "sharp" / "curated_universe.json"


def _snapshot():
    return json.loads(SNAPSHOT.read_text(encoding="utf-8"))


def _verify_one_sleeper_identity(ledger, *, user_id="900001"):
    """Walk a candidate all the way to a verified account, the only way there is.

    The workbook cannot confer verification, so every test that needs a
    verified Sleeper account has to earn one: inspect the candidate against
    the (faked) public API to obtain a stable platform id, then take an
    explicit human review action.  That is the whole promotion path, and
    exercising it is more valuable than seeding a row directly.
    """
    conn = curated.ensure_schema(ledger)
    try:
        candidate = conn.execute(
            """
            SELECT candidate_id, person_id, candidate_username
              FROM sharp_identity_candidates
             WHERE platform='sleeper'
             ORDER BY confidence DESC, candidate_id
             LIMIT 1
            """
        ).fetchone()
        candidate_id = str(candidate["candidate_id"])
        person_id = str(candidate["person_id"])
        username = str(candidate["candidate_username"])
    finally:
        conn.close()

    curated.inspect_sleeper_candidates(
        ledger_path=ledger,
        fetch_json=lambda _url: (200, {"user_id": user_id, "username": username}),
        request_sleep=0,
        budget=1,
    )
    curated.review_candidate(candidate_id, "approve", ledger_path=ledger)
    curated.refresh_memberships(ledger_path=ledger)
    return {"candidate_id": candidate_id, "person_id": person_id, "username": username}


def test_import_is_idempotent_and_every_candidate_is_stored(tmp_path):
    ledger = tmp_path / "intel.sqlite"
    first = curated.import_snapshot(_snapshot(), ledger_path=ledger)
    second = curated.import_snapshot(_snapshot(), ledger_path=ledger)
    assert first["status"] == second["status"] == "success"
    conn = curated.ensure_schema(ledger)
    try:
        assert conn.execute("SELECT COUNT(*) FROM sharp_people").fetchone()[0] == 247
        assert conn.execute("SELECT COUNT(*) FROM sharp_model_membership").fetchone()[0] == 247
        assert conn.execute("SELECT COUNT(*) FROM sharp_aliases").fetchone()[0] == 90
        assert conn.execute("SELECT COUNT(*) FROM sharp_identity_candidates").fetchone()[0] == 108
        assert conn.execute("SELECT COUNT(*) FROM sharp_import_runs").fetchone()[0] == 2
    finally:
        conn.close()


def test_curated_membership_is_mandatory_without_fake_performance(tmp_path):
    ledger = tmp_path / "intel.sqlite"
    curated.import_snapshot(_snapshot(), ledger_path=ledger)
    conn = curated.ensure_schema(ledger)
    try:
        row = conn.execute(
            """
            SELECT p.public_display_name, m.curated_industry_sharp,
                   m.algorithmically_qualified_sharp, m.membership_state,
                   pm.winning_percentage
              FROM sharp_people p
              JOIN sharp_model_membership m ON m.person_id=p.person_id
              LEFT JOIN sharp_performance_metrics pm ON pm.person_id=p.person_id
             WHERE p.public_display_name='Adam Harstad'
            """
        ).fetchone()
        assert row["curated_industry_sharp"] == 1
        assert row["algorithmically_qualified_sharp"] == 0
        assert row["membership_state"] == "curated_only"
        assert row["winning_percentage"] is None
    finally:
        conn.close()


def test_no_super_sharps_exist_until_an_identity_is_actually_verified(tmp_path):
    """Super Sharp = curated AND a verified public identity.

    The workbook lists 8 Sleeper usernames, but its supporting URLs establish
    curated INCLUSION, not account ownership -- and four of the eight are just
    the person's X handle lowercased.  So the import verifies nothing and the
    population starts empty.  This is a real state the UI must render, not an
    error, and it is the honest floor the population grows from.
    """
    ledger = tmp_path / "intel.sqlite"
    curated.import_snapshot(_snapshot(), ledger_path=ledger)
    summary = curated.summary_payload(ledger_path=ledger)
    assert summary["membership"]["curated_people"] == 100
    assert summary["membership"]["super_sharps"] == 0
    assert not summary["verifiedAccountsByPlatform"].get("sleeper")


def test_an_explicitly_reviewed_identity_creates_a_super_sharp(tmp_path):
    """The positive path still has to work -- it just has to be earned."""
    ledger = tmp_path / "intel.sqlite"
    curated.import_snapshot(_snapshot(), ledger_path=ledger)
    verified = _verify_one_sleeper_identity(ledger)

    summary = curated.summary_payload(ledger_path=ledger)
    assert summary["membership"]["super_sharps"] == 1
    assert summary["verifiedAccountsByPlatform"]["sleeper"] == 1

    conn = curated.ensure_schema(ledger)
    try:
        state = conn.execute(
            "SELECT membership_state, verified_super_sharp FROM sharp_model_membership WHERE person_id=?",
            (verified["person_id"],),
        ).fetchone()
        assert state["verified_super_sharp"] == 1
        assert state["membership_state"] == "trackable_curated_sharp"
    finally:
        conn.close()


def test_a_human_verified_account_survives_re_import(tmp_path):
    """Re-import must not undo a review decision.

    The workbook no longer carries any Sleeper account, so a naive importer
    that treated the snapshot as the complete account set would silently
    delete every identity the review queue had verified.
    """
    ledger = tmp_path / "intel.sqlite"
    curated.import_snapshot(_snapshot(), ledger_path=ledger)
    verified = _verify_one_sleeper_identity(ledger)

    curated.import_snapshot(_snapshot(), ledger_path=ledger)
    curated.refresh_memberships(ledger_path=ledger)

    conn = curated.ensure_schema(ledger)
    try:
        rows = conn.execute(
            """
            SELECT verification_status, verification_method
              FROM sharp_platform_accounts
             WHERE person_id=? AND platform='sleeper'
            """,
            (verified["person_id"],),
        ).fetchall()
        assert [row["verification_status"] for row in rows] == ["verified"]
        assert rows[0]["verification_method"] == "explicit_admin_review"
    finally:
        conn.close()


def test_changed_public_handle_retires_the_old_one_and_leaves_one_active(tmp_path):
    """A renamed X handle must not become two live identities for one person.

    X accounts are keyed by the handle string because X exposes no stable id
    we hold, so the importer keeps the old row as ``historical_handle``
    (people are findable under handles they used to use) and leaves exactly
    one active. That is history, not a fork -- the failure mode this guards
    against is two ACTIVE handles both counting as the person.
    """
    ledger = tmp_path / "intel.sqlite"
    snapshot = _snapshot()
    account = next(row for row in snapshot["platform_accounts"] if row["platform"] == "x")
    person_id = account["person_id"]
    curated.import_snapshot(snapshot, ledger_path=ledger)
    changed = copy.deepcopy(snapshot)
    updated = next(
        row
        for row in changed["platform_accounts"]
        if row["platform"] == "x" and row["person_id"] == person_id
    )
    updated["username"] = "renamed_public_handle"
    updated["account_id"] = "x:handle:renamed_public_handle"
    curated.import_snapshot(changed, ledger_path=ledger)
    conn = curated.ensure_schema(ledger)
    try:
        rows = conn.execute(
            """
            SELECT username, active_status FROM sharp_platform_accounts
             WHERE person_id=? AND platform='x' ORDER BY username
            """,
            (person_id,),
        ).fetchall()
        active = [row["username"] for row in rows if row["active_status"] != "historical_handle"]
        retired = [row["username"] for row in rows if row["active_status"] == "historical_handle"]
        assert active == ["renamed_public_handle"]
        assert retired == [account["username"]]
    finally:
        conn.close()


def test_candidate_existence_never_silently_verifies_identity(tmp_path):
    ledger = tmp_path / "intel.sqlite"
    curated.import_snapshot(_snapshot(), ledger_path=ledger)

    # ``inspect_sleeper_candidates`` orders by confidence, so pick the row it
    # will actually reach rather than the alphabetically-first candidate.
    conn = curated.ensure_schema(ledger)
    try:
        target = conn.execute(
            """
            SELECT candidate_id, candidate_username FROM sharp_identity_candidates
             WHERE platform='sleeper' ORDER BY confidence DESC, candidate_id LIMIT 1
            """
        ).fetchone()
        candidate_id = str(target["candidate_id"])
        username = str(target["candidate_username"])
    finally:
        conn.close()

    def fake_fetch(_url):
        return 200, {"user_id": "123", "username": username, "display_name": "Adam Harstad"}

    result = curated.inspect_sleeper_candidates(
        ledger_path=ledger,
        fetch_json=fake_fetch,
        request_sleep=0,
        budget=1,
    )
    assert result["found"] == 1
    conn = curated.ensure_schema(ledger)
    try:
        candidate = conn.execute(
            "SELECT verification_status FROM sharp_identity_candidates WHERE candidate_id=?",
            (candidate_id,),
        ).fetchone()
        # Existence is not ownership: the best a live hit can do is raise the
        # candidate to probable.  Only a human review action verifies it.
        assert candidate["verification_status"] in {"possible", "high_confidence_probable"}
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM sharp_platform_accounts WHERE platform='sleeper' AND platform_user_id='123'"
            ).fetchone()[0]
            == 0
        )
    finally:
        conn.close()


def _inspect_one(ledger, *, candidate_username, display_name):
    """Point the sweep at one candidate and answer with a chosen profile."""
    conn = curated.ensure_schema(ledger)
    try:
        conn.execute(
            "DELETE FROM sharp_identity_candidates WHERE platform='sleeper' AND candidate_username<>?",
            (candidate_username,),
        )
        conn.commit()
        row = conn.execute(
            "SELECT candidate_id FROM sharp_identity_candidates WHERE candidate_username=?",
            (candidate_username,),
        ).fetchone()
        candidate_id = str(row["candidate_id"])
    finally:
        conn.close()
    curated.inspect_sleeper_candidates(
        ledger_path=ledger,
        fetch_json=lambda _url: (
            200,
            # Sleeper echoes the queried username back verbatim.
            {"user_id": "555", "username": candidate_username, "display_name": display_name},
        ),
        request_sleep=0,
        budget=1,
    )
    conn = curated.ensure_schema(ledger)
    try:
        return dict(
            conn.execute(
                "SELECT verification_status, confidence, metadata_json FROM sharp_identity_candidates WHERE candidate_id=?",
                (candidate_id,),
            ).fetchone()
        )
    finally:
        conn.close()


def test_the_queried_username_can_never_corroborate_itself(tmp_path):
    """A username we searched for is not evidence that the person owns it.

    The first live sweep raised ALL 42 existing accounts to
    ``high_confidence_probable`` because the queried username sat in both
    the candidate set and the observed set, so the name-overlap test was a
    tautology. ``hrr5010`` "corroborated" Hasan Rahim on nothing at all.
    """
    ledger = tmp_path / "intel.sqlite"
    curated.import_snapshot(_snapshot(), ledger_path=ledger)
    # An opaque handle that resembles the person in no way, with a display
    # name that is just the handle echoed back -- the exact shape that used
    # to score as high confidence.
    result = _inspect_one(ledger, candidate_username="hrr5010", display_name="hrr5010")
    assert result["verification_status"] == "possible"
    assert json.loads(result["metadata_json"])["nameOverlap"] is False


def test_a_handle_encoding_the_persons_name_is_real_corroboration(tmp_path):
    ledger = tmp_path / "intel.sqlite"
    curated.import_snapshot(_snapshot(), ledger_path=ledger)
    result = _inspect_one(ledger, candidate_username="jjzachariason", display_name="JJ Zachariason")
    assert result["verification_status"] == "high_confidence_probable"
    assert json.loads(result["metadata_json"])["nameOverlap"] is True
    # Still not verified. Corroboration is not ownership.
    conn = curated.ensure_schema(ledger)
    try:
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM sharp_platform_accounts WHERE platform='sleeper'"
            ).fetchone()[0]
            == 0
        )
    finally:
        conn.close()


def test_a_handle_derived_workbook_claim_stays_merely_possible(tmp_path):
    """`carpentiernfl` is the X handle, not the name -- it must not promote."""
    ledger = tmp_path / "intel.sqlite"
    curated.import_snapshot(_snapshot(), ledger_path=ledger)
    result = _inspect_one(ledger, candidate_username="carpentiernfl", display_name="CarpentierNFL")
    assert result["verification_status"] == "possible"


def test_one_platform_account_cannot_be_verified_for_two_people(tmp_path):
    ledger = tmp_path / "intel.sqlite"
    curated.import_snapshot(_snapshot(), ledger_path=ledger)
    conn = curated.ensure_schema(ledger)
    try:
        people = conn.execute(
            "SELECT person_id FROM sharp_people WHERE candidate_status='curated_included' ORDER BY person_id LIMIT 2"
        ).fetchall()
        candidate_ids = []
        for index, person in enumerate(people):
            candidate_id = f"collision:{index}"
            candidate_ids.append(candidate_id)
            conn.execute(
                """
                INSERT INTO sharp_identity_candidates(
                  candidate_id, person_id, platform, candidate_username,
                  normalized_username, candidate_platform_user_id,
                  verification_status, confidence, manual_review_required,
                  supports_json, contradicts_json, metadata_json,
                  created_ms, updated_ms
                ) VALUES(?, ?, 'sleeper', 'same_account', 'sameaccount', 'same-id',
                         'high_confidence_probable', .9, 1, '[]', '[]', '{}', 1, 1)
                """,
                (candidate_id, person["person_id"]),
            )
        conn.commit()
    finally:
        conn.close()
    curated.review_candidate(candidate_ids[0], "approve", ledger_path=ledger)
    with pytest.raises(ValueError, match="already verified"):
        curated.review_candidate(candidate_ids[1], "approve", ledger_path=ledger)


def test_the_import_leaves_resolve_verified_sleeper_accounts_nothing_to_do(tmp_path):
    """No workbook row can put an account into the re-resolution queue.

    ``resolve_verified_sleeper_accounts`` only walks accounts already marked
    verified.  Post-demotion the import creates none, so this is the honest
    empty result -- the function is not dead, it just has nothing to re-check
    until the review queue verifies something.
    """
    ledger = tmp_path / "intel.sqlite"
    curated.import_snapshot(_snapshot(), ledger_path=ledger)
    result = curated.resolve_verified_sleeper_accounts(
        ledger_path=ledger,
        fetch_json=lambda _url: (404, None),
        request_sleep=0,
    )
    assert result == {"checked": 0, "resolved": 0, "notFound": 0, "errors": 0}


def test_deleted_or_renamed_verified_account_is_not_reassigned(tmp_path):
    ledger = tmp_path / "intel.sqlite"
    curated.import_snapshot(_snapshot(), ledger_path=ledger)
    verified = _verify_one_sleeper_identity(ledger)
    # Force the re-resolution path to reconsider the account.
    conn = curated.ensure_schema(ledger)
    try:
        conn.execute(
            "UPDATE sharp_platform_accounts SET platform_user_id=NULL WHERE person_id=? AND platform='sleeper'",
            (verified["person_id"],),
        )
        conn.commit()
    finally:
        conn.close()

    result = curated.resolve_verified_sleeper_accounts(
        ledger_path=ledger,
        fetch_json=lambda _url: (404, None),
        request_sleep=0,
    )
    assert result["checked"] == 1
    assert result["notFound"] == 1
    assert result["resolved"] == 0
    conn = curated.ensure_schema(ledger)
    try:
        # Marked stale rather than silently re-pointed at a similarly named
        # account that happens to still exist.
        assert (
            conn.execute(
                """
                SELECT COUNT(*) FROM sharp_platform_accounts
                 WHERE platform='sleeper' AND active_status='not_found_or_renamed'
                """
            ).fetchone()[0]
            == 1
        )
    finally:
        conn.close()


def test_reconciliation_reports_dynamic_workbook_counts(tmp_path):
    ledger = tmp_path / "intel.sqlite"
    curated.import_snapshot(_snapshot(), ledger_path=ledger)
    report = curated.reconciliation_report(ledger_path=ledger)
    assert report["totalWorkbookIdentitiesReviewed"] == 247
    assert report["totalImportedAsCuratedSharps"] == 100
    assert report["totalImportedAsResearchCandidates"] == 30
    assert report["totalScreenedOutStored"] == 117
    # Nothing is verified on import. Every Sleeper identity -- the 8 the
    # workbook named and the 84 generated from public handles -- starts
    # unresolved and has to be earned through the review queue.
    assert report["totalPositivelyVerifiedOnSleeper"] == 0
    assert report["totalUnresolvedSleeperIdentities"] == 92
    assert report["totalSuperSharps"] == 0
    assert report["totalFFPCTeamOrEntryNamesFound"] == 16
