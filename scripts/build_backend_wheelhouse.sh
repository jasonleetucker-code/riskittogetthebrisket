#!/usr/bin/env bash
# Build one hash-bound wheelhouse and prove that it installs without an index.
set -Eeuo pipefail

if [[ "$#" -ne 2 ]]; then
  echo "usage: build_backend_wheelhouse.sh requirements.lock.txt output.tar" >&2
  exit 2
fi

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
lock_name="$1"
archive_name="$2"
case "${lock_name}" in
  requirements.lock.txt|requirements-dev.lock.txt) ;;
  *) echo "unsupported lock: ${lock_name}" >&2; exit 2 ;;
esac
[[ "${archive_name}" =~ ^[A-Za-z0-9._-]+\.tar$ ]] || {
  echo "archive name must be a local .tar filename" >&2
  exit 2
}
work_dir="${repo_root}/${archive_name}.work"
[[ ! -e "${work_dir}" ]] || { echo "staging directory already exists" >&2; exit 2; }
mkdir -p "${work_dir}/backend-inputs" "${work_dir}/backend-wheels" \
  "${work_dir}/backend-sources"
cp "${repo_root}/${lock_name}" "${work_dir}/${lock_name}"
cp "${repo_root}/requirements-build.lock.txt" "${work_dir}/requirements-build.lock.txt"

python -m venv "${work_dir}/build-venv"
"${work_dir}/build-venv/bin/python" -m pip install \
  --require-hashes --only-binary=:all: \
  -r "${work_dir}/requirements-build.lock.txt"
"${work_dir}/build-venv/bin/python" -m pip download \
  --no-build-isolation --require-hashes \
  -r "${work_dir}/${lock_name}" --dest "${work_dir}/backend-inputs"
for package in "${work_dir}"/backend-inputs/*; do
  case "${package}" in
    *.whl) cp "${package}" "${work_dir}/backend-wheels/" ;;
    *.tar.gz|*.zip)
      cp "${package}" "${work_dir}/backend-sources/"
      "${work_dir}/build-venv/bin/python" -m pip wheel \
        --no-build-isolation --no-deps \
        --wheel-dir "${work_dir}/backend-wheels" "${package}"
      ;;
    *) echo "unsupported locked package: ${package}" >&2; exit 1 ;;
  esac
done
python "${repo_root}/scripts/backend_wheelhouse.py" create \
  --wheel-dir "${work_dir}/backend-wheels" \
  --source-dir "${work_dir}/backend-sources" \
  --lock "${work_dir}/${lock_name}" \
  --build-lock "${work_dir}/requirements-build.lock.txt" \
  --manifest "${work_dir}/backend-wheelhouse-manifest.json"
python "${repo_root}/scripts/backend_wheelhouse.py" requirements \
  --wheel-dir "${work_dir}/backend-wheels" \
  --source-dir "${work_dir}/backend-sources" \
  --lock "${work_dir}/${lock_name}" \
  --build-lock "${work_dir}/requirements-build.lock.txt" \
  --manifest "${work_dir}/backend-wheelhouse-manifest.json" \
  --output "${work_dir}/backend-install.requirements.txt"
python -m venv "${work_dir}/offline-venv"
"${work_dir}/offline-venv/bin/python" -m pip install \
  --no-index --no-deps --require-hashes \
  -r "${work_dir}/backend-install.requirements.txt"
"${work_dir}/offline-venv/bin/python" -m pip check
python "${repo_root}/scripts/backend_wheelhouse.py" verify \
  --wheel-dir "${work_dir}/backend-wheels" \
  --source-dir "${work_dir}/backend-sources" \
  --lock "${work_dir}/${lock_name}" \
  --build-lock "${work_dir}/requirements-build.lock.txt" \
  --manifest "${work_dir}/backend-wheelhouse-manifest.json"
tar --sort=name --mtime='@0' --owner=0 --group=0 --numeric-owner \
  -C "${work_dir}" -cf "${repo_root}/${archive_name}" \
  backend-wheelhouse-manifest.json "${lock_name}" \
  requirements-build.lock.txt backend-wheels backend-sources
(
  cd "${repo_root}"
  sha256sum "${archive_name}" > "${archive_name}.sha256"
  sha256sum -c "${archive_name}.sha256"
  du -h "${archive_name}"
)
