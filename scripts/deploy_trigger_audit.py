#!/usr/bin/env python3
"""Which commits on ``main`` start a production deploy -- and so restart the backend?

OFFLINE and READ-ONLY.  It reads ``git log`` of a local clone and the
``paths-ignore`` list of ``.github/workflows/deploy.yml``, applies GitHub's own
rule to each first-parent commit, and counts the commits that WOULD start a
push-triggered deploy, by kind.  It deploys, dispatches and restarts nothing.

WHY IT EXISTS
-------------
Every successful deploy restarts ``dynasty.service`` (``deploy/deploy.sh``
``restart_service``), and every backend start launches an unconditional scrape
3 s after boot (``server.py`` lifespan, ``run_scraper(trigger="startup")``,
which includes a ~700 MiB Chromium).  So "how often is the backend restarted,
and by what" is a question about commits, and it was being answered by hand.

GITHUB'S RULE, as implemented here
----------------------------------
A ``push`` workflow that lists only ``paths-ignore`` does NOT run when EVERY
file changed by the push matches an ignored pattern; it runs when at least one
does not.  A box-side refresh commit that touches ``CSVs/site_raw/*.csv`` as
well as ``data/scrape_state/*`` therefore starts a deploy, because ``CSVs/`` is
not ignored.  (One first-parent commit stands in for one push; a push that
carries several commits is counted once per commit, so counts are an upper
bound on pushes.)

A SECOND PATH THIS CANNOT SEE FROM GIT
--------------------------------------
``scheduled-refresh.yml`` DISPATCHES ``deploy.yml`` explicitly after a commit
whose message matches ``DISPATCH_SUBJECT`` (below -- a test pins it to the
workflow text).  Those deploys are ``workflow_dispatch`` events and are not in
``git log``; pass ``--runs-json`` (``gh run list --workflow=deploy.yml --json
createdAt,conclusion,event,displayTitle,headSha``) to count them.

COMMITS IN A WINDOW ARE NOT RESTARTS IN THAT WINDOW
---------------------------------------------------
The commit table selects by COMMIT time; a deploy completes 80-110 min later,
so the restarts inside a window come partly from commits before it, and the
last commits in it restart the backend after it closes.  To count RESTARTS by
cause, pass ``--restart-log`` (a restart-diagnostics log): each clean backend
stop is matched to the successful deploy run that completed 0-30 min after it
(``attribute_restarts``).  On 2026-10-19 09:55Z -> 2026-10-20 09:55Z the commit
table says 6 runtime / 1 docs-only / 4 DLF, while the 11 restarts were
7 runtime / 0 docs-only / 4 DLF.

Usage:
    python scripts/deploy_trigger_audit.py --since 2026-10-19T09:55Z --until 2026-10-20T09:55Z
           [--repo .] [--ref origin/main] [--runs-json runs.json]
           [--restart-log diagnostics.log] [--format json|text]
Exit codes: 0 report printed; 2 git/workflow unreadable; 3 report printed but the
``--restart-log`` input is incomplete (masked/unparseable lifecycle lines).
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
import subprocess
import sys

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = Path(".github") / "workflows" / "deploy.yml"

#: ``scheduled-refresh.yml`` "Trigger deploy": ``grep -qE "<this>"`` on the
#: latest commit message.  tests/deploy/test_deploy_trigger_audit.py asserts
#: the workflow still carries exactly this expression.
DISPATCH_SUBJECT = re.compile(r"automated data refresh|freshness stamps")

#: Box-side timers that push their own refresh commits to main
#: (``deploy/dlf_fetch_and_push.sh``, ``deploy/idpshow_fetch_and_push.sh``).
BOX_REFRESH_SUBJECT = re.compile(r"^chore\((?:dlf|idpshow)\): automated refresh")

#: Hill Autopilot's per-refit evidence commit (``config/model_registry/**``).
#: It passes the path filter, but Hill Autopilot pushes it as
#: ``github-actions[bot]`` (see TOKEN_PUSH_AUTHORS), so it starts NO push run.
HILL_EVIDENCE_SUBJECT = re.compile(r"^chore\(calibration\): record Hill")

#: A commit pushed with the workflow ``GITHUB_TOKEN`` does not start another
#: workflow (GitHub: "events triggered by the GITHUB_TOKEN ... will not create a
#: new workflow run").  scheduled-refresh and Hill Autopilot push as this
#: author, which is why scheduled-refresh has to ``gh workflow run deploy.yml``
#: explicitly.  Validated on PUSH RUNS, selected by commit / run-creation time:
#: for commits in 2026-10-19 09:55Z -> 2026-10-20 09:55Z this rule predicts 11
#: push deploys and 11 push runs were created; over 2026-10-19 00:00Z ->
#: 2026-10-21 12:00Z, 29 and 29.  That is NOT a count of the restarts in the
#: same window: a deploy completes 80-110 min after its commit, so restarts
#: are attributed separately, by run completion (``attribute_restarts``).
TOKEN_PUSH_AUTHORS = frozenset({"github-actions[bot]"})

#: A deploy restarts the backend a few minutes BEFORE its run completes (the
#: post-deploy smoke and live checks run after the restart).  Measured on
#: 2026-10-19..20: the clean stop precedes its run's completion by 4-16 min.
#: A stop is attributed to the earliest successful deploy run that completes
#: within this many minutes after it.
RESTART_TO_RUN_END_MAX_MINUTES = 30

_RS, _US = "\x1e", "\x1f"


def load_paths_ignore(workflow_path: Path) -> list[str]:
    """``on.push.paths-ignore`` of a workflow file (PyYAML reads ``on`` as True)."""
    doc = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
    on = doc.get("on", doc.get(True)) or {}
    push = (on.get("push") if isinstance(on, dict) else None) or {}
    patterns = push.get("paths-ignore") or []
    return [str(p) for p in patterns]


def glob_to_regex(pattern: str) -> re.Pattern[str]:
    """GitHub filter-pattern glob: ``**`` crosses ``/``; ``*`` and ``?`` do not."""
    out, i = [], 0
    while i < len(pattern):
        ch = pattern[i]
        if pattern.startswith("**", i):
            out.append(".*")
            i += 2
            # "**/" also matches zero directories
            if pattern.startswith("/", i):
                out[-1] = "(?:.*/)?"
                i += 1
            continue
        out.append("[^/]*" if ch == "*" else "[^/]" if ch == "?" else re.escape(ch))
        i += 1
    return re.compile("".join(out) + r"\Z")


def push_starts_deploy(changed: list[str], ignore: list[str]) -> bool:
    """True unless every changed file matches an ignored pattern."""
    if not changed:
        return True  # nothing to filter on: GitHub does not suppress the run
    compiled = [glob_to_regex(p) for p in ignore]
    return not all(any(c.match(f) for c in compiled) for f in changed)


#: Files that never reach the running process: prose and tests.  A commit
#: touching ONLY these still starts a full deploy (and so a restart) today,
#: because ``paths-ignore`` lists only ``data/**`` and ``exports/**``.
#: Deliberately conservative: workflows, config, scripts and CSVs are NOT here.
NON_RUNTIME_PATTERNS = ("docs/**", "**/*.md", "*.md", "tests/**", "frontend/__tests__/**")


def classify_commit(subject: str, files: list[str]) -> str:
    if BOX_REFRESH_SUBJECT.search(subject):
        return "box_data_refresh"
    if DISPATCH_SUBJECT.search(subject):
        return "ci_data_refresh"
    if HILL_EVIDENCE_SUBJECT.search(subject):
        return "hill_refit_evidence"
    if files:
        non_runtime = [glob_to_regex(p) for p in NON_RUNTIME_PATTERNS]
        if all(any(r.match(f) for r in non_runtime) for f in files):
            return "non_runtime_only"
    return "runtime_change"


def _git_log(repo: Path, ref: str, since: str | None, until: str | None) -> list[dict]:
    cmd = ["git", "-C", str(repo), "log", "--first-parent", "-m", "--name-only"]
    if since:
        cmd.append(f"--since={since}")
    if until:
        cmd.append(f"--until={until}")
    # Committer date, because ``--since`` / ``--until`` filter on it (an
    # author date can be weeks older on a squash or merge commit).
    cmd += [f"--format={_RS}%H{_US}%cI{_US}%an{_US}%s", ref]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=120)
    if proc.returncode:
        raise RuntimeError(proc.stderr.strip() or f"git log failed ({proc.returncode})")
    commits = []
    for block in proc.stdout.split(_RS):
        if not block.strip():
            continue
        head, _, files = block.partition("\n")
        sha, when, author, subject = (head.split(_US) + ["", "", "", ""])[:4]
        commits.append(
            {
                "sha": sha,
                "when": when,
                "author": author,
                "subject": subject,
                "files": [f for f in files.splitlines() if f.strip()],
            }
        )
    return commits


def audit(
    repo: Path,
    ref: str = "HEAD",
    since: str | None = None,
    until: str | None = None,
    workflow: Path | None = None,
) -> dict:
    ignore = load_paths_ignore(repo / WORKFLOW if workflow is None else workflow)
    commits = _git_log(repo, ref, since, until)
    rows, tally, starts = [], Counter(), Counter()
    for c in commits:
        kind = classify_commit(c["subject"], c["files"])
        passes_filter = push_starts_deploy(c["files"], ignore)
        deploys = passes_filter and c["author"] not in TOKEN_PUSH_AUTHORS
        tally[kind] += 1
        starts[kind] += int(deploys)
        rows.append(
            {
                "sha": c["sha"][:9],
                "when": _parse(c["when"]).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
                "author": c["author"],
                "kind": kind,
                "passes_paths_filter": passes_filter,
                "starts_push_deploy": deploys,
                "dispatches_deploy_after": bool(DISPATCH_SUBJECT.search(c["subject"])),
                "non_ignored_files": [
                    f for f in c["files"] if not any(glob_to_regex(p).match(f) for p in ignore)
                ][:5],
                "subject": c["subject"][:90],
            }
        )
    window_h = None
    if len(rows) >= 2:
        first, last = _parse(rows[-1]["when"]), _parse(rows[0]["when"])
        window_h = round((last - first).total_seconds() / 3600, 2)
    return {
        "paths_ignore": ignore,
        "commits_first_parent": len(rows),
        "by_kind": dict(tally),
        "push_deploys_by_kind": dict(starts),
        "push_deploys_total": sum(starts.values()),
        "first_to_last_commit_hours": window_h,
        "commits": rows,
    }


def _parse(stamp: str) -> datetime:
    return datetime.fromisoformat(stamp.replace("Z", "+00:00"))


def _shift(stamp: str | None, hours: float) -> str | None:
    """An ISO ``--since`` moved by ``hours``; other git date forms pass through."""
    if not stamp:
        return None
    try:
        return (_parse(stamp) + timedelta(hours=hours)).isoformat()
    except ValueError:
        return stamp


def tally_runs(
    path: Path, since: str | None, until: str | None, commits: list[dict] | None = None
) -> dict:
    """Count deploy workflow runs from ``gh run list --json``.

    ``by_event_conclusion`` is every run; ``push_runs_by_commit_kind`` joins each
    push run to the kind of the commit that started it, which is how a
    successful (= restarting) deploy is attributed to code or to data.
    Dispatch runs carry the head of main at dispatch time, not their cause, so
    they stay under their own event.
    """
    runs = json.loads(path.read_text(encoding="utf-8"))
    lo = _parse(since) if since else None
    hi = _parse(until) if until else None
    kind_of = {c["sha"]: c["kind"] for c in (commits or [])}
    by_event: Counter[str] = Counter()
    by_kind: Counter[str] = Counter()
    for r in runs:
        when = _parse(r["createdAt"])
        if (lo and when < lo) or (hi and when > hi):
            continue
        conclusion = r.get("conclusion") or "none"
        by_event[f"{r.get('event')}:{conclusion}"] += 1
        if r.get("event") == "push":
            by_kind[f"{kind_of.get(str(r.get('headSha'))[:9], 'unknown')}:{conclusion}"] += 1
    return {
        "by_event_conclusion": dict(sorted(by_event.items())),
        "push_runs_by_commit_kind": dict(sorted(by_kind.items())),
    }


def attribute_restarts(
    stops: list[dict],
    runs: list[dict],
    kind_of: dict[str, str],
    max_lag_minutes: float = RESTART_TO_RUN_END_MAX_MINUTES,
) -> dict:
    """Attribute each backend stop to the deploy run that caused it.

    ``stops``: ``{"ts": ISO, "kind": "clean_stop" | "watchdog_restart" | ...}``
    (``scripts/backend_restart_report.py``).  Only a ``clean_stop`` can be a
    deploy; every other kind is its own cause.  A clean stop is matched to the
    earliest SUCCESSFUL run (``gh run list --json``) completing in
    ``[stop, stop + max_lag_minutes]``, each run used once.  A push run's cause
    is the kind of its head commit (``kind_of``, keyed by 9-char SHA); a
    ``workflow_dispatch`` run is ``dispatch_deploy`` (scheduled-refresh).
    Unmatched clean stops are ``unattributed`` -- never guessed.
    """
    successes = sorted(
        (r for r in runs if r.get("conclusion") == "success" and r.get("updatedAt")),
        key=lambda r: _parse(r["updatedAt"]),
    )
    used: set[int] = set()
    rows, causes = [], Counter()
    for stop in sorted(stops, key=lambda s: _parse(s["ts"])):
        when = _parse(stop["ts"])
        row = {
            "stop": when.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "stop_kind": stop["kind"],
        }
        if stop["kind"] != "clean_stop":
            row["cause"] = stop["kind"]
        else:
            match = None
            for i, r in enumerate(successes):
                lag = (_parse(r["updatedAt"]) - when).total_seconds() / 60
                if i not in used and 0 <= lag <= max_lag_minutes:
                    match = i
                    break
            if match is None:
                row["cause"] = "unattributed"
            else:
                used.add(match)
                r = successes[match]
                sha = str(r.get("headSha") or "")[:9]
                row.update(
                    run_completed=r["updatedAt"],
                    run_event=r.get("event"),
                    head=sha,
                    minutes_before_run_end=round(
                        (_parse(r["updatedAt"]) - when).total_seconds() / 60, 1
                    ),
                    cause=(
                        "dispatch_deploy"
                        if r.get("event") == "workflow_dispatch"
                        else kind_of.get(sha, "unknown_commit")
                    ),
                )
        causes[row["cause"]] += 1
        rows.append(row)
    return {"by_cause": dict(sorted(causes.items())), "stops": rows}


def commit_kinds(repo: Path, ref: str, since: str | None, until: str | None) -> dict[str, str]:
    """9-char SHA -> kind for every first-parent commit in a window."""
    return {
        c["sha"][:9]: classify_commit(c["subject"], c["files"])
        for c in _git_log(repo, ref, since, until)
    }


def render_text(report: dict) -> str:
    lines = ["deploy trigger audit (offline; read-only)", ""]
    lines.append(f"  paths-ignore: {report['paths_ignore']}")
    lines.append(f"  first-parent commits: {report['commits_first_parent']}")
    lines.append(f"  by kind: {report['by_kind']}")
    lines.append(f"  would start a PUSH deploy, by kind: {report['push_deploys_by_kind']}")
    lines.append(f"  push deploys total: {report['push_deploys_total']}")
    if "deploy_runs" in report:
        lines.append(
            f"  actual deploy runs by event:conclusion: {report['deploy_runs']['by_event_conclusion']}"
        )
        lines.append(
            f"  push runs by commit kind:conclusion: {report['deploy_runs']['push_runs_by_commit_kind']}"
        )
    if "restart_attribution" in report:
        ra = report["restart_attribution"]
        if ra.get("input") == "incomplete":
            lines.append(
                f"  RESTART LOG INCOMPLETE: {ra['unparseable_relevant_lines']} relevant line(s) with "
                f"masked/unparseable timestamps {ra['unparseable_relevant_kinds']}; attribution is not a pass"
            )
        lines.append(f"  RESTARTS by cause (matched to deploy run completion): {ra['by_cause']}")
        for s in ra["stops"]:
            via = f" <- {s.get('run_event')} {s.get('head')} (run ended {s.get('minutes_before_run_end')} min later)"
            lines.append(f"    {s['stop']}  {s['cause']:<19}{via if 'head' in s else ''}")
    lines.append("")
    for row in report["commits"]:
        if row["starts_push_deploy"]:
            mark, extra = "DEPLOY", f"  via {row['non_ignored_files']}"
        elif row["passes_paths_filter"]:
            mark, extra = "bot-push", "  (GITHUB_TOKEN push: no push run; may dispatch)"
        else:
            mark, extra = "ignored", ""
        lines.append(
            f"  {row['when']}  {mark:<8} {row['kind']:<19} {row['sha']} {row['subject']}{extra}"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--repo", type=Path, default=REPO_ROOT)
    ap.add_argument("--ref", default="HEAD")
    ap.add_argument("--since")
    ap.add_argument("--until")
    ap.add_argument("--runs-json", type=Path)
    ap.add_argument(
        "--restart-log",
        type=Path,
        help="restart-diagnostics log; attributes each backend stop to its deploy run (needs --runs-json)",
    )
    ap.add_argument("--format", choices=("json", "text"), default="text")
    args = ap.parse_args(argv)
    if args.restart_log and not args.runs_json:
        print("deploy_trigger_audit: --restart-log needs --runs-json", file=sys.stderr)
        return 2
    try:
        report = audit(args.repo, args.ref, args.since, args.until)
        if args.runs_json:
            report["deploy_runs"] = tally_runs(
                args.runs_json, args.since, args.until, report["commits"]
            )
        if args.restart_log:
            if str(REPO_ROOT) not in sys.path:
                sys.path.insert(0, str(REPO_ROOT))
            from scripts import backend_restart_report as brr

            parsed = brr.parse_log(args.restart_log.read_text(encoding="utf-8", errors="replace"))
            stops = [{"ts": s.ts, "kind": s.kind} for s in parsed["stops"]]
            # The commit behind a restart can predate the window by the deploy
            # lag (80-110 min), so classify commits from a day earlier.
            kinds = commit_kinds(args.repo, args.ref, _shift(args.since, -24), args.until)
            runs = json.loads(args.runs_json.read_text(encoding="utf-8"))
            report["restart_attribution"] = attribute_restarts(stops, runs, kinds)
            # Same fail-closed rule as the restart report: a masked or
            # unparseable lifecycle line can hide or merge a restart, so the
            # attribution is marked incomplete and the exit code is 3.
            bad = parsed["unparseable_relevant_lines"]
            report["restart_attribution"]["input"] = "incomplete" if bad else "complete"
            report["restart_attribution"]["unparseable_relevant_lines"] = bad
            report["restart_attribution"]["unparseable_relevant_kinds"] = parsed[
                "unparseable_relevant_kinds"
            ]
    except (OSError, RuntimeError, ValueError, yaml.YAMLError) as exc:
        print(f"deploy_trigger_audit: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2) if args.format == "json" else render_text(report))
    if report.get("restart_attribution", {}).get("input") == "incomplete":
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
