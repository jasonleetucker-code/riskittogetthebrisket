"""The one CI apt installer: verified .deb cache, bounded phases, STAB-10 repair, never skips.

Evidence the STAB-10 repair answers: Deploy run 44368941410, hard-gate shard 2
(image ubuntu-26.04 20261103.629) -- ``apt-get update`` fetched only
packages.microsoft.com, so ``tesseract-ocr`` had no install candidate on all
four in-job attempts, while seven sibling shards on the same image passed.

Evidence the CI-1c cache and caps answer: Deploy run 44515440979, hard-gate
shard 3/8 -- 503s and dropped connections on three debs (libgif7,
libleptonica6, libtesseract5) on all four attempts; a re-run passed.

``scripts/ci/install_apt_packages.sh`` runs here for real, against fake
``sudo`` / ``apt-get`` / ``apt-cache`` / ``dpkg`` on PATH (``timeout``,
``sha512sum`` and friends are the real coreutils).  The fakes model a healthy
runner, the broken one, a flaky or hanging network, a bad signature, a restore
that does not help, a genuinely unknown package and a restored cache that is
genuine, tampered with or padded with unlisted files.  The fake mirror is a
directory of .deb files; ``--print-uris`` lists their real size and SHA-512,
so the installer's verification runs against real hashes.

The workflow tests pin that every tesseract install goes through the script,
in resolve -> restore -> install -> save order, that the cache is restored
into a quarantine and saved only on main, and that no inline copy or insecure
apt flag survives anywhere.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "ci" / "install_apt_packages.sh"
WORKFLOWS = ROOT / ".github" / "workflows"
RESTORED = "ci-restored-ubuntu-archive.sources"

# The fake mirror: the four files `tesseract-ocr` pulled on the failing shard
# (three of them are the ones that 503'd in run 44515440979).
DEBS = {
    "libgif7_5.2.2-1_amd64.deb": b"gif" * 400,
    "libleptonica6_1.84.1-4_amd64.deb": b"leptonica" * 300,
    "libtesseract5_5.5.0-1_amd64.deb": b"tesseract-lib" * 250,
    "tesseract-ocr_5.5.0-1_amd64.deb": b"tesseract-ocr" * 200,
}

_FAKES = {
    "sudo": 'exec "$@"\n',
    "dpkg": 'echo "dpkg $*" >> "$STATE/dpkg_calls"\necho amd64\n',
    # update: honours a scripted number of transient failures; an index whose
    # Release says o=Ubuntu exists only on a healthy runner, or once the restored
    # sources file is present (unless the restored archive is unreachable).
    # install: --print-uris lists every mirror .deb not already in the archive
    # directory (as apt does); --download-only copies the missing ones in;
    # --no-download installs only when every .deb is present and genuine.
    "apt-get": r"""
echo "apt-get $*" >> "$STATE/calls"
verb=""; mode=""
for a in "$@"; do
  case "$a" in
    update|install) [[ -n "$verb" ]] || verb="$a";;
    --print-uris) mode=print-uris;;
    --download-only) mode=download;;
    --no-download) mode=no-download;;
  esac
done
take() {  # decrement a scripted counter; true while it was positive
  local left; left=$(cat "$STATE/$1" 2>/dev/null || echo 0)
  if (( left > 0 )); then echo $((left - 1)) > "$STATE/$1"; return 0; fi
  return 1
}
if [[ "$verb" == update ]]; then
  if [[ -e "$STATE/update_badsig" ]]; then
    echo "W: GPG error: http://archive.ubuntu.com/ubuntu resolute InRelease: The following signatures couldn't be verified because the public key is not available: NO_PUBKEY 871920D1991BC93C"
    echo "E: The repository 'http://archive.ubuntu.com/ubuntu resolute InRelease' is not signed."
    exit 100
  fi
  if take update_failures_left; then echo "E: Could not resolve archive.ubuntu.com"; exit 100; fi
  if [[ -e "$STATE/healthy" ]] || { [[ -e "$APT_ETC_DIR/sources.list.d/ci-restored-ubuntu-archive.sources" ]] && [[ ! -e "$STATE/restore_useless" ]]; }; then
    touch "$STATE/ubuntu_index"
  fi
  if [[ -e "$STATE/update_partial" ]]; then
    echo "Err:3 http://security.ubuntu.com/ubuntu resolute-security InRelease"
    echo "W: Failed to fetch http://security.ubuntu.com/ubuntu/dists/resolute-security/InRelease  503  Service Unavailable [IP: 192.0.2.1 80]"
    echo "W: Some index files failed to download. They have been ignored, or old ones used instead."
  fi
  exit 0
