"""Decide whether a Deploy Production run may replace what is live (STAB-1).

The deploy job runs this from the WORKFLOW commit (never the target tree),
after a read-only SSH read of the box's last-successful-deploy commit and
BEFORE any production mutation ("Transfer tested release archive" and "Run
remote deploy script" come after it).  Exit 0 lets the run continue; exit 1
refuses it.  Every refusal prints a GitHub ``::error`` that names the values
it compared and how to retry.

Three questions, asked in this order:

1. **Is this run stale?**  On a run's FIRST attempt, a run created more than
   ``MAX_QUEUE_AGE`` before it reached this guard is refused: a deploy that
   sat queued that long is not the deploy anyone intended, because production
   may have moved in the meantime.  Two runs sat ``queued`` for months
   (32212914036, a 2026-08-19 dispatch of a commit not in main's history, and
   43096180672, a 2026-11-11 push); either could have started at any moment.
   A re-run (``run_attempt > 1``) is an explicit human action and is exempt.
   An unreadable or implausible creation time fails CLOSED.

   The bound is measured, not guessed.  Over the 85 Deploy Production runs of
   2026-11-06..19 that reached this guard, creation -> guard took 17-136 min
   (median ~21 min after the 2026-11-07 hard-gate sharding, worst 79 min after
   it, 136 min before it, both while queued behind another deploy).  Six hours
   is 2.6x the worst observation and still refuses anything that waited a day,
   let alone months.

2. **Is rollback intent legitimate?**  ``allow_non_fast_forward=true`` is a
   compare-and-swap: it is honoured only on a ``workflow_dispatch`` (a push can
   never carry rollback intent) and only when ``expected_live_sha`` equals the
   commit the box records as live right now.  A rollback requested against a
   production state that has since changed is therefore refused instead of
   reversing whatever shipped in between.

3. **Does the deploy move production forward?**  Same commit or a descendant
   passes; going backwards or sideways is refused unless (2) authorised it.
   No recorded baseline (a first deploy) passes, as it always has.

The box's state file is read in one of five states (``baseline_state``), and
only two of them let a deploy proceed without a verified baseline question:

* ``absent``    -- the file does not exist: a first deploy or a fresh host.
                   Passes, as before.
* ``ok``        -- the file holds a full 40-hex commit: (2) and (3) apply.
* ``empty``     -- the file EXISTS but holds nothing (or only whitespace).
                   That is what an interrupted ``printf > file`` leaves, not a
                   first deploy: refused, or any target would ship.
* ``malformed`` -- the file holds something that is not a full commit SHA.
                   Refused.
* ``failed``    -- the read itself failed (SSH error, unreadable file,
                   unrecognised output).  Refused.
"""

from __future__ import annotations

import argparse
import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

_SHA = re.compile(r"[0-9a-f]{40}")

#: Longest a first attempt may take from creation to this guard.  See the
#: module docstring for the measurement behind it.
MAX_QUEUE_AGE = timedelta(hours=6)

#: How far in the FUTURE a creation time may sit (runner vs API clock skew)
#: before it is treated as unreadable rather than as a fresh run.
CLOCK_SKEW_TOLERANCE = timedelta(minutes=10)

_LIVE_SHA_HELP = (
    "Read the live commit from GET <PROD_PUBLIC_URL>/api/status -> build.commit "
    "(or the 'In production:' line this guard prints)"
)


@dataclass(frozen=True)
class GuardInputs:
    """Everything the decision depends on, as the workflow hands it over."""

    target: str
    live: str
    event: str
    run_attempt: str
    run_created_at: str
    allow_non_fast_forward: str
    expected_live_sha: str
    now: datetime
    max_queue_age: timedelta = MAX_QUEUE_AGE
    #: What the remote read of the box's deploy-state file reported:
    #: ``absent`` (no such file), ``present`` (the file exists; ``live`` is its
    #: whitespace-stripped contents, possibly empty) or ``failed``.  The
    #: default is the fail-closed one: an empty ``live`` the caller did not
    #: declare absent is an EMPTY file, never "no baseline".
    live_read: str = "present"
    #: The state file's path on the box, for messages only.
    live_file: str = ""


