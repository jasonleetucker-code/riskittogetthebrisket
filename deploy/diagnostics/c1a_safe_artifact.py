"""Runner-only bounded capture. Never log or persist unvalidated SSH output."""

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import threading

LIMIT = 65536
LIMITS = "snapshot_only;assumed_default_store_path;actual_store_configuration_unverified;no_process_fd_recovery;no_credential_separation_proof"
PATTERNS = (
    r"dlf\.journal\.state=(classified|empty|unavailable_or_incomplete|probe_failed|unavailable)",
    r"dlf\.journal\.unclassified=[0-9]{1,3}",
    r"dlf\.journal\.event[0-9]{1,3}\.timestampUs=[0-9]{1,20}",
    r"dlf\.journal\.event[0-9]{1,3}\.board=(all|dlfSf|dlfIdp|dlfRookieSf|dlfRookieIdp)",
    r"dlf\.journal\.event[0-9]{1,3}\.stage=(fetch_failed|reauth_failed|persistent_preview|row_floor|native_value_floor|preview_reauth|login_failed|empty_rows|wrote|wrapper_fetch_nonzero)",
    r"dlf\.journal\.event[0-9]{1,3}\.(nativeCount|parsedRows|requiredFloor)=[0-9]{1,6}",
    r"dlf\.identity\.wrapperCommand=(expected_direct|expected_bash_wrapper|other_or_unverified|unavailable)",
    r"dlf\.identity\.(wrapper|defaultFetcher)Sha256=[0-9a-f]{64}",
    r"dlf\.identity\.(wrapper|defaultFetcher)State=unavailable",
    r"dlf\.identity\.defaultRevision=([0-9a-f]{40}|unavailable)",
)


def validate(raw):
    if len(raw) > LIMIT or not raw.endswith(b"\n"):
        raise ValueError("invalid")
    lines = raw.decode("utf-8", errors="strict").splitlines()
    if (
        len(lines) > 1500
        or lines.count("scope=performance-safe") != 1
        or lines.count("limits=" + LIMITS) != 1
    ):
        raise ValueError("invalid")
    selected = {}
    for line in lines:
        if len(line) > 1024:
            raise ValueError("invalid")
        if any(re.fullmatch(pattern, line) for pattern in PATTERNS):
            key, value = line.split("=", 1)
            if key in selected:
                raise ValueError("duplicate")
            selected[key] = value
        elif re.fullmatch(
            r"(?:scope|timestamp|revision|host\.[A-Za-z]+|(?:app|store)\.[A-Za-z]+|unit\.[A-Za-z0-9_.-]+|dlf\.(?:metadata|dedicated_path|(?:live|dedicated)\.[A-Za-z0-9_.]+))=[A-Za-z0-9_:./ -]*",
            line,
        ):
            pass  # Deliberately excluded from artifact: no principals or arbitrary metadata.
        elif line != "limits=" + LIMITS:
            raise ValueError("unknown")
    if "dlf.journal.state" not in selected:
        raise ValueError("missing")
    state = selected["dlf.journal.state"]
    count = selected.get("dlf.journal.unclassified")
    if state in {"classified", "empty"} and count is None:
        raise ValueError("missing")
    if state == "empty" and count != "0":
        raise ValueError("inconsistent")
    events = {}
    for key, value in selected.items():
        match = re.fullmatch(
            r"dlf.journal.event([0-9]+)\.(timestampUs|board|stage|nativeCount|parsedRows|requiredFloor)",
            key,
        )
        if match:
            events.setdefault(int(match[1]), set()).add(match[2])
    if events and (
        sorted(events) != list(range(len(events))) or selected["dlf.journal.state"] != "classified"
    ):
        raise ValueError("incomplete")
    for index, fields in events.items():
        prefix = f"dlf.journal.event{index}."
        base = {"timestampUs", "board", "stage"}
        numeric = {"nativeCount", "parsedRows", "requiredFloor"}
        coverage = selected.get(prefix + "stage") == "native_value_floor"
        if fields != (base | numeric if coverage else base):
            raise ValueError("incomplete")
        if coverage:
            native, rows, floor = (
                int(selected[prefix + key])
                for key in ("nativeCount", "parsedRows", "requiredFloor")
            )
            if selected[prefix + "board"] != "dlfSf" or not (
                native <= rows and 0 < floor and native < floor
            ):
                raise ValueError("inconsistent")
    if state == "classified" and not events and int(count) == 0:
        raise ValueError("inconsistent")
    return selected


def capture(command, script, timeout=180):
    with open(script, "rb") as source:
        child = subprocess.Popen(
            command, stdin=source, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
        )
        chunks = []

        def read():
            total = 0
            while True:
                block = child.stdout.read(min(4096, LIMIT + 1 - total))
                if not block:
                    return
                chunks.append(block)
                total += len(block)
                if total > LIMIT:
                    child.kill()
                    return

        reader = threading.Thread(target=read, daemon=True)
        reader.start()
        try:
            child.wait(timeout=timeout)
            reader.join(timeout=1)
            if reader.is_alive() or child.returncode != 0:
                raise ValueError("capture")
            return validate(b"".join(chunks))
        finally:
            if child.poll() is None:
                child.kill()
            child.wait(timeout=2)
            reader.join(timeout=2)
            if not reader.is_alive():
                child.stdout.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--script", required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    result = {
        "schemaVersion": 1,
        "scope": "performance-safe",
        "collection": "failed",
        "limitations": LIMITS.split(";"),
    }
    for source, target, pattern in [
        ("GITHUB_SHA", "workflowSha", r"[0-9a-f]{40}"),
        ("GITHUB_RUN_ID", "runId", r"[0-9]{1,24}"),
        ("GITHUB_RUN_ATTEMPT", "runAttempt", r"[0-9]{1,10}"),
    ]:
        value = os.environ.get(source, "")
        if re.fullmatch(pattern, value):
            result[target] = value
    try:
        command = args.command[1:] if args.command[:1] == ["--"] else args.command
        result["fields"] = capture(command, args.script)
        state = result["fields"]["dlf.journal.state"]
        result["collection"] = "complete" if state in {"classified", "empty"} else "incomplete"
    except Exception:
        pass  # No exception strings, subprocess output or stack traces leave this process.
    Path(args.output).write_text(json.dumps(result, sort_keys=True) + "\n", encoding="utf-8")
    return 0 if result["collection"] == "complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
