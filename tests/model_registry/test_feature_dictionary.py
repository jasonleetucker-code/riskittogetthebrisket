"""AL-0 versioned feature dictionary (A4): undefined features and redefinitions fail."""

from __future__ import annotations

import copy
import json
import os

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


def test_the_base_branch_lock_is_a_prefix_of_this_lock():
    """Append-only across history: every row the base locked survives here,
    unchanged and in order. The logic lives in scripts/check_feature_dictionary_lock.py
    (push event -> the payload's ``before``; PR -> merge-base; on main -> HEAD~1),
    and this gate runs exactly that check, so the two cannot disagree. Locally an
    unavailable base skips (exit 2); under CI it FAILS (exit 1) — a gate that
    cannot find its input has not passed."""
    code, message = chk.check()
    if code == 2:
        assert not os.environ.get("CI")
        pytest.skip(message)
    assert code == 0, message


# ── the lock-history script, with a fake git ────────────────────────────────


class _FakeGit:
    """``commits``: shas that exist (``cat-file -e <sha>^{commit}``); ``files``:
    ``"<sha>:<path>"`` -> text (``None`` = listed in the tree but unreadable)."""

    def __init__(self, revs: dict[str, str], merge_bases: dict[str, str], files=None, commits=()):
        self.revs, self.merge_bases, self.files = revs, merge_bases, files or {}
        self.commits = set(commits) | set(revs.values())
        self.commits |= {key.split(":", 1)[0] for key in self.files}

    def __call__(self, *args: str):
        if args[0] == "rev-parse":
            ref = args[-1].removesuffix("^{commit}")
            return (0, self.revs[ref] + "\n") if ref in self.revs else (1, "")
        if args[0] == "merge-base":
            mb = self.merge_bases.get(args[2])
            return (0, mb + "\n") if mb else (1, "")
        if args[0] == "cat-file":
            sha = args[2].removesuffix("^{commit}")
            return (0, "") if sha in self.commits else (128, "")
        if args[0] == "ls-tree":
            sha, path = args[1], args[3]
            if sha not in self.commits:
                return 128, ""
            return (0, f"100644 blob x\t{path}\n") if f"{sha}:{path}" in self.files else (0, "")
        if args[0] == "show":
            text = self.files.get(args[1])
            return (0, text) if isinstance(text, str) else (128, "")
        raise AssertionError(args)


def _event(tmp_path, payload) -> str:
    path = tmp_path / "event.json"
    path.write_text(payload if isinstance(payload, str) else json.dumps(payload), "utf-8")
    return str(path)


_LOCK_REL = fd.DEFAULT_LOCK_PATH.relative_to(fd.REPO).as_posix()


def test_on_a_push_event_the_base_is_the_pushs_before_not_head_1(tmp_path):
    """Round-3 D1: a push of three commits h <- p <- q <- b(before). HEAD~1 is p,
    which would hide a lock edit made in q; the base is the pre-push tip b."""
    git = _FakeGit(
        {"HEAD": "h", "HEAD~1": "p", "origin/main": "h", "b" * 40: "b" * 40},
        {"origin/main": "h"},
    )
    env = {"GITHUB_EVENT_NAME": "push", "GITHUB_EVENT_PATH": _event(tmp_path, {"before": "b" * 40})}
    assert chk.resolve_base(env, git)[0] == "b" * 40


def test_a_multi_commit_push_editing_the_lock_in_an_earlier_commit_fails(tmp_path, monkeypatch):
    base_rows = fd.parse_lock(LOCK)
    tampered = _lock()
    tampered["locked"][0]["definitionHash"] = "0" * 64
    before = "b" * 40
    git = _FakeGit(
        {"HEAD": "h", "HEAD~1": "p", before: before},
        {},
        files={f"{before}:{_LOCK_REL}": json.dumps(LOCK), f"p:{_LOCK_REL}": json.dumps(tampered)},
    )
    monkeypatch.setattr(fd, "load_lock", lambda *a, **k: tampered)
    env = {
        "GITHUB_EVENT_NAME": "push",
        "GITHUB_EVENT_PATH": _event(tmp_path, {"before": before}),
        "CI": "1",
    }
    code, message = chk.check(env, git=git)
    assert code == 1 and f"{base_rows[0][0]} v{base_rows[0][1]}" in message
    # what the old HEAD~1 rule would have compared against: the already-edited lock
    assert chk.compare(fd.parse_lock(tampered), chk.base_lock_rows("p", git)).ok


@pytest.mark.parametrize(
    "event",
    [None, "{not json", {"ref": "refs/heads/main"}, {"before": ""}, ["before"]],
    ids=["no-event-path", "unreadable", "no-before", "empty-before", "not-an-object"],
)
def test_a_push_without_a_readable_before_has_no_base_and_fails_under_ci(tmp_path, event):
    git = _FakeGit({"HEAD": "h", "HEAD~1": "p", "origin/main": "h"}, {"origin/main": "h"})
    env = {"GITHUB_EVENT_NAME": "push"}
    if event is not None:
        env["GITHUB_EVENT_PATH"] = _event(tmp_path, event)
    base, how = chk.resolve_base(env, git)
    assert base is None, "must never fall back to HEAD~1"
    assert chk.check({**env, "CI": "true"}, git=git)[0] == 1
    assert chk.check(env, git=git)[0] == 2


def test_a_missing_event_file_fails_closed(tmp_path):
    git = _FakeGit({"HEAD": "h", "HEAD~1": "p"}, {})
    env = {
        "GITHUB_EVENT_NAME": "push",
        "GITHUB_EVENT_PATH": str(tmp_path / "absent.json"),
        "CI": "1",
    }
    assert chk.resolve_base(env, git)[0] is None
    assert chk.check(env, git=git)[0] == 1