@dataclass
class Verdict:
    allowed: bool = True
    lines: list[str] = field(default_factory=list)

    def say(self, line: str) -> None:
        self.lines.append(line)

    def refuse(self, title: str, message: str) -> Verdict:
        self.lines.append(f"::error title={title}::{message}")
        self.allowed = False
        return self


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )


def _is_commit(repo: Path, sha: str) -> bool:
    return (
        bool(_SHA.fullmatch(sha))
        and _git(repo, "cat-file", "-e", f"{sha}^{{commit}}").returncode == 0
    )


def _is_ancestor(repo: Path, older: str, newer: str) -> bool:
    return _git(repo, "merge-base", "--is-ancestor", older, newer).returncode == 0


def _log(repo: Path, rng: str, prefix: str) -> list[str]:
    out = _git(repo, "log", "--oneline", "--no-decorate", rng).stdout
    return [f"  {prefix}: {line}" for line in out.splitlines() if line.strip()]


#: ``--live-read`` values, as the workflow's remote read reports them.
LIVE_READS = ("absent", "present", "failed")


def baseline_state(live_read: str, live: str) -> str:
    """Name the box's state-file state: absent / empty / malformed / ok / failed.

    Only ``absent`` means "no baseline".  A read that contradicts itself (an
    ``absent`` file with contents) or an unknown read value is ``failed``.
    """
    contents = live.strip().lower()
    if live_read == "absent":
        return "failed" if contents else "absent"
    if live_read != "present":
        return "failed"
    if not contents:
        return "empty"
    return "ok" if _SHA.fullmatch(contents) else "malformed"


def _parse_flag(raw: str) -> bool | None:
    value = raw.strip().lower()
    if value in ("", "false"):
        return False
    if value == "true":
        return True
    return None


