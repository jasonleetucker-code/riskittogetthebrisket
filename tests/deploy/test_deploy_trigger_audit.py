"""The deploy-trigger audit applies GitHub's path filter and the bot-push rule.

``scripts/deploy_trigger_audit.py`` answers "which commits on main restart the
backend" offline.  It is only useful if its rules are the real ones, so:

* the glob and ``paths-ignore`` semantics are pinned on small cases;
* a temporary repository reproduces the three causes found on 2026-10-19..21
  (a box refresh commit that touches ``CSVs/site_raw``, a bot data-refresh
  commit that does not start a push run, a docs-only commit) and checks each is
  classified and counted correctly;
* the audit's two assumptions about OTHER files are pinned to those files:
  the dispatch subject regex must still be the one ``scheduled-refresh.yml``
  greps for, and ``deploy.yml`` must still declare a ``paths-ignore`` list.
  If either moves, this fails and the audit must be re-read -- on purpose.

Validated against production before it was committed: for 2026-10-19 00:00Z ->
2026-10-21 12:00Z the audit predicted 29 push-triggered deploys and the
repository ran 29.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess

import pytest

from scripts import deploy_trigger_audit as audit

REPO = Path(__file__).resolve().parents[2]

WORKFLOW = """\
name: Deploy Production
on:
  push:
    branches: [main]
    paths-ignore:
      - 'data/**'
      - 'exports/**'
  workflow_dispatch:
