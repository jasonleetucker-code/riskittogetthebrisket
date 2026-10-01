"""AL-0 versioned feature dictionary (A4): undefined features and redefinitions fail."""

from __future__ import annotations

import copy
import json
import os
import subprocess

import pytest

from scripts import check_feature_dictionary_lock as chk
from src.model_registry import feature_dictionary as fd

DOC = json.loads(fd.DEFAULT_DICTIONARY_PATH.read_text(encoding="utf-8"))
LOCK = json.loads(fd.DEFAULT_LOCK_PATH.read_text(encoding="utf-8"))


def _doc():
    return copy.deepcopy(DOC)


def _lock():
    return copy.deepcopy(LOCK)


def test_the_committed_dictionary_validates_and_holds_definitions_only():
    d = fd.load_dictionary()
    assert d.features
    for f in DOC["features"]:
        assert set(f) <= set(fd.REQUIRED_FIELDS), f"{f['name']} carries non-definition fields"
        assert "value" not in f and "values" not in f


def test_it_is_seeded_only_with_what_the_adapted_producers_consume():
    from src.model_registry.learning_adapters import (
        HILL_FAMILY,
        HILL_FEATURES,
        SQ_FAMILY,
        SQ_FEATURES,
    )

    declared = {(f["name"], f["version"]) for f in (*HILL_FEATURES, *SQ_FEATURES)}
    assert set(fd.load_dictionary().features) == declared
    consumers = {c for f in DOC["features"] for c in f["allowedConsumers"]}
    assert consumers == {HILL_FAMILY, SQ_FAMILY}


def test_editing_a_definition_in_place_fails():
    doc = _doc()
    doc["features"][0]["missingSemantics"] = "treat missing as 0"
    with pytest.raises(fd.FeatureRedefinitionError, match="NEW version"):
        fd.build_dictionary(doc, lock=_lock())


def test_two_definitions_of_one_version_fail():
    doc = _doc()
    dup = copy.deepcopy(doc["features"][0])
    dup["unit"] = "something else"
    dup["definitionHash"] = fd.definition_hash(dup)
    doc["features"].append(dup)
    with pytest.raises(fd.FeatureRedefinitionError, match="defined twice"):
        fd.build_dictionary(doc, lock=_lock())


def test_a_new_version_is_how_a_definition_changes():
    doc = _doc()
    v2 = copy.deepcopy(doc["features"][0])
    v2["version"] = 2
    v2["unit"] = "a refined unit"
    v2["definitionHash"] = fd.definition_hash(v2)
    doc["features"].append(v2)
    lock = _lock()
    lock["locked"].append(
        {"name": v2["name"], "version": 2, "definitionHash": v2["definitionHash"]}
    )
    d = fd.build_dictionary(doc, lock=lock)
    name = v2["name"]
    assert d.get(name, 1).unit != d.get(name, 2).unit


def test_a_manifest_referencing_an_undefined_feature_fails():
    d = fd.load_dictionary()
    with pytest.raises(fd.UndefinedFeatureError):
        fd.validate_manifest(
            d, consumer="hill_scope_masters", features=[{"name": "ros_strength", "version": 1}]
        )
    with pytest.raises(fd.UndefinedFeatureError):
        fd.validate_manifest(
            d,
            consumer="hill_scope_masters",
            features=[{"name": "source_board_native_value", "version": 9}],
        )


def test_a_manifest_that_restates_a_definition_differently_fails():
    d = fd.load_dictionary()
    with pytest.raises(fd.FeatureRedefinitionError):
        fd.validate_manifest(
            d,
            consumer="hill_scope_masters",
            features=[
                {"name": "source_board_native_value", "version": 1, "missingSemantics": "zero"}
            ],
        )


def test_a_consumer_not_allowed_fails():
    d = fd.load_dictionary()
    with pytest.raises(fd.FeatureDictionaryError, match="not an allowed consumer"):
        fd.validate_manifest(
            d,
            consumer="source_quality_weights",
            features=[{"name": "source_board_native_value", "version": 1}],
        )


def test_the_manifest_hash_is_order_independent_and_definition_bound():
    d = fd.load_dictionary()
    a = [
        {"name": "source_board_native_value", "version": 1},
        {"name": "provider_family", "version": 1},
    ]
    assert fd.validate_manifest(
        d, consumer="hill_scope_masters", features=a
    ) == fd.validate_manifest(d, consumer="hill_scope_masters", features=list(reversed(a)))