def _parse_time(raw: str) -> datetime | None:
    value = raw.strip()
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _fmt_age(age: timedelta) -> str:
    minutes = int(age.total_seconds() // 60)
    days, rem = divmod(minutes, 24 * 60)
    hours, mins = divmod(rem, 60)
    return f"{days}d {hours}h {mins}m" if days else f"{hours}h {mins}m"


def _check_queue_age(inputs: GuardInputs, verdict: Verdict) -> bool:
    attempt_raw = inputs.run_attempt.strip()
    if not attempt_raw.isdigit() or int(attempt_raw) < 1:
        verdict.refuse(
            "Cannot verify run freshness",
            f"run_attempt is {attempt_raw or '<empty>'!r}, not a positive integer; failing closed.",
        )
        return False
    attempt = int(attempt_raw)
    if attempt > 1:
        verdict.say(
            f"::notice title=Re-run attempt::run_attempt={attempt}: the stale-queue check is exempt "
            "(a re-run is an explicit human action)."
        )
        return True

    created = _parse_time(inputs.run_created_at)
    if created is None:
        verdict.refuse(
            "Cannot verify run freshness",
            f"this run's creation time could not be read (got {inputs.run_created_at.strip() or '<empty>'!r}); "
            "failing closed rather than risk deploying a long-queued run. Re-run the job (a re-run attempt "
            "is exempt and needs no API read) or start a fresh deploy.",
        )
        return False
    age = inputs.now - created
    if age < -CLOCK_SKEW_TOLERANCE:
        verdict.refuse(
            "Cannot verify run freshness",
            f"run created_at {created.isoformat()} is {_fmt_age(-age)} in the future of the runner clock "
            f"({inputs.now.isoformat()}); failing closed.",
        )
        return False
    if age > inputs.max_queue_age:
        verdict.refuse(
            "Stale queued deploy refused",
            f"this run was created {created.isoformat()} and reached the deploy guard {_fmt_age(age)} later "
            f"(bound {_fmt_age(inputs.max_queue_age)}). A deploy that sat queued this long is not the deploy "
            "anyone intended: production may have moved since. Start a fresh deploy (push, or workflow_dispatch "
            "of the ref you want now); if this exact run really is still wanted, re-run it (re-run attempts are "
            "exempt).",
        )
        return False
    verdict.say(
        f"Run created {created.isoformat()}; reached the guard after {_fmt_age(max(age, timedelta(0)))}."
    )
    return True


def _check_rollback_intent(inputs: GuardInputs, verdict: Verdict, live: str) -> bool | None:
    """Return the authorised rollback flag, or None when refused."""
    flag = _parse_flag(inputs.allow_non_fast_forward)
    if flag is None:
        verdict.refuse(
            "Invalid rollback flag",
            f"allow_non_fast_forward is {inputs.allow_non_fast_forward!r}; expected true or false.",
        )
        return None
    if not flag:
        return False
    if inputs.event != "workflow_dispatch":
        verdict.refuse(
            "Rollback intent on a non-dispatch run",
            f"allow_non_fast_forward=true on a '{inputs.event}' run. Only a workflow_dispatch can authorise "
            "moving production backwards or sideways; a push never carries rollback intent.",
        )
        return None
    expected_raw = inputs.expected_live_sha.strip()
    expected = expected_raw.lower()
    if not expected_raw:
        verdict.refuse(
            "Rollback needs expected_live_sha",
            "allow_non_fast_forward=true requires expected_live_sha: the full 40-hex commit production is "
            f"running now (production records {live or '<none>'}). {_LIVE_SHA_HELP}, then re-dispatch with both "
            "inputs.",
        )
        return None
    if not _SHA.fullmatch(expected):
        verdict.refuse(
            "Malformed expected_live_sha",
            f"expected_live_sha={expected_raw!r} is not a full 40-hex commit SHA (abbreviations are refused). "
            f"Production records {live or '<none>'}. {_LIVE_SHA_HELP}.",
        )
        return None
    if not live:
        verdict.refuse(
            "Rollback has no live commit to compare",
            f"expected_live_sha={expected} but the box records no last-successful-deploy commit, so the "
            "compare-and-swap cannot be verified. With no baseline the ancestry check does not apply: "
            "re-dispatch with allow_non_fast_forward=false, or roll back on the box with deploy/rollback.sh.",
        )
        return None
    if expected != live:
        verdict.refuse(
            "Production moved since this rollback was requested",
            f"expected_live_sha={expected} but production records {live}. The rollback was authorised against "
            f"a production state that is no longer live. {_LIVE_SHA_HELP}; if the rollback is still intended, "
            "re-dispatch with expected_live_sha set to that value.",
        )
        return None
    verdict.say(
        f"::notice title=Rollback authorised::expected_live_sha matches production ({live})."
    )
    return True


def decide(inputs: GuardInputs, repo: Path) -> Verdict:
    verdict = Verdict()
    target = inputs.target.strip().lower()
    live = inputs.live.strip().lower()
    if not _SHA.fullmatch(target):
        return verdict.refuse(
            "No resolved deploy target", f"deploy target {inputs.target!r} is not a full SHA."
        )
    state = baseline_state(inputs.live_read, inputs.live)
    state_file = inputs.live_file.strip() or "the last-successful-deploy commit file"
    verdict.say(f"Deploying:      {target}")
    verdict.say(f"In production:  {live or '<none recorded>'} (state file: {state})")

    if not _check_queue_age(inputs, verdict):
        return verdict
    if state == "failed":
        return verdict.refuse(
            "Cannot read the production baseline",
            f"the SSH read of {state_file} failed or returned output that is not a recognised file state, "
            "so whether this deploy moves production forward cannot be checked; failing closed. Re-run the job.",
        )
    if state == "empty":
        return verdict.refuse(
            "Empty deploy baseline",
            f"{state_file} exists on the box but is empty (or whitespace only), so the commit production is "
            "running is unknown. An empty state file is not a first deploy (that is an ABSENT file): it is what "
            "an interrupted write leaves, and reading it as 'no baseline' would let any target ship. Failing "
            f"closed. Write the live commit into the file on the box ({_LIVE_SHA_HELP}), or delete the file only "
            "if this host has never completed a deploy.",
        )
    if state == "malformed":
        return verdict.refuse(
            "Unreadable deploy baseline",
            f"{state_file} records {live!r} as the last-successful-deploy commit, which is not a full SHA, so no "
            "deploy direction (and no rollback compare-and-swap) can be verified. Repair the state file on the "
            "box, or roll back there with deploy/rollback.sh.",
        )
    rollback = _check_rollback_intent(inputs, verdict, live)
    if rollback is None:
        return verdict

    if not live:
        verdict.say(
            "::notice title=No deploy baseline::No last-successful-deploy commit recorded; skipping the "
            "ancestry check. This is expected on a first deploy."
        )
        return verdict

    if not _is_commit(repo, live):
        message = (
            f"The recorded production commit {live} is not in this repository -- history may have been "
            "rewritten. Cannot verify the deploy moves forward."
        )
        if rollback:
            verdict.say(
                f"::warning title=Baseline commit not found::{message} Proceeding: rollback authorised."
            )
            return verdict
        return verdict.refuse(
            "Cannot verify deploy safety",
            f"{message} If this is intentional, re-dispatch with allow_non_fast_forward=true and "
            f"expected_live_sha={live}.",
        )

    if not _is_commit(repo, target):
        return verdict.refuse("Target missing", f"{target} is not a commit in this clone.")

    if live == target:
        verdict.say("::notice title=Redeploy::Already at this commit; redeploying the same tree.")
        return verdict

    if _is_ancestor(repo, live, target):
        ahead = _git(repo, "rev-list", "--count", f"{live}..{target}").stdout.strip()
        verdict.say(
            f"::notice title=Fast-forward deploy::Moving production forward by {ahead} commit(s)."
        )
        # Name them, so a cancelled middle deploy is visibly carried rather
        # than merely assumed to be.
        verdict.lines.extend(_log(repo, f"{live}..{target}", "shipping"))
        return verdict

    if _is_ancestor(repo, target, live):
        behind = _git(repo, "rev-list", "--count", f"{target}..{live}").stdout.strip()
        reason = f"this would move production BACKWARDS by {behind} commit(s), un-shipping code that is already live"
    else:
        reason = (
            "the deploy ref and the live commit have DIVERGED (neither is an ancestor of the other) -- likely a "
            "force-push or an unrelated ref"
        )
    verdict.say("Commits that would be lost from production:")
    verdict.lines.extend(_log(repo, f"{target}..{live}", "dropping"))

    if rollback:
        verdict.say(
            f"::warning title=Non-fast-forward deploy::{reason}. Proceeding: rollback authorised."
        )
        return verdict
    return verdict.refuse(
        "Deploy would skip or reverse shipped code",
        f"{reason}. If this is an intentional rollback, re-run via workflow_dispatch with "
        f"allow_non_fast_forward=true and expected_live_sha={live}.",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument(
        "--target", required=True, help="the resolved full commit SHA being deployed"
    )
    parser.add_argument(
        "--live", default="", help="the box's state-file contents, whitespace-stripped"
    )
    parser.add_argument(
        "--live-read",
        choices=LIVE_READS,
        default="present",
        help="what the remote read reported: the file is absent, present (--live is its contents, "
        "possibly empty), or the read failed.  Only 'absent' means no baseline.",
    )
    parser.add_argument(
        "--live-file", default="", help="the state file's path on the box (messages only)"
    )
    parser.add_argument("--event", required=True, help="github.event_name")
    parser.add_argument("--run-attempt", required=True, help="github.run_attempt")
    parser.add_argument(
        "--run-created-at", default="", help="the run's created_at (ISO 8601); '' if unreadable"
    )
    parser.add_argument("--allow-non-fast-forward", default="false")
    parser.add_argument("--expected-live-sha", default="")
    parser.add_argument("--now", default="", help="override the clock (ISO 8601, tests only)")
    parser.add_argument(
        "--max-queue-age-hours", type=float, default=MAX_QUEUE_AGE.total_seconds() / 3600
    )
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)

    now = _parse_time(args.now) if args.now else datetime.now(timezone.utc)
    if now is None:
        parser.error(f"--now {args.now!r} is not an ISO 8601 time with a timezone")
    verdict = decide(
        GuardInputs(
            target=args.target,
            live=args.live,
            event=args.event,
            run_attempt=args.run_attempt,
            run_created_at=args.run_created_at,
            allow_non_fast_forward=args.allow_non_fast_forward,
            expected_live_sha=args.expected_live_sha,
            now=now,
            max_queue_age=timedelta(hours=args.max_queue_age_hours),
            live_read=args.live_read,
            live_file=args.live_file,
        ),
        args.repo,
    )
    for line in verdict.lines:
        print(line)
    return 0 if verdict.allowed else 1


if __name__ == "__main__":
    raise SystemExit(main())
