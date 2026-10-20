"""The on-box package-model market-ledger evaluation cannot mutate production.

``.github/workflows/package-model-market-ledger.yml`` runs
``deploy/diagnostics/package_model_ledger_onbox.sh`` on the production host,
which runs ``scripts/package_model_phase2_research.py --market-ledger-only``
under ``scripts/research_readonly_guard.py`` (master directive 2026-10-19 §11,
"Option 2": a controlled read-only server-side run, no deploy).

What is pinned here, without any network or production access:

1. PINNED CODE — the sha256 pins match the scripts, so changing a research
   script without a reviewed pin update fails CI;
2. HOST SCRIPT IS READ-ONLY — a static scan (comments and single-quoted
   strings stripped) proves it writes only inside its own ``mktemp -d`` dir,
   removes only that dir, never ``cd``s into the app, and never calls
   systemctl / git / sudo / package managers / network tools / sqlite3;
3. WORKFLOW SHAPE — dispatch-only, ``contents: read``, the ``production``
   environment (owner approval), deploy-group serialisation, main-only, only
   the deploy SSH secrets, and an artifact uploaded only after both
   aggregate-only gates passed;
4. PYTHON BOX PATH — the function the host runs performs no write, process or
   network call itself, and the ledger is opened ``mode=ro``;
5. REHEARSAL — the real host script, run locally against a fake app dir,
   verifies the pins, refuses a tampered payload, leaves the app dir
   byte-for-byte unchanged and removes its temp dir.
"""

from __future__ import annotations

import ast
import base64
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
WORKFLOW = REPO / ".github" / "workflows" / "package-model-market-ledger.yml"
HOST_SCRIPT = REPO / "deploy" / "diagnostics" / "package_model_ledger_onbox.sh"
PINS = REPO / "deploy" / "diagnostics" / "package_model_ledger_onbox.sha256"
SCRIPTS = (
    "package_model_phase2_research.py",
    "package_model_hybrid_research.py",
    "research_readonly_guard.py",
)

# Commands a read-only research run never needs.  Any of them in the host
# script is a defect, whatever the surrounding logic.
FORBIDDEN_HOST_COMMANDS = (
    "systemctl",
    "service",
    "journalctl",
    "git",
    "gh",
    "sudo",
    "su",
    "doas",
    "curl",
    "wget",
    "ssh",
    "scp",
    "rsync",
    "nc",
    "pip",
    "pip3",
    "apt",
    "apt-get",
    "npm",
    "npx",
    "sqlite3",
    "crontab",
    "kill",
    "pkill",
    "killall",
    "reboot",
    "shutdown",
    "chmod",
    "chown",
    "chgrp",
    "mv",
    "cp",
    "ln",
    "tee",
    "dd",
    "install",
    "mkdir",
    "touch",
    "truncate",
    "docker",
    "mount",
    "nginx",
)


def _runnable_shell(text: str) -> str:
    """Shell text with comment lines and single-quoted strings removed."""
    lines = [ln for ln in text.splitlines() if not ln.lstrip().startswith("#")]
    return re.sub(r"'[^']*'", "''", "\n".join(lines))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _steps() -> list[dict]:
    return _workflow()["jobs"]["evaluate"]["steps"]


def _run_blocks() -> str:
    return "\n".join(s.get("run", "") for s in _steps())


# ── 1. pinned code ───────────────────────────────────────────────────────────


def test_pins_cover_exactly_the_shipped_scripts_and_match_them():
    pins = {}
    for line in PINS.read_text(encoding="utf-8").splitlines():
        digest, name = line.split("  ", 1)
        assert re.fullmatch(r"[0-9a-f]{64}", digest)
        pins[name] = digest
    assert set(pins) == set(SCRIPTS)
    for name in SCRIPTS:
        assert pins[name] == _sha256(
            REPO / "scripts" / name
        ), f"scripts/{name} changed without a reviewed pin update in {PINS.name}"


def test_workflow_and_host_both_verify_the_pins():
    run = _run_blocks()
    assert (
        "sha256sum --check --strict ../deploy/diagnostics/package_model_ledger_onbox.sha256" in run
    )
    host = _runnable_shell(HOST_SCRIPT.read_text(encoding="utf-8"))
    assert "sha256sum --check --strict" in host
    for name in SCRIPTS:
        assert name in host


# ── 2. the host script is read-only ──────────────────────────────────────────


