#!/usr/bin/env python3
"""Idempotent single-key edits to a production ``.env`` file.

Built for the V1-49 controlled-activation workflow
(``.github/workflows/v1-49-host-native-scoring-activation.yml``), which
flips exactly one ``RISKIT_FEATURE_*`` flag in production's
``<PROD_APP_DIR>/.env`` (loaded via ``EnvironmentFile=-__APP_DIR__/.env``
in ``deploy/systemd/dynasty.service.template``) and must be able to
restore the prior state deterministically on any failure. This module is
intentionally general (it edits one ``KEY=value`` line, nothing else) so
the same code path serves both the forward flip and the rollback restore
— there is exactly one write function
(:func:`atomic_write_env_lines`) and exactly one line-mutation pair
(:func:`upsert_line` / :func:`remove_line`).

Every write is atomic (temp file + ``os.replace``) and every operation is
idempotent: applying ``set`` twice with the same value, or ``restore``
twice with the same prior state, converges to one line and never
duplicates or corrupts the file. No other keys in the file are ever
touched.

Subcommands:

* ``show``    — print the current raw value for a key (or ``ABSENT``).
* ``set``     — upsert ``key=value``; prints the PRIOR value (or
  ``ABSENT``) as JSON so a caller can capture it for later restore in
  the same call that performs the write.
* ``restore`` — set the key back to a previously captured value, or
  remove the line entirely if the captured prior state was ``ABSENT``.

Exit codes: 0 success, 2 usage/IO error (missing/unwritable file,
invalid key, value containing a newline).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

ABSENT_SENTINEL = "ABSENT"

_KEY_RE = re.compile(r"^[A-Z_][A-Z0-9_]*$")


class EnvOpsError(Exception):
    """Raised on invalid input; callers should exit 2."""


def _validate_key(key: str) -> None:
    if not _KEY_RE.match(key):
        raise EnvOpsError(f"invalid env key (must match {_KEY_RE.pattern!r}): {key!r}")


def _validate_value(value: str) -> None:
    if "\n" in value or "\r" in value:
        raise EnvOpsError("value must not contain a newline")


def read_env_lines(path: Path) -> list[str]:
    """Read an ``.env`` file as a list of lines (with trailing newlines).

    A missing file reads as empty content — matches the systemd
    ``EnvironmentFile=-...`` convention where a leading ``-`` tolerates
    an absent file.
    """
    if not path.exists():
        return []
    return path.read_text().splitlines(keepends=True)


def read_current_value(lines: list[str], key: str) -> str:
    """Return the raw value string for ``key=...``, or ``ABSENT_SENTINEL``."""
    _validate_key(key)
    pattern = re.compile(rf"^{re.escape(key)}=(.*)$")
    for line in lines:
        match = pattern.match(line.rstrip("\n\r"))
        if match:
            return match.group(1)
    return ABSENT_SENTINEL


def upsert_line(lines: list[str], key: str, value: str) -> list[str]:
    """Return ``lines`` with ``key=value`` set: rewrite the existing line
    in place, or append a new one if absent. Idempotent — reapplying with
    the same value produces byte-identical output.
    """
    _validate_key(key)
    _validate_value(value)
    pattern = re.compile(rf"^{re.escape(key)}=")
    new_lines: list[str] = []
    replaced = False
    for line in lines:
        stripped = line.rstrip("\n\r")
        if pattern.match(stripped):
            new_lines.append(f"{key}={value}\n")
            replaced = True
        else:
            new_lines.append(line if line.endswith("\n") else line + "\n")
    if not replaced:
        if new_lines and not new_lines[-1].endswith("\n"):
            new_lines[-1] += "\n"
        new_lines.append(f"{key}={value}\n")
    return new_lines


def remove_line(lines: list[str], key: str) -> list[str]:
    """Return ``lines`` with any ``key=...`` line removed. Idempotent —
    removing an already-absent key is a no-op.
    """
    _validate_key(key)
    pattern = re.compile(rf"^{re.escape(key)}=")
    return [line for line in lines if not pattern.match(line.rstrip("\n\r"))]


def atomic_write_env_lines(path: Path, lines: list[str]) -> None:
    """Write ``lines`` to ``path`` atomically (temp file + rename)."""
    tmp_path = path.with_name(f"{path.name}.tmp.{os.getpid()}")
    tmp_path.write_text("".join(lines))
    tmp_path.replace(path)


def apply_set(path: Path, key: str, value: str) -> str:
    """Upsert ``key=value`` in the env file at ``path``; return the prior
    value (or :data:`ABSENT_SENTINEL`) so the caller can capture it.
    """
    lines = read_env_lines(path)
    prior = read_current_value(lines, key)
    new_lines = upsert_line(lines, key, value)
    atomic_write_env_lines(path, new_lines)
    return prior


def apply_restore(path: Path, key: str, prior_state: str) -> None:
    """Restore ``key`` to ``prior_state`` (or remove it if ``prior_state``
    is :data:`ABSENT_SENTINEL`). Idempotent.
    """
    _validate_key(key)
    lines = read_env_lines(path)
    if prior_state == ABSENT_SENTINEL:
        new_lines = remove_line(lines, key)
    else:
        new_lines = upsert_line(lines, key, prior_state)
    atomic_write_env_lines(path, new_lines)


def _cmd_show(args: argparse.Namespace) -> int:
    path = Path(args.env_file)
    value = read_current_value(read_env_lines(path), args.key)
    print(json.dumps({"key": args.key, "value": value}))
    return 0


def _cmd_set(args: argparse.Namespace) -> int:
    path = Path(args.env_file)
    prior = apply_set(path, args.key, args.value)
    print(json.dumps({"key": args.key, "prior_state": prior, "new_value": args.value}))
    return 0


def _cmd_restore(args: argparse.Namespace) -> int:
    path = Path(args.env_file)
    apply_restore(path, args.key, args.prior_state)
    print(json.dumps({"key": args.key, "restored_to": args.prior_state}))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    show = sub.add_parser("show", help="print the current value for a key")
    show.add_argument("--env-file", required=True)
    show.add_argument("--key", required=True)
    show.set_defaults(func=_cmd_show)

    set_cmd = sub.add_parser("set", help="upsert key=value, printing the prior state")
    set_cmd.add_argument("--env-file", required=True)
    set_cmd.add_argument("--key", required=True)
    set_cmd.add_argument("--value", required=True)
    set_cmd.set_defaults(func=_cmd_set)

    restore = sub.add_parser("restore", help="restore a key to a captured prior state")
    restore.add_argument("--env-file", required=True)
    restore.add_argument("--key", required=True)
    restore.add_argument("--prior-state", required=True)
    restore.set_defaults(func=_cmd_restore)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except EnvOpsError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