@pytest.mark.parametrize(
    "owner",
    [
        "src.nowhere.module:fn",
        "src.model_registry.training_manifest:not_a_name",
        "scripts.x:y",
        "nocolon",
    ],
)
def test_a_definition_owner_must_resolve_statically(owner):
    doc = _doc()
    doc["features"][0]["definitionOwner"] = owner
    doc["features"][0]["definitionHash"] = fd.definition_hash(doc["features"][0])
    with pytest.raises(fd.FeatureDictionaryError):
        fd.build_dictionary(doc, lock=_lock())


@pytest.mark.parametrize("field", ["knownAtRule", "missingSemantics", "allowedConsumers"])
def test_missing_semantics_and_known_at_are_mandatory(field):
    doc = _doc()
    del doc["features"][0][field]
    with pytest.raises(fd.FeatureDictionaryError):
        fd.build_dictionary(doc, lock=_lock())


# ── rule 3a: the append-only lock ────────────────────────────────────────────


def test_every_locked_definition_matches_the_committed_dictionary():
    """The lock IS the record of every (name, version) ever committed: each row must
    still be defined, at exactly its locked hash, recomputed from the definition
    fields (not read back from the entry's own pin). Needs no git."""
    by_key = {(f["name"], f["version"]): f for f in DOC["features"]}
    rows = fd.parse_lock(LOCK)
    assert rows, "empty lock"
    for name, version, digest in rows:
        assert (name, version) in by_key, f"locked {name} v{version} was removed"
        assert (
            fd.definition_hash(by_key[(name, version)]) == digest
        ), f"{name} v{version} was redefined in place"
    assert {(n, v) for n, v, _ in rows} == set(by_key), "a definition is unlocked"


def test_in_place_edit_with_recomputed_hash_is_rejected():
    doc = _doc()
    doc["features"][0]["missingSemantics"] = "treat missing as 0"
    doc["features"][0]["definitionHash"] = fd.definition_hash(doc["features"][0])
    with pytest.raises(fd.FeatureRedefinitionError, match="NEW version"):
        fd.build_dictionary(doc, lock=_lock())


def test_new_version_with_an_appended_lock_row_is_accepted_and_without_one_rejected():
    doc = _doc()
    v2 = copy.deepcopy(doc["features"][0])
    v2["version"] = 2
    v2["missingSemantics"] = "a stricter absence rule"
    v2["definitionHash"] = fd.definition_hash(v2)
    doc["features"].append(v2)
    with pytest.raises(fd.FeatureRedefinitionError, match="not in the append-only lock"):
        fd.build_dictionary(doc, lock=_lock())
    lock = _lock()
    lock["locked"].append(
        {"name": v2["name"], "version": 2, "definitionHash": v2["definitionHash"]}
    )
    d = fd.build_dictionary(doc, lock=lock)
    assert d.get(v2["name"], 1).missing_semantics != d.get(v2["name"], 2).missing_semantics


def test_removing_a_lock_row_is_rejected():
    lock = _lock()
    del lock["locked"][0]
    with pytest.raises(fd.FeatureRedefinitionError, match="not in the append-only lock"):
        fd.build_dictionary(_doc(), lock=lock)


def test_removing_a_locked_definition_is_rejected():
    doc = _doc()
    del doc["features"][0]
    with pytest.raises(fd.FeatureRedefinitionError, match="no longer defined"):
        fd.build_dictionary(doc, lock=_lock())


def test_a_lock_naming_one_version_twice_is_rejected():
    lock = _lock()
    lock["locked"].append(dict(lock["locked"][0]))
    with pytest.raises(fd.FeatureRedefinitionError, match="twice"):
        fd.build_dictionary(_doc(), lock=lock)


def test_the_lock_is_immutable_across_its_whole_history():
    """Append-only across history: every (name, version) the lock has EVER held,
    in any commit reachable from HEAD, survives here with its first hash. The
    logic lives in scripts/check_feature_dictionary_lock.py and this gate runs
    exactly that check, so the two cannot disagree. Locally an unavailable or
    shallow history skips (exit 2); under CI it FAILS (exit 1) — a gate that
    cannot read its input has not passed."""
    code, message = chk.check()
    if code == 2:
        assert not os.environ.get("CI")
        pytest.skip(message)
    assert code == 0, message


