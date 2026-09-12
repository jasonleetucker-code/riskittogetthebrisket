"""Execute the install-only branch with fake principals and no host mutations."""

from pathlib import Path
import os
import shlex
import shutil
import subprocess

import pytest


REPO = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    "scenario",
    [
        "healthy",
        "same_uid",
        "managed_env",
        "web_key",
        "active",
        "missing",
        "extra",
        "web_write_key",
        "web_write_env",
        "probe_failure",
        "uid_mismatch",
        "static_inactive",
        "systemctl_failure",
        "enabled",
        "incomplete_state",
        "resolved_space",
        "resolved_dollar",
        "resolved_percent",
        "resolved_newline",
    ],
)
def test_prepared_install_only_branch(tmp_path, scenario):
    git_bash = Path("C:/Program Files/Git/bin/bash.exe")
    bash = str(git_bash) if git_bash.is_file() else shutil.which("bash")
    if not bash:
        pytest.skip("Bash is unavailable")
    templates = tmp_path / "app/deploy/systemd"
    templates.mkdir(parents=True)
    for name in (
        "source-producer.service",
        "source-producer.timer",
        "source-producer.path",
        "league-serving.service",
        "league-serving.timer",
        "league-serving.path",
        "prepared-news.service",
    ):
        shutil.copyfile(
            REPO / f"deploy/systemd/dynasty-{name}.template", templates / f"dynasty-{name}.template"
        )
    for name in ("producer.env", "web.env", "key", "pin"):
        (tmp_path / name).write_text("# nonsecret fixture\n", encoding="utf-8")
    (tmp_path / "store").mkdir()
    (tmp_path / "venv").mkdir()
    (tmp_path / "installed").mkdir()
    if scenario == "managed_env":
        (tmp_path / "producer.env").write_text("RISKIT_SERVING_DIR=/wrong\n", encoding="utf-8")
    source = (REPO / "deploy/install-systemd-service.sh").read_text(encoding="utf-8")
    assert source.rstrip().endswith('main "$@"')
    (tmp_path / "installer-functions.sh").write_text(
        source.rsplit('main "$@"', 1)[0], encoding="utf-8"
    )
    script = r"""
APP_DIR="$PWD/app" APP_USER=legacy SERVICE_NAME=example VENV_DIR="$PWD/venv"
source ./installer-functions.sh
PRODUCER_USER=producer WEB_USER=web SERVING_READER_GROUP=readers
PRODUCER_ENV_FILE="$PWD/producer.env" WEB_ENV_FILE="$PWD/web.env"
SERVING_DIR="$PWD/store" SIGNING_KEY_FILE="$PWD/key" PUBLIC_PIN_FILE="$PWD/pin"
require_command() { return 0; }
resolve_and_validate_sudo_binaries() { SYSTEMCTL_BIN=systemctl; INSTALL_BIN=install; }
id() { if [[ "$1" == -g ]]; then echo 60121; elif [[ "$2" == producer || "$SCENARIO" == same_uid ]]; then echo 60121; else echo 60122; fi; }
getent() { echo 'readers:x:60123:'; }
stat() { echo 60121; }
realpath() {
  if [[ "$2" == "$PUBLIC_PIN_FILE" && "$SCENARIO" == resolved_* ]]; then
    local suffix
    case "$SCENARIO" in
      resolved_space) suffix='unsafe pin';;
      resolved_dollar) suffix='unsafe$pin';;
      resolved_percent) suffix='unsafe%pin';;
      resolved_newline) suffix=$'unsafe\npin';;
    esac
    printf '# fixture\n' > "$PWD/$suffix"
    printf '%s\n' "$PWD/$suffix"
  else command realpath "$@"; fi
}
systemd-analyze() { printf 'VERIFY\n' >> calls; return 0; }
sudo() {
  [[ "$1" == -n ]] || return 90
  shift
  if [[ "$1" == -u ]]; then
    local user="$2"; shift 2
    [[ "$1" == /bin/sh ]] || return 91
    if [[ "$SCENARIO" == uid_mismatch ]]; then "$@"; return; fi
    local mode="$6" path="$7"
    if [[ "$user" == web && "$mode" == -r && ( "$path" == "$SIGNING_KEY_FILE" || "$path" == "$PRODUCER_ENV_FILE" ) ]]; then
      [[ "$SCENARIO" != probe_failure ]] || return 2
      if [[ "$SCENARIO" == web_key && "$path" == "$SIGNING_KEY_FILE" ]]; then return 10; else return 11; fi
    fi
    if [[ "$mode" == -w ]]; then
      if [[ ( "$SCENARIO" == web_write_key && "$path" == "$SIGNING_KEY_FILE" ) ||
         ( "$SCENARIO" == web_write_env && "$path" == "$PRODUCER_ENV_FILE" ) ]]; then return 10; else return 11; fi
    fi
    if test -f "$path"; then return 10; else return 11; fi
  fi
  if [[ "$1" == install ]]; then
    printf 'INSTALL %s\n' "${@: -1}" >> calls
    cp "$4" "installed/$(basename "${@: -1}")"; return
  fi
  if [[ "$1" == systemctl ]]; then
    printf 'SYSTEMCTL %s\n' "${*:2}" >> calls
    if [[ "$2" == show ]]; then
      [[ "$SCENARIO" != systemctl_failure ]] || return 4
      if [[ "$SCENARIO" == incomplete_state ]]; then printf 'LoadState=loaded\n'; return 0; fi
      if [[ "$SCENARIO" == active ]]; then printf 'LoadState=loaded\nActiveState=active\nUnitFileState=disabled\n'
      elif [[ "$SCENARIO" == enabled ]]; then printf 'LoadState=loaded\nActiveState=inactive\nUnitFileState=enabled\n'
      elif [[ "$SCENARIO" == static_inactive ]]; then printf 'LoadState=loaded\nActiveState=inactive\nUnitFileState=static\n'
      else printf 'LoadState=not-found\nActiveState=inactive\nUnitFileState=\n'; fi
      return 0
    fi
    [[ "$2" == daemon-reload ]] || return 92
    return 0
  fi
  return 93
}
[[ "$SCENARIO" != missing ]] || unset PRODUCER_ENV_FILE
if [[ "$SCENARIO" == extra ]]; then main --prepared-units-only extra; else main --prepared-units-only; fi
"""
    script = f"SCENARIO={scenario}\n" + script
    result = subprocess.run(
        [bash, "-c", script], cwd=tmp_path, text=True, capture_output=True, timeout=20, check=False
    )
    calls = (tmp_path / "calls").read_text() if (tmp_path / "calls").exists() else ""
    assert " enable " not in calls and " start " not in calls and " restart " not in calls
    if scenario not in {"healthy", "managed_env", "static_inactive"}:
        assert result.returncode != 0, result.stdout
        assert "INSTALL" not in calls
        if scenario.startswith("resolved_"):
            assert "Resolved prepared paths contain unsafe" in result.stderr
        return
    assert result.returncode == 0, result.stderr
    installed = list((tmp_path / "installed").iterdir())
    assert len(installed) == 7
    assert "SYSTEMCTL daemon-reload" in calls
    assert not (tmp_path / "installed/example.service").exists()
    for path in installed:
        body = path.read_text()
        assert "__" not in body
        if path.suffix == ".service":
            assert "User=producer" in body and "Group=60121" in body
            assert "SupplementaryGroups=readers" in body
            assert "EnvironmentFile=-" not in body and "/app/.env" not in body
            assert "RISKIT_SERVING_READER_GID=60123" in body
            command = next(
                line.removeprefix("ExecStart=")
                for line in body.splitlines()
                if line.startswith("ExecStart=")
            )
            tokens = shlex.split(command)
            assert tokens[0] == "/usr/bin/env"
            managed = dict(token.split("=", 1) for token in tokens[1:5])
            assert set(managed) == {
                "RISKIT_SERVING_DIR",
                "RISKIT_SERVING_READER_GID",
                "RISKIT_SERVING_ATTESTATION_PRIVATE_KEY",
                "RISKIT_SERVING_ATTESTATION_PUBLIC_KEY",
            }
            assert tokens[5].endswith("/venv/bin/python")
            # Exercise the actual env executable precedence without running a
            # producer. Print only these nonsecret fixture path/group values.
            environment = {**os.environ, **{key: "/wrong" for key in managed}}
            probe = "printf '%s\\n' " + " ".join(f'"${{{key}}}"' for key in managed)
            shell = shlex.join(tokens[:5] + ["/usr/bin/bash", "-c", probe])
            observed = subprocess.run(
                [bash, "-c", shell],
                env=environment,
                capture_output=True,
                text=True,
                timeout=10,
                check=True,
            )
            assert observed.stdout.splitlines() == list(managed.values())
        if path.suffix == ".path":
            assert "/store/requests/" in body