fi
if [[ "$verb" == install ]]; then
  [[ -e "$STATE/ubuntu_index" ]] || { echo "E: Unable to locate package" >&2; exit 100; }
  for a in "$@"; do
    if grep -qx -- "$a" "$STATE/unknown" 2>/dev/null; then echo "E: Unable to locate package $a" >&2; exit 100; fi
  done
  mkdir -p "$APT_ARCHIVES_DIR"
  case "$mode" in
    print-uris)
      for f in "$STATE"/repo/*.deb; do
        name=$(basename "$f")
        [[ -e "$APT_ARCHIVES_DIR/$name" ]] && continue
        echo "'http://${MIRROR:-archive.ubuntu.com}/ubuntu/pool/main/x/$name' $name $(stat -c %s "$f") SHA512:$(sha512sum "$f" | cut -d' ' -f1)"
      done
      exit 0;;
    download)
      if take download_hangs_left; then exec sleep 30; fi
      if take download_failures_left; then echo "E: Failed to fetch http://archive.ubuntu.com/ubuntu/pool/main/g/giflib/libgif7.deb  503  Service Unavailable" >&2; exit 100; fi
      for f in "$STATE"/repo/*.deb; do
        name=$(basename "$f")
        if ! cmp -s "$f" "$APT_ARCHIVES_DIR/$name"; then cp "$f" "$APT_ARCHIVES_DIR/$name"; echo "$name" >> "$STATE/downloads"; fi
      done
      exit 0;;
    no-download)
      for f in "$STATE"/repo/*.deb; do
        cmp -s "$f" "$APT_ARCHIVES_DIR/$(basename "$f")" || { echo "E: Unable to fetch some archives" >&2; exit 100; }
      done
      touch "$STATE/installed"; exit 0;;
  esac
  echo "unexpected install invocation: $*" >&2; exit 99
fi
exit 0
""",
    "apt-cache": r"""
[[ "$1" == policy ]] || exit 0
shift
if (( $# == 0 )); then
  echo "Package files:"
  echo " 500 https://packages.microsoft.com/ubuntu/26.04/prod resolute/main amd64 Packages"
  echo "     release o=microsoft-ubuntu-resolute-prod resolute,a=resolute"
  if [[ -e "$STATE/ubuntu_index" ]]; then
    echo " 500 http://archive.ubuntu.com/ubuntu resolute/universe amd64 Packages"
    echo "     release v=26.04,o=Ubuntu,a=resolute,n=resolute,l=Ubuntu,c=universe,b=amd64"
  fi
  exit 0
fi
for pkg in "$@"; do
  if [[ -e "$STATE/ubuntu_index" ]] && ! grep -qx -- "$pkg" "$STATE/unknown" 2>/dev/null; then
    printf '%s:\n  Installed: (none)\n  Candidate: 5.5.0-1\n' "$pkg"
  fi
done
""",
}


@pytest.fixture
def runner(tmp_path):
    bash = shutil.which("bash")
    if bash is None or shutil.which("timeout") is None or shutil.which("sha512sum") is None:
        pytest.skip("bash and GNU coreutils (timeout, sha512sum) are required")
    bin_dir, state, apt_dir = tmp_path / "bin", tmp_path / "state", tmp_path / "etc_apt"
    runner_temp, archives = tmp_path / "runner_temp", tmp_path / "archives"
    for d in (bin_dir, state / "repo", apt_dir / "sources.list.d", runner_temp):
        d.mkdir(parents=True)
    for name, body in _FAKES.items():
        fake = bin_dir / name
        fake.write_text("#!/usr/bin/env bash\n" + body, encoding="utf-8")
        fake.chmod(0o755)
    for name, content in DEBS.items():
        (state / "repo" / name).write_bytes(content)
    os_release = tmp_path / "os-release"
    os_release.write_text(
        'ID=ubuntu\nVERSION_ID="26.04"\nVERSION_CODENAME=resolute\n', encoding="utf-8"
    )
    keyring = tmp_path / "ubuntu-archive-keyring.gpg"
    keyring.write_bytes(b"key")
    gh_output = tmp_path / "github_output"

    def run(*args: str, env: dict[str, str] | None = None):
        full_env = {
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            "HOME": str(tmp_path),
            "STATE": str(state),
            "APT_ETC_DIR": str(apt_dir),
            "OS_RELEASE_FILE": str(os_release),
            "UBUNTU_KEYRING": str(keyring),
            "APT_RETRY_SLEEP_UNIT": "0",
            "APT_ARCHIVES_DIR": str(archives),
            "RUNNER_TEMP": str(runner_temp),
            "GITHUB_OUTPUT": str(gh_output),
            **(env or {}),
        }
        return subprocess.run(
            [bash, str(SCRIPT), *args], env=full_env, capture_output=True, text=True, timeout=120
        )

    def calls() -> list[str]:
        path = state / "calls"
        return path.read_text(encoding="utf-8").splitlines() if path.exists() else []

    def outputs() -> dict[str, str]:
        if not gh_output.exists():
            return {}
        return dict(
            line.split("=", 1) for line in gh_output.read_text(encoding="utf-8").splitlines()
        )

    def downloads() -> list[str]:
        path = state / "downloads"
        return sorted(path.read_text(encoding="utf-8").split()) if path.exists() else []

    return {
        "run": run,
        "calls": calls,
        "outputs": outputs,
        "downloads": downloads,
        "state": state,
        "repo": state / "repo",
        "archives": archives,
        "quarantine": runner_temp / "apt-quarantine",
        "save": runner_temp / "apt-save",
        "gh_output": gh_output,
        "restored": apt_dir / "sources.list.d" / RESTORED,
        "os_release": os_release,
    }


def _verbs(calls: list[str]) -> list[str]:
    """update / resolve (--print-uris) / download (--download-only) / install."""
    out = []
    for call in calls:
        words = call.split()
        if "update" in words:
            out.append("update")
        elif "--print-uris" in words:
            out.append("resolve")
        elif "--download-only" in words:
            out.append("download")
        elif "install" in words:
            out.append("install")
    return out


def _restore_cache(runner, files: dict[str, bytes] | None = None) -> Path:
    """What actions/cache/restore would leave in the quarantine directory."""
    quarantine = runner["quarantine"]
    quarantine.mkdir(parents=True, exist_ok=True)
    for name, content in (DEBS if files is None else files).items():
        (quarantine / name).write_bytes(content)
    return quarantine


def _dir_contents(path: Path) -> dict[str, bytes]:
    return {p.name: p.read_bytes() for p in sorted(path.iterdir())} if path.exists() else {}


# ── update phase, STAB-10 repair, failure classes ────────────────────


def test_healthy_runner_installs_once_and_is_never_modified(runner):
    (runner["state"] / "healthy").touch()
    result = runner["run"]("tesseract-ocr")
    assert result.returncode == 0, result.stdout + result.stderr
    assert _verbs(runner["calls"]()) == ["update", "resolve", "download", "install"]
    assert not runner["restored"].exists()
    assert "::warning" not in result.stdout
    assert runner["downloads"]() == sorted(DEBS)
    # The install itself never touches the network.
    install_call = runner["calls"]()[-1]
    assert "--no-download" in install_call.split()


def test_every_network_phase_carries_timeouts_and_skips_translations(runner):
    (runner["state"] / "healthy").touch()
    assert runner["run"]("tesseract-ocr").returncode == 0
    for call in runner["calls"]():
        for option in (
            "Acquire::Retries=3",
            "Acquire::http::Timeout=30",
            "Acquire::https::Timeout=30",
            "Acquire::Languages=none",
        ):
            assert option in call.split(), (option, call)


def test_runner_with_no_ubuntu_archive_is_repaired_for_its_own_codename(runner):
    # The 44368941410 shard-2 runner: update succeeds, Microsoft only.
    result = runner["run"]("tesseract-ocr")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "::warning title=Runner apt sources repaired::" in result.stdout
    assert (runner["state"] / "installed").exists()
    assert _verbs(runner["calls"]()) == ["update", "update", "resolve", "download", "install"]
    sources = runner["restored"].read_text(encoding="utf-8")
    blocks = [b for b in sources.strip().split("\n\n")]
    assert len(blocks) == 2
    assert "URIs: http://archive.ubuntu.com/ubuntu" in blocks[0]
    assert "Suites: resolute resolute-updates resolute-backports" in blocks[0]
    assert "URIs: http://security.ubuntu.com/ubuntu" in blocks[1]
    assert "Suites: resolute-security" in blocks[1]
    for block in blocks:
        assert "Types: deb" in block
        assert "Components: main universe" in block
        assert re.search(r"^Signed-By: \S+ubuntu-archive-keyring\.gpg$", block, re.M)


def test_transient_update_failures_keep_the_bounded_retry(runner):
    (runner["state"] / "healthy").touch()
    (runner["state"] / "update_failures_left").write_text("2", encoding="utf-8")
    result = runner["run"]("tesseract-ocr")
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.count("::warning::apt attempt") == 2
    assert not runner["restored"].exists()


def test_a_restore_that_does_not_help_fails_loudly_and_says_re_run(runner):
    (runner["state"] / "restore_useless").touch()
    result = runner["run"]("tesseract-ocr")
    assert result.returncode == 1
    assert "::error title=Runner apt sources broken::" in result.stdout
    assert "restoring the standard Ubuntu archive did not make" in result.stdout
    assert "re-run the job" in result.stdout
    assert "Nothing was skipped" in result.stdout
    # One restore, then the bounded attempts: never an unbounded loop.
    assert result.stdout.count("Runner apt sources repaired") == 1
    verbs = _verbs(runner["calls"]())
    assert verbs.count("update") == 5
    assert verbs == ["update"] * 5


def test_unknown_package_on_a_healthy_runner_is_not_blamed_on_the_runner(runner):
    (runner["state"] / "healthy").touch()
    (runner["state"] / "unknown").write_text("no-such-package\n", encoding="utf-8")
    result = runner["run"]("tesseract-ocr", "no-such-package")
    assert result.returncode == 1
    assert "Runner apt sources broken" not in result.stdout
    assert not runner["restored"].exists()
    assert (
        "::error::apt install of tesseract-ocr no-such-package failed after 4 attempts "
        "(no install candidate for: no-such-package)."
    ) in result.stdout


def test_a_runner_that_cannot_name_its_codename_is_not_guessed(runner):
    runner["os_release"].write_text("ID=debian\n", encoding="utf-8")
    result = runner["run"]("tesseract-ocr")
    assert result.returncode == 1
    assert "Cannot restore Ubuntu sources" in result.stdout
    assert "::error title=Runner apt sources broken::" in result.stdout
    assert not runner["restored"].exists()


@pytest.mark.parametrize("args", [(), ("--resolve",)])
def test_no_packages_is_a_usage_error(runner, args):
    result = runner["run"](*args)
    assert result.returncode == 2
    assert "usage" in result.stderr


def test_an_unknown_option_is_a_usage_error_not_a_package(runner):
    result = runner["run"]("--force", "tesseract-ocr")
    assert result.returncode == 2
    assert runner["calls"]() == []


@pytest.mark.parametrize("cache_restored", [False, True])
def test_a_missing_index_exits_1_and_never_installs_from_the_cache(runner, cache_restored):
    # Every update fails: there is no signed index to verify anything against,
    # so even a genuine restored cache must not be installed.
    (runner["state"] / "healthy").touch()
    (runner["state"] / "update_failures_left").write_text("99", encoding="utf-8")
    if cache_restored:
        _restore_cache(runner)
    result = runner["run"]("tesseract-ocr")
    assert result.returncode == 1
    assert "::error title=apt index unreachable::" in result.stdout
    assert "index unreachable; nothing installed, nothing skipped" in result.stdout
    assert _verbs(runner["calls"]()) == ["update"] * 4
    assert not (runner["state"] / "installed").exists()
    assert _dir_contents(runner["archives"]) == {}
    dpkg_calls = runner["state"] / "dpkg_calls"
    calls = dpkg_calls.read_text(encoding="utf-8") if dpkg_calls.exists() else ""
    assert "-i" not in calls.split() and "--install" not in calls


def test_resolve_with_a_missing_index_publishes_no_cache_key(runner):
    (runner["state"] / "healthy").touch()
    (runner["state"] / "update_failures_left").write_text("99", encoding="utf-8")
    result = runner["run"]("--resolve", "tesseract-ocr")
    assert result.returncode == 1
    assert "index unreachable; nothing installed, nothing skipped" in result.stdout
    assert runner["outputs"]() == {}


def test_a_bad_signature_is_its_own_error_and_is_never_bypassed(runner):
    (runner["state"] / "healthy").touch()
    (runner["state"] / "update_badsig").touch()
    _restore_cache(runner)
    result = runner["run"]("tesseract-ocr")
    assert result.returncode == 1
    assert "::error title=apt index integrity failure::" in result.stdout
    assert "NO_PUBKEY" in result.stdout
    assert "failed signature or hash verification" in result.stdout
    assert "index unreachable; nothing installed, nothing skipped" in result.stdout
    assert _verbs(runner["calls"]()) == ["update"] * 4
    assert not (runner["state"] / "installed").exists()


def test_a_partially_fetched_index_warns_and_names_the_failed_index(runner):
    (runner["state"] / "healthy").touch()
    (runner["state"] / "update_partial").touch()
    result = runner["run"]("tesseract-ocr")
    assert result.returncode == 0, result.stdout + result.stderr
    assert (
        "::warning title=apt index partially unavailable::attempt 1/4: failed to fetch "
        "http://security.ubuntu.com/ubuntu/dists/resolute-security/InRelease;"
    ) in result.stdout
    assert (runner["state"] / "installed").exists()


# ── resolve phase: the cache key ─────────────────────────────────────


def test_resolve_publishes_a_content_addressed_key_and_installs_nothing(runner):
    (runner["state"] / "healthy").touch()
    result = runner["run"]("--resolve", "tesseract-ocr")
    assert result.returncode == 0, result.stdout + result.stderr
    out = runner["outputs"]()
    assert out["restore-prefix"] == "apt-debs-v1-resolute-amd64-"
    assert re.fullmatch(r"apt-debs-v1-resolute-amd64-[0-9a-f]{64}", out["key"])
    assert out["debs"] == str(len(DEBS))
    # The key is sha256 over (file, size, SHA512, hash) of every .deb, sorted.
    lines = "".join(
        f"{name}\t{len(content)}\tSHA512\t{hashlib.sha512(content).hexdigest()}\n"
        for name, content in sorted(DEBS.items())
    )
    assert out["key"] == "apt-debs-v1-resolute-amd64-" + hashlib.sha256(lines.encode()).hexdigest()
    assert _verbs(runner["calls"]()) == ["update", "resolve"]
    assert runner["downloads"]() == []
    assert not (runner["state"] / "installed").exists()


def test_the_key_ignores_the_mirror_but_follows_the_signed_content(runner):
    (runner["state"] / "healthy").touch()
    keys = []
    for mirror in ("us-east-2.ec2.archive.ubuntu.com", "azure.archive.ubuntu.com"):
        runner["gh_output"].unlink(missing_ok=True)
        assert runner["run"]("--resolve", "tesseract-ocr", env={"MIRROR": mirror}).returncode == 0
        keys.append(runner["outputs"]()["key"])
    assert keys[0] == keys[1]
    (runner["repo"] / "libgif7_5.2.2-1_amd64.deb").write_bytes(b"a new upload")
    runner["gh_output"].unlink()
    assert runner["run"]("--resolve", "tesseract-ocr").returncode == 0
    assert runner["outputs"]()["key"] != keys[0]


# ── verify / download / stage / install ──────────────────────────────


def test_a_verified_cache_hit_downloads_nothing_and_reuses_the_resolved_index(runner):
    (runner["state"] / "healthy").touch()
    assert runner["run"]("--resolve", "tesseract-ocr").returncode == 0
    _restore_cache(runner)
    result = runner["run"]("tesseract-ocr")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "::warning" not in result.stdout
    assert f"reused {len(DEBS)} verified .deb file(s)" in result.stdout
    # No second `apt-get update` in the install step, and nothing downloaded.
    assert _verbs(runner["calls"]()) == ["update", "resolve", "resolve", "download", "install"]
    assert runner["downloads"]() == []
    assert (runner["state"] / "installed").exists()
    assert runner["outputs"]()["saved"] == str(len(DEBS))
    assert runner["outputs"]()["reused"] == str(len(DEBS))
    assert _dir_contents(runner["quarantine"]) == dict(sorted(DEBS.items()))


def test_a_cache_miss_downloads_everything_and_stages_it_for_the_save(runner):
    (runner["state"] / "healthy").touch()
    assert runner["run"]("--resolve", "tesseract-ocr").returncode == 0
    result = runner["run"]("tesseract-ocr")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "nothing restored" in result.stdout
    assert runner["downloads"]() == sorted(DEBS)
    assert runner["outputs"]()["saved"] == str(len(DEBS))
    # The save step names the restore's path; it now holds the verified set.
    assert _dir_contents(runner["quarantine"]) == dict(sorted(DEBS.items()))
    assert not runner["save"].exists()


def test_a_hash_mismatch_is_discarded_then_downloaded_and_never_saved(runner):
    (runner["state"] / "healthy").touch()
    assert runner["run"]("--resolve", "tesseract-ocr").returncode == 0
    genuine = dict(DEBS)
    tampered_name = "libleptonica6_1.84.1-4_amd64.deb"
    tampered = bytearray(genuine[tampered_name])
    tampered[0] ^= 0xFF  # same size, different bytes
    quarantine = _restore_cache(
        runner,
        {
            tampered_name: bytes(tampered),
            "libtesseract5_5.5.0-1_amd64.deb": genuine["libtesseract5_5.5.0-1_amd64.deb"][:-1],
            "tesseract-ocr_5.5.0-1_amd64.deb": genuine["tesseract-ocr_5.5.0-1_amd64.deb"],
            "evil_1.0_amd64.deb": b"not in the signed index",
        },
    )
    # A symlink is never followed, even to the genuine bytes.
    (quarantine / "libgif7_5.2.2-1_amd64.deb").symlink_to(
        runner["repo"] / "libgif7_5.2.2-1_amd64.deb"
    )
    result = runner["run"]("tesseract-ocr")
    assert result.returncode == 0, result.stdout + result.stderr
    for name in (tampered_name, "libtesseract5_5.5.0-1_amd64.deb", "libgif7_5.2.2-1_amd64.deb"):
        assert f"::warning title=apt cache entry discarded::{name}:" in result.stdout
    assert runner["downloads"]() == sorted(
        [tampered_name, "libtesseract5_5.5.0-1_amd64.deb", "libgif7_5.2.2-1_amd64.deb"]
    )
    assert "reused 1 verified .deb file(s)" in result.stdout
    # apt read only genuine bytes; the unlisted file never reached it.
    assert _dir_contents(runner["archives"]) == dict(sorted(genuine.items()))
    assert (runner["state"] / "installed").exists()
    # What the save uploads is exactly the verified set: no tampered bytes, no
    # symlink, no unlisted file.
    assert _dir_contents(runner["quarantine"]) == dict(sorted(genuine.items()))
    assert not any(p.is_symlink() for p in runner["quarantine"].iterdir())


def test_install_without_a_prior_resolve_still_updates_first(runner):
    (runner["state"] / "healthy").touch()
    _restore_cache(runner)
    result = runner["run"]("tesseract-ocr")
    assert result.returncode == 0, result.stdout + result.stderr
    assert _verbs(runner["calls"]()) == ["update", "resolve", "download", "install"]
    assert runner["downloads"]() == []


def test_a_killed_download_is_retried(runner):
    # The fake download hangs once; the real `timeout` stops it.
    (runner["state"] / "healthy").touch()
    (runner["state"] / "download_hangs_left").write_text("1", encoding="utf-8")
    result = runner["run"](
        "tesseract-ocr", env={"APT_DOWNLOAD_TIMEOUT": "1", "APT_KILL_AFTER": "1"}
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert (
        "::warning::apt download attempt 1/4 did not finish within 1s and was stopped "
        "(dpkg had not run)"
    ) in result.stdout
    assert _verbs(runner["calls"]()).count("download") == 2
    assert (runner["state"] / "installed").exists()


def test_failed_downloads_are_retried_without_a_new_update(runner):
    (runner["state"] / "healthy").touch()
    (runner["state"] / "download_failures_left").write_text("2", encoding="utf-8")
    result = runner["run"]("tesseract-ocr")
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.count("::warning::apt download attempt") == 2
    assert _verbs(runner["calls"]()) == [
        "update",
        "resolve",
        "download",
        "download",
        "download",
        "install",
    ]


def test_downloads_that_never_succeed_fail_without_installing(runner):
    (runner["state"] / "healthy").touch()
    (runner["state"] / "download_failures_left").write_text("99", encoding="utf-8")
    result = runner["run"]("tesseract-ocr")
    assert result.returncode == 1
    assert "::error title=apt download failed::" in result.stdout
    assert "nothing installed, nothing skipped" in result.stdout
    verbs = _verbs(runner["calls"]())
    assert verbs.count("download") == 4
    assert "install" not in verbs
    assert not (runner["state"] / "installed").exists()
    assert "saved" not in runner["outputs"]()


# ── the installer's own text ─────────────────────────────────────────

# Every way of telling apt to accept an unsigned, unverifiable or expired index
# or package.  Matched case-insensitively (apt option names are).
INSECURE_APT = {
    r"--allow-unauthenticated": "apt-get --allow-unauthenticated install x",
    r"allow-?unauthenticated": "-o APT::Get::AllowUnauthenticated=true",
    r"allow-?insecure-?repositories": "-o Acquire::AllowInsecureRepositories=true",
    r"allow-?downgrade-?to-?insecure-?repositories": "Acquire::AllowDowngradeToInsecureRepositories",
    r"--allow-insecure-repositories": "apt-get update --allow-insecure-repositories",
    r"trusted\s*[:=]\s*yes": "deb [trusted=yes] http://x y z",
    r"check-valid-until": "-o Acquire::Check-Valid-Until=false",
    r"--force-yes": "apt-get install --force-yes x",
}


def test_the_insecure_flag_patterns_are_not_vacuous():
    for pattern, example in INSECURE_APT.items():
        assert re.search(pattern, example, re.I), pattern
    assert re.search(r"trusted\s*[:=]\s*yes", "Trusted: yes", re.I)


@pytest.mark.parametrize(
    "path",
    [SCRIPT, *sorted(WORKFLOWS.glob("*.yml")), *sorted(WORKFLOWS.glob("*.yaml"))],
    ids=lambda p: p.name,
)
def test_no_insecure_apt_flag_in_the_installer_or_any_workflow(path):
    text = path.read_text(encoding="utf-8")
    found = [p for p in INSECURE_APT if re.search(p, text, re.I)]
    assert found == [], f"{path.name} weakens apt's signature checks: {found}"


def test_the_installer_never_installs_a_deb_directly_or_caches_the_index():
    text = SCRIPT.read_text(encoding="utf-8")
    assert not re.search(r"\bdpkg\s+(-i|--install|--unpack)\b", text)
    assert "/var/lib/apt/lists" not in text
    assert "--no-download" in text and "--download-only" in text and "--print-uris" in text
    assert re.search(r"sudo timeout --kill-after=", text), "the cap must run under sudo"
    assert 'QUARANTINE="${APT_QUARANTINE_DIR:-${WORK_ROOT}/apt-quarantine}"' in text
    assert 'SAVE_DIR="${APT_SAVE_DIR:-${WORK_ROOT}/apt-save}"' in text


# ── workflow wiring ──────────────────────────────────────────────────

RESOLVE_STEP = "Resolve tesseract-ocr apt packages (cache key)"
RESTORE_STEP = "Restore verified apt package cache"
INSTALL_STEP = "Install tesseract-ocr (screenshot import OCR tests)"
SAVE_STEP = "Save verified apt package cache"
QUARANTINE_PATH = "${{ runner.temp }}/apt-quarantine"
CALLERS = {
    ("pr-validation.yml", "backend"): "bash scripts/ci/install_apt_packages.sh tesseract-ocr",
    ("release-candidate.yml", "hard-gate"): "bash scripts/ci/install_apt_packages.sh tesseract-ocr",
    ("deploy.yml", "hard-gate"): 'bash "${INSTALLER}" tesseract-ocr',
}
RESOLVE_CALLERS = {
    ("pr-validation.yml", "backend"): (
        "bash scripts/ci/install_apt_packages.sh --resolve tesseract-ocr"
    ),
    ("release-candidate.yml", "hard-gate"): (
        "bash scripts/ci/install_apt_packages.sh --resolve tesseract-ocr"
    ),
    ("deploy.yml", "hard-gate"): 'bash "${INSTALLER}" --resolve tesseract-ocr',
}


def _job(workflow: str, job: str) -> dict:
    doc = yaml.safe_load((WORKFLOWS / workflow).read_text(encoding="utf-8"))
    return doc["jobs"][job]


def _named(job: dict, name: str) -> dict:
    matches = [s for s in job["steps"] if s.get("name") == name]
    assert len(matches) == 1, f"expected exactly one step named {name!r}"
    return matches[0]


@pytest.mark.parametrize(("workflow", "job"), sorted(CALLERS))
def test_every_tesseract_install_goes_through_the_shared_installer(workflow, job):
    for name, calls in ((INSTALL_STEP, CALLERS), (RESOLVE_STEP, RESOLVE_CALLERS)):
        step = _named(_job(workflow, job), name)
        run = step["run"]
        assert calls[(workflow, job)] in run
        assert "apt-get" not in run, "the inline apt copy must not come back"
        assert "continue-on-error" not in step, "the install is a gate input; never skipped"
        assert step["timeout-minutes"] == 20


@pytest.mark.parametrize(("workflow", "job"), sorted(CALLERS))
def test_the_cache_is_resolved_restored_installed_then_saved_on_main_only(workflow, job):
    steps = _job(workflow, job)["steps"]
    names = [s.get("name") for s in steps]
    i = names.index(RESOLVE_STEP)
    assert names[i : i + 4] == [RESOLVE_STEP, RESTORE_STEP, INSTALL_STEP, SAVE_STEP]
    resolve, restore, install, save = steps[i : i + 4]
    assert resolve["id"] == "apt-resolve" and install["id"] == "apt-install"
    # Restore lands in the quarantine; the installer copies only files it
    # verified against the signed index into apt's archive directory.
    assert restore["uses"] == "actions/cache/restore@v6"
    assert restore["id"] == "apt-cache"
    assert restore["with"] == {
        "path": QUARANTINE_PATH,
        "key": "${{ steps.apt-resolve.outputs.key }}",
        "restore-keys": "${{ steps.apt-resolve.outputs.restore-prefix }}",
    }
    # A cache outage costs a download, never the gate.
    assert restore["continue-on-error"] is True
    # Save: same path (actions/cache versions an entry by its path list), the
    # resolved key, main only, only on a miss, only when something was staged.
    assert save["uses"] == "actions/cache/save@v6"
    assert save["with"] == {"path": QUARANTINE_PATH, "key": "${{ steps.apt-resolve.outputs.key }}"}
    assert save["continue-on-error"] is True
    condition = save["if"]
    assert "github.ref == 'refs/heads/main'" in condition
    assert "steps.apt-cache.outputs.cache-hit != 'true'" in condition
    assert "steps.apt-install.outputs.saved != '0'" in condition
    for step in (restore, save):
        assert 0 < step["timeout-minutes"] <= 20


def test_no_workflow_caches_apt_state_any_other_way():
    # Only the split restore/save pair, only the quarantine path: never apt's
    # archive directory, never its index lists, never the combined action
    # (whose post-step would save unverified state).
    for path in sorted(WORKFLOWS.glob("*.yml")):
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for job in (doc.get("jobs") or {}).values():
            for step in job.get("steps") or []:
                uses = str(step.get("uses") or "")
                if not uses.startswith("actions/cache"):
                    continue
                cached = str((step.get("with") or {}).get("path", ""))
                assert "/var/lib/apt" not in cached and "/var/cache/apt" not in cached
                if "apt" in cached:
                    assert uses in ("actions/cache/restore@v6", "actions/cache/save@v6"), uses
                    assert cached == QUARANTINE_PATH, (path.name, cached)


def test_deploy_hard_gate_reads_the_installer_from_the_workflow_commit():
    # The hard gate checks out the TARGET tree; a rollback target can predate
    # the script, so the installer must come from the workflow commit -- in the
    # install step too, so a restored cache cannot hand it a different copy.
    job = _job("deploy.yml", "hard-gate")
    checkout = next(s for s in job["steps"] if s.get("name") == "Checkout")
    assert checkout["with"]["fetch-depth"] == 0
    for name in (RESOLVE_STEP, INSTALL_STEP):
        step = _named(job, name)
        assert 'git show "${GITHUB_SHA}:scripts/ci/install_apt_packages.sh"' in step["run"]


def test_no_workflow_inlines_a_tesseract_apt_install():
    offenders = []
    for path in sorted(WORKFLOWS.glob("*.yml")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if "apt-get" in line and "install" in line and "tesseract" in line:
                offenders.append(f"{path.name}: {line.strip()}")
    assert offenders == []


# ── Playwright mode (CI-1d) ──────────────────────────────────────────
#
# Playwright 1.64.1 (the version package-lock.json pins; read from
# playwright-core/lib/coreBundle.js and run locally) answers
# `install-deps --dry-run <browsers>` by running `apt-get install -s` and
# printing "Missing system dependencies (N):" + two-space-indented sorted
# package names with exit 1, or "All system dependencies are installed." with
# exit 0.  A failing simulation (stale lists) is an Error with exit 1 and no
# header.  The fake below reproduces those three shapes.

MISSING_OUTPUT = "Missing system dependencies (3):\n  libgbm1\n  libwoff1\n  libxkbcommon0\n"
INSTALLED_OUTPUT = "All system dependencies are installed.\n"

_FAKE_PLAYWRIGHT = r"""#!/usr/bin/env bash
echo "playwright $*" >> "$STATE/pw_calls"
case "$1" in
  install-deps)
    [[ -e "$STATE/pw_dry_sleep" ]] && sleep "$(cat "$STATE/pw_dry_sleep")"
    # Scripted answers win; otherwise model Playwright: missing until the apt
    # install ran, then installed (unless a library is still missing).
    if [[ -e "$STATE/pw_dry_output" ]]; then
      cat "$STATE/pw_dry_output"; exit "$(cat "$STATE/pw_dry_rc")"
    fi
    if [[ -e "$STATE/installed" && ! -e "$STATE/pw_still_missing" ]]; then
      cat "$STATE/pw_installed_output"; exit 0
    fi
    cat "$STATE/pw_missing_output"; exit 1;;
  install)
    [[ -e "$STATE/pw_install_sleep" ]] && sleep "$(cat "$STATE/pw_install_sleep")"
    exit "$(cat "$STATE/pw_install_rc" 2>/dev/null || echo 0)";;
esac
exit 99
"""


@pytest.fixture
def pw(runner, tmp_path):
    fake = tmp_path / "bin" / "fake-playwright"
    fake.write_text(_FAKE_PLAYWRIGHT, encoding="utf-8")
    fake.chmod(0o755)
    state = runner["state"]
    (state / "healthy").touch()
    (state / "pw_missing_output").write_text(MISSING_OUTPUT, encoding="utf-8")
    (state / "pw_installed_output").write_text(INSTALLED_OUTPUT, encoding="utf-8")

    def run(*browsers: str, env: dict | None = None):
        return runner["run"](
            "--playwright", *browsers, env={"PLAYWRIGHT_CMD": str(fake), **(env or {})}
        )

    def pw_calls() -> list[str]:
        path = state / "pw_calls"
        return path.read_text(encoding="utf-8").splitlines() if path.exists() else []

    def script(output: str, rc: int) -> None:
        (state / "pw_dry_output").write_text(output, encoding="utf-8")
        (state / "pw_dry_rc").write_text(str(rc), encoding="utf-8")

    return {**runner, "pw_run": run, "pw_calls": pw_calls, "script": script}


def _apt_install_words(calls: list[str]) -> list[str]:
    return next(c for c in calls if "--no-download" in c.split()).split()


def test_playwright_missing_packages_go_through_the_verified_install_in_order(pw):
    result = pw["pw_run"]("chromium", "webkit")
    assert result.returncode == 0, result.stdout + result.stderr
    # One update, the same resolve -> download -> no-network install as every
    # other caller, with exactly the packages Playwright's own dry-run named.
    assert _verbs(pw["calls"]()) == ["update", "resolve", "download", "install"]
    words = _apt_install_words(pw["calls"]())
    assert words[-3:] == ["libgbm1", "libwoff1", "libxkbcommon0"]
    # dry-run -> (apt) -> browsers only -> dry-run proving nothing is missing.
    assert [c.split(" ", 1)[1] for c in pw["pw_calls"]()] == [
        "install-deps --dry-run chromium webkit",
        "install chromium webkit",
        "install-deps --dry-run chromium webkit",
    ]
    assert "--with-deps" not in "".join(pw["pw_calls"]())
    assert pw["downloads"]() == sorted(DEBS)


def test_playwright_with_nothing_missing_installs_browsers_without_apt_install(pw):
    pw["script"](INSTALLED_OUTPUT, 0)
    result = pw["pw_run"]("chromium")
    assert result.returncode == 0, result.stdout + result.stderr
    assert _verbs(pw["calls"]()) == ["update"]
    assert [c.split(" ", 1)[1] for c in pw["pw_calls"]()] == [
        "install-deps --dry-run chromium",
        "install chromium",
        "install-deps --dry-run chromium",
    ]


def test_playwright_upgrade_that_adds_a_library_fails_loudly_after_the_install(pw):
    (pw["state"] / "pw_still_missing").touch()
    result = pw["pw_run"]("chromium")
    assert result.returncode == 1
    assert "Playwright dependencies still missing" in result.stdout
    assert "libgbm1" in result.stdout


def test_playwright_browser_download_failure_is_a_failure(pw):
    (pw["state"] / "pw_install_rc").write_text("1", encoding="utf-8")
    result = pw["pw_run"]("chromium")
    assert result.returncode == 1
    assert "Playwright browser install failed" in result.stdout


@pytest.mark.parametrize(
    ("output", "rc"),
    [
        # a failing `apt-get install -s` (stale lists): Playwright throws
        ("Failed to install browser dependencies\nE: Unable to locate package libgtk-4-1\n", 1),
        # header count disagrees with the list
        ("Missing system dependencies (4):\n  libgbm1\n  libwoff1\n", 1),
        # header with an empty list
        ("Missing system dependencies (0):\n", 1),
        # trailing noise after the list
        ("Missing system dependencies (1):\n  libgbm1\nsomething else\n", 1),
        # a package name that is not a package name
        ("Missing system dependencies (1):\n  libgbm1;rm\n", 1),
        # exit 0 without the all-installed sentence
        ("", 0),
        ("Missing system dependencies (1):\n  libgbm1\n", 0),
        # all-installed sentence with a failing exit code
        (INSTALLED_OUTPUT, 1),
        # any other exit code
        (MISSING_OUTPUT, 2),
    ],
)
def test_playwright_unexpected_dry_run_output_is_never_read_as_nothing_to_do(pw, output, rc):
    pw["script"](output, rc)
    result = pw["pw_run"]("chromium")
    assert result.returncode == 1, result.stdout
    assert "Playwright dependency check unusable" in result.stdout
    # It never proceeds to an install or to the browsers.
    assert _verbs(pw["calls"]()) == ["update"]
    assert all("playwright install " not in c for c in pw["pw_calls"]())


def test_playwright_with_an_unreachable_index_installs_nothing(pw):
    (pw["state"] / "healthy").unlink()
    (pw["state"] / "update_failures_left").write_text("99", encoding="utf-8")
    result = pw["pw_run"]("chromium")
    assert result.returncode == 1
    assert "index unreachable; nothing installed, nothing skipped" in result.stdout
    assert pw["pw_calls"]() == []


@pytest.mark.parametrize(
    "args",
    [
        ["--playwright"],
        ["--playwright", "--resolve"],
        ["--playwright", "chromium; rm"],
        ["--playwright", "Chromium"],
    ],
)
def test_playwright_usage_errors(runner, args):
    assert runner["run"](*args).returncode == 2


PLAYWRIGHT_STEPS = {
    ("e2e.yml", "e2e"): (
        "Install Playwright browsers + system deps (chromium, webkit)",
        "--playwright chromium webkit",
    ),
    ("prod-e2e-smoke.yml", "smoke"): (
        "Install Playwright chromium",
        "--playwright chromium",
    ),
    ("v1-authenticated-verification.yml", "verify"): None,
}


def _code_lines(run: str) -> str:
    return "\n".join(line for line in run.splitlines() if not line.lstrip().startswith("#"))


def _playwright_runs():
    """Every (workflow, job, step) whose run script mentions Playwright installs."""
    found = []
    for path in sorted(WORKFLOWS.glob("*.yml")):
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for job_id, job in (doc.get("jobs") or {}).items():
            for step in job.get("steps") or []:
                run = _code_lines(str(step.get("run") or ""))
                if (
                    re.search(r"playwright\s+install\b", run)
                    or "install_apt_packages.sh --playwright" in run
                    or '"${INSTALLER}" --playwright' in run
                ):
                    found.append((path.name, job_id, step))
    return found


@pytest.mark.parametrize(
    "workflow", ["e2e.yml", "prod-e2e-smoke.yml", "v1-authenticated-verification.yml"]
)
def test_playwright_workflows_use_the_shared_installer_and_never_with_deps(workflow):
    steps = [(j, s) for w, j, s in _playwright_runs() if w == workflow]
    assert steps, workflow
    doc = yaml.safe_load((WORKFLOWS / workflow).read_text(encoding="utf-8"))
    for job_id, step in steps:
        run = _code_lines(step["run"])
        assert re.search(
            r'bash (scripts/ci/install_apt_packages\.sh|"\$\{INSTALLER\}") --playwright chromium',
            run,
        )
        assert not re.search(r"npx playwright install\b", run), "browsers come from the installer"
        assert "continue-on-error" not in step
        # A step cap at or above the job's own budget can never fire: the job is
        # cancelled first and the failure-handling steps never run.
        assert 0 < step["timeout-minutes"] < doc["jobs"][job_id]["timeout-minutes"]


def test_no_workflow_uses_with_deps_or_a_bare_install_deps():
    offenders = []
    for path in sorted(WORKFLOWS.glob("*.yml")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.lstrip().startswith("#"):
                continue
            if "--with-deps" in line or re.search(r"playwright\s+install-deps", line):
                offenders.append(f"{path.name}: {line.strip()}")
    assert offenders == []


def test_e2e_installs_both_browsers_in_one_step():
    job = _job("e2e.yml", "e2e")
    name, flag = PLAYWRIGHT_STEPS[("e2e.yml", "e2e")]
    step = _named(job, name)
    assert f"bash scripts/ci/install_apt_packages.sh {flag}" in step["run"]
    assert step["timeout-minutes"] == 20
    installs = [
        s
        for s in job["steps"]
        if re.search(r"playwright\s+install\b|--playwright", _code_lines(str(s.get("run", ""))))
    ]
    assert installs == [step], "one step installs both engines"


def test_prod_smoke_installs_through_the_shared_installer():
    name, flag = PLAYWRIGHT_STEPS[("prod-e2e-smoke.yml", "smoke")]
    job = _job("prod-e2e-smoke.yml", "smoke")
    step = _named(job, name)
    assert f"bash scripts/ci/install_apt_packages.sh {flag}" in step["run"]
    assert step["timeout-minutes"] < job["timeout-minutes"]


def test_v1_reads_the_installer_from_the_workflow_commit():
    """V1 checks out the DEPLOYED sha while its YAML comes from main, so a deploy
    that predates --playwright must still get an installer that has it."""
    doc = yaml.safe_load(
        (WORKFLOWS / "v1-authenticated-verification.yml").read_text(encoding="utf-8")
    )
    runs = [
        _code_lines(str(s.get("run") or ""))
        for job in doc["jobs"].values()
        for s in job.get("steps") or []
        if "--playwright" in str(s.get("run") or "")
    ]
    assert len(runs) == 2
    for run in runs:
        assert 'git fetch -q --no-tags --depth=1 origin "${GITHUB_SHA}"' in run
        assert 'git show "${GITHUB_SHA}:scripts/ci/install_apt_packages.sh"' in run
        assert 'bash "${INSTALLER}" --playwright chromium' in run
        assert "bash scripts/ci/install_apt_packages.sh" not in run


def test_playwright_default_command_never_downloads_an_unpinned_playwright():
    """`npx playwright` with no local install fetches whatever npm serves; the
    default is `npx --no playwright`, which fails instead."""
    text = (ROOT / "scripts/ci/install_apt_packages.sh").read_text(encoding="utf-8")
    assert 'PLAYWRIGHT_CMD="${PLAYWRIGHT_CMD:-npx --no playwright}"' in text


@pytest.mark.parametrize(
    ("sleep_file", "env", "title"),
    [
        ("pw_install_sleep", {"PW_INSTALL_TIMEOUT": "1"}, "Playwright browser install timed out"),
        ("pw_dry_sleep", {"PW_DRY_TIMEOUT": "1"}, "Playwright dependency check timed out"),
    ],
)
def test_a_hung_playwright_call_ends_with_a_named_error(pw, sleep_file, env, title):
    import time

    (pw["state"] / sleep_file).write_text("30", encoding="utf-8")
    started = time.monotonic()
    result = pw["pw_run"]("chromium", env=env)
    assert result.returncode != 0
    assert title in result.stdout + result.stderr
    assert time.monotonic() - started < 25, "the timeout fired, not the sleep"
