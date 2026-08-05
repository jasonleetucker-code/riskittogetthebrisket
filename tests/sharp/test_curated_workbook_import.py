import json
from pathlib import Path

from src.sharp.workbook_import import build_snapshot

REPO_ROOT = Path(__file__).parents[2]
SNAPSHOT = REPO_ROOT / "config" / "sharp" / "curated_universe.json"


def _snapshot():
    return json.loads(SNAPSHOT.read_text(encoding="utf-8"))


def test_full_workbook_snapshot_was_parsed_dynamically():
    snapshot = _snapshot()
    assert snapshot["counts"] == {
        "candidate_pool_rows": 247,
        "final_100": 100,
        "sharp_tracker_subset": 40,
        "ffpc_high_stakes_subset": 16,
        "near_misses": 30,
        "sources": 35,
        "workbook_claimed_sleeper_usernames": 8,
        "verified_platform_accounts": 88,
        "identity_candidates": 108,
    }
    assert len(snapshot["people"]) == 100
    assert len(snapshot["candidate_pool"]) == 247
    assert len(snapshot["research_people"]) == 30
    assert snapshot.get("workbook_sha256")
    assert snapshot.get("sheet_inventory")


def test_non_people_and_placeholder_handles_are_not_accounts():
    snapshot = _snapshot()
    usernames = {row.get("username") for row in snapshot["platform_accounts"]}
    assert "No current handle confidently verified" not in usernames
    assert all(row["canonical_name"] != "Fritz Pollard" for row in snapshot["people"])
    fritz = next(
        row for row in snapshot["research_people"] if "Fritz Pollard" in row["public_display_name"]
    )
    assert fritz["candidate_status"] == "insufficient_identity_information"


def test_the_workbooks_claimed_sleeper_usernames_are_candidates_not_verified_accounts():
    """The workbook cannot verify account OWNERSHIP, so the import never claims it.

    Its "Verified Sleeper username" column carries 8 usernames, but each row's
    supporting URLs are podcast/company pages establishing why the PERSON is a
    sharp -- they say nothing about who holds the handle. Four of the eight are
    exact lowercase transforms of the person's X handle, which is the
    handle==username inference the brief forbids. So the import creates NO
    verified Sleeper account; ownership is re-derived against the public API.
    """
    snapshot = _snapshot()
    assert not [row for row in snapshot["platform_accounts"] if row["platform"] == "sleeper"]

    claimed = {
        row["candidate_username"]: row
        for row in snapshot["identity_candidates"]
        if row["candidate_generation_method"].startswith("workbook_claimed_username")
    }
    assert set(claimed) == {
        "carpentiernfl",
        "jjzachariason",
        "mattykiwoom",
        "patfitz",
        "raygque",
        "charleschillffb",
        "shanesays",
        "sigmundbloomfbg",
    }
    assert all(row["verification_status"] == "unresolved" for row in claimed.values())
    assert all(row["manual_review_required"] for row in claimed.values())

    # The four that merely echo the public X handle are marked as such and
    # ranked BELOW the four that were sourced independently of it.
    handle_derived = {
        name
        for name, row in claimed.items()
        if row["candidate_generation_method"] == "workbook_claimed_username_matching_public_handle"
    }
    assert handle_derived == {"carpentiernfl", "mattykiwoom", "raygque", "charleschillffb"}
    assert max(claimed[name]["confidence"] for name in handle_derived) < min(
        row["confidence"] for name, row in claimed.items() if name not in handle_derived
    )

    generated = [row for row in snapshot["identity_candidates"] if row["platform"] == "sleeper"]
    assert generated
    assert all(row["verification_status"] == "unresolved" for row in generated)
    assert all(row["manual_review_required"] for row in generated)


def test_no_person_is_a_super_sharp_on_import():
    """Super Sharp = curated AND a verified public identity.

    Import verifies nothing, so the population starts empty and grows only
    through ``curated.refresh_memberships`` once accounts actually resolve.
    """
    snapshot = _snapshot()
    assert not [row for row in snapshot["model_memberships"] if row["verified_super_sharp"]]
    assert all(row["membership_state"] == "curated_only" for row in snapshot["model_memberships"])


def test_snapshot_is_reproducible_from_the_tracked_workbook():
    """The committed snapshot must be regenerable, byte-for-byte, from the repo."""
    workbook = REPO_ROOT / "config" / "sharp" / "workbooks"
    candidates = sorted(workbook.glob("*.xlsx"))
    assert candidates, "the source workbook must be tracked so the import is reproducible"
    rebuilt = build_snapshot(candidates[0])
    assert rebuilt["workbook_sha256"] == _snapshot()["workbook_sha256"]
    assert rebuilt["counts"] == _snapshot()["counts"]


def test_build_snapshot_rejects_missing_workbook(tmp_path):
    missing = tmp_path / "missing.xlsx"
    try:
        build_snapshot(missing)
    except (FileNotFoundError, OSError):
        pass
    else:
        raise AssertionError("missing workbook should not silently produce an empty universe")