# ── the lock-history script, against real temporary git repositories ───────

_LOCK_REL = chk.LOCK_REL


def _h(ch: str) -> str:
    return ch * 64


def _git(repo, *args) -> str:
    out = subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )
    return out.stdout.strip()


def _write_lock(repo, rows) -> None:
    path = repo / _LOCK_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    locked = [{"name": n, "version": v, "definitionHash": h} for n, v, h in rows]
    path.write_text(json.dumps({"schemaVersion": 1, "locked": locked}, indent=2), "utf-8")


def _commit(repo, message: str, rows=None) -> str:
    if rows is not None:
        _write_lock(repo, rows)
    else:
        (repo / "other.txt").write_text(message, "utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    return root


def _check(repo, env=None):
    return chk.check({"CI": "1"} if env is None else env, repo=repo, lock_rel=_LOCK_REL)


A1, B1 = ("a", 1, _h("a")), ("b", 1, _h("b"))


def test_a_clean_history_with_an_appended_new_version_passes(repo):
    _commit(repo, "lock", [A1, B1])
    _commit(repo, "unrelated")
    _commit(repo, "a v2", [A1, B1, ("a", 2, _h("c"))])
    code, message = _check(repo)
    assert code == 0, message
    _write_lock(repo, [A1, B1, ("a", 2, _h("c")), ("b", 2, _h("d"))])  # uncommitted append
    assert _check(repo)[0] == 0


def test_a_rewrite_followed_by_an_unrelated_commit_is_caught(repo):
    """The laundering case: P2 rewrites a row (its deploy red or replaced), P3 is
    unrelated. A single-base check run on P3 compares against P2 and passes."""
    _commit(repo, "lock", [A1, B1])
    _commit(repo, "P2 rewrite", [("a", 1, _h("e")), B1])
    _commit(repo, "P3 unrelated")
    code, message = _check(repo)
    assert code == 1 and "a v1 rewritten" in message


def test_a_rewrite_that_is_later_restored_is_still_caught(repo):
    _commit(repo, "lock", [A1, B1])
    _commit(repo, "rewrite", [("a", 1, _h("e")), B1])
    _commit(repo, "restore", [A1, B1])
    assert _check(repo)[0] == 1


def test_an_uncommitted_rewrite_is_caught(repo):
    _commit(repo, "lock", [A1, B1])
    _write_lock(repo, [A1, ("b", 1, _h("f"))])
    code, message = _check(repo)
    assert code == 1 and "b v1 rewritten at working tree" in message


def test_a_removed_row_is_caught(repo):
    _commit(repo, "lock", [A1, B1])
    _commit(repo, "remove b", [A1])
    _commit(repo, "unrelated")
    code, message = _check(repo)
    assert code == 1 and "b v1 was removed at" in message


def test_re_adding_a_removed_row_with_its_original_hash_does_not_repair_the_removal(repo):
    """Removal is already a violation, seen AT the commit that dropped the row:
    the re-add restores the same hash in the same position, so neither the
    hash, the current-lock membership nor the order rule would notice."""
    _commit(repo, "lock", [A1, B1])
    removal = _commit(repo, "remove b", [A1])
    _commit(repo, "re-add b", [A1, B1])
    code, message = _check(repo)
    assert code == 1 and f"b v1 was removed at {removal[:12]}" in message


def test_a_merge_that_drops_a_side_branch_row_is_caught(repo):
    """`-s ours` keeps main's lock and silently discards the side branch's row."""
    _commit(repo, "lock", [A1])
    _git(repo, "checkout", "-q", "-b", "side")
    _commit(repo, "side appends c", [A1, ("c", 1, _h("c"))])
    _git(repo, "checkout", "-q", "main")
    _commit(repo, "main appends b", [A1, B1])
    _git(repo, "merge", "-q", "--no-edit", "-s", "ours", "side")
    code, message = _check(repo)
    assert code == 1 and "c v1 was removed at" in message


def test_a_reordered_lock_is_caught(repo):
    _commit(repo, "lock", [A1, B1])
    _commit(repo, "reorder", [B1, A1])
    code, message = _check(repo)
    assert code == 1 and "reordered" in message


def test_a_new_row_inserted_before_a_locked_row_is_caught(repo):
    _commit(repo, "lock", [A1, B1])
    _write_lock(repo, [A1, ("c", 1, _h("c")), B1])
    code, message = _check(repo)
    assert code == 1 and "not appended" in message


def test_parallel_branches_appending_different_rows_merge_cleanly(repo):
    _commit(repo, "lock", [A1])
    _git(repo, "checkout", "-q", "-b", "side")
    _commit(repo, "side appends c", [A1, ("c", 1, _h("c"))])
    _git(repo, "checkout", "-q", "main")
    _commit(repo, "main appends b", [A1, B1])
    _git(repo, "merge", "-q", "--no-commit", "-s", "ours", "side")
    _write_lock(repo, [A1, B1, ("c", 1, _h("c"))])
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "merge side")
    code, message = _check(repo)
    assert code == 0, message