jobs: {}
"""


@pytest.mark.parametrize(
    ("pattern", "path", "expected"),
    [
        ("data/**", "data/scrape_state/x_last_success", True),
        ("data/**", "data/a.json", True),
        ("data/**", "CSVs/site_raw/dlfSf.csv", False),
        ("data/**", "metadata/x", False),
        ("exports/**", "exports/latest/a/b/c.csv", True),
        ("*.md", "README.md", True),
        ("*.md", "docs/README.md", False),
        ("**/*.md", "docs/a/README.md", True),
        ("**/*.md", "README.md", True),
        ("docs/**", "docs/a/b.md", True),
        ("tests/**", "tests/deploy/test_x.py", True),
        ("a?c", "abc", True),
        ("a?c", "a/c", False),
        ("a.c", "abc", False),
    ],
)
def test_glob_semantics(pattern, path, expected):
    assert bool(audit.glob_to_regex(pattern).match(path)) is expected


def test_a_push_is_suppressed_only_when_every_file_is_ignored():
    ignore = ["data/**", "exports/**"]
    assert not audit.push_starts_deploy(["data/a", "exports/b"], ignore)
    assert audit.push_starts_deploy(["data/a", "CSVs/site_raw/dlfSf.csv"], ignore)
    assert audit.push_starts_deploy([], ignore)  # nothing to filter on: not suppressed


@pytest.mark.parametrize(
    ("subject", "files", "expected"),
    [
        (
            "chore(dlf): automated refresh 2026-10-19T12:27:31Z",
            ["CSVs/site_raw/dlfSf.csv"],
            "box_data_refresh",
        ),
        ("chore(idpshow): automated refresh 2026-10-20T08:32:17Z", ["data/x"], "box_data_refresh"),
        (
            "chore: automated data refresh 2026-10-20T05:26:10Z",
            ["CSVs/dynasty_full.csv"],
            "ci_data_refresh",
        ),
        (
            "chore: freshness stamps 2026-10-20T05:26:07Z",
            ["data/scrape_state/a"],
            "ci_data_refresh",
        ),
        (
            "chore(calibration): record Hill two-hour refit evidence",
            ["config/model_registry/a.json"],
            "hill_refit_evidence",
        ),
        ("docs: note", ["docs/a.md", "README.md"], "non_runtime_only"),
        ("test: add", ["tests/a.py", "frontend/__tests__/a.test.js"], "non_runtime_only"),
        ("ci: workflow", ["tests/a.py", ".github/workflows/deploy.yml"], "runtime_change"),
        ("fix: server", ["server.py", "docs/a.md"], "runtime_change"),
    ],
)
def test_commit_classification(subject, files, expected):
    assert audit.classify_commit(subject, files) == expected


def _git(repo: Path, *args: str, env: dict | None = None) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        env={**os.environ, **(env or {})},
    )


def _commit(repo: Path, files: dict[str, str], subject: str, author: str, when: str) -> None:
    for rel, body in files.items():
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    _git(repo, "add", "-A")
    stamp = {"GIT_AUTHOR_DATE": when, "GIT_COMMITTER_DATE": when}
    _git(
        repo,
        "-c",
        f"user.name={author}",
        "-c",
        "user.email=x@example.invalid",
        "commit",
        "-q",
        "-m",
        subject,
        env=stamp,
    )


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q", "-b", "main")
    _commit(
        tmp_path,
        {".github/workflows/deploy.yml": WORKFLOW, "server.py": "v=1\n"},
        "init",
        "owner",
        "2026-10-18T00:00:00+00:00",
    )
    return tmp_path


def test_the_three_causes_found_in_production_are_classified_and_counted(repo: Path):
    # 1. box DLF refresh: touches a CSV outside paths-ignore -> starts a deploy
    _commit(
        repo,
        {"CSVs/site_raw/dlfSf.csv": "a\n", "data/scrape_state/dlf_last_success": "1\n"},
        "chore(dlf): automated refresh 2026-10-19T12:27:31Z",
        "DLF Fetch (prod)",
        "2026-10-19T12:27:40+00:00",
    )
    # 2. bot data refresh: passes the filter but GITHUB_TOKEN pushes start no run
    _commit(
        repo,
        {"CSVs/dynasty_full.csv": "b\n"},
        "chore: automated data refresh 2026-10-19T14:04:10Z",
        "github-actions[bot]",
        "2026-10-19T14:04:11+00:00",
    )
    # 3. docs-only human commit: still starts a deploy today
    _commit(
        repo,
        {"docs/notes.md": "x\n"},
        "docs: note",
        "owner",
        "2026-10-19T15:00:00+00:00",
    )
    # 4. box IDP Show refresh that only touches data/: suppressed by the filter
    _commit(
        repo,
        {"data/scrape_state/idpShow_last_success": "2\n"},
        "chore(idpshow): automated refresh 2026-10-19T16:32:14Z",
        "IDP Show Fetch (prod)",
        "2026-10-19T16:32:20+00:00",
    )
    report = audit.audit(repo, "HEAD", "2026-10-19T00:00:00Z", "2026-10-20T00:00:00Z")
    rows = {r["subject"].split(" 2026")[0]: r for r in report["commits"]}

    dlf = rows["chore(dlf): automated refresh"]
    assert dlf["kind"] == "box_data_refresh" and dlf["starts_push_deploy"]
    assert dlf["non_ignored_files"] == ["CSVs/site_raw/dlfSf.csv"]

    bot = rows["chore: automated data refresh"]
    assert bot["passes_paths_filter"] and not bot["starts_push_deploy"]
    assert bot["dispatches_deploy_after"]  # scheduled-refresh dispatches deploy.yml instead

    docs = rows["docs: note"]
    assert docs["kind"] == "non_runtime_only" and docs["starts_push_deploy"]

    idp = rows["chore(idpshow): automated refresh"]
    assert idp["kind"] == "box_data_refresh" and not idp["passes_paths_filter"]
    assert not idp["starts_push_deploy"]

    assert report["by_kind"] == {"box_data_refresh": 2, "ci_data_refresh": 1, "non_runtime_only": 1}
    assert report["push_deploys_by_kind"] == {
        "box_data_refresh": 1,
        "ci_data_refresh": 0,
        "non_runtime_only": 1,
    }
    assert report["push_deploys_total"] == 2
    # the pre-window "init" commit is outside --since
    assert report["commits_first_parent"] == 4


def test_window_uses_committer_date_and_reports_utc(repo: Path):
    _commit(repo, {"server.py": "v=2\n"}, "fix: a", "owner", "2026-10-19T12:00:00+02:00")
    report = audit.audit(repo, "HEAD", "2026-10-19T09:00:00Z", "2026-10-19T11:00:00Z")
    assert [c["when"] for c in report["commits"]] == ["2026-10-19T10:00Z"]


def test_tally_joins_push_runs_to_commit_kinds_and_keeps_dispatch_separate(tmp_path: Path):
    commits = [
        {"sha": "aaaaaaaaa", "kind": "box_data_refresh"},
        {"sha": "bbbbbbbbb", "kind": "runtime_change"},
    ]
    runs = [
        {
            "createdAt": "2026-10-19T12:30:00Z",
            "event": "push",
            "conclusion": "success",
            "headSha": "a" * 40,
        },
        {
            "createdAt": "2026-10-19T13:30:00Z",
            "event": "push",
            "conclusion": "cancelled",
            "headSha": "b" * 40,
        },
        {
            "createdAt": "2026-10-19T14:30:00Z",
            "event": "workflow_dispatch",
            "conclusion": "failure",
            "headSha": "c" * 40,
        },
        {
            "createdAt": "2026-10-19T15:30:00Z",
            "event": "push",
            "conclusion": None,
            "headSha": "d" * 40,
        },
        {
            "createdAt": "2026-10-25T00:00:00Z",
            "event": "push",
            "conclusion": "success",
            "headSha": "a" * 40,
        },
    ]
    path = tmp_path / "runs.json"
    path.write_text(json.dumps(runs), encoding="utf-8")
    out = audit.tally_runs(path, "2026-10-19T00:00:00Z", "2026-10-20T00:00:00Z", commits)
    assert out["by_event_conclusion"] == {
        "push:cancelled": 1,
        "push:none": 1,
        "push:success": 1,
        "workflow_dispatch:failure": 1,
    }
    assert out["push_runs_by_commit_kind"] == {
        "box_data_refresh:success": 1,
        "runtime_change:cancelled": 1,
        "unknown:none": 1,
    }


def test_cli_reports_and_fails_cleanly(repo: Path, capsys, tmp_path: Path):
    assert audit.main(["--repo", str(repo), "--format", "json"]) == 0
    assert json.loads(capsys.readouterr().out)["commits_first_parent"] == 1
    assert audit.main(["--repo", str(tmp_path / "no-such-repo")]) == 2
    assert "deploy_trigger_audit" in capsys.readouterr().err


# ── drift guards: the audit's assumptions about other files ──────────────


def test_dispatch_subject_is_the_expression_scheduled_refresh_greps_for():
    text = (REPO / ".github" / "workflows" / "scheduled-refresh.yml").read_text(encoding="utf-8")
    assert f'grep -qE "{audit.DISPATCH_SUBJECT.pattern}"' in text, (
        "scheduled-refresh.yml no longer dispatches deploy.yml on this commit-message expression; "
        "update DISPATCH_SUBJECT in scripts/deploy_trigger_audit.py (and re-read the audit)."
    )


def test_deploy_workflow_still_declares_a_paths_ignore_list():
    ignore = audit.load_paths_ignore(REPO / ".github" / "workflows" / "deploy.yml")
    assert ignore and all(isinstance(p, str) and p for p in ignore)


def test_the_real_repo_audit_runs_on_head():
    # bounded window: a shallow CI checkout may hold one commit, and walking the
    # whole history with --name-only would make this test slow for no reason.
    report = audit.audit(REPO, "HEAD", since="1 day ago", until=None)
    assert report["paths_ignore"] == audit.load_paths_ignore(
        REPO / ".github" / "workflows" / "deploy.yml"
    )
