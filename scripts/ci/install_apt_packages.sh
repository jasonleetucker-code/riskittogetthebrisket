#!/usr/bin/env bash
# Install apt packages on a GitHub-hosted runner, with a verified .deb cache
# (CI-1c), bounded network phases, and the repair of a runner whose apt sources
# carry no Ubuntu archive (STAB-10, owner directive 2026-11-19).
#
# Usage:
#   bash scripts/ci/install_apt_packages.sh --resolve <package> [<package> ...]
#   bash scripts/ci/install_apt_packages.sh <package> [<package> ...]
#
# The ONE copy of the CI apt install: PR Validation, Release Candidate and the
# Deploy Production hard gate all call it.  Nothing here skips the install or
# weakens a gate: the script installs every requested package or exits 1 with
# an ::error naming the cause.
#
# Phases.  A workflow runs `--resolve`, restores the cache, runs the install,
# then (on main only) saves the cache:
#
#   1. update   `apt-get update` with per-connection http timeouts, a
#               wall-clock cap, and the STAB-10 repair.  A signature or hash
#               failure is its own ::error; an index that failed to download
#               while the update still exited 0 is a ::warning naming it.
#   2. resolve  `apt-get install --print-uris` lists every .deb the install
#               needs, with its size and the hash the SIGNED index records.
#               `--resolve` publishes a cache key derived from that list
#               (GITHUB_OUTPUT `key`, `restore-prefix`, `debs`) and stops.
#   3. verify   (install mode) a file restored from the cache into the
#               quarantine directory is copied into apt's archive directory
#               ONLY when the resolved list names it and its size and SHA-256
#               or SHA-512 match the index.  The hash is taken of the copy that
#               apt will read, never trusted from the cache and never left to
#               apt to re-check.  Anything else is deleted with a ::warning.
#   4. download `apt-get install --download-only` fetches what is still
#               missing, under `timeout`.  Killing it is safe: dpkg has not
#               run.  Bounded retries.
#   5. stage    the verified, downloaded files are copied to the save
#               directory BEFORE dpkg runs.
#   6. install  `apt-get install --no-download`: no network, so a mirror
#               failure cannot interrupt dpkg.  After it succeeds the staged
#               set replaces the quarantine directory, so the cache save (which
#               must name the restore's path) uploads only verified files.
#
# Integrity rule: a cached file is never trusted until it has been verified
# against the freshly signature-checked index.  This script never installs a
# .deb with dpkg directly, never restores apt's index lists from a cache, and
# never weakens apt's signature checks (the flag ban in
# tests/deploy/test_install_apt_packages.py).  If the index cannot be fetched
# it exits 1 -- "index unreachable; nothing installed, nothing skipped" -- and
# a restored cache is left unused.
#
# The cache key hashes each .deb's file name, size and signed hash, NOT its
# download URL: runners in different regions use different mirrors for
# byte-identical files.
#
# Why the STAB-10 repair exists.  Deploy run 44368941410, hard-gate shard 2
# (image ubuntu-26.04 20261103.629): `apt-get update` fetched only
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
# Why the cache and the caps exist (CI-1c).  Deploy run 44515440979, hard-gate
# shard 3/8: `apt-get install tesseract-ocr` hit 503s and dropped connections
# on the us-east-2 EC2 mirror and archive/security.ubuntu.com for three debs
# (libgif7, libleptonica6, libtesseract5) on all four attempts; a re-run
# passed.  A verified cache removes most downloads, and the timeouts stop a
# slow trickle from holding a shard until its job timeout.
#
# Transient network failures keep the bounded retry the inline copies had (4
# attempts, 10/20/30 s back-off; apt's own Acquire::Retries does not cover a
# failed name resolution), once for the index and once for the download.
#
# Test seams (tests/deploy/test_install_apt_packages.py): APT_ETC_DIR,
# OS_RELEASE_FILE, UBUNTU_KEYRING, APT_RETRY_SLEEP_UNIT, APT_ARCHIVES_DIR,
# APT_UPDATE_TIMEOUT, APT_DOWNLOAD_TIMEOUT, APT_KILL_AFTER, APT_QUARANTINE_DIR
# and APT_SAVE_DIR.  The defaults are the real runner paths; the quarantine and
# save directories default to ${RUNNER_TEMP}/apt-quarantine and
# ${RUNNER_TEMP}/apt-save, the paths the workflows' cache steps name.