def test_a_rewrite_on_a_merged_side_branch_is_caught(repo):
    _commit(repo, "lock", [A1, B1])
    _git(repo, "checkout", "-q", "-b", "side")
    _commit(repo, "side rewrites a", [("a", 1, _h("e")), B1])
    _commit(repo, "side restores a", [A1, B1])
    _git(repo, "checkout", "-q", "main")
    _commit(repo, "main unrelated")
    _git(repo, "merge", "-q", "--no-edit", "side")
    assert _check(repo)[0] == 1


def test_history_before_the_lock_existed_passes(repo):
    _commit(repo, "pre-AL-0")
    _commit(repo, "lock", [A1])
    assert _check(repo)[0] == 0


def _shallow_clone(src, dest, depth: int):
    subprocess.run(
        ["git", "clone", "-q", f"--depth={depth}", src.resolve().as_uri(), str(dest)],
        capture_output=True,
        text=True,
        check=True,
    )
    return dest


def test_a_shallow_clone_that_cuts_the_lock_history_fails_closed_under_ci(repo, tmp_path):
    _commit(repo, "lock", [A1, B1])
    _commit(repo, "rewrite", [("a", 1, _h("e")), B1])
    _commit(repo, "unrelated")
    clone = _shallow_clone(repo, tmp_path / "shallow", 1)
    code, message = _check(clone)
    assert code == 1 and "shallow" in message
    assert _check(clone, env={})[0] == 2  # locally: not checked, never passed


def test_a_shallow_clone_whose_boundary_predates_the_lock_is_complete(repo, tmp_path):
    _commit(repo, "pre-AL-0")
    _commit(repo, "lock", [A1])
    _commit(repo, "unrelated")
    assert _check(_shallow_clone(repo, tmp_path / "d2", 2))[0] == 1  # boundary IS the lock commit
    assert _check(_shallow_clone(repo, tmp_path / "d3", 3))[0] == 0  # boundary predates it


def test_no_repository_fails_closed_under_ci(tmp_path):
    _write_lock(tmp_path, [A1])
    assert _check(tmp_path)[0] == 1
    assert _check(tmp_path, env={})[0] == 2


def test_a_historical_lock_that_does_not_parse_is_an_error(repo):
    path = repo / _LOCK_REL
    path.parent.mkdir(parents=True)
    path.write_text("{not json", "utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "broken")
    _commit(repo, "fixed", [A1])
    code, message = _check(repo, env={})
    assert code == 1 and "does not parse" in message


def test_main_reports_the_check(monkeypatch, capsys):
    monkeypatch.setattr(chk, "check", lambda env=None, **k: (2, "not checked"))
    assert chk.main([], env={}) == 2
    assert "not checked" in capsys.readouterr().out


def test_the_lock_path_is_pinned_so_a_rename_cannot_reset_its_history():
    """The history check walks one path and git rev-list does not follow renames:
    moving the lock (and DEFAULT_LOCK_PATH with it) would start a fresh history
    in which existing rows could be rewritten undetected.  Moving it is therefore
    a deliberate act that must update this literal in the same change."""
    from src.model_registry import feature_dictionary as fd

    rel = fd.DEFAULT_LOCK_PATH.relative_to(fd.REPO).as_posix()
    assert rel == "config/model_registry/feature_dictionary.lock.json"
