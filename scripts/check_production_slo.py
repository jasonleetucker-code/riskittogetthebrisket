#!/usr/bin/env python3
"""Production SLO check: code freshness, pipeline health, data freshness.

Run by ``.github/workflows/health-check.yml``.  Every threshold comes from
``config/ops/production_slo.json`` -- this file holds no threshold literal.

Why (audit remediation 2026-11-18): production went 63 h and then 31 h without
a successful deploy, 38 of the last 100 Deploy Production runs failed, and on
2026-11-17 the served board had 190 of its top-200 players freshness-low.
Nothing alerted on any of it.

Named results (code freshness and data freshness are kept separate):

* ``code_freshness.deploy_lag``       age of the oldest deploy-relevant ``main``
  commit not contained in the SHA production reports on ``/api/status``;
* ``code_freshness.deploy_failures``  consecutive failed Deploy Production runs
  / hours since the last success, while such commits are undeployed;
* ``pipeline.refresh``                hours since the last successful
  ``scheduled-refresh.yml`` run;
* ``data_freshness.*``                the ``freshness_slo`` block of
  ``/api/status`` (top-200 stale share, withheld share, board age) and
  ``data_freshness.private_sources`` (provisioned private sources past budget).

A rule that could not be measured is ``UNKNOWN`` -- never ``OK``.  Exit codes:
0 all measured and within budget, 1 at least one BREACH, 3 no breach but at
least one UNKNOWN (``--unknown-ok`` makes that 0).  Output carries measured
values and thresholds only: no token, no URL beyond the one given.

``--backtest-days N`` replays the code-freshness and pipeline rules over real
GitHub Actions / git history and prints alert-hours per rule.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = REPO_ROOT / "config" / "ops" / "production_slo.json"

OK = "OK"
BREACH = "BREACH"
UNKNOWN = "UNKNOWN"

CODE = "code_freshness"
PIPELINE = "pipeline"
DATA = "data_freshness"

_FAILED = frozenset({"failure", "timed_out", "startup_failure"})
_SUCCEEDED = frozenset({"success"})
_FULL_SHA = re.compile(r"^[0-9a-f]{40}$")


@dataclass(frozen=True)
class Result:
    rule: str
    category: str
    status: str
    measured: Any = None
    threshold: Any = None
    detail: str = ""

    def line(self) -> str:
        return (
            f"[{self.status}] {self.rule}: measured={self.measured} "
            f"threshold={self.threshold}" + (f" -- {self.detail}" if self.detail else "")
        )


@dataclass
class Snapshot:
    """Everything the rules read, as of ``now``.  Pure data: no IO."""

    now: datetime
    #: Commit timestamps of deploy-relevant ``main`` commits NOT in the deployed
    #: SHA; ``None`` when that could not be determined (never ``[]``).
    undeployed_relevant: list[datetime] | None = None
    #: Deploy Production runs ``{conclusion, updated_at}`` (any order).
    deploy_runs: list[Mapping[str, Any]] | None = None
    refresh_runs: list[Mapping[str, Any]] | None = None
    #: ``/api/status`` ``freshness_slo`` block (public numbers), or ``None``.
    freshness_slo: Mapping[str, Any] | None = None
    #: Whether the status endpoint itself answered.
    status_reachable: bool = True
    notes: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# time / run helpers
# --------------------------------------------------------------------------- #


def parse_ts(raw: Any) -> datetime | None:
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _hours(a: datetime, b: datetime) -> float:
    return (a - b).total_seconds() / 3600.0


def _completed(runs: Iterable[Mapping[str, Any]], now: datetime) -> list[tuple[datetime, str]]:
    """``(finished_at, conclusion)`` of runs finished at or before ``now``,
    oldest first.  Cancelled / skipped / in-progress runs say nothing about
    health and are excluded."""
    out: list[tuple[datetime, str]] = []
    for r in runs:
        conclusion = r.get("conclusion")
        if conclusion not in _FAILED and conclusion not in _SUCCEEDED:
            continue
        finished = parse_ts(r.get("updated_at") or r.get("run_started_at") or r.get("created_at"))
        if finished is None or finished > now:
            continue
        out.append((finished, str(conclusion)))
    out.sort(key=lambda x: x[0])
    return out


def last_success_and_failures(
    runs: Iterable[Mapping[str, Any]], now: datetime
) -> tuple[datetime | None, int]:
    """(time of the most recent success, consecutive failures since it)."""
    done = _completed(runs, now)
    last_success = None
    failures = 0
    for finished, conclusion in done:
        if conclusion in _SUCCEEDED:
            last_success, failures = finished, 0
        else:
            failures += 1
    return last_success, failures


# --------------------------------------------------------------------------- #
# rules (pure)
# --------------------------------------------------------------------------- #


def rule_deploy_lag(snap: Snapshot, cfg: Mapping[str, Any]) -> Result:
    name = "code_freshness.deploy_lag"
    limit = float(cfg["codeFreshness"]["deployLagMaxHours"])
    if snap.undeployed_relevant is None:
        return Result(
            name, CODE, UNKNOWN, None, limit, "deployed SHA / main history not determinable"
        )
    if not snap.undeployed_relevant:
        return Result(name, CODE, OK, 0.0, limit, "every deploy-relevant main commit is deployed")
    age = round(_hours(snap.now, min(snap.undeployed_relevant)), 2)
    status = BREACH if age > limit else OK
    detail = f"{len(snap.undeployed_relevant)} deploy-relevant commit(s) not in the deployed SHA; oldest is {age}h old"
    return Result(name, CODE, status, age, limit, detail)


def rule_deploy_failures(snap: Snapshot, cfg: Mapping[str, Any]) -> Result:
    name = "code_freshness.deploy_failures"
    c = cfg["codeFreshness"]["deployFailures"]
    max_fail = int(c["maxConsecutiveFailures"])
    max_hours = float(c["maxHoursSinceSuccessWithUndeployed"])
    if snap.deploy_runs is None or snap.undeployed_relevant is None:
        return Result(
            name, CODE, UNKNOWN, None, max_fail, "deploy run history or undeployed set unavailable"
        )
    if not snap.undeployed_relevant:
        return Result(name, CODE, OK, 0, max_fail, "nothing deploy-relevant is waiting")
    last_ok, failures = last_success_and_failures(snap.deploy_runs, snap.now)
    since = None if last_ok is None else round(_hours(snap.now, last_ok), 2)
    # BOTH must hold: a quick run of failures that recovered within hours is
    # normal here (38 of the last 100 deploys failed); repeated failure PLUS
    # a long gap since the last success is the incident.
    repeated = failures >= max_fail
    long_gap = since is None or since > max_hours
    reasons = []
    if repeated and long_gap:
        gap = (
            "no successful deploy in the history window"
            if since is None
            else f"{since}h since last success > {max_hours}h"
        )
        reasons.append(f"{failures} consecutive failed deploys >= {max_fail} and {gap}")
    status = BREACH if reasons else OK
    detail = "; ".join(reasons) or f"{failures} consecutive failure(s), last success {since}h ago"
    return Result(
        name,
        CODE,
        status,
        {"consecutiveFailures": failures, "hoursSinceSuccess": since},
        {"maxConsecutiveFailures": max_fail, "maxHoursSinceSuccess": max_hours},
        detail,
    )


def rule_refresh(snap: Snapshot, cfg: Mapping[str, Any]) -> Result:
    name = "pipeline.refresh"
    limit = float(cfg["refreshPipeline"]["maxHoursSinceSuccess"])
    if snap.refresh_runs is None:
        return Result(
            name, PIPELINE, UNKNOWN, None, limit, "scheduled-refresh run history unavailable"
        )
    last_ok, failures = last_success_and_failures(snap.refresh_runs, snap.now)
    if last_ok is None:
        return Result(
            name, PIPELINE, UNKNOWN, None, limit, "no successful refresh run in the history window"
        )
    since = round(_hours(snap.now, last_ok), 2)
    status = BREACH if since > limit else OK
    return Result(
        name,
        PIPELINE,
        status,
        since,
        limit,
        f"last successful scheduled refresh {since}h ago; {failures} failed run(s) since",
    )


def _share_rule(snap: Snapshot, key: str, limit: float, name: str, label: str) -> Result:
    if not snap.status_reachable:
        return Result(name, DATA, UNKNOWN, None, limit, "/api/status unreachable")
    slo = snap.freshness_slo
    if not isinstance(slo, Mapping):
        return Result(
            name,
            DATA,
            UNKNOWN,
            None,
            limit,
            "status_block_absent: /api/status has no freshness_slo block (deployed build predates it)",
        )
    value = slo.get(key)
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return Result(
            name, DATA, UNKNOWN, None, limit, f"{label} not measured (state={slo.get('state')})"
        )
    return Result(name, DATA, BREACH if value > limit else OK, value, limit, label)


def rule_top200_stale(snap: Snapshot, cfg: Mapping[str, Any]) -> Result:
    return _share_rule(
        snap,
        "top200StaleShare",
        float(cfg["dataFreshness"]["maxTop200StaleShare"]),
        "data_freshness.top200_stale_share",
        "share of top-200 ranked players with confidenceAxes.freshness low",
    )


def rule_withheld(snap: Snapshot, cfg: Mapping[str, Any]) -> Result:
    return _share_rule(
        snap,
        "pricedWithheldShare",
        float(cfg["dataFreshness"]["maxPricedWithheldShare"]),
        "data_freshness.priced_withheld_share",
        "share of priced assets withheld (quarantined or freshness low)",
    )


def rule_board_age(snap: Snapshot, cfg: Mapping[str, Any]) -> Result:
    return _share_rule(
        snap,
        "boardAgeHours",
        float(cfg["dataFreshness"]["maxBoardAgeHours"]),
        "data_freshness.board_age_hours",
        "hours since the served board's scrape timestamp",
    )


def rule_private_sources(snap: Snapshot, cfg: Mapping[str, Any]) -> Result:
    name = "data_freshness.private_sources"
    limit = int(cfg["dataFreshness"]["maxStalePrivateSources"])
    if not snap.status_reachable:
        return Result(name, DATA, UNKNOWN, None, limit, "/api/status unreachable")
    slo = snap.freshness_slo
    if not isinstance(slo, Mapping):
        return Result(
            name,
            DATA,
            UNKNOWN,
            None,
            limit,
            "status_block_absent: /api/status has no freshness_slo block",
        )
    stale, unknown = slo.get("privateSourcesStale"), slo.get("privateSourcesUnknown")
    if not isinstance(stale, int) or isinstance(stale, bool):
        return Result(name, DATA, UNKNOWN, None, limit, "private source staleness not measured")
    if stale > limit:
        return Result(
            name,
            DATA,
            BREACH,
            stale,
            limit,
            f"{stale} of {slo.get('privateSourcesProvisioned')} provisioned private source(s) "
            "past their fetch budget (names: admin diagnostics)",
        )
    if isinstance(unknown, int) and unknown > 0:
        return Result(
            name,
            DATA,
            UNKNOWN,
            stale,
            limit,
            f"{unknown} provisioned private source(s) unmeasurable",
        )
    return Result(name, DATA, OK, stale, limit, "")


RULES = (
    rule_deploy_lag,
    rule_deploy_failures,
    rule_refresh,
    rule_top200_stale,
    rule_withheld,
    rule_board_age,
    rule_private_sources,
)
HISTORY_RULES = (rule_deploy_lag, rule_deploy_failures, rule_refresh)


def evaluate(snap: Snapshot, cfg: Mapping[str, Any], rules: Sequence = RULES) -> list[Result]:
    return [r(snap, cfg) for r in rules]


def exit_code(results: Sequence[Result], unknown_ok: bool = False) -> int:
    if any(r.status == BREACH for r in results):
        return 1
    if any(r.status == UNKNOWN for r in results) and not unknown_ok:
        return 3
    return 0


def render(results: Sequence[Result], now: datetime) -> str:
    lines = [f"Production SLO report @ {now.strftime('%Y-%m-%dT%H:%MZ')}"]
    for cat in (CODE, PIPELINE, DATA):
        group = [r for r in results if r.category == cat]
        if group:
            lines.append(f"{cat}:")
            lines.extend("  " + r.line() for r in group)
    breached = [r.rule for r in results if r.status == BREACH]
    unknown = [r.rule for r in results if r.status == UNKNOWN]
    lines.append(f"BREACHED: {', '.join(breached) or 'none'}")
    lines.append(f"UNKNOWN: {', '.join(unknown) or 'none'}")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# deploy path classification (deploy.yml `paths-ignore` is the one source)
# --------------------------------------------------------------------------- #


def glob_to_regex(pattern: str) -> re.Pattern[str]:
    """GitHub Actions path glob: ``*`` stays inside a segment, ``**`` spans."""
    out, i = [], 0
    while i < len(pattern):
        ch = pattern[i]
        if pattern.startswith("**", i):
            out.append(".*")
            i += 2
            if pattern.startswith("/", i):
                i += 1
                out[-1] = "(?:.*/)?"
        elif ch == "*":
            out.append("[^/]*")
            i += 1
        elif ch == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(ch))
            i += 1
    return re.compile("^" + "".join(out) + "$")


def load_paths_ignore(workflow_path: Path) -> list[re.Pattern[str]]:
    import yaml  # PyYAML is a repo dependency

    doc = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
    triggers = doc.get("on", doc.get(True)) or {}
    patterns = ((triggers.get("push") or {}).get("paths-ignore")) or []
    return [glob_to_regex(str(p)) for p in patterns]


def commit_is_deploy_relevant(files: Sequence[str], ignore: Sequence[re.Pattern[str]]) -> bool:
    """A push starts a deploy unless EVERY changed file is ignored.  A commit
    whose file list is unknown/empty is treated as relevant (fail toward alert)."""
    if not files:
        return True
    return any(not any(p.match(f) for p in ignore) for f in files)


# --------------------------------------------------------------------------- #
# IO: git, GitHub REST, /api/status
# --------------------------------------------------------------------------- #


def _git(args: Sequence[str]) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO_ROOT, check=True, capture_output=True, text=True
    ).stdout


def git_commits_not_in(base_sha: str, head_ref: str) -> list[tuple[str, datetime, list[str]]]:
    """Commits reachable from ``head_ref`` but not from ``base_sha``:
    ``(sha, committer time, changed files)``.  Raises on an unknown base SHA."""
    _git(["cat-file", "-e", f"{base_sha}^{{commit}}"])
    marker = "\x1e"
    raw = _git(
        [
            "log",
            "--first-parent",
            "-m",
            "--name-only",
            f"--format={marker}%H %cI",
            f"{base_sha}..{head_ref}",
        ]
    )
    out = []
    for chunk in raw.split(marker):
        chunk = chunk.strip("\n")
        if not chunk:
            continue
        head, _, rest = chunk.partition("\n")
        sha, _, ts = head.partition(" ")
        when = parse_ts(ts)
        if when is None:
            continue
        out.append((sha, when, [f for f in rest.split("\n") if f.strip()]))
    return out


def undeployed_relevant_times(
    deployed_sha: str, head_ref: str, ignore: Sequence[re.Pattern[str]]
) -> list[datetime]:
    return [
        when
        for _sha, when, files in git_commits_not_in(deployed_sha, head_ref)
        if commit_is_deploy_relevant(files, ignore)
    ]


def gh_get(path: str, token: str | None) -> Any:
    if token:
        req = urllib.request.Request(
            "https://api.github.com/" + path.lstrip("/"),
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "production-slo-check",
            },
        )
        with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 - fixed https host
            return json.load(resp)
    return json.loads(
        subprocess.run(["gh", "api", path], check=True, capture_output=True, text=True).stdout
    )


def fetch_runs(
    repo: str, workflow: str, since: datetime, token: str | None, per_page: int = 100
) -> list[dict]:
    runs: list[dict] = []
    created = since.strftime("%Y-%m-%dT%H:%M:%SZ")
    for page in range(1, 30):
        data = gh_get(
            f"repos/{repo}/actions/workflows/{workflow}/runs?per_page={per_page}"
            f"&page={page}&created=%3E%3D{created}",
            token,
        )
        batch = data.get("workflow_runs") or []
        runs.extend(
            {
                k: r.get(k)
                for k in (
                    "id",
                    "event",
                    "status",
                    "conclusion",
                    "created_at",
                    "run_started_at",
                    "updated_at",
                    "head_sha",
                )
            }
            for r in batch
        )
        if len(batch) < per_page:
            break
    return runs


def fetch_status(base_url: str, timeout: float = 30.0) -> tuple[dict | None, str]:
    url = base_url.rstrip("/") + "/api/status"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310
            return json.load(resp), ""
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return None, f"{type(exc).__name__}"


# --------------------------------------------------------------------------- #
# live run
# --------------------------------------------------------------------------- #


def build_live_snapshot(args: argparse.Namespace, cfg: Mapping[str, Any]) -> Snapshot:
    now = datetime.now(timezone.utc)
    snap = Snapshot(now=now)
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    status, err = fetch_status(args.url) if args.url else (None, "no --url")
    snap.status_reachable = status is not None
    if status is None:
        snap.notes.append(f"/api/status unreachable ({err})")
    else:
        slo = status.get("freshness_slo")
        snap.freshness_slo = slo if isinstance(slo, Mapping) else None
        sha = (status.get("build") or {}).get("commit")
        if isinstance(sha, str) and _FULL_SHA.match(sha):
            try:
                ignore = load_paths_ignore(REPO_ROOT / cfg["deployPathsIgnoreFile"])
                snap.undeployed_relevant = undeployed_relevant_times(sha, args.head_ref, ignore)
            except (subprocess.CalledProcessError, OSError, ValueError) as exc:
                snap.notes.append(
                    f"deployed SHA not found in checkout history ({type(exc).__name__}); "
                    "fetch full history or the SHA was rewritten"
                )
        else:
            snap.notes.append("/api/status reports no deployed commit")
    since = now - timedelta(days=args.history_days)
    try:
        snap.deploy_runs = fetch_runs(
            cfg["repo"], cfg["deployWorkflow"], since, token, cfg["history"]["runsPerPage"]
        )
        snap.refresh_runs = fetch_runs(
            cfg["repo"], cfg["refreshWorkflow"], since, token, cfg["history"]["runsPerPage"]
        )
    except (urllib.error.URLError, OSError, subprocess.CalledProcessError, ValueError) as exc:
        snap.notes.append(f"GitHub run history unavailable ({type(exc).__name__})")
    return snap


# --------------------------------------------------------------------------- #
# backtest
# --------------------------------------------------------------------------- #


def backtest(
    cfg: Mapping[str, Any],
    days: int,
    head_ref: str,
    token: str | None,
    step_hours: float = 1.0,
    warmup_days: int = 4,
) -> dict[str, Any]:
    """Replay the history rules hourly over the last ``days`` days."""
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    start = now - timedelta(days=days)
    since = start - timedelta(days=warmup_days)
    deploys = fetch_runs(cfg["repo"], cfg["deployWorkflow"], since, token)
    refreshes = fetch_runs(cfg["repo"], cfg["refreshWorkflow"], since, token)
    ignore = load_paths_ignore(REPO_ROOT / cfg["deployPathsIgnoreFile"])
    cache: dict[str, list[tuple[datetime, bool]] | None] = {}

    def not_deployed(sha: str) -> list[tuple[datetime, bool]] | None:
        if sha not in cache:
            try:
                cache[sha] = [
                    (w, commit_is_deploy_relevant(f, ignore))
                    for _s, w, f in git_commits_not_in(sha, head_ref)
                ]
            except subprocess.CalledProcessError:
                cache[sha] = None  # SHA not in this history: UNKNOWN, never "deployed"
        return cache[sha]

    ok_deploys = sorted(
        (
            (parse_ts(r["updated_at"]), r["head_sha"])
            for r in deploys
            if r.get("conclusion") == "success"
        ),
        key=lambda x: x[0],
    )
    series: dict[str, list[tuple[datetime, str]]] = {}
    t = start
    while t <= now:
        deployed = None
        for finished, sha in ok_deploys:
            if finished <= t:
                deployed = sha
        undeployed = None
        pending = not_deployed(deployed) if deployed else None
        if pending is not None:
            undeployed = [w for w, rel in pending if rel and w <= t]
        snap = Snapshot(
            now=t, undeployed_relevant=undeployed, deploy_runs=deploys, refresh_runs=refreshes
        )
        for res in evaluate(snap, cfg, HISTORY_RULES):
            series.setdefault(res.rule, []).append((t, res.status))
        t += timedelta(hours=step_hours)
    summary: dict[str, Any] = {}
    for rule, pts in series.items():
        episodes, cur = [], None
        for ts, st in pts:
            if st == BREACH and cur is None:
                cur = [ts, ts]
            elif st == BREACH:
                cur[1] = ts
            elif cur is not None:
                episodes.append(tuple(cur))
                cur = None
        if cur is not None:
            episodes.append(tuple(cur))
        summary[rule] = {
            "alertHours": sum(1 for _t, s in pts if s == BREACH) * step_hours,
            "unknownHours": sum(1 for _t, s in pts if s == UNKNOWN) * step_hours,
            "totalHours": len(pts) * step_hours,
            "episodes": [
                (a.strftime("%m-%d %H:%M"), b.strftime("%m-%d %H:%M")) for a, b in episodes
            ],
        }
    return summary


def render_backtest(summary: Mapping[str, Any], days: int) -> str:
    lines = [
        f"Backtest over the last {days} days (hourly samples)",
        "| rule | alert-hours | episodes | unknown-hours |",
        "|---|---|---|---|",
    ]
    for rule, s in summary.items():
        eps = "; ".join(f"{a} -> {b}" for a, b in s["episodes"]) or "none"
        lines.append(
            f"| {rule} | {s['alertHours']:.0f} / {s['totalHours']:.0f} | {eps} | {s['unknownHours']:.0f} |"
        )
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    p.add_argument(
        "--url",
        default=os.environ.get("PROD_PUBLIC_URL", ""),
        help="production origin (default $PROD_PUBLIC_URL)",
    )
    p.add_argument("--head-ref", default="origin/main", help="ref holding main's history")
    p.add_argument("--history-days", type=int, default=7, help="run-history window for live checks")
    p.add_argument(
        "--backtest-days", type=int, default=0, help="replay history rules instead of checking"
    )
    p.add_argument("--report-json", type=Path, help="write machine-readable results here")
    p.add_argument("--unknown-ok", action="store_true", help="UNKNOWN results do not fail the run")
    return p.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    cfg = json.loads(args.config.read_text(encoding="utf-8"))
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if args.backtest_days:
        print(
            render_backtest(
                backtest(cfg, args.backtest_days, args.head_ref, token), args.backtest_days
            )
        )
        return 0
    snap = build_live_snapshot(args, cfg)
    results = evaluate(snap, cfg)
    print(render(results, snap.now))
    for note in snap.notes:
        print(f"note: {note}")
    if args.report_json:
        args.report_json.write_text(
            json.dumps(
                {
                    "checkedAt": snap.now.isoformat(),
                    "results": [r.__dict__ for r in results],
                    "breached": sorted(r.rule for r in results if r.status == BREACH),
                    "unknown": sorted(r.rule for r in results if r.status == UNKNOWN),
                    "notes": snap.notes,
                },
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )
    return exit_code(results, args.unknown_ok)


if __name__ == "__main__":
    sys.exit(main())
