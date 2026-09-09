#!/usr/bin/env bash
# Canonical agent/developer Python formatting gate.
#
# Usage:
#   bash scripts/format_python_changes.sh [path/to/file.py ...]
#
# With explicit paths, format those Python files. With no paths, discover
# changed/untracked Python files relative to origin/main plus the working tree.
# Always finish with the same repo-wide format/lint checks used by CI.

set -Eeuo pipefail
cd "$(git rev-parse --show-toplevel 2>/dev/null || pwd)"

EXPECTED_RUFF_VERSION="0.6.9"
ACTUAL_RUFF_VERSION="$(python -m ruff --version | awk '{print $2}')"

if [[ "$ACTUAL_RUFF_VERSION" != "$EXPECTED_RUFF_VERSION" ]]; then
  echo "ERROR: Ruff version mismatch: expected $EXPECTED_RUFF_VERSION, got $ACTUAL_RUFF_VERSION" >&2
  echo "Install the repo toolchain with: python -m pip install -r requirements-dev.txt" >&2
  exit 2
fi

declare -a FILES=()
declare -A SEEN=()

add_file() {
  local file="$1"
  [[ "$file" == *.py ]] || return 0
  [[ -f "$file" ]] || return 0
  if [[ -z "${SEEN[$file]+x}" ]]; then
    FILES+=("$file")
    SEEN["$file"]=1
  fi
}

if (( $# > 0 )); then
  for file in "$@"; do
    add_file "$file"
  done
else
  BASE_REF="${RUFF_BASE_REF:-origin/main}"
  if git rev-parse --verify "$BASE_REF" >/dev/null 2>&1; then
    MERGE_BASE="$(git merge-base "$BASE_REF" HEAD)"
    while IFS= read -r file; do add_file "$file"; done < <(
      git diff --name-only --diff-filter=ACMRT "$MERGE_BASE"...HEAD -- '*.py'
    )
  fi
  while IFS= read -r file; do add_file "$file"; done < <(
    git diff --name-only --diff-filter=ACMRT -- '*.py'
  )
  while IFS= read -r file; do add_file "$file"; done < <(
    git diff --cached --name-only --diff-filter=ACMRT -- '*.py'
  )
  while IFS= read -r file; do add_file "$file"; done < <(
    git ls-files --others --exclude-standard -- '*.py'
  )
fi

if (( ${#FILES[@]} > 0 )); then
  echo "Formatting ${#FILES[@]} changed Python file(s) with Ruff $EXPECTED_RUFF_VERSION:"
  printf '  %s\n' "${FILES[@]}"
  python -m ruff format "${FILES[@]}"
else
  echo "No changed Python files detected; running verification only."
fi

python -m ruff format --check .
python -m ruff check .
git diff --check

echo "Python formatting contract: GREEN (Ruff $EXPECTED_RUFF_VERSION)"