def test_a_push_whose_before_is_not_in_the_checkout_fails_closed(tmp_path):
    """A shallow clone or a force-push that orphaned ``before``."""
    git = _FakeGit({"HEAD": "h", "HEAD~1": "p"}, {})
    env = {"GITHUB_EVENT_NAME": "push", "GITHUB_EVENT_PATH": _event(tmp_path, {"before": "c" * 40})}
    base, how = chk.resolve_base(env, git)
    assert base is None and "fetch-depth" in how
    assert chk.check({**env, "CI": "1"}, git=git)[0] == 1


@pytest.mark.parametrize("zeros", ["0" * 40, "0" * 64])
def test_a_push_that_created_the_ref_compares_against_the_merge_base(tmp_path, zeros):
    git = _FakeGit({"HEAD": "h", "HEAD~1": "p", "origin/main": "m"}, {"origin/main": "mb"})
    env = {"GITHUB_EVENT_NAME": "push", "GITHUB_EVENT_PATH": _event(tmp_path, {"before": zeros})}
    base, how = chk.resolve_base(env, git)
    assert base == "mb" and "created the ref" in how


def test_when_the_merge_base_is_head_the_base_is_the_previous_commit():
    git = _FakeGit({"HEAD": "h", "HEAD~1": "p", "origin/main": "h"}, {"origin/main": "h"})
    assert chk.resolve_base({}, git)[0] == "p"


def test_a_pull_request_compares_against_its_base_ref_merge_base():
    git = _FakeGit(
        {"HEAD": "h", "HEAD~1": "p", "origin/release": "r", "origin/main": "m"},
        {"origin/release": "mb-r", "origin/main": "mb-m"},
    )
    assert chk.resolve_base({"GITHUB_BASE_REF": "release"}, git)[0] == "mb-r"
    assert chk.resolve_base({}, git)[0] == "mb-m"


def test_a_set_base_ref_that_does_not_resolve_is_no_base_not_origin_main():
    """Round-3 D2: GITHUB_BASE_REF names the PR's base; when it does not resolve,
    quietly comparing against origin/main would check the wrong branch."""
    git = _FakeGit({"HEAD": "h", "HEAD~1": "p", "origin/main": "m"}, {"origin/main": "mb-m"})
    base, how = chk.resolve_base({"GITHUB_BASE_REF": "release"}, git)
    assert base is None and "release" in how
    assert chk.check({"GITHUB_BASE_REF": "release", "CI": "1"}, git=git)[0] == 1


def test_schedule_and_dispatch_on_main_keep_head_1():
    """smoke-test (schedule/dispatch, fetch-depth 2) is not a push event."""
    git = _FakeGit({"HEAD": "h", "HEAD~1": "p", "origin/main": "h"}, {"origin/main": "h"})
    for event in ("schedule", "workflow_dispatch"):
        assert chk.resolve_base({"GITHUB_EVENT_NAME": event}, git)[0] == "p"


def test_under_ci_a_missing_base_fails_and_locally_it_is_not_checked(monkeypatch):
    monkeypatch.setattr(chk, "resolve_base", lambda env, git=None: (None, "no refs"))
    assert chk.main([], env={"CI": "true"}) == 1
    assert chk.main([], env={}) == 2


@pytest.mark.parametrize("bogus", ["0" * 40, "deadbeef" * 5, "not-a-ref"])
def test_a_bogus_base_is_an_error_never_history_before_the_lock(bogus):
    """Round-3 D2: `--base 0000…` under CI used to exit 0, because any cat-file
    failure read as "the base predates the lock"."""
    git = _FakeGit({"HEAD": "h"}, {})
    with pytest.raises(chk.LockCheckError, match="not a commit"):
        chk.base_lock_rows(bogus, git)
    assert chk.check({"CI": "1"}, base=bogus, git=git)[0] == 1
    assert chk.check({}, base=bogus, git=git)[0] == 1


def test_a_base_lock_that_exists_but_cannot_be_read_is_an_error():
    git = _FakeGit({}, {}, files={f"b:{_LOCK_REL}": None})
    with pytest.raises(chk.LockCheckError, match="git show"):
        chk.base_lock_rows("b", git)
    git = _FakeGit({}, {}, files={f"b:{_LOCK_REL}": "{not json"})
    with pytest.raises(chk.LockCheckError, match="does not parse"):
        chk.base_lock_rows("b", git)


def test_a_base_without_the_lock_file_has_nothing_to_preserve():
    """Only a commit that EXISTS and whose tree lists no lock predates AL-0."""
    git = _FakeGit({}, {}, commits={"b"})
    assert chk.base_lock_rows("b", git) is None
    assert chk.compare(fd.parse_lock(LOCK), None).ok
    assert chk.check({"CI": "1"}, base="b", git=git)[0] == 0


def test_a_commit_rewriting_a_definition_and_its_lock_row_is_caught():
    """The case the git-free test cannot see: dictionary and lock agree with each
    other, but the lock row differs from the one the previous commit held."""
    base = fd.parse_lock(LOCK)
    rewritten = [(base[0][0], base[0][1], "0" * 64), *base[1:]]
    result = chk.compare(rewritten, base)
    assert not result.ok and f"{base[0][0]} v{base[0][1]}" in result.message
    assert not chk.compare(base[1:], base).ok  # a removed row
    assert chk.compare([*base, ("new_feature", 1, "f" * 64)], base).ok  # an appended row