def test_host_script_calls_no_mutating_or_network_command():
    text = _runnable_shell(HOST_SCRIPT.read_text(encoding="utf-8"))
    for cmd in FORBIDDEN_HOST_COMMANDS:
        # A command position: line start, after a pipe / ; / && / ( / $( / then / do.
        pattern = rf"(?:^|[|;&(]|\$\(|\bthen\b|\bdo\b|\bexec\b)\s*{re.escape(cmd)}(?=\s|$)"
        assert not re.search(pattern, text, re.M), f"host script invokes `{cmd}`"


def test_host_script_removes_only_its_own_temp_dir():
    raw = HOST_SCRIPT.read_text(encoding="utf-8")
    text = "\n".join(ln for ln in raw.splitlines() if not ln.lstrip().startswith("#"))
    assert text.count("mktemp -d") == 1
    assert "trap 'rm -rf -- \"$WORK\"' EXIT" in text
    rms = re.findall(r"\brm\b[^\n']*", text)
    assert rms == ['rm -rf -- "$WORK"'], rms


def test_every_host_redirection_targets_the_temp_dir_stderr_or_null():
    text = _runnable_shell(HOST_SCRIPT.read_text(encoding="utf-8"))
    targets = re.findall(r"(?<![<>=-])\d?>{1,2}\s*(&\d|\"[^\"]*\"|\S+)", text)
    assert targets, "scan found no redirections — it would pass vacuously"
    for target in targets:
        ok = target in {"&2", "&1", "/dev/null"} or target.startswith('"$WORK/')
        assert ok, f"host script redirects output to {target!r}"


def test_host_script_never_enters_or_writes_the_app_dir():
    text = _runnable_shell(HOST_SCRIPT.read_text(encoding="utf-8"))
    assert re.findall(r"\bcd\s+(\S+)", text) == ['"$WORK"', '"$WORK"']
    allowed = (
        'APP_DIR="${APP_DIR:-/home/dynasty/trade-calculator}"',
        '[[ -d "$APP_DIR/src" ]]',
        '[[ -x "$PY" ]] || PY="$APP_DIR/.venv/bin/python"',
        'RISKIT_APP_DIR="$APP_DIR"',
    )
    for line in text.splitlines():
        if "APP_DIR" in line:
            assert any(a in line for a in allowed), f"unexpected APP_DIR use: {line.strip()}"


def test_host_script_runs_only_the_guarded_box_mode_bounded():
    text = _runnable_shell(HOST_SCRIPT.read_text(encoding="utf-8"))
    assert '"$PY" -B "$WORK/package_model_phase2_research.py"' in text
    assert "--market-ledger-only" in text
    # The non-box modes write evidence files into the repository tree.
    for flag in ("--out", "--finder", "--market-ledger ", "--local-"):
        assert flag not in text
    for bound in ("nice -n 19", "ionice -c3", "timeout ", "ulimit -v"):
        assert bound in text
    # Raw stderr is never forwarded: it is captured in the temp dir and read
    # back only as a line count or through the structure-only grep.
    assert '2> "$WORK/stderr.log"' in text
    readers = [ln.strip() for ln in text.splitlines() if "stderr.log" in ln]
    assert len(readers) == 3, readers
    assert any(r.startswith(') 2> "$WORK/stderr.log"') for r in readers)
    assert any(r.startswith('LINES="$(wc -l < "$WORK/stderr.log")"') for r in readers)
    assert any(r.startswith("grep -E ") for r in readers)


# ── 3. workflow shape ────────────────────────────────────────────────────────


def test_workflow_is_dispatch_only_with_one_validated_input():
    doc = _workflow()
    on = doc.get(True, doc.get("on"))
    assert set(on) == {"workflow_dispatch"}
    assert set((on["workflow_dispatch"] or {}).get("inputs") or {}) == {"max_lag_days"}
    run = _run_blocks()
    assert '[[ "$MAX_LAG_DAYS" =~ ^[0-9]{1,2}$ ]]' in run


def test_workflow_least_privilege_and_owner_gate():
    doc = _workflow()
    assert doc["permissions"] == {"contents": "read"}
    job = doc["jobs"]["evaluate"]
    assert job["environment"] == "production"
    assert "if" not in job
    assert doc["concurrency"] == {"group": "production-deploy", "cancel-in-progress": False}
    assert job["timeout-minutes"] <= 60
    assert list(doc["jobs"]) == ["evaluate"]


