#!/usr/bin/env python3
# Usage (PowerShell):
# python .\codex_loop.py --repo . --config .\codex_loop_config.example.json --agent-command "codex exec --full-auto -" --max-iters 6

from __future__ import annotations
import argparse, dataclasses, datetime as dt, json, hashlib, os, re, shlex, subprocess, sys, textwrap
from pathlib import Path
from typing import Any

JSON_START = "===AUDIT_JSON_START==="
JSON_END = "===AUDIT_JSON_END==="

@dataclasses.dataclass
class CommandResult:
    command: str
    returncode: int
    stdout: str
    stderr: str
    started_at: str
    finished_at: str

def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")

def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")

def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()

def file_hash(path: Path) -> str:
    return sha256_text(read_text(path)) if path.exists() else ""

def shorten(text: str, limit: int = 5000) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    head = text[: limit // 2]
    tail = text[-limit // 2 :]
    return f"{head}\n\n... [truncated] ...\n\n{tail}"

def shell_join(parts: list[str]) -> str:
    if os.name == "nt":
        return subprocess.list2cmdline(parts)
    return " ".join(shlex.quote(p) for p in parts)

def split_command(command: str) -> list[str]:
    return shlex.split(command, posix=(os.name != "nt"))

def has_shell_operators(command: str) -> bool:
    # Keep this conservative: if present, use shell=True for that command.
    return bool(re.search(r"[|&;<>()`]", command))

def run_command(command: str | list[str], cwd: Path, stdin_text: str | None = None, timeout: int = 1800, shell: bool | None = None) -> CommandResult:
    if shell is None:
        shell = isinstance(command, str)
    resolved = command if isinstance(command, str) else shell_join(command)
    started = utc_now()
    proc = subprocess.run(
        command,
        cwd=str(cwd),
        input=stdin_text,
        text=True,
        capture_output=True,
        shell=shell,
        timeout=timeout,
    )
    return CommandResult(resolved, proc.returncode, proc.stdout, proc.stderr, started, utc_now())

def is_codex_exec_command(argv: list[str]) -> bool:
    if len(argv) < 2:
        return False
    exe = Path(str(argv[0]).strip('"')).name.lower()
    return exe in {"codex", "codex.exe"} and str(argv[1]).lower() == "exec"

def _argv_has_option(argv: list[str], opt: str) -> bool:
    for a in argv:
        if a == opt or a.startswith(opt + "="):
            return True
    return False

def codex_exec_has_prompt_token(argv: list[str]) -> bool:
    if not is_codex_exec_command(argv):
        return False
    # codex exec prompt token is positional; "-" means read prompt from stdin.
    # Skip values for known options that consume a following token.
    takes_value = {
        "-C", "--cd", "-m", "--model", "--config", "--profile",
        "--output-schema", "--output-last-message-file", "--output-json",
        "--sandbox", "--approval-mode",
    }
    need_value = False
    for token in argv[2:]:
        t = str(token)
        if need_value:
            need_value = False
            continue
        if t == "-":
            return True
        if t == "--":
            return True
        if t in takes_value:
            need_value = True
            continue
        if t.startswith("--") and "=" in t:
            continue
        if t.startswith("-"):
            continue
        return True
    return False

def resolve_agent_argv(base_argv: list[str], *, audit_mode: bool = False, audit_schema_path: Path | None = None, audit_output_path: Path | None = None) -> tuple[list[str], dict[str, Any]]:
    argv = list(base_argv)
    info: dict[str, Any] = {
        "is_codex_exec": is_codex_exec_command(argv),
        "codex_prompt_appended": False,
        "schema_mode": False,
    }
    if info["is_codex_exec"] and not codex_exec_has_prompt_token(argv):
        argv.append("-")
        info["codex_prompt_appended"] = True

    if info["is_codex_exec"] and audit_mode and audit_schema_path is not None:
        if not _argv_has_option(argv, "--output-schema"):
            argv.extend(["--output-schema", str(audit_schema_path)])
            info["schema_mode"] = True
        if audit_output_path is not None and not _argv_has_option(argv, "--output-last-message-file"):
            argv.extend(["--output-last-message-file", str(audit_output_path)])
            info["schema_mode"] = True
    return argv, info

def command_consumes_stdin(argv: list[str]) -> bool:
    if is_codex_exec_command(argv):
        return "-" in argv
    return True

def try_git(repo: Path, args: list[str]) -> CommandResult | None:
    try:
        return run_command(["git", *args], cwd=repo, timeout=120, shell=False)
    except Exception:
        return None

def git_available(repo: Path) -> bool:
    r = try_git(repo, ["rev-parse", "--is-inside-work-tree"])
    return bool(r and r.returncode == 0 and "true" in r.stdout.lower())

def snapshot_hashes(repo: Path, files: list[str]) -> dict[str, str]:
    return {rel: file_hash(repo / rel) for rel in files}

def changed_files_from_hashes(before: dict[str, str], after: dict[str, str]) -> list[str]:
    return [k for k in sorted(set(before) | set(after)) if before.get(k, "") != after.get(k, "")]

def summarize_validations(results: list[dict[str, Any]]) -> str:
    lines = []
    for i, r in enumerate(results, start=1):
        status = "PASS" if r["returncode"] == 0 else "FAIL"
        lines.append(f"{i}. {status} :: {r['command']}")
        if r.get("stdout"):
            lines.append("stdout:")
            lines.append(shorten(r["stdout"], 1500))
        if r.get("stderr"):
            lines.append("stderr:")
            lines.append(shorten(r["stderr"], 1500))
    return "\n".join(lines).strip()

def load_config(path: Path) -> dict[str, Any]:
    return json.loads(read_text(path))

AUDIT_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["status", "score", "summary", "issues", "satisfied_when"],
    "properties": {
        "status": {"type": "string", "enum": ["satisfied", "not_satisfied"]},
        "score": {"type": "number"},
        "summary": {"type": "string"},
        "issues": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["severity", "title", "file", "evidence", "why_it_matters", "exact_fix"],
                "properties": {
                    "severity": {"type": "string", "enum": ["critical", "high", "medium", "low"]},
                    "title": {"type": "string"},
                    "file": {"type": "string"},
                    "evidence": {"type": "string"},
                    "why_it_matters": {"type": "string"},
                    "exact_fix": {"type": "string"},
                },
            },
        },
        "satisfied_when": {"type": "array", "items": {"type": "string"}},
    },
}

