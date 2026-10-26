"""Fixed, credential-free Class-B maintenance worker pilot.

This worker accepts one task and one document. It has no Git or PR operations.
The container, rather than these cooperative policy functions, supplies the
filesystem and network boundary.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import socket
import subprocess
import sys
from pathlib import Path

TASK_ID = "repair-performance-audit-anchor"
FILE_NAME = "PERFORMANCE_AUDIT.md"
LINK_TEXT = "Optimisations that serve a different answer"
HEADING = "7. Optimisations that serve a different answer"
LINK = re.compile(r"\[Optimisations that serve a different answer\]\(#([^)]+)\)")


def digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def slug(heading: str) -> str:
    value = re.sub(r"[^\w -]", "", heading.casefold(), flags=re.UNICODE)
    return re.sub(r"\s+", "-", value.strip())


def repair(source: str) -> str:
    headings = re.findall(r"^## (.+)$", source, flags=re.MULTILINE)
    targets = [slug(value) for value in headings if value.rstrip("\r") == HEADING]
    links = list(LINK.finditer(source))
    if len(targets) != 1 or len(links) != 1:
        raise ValueError("expected one heading and one local link")
    before = links[0].group(1)
    after = targets[0]
    if before == after or before in {slug(value) for value in headings}:
        raise ValueError("no broken target anchor to repair")
    return source[: links[0].start(1)] + after + source[links[0].end(1) :]


def allowed_path(candidate: Path, source: Path, output: Path) -> bool:
    """A cooperative path policy. Container mounts enforce the actual boundary."""
    if candidate.is_symlink():
        return False
    resolved = candidate.resolve()
    return resolved == source.resolve() or resolved == output.resolve()


def allowed_command(argv: list[str], expected: list[str]) -> bool:
    return argv == expected


def check_repaired(path: Path) -> None:
    content = path.read_text(encoding="utf-8")
    target = LINK.search(content)
    if target is None or target.group(1) != slug(HEADING):
        raise ValueError("repaired anchor validation failed")
    if content.count("## " + HEADING) != 1:
        raise ValueError("target heading validation failed")


def execute(source: Path, output_dir: Path, *, probe_network: bool = False) -> dict:
    if source.name != FILE_NAME or not source.is_file() or source.is_symlink():
        raise ValueError("fixed task requires a regular performance audit document")
    if not output_dir.is_dir() or output_dir.is_symlink() or list(output_dir.iterdir()):
        raise ValueError("output directory must be empty and regular")
    output = output_dir / FILE_NAME
    refusals = []
    if allowed_path(source.parent / ".." / "forbidden", source, output):
        raise ValueError("forbidden path was accepted")
    refusals.append("path_denied")
    expected_test = [
        sys.executable,
        "-I",
        "-B",
        str(Path(__file__).resolve()),
        "--check",
        str(output),
    ]
    if allowed_command(["sudo", "true"], expected_test):
        raise ValueError("forbidden command was accepted")
    refusals.append("command_denied")
    original = source.read_bytes()
    repaired = repair(original.decode("utf-8")).encode("utf-8")
    output.write_bytes(repaired)
    if probe_network:
        connection = socket.socket()
        connection.settimeout(1)
        try:
            connection.connect(("1.1.1.1", 443))
        except OSError:
            refusals.append("network_denied_by_container")
        else:
            raise ValueError("container network access was accepted")
        finally:
            connection.close()
    if not allowed_command(expected_test, expected_test):
        raise ValueError("permitted test command was denied")
    subprocess.run(expected_test, check=True, timeout=10)
    receipt = {
        "schema": "class-b-branch-pilot/v1",
        "task_id": TASK_ID,
        "file": FILE_NAME,
        "before_sha256": digest(original),
        "after_sha256": digest(repaired),
        "test": "anchor-resolves",
        "test_result": "passed",
        "refusals": refusals,
    }
    (output_dir / "receipt.json").write_text(
        json.dumps(receipt, sort_keys=True) + "\n", encoding="utf-8"
    )
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--check", type=Path)
    parser.add_argument("--probe-network", action="store_true")
    args = parser.parse_args()
    if args.check is not None:
        check_repaired(args.check)
        return
    if args.source is None or args.output is None:
        parser.error("--source and --output are required")
    print(
        json.dumps(
            execute(args.source, args.output, probe_network=args.probe_network), sort_keys=True
        )
    )


if __name__ == "__main__":
    main()