set -Eeuo pipefail

usage() {
  echo "usage: $0 [--resolve] <package> [<package> ...]" >&2
}

MODE=install
if [[ "${1:-}" == "--resolve" ]]; then
  MODE=resolve
  shift
fi
if (( $# == 0 )); then
  usage
  exit 2
fi
for arg in "$@"; do
  if [[ "${arg}" == -* ]]; then
    echo "unknown option: ${arg}" >&2
    usage
    exit 2
  fi
done

PACKAGES=("$@")
APT_ETC_DIR="${APT_ETC_DIR:-/etc/apt}"
OS_RELEASE_FILE="${OS_RELEASE_FILE:-/etc/os-release}"
UBUNTU_KEYRING="${UBUNTU_KEYRING:-/usr/share/keyrings/ubuntu-archive-keyring.gpg}"
SLEEP_UNIT="${APT_RETRY_SLEEP_UNIT:-10}"
ARCHIVES_DIR="${APT_ARCHIVES_DIR:-/var/cache/apt/archives}"
UPDATE_TIMEOUT="${APT_UPDATE_TIMEOUT:-180}"
DOWNLOAD_TIMEOUT="${APT_DOWNLOAD_TIMEOUT:-300}"
KILL_AFTER="${APT_KILL_AFTER:-15}"
RESTORED_SOURCES="${APT_ETC_DIR}/sources.list.d/ci-restored-ubuntu-archive.sources"
ATTEMPTS=4

# Outside Actions there is no RUNNER_TEMP: work in a private directory so a
# stale state file from an earlier local run can never be read.
WORK_ROOT="${RUNNER_TEMP:-}"
if [[ -z "${WORK_ROOT}" ]]; then
  WORK_ROOT="$(mktemp -d)"
fi
QUARANTINE="${APT_QUARANTINE_DIR:-${WORK_ROOT}/apt-quarantine}"
SAVE_DIR="${APT_SAVE_DIR:-${WORK_ROOT}/apt-save}"
STATE_DIR="${WORK_ROOT}/apt-ci"
MANIFEST="${STATE_DIR}/manifest.tsv"
RESOLVED_MARKER="${STATE_DIR}/resolved"
if [[ "${QUARANTINE}" == "${SAVE_DIR}" ]]; then
  echo "the quarantine and save directories must differ (${QUARANTINE})" >&2
  exit 2
fi

APT_OPTS=(
  -o Acquire::Retries=3
  -o Acquire::http::Timeout=30
  -o Acquire::https::Timeout=30
  -o Acquire::Languages=none
  -o "Dir::Cache::archives=${ARCHIVES_DIR}/"
)

apt_get() {
  sudo apt-get "${APT_OPTS[@]}" "$@"
}

# `timeout` runs under sudo so it signals apt-get (and its fetch methods)
# directly: a SIGKILL sent to sudo would orphan apt-get still holding apt's lock.
apt_get_capped() {
  local limit="$1"
  shift
  sudo timeout --kill-after="${KILL_AFTER}" "${limit}" apt-get "${APT_OPTS[@]}" "$@"
}

# GitHub annotation; % and newlines are escaped as the runner requires.
annotate() {
  local level="$1" title="$2" message="$3"
  message="${message//'%'/'%25'}"
  message="${message//$'\r'/'%0D'}"
  message="${message//$'\n'/'%0A'}"
  echo "::${level} title=${title}::${message}"
}

emit_output() {
  if [[ -n "${GITHUB_OUTPUT:-}" ]]; then
    printf '%s=%s\n' "$1" "$2" >>"${GITHUB_OUTPUT}"
  fi
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

# ── phase 1: update ─────────────────────────────────────────────────

ATTEMPT=1
UPDATED=0
INTEGRITY_FAILED=0

run_update() {
  local log rc line
  log="$(mktemp)"
  set +e
  apt_get_capped "${UPDATE_TIMEOUT}" update -q 2>&1 | tee "${log}"
  rc="${PIPESTATUS[0]}"
  set -e
  if grep -Eq 'NO_PUBKEY|EXPKEYSIG|BADSIG|is not signed|Hash Sum mismatch' "${log}"; then
    INTEGRITY_FAILED=1
    while IFS= read -r line; do
      annotate error "apt index integrity failure" "attempt ${ATTEMPT}/${ATTEMPTS}: ${line}"
    done < <(grep -E 'NO_PUBKEY|EXPKEYSIG|BADSIG|is not signed|Hash Sum mismatch' "${log}" | head -n 10)
  fi
  if (( rc == 0 )); then
    while IFS= read -r line; do
      annotate warning "apt index partially unavailable" \
        "attempt ${ATTEMPT}/${ATTEMPTS}: failed to fetch ${line}; apt-get update still exited 0, so the install continues with the indexes that did download."
    done < <(sed -nE 's/^[WE]: Failed to fetch ([^ ]+).*/\1/p' "${log}" | head -n 10)
  elif (( rc == 124 || rc == 137 )); then
    echo "::warning::apt-get update did not finish within ${UPDATE_TIMEOUT}s and was stopped (attempt ${ATTEMPT}/${ATTEMPTS})"
  fi
  rm -f "${log}"
  return "${rc}"
}

# ── phase 2: resolve ────────────────────────────────────────────────

# Writes ${MANIFEST}: one line per .deb the install needs, sorted by file name,
# tab-separated: file, size, hash algorithm, hash, URI.  The algorithm is "-"
# when apt offered nothing this script can verify (only SHA256 / SHA512 are
# accepted); such a file is downloaded every time and never cached.
write_manifest() {
  local out rc=0 uri file size hash algo digest unsorted
  out="$(apt_get install --print-uris -qq -y --no-install-recommends "${PACKAGES[@]}")" || rc=$?
  if (( rc != 0 )); then
    echo "::warning::apt attempt ${ATTEMPT}/${ATTEMPTS}: could not resolve the download list (apt-get --print-uris exited ${rc})"
    return 1
  fi
  mkdir -p "${STATE_DIR}"
  unsorted="${MANIFEST}.unsorted"
  : >"${unsorted}"
  while read -r uri file size hash _; do
    [[ "${uri}" == \'* ]] || continue
    uri="${uri#\'}"
    uri="${uri%\'}"
    if [[ ! "${file}" =~ ^[A-Za-z0-9][A-Za-z0-9.+~_%-]*\.deb$ || ! "${size}" =~ ^[0-9]+$ ]]; then
      echo "::warning::apt listed an entry this script cannot use as a file name (${file:-?} ${size:-?}); it is downloaded by apt and never cached."
      continue
    fi
    algo="${hash%%:*}"
    digest="${hash#*:}"
    if [[ "${algo}" == SHA256 && "${digest}" =~ ^[0-9a-f]{64}$ ]] ||
      [[ "${algo}" == SHA512 && "${digest}" =~ ^[0-9a-f]{128}$ ]]; then
      :
    else
      algo="-"
      digest="-"
    fi
    printf '%s\t%s\t%s\t%s\t%s\n' "${file}" "${size}" "${algo}" "${digest}" "${uri}" >>"${unsorted}"
  done <<<"${out}"
  LC_ALL=C sort -u "${unsorted}" >"${MANIFEST}"
  rm -f "${unsorted}"
}

manifest_digest() {
  cut -f1-4 "${MANIFEST}" | sha256sum | cut -d' ' -f1
}

manifest_count() {
  grep -c . "${MANIFEST}" || true
}

fail_resolve() {
  if (( ! UPDATED )); then
    local detail="apt-get update failed on all ${ATTEMPTS} attempts (requested: ${PACKAGES[*]})"
    if (( INTEGRITY_FAILED )); then
      detail="${detail}; the index failed signature or hash verification (see the apt index integrity failure errors above), and an unverified or cached index is never used instead"
    fi
    echo "::error title=apt index unreachable::${detail}. index unreachable; nothing installed, nothing skipped. Re-run the job if the mirror was down."
  elif ! has_ubuntu_index; then
    local detail="apt holds no Ubuntu archive index"
    if (( restored )); then
      detail="${detail}, and restoring the standard Ubuntu archive did not make the packages installable"
    fi
    echo "::error title=Runner apt sources broken::${detail} (requested: ${PACKAGES[*]}). This is a defect of this runner instance, not of the change under test: re-run the job to get a fresh runner. Nothing was skipped."
  else
    echo "::error::apt install of ${PACKAGES[*]} failed after ${ATTEMPTS} attempts${missing:+ (no install candidate for: ${missing})}."
  fi
  exit 1
}

restored=0
missing=""

# Update (with the STAB-10 repair) until every package has a candidate and the
# download list resolves; bounded at ATTEMPTS.  Exits 1 when it never does.
resolve_index() {
  local attempt
  for attempt in $(seq 1 "${ATTEMPTS}"); do
    ATTEMPT="${attempt}"
    if run_update; then
      UPDATED=1
      missing="$(packages_without_candidate)"
      if [[ -n "${missing}" && "${restored}" == 0 ]] && ! has_ubuntu_index; then
        restored=1
        if restore_ubuntu_sources && run_update; then
          missing="$(packages_without_candidate)"
        fi
      fi
      if [[ -z "${missing}" ]]; then
        if write_manifest; then
          return 0
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
  fail_resolve
}

cache_key_prefix() {
  local codename="" arch
  if [[ -r "${OS_RELEASE_FILE}" ]]; then
    codename="$(. "${OS_RELEASE_FILE}" && printf '%s' "${VERSION_CODENAME:-${UBUNTU_CODENAME:-}}")"
  fi
  [[ "${codename}" =~ ^[a-z0-9]+$ ]] || codename="unknown"
  arch="$(dpkg --print-architecture 2>/dev/null || echo unknown)"
  [[ "${arch}" =~ ^[a-z0-9]+$ ]] || arch="unknown"
  printf 'apt-debs-v1-%s-%s-' "${codename}" "${arch}"
}

if [[ "${MODE}" == resolve ]]; then
  resolve_index
  prefix="$(cache_key_prefix)"
  digest="$(manifest_digest)"
  count="$(manifest_count)"
  emit_output key "${prefix}${digest}"
  emit_output restore-prefix "${prefix}"
  emit_output debs "${count}"
  printf 'packages=%s\ndigest=%s\n' "${PACKAGES[*]}" "${digest}" >"${RESOLVED_MARKER}"
  echo "Resolved ${count} .deb file(s) for ${PACKAGES[*]}; cache key ${prefix}${digest}"
  exit 0
fi

# Install mode.  When `--resolve` already updated the index in this job for
# the same packages, reuse that index (no second update, no second exposure to
# the mirror); the download list is recomputed from apt's own root-owned index
# rather than read back from a file the cache restore could have touched.
reuse_index=0
if [[ -r "${RESOLVED_MARKER}" ]] && grep -qxF "packages=${PACKAGES[*]}" "${RESOLVED_MARKER}"; then
  missing="$(packages_without_candidate)"
  if [[ -z "${missing}" ]] && write_manifest; then
    reuse_index=1
    UPDATED=1
    resolved_digest="$(sed -n 's/^digest=//p' "${RESOLVED_MARKER}")"
    if [[ "$(manifest_digest)" != "${resolved_digest}" ]]; then
      annotate warning "apt download list changed" \
        "the download list differs from the one --resolve keyed the cache on; every cached file is still verified against the current index."
    fi
  fi
fi
if (( ! reuse_index )); then
  resolve_index
fi

# ── phase 3: verify the restored cache ──────────────────────────────

file_matches() {
  local path="$1" size="$2" algo="$3" hash="$4" actual
  [[ -f "${path}" && ! -L "${path}" ]] || return 1
  actual="$(stat -c %s -- "${path}" 2>/dev/null)" || return 1
  [[ "${actual}" == "${size}" ]] || return 1
  case "${algo}" in
    SHA256) actual="$(sha256sum -- "${path}" | cut -d' ' -f1)" ;;
    SHA512) actual="$(sha512sum -- "${path}" | cut -d' ' -f1)" ;;
    *) return 1 ;;
  esac
  [[ "${actual}" == "${hash}" ]]
}

reused=0
discarded=0
if [[ -d "${QUARANTINE}" ]]; then
  sudo mkdir -p "${ARCHIVES_DIR}"
  while IFS=$'\t' read -r file size algo hash _; do
    src="${QUARANTINE}/${file}"
    [[ -e "${src}" || -L "${src}" ]] || continue
    dest="${ARCHIVES_DIR}/${file}"
    if [[ "${algo}" != "-" && ! -e "${dest}" && -f "${src}" && ! -L "${src}" ]]; then
      stage="${dest}.ci-verify"
      sudo cp -- "${src}" "${stage}"
      if file_matches "${stage}" "${size}" "${algo}" "${hash}"; then
        sudo mv -f -- "${stage}" "${dest}"
        reused=$((reused + 1))
        continue
      fi
      sudo rm -f -- "${stage}"
    fi
    if [[ -e "${dest}" ]]; then
      continue
    fi
    annotate warning "apt cache entry discarded" \
      "${file}: the restored copy does not match the size and hash the signed index records (or cannot be verified); deleted, it will be downloaded."
    rm -f -- "${src}"
    discarded=$((discarded + 1))
  done <"${MANIFEST}"
  echo "apt cache: reused ${reused} verified .deb file(s) of $(manifest_count) needed, discarded ${discarded}; downloading the rest."
else
  echo "apt cache: nothing restored; downloading all $(manifest_count) needed .deb file(s)."
fi

# ── phase 4: download ───────────────────────────────────────────────

downloaded=0
for attempt in $(seq 1 "${ATTEMPTS}"); do
  rc=0
  apt_get_capped "${DOWNLOAD_TIMEOUT}" install --download-only -y -q --no-install-recommends "${PACKAGES[@]}" || rc=$?
  if (( rc == 0 )); then
    downloaded=1
    break
  fi
  if (( rc == 124 || rc == 137 )); then
    reason="did not finish within ${DOWNLOAD_TIMEOUT}s and was stopped (dpkg had not run)"
  else
    reason="failed (exit ${rc})"
  fi
  if (( attempt < ATTEMPTS )); then
    echo "::warning::apt download attempt ${attempt}/${ATTEMPTS} ${reason}; retrying in $((attempt * SLEEP_UNIT))s"
    sleep $((attempt * SLEEP_UNIT))
  else
    echo "::warning::apt download attempt ${attempt}/${ATTEMPTS} ${reason}"
  fi
done
if (( ! downloaded )); then
  echo "::error title=apt download failed::could not download ${PACKAGES[*]} after ${ATTEMPTS} attempts (each capped at ${DOWNLOAD_TIMEOUT}s); nothing installed, nothing skipped. Re-run the job if the mirror was down."
  exit 1
fi

# ── phase 5: stage the verified set for the cache save ──────────────

rm -rf -- "${SAVE_DIR:?}"
mkdir -p "${SAVE_DIR}"
saved=0
while IFS=$'\t' read -r file size algo hash _; do
  [[ "${algo}" != "-" ]] || continue
  if file_matches "${ARCHIVES_DIR}/${file}" "${size}" "${algo}" "${hash}"; then
    cp -f -- "${ARCHIVES_DIR}/${file}" "${SAVE_DIR}/${file}"
    saved=$((saved + 1))
  else
    annotate warning "apt package not cached" \
      "${file}: not in apt's archive directory with the size and hash the signed index records after the download; not saved to the cache."
  fi
done <"${MANIFEST}"

# ── phase 6: install (no network) ───────────────────────────────────

if ! apt_get -o DPkg::Lock::Timeout=60 install -y -q --no-download --no-install-recommends "${PACKAGES[@]}"; then
  echo "::error::apt install of ${PACKAGES[*]} failed after a complete download (apt/dpkg error above); nothing skipped."
  exit 1
fi

# The cache save must name the same path as the restore (actions/cache keys an
# entry's version by its path list), so the verified set replaces whatever the
# restore put in the quarantine directory.  Unlisted or rejected files are gone.
rm -rf -- "${QUARANTINE:?}"
mkdir -p "$(dirname -- "${QUARANTINE}")"
mv -- "${SAVE_DIR}" "${QUARANTINE}"
emit_output saved "${saved}"
emit_output reused "${reused}"
echo "Installed: ${PACKAGES[*]} (${reused} .deb file(s) from the verified cache, ${saved} verified file(s) staged for the cache save)"
exit 0
