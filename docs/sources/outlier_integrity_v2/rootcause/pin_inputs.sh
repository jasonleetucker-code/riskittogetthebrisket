#!/bin/bash
# usage: pin_inputs.sh TREE COMMIT
# Make TREE's CSVs/ and data/ exactly the tracked state at COMMIT (code stays at TREE's HEAD).
set -euo pipefail
tree=$1; c=$2
cd "$tree"
git checkout -q HEAD -- CSVs data   # reset to HEAD first (idempotent)
git diff --name-only --diff-filter=AR "$c" HEAD -- CSVs data | while read -r f; do rm -f -- "$f"; done
git checkout -q "$c" -- CSVs data
echo "pinned $tree inputs to $c; CSVs+data tree diff vs $c:" $(git diff --stat "$c" -- CSVs data | tail -1)
git ls-files -s CSVs data | sha256sum | cut -c1-16