def test_workflow_refuses_any_ref_but_main_before_reading_secrets():
    steps = _steps()
    assert "refs/heads/main" in steps[0]["run"]
    assert "secrets." not in json.dumps(steps[0])
    checkout = next(s for s in steps if str(s.get("uses", "")).startswith("actions/checkout"))
    assert checkout["with"]["persist-credentials"] is False


def test_workflow_reads_only_the_deploy_ssh_secrets():
    text = WORKFLOW.read_text(encoding="utf-8")
    secrets = set(re.findall(r"secrets\.([A-Z0-9_]+)", text))
    assert secrets <= {
        "DEPLOY_HOST",
        "DEPLOY_USER",
        "DEPLOY_SSH_PRIVATE_KEY",
        "DEPLOY_KNOWN_HOSTS",
        "DEPLOY_PORT",
    }


def test_workflow_sends_only_the_pinned_host_script_over_ssh():
    run = _run_blocks()
    assert len(re.findall(r"(?m)^\s*ssh\s", run)) == 1
    assert re.search(
        r'bash -s" \\\n\s*< deploy/diagnostics/package_model_ledger_onbox\.sh \\\n'
        r'\s*> "\$RUNNER_TEMP/package-model-market-ledger\.json"',
        run,
    )
    runnable = _runnable_shell(run)
    for token in ("git push", "git commit", "gh ", "systemctl", "sudo", "curl ", "rsync", "scp "):
        assert token not in runnable, token


def test_artifact_is_the_gated_aggregate_report_only():
    steps = _steps()
    names = [s.get("name") for s in steps]
    gate = names.index("Aggregate-only gate and summary")
    upload = next(i for i, s in enumerate(steps) if "upload-artifact" in str(s.get("uses", "")))
    assert upload > gate
    up = steps[upload]
    assert up.get("if") == "success()"
    assert up["with"]["path"].endswith("/package-model-market-ledger.json")
    assert int(up["with"]["retention-days"]) <= 30
    assert "always()" not in WORKFLOW.read_text(encoding="utf-8")


def _gate_code() -> str:
    step = next(s for s in _steps() if s.get("name") == "Aggregate-only gate and summary")
    body = re.search(r"<<'EOF'\n(.*?)\n\s*EOF", step["run"], re.S).group(1)
    lines = body.splitlines()
    indent = min(len(ln) - len(ln.lstrip()) for ln in lines if ln.strip())
    return "\n".join(ln[indent:] for ln in lines)


_GOOD_REPORT = {
    "deployedCodeSha": "0123456789abcdef0123456789abcdef01234567",
    "readOnlyGuard": {"installed": True, "refusedWriteOrProcessAttempts": 0},
    "marketLedgerCalibration": {"audit": {"graded": 3}, "calibration": {"byModel": {}}},
}


@pytest.mark.parametrize(
    ("label", "report", "accepted"),
    [
        ("aggregate", _GOOD_REPORT, True),
        ("long float statistic", dict(_GOOD_REPORT, meanSigned=-0.46123456789012345), True),
        ("roster id key", dict(_GOOD_REPORT, sample={"rosterId": 3}), False),
        ("long digit run", dict(_GOOD_REPORT, note="league 1312006700437352448"), False),
        ("asset id", dict(_GOOD_REPORT, note="player:4046"), False),
        ("not a sha", dict(_GOOD_REPORT, deployedCodeSha="1312006700437352448"), False),
        ("guard missing", dict(_GOOD_REPORT, readOnlyGuard={"installed": False}), False),
        (
            "guard refused a write",
            dict(
                _GOOD_REPORT,
                readOnlyGuard={"installed": True, "refusedWriteOrProcessAttempts": 1},
            ),
            False,
        ),
    ],
)
def test_runner_gate_refuses_identifier_like_or_unguarded_reports(
    tmp_path, label, report, accepted
):
    path = tmp_path / "report.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, "-I", "-c", _gate_code(), str(path)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert (proc.returncode == 0) is accepted, (label, proc.stdout, proc.stderr)
    if not accepted:
        assert proc.stdout == "", "a refused report must print nothing"


# ── 4. the Python box path ───────────────────────────────────────────────────


def _function(src: str, name: str) -> ast.FunctionDef:
    tree = ast.parse(src)
    return next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == name)


