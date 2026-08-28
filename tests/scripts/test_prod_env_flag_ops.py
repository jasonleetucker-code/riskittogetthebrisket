"""Unit tests for ``scripts/prod_env_flag_ops.py``.

Pins the properties the V1-49 activation/rollback workflow depends on:

1. ``set`` is idempotent — applying the same value twice converges to
   one line, never duplicates it.
2. ``set`` correctly captures the prior state, including ``ABSENT``
   when the key did not exist.
3. ``restore`` round-trips exactly: restoring a captured real value
   reproduces the original line; restoring a captured ``ABSENT``
   removes the key entirely, even if something else set it in between.
4. No other line in the file is ever touched.
5. Writes are atomic (no partial file left behind on the happy path).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "prod_env_flag_ops.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("prod_env_flag_ops", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


_mod = _load_module()

ABSENT = _mod.ABSENT_SENTINEL
KEY = "RISKIT_FEATURE_HOST_NATIVE_SCORING"


def test_set_on_missing_file_creates_it_and_prior_is_absent(tmp_path):
    env_file = tmp_path / ".env"
    prior = _mod.apply_set(env_file, KEY, "1")
    assert prior == ABSENT
    assert env_file.read_text() == f"{KEY}=1\n"


def test_set_is_idempotent(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("OTHER_KEY=unchanged\n")
    _mod.apply_set(env_file, KEY, "1")
    first = env_file.read_text()
    prior_second = _mod.apply_set(env_file, KEY, "1")
    second = env_file.read_text()
    assert first == second
    assert prior_second == "1"
    assert first.count(f"{KEY}=") == 1


def test_set_captures_prior_real_value_and_preserves_other_lines(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(f"BEFORE=1\n{KEY}=0\nAFTER=2\n")
    prior = _mod.apply_set(env_file, KEY, "1")
    assert prior == "0"
    content = env_file.read_text()
    assert "BEFORE=1" in content
    assert "AFTER=2" in content
    assert f"{KEY}=1" in content
    assert content.count(f"{KEY}=") == 1


def test_restore_to_absent_removes_the_key(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(f"BEFORE=1\n{KEY}=1\nAFTER=2\n")
    _mod.apply_restore(env_file, KEY, ABSENT)
    content = env_file.read_text()
    assert KEY not in content
    assert "BEFORE=1" in content
    assert "AFTER=2" in content


def test_restore_to_absent_is_idempotent_when_key_already_gone(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("BEFORE=1\nAFTER=2\n")
    _mod.apply_restore(env_file, KEY, ABSENT)
    content = env_file.read_text()
    assert content == "BEFORE=1\nAFTER=2\n"


def test_restore_to_prior_real_value_round_trips_exactly(tmp_path):
    env_file = tmp_path / ".env"
    original = f"BEFORE=1\n{KEY}=0\nAFTER=2\n"
    env_file.write_text(original)
    prior = _mod.apply_set(env_file, KEY, "1")
    assert env_file.read_text() != original
    _mod.apply_restore(env_file, KEY, prior)
    assert env_file.read_text() == original


def test_capture_then_restore_round_trip_survives_an_intervening_set(tmp_path):
    """The rollback scenario: set captures prior, something else (a
    retry, or the activation's own restart-and-recheck) sets it again,
    and restore still lands on the ORIGINAL captured value.
    """
    env_file = tmp_path / ".env"
    env_file.write_text(f"{KEY}=0\n")
    prior = _mod.apply_set(env_file, KEY, "1")
    assert prior == "0"
    _mod.apply_set(env_file, KEY, "1")  # idempotent re-set, e.g. a retry
    _mod.apply_restore(env_file, KEY, prior)
    assert env_file.read_text() == f"{KEY}=0\n"


def test_show_reports_absent_for_missing_key(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("OTHER=1\n")
    lines = _mod.read_env_lines(env_file)
    assert _mod.read_current_value(lines, KEY) == ABSENT


def test_show_reports_absent_for_missing_file(tmp_path):
    env_file = tmp_path / "does_not_exist.env"
    lines = _mod.read_env_lines(env_file)
    assert _mod.read_current_value(lines, KEY) == ABSENT


def test_set_appends_trailing_newline_before_new_key_if_missing(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("NO_TRAILING_NEWLINE=1")
    _mod.apply_set(env_file, KEY, "1")
    content = env_file.read_text()
    assert content == f"NO_TRAILING_NEWLINE=1\n{KEY}=1\n"


def test_invalid_key_is_rejected(tmp_path):
    env_file = tmp_path / ".env"
    try:
        _mod.apply_set(env_file, "not a valid key!", "1")
        raise AssertionError("expected EnvOpsError")
    except _mod.EnvOpsError:
        pass


def test_value_with_newline_is_rejected(tmp_path):
    env_file = tmp_path / ".env"
    try:
        _mod.apply_set(env_file, KEY, "1\nINJECTED=1")
        raise AssertionError("expected EnvOpsError")
    except _mod.EnvOpsError:
        pass


def test_atomic_write_leaves_no_temp_file_behind(tmp_path):
    env_file = tmp_path / ".env"
    _mod.apply_set(env_file, KEY, "1")
    leftovers = list(tmp_path.glob(".env.tmp.*"))
    assert leftovers == []


def test_cli_set_then_restore_round_trips(tmp_path, capsys):
    env_file = tmp_path / ".env"
    env_file.write_text(f"{KEY}=0\n")

    rc = _mod.main(["set", "--env-file", str(env_file), "--key", KEY, "--value", "1"])
    assert rc == 0
    out = capsys.readouterr().out
    assert '"prior_state": "0"' in out
    assert env_file.read_text() == f"{KEY}=1\n"

    rc = _mod.main(["restore", "--env-file", str(env_file), "--key", KEY, "--prior-state", "0"])
    assert rc == 0
    assert env_file.read_text() == f"{KEY}=0\n"


def test_cli_show(tmp_path, capsys):
    env_file = tmp_path / ".env"
    env_file.write_text(f"{KEY}=1\n")
    rc = _mod.main(["show", "--env-file", str(env_file), "--key", KEY])
    assert rc == 0
    out = capsys.readouterr().out
    assert '"value": "1"' in out