def write_audit_schema(path: Path) -> None:
    write_text(path, json.dumps(AUDIT_JSON_SCHEMA, indent=2))

def extract_audit_json(text: str) -> dict[str, Any] | None:
    pat = re.compile(re.escape(JSON_START) + r"\s*(\{.*?\})\s*" + re.escape(JSON_END), re.DOTALL)
    m = pat.search(text or "")
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return None

def extract_json_object(text: str) -> dict[str, Any] | None:
    raw = (text or "").strip()
    if not raw:
        return None
    try:
        obj = json.loads(raw)
        return obj if isinstance(obj, dict) else None
    except Exception:
        pass
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    candidate = raw[start : end + 1]
    try:
        obj = json.loads(candidate)
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None

def normalize_audit(audit: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(audit, dict):
        return None
    status = str(audit.get("status", "")).lower()
    if status not in {"satisfied", "not_satisfied"}:
        status = "not_satisfied"
    score_raw = audit.get("score", 0)
    try:
        score = float(score_raw)
    except Exception:
        score = 0.0
    summary = str(audit.get("summary", "") or "").strip()
    issues_in = audit.get("issues")
    issues: list[dict[str, Any]] = []
    if isinstance(issues_in, list):
        for item in issues_in:
            if not isinstance(item, dict):
                continue
            sev = str(item.get("severity", "medium")).lower()
            if sev not in {"critical", "high", "medium", "low"}:
                sev = "medium"
            issues.append({
                "severity": sev,
                "title": str(item.get("title", "") or ""),
                "file": str(item.get("file", "") or ""),
                "evidence": str(item.get("evidence", "") or ""),
                "why_it_matters": str(item.get("why_it_matters", "") or ""),
                "exact_fix": str(item.get("exact_fix", "") or ""),
            })
    satisfied_when_in = audit.get("satisfied_when")
    satisfied_when = [str(x) for x in satisfied_when_in] if isinstance(satisfied_when_in, list) else []
    return {
        "status": status,
        "score": score,
        "summary": summary,
        "issues": issues,
        "satisfied_when": satisfied_when,
    }

def compact_issue_list(issues: list[dict[str, Any]], max_items: int = 10) -> str:
    if not issues:
        return "None."
    lines = []
    for idx, issue in enumerate(issues[:max_items], start=1):
        lines.append(f"{idx}. [{issue.get('severity','unknown')}] {issue.get('title','Untitled issue')}")
        if issue.get("why_it_matters"):
            lines.append(f"   Why: {issue['why_it_matters']}")
        if issue.get("exact_fix"):
            lines.append(f"   Fix: {issue['exact_fix']}")
    if len(issues) > max_items:
        lines.append(f"... and {len(issues) - max_items} more")
    return "\n".join(lines)

def build_implement_prompt(goal: str, files: list[str], rules: list[str], previous_findings: list[dict[str, Any]], validation_summary: str, iteration: int) -> str:
    files_block = "\n".join(f"- {x}" for x in files)
    rules_block = "\n".join(f"- {x}" for x in rules) if rules else "- Keep changes targeted."
    findings_block = compact_issue_list(previous_findings) if previous_findings else "None."
    return textwrap.dedent(f'''
    You are operating inside a local code repository.

    Objective:
    {goal}

    Iteration:
    {iteration}

    Allowed target files:
    {files_block}

    Ground rules:
    {rules_block}

    Remaining findings from the last audit:
    {findings_block}

    Latest validation results:
    {validation_summary or "No validations have been run yet."}

    Instructions:
    1. Modify the repository directly.
    2. Keep changes tightly scoped to the objective.
    3. Remove contradictory or duplicate live logic where appropriate.
    4. Do not stop at helper functions; ensure the real active code path is fixed.
    5. If a change would be unsafe, do the smallest safe version that advances the objective.
    6. When done, print a short summary of what you changed.

    Do not return an audit report here. Implement only.
    ''').strip() + "\n"

def build_audit_prompt(goal: str, files: list[str], audit_requirements: list[str], validation_summary: str, iteration: int) -> str:
    files_block = "\n".join(f"- {x}" for x in files)
    reqs_block = "\n".join(f"- {x}" for x in audit_requirements) if audit_requirements else "- Audit the real live path."
    example = {
        "status": "not_satisfied",
        "score": 72,
        "summary": "Brief overall verdict.",
        "issues": [{
            "severity": "high",
            "title": "Example issue",
            "file": "index.html",
            "evidence": "function buildX still renders raw values from pData",
            "why_it_matters": "Breaks canonical value display",
            "exact_fix": "Route table cell rendering through canonical siteDetails path"
        }],
        "satisfied_when": [
            "All validation commands pass",
            "No high-severity issues remain",
            "Live path matches intended architecture"
        ]
    }
    return textwrap.dedent(f'''
    Audit this repository without modifying files.

    Objective being audited:
    {goal}

    Iteration:
    {iteration}

    Files to inspect first:
    {files_block}

    Audit requirements:
    {reqs_block}

    Latest validation results:
    {validation_summary or "No validations have been run yet."}

    Instructions:
    1. Trace the real active code path, not helper names.
    2. Be skeptical about dead code, duplicate logic, old branches, and UI/backend drift.
    3. Return ONLY structured JSON between the required markers.
    4. Use status="satisfied" only if the repository is genuinely done for this objective.
    5. If any material issue remains, status must be "not_satisfied".
    6. Use severity values: critical, high, medium, low.

    Required output format:
    {JSON_START}
    {json.dumps(example, indent=2)}
    {JSON_END}
    ''').strip() + "\n"

def run_validations(repo: Path, commands: list[str], timeout_each: int = 1800) -> list[dict[str, Any]]:
    results = []
    for cmd in commands:
        if has_shell_operators(cmd):
            r = run_command(cmd, cwd=repo, timeout=timeout_each, shell=True)
        else:
            r = run_command(split_command(cmd), cwd=repo, timeout=timeout_each, shell=False)
        results.append(dataclasses.asdict(r))
    return results

def has_blocking_issues(audit: dict[str, Any], allow_medium: bool = False) -> bool:
    levels = {"critical", "high"} | (set() if allow_medium else {"medium"})
    return any(str(i.get("severity","")).lower() in levels for i in (audit.get("issues") or []))

def build_run_summary(
    iteration: int,
    changed_files: list[str],
    validations: list[dict[str, Any]],
    audit: dict[str, Any] | None,
    *,
    implement_stdin_consumed: bool,
    implement_command: str,
    audit_command: str,
    audit_parse_source: str,
    no_change_streak: int,
    identical_audit_streak: int,
) -> str:
    lines = [f"Iteration {iteration}"]
    lines.append(f"Implement stdin consumed: {'yes' if implement_stdin_consumed else 'no'}")
    lines.append(f"Implement command: {implement_command}")
    lines.append(f"Audit command: {audit_command}")
    lines.append(f"Audit parse: {audit_parse_source}")
    lines.append("Changed files: " + (", ".join(changed_files) if changed_files else "none detected"))
    if no_change_streak >= 2:
        lines.append(f"No-op loop warning: no file changes for {no_change_streak} consecutive iterations")
    if identical_audit_streak >= 2:
        lines.append(f"Repeated audit warning: identical audit output for {identical_audit_streak} consecutive iterations")
    if validations:
        passed = sum(1 for r in validations if r["returncode"] == 0)
        lines.append(f"Validations: {passed}/{len(validations)} passed")
    if audit:
        lines.append(f"Audit status: {audit.get('status','unknown')}, score={audit.get('score','n/a')}")
        lines.append(f"Issues: {len(audit.get('issues') or [])}")
    return "\n".join(lines)

def default_unparseable_audit(reason: str, evidence: str) -> dict[str, Any]:
    return {
        "status": "not_satisfied",
        "score": 0,
        "summary": reason,
        "issues": [{
            "severity": "high",
            "title": "Unparseable audit output",
            "file": "",
            "evidence": evidence,
            "why_it_matters": "Loop cannot evaluate completion reliably.",
            "exact_fix": "Ensure audit mode returns valid JSON via schema or required markers.",
        }],
        "satisfied_when": ["Audit output is parseable and validations pass."],
    }

def main() -> int:
    ap = argparse.ArgumentParser(description="Loop an agent through implement -> validate -> audit until done.")
    ap.add_argument("--repo", required=True)
    ap.add_argument("--config", required=True)
    ap.add_argument("--agent-command", required=True, help='Shell command for your coding agent. Prompt is passed on stdin.')
    ap.add_argument("--max-iters", type=int, default=6)
    ap.add_argument("--timeout", type=int, default=1800)
    ap.add_argument("--allow-medium", action="store_true")
    ap.add_argument("--log-dir", default=".codex-loop")
    args = ap.parse_args()

    repo = Path(args.repo).expanduser().resolve()
    config = Path(args.config).expanduser().resolve()
    log_dir = (repo / args.log_dir).resolve()
    log_dir.mkdir(parents=True, exist_ok=True)

    cfg = load_config(config)
    goal = cfg["goal"].strip()
    files = cfg.get("files") or []
    implementation_rules = cfg.get("implementation_rules") or []
    audit_requirements = cfg.get("audit_requirements") or []
    validation_commands = cfg.get("validation_commands") or []

    if not repo.exists():
        print(f"Repository does not exist: {repo}", file=sys.stderr)
        return 2
    if not files:
        print("Config must include a non-empty 'files' list.", file=sys.stderr)
        return 2

    try:
        base_agent_argv = split_command(args.agent_command)
    except ValueError as e:
        print(f"Could not parse --agent-command: {e}", file=sys.stderr)
        return 2
    if not base_agent_argv:
        print("--agent-command resolved to empty argv.", file=sys.stderr)
        return 2

    meta = {
        "started_at": utc_now(),
        "repo": str(repo),
        "config": str(config),
        "agent_command": args.agent_command,
        "agent_argv": base_agent_argv,
        "git_available": git_available(repo),
        "files": files,
        "goal": goal,
    }
    write_text(log_dir / "run_meta.json", json.dumps(meta, indent=2))

    previous_findings = []
    last_validation_summary = ""
    no_change_streak = 0
    identical_audit_streak = 0
    previous_audit_fingerprint = ""

    for iteration in range(1, args.max_iters + 1):
        iter_dir = log_dir / f"iter_{iteration:02d}"
        iter_dir.mkdir(parents=True, exist_ok=True)

        before_hashes = snapshot_hashes(repo, files)

        impl_prompt = build_implement_prompt(goal, files, implementation_rules, previous_findings, last_validation_summary, iteration)
        write_text(iter_dir / "implement_prompt.txt", impl_prompt)
        impl_argv, impl_cmd_info = resolve_agent_argv(base_agent_argv, audit_mode=False)
        impl_result = run_command(impl_argv, cwd=repo, stdin_text=impl_prompt, timeout=args.timeout, shell=False)
        write_text(iter_dir / "implement_stdout.txt", impl_result.stdout)
        write_text(iter_dir / "implement_stderr.txt", impl_result.stderr)
        write_text(iter_dir / "implement_result.json", json.dumps(dataclasses.asdict(impl_result), indent=2))
        write_text(iter_dir / "implement_command.txt", shell_join(impl_argv) + "\n")
        write_text(iter_dir / "implement_diagnostics.json", json.dumps({
            "resolved_command": shell_join(impl_argv),
            "is_codex_exec": impl_cmd_info.get("is_codex_exec", False),
            "codex_prompt_appended": impl_cmd_info.get("codex_prompt_appended", False),
            "stdin_consumed": command_consumes_stdin(impl_argv),
        }, indent=2))

        after_hashes = snapshot_hashes(repo, files)
        changed_files = changed_files_from_hashes(before_hashes, after_hashes)
        no_change_streak = 0 if changed_files else (no_change_streak + 1)

        validations = run_validations(repo, validation_commands) if validation_commands else []
        write_text(iter_dir / "validations.json", json.dumps(validations, indent=2))
        last_validation_summary = summarize_validations(validations)

        audit_prompt = build_audit_prompt(goal, files, audit_requirements, last_validation_summary, iteration)
        write_text(iter_dir / "audit_prompt.txt", audit_prompt)
        audit_schema_path = iter_dir / "audit_schema.json"
        audit_output_path = iter_dir / "audit_structured_output.json"
        write_audit_schema(audit_schema_path)
        audit_argv, audit_cmd_info = resolve_agent_argv(
            base_agent_argv,
            audit_mode=True,
            audit_schema_path=audit_schema_path,
            audit_output_path=audit_output_path,
        )
        audit_result = run_command(audit_argv, cwd=repo, stdin_text=audit_prompt, timeout=args.timeout, shell=False)
        write_text(iter_dir / "audit_stdout.txt", audit_result.stdout)
        write_text(iter_dir / "audit_stderr.txt", audit_result.stderr)
        write_text(iter_dir / "audit_result.json", json.dumps(dataclasses.asdict(audit_result), indent=2))
        write_text(iter_dir / "audit_command.txt", shell_join(audit_argv) + "\n")

        audit_parse_source = "unparsed"
        audit = None

        if audit_output_path.exists():
            audit = normalize_audit(extract_json_object(read_text(audit_output_path)))
            if audit:
                audit_parse_source = "schema_file"
        if audit is None:
            audit = normalize_audit(extract_audit_json(audit_result.stdout))
            if audit:
                audit_parse_source = "markers"
        if audit is None:
            audit = normalize_audit(extract_json_object(audit_result.stdout))
            if audit:
                audit_parse_source = "stdout_json_fallback"

        schema_option_error = (
            "unknown option" in (audit_result.stderr or "").lower()
            or "unrecognized arguments" in (audit_result.stderr or "").lower()
            or "unexpected argument '--output-schema'" in (audit_result.stderr or "").lower()
        )
        if audit is None and audit_cmd_info.get("schema_mode") and schema_option_error:
            legacy_audit_argv, _ = resolve_agent_argv(base_agent_argv, audit_mode=False)
            legacy_result = run_command(legacy_audit_argv, cwd=repo, stdin_text=audit_prompt, timeout=args.timeout, shell=False)
            write_text(iter_dir / "audit_stdout_legacy.txt", legacy_result.stdout)
            write_text(iter_dir / "audit_stderr_legacy.txt", legacy_result.stderr)
            write_text(iter_dir / "audit_result_legacy.json", json.dumps(dataclasses.asdict(legacy_result), indent=2))
            audit = normalize_audit(extract_audit_json(legacy_result.stdout))
            if audit:
                audit_parse_source = "markers_legacy"
            else:
                audit = normalize_audit(extract_json_object(legacy_result.stdout))
                if audit:
                    audit_parse_source = "stdout_json_fallback_legacy"

        if audit is None:
            audit = default_unparseable_audit(
                "Audit JSON could not be parsed from agent output.",
                "Schema output file and marker/fallback parsing all failed.",
            )
            audit_parse_source = "default_unparseable"

        audit_fingerprint = sha256_text(json.dumps(audit, sort_keys=True))
        if previous_audit_fingerprint and audit_fingerprint == previous_audit_fingerprint:
            identical_audit_streak += 1
        else:
            identical_audit_streak = 1
        previous_audit_fingerprint = audit_fingerprint

        write_text(iter_dir / "audit_diagnostics.json", json.dumps({
            "resolved_command": shell_join(audit_argv),
            "is_codex_exec": audit_cmd_info.get("is_codex_exec", False),
            "codex_prompt_appended": audit_cmd_info.get("codex_prompt_appended", False),
            "schema_mode": audit_cmd_info.get("schema_mode", False),
            "stdin_consumed": command_consumes_stdin(audit_argv),
            "parse_source": audit_parse_source,
        }, indent=2))
        write_text(iter_dir / "audit.json", json.dumps(audit, indent=2))

        validation_failures = [r for r in validations if r["returncode"] != 0]
        satisfied = (
            str(audit.get("status", "")).lower() == "satisfied"
            and not validation_failures
            and not has_blocking_issues(audit, allow_medium=args.allow_medium)
        )

        summary = build_run_summary(
            iteration,
            changed_files,
            validations,
            audit,
            implement_stdin_consumed=command_consumes_stdin(impl_argv),
            implement_command=shell_join(impl_argv),
            audit_command=shell_join(audit_argv),
            audit_parse_source=audit_parse_source,
            no_change_streak=no_change_streak,
            identical_audit_streak=identical_audit_streak,
        )
        print(summary)
        write_text(iter_dir / "summary.txt", summary + "\n")

        if satisfied:
            final = {
                "finished_at": utc_now(),
                "status": "satisfied",
                "iteration": iteration,
                "summary": audit.get("summary", ""),
                "issues": audit.get("issues", []),
            }
            write_text(log_dir / "final_result.json", json.dumps(final, indent=2))
            print("\nDONE: repository reported satisfied state.")
            return 0

        if no_change_streak >= 2:
            final = {
                "finished_at": utc_now(),
                "status": "stalled_no_changes",
                "iteration": iteration,
                "summary": "No file changes detected for 2 consecutive iterations.",
                "last_findings": audit.get("issues", []),
                "audit_parse_source": audit_parse_source,
            }
            write_text(log_dir / "final_result.json", json.dumps(final, indent=2))
            print("\nSTOPPED: no-op loop detected (no file changes for 2 consecutive iterations).")
            return 1

        previous_findings = audit.get("issues") or []

    final = {
        "finished_at": utc_now(),
        "status": "max_iterations_reached",
        "iteration": args.max_iters,
        "summary": "Loop stopped at max iterations.",
        "last_findings": previous_findings,
    }
    write_text(log_dir / "final_result.json", json.dumps(final, indent=2))
    print("\nSTOPPED: max iterations reached before satisfied state.")
    return 1

if __name__ == "__main__":
    raise SystemExit(main())