def test_box_function_performs_no_write_process_or_network_call():
    src = (REPO / "scripts" / "package_model_phase2_research.py").read_text(encoding="utf-8")
    fn = _function(src, "market_ledger_only")
    banned = {
        "write_text",
        "write_bytes",
        "open",
        "mkdir",
        "unlink",
        "rename",
        "replace",
        "rmtree",
        "touch",
        "Popen",
        "check_output",
        "check_call",
        "system",
        "urlopen",
        "connect",
        "commit",
        "executescript",
    }
    called = set()
    for node in ast.walk(fn):
        if isinstance(node, ast.Call):
            f = node.func
            called.add(f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", ""))
    assert not (called & banned), sorted(called & banned)
    assert "open_canonical_ledger" in called


def test_ledger_is_opened_read_only():
    src = (REPO / "src" / "trade" / "market_trade_report.py").read_text(encoding="utf-8")
    body = ast.get_source_segment(src, _function(src, "open_canonical_ledger"))
    assert "?mode=ro" in body and "uri=True" in body


# ── 5. rehearsal of the real host script (offline, fake app dir) ─────────────


def _payload() -> tuple[str, str]:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name in SCRIPTS:
            tar.add(REPO / "scripts" / name, arcname=name)
    return base64.b64encode(buf.getvalue()).decode(), PINS.read_text(encoding="utf-8")


def _tree(root: Path) -> dict:
    out = {}
    for p in sorted(root.rglob("*")):
        if p.is_symlink():
            out[str(p.relative_to(root))] = ("link", os.readlink(p))
        elif p.is_file():
            st = p.stat()
            out[str(p.relative_to(root))] = ("file", st.st_size, st.st_mtime_ns, _sha256(p))
        else:
            out[str(p.relative_to(root))] = ("dir",)
    return out


@pytest.fixture
def fake_host(tmp_path):
    if (REPO / "data" / "market_trades" / "underlying_trades.sqlite").exists():
        pytest.skip("a real market-trade ledger is present; the rehearsal expects none")
    app = tmp_path / "app"
    (app / ".venv" / "bin").mkdir(parents=True)
    (app / ".venv" / "bin" / "python").symlink_to(sys.executable)
    (app / "src").symlink_to(REPO / "src")
    (app / "exports" / "archive").mkdir(parents=True)
    tmpdir = tmp_path / "tmp"
    tmpdir.mkdir()
    return app, tmpdir


def _run_host(app: Path, tmpdir: Path, **overrides) -> subprocess.CompletedProcess:
    payload, pins = _payload()
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(tmpdir),
        "TMPDIR": str(tmpdir),
        "APP_DIR": str(app),
        "MAX_LAG_DAYS": "7",
        "PAYLOAD_B64": payload,
        "PINS": pins,
    }
    env.update(overrides)
    return subprocess.run(
        ["bash", str(HOST_SCRIPT)], capture_output=True, text=True, env=env, timeout=600
    )


def test_rehearsal_reads_nothing_writes_nothing_and_cleans_up(fake_host):
    app, tmpdir = fake_host
    before = _tree(app)
    proc = _run_host(app, tmpdir)
    # No ledger on this "host": exit 2 with an explicit unavailable report —
    # "could not look" is never a success.
    assert proc.returncode == 2, proc.stderr
    assert json.loads(proc.stdout) == {
        "available": False,
        "reason": "no_market_trade_ledger_on_this_host",
    }
    assert _tree(app) == before, "the host script changed the app dir"
    assert list(tmpdir.iterdir()) == [], "the temp dir was not removed"
    assert "evaluation exit=2" in proc.stderr


def test_rehearsal_refuses_a_tampered_payload_before_running_anything(fake_host):
    app, tmpdir = fake_host
    _payload_b64, pins = _payload()
    tampered = pins.replace(pins[:8], "00000000", 1)
    proc = _run_host(app, tmpdir, PINS=tampered)
    assert proc.returncode == 65
    assert "pinned sha256 mismatch" in proc.stderr
    assert "evaluation exit" not in proc.stderr
    assert proc.stdout == ""
    assert list(tmpdir.iterdir()) == []


@pytest.mark.parametrize("bad", ["", "7; rm -rf /", "1000", "-1", "7d"])
def test_rehearsal_refuses_a_bad_lag_input(fake_host, bad):
    app, tmpdir = fake_host
    proc = (
        _run_host(app, tmpdir, MAX_LAG_DAYS=bad)
        if bad
        else _run_host(app, tmpdir, MAX_LAG_DAYS="x")
    )
    assert proc.returncode == 64
    assert proc.stdout == ""
    assert list(tmpdir.iterdir()) == []
