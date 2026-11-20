#!/usr/bin/env bash
# Install apt packages on a GitHub-hosted runner, repairing a runner whose apt
# sources carry no Ubuntu archive (STAB-10, owner directive 2026-11-19).
#
# Usage: bash scripts/ci/install_apt_packages.sh <package> [<package> ...]
#
# The ONE copy of the CI apt install: PR Validation, Release Candidate and the
# Deploy Production hard gate all call it.  Nothing here skips the install or
# weakens a gate: the script installs every requested package or exits 1 with
# an ::error naming the cause.
#
# Why the repair exists.  Deploy run 44368941410, hard-gate shard 2 (image
# ubuntu-26.04 20261103.629): `apt-get update` fetched only
# packages.microsoft.com -- no /etc/apt/apt-mirrors.txt, no Ubuntu archive --
# so `apt-get install tesseract-ocr` answered "Unable to locate package" on all
# four in-job attempts, while seven sibling shards on the SAME image version
# fetched us-east-2.ec2.archive.ubuntu.com + security.ubuntu.com and passed.
# Retrying on a runner with no Ubuntu source can never help.  So when a
# requested package has no install candidate AND apt holds no Ubuntu index at
# all, this restores the standard Ubuntu archive for the runner's OWN codename
# (from /etc/os-release) and tries again.  A runner that has an Ubuntu index is
# never modified: a missing candidate there is a real package problem.
#
# Transient network failures keep the bounded retry the inline copies had (4
# attempts, 10/20/30 s back-off; apt's own Acquire::Retries does not cover a
# failed name resolution).
#
# Test seams (tests/deploy/test_install_apt_packages.py): APT_ETC_DIR,
# OS_RELEASE_FILE, UBUNTU_KEYRING and APT_RETRY_SLEEP_UNIT.  The defaults are
# the real runner paths.

set -Eeuo pipefail

if (( $# == 0 )); then
  echo "usage: $0 <package> [<package> ...]" >&2
  exit 2
fi

PACKAGES=("$@")
APT_ETC_DIR="${APT_ETC_DIR:-/etc/apt}"
OS_RELEASE_FILE="${OS_RELEASE_FILE:-/etc/os-release}"
UBUNTU_KEYRING="${UBUNTU_KEYRING:-/usr/share/keyrings/ubuntu-archive-keyring.gpg}"
SLEEP_UNIT="${APT_RETRY_SLEEP_UNIT:-10}"
RESTORED_SOURCES="${APT_ETC_DIR}/sources.list.d/ci-restored-ubuntu-archive.sources"
ATTEMPTS=4

apt_get() {
  sudo apt-get -o Acquire::Retries=3 "$@"
}

# True when apt has fetched at least one index whose Release file says
# o=Ubuntu.  That is the observable difference between the broken runner (only
# packages.microsoft.com) and a healthy one, whatever mirror scheme the image
# uses (mirror+file:, a regional EC2 mirror, archive.ubuntu.com).
has_ubuntu_index() {
  apt-cache policy 2>/dev/null | grep -Eq 'o=Ubuntu(,|$)'
}

# Space-separated list of requested packages with no install candidate.
packages_without_candidate() {
  local pkg candidate out=()
  for pkg in "${PACKAGES[@]}"; do
    candidate="$(apt-cache policy "${pkg}" 2>/dev/null | awk '/Candidate:/ {print $2; exit}')"
    if [[ -z "${candidate}" || "${candidate}" == "(none)" ]]; then
      out+=("${pkg}")
    fi
  done
  printf '%s' "${out[*]:-}"
}

restore_ubuntu_sources() {
  local id="" codename="" arch archive security
  if [[ -r "${OS_RELEASE_FILE}" ]]; then
    id="$(. "${OS_RELEASE_FILE}" && printf '%s' "${ID:-}")"
    codename="$(. "${OS_RELEASE_FILE}" && printf '%s' "${VERSION_CODENAME:-${UBUNTU_CODENAME:-}}")"
  fi
  if [[ "${id}" != "ubuntu" || -z "${codename}" ]]; then
    echo "::warning title=Cannot restore Ubuntu sources::${OS_RELEASE_FILE} names no Ubuntu codename (ID='${id}', codename='${codename}')."
    return 1
  fi
  if [[ ! -r "${UBUNTU_KEYRING}" ]]; then
    echo "::warning title=Cannot restore Ubuntu sources::archive keyring ${UBUNTU_KEYRING} is missing."
    return 1
  fi
  arch="$(dpkg --print-architecture 2>/dev/null || echo amd64)"
  case "${arch}" in
    amd64 | i386)
      archive="http://archive.ubuntu.com/ubuntu"
      security="http://security.ubuntu.com/ubuntu"
      ;;
    *)
      archive="http://ports.ubuntu.com/ubuntu-ports"
      security="http://ports.ubuntu.com/ubuntu-ports"
      ;;
  esac
  echo "::warning title=Runner apt sources repaired::apt holds no Ubuntu archive index on this runner (only third-party sources); restoring ${archive} + ${security} for ${codename} (${arch}) in ${RESTORED_SOURCES}."
  sudo tee "${RESTORED_SOURCES}" >/dev/null <<SOURCES
Types: deb
URIs: ${archive}
Suites: ${codename} ${codename}-updates ${codename}-backports
Components: main universe
Signed-By: ${UBUNTU_KEYRING}

Types: deb
URIs: ${security}
Suites: ${codename}-security
Components: main universe
Signed-By: ${UBUNTU_KEYRING}
SOURCES
}

restored=0
missing=""
for attempt in $(seq 1 "${ATTEMPTS}"); do
  if apt_get update -q; then
    missing="$(packages_without_candidate)"
    if [[ -n "${missing}" && "${restored}" == 0 ]] && ! has_ubuntu_index; then
      restored=1
      if restore_ubuntu_sources && apt_get update -q; then
        missing="$(packages_without_candidate)"
      fi
    fi
    if [[ -z "${missing}" ]]; then
      if apt_get install -y -q --no-install-recommends "${PACKAGES[@]}"; then
        echo "Installed: ${PACKAGES[*]}"
        exit 0
      fi
    else
      echo "::warning::apt attempt ${attempt}/${ATTEMPTS}: no install candidate for: ${missing}"
    fi
  fi
  if (( attempt < ATTEMPTS )); then
    echo "::warning::apt attempt ${attempt}/${ATTEMPTS} failed; retrying in $((attempt * SLEEP_UNIT))s"
    sleep $((attempt * SLEEP_UNIT))
  fi
done

if ! has_ubuntu_index; then
  detail="apt holds no Ubuntu archive index"
  if (( restored )); then
    detail="${detail}, and restoring the standard Ubuntu archive did not make the packages installable"
  fi
  echo "::error title=Runner apt sources broken::${detail} (requested: ${PACKAGES[*]}). This is a defect of this runner instance, not of the change under test: re-run the job to get a fresh runner. Nothing was skipped."
else
  echo "::error::apt install of ${PACKAGES[*]} failed after ${ATTEMPTS} attempts${missing:+ (no install candidate for: ${missing})}."
fi
exit 1
